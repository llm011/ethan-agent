#!/usr/bin/env bash

# manager.sh - 一键启停 Ethan AI 前后端
# 用法: ./manager.sh [start|stop|restart|status]

PROJECT_ROOT="/Users/jsongo/code/life/ethan-ai"
PID_DIR="$PROJECT_ROOT/.run"
BACKEND_PID_FILE="$PID_DIR/backend.pid"
FRONTEND_PID_FILE="$PID_DIR/frontend.pid"

mkdir -p "$PID_DIR"

# 获取进程状态 (1 运行中, 0 已停止)
get_status() {
    local pid_file=$1
    if [ -f "$pid_file" ]; then
        local pid=$(cat "$pid_file")
        if ps -p "$pid" > /dev/null; then
            echo 1
            return
        fi
    fi
    echo 0
}

start_backend() {
    if [ "$(get_status "$BACKEND_PID_FILE")" -eq 1 ]; then
        echo "[后端] 已经在运行中 (PID: $(cat "$BACKEND_PID_FILE"))"
    else
        echo "[后端] 启动中..."
        cd "$PROJECT_ROOT" || exit 1
        nohup uv run ethan serve > "$PID_DIR/backend.log" 2>&1 &
        echo $! > "$BACKEND_PID_FILE"
        echo "[后端] 已启动 (PID: $(cat "$BACKEND_PID_FILE"))，日志: $PID_DIR/backend.log"
    fi
}

start_frontend() {
    if [ "$(get_status "$FRONTEND_PID_FILE")" -eq 1 ]; then
        echo "[前端] 已经在运行中 (PID: $(cat "$FRONTEND_PID_FILE"))"
    else
        echo "[前端] 启动中..."
        cd "$PROJECT_ROOT/web" || exit 1
        nohup npm run dev > "$PID_DIR/frontend.log" 2>&1 &
        echo $! > "$FRONTEND_PID_FILE"
        echo "[前端] 已启动 (PID: $(cat "$FRONTEND_PID_FILE"))，日志: $PID_DIR/frontend.log"
    fi
}

stop_process() {
    local name=$1
    local pid_file=$2
    if [ "$(get_status "$pid_file")" -eq 1 ]; then
        local pid=$(cat "$pid_file")
        echo "[$name] 停止中 (PID: $pid)..."
        # 尝试优雅停止
        kill "$pid" 2>/dev/null
        # 等待最多 5 秒
        for i in {1..5}; do
            if ! ps -p "$pid" > /dev/null; then
                break
            fi
            sleep 1
        done
        # 如果还在运行，强制停止
        if ps -p "$pid" > /dev/null; then
            echo "[$name] 强制停止中..."
            kill -9 "$pid" 2>/dev/null
        fi
        echo "[$name] 已停止"
    else
        echo "[$name] 未运行"
    fi
    rm -f "$pid_file"
}

status_process() {
    local name=$1
    local pid_file=$2
    if [ "$(get_status "$pid_file")" -eq 1 ]; then
        echo -e "🟢 [$name] 运行中 (PID: $(cat "$pid_file"))"
    else
        echo -e "🔴 [$name] 已停止"
    fi
}

start() {
    start_backend
    start_frontend
    echo "========================================="
    echo "后端 API: http://localhost:8900"
    echo "前端 Web: http://localhost:3000"
    echo "========================================="
}

stop() {
    stop_frontend
    stop_backend
    
    # 清理可能遗留的 Node 进程 (Next.js dev 启动可能会有子进程)
    if lsof -i :3000 >/dev/null 2>&1; then
        echo "[清理] 发现残留的 3000 端口占用，强制清理..."
        lsof -ti :3000 | xargs kill -9 2>/dev/null
    fi
}

stop_frontend() {
    stop_process "前端" "$FRONTEND_PID_FILE"
}

stop_backend() {
    stop_process "后端" "$BACKEND_PID_FILE"
}

status() {
    status_backend
    status_frontend
}

status_frontend() {
    status_process "前端" "$FRONTEND_PID_FILE"
}

status_backend() {
    status_process "后端" "$BACKEND_PID_FILE"
}

case "$1" in
    start)
        start
        ;;
    stop)
        stop
        ;;
    restart)
        stop
        sleep 2
        start
        ;;
    status)
        status
        ;;
    *)
        echo "用法: $0 {start|stop|restart|status}"
        exit 1
        ;;
esac

exit 0
