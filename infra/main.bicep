// ---------------------------------------------------------------------------
// Foundry prompt agents + third-party MCP servers through Azure API
// Management, with per-user OAuth (each user signs in to each service once;
// calls run as that user).
//
// Deploys:
//   * Foundry account, project, and model deployment
//   * API Management with streaming MCP passthroughs for the MCP servers you
//     enable: GitHub's hosted MCP (enableGitHub) and ZoomInfo's hosted MCP
//     (enableZoomInfo)
//   * Foundry OAuth connections that hold each user's tokens
//   * Optional Foundry role assignments for developers and agent users
//
// Prompt agents are Foundry data-plane objects, not Azure Resource Manager
// resources, so scripts/deploy_agent.py creates the agent and attaches the
// MCP tool after this deployment. See README.md.
// ---------------------------------------------------------------------------

targetScope = 'resourceGroup'

@description('Azure region for all resources.')
param location string = resourceGroup().location

@minLength(3)
@maxLength(12)
@description('Lowercase letters and digits used to name resources.')
param namePrefix string = 'mcpagent'

@description('Foundry account name. Must be globally unique.')
param foundryAccountName string = '${namePrefix}${take(uniqueString(resourceGroup().id), 8)}'

@description('Foundry project name.')
param projectName string = 'mcp-agents'

@description('Model deployment name that the agent uses.')
param modelDeploymentName string = 'gpt-5.4-mini'

@description('Model name.')
param modelName string = 'gpt-5.4-mini'

@description('Model version.')
param modelVersion string = '2026-03-17'

@description('Model deployment SKU.')
param modelSkuName string = 'GlobalStandard'

@description('Model capacity in thousands of tokens per minute. MCP tool definitions are large (ZoomInfo adds about 35K input tokens per request), so 10 is too low.')
param modelCapacity int = 100

@description('API Management service name. Must be globally unique.')
param apimName string = '${namePrefix}-apim-${take(uniqueString(resourceGroup().id), 8)}'

@allowed([
  'Developer'
  'BasicV2'
  'StandardV2'
  'Premium'
])
@description('API Management SKU. Developer has no SLA; use a production SKU for production.')
param apimSku string = 'Developer'

@description('Publisher email for API Management notifications.')
param apimPublisherEmail string

@description('Publisher name shown in API Management.')
param apimPublisherName string = 'MCP Gateway'

@description('Deploy GitHub MCP: an APIM passthrough and a Foundry OAuth connection. See docs/github-setup.md.')
param enableGitHub bool = false

@description('Client ID of the GitHub App that users authorize. If empty, the connection is created with placeholders so you can get its callback URL first.')
param githubAppClientId string = ''

@secure()
@description('Client secret of the GitHub App. Pass it at deployment time and never store it in source control. Once the app exists, pass it on every deployment; an empty value resets the connection to placeholders.')
param githubAppClientSecret string = ''

@description('Name of the Foundry OAuth connection for GitHub. Must be unique within the Foundry account. Changing it signs every user out.')
param githubConnectionName string = 'github-mcp-oauth'

@description('OAuth scopes requested during sign-in. GitHub App permissions, not scopes, limit access.')
param githubScopes array = [
  'read:user'
]

@description('GitHub MCP toolsets that API Management enforces for every agent.')
param githubToolsets string = 'context,repos,issues,pull_requests,actions'

@description('Force GitHub MCP read-only mode for every agent.')
param githubReadOnly bool = true

@description('Deploy ZoomInfo MCP: an APIM passthrough and a Foundry OAuth connection. See docs/zoominfo-setup.md.')
param enableZoomInfo bool = false

@description('Client ID of the ZoomInfo MCP app. If empty, the connection is created with placeholders so you can get its callback URL first.')
param zoominfoClientId string = ''

@secure()
@description('Client secret of the ZoomInfo MCP app. Once the app exists, pass it on every deployment; an empty value resets the connection to placeholders.')
param zoominfoClientSecret string = ''

@description('Name of the Foundry OAuth connection for ZoomInfo. Must be unique within the Foundry account. Changing it signs every user out.')
param zoominfoConnectionName string = 'zoominfo-mcp-oauth'

