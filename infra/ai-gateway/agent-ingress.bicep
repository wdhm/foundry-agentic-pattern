targetScope = 'resourceGroup'

@description('Existing separately approved APIM instance. Independent of model/tool route installation.')
param apimName string

@description('Reviewed Foundry HTTPS project endpoint, without trailing slash.')
param projectEndpoint string

@description('Fixed hosted assessment agent name, matching the reviewed CLI artifact. Not selected by the caller URL.')
param agentName string

param tenantId string

@description('Allowed CLIENT object ID, not the hosted agent managed identity used for model/tool calls.')
param ingressCallerObjectId string

@description('Resource ID of the existing APIM Application Insights logger.')
param loggerResourceId string

@minValue(1)
param requestsPerMinute int

resource apim 'Microsoft.ApiManagement/service@2024-05-01' existing = {
  name: apimName
}

var settings = {
  'documentation-ingress-tenant': tenantId
  'documentation-ingress-caller': ingressCallerObjectId
  'documentation-ingress-rate': string(requestsPerMinute)
  'documentation-ingress-counter': '${apimName}:${projectEndpoint}:${agentName}:ingress'
}

resource namedValues 'Microsoft.ApiManagement/service/namedValues@2024-05-01' = [for setting in items(settings): {
  parent: apim
  name: setting.key
  properties: { displayName: setting.key, value: setting.value, secret: false }
}]

resource agentApi 'Microsoft.ApiManagement/service/apis@2024-05-01' = {
  parent: apim
  name: 'documentation-agent'
  properties: {
    displayName: 'Version-bound assessment Responses ingress (opt-in)'
    path: 'documentation-agent'
    protocols: ['https']
    subscriptionRequired: false
    serviceUrl: '${projectEndpoint}/agents/${agentName}/endpoint/protocols/openai'
    format: 'openapi+json'
    value: string({
      openapi: '3.0.1'
      info: { title: 'Hosted assessment Responses ingress', version: '1.0.0' }
      paths: {
        '/responses': {
          post: {
            operationId: 'invokeAssessmentSession'
            requestBody: {
              required: true
              content: {
                'application/json': {
                  schema: {
                    type: 'object'
                    required: ['input', 'agent_session_id']
                    properties: {
                      input: { type: 'string' }
                      agent_session_id: { type: 'string', minLength: 1 }
                      stream: { type: 'boolean' }
                      store: { type: 'boolean' }
                    }
                    additionalProperties: false
                  }
                }
              }
            }
            responses: { '200': { description: 'Unmodified hosted Responses JSON or SSE' } }
          }
        }
      }
    })
  }
}

resource policy 'Microsoft.ApiManagement/service/apis/policies@2024-05-01' = {
  parent: agentApi
  name: 'policy'
  properties: { format: 'rawxml', value: loadTextContent('agent-policy.xml') }
  dependsOn: [namedValues]
}

resource diagnostics 'Microsoft.ApiManagement/service/apis/diagnostics@2024-05-01' = {
  parent: agentApi
  name: 'applicationinsights'
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
}

output agentGatewayEndpoint string = '${apim.properties.gatewayUrl}/documentation-agent/'
