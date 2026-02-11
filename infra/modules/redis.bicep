@description('Redis cache name')
param name string

@description('Location for resources')
param location string = resourceGroup().location

@description('Resource tags')
param tags object = {}

// Azure Managed Redis (redisEnterprise) — replaces retired Azure Cache for Redis
resource redisEnterprise 'Microsoft.Cache/redisEnterprise@2025-04-01' = {
  name: name
  location: location
  tags: tags
  sku: {
    name: 'Balanced_B0'
  }
  properties: {
    minimumTlsVersion: '1.2'
  }
}

resource redisDatabase 'Microsoft.Cache/redisEnterprise/databases@2025-04-01' = {
  parent: redisEnterprise
  name: 'default'
  properties: {
    clientProtocol: 'Encrypted'
    clusteringPolicy: 'OSSCluster'
    evictionPolicy: 'VolatileLRU'
    port: 10000
  }
}

output hostName string = '${redisEnterprise.properties.hostName}:${redisDatabase.properties.port}'
output id string = redisEnterprise.id
output name string = redisEnterprise.name
output connectionString string = 'rediss://:${redisDatabase.listKeys().primaryKey}@${redisEnterprise.properties.hostName}:${redisDatabase.properties.port}'
