# Ethan 浏览器控制方案

> 把一套成熟的浏览器控制链路核心逻辑迁移进 Ethan,实现「不管在哪个渠道对话,都能操作 ethan server 那台机器上的浏览器(前提是装了扩展)」。

## 1. 目标与非目标

### 目标
- ethan 通过工具调用,操作 **ethan server 所在机器**上用户真实 Chrome。
- 扩展独立成一个目录,只负责浏览器侧(连接 + CDP);其余交互逻辑全部在 ethan server。
- 渠道无关:飞书 / Web / CLI 任意渠道的对话,都能驱动同一台机器的浏览器。
- 复用一套成熟的扩展内核(CDP / AX 快照 / ref / session 逻辑),只重写传输层。

### 非目标(本阶段)
- 不做远程跨公网控制(已确认:ethan 与浏览器同机,本机裸跑或本机 Docker)。
- 不做多浏览器连接池(YAGNI)。
- 不做完整 iframe 跨域、turn_id/lease/overlay runtime。

## 2. 架构总览

### 原链路(5 段)
```
browser CLI
  → Desktop browser-control JSON-RPC server (Unix socket)
  → Native Messaging Host (stdio 转发)
  → Chrome Extension (background SW)
  → CDP → Page
```

### Ethan 目标链路(简化为 3 段)
```
ethan agent (browser 工具)
  → BrowserHub (进程内单例) ──WebSocket──> Chrome Extension (background SW)
                                              → CDP → Page
```

关键简化:**用 WebSocket 取代「Desktop RPC server + Native Messaging Host」两层**。
ethan 本来就是个 HTTP server,扩展直接用 WS client 连上来即可,不需要装 native host、不需要本地 socket。

### 复用 / 重写 / 丢弃

| 来源 | 处置 | 说明 |
|---|---|---|
| 扩展 `ax-snapshot.ts` | **复用** | AX 树 → ref map,纯逻辑 |
| 扩展 `page-controller.ts` | **复用** | CDP 页面操作 |
| 扩展 `cdp-client.ts` | **复用** | 按 tab 缓存 CDP attach |
| 扩展 `ref-store.ts` / `page-runtime.ts` | **复用** | ref 生命周期 |
| 扩展 `session-store.ts` | **复用(调整归属)** | session = Chrome Tab Group |
| 扩展 `rpc.ts` 方法路由 | **保留分发,换传输** | method dispatch 留下,底层从 native port 换 WS |
| 扩展 `index.ts` / `manifest.json` | **重写** | WS 连接 + 保活 + 重连;manifest 去掉 native messaging |
| `browser` CLI | **丢弃** | ethan 工具替代 |
| Desktop `browser-control/` server | **丢弃** | ethan `BrowserHub` 替代 |
| `native-host/` + 安装脚本 | **丢弃** | WS 直连,无 native host |
| 原 `desktop-shared` 协议类型 | **内联为本地常量** | 在 Python 侧与扩展侧各自重定义协议常量 |

## 3. 目录结构

### 扩展(独立目录,放在仓库内的 `browser-extension/`)
```
browser-extension/
  src/background/
    ax-snapshot.ts        # 复用:AX 树 → ref map
    page-controller.ts    # 复用:CDP 页面操作
    cdp-client.ts         # 复用:按 tab 缓存 CDP attach
    ref-store.ts          # 复用:ref 生命周期
    page-runtime.ts       # 复用:页面运行时辅助
    session-store.ts      # 复用(调整 ownership):session = Chrome Tab Group
    rpc.ts                # 复用方法分发,改为从 WS 收发
    ws-client.ts          # 新增:WS 连接 + 保活 + 重连
    index.ts              # 重写:启动 WS,不再 connectNative
  src/shared/             # 本地内联协议常量与类型
  src/popup/              # 弹窗设置:填 server 地址 + token + 连接状态
  manifest.json           # 重写:去 nativeMessaging,加 WS host 权限
```

### ethan server(Python)
```
ethan/browser/
  __init__.py
  hub.py            # BrowserHub 单例:WS 端点、连接管理、请求/响应配对、锁、超时
  session_map.py    # ethan session_id ↔ browser session_id 映射 + idle TTL
  protocol.py       # JSON-RPC method 常量 + error code + 超时常量
  ws_route.py       # FastAPI WS 路由 /ws/browser
ethan/tools/builtin/browser.py   # 3 个工具:browser_session / browser_tab / browser_page
```

WS 路由挂到现有 `ethan/interface/api.py`;3 个工具在 `ethan/core/agent_factory.py` 注册。

## 4. 传输层设计(WebSocket)

