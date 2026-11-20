# Ethan Agent v2 重构 — 进度与后续计划

> 最后更新：2026-11-21
> 状态：**重构已全部合入 main**。1992 个测试。四条发版流水线全绿。
>
> ### 待办清单（一眼看全）
>
> | 项 | 状态 |
> |---|---|
> | P0 多内核 | ✅ 完成（6 个内核，DSH/Claude 可共享 Ethan 工具） |
> | P1 `tools.md` 结构性拆分 | ❌ **唯一未做**（34K 字符，占 prompt 66%） |
> | P2 `skill_filter.py` | ✅ 已删除（零引用） |
> | P3 Android 编译 / 设置页 | ✅ 完成（APK 可构建，内核/语音 Tab 有真实数据通道） |
> | P4 8 种场景 / Power Bundles | ✅ 确认不做（现有 match + find_tools 已覆盖） |
>
> 发版流程的坑与自检清单见 [docs/release.md](docs/release.md)。

---

## 零、本轮（2026-11-15）新增了什么

这一轮把 v2 从「设计 + 半成品」推进到**可验收状态**。

### 多内核运行时（六个内核全部可用）

| 内核 | 可用 | 用 Ethan 的工具 | 实现 |
|---|---|---|---|
| ethan | ✅ | ✅ 原生 | — |
| claude_code | ✅ | ✅ | `--mcp-config` + `--dangerously-skip-permissions` |
| codex | ✅ | ❌ | 能接受 MCP 配置但不加载工具 |
| opencode | ✅ | ❌ | 只能改全局配置（不做，避免污染用户环境） |
| dsh | ✅ | ✅ | ACP `mcp_servers` 参数 |
| pi | ✅ | ❌ | 源码里没有 MCP 实现 |

「用 Ethan 的工具」是本轮的核心：外部内核有自己的大脑，但通过 MCP 拿到 Ethan
的 58 个工具（`/kernel-tools` 端点），于是能读 Ethan 的知识库、用 Ethan 的搜索。
实测 DSH 调用 `mcp__ethan__ethan_web_search`、Claude 调用同名工具均成功。

**不污染用户环境**：`mcp_servers` 是 ACP 的 `new_session()` 参数，`--mcp-config`
是临时文件，都不写入 `~/.dsh` / `~/.claude`。实测注入后 DSH 自带的 22 个工具全在。

**外壳暴露权限**（用户确认）：所有外部内核以完全放行权限运行
（`--dangerously-skip-permissions` / `--approval-policy never`），MCP 共享里
排除 `shell`（等于交出整台机器）与 `delegate_coding`（递归无意义）。

### 外部内核 session id 展示

用外部内核时，对话标题下展示内核自己的 session id + 复制按钮
（三端：web / desktop / Android）。用户拿它去命令行定位：
`dsh --session-id <id>` / `claude --resume <uuid>`。

落库持久化，刷新不丢。两个 id 严格分开：`request.session_id` 是 Ethan 的，
`request.kernel_session_id` 是内核的——早期实现混用会导致续接错位。

### 外部内核活性检测

外部内核**完全绕开 Ethan 的 `LoopMonitor`**（那套熔断在 `Agent.stream_chat` 内部，
内核模式下不执行）。所以补了一层：120s（coding 300s）无任何事件即中止并提示，
而不是干等整轮 timeout。

### TTS / ASR 后端可配置

`edge-tts`（在线零安装）与 `ethan-tts`（本地，需 Apple Silicon + MLX）。
选本地后端时**先做系统预检**：非 Apple Silicon 直接拒绝，零安装动作。
服务启动由选择动作触发，用户不需要敲命令。

### DeepSeek 自研能力接成 provider

Search / Fetch / OCR 三个接入 `web_search` / `web_fetch` / `ocr_extract_text`，
provider 顺序 `searxng → deepseek → tavily → duckduckgo → bing`。
OCR 走独立工具，但**系统提示词强制优先用模型自身识图**，OCR 只作兜底。

### 修掉的重大回归

