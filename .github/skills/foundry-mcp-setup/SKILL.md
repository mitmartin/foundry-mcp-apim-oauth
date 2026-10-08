---
name: foundry-mcp-setup
description: Guides a user through deploying this repository's Microsoft Foundry prompt agents that call third-party MCP servers (GitHub and ZoomInfo) through Azure API Management with per-user OAuth. Use when asked to set up, deploy, test, or troubleshoot the GitHub or ZoomInfo MCP agents, create the GitHub App, register the ZoomInfo app, add Foundry callback URLs, or reset sign-ins.
---

# Foundry MCP setup

Walk the user through `README.md` for the MCP servers they choose. Run every command you can. When a step needs the user in a browser, give them the exact URL and the exact buttons to select, then **wait for them to confirm** before continuing.

## Ground rules

- **Secrets.** Never print, log, paste into chat, or commit a client secret or token. Read secrets from the credentials files only inside the command that needs them. Ask users to paste credentials into local files, never into chat.
- **Browser links.** Give URLs as text and ask before opening a browser. People often have several browser profiles, and the wrong profile can be signed in to the wrong account. Open links automatically only if the user asks.
- **Right account.** Before the user creates anything in GitHub or ZoomInfo, have them confirm the page shows the intended organization or account.
- **Right Azure context.** Before any Azure write, run `az account show` and have the user confirm the subscription and tenant. Pass `--subscription` explicitly when they have more than one.
- **Don't sign in for the user.** Don't open sign-in links or complete consent yourself. The smoke test only prints a link for the user.
- **One step at a time.** Check each command's exit code and output. On failure, show the error, explain it in plain words, and use the troubleshooting tables below. Don't skip ahead.
- **Long waits.** Warn the user that API Management takes about 30 to 45 minutes to deploy the first time.
- **Secrets on every deployment.** Once a service's app exists, pass its client secret on every later deployment. An empty secret resets that connection to placeholders.

## Step 0: Choose services and collect inputs

First ask which MCP servers to set up: **GitHub**, **ZoomInfo**, or **both**. Follow only the sections for the chosen services.

Then collect these values together, suggesting defaults:

| Input | Needed for | Notes |
|---|---|---|
| Azure subscription | All | Confirm with `az account show` |
| Region | All | Must have quota for the model. The default model is `gpt-5.4-mini`. |
| Resource group | All | New or existing |
| Publisher email | All | For API Management notifications |
| GitHub organization | GitHub | The user must be an owner, or have one available |
| GitHub App name | GitHub | Must be unique across GitHub, for example `<org>-foundry-mcp` |
| ZoomInfo account type | ZoomInfo | gtm.ai sign-up (API/MCP tab) or existing customer (Developer Portal) |
| Open links automatically? | All | Default: no, print them |

Check prerequisites:

```bash
az version
az bicep version
python --version   # 3.10 or later
python -m pip install -r scripts/requirements.txt
```

If `az account show` fails, ask the user to run `az login` (with `--tenant <tenant-id>` if they use several tenants).

## Step 1: Prepare parameters (and the GitHub App)

