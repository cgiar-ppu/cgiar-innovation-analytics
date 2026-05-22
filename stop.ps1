# Stop Synapsis Analytics Agent
Write-Host "Stopping Synapsis Analytics Agent..." -ForegroundColor Yellow
docker compose down
Write-Host "Agent has been stopped." -ForegroundColor Green
