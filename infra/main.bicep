@description('Environment name (dev, staging, production)')
param environment string = 'dev'

@description('Location for all resources')
param location string = 'westeurope'

@description('Location for PostgreSQL Flexible Server')
param dbLocation string = 'northeurope'

@description('Database administrator login')
param dbAdminLogin string = 'qprismaadmin'

@description('Database administrator password')
@secure()
param dbAdminPassword string

@description('Neo4j URI (AuraDB connection URL, e.g. neo4j+s://xxxx.databases.neo4j.io)')
param neo4jUri string = ''

@description('Neo4j username')
param neo4jUser string = 'neo4j'

@description('Neo4j database name')
param neo4jDatabase string = 'neo4j'

@description('Neo4j admin password')
@secure()
param neo4jPassword string

@description('JWT secret key')
@secure()
param jwtSecretKey string = ''

@description('Microsoft Entra ID tenant ID for backend token validation')
param entraAuthTenantId string

@description('Backend API app registration client ID (Entra ID)')
param entraAuthClientId string

@description('Backend API scope exposed by the app registration (e.g. api://<id>/access_as_user)')
param entraAuthApiScope string

@description('API container image (leave empty to use ACR default)')
param apiImageName string = ''

@description('Frontend container image (leave empty to use ACR default)')
param frontendImageName string = ''

@description('Worker container image (leave empty to use ACR default)')
param workerImageName string = ''

@description('Foundry Memory Store name')
param foundryMemoryStoreName string = ''

@description('Foundry Memory Store chat model deployment')
param foundryMemoryChatModel string = 'gpt-4o'

@description('Foundry Memory Store embedding model deployment')
param foundryMemoryEmbeddingModel string = 'text-embedding-3-large'

@description('Artifact cache TTL in seconds')
param artifactCacheTtlSeconds int = 21600

@description('Artifact cache key prefix')
param artifactCacheKeyPrefix string = 'tool_artifact'

@description('Artifact blob prefix')
param artifactBlobPrefix string = 'tool-artifacts'

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
var aiFoundryName = 'aif-qprisma-${environment}'
var containerAppsEnvName = 'cae-qprisma-${environment}'
var logAnalyticsName = 'log-qprisma-${environment}'
var appInsightsName = 'appi-qprisma-${environment}'
var apiContainerAppName = 'ca-qprisma-api-${environment}'
var frontendContainerAppName = 'ca-qprisma-web-${environment}'
var workerContainerAppName = 'ca-qprisma-worker-${environment}'
var runtimeIdentityName = 'id-qprisma-runtime-${environment}'

// Compute defaultcontainer images from ACR (used when image params are empty)
var acrLoginServer = '${containerRegistryName}.azurecr.io'
var effectiveApiImage = empty(apiImageName) ? '${acrLoginServer}/qprisma-api:latest' : apiImageName
var effectiveFrontendImage = empty(frontendImageName) ? '${acrLoginServer}/qprisma-frontend:latest' : frontendImageName
var effectiveWorkerImage = empty(workerImageName) ? '${acrLoginServer}/qprisma-worker:latest' : workerImageName
var apiIsPlaceholder = contains(effectiveApiImage, 'helloworld') || contains(effectiveApiImage, 'mcr.microsoft.com')

// =====================================================================
// Foundation: Storage, Databases, Container Registry
// =====================================================================

module storage 'modules/storage.bicep' = {
  name: 'storage-deployment'
  params: {
    name: storageAccountName
    location: location
    tags: tags
    corsAllowedOrigins: [
      'https://${frontendFqdn}'
      'http://localhost:3000'
    ]
  }
}

