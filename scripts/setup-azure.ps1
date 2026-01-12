# QPrisma - Azure Setup Script
# Este script te guía para configurar los recursos de Azure necesarios

$ErrorActionPreference = "Stop"

Write-Host "=" -ForegroundColor Cyan -NoNewline
Write-Host "================================================" -ForegroundColor Cyan
Write-Host "  QPrisma - Azure Resources Setup" -ForegroundColor Cyan
Write-Host "=" -ForegroundColor Cyan -NoNewline
Write-Host "================================================" -ForegroundColor Cyan
Write-Host ""

# Verificar que Azure CLI está instalado
Write-Host "Verificando Azure CLI..." -ForegroundColor Yellow
try {
    $azVersion = az --version 2>&1 | Select-String "azure-cli" | Select-Object -First 1
    Write-Host "✓ Azure CLI instalado: $azVersion" -ForegroundColor Green
} catch {
    Write-Host "✗ Azure CLI no está instalado" -ForegroundColor Red
    Write-Host "Instala Azure CLI desde: https://docs.microsoft.com/cli/azure/install-azure-cli" -ForegroundColor Yellow
    exit 1
}

Write-Host ""

# Login a Azure
Write-Host "Verificando sesión de Azure..." -ForegroundColor Yellow
$account = az account show 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host "No hay sesión activa. Iniciando login..." -ForegroundColor Yellow
    az login
    if ($LASTEXITCODE -ne 0) {
        Write-Host "✗ Error al hacer login en Azure" -ForegroundColor Red
        exit 1
    }
}

$accountInfo = az account show | ConvertFrom-Json
Write-Host "✓ Sesión activa: $($accountInfo.user.name)" -ForegroundColor Green
Write-Host "  Subscription: $($accountInfo.name)" -ForegroundColor Cyan
Write-Host ""

# Configuración
Write-Host "Configuración del proyecto:" -ForegroundColor Yellow
Write-Host "──────────────────────────────────────────────" -ForegroundColor Gray

$projectName = Read-Host "Nombre del proyecto (default: qprisma)"
if ([string]::IsNullOrWhiteSpace($projectName)) { $projectName = "qprisma" }

$environment = Read-Host "Entorno (dev/staging/prod) (default: dev)"
if ([string]::IsNullOrWhiteSpace($environment)) { $environment = "dev" }

$location = Read-Host "Región de Azure (default: westeurope)"
if ([string]::IsNullOrWhiteSpace($location)) { $location = "westeurope" }

Write-Host ""
Write-Host "Resumen de configuración:" -ForegroundColor Yellow
Write-Host "  Proyecto: $projectName" -ForegroundColor Cyan
Write-Host "  Entorno: $environment" -ForegroundColor Cyan
Write-Host "  Región: $location" -ForegroundColor Cyan
Write-Host ""

$confirm = Read-Host "¿Continuar con la creación de recursos? (s/n)"
if ($confirm -ne "s" -and $confirm -ne "S" -and $confirm -ne "y" -and $confirm -ne "Y") {
    Write-Host "Operación cancelada" -ForegroundColor Yellow
    exit 0
}

# Nombres de recursos
$resourceGroup = "rg-$projectName-$environment"
$storageAccount = "st$projectName$environment"
$openaiName = "openai-$projectName-$environment"
$searchName = "search-$projectName-$environment"
$cosmosName = "cosmos-$projectName-$environment"
$redisName = "redis-$projectName-$environment"

Write-Host ""
Write-Host "=" -ForegroundColor Cyan -NoNewline
Write-Host "================================================" -ForegroundColor Cyan
Write-Host "  Creando Recursos" -ForegroundColor Cyan
Write-Host "=" -ForegroundColor Cyan -NoNewline
Write-Host "================================================" -ForegroundColor Cyan
Write-Host ""

