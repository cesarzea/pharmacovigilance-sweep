// Pharmacovigilance Sweep: subscription-scope entry point.
//
//   az deployment sub create -l swedencentral -f infra/main.bicep -p @infra/main.parameters.local.json
//
// Creates the resource group, a monthly cost budget with alerts, and the Foundry module.
// Spike scope (docs/architecture.md, section 17): Foundry and small models only. Container Apps,
// Key Vault, registry and hosted agents are added by later modules.

targetScope = 'subscription'

@description('Short environment name, used in resource names.')
@minLength(2)
@maxLength(8)
param environmentName string = 'dev'

@description('Azure region. Sweden Central is the only EU region with Claude on Foundry.')
param location string = 'swedencentral'

@description('Monthly budget in the billing currency; alerts at 80 % actual and 100 % forecast.')
param monthlyBudget int = 50
@description('First day of the current month, yyyy-MM-01.')
param budgetStartDate string
@description('Who receives budget alerts. Keep in the local parameters file, not in the repo.')
param budgetContactEmails array

param claudeOrganizationName string
param claudeCountryCode string
param claudeIndustry string

@description('Object id of the engineer running the deployment, for RBAC on the Foundry resource.')
param principalId string = ''

param claudeSmallModel string = 'claude-haiku-5-5'
param claudeLargeModel string = ''
param gptSmallModel string = 'gpt-5.4-mini'
param gptLargeModel string = ''

var baseName = 'pvsweep-${environmentName}'
var suffix = take(uniqueString(subscription().id, baseName), 6)
var tags = {
  project: 'pharmacovigilance-sweep'
  environment: environmentName
}

resource rg 'Microsoft.Resources/resourceGroups@2024-03-01' = {
  name: 'rg-${baseName}'
  location: location
  tags: tags
}

resource budget 'Microsoft.Consumption/budgets@2023-05-01' = {
  name: 'budget-${baseName}'
  properties: {
    category: 'Cost'
    amount: monthlyBudget
    timeGrain: 'Monthly'
    timePeriod: { startDate: budgetStartDate }
    filter: {
      dimensions: {
        name: 'ResourceGroupName'
        operator: 'In'
        values: [rg.name]
      }
    }
    notifications: {
      actual80: {
        enabled: true
        operator: 'GreaterThan'
        threshold: 80
        thresholdType: 'Actual'
        contactEmails: budgetContactEmails
      }
      forecast100: {
        enabled: true
        operator: 'GreaterThanOrEqualTo'
        threshold: 100
        thresholdType: 'Forecasted'
        contactEmails: budgetContactEmails
      }
    }
  }
}

module foundry 'modules/foundry.bicep' = {
  name: 'foundry'
  scope: rg
  params: {
    location: location
    tags: tags
    accountName: 'aif-${baseName}-${suffix}'
    projectName: 'proj-${baseName}'
    claudeSmallModel: claudeSmallModel
    claudeLargeModel: claudeLargeModel
    gptSmallModel: gptSmallModel
    gptLargeModel: gptLargeModel
    claudeOrganizationName: claudeOrganizationName
    claudeCountryCode: claudeCountryCode
    claudeIndustry: claudeIndustry
    principalId: principalId
  }
}

module platform 'modules/platform.bicep' = {
  name: 'platform'
  scope: rg
  params: {
    location: location
    tags: tags
    registryName: replace('cr${baseName}${suffix}', '-', '')
    runnerIdentityName: 'id-${baseName}-runner'
    foundryAccountId: foundry.outputs.accountId
    foundryProjectPrincipalId: foundry.outputs.projectPrincipalId
  }
}

output resourceGroup string = rg.name
output foundryAccountName string = foundry.outputs.accountName
output foundryProjectName string = foundry.outputs.projectName
output registryName string = platform.outputs.registryName
output registryLoginServer string = platform.outputs.registryLoginServer
output runnerIdentityClientId string = platform.outputs.runnerIdentityClientId
output anthropicBaseUrl string = foundry.outputs.anthropicBaseUrl
output openaiBaseUrl string = foundry.outputs.openaiBaseUrl
output projectEndpoint string = foundry.outputs.projectEndpoint
output claudeSmallDeployment string = foundry.outputs.claudeSmallDeployment
output gptSmallDeployment string = foundry.outputs.gptSmallDeployment
