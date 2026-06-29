# 工具系统设计文档

## 概述

工具系统让 Agent 能够执行真实操作：运行命令、读写文件、搜索网页等。
LLM 通过 tool call 请求工具，工具系统负责执行并把结果回传给 LLM。

设计原则：**完全可插拔**。新增功能 = 新增一个 Tool 文件，Agent Loop 和 Provider 完全不需要改动。

---

## 三层结构

![Tools 三层结构](./images/tools-layers.jpg)
<!-- diagram-source
```
BaseTool（抽象）
    │  name / description / parameters / run()
    ▼
ToolRegistry（注册表）
    │  register() / get() / all()
    ▼
ToolExecutor（执行器）
    │  接收 ToolCall 列表，asyncio.gather 并发执行
    ▼
Agent Loop
```
-->

---

## BaseTool 接口（`ethan/tools/base.py`）

```python
class BaseTool(ABC):
    name: str           # LLM 用这个名字来调用
    description: str    # 告诉 LLM 这个工具干什么（影响调用决策）
    parameters: dict    # JSON Schema，定义入参
    fast_path: bool = False  # 是否在 fast path 模式下提供给 LLM

    async def run(self, **kwargs) -> str  # 执行逻辑，返回字符串
```

设计决策：
- `run()` 返回纯字符串而非结构化数据，因为最终是给 LLM 阅读的
- 异步接口，所有 I/O 都不阻塞 event loop
- `parameters` 用 JSON Schema 描述，直接传给 LLM 的 function/tool 定义
- `fast_path = True` 的工具会在 fast path 模式下随简化版 system prompt 一起传给 LLM；目前默认开启的有 `shell` 和 `file_read`

---

## ToolExecutor 并发执行

LLM 有时会在一次回复中请求多个 tool（如同时查文件和执行命令）。
`ToolExecutor` 用 `asyncio.gather()` 并发执行，减少延迟。

错误处理：工具不存在或执行抛异常 → 返回 `ToolResult(is_error=True)`，不崩溃整个 loop。
LLM 会看到错误信息并决定如何处理（重试或换个方式）。

---

## 内置工具一览

### ShellTool — `ethan/tools/builtin/shell.py`

执行 shell 命令。

```
shell(command="ls -la", timeout=30)
```

安全设计：
- 默认 30 秒超时
- 输出超 8000 字符自动截断
- `asyncio.create_subprocess_shell` 异步执行

### WebSearchTool — `ethan/tools/builtin/web_search.py`

搜索互联网信息。默认使用 DuckDuckGo，无需 API Key；也支持切换到 Tavily 以获得更精准的结构化结果。

```
web_search(query="今天科技新闻", max_results=5)
```

**切换 Tavily**：在 `~/.ethan/config.yaml` 中添加：

```yaml
tools:
  web_search:
    provider: tavily
    api_key: tvly-xxxxxxxxxxxxxxxx
```

设计决策：
- 默认 DuckDuckGo：免费、无需注册、无 rate limit
- Tavily：需要 API Key，结果更精准，适合研究型搜索任务
- 配置热切换，无需重启服务

### WebFetchTool — `ethan/tools/builtin/web.py`

抓取网页并提取可读文本。

```
web_fetch(url="https://example.com/article")
```

设计决策：
- 用正则清理 HTML（移除 script/style/标签），保留纯文本
- 超过 8000 字符截断，防止 context 爆炸
- 没用 BeautifulSoup 或 readability，保持零额外依赖