module postgres 'modules/postgresql.bicep' = {
  name: 'postgres-deployment'
  params: {
    name: postgresName
    location: dbLocation
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
// Application Insights (APM, distributed tracing, Foundry tracing)
// =====================================================================

module appInsights 'modules/app-insights.bicep' = {
  name: 'appinsights-deployment'
  params: {
    name: appInsightsName
    location: location
    logAnalyticsWorkspaceId: containerAppsEnv.outputs.logAnalyticsWorkspaceId
    tags: tags
  }
}

// =====================================================================
// Shared runtime identity, secrets & env vars for API and Worker
// =====================================================================

resource runtimeIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: runtimeIdentityName
  location: location
  tags: tags
}

// Existing resource references for secret retrieval and RBAC scopes
resource existingAcr 'Microsoft.ContainerRegistry/registries@2023-11-01-preview' existing = {
  name: containerRegistryName
}

resource existingAiFoundry 'Microsoft.CognitiveServices/accounts@2025-06-01' existing = {
  name: aiFoundryName
}

resource existingAiProject 'Microsoft.CognitiveServices/accounts/projects@2025-06-01' existing = {
  name: '${aiFoundryName}-project'
  parent: existingAiFoundry
}

resource existingStorage 'Microsoft.Storage/storageAccounts@2023-05-01' existing = {
  name: storageAccountName
}

resource existingRedis 'Microsoft.Cache/redisEnterprise@2025-04-01' existing = {
  name: redisName
}

resource existingRedisDb 'Microsoft.Cache/redisEnterprise/databases@2025-04-01' existing = {
  name: 'default'
  parent: existingRedis
}

// Resolve secrets via existing resource methods (never exposed as Bicep outputs)
var pgConnectionString = 'postgresql://${dbAdminLogin}:${dbAdminPassword}@${postgres.outputs.fqdn}:5432/qprisma?sslmode=require'
var redisAccessKey = existingRedisDb.listKeys().primaryKey
var redisConnectionString = 'rediss://:${redisAccessKey}@${redis.outputs.hostName}'

// =====================================================================
// Key Vault (grants runtime identity access before Container Apps depend on it)
// =====================================================================

module keyVault 'modules/key-vault.bicep' = {
  name: 'keyvault-deployment'
  params: {
    name: keyVaultName
    location: location
    principalIds: [
      runtimeIdentity.properties.principalId
    ]
    tags: tags
  }
}

resource keyVaultResource 'Microsoft.KeyVault/vaults@2023-07-01' existing = {
  name: keyVaultName
}

resource neo4jPasswordSecret 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: keyVaultResource
  name: 'neo4j-password'
  properties: {
    value: neo4jPassword
  }
  dependsOn: [
    keyVault
  ]
}

resource jwtSecretKeySecret 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: keyVaultResource
  name: 'jwt-secret-key'
  properties: {
    value: jwtSecretKey
  }
  dependsOn: [
    keyVault
  ]
}

resource databaseUrlSecret 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: keyVaultResource
  name: 'database-url'
  properties: {
    value: pgConnectionString
  }
  dependsOn: [
    keyVault
  ]
}

resource redisUrlSecret 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: keyVaultResource
  name: 'redis-url'
  properties: {
    value: redisConnectionString
  }
  dependsOn: [
    keyVault
  ]
}

var appSecrets = [
  {
    name: 'neo4j-password'
    keyVaultUrl: '${keyVault.outputs.uri}secrets/neo4j-password'
    identity: runtimeIdentity.id
  }
  {
    name: 'jwt-secret-key'
    keyVaultUrl: '${keyVault.outputs.uri}secrets/jwt-secret-key'
    identity: runtimeIdentity.id
  }
  {
    name: 'database-url'
    keyVaultUrl: '${keyVault.outputs.uri}secrets/database-url'
    identity: runtimeIdentity.id
  }
  {
    name: 'redis-url'
    keyVaultUrl: '${keyVault.outputs.uri}secrets/redis-url'
    identity: runtimeIdentity.id
  }
]

// Construct frontend FQDN from naming convention + environment domain (avoids circular dependency)
var frontendFqdn = '${frontendContainerAppName}.${containerAppsEnv.outputs.defaultDomain}'

// Normalize empty strings back to defaults (empty secrets override Bicep param defaults)
var effectiveNeo4jUser = empty(neo4jUser) ? 'neo4j' : neo4jUser
var effectiveNeo4jDatabase = empty(neo4jDatabase) ? 'neo4j' : neo4jDatabase

