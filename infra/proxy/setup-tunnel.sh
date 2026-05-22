#!/bin/bash
# ============================================================================
# setup-tunnel.sh — Configure persistent SSH reverse tunnel on macOS
#
# This script sets up autossh to maintain a reverse tunnel from your Mac
# to the EC2 proxy instance. Traffic to https://synaptic.synapsis-analytics.com
# and port subdomains (p{PORT}.synaptic.synapsis-analytics.com) is forwarded
# through the tunnel to your local apps.
#
# Usage:
#   chmod +x infra/proxy/setup-tunnel.sh
#   ./infra/proxy/setup-tunnel.sh
#
# Prerequisites:
#   - SSH key at ~/.ssh/synapsis-proxy (generated during setup)
#   - Homebrew installed
#   - AWS CLI configured (to read stack outputs)
# ============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SSH_KEY="$HOME/.ssh/synapsis-proxy"
PLIST_NAME="com.synapsis.proxy-tunnel"
PLIST_PATH="$HOME/Library/LaunchAgents/$PLIST_NAME.plist"
STACK_NAME="synapsis-proxy"
AWS_PROFILE="${AWS_PROFILE:-ai-sandbox}"

echo "=== Synapsis Proxy Tunnel Setup ==="

# -----------------------------------------------------------------------
# 1. Check prerequisites
# -----------------------------------------------------------------------
echo ""
echo "1. Checking prerequisites..."

if [ ! -f "$SSH_KEY" ]; then
  echo "ERROR: SSH key not found at $SSH_KEY"
  echo "Generate it with: ssh-keygen -t ed25519 -f ~/.ssh/synapsis-proxy -N '' -C 'synapsis-proxy-tunnel'"
  exit 1
fi
echo "   SSH key: OK ($SSH_KEY)"

if ! command -v autossh &>/dev/null; then
  echo "   Installing autossh via Homebrew..."
  brew install autossh
else
  echo "   autossh: OK ($(which autossh))"
fi

# -----------------------------------------------------------------------
# 2. Get proxy IP from CloudFormation outputs
# -----------------------------------------------------------------------
echo ""
echo "2. Fetching proxy IP from CloudFormation stack '$STACK_NAME'..."

PROXY_IP=$(aws cloudformation describe-stacks \
  --stack-name "$STACK_NAME" \
  --query 'Stacks[0].Outputs[?OutputKey==`ProxyPublicIP`].OutputValue' \
  --output text \
  --profile "$AWS_PROFILE" 2>/dev/null || true)

if [ -z "$PROXY_IP" ] || [ "$PROXY_IP" = "None" ]; then
  echo "   Could not auto-detect proxy IP from CloudFormation."
  echo -n "   Enter the proxy EC2 public IP manually: "
  read -r PROXY_IP
fi

echo "   Proxy IP: $PROXY_IP"

# -----------------------------------------------------------------------
# 3. Test SSH connection
# -----------------------------------------------------------------------
echo ""
echo "3. Testing SSH connection to ec2-user@$PROXY_IP..."

if ssh -i "$SSH_KEY" \
  -o StrictHostKeyChecking=accept-new \
  -o ConnectTimeout=10 \
  "ec2-user@$PROXY_IP" "echo 'SSH connection successful'" 2>/dev/null; then
  echo "   SSH: OK"
else
  echo "   WARNING: SSH connection failed. The EC2 instance may still be provisioning."
  echo "   The LaunchAgent will retry automatically."
fi

# -----------------------------------------------------------------------
# 4. Create LaunchAgent for persistent tunnel (uses dynamic wrapper)
# -----------------------------------------------------------------------
echo ""
echo "4. Creating LaunchAgent at $PLIST_PATH..."

# Unload existing agent if present
launchctl unload "$PLIST_PATH" 2>/dev/null || true