# 1. Resource Group
Write-Host "[1/6] Creando Resource Group: $resourceGroup" -ForegroundColor Yellow
az group create --name $resourceGroup --location $location --output none
if ($LASTEXITCODE -eq 0) {
    Write-Host "✓ Resource Group creado" -ForegroundColor Green
} else {
    Write-Host "✗ Error al crear Resource Group" -ForegroundColor Red
    exit 1
}

# 2. Storage Account
Write-Host "[2/6] Creando Storage Account: $storageAccount" -ForegroundColor Yellow
Write-Host "  (Esto puede tomar 1-2 minutos...)" -ForegroundColor Gray
az storage account create `
    --name $storageAccount `
    --resource-group $resourceGroup `
    --location $location `
    --sku Standard_LRS `
    --kind StorageV2 `
    --output none

if ($LASTEXITCODE -eq 0) {
    Write-Host "✓ Storage Account creado" -ForegroundColor Green
    
    # Crear container
    Write-Host "  Creando container 'media'..." -ForegroundColor Gray
    az storage container create `
        --name media `
        --account-name $storageAccount `
        --auth-mode login `
        --output none
    
    if ($LASTEXITCODE -eq 0) {
        Write-Host "  ✓ Container 'media' creado" -ForegroundColor Green
    }
} else {
    Write-Host "✗ Error al crear Storage Account" -ForegroundColor Red
}

# 3. Azure OpenAI
Write-Host "[3/6] Creando Azure OpenAI: $openaiName" -ForegroundColor Yellow
Write-Host "  (Esto puede tomar 2-3 minutos...)" -ForegroundColor Gray
az cognitiveservices account create `
    --name $openaiName `
    --resource-group $resourceGroup `
    --location $location `
    --kind OpenAI `
    --sku S0 `
    --output none

if ($LASTEXITCODE -eq 0) {
    Write-Host "✓ Azure OpenAI creado" -ForegroundColor Green
    
    Write-Host "  Esperando que el servicio esté listo..." -ForegroundColor Gray
    Start-Sleep -Seconds 30
    
    # Deploy GPT-4o
    Write-Host "  Desplegando modelo GPT-4o..." -ForegroundColor Gray
    az cognitiveservices account deployment create `
        --name $openaiName `
        --resource-group $resourceGroup `
        --deployment-name gpt-4o `
        --model-name gpt-4o `
        --model-version "2024-08-06" `
        --model-format OpenAI `
        --sku-capacity 10 `
        --sku-name "Standard" `
        --output none 2>$null
    
    if ($LASTEXITCODE -eq 0) {
        Write-Host "  ✓ Modelo GPT-4o desplegado" -ForegroundColor Green
    }
    
    # Deploy Embeddings
    Write-Host "  Desplegando modelo text-embedding-3-large..." -ForegroundColor Gray
    az cognitiveservices account deployment create `
        --name $openaiName `
        --resource-group $resourceGroup `
        --deployment-name text-embedding-3-large `
        --model-name text-embedding-3-large `
        --model-version "1" `
        --model-format OpenAI `
        --sku-capacity 10 `
        --sku-name "Standard" `
        --output none 2>$null
    
    if ($LASTEXITCODE -eq 0) {
        Write-Host "  ✓ Modelo embeddings desplegado" -ForegroundColor Green
    }
} else {
    Write-Host "✗ Error al crear Azure OpenAI" -ForegroundColor Red
    Write-Host "  Nota: Azure OpenAI requiere aprobación. Verifica que tu subscription tenga acceso." -ForegroundColor Yellow
}