// Plain-value env vars (Neo4j URI from AuraDB, passed via parameter)
var appEnvVars = [
  { name: 'NEO4J_URI', value: neo4jUri }
  { name: 'NEO4J_USER', value: effectiveNeo4jUser }
  { name: 'NEO4J_DATABASE', value: effectiveNeo4jDatabase }
  { name: 'AZURE_OPENAI_ENDPOINT', value: existingAiFoundry.properties.endpoint }
  { name: 'AZURE_USE_MANAGED_IDENTITY', value: 'true' }
  { name: 'AZURE_STORAGE_ACCOUNT_URL', value: storage.outputs.blobEndpoint }
  { name: 'AZURE_OPENAI_DEPLOYMENT_GPT', value: 'gpt-4o' }
  { name: 'AZURE_OPENAI_DEPLOYMENT_GPT_CHAT', value: 'gpt-5.2-chat' }
  { name: 'AZURE_OPENAI_DEPLOYMENT_EMBEDDING', value: 'text-embedding-3-large' }
  { name: 'AZURE_OPENAI_DEPLOYMENT_WHISPER', value: 'whisper' }
  { name: 'AZURE_OPENAI_DEPLOYMENT_GPT_BATCH', value: 'gpt-4o-batch' }
  { name: 'ENVIRONMENT', value: environment }
  { name: 'ALLOWED_ORIGINS', value: 'https://${frontendFqdn}' }
  { name: 'FOUNDRY_MEMORY_STORE_NAME', value: foundryMemoryStoreName }
  { name: 'FOUNDRY_MEMORY_CHAT_MODEL', value: foundryMemoryChatModel }
  { name: 'FOUNDRY_MEMORY_EMBEDDING_MODEL', value: foundryMemoryEmbeddingModel }
  { name: 'ARTIFACT_CACHE_TTL_SECONDS', value: string(artifactCacheTtlSeconds) }
  { name: 'ARTIFACT_CACHE_KEY_PREFIX', value: artifactCacheKeyPrefix }
  { name: 'ARTIFACT_BLOB_PREFIX', value: artifactBlobPrefix }
  { name: 'FOUNDRY_PROJECT_ENDPOINT', value: 'https://${aiFoundryName}.services.ai.azure.com/api/projects/${existingAiProject.name}' }
  { name: 'FOUNDRY_AGENT_NAME', value: 'qprisma-video-agent' }
  { name: 'APPLICATIONINSIGHTS_CONNECTION_STRING', value: appInsights.outputs.connectionString }
  { name: 'OTEL_SERVICE_NAME', value: 'qprisma-api' }
  { name: 'ENTRA_TENANT_ID', value: entraAuthTenantId }
  { name: 'ENTRA_CLIENT_ID', value: entraAuthClientId }
  { name: 'ENTRA_API_SCOPE', value: entraAuthApiScope }
]

// Env vars that reference secrets by name
var appSecretEnvVars = [
  { name: 'DATABASE_URL', secretRef: 'database-url' }
  { name: 'REDIS_URL', secretRef: 'redis-url' }
  { name: 'NEO4J_PASSWORD', secretRef: 'neo4j-password' }
  { name: 'JWT_SECRET_KEY', secretRef: 'jwt-secret-key' }
]

// =====================================================================
// Container Apps
// =====================================================================

module apiContainerApp 'modules/container-app-api.bicep' = {
  name: 'api-deployment'
  dependsOn: [neo4jPasswordSecret, jwtSecretKeySecret, databaseUrlSecret, redisUrlSecret, runtimeAcrPullRole]
  params: {
    name: apiContainerAppName
    location: location
    environmentId: containerAppsEnv.outputs.id
    imageName: effectiveApiImage
    registryServer: containerRegistry.outputs.loginServer
    runtimeIdentityResourceId: runtimeIdentity.id
    enableProbes: !apiIsPlaceholder
    envVars: appEnvVars
    secrets: appSecrets
    secretEnvVars: appSecretEnvVars
    tags: tags
  }
}

module frontendContainerApp 'modules/container-app-frontend.bicep' = {
  name: 'frontend-deployment'
  dependsOn: [runtimeAcrPullRole]
  params: {
    name: frontendContainerAppName
    location: location
    environmentId: containerAppsEnv.outputs.id
    imageName: effectiveFrontendImage
    registryServer: containerRegistry.outputs.loginServer
    runtimeIdentityResourceId: runtimeIdentity.id
    envVars: [
      { name: 'NEXT_PUBLIC_API_URL', value: 'https://${apiContainerApp.outputs.fqdn}' }
    ]
    tags: tags
  }
}

module workerContainerApp 'modules/container-app-worker.bicep' = {
  name: 'worker-deployment'
  dependsOn: [neo4jPasswordSecret, jwtSecretKeySecret, databaseUrlSecret, redisUrlSecret, runtimeAcrPullRole]
  params: {
    name: workerContainerAppName
    location: location
    environmentId: containerAppsEnv.outputs.id
    imageName: effectiveWorkerImage
    registryServer: containerRegistry.outputs.loginServer
    runtimeIdentityResourceId: runtimeIdentity.id
    redisHost: redis.outputs.hostName
    envVars: appEnvVars
    secrets: appSecrets
    secretEnvVars: appSecretEnvVars
    tags: tags
  }
}