**配置写入全线失效**（本轮最严重的自伤）：修并发时让 `save_config` 拿内存单例
做 diff 基线，而所有调用方都是「`get_config()` 改字段 → `save_config()`」，
基线已含改动 → 变更集恒为空 → 接口返回 `{"ok": true}` 但一个字没写。
影响 **50 处调用点**（模型增删改、内核切换、语音后端、providers、channels……）。
改用「上次落盘快照」做基线，并加 `tests/test_config_write_contract.py` 锁死。

**Android 编译不过**：14 个文件来自三个未完成的「深度重构」（`7d866b51` /
`0f45b6b3` / `39920bfa`），从引入起就没编译过，且零生产引用。连同 7 个
`Optimized*.kt` 一起删除（生产入口用的是 `ChatScreen` / `EthanApp`）。
删完 `assembleDebug` 通过，APK 22MB，dex 里能查到新增的类。

**对话白屏**：`swimlane-diagram.tsx` 的 `ENTITY_CONFIG` 连 `builtin` 兜底项都没有，
多内核后 `entity_type` 出现 `acp`/`dsh`/`pi` → `cfg` 为 undefined → `cfg.color` 崩。

**点进对话跳回 /chat**：合并路由后产物只剩 `chat/index.html`，但后端 fallback
只认 `chat/__placeholder__/index.html` → 落到站点根。改成逐层往上找最近的 index。

---

## 一、先说结论：v2 第一轮实际交付了什么

`#443` 与 `cf53d363`（已进 main）声称完成 Phase 1–5。逐条核实后的实际情况：

| 声称完成 | 实际状态 |
|---|---|
| 智能技能包系统（`skill_bundle_manager.py`） | 零引用。与已存在的 `skill_bundle.py` 重复；`init_skill_bundles()` 从未被调用，注册表恒空，`build_context()` 只吐空标题 |
| 场景感知（`scene_detector.py`） | 零引用。第四套并行机制（已有 `SkillRegistry.match` + `skill_filter` + `find_tools`） |
| 实时反馈引擎（`feedback_engine.py`） | 零引用。现有 `ToolEvent`→SSE→`ToolTimeline` 已完整覆盖 |
| 编程能力（`code_assistant.py`） | 类写好了但**没注册进 registry**，模型看不到 |
| `agent_factory.py` 集成 | 只有一行未使用的 import（ruff F401） |
| 集成检查 `integration_check.py` | 用 `'get_context_manager' in 文件文本` 判「集成成功」，跑出 5/5 全绿 |
| UI 集成检查 `ui_integration.py` | 模块级两段顶层代码，运行即 `SyntaxError`，从未执行过 |
| Android 设置页重构 | **导致编译失败**（详见下） |
| Desktop 技能包界面 | 无人引用，数据前端写死，无后端接口 |

### 最严重的问题：Android 编译不过

`cf53d363` 把 1089 行的真实 `SettingsScreen.kt` 换成 823 行版本：

- 签名从 `SettingsScreen(state, onTabChange, onSaveServerUrl, ... 40+ 回调)`
  缩成 `SettingsScreen(onBack, modifier)`
- 但 `EthanApp.kt:268` 仍按旧签名调用 → **编译失败**
- 新版本本身没有任何数据通道：14 个 `remember { mutableStateOf }` 局部状态、
  4 个 `expanded = false` 的假下拉、零网络/持久化调用，改完即丢
- 那个「AI 内核」选择器（DSH / Claude / Legacy）是纯 UI 占位——后端没有任何 kernel
  概念，选中值不落盘、不生效

---

## 二、已完成（本次）

### Step 0 ✅ 清理

- `integration_check.py`、`ui_integration.py`、`scene_detector.py`、
  `skill_bundle_manager.py`、`feedback_engine.py` 全部删除（每个都验证过零引用/无法运行）
- `agent_factory.py` 的无用 import 回滚
- `desktop/.../SkillBundlesSettings.tsx` 删除（`skills-view.tsx` 早就有更完整的管理界面）
- `app/android/.../KernelSettings.kt` 删除（import 的 Kotlin 包不存在）
- **`SettingsScreen.kt` 恢复到 `cf53d363^`**：已验证签名与 `EthanApp.kt` 调用完全匹配、
  28 个 import 全部可解析

### Step 1 ⚠️ prompt 瘦身（只落地了一半，别被上面的数字误导）