- **方向**:扩展是 WS **client**,ethan 是 WS **server**(浏览器内无法当 server)。同机 `localhost` 在裸跑/Docker 两种形态下都可达。
- **端点**:`ws://localhost:<ethan_port>/ws/browser`,复用 ethan 现有 HTTP 端口。Docker 下只要该端口 publish 到宿主机即可,无需额外映射。
- **鉴权**:WS 连接首帧携带 ethan 现有 token(扩展弹窗里配置)。校验失败直接 close。
- **协议**:JSON-RPC 2.0,method 用 `sessions.* / tabs.* / pages.*` 命名空间。ethan 侧按 id 配对请求与响应。

### 连接策略(Q4 = last-wins)
- 新 WS 连进来时,顶掉旧连接;旧连接所有 pending 请求立即 fail。
- 同机单浏览器场景下,扩展被 Chrome 杀后重启是常态,新连接就该接管。

### MV3 service worker 保活(本方案最高风险,Q3 已确认完整做但需重点验证)
> 原桌面方案用的是 Native Messaging port(有「port 在即保活」语义),**完全没踩过 WS+MV3 这个坑**,这部分是净新增代码、净新增风险。

扩展侧三重保活:
1. WS 每 20s 发 ping;
2. `chrome.alarms` 每 ~25s 唤醒 SW(防止 SW 被回收);
3. 断线指数退避重连,重连后重新发送鉴权帧。

**实现时第一件事就是把保活验证一晚上**:若 SW 仍频繁断且重连后 CDP attach 状态丢失,需评估退路(ethan 直连 Chrome `--remote-debugging-port`,但那样要用户用调试端口起 Chrome,体验差,作为最后兜底)。

### 超时与断连(Q9)
- 每个 RPC 请求 **30s 超时**。
- 断连 / 被 last-wins 顶掉时,该连接所有 pending 请求立即返回**可重试错误**(「浏览器断连,请重新 snapshot 后重试」),由 agent 自行重试,而不是整体卡死。

## 5. 会话模型

### session 绑对话(Q1 = B)
- 每个 ethan 会话(session_id)维护自己的 browser session 集合。
- `session_map.py` 存 `ethan_session_id → [browser_session_id...]` 映射 + 每个 browser session 的最后活跃时间。
- 隔离效果:飞书不同用户、Web 不同标签互不踩页面。

### 并发控制(Q2 = 单进程 + per-session 锁)
- **保持 `uvicorn.run` 单进程**,不改 gunicorn/多 worker。
  - 原因:consent(内存 Future)、APScheduler、飞书监听、heartbeat、BrowserHub 单例全部依赖单进程共享内存;多 worker 会导致授权回不来、定时任务执行 N 次、飞书事件重复、扩展 WS 只连得上 1/N 的 worker。
  - 浏览器是单一物理资源,多 worker 解决不了「两对话争用同一浏览器」,反而更乱。
- 并发靠 asyncio 协程(本来就是并发处理多请求),不靠多进程。
- **per-session `asyncio.Lock`**:同一 browser session 内的 page 操作排队(防 CDP 命令交错),不同 session 并行。

### 生命周期清理(Q8)
- browser session 闲置超过 **30min**,由现有 scheduler 扫描后 **release**(放掉控制权、保留用户 tab),**不是 close**(不杀 tab,避免破坏用户正在看的页面)。
- 真正 close 只在 agent/用户显式要求时发生。
- 用户回头继续对话,agent 重新 create session。

## 6. 工具层

### 三个工具(三组命令,用 action 参数收敛)
- `browser_session`:`create / attach_current / list / rename / release / close`
- `browser_tab`:`open / list / user_list / attach / active / activate / close`
- `browser_page`:`snapshot / click / fill / type / press / hover / select / scroll / scroll_into_view / screenshot / get / mouse / wait / eval`

### consent:会话级一次性授权(Q6)
- 一个 ethan 会话内**第一次**调用任意 browser 工具时,触发一次 consent(复用现有 Future + 弹窗/飞书机制)。
- 批准后,**该 session 内**后续所有 browser 操作(含 `eval`)全部放行,不再问。
- 飞书非主人的 `side_effect` 硬策略仍叠加(非主人即便授权过也拦)。
- **待落地的集成点**:现有 `tool.consent_check(**tc.arguments)` 不带 session/user 上下文。需二选一:
  - (推荐)把 `user_id` / `session_id` 注入 browser 工具的运行上下文(contextvar 或构造时绑定),consent 网关读 `session_map` 里的「已授权」标志;
  - 或把授权网关下沉到 `BrowserHub`,按 session 记授权态。
  - 实现时先确认现有 agent 如何把上下文传给工具,再定具体接法。

### screenshot 回传(Q5)
- CDP 截图返回 base64 → 工具落盘到**专属目录**(ethan 数据目录下 `browser-shots/`,**不用 /tmp**)。
  - macOS `/tmp` 默认不自动清,Docker 容器内 `/tmp` 更无清理 → 必须自管。
- 飞书:复用现有 `send_lark_image(chat_id, image_path)`(只认本地路径),零改动。
- Web:新增 `/api/browser/shot/{id}` 文件路由读该目录。
- 清理:复用现有 scheduler,删超过 N 分钟(建议 30min)的截图 + 设总量上限。文件需活到飞书上传完成,故不能「跑完立删」。

