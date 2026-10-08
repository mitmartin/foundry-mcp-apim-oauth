# GitHub setup

This guide covers everything you do in GitHub: creating the GitHub App, installing it, connecting it to Foundry, and maintaining it. You need to be an **owner of the GitHub organization**, or work with one.

- [Why a GitHub App](#why-a-github-app)
- [Step 1: Create the GitHub App](#step-1-create-the-github-app)
- [Step 2: Install the app on your organization](#step-2-install-the-app-on-your-organization)
- [Step 3: Add the Foundry callback URL](#step-3-add-the-foundry-callback-url)
- [Step 4: Confirm token expiration is on](#step-4-confirm-token-expiration-is-on)
- [What users see the first time](#what-users-see-the-first-time)
- [Maintenance](#maintenance)
- [Troubleshooting](#troubleshooting)

## Why a GitHub App

Each user signs in to GitHub once through the agent. GitHub then issues a token that acts as that user, limited by the app. A GitHub App works better here than an OAuth App or a personal access token:

| | GitHub App (used here) | OAuth App or personal access token |
|---|---|---|
| What a user's token can reach | Only what **both** the user and the app can access | Everything the user can access, within broad scopes |
| Repository scope | Only the organizations and repositories where the app is installed | Not restricted by installation |
| Permissions | Fine-grained, for example read-only contents | Coarse scopes, such as `repo` |
| Token lifetime | 8-hour access tokens with 6-month refresh tokens, when expiration is on | Usually long-lived |
| Control | Organization owners approve installation and permission changes | Users authorize individually |

You don't need the app's private key. The app's private key is for app installation tokens, and this pattern only uses user tokens.

## Step 1: Create the GitHub App

Use either option.

### Option A: Script (recommended)

The script sends a prepared, read-only app manifest to GitHub. You review it and select **Create**. The script saves the client ID and client secret to a file outside the repository.

```bash
python scripts/create_github_app.py --org <your-org> --app-name <unique-app-name>
```

1. Open the printed `http://127.0.0.1:<port>/` link in the browser where you're signed in to GitHub as an organization owner. The script prints links instead of opening them, because a different browser profile could be signed in to a different GitHub account. Add `--open-browser` to open them automatically.
2. GitHub shows the new app form, prefilled. Confirm that the page says the app will be owned by **your organization**, not your personal account.
3. Select **Create GitHub App for &lt;your-org&gt;**.
4. Open the second printed link to install the app (see [Step 2](#step-2-install-the-app-on-your-organization)).

The credentials file defaults to `~/.foundry-mcp/<app-name>.json`. Keep it private.

### Option B: GitHub website

1. Go to `https://github.com/organizations/<your-org>/settings/apps/new`.
2. Fill in the form:

   | Field | Value |
   |---|---|
   | GitHub App name | A unique name, such as `<your-org>-foundry-mcp` |
   | Homepage URL | Any URL you own, such as `https://github.com/<your-org>` |
   | Callback URL | Leave empty for now. You add it in [Step 3](#step-3-add-the-foundry-callback-url). |
   | Expire user authorization tokens | **Checked** |
   | Request user authorization (OAuth) during installation | Unchecked |
   | Enable Device Flow | Unchecked |
   | Setup URL | Empty |
   | Webhook → Active | **Unchecked** |

3. Under **Permissions → Repository permissions**, set:

   | Permission | Access |
   |---|---|
   | Actions | Read-only |
   | Contents | Read-only |
   | Issues | Read-only |
   | Metadata | Read-only (required) |
   | Pull requests | Read-only |

   Leave **Organization permissions** and **Account permissions** at **No access**.

4. Under **Where can this GitHub App be installed?**, select **Only on this account**.
5. Select **Create GitHub App**.
6. On the app's **General** page, copy the **Client ID**. Then select **Generate a new client secret** and copy the secret right away; GitHub shows it only once. Store both in a file outside the repository:

   ```json
   { "client_id": "<client-id>", "client_secret": "<client-secret>" }
   ```

## Step 2: Install the app on your organization

1. Go to `https://github.com/apps/<app-slug>/installations/new`, or open the app's settings and select **Install App**.
2. Select your organization.
3. Choose **Only select repositories** and pick the repositories the agent may read. **All repositories** also works.
4. Select **Install**.

The agent can only see private repositories where the app is installed. It can also read public repositories.

## Step 3: Add the Foundry callback URL

The Foundry OAuth connection gets its own callback URL when the infrastructure is deployed with `enableGitHub=true`. GitHub only sends users back to registered URLs, so sign-in fails until you add it.

1. Get the URL from the deployment:

   ```bash
   az deployment group show -g <resource-group> -n main \
     --query properties.outputs.githubOAuthRedirectUrl.value -o tsv
   ```

   It looks like `https://global.consent.azure-apim.net/redirect/<id>`.

2. Go to `https://github.com/organizations/<your-org>/settings/apps/<app-slug>`.
3. Under **Identifying and authorizing users → Callback URL**, paste the URL. To support more environments, select **Add Callback URL** and add each environment's URL.
4. Select **Save changes**.

Redeploying the same Bicep template keeps the same callback URL. A **new** connection, such as one with a different `githubConnectionName` or one that was deleted and recreated, gets a new URL that you must add.

## Step 4: Confirm token expiration is on

In the app settings, select **Optional features** and confirm **User-to-server token expiration** is opted in. With expiration on, access tokens last 8 hours and Foundry refreshes them automatically for up to 6 months of inactivity. With it off, tokens never expire unless revoked.

## What users see the first time

1. In the agent chat, the user asks something that needs GitHub.
2. The agent shows a sign-in card. The user selects it.
3. A Microsoft consent page opens (`*.consent.azure-apim.net`). This page is hosted by Microsoft, not by your API Management instance, and it can't be branded.
4. GitHub asks the user to sign in, if needed, and to authorize the app. The page lists the app's read-only permissions.
5. The user returns to the chat and asks again. Later requests don't prompt.

If the user is already signed in to GitHub and authorized the app before, GitHub skips the sign-in and authorization steps.

The sign-in applies to **one Microsoft Entra user and one Foundry connection**. Every agent in the project that uses the same connection reuses it. A different Entra user signs in separately.

> **Testing with several users on one computer:** if user B selects the sign-in card in a browser where user A is still signed in to GitHub, GitHub authorizes **user A's** GitHub account for user B. Use separate browsers or a fresh private window for each test user.

## Maintenance

### Add permissions or toolsets

1. Update the app's permissions in GitHub. An organization owner must approve the change on the installation.
2. Update the `githubToolsets` (and `githubReadOnly`) Bicep parameters and redeploy.
3. If you enable write tools, set `require_approval: always` in `agent/github-agent.yaml` and redeploy the agent.

### Rotate the client secret

1. Generate a new client secret in the app settings.
2. Redeploy the Bicep template with the new secret. Updating the connection in place keeps users signed in and keeps the same callback URL.
3. Delete the old secret in GitHub.

### Revoke access

| Goal | Action | Effect |
|---|---|---|
| Remove one user's access | The user revokes the app at `https://github.com/settings/apps/authorizations` | Access stops immediately. See the note below. |
| Remove access to some repositories | Change the installation's repository selection | Applies to everyone right away |
| Remove access for the whole organization | Uninstall or suspend the app at `https://github.com/organizations/<your-org>/settings/installations` | Applies to everyone right away |
| Sign out every user | Recreate the Foundry connection, then add its new callback URL to the app | Everyone signs in again on next use |

> **Note:** When a user revokes the app, Foundry keeps sending the revoked token, and the user gets a `401 ... token authentication failed` error instead of a new sign-in card. Foundry has no per-user sign-out today, so the fix is to recreate the connection, which signs out every user. Delete the connection and redeploy the Bicep template, then add the new callback URL.

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| GitHub says the `redirect_uri` isn't associated with this application | The callback URL is missing or outdated | Add the current `githubOAuthRedirectUrl` output ([Step 3](#step-3-add-the-foundry-callback-url)) |
| `401 ... token authentication failed` after sign-in worked before | The user's GitHub token was revoked | See [Revoke access](#revoke-access) |
| Public repositories work, but a private repository returns not found | The app isn't installed on that repository, or the user can't access it | Add the repository to the installation, or grant the user access |
| The agent asks which organization to use, or returns results from unrelated repositories | GitHub search covers all of GitHub unless the query names an owner. GitHub's MCP server has no tool that lists the organizations a user can reach. | Deploy the agent with `--github-org`, or tell the agent the organization |
| The sign-in card never appears for a new user | The user lacks a Foundry role on the project, or is in a different Entra tenant | Assign the **Foundry Agent Consumer** or **Foundry User** role. The user must be in the project's tenant. |
| The organization enforces SAML single sign-on | GitHub may require an active SAML session for the user's token | Have the user complete single sign-on in GitHub, then sign in through the agent again |

Before production, confirm with your GitHub administrators that your organization's GitHub policies allow access to GitHub's hosted MCP server (`https://api.githubcopilot.com/mcp/`) and GitHub App installations.
