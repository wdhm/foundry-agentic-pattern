targetScope = 'resourceGroup'

@allowed(['swedencentral'])
param location string = 'swedencentral'

var accountName = 'foundry-eval-ci-r8n3ld'
var projectName = 'evaluation-ci'
var identityName = 'id-gh-isolated-eval'

var tags = {
  purpose: 'isolated-supplied-source-evaluation'
  repository: 'wdhm/foundry-agentic-pattern'
  production: 'false'
}

resource account 'Microsoft.CognitiveServices/accounts@2025-10-01-preview' = {
  name: accountName
  location: location
  kind: 'AIServices'
  sku: { name: 'S0' }
  identity: { type: 'SystemAssigned' }
  tags: tags
  properties: {
    allowProjectManagement: true
    customSubDomainName: accountName
    disableLocalAuth: true
    publicNetworkAccess: 'Enabled'
    dynamicThrottlingEnabled: false
  }
}

resource project 'Microsoft.CognitiveServices/accounts/projects@2025-10-01-preview' = {
  parent: account
  name: projectName
  location: location
  identity: { type: 'SystemAssigned' }
  tags: tags
  properties: {
    displayName: 'Isolated evaluation CI'
    description: 'Three supplied-source cases only; no toolbox, connections, agents or source credentials.'
  }
}

@batchSize(1)
resource models 'Microsoft.CognitiveServices/accounts/deployments@2025-10-01-preview' = [for model in [
  { name: 'eval-candidate', capacity: 50 }
  { name: 'eval-judge', capacity: 50 }
  { name: 'eval-optimizer', capacity: 10 }
]: {
  parent: account
  name: model.name
  dependsOn: [project]
  sku: { name: 'GlobalStandard', capacity: model.capacity }
  properties: {
    model: { format: 'OpenAI', name: 'gpt-5.4-mini', version: '2026-03-17' }
    versionUpgradeOption: 'NoAutoUpgrade'
    raiPolicyName: 'Microsoft.DefaultV2'
  }
}]

resource fullCandidate 'Microsoft.CognitiveServices/accounts/deployments@2025-10-01-preview' = {
  parent: account
  name: 'eval-candidate-full'
  dependsOn: [models]
  sku: { name: 'GlobalStandard', capacity: 50 }
  properties: {
    model: { format: 'OpenAI', name: 'gpt-5.4', version: '2026-03-05' }
    versionUpgradeOption: 'NoAutoUpgrade'
    raiPolicyName: 'Microsoft.DefaultV2'
  }
}

resource identity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: identityName
  location: location
  tags: tags
}

resource federation 'Microsoft.ManagedIdentity/userAssignedIdentities/federatedIdentityCredentials@2023-01-31' = {
  parent: identity
  name: 'github-isolated-evaluation'
  properties: {
    issuer: 'https://token.actions.githubusercontent.com'
    audiences: ['api://AzureADTokenExchange']
    subject: 'repo:wdhm@253040606/foundry-agentic-pattern@1407061088:environment:isolated-agent-evaluation'
  }
}

var inferenceDataActions = [
  'Microsoft.CognitiveServices/accounts/OpenAI/deployments/read'
  'Microsoft.CognitiveServices/accounts/AIServices/deployments/read'
  'Microsoft.CognitiveServices/accounts/OpenAI/responses/write'
  'Microsoft.CognitiveServices/accounts/OpenAI/responses/read'
  'Microsoft.CognitiveServices/accounts/AIServices/responses/write'
  'Microsoft.CognitiveServices/accounts/AIServices/responses/read'
  'Microsoft.CognitiveServices/accounts/OpenAI/deployments/chat/completions/action'
]

