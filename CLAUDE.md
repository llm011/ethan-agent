# Ethan Agent - Project Instructions

## Agent Behaviors & Rules
- **ALWAYS run the code and verify it passes after modifying it.** Never stop after just modifying code without running a local test to catch IndentationError, SyntaxError, or logic errors. Use `uv run ...` or node scripts to verify.

- **Never write literal newlines inside f-strings.** Use `\n` escape sequences instead (e.g., `f"line1\nline2"`, never a real line break inside an f-string). Literal newlines in f-strings cause SyntaxError in Python < 3.12.

- **Always update both READMEs together.** `README.md` and `README_CN.md` must stay in sync — never update one without updating the other.

- **Review `docs/` after any feature change.** When a new feature is added or existing behavior is changed, check whether any file in `docs/` describes the affected area and update it if needed.

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
