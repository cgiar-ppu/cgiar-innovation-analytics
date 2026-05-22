#!/usr/bin/env bash
# ===========================================================================
# Synapsis Analytics Agent – Quick Start Script
# ===========================================================================
# This script handles everything: checks prerequisites, detects your
# Claude Code subscription, builds the Docker image, and launches the agent.
# ===========================================================================

set -euo pipefail

BOLD="\033[1m"
GREEN="\033[32m"
YELLOW="\033[33m"
RED="\033[31m"
CYAN="\033[36m"
RESET="\033[0m"

banner() {
    echo -e "${GREEN}${BOLD}"
    echo "  ╔═══════════════════════════════════════════╗"
    echo "  ║  Synapsis Analytics Agent                 ║"
    echo "  ║  Powered by Claude Opus 4.6 + SDK         ║"
    echo "  ╚═══════════════════════════════════════════╝"
    echo -e "${RESET}"
}

info()  { echo -e "  ${GREEN}✓${RESET} $1"; }
warn()  { echo -e "  ${YELLOW}⚠${RESET} $1"; }
fail()  { echo -e "  ${RED}✗${RESET} $1"; exit 1; }

banner

# ---- Check Docker ----
if ! command -v docker &>/dev/null; then
    fail "Docker is not installed. Please install Docker Desktop or Docker Engine first."
fi
if ! docker compose version &>/dev/null 2>&1; then
    fail "docker compose (v2) not found. Please update Docker."
fi
info "Docker detected"

# ---- Check authentication ----
AUTH_METHOD="none"

# Check for Claude Code subscription (preferred)
if [ -d "$HOME/.claude" ] && [ "$(ls -A "$HOME/.claude" 2>/dev/null)" ]; then
    AUTH_METHOD="subscription"
    info "Claude Code subscription detected (~/.claude)"
    echo -e "  ${GREEN}→${RESET} Agent will use your existing Claude Code subscription"
fi

# Fallback: check for API key in .env
if [ "$AUTH_METHOD" = "none" ]; then
    if [ -f .env ] && grep -q "ANTHROPIC_API_KEY" .env 2>/dev/null && ! grep -q "sk-ant-xxx" .env 2>/dev/null; then
        AUTH_METHOD="apikey"
        info "API key found in .env"
    fi
fi

# No auth at all — guide the user
if [ "$AUTH_METHOD" = "none" ]; then
    echo ""
    echo -e "  ${YELLOW}No authentication found.${RESET}"
    echo ""
    echo -e "  ${BOLD}Option A (recommended):${RESET} Log in with Claude Code"
    echo "    Run: claude login"
    echo "    This uses your existing Claude subscription — no API key needed."
    echo ""
    echo -e "  ${BOLD}Option B:${RESET} Use an API key"
    echo "    1. Copy .env.example to .env"
    echo "    2. Paste your ANTHROPIC_API_KEY"
    echo ""
    read -rp "  Press Enter once you've set up auth (or Ctrl+C to abort)… "

    # Re-check after user action
    if [ -d "$HOME/.claude" ] && [ "$(ls -A "$HOME/.claude" 2>/dev/null)" ]; then
        AUTH_METHOD="subscription"
        info "Claude Code subscription detected"
    elif [ -f .env ] && grep -q "ANTHROPIC_API_KEY" .env 2>/dev/null && ! grep -q "sk-ant-xxx" .env 2>/dev/null; then
        AUTH_METHOD="apikey"
        info "API key found in .env"
    else
        fail "Still no authentication found. Please set up auth and try again."
    fi
fi

# ---- Extract OAuth credentials from macOS Keychain (for Docker) ----
# On macOS, Claude Code stores OAuth tokens in the Keychain rather than files.
# Docker containers can't access the macOS Keychain, so we extract and pass
# the tokens via environment variables that the CLI recognizes.
if [ "$(uname)" = "Darwin" ] && [ "$AUTH_METHOD" = "subscription" ]; then
    OAUTH_JSON=$(security find-generic-password -s "Claude Code-credentials" -w 2>/dev/null || echo "")
    if [ -n "$OAUTH_JSON" ]; then
        CLAUDE_CODE_OAUTH_TOKEN=$(echo "$OAUTH_JSON" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('claudeAiOauth',{}).get('accessToken',''))" 2>/dev/null || echo "")
        CLAUDE_CODE_OAUTH_REFRESH_TOKEN=$(echo "$OAUTH_JSON" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('claudeAiOauth',{}).get('refreshToken',''))" 2>/dev/null || echo "")
        export CLAUDE_CODE_OAUTH_TOKEN CLAUDE_CODE_OAUTH_REFRESH_TOKEN
        if [ -n "$CLAUDE_CODE_OAUTH_TOKEN" ]; then
            info "Extracted OAuth credentials from macOS Keychain"
        else
            warn "Could not parse OAuth token from Keychain entry"
        fi
    else
        warn "Could not read Claude Code credentials from macOS Keychain"
        warn "If auth fails inside Docker, run: claude login"
    fi
