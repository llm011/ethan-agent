# Ethan Agent

[中文文档](./README_CN.md)

A lightweight, extensible personal AI agent built in Python. Designed to run persistently on your own hardware with memory that grows over time, scheduled tasks, and a pluggable tool/skill system.

Ethan combines ideas from [OpenClaw](https://github.com/openclaw/openclaw) (structured agent loop, layered memory), [Hermes Agent](https://github.com/NousResearch/hermes-agent) (self-improving skills, memory consolidation), and [nanobot](https://github.com/HKUDS/nanobot) (minimal core, readable codebase).

---

## Features at a Glance

| Category | What you get |
|----------|--------------|
| **Memory** | Structured long-term memory with quote-backed evidence, 64 typed dimensions, semantic dedup, nightly "dream" consolidation, procedures, user profile |
| **Routing** | Three-track (fast / medium / full) intent routing with stuck detection and graceful finalize |
| **Skills** | Pluggable Markdown skills with keyword + optional semantic router matching; 40+ built-in skills ship in the box |
| **Tools** | Shell, web search, web fetch, file I/O, knowledge base, charts, browser, desktop, ACP coding-agent delegation |
| **Channels** | CLI REPL, Web UI (Next.js), Desktop app (Tauri), Android app, Feishu/Lark (WebSocket, no public IP) |
| **Scheduler** | Cron + interval jobs, natural-language `heartbeat.md` tasks, async background tasks |
| **Modes** | Switchable conversation modes — companion (苏念), legal expert, immersive coding agents (Codex / Claude Code / OpenCode) |
| **Caching** | Prompt Caching (Anthropic stable-prefix, ~0.1× input cost) + per-turn tool-call dedup |
| **Multi-user** | Isolated memory / skills / knowledge per user, shared provider config |
| **UI** | A2UI structured cards, interactive Chart.js charts (MCP Apps / SEP-1865), tool timeline, search card carousel |

Detailed feature breakdowns are in [Features](#features) below.

---

## Deployment

Pick the option that fits your scenario. All four end up with the same `~/.ethan/` data directory and the same `ethan` CLI.

| Option | Best for | Requirements |
|--------|----------|--------------|
| [Desktop App](#option-1-desktop-app-macos--windows) | End users on macOS / Windows | None (one-click installer) |
| [pip install](#option-2-pip-install) | Local CLI / Python users | Python 3.12+ |
| [Docker](#option-3-docker-recommended-for-servers) | Server / NAS deployment | Docker 20.10+ & Compose v2 |
| [From source](#option-4-from-source-development) | Development / contributing | Python 3.12+, uv, Node 20+ |

### Option 1: Desktop App (macOS / Windows)

Download the installer from [GitHub Releases](https://github.com/llm011/ethan-agent/releases):

| Platform | File |
|----------|------|
| macOS Apple Silicon | `Ethan.Agent_<ver>_aarch64.dmg` |
| macOS Intel | `Ethan.Agent_<ver>_x64.dmg` |
| Windows | `Ethan.Agent_<ver>_x64-setup.exe` or `.msi` |

The desktop app bundles the full Web UI in a Tauri native window. On first launch it auto-initializes `~/.ethan/` and walks you through an onboarding flow (API key, model, agent name).

> **macOS Gatekeeper note**: the app is unsigned, so the first launch will say "damaged". Run this once, then open normally:
> ```bash
> xattr -dr com.apple.quarantine "/Applications/Ethan Agent.app"
> ```

### Option 2: pip install

Requires Python 3.12+.

```bash
pip3 install ethan-agent
```

That's it — the `ethan` command is now available. On first run, default skills and system files are written to `~/.ethan/`.

### Option 3: Docker (recommended for servers)

Backend and Web UI in one container, data persisted to the host's `~/.ethan/` (bind mount — inspectable, backup-friendly, and shared with any `pip`-installed `ethan` on the same machine). **No need to clone the repository.**

```bash
mkdir ethan-agent && cd ethan-agent
# Self-contained variant: pulls latest PyPI build inside container (no external files needed)
curl -o docker-compose.yml https://raw.githubusercontent.com/llm011/ethan-agent/main/deploy/docker-compose.pip.yml

# Create .env (see below for required keys)
cat > .env <<'EOF'
ANTHROPIC_API_KEY=sk-ant-xxx
AGENT_DEFAULT_MODEL=claude-sonnet-4-6
EOF

docker compose up -d
```

Want SearXNG (free, privacy-friendly self-hosted search) bundled in? Clone the repo and use the full compose instead:

```bash
git clone --depth=1 https://github.com/llm011/ethan-agent.git
cd ethan-agent/deploy
cp .env.example .env   # edit .env to fill in your API key
docker compose -f docker-compose.yml up -d   # bundles SearXNG + uses prebuilt GHCR image
```

`.env` keys (see [`deploy/.env.example`](./deploy/.env.example) for the full template):

```bash
ANTHROPIC_API_KEY=sk-ant-xxx        # or OPENAI_API_KEY + OPENAI_BASE_URL
AGENT_DEFAULT_MODEL=claude-sonnet-4-6
ETHAN_AUTH_TOKEN=                   # Web UI login token (empty = no auth, fine on LAN)
ETHAN_PROXY=                        # optional HTTP proxy
GH_TOKEN=                           # optional, lets the container use gh CLI
SEARXNG_BASE_URL=                   # optional, point web_search at a SearXNG instance
```

Access:

| Service | URL |
|---------|-----|
| Web UI & API | http://localhost:8900 |
| Health check | http://localhost:8900/health |
| SearXNG (if enabled) | http://localhost:8888 |

Common ops:

```bash
docker compose logs -f                    # tail logs (omit service name; picks the only one)
docker compose restart                    # restart backend
docker compose down                       # stop
```

> Updating the pip variant: `docker compose build --pull` and `docker compose up -d` re-runs the `pip install` and recreates the container. The GHCR-variant updates with `docker compose pull && docker compose up -d`.

**Other compose variants** in [`deploy/`](./deploy/):
- [`docker-compose.yml`](./deploy/docker-compose.yml) — full deployment with prebuilt GHCR image + bundled SearXNG (uses `deploy/searxng/settings.yml`, hence needs the cloned dir)
- [`docker-compose.searxng.yml`](./deploy/docker-compose.searxng.yml) — bring-your-own SearXNG add-on (use with `docker-compose.pip.yml`)
- [`docker-compose.nas.yml`](./deploy/docker-compose.nas.yml) — NAS-tuned variant

> **One-shot legal mode**: set `ETHAN_INSTALL_SKILLS=legal` before `docker compose up` (or run `docker compose exec ethan-agent ethan skill add legal` after start — replace `ethan-agent` with `ethan` if using the GHCR variant), then pick "⚖️ 法律专家" in the Web mode dropdown.

### Option 4: From source (development)

```bash
git clone https://github.com/llm011/ethan-agent.git
cd ethan-agent
uv sync                              # Python deps
cd web && npm install && cd ..       # Web UI deps (optional)
```

Optional — semantic router (smarter skill matching, beginners can skip):

```bash
uv sync --extra embedding            # or: pip install 'ethan-agent[embedding]'
ethan router pull                    # ~24MB model, first-time only
ethan router status                  # "✓ router ready"
```

Run:

```bash
ethan                                # interactive REPL (auto-opens Web UI if serve is up)
ethan serve                          # HTTP API + embedded Web UI on port 8900
ethan web                           # open Web UI in browser
cd web && npm run dev               # http://localhost:3000 (dev mode, API on 8900)
```

Optional extras:

- **Browser extension** — drive your real Chrome from any channel: load [`browser-extension/`](./browser-extension) in Chrome, point it at `ws://localhost:8900/ws/browser`
- **Desktop control** (macOS) — `ethan server install` registers `cua-driver` as a launchd service, or `pip install 'ethan-agent[computer]'` for the Python SDK
- **Android app** — `cd app/android && ./gradlew assembleDebug` (needs Android SDK 35 + JDK 17+); see [`app/android/PRD.md`](./app/android/PRD.md)
- **macOS auto-start** — `./deploy/install.sh` installs a launchd plist

---

## Configure Models

After any of the deployment options above, configure at least one model provider:

```bash
# Anthropic Claude (recommended — supports Prompt Caching)
ethan provider set anthropic --api-key sk-ant-xxx

# OR any OpenAI-compatible API (Gemini, OpenRouter, DeepSeek, Ollama, etc.)
ethan provider set openai_compat --api-key sk-xxx --base-url https://api.example.com/v1
ethan model default <model-id>

# OR Zhipu GLM (built-in preset — fills base_url/type/anti-cache + registers glm-5.2 etc.)
ethan provider set glm --api-key <your-glm-key>
ethan model default glm-5.2

# List all built-in presets
ethan provider presets
```

Docker users: skip the CLI and set `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` / `AGENT_DEFAULT_MODEL` in `.env` instead.

> ⚠️ **Already running?** Restart `ethan serve` / the desktop app / `ethan web` after any `ethan provider set` / `ethan model default` change. The running server caches config in memory and won't pick up edits to `~/.ethan/config.yaml` until it restarts.

Then start chatting:

```bash
ethan            # interactive REPL
ethan -p "..."   # single-turn query
ethan -m MODEL   # use specific model
ethan -r last    # resume last session
```

Web UI tokens:

```bash
ethan web token          # show current Web login token
ethan web token --rotate # regenerate token
```

---

## Feishu (Lark) Integration

Ethan connects to Feishu/Lark via **WebSocket long connection** — no public IP, no webhook URL needed. `ethan serve` spawns one `lark-cli event consume <EventKey>` subprocess per subscribed event.

### Setup

1. Create a Feishu app at [open.feishu.cn](https://open.feishu.cn), grab `app_id` and `app_secret`.
2. Enable the **Bot** capability and subscribe to events (at minimum `im.message.receive_v1`; optionally message read receipts, reactions, `card.action.trigger` for interactive card buttons).
3. Authorize user-token operations (e.g. reading group context with `--as user`): run `lark-cli auth login --domain im` once on the host. When the user token expires, the bot sends a red guidance card to the affected chat telling the user to re-run the command.
4. Add the credentials to `~/.ethan/config.yaml`:

```yaml
lark:
  app_id: "cli_xxxxxxxxxxxxxxxx"
  app_secret: "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
```

5. Restart `ethan serve`. Each EventKey gets its own subprocess with independent reconnect.

### What you get

- Markdown post bubbles + interactive cards (streaming `patch` updates)
- Multi-event subscription (messages / read receipts / reactions / card button callbacks)
- `THINKING_FACE` emoji ack on receipt, natural-language stop ("停" / "cancel" / "stop"), `/` slash commands (`/new`, `/stop`, `/help`, …)
- Auto auth-guidance card when a user-token call fails (99991663 / 99991661 / `need_user_authorization`)
- Per-chat session isolation; Lark sessions are visible in the Web UI with `lark:<chat_id>:` title prefix

Full event flow, card rendering details, and table-rendering quirks are in [docs/interface.md](docs/interface.md).

---

## Built-in Skills

All skills in [`ethan/defaults/skills/`](./ethan/defaults/skills/) are auto-copied to `~/.ethan/skills/` on first run and auto-updated on upgrade (only `SKILL.md` + `references/` — your own files are never touched). Install third-party skills with `ethan skill add <name>`.

### Browser & Desktop Control

| Skill | Description |
|-------|-------------|
| [use-browser](./ethan/defaults/skills/use-browser/SKILL.md) | Main browser skill — drive the real user Chrome via the Ethan Browser extension (reuses login cookies) |
| [agent-browser](./ethan/defaults/skills/agent-browser/SKILL.md) | Fallback: bundled isolated Chrome via Rust CLI, token-efficient AX snapshots |
| [dev-browser](./ethan/defaults/skills/dev-browser/SKILL.md) | Sandboxed JS + full Playwright API for complex multi-step flows |
| [computer-use](./ethan/defaults/skills/computer-use/SKILL.md) | macOS desktop control via `cua-driver` (screenshots / click / type / drag / open apps) |
| [macos-automation](./ethan/defaults/skills/macos-automation/SKILL.md) | Automate macOS apps (TickTick / Reminders / Calendar / Notes) via `osascript` |

### Feishu / Lark

| Skill | Description |
|-------|-------------|
| [lark-im](./ethan/defaults/skills/lark-im/SKILL.md) | Send / reply / search messages, manage chats & members, reactions, interactive cards |
| [lark-doc](./ethan/defaults/skills/lark-doc/SKILL.md) | Read & edit Feishu Docx / Wiki documents |
| [lark-task](./ethan/defaults/skills/lark-task/SKILL.md) | Create / assign / track Feishu tasks & lists |
| [lark-shared](./ethan/defaults/skills/lark-shared/SKILL.md) | lark-cli setup, auth login, identity switching, scope errors |
| [feishu-writer](./ethan/defaults/skills/feishu-writer/SKILL.md) | Long-form Feishu document generation with rich formatting & Mermaid |
| [channels](./ethan/defaults/skills/channels/SKILL.md) | Messaging channel config (Feishu WebSocket now; WeChat / Telegram later) |

### Notes & Knowledge

| Skill | Description |
|-------|-------------|
| [deepwiki](./ethan/defaults/skills/deepwiki/SKILL.md) | Query any GitHub repo's documentation via DeepWiki |
| [obsidian](./ethan/defaults/skills/obsidian/SKILL.md) | Read / search / create / edit Obsidian vault notes |
| [flomo](./ethan/defaults/skills/flomo/SKILL.md) | Read / search / write flomo (浮墨) short notes |
| [getnote](./ethan/defaults/skills/getnote/SKILL.md) | 得到大脑 (Get笔记) — save / search personal notes & knowledge base |
| [wechat-reading](./ethan/defaults/skills/wechat-reading/SKILL.md) | 微信读书 — search books, manage bookshelf, view highlights |
| [notebooklm](./ethan/defaults/skills/notebooklm/SKILL.md) | Query Google NotebookLM with source citations |
| [llm-wiki](./ethan/defaults/skills/llm-wiki/SKILL.md) | Karpathy's LLM Wiki — build & query interlinked markdown KB |

### Search & Information

| Skill | Description |
|-------|-------------|
| [arxiv](./ethan/defaults/skills/arxiv/SKILL.md) | Search arXiv papers by keyword / author / category / ID |
| [url-process](./ethan/defaults/skills/url-process/SKILL.md) | Universal link entry — auto-detect platform & route to fastest path |
| [blogwatcher](./ethan/defaults/skills/blogwatcher/SKILL.md) | Monitor blogs & RSS / Atom feeds |
| [rss-briefing](./ethan/defaults/skills/rss-briefing/SKILL.md) | Daily RSS briefing with Feishu-compatible layout |

### Coding & Research

| Skill | Description |
|-------|-------------|
| [code-review](./ethan/defaults/skills/code-review/SKILL.md) | Review diffs — P0 must-fix / P1 suggestion / P2 one-liner; posts inline comments |
| [vercel-deploy](./ethan/defaults/skills/vercel-deploy/SKILL.md) | Deploy static sites / web apps to Vercel |
| [research-paper-writing](./ethan/defaults/skills/research-paper-writing/SKILL.md) | Write ML papers for NeurIPS / ICML / ICLR — design to submit |
| [paper-analysis](./ethan/defaults/skills/paper-analysis/SKILL.md) | Map-Reduce deep read of academic papers (PDF / arXiv ID / local file) |

### Life & Productivity

| Skill | Description |
|-------|-------------|
| [amap-lbs](./ethan/defaults/skills/amap-lbs/SKILL.md) | Amap POI search, route planning, travel planning, heatmaps |
| [didi-ride](./ethan/defaults/skills/didi-ride/SKILL.md) | Call a Didi ride from Feishu chat |
| [jd-shopping](./ethan/defaults/skills/jd-shopping/SKILL.md) | JD orders export, product search, cart management |
| [travel-query](./ethan/defaults/skills/travel-query/SKILL.md) | 12306 train / high-speed rail timetable query |
| [finance-query](./ethan/defaults/skills/finance-query/SKILL.md) | A-share / HK / US stock quotes, K-line, PE/PB, financial statements |
| [xiaohongshu](./ethan/defaults/skills/xiaohongshu/SKILL.md) | Xiaohongshu automation — search / publish / interact |
| [gws-gmail](./ethan/defaults/skills/gws-gmail/SKILL.md) | Gmail via gws CLI — send / read / reply / forward / triage |

### Image & UI

| Skill | Description |
|-------|-------------|
| [ui-card](./ethan/defaults/skills/ui-card/SKILL.md) | Render structured UI cards (comparison / ranking / stats / timeline) |
| [image-split](./ethan/defaults/skills/image-split/SKILL.md) | Split long screenshots into grid pieces (smart gap-aware cutting) |
| [excalidraw](./ethan/defaults/skills/excalidraw/SKILL.md) | Generate editable Excalidraw diagrams (Obsidian-first) |
| [upload-cdn](./ethan/defaults/skills/upload-cdn/SKILL.md) | Upload local files to S3-compatible storage, get public URL |

### Companion & Mode

| Skill | Description |
|-------|-------------|
| [companion-listen](./ethan/defaults/skills/companion-listen/SKILL.md) | 苏念 — young gentle female companion grounded in *The Surrender Experiment* |
| [task-strategy](./ethan/defaults/skills/task-strategy/SKILL.md) | Generic fallback strategy when tools fail / are denied / timeout |

### Skill Self-Management

| Skill | Description |
|-------|-------------|
| [skill-creator](./ethan/defaults/skills/skill-creator/SKILL.md) | Draft SKILL.md, design triggers, organize references / scripts |
| [skills-manager](./ethan/defaults/skills/skills-manager/SKILL.md) | Search / install / update / uninstall skills via `npx skills` |

### Optional / External

| Skill | Description |
|-------|-------------|
| [legal-assistant](https://github.com/llm011/ethan-legal-skill) | Legal expert mode — case analysis, litigation review, contract review, IP, legal search (`ethan skill add legal`) |
| [eigenflux](./ethan/defaults/skills/eigenflux/SKILL.md) | AI signal broadcast network for cross-agent collaboration (privacy-first) |

---

## Features

### Memory system

- **Structured long-term memory** (`memory.db`, the single source of truth for user facts): every 5 turns, source-backed candidates are extracted (each must carry an exact quote from a user message) and deterministically admitted — explicit → active immediately, observed → promoted only after ≥2 independent sessions. 64 typed dimensions across 7 categories (personal info / preference / activity / decision / relationship / methodology / companion), with TTL expiry, supersede chains, and redaction-on-forget.
- **Semantic recall & dedup**: hybrid FTS5 + BGE vector retrieval (RRF-fused) feeds a single `<memory_context>` prompt block; at admission, embedding near-neighbors are paired and merged/superseded by deterministic rules ("住在深圳" ≈ "家在深圳南山" never stored twice).
- **Dimension registry**: the extraction prompt's dimension guide and the validation whitelist are both generated from one declarative registry — extending memory types never touches prompt text by hand.
- Hot/warm sliding window for long-conversation context (REPL); older content auto-compressed by a cheap model.
- **Behavioral Procedures**: learned from user corrections, loaded every conversation (`playbook.json`).
- **User Profile**: narrative document storing personal phrases, goals, and agent agreements (`user_profile.md`); sections include 基础特征 (basic traits) and 心理与情绪 (emotional/psychological traits).
- **Proactive memory write**: Agent calls `memory_write` mid-conversation — the write flows through the same candidate→admission pipeline (no separate store, same evidence semantics).

### Dream — nightly memory consolidation ("做梦")

- Every night at 0:00, one unified pass (`run_nightly_consolidation`): re-extract the day's sessions, re-evaluate pending observations across sessions, expire TTL memories, write per-domain daily summaries, rebuild the memory vector index — then "dream": distill cross-session signals (recurring needs ≥3×, errors, success paths) into permanent insights, deduped via sqlite-vec against the freshly-admitted memories.
- Companion (苏念) emotional memory is isolated to companion mode (separate domain, never recalled elsewhere); diagnostic/clinical labels are hard-rejected by a denied-term list.
- **Reflect-back**: insights flow back as structured candidates (repetition/error → admission pipeline) and `playbook.json` (success_path) — no separate read path needed.
- **fact_sync mirror**: before each dream, active memories/playbook entries are mirrored into the vector store (type=`fact_sync`) so insight dedup naturally covers already-known facts; the mirror is fully rebuilt each cycle.
- **Permanent by design**: insights are never auto-deleted; `last_accessed` is tracked for observability but not used as an eviction basis (memory.db stays tiny, ~15KB per insight).
- **Sessions.db rotation**: full message history grows fast, so sessions.db is auto-archived via `VACUUM INTO` to `~/.ethan/archive/sessions.{start}~{end}.db` once it exceeds 10 MB, keeping the active db small while old chats remain queryable by date.

### Companion mode — 苏念 (Surrender Experiment counselor)

- A loadable plugin: toggle "苏念 · 陪伴倾听" in the chat UI to switch from the work assistant into a young, gentle female listener grounded in *The Surrender Experiment* (道法自然).
- In this mode the agent affirms first, listens deeply, and accompanies rather than rushing to solve — speaking like a real person, no AI stiffness.
- While in companion mode, the consolidator auto-extracts 心理与情绪 (mood / stressors / what soothes you / inner feelings) into your profile; basic traits are set by you in the "我的画像" (My Profile) settings tab.

### Legal expert mode — legal-assistant (install on demand)

- Switch to "法律专家" (legal expert) mode and a single `legal-assistant` skill covers case analysis, litigation review, contract review, legal document/proposal generation, trademark & patent IP, case intake, legal search and visualization — routed by "task verb + practice area" to the matching playbook, instead of dozens of sub-skills.
- **Zero pollution**: legal skills are tagged `modes: [法律]` and only activate in legal mode; in normal work mode they never enter the context.
- **Auto-install (on demand)**: the first time you enter legal mode without the skill installed, the agent **automatically pulls and installs** `legal-assistant` from the repo (it announces "installing…" first — no silent network access; on failure it tells you to run `ethan skill add legal` manually). Legal content is not bundled with the main repo, honoring the upstream CC-BY-NC non-commercial license.
- **Manual install**: run `ethan skill add legal` from the CLI (= `llm011/ethan-legal-skill/skills/legal-assistant`).
- **`/mode` switching**: both the CLI (REPL) and channels (Lark, etc.) support `/mode 法律` to enter and `/mode default` to return; an unrecognized name leaves the current mode unchanged. The mode is persisted per session and restored when you resume.

### Skill system

- Keyword trigger matching, auto-injected into system prompt.
- Optional semantic router (BGE INT8 + LR head) adds recall on top of keywords so differently-phrased requests still match (`pip install 'ethan-agent[embedding]'`; keyword-only without it — see [Deployment](#option-4-from-source-development)).
- `fast_path: true` routes matched input to the millisecond fast track.
- `channels: [lark, web]` filters skills by channel so each surface gets only relevant skills.
- `modes: [法律]` filters skills by conversation mode so each mode gets only relevant skills (empty = all modes).
- Hit tracking and correction collection; Heartbeat auto-updates skill content with a cheap model when corrections accumulate.
- Agent can create new skills mid-conversation via the `skill_create` tool.

### Three-track routing

- **fast**: short commands + keyword match → minimal prompt + fast_path tools only + 2 iterations.
- **medium**: mid-length messages → full prompt + all tools + 4 iterations.
- **full**: complex tasks → full prompt + all tools + 10 iterations.

### Loop control

- **Stuck detection**: when the agent repeats the same tool+args for 3 rounds (or 2 rounds of the same error), it injects a forced-reflection prompt (`<diagnosis>` + must switch strategy) instead of spinning to the iteration cap.
- **Graceful finalize**: on stuck-give-up (after 2 reflections) or hitting the iteration cap, the last round disables tools and the model writes a "done / blocker / what's needed from you" summary — never a raw `[max tool iterations reached]`.

### Scheduler & background tasks

- Create cron or interval jobs in conversation; SQLite-persisted, survives restarts.
- `heartbeat.md`: write natural-language tasks; the system runs them periodically.
- **Background tasks**: kick off a long-running task that runs async in its own session without blocking the current chat; result is fed back when done (Lark pushes to the originating chat, web surfaces the session). View / stop them on the `/background-tasks` page, with a running-count badge in the sidebar.

### Tool system

- Shell execution, web search (DuckDuckGo by default; Tavily or self-hosted SearXNG via config — see [`deploy/docker-compose.searxng.yml`](./deploy/docker-compose.searxng.yml)), web fetch, file I/O, knowledge base, charts, browser, desktop control, ACP delegation.
- Sensitive / side-effecting ops (shell, file write, secret read) ask for consent before running; the web shows a consent card, the REPL prompts y/N, and once granted in a session the same tool won't ask again.
- Tool results over 4 000 chars are auto-summarized by a cheap model before going back to the main model.
- Identical calls within the same turn hit an in-memory cache — no duplicate execution.
- `no_compress = True` for tools whose output contains IDs / refs / structured JSON the model must pass back verbatim.

### Prompt Caching

- System prompt split into stable layer / dynamic layer; stable layer cached 5 min, token cost drops to 0.1× (Anthropic).

### Multi-channel

- CLI REPL, Web UI (Next.js), **Desktop App** (Tauri, macOS + Windows), **Android App** (Kotlin/Compose), Lark/Feishu (WebSocket, no public IP required).
- **Lark auto-auth guidance**: when a user-token-dependent call (e.g. reading group chat context via `--as user`) fails with an auth-class error (99991663 / 99991661 / `need_user_authorization`), the bot sends a red guidance card to that chat telling the user to run `lark-cli auth login --domain im`. Throttled to once per 5 min per chat; non-auth errors (network / param / not-found) do not trigger it.
- **Lark multi-event subscription + card action callbacks**: each EventKey (message received / read receipts / reactions / `card.action.trigger`) runs in its own `lark-cli event consume` subprocess with independent reconnect; interactive card button clicks route back through `_handle_card_action` for button-driven workflows.
- **OpenAI-compatible Completions API** (`/v1/chat/completions`) with per-user API keys — drop Ethan in as a drop-in replacement for the OpenAI API.

### Browser control (real Chrome)

- Drive the real Chrome on the machine where ethan runs, from any channel (Web / Lark / CLI) — install the bundled [`browser-extension`](./browser-extension), point it at your ethan WebSocket endpoint, and the agent gets `browser_session` / `browser_tab` / `browser_page` tools.
- agent-browser style: accessibility-tree snapshot + ref map, click / fill / type / press / select / scroll / hover, screenshot, keyboard/mouse, page `eval`, all over Chrome DevTools Protocol.
- Session is bound to the conversation (isolated per chat); page ops within a session are serialized, different sessions run in parallel; idle sessions are released (tabs kept) after 30 min.
- Session-level one-time consent: the first browser call in a chat asks once, then all browser ops (incl. `eval`) are allowed for that chat.
- Transport is WebSocket only (extension → ethan), no native messaging host; see [docs/browser-control-plan.md](docs/browser-control-plan.md).

### Desktop control (macOS, via cua-driver)

- Control the local macOS desktop from any channel — take screenshots, click, type, drag, scroll, launch apps, open URLs.
- Powered by [trycua/cua](https://github.com/trycua/cua); connects to `cua-driver` (a native background daemon at `localhost:8000`) — no VM required.
- Screenshot results are passed directly to vision models; the agent sees the screen and decides the next action.
- `ethan server install` automatically installs and registers `cua-driver` as a launchd service; or install manually.
- Optional Python SDK: `pip install 'ethan-agent[computer]'` (cua-computer); gracefully absent when not installed.

### Coding Agent integration (ACP)

- `delegate_coding` / `ethan code "query"` delegates complex coding tasks to **Claude Code / OpenCode / Codex**, all running as JSON event streams with session resume.
- **Immersive tool modes**: switch the conversation mode to Codex / Claude Code / OpenCode; once switched, every message in that session continues the same tool (same tool session, per-session working dir).
- **Mirror sessions**: each `delegate()` becomes a real Ethan session (`source` = the actual tool: codex / claude / opencode) recording the dispatched query + coding-agent reply + steps, registered as a RunManager run so the delegated conversation can be watched live via SSE.
- Tool calls parse into collapsible sub-steps in the Web UI tool timeline with the final result highlighted. See [docs/acp.md](docs/acp.md).

### UI Cards & Interactive Charts

- **`ui_card` tool**: render structured info as cards instead of plain text. High-frequency types (comparison / ranking / stats / timeline) use fixed backend templates — the model just fills in typed data, so styling stays clean and consistent; free-form cards can still be hand-authored. Rendering is channel-aware over the same structured `card` data: Web renders [A2UI](https://a2ui.org/) via `@a2ui/react`, the REPL degrades to text, and Feishu/Lark renders native interactive cards.
- **Interactive charts** (`generate_chart`): Chart.js bar / line / pie / doughnut / horizontalBar / radar, following the [MCP Apps](https://modelcontextprotocol.io/) UI-resource convention (SEP-1865). The tool result carries only `{uri, data}` — the Web frontend fetches the template once per URI, renders it in a sandboxed iframe, and pushes data in via `postMessage`. A [quickchart.io](https://quickchart.io/) PNG is saved as a fallback for non-web channels.

### Multi-user

- Multiple isolated users share one instance. Each user has their own memory (structured memories / procedures / sessions), skills, and knowledge base — fully isolated per user. System prompts and provider config stay shared.
- Define users in `config.yaml` (each user binds a `web_token` for browser login and `api_keys` for the `/v1/chat/completions` API — both resolve to the same `user_id`):

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
│       ├── web_search.py      # DuckDuckGo / Tavily / SearXNG search
│       ├── web.py             # Fetch & extract web page text
│       ├── file.py            # File read/write/list
│       ├── memory_write.py    # Proactive fact write
│       ├── procedure_write.py # Proactive procedure write
│       ├── profile_update.py  # Update user profile
│       ├── skill_create.py    # Create skill mid-conversation
│       ├── chart.py           # Interactive Chart.js charts (MCP Apps)
│       ├── ui_card.py         # Structured A2UI cards
│       ├── acp.py             # Delegate to Claude Code / Codex / OpenCode
│       ├── browser.py         # Real Chrome control
│       ├── computer_use.py    # macOS desktop control
│       └── lark_tools.py     # Lark CLI wrappers (calendar / chat / send)
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

See [docs/memory.md](docs/memory.md) for the full architecture.

---

## Skills

Skills are Markdown files loaded from `~/.ethan/skills/`. On first run, all skills in [`ethan/defaults/skills/`](./ethan/defaults/skills/) are auto-copied there from the package; upgrades sync `SKILL.md` and `references/` (your own files are never touched).

Both directory format (`<name>/SKILL.md` + `references/`) and legacy single-file `.md` format are supported. When a directory-format skill is matched, its `references/*.md` filenames plus a one-line summary are listed in the injected context so the model knows which detail docs exist — use `skill_read(name=..., file="references/<name>.md")` to pull the full content on demand (pull-based, not bulk-injected).

```markdown
---
name: deploy-checklist
trigger: deploy|ship|release
description: Pre-deployment checklist
fast_path: true       # route to fast track when triggered
channels:             # empty = all channels; list = restrict
  - web
modes:                # empty = all modes; list = restrict to specific modes
  - 法律
version: "1.0"
---

Steps before deploying:
1. Run tests
2. Check for uncommitted changes
3. ...
```

When a user message matches a skill's `trigger`, the skill content is injected into the system prompt. See the [Built-in Skills](#built-in-skills) table above for everything that ships in the box.

Skills accumulate hit stats and user corrections. When corrections reach a threshold (default: 2), the Heartbeat job merges them into the skill file using a cheap model.

Install third-party skills with `ethan skill add <name>` (e.g. `ethan skill add legal`).

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

### Built-in tools

| Tool | Description |
|------|-------------|
| `shell` | Execute shell commands |
| `web_search` | DuckDuckGo (default) / Tavily / self-hosted SearXNG |
| `web` | Fetch and extract web page text |
| `file` | File read / write / list |
| `find_tools` | `rg` (ripgrep) and `fd` for code / file search |
| `knowledge` | Local markdown KB + sqlite-vec semantic search |
| `schedule` | Cron / interval job management |
| `memory_write` | Proactive fact write (candidate→admission pipeline) |
| `procedure_write` | Proactive procedure write |
| `profile_update` | Update user profile |
| `skill_create` / `skill_read` | Create / read skills mid-conversation |
| `install_skill` | Install third-party skill on demand |
| `secrets` | Read secret values from `~/.ethan/.secrets/` |
| `config` | Read / edit runtime config |
| `acp` | Delegate to Claude Code / Codex / OpenCode |
| `browser` | Real Chrome control (`browser_session` / `browser_tab` / `browser_page`) |
| `computer_use` | macOS desktop control via cua-driver |
| `ui_card` | Structured A2UI cards |
| `chart` | Interactive Chart.js charts (MCP Apps / SEP-1865) |
| `image_search` | Image search |
| `lark_tools` | Lark CLI wrappers (calendar / chat / messages) |
| `background_task` | Kick off async long-running tasks |
| `weather` | Weather lookup |

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
ethan web                          Open Web UI in browser
ethan web token                    Show / rotate Web login token

ethan model list|add|remove|default
ethan provider list|set|presets
ethan session list|show|delete
ethan skill list|show|add|create
ethan schedule list|remove|pause|resume
ethan router pull|status           # optional semantic router
ethan server install              # install cua-driver / launchd services
ethan code "query"                # ACP delegation to coding agents
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
POST /v1/chat/completions       # OpenAI-compatible API (per-user API key)
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

lark:
  app_id: "cli_xxxxxxxxxxxxxxxx"
  app_secret: "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"

users:
  - id: admin
    name: Admin
    web_token: admin_pass
    api_keys: [sk-ethan-admin-key]
    is_admin: true

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

Environment variables in `.env` override config values (useful for secrets). See [`deploy/.env.example`](./deploy/.env.example) for the Docker template.

### Config directory layout

```
~/.ethan/
├── config.yaml          # Main config (providers, models, routing, lark, users)
├── system/
│   ├── identity.md      # Agent identity (name, role)
│   ├── soul.md          # Behavioral principles
│   └── heartbeat.md     # Heartbeat tasks (natural language)
├── memory/
│   ├── memory.db        # Structured memories + evidence + insights + vector index
│   ├── playbook.json  # Behavioral rules
│   └── user_profile.md  # User profile (narrative)
├── skills/              # User-installed + auto-copied default skills
│   └── <name>/
│       └── SKILL.md
├── .secrets/             # Secret files for skills (e.g. Feishu app creds)
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
- [x] 40+ built-in skills shipping in the box (see [Built-in Skills](#built-in-skills))

**Tools**
- [x] shell, web_search, web_fetch, file_read/write/list, rg, fd
- [x] Knowledge base (sqlite-vec semantic search), scheduler tools, ACP → Claude Code / Codex / OpenCode
- [x] `ui_card` (A2UI structured cards), `generate_chart` (interactive Chart.js via MCP Apps)
- [x] Browser control (real Chrome via extension) + desktop control (macOS via cua-driver)

**Scheduler**
- [x] cron + interval, SQLite persistence, auto-restore on restart
- [x] `heartbeat.md`: natural-language periodic tasks executed automatically
- [x] Background tasks with per-chat async execution

**Channels & API**
- [x] Web UI (Next.js): chat timeline, memory, skills, schedule, knowledge, settings
- [x] Desktop App (Tauri): macOS + Windows, native window with embedded Web UI
- [x] Android App (Kotlin/Compose): mobile client with chat SSE, sessions, memory, settings
- [x] Feishu/Lark WebSocket (no public IP required) + multi-event subscription + card action callbacks
- [x] OpenAI-compatible Completions API (`/v1/chat/completions`) + per-user API key management
- [x] Docker deployment + macOS launchd auto-start
- [x] Multi-user isolation (memory / skills / knowledge per user)

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
- [x] **ACP multi-turn optimization**: `delegate_coding` resumes coding-agent sessions per (agent × working_dir). All three backends (Claude Code / OpenCode / Codex) run as JSON event streams with session resume, parsed into collapsible sub-steps in the Web UI tool timeline with highlighted final result.
- [x] **Mirror sessions**: each `delegate()` becomes a real Ethan session recording the dispatched query + coding-agent reply + steps
- [x] **Immersive tool modes**: switch the conversation mode to Codex / Claude Code / OpenCode
- [ ] **MCP client**: connect external MCP servers, auto-register tools

**Long-term**
- [ ] **Space isolation**: separate memory/skills per context (life / work / project)
- [ ] **Async interrupt**: detect new messages during long tasks, respond between tool calls
- [ ] **Obsidian integration**: read/write Obsidian vault as knowledge base

---

## Documentation

Full documentation is available at **[llm011.github.io/ethan-agent](https://llm011.github.io/ethan-agent/)** — the same docs site you see in Ethan's built-in "Docs" tab.

Key docs:
- [Installation](docs/installation.md) — pip / Docker / source / desktop app
- [Memory System](docs/memory.md) — five-layer architecture, dream consolidation, fact_sync
- [Agent Loop](docs/agent-loop.md) — three-track routing, memory injection
- [Architecture Overview](docs/architecture.md) — system components, data flow
- [Interface](docs/interface.md) — CLI / REPL / HTTP API / Web UI / Desktop / Feishu channels
- [Heartbeat](docs/heartbeat.md) — background maintenance, midnight loop
- [Tools](docs/tools.md) — built-in tools, `no_compress`, `ui_card`, MCP Apps charts
- [ACP Integration](docs/acp.md) — Claude Code / OpenCode / Codex delegation
- [Browser Control](docs/browser/overview.md) — real Chrome automation
- [Web Search](docs/web-search.md) — DuckDuckGo / Tavily / SearXNG
- [Modes](docs/modes.md) — companion / legal / coding agent modes
- [Legal Mode](docs/legal-mode.md) — `legal-assistant` skill details

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
