#!/bin/bash
# Auth setup: either use mounted .claude config (local) or API key (cloud).
# When ANTHROPIC_API_KEY is set, skip the .claude mount entirely.
if [ -n "${ANTHROPIC_API_KEY:-}" ]; then
    echo "[Synapsis] Using ANTHROPIC_API_KEY for authentication (cloud mode)"
elif [ -d /tmp/.claude-mount ]; then
    echo "[Synapsis] Copying Claude Code config from mount (local mode)"
    mkdir -p /home/synapsis/.claude
    # Enable dotglob so hidden files like .credentials.json are included
    shopt -s dotglob
    for f in /tmp/.claude-mount/*; do
        [ -f "$f" ] && cp "$f" /home/synapsis/.claude/
    done
    shopt -u dotglob
    # Copy small essential subdirectories (skip large ones like todos, cache)
    for d in credentials statsig projects session-env plugins sessions; do
        [ -d "/tmp/.claude-mount/$d" ] && cp -r "/tmp/.claude-mount/$d" /home/synapsis/.claude/
    done
    chown -R synapsis:synapsis /home/synapsis/.claude
else
    echo "[Synapsis] Warning: No authentication configured. Set ANTHROPIC_API_KEY or mount ~/.claude"
fi

# Pre-create app config dirs to avoid first-launch delays
mkdir -p /home/synapsis/.mozilla /home/synapsis/.config/libreoffice
chown -R synapsis:synapsis /home/synapsis/.mozilla /home/synapsis/.config/libreoffice

# Ensure synapsis user can write to the Docker workspace volume.
# The volume (and any subdirs like uploads/) may be root-owned from prior runs.
if [ -d /workspace ]; then
    find /workspace ! -user synapsis -exec chown synapsis:synapsis {} + 2>/dev/null || true
fi

# ---- Start GUI stack (Xvfb + Fluxbox + x11vnc + noVNC) ----
# Clean stale X locks from prior runs (prevents Xvfb "Fatal server error" on restart)
rm -f /tmp/.X1-lock /tmp/.X11-unix/X1

echo "[Synapsis] Starting virtual display (Xvfb :1 @ ${SCREEN_WIDTH}x${SCREEN_HEIGHT})"
Xvfb :1 -screen 0 ${SCREEN_WIDTH}x${SCREEN_HEIGHT}x24 -ac +extension GLX +render -noreset &
XVFB_PID=$!

# Wait for Xvfb to be ready (up to 5 seconds)
for i in $(seq 1 10); do
    if xdpyinfo -display :1 >/dev/null 2>&1; then
        echo "[Synapsis] Xvfb is ready"
        break
    fi
    sleep 0.5
done

if ! xdpyinfo -display :1 >/dev/null 2>&1; then
    echo "[Synapsis] ERROR: Xvfb failed to start"
fi

echo "[Synapsis] Starting D-Bus session bus"
eval $(dbus-launch --sh-syntax) 2>/dev/null || true
export DBUS_SESSION_BUS_ADDRESS

echo "[Synapsis] Starting XFCE4 desktop"
DISPLAY=:1 startxfce4 &
sleep 3

echo "[Synapsis] Starting VNC server (x11vnc :5900)"
x11vnc -display :1 -nopw -listen 0.0.0.0 -xkb -forever -shared -rfbport 5900 2>&1 &
X11VNC_PID=$!
sleep 1

# Verify x11vnc is running
if kill -0 $X11VNC_PID 2>/dev/null; then
    echo "[Synapsis] x11vnc is running (PID $X11VNC_PID)"
else
    echo "[Synapsis] ERROR: x11vnc failed to start"
fi

echo "[Synapsis] Starting noVNC web client (:6080)"
websockify --web /usr/share/novnc/ 6080 localhost:5900 &
WEBSOCKIFY_PID=$!
sleep 1

if kill -0 $WEBSOCKIFY_PID 2>/dev/null; then
    echo "[Synapsis] websockify is running (PID $WEBSOCKIFY_PID)"
else
    echo "[Synapsis] ERROR: websockify failed to start"
fi

# ---- Start the main application ----
exec gosu synapsis "$@"
