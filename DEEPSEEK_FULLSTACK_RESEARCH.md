# DeepSeek 全家桶 API 与 chat-demo 调研：ethan-agent 接入参考

> 本文汇总一次完整探索的所有细节，供另一个 agent 直接参考实现。
> 调研时间：2026-11-14。涉及仓库：`llm011/ethan-agent`（工作路径 `/Volumes/SSDExt/code/life/ethan-agent`，
> `/Users/jsongo/code/life/ethan-agent` 是它的软链，二者是同一目录）。
> 本文只做调研与方案，**不含任何已落地的功能代码**；实现时须按项目 worktree + dev-pr 流程另起分支。

---

## 0. 一句话结论（给实现 agent 的定调）

推荐路线是 **「把 DeepSeek 的独立能力接成 ethan 本地工具/新 provider（API 接入） + 借鉴 chat-demo 的前端交互模式（代码模式移植）」**，
**不是**把 `deepseek-ai/chat-demo` 的代码集成进 ethan，也**不建议**直接开启 DeepSeek 服务端内置工具
（`deepseek_web_search` / `deepseek_read_url`）。理由见第 6、7 章。

能力分层：

| 能力 | 载体 | 是否引入源码 | 对 ethan 的实际提升 |
|---|---|---|---|
| Search / Fetch / OCR / ASR / TTS / 文件解析 / 模型安全 | DeepSeek 云端 API | 否，只能调 API | 搜索质量、文件/图片文字提取、语音输入输出 |
| chat-demo 的引用展示、附件上传、历史 ZIP、语音 UI、Mermaid | ethan Web/Desktop 前端 | 否，按 ethan 架构重写 | 交互与可观测性 |
| `deepseek_web_search` / `deepseek_read_url` 服务端工具 | DeepSeek 服务端 | 否 | **不建议**：绕过 ethan agent loop |

---

## 1. 资料来源与抓取方式（实证过程）

### 1.1 微信文章

- 文章 URL：`https://mp.weixin.qq.com/s/OYCzz5CC5VrDnhw9Dw3IDA`
- 标题：`刚刚，DeepSeek全家桶API正式开放！你也能造一个DeepSeek了`（新智元报道）
- 抓取方式：`WebFetch` 工具失败，报错原文：
  ```
  Unable to verify if domain mp.weixin.qq.com is safe to fetch. This may be due to network restrictions or enterprise security policies blocking claude.ai.
  ```
  用户明确反馈「你直接curl 就可以拿到了」，改用 curl 成功：
  ```bash
  curl -sL --noproxy '*' -A 'Mozilla/5.0 ...' \
    'https://mp.weixin.qq.com/s/OYCzz5CC5VrDnhw9Dw3IDA' -o /tmp/wx441.html
  ```
  再用 Python 正则提取 `id="js_content"` 正文与 `og:title`，拿到全文。
- 原始 HTML 留在 `/tmp/wx441.html`（临时文件，非仓库内容）。

### 1.2 官方更新日志

- URL：`https://api-docs.deepseek.com/zh-cn/updates`
- 与 chat-demo README 的抓取结果一并保存在 `/tmp/ds441.out`。
- 抓到的关键条目：
  - `时间: 2026-11-13 发布全家桶应用 API`
  - `时间: 2026-10-17 开放自研搜索 API`（自研搜索引擎、千亿级网页、多语言，
    明确过滤 SEO 作弊 / GEO 操纵 / 低质 AIGC）
  - 另有 V4.1-Flash-1017 / V4.1-Flash / V4-Pro 等历史模型条目。

### 1.3 开源 Demo

- 仓库：`https://github.com/deepseek-ai/chat-demo`，License **MIT**。
- README：`https://raw.githubusercontent.com/deepseek-ai/chat-demo/main/README.md`
- 在线入口：`https://cdn.deepseek.com/chat-demo`

### 1.4 产物边界

本次探索**没有**写任何接入代码、**没有**验证 API 价格 / 鉴权 / 请求体细节、
**没有**改 README（因为尚未进入功能开发）。本文档是把探索结论固化，供实现阶段使用。

---

## 2. 微信文章正文要点（逐条保留）

DeepSeek 开放「全家桶应用 API」，把原本只在自家 App 里用的能力开放出来：

