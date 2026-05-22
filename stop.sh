#!/usr/bin/env bash
# Stop Synapsis Analytics Agent
set -euo pipefail
echo "Stopping Synapsis Analytics Agent..."
docker compose down
echo "Agent has been stopped."
