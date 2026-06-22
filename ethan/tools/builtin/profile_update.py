"""用户画像更新工具 — 操作 ~/.ethan/memory/user_profile.md 的指定章节。

章节：
- 身份与背景
- 目标与方向
- 工作与沟通方式
- 个人语言与激励
- 与 Agent 的约定
"""
from pathlib import Path

from ethan.tools.base import BaseTool

_SECTIONS = [
    "身份与背景",
    "目标与方向",
    "工作与沟通方式",
    "个人语言与激励",
    "与 Agent 的约定",
]

_SECTION_HEADER = "## "


def _ensure_profile(profile_path: Path) -> str:
    """Ensure user_profile.md exists with all section headers and return its content."""
    if profile_path.exists():
        return profile_path.read_text(encoding="utf-8")

    profile_path.parent.mkdir(parents=True, exist_ok=True)
    lines = ["# 用户画像\n"]
    for s in _SECTIONS:
        lines.append(f"\n{_SECTION_HEADER}{s}\n")
    content = "\n".join(lines)
    profile_path.write_text(content, encoding="utf-8")
    return content


def _update_section(content: str, section: str, entry: str, mode: str) -> str:
    """Update a section in the profile content.

    mode='append': add entry as a new bullet under the section.
    mode='overwrite': replace everything under the section with entry.
    """
    header = f"{_SECTION_HEADER}{section}"
    lines = content.splitlines(keepends=True)

    # Find section start
    start_idx = None
    for i, line in enumerate(lines):
        if line.strip() == header.strip():
            start_idx = i
            break

    if start_idx is None:
        # Section not found — append it
        new_section = f"\n{header}\n- {entry}\n"
        return content + new_section

    # Find next section start (or end of file)
    end_idx = len(lines)
    for i in range(start_idx + 1, len(lines)):
        if lines[i].startswith(_SECTION_HEADER):
            end_idx = i
            break

    if mode == "overwrite":
        new_block = [lines[start_idx], f"- {entry}\n"]
        # Preserve trailing newline before next section
        if end_idx < len(lines):
            new_block.append("\n")
        return "".join(lines[:start_idx] + new_block + lines[end_idx:])
    else:  # append
        # Insert before the next section, after the last non-empty content line
        insert_at = end_idx
        # Walk back to find last content line (skip trailing blank lines before next section)
        for i in range(end_idx - 1, start_idx, -1):
            if lines[i].strip():
                insert_at = i + 1
                break
        new_line = f"- {entry}\n"
        return "".join(lines[:insert_at] + [new_line] + lines[insert_at:])


class ProfileUpdateTool(BaseTool):
    fast_path = False
    name = "profile_update"
    description = (
        "Update the user's long-term profile document with narrative context that doesn't fit "
        "as a standalone fact. Use for personal phrases, mottos, goals, communication preferences, "
        "and special agreements between user and agent. "
        "Sections: '身份与背景' | '目标与方向' | '工作与沟通方式' | '个人语言与激励' | '与 Agent 的约定'"
    )
    parameters = {
        "type": "object",
        "properties": {
            "section": {
                "type": "string",
                "description": (
                    "Which profile section to update. One of: "
                    "身份与背景 / 目标与方向 / 工作与沟通方式 / 个人语言与激励 / 与 Agent 的约定"
                ),
            },
            "entry": {
                "type": "string",
                "description": "The entry to add (written as a short sentence or phrase)",
            },
            "mode": {
                "type": "string",
                "description": "'append' (default) adds a new bullet; 'overwrite' replaces the section",
                "default": "append",
            },
        },
        "required": ["section", "entry"],
    }

    def __init__(self, user_id: str = ""):
        self._user_id = user_id

    async def run(self, section: str, entry: str, mode: str = "append") -> str:
        from ethan.core.paths import user_profile_path
        if section not in _SECTIONS:
            valid = " / ".join(_SECTIONS)
            return f"Unknown section '{section}'. Valid sections: {valid}"

        profile_path = user_profile_path()
        content = _ensure_profile(profile_path)
        updated = _update_section(content, section, entry, mode)
        profile_path.write_text(updated, encoding="utf-8")
        return f"Profile updated [{section}]: {entry}"