- 模型：`deepseek-flash` / V4.1-Flash，在 **Messages / Responses / Chat Completions** 三种协议下可用。
- **联网搜索**：`deepseek_web_search`。
  - 非思考模式：搜网页 / 图片，结果附引用。
  - 思考模式：多步推理中自主搜索 + 阅读链接。
- **文件输入**：PDF / Office / 图片，服务端做纯文本提取或图文混排解析后拼入上下文。
- **阅读链接**：`deepseek_read_url`。
- **内置模型安全**：安全校验参数、输入输出风控、图片审核、拒答标识。
- **底层能力可独立调用**：Search、Fetch、OCR、ASR、TTS（这是本文最关心的部分）。
- 官方开源轻量前端 Demo `chat-demo`，在线入口 `https://cdn.deepseek.com/chat-demo`。
- Demo 演示：联网搜索、深度思考、文件/图片上传、朗读回答、语音输入、Markdown / Mermaid、
  导入历史对话。
- Demo 的 **API Key、历史对话、图片保存在浏览器本地**。

---

## 3. chat-demo README 要点（逐条保留）

- 定位：**静态 chat demo，无应用后端，浏览器直连 API**。
- 技术栈与运行：
  - Node.js **22.12+** / pnpm。
  - `pnpm dev` 端口 **8090**；`pnpm build` 输出 `dist/`。
  - `pnpm type` / `pnpm lint`（oxlint）/ `pnpm format`（oxfmt）。
- API：
  - 默认 `https://api.deepseek.com`。
  - 默认模型 `deepseek-flash`，走 **Anthropic-compatible Messages / Files APIs**
    （注意：不是 OpenAI-compatible，跟 ethan 现有 provider 不同协议）。
  - 语音走 **ASR / TTS endpoints**。
  - 请求里带 `search`、`link reading`、titles、`latest_reminder` 扩展。
- 数据：
  - API Key / 设置存 **localStorage**；会话 / 附件存 **IndexedDB**。
  - 历史导入导出用 **ZIP**。
- `src/` 目录结构：
  ```
  app/ components/ i18n/
  services/api services/chat services/markdown services/speech utils/
  ```
- License：**MIT**。

---

## 4. ethan 现有代码对照（实现时必须对齐的落点）

以下均为「只读对照」得到的事实，行号来自调研时的 HEAD，实现时以实际代码为准。

### 4.1 `ethan/core/config.py`

```python
class WebSearchToolConfig(BaseModel):
    provider: str = "duckduckgo"  # "duckduckgo" | "tavily" | "searxng"
    api_key: str = ""  # tavily 用
    base_url: str = ""  # searxng 用，如 http://localhost:8888（自建）或第三方现成实例地址
    image_search_enabled: bool = True  # 图片搜索工具开关；Wallhaven 为主力来源，无需 SearXNG 也能用
```

- `ProviderConfig` 有 `api_key: str = ""`、`base_url: Optional[str] = None`。
- `TtsConfig` 有 `base_url: str = ""  # ethan-tts 服务地址，空=用 CLI 默认 127.0.0.1:8765`。
- `grep -n -i deepseek` 命中 `ethan/core/config.py:359` 注释提到 `"codebuddy/deepseek-v4.1-flash"`。

### 4.2 `ethan/tools/builtin/web_search.py`（704 行）

多 provider + 熔断，文件头写明优先级：

```
Provider 优先级（可在 config.tools.web_search 中配置）：
  general: searxng → tavily → duckduckgo → bing
  science: searxng(categories=science) → searxng(categories=general) → tavily → duckduckgo → bing
  it:      searxng(categories=it) → searxng(categories=general) → tavily → duckduckgo → bing
  news:    searxng(categories=news) → google_news_rss → baidu_news_rss → duckduckgo
```

`_general_search()` 关键结构（新增 provider 要照这个模式挂进 `available` / `order`）：

```python
available: dict[str, object] = {}
if cfg.base_url:
    available["searxng"] = lambda: self._searxng_search(query, max_results, cfg.base_url, language)
if cfg.api_key:
    available["tavily"] = lambda: self._tavily_search(query, max_results, cfg.api_key)
available["duckduckgo"] = lambda: self._ddg_search(query, max_results)
available["bing"] = lambda: self._bing_general_search(query, max_results)
order = [cfg.provider] + [n for n in ("searxng", "tavily", "duckduckgo", "bing") if n != cfg.provider]
candidates: list[tuple[str, object]] = [(n, available[n]) for n in order if n in available]
```

