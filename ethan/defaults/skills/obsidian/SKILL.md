---
name: obsidian
title: Obsidian Vault Manager
description: Read, search, create, and edit notes in the Obsidian vault.
version: 1.1.0
author: NousResearch
license: MIT
platforms: [linux, macos, windows]
trigger:
  - obsidian
  - 笔记
  - vault
  - 知识库笔记
  - wikilink
  - note
  - 读笔记
  - 写笔记
  - 搜索笔记
  - 标签
  - tag
  - 双链
  - backlink
  - frontmatter
  - 属性
  - canvas
  - 画布
  - daily note
  - 日记
  - 重命名笔记
---
# Obsidian Vault

Use this skill for filesystem-first Obsidian vault work: reading notes, listing notes, searching note files, creating notes, appending content, adding wikilinks, managing tags, maintaining backlinks, and editing frontmatter.

## Vault path

Use a known or resolved vault path before calling file tools.

The documented vault-path convention is the `OBSIDIAN_VAULT_PATH` environment variable, for example from `${ETHAN_HOME:-~/.ethan}/.env`. If it is unset, fall back to `~/Documents/obsidian/work`, then `~/Documents/Obsidian Vault`.

File tools do not expand shell variables. Do not pass paths containing `$OBSIDIAN_VAULT_PATH` to `read_file`, `write_file`, `patch`, or `search_files`; resolve the vault path first and pass a concrete absolute path. Vault paths may contain spaces, which is another reason to prefer file tools over shell commands.

If the vault path is unknown, `terminal` is acceptable for resolving `OBSIDIAN_VAULT_PATH` or checking whether the fallback path exists. Once the path is known, switch back to file tools.

## Read a note

Use `read_file` with the resolved absolute path to the note. Prefer this over `cat` because it provides line numbers and pagination.

## List notes

Use `search_files` with `target: "files"` and the resolved vault path. Prefer this over `find` or `ls`.

- To list all markdown notes, use `pattern: "*.md"` under the vault path.
- To list a subfolder, search under that subfolder's absolute path.

## Search

Use `search_files` for both filename and content searches. Prefer this over `grep`, `find`, or `ls`.

- For filenames, use `search_files` with `target: "files"` and a filename `pattern`.
- For note contents, use `search_files` with `target: "content"`, the content regex as `pattern`, and `file_glob: "*.md"` when you want to restrict matches to markdown notes.

## Create a note

Use `write_file` with the resolved absolute path and the full markdown content. Prefer this over shell heredocs or `echo` because it avoids shell quoting issues and returns structured results.

## Append to a note

Prefer a native file-tool workflow when it is not awkward:

- Read the target note with `read_file`.
- Use `patch` for an anchored append when there is stable context, such as adding a section after an existing heading or appending before a known trailing block.
- Use `write_file` when rewriting the whole note is clearer than constructing a fragile patch.

For an anchored append with `patch`, replace the anchor with the anchor plus the new content.
For a simple append with no stable context, `terminal` is acceptable if it is the clearest safe option.

## Targeted edits

Use `patch` for focused note changes when the current content gives you stable context. Prefer this over shell text rewriting.

## Wikilinks

Obsidian links notes with `[[Note Name]]` syntax. When creating notes, use these to link related content.

- `[[Note Name]]` — link to a note
- `[[Note Name|Display Text]]` — custom display text
- `[[Note Name#Heading]]` — link to a heading inside a note
- `[[Note Name#^block-id]]` — link to a block reference
- `![[Note Name]]` — embed a full note
- `![[image.png]]` — embed an image attachment
- `![[image.png|300]]` — embed an image with a width hint

## Frontmatter / Properties

Notes may start with a YAML frontmatter block delimited by `---`. Common fields: `title`, `tags`, `aliases`, `date`, `cssclass`.

When creating notes that need metadata, include frontmatter at the very top, followed by a blank line before the body:

```yaml
---
title: My Note
tags:
  - project/active
  - meeting
date: 2026-07-20
---
```

To update frontmatter on an existing note, read the note with `read_file` first, then use `patch` against the lines between the two `---` fences. Keep YAML valid; arrays can be inline (`[a, b]`) or block-list style.

## Tag Management

Tags use the `一级/二级/三级` hierarchical format. Reuse existing tags whenever possible; do not invent new top-level tags impulsively.

- **List existing tags**: `python3 ~/.ethan/skills/obsidian/scripts/tag_manager.py list` — scans frontmatter `tags:` fields and inline `#tag` occurrences across the vault.
- **Add a tag to a note**: `python3 ~/.ethan/skills/obsidian/scripts/tag_manager.py add "note_path.md" "project/active"` — patches the note's frontmatter (creates one if missing). `note_path` may be absolute, or relative to the vault root.
- **Tag format**: `alpha/beta/gamma`, supports unlimited nesting. No leading digits; allowed chars: letters, digits, `_`, `-`, `/`.
- **Inline vs frontmatter**: inline `#tag` works anywhere in the body; frontmatter `tags:` is preferred for structured classification.

Before creating a new tag, always run `list` first and reuse an existing one if a close match exists.

## Backlinks / Link Maintenance

Backlinks are `[[Note Name]]` references pointing TO a note. Obsidian builds them automatically in-app; on the filesystem you maintain them by editing the source notes.

- **Find backlinks to a note**: `search_files` with `target: "content"`, `pattern: "\\[\\[Note Name"` and `file_glob: "*.md"` across the vault. The same prefix matches both `[[Note Name]]` and `[[Note Name|...]]`.
- **Rename a note safely**:
  1. Move the file with `terminal` (`mv "old.md" "new.md"`), or read+write+delete via file tools.
  2. Search for `[[Old Name]]` and `[[Old Name|...]]` across the vault.
  3. Patch each referring note to use `[[New Name]]` (preserve display text after `|`).
- **Delete a note safely**: search for backlinks first; either remove the links or convert them to plain text, then delete the file.

## Daily Notes

If the user keeps a daily-notes folder (commonly `Daily/`, `日记/`, or `journals/`), create today's note with `write_file` at the conventional path. Use `YYYY-MM-DD.md` naming unless the user has an existing convention. If unsure, list the vault root first to discover the folder.

## Canvas Files

`.canvas` files are JSON describing nodes (text/file/link/group) and edges on a 2D plane. See `references/canvas.md` for the spec. Edit with `write_file` producing valid JSON; do not hand-edit fragments. Coordinates: `x` increases right, `y` increases down; position is the top-left corner.

## Obsidian CLI (optional enhancement)

If `obsidian-cli` is installed (check with `terminal` running `which obsidian-cli`), it can automate some operations more safely than raw filesystem edits:

- `obsidian-cli print "note"` — print note content
- `obsidian-cli search "keyword"` — search note titles
- `obsidian-cli search-content "keyword"` — search note content
- `obsidian-cli create "path/note.md" --content "..."` — create note
- `obsidian-cli daily` — open today's daily note
- `obsidian-cli frontmatter "note" --set "key:value"` — write frontmatter field
- `obsidian-cli move "old.md" "new.md"` — rename note (auto-updates backlinks)
- `obsidian-cli list` — list vault files

Prefer the filesystem-first workflows above when `obsidian-cli` is unavailable. Use `obsidian-cli move` for renames when available, since it updates backlinks automatically.

## References

- `references/markdown.md` — Obsidian Flavored Markdown reference (wikilinks, embeds, callouts, frontmatter).
- `references/canvas.md` — JSON Canvas spec for `.canvas` files.
