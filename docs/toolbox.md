# Toolbox and agents

Set up the MCP tools once in a Foundry toolbox, then give agents those tools in whichever way fits each agent.

- [How it fits together](#how-it-fits-together)
- [Step 1: Put the tools in a toolbox](#step-1-put-the-tools-in-a-toolbox)
- [Step 2: Give an agent the tools](#step-2-give-an-agent-the-tools)
- [Which option to use](#which-option-to-use)
- [Model capacity](#model-capacity)
- [Troubleshooting](#troubleshooting)

## How it fits together

```text
Bicep deployment
  └─ OAuth connections (github-mcp-oauth, zoominfo-mcp-oauth)   ← hold each user's tokens
       │
       ▼
Toolbox (scripts/create_toolbox.py)                             ← the tools, set up once
  ├─ GitHub MCP tool   → APIM /github-mcp/mcp
  └─ ZoomInfo MCP tool → APIM /zoominfo-mcp/mcp
       │
       ├─ Option A: attach the whole toolbox to an agent (code)
       └─ Option B: add individual tools directly to an agent (portal "Configured", or code)
```

Both options use the same OAuth connections, so each user signs in to each service **once per project**. Switching an agent from one option to the other doesn't require signing in again.

## Step 1: Put the tools in a toolbox

After the infrastructure is deployed and the service apps are registered, run:

```bash
python scripts/create_toolbox.py --resource-group <resource-group> --service github --service zoominfo
```

- Include a `--service` for each enabled MCP server you want in the toolbox.
- The toolbox is named `mcp-tools` by default. Use `--toolbox-name` for another name, such as one toolbox per team.
- The script also creates the connection that lets agents call the toolbox as the signed-in user (`<toolbox-name>-user`).
- It's safe to rerun. A new toolbox version is created and made the default only when the tools change.

Toolboxes are [in preview](https://learn.microsoft.com/azure/foundry/agents/how-to/tools/toolbox). They're Foundry data-plane objects, so the script creates them instead of Bicep.

## Step 2: Give an agent the tools

### Option A: Attach the whole toolbox (code)

```bash
python scripts/deploy_agent.py --resource-group <resource-group> --service zoominfo --toolbox-name mcp-tools
```

The agent gets **one** MCP tool that points at the toolbox and exposes every tool in it. Tool names are prefixed with the service, for example `zoominfo___lookup`.

- Change the toolbox later and every agent that uses it picks up the change, without redeploying the agents.
- The Foundry portal **doesn't list a toolbox's tools** in the agent's **Tools** section. The tools still work in the playground and at runtime.
- Hosted agents and other MCP clients can use the same toolbox endpoint. See [Use a toolbox with a hosted agent](https://learn.microsoft.com/azure/foundry/agents/how-to/tools/use-toolbox-hosted-agent).

`--service` picks the agent definition (instructions and name) from `agent/<service>-agent.yaml`. Use `--agent-name` to deploy a separate agent alongside a directly attached one.

### Option B: Add tools directly to an agent

Putting the tools in a toolbox also makes them available as individual options for any agent:

- **Portal:** in the [Foundry portal](https://ai.azure.com), open the agent, select **Add** under **Tools**, and choose the GitHub or ZoomInfo tool under **Configured**. The tool shows in the agent's **Tools** list.
- **Code:** run `deploy_agent.py` without `--toolbox-name`. It attaches the service's MCP tool directly, as defined in `agent/<service>-agent.yaml`:

  ```bash
  python scripts/deploy_agent.py --resource-group <resource-group> --service zoominfo
  ```

A directly attached tool is a copy of the tool settings in that agent. Changing the toolbox doesn't change it, so update or redeploy those agents yourself.

## Which option to use

| | Option A: toolbox | Option B: direct |
|---|---|---|
| How you add it | Code (`--toolbox-name`) | Portal **Configured** list, or code |
| Shows in the agent's Tools list in the portal | No | Yes |
| Tool changes reach agents | Automatically, from the toolbox's default version | Only when you update each agent |
| Usable by hosted agents and other MCP clients | Yes | Prompt agents only |
| User sign-in | Once per service per project | Same, and shared with Option A |

Use the toolbox when many agents share the same tools, or when you want to change tools centrally. Use direct tools when people build agents in the portal and want to see the tools there.

## Model capacity

MCP tool definitions are sent to the model with every request, so tools add input tokens:

- In testing, the ZoomInfo tools added about **35K input tokens** per request. A request that calls one tool uses two model turns.
- The GitHub tools are smaller, but a toolbox with **both** services sends both sets of definitions on every request.

The template's default model capacity is 100K tokens per minute. A deployment of 10K tokens per minute rejects ZoomInfo requests with `429 Model deployment rate limit exceeded`. Raise `modelCapacity` for more users, or keep services in separate toolboxes so agents only load the tools they need. For large toolboxes, also consider [Tool Search](https://learn.microsoft.com/azure/foundry/agents/how-to/tools/tool-search) (preview), which loads tool definitions on demand.

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `Missing required query parameter: audience` | The agent's toolbox URL lacks `&audience=https%3A%2F%2Fai.azure.com` | Use `deploy_agent.py --toolbox-name`, which builds the right URL |
| `Toolbox connection '<name>-user' wasn't found` | The toolbox hasn't been created | Run `create_toolbox.py` with the same `--toolbox-name` |
| `429 Model deployment rate limit exceeded` | The model's tokens-per-minute limit is too low for the tool definitions | Raise `modelCapacity`. See [Model capacity](#model-capacity). |
| `tools/list failed ... HTTP_429 ... ZI0004` | ZoomInfo throttled rapid repeated requests | Wait a minute and retry |
| The tools don't appear in the agent's Tools list | The agent uses the toolbox (Option A) | Expected. Use Option B if the tools need to show in the portal. |
| The sign-in card appears again after switching options | The agent uses a different OAuth connection | Point both options at the same connection. `create_toolbox.py` uses the Bicep connections. |
