# ===========================================================================
# Synapsis Analytics Agent - Windows Quick Start Script (PowerShell)
# ===========================================================================
# Run from PowerShell:   .\start.ps1
# ===========================================================================

$ErrorActionPreference = "Stop"

function Write-Banner {
    Write-Host ""
    Write-Host "  +=============================================+" -ForegroundColor Green
    Write-Host "  |   Synapsis Analytics Agent                  |" -ForegroundColor Green
    Write-Host "  |   Powered by Claude Opus 4.6 + SDK          |" -ForegroundColor Green
    Write-Host "  +=============================================+" -ForegroundColor Green
    Write-Host ""
}

function Write-OK {
    param([string]$msg)
    Write-Host "  [OK] $msg" -ForegroundColor Green
}

function Write-Warn {
    param([string]$msg)
    Write-Host "  [!!] $msg" -ForegroundColor Yellow
}

function Write-Fail {
    param([string]$msg)
    Write-Host "  [FAIL] $msg" -ForegroundColor Red
    exit 1
}

Write-Banner

# ---- Check Docker ----
$dockerFound = $false
try {
    $null = & docker --version 2>&1
    if ($LASTEXITCODE -eq 0) { $dockerFound = $true }
}
catch { }

if (-not $dockerFound) {
    Write-Fail "Docker is not installed. Install Docker Desktop: https://docs.docker.com/desktop/install/windows-install/"
}
Write-OK "Docker detected"

$composeFound = $false
try {
    $null = & docker compose version 2>&1
    if ($LASTEXITCODE -eq 0) { $composeFound = $true }
}
catch { }

if (-not $composeFound) {
    Write-Fail "docker compose (v2) not found. Please update Docker Desktop."
}
Write-OK "Docker Compose detected"

# ---- Check Docker is running ----
$dockerRunning = $false
try {
    $null = & docker info 2>&1
    if ($LASTEXITCODE -eq 0) { $dockerRunning = $true }
}
catch { }

if (-not $dockerRunning) {
    Write-Fail "Docker engine is not running. Please start Docker Desktop first."
}
Write-OK "Docker engine is running"

# ---- Check authentication ----
$authMethod = "none"
$claudeDir = Join-Path $env:USERPROFILE ".claude"

if (Test-Path $claudeDir) {
    $items = Get-ChildItem $claudeDir -ErrorAction SilentlyContinue
    if ($null -ne $items) {
        if ($items.Count -gt 0) {
            $authMethod = "subscription"
            Write-OK "Claude Code subscription detected (~/.claude)"
            Write-Host "  --> Agent will use your existing Claude Code subscription" -ForegroundColor Green
        }
    }
}

# Fallback: check for API key in .env
if ($authMethod -eq "none") {
    if (Test-Path ".env") {
        $envContent = Get-Content ".env" -Raw -ErrorAction SilentlyContinue
        if ($null -ne $envContent) {
            if ($envContent -match "ANTHROPIC_API_KEY=sk-ant-[^x]") {
                $authMethod = "apikey"
                Write-OK "API key found in .env"
            }
        }
    }
}

# No auth at all - guide the user
if ($authMethod -eq "none") {
    Write-Host ""
    Write-Warn "No authentication found."
    Write-Host ""
    Write-Host "  Option A (recommended): Log in with Claude Code" -ForegroundColor White
    Write-Host "    Run: claude login"
    Write-Host "    This uses your existing Claude subscription - no API key needed."
    Write-Host ""
    Write-Host "  Option B: Use an API key" -ForegroundColor White
    Write-Host "    1. Copy .env.example to .env"
    Write-Host "    2. Uncomment and fill in ANTHROPIC_API_KEY"
    Write-Host ""
    $null = Read-Host "  Press Enter once you have set up auth (or Ctrl+C to abort)"

    # Re-check after user action
    if (Test-Path $claudeDir) {
        $items = Get-ChildItem $claudeDir -ErrorAction SilentlyContinue
        if (($null -ne $items) -and ($items.Count -gt 0)) {
            $authMethod = "subscription"
            Write-OK "Claude Code subscription detected"
        }
    }

    if ($authMethod -eq "none") {
        if (Test-Path ".env") {
            $envContent = Get-Content ".env" -Raw -ErrorAction SilentlyContinue
            if (($null -ne $envContent) -and ($envContent -match "ANTHROPIC_API_KEY=sk-ant-[^x]")) {
                $authMethod = "apikey"
                Write-OK "API key found in .env"
            }
        }
    }

    if ($authMethod -eq "none") {
        Write-Fail "Still no authentication found. Please set up auth and try again."
    }
}

# ---- Create .env if it doesn't exist ----
if (-not (Test-Path ".env")) {
    if (Test-Path ".env.example") {
        Copy-Item ".env.example" ".env"
        Write-OK ".env created (optional settings)"
    }
}

