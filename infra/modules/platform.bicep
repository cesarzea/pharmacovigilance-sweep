// Platform pieces around Foundry: container registry, the runner's identity and role assignments.
//
// - The Foundry project's managed identity pulls the agent image from the registry.
// - The runner identity (used later by the Container Apps job) can call models and invoke agents.

param location string
param tags object
param registryName string
param runnerIdentityName string
@description('Resource id of the Foundry account (role assignment scope for the runner).')
param foundryAccountId string
@description('Principal id of the Foundry project managed identity (pulls the agent image).')
param foundryProjectPrincipalId string

// AcrPull rather than "Container Registry Repository Reader": the repository-scoped role only takes
// effect on registries in "RBAC Registry + ABAC Repository Permissions" mode; AcrPull works in the
// default mode. The hosted agent docs accept either.
var acrPullRoleId = '7f951dda-4ed3-4680-a7ca-43fe172d538d'
var cognitiveServicesUserRoleId = 'a97b65f3-24c7-4388-baec-2e87135dc908'
var azureAiUserRoleId = '53ca6127-db72-4b80-b1b0-d745d6d5456d'

resource registry 'Microsoft.ContainerRegistry/registries@2023-11-01-preview' = {
  name: registryName
  location: location
  tags: tags
  sku: { name: 'Basic' }
  properties: {
    adminUserEnabled: false
    publicNetworkAccess: 'Enabled'
    policies: {
      // Required for the Foundry project identity to pull with Entra ID.
      azureADAuthenticationAsArmPolicy: { status: 'enabled' }
    }
  }
}

resource runnerIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: runnerIdentityName
  location: location
  tags: tags
}

resource projectPullsImages 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(registry.id, foundryProjectPrincipalId, acrPullRoleId)
  scope: registry
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', acrPullRoleId)
    principalId: foundryProjectPrincipalId
    principalType: 'ServicePrincipal'
  }
}

resource foundryAccount 'Microsoft.CognitiveServices/accounts@2025-10-01-preview' existing = {
  name: last(split(foundryAccountId, '/'))
}

resource runnerInference 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(foundryAccountId, runnerIdentity.id, cognitiveServicesUserRoleId)
  scope: foundryAccount
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', cognitiveServicesUserRoleId)
    principalId: runnerIdentity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

resource runnerProject 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(foundryAccountId, runnerIdentity.id, azureAiUserRoleId)
  scope: foundryAccount
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', azureAiUserRoleId)
    principalId: runnerIdentity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

output registryName string = registry.name
output registryLoginServer string = registry.properties.loginServer
output runnerIdentityId string = runnerIdentity.id
output runnerIdentityClientId string = runnerIdentity.properties.clientId
