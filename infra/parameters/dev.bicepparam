using '../main.bicep'

param environment = 'dev'
param dbAdminLogin = 'qprismaadmin'
param dbAdminPassword = readEnvironmentVariable('DB_ADMIN_PASSWORD', '')
param deployBatchModel = true
param neo4jPassword = readEnvironmentVariable('NEO4J_PASSWORD', '')
param jwtSecretKey = readEnvironmentVariable('JWT_SECRET_KEY', '')

// Initial deployment uses placeholder images; real images are set by deploy-app workflow
param apiImageName = 'mcr.microsoft.com/azuredocs/containerapps-helloworld:latest'
param frontendImageName = 'mcr.microsoft.com/azuredocs/containerapps-helloworld:latest'
param workerImageName = 'mcr.microsoft.com/azuredocs/containerapps-helloworld:latest'
