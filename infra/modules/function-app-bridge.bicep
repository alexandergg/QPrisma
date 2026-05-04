@description('Azure Function App name')
param name string

@description('App Service plan name')
param planName string

@description('Dedicated storage account name for Azure Functions host state')
param storageAccountName string

@description('Location for resources')
param location string = resourceGroup().location

@description('User-assigned managed identity resource ID used by the Function App')
param runtimeIdentityResourceId string

@description('User-assigned managed identity principal ID used by the Function App')
param runtimeIdentityPrincipalId string

@description('User-assigned managed identity client ID used by Service Bus identity-based trigger connection')
param runtimeIdentityClientId string

@description('Service Bus namespace FQDN, for example namespace.servicebus.windows.net')
param serviceBusFullyQualifiedNamespace string

@description('Service Bus queue consumed by the bridge')
param serviceBusQueueName string

@description('Databricks workspace URL')
param databricksWorkspaceUrl string

@description('Databricks Job ID invoked by the bridge')
param databricksVideoJobId string

@description('Databricks SQL warehouse ID used by the outbox projection timer. Leave empty to skip polling.')
param databricksSqlWarehouseId string = ''

@description('Databricks catalog that contains the video pipeline outbox table')
param databricksOutboxCatalog string = 'dbw_qprisma_dev'

@description('Databricks schema that contains the video pipeline outbox table')
param databricksOutboxSchema string = 'video'

@description('Databricks outbox table name')
param databricksOutboxTable string = 'video_pipeline_outbox'

@description('Maximum number of Databricks outbox rows projected per timer invocation')
@minValue(1)
param databricksOutboxPollBatchSize int = 25

@description('Enable source media staging from upload Blob storage into the Unity Catalog volume before starting Databricks Jobs')
param databricksStagingEnabled bool = true

@description('Unity Catalog catalog that contains the managed source media volume')
param databricksSourceVolumeCatalog string = 'dbw_qprisma_dev'

@description('Unity Catalog schema that contains the managed source media volume')
param databricksSourceVolumeSchema string = 'video'

@description('Unity Catalog managed volume name used for source media staging')
param databricksSourceVolumeName string = 'source_media'

@description('Path prefix inside the managed source media volume for staged uploads')
param databricksSourceVolumePrefix string = ''

@description('NCRONTAB schedule for the Databricks outbox projection timer')
param outboxPollSchedule string = '0 */5 * * * *'

@description('Databricks authentication mode')
@allowed([
  'oauth_m2m'
  'azure_managed_identity'
  'pat'
])
param databricksAuthType string = 'oauth_m2m'

@description('Databricks OAuth service principal client ID, or managed identity client ID for azure_managed_identity mode')
param databricksClientId string = ''

@description('Key Vault secret URL for Databricks OAuth client secret')
@secure()
param databricksClientSecretKeyVaultUrl string = ''

@description('Key Vault secret URL for temporary dev Databricks PAT fallback')
@secure()
param databricksTokenKeyVaultUrl string = ''

@description('Key Vault secret URL for PostgreSQL DATABASE_URL')
param databaseUrlKeyVaultUrl string

@description('Application Insights connection string')
param appInsightsConnectionString string

@description('Resource tags')
param tags object = {}

var functionIdentity = {
  '${runtimeIdentityResourceId}': {}
}
var deploymentStorageContainerName = 'app-package-${take(name, 32)}'
var storageBlobDataOwnerRoleId = 'b7e6dc6d-f1e8-4753-8033-0f276bb0955b'
var storageQueueDataContributorRoleId = '974c5e8b-45b9-4653-ba55-5f855dd0fb88'
var storageTableDataContributorRoleId = '0a9a7e1f-b9d0-4cc4-a60d-0319b160aaa3'

resource functionStorage 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: storageAccountName
  location: location
  tags: tags
  sku: {
    name: 'Standard_LRS'
  }
  kind: 'StorageV2'
  properties: {
    allowBlobPublicAccess: false
    allowSharedKeyAccess: false
    minimumTlsVersion: 'TLS1_2'
    supportsHttpsTrafficOnly: true
  }
}

resource functionBlobService 'Microsoft.Storage/storageAccounts/blobServices@2023-05-01' = {
  parent: functionStorage
  name: 'default'
  properties: {
    deleteRetentionPolicy: {}
  }
}

resource deploymentStorageContainer 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' = {
  parent: functionBlobService
  name: deploymentStorageContainerName
  properties: {
    publicAccess: 'None'
  }
}

resource functionStorageBlobOwnerRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(functionStorage.id, runtimeIdentityPrincipalId, storageBlobDataOwnerRoleId)
  scope: functionStorage
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', storageBlobDataOwnerRoleId)
    principalId: runtimeIdentityPrincipalId
    principalType: 'ServicePrincipal'
  }
}

resource functionStorageQueueContributorRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(functionStorage.id, runtimeIdentityPrincipalId, storageQueueDataContributorRoleId)
  scope: functionStorage
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', storageQueueDataContributorRoleId)
    principalId: runtimeIdentityPrincipalId
    principalType: 'ServicePrincipal'
  }
}

resource functionStorageTableContributorRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(functionStorage.id, runtimeIdentityPrincipalId, storageTableDataContributorRoleId)
  scope: functionStorage
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', storageTableDataContributorRoleId)
    principalId: runtimeIdentityPrincipalId
    principalType: 'ServicePrincipal'
  }
}