@description('OAuth scopes requested during ZoomInfo sign-in.')
param zoominfoScopes array = [
  'openid'
  'profile'
  'email'
  'offline_access'
  'zi_mcp'
  'api:data:mcp'
]

@description('Object IDs of users or groups that build and test agents (Foundry User role on the project).')
param developerPrincipalIds array = []

@description('Object IDs of users or groups that only chat with agents (Foundry Agent Consumer role on the project).')
param agentConsumerPrincipalIds array = []

var foundryUserRoleId = '53ca6127-db72-4b80-b1b0-d745d6d5456d'
var foundryAgentConsumerRoleId = 'eed3b665-ab3a-47b6-8f48-c9382fb1dad6'

// ---------------------------------------------------------------------------
// Foundry
// ---------------------------------------------------------------------------
resource account 'Microsoft.CognitiveServices/accounts@2025-06-01' = {
  name: foundryAccountName
  location: location
  kind: 'AIServices'
  sku: {
    name: 'S0'
  }
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    customSubDomainName: foundryAccountName
    allowProjectManagement: true
    publicNetworkAccess: 'Enabled'
    // Require Microsoft Entra ID; API keys stay disabled.
    disableLocalAuth: true
  }
}

resource project 'Microsoft.CognitiveServices/accounts/projects@2025-06-01' = {
  parent: account
  name: projectName
  location: location
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    displayName: projectName
    description: 'Prompt agents that call MCP servers as the signed-in user.'
  }
}

resource modelDeployment 'Microsoft.CognitiveServices/accounts/deployments@2025-06-01' = {
  parent: account
  name: modelDeploymentName
  sku: {
    name: modelSkuName
    capacity: modelCapacity
  }
  properties: {
    model: {
      format: 'OpenAI'
      name: modelName
      version: modelVersion
    }
  }
  // The account accepts one child operation at a time.
  dependsOn: [
    project
  ]
}

// ---------------------------------------------------------------------------
// API Management
// ---------------------------------------------------------------------------
resource apim 'Microsoft.ApiManagement/service@2024-05-01' = {
  name: apimName
  location: location
  sku: {
    name: apimSku
    capacity: 1
  }
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    publisherEmail: apimPublisherEmail
    publisherName: apimPublisherName
  }
}

// ---------------------------------------------------------------------------
// MCP servers. Each one gets an APIM passthrough and a Foundry OAuth
// connection; Foundry stores each user's token after that user's first
// sign-in and sends it with every MCP call. A connection is created with
// placeholder credentials until the app credentials are passed, so its
// callback URL can be registered first. Redeploying with the real
// credentials updates it in place and keeps the same callback URL.
// ---------------------------------------------------------------------------
var placeholderCredential = 'pending-registration'

// GitHub
var githubRegistered = !empty(githubAppClientId) && !empty(githubAppClientSecret)
var githubPolicy = replace(
  replace(loadTextContent('policies/github-mcp.xml'), '__GITHUB_TOOLSETS__', githubToolsets),
  '__GITHUB_READONLY__',
  githubReadOnly ? 'true' : 'false'
)

module githubMcp 'modules/apim-mcp-passthrough.bicep' = if (enableGitHub) {
  name: 'github-mcp-passthrough'
  params: {
    apimName: apim.name
    apiName: 'github-mcp'
    displayName: 'GitHub MCP (per-user OAuth passthrough)'
    apiPath: 'github-mcp'
    backendUrl: 'https://api.githubcopilot.com'
    policyXml: githubPolicy
  }
}

resource githubConnection 'Microsoft.CognitiveServices/accounts/projects/connections@2025-06-01' = if (enableGitHub) {
  parent: project
  name: githubConnectionName
  properties: any({
    authType: 'OAuth2'
    category: 'RemoteTool'
    target: githubMcp!.outputs.mcpUrl
    credentials: {
      clientId: githubRegistered ? githubAppClientId : placeholderCredential
      clientSecret: githubRegistered ? githubAppClientSecret : placeholderCredential
    }
    authorizationUrl: 'https://github.com/login/oauth/authorize'
    tokenUrl: 'https://github.com/login/oauth/access_token'
    refreshUrl: 'https://github.com/login/oauth/access_token'
    scopes: githubScopes
    isSharedToAll: false
    peRequirement: 'NotRequired'
  })
}

