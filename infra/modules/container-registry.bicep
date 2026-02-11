@description('Container Registry name')
param name string

@description('Location for resources')
param location string = resourceGroup().location

@description('Resource tags')
param tags object = {}

resource containerRegistry 'Microsoft.ContainerRegistry/registries@2023-11-01-preview' = {
  name: name
  location: location
  tags: tags
  sku: {
    name: 'Basic'
  }
  properties: {
    adminUserEnabled: true
    publicNetworkAccess: 'Enabled'
  }
}

output loginServer string = containerRegistry.properties.loginServer
output name string = containerRegistry.name
output id string = containerRegistry.id