resource runnerRole 'Microsoft.Authorization/roleDefinitions@2022-04-01' = {
  name: guid(resourceGroup().id, 'isolated-eval-runner')
  properties: {
    roleName: 'Isolated Evaluation CI Runner ${uniqueString(resourceGroup().id)}'
    description: 'Only inference, model metadata and eval read/write; no keys, connections, agents, deployment or RBAC writes.'
    type: 'CustomRole'
    assignableScopes: [resourceGroup().id]
    permissions: [{
      actions: [
        'Microsoft.CognitiveServices/accounts/read'
        'Microsoft.CognitiveServices/accounts/projects/read'
        'Microsoft.CognitiveServices/accounts/deployments/read'
      ]
      notActions: []
      dataActions: concat(inferenceDataActions, [
        'Microsoft.CognitiveServices/accounts/OpenAI/evals/read'
        'Microsoft.CognitiveServices/accounts/OpenAI/evals/write'
        'Microsoft.CognitiveServices/accounts/AIServices/evaluations/read'
        'Microsoft.CognitiveServices/accounts/AIServices/evaluations/write'
      ])
      notDataActions: []
    }]
  }
}

resource modelRole 'Microsoft.Authorization/roleDefinitions@2022-04-01' = {
  name: guid(resourceGroup().id, 'isolated-eval-model-inference')
  properties: {
    roleName: 'Isolated Evaluation Model Inference ${uniqueString(resourceGroup().id)}'
    description: 'Inference only for the isolated project identity; no source access.'
    type: 'CustomRole'
    assignableScopes: [resourceGroup().id]
    permissions: [{
      actions: ['Microsoft.CognitiveServices/accounts/deployments/read']
      notActions: []
      dataActions: inferenceDataActions
      notDataActions: []
    }]
  }
}

resource runnerAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: account
  name: guid(account.id, identity.id, runnerRole.id)
  properties: {
    principalId: identity.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: runnerRole.id
  }
}

resource projectAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: account
  name: guid(account.id, project.id, modelRole.id)
  properties: {
    principalId: project.identity.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: modelRole.id
  }
}

resource runnerProjectStorageRole 'Microsoft.Authorization/roleDefinitions@2022-04-01' = {
  name: guid(resourceGroup().id, 'isolated-eval-project-storage')
  properties: {
    roleName: 'Isolated Evaluation Project Storage ${uniqueString(resourceGroup().id)}'
    description: 'Documented project inference prerequisite hypothesis; child read/write patterns exceed storage only.'
    type: 'CustomRole'
    assignableScopes: [resourceGroup().id]
    permissions: [{
      actions: []
      notActions: []
      dataActions: [
        'Microsoft.CognitiveServices/accounts/AIServices/agents/*/read'
        'Microsoft.CognitiveServices/accounts/AIServices/agents/*/write'
      ]
      notDataActions: []
    }]
  }
}

resource runnerProjectStorageAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: project
  name: guid(project.id, identity.id, runnerProjectStorageRole.id)
  properties: {
    principalId: identity.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: runnerProjectStorageRole.id
  }
}

resource runnerEvaluationAssetsRole 'Microsoft.Authorization/roleDefinitions@2022-04-01' = {
  name: guid(resourceGroup().id, 'isolated-eval-project-assets')
  properties: {
    roleName: 'Isolated Evaluation Project Assets ${uniqueString(resourceGroup().id)}'
    description: 'Create evaluation definition assets in the isolated project; generic asset-version write also covers other asset types.'
    type: 'CustomRole'
    assignableScopes: [resourceGroup().id]
    permissions: [{
      actions: []
      notActions: []
      dataActions: [
        'Microsoft.CognitiveServices/accounts/AIServices/assets/write'
      ]
      notDataActions: []
    }]
  }
}

resource runnerEvaluationAssetsAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: project
  name: guid(project.id, identity.id, runnerEvaluationAssetsRole.id)
  properties: {
    principalId: identity.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: runnerEvaluationAssetsRole.id
  }
}

output projectEndpoint string = 'https://${accountName}.services.ai.azure.com/api/projects/${projectName}'
output accountResourceId string = account.id
output projectResourceId string = project.id
output runnerClientId string = identity.properties.clientId
output runnerPrincipalId string = identity.properties.principalId
output projectPrincipalId string = project.identity.principalId
output tenantId string = tenant().tenantId
