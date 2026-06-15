#!/usr/bin/env bash
# Install/update the Ethan Agent launchd service on macOS.
# Usage: ./deploy/install.sh

set -e

PLIST_NAME="com.ethan.agent"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PLIST_TEMPLATE="$SCRIPT_DIR/${PLIST_NAME}.plist"
PLIST_DST="$HOME/Library/LaunchAgents/${PLIST_NAME}.plist"
LOG_DIR="$HOME/.ethan/logs"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
ETHAN_HOME="$HOME/.ethan"

echo "Installing Ethan Agent service..."
echo "  Project: $PROJECT_ROOT"

# 查找 uv 路径
UV_BIN=$(which uv 2>/dev/null || echo "$HOME/.local/bin/uv")
if [[ ! -x "$UV_BIN" ]]; then
    echo "❌ uv not found. Install it first: curl -LsSf https://astral.sh/uv/install.sh | sh"
    exit 1
fi
UV_BIN_DIR="$(dirname "$UV_BIN")"

# Create log directory
mkdir -p "$LOG_DIR"
mkdir -p "$(dirname "$PLIST_DST")"

# Stop existing service if running
launchctl unload "$PLIST_DST" 2>/dev/null || true

# 用实际路径替换模板占位符，生成最终 plist
sed \
    -e "s|__UV_BIN__|$UV_BIN|g" \
    -e "s|__UV_BIN_DIR__|$UV_BIN_DIR|g" \
    -e "s|__PROJECT_ROOT__|$PROJECT_ROOT|g" \
    -e "s|__ETHAN_HOME__|$ETHAN_HOME|g" \
    "$PLIST_TEMPLATE" > "$PLIST_DST"

# Start service
launchctl load "$PLIST_DST"

echo "✓ Service installed and started."
echo "  Logs: $LOG_DIR/"
echo "  Stop: launchctl unload $PLIST_DST"
echo "  Start: launchctl load $PLIST_DST"
echo "  Status: launchctl list | grep ethan"
