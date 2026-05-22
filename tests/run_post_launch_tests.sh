#!/usr/bin/env bash
set -euo pipefail

# ---------------------------------------------------------------------------
# Synapsis Post-Launch Test Runner
#
# Runs unit and integration tests after the server has started.
# Generates timestamped reports to disk. Designed to run in the background
# without interfering with the server process.
#
# Usage:
#   ./tests/run_post_launch_tests.sh [--port PORT] [--report-dir DIR]
#
# Environment variables:
#   SYNAPSIS_PORT   - Server port (default: 7777)
#   TEST_BASE_URL   - Override base URL for integration tests
#   TEST_WS_URL     - Override WebSocket URL for integration tests
# ---------------------------------------------------------------------------

# ---- Error trap: ensure the script always finishes ----------------------

OVERALL_EXIT=0

trap 'true' ERR

on_exit() {
    if [ "$OVERALL_EXIT" -ne 0 ]; then
        echo ""
        echo "============================================================"
        echo "  POST-LAUNCH TESTS: FAILURES DETECTED (exit code $OVERALL_EXIT)"
        echo "============================================================"
    fi
    exit "$OVERALL_EXIT"
}
trap on_exit EXIT

# ---- Parse arguments ----------------------------------------------------

PORT="${SYNAPSIS_PORT:-7777}"
REPORT_DIR="${HOME}/workspace/test-reports"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --port)
            PORT="$2"
            shift 2
            ;;
        --report-dir)
            REPORT_DIR="$2"
            shift 2
            ;;
        *)
            echo "[WARN] Unknown argument: $1"
            shift
            ;;
    esac
done

# ---- Derived variables --------------------------------------------------

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
TIMESTAMP="$(date '+%Y%m%d-%H%M%S')"
REPORT_FILE="${REPORT_DIR}/test-report-${TIMESTAMP}.txt"
LATEST_LINK="${REPORT_DIR}/latest-test-report.txt"

export TEST_BASE_URL="${TEST_BASE_URL:-http://localhost:${PORT}}"
export TEST_WS_URL="${TEST_WS_URL:-ws://localhost:${PORT}/ws/chat}"

# ---- Ensure report directory exists -------------------------------------

mkdir -p "$REPORT_DIR"

# ---- Check for pytest ---------------------------------------------------

if ! python3 -m pytest --version &>/dev/null; then
    echo "[ERROR] pytest is not installed. Install via: pip3 install pytest"
    echo "pytest not found -- aborting test run" > "$REPORT_FILE"
    OVERALL_EXIT=1
    exit 1
fi

# ---- Git info (best-effort) ---------------------------------------------

GIT_BRANCH="unknown"
GIT_COMMIT="unknown"
if command -v git &>/dev/null && git -C "$PROJECT_DIR" rev-parse --git-dir &>/dev/null 2>&1; then
    GIT_BRANCH="$(git -C "$PROJECT_DIR" rev-parse --abbrev-ref HEAD 2>/dev/null || echo 'unknown')"
    GIT_COMMIT="$(git -C "$PROJECT_DIR" rev-parse --short HEAD 2>/dev/null || echo 'unknown')"
fi

# ---- Write report header ------------------------------------------------

{
    echo "============================================================"
    echo "  Synapsis Post-Launch Test Report"
    echo "============================================================"
    echo ""
    echo "Timestamp   : $(date '+%Y-%m-%d %H:%M:%S %Z')"
    echo "Server Port : $PORT"
    echo "Base URL    : $TEST_BASE_URL"
    echo "WS URL      : $TEST_WS_URL"
    echo "Git Branch  : $GIT_BRANCH"
    echo "Git Commit  : $GIT_COMMIT"
    echo "Python      : $(python3 --version 2>&1)"
    echo "pytest      : $(python3 -m pytest --version 2>&1 | head -1)"
    echo ""
} > "$REPORT_FILE"

# ---- Wait for server health ---------------------------------------------

echo "[INFO] Waiting for server on port $PORT to become healthy..."

HEALTH_URL="http://localhost:${PORT}/api/health"
MAX_WAIT=60
ELAPSED=0

while [ "$ELAPSED" -lt "$MAX_WAIT" ]; do
    if curl -sf "$HEALTH_URL" &>/dev/null; then
        echo "[INFO] Server is healthy after ${ELAPSED}s."
        {
            echo "Health Check : PASSED (${ELAPSED}s)"
            echo ""
        } >> "$REPORT_FILE"
        break
    fi
    sleep 2
    ELAPSED=$((ELAPSED + 2))
done

if [ "$ELAPSED" -ge "$MAX_WAIT" ]; then
    echo "[ERROR] Server did not become healthy within ${MAX_WAIT}s. Aborting tests."
    {
        echo "Health Check : FAILED (timeout after ${MAX_WAIT}s)"
        echo ""
        echo "ABORTED: Server not healthy. No tests were run."
    } >> "$REPORT_FILE"
    ln -sf "$REPORT_FILE" "$LATEST_LINK"
    OVERALL_EXIT=1
    exit 1
fi

# ---- Counters -----------------------------------------------------------

UNIT_PASSED=0
UNIT_FAILED=0
UNIT_ERRORS=0
INTEGRATION_PASSED=0
INTEGRATION_FAILED=0
INTEGRATION_ERRORS=0

# ---- Helper: parse pytest summary line ----------------------------------