fi

# ---- Create .env if it doesn't exist (for optional overrides) ----
if [ ! -f .env ]; then
    if [ -f .env.example ]; then
        cp .env.example .env
        info ".env created (optional settings — auth comes from your subscription)"
    fi
fi

# ---- Generate unique session ID ----
SESSION_ID=$(date +%s | tail -c 5)
PROJECT_NAME="synapsis-${SESSION_ID}"

# ---- Find available ports ----
port_in_use() {
    lsof -iTCP:"$1" -sTCP:LISTEN &>/dev/null
}

find_available_port() {
    local port="$1"
    while port_in_use "$port"; do
        warn "Port $port is in use, trying $((port + 1))..." >&2
        port=$((port + 1))
    done
    echo "$port"
}

SYNAPSIS_PORT=$(find_available_port "${SYNAPSIS_PORT:-7777}")
SYNAPSIS_VNC_PORT=$(find_available_port "${SYNAPSIS_VNC_PORT:-6080}")
export SYNAPSIS_PORT SYNAPSIS_VNC_PORT

info "Session:     ${SESSION_ID}"
info "Web UI port: ${SYNAPSIS_PORT}"
info "VNC port:    ${SYNAPSIS_VNC_PORT}"

# ---- Resolve shared folder (optional host ↔ container file exchange) ----
SHARED_MOUNT=""
if [ -f .env ]; then
    SHARED_DIR=$(grep -E '^\s*SYNAPSIS_SHARED_DIR\s*=' .env 2>/dev/null | head -1 | sed 's/^[^=]*=\s*//' | xargs || true)
fi
if [ -n "${SHARED_DIR:-}" ]; then
    # "auto" → platform-appropriate default
    if [ "$SHARED_DIR" = "auto" ]; then
        SHARED_DIR="$HOME/Documents/synapsis-shared"
    fi
    # Create if missing (fail gracefully)
    if mkdir -p "$SHARED_DIR" 2>/dev/null; then
        SHARED_MOUNT="      - ${SHARED_DIR}:/workspace/shared"
        info "Shared folder: ${SHARED_DIR} ↔ /workspace/shared"
    else
        warn "Could not create shared folder ${SHARED_DIR} — continuing without it"
    fi
fi

# ---- Write docker-compose.override.yml (only if not on Windows / start.ps1) ----
if [ "$(uname)" = "Darwin" ] || [ "$(uname)" = "Linux" ]; then
    OVERRIDE_LINES="# Auto-generated by start.sh
services:
  synapsis-agent:
    volumes:
      - ${HOME}/.claude:/tmp/.claude-mount:ro
      - synapsis-workspace:/workspace"
    if [ -n "$SHARED_MOUNT" ]; then
        OVERRIDE_LINES="${OVERRIDE_LINES}
${SHARED_MOUNT}"
    fi
    echo "$OVERRIDE_LINES" > docker-compose.override.yml
    info "Generated docker-compose.override.yml"
fi

# ---- Ensure shared workspace volume exists ----
docker volume create synapsis-agent-workspace &>/dev/null || true

# ---- Get local IP for network access ----
LOCAL_IP=$(ipconfig getifaddr en0 2>/dev/null || hostname -I 2>/dev/null | awk '{print $1}' || echo "localhost")

echo ""
info "Building and starting Synapsis Analytics Agent (session ${SESSION_ID})..."
echo ""

# ---- Build & launch with unique project name ----
docker compose -p "${PROJECT_NAME}" up --build -d

echo ""
echo -e "${GREEN}${BOLD}  Synapsis Analytics Agent is running!${RESET}"
echo ""
if [ "$AUTH_METHOD" = "subscription" ]; then
    echo -e "  ${BOLD}Auth:${RESET}            Claude Code subscription"
else
    echo -e "  ${BOLD}Auth:${RESET}            API key"
fi
echo -e "  ${BOLD}Session:${RESET}         ${SESSION_ID}"
echo -e "  ${BOLD}Local access:${RESET}    http://localhost:${SYNAPSIS_PORT}"
echo -e "  ${BOLD}Network access:${RESET}  http://${LOCAL_IP}:${SYNAPSIS_PORT}"
echo -e "  ${BOLD}VNC access:${RESET}      http://localhost:${SYNAPSIS_VNC_PORT}"
echo ""
echo -e "  ${BOLD}Manage this session:${RESET}"
echo "    docker compose -p ${PROJECT_NAME} logs -f     # Watch logs"
echo "    docker compose -p ${PROJECT_NAME} down        # Stop this session"
echo "    docker compose -p ${PROJECT_NAME} restart     # Restart this session"
echo ""
echo -e "  ${BOLD}Manage all sessions:${RESET}"
echo "    docker ps --filter 'name=synapsis'            # List all running agents"
echo "    ./stop-all.sh                                 # Stop all agents"
echo ""
echo -e "  ${CYAN}Open the URL above in your browser to get started.${RESET}"
echo ""
