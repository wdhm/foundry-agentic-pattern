targetScope = 'resourceGroup'

@description('Existing, separately provisioned APIM instance. Uses its built-in azuremonitor logger.')
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

var monitorLoggerId = resourceId('Microsoft.ApiManagement/service/loggers', apimName, 'azuremonitor')

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
}

resource monitorDefaults 'Microsoft.ApiManagement/service/diagnostics@2024-05-01' = {
  parent: apim
  name: 'azuremonitor'
  properties: {
    loggerId: monitorLoggerId
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

output loggerResourceId string = monitorLoggerId
