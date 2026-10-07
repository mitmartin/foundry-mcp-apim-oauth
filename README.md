# Foundry agents with GitHub MCP through Azure API Management (per-user OAuth)

A deployable reference for giving Microsoft Foundry prompt agents access to GitHub's hosted MCP server, where **every tool call runs as the signed-in user**. Azure API Management (APIM) sits in the middle to enforce policy centrally. No user tokens or secrets are stored in this repository or in APIM.

```text
User in Foundry (signed in with Microsoft Entra ID)
   │
   ▼
Foundry prompt agent ── MCP tool, attached directly to the agent
   │                    uses the Foundry OAuth connection, which holds each user's GitHub token
   ▼
Azure API Management   /github-mcp/mcp
   │                    requires a token, pins toolsets, forces read-only, throttles, streams
   ▼
GitHub hosted MCP server (api.githubcopilot.com/mcp/)
   │                    runs as that GitHub user
   ▼
Repositories where your GitHub App is installed (plus public repositories)
```

## How it works

- **Per-user access.** The first time a user calls a GitHub tool, the agent shows a sign-in card. The user authorizes your organization's GitHub App, and Foundry stores that user's GitHub token for the connection. Later calls reuse it and refresh it automatically.
- **Least privilege.** A user's effective access is what **they** can access in GitHub, limited to the app's read-only permissions and the repositories where the app is installed.
- **Central governance.** The APIM policy rejects calls without a token, pins the GitHub toolsets, forces read-only mode, and throttles traffic, for every agent that uses the endpoint.
- **Configure once.** The OAuth connection is a project resource. Any agent in the project can attach the same MCP tool and reuse each user's sign-in.

## What gets deployed

| Resource | Purpose |
|---|---|
| Foundry account, project, and model deployment | Hosts the prompt agent. API keys are disabled; Microsoft Entra ID is required. |
| API Management service and `github-mcp` API | Streaming MCP passthrough with the policy in [`infra/policies/github-mcp.xml`](infra/policies/github-mcp.xml) |
| Foundry OAuth connection (`github-mcp-oauth`) | Your GitHub App's client ID and secret. Stores each user's GitHub token after sign-in. |
| Foundry role assignments (optional) | **Foundry User** for developers, **Foundry Agent Consumer** for chat-only users |
| Prompt agent `github-mcp-agent` | Created by [`scripts/deploy_agent.py`](scripts/deploy_agent.py). Prompt agents are Foundry data-plane objects, so Bicep can't create them. |

## Prerequisites

