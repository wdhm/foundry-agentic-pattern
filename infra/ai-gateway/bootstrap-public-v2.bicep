targetScope = 'resourceGroup'

@description('New paid Basic v2 instance; never use the existing classic Developer name.')
@minLength(1)
param apimName string

@description('Explicit approved Basic v2 region; check current regional capacity before deployment.')
@minLength(1)
param location string

@description('Operator-provided publisher organization/contact, stored in ignored live parameters.')
@minLength(1)
param publisherName string

@minLength(1)
param publisherEmail string

@description('Existing Log Analytics workspace in this resource group.')
@minLength(1)
param logAnalyticsWorkspaceName string

resource apim 'Microsoft.ApiManagement/service@2024-05-01' = {
  name: apimName
  location: location
  sku: { name: 'BasicV2', capacity: 1 }
  identity: { type: 'SystemAssigned' }
  properties: {
    publisherName: publisherName
    publisherEmail: publisherEmail
    virtualNetworkType: 'None'
    publicNetworkAccess: 'Enabled'
    developerPortalStatus: 'Disabled'
    customProperties: {
      'Microsoft.WindowsAzure.ApiManagement.Gateway.Security.Protocols.Tls10': 'false'
      'Microsoft.WindowsAzure.ApiManagement.Gateway.Security.Protocols.Tls11': 'false'
      'Microsoft.WindowsAzure.ApiManagement.Gateway.Security.Protocols.Ssl30': 'false'
      'Microsoft.WindowsAzure.ApiManagement.Gateway.Security.Backend.Protocols.Tls10': 'false'
      'Microsoft.WindowsAzure.ApiManagement.Gateway.Security.Backend.Protocols.Tls11': 'false'
      'Microsoft.WindowsAzure.ApiManagement.Gateway.Security.Backend.Protocols.Ssl30': 'false'
    }
  }
}

module monitoring './azure-monitor-diagnostics.bicep' = {
  name: '${deployment().name}-monitor'
  params: {
    apimName: apim.name
    logAnalyticsWorkspaceName: logAnalyticsWorkspaceName
  }
  dependsOn: [apim]
}

output apimResourceId string = apim.id
output gatewayUrl string = apim.properties.gatewayUrl
output apimPrincipalId string = apim.identity.principalId
output loggerResourceId string = monitoring.outputs.loggerResourceId
