---
name: foundry-github-mcp-setup
description: Guides a user through deploying this repository's Microsoft Foundry prompt agent that calls GitHub's hosted MCP server through Azure API Management with per-user OAuth. Use when asked to set up, deploy, test, or troubleshoot the GitHub MCP agent, create or install the GitHub App, add the Foundry callback URL to GitHub, or reset GitHub sign-ins.
---

# Foundry GitHub MCP setup

Walk the user through the five steps in `README.md`: create the GitHub App, deploy the infrastructure, add the callback URL, deploy the agent, and test. Run every command you can. When a step needs the user in a browser, give them the exact URL and the exact buttons to select, then **wait for them to confirm** before continuing.

## Ground rules

- **Secrets.** Never print, log, paste into chat, or commit the GitHub App client secret or any token. Read the secret from the credentials file only inside the command that needs it.
- **Browser links.** Give URLs as text and ask before opening a browser. People often have several browser profiles, and the wrong profile can be signed in to the wrong GitHub account. Open links automatically only if the user asks.
- **Right GitHub account.** Before the user creates or installs anything in GitHub, have them confirm the page shows the intended **organization**, not a personal account or another organization.
- **Right Azure context.** Before any Azure write, run `az account show` and have the user confirm the subscription and tenant. Pass `--subscription` explicitly when they have more than one.
- **One step at a time.** Check each command's exit code and output. On failure, show the error, explain it in plain words, and use the troubleshooting table below. Don't skip ahead.
- **Long waits.** Warn the user that API Management takes about 30 to 45 minutes to deploy.

## Step 0: Collect inputs

Ask for these values together, and suggest defaults:

| Input | Notes |
|---|---|
| Azure subscription | Confirm with `az account show` |
| Region | Must have quota for the model. The default model is `gpt-5.4-mini`. |
| Resource group | New or existing |
| GitHub organization | The user must be an owner, or have an owner available |
| GitHub App name | Must be unique across GitHub, for example `<org>-foundry-mcp` |
| Publisher email | For API Management notifications |
| Open links automatically? | Default: no, print them |

Check prerequisites:

```bash
az version
az bicep version
python --version   # 3.10 or later
python -m pip install -r scripts/requirements.txt
```

If `az account show` fails, ask the user to run `az login` (with `--tenant <tenant-id>` if they use several tenants).

## Step 1: Create and install the GitHub App

Run:

```bash
python scripts/create_github_app.py --org <org> --app-name <app-name>
```

Add `--open-browser` only if the user asked for it. The script keeps running while the user works in the browser. Tell the user:

1. "Open the `http://127.0.0.1:...` link it printed, in the browser where you're signed in to GitHub as an owner of **&lt;org&gt;**."
2. "GitHub shows a prefilled form for a new GitHub App. Check that the page says the app belongs to **&lt;org&gt;**. Leave the read-only permissions as they are."
3. "Select **Create GitHub App for &lt;org&gt;**."
4. "Open the second link the script prints. Choose **&lt;org&gt;**, select **Only select repositories** (or **All repositories**), pick the repositories the agent may read, and select **Install**."

When the script finishes, confirm the credentials file exists (`~/.foundry-mcp/<app-name>.json` by default) **without printing its contents**. Note the app slug and client ID, which aren't secret.

If the user prefers to create the app by hand, follow `docs/github-setup.md`, Step 1, Option B, and have them save `{"client_id": "...", "client_secret": "..."}` to a file outside the repository.

## Step 2: Deploy the infrastructure

