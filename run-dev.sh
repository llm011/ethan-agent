#!/usr/bin/env bash
# 在集成 worktree 里跑一个独立实例（默认 8910），与主仓库的 8900 互不干扰。
#
# 为什么必须有这个脚本：ethan 的 watchdog 通过 /tmp/ethan/server.pid 管进程，
# 多个实例会互相杀。规则（见 CLAUDE.md）：
#   · 默认端口 8900 同时只能有一个实例
#   · 开发测试用随机/独立端口，且必须 ETHAN_NO_WATCHDOG=1
#     （不写 server.pid、不拉起 watchdog、heartbeat 不检查 watchdog）
#   · 不要 pkill -f "ethan serve"，会误杀别的 worktree 实例
#
# 用法：
#   ./run-dev.sh            # 8910 前台起
#   ./run-dev.sh 8911       # 指定端口
#   ./run-dev.sh 8910 stop  # 停掉本脚本起的实例

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PORT="${1:-8910}"
ACTION="${2:-start}"
PIDFILE="/tmp/ethan-dev-${PORT}.pid"

if [[ "$ACTION" == "stop" ]]; then
  if [[ -f "$PIDFILE" ]]; then
    PID="$(cat "$PIDFILE")"
    if ps -p "$PID" > /dev/null 2>&1; then
      echo "停止 $PID (端口 $PORT)"
      kill -TERM "$PID" || true
      for _ in $(seq 1 20); do
        ps -p "$PID" > /dev/null 2>&1 || break
        sleep 0.5
      done
    fi
    rm -f "$PIDFILE"
  else
    echo "没有找到 $PIDFILE"
  fi
  exit 0
fi

# 端口占用检查：只查端口，不去扫别人的进程
if lsof -nP -i TCP:"$PORT" -sTCP:LISTEN > /dev/null 2>&1; then
  echo "端口 $PORT 已被占用：" >&2
  lsof -nP -i TCP:"$PORT" -sTCP:LISTEN >&2
  exit 1
fi

cd "$HERE"

# 关键：ETHAN_NO_WATCHDOG=1
#   1. 不写 /tmp/ethan/server.pid  → 不会被 8900 的 watchdog 杀
#   2. 不拉起 watchdog             → 不会去接管别的实例
#   3. heartbeat 不检查 watchdog   → 不会互相拉起
#
export ETHAN_NO_WATCHDOG=1

# 数据目录：**共享只读资源，隔离可变状态**。
#
# 直接共用 ~/.ethan 会让两个实例同时写同一份 SQLite（向量库/会话库），
# 实测报 `UNIQUE constraint failed on vec_index primary key`——两个进程
# 同时 reindex 同一批 memory。那不是代码 bug，但会污染真实数据。
#
# 而完整复制 ~/.ethan 也不现实：7.8G（output 3.5G + tmp 1.4G + db 1G...）。
#
# 所以用 overlay 目录：软链共享 skills/projects/assets 等只读资源，
# 但 db（会话/向量/调度库）用独立的，避免互相踩。
DATA_ROOT="${ETHAN_DEV_DATA_DIR:-/tmp/ethan-dev-data-$PORT}"
mkdir -p "$DATA_ROOT"

for shared in skills remote-skills knowledge memory documents assets browser-shots life system; do
  src="$HOME/.ethan/$shared"
  dst="$DATA_ROOT/$shared"
  if [[ -e "$src" && ! -e "$dst" ]]; then
    ln -s "$src" "$dst" 2>/dev/null || true
  fi
done

# config.yaml 共享（这样内核/语音/搜索的配置与 8900 一致，便于对比体验）
if [[ -f "$HOME/.ethan/config.yaml" && ! -e "$DATA_ROOT/config.yaml" ]]; then
  ln -s "$HOME/.ethan/config.yaml" "$DATA_ROOT/config.yaml"
fi

# db 目录独立：不软链，让实例自己初始化一套
mkdir -p "$DATA_ROOT/db"

export ETHAN_DATA_DIR="$DATA_ROOT"
echo "数据目录: ${DATA_ROOT} (db 独立, 其余软链到 ~/.ethan)"

echo "启动 $HERE/.venv/bin/ethan serve --host 127.0.0.1 --port $PORT"
nohup .venv/bin/ethan serve --host 127.0.0.1 --port "$PORT" \
  > "/tmp/ethan-dev-${PORT}.log" 2>&1 &

echo $! > "$PIDFILE"
echo "PID $(cat "$PIDFILE")  →  http://127.0.0.1:$PORT"
echo "日志: /tmp/ethan-dev-${PORT}.log"
