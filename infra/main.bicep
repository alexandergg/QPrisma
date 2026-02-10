@description('Environment name (dev, staging, production)')
param environment string = 'dev'

@description('Location for all resources')
param location string = 'westeurope'

@description('Location for Azure AI Foundry (OpenAI) resources')
param aiLocation string = 'swedencentral'

@description('Database administrator login')
param dbAdminLogin string = 'qprismaadmin'

@description('Database administrator password')
@secure()
param dbAdminPassword string

@description('Deploy batch model (gpt-4o-batch)')
param deployBatchModel bool = true

@description('Neo4j admin password (for Container App Neo4j instance)')
@secure()
param neo4jPassword string

@description('JWT secret key')
@secure()
param jwtSecretKey string = ''

@description('API container image')
param apiImageName string = 'mcr.microsoft.com/azuredocs/containerapps-helloworld:latest'

@description('Frontend container image')
param frontendImageName string = 'mcr.microsoft.com/azuredocs/containerapps-helloworld:latest'

@description('Worker container image')
param workerImageName string = 'mcr.microsoft.com/azuredocs/containerapps-helloworld:latest'

// =====================================================================
// Tags & Naming
// =====================================================================

var tags = {
  environment: environment
  project: 'qprisma'
}

var storageAccountName = 'stqprisma${environment}'
var postgresName = 'psql-qprisma-${environment}'
var redisName = 'redis-qprisma-${environment}'
var keyVaultName = 'kv-qprisma-${environment}'
var containerRegistryName = 'acrqprisma${environment}'
var openAiName = 'oai-qprisma-${environment}'
var containerAppsEnvName = 'cae-qprisma-${environment}'
var logAnalyticsName = 'log-qprisma-${environment}'
var apiContainerAppName = 'ca-qprisma-api-${environment}'
var frontendContainerAppName = 'ca-qprisma-web-${environment}'
var workerContainerAppName = 'ca-qprisma-worker-${environment}'
var neo4jContainerAppName = 'ca-qprisma-neo4j-${environment}'

// =====================================================================
// Foundation: Storage, Databases, AI
// =====================================================================

module storage 'modules/storage.bicep' = {
  name: 'storage-deployment'
  params: {
    name: storageAccountName
    location: location
    tags: tags
  }
}

module postgres 'modules/postgresql.bicep' = {
  name: 'postgres-deployment'
  params: {
    name: postgresName
    location: location
    adminLogin: dbAdminLogin
    adminPassword: dbAdminPassword
    tags: tags
  }
}

module redis 'modules/redis.bicep' = {
  name: 'redis-deployment'
  params: {
    name: redisName
    location: location
    tags: tags
  }
}

module containerRegistry 'modules/container-registry.bicep' = {
  name: 'acr-deployment'
  params: {
    name: containerRegistryName
    location: location
    tags: tags
  }
}

module openAi 'modules/ai-foundry.bicep' = {
  name: 'openai-deployment'
  params: {
    name: openAiName
    location: aiLocation
    deployBatchModel: deployBatchModel
    tags: tags
  }
}

// =====================================================================
// Container Apps Environment
// =====================================================================

module containerAppsEnv 'modules/container-apps-env.bicep' = {
  name: 'cae-deployment'
  params: {
    name: containerAppsEnvName
    location: location
    logAnalyticsName: logAnalyticsName
    tags: tags
  }
}

// =====================================================================
// Neo4j (Container App — dev environment)
// =====================================================================

module neo4j 'modules/neo4j.bicep' = {
  name: 'neo4j-deployment'
  params: {
    name: neo4jContainerAppName
    location: location
    environmentId: containerAppsEnv.outputs.id
    neo4jPassword: neo4jPassword
    storageAccountName: storage.outputs.name
    storageAccountKey: storage.outputs.storageKey
    tags: tags
  }
}

// =====================================================================
// Shared secrets & env vars for API and Worker
// =====================================================================

// Secrets stored in Container Apps (actual values)
var appSecrets = [
  { name: 'neo4j-password', value: neo4jPassword }
  { name: 'openai-api-key', value: openAi.outputs.apiKey }
  { name: 'storage-connection-string', value: storage.outputs.connectionString }
  { name: 'jwt-secret-key', value: jwtSecretKey }
  { name: 'database-url', value: postgres.outputs.connectionString }
  { name: 'redis-url', value: redis.outputs.connectionString }
]

