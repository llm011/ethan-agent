# 内核架构

> 面向：想加一个新内核、或想搞清「换内核后哪些能力还在」的人。
> 代码入口：`ethan/kernel/`。本文与代码同步，改动内核层请顺手更新这里。

---

## 一句话

内核决定**「这一轮由谁执行」**。换的是大脑（规划/推理），Ethan 的手脚（工具、
技能、记忆）尽可能保留 —— 但保留到什么程度，每个内核不一样，且必须**如实告诉
用户**，因为差异是最容易被当成 bug 报上来的东西。

```
producers.py                     ← 上游只认 .stream_chat()
   └── KernelRunner              ← 鸭子类型兼容 Agent（.usage / .model / .session_id）
         └── KernelRuntime.run() ← 事件流契约（str / ThinkingEvent / ToolEvent / ...）
               ├── EthanKernel     原生，直接委托 Agent（零行为变化，默认兜底）
               ├── AcpClientKernel DSH / Antigravity（ACP stdio + mcp_servers 注入工具）
               ├── ACPKernelBase   Claude Code / Codex / OpenCode（经 ethan.acp.delegate）
               └── PiKernel        Pi（NDJSON，无 MCP）
```

## 为什么是「事件流」而不是任务函数

上一版抽象成 `execute_task(task_id, prompt, context) -> Any`，写不出「工具跑到
一半要问用户」这种事，最终是 1318 行 TODO + 假数据、零引用。现在的契约是
`Agent.stream_chat()` 的产出词表：`str` / `ThinkingEvent` / `ToolEvent` /
`InjectEvent` / `SkillsMatchedEvent` / `ConsentEvent` / `AskUserEvent`。

任何内核只要按这套词表产出，`producers.py` 一行都不用改 —— 多内核对上层透明。

---

## 能力矩阵（改动这里时务必同步 UI）

`KernelCapabilities`（`runtime.py`）是唯一事实源，经 `GET /api/kernels` 下发到
Web / Desktop / Android 三端。

| 内核 | 工具共享 | 人格/画像 | 中途授权 | 续接 | 注入方式 |
|---|---|---|---|---|---|
| `ethan` | 原生 | ✅ | ✅ | — | — |
| `dsh` | ✅ | ❌ | ✅ | ✅ | ACP `new_session(mcp_servers=...)` |
| `claude_code` | ✅ | ❌ | ❌ | ✅ | `--mcp-config <临时文件>` |
| `opencode` | ✅ | ❌ | ❌ | ✅ | ACP `mcp_servers`（#464 起） |
| `antigravity` | ✅ | ❌ | ❌ | ✅ | ACP `mcp_servers`（`agy acp --process-per-session`） |
| `codex` | ❌ | ❌ | ❌ | ✅ | 能接受配置但**不加载工具**（实测工具列表只有自带的 10 个） |
| `pi` | ❌ | ❌ | ❌ | ✅ | 源码无 MCP 实现 |

> 这张表会变（OpenCode 就是后补上 ACP 的）。以 `runtime.py` 里各 kernel 的
> `capabilities` 为准；`tests/test_kernel_briefing.py` 里有一张逐内核的断言表，
> 新增内核忘了声明会立刻失败。

### 两个字段别搞混

- **`shares_ethan_tools`** —— 能不能**用** Ethan 的工具/技能/记忆（经 MCP 注入）。
- **`ethan_context`** —— 是否原生运行 Ethan 自身的完整系统提示词与 agent 循环（外部内核有自己的系统提示词，固定为 `False`）。

至于外部内核要不要接收 `soul.md` / `user_profile.md` / `identity.md` 等上下文，由配置项 **`defaults.kernel.inject_context`** 单独控制（设置页「AI 内核 → 外部内核上下文注入」可切换）：