# 4. Azure AI Search
Write-Host "[4/6] Creando Azure AI Search: $searchName" -ForegroundColor Yellow
Write-Host "  (Esto puede tomar 1-2 minutos...)" -ForegroundColor Gray
az search service create `
    --name $searchName `
    --resource-group $resourceGroup `
    --location $location `
    --sku basic `
    --output none

if ($LASTEXITCODE -eq 0) {
    Write-Host "✓ Azure AI Search creado" -ForegroundColor Green
} else {
    Write-Host "✗ Error al crear Azure AI Search" -ForegroundColor Red
}

# 5. Cosmos DB
Write-Host "[5/6] Creando Cosmos DB: $cosmosName" -ForegroundColor Yellow
Write-Host "  (Esto puede tomar 3-5 minutos...)" -ForegroundColor Gray
az cosmosdb create `
    --name $cosmosName `
    --resource-group $resourceGroup `
    --locations regionName=$location `
    --default-consistency-level Session `
    --output none

if ($LASTEXITCODE -eq 0) {
    Write-Host "✓ Cosmos DB creado" -ForegroundColor Green
    
    # Crear database
    Write-Host "  Creando database 'qprisma'..." -ForegroundColor Gray
    az cosmosdb sql database create `
        --account-name $cosmosName `
        --resource-group $resourceGroup `
        --name qprisma `
        --throughput 400 `
        --output none
    
    if ($LASTEXITCODE -eq 0) {
        Write-Host "  ✓ Database 'qprisma' creado" -ForegroundColor Green
        
        # Crear container
        Write-Host "  Creando container 'media-metadata'..." -ForegroundColor Gray
        az cosmosdb sql container create `
            --account-name $cosmosName `
            --resource-group $resourceGroup `
            --database-name qprisma `
            --name media-metadata `
            --partition-key-path "/id" `
            --output none
        
        if ($LASTEXITCODE -eq 0) {
            Write-Host "  ✓ Container 'media-metadata' creado" -ForegroundColor Green
        }
    }
} else {
    Write-Host "✗ Error al crear Cosmos DB" -ForegroundColor Red
}

# 6. Redis Cache
Write-Host "[6/6] Creando Redis Cache: $redisName" -ForegroundColor Yellow
Write-Host "  (Esto puede tomar 5-10 minutos...)" -ForegroundColor Gray
az redis create `
    --name $redisName `
    --resource-group $resourceGroup `
    --location $location `
    --sku Basic `
    --vm-size c0 `
    --output none

if ($LASTEXITCODE -eq 0) {
    Write-Host "✓ Redis Cache creado" -ForegroundColor Green
} else {
    Write-Host "✗ Error al crear Redis Cache" -ForegroundColor Red
}

Write-Host ""
Write-Host "=" -ForegroundColor Cyan -NoNewline
Write-Host "================================================" -ForegroundColor Cyan
Write-Host "  Obteniendo Credenciales" -ForegroundColor Cyan
Write-Host "=" -ForegroundColor Cyan -NoNewline
Write-Host "================================================" -ForegroundColor Cyan
Write-Host ""

# Obtener credenciales
Write-Host "Obteniendo credenciales de los servicios..." -ForegroundColor Yellow
Write-Host ""

# Storage
$storageConnString = az storage account show-connection-string --name $storageAccount --resource-group $resourceGroup --query connectionString -o tsv
Write-Host "✓ Storage Connection String obtenido" -ForegroundColor Green

# OpenAI
$openaiEndpoint = az cognitiveservices account show --name $openaiName --resource-group $resourceGroup --query properties.endpoint -o tsv
$openaiKey = az cognitiveservices account keys list --name $openaiName --resource-group $resourceGroup --query key1 -o tsv
Write-Host "✓ Azure OpenAI credenciales obtenidas" -ForegroundColor Green

# Search
$searchKey = az search admin-key show --service-name $searchName --resource-group $resourceGroup --query primaryKey -o tsv
Write-Host "✓ Azure AI Search key obtenida" -ForegroundColor Green

# Cosmos
$cosmosConnString = az cosmosdb keys list --name $cosmosName --resource-group $resourceGroup --type connection-strings --query "connectionStrings[0].connectionString" -o tsv
Write-Host "✓ Cosmos DB connection string obtenida" -ForegroundColor Green

# Redis
$redisKey = az redis list-keys --name $redisName --resource-group $resourceGroup --query primaryKey -o tsv
$redisHost = az redis show --name $redisName --resource-group $resourceGroup --query hostName -o tsv
Write-Host "✓ Redis credenciales obtenidas" -ForegroundColor Green

Write-Host ""
Write-Host "=" -ForegroundColor Cyan -NoNewline
Write-Host "================================================" -ForegroundColor Cyan
Write-Host "  Configurando archivo .env" -ForegroundColor Cyan
Write-Host "=" -ForegroundColor Cyan -NoNewline
Write-Host "================================================" -ForegroundColor Cyan
Write-Host ""

# Crear archivo .env
$envPath = Join-Path $PSScriptRoot "..\backend\.env"
$envContent = @"
# Azure OpenAI
AZURE_OPENAI_ENDPOINT=$openaiEndpoint
AZURE_OPENAI_API_KEY=$openaiKey
AZURE_OPENAI_DEPLOYMENT_GPT=gpt-4o
AZURE_OPENAI_DEPLOYMENT_EMBEDDING=text-embedding-3-large
AZURE_OPENAI_API_VERSION=2024-08-01-preview

# Azure Storage
AZURE_STORAGE_CONNECTION_STRING=$storageConnString
AZURE_STORAGE_CONTAINER_NAME=media

# Azure AI Search
AZURE_SEARCH_ENDPOINT=https://$searchName.search.windows.net
AZURE_SEARCH_KEY=$searchKey
AZURE_SEARCH_INDEX_NAME=media-index

# Azure Cosmos DB
COSMOS_CONNECTION_STRING=$cosmosConnString
COSMOS_DATABASE_NAME=qprisma
COSMOS_CONTAINER_NAME=media-metadata

# Redis
REDIS_URL=redis://:$redisKey@$redisHost:6380/0?ssl=True

# Application
APP_ENV=$environment
LOG_LEVEL=INFO
API_PORT=8000
"@

$envContent | Out-File -FilePath $envPath -Encoding UTF8
Write-Host "✓ Archivo .env actualizado en: $envPath" -ForegroundColor Green

Write-Host ""
Write-Host "=" -ForegroundColor Cyan -NoNewline
Write-Host "================================================" -ForegroundColor Cyan
Write-Host "  ¡Setup Completado!" -ForegroundColor Green
Write-Host "=" -ForegroundColor Cyan -NoNewline
Write-Host "================================================" -ForegroundColor Cyan
Write-Host ""

Write-Host "Recursos creados:" -ForegroundColor Yellow
Write-Host "  • Resource Group: $resourceGroup" -ForegroundColor Cyan
Write-Host "  • Storage Account: $storageAccount" -ForegroundColor Cyan
Write-Host "  • Azure OpenAI: $openaiName" -ForegroundColor Cyan
Write-Host "  • Azure AI Search: $searchName" -ForegroundColor Cyan
Write-Host "  • Cosmos DB: $cosmosName" -ForegroundColor Cyan
Write-Host "  • Redis Cache: $redisName" -ForegroundColor Cyan
Write-Host ""

Write-Host "Próximos pasos:" -ForegroundColor Yellow
Write-Host "  1. Reinicia la API para que tome las nuevas credenciales" -ForegroundColor White
Write-Host "     cd backend" -ForegroundColor Gray
Write-Host "     uv run python api/main.py" -ForegroundColor Gray
Write-Host ""
Write-Host "  2. Ejecuta el script de prueba" -ForegroundColor White
Write-Host "     uv run python test_api.py" -ForegroundColor Gray
Write-Host ""

Write-Host "Azure Portal: https://portal.azure.com/#@/resource/subscriptions/$($accountInfo.id)/resourceGroups/$resourceGroup" -ForegroundColor Cyan
Write-Host ""
