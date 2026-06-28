# Ethan Agent

[中文文档](./README_CN.md)

A lightweight, extensible personal AI agent built in Python. Designed to run persistently on your own hardware with memory that grows over time, scheduled tasks, and a pluggable tool/skill system.

Ethan combines ideas from [OpenClaw](https://github.com/openclaw/openclaw) (structured agent loop, layered memory), [Hermes Agent](https://github.com/NousResearch/hermes-agent) (self-improving skills, memory consolidation), and [nanobot](https://github.com/HKUDS/nanobot) (minimal core, readable codebase).

---

## Features

**Memory system (five layers)**
- Hot/warm/cold three-tier sliding window for long-conversation context; older content auto-compressed by a cheap model
- Structured Facts: confidence-scored entries with conflict detection and deduplication (`~/.ethan/memory/facts.json`)
- Behavioral Procedures: learned from user corrections, loaded every conversation (`procedures.json`)
- Session Episodes: auto-summarized on exit, supports keyword search (`episodes.json`)
- User Profile: narrative document storing personal phrases, goals, and agent agreements (`user_profile.md`); sections include 基础特征 (basic traits) and 心理与情绪 (emotional/psychological traits)
- **Proactive memory write**: Agent calls tools mid-conversation to instantly persist anything worth remembering — no waiting for batch processing

**Companion mode — 苏念 (Surrender Experiment counselor)**
- A loadable plugin: toggle "苏念 · 陪伴倾听" in the chat UI to switch from the work assistant into a young, gentle female listener grounded in *The Surrender Experiment* (道法自然)
- In this mode the agent affirms first, listens deeply, and accompanies rather than rushing to solve — speaking like a real person, no AI stiffness
- While in companion mode, the consolidator auto-extracts 心理与情绪 (mood / stressors / what soothes you / inner feelings) into your profile; basic traits are set by you in the "我的画像" (My Profile) settings tab

**Legal expert mode — legal-assistant (install on demand)**
- Switch to "法律专家" (legal expert) mode and a single `legal-assistant` skill covers case analysis, litigation review, contract review, legal document/proposal generation, trademark & patent IP, case intake, legal search and visualization — routed by "task verb + practice area" to the matching playbook, instead of dozens of sub-skills
- **Zero pollution**: legal skills are tagged `modes: [法律]` and only activate in legal mode; in normal work mode they never enter the context
- **Auto-install (on demand)**: the first time you enter legal mode without the skill installed, the agent **automatically pulls and installs** `legal-assistant` from the repo (it announces "installing…" first — no silent network access; on failure it tells you to run `ethan skill add legal` manually). Legal content is not bundled with the main repo, honoring the upstream CC-BY-NC non-commercial license
- **Manual install**: run `ethan skill add legal` from the CLI (= `llm011/ethan-legal-skill/skills/legal-assistant`)
- **`/mode` switching**: both the CLI (REPL) and channels (Lark, etc.) support `/mode 法律` to enter and `/mode default` to return; an unrecognized name leaves the current mode unchanged. The mode is persisted per session and restored when you resume

**Skill system**
- Keyword trigger matching, auto-injected into system prompt
- `fast_path: true` routes matched input to the millisecond fast track
- `channels: [lark, web]` filters skills by channel so each surface gets only relevant skills
- `modes: [法律]` filters skills by conversation mode so each mode gets only relevant skills (empty = all modes)
- Hit tracking and correction collection; Heartbeat auto-updates skill content with a cheap model when corrections accumulate
- Agent can create new skills mid-conversation via the `skill_create` tool

**Three-track routing**
- **fast**: short commands + keyword match → minimal prompt + fast_path tools only + 2 iterations
- **medium**: mid-length messages → full prompt + all tools + 4 iterations
- **full**: complex tasks → full prompt + all tools + 10 iterations

**Scheduler**
- Create cron or interval jobs in conversation; SQLite-persisted, survives restarts
- `heartbeat.md`: write natural-language tasks; the system runs them periodically

**Tool system**
- Shell execution, web search (DuckDuckGo by default, or Tavily via config), web fetch, file I/O, knowledge base
- Tool results over 4 000 chars are auto-summarized by a cheap model before going back to the main model
- Identical calls within the same turn hit an in-memory cache — no duplicate execution

**Prompt Caching**
- System prompt split into stable layer / dynamic layer; stable layer cached 5 min, token cost drops to 0.1×

**Multi-channel**
- CLI REPL, Web UI (Next.js), Lark/Feishu (WebSocket, no public IP required)

---

## Install

Requires Python 3.12+.

```bash
pip3 install ethan-agent
```

Set an API key and start:

```bash
# Anthropic Claude
ethan provider set anthropic --api-key sk-ant-xxx

# OR any OpenAI-compatible API (Gemini, OpenRouter, DeepSeek, Ollama, etc.)
ethan provider set openai_compat --api-key sk-xxx --base-url https://api.example.com/v1
ethan model default <model-id>

# OR Zhipu GLM (built-in preset — fills base_url/type/anti-cache + registers glm-5.2 etc.)
ethan provider set glm --api-key <your-glm-key>
ethan model default glm-5.2
# (see `ethan provider presets` for all built-in presets)

ethan
```

> 💡 **Notice**: Run `ethan` command to start the interactive chat REPL in your terminal. When `ethan serve` is running, it also hosts the Web UI on port `8900`. Running `ethan` will automatically open it in your browser. You can also run `ethan web` to open the Web UI directly.

That's it. On first run, default skills and system files are written to `~/.ethan/`.

---

## Quick Start (Docker, recommended for server deployment)

Docker runs backend and Web UI as separate containers, data persisted to a local volume. No need to clone the repository.

### Prerequisites

- Docker 20.10+
- Docker Compose v2

### 1. Download compose file

```bash
mkdir ethan-agent && cd ethan-agent
curl -O https://raw.githubusercontent.com/llm011/ethan-agent/main/docker-compose.yml
```

### 2. Configure

Create a `.env` file and add your API keys:

```bash
cat > .env << 'EOF'
ANTHROPIC_API_KEY=sk-ant-xxx
# OPENAI_API_KEY=sk-xxx
# OPENAI_BASE_URL=https://api.example.com/v1
AGENT_DEFAULT_MODEL=claude-sonnet-4-6
EOF
```

### 3. Start

```bash
docker compose up -d
```

### 4. Access

- **Web UI**: http://localhost:3000
- **API**: http://localhost:8900
- **Health check**: http://localhost:8900/health

### 5. Common commands

```bash
docker compose logs -f ethan-backend  # tail logs
docker compose restart ethan-backend  # restart backend
docker compose pull && docker compose up -d  # update to latest version
docker compose down                   # stop
```

> **One-shot legal expert mode**: set `ETHAN_INSTALL_SKILLS=legal` before `docker compose up` (or run `docker compose exec ethan-agent ethan skill add legal` after the container is up) to install the `legal-assistant` skill; then pick "⚖️ 法律专家" in the Web mode dropdown to activate it.

### 6. Multi-user (optional)

Ethan supports multiple isolated users sharing one instance. Each user has their own memory (facts / procedures / episodes / sessions), skills, and knowledge base — fully isolated per user. System prompts and provider config stay shared.

Define users in `config.yaml` (each user binds a `web_token` for browser login and `api_keys` for the `/v1/chat/completions` API — both resolve to the same `user_id`):

```yaml
users:
  - id: admin              # stable identifier, also the data dir name (use ASCII)
    name: Admin
    web_token: admin_pass  # browser login
    api_keys: [sk-ethan-admin-key]  # programmatic API access
    is_admin: true
  - id: alice
    name: Alice
    web_token: alice_pass
    api_keys: [sk-ethan-alice-key]
    is_admin: false
```

If `users` is empty (or absent), Ethan auto-creates an `admin` user whose `web_token` reuses `network.auth_token` — so existing single-user deployments keep working with zero config change. On first launch, existing global data is migrated to the admin user's directory (originals kept as backup; idempotent).

---

## Local Development / Install from Source

### Prerequisites

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) package manager
- Node.js 20+ (Web UI only)