parse_pytest_summary() {
    # Expects the raw pytest output as $1
    # Sets PARSED_PASSED, PARSED_FAILED, PARSED_ERRORS
    local output="$1"
    PARSED_PASSED=0
    PARSED_FAILED=0
    PARSED_ERRORS=0

    # Match lines like "5 passed", "2 failed", "1 error"
    local summary_line
    summary_line="$(echo "$output" | grep -E '(passed|failed|error)' | tail -1)" || true

    if [ -n "$summary_line" ]; then
        PARSED_PASSED="$(echo "$summary_line" | grep -oE '[0-9]+ passed' | grep -oE '[0-9]+' || echo 0)"
        PARSED_FAILED="$(echo "$summary_line" | grep -oE '[0-9]+ failed' | grep -oE '[0-9]+' || echo 0)"
        PARSED_ERRORS="$(echo "$summary_line" | grep -oE '[0-9]+ error' | grep -oE '[0-9]+' || echo 0)"
    fi

    # Default to 0 if empty
    PARSED_PASSED="${PARSED_PASSED:-0}"
    PARSED_FAILED="${PARSED_FAILED:-0}"
    PARSED_ERRORS="${PARSED_ERRORS:-0}"
}

# ---- Run unit tests -----------------------------------------------------

echo "[INFO] Running unit tests..."
{
    echo "============================================================"
    echo "  UNIT TESTS"
    echo "============================================================"
    echo ""
} >> "$REPORT_FILE"

UNIT_START="$(date +%s)"
UNIT_OUTPUT=""
UNIT_RC=0

UNIT_OUTPUT="$(cd "$PROJECT_DIR" && python3 -m pytest tests/ \
    --ignore=tests/test_run_id_integration.py \
    --ignore=tests/test_advanced_scenarios.py \
    -v --timeout=30 --tb=short 2>&1)" || UNIT_RC=$?

UNIT_END="$(date +%s)"
UNIT_DURATION=$((UNIT_END - UNIT_START))

echo "$UNIT_OUTPUT" >> "$REPORT_FILE"
{
    echo ""
    echo "Unit test duration: ${UNIT_DURATION}s"
    echo "Unit test exit code: ${UNIT_RC}"
    echo ""
} >> "$REPORT_FILE"

parse_pytest_summary "$UNIT_OUTPUT"
UNIT_PASSED="$PARSED_PASSED"
UNIT_FAILED="$PARSED_FAILED"
UNIT_ERRORS="$PARSED_ERRORS"

if [ "$UNIT_RC" -ne 0 ]; then
    echo "[WARN] Unit tests had failures (exit code $UNIT_RC)."
    OVERALL_EXIT=1
else
    echo "[INFO] Unit tests passed."
fi

# ---- Run integration tests ----------------------------------------------

echo "[INFO] Running integration tests..."
{
    echo "============================================================"
    echo "  INTEGRATION TESTS"
    echo "============================================================"
    echo ""
} >> "$REPORT_FILE"

INTEGRATION_START="$(date +%s)"
INTEGRATION_OUTPUT=""
INTEGRATION_RC=0

INTEGRATION_OUTPUT="$(cd "$PROJECT_DIR" && python3 -m pytest \
    tests/test_run_id_integration.py \
    tests/test_advanced_scenarios.py \
    -v --timeout=120 --tb=short 2>&1)" || INTEGRATION_RC=$?

INTEGRATION_END="$(date +%s)"
INTEGRATION_DURATION=$((INTEGRATION_END - INTEGRATION_START))

echo "$INTEGRATION_OUTPUT" >> "$REPORT_FILE"
{
    echo ""
    echo "Integration test duration: ${INTEGRATION_DURATION}s"
    echo "Integration test exit code: ${INTEGRATION_RC}"
    echo ""
} >> "$REPORT_FILE"

parse_pytest_summary "$INTEGRATION_OUTPUT"
INTEGRATION_PASSED="$PARSED_PASSED"
INTEGRATION_FAILED="$PARSED_FAILED"
INTEGRATION_ERRORS="$PARSED_ERRORS"

if [ "$INTEGRATION_RC" -ne 0 ]; then
    echo "[WARN] Integration tests had failures (exit code $INTEGRATION_RC)."
    OVERALL_EXIT=1
else
    echo "[INFO] Integration tests passed."
fi

# ---- Summary ------------------------------------------------------------

TOTAL_PASSED=$((UNIT_PASSED + INTEGRATION_PASSED))
TOTAL_FAILED=$((UNIT_FAILED + INTEGRATION_FAILED))
TOTAL_ERRORS=$((UNIT_ERRORS + INTEGRATION_ERRORS))
TOTAL_DURATION=$((UNIT_DURATION + INTEGRATION_DURATION))

if [ "$TOTAL_FAILED" -gt 0 ] || [ "$TOTAL_ERRORS" -gt 0 ]; then
    VERDICT="FAIL"
    OVERALL_EXIT=1
else
    VERDICT="PASS"
fi

SUMMARY="$(cat <<EOF

============================================================
  SUMMARY
============================================================

Verdict     : $VERDICT
Total Duration: ${TOTAL_DURATION}s

Unit Tests:
  Passed  : $UNIT_PASSED
  Failed  : $UNIT_FAILED
  Errors  : $UNIT_ERRORS
  Duration: ${UNIT_DURATION}s

Integration Tests:
  Passed  : $INTEGRATION_PASSED
  Failed  : $INTEGRATION_FAILED
  Errors  : $INTEGRATION_ERRORS
  Duration: ${INTEGRATION_DURATION}s

Totals:
  Passed  : $TOTAL_PASSED
  Failed  : $TOTAL_FAILED
  Errors  : $TOTAL_ERRORS

Report: $REPORT_FILE
EOF
)"

echo "$SUMMARY" >> "$REPORT_FILE"
echo "$SUMMARY"

# ---- Symlink to latest report -------------------------------------------

ln -sf "$REPORT_FILE" "$LATEST_LINK"

echo ""
echo "[INFO] Report written to: $REPORT_FILE"
echo "[INFO] Latest symlink  : $LATEST_LINK"