先纠正需求文档的一个前提错误：文档说「Context 占用 ~6KB → ~300B」。实测的 6KB 级别
占用根本不在技能包，而在两处：

```
块                     改前     当时改后   ← 注意：这是 2026-11-14 当时的中间态
tools_reference       34317    16209      ← ~/.ethan/system/tools.md，是工具经验笔记不是工具清单
available_skills      12860     4498      ← 167 个技能的触发词/描述全量罗列
------------------------------------------------
TOTAL                 60397    33576      (-44%, 约 20K → 11K tokens)
```

**重要更正**：上表里的 `tools_reference 16209` 和 `TOTAL 33576` **没有保留下来**。
按「压缩日志」思路合并 tools.md 时误删了 `docs +fetch`、`--content-limit 4000`、
`Interrupted system call`、`_synthesize_once` 等下次踩坑能直接抄的内容，**已恢复原文件**
（详见下方 P1 的「本次教训」）。所以 Step 1 真正落地的只有第 2 项技能分级。

当前实测基线（2026-11-14 复核，`python -m tests.bench_prompt_size`）：

```
块                     字符     占比
tools_reference       34317    66%   ← 仍是未拆分的全量，P1 待办由另一分支负责
agent_protocols        4634     9%
available_skills       4520     9%   ← 分级后（原 12860）
behavioral_guidelines  3777     7%
soul                   2794     5%
其余 6 块合计          1912     4%
------------------------------------------------
TOTAL                 ~52K           ≈ 17K tokens（不含历史消息、不含 tools schema）
```

> 表中字符数会随 `Current time:` 等动态内容小幅浮动，精确值以
> `python -m tests.bench_prompt_size` 实时输出为准，不要在文档里写死具体数字。

另外，Full Path 曾在稳定层和动态层各拼一个 `<available_skills>`（标签重复、内容重叠），
现已合并为一个块并整体放进 `Current time:` 之前的缓存稳定层；预览页的 tools token
估算也从写死的 `tool_count * 70` 改为按真实 schema 长度计算。这两项属于代码层清理，
不改变 tools.md 本身。

做法（落地项）：
1. ~~**`tools.md` 合并去重**（34.3K → 16.2K）~~ —— **已回退，见上方更正**。
   正确做法不是压缩，而是按检索需要结构性拆分，留作 P1。
2. **技能分级**：`SkillRegistry.build_index_block()`——高频技能（`fast_path` 或
   `stats.hit_count > 0`）保留描述，其余 142 个只列名字，细节用 `skill_list` /
   `skill_read` 现取。

### Step 2 ✅ code_assistant 做实

- 真正注册进 `build_tool_registry()`（`code_analyze` / `code_run`）
- `code_run` 改为委托 `ShellTool` 执行，继承授权弹窗 / secret 注入与 mask /
  进程组 kill / working_dir 语义，不再裸调 `subprocess.run`
- **补掉一个真实安全洞**：交给 shell 的命令串只有 `python3 /tmp/xxx.py`，代码正文在
  文件里。只扫命令串会让 `os.system('rm -rf ~/x')` 完整绕过高危判定。现在命令串 +
  正文一起送进 shell 判定，并按危险 API 名（`subprocess.` / `shutil.rmtree` /
  `child_process` 等）补扫——因为 `subprocess.run(['rm','-rf','/'])` 这种写法
  shell 的 `rm ` 正则匹配不到

### Step 3 ✅ 反馈引擎：不实现

需求文档要的「阶段总结 + 进度可视化 + 流式反馈」现有链路已完整具备：

- 后端：`ToolEvent` → `run.emit({"tool":..., "state":"start"/"done", "duration_ms",
  "result_preview"})`（`producers.py:409`）
- 前端：`packages/shared/src/components/tool-timeline.tsx`（684 行，desktop/web 共用），
  含 running 转圈、耗时、结果预览、子步骤
- 消费：`use-chat-stream.ts:388` 已处理 `state === "start"`

### Step 4 ✅ UI

见 Step 0。技能管理真正的入口是 `skills-view.tsx` + `/skills` 路由（desktop）与
`web/app/(protected)/skills/page.tsx`，功能比那个假组件完整（搜索/增删改）。

### Step 5 ✅ 服务重启