> `web_fetch` 只抓静态 HTML 正文，不执行 JS、不能交互。需要操作页面（点击/填表/登录态）或抓 JS 渲染的内容时，走 Skill 系统的 `agent-browser` / `dev-browser`（见 [Skill 系统 · 浏览器自动化](./skills.md#浏览器自动化agent-browser-vs-dev-browser)）。

### FileReadTool — `ethan/tools/builtin/file.py`

读取本地文件。

```
file_read(path="~/config.yaml", max_lines=100)
```

安设计：
- 文件超过 1MB 拒绝读取，提示用 max_lines
- 输出超 8000 字符截断

### FileWriteTool — `ethan/tools/builtin/file.py`

写入本地文件。

```
file_write(path="/tmp/output.txt", content="...", append=False)
```

设计决策：
- 自动创建父目录
- 支持 append 模式

### FileListTool — `ethan/tools/builtin/file.py`

列出目录内容。

```
file_list(path="~/projects")
```

### RipgrepTool — `ethan/tools/builtin/rg_search.py`

基于 ripgrep，在文件内容中进行正则搜索。速度极快，自动遵守 `.gitignore` 规则。

```
rg_search(pattern="TODO", path="~/projects", case_sensitive=False, file_type="py", max_results=50)
```

参数：

| 参数 | 类型 | 说明 |
|------|------|------|
| `pattern` | string（必填）| 搜索的正则或字面字符串 |
| `path` | string | 搜索根目录，默认当前目录 |
| `case_sensitive` | bool | 是否区分大小写，默认 false |
| `file_type` | string | 限定文件类型（如 `py`、`js`、`md`） |
| `max_results` | int | 最多返回结果数，默认 50 |

设计决策：
- 直接调用系统 `rg` 命令，性能远超纯 Python 实现
- 自动跳过 `.git`、`node_modules` 等目录（`.gitignore` 支持）
- 适合在大型代码仓库中快速定位代码片段

### FdTool — `ethan/tools/builtin/fd_find.py`

基于 fd，按文件名/目录名模式查找文件。自动遵守 `.gitignore` 规则。

```
fd_find(pattern="config", path="~/projects", file_type="f", extension="yaml", max_results=20)
```

参数：

| 参数 | 类型 | 说明 |
|------|------|------|
| `pattern` | string（必填）| 文件名匹配模式（支持正则） |
| `path` | string | 搜索根目录，默认当前目录 |
| `file_type` | string | `f`（文件）、`d`（目录）、`l`（符号链接） |
| `extension` | string | 按扩展名过滤（如 `py`、`json`） |
| `max_results` | int | 最多返回结果数，默认 50 |

设计决策：
- 直接调用系统 `fd` 命令，比 `find` 更快、语法更简洁
- 自动跳过隐藏目录和 `.gitignore` 中忽略的路径
- 与 `rg_search` 形成互补：`fd_find` 找文件位置，`rg_search` 找文件内容

### ScheduleCreateTool — `ethan/tools/builtin/schedule.py`

创建定时任务，支持 cron 表达式或 interval 两种模式。任务持久化到 APScheduler SQLite，服务重启后自动恢复。

```
schedule_create(job_id="morning-reminder", prompt="提醒我喝水", interval_minutes=30)
schedule_create(job_id="daily-report", prompt="生成今日摘要", cron="0 9 * * *")
```

参数：

| 参数 | 类型 | 说明 |
|------|------|------|
| `job_id` | string（必填）| 唯一任务 ID |
| `prompt` | string（必填）| 任务触发时发给 Agent 的指令 |
| `cron` | string | 5 段 cron 表达式（分 时 日 月 周） |
| `interval_minutes` | int | 每 N 分钟执行一次 |

`cron` 和 `interval_minutes` 二选一。执行时会自动创建专属 Session，执行结果保存在该 Session 中，可在界面的"定时任务"菜单查看。

### ScheduleListTool — `ethan/tools/builtin/schedule.py`

列出当前所有定时任务及其状态。

```
schedule_list()
```

### ScheduleRemoveTool — `ethan/tools/builtin/schedule.py`

按 job_id 删除定时任务。

```
schedule_remove(job_id="morning-reminder")
```

### KnowledgeSearchTool — `ethan/tools/builtin/knowledge.py`

在个人知识库中语义搜索相关条目。

```
knowledge_search(query="Python 异步编程", limit=5)
```

### KnowledgeAddTool — `ethan/tools/builtin/knowledge.py`

向个人知识库添加条目（文本片段、笔记、参考资料等）。

```
knowledge_add(content="...", title="笔记标题", tags=["python", "async"])
```

---

## 新增自定义工具

只需继承 `BaseTool` + 注册：

```python
class MyTool(BaseTool):
    name = "my_tool"
    description = "Does something useful"
    parameters = {"type": "object", "properties": {...}, "required": [...]}

    async def run(self, **kwargs) -> str:
        ...

# 注册
registry.register(MyTool())
```

LLM 会自动在 tool 列表中看到它。无需修改 Agent Loop、Provider 或任何其他代码。

---

## MCP 协议支持（计划中）

MCP（Model Context Protocol）让 Ethan 连接外部 MCP server（如数据库、浏览器等）。

实现思路：
- 用 `mcp` Python SDK 作为 client
- 连接到 MCP server 后，自动将其暴露的 tools 注册到 `ToolRegistry`
- 对 Agent Loop 完全透明

---

## 关于 Tool 数量对 LLM 的影响

当前 8 个内置工具。每增加一个 tool，LLM 的 system prompt 就多几百 token（tool 的 JSON Schema）。

经验法则：
- < 10 个工具：对 LLM 判断力无明显影响
- 10-20 个：需要更精确的 description 来帮助 LLM 区分
- > 20 个：考虑分组，按需加载（类似 Skill 的匹配机制）

---

## 工具注册范围

并非所有工具在所有接口中都注册。当前注册情况：

| 工具 | CLI | Web API (`/chat`) | Lark Bot | Fast Path |
|------|:---:|:---:|:---:|:---:|
| shell | ✓ | ✓ | ✓ | ✓ |
| file_read / file_write / file_list | ✓ | ✓ | ✓ | ✓ (read) |
| web_search / web_fetch | ✓ | ✓ | ✓ | — |
| rg_search / fd_find | ✓ | ✓ | ✓ | — |
| schedule_create / list / remove | ✓ | ✓ | ✓ | — |
| knowledge_add / knowledge_search | ✓ | ✓ | ✓ | — |
