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

@description('Neo4j admin password (for Container App Neo4j instance)')
@secure()
param neo4jPassword string

@description('JWT secret key')
@secure()
param jwtSecretKey string = ''

@description('Microsoft Entra ID tenant ID for backend token validation')
param entraAuthTenantId string = ''

@description('Backend API app registration client ID (Entra ID)')
param entraAuthClientId string = ''

@description('Backend API scope exposed by the app registration (e.g. api://<id>/access_as_user)')
param entraAuthApiScope string = ''

@description('API container image')
param apiImageName string = 'mcr.microsoft.com/azuredocs/containerapps-helloworld:latest'

@description('Frontend container image')
param frontendImageName string = 'mcr.microsoft.com/azuredocs/containerapps-helloworld:latest'

@description('Worker container image')
param workerImageName string = 'mcr.microsoft.com/azuredocs/containerapps-helloworld:latest'

@description('Enable Mem0 semantic memory integration')
param mem0Enabled bool = false

@description('Mem0 retrieval top-k')
param mem0TopK int = 5

@description('Mem0 API key (required for Mem0 cloud mode)')
@secure()
param mem0ApiKey string = ''

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
var neo4jContainerAppName = 'ca-qprisma-neo4j-${environment}'

// =====================================================================
// Foundation: Storage, Databases, Container Registry
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
    storageAccountKey: storageAccountKey
    tags: tags
  }
}

// =====================================================================
// Shared secrets & env vars for API and Worker
// =====================================================================

// Existing resource references for secret retrieval (avoids exposing secrets as module outputs)
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
var acrAdminPassword = existingAcr.listCredentials().passwords[0].value
var aiApiKey = existingAiFoundry.listKeys().key1
var storageAccountKey = existingStorage.listKeys().keys[0].value
var storageConnectionString = 'DefaultEndpointsProtocol=https;AccountName=${storageAccountName};AccountKey=${storageAccountKey};EndpointSuffix=${az.environment().suffixes.storage}'
var pgConnectionString = 'postgresql://${dbAdminLogin}:${dbAdminPassword}@${postgres.outputs.fqdn}:5432/qprisma?sslmode=require'
var redisAccessKey = existingRedisDb.listKeys().primaryKey
var redisConnectionString = 'rediss://:${redisAccessKey}@${redis.outputs.hostName}'

// Secrets stored in Container Apps (actual values)
var appSecrets = [
  { name: 'neo4j-password', value: neo4jPassword }
  { name: 'openai-api-key', value: aiApiKey }
  { name: 'storage-connection-string', value: storageConnectionString }
  { name: 'jwt-secret-key', value: jwtSecretKey }
  { name: 'database-url', value: pgConnectionString }
  { name: 'redis-url', value: redisConnectionString }
  { name: 'mem0-api-key', value: empty(mem0ApiKey) ? 'not-configured' : mem0ApiKey }
]

// Construct frontend FQDN from naming convention + environment domain (avoids circular dependency)
var frontendFqdn = '${frontendContainerAppName}.${containerAppsEnv.outputs.defaultDomain}'

// Plain-value env vars (Neo4j URI auto-wired from Container App internal FQDN)
var appEnvVars = [
  { name: 'NEO4J_URI', value: neo4j.outputs.boltUri }
  { name: 'NEO4J_USER', value: 'neo4j' }
  { name: 'AZURE_OPENAI_ENDPOINT', value: existingAiFoundry.properties.endpoint }
  { name: 'AZURE_OPENAI_DEPLOYMENT_GPT', value: 'gpt-4o' }
  { name: 'AZURE_OPENAI_DEPLOYMENT_GPT_CHAT', value: 'gpt-5.2-chat' }
  { name: 'AZURE_OPENAI_DEPLOYMENT_EMBEDDING', value: 'text-embedding-3-large' }
  { name: 'AZURE_OPENAI_DEPLOYMENT_WHISPER', value: 'whisper' }
  { name: 'AZURE_OPENAI_DEPLOYMENT_GPT_BATCH', value: 'gpt-4o-batch' }
  { name: 'ENVIRONMENT', value: environment }
  { name: 'ALLOWED_ORIGINS', value: 'https://${frontendFqdn}' }
  { name: 'MEM0_ENABLED', value: string(mem0Enabled) }
  { name: 'MEM0_TOP_K', value: string(mem0TopK) }
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
  { name: 'AZURE_OPENAI_API_KEY', secretRef: 'openai-api-key' }
  { name: 'AZURE_STORAGE_CONNECTION_STRING', secretRef: 'storage-connection-string' }
  { name: 'JWT_SECRET_KEY', secretRef: 'jwt-secret-key' }
  { name: 'MEM0_API_KEY', secretRef: 'mem0-api-key' }
]

// =====================================================================
// Container Apps
// =====================================================================

module apiContainerApp 'modules/container-app-api.bicep' = {
  name: 'api-deployment'
  dependsOn: [storage, postgres, redis, containerRegistry]
  params: {
    name: apiContainerAppName
    location: location
    environmentId: containerAppsEnv.outputs.id
    imageName: apiImageName
    registryServer: containerRegistry.outputs.loginServer
    registryUsername: containerRegistry.outputs.name
    registryPassword: acrAdminPassword
    envVars: appEnvVars
    secrets: appSecrets
    secretEnvVars: appSecretEnvVars
    tags: tags
  }
}

module frontendContainerApp 'modules/container-app-frontend.bicep' = {
  name: 'frontend-deployment'
  dependsOn: [containerRegistry]
  params: {
    name: frontendContainerAppName
    location: location
    environmentId: containerAppsEnv.outputs.id
    imageName: frontendImageName
    registryServer: containerRegistry.outputs.loginServer
    registryUsername: containerRegistry.outputs.name
    registryPassword: acrAdminPassword
    envVars: [
      { name: 'NEXT_PUBLIC_API_URL', value: 'https://${apiContainerApp.outputs.fqdn}' }
    ]
    tags: tags
  }
}

module workerContainerApp 'modules/container-app-worker.bicep' = {
  name: 'worker-deployment'
  dependsOn: [storage, postgres, redis, containerRegistry]
  params: {
    name: workerContainerAppName
    location: location
    environmentId: containerAppsEnv.outputs.id
    imageName: workerImageName
    registryServer: containerRegistry.outputs.loginServer
    registryUsername: containerRegistry.outputs.name
    registryPassword: acrAdminPassword
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
// RBAC — AI Foundry access for API Container App
// Azure AI Developer: agents/read, agents/write, OpenAI data actions
// Cognitive Services User: wildcard data actions for threads/messages/runs
// Both are needed so the backend can fully operate Foundry agents.
// =====================================================================

var azureAiDeveloperRoleId = '64702f94-c441-49e6-a78b-ef80e0188fee'
var cognitiveServicesUserRoleId = 'a97b65f3-24c7-4388-baec-2e87135dc908'

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
output neo4jBoltUri string = neo4j.outputs.boltUri
output appInsightsConnectionString string = appInsights.outputs.connectionString
