# Ethan Agent - Project Instructions

## Agent Behaviors & Rules
- **ALWAYS run the code and verify it passes after modifying it.** Never stop after just modifying code without running a local test to catch IndentationError, SyntaxError, or logic errors. Use `uv run ...` or node scripts to verify.

- **Never write literal newlines inside f-strings.** Use `\n` escape sequences instead (e.g., `f"line1\nline2"`, never a real line break inside an f-string). Literal newlines in f-strings cause SyntaxError in Python < 3.12.

- **Always update both READMEs together.** `README.md` and `README_CN.md` must stay in sync — never update one without updating the other.

- **Review `docs/` after any feature change.** When a new feature is added or existing behavior is changed, check whether any file in `docs/` describes the affected area and update it if needed.
