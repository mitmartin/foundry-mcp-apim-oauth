# ZoomInfo setup

This guide covers everything you do in ZoomInfo to connect its hosted MCP server (`https://mcp.zoominfo.com/mcp`) to Foundry agents through API Management: registering an app, connecting it to Foundry, and maintaining it.

- [How sign-in works](#how-sign-in-works)
- [Before you start](#before-you-start)
- [Step 1: Deploy with ZoomInfo enabled](#step-1-deploy-with-zoominfo-enabled)
- [Step 2: Register a ZoomInfo MCP app](#step-2-register-a-zoominfo-mcp-app)
- [Step 3: Redeploy with the app credentials](#step-3-redeploy-with-the-app-credentials)
- [Step 4: Deploy and test the agent](#step-4-deploy-and-test-the-agent)
- [Credits](#credits)
- [Maintenance](#maintenance)
- [Troubleshooting](#troubleshooting)

## How sign-in works

Each user signs in to ZoomInfo once through the agent, with their own ZoomInfo login or single sign-on, such as **Sign in with Microsoft**. Foundry stores that user's ZoomInfo token for the connection and sends it with every MCP call. API Management forwards it unchanged. Results reflect that user's ZoomInfo access, and credits come from that user's account.

| Setting | Value |
|---|---|
| MCP server | `https://mcp.zoominfo.com/mcp` (Streamable HTTP, exactly `/mcp` with no trailing slash) |
| Authorization URL | `https://mcp.zoominfo.com/oauth/authorize` |
| Token and refresh URL | `https://okta-login.zoominfo.com/oauth2/default/v1/token` |
| Scopes | `openid profile email offline_access zi_mcp api:data:mcp` |
| PKCE | Required (S256). Foundry's OAuth sign-in sends it. |

The Bicep template sets all of these. You only supply the app's client ID and client secret.

## Before you start

- **A ZoomInfo login with data access.** Admin-only seats can't use MCP. A new [gtm.ai](https://gtm.ai/start-building) builder account includes free starter credits.
- **A place to register an app:**
  - If you signed up through gtm.ai, use the **API/MCP** tab in the ZoomInfo app.
  - Existing ZoomInfo customers use the [Developer Portal](https://developer.zoominfo.com). A ZoomInfo admin enables it by assigning the DevPortal subscription (**Admin Portal → User Management → Users**).

You have to register the app yourself. ZoomInfo only allows automatic client registration (dynamic client registration) for its approved vendors, and it rejects other clients with `Vendor ... was not found in approved vendors`.

## Step 1: Deploy with ZoomInfo enabled

ZoomInfo needs the Foundry connection's callback URL when you register the app, and the connection needs the app's credentials. To break that loop, the first deployment creates the connection with placeholder credentials.

1. In `infra/main.parameters.json`, set `"enableZoomInfo": { "value": true }` and leave `zoominfoClientId` empty.
2. Deploy the template. See the [README quick start](../README.md#quick-start).
3. Get the callback URL:

   ```bash
   az deployment group show -g <resource-group> -n main \
     --query properties.outputs.zoominfoOAuthRedirectUrl.value -o tsv
   ```

   It looks like `https://global.consent.azure-apim.net/redirect/<id>`.

## Step 2: Register a ZoomInfo MCP app

1. Open the app area:
   - **gtm.ai accounts:** sign in at `https://gtm-studio.zoominfo.com` and select **API/MCP** in the left navigation.
   - **Existing customers:** sign in at `https://developer.zoominfo.com`.
2. Select **Create App** and enter a name. Users see this name on the ZoomInfo consent screen. In the Developer Portal, choose **MCP App**, not API App.
3. Add the callback URL from Step 1 as a **redirect URI**. It must match character for character, with no trailing slash or spaces.
4. Select **Create**. Internal-use apps are approved immediately.
5. Open the app and copy the **Client ID** and **Client Secret**. Save them to a file outside the repository, for example `~/.foundry-mcp/zoominfo-app.json`:

   ```json
   { "client_id": "<client-id>", "client_secret": "<client-secret>" }
   ```

   Treat the secret like a password, and never commit it.

## Step 3: Redeploy with the app credentials

Set `zoominfoClientId` in `infra/main.parameters.json`, then redeploy and pass the secret at deployment time. Pass the GitHub secret too if GitHub is enabled.

PowerShell:

```powershell
$zi = Get-Content "$HOME/.foundry-mcp/zoominfo-app.json" | ConvertFrom-Json
az deployment group create -g <resource-group> -n main `
  -f infra/main.bicep -p '@infra/main.parameters.json' `
  -p "zoominfoClientSecret=$($zi.client_secret)"
```

Bash:

```bash
az deployment group create -g <resource-group> -n main \
  -f infra/main.bicep -p @infra/main.parameters.json \
  -p zoominfoClientSecret="$(python -c "import json,os;print(json.load(open(os.path.expanduser('~/.foundry-mcp/zoominfo-app.json')))['client_secret'])")"
```

The connection is updated in place, so its callback URL stays the same. Confirm that the `zoominfoRegistered` output is now `true`.

> **Important:** Pass `zoominfoClientSecret` on **every** later deployment. Deploying with an empty secret resets the connection to placeholder credentials, and ZoomInfo sign-in stops working until you redeploy with the secret.

## Step 4: Deploy and test the agent

```bash
python scripts/deploy_agent.py --resource-group <resource-group> --service zoominfo
python scripts/smoke_test.py --resource-group <resource-group> --service zoominfo
```

The first smoke-test run prints a ZoomInfo sign-in link and exits with code 2. Open it, sign in, approve access, and run it again. The test calls ZoomInfo's free **Lookup** tool, so it doesn't use credits.

You can also test in the [Foundry portal](https://ai.azure.com): open the project, select **Agents → zoominfo-research-agent**, and ask "What ZoomInfo tools do you have access to?" Approve the sign-in card when it appears.

## Credits

Most ZoomInfo tools are free, including search and Lookup. Two groups use credits ([details](https://gtm.ai/docs/mcp/credits)):

| Credit type | Used by |
|---|---|
| Data credits | Enrich Companies, Enrich Contacts, Enrich Company Signals, and loading records into audiences. One credit per record that your organization hasn't enriched in the last 12 months. |
| AI credits | Account Research, Contact Research, Conversation Intelligence, and Audience Analysis. Usually 5 to 15 credits per research call. |

ZoomInfo doesn't preview costs before a call. The agent's instructions in `agent/zoominfo-agent.yaml` tell it to keep requests small and to say when a request uses credits. ZoomInfo admins can set per-user credit limits in **Admin Portal → Users → User Management**, and MCP respects them.

## Maintenance

| Task | How |
|---|---|
| Rotate the client secret | Generate a new secret on the ZoomInfo app, then redeploy with it. Users stay signed in, and the callback URL doesn't change. |
| Add another environment | Each environment's connection has its own callback URL. Add each one as a redirect URI on the same app, or register one app per environment. |
| Sign out every user | Delete the Foundry connection and redeploy, then add the new callback URL to the ZoomInfo app. |
| Remove ZoomInfo | Set `enableZoomInfo` to `false`. That stops managing the resources but doesn't delete them, so delete the `zoominfo-mcp` API in API Management and the connection in Foundry. Then delete the ZoomInfo app. |

ZoomInfo sessions can expire after a few hours of inactivity, depending on your ZoomInfo security settings. Foundry refreshes tokens automatically while the refresh token is valid. If it isn't, the user sees the sign-in card again.

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| ZoomInfo shows **400 Bad Request: The 'redirect_uri' parameter must be a Login redirect URI in the client app settings**, often after choosing **Sign in with Microsoft** | The Foundry callback URL isn't a redirect URI on the ZoomInfo app, or doesn't match exactly | Add the current `zoominfoOAuthRedirectUrl` output to the app's redirect URIs ([Step 2](#step-2-register-a-zoominfo-mcp-app)) |
| Sign-in fails right away with an unknown or invalid client error | The connection still has placeholder credentials | Redeploy with the client ID and secret ([Step 3](#step-3-redeploy-with-the-app-credentials)). Check that `zoominfoRegistered` is `true`. |
| `Vendor ... was not found in approved vendors` | Something tried automatic client registration | Register the app manually ([Step 2](#step-2-register-a-zoominfo-mcp-app)) |
| Tools return `403` | The user's package lacks the entitlement, or the user is out of credits | Check the user's ZoomInfo package and credit balance |
| Enrichment fails with a credit error on an older subscription | MCP can't use recurring monthly credits | Ask the ZoomInfo admin to enable bulk data credits |
| `429 Too Many Requests` | ZoomInfo allows 25 requests per second | Retry later, or lower the API Management rate limit |

## References

- [ZoomInfo MCP getting started](https://gtm.ai/docs/mcp/getting-started)
- [Add ZoomInfo as a custom connector](https://gtm.ai/docs/mcp/clients/custom)
- [Build your own app on the ZoomInfo MCP](https://gtm.ai/guides/how-to-build-a-custom-mcp-app)
- [ZoomInfo MCP tools](https://gtm.ai/docs/mcp/tools)
- [Credits and billing](https://gtm.ai/docs/mcp/credits)