8900 服务已用新代码重启（旧进程 13:52 启动、无 `--reload`，跑的是含全部假模块的旧代码）。

---

## 三、验收方式（替代原来的假检查）

```bash
# prompt 体积实测，超预算直接失败
.venv/bin/python -m tests.bench_prompt_size

# 预算回归 + 技能分级行为
.venv/bin/python -m pytest tests/test_prompt_budget.py -q

# code 工具功能 + 安全网
.venv/bin/python -m pytest tests/test_code_assistant.py -q
```

`tests/test_prompt_budget.py` 锁住了各块上限（以 `tests/bench_prompt_size.py` 的
`BUDGETS` 为准：`tools_reference` 36K、`available_skills` 6K、`agent_protocols` 6K、
`soul` 4K、`behavioral_guidelines` 5K，总计 `TOTAL_BUDGET` 55K），再有人往每轮 prompt
里塞整块内容会直接测试失败。另有 3 条断言守结构：xml 块不得重复、预览 prompt 必须与
真实典型一轮完全一致、tools token 估算必须取自真实 schema 长度。

**注意**：这些阈值是「防止继续增长」的护栏，按当前实测值留少量余量设定，**不代表
prompt 已经够小**。`tools_reference` 仍是 34.3K 全量，拆分是 P1 待办。

---

## 四、后续待办（按价值排序）

### P0 ✅ 多内核（已完成）

已按「事件流对齐」重写，详见下方专章。

### P1：`tools.md` 的结构性拆分（**唯一剩余的待办**）

> **状态（2026-11-21）**：除本项外，P0/P2/P3/P4 全部完成或确认不做。
>
> 实测：`tools_reference` **34,317 字符，占 system prompt 52,160 的 66%**。
> 每轮对话都要全量带上，且工具循环里每次迭代重复发送。
>
> 这不是「还能再省点」的优化，是当前 prompt 体积的**主要构成**。
> 但要小心：上一轮曾误删有效细节（见下方教训），**拆分必须先确认内容清单**。

**先说清楚它的定位**：`tools.md` 不是日志，是**操作手册**——教 agent 怎么用工具。
机制是 `Agent._load_system_files()` → `<tools_reference>` → 每轮全量进 system prompt。
（工具 schema 走 API 的 `tools` 参数，那是「工具叫什么、什么参数」；
`tools.md` 是「这工具的坑在哪、怎么用才对」，两者互补。）

**为什么值得单独做**：`_load_system_files()` 只在启动时读盘，但
`build_system_prompt()` **每次都把全文重新拼进 system 字符串**；而工具循环里
`provider.chat(working, tools=tools, system=sys)` 每轮迭代都带同一份 system + 工具
schema。实测 full 档单次调用的固定开销约 **29.7K tokens**（system 17.3K + 41 个
广播工具的 schema 12.4K），不含历史消息，且随每次工具迭代重复发送。Anthropic 的
prompt cache（`docs/caching.md`）能省**费用**（稳定层命中 0.1×），但不省上下文窗口、
不省首 token 延迟；OpenAI 兼容协议不走这套分割。所以减体积本身仍有价值。

**范围约定**：53KB 的 `~/.ethan/system/tools.md` 是用户运行时文件、不在 git 里
（git 内的 `ethan/defaults/system/tools.md` 模板仅 4.7K 且所有分支一致）。本轮的代码层
清理不触碰它的内容，P1 的拆分由另一分支进行，避免重复改动。

**本次教训**：我一度按「压缩日志」的思路把它从 34K 合并到 16K，结果误删了
`docs +fetch`、`--content-limit 4000`、`Interrupted system call`、
`_synthesize_once` 这些下次踩坑能直接抄的东西。**已恢复原文件。**

正确的拆分方式不是压缩，而是**按检索需要分开**（实测数据）：

| 内容 | 体量 | 该在哪 |
|---|---|---|
| 通用工具知识（gws 代理、lark-cli 用法、shell 坑、HA、生图） | ~13K | 留在 `tools.md`，每轮都该有 |
| 任务专属 playbook（EigenFlux 批次流程、book-audio-digest、SSDExt） | ~21K | 迁到知识库，按需 `knowledge_search` |

