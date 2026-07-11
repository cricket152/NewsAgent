# Start local RSSHub container for news-agent
# Ensures RSSHub is healthy on http://localhost:1200 before returning.

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# Resolve project root (parent of the scripts directory)
$projectRoot = Split-Path -Parent $PSScriptRoot

# Verify Docker engine is running
try {
    docker info 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Write-Error "Docker engine is not running. Start Docker Desktop and retry."
        exit 1
    }
} catch {
    Write-Error "Docker is not installed or not available. Install Docker Desktop from https://www.docker.com/products/docker-desktop/"
    exit 1
}

Write-Host "Starting RSSHub container..."

docker compose -f "$projectRoot\docker-compose.yml" up -d
if ($LASTEXITCODE -ne 0) {
    Write-Error "Failed to start RSSHub container. Check docker compose logs for details."
    exit 1
}

Write-Host "Waiting for RSSHub healthcheck..."

$maxAttempts = 30
for ($i = 1; $i -le $maxAttempts; $i++) {
    Start-Sleep -Seconds 1

    $healthStatus = docker inspect --format='{{.State.Health.Status}}' news-agent-rsshub 2>&1
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Container not ready yet (attempt $i/$maxAttempts)..."
        continue
    }

    $healthStatus = $healthStatus.Trim()

    if ($healthStatus -eq "healthy") {
        Write-Host "RSSHub is up at http://localhost:1200"
        exit 0
    } elseif ($healthStatus -eq "unhealthy") {
        Write-Error "RSSHub container is unhealthy. Check logs: docker logs news-agent-rsshub"
        exit 1
    }

    Write-Host "Status: $healthStatus (attempt $i/$maxAttempts)..."
}

Write-Error "RSSHub did not become healthy within $maxAttempts seconds. Check logs: docker logs news-agent-rsshub"
exit 1
