// Microsoft Foundry resource, project and model deployments for Pharmacovigilance Sweep.
//
// Claude deployments carry modelProviderData: the Cognitive Services resource provider uses it to
// accept the Azure Marketplace offer for Anthropic Claude, so no manual click-through is needed.
// Model version '2' selects the "Hosted on Azure" variant (see docs/architecture.md, section 3).

param location string
param tags object
param accountName string
param projectName string

@description('Small Claude model (screening, extraction). Empty string skips it.')
param claudeSmallModel string = 'claude-haiku-5-5'
@description('Large Claude model (matching agent). Empty string skips it.')
param claudeLargeModel string = ''
@description('Small GPT model, deployed as EU Data Zone Standard. Empty string skips it.')
param gptSmallModel string = 'gpt-5.4-mini'
@description('Large GPT model, deployed as EU Data Zone Standard. Empty string skips it.')
param gptLargeModel string = ''

@description('Capacity in thousands of tokens per minute, per deployment.')
param smallCapacity int = 10
param largeCapacity int = 10

@description('"2" = Hosted on Azure, "1" = Hosted on Anthropic infrastructure.')
param claudeModelVersion string = '2'

param claudeOrganizationName string
param claudeCountryCode string
param claudeIndustry string

@description('Object id of the engineer who runs the spike; gets inference and project rights.')
param principalId string = ''

// Cognitive Services User: data actions for inference on the account.
var cognitiveServicesUserRoleId = 'a97b65f3-24c7-4388-baec-2e87135dc908'
// Azure AI User: project-level data plane (agents, evaluations, connections).
var azureAiUserRoleId = '53ca6127-db72-4b80-b1b0-d745d6d5456d'

resource account 'Microsoft.CognitiveServices/accounts@2025-10-01-preview' = {
  name: accountName
  location: location
  tags: tags
  kind: 'AIServices'
  sku: { name: 'S0' }
  identity: { type: 'SystemAssigned' }
  properties: {
    customSubDomainName: accountName
    allowProjectManagement: true
    publicNetworkAccess: 'Enabled'
    // Entra ID only: no API keys exist for this resource.
    disableLocalAuth: true
  }
}

resource project 'Microsoft.CognitiveServices/accounts/projects@2025-10-01-preview' = {
  parent: account
  name: projectName
  location: location
  tags: tags
  identity: { type: 'SystemAssigned' }
  properties: {}
}

resource inferenceRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(principalId)) {
  name: guid(account.id, principalId, cognitiveServicesUserRoleId)
  scope: account
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', cognitiveServicesUserRoleId)
    principalId: principalId
    principalType: 'User'
  }
}

resource projectRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(principalId)) {
  name: guid(account.id, principalId, azureAiUserRoleId)
  scope: account
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', azureAiUserRoleId)
    principalId: principalId
    principalType: 'User'
  }
}

// Deployments are chained with dependsOn: Foundry serialises them per account and returns 409 on
// concurrent creates.

resource claudeSmall 'Microsoft.CognitiveServices/accounts/deployments@2025-10-01-preview' = if (!empty(claudeSmallModel)) {
  parent: account
  name: claudeSmallModel
  sku: { name: 'GlobalStandard', capacity: smallCapacity }
  properties: {
    model: { format: 'Anthropic', name: claudeSmallModel, version: claudeModelVersion }
    modelProviderData: {
      organizationName: claudeOrganizationName
      countryCode: claudeCountryCode
      industry: claudeIndustry
    }
    versionUpgradeOption: 'NoAutoUpgrade'
    raiPolicyName: 'Microsoft.DefaultV2'
  }
  dependsOn: [project]
}

resource claudeLarge 'Microsoft.CognitiveServices/accounts/deployments@2025-10-01-preview' = if (!empty(claudeLargeModel)) {
  parent: account
  name: claudeLargeModel
  sku: { name: 'GlobalStandard', capacity: largeCapacity }
  properties: {
    model: { format: 'Anthropic', name: claudeLargeModel, version: claudeModelVersion }
    modelProviderData: {
      organizationName: claudeOrganizationName
      countryCode: claudeCountryCode
      industry: claudeIndustry
    }
    versionUpgradeOption: 'NoAutoUpgrade'
    raiPolicyName: 'Microsoft.DefaultV2'
  }
  dependsOn: [project, claudeSmall]
}

resource gptSmall 'Microsoft.CognitiveServices/accounts/deployments@2025-10-01-preview' = if (!empty(gptSmallModel)) {
  parent: account
  name: replace(gptSmallModel, '.', '-')
  sku: { name: 'DataZoneStandard', capacity: smallCapacity }
  properties: {
    model: { format: 'OpenAI', name: gptSmallModel }
    versionUpgradeOption: 'NoAutoUpgrade'
    raiPolicyName: 'Microsoft.DefaultV2'
  }
  dependsOn: [project, claudeSmall, claudeLarge]
}

resource gptLarge 'Microsoft.CognitiveServices/accounts/deployments@2025-10-01-preview' = if (!empty(gptLargeModel)) {
  parent: account
  name: replace(gptLargeModel, '.', '-')
  sku: { name: 'DataZoneStandard', capacity: largeCapacity }
  properties: {
    model: { format: 'OpenAI', name: gptLargeModel }
    versionUpgradeOption: 'NoAutoUpgrade'
    raiPolicyName: 'Microsoft.DefaultV2'
  }
  dependsOn: [project, gptSmall]
}

output accountName string = account.name
output accountId string = account.id
output projectName string = project.name
output projectPrincipalId string = project.identity.principalId
output anthropicBaseUrl string = 'https://${account.name}.services.ai.azure.com/anthropic'
output openaiBaseUrl string = 'https://${account.name}.services.ai.azure.com/openai/v1'
output projectEndpoint string = 'https://${account.name}.services.ai.azure.com/api/projects/${project.name}'
output claudeSmallDeployment string = claudeSmallModel
output claudeLargeDeployment string = claudeLargeModel
output gptSmallDeployment string = empty(gptSmallModel) ? '' : replace(gptSmallModel, '.', '-')
output gptLargeDeployment string = empty(gptLargeModel) ? '' : replace(gptLargeModel, '.', '-')
