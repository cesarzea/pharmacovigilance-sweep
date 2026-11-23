// Azure Databricks workspace for the second data platform (Unity Catalog, serverless SQL warehouse).
// The workspace is the only Databricks object ARM can create; the SQL warehouse, catalog, schemas,
// volume and the review app are created by scripts/dbx_setup.py and the databricks/ SQL through the
// Databricks SDK, authenticated with the deploying user's Azure CLI login or the runner identity.
param location string
param tags object
param baseName string
param suffix string

resource workspace 'Microsoft.Databricks/workspaces@2024-05-01' = {
  name: 'dbw-${baseName}-${suffix}'
  location: location
  tags: tags
  sku: { name: 'premium' }   // Unity Catalog and serverless SQL need Premium
  properties: {
    managedResourceGroupId: subscriptionResourceId('Microsoft.Resources/resourceGroups', 'rg-${baseName}-dbx-managed')
    publicNetworkAccess: 'Enabled'
  }
}

output workspaceName string = workspace.name
output workspaceUrl string = 'https://${workspace.properties.workspaceUrl}'
output workspaceResourceId string = workspace.id
