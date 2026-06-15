#!/usr/bin/env bash

# manager.sh - 一键启停 Ethan AI 前后端
# 用法: ./manager.sh [start|stop|restart|status|logs]

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PID_DIR="$PROJECT_ROOT/.run"
BACKEND_PID_FILE="$PID_DIR/backend.pid"
FRONTEND_PID_FILE="$PID_DIR/frontend.pid"
BACKEND_LOG="$PID_DIR/backend.log"
FRONTEND_LOG="$PID_DIR/frontend.log"
BACKEND_PORT=8900
FRONTEND_PORT=3000

mkdir -p "$PID_DIR"

# ── 工具函数 ────────────────────────────────────────────────────

pid_alive() {
    local pid=$1
    [[ -n "$pid" ]] && ps -p "$pid" > /dev/null 2>&1
}

port_occupied() {
    lsof -ti :"$1" > /dev/null 2>&1
}

kill_port() {
    local port=$1
    local pids
    pids=$(lsof -ti :"$port" 2>/dev/null || true)
    if [[ -n "$pids" ]]; then
        echo "$pids" | xargs kill -9 2>/dev/null || true
    fi
}

# 等待端口就绪（最多 N 秒）
wait_for_port() {
    local port=$1 timeout=${2:-15} elapsed=0
    while ! lsof -ti :"$port" > /dev/null 2>&1; do
        sleep 0.5
        elapsed=$((elapsed + 1))
        if [[ $elapsed -ge $((timeout * 2)) ]]; then
            return 1
        fi
    done
    return 0
}

# 等待端口释放（最多 N 秒）
wait_port_free() {
    local port=$1 timeout=${2:-10} elapsed=0
    while lsof -ti :"$port" > /dev/null 2>&1; do
        sleep 0.5
        elapsed=$((elapsed + 1))
        if [[ $elapsed -ge $((timeout * 2)) ]]; then
            return 1
        fi
    done
    return 0
}

stop_by_pid_and_port() {
    local name=$1 pid_file=$2 port=$3

    # 先尝试通过 PID 停止（包括进程组）
    if [[ -f "$pid_file" ]]; then
        local pid
        pid=$(cat "$pid_file")
        if pid_alive "$pid"; then
            echo "[$name] 停止中 (PID: $pid)..."
            # 先发 SIGTERM 给整个进程组
            kill -- "-$pid" 2>/dev/null || kill "$pid" 2>/dev/null || true
            # 等待最多 5 秒
            local i=0
            while pid_alive "$pid" && [[ $i -lt 10 ]]; do
                sleep 0.5; i=$((i+1))
            done
            # 还活着就 SIGKILL
            if pid_alive "$pid"; then
                kill -9 -- "-$pid" 2>/dev/null || kill -9 "$pid" 2>/dev/null || true
            fi
        fi
        rm -f "$pid_file"
    fi

    # 兜底：清理端口上的残留进程
    if port_occupied "$port"; then
        echo "[$name] 清理残留端口 $port..."
        kill_port "$port"
    fi

    # 等待端口真正释放
    if ! wait_port_free "$port" 8; then
        echo "[$name] 警告：端口 $port 未能完全释放"
    else
        echo "[$name] 已停止"
    fi
}

# ── 启动 ────────────────────────────────────────────────────────

start_backend() {
    if port_occupied "$BACKEND_PORT"; then
        echo "[后端] 端口 $BACKEND_PORT 已被占用，跳过启动"
        return
    fi
    echo "[后端] 启动中..."
    cd "$PROJECT_ROOT"
    nohup uv run ethan serve >> "$BACKEND_LOG" 2>&1 &
    local bgpid=$!
    echo "$bgpid" > "$BACKEND_PID_FILE"

    if wait_for_port "$BACKEND_PORT" 20; then
        echo "[后端] 已就绪 http://localhost:$BACKEND_PORT (PID: $bgpid)"
    else
        echo "[后端] 警告：启动超时，请检查日志: $BACKEND_LOG"
        tail -5 "$BACKEND_LOG" | sed 's/^/  /'
    fi
}

start_frontend() {
    if port_occupied "$FRONTEND_PORT"; then
        echo "[前端] 端口 $FRONTEND_PORT 已被占用，跳过启动"
        return
    fi
    echo "[前端] 启动中..."
    cd "$PROJECT_ROOT/web"
    nohup npm run dev >> "$FRONTEND_LOG" 2>&1 &
    local bgpid=$!
    echo "$bgpid" > "$FRONTEND_PID_FILE"

    if wait_for_port "$FRONTEND_PORT" 30; then
        echo "[前端] 已就绪 http://localhost:$FRONTEND_PORT (PID: $bgpid)"
    else
        echo "[前端] 警告：启动超时，请检查日志: $FRONTEND_LOG"
        tail -5 "$FRONTEND_LOG" | sed 's/^/  /'
    fi
}

# ── 公共命令 ────────────────────────────────────────────────────

start() {
    start_backend
    start_frontend
    echo "========================================="
    echo "后端 API: http://localhost:$BACKEND_PORT"
    echo "前端 Web: http://localhost:$FRONTEND_PORT"
    echo "========================================="
}

stop() {
    stop_by_pid_and_port "前端" "$FRONTEND_PID_FILE" "$FRONTEND_PORT"
    stop_by_pid_and_port "后端" "$BACKEND_PID_FILE" "$BACKEND_PORT"
}

restart() {
    stop
    start
}

status() {
    if port_occupied "$BACKEND_PORT"; then
        local bpid
        bpid=$(lsof -ti :"$BACKEND_PORT" | head -1)
        echo "🟢 [后端] 运行中 (port $BACKEND_PORT, PID: $bpid)"
    else
        echo "🔴 [后端] 已停止"
    fi

    if port_occupied "$FRONTEND_PORT"; then
        local fpid
        fpid=$(lsof -ti :"$FRONTEND_PORT" | head -1)
        echo "🟢 [前端] 运行中 (port $FRONTEND_PORT, PID: $fpid)"
    else
        echo "🔴 [前端] 已停止"
    fi
}

logs() {
    local target=${2:-both}
    case "$target" in
        backend|be)
            echo "=== 后端日志 ($BACKEND_LOG) ==="
            tail -50 "$BACKEND_LOG"
            ;;
        frontend|fe)
            echo "=== 前端日志 ($FRONTEND_LOG) ==="
            tail -50 "$FRONTEND_LOG"
            ;;
        *)
            echo "=== 后端日志 ==="
            tail -20 "$BACKEND_LOG"
            echo ""
            echo "=== 前端日志 ==="
            tail -20 "$FRONTEND_LOG"
            ;;
    esac
}

# ── 入口 ────────────────────────────────────────────────────────

case "${1:-}" in
    start)   start ;;
    stop)    stop ;;
    restart) restart ;;
    status)  status ;;
    logs)    logs "$@" ;;
    *)
        echo "用法: $0 {start|stop|restart|status|logs [backend|frontend]}"
        exit 1
        ;;
esac