### snapshot 体积控制(Q7)
- **默认参数交给模型**(B):interactive/compact/depth 由模型按 SKILL.md 引导决定。
- **硬截断安全网**(与上一条正交):单次输出超过 N token 即截断,提示模型「太大,缩小 selector/depth 重试」。防止复杂页面 AX 树打爆上下文。
- snapshot 类工具设 **`no_compress=True`**:绝不过 `result_compressor`(压缩会毁掉 ref,摘要后 ref 对不上元素)。

## 7. 协议(JSON-RPC)

BrowserHub 与扩展之间使用统一的方法命名空间(扩展侧 dispatch 直接按这些字符串路由):
- `sessions.create / sessions.attachCurrent / sessions.list / sessions.rename / sessions.release / sessions.close`
- `tabs.open / tabs.list / tabs.userList / tabs.attach / tabs.active / tabs.activate / tabs.close`
- `pages.snapshot / pages.click / pages.fill / pages.type / pages.press / pages.hover / pages.select / pages.scroll / pages.scrollIntoView / pages.screenshot / pages.get / pages.mouse / pages.wait / pages.eval`

工具层把 `browser_*` 的 action 映射到这些 method。

## 8. 安全

- WS 端点用 ethan 现有 token 鉴权;token 配在扩展 options。
- `eval` 高权限:被会话级 consent 覆盖(首次任意 browser 操作即授权)。
- 截图可能含隐私页面 → 落专属目录 + 定时清理 + 总量上限,不进模型上下文(只回传路径/渲染)。
- secrets 安全网(`mask_text`)对 browser 工具输出同样生效。

## 9. 风险

| 风险 | 等级 | 缓解 |
|---|---|---|
| MV3 SW 被杀导致 WS 断 | **高** | ping + alarms + 退避重连;**实现首日先验证一晚** |
| 重连后 CDP attach 状态丢失 | 中 | per-tab attach 重建;in-flight 请求超时 fail 后重试 |
| 模型全量 dump snapshot 打爆上下文 | 中 | 硬截断安全网 |
| consent 上下文注入改动现有 agent | 中 | 实现前先确认上下文传递方式,二选一接法 |
| Docker 端口/网络 | 低 | WS 复用已 publish 的 HTTP 端口 |

## 10. 分阶段实现清单

> Q3 已确认完整做,但按依赖与风险排序,**最高风险(WS+MV3 保活)前置验证**。

1. **传输骨架 + 保活验证(最高优先)**
   - ethan:`BrowserHub` + `/ws/browser` 路由(鉴权、last-wins、id 配对、30s 超时)。
   - 扩展:`ws-client.ts` + `index.ts`(连接 + ping + alarms + 退避重连)。
   - 验证:扩展连上、挂一晚观察断连/重连行为。**此步决定 WS 路线是否成立。**
2. **移植扩展 CDP 核心**:把 ax-snapshot / page-controller / cdp-client / ref-store / session-store / page-runtime 接到新的 WS 收发上,跑通 `sessions.create` + `pages.snapshot`。
3. **会话模型**:`session_map`(绑对话映射 + idle 时间)、per-session 锁、scheduler idle release。
4. **工具层**:`browser_session / browser_tab / browser_page` 三工具 + 注册;action → method 映射。
5. **consent**:会话级一次性授权接入(先定上下文注入方式)。
6. **screenshot 回传**:落盘专属目录 + 飞书复用 + Web 文件路由 + 定时清理。
7. **snapshot 安全网**:默认参数走模型 + 硬截断 + `no_compress`。
8. **SKILL.md**:编写 `use-browser` 技能,描述三工具的使用流程与约束。
9. **文档**:更新 `docs/` + README/README_CN(双语同步)。

## 11. 已确认决策(grill 结论)

| # | 决策 | 选择 |
|---|---|---|
| Q1 | session 归属 | **绑对话**(隔离干净) |
| Q2 | 并发模型 | **单进程 uvicorn + per-session asyncio.Lock**(不改多 worker) |
| Q3 | 实施方式 | 完整做,边做边调;保活前置验证 |
| Q4 | 连接策略 | **last-wins**(新连接顶掉旧的) |
| Q5 | 截图回传 | **落专属目录 + 定时按龄清理**(不用 /tmp) |
| Q6 | 授权粒度 | **会话级一次性授权**(覆盖含 eval 的全部 browser 操作) |
| Q7 | snapshot | 参数交给模型 + 硬截断安全网 + `no_compress=True` |
| Q8 | 清理 | idle 30min **release**(保留 tab,非 close) |
| Q9 | 断连 | 30s 超时 + 断连即 fail + 可重试错误 |
| Q10 | 分支 | `feat/browser-control` from `main`,worktree `~/code/life/ethan-ai-browser` |
