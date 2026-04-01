using '../main.bicep'

param environment = 'dev'
param dbAdminLogin = 'qprismaadmin'
param dbAdminPassword = readEnvironmentVariable('DB_ADMIN_PASSWORD', '')
param neo4jPassword = readEnvironmentVariable('NEO4J_PASSWORD', '')
param jwtSecretKey = readEnvironmentVariable('JWT_SECRET_KEY', '')
param entraAuthTenantId = readEnvironmentVariable('ENTRA_TENANT_ID', '')
param entraAuthClientId = readEnvironmentVariable('ENTRA_CLIENT_ID', '')
param entraAuthApiScope = readEnvironmentVariable('ENTRA_API_SCOPE', '')

// Initial deployment uses placeholder images; real images are set by deploy-app workflow
param apiImageName = 'mcr.microsoft.com/azuredocs/containerapps-helloworld:latest'
param frontendImageName = 'mcr.microsoft.com/azuredocs/containerapps-helloworld:latest'
param workerImageName = 'mcr.microsoft.com/azuredocs/containerapps-helloworld:latest'
