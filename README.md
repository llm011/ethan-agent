# Ethan Agent

[中文文档](./README_CN.md)

A lightweight, extensible personal AI agent built in Python. Designed to run persistently on your own hardware with memory that grows over time, scheduled tasks, and a pluggable tool/skill system.

Ethan combines ideas from [OpenClaw](https://github.com/openclaw/openclaw) (structured agent loop, layered memory), [Hermes Agent](https://github.com/NousResearch/hermes-agent) (self-improving skills, memory consolidation), and [nanobot](https://github.com/HKUDS/nanobot) (minimal core, readable codebase).

## Features

- **Multi-model support** — Connect to Claude, GPT, Gemini, or any OpenAI-compatible endpoint (Ollama, LM Studio, OpenRouter). Switch models mid-conversation with a single slash command. Provider-level proxy and alias support built in.

- **Persistent memory** — A three-tier memory system (hot/warm/cold) keeps context across long conversations without blowing up token costs. Recent turns stay verbatim; older context is batch-compressed into summaries by a cheap model (auto-inferred from your main model); key facts persist forever in a cross-session store.

- **Session management** — Every conversation is automatically saved to SQLite. Resume any past session with `ethan -r last` or browse history with `/sessions`. Sessions include full message replay and metadata.

- **Skill system** — Two-source loading: built-in skills ship with the project (`ethan/skills/<name>/SKILL.md`); user skills live in `~/.ethan/skills/`. Both support a directory format (`<name>/SKILL.md` + `references/`) and the legacy single-file `.md` format. Built-in skills include `channels`, `lark-im`, and `home-assistant`. Skills matched by keyword triggers are injected into the system prompt; skills can also be auto-generated from complex sessions (Hermes-style).

- **Fast Path** — Simple commands short-circuit the full agent loop. The fast path shares the same tool set as the full agent (filtered by `tool.fast_path = True`, e.g. `shell` and `file_read`), only the system prompt differs. Skills can opt into the fast path via `fast_path: true` frontmatter, and config supports `fast_skill_triggers`.

- **Prompt Caching** — The Anthropic provider splits the system prompt at the `Current time:` boundary. The stable prefix gets `cache_control` (ephemeral), so repeated calls within 5 minutes pay only 0.1× input token cost.

- **Tool system** — Fully pluggable: implement `BaseTool`, register it, done. Ships with shell execution, web search (DuckDuckGo), web page fetching, file I/O, ripgrep/fd search, schedule management, and knowledge base operations. Tools expose a `fast_path` field to control whether they are available in fast-path mode.

- **Scheduled tasks** — Create cron or interval jobs that persist across restarts (APScheduler + SQLite). A built-in heartbeat job runs periodically to deduplicate facts and execute tasks defined in `heartbeat.md`.

- **Knowledge base** — Vector search powered by `sqlite-vec`. Add notes/snippets via the `knowledge_add` tool or Web UI; retrieve with `knowledge_search`. The `/knowledge/search` HTTP endpoint exposes semantic search to external callers.

- **HTTP API** — A FastAPI server (`ethan serve`) exposes `/chat` (SSE streaming, HOT_SIZE=20 sliding window), `/models`, `/health`, `/knowledge/search`, `/channels`, and `/system-prompt-preview`. Ready to plug into a web frontend or mobile app.

- **Web UI** — Next.js 16 browser interface with pages for chat, memory (Facts / Episodes / Procedures tabs with edit/delete and Markdown rendering), knowledge base, schedule, skills, sessions, settings (proxy, max_tokens, fast-path keywords, heartbeat config, system prompt preview), and a new `/channels` channel management page. Message bubbles show TTFT latency.

- **Fast CLI** — A lightweight REPL powered by prompt_toolkit with proper CJK character handling, a bottom status bar (model, tokens, path), slash commands for in-session control, and streaming output that starts printing the moment the first token arrives.

## Quick Start

### Prerequisites

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) package manager

