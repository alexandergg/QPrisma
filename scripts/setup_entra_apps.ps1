<#
.SYNOPSIS
    Creates Microsoft Entra ID App Registrations for QPrisma (backend API + frontend SPA).

.DESCRIPTION
    This script uses Azure CLI to:
    1. Create a Backend API app registration with an exposed scope (access_as_user)
    2. Create a Frontend SPA app registration with redirect URIs
    3. Grant the frontend app permission to the backend API scope
    4. Output all required environment variables

.PREREQUISITES
    - Azure CLI installed and logged in (az login)
    - Permissions: Application Administrator or Global Administrator in your Entra ID tenant

.PARAMETER TenantId
    Your Microsoft Entra ID tenant ID. If omitted, uses the current az login tenant.

.PARAMETER FrontendRedirectUris
    Comma-separated redirect URIs for the frontend SPA (default: http://localhost:3000).

.EXAMPLE
    .\setup_entra_apps.ps1
    .\setup_entra_apps.ps1 -TenantId "your-tenant-id" -FrontendRedirectUris "http://localhost:3000,https://qprisma.example.com"
#>

param(
    [string]$TenantId = "",
    [string]$FrontendRedirectUris = "http://localhost:3000"
)

$ErrorActionPreference = "Stop"

Write-Host "`n=== QPrisma Entra ID App Registration Setup ===" -ForegroundColor Cyan

# Resolve tenant
if (-not $TenantId) {
    $TenantId = az account show --query tenantId -o tsv
    Write-Host "Using current tenant: $TenantId"
}

# ---------------------------------------------------------------------------
# 1. Backend API App Registration
# ---------------------------------------------------------------------------
Write-Host "`n--- Step 1: Creating Backend API app registration ---" -ForegroundColor Yellow

$backendAppName = "QPrisma Backend API"

# Create the app registration
$backendApp = az ad app create `
    --display-name $backendAppName `
    --sign-in-audience "AzureADMyOrg" `
    --query "{appId: appId, id: id}" `
    -o json | ConvertFrom-Json

$backendClientId = $backendApp.appId
$backendObjectId = $backendApp.id

Write-Host "  Created: $backendAppName"
Write-Host "  Client ID: $backendClientId"

# Set the Application ID URI
$identifierUri = "api://$backendClientId"
az ad app update --id $backendObjectId --identifier-uris $identifierUri | Out-Null
Write-Host "  Identifier URI: $identifierUri"

# Expose a scope: access_as_user (delegated permission)
$scopeId = [guid]::NewGuid().ToString()
$apiPermissions = @{
    oauth2PermissionScopes = @(
        @{
            adminConsentDescription = "Allow the application to access QPrisma API on behalf of the signed-in user."
            adminConsentDisplayName = "Access QPrisma API"
            id                      = $scopeId
            isEnabled               = $true
            type                    = "User"
            userConsentDescription  = "Allow the application to access QPrisma API on your behalf."
            userConsentDisplayName  = "Access QPrisma API"
            value                   = "access_as_user"
        }
    )
} | ConvertTo-Json -Depth 5 -Compress

$tempFile = [System.IO.Path]::GetTempFileName()
$apiPermissions | Out-File -FilePath $tempFile -Encoding utf8
az ad app update --id $backendObjectId --set api=@$tempFile | Out-Null
Remove-Item $tempFile
Write-Host "  Exposed scope: $identifierUri/access_as_user"

# Create a service principal for the backend app
az ad sp create --id $backendClientId 2>$null | Out-Null
Write-Host "  Service principal created"

# ---------------------------------------------------------------------------
# 2. Frontend SPA App Registration
# ---------------------------------------------------------------------------
Write-Host "`n--- Step 2: Creating Frontend SPA app registration ---" -ForegroundColor Yellow

$frontendAppName = "QPrisma Frontend SPA"

# Build redirect URI list
$redirectUriList = $FrontendRedirectUris -split "," | ForEach-Object { $_.Trim() }
$redirectUriArgs = ($redirectUriList | ForEach-Object { $_ }) -join " "

# Create the SPA app registration
$frontendApp = az ad app create `
    --display-name $frontendAppName `
    --sign-in-audience "AzureADMyOrg" `
    --query "{appId: appId, id: id}" `
    -o json | ConvertFrom-Json

$frontendClientId = $frontendApp.appId
$frontendObjectId = $frontendApp.id

Write-Host "  Created: $frontendAppName"
Write-Host "  Client ID: $frontendClientId"

# Configure SPA redirect URIs
$spaConfig = @{ redirectUris = $redirectUriList } | ConvertTo-Json -Compress
$tempFile = [System.IO.Path]::GetTempFileName()
$spaConfig | Out-File -FilePath $tempFile -Encoding utf8
az ad app update --id $frontendObjectId --set spa=@$tempFile | Out-Null
Remove-Item $tempFile
Write-Host "  Redirect URIs: $($redirectUriList -join ', ')"

# ---------------------------------------------------------------------------
# 3. Grant Frontend → Backend API Permission
# ---------------------------------------------------------------------------
Write-Host "`n--- Step 3: Granting API permission to frontend app ---" -ForegroundColor Yellow

az ad app permission add `
    --id $frontendObjectId `
    --api $backendClientId `
    --api-permissions "$scopeId=Scope" | Out-Null

Write-Host "  Granted: $identifierUri/access_as_user (delegated)"

# Admin consent (optional — requires admin role)
Write-Host "`n  Attempting admin consent..." -ForegroundColor Gray
try {
    az ad app permission admin-consent --id $frontendObjectId 2>$null | Out-Null
    Write-Host "  Admin consent granted" -ForegroundColor Green
} catch {
    Write-Host "  Admin consent skipped (grant manually in Azure Portal > Enterprise Applications)" -ForegroundColor DarkYellow
}

# ---------------------------------------------------------------------------
# 4. Output Environment Variables
# ---------------------------------------------------------------------------
$apiScope = "$identifierUri/access_as_user"
$authority = "https://login.microsoftonline.com/$TenantId"

Write-Host "`n=== Setup Complete ===" -ForegroundColor Green
Write-Host "`n--- Backend Environment Variables (.env) ---" -ForegroundColor Cyan
Write-Host "ENTRA_TENANT_ID=$TenantId"
Write-Host "ENTRA_CLIENT_ID=$backendClientId"
Write-Host "ENTRA_API_SCOPE=$apiScope"

Write-Host "`n--- Frontend Environment Variables (.env.local) ---" -ForegroundColor Cyan
Write-Host "NEXT_PUBLIC_ENTRA_CLIENT_ID=$frontendClientId"
Write-Host "NEXT_PUBLIC_ENTRA_AUTHORITY=$authority"
Write-Host "NEXT_PUBLIC_ENTRA_REDIRECT_URI=$($redirectUriList[0])"
Write-Host "NEXT_PUBLIC_ENTRA_API_SCOPE=$apiScope"

Write-Host "`n--- Key Vault Secrets (for production) ---" -ForegroundColor Cyan
Write-Host "az keyvault secret set --vault-name <vault> --name entra-tenant-id --value $TenantId"
Write-Host "az keyvault secret set --vault-name <vault> --name entra-client-id --value $backendClientId"
Write-Host "az keyvault secret set --vault-name <vault> --name entra-api-scope --value $apiScope"

Write-Host "`n--- App Registration Summary ---" -ForegroundColor Cyan
Write-Host "Backend API:   $backendAppName (Client ID: $backendClientId)"
Write-Host "Frontend SPA:  $frontendAppName (Client ID: $frontendClientId)"
Write-Host "Tenant:        $TenantId"
Write-Host "API Scope:     $apiScope"
Write-Host ""