// =====================================================================
// RBAC — AI Foundry access for API Container App
// Azure AI Developer: agents/read, agents/write, OpenAI data actions
// Cognitive Services User: wildcard data actions for threads/messages/runs
// Both are needed so the backend can fully operate Foundry agents.
// =====================================================================

var acrPullRoleId = '7f951dda-4ed3-4680-a7ca-43fe172d538d'
var storageBlobDataContributorRoleId = 'ba92f5b4-2d11-453d-a403-e96b0029c9fe'
var azureAiDeveloperRoleId = '64702f94-c441-49e6-a78b-ef80e0188fee'
var cognitiveServicesUserRoleId = 'a97b65f3-24c7-4388-baec-2e87135dc908'
var cognitiveServicesOpenAiUserRoleId = '5e0bd9bd-7b93-4f28-af87-19fc36ad61bd'
var cognitiveServicesOpenAiContributorRoleId = 'a001fd3d-188f-4b5d-821b-7da978bf7442'

resource runtimeAcrPullRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(existingAcr.id, runtimeIdentityName, acrPullRoleId)
  scope: existingAcr
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', acrPullRoleId)
    principalId: runtimeIdentity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

resource apiStorageBlobContributorRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(existingStorage.id, apiContainerAppName, storageBlobDataContributorRoleId)
  scope: existingStorage
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', storageBlobDataContributorRoleId)
    principalId: apiContainerApp.outputs.principalId
    principalType: 'ServicePrincipal'
  }
}

resource workerStorageBlobContributorRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(existingStorage.id, workerContainerAppName, storageBlobDataContributorRoleId)
  scope: existingStorage
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', storageBlobDataContributorRoleId)
    principalId: workerContainerApp.outputs.principalId
    principalType: 'ServicePrincipal'
  }
}

resource apiAiDeveloperRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(existingAiFoundry.id, 'ca-qprisma-api', azureAiDeveloperRoleId)
  scope: existingAiFoundry
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', azureAiDeveloperRoleId)
    principalId: apiContainerApp.outputs.principalId
    principalType: 'ServicePrincipal'
  }
}

resource apiCognitiveServicesUserRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(existingAiFoundry.id, 'ca-qprisma-api', cognitiveServicesUserRoleId)
  scope: existingAiFoundry
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', cognitiveServicesUserRoleId)
    principalId: apiContainerApp.outputs.principalId
    principalType: 'ServicePrincipal'
  }
}

resource apiOpenAiUserRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(existingAiFoundry.id, apiContainerAppName, cognitiveServicesOpenAiUserRoleId)
  scope: existingAiFoundry
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', cognitiveServicesOpenAiUserRoleId)
    principalId: apiContainerApp.outputs.principalId
    principalType: 'ServicePrincipal'
  }
}

// Contributor (not User) so the worker can upload files and create batches
// via the OpenAI Batch API (requires Microsoft.CognitiveServices/accounts/OpenAI/files/write)
resource workerOpenAiContributorRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(existingAiFoundry.id, workerContainerAppName, cognitiveServicesOpenAiContributorRoleId)
  scope: existingAiFoundry
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', cognitiveServicesOpenAiContributorRoleId)
    principalId: workerContainerApp.outputs.principalId
    principalType: 'ServicePrincipal'
  }
}

// =====================================================================
// Outputs
// =====================================================================

output apiFqdn string = apiContainerApp.outputs.fqdn
output frontendFqdn string = frontendContainerApp.outputs.fqdn
output acrLoginServer string = containerRegistry.outputs.loginServer
output openAiEndpoint string = existingAiFoundry.properties.endpoint
output foundryProjectEndpoint string = 'https://${aiFoundryName}.services.ai.azure.com/api/projects/${existingAiProject.name}'
output foundryProjectName string = existingAiProject.name
output foundryProjectPrincipalId string = existingAiProject.identity.principalId
output keyVaultUri string = keyVault.outputs.uri
output storageAccountName string = storage.outputs.name
output postgresServerName string = postgres.outputs.name
output redisHostName string = redis.outputs.hostName
output neo4jUri string = neo4jUri
output appInsightsConnectionString string = appInsights.outputs.connectionString