1. Get the user's object ID: `az ad signed-in-user show --query id -o tsv`.
2. Copy `infra/main.parameters.example.json` to `infra/main.parameters.json`. Fill in `apimPublisherEmail`, `githubAppClientId`, and `developerPrincipalIds` (the user's object ID). Add teammates' object IDs to `agentConsumerPrincipalIds` if they should only chat with the agent. Confirm `infra/main.parameters.json` is ignored by Git.
3. Create the resource group if needed: `az group create -n <rg> -l <region>`.
4. Deploy. Read the secret inside the same command, and never echo it.

   PowerShell:

   ```powershell
   $secret = (Get-Content "$HOME/.foundry-mcp/<app-name>.json" | ConvertFrom-Json).client_secret
   az deployment group create -g <rg> -n main -f infra/main.bicep -p '@infra/main.parameters.json' -p "githubAppClientSecret=$secret" --query properties.provisioningState -o tsv
   ```

   Bash:

   ```bash
   az deployment group create -g <rg> -n main -f infra/main.bicep -p @infra/main.parameters.json \
     -p githubAppClientSecret="$(python -c "import json,os;print(json.load(open(os.path.expanduser('~/.foundry-mcp/<app-name>.json')))['client_secret'])")" \
     --query properties.provisioningState -o tsv
   ```

5. Expect `Succeeded`. Run it as a background command if your environment supports that, and check on it periodically.

## Step 3: Add the callback URL in GitHub

Get the URL:

```bash
az deployment group show -g <rg> -n main --query properties.outputs.githubOAuthRedirectUrl.value -o tsv
```

Tell the user:

1. "Open `https://github.com/organizations/<org>/settings/apps/<app-slug>`."
2. "Under **Identifying and authorizing users**, paste this into **Callback URL**: `<redirect-url>`. If a callback URL is already there for another environment, select **Add Callback URL** instead of replacing it."
3. "Scroll down and select **Save changes**."
4. "Then select **Optional features** and confirm **User-to-server token expiration** is opted in."

Wait for the user to confirm before continuing.

## Step 4: Deploy the agent

```bash
python scripts/deploy_agent.py --resource-group <rg> --github-org <org>
```

Expect `Deployed agent 'github-mcp-agent' version <n>.` If it fails with 401 or 403, the user's Foundry role assignment may still be propagating. Wait a few minutes and try again.

## Step 5: Test

```bash
python scripts/smoke_test.py --resource-group <rg> --github-org <org>
```

- **Exit code 2:** this is expected on the first run. Give the user the printed sign-in link and tell them: "Open this link, sign in to GitHub if asked, and select **Authorize**. Then tell me when you're done." Run the test again afterward.
- **Exit code 0 and `PASS`:** done.
- **Anything else:** see the troubleshooting table.

Also offer a portal test: in `https://ai.azure.com`, open the project, select **Agents → github-mcp-agent**, and ask "Who am I on GitHub?"

## Wrap up

Summarize for the user:

- Resource group, project endpoint, agent name, and APIM MCP URL (from the deployment outputs)
- GitHub App slug and where the credentials file is
- How other users get access: assign them **Foundry Agent Consumer** on the project, and they sign in to GitHub on first use
- Where to read about maintenance: `docs/github-setup.md#maintenance`

## Troubleshooting

| Symptom | Fix |
|---|---|
| GitHub: `redirect_uri` isn't associated with this application | The callback URL is missing or outdated. Repeat Step 3. |
| Model deployment fails with a quota or availability error | Choose another region, or override `modelName`, `modelVersion`, `modelSkuName`, or `modelCapacity`. |
| `401 ... token authentication failed` after sign-in worked before | The user's GitHub authorization was revoked. Recreating the connection signs out every user; see `docs/github-setup.md#revoke-access`. Confirm with the user before doing it. |
| Private repository not found, public ones work | The GitHub App isn't installed on that repository. Have the user update the installation's repository selection. |
| The agent searches unrelated repositories or asks for the organization | Redeploy the agent with the right `--github-org`. GitHub's MCP server can't list a user's organizations. |
| No sign-in card for a new user | Assign **Foundry Agent Consumer** or **Foundry User** on the project. The user must be in the project's Entra tenant. |
| Python can't resolve the Foundry endpoint, but other tools can | A stale local DNS cache. Retry after a minute, or flush the DNS cache. |

## Clean up (only when the user asks)

1. `az group delete -n <rg>` after the user confirms the resource group name.
2. Tell the user to delete the GitHub App at `https://github.com/organizations/<org>/settings/apps/<app-slug>/advanced` → **Delete GitHub App**, and to delete the local credentials file.