# Copy the wrapper script to a stable location
WRAPPER_DEST="$HOME/.local/bin/synapsis-tunnel-wrapper.sh"
mkdir -p "$(dirname "$WRAPPER_DEST")"
cp "$SCRIPT_DIR/tunnel-wrapper.sh" "$WRAPPER_DEST"
chmod +x "$WRAPPER_DEST"
echo "   Wrapper script installed at $WRAPPER_DEST"

# Seed the IP cache so the wrapper works immediately (even if AWS CLI is slow)
mkdir -p "$HOME/.cache"
echo "$PROXY_IP" > "$HOME/.cache/synapsis-proxy-ip"
echo "   IP cache seeded: $PROXY_IP"

# The LaunchAgent calls the wrapper script, which dynamically resolves
# the proxy IP from CloudFormation at each autossh restart. This means
# IP changes (e.g. EIP allocation) are picked up automatically — no need
# to re-run setup-tunnel.sh or manually edit the plist.
cat > "$PLIST_PATH" << PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>$PLIST_NAME</string>

    <key>ProgramArguments</key>
    <array>
        <string>/bin/bash</string>
        <string>$WRAPPER_DEST</string>
    </array>

    <key>EnvironmentVariables</key>
    <dict>
        <key>AUTOSSH_GATETIME</key>
        <string>0</string>
        <key>PATH</key>
        <string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
        <key>HOME</key>
        <string>$HOME</string>
    </dict>

    <key>RunAtLoad</key>
    <true/>

    <key>KeepAlive</key>
    <true/>

    <key>ThrottleInterval</key>
    <integer>10</integer>

    <key>StandardErrorPath</key>
    <string>/tmp/synapsis-proxy-tunnel.err.log</string>

    <key>StandardOutPath</key>
    <string>/tmp/synapsis-proxy-tunnel.out.log</string>
</dict>
</plist>
PLIST

echo "   LaunchAgent written."

# -----------------------------------------------------------------------
# 5. Load and start the tunnel
# -----------------------------------------------------------------------
echo ""
echo "5. Loading and starting tunnel..."

launchctl load "$PLIST_PATH"
sleep 2

# Check if it's running
if launchctl list | grep -q "$PLIST_NAME"; then
  echo "   Tunnel agent is running."
else
  echo "   WARNING: Tunnel agent may not have started. Check logs:"
  echo "     tail -f /tmp/synapsis-proxy-tunnel.err.log"
fi

# -----------------------------------------------------------------------
# 6. Summary
# -----------------------------------------------------------------------
echo ""
echo "=== Setup Complete ==="
echo ""
echo "  Main URL:    https://synaptic.synapsis-analytics.com"
echo "  Port URLs:   https://p{PORT}.synaptic.synapsis-analytics.com"
echo "  Proxy IP:    $PROXY_IP"
echo "  SSH Key:     $SSH_KEY"
echo "  LaunchAgent: $PLIST_PATH"
echo "  Logs:        /tmp/synapsis-proxy-tunnel.{out,err}.log"
echo ""
echo "  Forwarded port ranges:"
echo "    7777-7790  Synapsis agent instances"
echo "    5173-5178  Vite dev servers"
echo "    4173-4175  Vite preview"
echo "    3000-3002  Node/React dev servers"
echo "    8000, 8080, 8888  Common dev servers"
echo ""
echo "  The tunnel starts automatically on login."
echo "  IP is resolved dynamically from CloudFormation at each restart."
echo "  ExitOnForwardFailure=no allows partial port binding."
echo "  IPQoS=throughput optimizes tunnel bandwidth (~2 MB/s vs ~92 KB/s)."
echo ""
echo "  Manage the tunnel:"
echo "    Stop:    launchctl unload $PLIST_PATH"
echo "    Start:   launchctl load $PLIST_PATH"
echo "    Status:  launchctl list | grep $PLIST_NAME"
echo "    Logs:    tail -f /tmp/synapsis-proxy-tunnel.err.log"
echo ""
