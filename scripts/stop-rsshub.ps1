# Stop local RSSHub container for news-agent

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# Resolve project root (parent of the scripts directory)
$projectRoot = Split-Path -Parent $PSScriptRoot

docker compose -f "$projectRoot\docker-compose.yml" down
if ($LASTEXITCODE -ne 0) {
    Write-Warning "docker compose down returned non-zero exit code. Container may already be stopped."
}

Write-Host "RSSHub stopped"
exit 0
