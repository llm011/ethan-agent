# Ethan Agent

[中文文档](./README_CN.md)

A lightweight, extensible personal AI agent built in Python. Designed to run persistently on your own hardware with memory that grows over time, scheduled tasks, and a pluggable tool/skill system.

Ethan combines ideas from [OpenClaw](https://github.com/openclaw/openclaw) (structured agent loop, layered memory), [Hermes Agent](https://github.com/NousResearch/hermes-agent) (self-improving skills, memory consolidation), and [nanobot](https://github.com/HKUDS/nanobot) (minimal core, readable codebase).

---

## Features

**Memory system**
- **Structured long-term memory** (`memory.db`, the single source of truth for user facts): every 5 turns, source-backed candidates are extracted (each must carry an exact quote from a user message) and deterministically admitted — explicit → active immediately, observed → promoted only after ≥2 independent sessions. 64 typed dimensions across 7 categories (personal info / preference / activity / decision / relationship / methodology / companion), with TTL expiry, supersede chains, and redaction-on-forget
- **Semantic recall & dedup**: hybrid FTS5 + BGE vector retrieval (RRF-fused) feeds a single `<memory_context>` prompt block; at admission, embedding near-neighbors are paired and merged/superseded by deterministic rules ("住在深圳" ≈ "家在深圳南山" never stored twice)
- **Dimension registry**: the extraction prompt's dimension guide and the validation whitelist are both generated from one declarative registry — extending memory types never touches prompt text by hand
- Hot/warm sliding window for long-conversation context (REPL); older content auto-compressed by a cheap model
- Behavioral Procedures: learned from user corrections, loaded every conversation (`playbook.json`)
- User Profile: narrative document storing personal phrases, goals, and agent agreements (`user_profile.md`); sections include 基础特征 (basic traits) and 心理与情绪 (emotional/psychological traits)
- **Proactive memory write**: Agent calls `memory_write` mid-conversation — the write flows through the same candidate→admission pipeline (no separate store, same evidence semantics)

**Dream — nightly memory consolidation ("做梦")**
- Every night at 0:00, one unified pass (`run_nightly_consolidation`): re-extract the day's sessions, re-evaluate pending observations across sessions, expire TTL memories, write per-domain daily summaries, rebuild the memory vector index — then "dream": distill cross-session signals (recurring needs ≥3×, errors, success paths) into permanent insights, deduped via sqlite-vec against the freshly-admitted memories
- Companion (苏念) emotional memory is isolated to companion mode (separate domain, never recalled elsewhere); diagnostic/clinical labels are hard-rejected by a denied-term list
- **Reflect-back**: insights flow back as structured candidates (repetition/error → admission pipeline) and `playbook.json` (success_path) — no separate read path needed
- **fact_sync mirror**: before each dream, active memories/playbook entries are mirrored into the vector store (type=`fact_sync`) so insight dedup naturally covers already-known facts; the mirror is fully rebuilt each cycle
- **Permanent by design**: insights are never auto-deleted; `last_accessed` is tracked for observability but not used as an eviction basis (memory.db stays tiny, ~15KB per insight)
- **Sessions.db rotation**: full message history grows fast, so sessions.db is auto-archived via `VACUUM INTO` to `~/.ethan/archive/sessions.{start}~{end}.db` (filename carries the date span) once it exceeds 10 MB, keeping the active db small while old chats remain queryable by date

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
- Optional semantic router (BGE INT8 + LR head) adds recall on top of keywords so differently-phrased requests still match (`pip install 'ethan-agent[embedding]'`; keyword-only without it — see Install section)
- `fast_path: true` routes matched input to the millisecond fast track
- `channels: [lark, web]` filters skills by channel so each surface gets only relevant skills
- `modes: [法律]` filters skills by conversation mode so each mode gets only relevant skills (empty = all modes)
- Hit tracking and correction collection; Heartbeat auto-updates skill content with a cheap model when corrections accumulate
- Agent can create new skills mid-conversation via the `skill_create` tool

**Three-track routing**
- **fast**: short commands + keyword match → minimal prompt + fast_path tools only + 2 iterations
- **medium**: mid-length messages → full prompt + all tools + 4 iterations
- **full**: complex tasks → full prompt + all tools + 10 iterations

**Loop control**
- Stuck detection: when the agent repeats the same tool+args for 3 rounds (or 2 rounds of the same error), it injects a forced-reflection prompt (`<diagnosis>` + must switch strategy) instead of spinning to the iteration cap
- Graceful finalize: on stuck-give-up (after 2 reflections) or hitting the iteration cap, the last round disables tools and the model writes a "done / blocker / what's needed from you" summary — never a raw `[max tool iterations reached]`

**Scheduler & background tasks**
- Create cron or interval jobs in conversation; SQLite-persisted, survives restarts
- `heartbeat.md`: write natural-language tasks; the system runs them periodically
- Background tasks: kick off a long-running task that runs async in its own session without blocking the current chat; result is fed back when done (Lark pushes to the originating chat, web surfaces the session). View/stop them on the `/background-tasks` page, with a running-count badge in the sidebar

**Tool system**
- Shell execution, web search (DuckDuckGo by default, or Tavily / self-hosted SearXNG via config — see `deploy/docker-compose.searxng.yml`), web fetch, file I/O, knowledge base
- Sensitive/side-effecting ops (shell, file write, secret read) ask for consent before running; the web shows a consent card, the REPL prompts y/N, and once granted in a session the same tool won't ask again
- Tool results over 4 000 chars are auto-summarized by a cheap model before going back to the main model
- Identical calls within the same turn hit an in-memory cache — no duplicate execution

**Prompt Caching**
- System prompt split into stable layer / dynamic layer; stable layer cached 5 min, token cost drops to 0.1×

**Multi-channel**
- CLI REPL, Web UI (Next.js), **Android App** (Kotlin/Compose), Lark/Feishu (WebSocket, no public IP required)
- Lark auto-auth guidance: when a user-token-dependent call (e.g. reading group chat context via `--as user`) fails with an auth-class error (99991663 / 99991661 / `need_user_authorization`), the bot sends a red guidance card to that chat telling the user to run `lark-cli auth login --domain im`. Throttled to once per 5 min per chat; non-auth errors (network / param / not-found) do not trigger it.
- Lark multi-event subscription + card action callbacks: each EventKey (message received / read receipts / reactions / `card.action.trigger`) runs in its own `lark-cli event consume` subprocess with independent reconnect; interactive card button clicks route back through `_handle_card_action` for button-driven workflows.

**Browser control (real Chrome)**
- Drive the real Chrome on the machine where ethan runs, from any channel (Web / Lark / CLI) — install the bundled `browser-extension`, point it at your ethan WebSocket endpoint, and the agent gets `browser_session` / `browser_tab` / `browser_page` tools
- agent-browser style: accessibility-tree snapshot + ref map, click/fill/type/press/select/scroll/hover, screenshot, keyboard/mouse, page `eval`, all over Chrome DevTools Protocol
- Session is bound to the conversation (isolated per chat); page ops within a session are serialized, different sessions run in parallel; idle sessions are released (tabs kept) after 30 min
- Session-level one-time consent: the first browser call in a chat asks once, then all browser ops (incl. `eval`) are allowed for that chat
- Transport is WebSocket only (extension → ethan), no native messaging host; see [docs/browser-control-plan.md](docs/browser-control-plan.md)

**Desktop control (macOS, via cua-driver)**
- Control the local macOS desktop from any channel — take screenshots, click, type, drag, scroll, launch apps, open URLs
- Powered by [trycua/cua](https://github.com/trycua/cua); connects to `cua-driver` (a native background daemon at `localhost:8000`) — no VM required
- Screenshot results are passed directly to vision models; the agent sees the screen and decides the next action
- `ethan server install` automatically installs and registers `cua-driver` as a launchd service; or install manually: `curl -fsSL .../install.sh | bash && cua-driver install`
- Optional Python SDK: `pip install 'ethan-agent[computer]'` (cua-computer); gracefully absent when not installed

---

## Install

Requires Python 3.12+.

```bash
pip3 install ethan-agent
```

Set an API key and start:

```bash
# Any OpenAI-compatible API (OpenAI / Gemini / OpenRouter / DeepSeek / Ollama / etc.)
ethan provider set openai_compat --api-key sk-xxx --base-url https://api.openai.com/v1
ethan model default gpt-5.4   # or gemini-2.5-flash, etc.

# OR Anthropic Claude
ethan provider set anthropic --api-key sk-ant-xxx

# OR Zhipu GLM (built-in preset — fills base_url/type/anti-cache + registers glm-5.2 etc.)
ethan provider set glm --api-key <your-glm-key>
ethan model default glm-5.2
# (see `ethan provider presets` for all built-in presets)

ethan
```

> 💡 **First-run wizard**: if you just run `ethan` without configuring a provider first, an interactive prompt will guide you through choosing a provider (default: OpenAI-compatible), entering Base URL, then API Key, and finally a default model ID.

> ⚠️ **Already running?** If `ethan serve`, the desktop app, or `ethan web` is already up, **restart it** after any `ethan provider set` / `ethan model default` change. The running server caches config in memory and won't pick up edits to `~/.ethan/config.yaml` until it restarts.

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

Ethan supports multiple isolated users sharing one instance. Each user has their own memory (structured memories / procedures / sessions), skills, and knowledge base — fully isolated per user. System prompts and provider config stay shared.

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

### Optional: Semantic Router (smarter skill matching — beginners can skip)

By default, Ethan uses keyword matching to decide which skill to activate. This is enough for most cases and **works without any extra setup**.

If you want skills to match even when phrased differently (e.g. triggering the Feishu skill by saying "pass a message to the client" instead of literally "send Feishu"), enable the optional semantic router:

```bash
# 1. Install the optional dependency (a lightweight inference runtime, a few tens of MB)
pip install 'ethan-agent[embedding]'      # from PyPI
# from source: uv sync --extra embedding

# 2. Pull the model (~24MB, first time only; skippable — the first message auto-downloads it)
ethan router pull

# 3. Check status
ethan router status                    # "✓ router ready" means you're set
```

- **Fully optional**: with no dependency, no model, or offline, it silently falls back to keyword matching — nothing breaks.
- The model is hosted on GitHub, downloaded and cached locally on first use, then works offline.
- To disable: just uninstall the optional dependency, no config change needed.

### Configure

```bash
ethan provider set anthropic --api-key sk-ant-xxx
# or
ethan provider set openai_compat --api-key sk-xxx --base-url https://api.example.com/v1
```

> ⚠️ Restart any running `ethan serve` / desktop app / `ethan web` after changing provider or model config — the server caches config in memory and only reloads on restart.

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

### Android App

Native mobile client in `app/android/`. Requires Android SDK 35 and JDK 17+.

```bash
cd app/android
./gradlew assembleDebug
# APK: app/build/outputs/apk/debug/app-debug.apk
```

On first launch, configure the server URL (e.g. `http://<your-nas>:8900`) and Access Token (`network.auth_token` in `~/.ethan/config.yaml`). See [app/android/PRD.md](./app/android/PRD.md) for the full feature list.

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
│   ├── store.py               # Structured memory store (memories/evidence/candidates/jobs/FTS)
│   ├── extractors.py          # LLM candidate extraction (quote-backed)
│   ├── admission.py           # Deterministic admission + semantic pairing
│   ├── dimensions.py          # Dimension registry (whitelist + prompt generation)
│   ├── recall.py              # Hybrid recall (FTS + vector, RRF)
│   ├── memory_vectors.py      # BGE vector index for memories
│   ├── nightly_consolidation.py # Unified nightly pass (structured + dream)
│   ├── procedures.py          # Behavioral rules (learned from corrections)
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
│       ├── skill_create.py    # Create skill mid-conversation
│       └── lark_tools.py      # Lark CLI wrappers (calendar / chat messages / message send)
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

Ethan's long-term memory is a structured pipeline (extract → admit → recall → nightly consolidation) with several satellite stores:

| Component | Content | Storage |
|-------|---------|---------|
| Structured memories | Source-backed user facts, deterministically admitted | `~/.ethan/memory/memory.db` |
| Insights (dream) | Cross-session patterns (recurring needs, errors, success paths) | `~/.ethan/memory/memory.db` (vector store) |
| Procedures | Behavioral rules learned from corrections | `~/.ethan/memory/playbook.json` |
| User Profile | Narrative personal context (goals, phrases, agreements) | `~/.ethan/memory/user_profile.md` |
| Hot/Warm | Last N turns + rolling summary (in-session compression) | In-memory |

Extraction runs every 5 turns on the main chat model; in-session compression is **batched** (not per-turn) and uses an automatically inferred cheap model (e.g. Haiku for Claude users, Flash Lite for Gemini users).

Agent proactively writes to all layers mid-conversation via `memory_write`, `procedure_write`, and `profile_update` tools — no waiting for the next compression cycle.

---

## Skills

Skills are Markdown files loaded from `~/.ethan/skills/`. On first run, default skills (channels, deepwiki, lark-im, lark-shared, skills-manager, use-browser, agent-browser, dev-browser) are automatically copied there from the package.

Both directory format (`<name>/SKILL.md` + `references/`) and legacy single-file `.md` format are supported. When a directory-format skill is matched, its `references/*.md` filenames plus a one-line summary are listed in the injected context so the model knows which detail docs exist — use `skill_read(name=..., file="references/<name>.md")` to pull the full content on demand (pull-based, not bulk-injected).

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
    no_compress = False # set True if output carries IDs/refs/structured data the model must reuse verbatim
    parameters = {"type": "object", "properties": {...}, "required": [...]}

    async def run(self, **kwargs) -> str:
        return "result"
```

Register it in `cli.py` and the LLM will automatically use it when relevant.

> **`no_compress`**: tool output over 4000 chars is auto-summarized by a cheap model before reaching the main model. Leave it off when the output is prose to *read* (web pages, logs). Turn it on when the output contains data the model must pass back *verbatim* — IDs, refs, paths, structured JSON — otherwise the summary loses those tokens and the model can't act on the result.

Built-in tools also include `ui_card`, which renders structured info as cards instead of plain text. High-frequency types (comparison / ranking / stats / timeline) use fixed backend templates — the model just fills in typed data, so styling stays clean and consistent; free-form cards can still be hand-authored. Rendering is channel-aware over the same structured `card` data: the web renders [A2UI](https://a2ui.org/) via `@a2ui/react`, the REPL degrades to text, and Feishu/Lark renders native interactive cards (an incremental nicety on top of the base text/post + streaming-card output). Format details live in the on-demand `ui-card` skill, so the system prompt stays lean.

### Interactive Charts (MCP Apps / SEP-1865)

The `generate_chart` tool renders **interactive** Chart.js charts (bar / line / pie / doughnut / horizontalBar / radar) in the web UI, following the [MCP Apps](https://modelcontextprotocol.io/) UI-resource convention (SEP-1865):

- UI templates are registered as `ui://` resources (`ethan/tools/ui_resources.py`) and served over `GET /api/ui-resources` (list) and `GET /api/ui-resources/read?uri=…` (read HTML + `_meta` CSP).
- The tool result carries only `{uri, data}` — **no inline HTML**. The web frontend (the MCP host) fetches the template once per URI, caches it, renders it in a sandboxed iframe, and pushes the chart data in via `postMessage` (JSON-RPC `init`). Template and data stay separated, which is the core of the MCP Apps model.
- A [quickchart.io](https://quickchart.io/) PNG is still saved as a fallback, so non-web channels (e.g. Feishu/Lark) get a static image.

Charts persist on the assistant message (`mcp_apps` column), so they re-render after a page refresh.

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
GET  /memory/facts              # Memories list (legacy-compatible view)
GET  /memory/records            # Structured memories (filter: type/domain/status)
GET  /memory/records/{id}       # Memory detail + evidence chain
GET  /skills                    # Skill list
POST /skills                    # Create skill
POST /skills/evolve             # Trigger skill auto-update
GET  /schedule                  # Scheduled jobs
GET  /system-prompt-preview     # Current system prompt preview
GET  /channels                  # Channel list
GET  /knowledge/search          # Semantic search
GET  /ui-resources              # MCP Apps UI resources (SEP-1865): list
GET  /ui-resources/read?uri=    # MCP Apps UI resource: read HTML + _meta
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
│   ├── memory.db        # Structured memories + evidence + insights + vector index
│   ├── playbook.json  # Behavioral rules
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
- [x] User Profile — narrative document with five named sections
- [x] Proactive memory write: `memory_write`, `procedure_write`, `profile_update`, `skill_create`
- [x] Memory context isolation (anti-pollution XML tags)

**Skill System**
- [x] Dual-source loading (built-in + user-defined) + channel filter (`channels` field)
- [x] `fast_path` opt-in, hit stats, correction collection, auto-update (Updater)
- [x] Session-end background Skill generation (Hermes-style)
- [x] Optional semantic router (BGE INT8 + LR head, macro F1 0.851) for recall beyond keywords; silent keyword fallback. The same `[embedding]` optional dependency also powers semantic dedup in memory.db
- [x] Built-in skills: home-assistant, lark-im, channels, deepwiki

**Tools**
- [x] shell, web_search, web_fetch, file_read/write/list, rg, fd
- [x] Knowledge base (sqlite-vec semantic search), scheduler tools, ACP → Claude Code

**Scheduler**
- [x] Cron + interval, SQLite persistence, auto-restore on restart
- [x] `heartbeat.md`: natural-language periodic tasks executed automatically

**Channels & API**
- [x] Web UI (Next.js): chat timeline, memory, skills, schedule, knowledge, settings
- [x] Android App (Kotlin/Compose): mobile client with chat SSE, sessions, memory, settings
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
- [x] **ACP multi-turn optimization**: `delegate_coding` resumes coding-agent sessions per (agent × working_dir). All three backends (Claude Code / OpenCode / Codex) run as JSON event streams with session resume, parsed into collapsible sub-steps in the Web UI tool timeline with highlighted final result. Codex reuses Ethan's cliproxy provider; timeouts terminate gracefully and clear the session to avoid resuming a stuck thread
- [x] **Mirror sessions**: each `delegate()` becomes a real Ethan session (`source` = the actual tool: codex/claude/opencode) recording the dispatched query + coding-agent reply + steps, registered as a RunManager run so the delegated conversation can be watched live via SSE
- [x] **Immersive tool modes**: switch the conversation mode to Codex / Claude Code / OpenCode; once switched, every message in that session continues the same tool (same tool session, per-session working dir). Supports both ad-hoc delegation and immersive continuous conversation. Messaging a mirror session also auto-resumes the matching tool
- [ ] **MCP client**: connect external MCP servers, auto-register tools

**Long-term**
- [ ] **Space isolation**: separate memory/skills per context (life / work / project)
- [ ] **Async interrupt**: detect new messages during long tasks, respond between tool calls
- [ ] **Obsidian integration**: read/write Obsidian vault as knowledge base

---

## Documentation

Full documentation is available at **[llm011.github.io/ethan-agent](https://llm011.github.io/ethan-agent/)** — the same docs site you see in Ethan's built-in "Docs" tab.

Key docs:
- [Memory System](docs/memory.md) — five-layer architecture, dream consolidation, fact_sync
- [Agent Loop](docs/agent-loop.md) — dual-track routing, memory injection
- [Architecture Overview](docs/architecture.md) — system components, data flow
- [Heartbeat](docs/heartbeat.md) — background maintenance, midnight loop

All source markdown lives in [`docs/`](./docs/); changes to `main` auto-deploy via GitHub Actions.

---

## Contributors

<!-- ALL-CONTRIBUTORS-LIST:START -->
<a href="https://github.com/llm011/ethan-agent/graphs/contributors">
  <img src="https://contrib.rocks/image?repo=llm011/ethan-agent" />
</a>
<!-- ALL-CONTRIBUTORS-LIST:END -->

---

## License

MIT
