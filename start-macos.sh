#!/usr/bin/env bash
set -euo pipefail

# ---------------------------------------------------------------------------
# Synapsis Analytics Agent — Native macOS Launcher
# ---------------------------------------------------------------------------

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

info()  { echo -e "${GREEN}[INFO]${NC} $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $*"; }
error() { echo -e "${RED}[ERROR]${NC} $*"; exit 1; }

# ---- Prerequisites -------------------------------------------------------

# Python 3.11+
if ! command -v python3 &>/dev/null; then
    error "Python 3 not found. Install via: brew install python@3.11"
fi
PY_VER=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
PY_MAJOR=$(echo "$PY_VER" | cut -d. -f1)
PY_MINOR=$(echo "$PY_VER" | cut -d. -f2)
if [ "$PY_MAJOR" -lt 3 ] || { [ "$PY_MAJOR" -eq 3 ] && [ "$PY_MINOR" -lt 11 ]; }; then
    error "Python 3.11+ required (found $PY_VER). Install via: brew install python@3.11"
fi
info "Python $PY_VER ✓"

# cliclick
if ! command -v cliclick &>/dev/null; then
    warn "cliclick not found — required for mouse/keyboard control"
    read -rp "Install via Homebrew? [Y/n] " answer
    if [[ "${answer:-Y}" =~ ^[Yy]$ ]]; then
        brew install cliclick
    else
        error "cliclick is required. Install manually: brew install cliclick"
    fi
fi
info "cliclick $(cliclick -V 2>&1 | head -1) ✓"

# Test Accessibility permissions
if ! cliclick m:. 2>/dev/null; then
    warn "Accessibility permissions may not be granted."
    warn "Go to: System Settings → Privacy & Security → Accessibility"
    warn "Grant access to Terminal.app (or your terminal emulator)."
fi

# Node.js (for frontend build)
if ! command -v node &>/dev/null; then
    warn "Node.js not found — needed to build the frontend"
    warn "Install via: brew install node"
fi

# ---- Auth Detection -------------------------------------------------------

if [ -n "${ANTHROPIC_API_KEY:-}" ]; then
    info "Auth: API key detected"
elif [ -d "$HOME/.claude" ]; then
    info "Auth: Claude subscription credentials detected (~/.claude)"
else
    warn "No auth detected. Set ANTHROPIC_API_KEY or log in via 'claude' CLI."
fi

# ---- Workspace Setup ------------------------------------------------------

WORKSPACE="${SYNAPSIS_WORKSPACE:-$HOME/workspace}"
for dir in uploads analysis outputs scripts; do
    mkdir -p "$WORKSPACE/$dir"
done
info "Workspace: $WORKSPACE"

# ---- Python Dependencies --------------------------------------------------

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if ! python3 -c "import fastapi" 2>/dev/null; then
    info "Installing Python dependencies..."
    pip3 install -r "$SCRIPT_DIR/requirements-macos.txt"
else
    info "Python dependencies already installed ✓"
fi

# ---- Frontend Build -------------------------------------------------------

if [ -d "$SCRIPT_DIR/frontend" ]; then
    if [ ! -d "$SCRIPT_DIR/static" ] || [ "$SCRIPT_DIR/frontend/src" -nt "$SCRIPT_DIR/static/index.html" ] 2>/dev/null; then
        if command -v node &>/dev/null; then
            info "Building frontend..."
            (cd "$SCRIPT_DIR/frontend" && npm install --silent && npm run build --silent)
            # Vite outputs to frontend/dist — copy to static/ for FastAPI
            if [ -d "$SCRIPT_DIR/frontend/dist" ]; then
                rm -rf "$SCRIPT_DIR/static"
                cp -r "$SCRIPT_DIR/frontend/dist" "$SCRIPT_DIR/static"
            fi
            info "Frontend built ✓"
        else
            warn "Skipping frontend build (Node.js not installed)"
        fi
    else
        info "Frontend up to date ✓"
    fi
fi

# ---- Prevent Display Sleep ------------------------------------------------

caffeinate -d &
CAFFEINATE_PID=$!
trap "kill $CAFFEINATE_PID 2>/dev/null" EXIT
info "Display sleep prevention active (caffeinate PID $CAFFEINATE_PID)"

# ---- Find Available Port --------------------------------------------------

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
export SYNAPSIS_PORT

# ---- Parse launch flags ---------------------------------------------------

RUN_TESTS=false
REMAINING_ARGS=()
for arg in "$@"; do
    case "$arg" in
        --run-tests)
            RUN_TESTS=true
            ;;
        *)
            REMAINING_ARGS+=("$arg")
            ;;
    esac
done

# Also honor the environment variable
if [ "${SYNAPSIS_AUTO_TEST:-false}" = "true" ]; then
    RUN_TESTS=true
fi

# ---- Launch ---------------------------------------------------------------

info "Starting Synapsis Agent on port ${SYNAPSIS_PORT}..."
export SYNAPSIS_PLATFORM=macos

# ---- Post-launch test hook -----------------------------------------------

if [ "$RUN_TESTS" = "true" ]; then
    TEST_RUNNER="$SCRIPT_DIR/tests/run_post_launch_tests.sh"
    if [ -x "$TEST_RUNNER" ]; then
        REPORT_DIR="${HOME}/workspace/test-reports"
        info "Post-launch tests running in background. Report: ${REPORT_DIR}/latest-test-report.txt"
        "$TEST_RUNNER" --port "$SYNAPSIS_PORT" --report-dir "$REPORT_DIR" &
        disown
    else
        warn "Test runner not found or not executable: $TEST_RUNNER"
    fi
fi

exec python3 "$SCRIPT_DIR/app.py"
