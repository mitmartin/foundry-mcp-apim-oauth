// ---------------------------------------------------------------------------
// APIM passthrough for a remote MCP server.
//
// The API forwards the caller's Authorization header unchanged, so every
// request runs as the signed-in user. API Management adds governance (policy,
// throttling, logging) without storing user tokens. Deploy one instance of
// this module per MCP server.
// ---------------------------------------------------------------------------

@description('Name of the existing API Management service.')
param apimName string

@description('API identifier in API Management.')
param apiName string

@description('Display name for the API.')
param displayName string

@description('Gateway path. The MCP endpoint is https://<gateway>/<apiPath>/mcp.')
param apiPath string

@description('Base URL of the upstream MCP server.')
param backendUrl string

@description('Policy XML applied to every MCP request.')
param policyXml string

resource apim 'Microsoft.ApiManagement/service@2024-05-01' existing = {
  name: apimName
}

resource api 'Microsoft.ApiManagement/service/apis@2024-05-01' = {
  parent: apim
  name: apiName
  properties: {
    displayName: displayName
    path: apiPath
    protocols: [
      'https'
    ]
    serviceUrl: backendUrl
    // Callers authenticate with their own OAuth token, not an APIM key.
    subscriptionRequired: false
  }
}

// Streamable HTTP MCP uses POST for requests, GET for server streams, and
// DELETE to end a session.
var mcpMethods = [
  'POST'
  'GET'
  'DELETE'
]

resource operations 'Microsoft.ApiManagement/service/apis/operations@2024-05-01' = [
  for method in mcpMethods: {
    parent: api
    name: 'mcp-${toLower(method)}'
    properties: {
      displayName: '${method} MCP'
      method: method
      urlTemplate: '/mcp'
      templateParameters: []
      responses: []
    }
  }
]

resource policy 'Microsoft.ApiManagement/service/apis/policies@2024-05-01' = {
  parent: api
  name: 'policy'
  properties: {
    format: 'rawxml'
    value: policyXml
  }
}

output mcpUrl string = '${apim.properties.gatewayUrl}/${apiPath}/mcp'
