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