1. Get the user's object ID: `az ad signed-in-user show --query id -o tsv`.
2. Copy `infra/main.parameters.example.json` to `infra/main.parameters.json`. Set `enableGitHub` and `enableZoomInfo` to match Step 0. Fill in `apimPublisherEmail` and `developerPrincipalIds` (the user's object ID). Add teammates to `agentConsumerPrincipalIds` if they should only chat with agents. Leave `zoominfoClientId` empty for now. Confirm `infra/main.parameters.json` is ignored by Git.
3. **GitHub only:** create and install the GitHub App before deploying:

   ```bash
   python scripts/create_github_app.py --org <org> --app-name <app-name>
   ```

   Add `--open-browser` only if the user asked for it. The script keeps running while the user works in the browser. Tell the user:

   1. "Open the `http://127.0.0.1:...` link it printed, in the browser where you're signed in to GitHub as an owner of **&lt;org&gt;**."
   2. "GitHub shows a prefilled form for a new GitHub App. Check that the page says the app belongs to **&lt;org&gt;**. Leave the read-only permissions as they are."
   3. "Select **Create GitHub App for &lt;org&gt;**."
   4. "Open the second link the script prints. Choose **&lt;org&gt;**, select **Only select repositories** (or **All repositories**), pick the repositories the agent may read, and select **Install**."

   When it finishes, confirm the credentials file exists (`~/.foundry-mcp/<app-name>.json`) **without printing its contents**, and put the client ID in `githubAppClientId`. To create the app by hand instead, follow `docs/github-setup.md`, Step 1, Option B.

## Step 2: Deploy the infrastructure

Create the resource group if needed: `az group create -n <rg> -l <region>`.

Deploy, reading each secret inside the same command. Include `githubAppClientSecret` only if GitHub is enabled, and `zoominfoClientSecret` only once the ZoomInfo app exists.

PowerShell:

```powershell
$gh = Get-Content "$HOME/.foundry-mcp/<github-app-name>.json" | ConvertFrom-Json
az deployment group create -g <rg> -n main -f infra/main.bicep -p '@infra/main.parameters.json' `
  -p "githubAppClientSecret=$($gh.client_secret)" `
  --query "{state:properties.provisioningState, github:properties.outputs.githubRegistered.value, zoominfo:properties.outputs.zoominfoRegistered.value}" -o json
```

Bash:

```bash
az deployment group create -g <rg> -n main -f infra/main.bicep -p @infra/main.parameters.json \
  -p githubAppClientSecret="$(python -c "import json,os;print(json.load(open(os.path.expanduser('~/.foundry-mcp/<github-app-name>.json')))['client_secret'])")" \
  --query "{state:properties.provisioningState, github:properties.outputs.githubRegistered.value, zoominfo:properties.outputs.zoominfoRegistered.value}" -o json
```

Expect `Succeeded`. Run it as a background command if your environment supports that, and check on it periodically.

Then get the callback URLs:

```bash
az deployment group show -g <rg> -n main --query "properties.outputs.{github:githubOAuthRedirectUrl.value, zoominfo:zoominfoOAuthRedirectUrl.value}" -o json
```

## Step 3a: GitHub callback URL

Tell the user:

1. "Open `https://github.com/organizations/<org>/settings/apps/<app-slug>`."
2. "Under **Identifying and authorizing users**, paste this into **Callback URL**: `<github-redirect-url>`. If a callback URL is already there for another environment, select **Add Callback URL** instead of replacing it."
3. "Scroll down and select **Save changes**."
4. "Then select **Optional features** and confirm **User-to-server token expiration** is opted in."

Wait for the user to confirm.

## Step 3b: ZoomInfo app

ZoomInfo only allows automatic client registration for its approved vendors, so the user registers the app by hand. Never try to register a client by posing as an approved vendor.

1. Create a credentials template the user can fill in, without overwriting an existing file:

   ```powershell
   $f = Join-Path $HOME '.foundry-mcp/zoominfo-app.json'
   New-Item -ItemType Directory -Force (Split-Path $f) | Out-Null
   if (-not (Test-Path $f)) { Set-Content $f '{ "client_id": "PASTE_CLIENT_ID", "client_secret": "PASTE_CLIENT_SECRET" }' }
   ```

2. Tell the user:
   1. "Open the ZoomInfo app area: for a gtm.ai sign-up, `https://gtm-studio.zoominfo.com`, then **API/MCP** in the left navigation. For an existing customer, `https://developer.zoominfo.com`."
   2. "Select **Create App** and name it, for example `Foundry agents`. Users see this name when they sign in. In the Developer Portal, choose **MCP App**."
   3. "Add this redirect URI exactly, with no trailing slash: `<zoominfo-redirect-url>`."
   4. "Select **Create**, then copy the **Client ID** and **Client Secret** into `~/.foundry-mcp/zoominfo-app.json`, replacing the placeholders. Don't paste them in chat."
3. When the user confirms, check that the file no longer contains `PASTE_`, **without printing it**. Set `zoominfoClientId` in `infra/main.parameters.json`.
4. Redeploy with **both** secrets. Omit `githubAppClientSecret` if GitHub is off:

   ```powershell
   $zi = Get-Content "$HOME/.foundry-mcp/zoominfo-app.json" | ConvertFrom-Json
   az deployment group create -g <rg> -n main -f infra/main.bicep -p '@infra/main.parameters.json' `
     -p "githubAppClientSecret=$($gh.client_secret)" -p "zoominfoClientSecret=$($zi.client_secret)" `
     --query "properties.outputs.zoominfoRegistered.value" -o tsv
   ```

   Expect `true`. The callback URL doesn't change.

5. Optional check that signs no one in: request ZoomInfo's authorization endpoint with the app's client ID, the callback URL, and a PKCE challenge, without following redirects. A redirect to the ZoomInfo login page means the redirect URI is accepted. Requesting `https://okta-login.zoominfo.com/oauth2/default/v1/authorize` with the same values returns **400 "redirect_uri parameter must be a Login redirect URI"** if the URI isn't registered on the app.

## Step 4: Deploy the agents

Run only for the chosen services:

```bash
python scripts/deploy_agent.py --resource-group <rg> --service github --github-org <org>
python scripts/deploy_agent.py --resource-group <rg> --service zoominfo
```

Expect `Deployed agent '<name>' version <n>.` A warning about placeholder credentials means Step 2 or Step 3b wasn't completed with that service's secret. A 401 or 403 usually means the user's Foundry role assignment is still propagating. Wait a few minutes and try again.

## Step 5: Test

```bash
python scripts/smoke_test.py --resource-group <rg> --service github --github-org <org>
python scripts/smoke_test.py --resource-group <rg> --service zoominfo
```

- **Exit code 2:** this is expected on the first run. Give the user the printed sign-in link and tell them: "Open this link, sign in to <service> if asked, and approve access. Then tell me when you're done." Run the test again afterward.
- **Exit code 0 and `PASS`:** done. The ZoomInfo test uses the free Lookup tool, so it doesn't use credits.
- **Anything else:** see the troubleshooting tables.

Also offer a portal test: in `https://ai.azure.com`, open the project, select **Agents**, open an agent, and ask "Who am I on GitHub?" or "What ZoomInfo tools do you have access to?" If the user prefers to sign in through the portal, let them, and don't run the smoke test until they confirm.

## Wrap up

Summarize for the user:

- Resource group, project endpoint, agent names, and APIM MCP URLs (from the deployment outputs)
- GitHub App slug and ZoomInfo app name, and where the credentials files are
- How other users get access: assign them **Foundry Agent Consumer** on the project, and they sign in to each service on first use
- That every later deployment must pass each service's client secret
- Where to read about maintenance: `docs/github-setup.md#maintenance` and `docs/zoominfo-setup.md#maintenance`

## Troubleshooting

### Both services

| Symptom | Fix |
|---|---|
| Model deployment fails with a quota or availability error | Choose another region, or override `modelName`, `modelVersion`, `modelSkuName`, or `modelCapacity`. |
| `deploy_agent.py` says the service isn't deployed | Redeploy with `enableGitHub=true` or `enableZoomInfo=true`. |
| Sign-in stopped working after a redeploy | The secret wasn't passed, so the connection was reset to placeholders. Redeploy with the secret. |
| `Connection ... already exist, and can only be updated by the workspace that created it` | Connection names are unique across the Foundry account. Set different `githubConnectionName` and `zoominfoConnectionName` values for each project. |
| `401 ... token authentication failed` after sign-in worked before | The user's authorization was revoked in the service. Recreating the connection signs out every user. Confirm with the user before doing it. |
| No sign-in card for a new user | Assign **Foundry Agent Consumer** or **Foundry User** on the project. The user must be in the project's Entra tenant. |
| Python can't resolve the Foundry endpoint, but other tools can | A stale local DNS cache. Retry after a minute, or flush the DNS cache. |

### GitHub

| Symptom | Fix |
|---|---|
| GitHub: `redirect_uri` isn't associated with this application | The callback URL is missing or outdated. Repeat Step 3a. |
| Private repository not found, public ones work | The GitHub App isn't installed on that repository. Have the user update the installation's repository selection. |
| The agent searches unrelated repositories or asks for the organization | Redeploy the agent with the right `--github-org`. GitHub's MCP server can't list a user's organizations. |

### ZoomInfo

| Symptom | Fix |
|---|---|
| ZoomInfo **400: The 'redirect_uri' parameter must be a Login redirect URI**, often after **Sign in with Microsoft** | The callback URL isn't a redirect URI on the ZoomInfo app, or doesn't match exactly. Repeat Step 3b, item 2.3. |
| `Vendor ... was not found in approved vendors` | Automatic client registration was attempted. Register the app by hand (Step 3b). |
| Tools return `403`, or enrichment fails with a credit error | Check the user's ZoomInfo package and credits. MCP can't use recurring monthly credits. |
| `429 Too Many Requests` | ZoomInfo allows 25 requests per second. Retry later. |

## Clean up (only when the user asks)

1. `az group delete -n <rg>` after the user confirms the resource group name.
2. Tell the user to delete the GitHub App at `https://github.com/organizations/<org>/settings/apps/<app-slug>/advanced` → **Delete GitHub App**, delete the ZoomInfo app in the API/MCP tab or Developer Portal, and delete the local credentials files.
