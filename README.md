# Foundry agents with third-party MCP servers through Azure API Management (per-user OAuth)

A deployable reference for giving Microsoft Foundry prompt agents access to third-party MCP servers, where **every tool call runs as the signed-in user**. Azure API Management (APIM) sits in the middle to enforce policy centrally. No user tokens or secrets are stored in this repository or in APIM.

Two MCP servers are included. Turn on either or both:

| MCP server | Flag | What it gives agents | Setup guide |
|---|---|---|---|
| GitHub (`api.githubcopilot.com/mcp/`) | `enableGitHub` | Read-only access to repositories, issues, pull requests, and Actions | [docs/github-setup.md](docs/github-setup.md) |
| ZoomInfo (`mcp.zoominfo.com/mcp`) | `enableZoomInfo` | Company and contact search, lookup, enrichment, and account research | [docs/zoominfo-setup.md](docs/zoominfo-setup.md) |

```text
User in Foundry (signed in with Microsoft Entra ID)
   │
   ▼
Foundry prompt agent ── tools from a toolbox, or attached directly to the agent
   │                    both use a Foundry OAuth connection, which holds each user's token for that service
   ▼
Azure API Management   /github-mcp/mcp, /zoominfo-mcp/mcp
   │                    requires a token, applies policy, throttles, streams
   ▼
Third-party MCP server (GitHub, ZoomInfo)
                        runs as that user, with that user's access
```

## How it works

- **Per-user access.** The first time a user calls a service's tool, the agent shows a sign-in card. The user signs in to that service, and Foundry stores that user's token for the connection. Later calls reuse it and refresh it automatically.
- **Least privilege.** A user can only reach what **they** can access in the service. For GitHub, access is further limited by your GitHub App's read-only permissions and installation.
- **Central governance.** Each service has its own APIM API and policy. Every policy rejects calls without a token and throttles traffic. The GitHub policy also pins toolsets and forces read-only mode.
- **Tools set up once.** The MCP tools go in a [Foundry toolbox](docs/toolbox.md). An agent can attach the whole toolbox in code, or you can add individual tools directly to an agent; in the portal they appear under **Configured**. Both options use the same OAuth connections, so users sign in to each service once per project.

## What gets deployed

| Resource | When | Purpose |
|---|---|---|
| Foundry account, project, and model deployment | Always | Hosts the prompt agents. API keys are disabled; Microsoft Entra ID is required. |
| API Management service | Always | Gateway for the MCP servers |
| `github-mcp` API and `github-mcp-oauth` connection | `enableGitHub` | GitHub MCP passthrough ([policy](infra/policies/github-mcp.xml)) and the connection that stores users' GitHub tokens |
| `zoominfo-mcp` API and `zoominfo-mcp-oauth` connection | `enableZoomInfo` | ZoomInfo MCP passthrough ([policy](infra/policies/zoominfo-mcp.xml)) and the connection that stores users' ZoomInfo tokens |
| Foundry role assignments | Optional | **Foundry User** for developers, **Foundry Agent Consumer** for chat-only users |
| Toolbox `mcp-tools` and connection `mcp-tools-user` | After deployment | Created by [`scripts/create_toolbox.py`](scripts/create_toolbox.py). Holds the MCP tools for agents to share. |
| Prompt agents `github-mcp-agent` and `zoominfo-research-agent` | Per service | Created by [`scripts/deploy_agent.py`](scripts/deploy_agent.py), with the toolbox or with tools attached directly. Toolboxes and prompt agents are Foundry data-plane objects, so Bicep can't create them. |

## Prerequisites

