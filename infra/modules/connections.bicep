// Project connections that carry secrets for the hosted agents. The platform resolves
// ${{connections.<name>.credentials.<key>}} placeholders in a hosted agent's environment variables
// at runtime, so the private key never sits in the agent definition or the image.
param accountName string
param projectName string
param snowflakeAccount string
@secure()
param snowflakeAgentPrivateKey string

resource account 'Microsoft.CognitiveServices/accounts@2025-10-01-preview' existing = {
  name: accountName
}

resource project 'Microsoft.CognitiveServices/accounts/projects@2025-10-01-preview' existing = {
  parent: account
  name: projectName
}

resource snowflakeAgent 'Microsoft.CognitiveServices/accounts/projects/connections@2025-10-01-preview' = {
  parent: project
  name: 'pvsweep-snowflake-agent'
  properties: {
    category: 'CustomKeys'
    authType: 'CustomKeys'
    target: 'https://${snowflakeAccount}.snowflakecomputing.com'
    isSharedToAll: false
    credentials: {
      keys: {
        account: snowflakeAccount
        private_key: snowflakeAgentPrivateKey
      }
    }
    metadata: {
      purpose: 'Key-pair credential of the PVSWEEP_AGENT service user (AGENT_API views only)'
    }
  }
}

output snowflakeAgentConnection string = snowflakeAgent.name