// ZoomInfo
var zoominfoRegistered = !empty(zoominfoClientId) && !empty(zoominfoClientSecret)

module zoominfoMcp 'modules/apim-mcp-passthrough.bicep' = if (enableZoomInfo) {
  name: 'zoominfo-mcp-passthrough'
  params: {
    apimName: apim.name
    apiName: 'zoominfo-mcp'
    displayName: 'ZoomInfo MCP (per-user OAuth passthrough)'
    apiPath: 'zoominfo-mcp'
    backendUrl: 'https://mcp.zoominfo.com'
    policyXml: loadTextContent('policies/zoominfo-mcp.xml')
  }
}

resource zoominfoConnection 'Microsoft.CognitiveServices/accounts/projects/connections@2025-06-01' = if (enableZoomInfo) {
  parent: project
  name: zoominfoConnectionName
  // A new project's first OAuth connection provisions a shared connector
  // gateway; creating two OAuth connections in parallel conflicts.
  dependsOn: [
    githubConnection
  ]
  properties: any({
    authType: 'OAuth2'
    category: 'RemoteTool'
    target: zoominfoMcp!.outputs.mcpUrl
    credentials: {
      clientId: zoominfoRegistered ? zoominfoClientId : placeholderCredential
      clientSecret: zoominfoRegistered ? zoominfoClientSecret : placeholderCredential
    }
    // ZoomInfo requires PKCE (S256), which Foundry's OAuth sign-in sends.
    authorizationUrl: 'https://mcp.zoominfo.com/oauth/authorize'
    tokenUrl: 'https://okta-login.zoominfo.com/oauth2/default/v1/token'
    refreshUrl: 'https://okta-login.zoominfo.com/oauth2/default/v1/token'
    scopes: zoominfoScopes
    isSharedToAll: false
    peRequirement: 'NotRequired'
  })
}

// ---------------------------------------------------------------------------
// Foundry roles on the project
// ---------------------------------------------------------------------------
resource developerRoles 'Microsoft.Authorization/roleAssignments@2022-04-01' = [
  for principalId in developerPrincipalIds: {
    scope: project
    name: guid(project.id, principalId, foundryUserRoleId)
    properties: {
      roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', foundryUserRoleId)
      principalId: principalId
    }
  }
]

resource consumerRoles 'Microsoft.Authorization/roleAssignments@2022-04-01' = [
  for principalId in agentConsumerPrincipalIds: {
    scope: project
    name: guid(project.id, principalId, foundryAgentConsumerRoleId)
    properties: {
      roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', foundryAgentConsumerRoleId)
      principalId: principalId
    }
  }
]

output foundryAccountName string = account.name
output projectName string = project.name
output projectEndpoint string = 'https://${account.name}.services.ai.azure.com/api/projects/${project.name}'
output modelDeploymentName string = modelDeployment.name
output apimName string = apim.name
output githubMcpUrl string = enableGitHub ? githubMcp!.outputs.mcpUrl : ''
output githubConnectionId string = enableGitHub ? githubConnection.id : ''
@description('Add this URL to the GitHub App as a callback URL.')
output githubOAuthRedirectUrl string = enableGitHub ? any(githubConnection!.properties).redirectUrl : ''
@description('False until the GitHub App credentials are passed. Users cannot sign in to GitHub while this is false.')
output githubRegistered bool = enableGitHub && githubRegistered
output zoominfoMcpUrl string = enableZoomInfo ? zoominfoMcp!.outputs.mcpUrl : ''
output zoominfoConnectionId string = enableZoomInfo ? zoominfoConnection.id : ''
@description('Register this URL as a redirect URI on the ZoomInfo MCP app.')
output zoominfoOAuthRedirectUrl string = enableZoomInfo ? any(zoominfoConnection!.properties).redirectUrl : ''
@description('False until the ZoomInfo app credentials are passed. Users cannot sign in to ZoomInfo while this is false.')
output zoominfoRegistered bool = enableZoomInfo && zoominfoRegistered
