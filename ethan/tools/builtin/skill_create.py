"""Skill 自生成工具 — 让 agent 将可复用模式写入 ~/.ethan/skills/。"""
import yaml

from ethan.core.config import CONFIG_DIR
from ethan.tools.base import BaseTool

_SKILLS_DIR = CONFIG_DIR / "skills"


class SkillCreateTool(BaseTool):
    fast_path = False
    name = "skill_create"
    description = (
        "Create a new personal skill (reusable prompt template) saved to ~/.ethan/skills/. "
        "Call this when you identify a recurring pattern worth formalizing. "
        "Idempotent — will not overwrite an existing skill with the same name."
    )
    parameters = {
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "Skill name, lowercase with hyphens, e.g. 'morning-checklist'",
            },
            "description": {
                "type": "string",
                "description": "One-line description of what this skill does",
            },
            "trigger": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Keywords that trigger this skill automatically",
            },
            "content": {
                "type": "string",
                "description": "The skill's Markdown content — instructions or template the agent follows",
            },
        },
        "required": ["name", "description", "trigger", "content"],
    }

    async def run(self, name: str, description: str, trigger: list[str], content: str) -> str:
        # Sanitize name to prevent path traversal
        safe_name = "".join(c for c in name if c.isalnum() or c in "-_")
        if not safe_name:
            return "Error: invalid skill name"

        skill_dir = _SKILLS_DIR / safe_name
        skill_path = skill_dir / "SKILL.md"
        if skill_path.exists() or (_SKILLS_DIR / f"{safe_name}.md").exists():
            return f"Skill '{safe_name}' already exists. Not overwriting."

        skill_dir.mkdir(parents=True, exist_ok=True)
        frontmatter = {"name": safe_name, "description": description, "trigger": trigger}
        text = f"---\n{yaml.dump(frontmatter, allow_unicode=True, sort_keys=False)}---\n\n{content}"
        skill_path.write_text(text, encoding="utf-8")
        return f"Skill '{safe_name}' created at {skill_path}"