### Install

```bash
git clone https://github.com/llm011/ethan-agent.git
cd ethan-agent
uv sync
```

### Configure

Create `~/.ethan/config.yaml` (auto-generated on first run), or set environment variables:

```bash
cp .env.example .env
# Edit .env with your API keys
```

Alternatively, use the CLI:

```bash
# Set up a provider
ethan provider set openai_compat --api-key sk-xxx --base-url https://api.example.com/v1

# Add a model
ethan model add gpt-4o -p openai_compat -d "GPT-4o"

# Set default model
ethan model default gpt-4o
```

### Run

```bash
# Interactive REPL
uv run python -m ethan.interface.cli

# Single-turn query
uv run python -m ethan.interface.cli -p "What's the weather in Tokyo?"

# Specify model
uv run python -m ethan.interface.cli -m claude-sonnet-4-6

# Resume last session
uv run python -m ethan.interface.cli -r last

# Start HTTP API server
uv run python -m ethan.interface.cli serve
```

### Install globally (optional)

```bash
chmod +x bin/ethan
ln -s $(pwd)/bin/ethan ~/bin/ethan
# Then use: ethan "hello"
```

## Architecture

```
ethan/
├── core/
│   ├── agent.py               # ReAct agent loop
│   └── config.py              # YAML config (~/.ethan/config.yaml)
├── providers/
│   ├── base.py                # Unified interface (Message, ToolCall, BaseProvider)
│   ├── anthropic.py           # Claude native protocol
│   ├── openai_compat.py       # OpenAI-compatible protocol
│   └── manager.py             # Route model ID → provider
├── memory/
│   ├── session.py             # Session persistence (SQLite)
│   ├── working.py             # Three-tier sliding window memory
│   ├── consolidator.py        # Compress with cheap model
│   └── persistent.py          # Cross-session key facts
├── skills/
│   ├── loader.py              # Load .md skills from disk
│   ├── registry.py            # Match & inject skills into context
│   └── generator.py           # Auto-generate skills from experience
├── tools/
│   ├── base.py                # BaseTool abstract class
│   ├── registry.py            # Registry + concurrent executor
│   └── builtin/
│       ├── shell.py           # Execute shell commands
│       ├── web_search.py      # DuckDuckGo search (no API key needed)
│       ├── web.py             # Fetch & extract web page text
│       └── file.py            # File read/write/list
├── scheduler/
│   └── cron.py                # APScheduler with SQLite persistence
└── interface/
    ├── cli.py                 # Typer CLI entry point
    ├── repl.py                # Interactive REPL with prompt_toolkit
    ├── api.py                 # FastAPI HTTP + SSE streaming
    └── commands/              # Subcommands (model, provider, session, skill, schedule)
```

## Memory System

Ethan uses a three-tier memory architecture to maintain context without blowing up token costs:

| Layer | Content | Storage |
|-------|---------|---------|
| Hot   | Last N turns (full messages) | In-memory |
| Warm  | Rolling summary of older turns | In-memory |
| Cold  | Key facts extracted across sessions | `~/.ethan/memory/persistent.md` |

Compression is **batched** (not per-turn) and uses an automatically inferred cheap model (e.g., Haiku for Claude users, Flash Lite for Gemini users).

## Skills

Skills are Markdown files loaded from two sources, in priority order:

1. **内置 skills** — `ethan/skills/<name>/SKILL.md`（随项目发布）
2. **用户 skills** — `~/.ethan/skills/<name>/SKILL.md` 或 `~/.ethan/skills/<name>.md`

两种来源都支持目录格式（`<name>/SKILL.md` + `references/` 子目录）和旧版单文件 `.md` 格式。

```markdown
---
name: deploy-checklist
trigger: deploy|ship|release
description: Pre-deployment checklist
fast_path: true      # 是否在 fast path 模式下也生效
version: "1.0"
---

Steps before deploying:
1. Run tests
2. Check for uncommitted changes
3. ...
```