### Install

```bash
# From PyPI
pip install ethan-agent

# Or from source
git clone https://github.com/llm011/ethan-agent.git
cd ethan-agent
uv sync
```

### Configure

```bash
ethan provider set anthropic --api-key sk-ant-xxx
# or
ethan provider set openai_compat --api-key sk-xxx --base-url https://api.example.com/v1
```

### Run

```bash
# Interactive REPL
ethan

# Launch Web UI and open in browser
ethan web
# (Supports custom port via `--port 8900` or direct URL via `--url`)

# Manage Web UI login token
ethan web token
ethan web token --rotate

# Single-turn query
ethan -p "What's the weather in Tokyo?"

# Specify model
ethan -m claude-sonnet-4-6

# Resume last session
ethan -r last

# Start HTTP API server (needed for Web UI)
ethan serve
```

### Web UI (dev mode)

```bash
cd web
npm install
npm run dev   # http://localhost:3000 (dev mode, API still on port 8900)
```

### macOS auto-start (launchd)

```bash
./deploy/install.sh
```

---

## Architecture

```
ethan/
├── core/
│   ├── agent.py               # ReAct loop, three-track router (fast/medium/full)
│   ├── config.py              # YAML config (~/.ethan/config.yaml)
│   └── heartbeat.py           # Heartbeat system, periodic maintenance
├── providers/
│   ├── base.py                # Unified interface (Message, ToolCall, BaseProvider)
│   ├── anthropic.py           # Claude native protocol + Prompt Caching
│   ├── openai_compat.py       # OpenAI-compatible protocol
│   └── manager.py             # Route model ID → provider
├── memory/
│   ├── session.py             # Session persistence (SQLite)
│   ├── working.py             # Three-tier sliding window memory
│   ├── facts.py               # Structured Facts (conflict detection + confidence)
│   ├── procedures.py          # Behavioral rules (learned from corrections)
│   ├── episodic.py            # Session episode archive
│   └── consolidator.py        # Compress with cheap model
├── skills/
│   ├── loader.py              # Load skills (directory format + legacy .md)
│   ├── registry.py            # Match (with channel filter) + hit stats
│   ├── stats.py               # Hit count + correction collection
│   ├── updater.py             # Auto-update skill content via cheap model
│   └── generator.py           # Auto-generate skills from sessions
├── tools/
│   ├── base.py                # BaseTool abstract class
│   ├── registry.py            # Registry + concurrent executor + turn cache
│   ├── result_compressor.py   # Auto-summarize long tool output
│   └── builtin/
│       ├── shell.py           # Execute shell commands
│       ├── web_search.py      # DuckDuckGo search
│       ├── web.py             # Fetch & extract web page text
│       ├── file.py            # File read/write/list
│       ├── memory_write.py    # Proactive fact write
│       ├── procedure_write.py # Proactive procedure write
│       ├── profile_update.py  # Update user profile
│       └── skill_create.py    # Create skill mid-conversation
├── scheduler/
│   └── cron.py                # APScheduler with SQLite persistence
└── interface/
    ├── cli.py                 # Typer CLI entry point
    ├── repl.py                # Interactive REPL with prompt_toolkit
    ├── api.py                 # FastAPI HTTP + SSE streaming
    ├── lark_events.py         # Lark WebSocket
    └── commands/              # Subcommands (model, provider, session, skill, schedule)
```