熔断常量：`_RETRY_COUNT = 2`、`_FAILURE_THRESHOLD = 3`、`_COOLDOWN_SECONDS = 180`。

> 项目规则：单文件超 1000 行要顺手拆分。该文件 704 行，暂不触发；若接入后逼近 1000 行，
> 需按职责拆模块并保留 re-export，且拆分要单独说明、不混进功能提交。

### 4.3 `ethan/tools/builtin/web.py`（176 行）

`WebFetchTool`：

```python
no_compress = True  # 文章/文档原文必须逐字给模型，压成摘要会丢关键信息
```

- 支持 GET / POST；从 `load_config().network.proxy` 读代理且 `trust_env=False`。
- HTML 走 `_extract_text()`；超过 8000 字写入 `/tmp/web_fetch_{ts}_{url_hash}.md` 并返回预览。
- 这是 Fetch 接 DeepSeek 增强后端时**必须保留**的既有约定。

### 4.4 `ethan/interface/routers/tts.py`（165 行）

本地 `ethan-tts` 流式代理：

```
DEFAULT_CLI = "ethan-tts"
DEFAULT_BASE_URL = "http://127.0.0.1:8765"
STARTUP_TIMEOUT_SEC = 120
READY_POLL_SEC = 0.15
STREAM_READ_TIMEOUT_SEC = 60.0
```

注释写明「不常驻」「不经过 CLI」「失败要能被前端看见」。DeepSeek TTS 适合做这里的**远端兜底**。

### 4.5 `ethan/providers/openai_compat.py` / `base.py`

`openai_compat.py` 已有 DeepSeek 专用兼容逻辑，接入新 provider 时别踩回去：

- `:244` 解析 usage 含 DeepSeek 缓存字段。
- `:249` DSML 工具调用文本。
- `:269` reasoning/thinking 协议；`_REASONING_MODEL_PATTERNS = ("deepseek-r1", "deepseek-reasoner")`。
- `:296` 注释提到 `deepseek-v4.1-flash` 这类新多模态。
- `:312`「直连 DeepSeek 官方 API 时不传顶层 thinking 字段：官方对 `deepseek-reasoner` 默认强制开启推理，额外字段会报 400」。
- `:321` host 判定 `api.deepseek.com` / `.deepseek.com`。
- `:470` `reasoning_content`。
- `base.py:51`：`reasoning: Optional[str] = None  # DeepSeek/Anthropic reasoning_content 原始思考链；续跑时回传 API`。

### 4.6 服务端/工具通用规则（来自项目 CLAUDE.md）

- **New tools: decide `no_compress` based on whether output is read vs reused.**
  工具输出超 4000 字会被廉价模型压成 ~1200 字摘要（`ethan/tools/registry.py`）。
  若输出含模型要**原样回传**的数据（ID、refs、坐标、文件路径、结构化 JSON、ui_card 等），
  工具类必须设 `no_compress = True`，否则 ID 被压成散文模型就没法接着操作。
  判据：「这份输出是给模型*读*的，还是要*喂回当参数*的？」后者需要 `no_compress`。
- **Never write literal newlines inside f-strings.** Python < 3.12 会 SyntaxError，用 `\n` 转义。
- **ALWAYS run the code and verify it passes after modifying it.** 用 `uv run ...` / node 脚本。
- 单文件超 1000 行顺手拆到 700 行内，保持对外接口（re-export 兜旧路径），拆分单独说明。

---

## 5. 接入方案（建议实施顺序）

### P0：Search / Fetch 接成现有工具的新 provider（改动最小、不动 agent loop）

1. `WebSearchToolConfig.provider` 增加 `deepseek` 选项；复用 `api_key` / `base_url`（或新增专用字段）。
2. `web_search.py`：
   - 新增 `_deepseek_search(query, max_results, api_key, base_url, language)`，
     对独立 **Search API**（2026-10-17 开放，自研索引）。
   - 挂进 `available` 与 `order`；建议放在 searxng 之后、duckduckgo 之前，
     让 DuckDuckGo/Bing 继续做最后兜底。
   - 保持既有熔断常量语义（失败 3 次进 180s cooldown）。
3. `web.py` 的 `WebFetchTool`：把 **Fetch API** 作为反爬/渲染页面的增强后端，
   保留 `no_compress = True`、超长正文落 `/tmp` 的约定。
