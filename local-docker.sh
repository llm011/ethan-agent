#!/usr/bin/env bash
# 重新编译并跑起本地 Docker（基于本地源码，不是 PyPI）。
#
# 用法：
#   ./local-docker.sh          # 默认：本地源码构建（能看到你的代码改动）
#   ./local-docker.sh pip      # 从 PyPI 装最新版（复现线上环境）
#   ./local-docker.sh logs     # 只看日志，不重建
#   ./local-docker.sh down     # 只停掉容器
#
# 本地源码模式流程：
#   1. pnpm build web → 产物拷到 ethan/web_dist
#   2. 拷 docs → ethan/docs
#   3. uv build 打 wheel
#   4. 容器里 pip install 本地 wheel（挂载 dist 进去）
set -euo pipefail

cd "$(dirname "$0")"
ROOT="$(pwd)"
COMPOSE_FILE="docker-compose.pip.yml"
DIST_DIR="$ROOT/dist"
DATA_VOLUME="ethan-standalone-data"

# ── 辅助 ──────────────────────────────────────────────────────
check_docker() {
  if ! docker info >/dev/null 2>&1; then
    echo "❌ Docker daemon 没运行，请先启动 Docker Desktop。"
    exit 1
  fi
}

mode="${1:-local}"

case "$mode" in
  # ── 停容器 ───────────────────────────────────────────────
  down)
    check_docker
    docker compose -f "$COMPOSE_FILE" down
    echo "✓ 容器已停止"
    ;;

  # ── 看日志 ───────────────────────────────────────────────
  logs)
    check_docker
    docker compose -f "$COMPOSE_FILE" logs -f --tail=100
    ;;

  # ── PyPI 模式：直接用 docker-compose.pip.yml ─────────────
  pip)
    check_docker
    echo "📦 PyPI 模式：从 PyPI 安装最新 ethan-agent"
    docker compose -f "$COMPOSE_FILE" down
    docker compose -f "$COMPOSE_FILE" up -d --build
    echo "✓ 已启动，访问 http://localhost:${ETHAN_PORT:-8900}"
    docker compose -f "$COMPOSE_FILE" logs -f --tail=50
    ;;

  # ── 本地源码模式（默认）──────────────────────────────────
  local|"")
    check_docker
    echo "🔨 本地源码构建模式"

    # 1. 构建 web UI
    echo "→ [1/4] 构建 Web UI (pnpm build)..."
    cd "$ROOT/web"
    if [ ! -d node_modules ]; then
      pnpm install
    fi
    pnpm run build >/dev/null

    # 2. 拷贝产物进包
    echo "→ [2/4] 拷贝 web 产物和 docs 进包..."
    cd "$ROOT"
    rm -rf ethan/web_dist
    cp -r web/out ethan/web_dist
    rm -rf ethan/docs
    cp -r docs ethan/docs

    # 3. 打 wheel
    echo "→ [3/4] 构建 wheel (uv build)..."
    rm -rf "$DIST_DIR"
    uv build --wheel --out-dir "$DIST_DIR" >/dev/null
    WHEEL=$(ls "$DIST_DIR"/ethan_agent-*.whl | head -1)
    echo "   产物: $(basename "$WHEEL")"

    # 4. 用本地 wheel 起容器
    echo "→ [4/4] 重建并启动容器（装本地 wheel）..."
    docker compose -f "$COMPOSE_FILE" down

    # 临时改 compose：把 dist 挂进容器，pip install 本地 wheel
    # 用 override 文件避免改原 compose
    cat > /tmp/ethan-local-override.yml <<EOF
services:
  ethan-agent:
    volumes:
      - $DIST_DIR:/dist:ro
    command: >
      bash -c "
        apt-get update -qq && apt-get install -y curl -qq >/dev/null 2>&1
        pip install --no-cache-dir --upgrade /dist/$(basename "$WHEEL")
        ethan serve --port 8900
      "
EOF

    docker compose -f "$COMPOSE_FILE" -f /tmp/ethan-local-override.yml up -d --build
    echo "✓ 已启动，访问 http://localhost:${ETHAN_PORT:-8900}"
    echo "   日志: ./local-docker.sh logs"
    echo "   停止: ./local-docker.sh down"
    ;;

  *)
    echo "用法: $0 [local|pip|logs|down]"
    echo "  local (默认) - 本地源码构建"
    echo "  pip          - 从 PyPI 装最新版"
    echo "  logs         - 看日志"
    echo "  down         - 停容器"
    exit 1
    ;;
esac
