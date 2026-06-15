# Ethan Agent - Project Instructions

## Agent Behaviors & Rules
- **ALWAYS run the code and verify it passes after modifying it.** Never stop after just modifying code without running a local test to catch IndentationError, SyntaxError, or logic errors. Use `uv run ...` or node scripts to verify.

- **Never write literal newlines inside f-strings.** Use `\n` escape sequences instead (e.g., `f"line1\nline2"`, never a real line break inside an f-string). Literal newlines in f-strings cause SyntaxError in Python < 3.12.

- **Always update both READMEs together.** `README.md` and `README_CN.md` must stay in sync — never update one without updating the other.

- **Review `docs/` after any feature change.** When a new feature is added or existing behavior is changed, check whether any file in `docs/` describes the affected area and update it if needed.

## Publishing to PyPI

When the user says "发版" or "release":

1. Read current version from `pyproject.toml` (`version = "X.Y.Z"`)
2. Bump the version:
   - Default: increment patch → `X.Y.Z+1`
   - User says "中版本" / minor: increment minor → `X.Y+1.0`
   - User says "大版本" / major: increment major → `X+1.0.0`
3. Update **both** files with the new version (easy to forget the second one):
   - `pyproject.toml` → `version = "X.Y.Z"`
   - `ethan/__init__.py` → `__version__ = "X.Y.Z"`
4. Create and push the tag — this triggers the GitHub Action which builds and publishes to PyPI:
   ```bash
   git add pyproject.toml ethan/__init__.py
   git commit -m "chore: bump version to vX.Y.Z"
   git tag vX.Y.Z
   git push origin main
   git push origin vX.Y.Z
   ```

The GitHub Action (`.github/workflows/publish-pypi.yml`) triggers on `v*` tags, reads the version from the tag name, injects it into `pyproject.toml`, builds, and publishes via `uv publish`. No manual PyPI interaction needed after the tag is pushed.