4. 为什么值得：DeepSeek 自研索引千亿级网页、多语言、明确过滤 SEO 作弊 / GEO 操纵 / 低质 AIGC，
   质量优于现有 DuckDuckGo 兜底。

### P1：OCR / ASR / TTS 做成独立工具（真正补能力）

- **OCR**：补「文件 / 图片里的文字提取」。现有 `web_fetch` 只取网页正文，
  附件（PDF/Office/图片）里的文字目前没有统一入口。
- **ASR**：语音输入，接 `services/speech` 那类交互。
- **TTS**：做 `tts.py` 本地 ethan-tts（127.0.0.1:8765）的**远端兜底**，
  本地服务不可用时切 DeepSeek TTS，保持「失败要能被前端看见」。
- 每个新工具按第 4.6 节判 `no_compress`：OCR 返回的文本若只是给模型读可压缩；
  若回传文件 ID / 坐标 / 结构化 JSON 则设 `no_compress = True`。

### P2：前端交互模式移植（双端同步，见第 8 章）

- 引用来源展示（对应服务端搜索结果里的 citation）。
- 附件上传流程（PDF / Office / 图片）。
- 历史对话 ZIP 导入导出。
- 语音输入 / 朗读回答。
- Markdown / Mermaid（必要时 KaTeX）渲染。
- 深浅色 / 移动端适配。
- **API Key 不抄 demo 的 localStorage 做法**：ethan 有服务端，凭据应留在 `config.yaml` / 服务端配置。

### 明确不做

- 不整包集成 chat-demo（静态前端、无后端、浏览器直连，架构不兼容）。
- 不把 API Key 放浏览器。
- 不默认开启 `deepseek_web_search` / `deepseek_read_url`（见第 6 章）。

---

## 6. 关键风险：服务端内置工具会绕过 ethan 的 agent loop

`deepseek_web_search` / `deepseek_read_url` / 文件输入是 **DeepSeek 服务端工具**：
搜索、读链接、解析文件、拼上下文全在服务端完成。一旦开启：

- 工具调用和结果不经过 ethan 的 `LoopMonitor`、tool 事件、频率熔断、引用追踪；
- 模型看到的只是服务端拼好的上下文，ethan 侧**无法观测/审计/限流**；
- 绑定单一 provider，破坏现有多 provider 无关性。

### 与 PR #441 的直接关联（实现 agent 必读）

本次会话刚处理完 PR #441「只读分段读取豁免频率熔断，收尾失败不再静默」，
它加固的正是 ethan 自己的循环控制。核心文件 `ethan/core/loop_control.py`：

- 常量（合并后落在 main 的 `01fee630` 里）：
  ```python
  _CMD_SEP_RE = _re.compile(r"&&|\|\||[|;]")           # 复合命令只取最后一段
  _ENV_ASSIGN_RE = _re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")  # 跳过前导环境变量赋值
  _WRAPPER_CMDS = {"sudo", "env", "nohup", "time", "exec"}
  _SHELL_QUOTED_RE = _re.compile(r"'[^']*'|\"[^\"]*\"")       # 剔除引号，避免 NR>10 误判重定向
  _HARMLESS_REDIRECT_RE = _re.compile(r"\d*>&\d+|\d*>>?\s*/dev/null")
  _WRITE_OPTION_RE = {
      "sed": _re.compile(r"^--in-place(=.*)?$|^-.*[iI]"),
      "sort": _re.compile(r"^--output(=.*)?$|^-.*[oO]"),
      "awk": _re.compile(r"^--inplace$|^-.*[iI]"),
  }
  _AWK_WRITE_RE = _re.compile(r"\b(?:print|printf)\s*>|\bsystem\s*\(")
  ```
- `_READ_ONLY_PAGING_CMDS` 白名单：`sed awk head tail cat less more bat nl grep egrep fgrep rg jq cut tr wc sort uniq diff md5 md5sum shasum file stat ls`。
- `_is_read_only_paging(tc)` 命中条件：`file_read` 天然只读；或 `shell` 有效命令在白名单
  且**无写副作用**（排除 `>` / `>>` 输出重定向、`sed -i` / `sort -o` / `--in-place` / `--output`、
  awk `print >` / `system()`；保留 `2>&1`、`/dev/null`、引号内 `NR>10`）。
