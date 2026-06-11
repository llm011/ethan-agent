#!/usr/bin/env bash
# Install/update the Ethan Agent launchd service on macOS.
# Usage: ./deploy/install.sh

set -e

PLIST_NAME="com.ethan.agent"
PLIST_SRC="$(cd "$(dirname "$0")" && pwd)/${PLIST_NAME}.plist"
PLIST_DST="$HOME/Library/LaunchAgents/${PLIST_NAME}.plist"
LOG_DIR="$HOME/.ethan/logs"

echo "Installing Ethan Agent service..."

# Create log directory
mkdir -p "$LOG_DIR"

# Stop existing service if running
launchctl unload "$PLIST_DST" 2>/dev/null || true

# Copy plist
cp "$PLIST_SRC" "$PLIST_DST"

# Start service
launchctl load "$PLIST_DST"

echo "✓ Service installed and started."
echo "  Logs: $LOG_DIR/"
echo "  Stop: launchctl unload $PLIST_DST"
echo "  Start: launchctl load $PLIST_DST"
echo "  Status: launchctl list | grep ethan"