后者只在做那个任务时有用，每轮全量注入是纯浪费。迁移后 `tools.md` 约 13K，
另一半进知识库仍可检索——**信息不丢，只是不再每轮都付 token**。

同时要治写入纪律：`system_file_guard.py` 有 200K 截断护栏，但根因是 agent 在往
里面追加运行日志。文件头已加规则，还需在心跳/定时任务 prompt 里明确禁止。

### P2 ✅ `skill_filter.py`（已删除）

`ethan/core/skill_filter.py`（155 行）定义了 `CORE_SKILLS` / `MEDIUM_SKILLS` 分级，
但全仓库零引用 —— 分级逻辑直接在 `SkillRegistry.build_index_block()` 里实现了。
已删除。

### P3 ✅ Android 设置页 / 编译问题（已解决）

两个层面都处理完了：

**1. 编译**：14 个文件（来自 `7d866b51` / `0f45b6b3` / `39920bfa` 三次未完成的
「深度重构」）+ 7 个 `Optimized*.kt` 全是死代码（零生产引用，生产入口是
`ChatScreen` / `EthanApp`）。删除后 `assembleDebug` 通过，产出 22MB APK。

**2. 数据通道**：新增的内核 / 语音 Tab 走真实后端接口
（`/api/kernels`、`/api/tts/backends`），链路是
Ktor `EthanApiService` → `EthanRepository` → `SettingsViewModel` → Compose，
每层都补了方法和类型。

**遗留**：Android 单元测试代码缺 junit/mockito 依赖配置（`compileDebugUnitTestKotlin`
报错），不影响 APK 产出，但意味着 Android 侧的单元测试跑不起来。**这是测试基建欠账，
不是功能缺陷**，需要单独补 `build.gradle.kts` 的 testImplementation。

**未做的验证**：没有真机/模拟器跑过。APK 能构建、dex 里能查到新类，
但「点进去能用」需要装一次才能确认。

### P4 ✅ 确认不实现（现有机制已覆盖）

现有 `SkillRegistry.match()` 的触发词 + 语义路由 + `find_tools` 按需激活已经覆盖
这个需求。**不建议再加一层 SceneDetector**。如果确实需要「场景」概念做 UI 展示，
应该复用 `match()` 的结果，而不是另写一套关键词表。

---

## 五、多内核运行时（已完成）

### 设计：不抽象流程，只抽象事件词表

原 `ethan/kernel/` 抽象成 `execute_task(task_id, prompt, context) -> Any`，
包不住真实需求（多轮工具循环 + 流式事件 + 中途授权），1318 行全是 TODO 假数据。

新方案利用项目里**已经稳定**的契约——`Agent.stream_chat()` 的事件词表：

```
str / ThinkingEvent / ToolEvent / InjectEvent / SkillsMatchedEvent
ConsentEvent / AskUserEvent / WaitForUserEvent
```

上游 `producers.py` 消费它转 SSE，前端 `ToolTimeline` 渲染。任何内核只要按这套
词表产出，**上层一行都不用改**。ACP 层（`ethan/acp/`）已经验证过这条路——
它跑 claude/codex/opencode 三个外部 CLI，只产 `step`/`text` 两种事件。

```
ethan/kernel/
├── runtime.py       KernelRuntime 基类 / KernelRegistry(选择+降级) / 数据类
├── ethan_kernel.py  原生内核：原样转发 Agent.stream_chat（默认，零行为变化）
├── claude_kernel.py ACPKernelBase：step/text → ToolEvent/str，异步队列实时转发
├── acp_kernel.py    Codex / OpenCode
└── dispatch.py      KernelRunner：对 Agent 鸭子类型兼容的句柄
```

### 六个内核

| kind | 名称 | 实现方式 |
|---|---|---|
| `ethan` | Ethan 原生 | 直接转发 `Agent.stream_chat`（默认，零行为变化） |
| `claude_code` | Claude Code | ACP → `claude -p --output-format stream-json` |
| `codex` | Codex | ACP → `codex` |
| `opencode` | OpenCode | ACP → `opencode` |
| `dsh` | DSH | `dsh --profile headless --json`（NDJSON） |
| `pi` | Pi Agent | `pi -p --mode json`（token 级流式） |

