#!/usr/bin/env bash
# ===========================================================================
# Stop all running Synapsis Agent sessions
# ===========================================================================

set -euo pipefail

GREEN="\033[32m"
YELLOW="\033[33m"
BOLD="\033[1m"
RESET="\033[0m"

# Find all synapsis compose projects
PROJECTS=$(docker compose ls --format json 2>/dev/null | python3 -c "
import sys, json
data = json.load(sys.stdin)
for p in data:
    if p['Name'].startswith('synapsis-'):
        print(p['Name'])
" 2>/dev/null || true)

if [ -z "$PROJECTS" ]; then
    echo -e "  ${YELLOW}No running Synapsis sessions found.${RESET}"
    exit 0
fi

echo -e "  ${BOLD}Stopping all Synapsis sessions...${RESET}"
echo ""

for project in $PROJECTS; do
    echo -e "  ${GREEN}→${RESET} Stopping ${project}..."
    docker compose -p "$project" down
done

echo ""
echo -e "  ${GREEN}${BOLD}All sessions stopped.${RESET}"