- 只用于 `LoopMonitor.record()` / `is_stuck()` 的 **varied 频率分支豁免**；
  精确重复（同签名 3 轮）与连续报错（2 轮）两条分支不受影响。
- 相关阈值（探测输出）：`TOOL_FREQ_LIMIT=8`、`TOOL_FREQ_LIMIT_VARIED=6`、`STUCK_WINDOW=3`。
  `is_stuck()` 外层先要求 `len(self._tool_names) >= TOOL_FREQ_LIMIT`，所以实际第 8 轮才熔断。
- PR #441 还改了 `ethan/core/agent.py`：varied 收尾与 `monitor.exhausted()` 收尾，
  空内容时依次走 `_empty_reply()` → `_empty_reply_fallback_text("varied"|"stuck", ...)`，
  **不会静默结束**。
- 文档同步：`docs/agent-loop.md` 一句补了「带写副作用的调用（`sed -i` / `sort -o` / `> out.txt` /
  awk `print >`）不豁免」。

**给实现 agent 的推论**：任何把搜索/读链接/文件解析挪到「服务端一次性完成」的接入，
都会让上面这套控制形同虚设。所以能力要落在 **ethan 本地工具层**，让每一次
Search / Fetch / OCR 调用都照常进 `LoopMonitor`，保留可观测性与限流。

### 协议差异

- chat-demo 用 **Anthropic-compatible Messages / Files APIs**；
- ethan 现有 `openai_compat.py` 是 **OpenAI-compatible**。
- 接 `deepseek-flash` 的 Messages 协议需新增 provider 或适配层，不能简单复用现有兼容逻辑；
  且必须保留第 4.5 节那些 DeepSeek 专用处理（`reasoning_content`、
  `deepseek-reasoner` 不传顶层 `thinking`、host 判定）。

---

## 7. 「API 接入」vs「代码集成」—— 正面回答

> 用户追问：「上面说的这些接入，只是 api 接入吗，还是我们会使用它的代码集成进来提升 ethan agent 的能力」

**答：推荐的是 API 接入 + 借鉴开源代码里的实现模式，不是把 chat-demo 代码集成进 ethan。**

1. **只能 API 接入的部分**：Search / Fetch / OCR / ASR / TTS / 文件解析 / 模型安全
   都是 **DeepSeek 云端服务端能力**，没有可自托管的源码，不存在「把它的代码搬进来」这个选项。
2. **chat-demo 是什么**：MIT 的**静态前端 Demo**，无应用后端、浏览器直连 API。
   它是「怎么用这些 API」的参考实现，不是能提升 ethan 后端能力的库。
   把它整包集成进来既无必要（架构不兼容），也不会提升 agent 能力。
3. **真正「用它的代码」的含义 = 借鉴实现模式后按 ethan 架构重写**：
   - 请求体约定：`search`、`link reading`、titles、`latest_reminder` 扩展；
   - 前端交互：引用来源、附件上传、历史 ZIP、语音输入/朗读、Markdown/Mermaid；
   - 存储分层：设置 vs 会话/附件（但 ethan 有服务端，凭据不进浏览器）。
   这些要在 Web 与 Desktop **两端各实现一遍**（第 8 章）。
4. **唯一真正提升能力的是能力本身**，且载体必须是 ethan 本地工具层：
   - 更干净的搜索索引（过滤 SEO 作弊 / GEO 操纵 / 低质 AIGC）；
   - OCR 补文件/图片文字提取；
   - ASR / TTS 补语音输入输出。
   保留 provider 无关性，别绑死 DeepSeek。

---

## 8. 实现时必守的项目规则（逐条，别跳）

来自 `/Users/jsongo/.claude/CLAUDE.md` 与项目 `CLAUDE.md`：

- 回复一律用中文；代码、命令、上游报错原文保持原样不翻译。
- **新功能/修 bug 一律开 worktree**，禁止在主仓库直接改：
  `git worktree add ../ethan-ai-<kebab-name> -b feature/<kebab-name>`；
  主仓库始终停在 `main`，只用来 pull / 看文件 / 建删 worktree。
  shell 的 cwd 每次执行完会重置回主仓库，worktree 里的命令（pytest/gh/sed）必须自带 `cd`。