// Plain-value env vars (Neo4j URI auto-wired from Container App internal FQDN)
var appEnvVars = [
  { name: 'NEO4J_URI', value: neo4j.outputs.boltUri }
  { name: 'NEO4J_USER', value: 'neo4j' }
  { name: 'AZURE_OPENAI_ENDPOINT', value: openAi.outputs.endpoint }
  { name: 'AZURE_OPENAI_DEPLOYMENT_GPT', value: 'gpt-4o' }
  { name: 'AZURE_OPENAI_DEPLOYMENT_EMBEDDING', value: 'text-embedding-3-large' }
  { name: 'AZURE_OPENAI_DEPLOYMENT_WHISPER', value: 'whisper' }
  { name: 'ENVIRONMENT', value: environment }
]

// Env vars that reference secrets by name
var appSecretEnvVars = [
  { name: 'DATABASE_URL', secretRef: 'database-url' }
  { name: 'REDIS_URL', secretRef: 'redis-url' }
  { name: 'NEO4J_PASSWORD', secretRef: 'neo4j-password' }
  { name: 'AZURE_OPENAI_API_KEY', secretRef: 'openai-api-key' }
  { name: 'AZURE_STORAGE_CONNECTION_STRING', secretRef: 'storage-connection-string' }
  { name: 'JWT_SECRET_KEY', secretRef: 'jwt-secret-key' }
]

// =====================================================================
// Container Apps
// =====================================================================

module apiContainerApp 'modules/container-app-api.bicep' = {
  name: 'api-deployment'
  params: {
    name: apiContainerAppName
    location: location
    environmentId: containerAppsEnv.outputs.id
    imageName: apiImageName
    registryServer: containerRegistry.outputs.loginServer
    registryUsername: containerRegistry.outputs.name
    registryPassword: containerRegistry.outputs.adminPassword
    envVars: appEnvVars
    secrets: appSecrets
    secretEnvVars: appSecretEnvVars
    tags: tags
  }
}

module frontendContainerApp 'modules/container-app-frontend.bicep' = {
  name: 'frontend-deployment'
  params: {
    name: frontendContainerAppName
    location: location
    environmentId: containerAppsEnv.outputs.id
    imageName: frontendImageName
    registryServer: containerRegistry.outputs.loginServer
    registryUsername: containerRegistry.outputs.name
    registryPassword: containerRegistry.outputs.adminPassword
    envVars: [
      { name: 'NEXT_PUBLIC_API_URL', value: 'https://${apiContainerApp.outputs.fqdn}' }
    ]
    tags: tags
  }
}

module workerContainerApp 'modules/container-app-worker.bicep' = {
  name: 'worker-deployment'
  params: {
    name: workerContainerAppName
    location: location
    environmentId: containerAppsEnv.outputs.id
    imageName: workerImageName
    registryServer: containerRegistry.outputs.loginServer
    registryUsername: containerRegistry.outputs.name
    registryPassword: containerRegistry.outputs.adminPassword
    redisHost: redis.outputs.hostName
    envVars: appEnvVars
    secrets: appSecrets
    secretEnvVars: appSecretEnvVars
    tags: tags
  }
}

// =====================================================================
// Key Vault (grants managed identity access to Container Apps)
// =====================================================================

module keyVault 'modules/key-vault.bicep' = {
  name: 'keyvault-deployment'
  params: {
    name: keyVaultName
    location: location
    principalIds: [
      apiContainerApp.outputs.principalId
      workerContainerApp.outputs.principalId
    ]
    tags: tags
  }
}

// =====================================================================
// Outputs
// =====================================================================

output apiFqdn string = apiContainerApp.outputs.fqdn
output frontendFqdn string = frontendContainerApp.outputs.fqdn
output acrLoginServer string = containerRegistry.outputs.loginServer
output openAiEndpoint string = openAi.outputs.endpoint
output keyVaultUri string = keyVault.outputs.uri
output storageAccountName string = storage.outputs.name
output postgresServerName string = postgres.outputs.name
output redisHostName string = redis.outputs.hostName
output neo4jBoltUri string = neo4j.outputs.boltUri