DSH 和 Pi 不复用 ACP 基类——它们的 CLI 参数与事件 schema 与 claude 那族完全不同
（强行塞进去会让基类长出三个 if 分支）。各自实现、共享同一套 `KernelRuntime` 契约。

### 依赖按需安装（默认不装）

**默认不安装任何外部内核依赖。** 用户在设置页选中某个内核时才触发安装：

```
GET  /api/kernels            → 列出所有内核 + 可用性 + 安装状态（只探测，不发安装）
POST /api/kernels/install    → 确保依赖就绪，缺失则自动 npm install
POST /api/kernels/select     → 设为默认内核（内部同样先确保依赖）
POST /api/kernels/task-rules → 设置按任务选内核
```

关键设计：`select` **先装依赖再写配置**。若反过来，装失败会留下「配置指向
不可用内核」的脏状态，导致后续每轮对话降级 + 刷警告。实测验证过：依赖装不上时
返回 409，配置保持原值。

npm 权限不足（EACCES）时不擅自 sudo，而是给出 `npm config set prefix ~/.npm-global`
的建议。

### 配置

```yaml
kernel:
  default: ""            # "" = 原生 Ethan
  task_rules:            # 按任务类型选内核
    coding: claude_code
```

选择顺序：显式 > `task_rules[task_kind]` > `default` > Ethan 兜底。
选到不可用的内核会记警告并继续降级——**绝不因此让对话失败**。

### 已实测（真机端到端）

**验证方式**：`scripts/e2e_kernels.py` —— 打真实 HTTP、走真实 SSE、真起外部 CLI
子进程。单测只能验证逻辑，验证不了「用户点一下之后到底发生了什么」。

```bash
python scripts/e2e_kernels.py --quick     # 只查列表
python scripts/e2e_kernels.py             # 全量（切内核 + 真对话）
python scripts/e2e_kernels.py --kernel pi # 单个
```

结果（2026-11-14）：

| 内核 | 耗时(total) | 结果 |
|---|---|---|
| ethan | 3.5s | ✓ |
| claude_code | 6.4s | ✓ |
| codex | 2.8s | ✓ |
| opencode | 5.6s | ✓ |
| pi | 2.2s | ✓ |
| dsh | 1.7s | ✗ 缺凭证（环境问题，见下） |

**端到端发现的三个 bug（单测完全没暴露）**：

1. **服务进程 PATH 与交互 shell 不同**。`ethan serve` 由 launchd 拉起，PATH 只有
   `/opt/homebrew/bin:/usr/bin:/bin`，看不到 `~/.npm-global/bin` 和 nvm 目录。
   Web UI 显示「未安装」，但命令行 `which claude` 明明正常。修法：`deps.locate()`
   主动扫候选目录（含 nvm 通配），找到后把目录写进 `os.environ["PATH"]`
   （否则子进程照样起不来）。

2. **codex 的 provider 被 ACP 层强行覆盖**。ACP 的 `_codex_provider_overrides`
   是为委派场景设计的（复用 Ethan 的 cliproxy，写死 `gpt-5.5`），但那个模型在
   cliproxy 上不存在 → `unknown provider for model gpt-5.5`。作为内核用时必须
   尊重用户自己的 `~/.codex/config.toml`，加了 `ETHAN_CODEX_NO_PROVIDER_OVERRIDE`
   开关（跑完恢复，委派工具不受影响）。另外补了 `--skip-git-repo-check`：
   codex 默认拒绝在非 git 目录跑。

3. **working_dir 落到了 `/`**。进程 cwd 是根目录时，codex 直接
   `Not inside a trusted directory`，claude 行为也不可预期。修法：
   `_kernel_working_dir` 兜底到用户 workspace，绝不返回空串。

**会话污染（我的失误，已修）**：第一版 E2E 脚本没传 `session_id`，每发一条
就在用户会话列表里新建一条「1+1 等于几」——跑完留了 7 个垃圾会话，已全部清理。
现在脚本用固定测试会话 + `finally` 自动删除，实测跑前跑后会话数都是 777。

### DSH 需要自己的凭证（环境问题，非代码 bug）

```
[DSH 错误] llm-deepseek: no API key for provider route "deepseek-official"
```