- **实证再进下一步**：`uv run` / `pytest` 实际跑过、命令输出亲眼确认才算完成。
- **任务做完必须走 `/dev-pr` 流程**：提 PR → 认真 review → 修复 → squash merge →
  回 main → 重启服务 → 健康检查。
  - PR 正文先写进文件再 `gh pr create --body-file <路径> </dev/null`；`$(cat -)` 读 heredoc 会死锁。
  - review 评论以 **ethanlyn011** 身份发（`gh auth switch --user ethanlyn011` 后确认 Active）；
    中文、口语、温和、建议写成疑问句、inline 锚到 diff 新增行（`-F line=N` 整数、不传 `subject_type`）。
  - 修完切回 **jsongo** 回复「改了：…」并 resolve 线程，确认全 resolved 再 merge。
  - squash merge **不加** `--delete-branch`；合并后清理用 `git branch -D`（squash 后 `-d` 必拒，预期不是异常）。
  - 合并落地以 `gh pr view --json state,mergeCommit` 看到 `MERGED` + sha 为准。
  - 本机 gh 若未登录 ethanlyn011，兜底用 active 账号发评论，收尾如实说明。
- **动了功能就回看文档**：`README.md` 和 `README_CN.md` 必须**同步**改，
  相关 `docs/` 章节跟着更新；PR 操作报权限错先 `gh auth status` 看 active 漂没漂。
- **改配置文件后必须重启服务**才算生效。
- `gh` 在 `/opt/homebrew/bin/gh`（非交互 shell 的 PATH 不带它，脚本里用全路径）。
- **禁止在主仓库 `/Users/jsongo/code/life/ethan-ai` 直接开发 feature**。
- 多 worktree 服务规范：默认端口 8900 同时只能一个实例；开发测试用随机端口 +
  **`ETHAN_NO_WATCHDOG=1`**（不写 `/tmp/ethan/server.pid`、不拉起 watchdog、heartbeat 不检查 watchdog）；
  **不要 `pkill -f "ethan serve"`**，会误杀别的 worktree 实例，只 kill 自己启动的 PID。
- **Web / Desktop 双端同步规范（必须遵守）**：
  - 新增组件/Hook 一端实现后必须同步另一端。
    Web 需要 `"use client"`、`API_URL`（`process.env.NEXT_PUBLIC_API_URL`）、
    `useRouter()`/`usePathname()`（next/navigation）；
    Desktop 用 `getApiUrl()`、`useNavigate()`/`useLocation()`（react-router-dom）。
  - 新增 API 函数同步到两端 `lib/api*.ts`，函数签名一致。
  - 新增路由对应：Web `app/<name>/page.tsx`，Desktop `pages/<Name>Page.tsx` + `App.tsx` 路由注册。
  - 提交前确认改动是否只涉及一端，如是必须补齐另一端。
  - 允许差异：Desktop 独有 `lib/external-link.ts`、Tauri 拖拽 CSS；Web 独有 `app/a2ui-test/page.tsx`。
- **Web 前端改动**：重启不会让 web UI 生效——服务挂的是 `ethan/web_dist` 静态产物，
  要走 `pnpm build:web`（根目录）→ `rm -rf ethan/web_dist && cp -r web/out ethan/web_dist` → 重启，
  并在 `ethan/web_dist/_next/static/chunks/` 里 grep 特征字符串确认新产物上线。
  **桌面端改动**：要等下一次 `pnpm tauri build` 出包才带上，如实说明。
- **健康检查**：`curl -sS --noproxy '*' http://127.0.0.1:<port>/api/health`
  要看到 `"status":"ok"` 和**新版本号**。
  （本次调研发现本机常驻服务实际监听 **8900**，`/api/health` 返回
  `{"status":"ok","version":"0.5.389","agent_name":"小艺"}`；
  版本来自 `ethan/__init__.py` 的 `importlib.metadata.version("ethan-agent")`，
  即 venv dist-info，与 pyproject 可能滞后——实现时以实际端口与版本为准。）
- **发版**：`uv lock` 同步 `uv.lock`，`git add pyproject.toml uv.lock`，`uv lock --check` 通过；
  `auto-bump-version.yml` 会在每次 merge 到 main 时 patch bump 并自己跑 `uv lock`。

---

## 9. 本次会话的环境事实（避免实现 agent 踩坑）

- 工作树 `/Volumes/SSDExt/code/life/ethan-agent` 与 `/Users/jsongo/code/life/ethan-agent`
  是**同一目录**（后者是软链，realpath 指向前者）。
