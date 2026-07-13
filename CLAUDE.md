# Ethan Agent - Project Instructions

## Worktree 工作流（必须遵守）

**禁止在主仓库 `/Users/jsongo/code/life/ethan-ai` 直接开发 feature。** 主仓库始终保持在 `main` 分支，只用于：
- 拉取最新 main：`git pull`
- 查看 main 上的文件
- 创建/删除 worktree
- 合并 PR 后清理 worktree

所有 feature 开发必须在 worktree 中进行：

```bash
# 创建 worktree（从最新 main 切出新分支）
git pull
git worktree add ../ethan-ai-<feature-name> -b feature/<feature-name>

# 进入 worktree 开发
cd ../ethan-ai-<feature-name>
# ... 编码、提交、推送、创建 PR ...

# PR 合并后清理
git worktree remove ../ethan-ai-<feature-name>
git branch -d feature/<feature-name>
```

**命名约定**：
- worktree 目录：`ethan-ai-<kebab-case-name>`（放在主仓库同级目录）
- 分支名：`feature/<kebab-case-name>`

**已有 worktree 列表**：`git worktree list`

## 多 worktree 开发的服务启动规范

**问题**：ethan 的 watchdog 机制通过 `/tmp/ethan/server.pid` 管理服务进程。多个 worktree 同时启动 `ethan serve` 会互相冲突——watchdog 会杀掉 PID 文件指向的进程，导致非主实例被误杀。

**规则**：
1. **默认端口 8900 同一时间只能有一个实例**。watchdog 只监控 8900 端口，非 8900 端口的实例会被 watchdog 视为"server 死亡"并触发重启，可能杀掉其他实例。
2. **开发测试时使用随机端口**（8901-8999 之间），但要意识到：
   - 启动的实例**不要写入 `/tmp/ethan/server.pid`**（否则会被 watchdog 杀）
   - 实例可能被 watchdog 的端口扫描误杀（`_kill_server` 会扫描 8900 端口占用）
   - 优先用 `ethan -p "prompt" --yes` 单轮模式测试，不启动常驻服务
3. **浏览器插件测试**：浏览器插件通过 `ws://localhost:<port>/ws/browser` 连接 ethan。测试前确认：
   - ethan 服务在监听目标端口
   - 系统代理（如 `127.0.0.1:7890`）会拦截 ws 连接，浏览器插件需绕过代理或配置 no_proxy
   - 可用 `NO_PROXY=localhost,127.0.0.1` 验证连接是否正常
   4. **启动命令示例**（worktree 开发测试）：
   ```bash
   # 随机端口 8901-8999，避开 8900（watchdog 占用）和已用端口
   # ETHAN_NO_WATCHDOG=1 跳过 PID 写入和 watchdog，避免与其他实例冲突
   PORT=$((RANDOM % 99 + 8901))
   ETHAN_NO_WATCHDOG=1 .venv/bin/ethan serve --host 127.0.0.1 --port $PORT
   ```
5. **不要 `pkill -f "ethan serve"`**：会误杀其他 worktree 的实例。只 kill 自己启动的 PID。
6. **`ETHAN_NO_WATCHDOG=1` 环境变量**：代码级开关（`api.py` + `heartbeat.py`），设为 1 时：
   - 不写 `/tmp/ethan/server.pid`（避免被 watchdog 杀）
   - 不拉起 watchdog 进程（避免接管其他实例）
   - heartbeat 不检查 watchdog 存活（避免互相拉起）
   开发测试时必须带这个环境变量。

   > 注意：`ethan serve` 默认（不设该变量）**会**写入 `/tmp/ethan/server.pid` 并自动拉起 watchdog。目前**没有** `--no-pid` 之类的独立命令行参数，唯一的开关就是这个环境变量。上面的启动示例（第 4 条）已带 `ETHAN_NO_WATCHDOG=1`，正是为了跳过 PID 写入——**请勿删除该变量**，否则仍会写 PID、被 watchdog 误杀。

## Agent Behaviors & Rules
- **ALWAYS run the code and verify it passes after modifying it.** Never stop after just modifying code without running a local test to catch IndentationError, SyntaxError, or logic errors. Use `uv run ...` or node scripts to verify.

- **Never write literal newlines inside f-strings.** Use `\n` escape sequences instead (e.g., `f"line1\nline2"`, never a real line break inside an f-string). Literal newlines in f-strings cause SyntaxError in Python < 3.12.

- **Always update both READMEs together.** `README.md` and `README_CN.md` must stay in sync — never update one without updating the other.

- **Review `docs/` after any feature change.** When a new feature is added or existing behavior is changed, check whether any file in `docs/` describes the affected area and update it if needed.

- **New tools: decide `no_compress` based on whether output is read vs. reused.** Tool output over 4000 chars is auto-compressed by a cheap model into a ~1200-char summary before reaching the main model (`ethan/tools/registry.py`). That's fine when the output is *prose for the model to read* (web pages, shell logs, search results) — let it compress. But if the output contains data the model must pass back *verbatim* — IDs, refs, coordinates, file paths, structured JSON (e.g. browser tab_id/session_id, snapshot refs, skill instructions, ui_card structures) — set `no_compress = True` on the tool class. Otherwise compression mangles the IDs into a prose summary and the model can no longer act on them (symptom: "it listed the items but couldn't operate on them"). When in doubt, ask: is this output for the model to *read*, or to *feed back as a parameter*? The latter needs `no_compress`.

- **Reviewing PRs: comment as the user, in Chinese, only on the most severe issues.** When asked to review a PR, post comments under the user's identity (not Claude's). Write in Chinese, short and human-sounding (casual tone, like the user wrote it). Only call out the 1-3 most serious problems worth acting on — mention minor/cleanup issues in one trailing line at most, or skip them. Don't post the full structured review. **Keep the tone gentle and friendly, not blunt or commanding** — these are someone else's PRs. Prefer soft phrasing like "可以关注下 / 建议看看" over "很要命 / 先修这俩". Stay 和气. **Phrase suggested fixes as questions, not imperatives** — say "改成 suspend 是不是好些？" / "是不是可以删掉这个 stub？" instead of "改成 suspend" / "删掉这个 stub". **Anchor each comment to the specific line/code it's about** — post inline review comments via `gh api repos/{owner}/{repo}/pulls/{n}/comments` (with `commit_id`, `path`, `line`, `side=RIGHT`), NOT a single lump comment in the general conversation area.

## Publishing to PyPI

When the user says "发版" or "release":

1. Read current version from `pyproject.toml` (`version = "X.Y.Z"`)
2. Bump the version:
   - Default: increment patch → `X.Y.Z+1`
   - User says "中版本" / minor: increment minor → `X.Y+1.0`
   - User says "大版本" / major: increment major → `X+1.0.0`
3. Update `pyproject.toml` with the new version.
4. Create and push the tag — this triggers the GitHub Action which builds and publishes to PyPI:
   ```bash
   git add pyproject.toml
   git commit -m "chore: bump version to vX.Y.Z"
   git tag vX.Y.Z
   git push origin main
   git push origin vX.Y.Z
   ```

The GitHub Action (`.github/workflows/publish-pypi.yml`) triggers on `v*` tags, reads the version from the tag name, injects it into `pyproject.toml`, builds, and publishes via `uv publish`. No manual PyPI interaction needed after the tag is pushed.