- An Azure subscription where you can create resource groups and assign roles (Owner, or Contributor plus User Access Administrator).
- Quota for the model in your region. The defaults are `gpt-5.4-mini`, version `2026-03-17`, Global Standard, 100K tokens per minute. MCP tool definitions are large, so don't go much lower. See [Model capacity](docs/toolbox.md#model-capacity). Override them with the `model*` parameters.
- For GitHub: owner access to a GitHub organization, or an owner who can do the [GitHub setup](docs/github-setup.md).
- For ZoomInfo: a ZoomInfo login with data access, and access to the API/MCP tab or the Developer Portal. See [ZoomInfo setup](docs/zoominfo-setup.md#before-you-start).
- [Azure CLI](https://learn.microsoft.com/cli/azure/install-azure-cli) with Bicep, and Python 3.10 or later.

```bash
az login
python -m pip install -r scripts/requirements.txt
```

## Let an agent walk you through it

This repository includes an agent skill, [`.github/skills/foundry-mcp-setup/SKILL.md`](.github/skills/foundry-mcp-setup/SKILL.md). It asks which MCP servers you want, runs the steps below with you, tells you exactly what to select in GitHub and ZoomInfo, and pauses whenever you need to act in a browser.

To use it with [GitHub Copilot CLI](https://docs.github.com/copilot/how-tos/use-copilot-agents/use-copilot-cli), open a terminal in this repository, start `copilot`, and ask:

```text
Use the foundry-mcp-setup skill to set up my MCP agents.
```

Other agents that support [agent skills](https://docs.github.com/copilot/concepts/agents/about-agent-skills) can use the same file.

## Quick start

Each service follows the same pattern: deploy its connection, register the service's app with the connection's callback URL, and deploy with the app credentials. Then put the tools in a toolbox, give agents the tools, and test.

### 1. Choose your MCP servers and fill in parameters

Copy [`infra/main.parameters.example.json`](infra/main.parameters.example.json) to `infra/main.parameters.json`, which Git ignores. Set `enableGitHub` and `enableZoomInfo` for the services you want, and fill in `apimPublisherEmail` and `developerPrincipalIds`. To find your object ID:

```bash
az ad signed-in-user show --query id -o tsv
```

For GitHub, you can create the GitHub App first, since GitHub lets you add the callback URL afterward:

```bash
python scripts/create_github_app.py --org <your-org> --app-name <unique-app-name>
```

The script prints a link to a prefilled, read-only app form in GitHub, then a link to install the app. Credentials are saved to `~/.foundry-mcp/<app-name>.json`. Put the client ID in `githubAppClientId`. For details, see [GitHub setup](docs/github-setup.md).

### 2. Deploy the infrastructure

Pass client secrets at deployment time, never in a file in the repository. A connection without credentials is created with placeholders so you can get its callback URL first. API Management provisioning takes about 30 to 45 minutes the first time.

PowerShell:

```powershell
az group create -n <resource-group> -l <region>
$gh = Get-Content "$HOME/.foundry-mcp/<github-app-name>.json" | ConvertFrom-Json   # GitHub only
az deployment group create -g <resource-group> -n main `
  -f infra/main.bicep -p '@infra/main.parameters.json' `
  -p "githubAppClientSecret=$($gh.client_secret)"
```

Bash:

```bash
az group create -n <resource-group> -l <region>
az deployment group create -g <resource-group> -n main \
  -f infra/main.bicep -p @infra/main.parameters.json \
  -p githubAppClientSecret="$(python -c "import json,os;print(json.load(open(os.path.expanduser('~/.foundry-mcp/<github-app-name>.json')))['client_secret'])")"
```

Omit the GitHub secret if GitHub is off. Add `zoominfoClientSecret` the same way once the ZoomInfo app exists.

### 3. Register the callback URLs

```bash
az deployment group show -g <resource-group> -n main --query "properties.outputs.{github:githubOAuthRedirectUrl.value, zoominfo:zoominfoOAuthRedirectUrl.value}"
```

- **GitHub:** paste `github` into the GitHub App's **Callback URL** and save. See [Step 3](docs/github-setup.md#step-3-add-the-foundry-callback-url).
- **ZoomInfo:** register a ZoomInfo MCP app with `zoominfo` as its redirect URI, set `zoominfoClientId`, and redeploy with `zoominfoClientSecret`. See [Steps 2 and 3](docs/zoominfo-setup.md#step-2-register-a-zoominfo-mcp-app).

The `githubRegistered` and `zoominfoRegistered` outputs show whether each connection has real credentials.

> **Important:** Once a service's app exists, pass its client secret on **every** deployment. Deploying with an empty secret resets that connection to placeholders, and sign-in to that service stops working.

### 4. Put the tools in a toolbox

```bash
python scripts/create_toolbox.py --resource-group <resource-group> --service github --service zoominfo
```

Include a `--service` for each enabled MCP server. This creates the `mcp-tools` toolbox and makes the tools available to agents. See [Toolbox and agents](docs/toolbox.md).

### 5. Deploy the agents

Give each agent the tools in either of two ways:

```bash
# Option A: attach the whole toolbox (doesn't show in the portal's Tools list)
python scripts/deploy_agent.py --resource-group <resource-group> --service zoominfo --toolbox-name mcp-tools

# Option B: attach the service's tool directly (shows in the portal's Tools list)
python scripts/deploy_agent.py --resource-group <resource-group> --service github --github-org <your-org>
python scripts/deploy_agent.py --resource-group <resource-group> --service zoominfo
```

`--service` picks the instructions and name from [`agent/github-agent.yaml`](agent/github-agent.yaml) or [`agent/zoominfo-agent.yaml`](agent/zoominfo-agent.yaml). Rerun the command whenever you change a definition. You can also add the tools directly to any agent in the [Foundry portal](https://ai.azure.com): under the agent's **Tools**, select **Add**, then choose the tool under **Configured**.

### 6. Test

```bash
python scripts/smoke_test.py --resource-group <resource-group> --service github --github-org <your-org>
python scripts/smoke_test.py --resource-group <resource-group> --service zoominfo
```

The first run for each service prints a sign-in link and exits with code 2. Open the link, sign in, approve access, and run the test again. It should print `PASS`. The ZoomInfo test uses the free Lookup tool.

You can also test in the [Foundry portal](https://ai.azure.com): open the project, select **Agents**, open an agent, and ask "Who am I on GitHub?" or "What ZoomInfo tools do you have access to?"

## Operating it

| Topic | What to know |
|---|---|
| Where tokens live | Foundry stores each user's token per Entra user and per connection. Tokens aren't stored in the browser, in APIM, or in this repository. |
| How long sign-in lasts | It depends on the service. GitHub App access tokens last 8 hours and refresh automatically for up to 6 months of inactivity. ZoomInfo sessions follow your ZoomInfo security settings. |
| Multiple agents | Agents in the same project that use the same connection share each user's sign-in, whether they use the toolbox or direct tools. Another project needs its own connections and its own sign-ins. |
| Several projects in one Foundry account | Connection names must be unique across the whole Foundry account, not just the project. Set `githubConnectionName` and `zoominfoConnectionName` per project. |
| Rotating a client secret | Redeploy the Bicep template with the new secret. Users stay signed in, and the callback URL doesn't change. |
| Signing everyone out | Delete and recreate the connection, then add its new callback URL to the service's app. |
| ZoomInfo credits | Search and Lookup are free. Enrichment and research use the signed-in user's credits. See [Credits](docs/zoominfo-setup.md#credits). |

## Customizing

| Change | How |
|---|---|
| GitHub toolsets | `githubToolsets` parameter (default `context,repos,issues,pull_requests,actions`). Match the GitHub App's permissions. |
| Allow GitHub write tools | Set `githubReadOnly` to `false`, add write permissions to the GitHub App, and set `require_approval: always` in `agent/github-agent.yaml`. |
| Agent instructions or names | Edit the files in `agent/`, then rerun `scripts/deploy_agent.py`. |
| Another MCP server | Add a policy file, another `modules/apim-mcp-passthrough.bicep` instance, and an OAuth connection with that provider's authorization URL, token URL, and scopes. Then add an entry to `SERVICES` in `scripts/common.py` and an agent definition. |
| Separate toolboxes | Run `create_toolbox.py` with a different `--toolbox-name` and `--service` set, for example one toolbox per team or per service. |
| Hosted agents and other MCP clients | Point them at the toolbox endpoint. See [Use a toolbox with a hosted agent](https://learn.microsoft.com/azure/foundry/agents/how-to/tools/use-toolbox-hosted-agent). |

## Known limitations

- **One credential per tool.** Each MCP tool carries one connection, so APIM receives the service's token, not the user's Entra token. To identify the user, APIM has to resolve them from the service token, for example with GitHub's `/user` endpoint.
- **No GitHub organization discovery.** GitHub's MCP server has no tool that lists a user's organizations, and its search tools search all of GitHub unless the query names an owner. Set a default organization with `--github-org`.
- **Revoked tokens aren't re-prompted.** If a user revokes access in the service, Foundry keeps sending the revoked token and the user sees a `401` error until the connection is recreated.
- **Consent page branding.** The sign-in page is hosted by Microsoft (`*.consent.azure-apim.net`) and can't be customized.
- **Rate limiting by IP address.** Agent traffic reaches APIM from shared platform IP addresses, so the rate limit applies to all users together. Size it for your workload.
- **Public endpoint.** The APIM endpoint is reachable from the internet. It rejects calls without a token, and a token only grants its owner's access, but you can add network restrictions for production.
- **Same tenant only.** Users must be in the same Microsoft Entra tenant as the Foundry project.
- **Toolboxes are in preview.** The portal doesn't list a toolbox's tools in an agent's **Tools** section, though they work at runtime. Tools added directly do show there.
- **Developer SKU.** The default APIM SKU has no SLA. Use `BasicV2`, `StandardV2`, or `Premium` for production.

## Security notes

- Keep app credentials outside the repository. `.gitignore` excludes `infra/main.parameters.json`.
- Client secrets are secure Bicep parameters, so they aren't returned in deployment outputs.
- The GitHub policy forces read-only mode no matter what an agent requests.
- Review the [considerations for non-Microsoft MCP servers](https://learn.microsoft.com/azure/foundry/agents/how-to/tools/model-context-protocol#considerations-for-using-non-microsoft-services-and-servers) before production use.

## Clean up

```bash
az group delete -n <resource-group>
```

Then delete the GitHub App (its settings → **Advanced → Delete GitHub App**) and the ZoomInfo app.

## Repository layout

```text
.github/skills/foundry-mcp-setup/SKILL.md     Agent skill that guides setup
agent/github-agent.yaml                       GitHub prompt agent definition
agent/zoominfo-agent.yaml                     ZoomInfo prompt agent definition
docs/github-setup.md                          GitHub App setup, maintenance, and troubleshooting
docs/toolbox.md                               Toolbox, direct tools, and model capacity
docs/zoominfo-setup.md                        ZoomInfo app setup, credits, maintenance, and troubleshooting
infra/main.bicep                              Foundry, APIM, OAuth connections, roles
infra/modules/apim-mcp-passthrough.bicep      Reusable APIM MCP passthrough
infra/policies/github-mcp.xml                 GitHub MCP gateway policy
infra/policies/zoominfo-mcp.xml               ZoomInfo MCP gateway policy
infra/main.parameters.example.json            Parameter template
scripts/common.py                             Shared helpers and per-service settings
scripts/create_github_app.py                  Creates the read-only GitHub App
scripts/create_toolbox.py                     Puts the MCP tools in a toolbox
scripts/deploy_agent.py                       Creates an agent with the toolbox or direct tools
scripts/smoke_test.py                         End-to-end test
```

## References

- [Set up MCP server authentication in Foundry](https://learn.microsoft.com/azure/foundry/agents/how-to/mcp-authentication)
- [Connect Foundry agents to MCP servers](https://learn.microsoft.com/azure/foundry/agents/how-to/tools/model-context-protocol)
- [GitHub remote MCP server](https://github.com/github/github-mcp-server/blob/main/docs/remote-server.md)
- [Refreshing GitHub App user access tokens](https://docs.github.com/apps/creating-github-apps/authenticating-with-a-github-app/refreshing-user-access-tokens)
- [ZoomInfo MCP getting started](https://gtm.ai/docs/mcp/getting-started)

## License

[MIT](LICENSE)
