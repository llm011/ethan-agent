#!/usr/bin/env bash
# 开发模式：重新构建 Web UI 并重启本地 ethan serve（8900）。
#
# 改完前端代码（web/ 下的 tsx/ts）或想刷新 8900 页面时，跑一条命令即可：
#   ./dev.sh
#
# 流程：
#   1. pnpm build web  → 产物 web/out
#   2. 拷到 ethan/web_dist（ethan serve 服务的静态目录）
#   3. 停掉旧 ethan serve 进程，后台重启
#   4. 等待 8900 就绪后提示
#
# 注意：只改 Python 代码（ethan/ 下）时，serve 进程也需重启才生效——
#       本脚本会顺带重启。若只改 Python 不想动 web，可加 --skip-web。
set -euo pipefail
cd "$(dirname "$0")"
ROOT="$(pwd)"
PORT=8900

SKIP_WEB=0
[ "${1:-}" = "--skip-web" ] && SKIP_WEB=1

# ── 1. 构建 web ──────────────────────────────────────────────
if [ "$SKIP_WEB" -eq 1 ]; then
  echo "⏭  跳过 web 构建（--skip-web）"
else
  echo "🔨 [1/3] 构建 Web UI..."
  cd "$ROOT/web"
  if [ ! -d node_modules ]; then
    echo "   首次：pnpm install..."
    pnpm install
  fi

  # 生产构建（ethan serve 前后端同端口 8900）必须走 origin/api 分支。
  # .env.local 里的 NEXT_PUBLIC_API_URL 是给 pnpm dev（前端 3000 → API 8900）用的，
  # 会被 Next.js 内联进产物，短路掉同端口的 origin/api 逻辑，导致前端打 /auth 而非 /api/auth → 405。
  # 所以 build 时临时移走它，build 完恢复。
  ENV_LOCAL=".env.local"
  ENV_MOVED=""
  if [ -f "$ENV_LOCAL" ]; then
    ENV_MOVED="$ENV_LOCAL.build-tmp"
    mv "$ENV_LOCAL" "$ENV_MOVED"
    echo "   （build 时临时移走 .env.local，避免 NEXT_PUBLIC_API_URL 短路同端口逻辑）"
  fi

  pnpm run build >/dev/null

  # 恢复 .env.local，pnpm dev 仍可用
  if [ -n "$ENV_MOVED" ] && [ -f "$ENV_MOVED" ]; then
    mv "$ENV_MOVED" "$ENV_LOCAL"
  fi
  cd "$ROOT"

  # ── 2. 拷产物 ───────────────────────────────────────────────
  echo "📦 [2/3] 更新 ethan/web_dist..."
  rm -rf ethan/web_dist
  cp -r web/out ethan/web_dist
fi

# ── 3. 重启 serve ────────────────────────────────────────────
echo "🔄 [3/3] 重启 ethan serve (port $PORT)..."

# 停旧进程：按端口杀（比 pgrep 匹配命令名更可靠，能覆盖 ethan serve / uvicorn 等各种启动方式）
OLD_PIDS=$(lsof -ti :"$PORT" -sTCP:LISTEN 2>/dev/null || true)
if [ -n "$OLD_PIDS" ]; then
  echo "   停止旧进程 (pid=$(echo $OLD_PIDS | tr '\n' ' '))..."
  for pid in $OLD_PIDS; do
    kill "$pid" 2>/dev/null || true
  done
  sleep 1
  # 没死的强杀
  for pid in $OLD_PIDS; do
    if kill -0 "$pid" 2>/dev/null; then
      kill -9 "$pid" 2>/dev/null || true
    fi
  done
  sleep 1
fi

# 后台重启（用 .venv 里的 ethan，保证是本地源码）
ETHAN_BIN="$ROOT/.venv/bin/ethan"
if [ ! -x "$ETHAN_BIN" ]; then
  ETHAN_BIN="ethan"
fi
# PYTHONUNBUFFERED=1 确保 uvicorn 日志实时写文件，便于排查
PYTHONUNBUFFERED=1 nohup "$ETHAN_BIN" serve --port "$PORT" >/tmp/ethan-serve.log 2>&1 &
SERVE_PID=$!
echo "   已后台启动 (pid=$SERVE_PID)，日志: /tmp/ethan-serve.log"

# ── 4. 等待就绪 ──────────────────────────────────────────────
echo "⏳ 等待 8900 就绪..."
for i in $(seq 1 30); do
  if curl -sf "http://127.0.0.1:$PORT/api/health" >/dev/null 2>&1; then
    echo "✓ 就绪！访问 http://localhost:$PORT"
    echo "  （浏览器若还显示旧的，Cmd+Shift+R 强制刷新）"
    exit 0
  fi
  sleep 0.5
done
echo "⚠  30s 内未就绪，看日志排查: tail -f /tmp/ethan-serve.log"
exit 1
