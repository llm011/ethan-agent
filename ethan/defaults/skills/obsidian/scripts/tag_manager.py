#!/usr/bin/env python3
"""Tag manager for Obsidian vault (filesystem-first, no obsidian-cli required).

Usage:
    python3 tag_manager.py list
    python3 tag_manager.py add "note_path.md" "project/active"

`note_path` may be absolute, or relative to the vault root.
Vault path is resolved from $OBSIDIAN_VAULT_PATH, defaulting to ~/Documents/obsidian/work.
"""
import json
import os
import re
import sys
from pathlib import Path

DEFAULT_VAULT = os.path.expanduser("~/Documents/obsidian/work")
TAG_PATTERN = re.compile(r'(^|\s)(#[a-zA-Z_/\-][a-zA-Z0-9_/\-]*)')


def get_vault_path():
    return os.environ.get("OBSIDIAN_VAULT_PATH") or DEFAULT_VAULT


def list_obsidian_tags():
    vault_path = get_vault_path()
    if not os.path.isdir(vault_path):
        return []
    tags = set()
    for md_file in Path(vault_path).rglob("*.md"):
        try:
            text = md_file.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        # Frontmatter tags
        if text.startswith("---\n"):
            end = text.find("\n---\n", 4)
            if end != -1:
                fm = text[4:end]
                for line in fm.splitlines():
                    if line.startswith("tags:"):
                        content = line.split("tags:", 1)[1].strip()
                        content = content.replace("[", "").replace("]", "")
                        content = content.replace('"', "").replace("'", "")
                        for t in re.split(r'[,\s]+', content):
                            t = t.strip()
                            if t:
                                tags.add(t)
        # Body #tags
        for m in TAG_PATTERN.finditer(text):
            tags.add(m.group(2)[1:])
    return sorted(tags)


def add_tag_to_note(note_path, new_tag):
    vault_path = get_vault_path()
    if not os.path.isabs(note_path):
        note_path = os.path.join(vault_path, note_path)
    if not os.path.isfile(note_path):
        print(f"❌ Note not found: {note_path}", file=sys.stderr)
        sys.exit(1)
    text = Path(note_path).read_text(encoding="utf-8")

    if text.startswith("---\n"):
        end = text.find("\n---\n", 4)
        if end != -1:
            fm = text[4:end]
            body = text[end + 5:]
            lines = fm.splitlines()
            tags_line_idx = None
            existing_tags = []
            for i, line in enumerate(lines):
                if line.startswith("tags:"):
                    tags_line_idx = i
                    content = line.split("tags:", 1)[1].strip()
                    content = content.replace("[", "").replace("]", "")
                    content = content.replace('"', "").replace("'", "")
                    existing_tags = [t.strip() for t in re.split(r'[,\s]+', content) if t.strip()]
                    break
            if new_tag in existing_tags:
                print(f"ℹ️  Tag '{new_tag}' already exists in {note_path}")
                return
            existing_tags.append(new_tag)
            tag_str = ", ".join(existing_tags)
            new_tags_line = f"tags: [{tag_str}]"
            if tags_line_idx is not None:
                lines[tags_line_idx] = new_tags_line
            else:
                lines.insert(0, new_tags_line)
            new_fm = "\n".join(lines)
            new_text = f"---\n{new_fm}\n---\n{body}"
            Path(note_path).write_text(new_text, encoding="utf-8")
            print(f"✅ Added tag '{new_tag}' to {note_path}")
            return

    # No frontmatter; create one
    new_text = f"---\ntags: [{new_tag}]\n---\n\n{text}"
    Path(note_path).write_text(new_text, encoding="utf-8")
    print(f"✅ Added tag '{new_tag}' to {note_path} (created frontmatter)")


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    cmd = sys.argv[1]
    if cmd == "list":
        print(json.dumps(list_obsidian_tags(), indent=2, ensure_ascii=False))
    elif cmd == "add" and len(sys.argv) == 4:
        add_tag_to_note(sys.argv[2], sys.argv[3])
    else:
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