---

## Memory System

Ethan uses a five-layer memory architecture:

| Layer | Content | Storage |
|-------|---------|---------|
| Hot | Last N turns (full messages) | In-memory |
| Warm | Rolling summary of older turns | In-memory |
| Cold (Facts) | Key facts extracted across sessions | `~/.ethan/memory/facts.json` |
| Procedures | Behavioral rules learned from corrections | `~/.ethan/memory/procedures.json` |
| User Profile | Narrative personal context (goals, phrases, agreements) | `~/.ethan/memory/user_profile.md` |

Compression is **batched** (not per-turn) and uses an automatically inferred cheap model (e.g. Haiku for Claude users, Flash Lite for Gemini users).

Agent proactively writes to all layers mid-conversation via `memory_write`, `procedure_write`, and `profile_update` tools — no waiting for the next compression cycle.

---

## Skills

Skills are Markdown files loaded from `~/.ethan/skills/`. On first run, default skills (channels, deepwiki, lark-im, lark-shared, skills-manager) are automatically copied there from the package.

Both directory format (`<name>/SKILL.md` + `references/`) and legacy single-file `.md` format are supported.

```markdown
---
name: deploy-checklist
trigger: deploy|ship|release
description: Pre-deployment checklist
fast_path: true       # route to fast track when triggered
channels:             # empty = all channels; list = restrict
  - web
version: "1.0"
---

Steps before deploying:
1. Run tests
2. Check for uncommitted changes
3. ...
```

