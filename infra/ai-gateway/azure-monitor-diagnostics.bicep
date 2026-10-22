targetScope = 'resourceGroup'

@description('Existing, separately provisioned APIM instance. Creates its credential-free Azure Monitor logger and default-deny policy.')
@minLength(1)
param apimName string

@description('Existing Log Analytics workspace in this resource group; no new workspace or ingestion role grant.')
@minLength(1)
param logAnalyticsWorkspaceName string

resource apim 'Microsoft.ApiManagement/service@2024-05-01' existing = {
  name: apimName
}

resource workspace 'Microsoft.OperationalInsights/workspaces@2023-09-01' existing = {
  name: logAnalyticsWorkspaceName
}

resource defaultDeny 'Microsoft.ApiManagement/service/policies@2024-05-01' = {
  parent: apim
  name: 'policy'
  properties: {
    format: 'rawxml'
    value: '''
<policies>
  <inbound>
    <return-response>
      <set-status code="403" reason="Gateway route not enabled" />
    </return-response>
  </inbound>
  <backend />
  <outbound />
  <on-error />
</policies>
'''
  }
}

resource monitorLogger 'Microsoft.ApiManagement/service/loggers@2024-05-01' = {
  parent: apim
  name: 'azuremonitor'
  properties: {
    loggerType: 'azureMonitor'
    description: 'Credential-free Azure Monitor gateway diagnostics.'
  }
  dependsOn: [defaultDeny]
}

resource gatewayLogs 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = {
  scope: apim
  name: 'documentation-gateway-logs'
  properties: {
    workspaceId: workspace.id
    logAnalyticsDestinationType: 'Dedicated'
    logs: [
      {
        category: 'GatewayLogs'
        enabled: true
      }
    ]
    metrics: []
  }
  dependsOn: [defaultDeny]
}

resource monitorDefaults 'Microsoft.ApiManagement/service/diagnostics@2024-05-01' = {
  parent: apim
  name: 'azuremonitor'
  properties: {
    loggerId: monitorLogger.id
    alwaysLog: 'allErrors'
    logClientIp: false
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
  dependsOn: [gatewayLogs]
}

output loggerResourceId string = monitorLogger.id
