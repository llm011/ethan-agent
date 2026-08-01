#!/usr/bin/env python3
"""cua-bridge — TCP→UDS 桥，让 Docker 容器内的 ethan 能访问宿主机上的 cua-driver。

背景：
  cua-driver（macOS）只暴露 Unix Domain Socket（~/Library/Caches/cua-driver/cua-driver.sock）。
  Docker Desktop 的 Linux VM 无法直接连宿主机的 UDS（跨内核，bind-mount 也不通）。
  本桥在宿主机上监听一个 TCP 端口，把流量透明转发到 cua-driver 的 UDS。

协议：
  cua-driver 的 UDS 协议是请求-响应模式，客户端发完 JSON 后必须半关闭（shutdown SHUT_WR），
  driver 才会处理并返回响应。本桥对每条 TCP 连接做：
    1. 读取 TCP 客户端发来的全部数据（读到 EOF 或对方半关闭）
    2. 连接 UDS，写入数据，shutdown(SHUT_WR)
    3. 读 UDS 响应，写回 TCP 客户端
    4. 关闭两端

用法：
  python3 cua-bridge.py                  # 默认 0.0.0.0:8000 → 默认 UDS 路径
  python3 cua-bridge.py --port 9000      # 自定义端口
  python3 cua-bridge.py --uds /custom.sock

依赖：仅 Python 3 标准库，无需 pip install。
"""
from __future__ import annotations

import argparse
import os
import signal
import socket
import sys
import threading

DEFAULT_PORT = 8000
DEFAULT_UDS = os.path.expanduser("~/Library/Caches/cua-driver/cua-driver.sock")
RECV_BUF = 65536
UDS_TIMEOUT = 30  # cua-driver 截图等操作可能较慢


def forward(client: socket.socket, peer: str, uds_path: str) -> None:
    """一条 TCP 连接 → 一条 UDS 连接，透明转发。"""
    uds = None
    try:
        # 读客户端全部请求数据（读到 EOF / 半关闭）
        chunks: list[bytes] = []
        while True:
            data = client.recv(RECV_BUF)
            if not data:
                break
            chunks.append(data)

        if not chunks:
            return

        # 连 UDS
        uds = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        uds.settimeout(UDS_TIMEOUT)
        uds.connect(uds_path)

        # 写请求 + 半关闭（cua-driver 要求客户端写完后 shutdown SHUT_WR 才处理）
        uds.sendall(b"".join(chunks))
        uds.shutdown(socket.SHUT_WR)

        # 读响应并回写
        while True:
            data = uds.recv(RECV_BUF)
            if not data:
                break
            client.sendall(data)

    except FileNotFoundError:
        try:
            client.sendall(
                b'{"ok":false,"error":"cua-driver UDS not found: '
                + uds_path.encode()
                + b'. Is cua-driver serve running?"}'
            )
        except OSError:
            pass
    except ConnectionRefusedError:
        try:
            client.sendall(
                b'{"ok":false,"error":"cua-driver refused connection. '
                b'Run: cua-driver serve"}'
            )
        except OSError:
            pass
    except Exception as e:
        try:
            client.sendall(
                b'{"ok":false,"error":"bridge: '
                + str(e).encode().replace(b'"', b'\\"')
                + b'"}'
            )
        except OSError:
            pass
    finally:
        if uds:
            try:
                uds.close()
            except OSError:
                pass
        try:
            client.close()
        except OSError:
            pass


def serve(host: str, port: int, uds_path: str) -> None:
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind((host, port))
    srv.listen(64)
    print(f"cua-bridge listening on {host}:{port} → {uds_path}", flush=True)
    print(
        f"  Docker 容器内设置: CUA_BRIDGE_HOST=host.docker.internal CUA_BRIDGE_PORT={port}",
        flush=True,
    )

    # 优雅退出
    stop = threading.Event()

    def _sig(_s, _f):
        stop.set()
        try:
            srv.close()
        except OSError:
            pass

    signal.signal(signal.SIGTERM, _sig)
    signal.signal(signal.SIGINT, _sig)

    while not stop.is_set():
        try:
            client, (ip, p) = srv.accept()
        except OSError:
            break
        peer = f"{ip}:{p}"
        t = threading.Thread(
            target=forward, args=(client, peer, uds_path), daemon=True
        )
        t.start()


def main() -> int:
    ap = argparse.ArgumentParser(description="TCP→UDS bridge for cua-driver")
    ap.add_argument("--host", default="0.0.0.0", help="监听地址（默认 0.0.0.0）")
    ap.add_argument(
        "--port", type=int, default=DEFAULT_PORT, help=f"监听端口（默认 {DEFAULT_PORT}）"
    )
    ap.add_argument(
        "--uds",
        default=DEFAULT_UDS,
        help=f"cua-driver UDS 路径（默认 {DEFAULT_UDS}）",
    )
    args = ap.parse_args()

    if not os.path.exists(args.uds):
        print(
            f"⚠️  UDS 路径不存在: {args.uds}\n"
            "    请先启动 cua-driver: cua-driver serve\n"
            "    （桥会继续启动，等 driver 起来后连接自动可用）",
            file=sys.stderr,
        )

    serve(args.host, args.port, args.uds)
    return 0


if __name__ == "__main__":
    sys.exit(main())
