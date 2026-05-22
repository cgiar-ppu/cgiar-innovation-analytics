#!/bin/bash
# ============================================================================
# tunnel-wrapper.sh — Dynamic IP resolution wrapper for autossh
#
# Instead of hardcoding the proxy IP in the LaunchAgent plist, this wrapper
# resolves the current IP from CloudFormation at launch time. This means:
#   - When EIP replaces the ephemeral IP, the tunnel auto-recovers on next
#     autossh restart (no manual plist update needed)
#   - Works with both ephemeral and Elastic IPs
#
# The LaunchAgent calls this script; it resolves the IP, then exec's autossh.
# ============================================================================
set -euo pipefail

STACK_NAME="synapsis-proxy"
AWS_PROFILE="${AWS_PROFILE:-ai-sandbox}"
SSH_KEY="$HOME/.ssh/synapsis-proxy"
IP_CACHE="$HOME/.cache/synapsis-proxy-ip"
LOG="/tmp/synapsis-proxy-tunnel-wrapper.log"

log() { echo "$(date '+%Y-%m-%d %H:%M:%S') $*" >> "$LOG"; }

# Ensure cache directory exists
mkdir -p "$(dirname "$IP_CACHE")"

# Resolve IP from CloudFormation (with cache fallback)
PROXY_IP=$(aws cloudformation describe-stacks \
  --stack-name "$STACK_NAME" \
  --query 'Stacks[0].Outputs[?OutputKey==`ProxyPublicIP`].OutputValue' \
  --output text \
  --profile "$AWS_PROFILE" 2>/dev/null || true)

if [ -n "$PROXY_IP" ] && [ "$PROXY_IP" != "None" ]; then
  # Cache the resolved IP for offline fallback
  echo "$PROXY_IP" > "$IP_CACHE"
  log "Resolved IP from CloudFormation: $PROXY_IP"
elif [ -f "$IP_CACHE" ]; then
  PROXY_IP=$(cat "$IP_CACHE")
  log "CloudFormation unavailable — using cached IP: $PROXY_IP"
else
  log "ERROR: Cannot resolve proxy IP and no cache exists. Exiting."
  exit 1
fi

# Build the port forwarding arguments
PORTS=(
  # Synapsis agent instances (7777-7790)
  7777 7778 7779 7780 7781 7782 7783 7784 7785 7786 7787 7788 7789 7790
  # Vite dev servers
  5173 5174 5175 5176 5177 5178
  # Vite preview
  4173 4174 4175
  # Node/React dev servers
  3000 3001 3002
  # Common dev servers
  8000 8080 8888
)

FORWARD_ARGS=()
for PORT in "${PORTS[@]}"; do
  FORWARD_ARGS+=("-R" "127.0.0.1:${PORT}:127.0.0.1:${PORT}")
done

# Remove any stale host key for this IP before connecting.
# CloudFormation may replace the EC2 instance (new host key, same Elastic IP).
# Without this, SSH rejects the connection as a potential MITM attack and the
# tunnel silently fails until someone manually runs ssh-keygen -R.
ssh-keygen -R "$PROXY_IP" >> "$LOG" 2>&1 || true

log "Connecting to ec2-user@$PROXY_IP with ${#PORTS[@]} port forwards"

# exec replaces this process with autossh (so launchd tracks the right PID)
exec autossh -M 0 -N \
  -o ServerAliveInterval=30 \
  -o ServerAliveCountMax=3 \
  -o StrictHostKeyChecking=accept-new \
  -o ExitOnForwardFailure=no \
  -o IPQoS=throughput \
  "${FORWARD_ARGS[@]}" \
  -i "$SSH_KEY" \
  "ec2-user@$PROXY_IP"