| 档位 | 注入内容 | 适用场景 |
|---|---|---|
| `rules_profile`（默认） | `soul.md`（主人授权/安全红线/密钥铁律）、`user_profile.md`、`<behavioral_guidelines>`、`<runtime_context>` | 既保留外部内核原生工作流与语气，又让安全红线和个人画像生效 |
| `full` | 在 `rules_profile` 基础上额外注入 `identity.md` 与当前模式人设（`<persona_override>` / `<mode_identity>`） | 希望外部内核也沿用 Ethan 的人设与对话模式语气 |
| `off` | 不注入上述任何规则/画像/人设 | 仅把外部内核当作纯三方执行器（有工具共享时仍给技能与记忆简报） |

---

## 工具与技能怎么共享（`/kernel-tools` MCP 端点）

`kernel_mcp.py` 起一个 `FastMCP("EthanTools")`，把 Ethan 的工具注册成 MCP tool，
名字带 `ethan_` 前缀（`ethan_web_search`），与外部 agent 自带的同名工具区分开。

链路：

```
外部内核 (DSH) ──MCP over HTTP──▶ /kernel-tools ──▶ 58 个 Ethan 工具
```

### 暴露规则（`tool_bridge.py`）

- `share_tools: "off"` → 不挂端点，也不注入
- `"readonly"` → 只暴露 `READ_ONLY_TOOLS` 白名单
- `"all"`（默认）→ 除 `NEVER_EXPOSE` 之外全给（含 `file_write`：只读等于废掉大半能力）

**`NEVER_EXPOSE` 里有什么、为什么**：

| 工具 | 为什么拦 |
|---|---|
| `shell` | 拿到 shell 等于拿到整台机器，而外部内核的权限模型（`--approval-policy` / `--dangerously-skip-permissions`）与 Ethan 的 consent 不同源，中间拦不住。要执行能力用 `code_run`（走 Ethan 的授权链） |
| `config_set` | 改 Ethan 自身配置，误触代价高（例如"贴心地"清空 `lark.app_id`） |
| `profile_update` / `procedure_write` | 改人格画像 / 行为准则 —— 这是"自我修改"，与"记住对话事实"不是一回事 |
| `delegate_coding` | 递归委派，A→B→A 无意义且放大资源占用 |

`memory_write` **不在**拦截名单里（2026-11 调整）：记忆是「对话产生的事实」，
不是「Ethan 的自我定义」。用户在外部内核里说「以后都叫我阿凌」，记不住才是 bug。
写入怎么落库（证据等级固定 EXPLICIT、supersede 判定）全由 `memory_write` 内部
的准入管道决定，调用方无从指定。

### 简报表（`briefing.py`）—— 有工具 ≠ 会用

这是「切到 DSH 后记忆/技能不生效」的真因，值得单独说清：

`ethan_recall_memory` 挂在 DSH 手上，但 **DSH 不知道要调它**。原生内核靠系统
提示词里的两段引导：

- `<available_skills>` —— 有哪些技能，命中触发词就 `skill_read`
- `<memory_recall_hint>` —— 涉及个人上下文时先调 `recall_memory`

`a8923c15` 把记忆召回从「每次调用前无条件注入」改成「模型按需调 `recall_memory`」，
**替代自动注入的正是那个 hint**。外部内核走自己的系统提示词，一个字都收不到 →
等价于自动注入被撤掉、又没给替代品，记忆彻底失效。

`build_kernel_briefing()` + `match_kernel_skills()` 补的正是这两块，外加 `<memory_write_hint>` 与分层上下文。规则：

