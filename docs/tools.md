# 工具系统使用指南

## 快速开始

工具让 Agent 能够执行真实操作：**运行命令、读写文件、搜索网页**等。

### 核心概念

- **BaseTool**: 工具基类，定义 `name`、`description`、`parameters`、`run()`
- **ToolRegistry**: 注册表，管理所有可用工具
- **ToolExecutor**: 并发执行器，支持多个工具并行调用

---

## 内置工具一览

### 🔧 基础工具

#### Shell 命令
```bash
shell(command="ls -la", timeout=30)
```
- 默认 30 秒超时
- 需要用户授权（高危命令每次必问）

#### 文件操作
```bash
file_read(path="~/config.yaml", max_lines=100)
file_write(path="/tmp/output.txt", content="...")
file_list(path="~/projects")
```
- 图片自动渲染卡片（VLM 模型可直接查看）
- 写文件需要授权（临时目录豁免）

#### 搜索工具
```bash
web_search(query="科技新闻", max_results=5)
rg_search(pattern="TODO", path="~/projects")
fd_find(pattern="config", extension="yaml")
```
- `web_search`: 默认 DuckDuckGo（免费），可切换 Tavily/SearXNG
- `rg_search`: 按内容搜索（基于 ripgrep）
- `fd_find`: 按文件名搜索（基于 fd）

#### 网页抓取
```bash
web_fetch(url="https://example.com/article")
```
- 提取纯文本，自动清理 HTML
- 不执行 JS（需浏览器自动化走 Skill）

---

### 📝 文档与知识

#### 文档管理
```bash
doc_save(path="work/report.md", content="# ...", title="报告")
doc_list(prefix="work/")
```
- 保存到 `~/.ethan/documents/`
- 一步完成落盘 + 交付

#### 知识库
```bash
knowledge_search(query="Python 异步编程")
knowledge_read(source="...md")
knowledge_add(content="...", title="笔记", tags=["python"])
knowledge_edit(source="...md", content="...", mode="append")
```
- 语义搜索 + 全文管理
- 支持追加或替换模式

---

### ⏰ 定时任务

```bash
schedule_create(job_id="reminder", prompt="提醒我喝水", interval_minutes=30)
schedule_create(job_id="report", prompt="生成摘要", cron="0 9 * * *")
schedule_list()
schedule_remove(job_id="reminder")
```
- 支持 cron 表达式或间隔分钟
- 持久化存储，重启后自动恢复

---

### 💼 飞书集成

```bash
lark_calendar_events(action="agenda")
lark_chat_messages(chat_id="xxx", count=20)
lark_message_send(chat_id="xxx", text="消息内容")
```
- 内部调用 `lark-cli`
- 发消息需要授权

---

### 🎴 结构化卡片

```bash
ui_card(card="compare", data={...})
```
- 对比 / 排行 / 统计 / 时间轴
- Web 端 A2UI 渲染，飞书端交互式卡片
- 见 [Skill: ui-card](skills.md) 获取模板

---

### 📁 文件交付

```bash
deliver_file(path="/path/to/file.pptx", title="报告")
```
- 交付任意格式文件（pptx/pdf/mp4 等）
- 前端渲染下载/预览卡片

---

## 高级功能

### 授权机制

敏感操作需要用户确认：

| 工具 | 触发条件 | 授权粒度 |
|------|---------|---------|
| `shell` | 普通命令 | 会话级（一次授权本会话有效） |
| `shell` | 高危命令 | 每次都问（rm -rf, sudo 等） |
| `file_write` | 非临时目录 | 目录级（子目录自动放行） |
| `file_read` | secrets 目录 | 单文件 |

**信任目录白名单**（免授权）:
```bash
ethan trust add /path/to/trusted/dir
ethan trust list
```

**超级权限模式**（Web 端）:
- 自动批准普通和高危非破坏性操作
- 仅破坏性操作（如 rm -rf）仍需确认

---

### MCP 协议

Ethan 可作为 MCP client 连接外部服务，或作为 MCP server 暴露 `ask_ethan` 工具。

**作为 Client**:
```yaml
tools:
  mcp:
    servers:
      - name: "dida365"
        command: "npx"
        args: ["-y", "@dida365/mcp-server"]
```

**作为 Server**:
- 启动 `ethan serve` 后访问 `/mcp/`
- 暴露 `ask_ethan(prompt, session_id?)` 工具
- 需要 API Key 鉴权（配置 `network.mcp_api_key`）

---

## 自定义工具

继承 `BaseTool` 并注册即可：

```python
from ethan.tools.base import BaseTool

class MyTool(BaseTool):
    name = "my_tool"
    description = "Does something useful"
    parameters = {"type": "object", "properties": {...}}
    
    async def run(self, **kwargs) -> str:
        # 实现逻辑
        return "结果"

# 注册
registry.register(MyTool())
```

无需修改 Agent Loop 或其他代码！

---

## 性能提示

- **Fast Path 模式**: 部分工具（`shell`, `file_read`）在 fast path 下可用
- **缓存**: 可缓存工具（`cacheable=True`）避免重复调用
- **无压缩**: 关键工具（`no_compress=True`）输出不被压缩，保持原始结构

---

## 常见问题

**Q: 如何切换搜索引擎？**  
A: 编辑 `~/.ethan/config.yaml`:
```yaml
tools:
  web_search:
    provider: tavily  # 或 searxng
    api_key: tvly-xxx
```

**Q: 为什么我的文件读不了图？**  
A: 确保图片格式为 png/jpeg/gif/webp，且未损坏。SVG/BMP 仅显示卡片。

**Q: 如何禁用某个工具？**  
A: 在 `agent_factory.py` 的 `build_tool_registry` 中注释掉对应注册行。

---

## 参考文档

- [完整设计文档](./tools-design.md)
- [Skill 系统](./skills.md)
- [接口文档](./interface.md)