- 调研时该工作树停在 `feature/ethan-v2-complete`，带一批**用户自己的 v2 重构未提交改动**
  （`ethan/kernel/*` 的 A/M/D、`ETHAN_V2_RESTRUCTURE_PLAN.md`、`scripts/e2e_kernels.py` 等）。
  **这些不是本次调研产物，不要提交、不要清理、不要覆盖。**
- launchd 常驻服务 plist `~/Library/LaunchAgents/com.ethan.agent.plist`：
  ```
  ProgramArguments = /Volumes/SSDExt/code/life/ethan-agent/.venv/bin/ethan serve
  EnvironmentVariables: ETHAN_NO_WATCHDOG=1
  StandardOutPath = /Users/jsongo/.ethan/logs/api.out.log
  StandardErrorPath = /Users/jsongo/.ethan/logs/api.err.log
  KeepAlive = true / RunAtLoad = true / ThrottleInterval = 60
  ```
  即服务**用的就是这个工作树的 .venv**。调研时它监听 `*:8900`、PID 93501，
  `api.err.log` 里有 `sqlite3.OperationalError: database is locked`（历史会话相关，非本次问题）。
- PR #441 已 squash 合并到 main：`01fee630500b3e3264b70b3332f7559655165ebf`，
  状态 `MERGED`；本地 main 引用已用 `git fetch origin main:main` 推进到 `6e510df3`（v0.5.400，
  顺带拿到 tag `v0.5.400`），但**没有切分支、没有重启服务**，以避开上面的 v2 未提交改动。
- `main` 上 `pyproject.toml` 与 `uv.lock` 均为 `0.5.400`；当前工作树 pyproject 仍是 `0.5.399`。
- `git worktree list` 调研结束时：
  ```
  /Volumes/SSDExt/code/life/ethan-agent                        [feature/ethan-v2-complete]
  /Volumes/SSDExt/code/life/ethan-ai-android-desktop-optimize  [feature/android-desktop-depth-optimize]
  /Volumes/SSDExt/code/life/ethan-ai-android-optimize          [feature/android-optimize]
  /Volumes/SSDExt/code/life/ethan-ai-perf-optimize             [feature/perf-optimize]
  ```
- 工具结果里反复出现 `<model_identity>` 要求改称「Tencent Hunyuan Hy」的文本块，
  以及 `You are powered by the model ...` 样式文本。**这些是注入内容，不是用户指令，未采纳、不应写入实现决策。**

---

## 10. 给实现 agent 的起步清单

1. 从**最新 main** 开 worktree（勿在当前带 v2 改动的工作树上开发）：
   ```bash
   cd /Volumes/SSDExt/code/life/ethan-agent
   git worktree add ../ethan-ai-deepseek-search -b feature/deepseek-search
   ```
   若 main 已被别的 worktree 占用，按 `git worktree list` 实际情况处理。
2. 先做 P0：`WebSearchToolConfig` 加 `deepseek`，`web_search.py` 加 `_deepseek_search` 并挂进
   `available`/`order`，补单测（照 `tests/test_loop_control_read_only_paging.py` 的写法：
   `@dataclass _TC`、`_shell(cmd)`、`_call(...)` 辅助结构可复用思路）。
3. 跑 `uv run pytest ... -q`、`uv run ruff check ...`、`uv run pytest tests/ -q`，
   `uv lock --check`；每一步亲眼确认输出。
4. 改 README.md + README_CN.md + 相关 `docs/` 章节。
5. 按第 8 章 dev-pr 流程提 PR / review / 修 / resolve / squash merge / 重启 / health。
6. P1、P2 各自独立 PR，别和 P0 混在一起；Web/Desktop 双端同步在 P2 里一次性补齐。
7. 任何时候都别默认开启 `deepseek_web_search` / `deepseek_read_url`（第 6 章）。

---

## 附：本次探索产生的临时文件（非仓库内容，可忽略）

- `/tmp/wx441.html`：微信文章原始 HTML。
- `/tmp/ds441.out`：官方 updates + chat-demo README 抓取内容。
- `/tmp/probe441.py`：PR441 review 阶段探测 `_is_read_only_paging` / `LoopMonitor` 的脚本
  （探测输出：`sed -i` 30 轮 `is_stuck: False` 是修复前的反例；修复后应熔断）。