# ---- Resolve shared folder (optional host ↔ container file exchange) ----
$sharedMount = ""
try {
    $sharedDir = ""
    # Check .env for SYNAPSIS_SHARED_DIR
    if (Test-Path ".env") {
        $envContent = Get-Content ".env" -Raw -ErrorAction SilentlyContinue
        if ($null -ne $envContent) {
            $match = [regex]::Match($envContent, '(?m)^\s*SYNAPSIS_SHARED_DIR\s*=\s*(.+?)\s*$')
            if ($match.Success) {
                $sharedDir = $match.Groups[1].Value
            }
        }
    }
    if ($sharedDir -and $sharedDir -ne "") {
        # "auto" → platform-appropriate default
        if ($sharedDir -eq "auto") {
            $sharedDir = Join-Path $env:USERPROFILE "Documents\synapsis-shared"
        }
        # Create the directory if it doesn't exist
        if (-not (Test-Path $sharedDir)) {
            New-Item -ItemType Directory -Path $sharedDir -Force | Out-Null
        }
        $sharedDirForward = $sharedDir -replace "\\", "/"
        $sharedMount = "      - ${sharedDirForward}:/workspace/shared"
        Write-OK "Shared folder: $sharedDir <-> /workspace/shared"
    }
}
catch {
    Write-Warn "Could not set up shared folder (continuing without it): $_"
    $sharedMount = ""
}

# ---- Write docker-compose.override.yml with correct Windows path ----
$claudeDirForward = $claudeDir -replace "\\", "/"
$overrideLines = @(
    "# Auto-generated by start.ps1 - sets the correct Windows path for ~/.claude",
    "services:",
    "  synapsis-agent:",
    "    volumes:",
    "      - ${claudeDirForward}:/tmp/.claude-mount:ro",
    "      - synapsis-workspace:/workspace"
)
if ($sharedMount -ne "") {
    $overrideLines += $sharedMount
}
$overrideLines | Set-Content -Path "docker-compose.override.yml" -Encoding UTF8
Write-OK "Generated docker-compose.override.yml with Windows paths"

# ---- Get local IP (skip WSL, Docker, Hyper-V virtual adapters) ----
$localIP = "localhost"
try {
    $ipObj = Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
        Where-Object {
            ($_.InterfaceAlias -notmatch "Loopback|vEthernet|WSL|Docker|Hyper-V") -and
            ($_.PrefixOrigin -ne "WellKnown") -and
            ($_.IPAddress -notmatch "^172\.(1[6-9]|2[0-9]|3[0-1])\.")
        } |
        Select-Object -First 1
    if ($null -ne $ipObj) {
        $localIP = $ipObj.IPAddress
    }
}
catch { }

# ---- Build and launch ----
Write-Host ""
Write-OK "Building and starting Synapsis Analytics Agent..."
Write-Host ""

& docker compose up --build -d

if ($LASTEXITCODE -ne 0) {
    Write-Fail "Docker Compose failed. Check the output above for errors."
}

Write-Host ""
Write-Host "  Synapsis Analytics Agent is running!" -ForegroundColor Green
Write-Host ""

if ($authMethod -eq "subscription") {
    Write-Host "  Auth:            Claude Code subscription" -ForegroundColor White
}
else {
    Write-Host "  Auth:            API key" -ForegroundColor White
}

Write-Host "  Local access:    http://localhost:7777" -ForegroundColor Cyan
Write-Host "  Network access:  http://${localIP}:7777" -ForegroundColor Cyan
Write-Host ""
Write-Host "  Useful commands:" -ForegroundColor White
Write-Host "    docker compose logs -f        # Watch logs"
Write-Host "    docker compose down            # Stop agent"
Write-Host "    docker compose restart         # Restart agent"
Write-Host ""
Write-Host "  Open the URL above in your browser to get started." -ForegroundColor Cyan
Write-Host ""

# ---- Windows Firewall guidance for network access ----
$fwRuleExists = $false
try {
    $rule = Get-NetFirewallRule -DisplayName "Synapsis Agent" -ErrorAction SilentlyContinue
    if ($null -ne $rule) { $fwRuleExists = $true }
}
catch { }

if (-not $fwRuleExists) {
    Write-Host "  Network Access:" -ForegroundColor Yellow
    Write-Host "  To let other devices on your network reach the agent, run this" -ForegroundColor Yellow
    Write-Host "  command once in an elevated (Admin) PowerShell:" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "    New-NetFirewallRule -DisplayName 'Synapsis Agent' -Direction Inbound -LocalPort 7777 -Protocol TCP -Action Allow" -ForegroundColor White
    Write-Host ""
}