- **上下文分层注入（`inject_context`）**：默认 `rules_profile` 注入 `soul.md`、`user_profile.md`、`<behavioral_guidelines>` 与 `<runtime_context>`（不依赖 MCP 工具，Codex / Pi 同样可用）；`full` 再追加 `identity.md` 与模式人设；`off` 关闭；`minimal` 精简模式下不注入画像、记忆提示与技能匹配
- **工具简报只在 `shares_ethan_tools=True` 且 `share_tools != "off"` 时注入** —— 教 Codex/Pi 调它们没有的工具，只会让它失败一轮再绕路
- **每轮按 Skill frontmatter 自动匹配**（`match_kernel_skills()`）：复用 `SkillRegistry.match()` 按 `trigger` / `modes` / `channels` / 语义路由匹配，命中 `default` 技能直接注入 `<relevant_skills>`（正文 + references），命中 `discoverable` 技能注入 `<matched_skills_brief>` 引导调用 `ethan_skill_read`，并发送 `SkillsMatchedEvent` 与记录命中统计
- **模式专属技能不泄漏** —— `legal-assistant` 只在法律模式的简报里出现，「零污染」的硬保证对外部内核同样成立
- 按 `(mode, 技能目录 mtime, soul/identity/profile/playbook 指纹)` 缓存；构建失败退化成只给记忆提示，不让整轮失败

接线在 `KernelRuntime._prepare_prompt()` / `_compose_prompt()`：`_build_prompt()` 保持「只压对话历史」
的纯粹语义，上下文、简报与命中技能在 `_prepare_prompt` 里前置拼上去。

---

## 「内核作为 Ethan 的心脏」还差哪些

诚实记录，免得下次又当成 bug 查：

- **记忆能被读、能被写，但不会自动出现**。外部内核不预召回，靠模型判断后调
  `ethan_recall_memory`；它不调，这一轮就没有记忆。这是「按需召回」的设计代价。
- **对话仍会被 Ethan 记住**。收尾时 `_maybe_consolidate` 用的是 `runner.real_model`
  （不是 `runner.model` —— 后者在外部内核下是显示名 `"DSH"`，拿去
  `create_provider()` 会报 `Provider 'openai_compat' not found`），走 Ethan 自己的
  provider 抽记忆。所以是「写得进、想不起来」，不是「记不住」。
- **外部内核绕开 Ethan 的 `LoopMonitor`**（那套熔断在 `Agent.stream_chat` 内部）。
  兜底是 `_idle_timeout()`：120s（coding 300s）无任何事件即中止。
- **`skill_category` / `sub_steps` 打不平**：ACP 没有对应字段，留空，不谎报。
- **token 统计拿不到**：外部内核保持 0，不瞎估（估出来的数会污染内核对比）。
- **图片不走 inline，改给本地路径**。外部内核的 ACP 传输层普遍声明
  `promptCapabilities.image=false`，实测 dsh 直接拒收整条 prompt：
  `Invalid params: inline image prompts were not advertised by this connection`。
  所以 `_build_prompt()` 把图片存盘后只附**绝对路径**（`[附图，本地文件]`），
  不塞 base64、也不在提示里指定用哪个工具读——拒收的是传输格式，不是模型不能
  识图，怎么读交给内核自己判断。

---

## 加一个新内核

1. 选基类：走 ACP 协议 → `AcpClientKernel`（只需声明 `AcpAgentSpec`）；
   走某个 CLI 的 NDJSON → 参考 `PiKernel`；能用 ACP 就别手写解析器
2. 声明 `capabilities`，**每一条都要有实测依据**，不能共享就写
   `shares_ethan_tools_reason`（要可操作，不要「暂不支持」这种废话）
3. 在 `KernelKind` 加枚举值，`runtime.get_kernel_registry()` 里注册
4. `deps.py` 加安装命令与探测方式
5. UI 自动跟随 `capabilities` 渲染，不用改三端

---

## 配置

```yaml
defaults:
  kernel:
    default: ""                    # "" = 原生 Ethan；可填 ethan / dsh / claude_code / ...
    task_rules: {}                 # {"coding": "claude_code"} 按任务类型选内核
    share_tools: all               # all | readonly | off —— 外部内核能用多少 Ethan 的工具
    inject_context: rules_profile  # off | rules_profile | full —— 注入准则/画像/人格粒度
```

`resolve()` 的选择顺序：请求级显式指定 → `task_rules` → `default` → 兜底原生。
任何一步选出的内核 `available()` 为 False 就告警并继续往下退 —— **绝不因为选了
个没装的内核而让整轮对话失败**。
