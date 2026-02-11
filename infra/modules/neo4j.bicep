@description('Container App name')
param name string

@description('Location for resources')
param location string = resourceGroup().location

@description('Container Apps Environment ID')
param environmentId string

@description('Neo4j admin password')
@secure()
param neo4jPassword string

@description('Azure Files storage account name (for persistent data)')
param storageAccountName string

@description('Azure Files storage account key')
@secure()
param storageAccountKey string

@description('Resource tags')
param tags object = {}

// Azure File Share for Neo4j data persistence
resource storageAccount 'Microsoft.Storage/storageAccounts@2023-05-01' existing = {
  name: storageAccountName
}

resource fileService 'Microsoft.Storage/storageAccounts/fileServices@2023-05-01' = {
  name: 'default'
  parent: storageAccount
}

resource neo4jShare 'Microsoft.Storage/storageAccounts/fileServices/shares@2023-05-01' = {
  name: 'neo4j-data'
  parent: fileService
  properties: {
    shareQuota: 5 // 5 GB for dev
  }
}

// Managed storage mount on the Container Apps Environment
resource containerAppsEnv 'Microsoft.App/managedEnvironments@2024-03-01' existing = {
  name: split(environmentId, '/')[8] // Extract name from resource ID
}

resource neo4jStorage 'Microsoft.App/managedEnvironments/storages@2024-03-01' = {
  name: 'neo4jstorage'
  parent: containerAppsEnv
  properties: {
    azureFile: {
      accountName: storageAccountName
      accountKey: storageAccountKey
      shareName: neo4jShare.name
      accessMode: 'ReadWrite'
    }
  }
}

resource neo4jContainerApp 'Microsoft.App/containerApps@2024-03-01' = {
  name: name
  location: location
  tags: tags
  properties: {
    environmentId: environmentId
    configuration: {
      // Internal-only: accessible by other Container Apps in the same environment
      ingress: {
        external: false
        targetPort: 7687
        exposedPort: 7687
        transport: 'tcp'
      }
      secrets: [
        {
          name: 'neo4j-password'
          value: neo4jPassword
        }
      ]
    }
    template: {
      containers: [
        {
          name: 'neo4j'
          image: 'neo4j:5-community'
          resources: {
            cpu: json('1.0')
            memory: '2Gi'
          }
          env: [
            {
              name: 'NEO4J_AUTH'
              value: 'neo4j/${neo4jPassword}'
            }
            {
              name: 'NEO4J_PLUGINS'
              value: '["apoc"]'
            }
            {
              name: 'NEO4J_apoc_export_file_enabled'
              value: 'true'
            }
            {
              name: 'NEO4J_apoc_import_file_enabled'
              value: 'true'
            }
            {
              name: 'NEO4J_apoc_import_file_use__neo4j__config'
              value: 'true'
            }
            {
              name: 'NEO4J_dbms_security_procedures_unrestricted'
              value: 'apoc.*'
            }
            {
              name: 'NEO4J_dbms_memory_heap_initial__size'
              value: '512m'
            }
            {
              name: 'NEO4J_dbms_memory_heap_max__size'
              value: '1G'
            }
          ]
          volumeMounts: [
            {
              volumeName: 'neo4j-data'
              mountPath: '/data'
            }
          ]
          probes: [
            {
              type: 'Startup'
              tcpSocket: {
                port: 7687
              }
              periodSeconds: 10
              failureThreshold: 6
            }
            {
              type: 'Liveness'
              tcpSocket: {
                port: 7687
              }
              periodSeconds: 30
              failureThreshold: 3
            }
          ]
        }
      ]
      volumes: [
        {
          name: 'neo4j-data'
          storageType: 'AzureFile'
          storageName: neo4jStorage.name
        }
      ]
      scale: {
        minReplicas: 1
        maxReplicas: 1
      }
    }
  }
}

output fqdn string = neo4jContainerApp.properties.configuration.ingress.fqdn
// TCP container apps are accessible by name (not FQDN) within the same ACA environment
output boltUri string = 'bolt://${name}:7687'
output id string = neo4jContainerApp.id
output name string = neo4jContainerApp.name
