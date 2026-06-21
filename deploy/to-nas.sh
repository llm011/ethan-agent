#!/usr/bin/env bash
# Ethan Agent — 推送到绿联 NAS 并 build + 部署（一条龙，calvin 自建镜像）
#
# 用法（在 Mac 上、连着家庭内网时执行）：
#   bash deploy/to-nas.sh
#
# 做的事：
#   1. 本地打包源码（含所有改动：UA 覆盖 / consolidator cheap model / ETHAN_AUTH_TOKEN 修复 / web_dist）
#   2. 传到 NAS（用 cat|ssh 管道，绕开 UGREEN 受限的 scp 子系统）
#   3. SSH 到 NAS：解压 → docker build → 启动 → 打印登录 token
#
# 前提：Mac 与 NAS 同在家庭内网，NAS SSH 可达。

set -euo pipefail

NAS_HOST="${NAS_HOST:-10.0.0.75}"
NAS_USER="${NAS_USER:-calvinlai}"
NAS_PASS="${NAS_PASS:-YOUR_NAS_PASSWORD}"   # 不想明文就改成交互输入

PROJ_DIR="$(cd "$(dirname "$0")/.." && pwd)"
REMOTE_DIR="ethan-agent"
TARBALL="/tmp/ethan-src.tar.gz"
COMPOSE_FILE="docker-compose.calvin.yml"

# 用 sshpass 避免反复输密码；没有就装一下
SSHPASS=""
if ! command -v sshpass >/dev/null 2>&1; then
  echo "==> 安装 sshpass（brew）"
  brew install hudochenkov/sshpass/sshpass 2>/dev/null && SSHPASS="sshpass -p $NAS_PASS" || {
    echo "sshpass 装不上，改用交互式（每次输密码 $NAS_PASS）"
  }
else
  SSHPASS="sshpass -p $NAS_PASS"
fi

ssh_pipe() { $SSHPASS ssh -o StrictHostKeyChecking=no "$NAS_USER@$NAS_HOST" "$@"; }

echo "==> [1/4] 打包源码 $PROJ_DIR"
cd "$PROJ_DIR"
tar --exclude='.git' --exclude='__pycache__' --exclude='*.pyc' --exclude='.venv' \
    --exclude='node_modules' --exclude='.ethan' --exclude='.ruff_cache' \
    --exclude='.pytest_cache' --exclude='*.tar' \
    -czf "$TARBALL" ethan pyproject.toml uv.lock README.md README_CN.md deploy
echo "    打包完成: $(ls -lh "$TARBALL" | awk '{print $5}')"

echo "==> [2/4] 传源码到 NAS"
cat "$TARBALL" | ssh_pipe "cat > /home/$NAS_USER/ethan-src.tar.gz"
echo "    传输完成"

echo "==> [3/4] NAS 上解压 + build 镜像（原生 amd64，约 5-10 分钟）"
ssh_pipe "set -e; cd /home/$NAS_USER && rm -rf $REMOTE_DIR && mkdir -p $REMOTE_DIR && \
  tar xzf ethan-src.tar.gz -C $REMOTE_DIR && cd $REMOTE_DIR && \
  echo '$NAS_PASS' | sudo -S docker build -t ethan-agent:calvin -f deploy/Dockerfile.calvin . && \
  echo '=== build 完成 ===' && echo '$NAS_PASS' | sudo -S docker images ethan-agent:calvin"

echo "==> [4/4] 启动容器并打印登录 token"
ssh_pipe "set -e; cd /home/$NAS_USER/$REMOTE_DIR/deploy && \
  [ -f .env ] || cp .env.nas.example .env && \
  echo '$NAS_PASS' | sudo -S docker compose -f $COMPOSE_FILE up -d && sleep 3 && \
  echo '=== 容器状态 ===' && echo '$NAS_PASS' | sudo -S docker compose -f $COMPOSE_FILE ps && \
  echo '' && echo '=== Web UI 登录 token ===' && grep ETHAN_AUTH_TOKEN .env && \
  echo '' && echo '访问: http://$NAS_HOST:8900'"

echo ""
echo "✅ 完成。打开 http://$NAS_HOST:8900 ，用 .env 里的 ETHAN_AUTH_TOKEN 登录。"
echo "看日志: ssh $NAS_USER@$NAS_HOST 'cd ~/ethan-agent/deploy && sudo docker compose -f $COMPOSE_FILE logs -f'"
