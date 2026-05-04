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
param databricksOutboxCatalog string = 'qprisma_dev'

@description('Databricks schema that contains the video pipeline outbox table')
param databricksOutboxSchema string = 'video'

@description('Databricks outbox table name')
param databricksOutboxTable string = 'video_pipeline_outbox'

@description('Maximum number of Databricks outbox rows projected per timer invocation')
@minValue(1)
param databricksOutboxPollBatchSize int = 25

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

var storageConnectionString = 'DefaultEndpointsProtocol=https;AccountName=${functionStorage.name};EndpointSuffix=${environment().suffixes.storage};AccountKey=${functionStorage.listKeys().keys[0].value}'

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
    minimumTlsVersion: 'TLS1_2'
    supportsHttpsTrafficOnly: true
  }
}

resource plan 'Microsoft.Web/serverfarms@2023-12-01' = {
  name: planName
  location: location
  tags: tags
  sku: {
    name: 'Y1'
    tier: 'Dynamic'
  }
  properties: {
    reserved: true
  }
}

resource functionApp 'Microsoft.Web/sites@2023-12-01' = {
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
      linuxFxVersion: 'Python|3.11'
      ftpsState: 'Disabled'
      minTlsVersion: '1.2'
      appSettings: [
        {
          name: 'AzureWebJobsStorage'
          value: storageConnectionString
        }
        {
          name: 'FUNCTIONS_EXTENSION_VERSION'
          value: '~4'
        }
        {
          name: 'FUNCTIONS_WORKER_RUNTIME'
          value: 'python'
        }
        {
          name: 'SCM_DO_BUILD_DURING_DEPLOYMENT'
          value: 'true'
        }
        {
          name: 'ENABLE_ORYX_BUILD'
          value: 'true'
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
  }
}

output id string = functionApp.id
output name string = functionApp.name
output principalId string = runtimeIdentityPrincipalId
output defaultHostName string = functionApp.properties.defaultHostName
