#!/usr/bin/env bash
# cua-bridge 安装脚本 — 在 macOS 宿主机上部署 TCP→UDS 桥 + launchd 自启服务。
#
# 用法（curl 一键安装）:
#   curl -fsSL https://raw.githubusercontent.com/llm011/ethan-agent/main/deploy/cua-bridge/install.sh | bash
#
# 或本地运行:
#   bash deploy/cua-bridge/install.sh
#
# 做什么:
#   1. 确认 cua-driver 已安装（没装则提示安装命令）
#   2. 把 cua-bridge.py 复制到 ~/.cua-bridge/cua-bridge.py
#   3. 生成 launchd plist（端口可配: CUA_BRIDGE_PORT=8000）
#   4. load launchd 服务（开机自启）
#
# 卸载:
#   launchctl unload ~/Library/LaunchAgents/com.ethan.cua-bridge.plist
#   rm ~/Library/LaunchAgents/com.ethan.cua-bridge.plist
#   rm -rf ~/.cua-bridge
set -euo pipefail

PORT="${CUA_BRIDGE_PORT:-8000}"
INSTALL_DIR="$HOME/.cua-bridge"
PLIST="$HOME/Library/LaunchAgents/com.ethan.cua-bridge.plist"
LABEL="com.ethan.cua-bridge"

# ── 颜色 ──────────────────────────────────────────────
if [ -t 1 ]; then
    GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; CYAN='\033[0;36m'; NC='\033[0m'
else
    GREEN=''; YELLOW=''; RED=''; CYAN=''; NC=''
fi
info()  { echo -e "${CYAN}›${NC} $*"; }
ok()    { echo -e "${GREEN}✓${NC} $*"; }
warn()  { echo -e "${YELLOW}⚠${NC} $*"; }
fail()  { echo -e "${RED}✗${NC} $*" >&2; exit 1; }

# ── 检查 macOS ────────────────────────────────────────
if [ "$(uname)" != "Darwin" ]; then
    fail "cua-bridge 仅支持 macOS（cua-driver 依赖 macOS Accessibility API）。"
fi

# ── 检查 cua-driver ───────────────────────────────────
CUA_DRIVER="$(command -v cua-driver 2>/dev/null || true)"
if [ -z "$CUA_DRIVER" ]; then
    warn "未检测到 cua-driver。请先安装:"
    echo "  curl -fsSL https://raw.githubusercontent.com/trycua/cua/main/libs/cua-driver/scripts/install.sh | bash"
    echo "  cua-driver install   # 注册开机自启"
    echo "  cua-driver serve     # 启动"
    echo ""
    echo "安装完 cua-driver 后重新运行本脚本。"
    exit 1
fi
ok "cua-driver: $CUA_DRIVER"

# ── 找 Python3 ────────────────────────────────────────
PYTHON3="$(command -v python3 2>/dev/null || true)"
if [ -z "$PYTHON3" ]; then
    fail "未找到 python3。请安装: brew install python3"
fi
ok "python3: $PYTHON3"

# ── 确定 cua-bridge.py 路径 ──────────────────────────
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SRC_SCRIPT="$SCRIPT_DIR/cua-bridge.py"

# curl 管道模式：脚本不在本地仓库里，从 GitHub 下载
if [ ! -f "$SRC_SCRIPT" ]; then
    info "从 GitHub 下载 cua-bridge.py..."
    mkdir -p "$INSTALL_DIR"
    SRC_SCRIPT="$INSTALL_DIR/cua-bridge.py"
    curl -fsSL "https://raw.githubusercontent.com/llm011/ethan-agent/main/deploy/cua-bridge/cua-bridge.py" -o "$SRC_SCRIPT"
fi

# ── 安装脚本 ──────────────────────────────────────────
mkdir -p "$INSTALL_DIR"
cp "$SRC_SCRIPT" "$INSTALL_DIR/cua-bridge.py"
chmod +x "$INSTALL_DIR/cua-bridge.py"
ok "脚本: $INSTALL_DIR/cua-bridge.py"

# ── 生成 launchd plist ────────────────────────────────
mkdir -p "$(dirname "$PLIST")"

# 先 unload 旧的（如果存在）
if launchctl list "$LABEL" >/dev/null 2>&1; then
    launchctl unload "$PLIST" 2>/dev/null || true
fi

cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>${LABEL}</string>
    <key>ProgramArguments</key>
    <array>
        <string>${PYTHON3}</string>
        <string>${INSTALL_DIR}/cua-bridge.py</string>
        <string>--port</string>
        <string>${PORT}</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>/tmp/cua-bridge.log</string>
    <key>StandardErrorPath</key>
    <string>/tmp/cua-bridge.err</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin</string>
    </dict>
</dict>
</plist>
EOF
ok "plist: $PLIST (端口 $PORT)"

# ── load 服务 ─────────────────────────────────────────
launchctl load "$PLIST" 2>/dev/null || true
sleep 1

if launchctl list "$LABEL" >/dev/null 2>&1; then
    ok "launchd 服务已启动 (KeepAlive, 开机自启)"
else
    warn "launchd 服务未正常启动，请检查: launchctl load $PLIST"
fi

# ── 验证 ──────────────────────────────────────────────
echo ""
info "验证桥是否工作..."
sleep 1
if python3 -c "
import socket, json, sys
s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
s.settimeout(5)
try:
    s.connect(('127.0.0.1', ${PORT}))
    s.sendall(json.dumps({'method':'call','name':'get_screen_size','arguments':{}}).encode())
    s.shutdown(socket.SHUT_WR)
    resp = b''
    while True:
        d = s.recv(65536)
        if not d: break
        resp += d
    r = json.loads(resp.decode())
    if r.get('ok'):
        sc = r['result']['structuredContent']
        print(f\"  屏幕尺寸: {sc['width']}x{sc['height']}\")
        sys.exit(0)
    else:
        print(f'  cua-driver 返回错误: {r.get(\"error\",\"?\")}')
        sys.exit(1)
except Exception as e:
    print(f'  连接失败: {e}')
    sys.exit(1)
"; then
    ok "桥工作正常!"
else
    warn "验证失败。请确认 cua-driver 已启动: cua-driver serve"
    echo "  日志: cat /tmp/cua-bridge.log /tmp/cua-bridge.err"
fi

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
ok "安装完成!"
echo ""
echo "  Docker 容器内设置环境变量:"
echo "    CUA_BRIDGE_HOST=host.docker.internal"
echo "    CUA_BRIDGE_PORT=${PORT}"
echo ""
echo "  日志:  cat /tmp/cua-bridge.log"
echo "  卸载:  launchctl unload $PLIST && rm $PLIST && rm -rf $INSTALL_DIR"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
