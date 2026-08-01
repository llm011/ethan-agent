# Computer Use Bridge — Docker 容器操控宿主机桌面

## 背景

`computer_use` 工具依赖 [cua-driver](https://github.com/trycua/cua) 操控 macOS 桌面（截图、鼠标、键盘）。cua-driver 只暴露 Unix Domain Socket（UDS），且依赖 macOS Accessibility API，**无法在 Linux 容器内运行**。

| 场景 | ethan 运行位置 | cua-driver 运行位置 | 连接方式 |
|------|---------------|-------------------|---------|
| 宿主机直跑 | macOS 宿主机 | 同一台 Mac | UDS（直连） |
| Docker 容器 | Linux 容器 | macOS 宿主机 | **cua-bridge（TCP→UDS）** |

宿主机直跑时不需要 bridge——`computer_use` 工具自动走 SDK 直连模式（装 `cua-computer` 包即可）。

Docker 容器场景下，由于 macOS Docker Desktop 的 Linux VM 无法直接访问宿主机的 UDS（跨内核，bind-mount 也不通），需要一个 TCP→UDS 桥把 cua-driver 的 UDS 暴露为 TCP 端口。

```
容器 ethan → host.docker.internal:8000 (TCP)
           → 宿主机 cua-bridge (TCP→UDS)
           → ~/Library/Caches/cua-driver/cua-driver.sock
           → cua-driver daemon
```

## 架构

```
┌─────────────────────────────────────────────────────────┐
│  Docker Desktop (Linux VM)                              │
│  ┌──────────────────┐                                   │
│  │  ethan 容器       │                                   │
│  │  computer_use    │  TCP: host.docker.internal:8000   │
│  │  (bridge 模式)   │ ──────────────────────────────────┼───▶
│  └──────────────────┘                                   │
└─────────────────────────────────────────────────────────┘
                                                          │
┌─────────────────────────────────────────────────────────┼─────
│  macOS 宿主机                                            │
│                                                          │
│  ┌──────────────────┐    ┌──────────────────────────┐   │
│  │  cua-bridge.py   │    │  cua-driver              │   │
│  │  TCP :8000       │───▶│  UDS: ~/Library/Caches/  │   │
│  │  (launchd 自启)  │    │    cua-driver.sock       │   │
│  └──────────────────┘    └──────────────────────────┘   │
│                                                          │
│  Accessibility + Screen Recording 权限 ──────────────────│
└──────────────────────────────────────────────────────────┘
```

**关键设计点**：

- bridge 是纯 Python stdlib（无第三方依赖），仅做 TCP→UDS 透明转发
- cua-driver 的 UDS 协议要求客户端发完请求后 `shutdown(SHUT_WR)` 半关闭，driver 才会处理并返回响应。bridge 对每条 TCP 连接自动处理这个半关闭
- Docker Desktop 把容器流量 NAT 到宿主机 loopback（`127.0.0.1`），不经 macOS 应用层防火墙，无需额外放行
- 容器内不需要装 `cua-computer` 包，纯 stdlib socket 通信
- 不设 `CUA_BRIDGE_HOST` 环境变量时，`computer_use` 工具自动走 SDK 直连模式，宿主机直跑场景完全不受影响

## 安装

### 方式一：ethan setup 菜单（推荐）

在宿主机上运行：

```bash
ethan setup
```

选择 `🧩 插件` → `桌面自动化-桥接`，按提示操作。

### 方式二：curl 一键安装

在宿主机（macOS）终端执行：

```bash
curl -fsSL https://raw.githubusercontent.com/llm011/ethan-agent/main/deploy/cua-bridge/install.sh | bash
```

脚本会：
1. 检查 cua-driver 是否已安装
2. 把 `cua-bridge.py` 复制到 `~/.cua-bridge/`
3. 生成 launchd plist 并注册为开机自启服务（KeepAlive）
4. 自动验证桥是否工作（调用 `get_screen_size` 测试）

### 前置条件

1. **安装 cua-driver**

   ```bash
   curl -fsSL https://raw.githubusercontent.com/trycua/cua/main/libs/cua-driver/scripts/install.sh | bash
   cua-driver install   # 注册开机自启
   cua-driver serve     # 或手动启动
   ```

2. **授予 macOS 权限**

   在 `系统设置 → 隐私与安全性` 中为 cua-driver 授予：
   - **辅助功能（Accessibility）**：鼠标/键盘控制
   - **屏幕录制（Screen Recording）**：截图

   首次运行 `cua-driver serve` 时 macOS 会弹窗提示授权。

3. **自定义端口**（可选）

   默认端口 8000。如需修改：

   ```bash
   CUA_BRIDGE_PORT=9000 bash deploy/cua-bridge/install.sh
   ```

   同时在容器的 docker-compose.yml 里设置 `CUA_BRIDGE_PORT=9000`。

## Docker 容器配置

docker-compose.yml 已预置环境变量，默认值开箱即用：

```yaml
environment:
  - CUA_BRIDGE_HOST=${CUA_BRIDGE_HOST:-host.docker.internal}
  - CUA_BRIDGE_PORT=${CUA_BRIDGE_PORT:-8000}
extra_hosts:
  - "host.docker.internal:host-gateway"
```

无需额外配置。如果自定义了端口，在 `.env` 里加：

```bash
CUA_BRIDGE_PORT=9000
```

## 验证

### 1. 宿主机上验证 bridge

```bash
# 检查 launchd 服务状态
launchctl list | grep cua-bridge

# 检查端口
lsof -nP -iTCP:8000 -sTCP:LISTEN

# 测试调用
python3 -c "
import socket, json
s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
s.connect(('127.0.0.1', 8000))
s.sendall(json.dumps({'method':'call','name':'get_screen_size','arguments':{}}).encode())
s.shutdown(socket.SHUT_WR)
resp = b''
while True:
    d = s.recv(65536)
    if not d: break
    resp += d
print(json.loads(resp.decode()))
"
```

### 2. 容器内验证 bridge

```bash
docker exec ethan-agent python3 -c "
import socket, json
s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
s.settimeout(5)
s.connect(('host.docker.internal', 8000))
s.sendall(json.dumps({'method':'call','name':'get_screen_size','arguments':{}}).encode())
s.shutdown(socket.SHUT_WR)
resp = b''
while True:
    d = s.recv(65536)
    if not d: break
    resp += d
print(json.loads(resp.decode()))
"
```

期望输出包含 `"ok": true` 和屏幕尺寸（如 `1728×1117`）。

### 3. 在 ethan 中使用

在对话中让 AI 使用 computer_use 工具：

```
帮我截图看看屏幕上有什么
```

AI 会调用 `computer_use(action="screenshot")`，通过 bridge 截取宿主机屏幕。

## 工作原理

### 模式自动切换

`computer_use` 工具在每次调用时检测 `CUA_BRIDGE_HOST` 环境变量：

- **存在** → bridge 模式：通过 TCP 连接 cua-bridge，纯 stdlib socket 通信
- **不存在** → SDK 直连模式：通过 `cua-computer` 包连本地 cua-driver UDS

这意味着：
- 宿主机直跑 ethan 时，不设 `CUA_BRIDGE_HOST` → 走 SDK 直连（需要 `cua-computer` 包）
- Docker 容器跑 ethan 时，docker-compose.yml 自动设 `CUA_BRIDGE_HOST` → 走 bridge 模式（不需要 `cua-computer` 包）

### cua-driver 协议

cua-driver 的 UDS 协议是自定义 JSON 格式（非标准 JSON-RPC）：

```json
// 请求
{"method": "call", "name": "get_screen_size", "arguments": {}}

// 响应
{"ok": true, "result": {"content": [...], "structuredContent": {...}}}
```

关键：客户端发完请求 JSON 后必须 `shutdown(SHUT_WR)` 半关闭，driver 才会处理并返回响应。bridge 对每条 TCP 连接自动处理这个半关闭。

### 工具映射

cua-driver 0.6.8 的工具面与 `cua-computer` SDK 接口有差异，bridge 模式做了映射：

| computer_use action | cua-driver 工具 | 说明 |
|---------------------|----------------|------|
| screenshot | `get_window_state(capture_mode=vision)` | 截取前台窗口截图 |
| get_screen_size | `get_screen_size` | 获取屏幕尺寸 |
| click | `click(pid, x, y, button=left)` | 左键单击 |
| double_click | `double_click(pid, x, y)` | 双击 |
| right_click | `right_click(pid, x, y)` | 右键单击 |
| move | `move_cursor(pid, x, y)` | 移动光标 |
| drag | `drag(pid, from_x, from_y, to_x, to_y)` | 拖拽 |
| type | `type_text(pid, text)` | 输入文本 |
| press | `press_key(pid, key)` | 按键 |
| hotkey | `hotkey(pid, keys)` | 组合键 |
| scroll | `scroll(pid, direction, amount)` | 滚动 |
| launch | `launch_app(name)` | 启动应用 |
| open | `launch_app(Safari)` + `type_text(url)` + `press_key(return)` | 打开 URL |

### 焦点窗口缓存

cua-driver 的 click/type 等工具需要 `pid`（进程 ID）寻址。bridge 客户端在首次 `screenshot` 时通过 `list_windows` 获取前台窗口的 pid+window_id 并缓存，后续 click/type/scroll 等复用该缓存。`launch`/`open` 等会改变前台窗口的操作会自动清除缓存。

## 卸载

```bash
# 停止并卸载 launchd 服务
launchctl unload ~/Library/LaunchAgents/com.ethan.cua-bridge.plist
rm ~/Library/LaunchAgents/com.ethan.cua-bridge.plist

# 删除脚本
rm -rf ~/.cua-bridge
```

## 故障排查

### bridge 连接失败

```bash
# 检查 bridge 是否在运行
launchctl list | grep cua-bridge
lsof -nP -iTCP:8000 -sTCP:LISTEN

# 查看 bridge 日志
cat /tmp/cua-bridge.log
cat /tmp/cua-bridge.err
```

### cua-driver 未运行

```bash
cua-driver status
cua-driver serve  # 手动启动
```

### 截图返回为空

确认 cua-driver 有**屏幕录制**权限：
`系统设置 → 隐私与安全性 → 屏幕录制 → cua-driver` 勾选。

### 点击/输入无效

确认 cua-driver 有**辅助功能**权限：
`系统设置 → 隐私与安全性 → 辅助功能 → cua-driver` 勾选。

### 容器连不到 host.docker.internal

```bash
# 在容器内检查
docker exec ethan-agent python3 -c "
import socket; s = socket.socket()
s.settimeout(3)
try:
    s.connect(('host.docker.internal', 8000))
    print('OK')
except Exception as e:
    print(f'FAIL: {e}')
"
```

如果失败，检查 docker-compose.yml 里的 `extra_hosts: ["host.docker.internal:host-gateway"]` 是否存在。

## 文件清单

| 文件 | 说明 |
|------|------|
| `deploy/cua-bridge/cua-bridge.py` | TCP→UDS 桥（纯 stdlib，~100 行） |
| `deploy/cua-bridge/install.sh` | 一键安装脚本（curl 管道友好） |
| `deploy/cua-bridge/com.ethan.cua-bridge.plist` | launchd plist 模板（install.sh 会生成实际文件） |
| `ethan/tools/builtin/computer_use.py` | 工具实现（含 bridge 客户端 + SDK 双模式） |
| `ethan/interface/commands/setup.py` | 插件注册（`computer-use-bridge` 插件项） |
| `deploy/docker-compose.yml` | 容器编排（预置 `CUA_BRIDGE_HOST` 环境变量） |
