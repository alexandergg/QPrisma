$ErrorActionPreference = "Stop"

$serviceName = if ($env:AZD_SERVICE_NAME) { $env:AZD_SERVICE_NAME } else { "qprisma-video-agent" }
$requireIdentity = $env:REQUIRE_AGENT_IDENTITY_RBAC -match "^(1|true|yes|on)$"

Write-Host "Running postdeploy hook for $serviceName..."

try {
    $agentJson = azd ai agent show $serviceName 2>$null | ConvertFrom-Json
    $agentPrincipalId = $agentJson.instance_identity.principal_id
} catch {
    $agentPrincipalId = $null
}

if (-not $agentPrincipalId) {
    $message = "Hosted agent runtime identity is not available yet; skipping downstream RBAC assignment."
    if ($requireIdentity) {
        Write-Error $message
        exit 1
    }

    Write-Warning $message
    exit 0
}

Write-Host "Hosted agent runtime identity detected: $($agentPrincipalId.Substring(0, [Math]::Min(8, $agentPrincipalId.Length)))..."

if ($env:AZURE_SUBSCRIPTION_ID -and $env:AZURE_RESOURCE_GROUP -and $env:AZURE_STORAGE_ACCOUNT_NAME) {
    $storageScope = "/subscriptions/$env:AZURE_SUBSCRIPTION_ID/resourceGroups/$env:AZURE_RESOURCE_GROUP/providers/Microsoft.Storage/storageAccounts/$env:AZURE_STORAGE_ACCOUNT_NAME"
    Write-Host "Assigning Storage Blob Data Contributor to hosted agent identity..."

    az role assignment create `
        --assignee-object-id $agentPrincipalId `
        --assignee-principal-type ServicePrincipal `
        --role "ba92f5b4-2d11-453d-a403-e96b0029c9fe" `
        --scope $storageScope `
        --only-show-errors `
        --output none 2>$null

    if ($LASTEXITCODE -ne 0) {
        Write-Host "Storage role assignment may already exist for $serviceName."
    }
} else {
    Write-Host "Storage account metadata is incomplete; skipping Storage Blob Data Contributor assignment."
}

Write-Host "Postdeploy hook complete."
