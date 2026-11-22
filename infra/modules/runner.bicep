// Runner: Key Vault for the Snowflake key, monitoring, and the Container Apps jobs (load, sweep).
// Deployed when deployRunnerJob = true (needs the runner image in the registry and a Snowflake account).

param location string
param tags object
param baseName string
param suffix string
param runnerIdentityId string
param runnerIdentityPrincipalId string
param runnerIdentityClientId string
param registryLoginServer string
@description('Runner image reference, e.g. <registry>/pvsweep-runner:<tag>.')
param runnerImage string
@description('Object id of the engineer, allowed to write secrets during deployment.')
param principalId string = ''
param foundryAccountName string
param foundryProjectEndpoint string
param snowflakeAccount string
param gptSmallDeployment string
param gptLargeDeployment string
param claudeSmallDeployment string
param claudeLargeDeployment string

var keyVaultSecretsUserRoleId = '4633458b-17de-408a-b874-0445c86b69e6'
var keyVaultSecretsOfficerRoleId = 'b86a8fe4-44ce-4948-aee5-eccb2c155cd7'
var acrPullRoleId = '7f951dda-4ed3-4680-a7ca-43fe172d538d'

resource logs 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: 'log-${baseName}'
  location: location
  tags: tags
  properties: { sku: { name: 'PerGB2018' }, retentionInDays: 30 }
}

resource appInsights 'Microsoft.Insights/components@2020-02-02' = {
  name: 'appi-${baseName}'
  location: location
  tags: tags
  kind: 'web'
  properties: { Application_Type: 'web', WorkspaceResourceId: logs.id }
}

resource keyVault 'Microsoft.KeyVault/vaults@2023-07-01' = {
  name: 'kv-${baseName}-${suffix}'
  location: location
  tags: tags
  properties: {
    sku: { family: 'A', name: 'standard' }
    tenantId: subscription().tenantId
    enableRbacAuthorization: true
    enableSoftDelete: true
    softDeleteRetentionInDays: 7
    publicNetworkAccess: 'Enabled'
  }
}

resource runnerReadsSecrets 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(keyVault.id, runnerIdentityPrincipalId, keyVaultSecretsUserRoleId)
  scope: keyVault
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', keyVaultSecretsUserRoleId)
    principalId: runnerIdentityPrincipalId
    principalType: 'ServicePrincipal'
  }
}

resource engineerWritesSecrets 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(principalId)) {
  name: guid(keyVault.id, principalId, keyVaultSecretsOfficerRoleId)
  scope: keyVault
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', keyVaultSecretsOfficerRoleId)
    principalId: principalId
    principalType: 'User'
  }
}

resource registry 'Microsoft.ContainerRegistry/registries@2023-11-01-preview' existing = {
  name: split(registryLoginServer, '.')[0]
}

resource runnerPullsImages 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(registry.id, runnerIdentityPrincipalId, acrPullRoleId)
  scope: registry
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', acrPullRoleId)
    principalId: runnerIdentityPrincipalId
    principalType: 'ServicePrincipal'
  }
}

resource env 'Microsoft.App/managedEnvironments@2024-03-01' = {
  name: 'cae-${baseName}'
  location: location
  tags: tags
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: { customerId: logs.properties.customerId, sharedKey: logs.listKeys().primarySharedKey }
    }
  }
}

var commonEnv = [
  { name: 'AZURE_CLIENT_ID', value: runnerIdentityClientId }
  { name: 'PVSWEEP_FOUNDRY_ACCOUNT', value: foundryAccountName }
  { name: 'PVSWEEP_PROJECT_ENDPOINT', value: foundryProjectEndpoint }
  { name: 'PVSWEEP_SNOWFLAKE_ACCOUNT', value: snowflakeAccount }
  { name: 'PVSWEEP_SNOWFLAKE_USER', value: 'PVSWEEP_RUNNER' }
  { name: 'PVSWEEP_SNOWFLAKE_PRIVATE_KEY', secretRef: 'snowflake-runner-key' }
  { name: 'PVSWEEP_GPT_SMALL', value: gptSmallDeployment }
  { name: 'PVSWEEP_GPT_LARGE', value: gptLargeDeployment }
  { name: 'PVSWEEP_CLAUDE_SMALL', value: claudeSmallDeployment }
  { name: 'PVSWEEP_CLAUDE_LARGE', value: claudeLargeDeployment }
  { name: 'APPLICATIONINSIGHTS_CONNECTION_STRING', value: appInsights.properties.ConnectionString }
]

var jobBase = {
  environmentId: env.id
  configuration: {
    triggerType: 'Manual'
    replicaTimeout: 6 * 3600
    replicaRetryLimit: 0
    manualTriggerConfig: { parallelism: 1, replicaCompletionCount: 1 }
    registries: [ { server: registryLoginServer, identity: runnerIdentityId } ]
    secrets: [
      { name: 'snowflake-runner-key', keyVaultUrl: '${keyVault.properties.vaultUri}secrets/snowflake-runner-key', identity: runnerIdentityId }
    ]
  }
}

resource loadJob 'Microsoft.App/jobs@2024-03-01' = {
  name: 'job-${baseName}-load'
  location: location
  tags: tags
  identity: { type: 'UserAssigned', userAssignedIdentities: { '${runnerIdentityId}': {} } }
  properties: union(jobBase, {
    template: {
      containers: [ {
        name: 'load'
        image: runnerImage
        command: [ 'python', '-I', '-m', 'pvsweep_load', '--out', '/tmp/stage', '--cache', '/tmp/cache', '--push-snowflake' ]
        resources: { cpu: json('1.0'), memory: '2Gi' }
        env: commonEnv
      } ]
    }
  })
}

resource sweepJob 'Microsoft.App/jobs@2024-03-01' = {
  name: 'job-${baseName}-sweep'
  location: location
  tags: tags
  identity: { type: 'UserAssigned', userAssignedIdentities: { '${runnerIdentityId}': {} } }
  properties: union(jobBase, {
    template: {
      containers: [ {
        name: 'sweep'
        image: runnerImage
        command: [ 'python', '-I', '-m', 'pvsweep_runner', 'sweep', '--backend', 'snowflake', '--provider', 'gpt', '--match', 'hosted' ]
        resources: { cpu: json('0.5'), memory: '1Gi' }
        env: commonEnv
      } ]
    }
  })
}

output keyVaultName string = keyVault.name
output appInsightsConnectionString string = appInsights.properties.ConnectionString
output loadJobName string = loadJob.name
output sweepJobName string = sweepJob.name
