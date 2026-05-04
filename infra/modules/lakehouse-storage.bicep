@description('ADLS Gen2 storage account name for Databricks lakehouse data')
param name string

@description('Location for resources')
param location string = resourceGroup().location

@description('Container names to create for the lakehouse layout')
param containerNames array = [
  'raw'
  'bronze'
  'silver'
  'gold'
  'ops'
  'checkpoints'
  'artifacts'
]

@description('Principal IDs that should receive Storage Blob Data Contributor on the lakehouse account')
param blobDataContributorPrincipalIds array = []

@description('Resource tags')
param tags object = {}

var storageBlobDataContributorRoleId = 'ba92f5b4-2d11-453d-a403-e96b0029c9fe'

resource storageAccount 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: name
  location: location
  tags: tags
  sku: {
    name: 'Standard_LRS'
  }
  kind: 'StorageV2'
  properties: {
    accessTier: 'Hot'
    allowBlobPublicAccess: false
    allowSharedKeyAccess: false
    isHnsEnabled: true
    minimumTlsVersion: 'TLS1_2'
    supportsHttpsTrafficOnly: true
  }
}

resource blobService 'Microsoft.Storage/storageAccounts/blobServices@2023-05-01' = {
  parent: storageAccount
  name: 'default'
}

resource containers 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' = [for containerName in containerNames: {
  parent: blobService
  name: containerName
  properties: {
    publicAccess: 'None'
  }
}]

resource contributorAssignments 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for principalId in blobDataContributorPrincipalIds: {
  name: guid(storageAccount.id, principalId, storageBlobDataContributorRoleId)
  scope: storageAccount
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', storageBlobDataContributorRoleId)
    principalId: principalId
    principalType: 'ServicePrincipal'
  }
}]

output id string = storageAccount.id
output name string = storageAccount.name
output blobEndpoint string = storageAccount.properties.primaryEndpoints.blob
output dfsEndpoint string = storageAccount.properties.primaryEndpoints.dfs
output containerNames array = containerNames
