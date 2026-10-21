targetScope = 'resourceGroup'

@description('Existing, separately approved APIM instance. This module creates no service, identity or role grants.')
param apimName string

@description('Foundry project HTTPS endpoint, without trailing slash. Must match the reviewed agent definition.')
param projectEndpoint string

@description('Exact versioned READ-ONLY Toolbox URL, excluding /mcp and query, without trailing slash.')
param readToolboxBaseUrl string

@description('Entra tenant and allowed caller object ID (managed identity in hosted deployments). Not caller headers.')
param tenantId string
param callerObjectId string

@description('Resource ID of an existing, reviewed APIM Application Insights logger. No instrumentation key is accepted here.')
param loggerResourceId string

@description('Existing deployment name. Its concrete model version remains pinned in the reviewed runtime artifact.')
param modelDeployment string

@minValue(1)
param tokensPerMinute int

@minValue(1)
param dailyTokenQuota int

@minValue(1)
param toolRequestsPerMinute int

resource apim 'Microsoft.ApiManagement/service@2024-05-01' existing = {
  name: apimName
}

var settings = {
  'documentation-gateway-tenant': tenantId
  'documentation-gateway-caller': callerObjectId
  'documentation-gateway-token-rate': string(tokensPerMinute)
  'documentation-gateway-token-quota': string(dailyTokenQuota)
  'documentation-gateway-tool-rate': string(toolRequestsPerMinute)
  'documentation-gateway-model-counter': '${apimName}:${projectEndpoint}:${modelDeployment}:model'
  'documentation-gateway-tool-counter': '${apimName}:${readToolboxBaseUrl}:tools'
}

resource namedValues 'Microsoft.ApiManagement/service/namedValues@2024-05-01' = [for setting in items(settings): {
  parent: apim
  name: setting.key
  properties: {
    displayName: setting.key
    value: setting.value
    secret: false
  }
}]

resource modelApi 'Microsoft.ApiManagement/service/apis@2024-05-01' = {
  parent: apim
  name: 'documentation-model'
  properties: {
    displayName: 'Documentation model inference (opt-in)'
    path: 'documentation-model'
    protocols: ['https']
    subscriptionRequired: false
    serviceUrl: '${projectEndpoint}/openai/v1'
    format: 'openapi+json'
    value: string({
      openapi: '3.0.1'
      info: { title: 'Reviewed model Responses API', version: '1.0.0' }
      paths: {
        '/responses': {
          post: {
            operationId: 'createResponse'
            requestBody: {
              required: true
              content: {
                'application/json': {
                  schema: {
                    type: 'object'
                    required: ['model', 'input', 'store']
                    properties: {
                      model: { type: 'string', enum: [modelDeployment] }
                      background: { type: 'boolean', enum: [false] }
                      store: { type: 'boolean', enum: [false] }
                    }
                    additionalProperties: true
                  }
                }
              }
            }
            responses: { '200': { description: 'Responses JSON or SSE stream' } }
          }
        }
      }
    })
  }
}

resource modelPolicy 'Microsoft.ApiManagement/service/apis/policies@2024-05-01' = {
  parent: modelApi
  name: 'policy'
  properties: {
    format: 'rawxml'
    value: loadTextContent('model-policy.xml')
  }
  dependsOn: [namedValues]
}

resource toolApi 'Microsoft.ApiManagement/service/apis@2024-05-01' = {
  parent: apim
  name: 'documentation-tools'
  properties: {
    displayName: 'Version-bound read Toolbox transport (opt-in)'
    path: 'documentation-tools'
    protocols: ['https']
    subscriptionRequired: false
    serviceUrl: readToolboxBaseUrl
  }
}

resource toolOperations 'Microsoft.ApiManagement/service/apis/operations@2024-05-01' = [for method in ['POST', 'GET', 'DELETE']: {
  parent: toolApi
  name: 'mcp-${toLower(method)}'
  properties: {
    displayName: 'MCP ${method}'
    method: method
    urlTemplate: '/mcp'
    templateParameters: []
    responses: []
  }
}]

resource toolPolicy 'Microsoft.ApiManagement/service/apis/policies@2024-05-01' = {
  parent: toolApi
  name: 'policy'
  properties: {
    format: 'rawxml'
    value: loadTextContent('tool-policy.xml')
  }
  dependsOn: [namedValues, toolOperations]
}

resource diagnostics 'Microsoft.ApiManagement/service/apis/diagnostics@2024-05-01' = [for apiName in ['documentation-model', 'documentation-tools']: {
  name: '${apim.name}/${apiName}/applicationinsights'
  properties: {
    loggerId: loggerResourceId
    alwaysLog: 'allErrors'
    logClientIp: false
    httpCorrelationProtocol: 'W3C'
    verbosity: 'error'
    sampling: { samplingType: 'fixed', percentage: 100 }
    frontend: {
      request: { headers: [], body: { bytes: 0 } }
      response: { headers: [], body: { bytes: 0 } }
    }
    backend: {
      request: { headers: [], body: { bytes: 0 } }
      response: { headers: [], body: { bytes: 0 } }
    }
  }
  dependsOn: [modelApi, toolApi]
}]

output modelGatewayEndpoint string = '${apim.properties.gatewayUrl}/documentation-model/'
output toolboxGatewayEndpoint string = '${apim.properties.gatewayUrl}/documentation-tools/mcp?api-version=v1'