- An Azure subscription where you can create resource groups and assign roles (Owner, or Contributor plus User Access Administrator).
- Quota for the model in your region. The defaults are `gpt-5.4-mini`, version `2026-03-17`, Global Standard, 10K tokens per minute. Override them with the `model*` parameters.
- Owner access to a GitHub organization, or an owner who can do the [GitHub setup](docs/github-setup.md).
- [Azure CLI](https://learn.microsoft.com/cli/azure/install-azure-cli) with Bicep, and Python 3.10 or later.

```bash
az login
python -m pip install -r scripts/requirements.txt
```

## Let an agent walk you through it

This repository includes an agent skill, [`.github/skills/foundry-github-mcp-setup/SKILL.md`](.github/skills/foundry-github-mcp-setup/SKILL.md). It runs the steps below with you, tells you exactly what to select in GitHub, and pauses whenever you need to act in a browser.

To use it with [GitHub Copilot CLI](https://docs.github.com/copilot/how-tos/use-copilot-agents/use-copilot-cli), open a terminal in this repository, start `copilot`, and ask:

```text
Use the foundry-github-mcp-setup skill to deploy the GitHub MCP agent.
```

Other agents that support [agent skills](https://docs.github.com/copilot/concepts/agents/about-agent-skills) can use the same file.

## Quick start

### 1. Create and install the GitHub App

```bash
python scripts/create_github_app.py --org <your-org> --app-name <unique-app-name>
```

The script prints a link that opens a prefilled, read-only app form in GitHub, then a link to install the app. The credentials are saved to `~/.foundry-mcp/<app-name>.json`. For details, or to create the app by hand, see [docs/github-setup.md](docs/github-setup.md).

### 2. Deploy the infrastructure

Copy [`infra/main.parameters.example.json`](infra/main.parameters.example.json) to `infra/main.parameters.json`, which Git ignores, and fill in the values. To find your object ID for `developerPrincipalIds`:

```bash
az ad signed-in-user show --query id -o tsv
```

Then deploy. The client secret is passed at deployment time and never written to a file in the repository. API Management provisioning takes about 30 to 45 minutes.

```bash
az group create -n <resource-group> -l <region>
az deployment group create -g <resource-group> -n main \
  -f infra/main.bicep -p @infra/main.parameters.json \
  -p githubAppClientSecret="$(python -c "import json,os;print(json.load(open(os.path.expanduser('~/.foundry-mcp/<app-name>.json')))['client_secret'])")"
```

PowerShell:

```powershell
$secret = (Get-Content "$HOME/.foundry-mcp/<app-name>.json" | ConvertFrom-Json).client_secret
az deployment group create -g <resource-group> -n main `
  -f infra/main.bicep -p '@infra/main.parameters.json' -p "githubAppClientSecret=$secret"
```

### 3. Add the callback URL to the GitHub App

```bash
az deployment group show -g <resource-group> -n main \
  --query properties.outputs.githubOAuthRedirectUrl.value -o tsv
```

Paste the URL into the app's **Callback URL** field at `https://github.com/organizations/<your-org>/settings/apps/<app-slug>` and select **Save changes**. See [Step 3 in the GitHub setup guide](docs/github-setup.md#step-3-add-the-foundry-callback-url).

### 4. Deploy the agent

```bash
python scripts/deploy_agent.py --resource-group <resource-group> --github-org <your-org>
```

This creates a new version of `github-mcp-agent` from [`agent/agent.yaml`](agent/agent.yaml), with the GitHub MCP tool attached directly. Rerun it whenever you change the definition.

### 5. Test it

```bash
python scripts/smoke_test.py --resource-group <resource-group> --github-org <your-org>
```

The first run prints a GitHub sign-in link and exits with code 2. Open the link, sign in, authorize the app, and run the test again. It should print `PASS`.

You can also test in the [Foundry portal](https://ai.azure.com): open the project, select **Agents → github-mcp-agent**, and ask "Who am I on GitHub?"

## Operating it

| Topic | What to know |
|---|---|
| Where tokens live | Foundry stores each user's GitHub token per Entra user and per connection. Tokens aren't stored in the browser, in APIM, or in this repository. |
| How long sign-in lasts | GitHub App access tokens last 8 hours and refresh automatically. Refresh tokens last 6 months, so users stay signed in as long as they use the agent at least that often. |
| Multiple agents | Agents in the same project that use the same connection share each user's sign-in. Another project needs its own connection and its own sign-ins. |
| Rotating the client secret | Redeploy the Bicep template with the new secret. Users stay signed in. |
| Signing everyone out | Recreate the connection, then add its new callback URL to the GitHub App. |

See [Maintenance](docs/github-setup.md#maintenance) in the GitHub setup guide for revoking access and changing permissions.

## Customizing

| Change | How |
|---|---|
| GitHub toolsets | `githubToolsets` parameter (default `context,repos,issues,pull_requests,actions`). Match the GitHub App's permissions. |
| Allow write tools | Set `githubReadOnly` to `false`, add write permissions to the GitHub App, and set `require_approval: always` in `agent/agent.yaml`. |
| Agent instructions or name | Edit `agent/agent.yaml`, then rerun `scripts/deploy_agent.py`. |
| Another MCP server | Add a policy file, another `modules/apim-mcp-passthrough.bicep` instance, and an OAuth connection with that provider's authorization URL, token URL, and scopes. Then add an MCP tool to the agent. |
| Share tools across many agents or runtimes | Consider a [Foundry toolbox](https://learn.microsoft.com/azure/foundry/agents/how-to/tools/toolbox) (preview). This repository attaches the tool directly to the agent. |

## Known limitations

- **No organization discovery.** GitHub's MCP server has no tool that lists the organizations or repositories a user can reach, and its search tools search all of GitHub unless the query names an owner. Set a default organization with `--github-org`.
- **Revoked tokens aren't re-prompted.** If a user revokes the GitHub App, Foundry keeps sending the revoked token and the user sees a `401` error until the connection is recreated.
- **Consent page branding.** The sign-in page is hosted by Microsoft (`*.consent.azure-apim.net`) and can't be customized.
- **Rate limiting by IP address.** Agent traffic reaches APIM from shared platform IP addresses, so the rate limit applies to all users together. Size it for your workload.
- **Public endpoint.** The APIM endpoint is reachable from the internet. It rejects calls without a token, and a token only grants its owner's access, but you can add network restrictions for production.
- **Same tenant only.** Users must be in the same Microsoft Entra tenant as the Foundry project.
- **Developer SKU.** The default APIM SKU has no SLA. Use `BasicV2`, `StandardV2`, or `Premium` for production.

## Security notes

- Keep GitHub App credentials outside the repository. `.gitignore` excludes `infra/main.parameters.json`.
- The client secret is a secure Bicep parameter, so it isn't returned in deployment outputs.
- The APIM policy forces read-only mode no matter what an agent requests.
- Review the [considerations for non-Microsoft MCP servers](https://learn.microsoft.com/azure/foundry/agents/how-to/tools/model-context-protocol#considerations-for-using-non-microsoft-services-and-servers) before production use.

## Clean up

```bash
az group delete -n <resource-group>
```

Then delete the GitHub App in its settings under **Advanced → Delete GitHub App**.

## Repository layout

```text
.github/skills/foundry-github-mcp-setup/SKILL.md   Agent skill that guides setup
agent/agent.yaml                                   Prompt agent definition
docs/github-setup.md                               GitHub App setup, maintenance, and troubleshooting
infra/main.bicep                                   Foundry, APIM, OAuth connection, roles
infra/modules/apim-mcp-passthrough.bicep           Reusable APIM MCP passthrough
infra/policies/github-mcp.xml                      GitHub MCP gateway policy
infra/main.parameters.example.json                 Parameter template
scripts/create_github_app.py                       Creates the read-only GitHub App
scripts/deploy_agent.py                            Creates the agent and attaches the MCP tool
scripts/smoke_test.py                              End-to-end test
```

## References

- [Set up MCP server authentication in Foundry](https://learn.microsoft.com/azure/foundry/agents/how-to/mcp-authentication)
- [Connect Foundry agents to MCP servers](https://learn.microsoft.com/azure/foundry/agents/how-to/tools/model-context-protocol)
- [GitHub remote MCP server](https://github.com/github/github-mcp-server/blob/main/docs/remote-server.md)
- [Refreshing GitHub App user access tokens](https://docs.github.com/apps/creating-github-apps/authenticating-with-a-github-app/refreshing-user-access-tokens)

## License

[MIT](LICENSE)