resource plan 'Microsoft.Web/serverfarms@2024-04-01' = {
  name: planName
  location: location
  tags: tags
  kind: 'functionapp'
  sku: {
    name: 'FC1'
    tier: 'FlexConsumption'
  }
  properties: {
    reserved: true
  }
}

resource functionApp 'Microsoft.Web/sites@2024-04-01' = {
  name: name
  location: location
  tags: tags
  kind: 'functionapp,linux'
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: functionIdentity
  }
  properties: {
    serverFarmId: plan.id
    httpsOnly: true
    keyVaultReferenceIdentity: runtimeIdentityResourceId
    siteConfig: {
      ftpsState: 'Disabled'
      minTlsVersion: '1.2'
      appSettings: [
        {
          name: 'AzureWebJobsStorage__accountName'
          value: functionStorage.name
        }
        {
          name: 'AzureWebJobsStorage__credential'
          value: 'managedidentity'
        }
        {
          name: 'AzureWebJobsStorage__clientId'
          value: runtimeIdentityClientId
        }
        {
          name: 'FUNCTIONS_EXTENSION_VERSION'
          value: '~4'
        }
        {
          name: 'AzureWebJobsFeatureFlags'
          value: 'EnableWorkerIndexing'
        }
        {
          name: 'APPLICATIONINSIGHTS_CONNECTION_STRING'
          value: appInsightsConnectionString
        }
        {
          name: 'ServiceBusQueueName'
          value: serviceBusQueueName
        }
        {
          name: 'ServiceBusConnection__fullyQualifiedNamespace'
          value: serviceBusFullyQualifiedNamespace
        }
        {
          name: 'ServiceBusConnection__credential'
          value: 'managedidentity'
        }
        {
          name: 'ServiceBusConnection__clientId'
          value: runtimeIdentityClientId
        }
        {
          name: 'DATABRICKS_WORKSPACE_URL'
          value: databricksWorkspaceUrl
        }
        {
          name: 'DATABRICKS_VIDEO_JOB_ID'
          value: databricksVideoJobId
        }
        {
          name: 'DATABRICKS_SQL_WAREHOUSE_ID'
          value: databricksSqlWarehouseId
        }
        {
          name: 'DATABRICKS_OUTBOX_CATALOG'
          value: databricksOutboxCatalog
        }
        {
          name: 'DATABRICKS_OUTBOX_SCHEMA'
          value: databricksOutboxSchema
        }
        {
          name: 'DATABRICKS_OUTBOX_TABLE'
          value: databricksOutboxTable
        }
        {
          name: 'DATABRICKS_OUTBOX_POLL_BATCH_SIZE'
          value: string(databricksOutboxPollBatchSize)
        }
        {
          name: 'DATABRICKS_STAGING_ENABLED'
          value: string(databricksStagingEnabled)
        }
        {
          name: 'DATABRICKS_SOURCE_VOLUME_CATALOG'
          value: databricksSourceVolumeCatalog
        }
        {
          name: 'DATABRICKS_SOURCE_VOLUME_SCHEMA'
          value: databricksSourceVolumeSchema
        }
        {
          name: 'DATABRICKS_SOURCE_VOLUME_NAME'
          value: databricksSourceVolumeName
        }
        {
          name: 'DATABRICKS_SOURCE_VOLUME_PREFIX'
          value: databricksSourceVolumePrefix
        }
        {
          name: 'AZURE_STORAGE_MANAGED_IDENTITY_CLIENT_ID'
          value: runtimeIdentityClientId
        }
        {
          name: 'OutboxPollSchedule'
          value: outboxPollSchedule
        }
        {
          name: 'DATABRICKS_AUTH_TYPE'
          value: databricksAuthType
        }
        {
          name: 'DATABRICKS_CLIENT_ID'
          value: databricksClientId
        }
        {
          name: 'DATABRICKS_CLIENT_SECRET'
          value: empty(databricksClientSecretKeyVaultUrl) ? '' : '@Microsoft.KeyVault(SecretUri=${databricksClientSecretKeyVaultUrl})'
        }
        {
          name: 'DATABRICKS_TOKEN'
          value: empty(databricksTokenKeyVaultUrl) ? '' : '@Microsoft.KeyVault(SecretUri=${databricksTokenKeyVaultUrl})'
        }
        {
          name: 'DATABASE_URL'
          value: '@Microsoft.KeyVault(SecretUri=${databaseUrlKeyVaultUrl})'
        }
      ]
    }
    functionAppConfig: {
      deployment: {
        storage: {
          type: 'blobContainer'
          value: '${functionStorage.properties.primaryEndpoints.blob}${deploymentStorageContainer.name}'
          authentication: {
            type: 'UserAssignedIdentity'
            userAssignedIdentityResourceId: runtimeIdentityResourceId
          }
        }
      }
      runtime: {
        name: 'python'
        version: '3.11'
      }
      scaleAndConcurrency: {
        maximumInstanceCount: 40
        instanceMemoryMB: 2048
      }
    }
  }
  dependsOn: [
    functionStorageBlobOwnerRole
    functionStorageQueueContributorRole
    functionStorageTableContributorRole
  ]
}

output id string = functionApp.id
output name string = functionApp.name
output principalId string = runtimeIdentityPrincipalId
output defaultHostName string = functionApp.properties.defaultHostName