`~/.dsh/profiles/headless/` 没配 provider（`dsh-tui` profile 配了 `BUDDY_PROXY_API_KEY`，
headless 没有）。这是用户侧配置，不该由代码擅自改用户的 profile。
正确做法是 UI 把原始错误透出来 + 给配置指引。

### 已知取舍

| 项 | 取舍 | 原因 |
|---|---|---|
| `ethan_context` | False | 外部 runtime 有自己的 system prompt + 工具集，注入 Ethan 技能会打架 |
| `consent` | False | ACP 用 `--dangerously-skip-permissions`，权限模型无法与 Ethan consent 对齐 |
| 流式粒度 | 较粗 | `claude -p` 的 stream-json 不保证 token 级，text 按 assistant message 粒度到达 |
| `working_dir` | 需显式传 | 否则用进程 cwd（通常是安装目录），外部 CLI 容易误改项目 |

### 待做

- **Android 端内核 Tab**：desktop/web 已接，Android 的 `SettingsScreen` 需要先确认
  它那套 `SettingsUiState` 的数据通路（刚恢复成能编译的版本，40+ 回调里哪些是真通路
  还没逐个核实）
- **对比可观测**：`KernelStats` 已记录耗时/工具数/token，但还没落库 + 前端展示。
  `usage` 对外部内核恒为 0（CLI 不返回 token），做对比时要标注这个局限
- **按任务自动选**：`_infer_task_kind` 目前是关键词粗判，可换成模型分类

## 六、教训

1. **「检查脚本全绿」不等于实现了。** 用字符串匹配判断集成，5/5 全绿而功能为零。
   验收必须跑真实路径并断言真实输出。
2. **先看现有实现，再加模块。** 技能包、场景检测、反馈引擎三块，现有代码都已覆盖；
   新增的三套是并行重复机制。
3. **优化目标要对准真正的开销。** 目标是「减少 prompt 占用」，但上一轮对着技能包使劲，
   而真正的 34K 在 `tools.md`。先测量，再优化。
4. **编辑器里的假 UI 会掩盖真实问题。** Android 那个假设置页不仅没功能，还让
   `EthanApp.kt` 的调用方编译不过——但因为没有 CI 跑 Android 构建，一直没被发现。

### 本轮（2026-11-15）新增的教训

5. **修基础设施前，先摸清所有调用方的写法。** 修配置并发时我把 `save_config` 的
   diff 基线设成内存单例，而 50 处调用方全是「`get_config()` 改完直接 save」——
   基线已含改动 → 变更集恒为空 → 接口返回 `{"ok": true}` 但磁盘一个字没写。
   用户报「模型删不掉、加不上」才发现。**基础设施的语义变更必须以「调用方实际怎么写」
   为准，不能以「设计上应该怎么写」为准。**

6. **必须验证「写入 → 重新读盘」，不能只测函数本身。** 上面那个 bug，单测全绿、
   类型检查全过、接口返回成功——只有真正读盘才能发现。现在有
   `tests/test_config_write_contract.py`（7 条）专做这件事。

7. **排查时先确认自己在看对的文件。** 一度以为内核切换没落盘，查了很久——结果是我
   在看 `~/.ethan/config.yaml`，而 dev 实例用的是独立数据目录
   `/tmp/ethan-dev-data-8910/config.yaml`。**先确认环境边界，再动手查。**

8. **「能接受配置」不等于「配置生效」。** Codex 对 `-c mcp_servers.*` 和
   `config.toml` 都接受、不报错，但工具列表里始终没有 MCP 工具。不能因为配置写进去了
   就宣称支持——要看**功能是否真的到达模型**。

9. **给用户展示能力差异，别让用户自己踩坑。** Codex/OpenCode/Pi 不能共享 Ethan 工具，
   界面就明说原因（「Codex 能接受 MCP 配置但不加载其中的工具」），而不是诱导用户
   以为能用、试了才发现不行。

10. **删死代码比修死代码更对。** Android 那 21 个文件是三次未完成重构的产物，
    内部逻辑本身就不完整，修编译错误只是让它「看起来能编译」。它们零生产引用，
    删掉才是正确处置——**先证明没人用，再删，别硬修。**
