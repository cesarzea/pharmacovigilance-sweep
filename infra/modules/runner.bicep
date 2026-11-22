// Runner: Key Vault for the Snowflake keys, monitoring, and the Container Apps jobs (sweep, optional load).
// Deployed when deployRunnerJob = true (needs the runner image in the registry and a Snowflake account).
// The jobs reference Key Vault secrets that must exist first: deploy once with deployJobs = false,
// run `make kv-secrets`, then deploy again (docs/ops/runner-job.md).

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
@description('Create the Container Apps jobs. False on the first pass, before the Key Vault secrets exist.')
param deployJobs bool = true
@description('Also create the data load job (not needed for sweeps).')
param deployLoadJob bool = false

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

// Consumption-only environment: no workloadProfiles, so jobs are billed per second of execution only.
resource env 'Microsoft.App/managedEnvironments@2024-03-01' = if (deployJobs) {
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

// PVSWEEP_SNOWFLAKE_USER is deliberately not set: the store defaults to PVSWEEP_RUNNER and the in-process
// agent backend to PVSWEEP_AGENT, and both read the same variable. Empty values are left out.
var plainEnv = filter([
  { name: 'AZURE_CLIENT_ID', value: runnerIdentityClientId }
  { name: 'PVSWEEP_FOUNDRY_ACCOUNT', value: foundryAccountName }
  { name: 'PVSWEEP_PROJECT_ENDPOINT', value: foundryProjectEndpoint }
  { name: 'PVSWEEP_SNOWFLAKE_ACCOUNT', value: snowflakeAccount }
  { name: 'PVSWEEP_PROVIDER', value: 'gpt' }
  { name: 'PVSWEEP_GPT_SMALL', value: gptSmallDeployment }
  { name: 'PVSWEEP_GPT_LARGE', value: gptLargeDeployment }
  { name: 'PVSWEEP_CLAUDE_SMALL', value: claudeSmallDeployment }
  { name: 'PVSWEEP_CLAUDE_LARGE', value: claudeLargeDeployment }
  { name: 'PVSWEEP_PROMPTS_DIR', value: '/app/prompts' }
  { name: 'PVSWEEP_CODE_VERSION', value: last(split(runnerImage, ':')) }
  { name: 'APPLICATIONINSIGHTS_CONNECTION_STRING', value: appInsights.properties.ConnectionString }
], e => !empty(e.value))
var commonEnv = concat(plainEnv, [
  { name: 'PVSWEEP_SNOWFLAKE_PRIVATE_KEY', secretRef: 'snowflake-runner-key' }
  { name: 'PVSWEEP_SNOWFLAKE_AGENT_PRIVATE_KEY', secretRef: 'snowflake-agent-key' }
])

var jobConfiguration = {
  triggerType: 'Manual'
  replicaTimeout: 6 * 3600
  replicaRetryLimit: 0
  manualTriggerConfig: { parallelism: 1, replicaCompletionCount: 1 }
  registries: [ { server: registryLoginServer, identity: runnerIdentityId } ]
  secrets: [
    { name: 'snowflake-runner-key', keyVaultUrl: '${keyVault.properties.vaultUri}secrets/snowflake-runner-key', identity: runnerIdentityId }
    { name: 'snowflake-agent-key', keyVaultUrl: '${keyVault.properties.vaultUri}secrets/snowflake-agent-key', identity: runnerIdentityId }
  ]
}

// Default run: the sweep against Snowflake with in-process agent matching. The provider comes from
// PVSWEEP_PROVIDER (gpt | claude), which also picks the small and large deployments. Arguments given at
// `az containerapp job start` time replace `args` and are appended last, so they win over these defaults.
var sweepScript = 'p="\${PVSWEEP_PROVIDER:-gpt}"; for a in "$@"; do [ "$prev" = "--provider" ] && p="$a"; prev="$a"; done; if [ "$p" = "gpt" ]; then s="$PVSWEEP_GPT_SMALL"; l="$PVSWEEP_GPT_LARGE"; else s="$PVSWEEP_CLAUDE_SMALL"; l="$PVSWEEP_CLAUDE_LARGE"; fi; set -x; exec python -I -m pvsweep_runner sweep --provider "$p" --small "$s" \${l:+--large "$l"} "$@"'

resource sweepJob 'Microsoft.App/jobs@2024-03-01' = if (deployJobs) {
  name: 'job-${baseName}-sweep'
  location: location
  tags: tags
  identity: { type: 'UserAssigned', userAssignedIdentities: { '${runnerIdentityId}': {} } }
  dependsOn: [ runnerReadsSecrets, runnerPullsImages ]
  properties: {
    environmentId: env.id
    configuration: jobConfiguration
    template: {
      containers: [ {
        name: 'sweep'
        image: runnerImage
        command: [ '/bin/sh', '-c', sweepScript, 'sweep' ]
        args: [ '--backend', 'snowflake', '--match', 'agent', '--concurrency', '2' ]
        resources: { cpu: json('0.5'), memory: '1Gi' }
        env: commonEnv
      } ]
    }
  }
}

resource loadJob 'Microsoft.App/jobs@2024-03-01' = if (deployJobs && deployLoadJob) {
  name: 'job-${baseName}-load'
  location: location
  tags: tags
  identity: { type: 'UserAssigned', userAssignedIdentities: { '${runnerIdentityId}': {} } }
  dependsOn: [ runnerReadsSecrets, runnerPullsImages ]
  properties: {
    environmentId: env.id
    configuration: jobConfiguration
    template: {
      containers: [ {
        name: 'load'
        image: runnerImage
        command: [ 'python', '-I', '-m', 'pvsweep_load', '--out', '/tmp/stage', '--cache', '/tmp/cache', '--push-snowflake' ]
        resources: { cpu: json('1.0'), memory: '2Gi' }
        env: commonEnv
      } ]
    }
  }
}

output keyVaultName string = keyVault.name
output logAnalyticsWorkspaceId string = logs.properties.customerId
output sweepJobName string = deployJobs ? 'job-${baseName}-sweep' : ''
output loadJobName string = deployJobs && deployLoadJob ? 'job-${baseName}-load' : ''
