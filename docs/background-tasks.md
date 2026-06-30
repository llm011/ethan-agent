# 后台任务设计文档

即时长任务异步执行系统：用户发起一个会跑很久的任务（深度调研、批量处理、长网页自动化等），任务在后台独立会话里跑，**不阻塞当前对话**，完成后结果回灌。

> 与 [Scheduler](./scheduler.md)（定时任务，未来某时刻触发）的区别：后台任务是「现在就发起、立刻后台跑」。两者复用同一套「独立 session + 子线程跑 /chat + 按渠道回灌」的模式，但触发时机不同。

---

## 为什么需要它

主对话的一次生成是同步的：长任务会占住整条会话，用户只能干等。后台任务把这类活儿剥离出去——主对话立即返回「已在后台开始」，用户可继续聊别的；任务在独立会话里异步推进，完成后通知。

---

## 架构

```
┌─────────────────────────────────────────────┐
│ background_task / _list / _stop  Tools       │  LLM 判断「这活儿很久」时主动调
├─────────────────────────────────────────────┤
│ _REGISTRY: dict[session_id → _BgTask]        │  进程内任务表（不持久化）
├─────────────────────────────────────────────┤
│ daemon 线程：对独立 session 跑 streaming /chat │
│   ├── 自动批准 consent（后台无 UI，发起即授权） │
│   ├── 累计正文                                │
│   └── 结束按渠道回灌 + 更新 status            │
├─────────────────────────────────────────────┤
│ GET  /api/background-tasks       任务中心轮询  │
│ POST /api/background-tasks/{id}/stop  终止     │
└─────────────────────────────────────────────┘
```

实现见 `ethan/tools/builtin/background_task.py` 与 `ethan/interface/routers/background_tasks.py`。

---

## 执行流程

1. **发起**（`background_task` 工具）：建一个独立 session「[后台] {标题}」，首条用户消息（任务描述）入库；起一个 daemon 线程对它跑 **streaming** `/chat`。工具立即返回「已在后台开始：{标题}（任务 ID：{session_id}）」。
2. **后台跑**：线程 drain SSE——遇到 `consent_request` 时**分级处理**：低风险自动批准；高危调用（`always=True`，如 `rm -rf`）一律拒绝并记录，回灌时提示用户去前台确认。累计 `content`、记录 `stopped`/`error`/`done`。走流式管线是为了让 `RunManager` 持有一个可停止的 run（终止功能依赖它）。
3. **回灌**：
   - **lark**：把最终结果经 `_send_lark_reply` 推回发起任务的 chat（前缀「【后台任务完成】」）。
   - **web**：结果落在后台 session，侧边栏经 `/poll` 浮现；`/background-tasks` 页可点「查看对话」查看。

---

## 终止

`background_task_stop` 工具或 `POST /api/background-tasks/{id}/stop` 都走 `RunManager.instance().stop(session_id)`——标记 `stop_requested` 并取消 producer 任务，已生成的部分内容会被保存（复用 streaming 生成的停止语义，见 [agent-loop.md](./agent-loop.md) 的 RunManager 部分）。任务状态置为 `stopped`。

---

## Web 交互

`/background-tasks` 页（侧边栏「后台任务」入口，带运行中数量角标）：

- **任务卡片**：标题、状态灯（运行中/已完成/失败/已停止）、已运行时长、「查看对话」、运行中显示「终止」按钮。
- **轮询刷新**：有运行中任务时每 5 秒刷新一次，全部结束停轮询。ethan 当前**无 WebSocket 任务推送**，故用轮询兜底——这也意味着 web 端是「被动浮现」（侧边栏/任务页更新），而非在当前对话里主动弹通知；lark 渠道才有真·主动推送。
- **历史后台会话**：折叠区列出所有 `[后台]` 前缀的 session（含进程重启后状态已清、但 session 仍在的）。

---

## 设计取舍

**状态不持久化**：`_REGISTRY` 在 server 进程内存，重启即清空。后台任务是一次性的，daemon 线程本就随进程重启被杀，无需持久化任务状态；产出已落在 session（持久），不丢。

**复用 /chat 而非另起执行器**：后台任务走的就是完整 agent 循环（含三档路由、全量工具、卡死检测/收尾），与前台对话同一套能力，不需要单独维护一条执行路径。

**consent 分级**：后台无交互 UI，无法逐次弹 consent，故线程内**分级处理**：低风险操作自动批准（用户主动发起后台任务即视为授权这类操作）；高危调用（`consent_always=True`，如 `rm -rf`）一律拒绝、记录，回灌时提示用户去前台确认后手动执行。避免长任务里模型「自作主张」删文件/花钱。高危判定复用工具自身的 `consent_always`，与前台一致。

**端口不写死**：回调本机 server 的 base url 从 `ETHAN_SERVER_PORT` 环境变量读取（`run_server` 启动时设置），回退 8900，避免服务跑在非默认端口时后台任务连不上、静默失败。