当用户输入匹配到 skill 的 `trigger` 关键词时，skill 内容自动注入 system prompt。内置 skill 包括 `channels`、`lark-im`、`home-assistant`。

## Tools

Tools are pluggable — add a new one without touching the agent loop:

```python
from ethan.tools.base import BaseTool

class MyTool(BaseTool):
    name = "my_tool"
    description = "Does something useful"
    parameters = {"type": "object", "properties": {...}, "required": [...]}

    async def run(self, **kwargs) -> str:
        return "result"
```

Register it in `cli.py` and the LLM will automatically use it when relevant.

## CLI Commands

```
ethan                              Start interactive REPL
ethan -p "..."                     Single-turn query
ethan -m MODEL                     Use specific model
ethan -r last                      Resume last session
ethan serve                        Start HTTP API server

ethan model list|add|remove|default
ethan provider list|set
ethan session list|show|delete
ethan skill list|show|create
ethan schedule list|remove|pause|resume
```

## HTTP API

```bash
# Health check
curl http://localhost:8900/health

# List models
curl http://localhost:8900/models

# Chat
curl -X POST http://localhost:8900/chat \
  -H "Content-Type: application/json" \
  -d '{"messages": [{"role": "user", "content": "hello"}]}'

# Chat with streaming (SSE)
curl -X POST http://localhost:8900/chat \
  -H "Content-Type: application/json" \
  -d '{"messages": [{"role": "user", "content": "hello"}], "stream": true}'
```

## Configuration

All config lives in `~/.ethan/config.yaml`:

```yaml
providers:
  anthropic:
    api_key: sk-ant-xxx
    base_url: https://api.anthropic.com   # optional
    proxy: null                           # per-provider proxy
  openai_compat:
    api_key: sk-xxx
    base_url: https://api.openai.com/v1

models:
  - id: claude-sonnet-4-6
    provider: anthropic
    description: Claude Sonnet 4.6
    alias: [sonnet]
  - id: gpt-4o
    provider: openai_compat
    alias: [gpt]

network:
  proxy: http://127.0.0.1:7890           # global proxy

defaults:
  model: claude-sonnet-4-6
  agent_name: Ethan
  max_tokens: 4096
  max_tool_iterations: 10
```

Environment variables in `.env` override config values (useful for secrets).

## Roadmap

- [x] Multi-model provider system (Anthropic + OpenAI compatible)
- [x] ReAct agent loop with streaming
- [x] Session persistence & resume
- [x] Three-tier memory with auto-compression
- [x] Skill system (dual-source, directory format, fast-path opt-in, auto-generate)
- [x] Built-in skills: channels, lark-im, home-assistant
- [x] Scheduler (cron + interval) + heartbeat job
- [x] Built-in tools (shell, search, file, web, rg/fd, schedule, knowledge)
- [x] HTTP API with SSE streaming + knowledge/channels/system-prompt-preview endpoints
- [x] Web UI (chat, memory, knowledge, schedule, skills, sessions, settings, channels)
- [x] Knowledge base with semantic vector search (sqlite-vec)
- [x] Prompt Caching (Anthropic stable-prefix cache_control)
- [x] Fast Path router with per-tool and per-skill opt-in
- [x] ACP protocol client
- [ ] MCP protocol client
- [ ] Procedural memory (learn from corrections)

## Documentation

Detailed design docs for each module are in [`docs/`](./docs/):

- [Architecture Overview](docs/architecture.md)
- [Agent Loop](docs/agent-loop.md)
- [Provider Layer](docs/providers.md)
- [Tool System](docs/tools.md)
- [Memory System](docs/memory.md)
- [Skill System](docs/skills.md)
- [Scheduler](docs/scheduler.md)
- [Interface Layer](docs/interface.md)

## License

MIT