When a user message matches a skill's `trigger`, the skill content is injected into the system prompt. Built-in skills include `channels`, `lark-im`, and `home-assistant`.

Skills accumulate hit stats and user corrections. When corrections reach a threshold (default: 2), the Heartbeat job merges them into the skill file using a cheap model.

---

## Tools

Tools are pluggable — add a new one without touching the agent loop:

```python
from ethan.tools.base import BaseTool

class MyTool(BaseTool):
    name = "my_tool"
    description = "Does something useful"
    fast_path = False   # set True to make available in fast-track mode
    cacheable = False   # set True to cache identical calls within a turn
    parameters = {"type": "object", "properties": {...}, "required": [...]}

    async def run(self, **kwargs) -> str:
        return "result"
```

Register it in `cli.py` and the LLM will automatically use it when relevant.

---

## CLI Commands

```
ethan                              Start interactive REPL
ethan -p "..."                     Single-turn query
ethan -m MODEL                     Use specific model
ethan -r last                      Resume last session
ethan serve                        Start HTTP API server (foreground)
ethan serve stop                   Stop background serve process
ethan serve restart                Restart background serve process

ethan model list|add|remove|default
ethan provider list|set
ethan session list|show|delete
ethan skill list|show|add|create
ethan schedule list|remove|pause|resume
```

---

## HTTP API

```bash
GET  /health                    # Health check
GET  /models                    # Available models
POST /chat                      # Chat (stream: true for SSE)
GET  /sessions                  # Session list
GET  /sessions/{id}             # Session detail + messages
GET  /memory/facts              # Facts list
GET  /memory/episodes           # Episode summaries
GET  /skills                    # Skill list
POST /skills                    # Create skill
POST /skills/evolve             # Trigger skill auto-update
GET  /schedule                  # Scheduled jobs
GET  /system-prompt-preview     # Current system prompt preview
GET  /channels                  # Channel list
GET  /knowledge/search          # Semantic search
```

---

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
  routing:
    fast_max_length: 12
    medium_max_length: 80
    medium_max_iters: 15
    fast_keywords:
      - "turn off*light"
      - "play music"
    fast_skill_triggers:
      - "home assistant"
