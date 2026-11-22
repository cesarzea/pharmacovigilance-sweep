// Pharmacovigilance Sweep: subscription-scope entry point.
//
//   az deployment sub create -l swedencentral -f infra/main.bicep -p @infra/main.parameters.local.json
//
// Creates the resource group, a monthly cost budget with alerts, and the Foundry module.
// Also the platform module (registry, runner identity) and, with deployRunnerJob = true, the runner
// module (Log Analytics, App Insights, Key Vault, Container Apps environment and jobs).

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
@description('Lowercase value from the Anthropic attestation list: technology, finance, healthcare, education, retail, manufacturing, government, media, other. Other spellings make the deployment fail with AnthropicOrganizationCreationFailed.')
@allowed(['technology', 'finance', 'healthcare', 'education', 'retail', 'manufacturing', 'government', 'media', 'other'])
param claudeIndustry string

@description('Object id of the engineer running the deployment, for RBAC on the Foundry resource.')
param principalId string = ''

param claudeSmallModel string = 'claude-haiku-5-5'
param claudeLargeModel string = ''
param gptSmallModel string = 'gpt-5.4-mini'
param gptLargeModel string = ''
param smallCapacity int = 50
param largeCapacity int = 50

@description('Deploy Key Vault, monitoring and the Container Apps jobs (needs the runner image and a Snowflake account).')
param deployRunnerJob bool = false
param runnerImageTag string = 'latest'
@description('With deployRunnerJob: create the Container Apps jobs. False on the first pass, before `make kv-secrets`.')
param deployRunnerJobs bool = true
@description('With deployRunnerJob: also create the data load job.')
param deployLoadJob bool = false
param snowflakeAccount string = ''
@description('PEM private key of the PVSWEEP_AGENT service user, stored in a project connection for the hosted agents. Empty skips the connection.')
@secure()
param snowflakeAgentPrivateKey string = ''

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
    smallCapacity: smallCapacity
    largeCapacity: largeCapacity
    claudeOrganizationName: claudeOrganizationName
    claudeCountryCode: claudeCountryCode
    claudeIndustry: claudeIndustry
    principalId: principalId
  }
}

module connections 'modules/connections.bicep' = if (!empty(snowflakeAgentPrivateKey) && !empty(snowflakeAccount)) {
  name: 'connections'
  scope: rg
  params: {
    accountName: foundry.outputs.accountName
    projectName: foundry.outputs.projectName
    snowflakeAccount: snowflakeAccount
    snowflakeAgentPrivateKey: snowflakeAgentPrivateKey
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

module runner 'modules/runner.bicep' = if (deployRunnerJob) {
  name: 'runner'
  scope: rg
  params: {
    location: location
    tags: tags
    baseName: baseName
    suffix: suffix
    runnerIdentityId: platform.outputs.runnerIdentityId
    runnerIdentityPrincipalId: platform.outputs.runnerIdentityPrincipalId
    runnerIdentityClientId: platform.outputs.runnerIdentityClientId
    registryLoginServer: platform.outputs.registryLoginServer
    runnerImage: '${platform.outputs.registryLoginServer}/pvsweep-runner:${runnerImageTag}'
    principalId: principalId
    foundryAccountName: foundry.outputs.accountName
    foundryProjectEndpoint: foundry.outputs.projectEndpoint
    snowflakeAccount: snowflakeAccount
    gptSmallDeployment: foundry.outputs.gptSmallDeployment
    gptLargeDeployment: foundry.outputs.gptLargeDeployment
    claudeSmallDeployment: foundry.outputs.claudeSmallDeployment
    claudeLargeDeployment: foundry.outputs.claudeLargeDeployment
    deployJobs: deployRunnerJobs
    deployLoadJob: deployLoadJob
  }
}

output resourceGroup string = rg.name
output foundryAccountName string = foundry.outputs.accountName
output foundryAccountId string = foundry.outputs.accountId
output foundryProjectName string = foundry.outputs.projectName
output registryName string = platform.outputs.registryName
output registryLoginServer string = platform.outputs.registryLoginServer
output runnerIdentityClientId string = platform.outputs.runnerIdentityClientId
output keyVaultName string = runner.?outputs.keyVaultName ?? ''
output logAnalyticsWorkspaceId string = runner.?outputs.logAnalyticsWorkspaceId ?? ''
output sweepJobName string = runner.?outputs.sweepJobName ?? ''
output anthropicBaseUrl string = foundry.outputs.anthropicBaseUrl
output openaiBaseUrl string = foundry.outputs.openaiBaseUrl
output projectEndpoint string = foundry.outputs.projectEndpoint
output snowflakeAgentConnection string = connections.?outputs.snowflakeAgentConnection ?? ''
output claudeSmallDeployment string = foundry.outputs.claudeSmallDeployment
output claudeLargeDeployment string = foundry.outputs.claudeLargeDeployment
output gptLargeDeployment string = foundry.outputs.gptLargeDeployment
output gptSmallDeployment string = foundry.outputs.gptSmallDeployment
