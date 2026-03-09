param(
    [Parameter(Mandatory = $true)]
    [string]$Org,

    [string]$Enterprise,

    [ValidateSet("organization", "enterprise")]
    [string]$Scope = "organization",

    [ValidateSet("aggregate", "users")]
    [string]$ReportType = "aggregate",

    [string]$Day,

    [switch]$Latest28Day,

    [string]$Token
)

$ErrorActionPreference = "Stop"

if (-not $Token) {
    $Token = $env:GITHUB_TOKEN
}

if (-not $Token) {
    throw "Provide -Token or set GITHUB_TOKEN."
}

if ($Scope -eq "enterprise" -and [string]::IsNullOrWhiteSpace($Enterprise)) {
    throw "For enterprise scope, provide -Enterprise."
}

if (-not $Latest28Day -and [string]::IsNullOrWhiteSpace($Day)) {
    throw "Provide -Day (YYYY-MM-DD) or use -Latest28Day."
}

$reportSegment = if ($ReportType -eq "users") { "users" } else { if ($Scope -eq "enterprise") { "enterprise" } else { "organization" } }

$basePath = if ($Scope -eq "enterprise") {
    "/enterprises/$Enterprise/copilot/metrics/reports"
} else {
    "/orgs/$Org/copilot/metrics/reports"
}

$endpoint = if ($Latest28Day) {
    "$basePath/$reportSegment-28-day/latest"
} else {
    "$basePath/$reportSegment-1-day?day=$Day"
}

$headers = @{
    "Accept"               = "application/vnd.github+json"
    "Authorization"        = "Bearer $Token"
    "X-GitHub-Api-Version" = "2022-11-28"
}

$url = "https://api.github.com$endpoint"
Write-Host "Requesting: $url"

$response = Invoke-RestMethod -Uri $url -Headers $headers -Method Get

[pscustomobject]@{
    Scope          = $Scope
    ReportType     = $ReportType
    ReportStartDay = $response.report_start_day
    ReportEndDay   = $response.report_end_day
    ReportDay      = $response.report_day
    DownloadLinks  = ($response.download_links -join "`n")
} | Format-List