```

Environment variables in `.env` override config values (useful for secrets).

### Config directory layout

```
~/.ethan/
├── config.yaml          # Main config (providers, models, routing)
├── system/
│   ├── identity.md      # Agent identity (name, role)
│   ├── soul.md          # Behavioral principles
│   └── heartbeat.md     # Heartbeat tasks (natural language)
├── memory/
│   ├── facts.json       # Structured facts
│   ├── procedures.json  # Behavioral rules
│   ├── episodes.json    # Session episode archive
│   └── user_profile.md  # User profile (narrative)
├── skills/              # User-defined skills
│   └── <name>/
│       └── SKILL.md
└── sessions.db          # Session history (SQLite)
```

---

## Roadmap

### ✅ Completed

**Core Agent**
- [x] Multi-model provider (Anthropic + OpenAI-compatible: Gemini, GPT, Ollama, etc.)
- [x] ReAct agent loop with streaming output
- [x] Three-track router: fast / medium / full, tool result compression, per-turn dedup cache
- [x] Prompt Caching (Anthropic stable-prefix cache_control, ~0.1× input cost)

**Five-Layer Memory**
- [x] Hot/warm/cold sliding window + cheap-model batch compression
- [x] Structured Facts (confidence scoring + conflict detection)
- [x] Behavioral Procedures (learned from user corrections)
- [x] Session Episode archive (auto-summary, keyword search)
- [x] User Profile — narrative document with five named sections
- [x] Proactive memory write: `memory_write`, `procedure_write`, `profile_update`, `skill_create`
- [x] Memory context isolation (anti-pollution XML tags)

**Skill System**
- [x] Dual-source loading (built-in + user-defined) + channel filter (`channels` field)
- [x] `fast_path` opt-in, hit stats, correction collection, auto-update (Updater)
- [x] Session-end background Skill generation (Hermes-style)
- [x] Built-in skills: home-assistant, lark-im, channels, deepwiki

**Tools**
- [x] shell, web_search, web_fetch, file_read/write/list, rg, fd
- [x] Knowledge base (sqlite-vec semantic search), scheduler tools, ACP → Claude Code

**Scheduler**
- [x] Cron + interval, SQLite persistence, auto-restore on restart
- [x] `heartbeat.md`: natural-language periodic tasks executed automatically

**Channels & API**
- [x] Web UI (Next.js): chat timeline, memory, skills, schedule, knowledge, settings
- [x] Tool call timeline (collapsible, with icons + duration)
- [x] Feishu/Lark WebSocket (no public IP required)
- [x] OpenAI-compatible Completions API (`/v1/chat/completions`) + API key management
- [x] Docker deployment + macOS launchd auto-start

---

### 🚀 Planned

**UX Improvements**
- [x] **Message quoting**: hover a chat bubble → quote button → quote preview bar in input box; quote block injected to model, original message stays clean
- [ ] **User profile settings**: avatar upload, display name shown in chat bubbles
- [x] **Scheduler suggestions**: Agent detects ambiguous periodic needs in conversation and proactively lists 1-2-3 candidate schedules (clear intent → creates directly)
- [ ] **Scheduler templates**: ready-to-use tasks (daily briefing, HA device check, knowledge digest)

**Channel Expansion**
- [ ] **WeCom (Enterprise WeChat)**: alongside Feishu as a second messaging channel
- [ ] **Mobile UI**: bottom tab nav, touch gestures, keyboard inset handling

**Coding Agent Integration**
- [x] **ACP multi-turn optimization**: `delegate_coding` resumes Claude Code sessions per (user × working_dir) via `--resume`; stream-json parsed into collapsible sub-steps in the Web UI tool timeline with highlighted final result. OpenCode / Codex also wired in (single-turn)
- [ ] **MCP client**: connect external MCP servers, auto-register tools

**Long-term**
- [ ] **Space isolation**: separate memory/skills per context (life / work / project)
- [ ] **Async interrupt**: detect new messages during long tasks, respond between tool calls
- [ ] **Obsidian integration**: read/write Obsidian vault as knowledge base

---

## Documentation

Detailed design docs for each module are in [`docs/`](./docs/):

- [Architecture Overview](docs/architecture.md)
- [Agent Loop](docs/agent-loop.md)
- [Routing](docs/routing.md)
- [Provider Layer](docs/providers.md)
- [Tool System](docs/tools.md)
- [Secrets Management](docs/secrets.md)
- [Memory System](docs/memory.md)
- [Skill System](docs/skills.md)
- [Scheduler](docs/scheduler.md)
- [Interface Layer](docs/interface.md)

## License

MIT
