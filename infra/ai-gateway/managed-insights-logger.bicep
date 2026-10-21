targetScope = 'resourceGroup'

@description('Existing APIM with system-assigned identity. Requires separately approved telemetry role assignment.')
@minLength(1)
param apimName string

@description('Existing workspace-based, Entra-only Application Insights resource in this resource group.')
@minLength(1)
param applicationInsightsName string

resource apim 'Microsoft.ApiManagement/service@2024-05-01' existing = {
  name: apimName
}

resource insights 'Microsoft.Insights/components@2020-02-02' existing = {
  name: applicationInsightsName
}

resource telemetryPublisher 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(insights.id, apim.id, 'Monitoring Metrics Publisher')
  scope: insights
  properties: {
    principalId: apim.identity.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '3913510d-42f4-4e42-8a64-420c390055eb')
  }
}

resource logger 'Microsoft.ApiManagement/service/loggers@2024-05-01' = {
  parent: apim
  name: 'documentation-managed-insights'
  properties: {
    loggerType: 'applicationInsights'
    description: 'Existing Application Insights destination; Entra ingestion as APIM system-assigned identity.'
    resourceId: insights.id
    credentials: {
      connectionString: insights.properties.ConnectionString
      identityClientId: 'SystemAssigned'
    }
  }
  dependsOn: [telemetryPublisher]
}

output loggerResourceId string = logger.id
