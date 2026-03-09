$ErrorActionPreference = "Stop"

$raw = [Console]::In.ReadToEnd()

try {
    $payload = if ([string]::IsNullOrWhiteSpace($raw)) { @{} } else { $raw | ConvertFrom-Json }
} catch {
    $payload = @{}
}

$toolName = [string]($payload.toolName)
$toolArgsRaw = $payload.toolArgs
$command = ""

if ($toolArgsRaw -is [string]) {
    try {
        $parsedArgs = $toolArgsRaw | ConvertFrom-Json
        $command = [string]$parsedArgs.command
    } catch {
        $command = [string]$toolArgsRaw
    }
} else {
    $command = [string]$toolArgsRaw
}

$text = ("$toolName $command").ToLowerInvariant()
$patterns = @(
    "git\s+reset\s+--hard",
    "git\s+checkout\s+--",
    "rm\s+-rf\s+/",
    "format\s+[a-z]:",
    "drop\s+table"
)

$blocked = $false
foreach ($pattern in $patterns) {
    if ($text -match $pattern) {
        $blocked = $true
        break
    }
}

if ($blocked) {
    @{
        permissionDecision = "deny"
        permissionDecisionReason = "Blocked by QPrisma Copilot guardrail policy"
    } | ConvertTo-Json -Compress
} else {
    @{
        permissionDecision = "allow"
    } | ConvertTo-Json -Compress
}
