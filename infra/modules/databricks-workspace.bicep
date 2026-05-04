@description('Azure Databricks workspace name')
param name string

@description('Databricks access connector name for Unity Catalog external locations')
param accessConnectorName string

@description('Location for resources')
param location string = resourceGroup().location

@description('Managed resource group name for the Databricks workspace')
param managedResourceGroupName string

@description('Databricks workspace SKU')
@allowed([
  'standard'
  'premium'
  'trial'
])
param skuName string = 'premium'

@description('Public network access for the pilot workspace')
@allowed([
  'Enabled'
  'Disabled'
])
param publicNetworkAccess string = 'Enabled'

@description('Required NSG rules for the Databricks workspace')
@allowed([
  'AllRules'
  'NoAzureDatabricksRules'
])
param requiredNsgRules string = 'AllRules'

@description('Resource tags')
param tags object = {}

resource workspace 'Microsoft.Databricks/workspaces@2024-05-01' = {
  name: name
  location: location
  tags: tags
  sku: {
    name: skuName
  }
  properties: {
    managedResourceGroupId: '${subscription().id}/resourceGroups/${managedResourceGroupName}'
    publicNetworkAccess: publicNetworkAccess
    requiredNsgRules: requiredNsgRules
    parameters: {
      enableNoPublicIp: {
        value: true
      }
    }
  }
}

resource accessConnector 'Microsoft.Databricks/accessConnectors@2024-05-01' = {
  name: accessConnectorName
  location: location
  tags: tags
  identity: {
    type: 'SystemAssigned'
  }
  properties: {}
}

output workspaceId string = workspace.id
output workspaceName string = workspace.name
output workspaceUrl string = workspace.properties.workspaceUrl
output accessConnectorId string = accessConnector.id
output accessConnectorPrincipalId string = accessConnector.identity.principalId
