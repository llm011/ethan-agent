"""Skill 自生成工具 — 让 agent 将可复用模式写入 ~/.ethan/skills/。"""
import yaml

from ethan.tools.base import BaseTool


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

    def __init__(self, user_id: str = ""):
        self._user_id = user_id

    async def run(self, name: str, description: str, trigger: list[str] | None = None, content: str = "") -> str:
        from ethan.core.paths import user_skills_dir

        # 参数校验：缺任何一个都返回明确错误，不要静默创建空 skill
        if not name or not name.strip():
            return "Error: name is required."
        if not description or not description.strip():
            return "Error: description is required."
        if not trigger:
            return "Error: trigger is required (a non-empty list of keywords)."
        if not content or not content.strip():
            return "Error: content is required (the skill's Markdown body)."

        # Sanitize name to prevent path traversal
        safe_name = "".join(c for c in name if c.isalnum() or c in "-_")
        if not safe_name:
            return "Error: invalid skill name"

        skills_dir = user_skills_dir(self._user_id)
        skill_dir = skills_dir / safe_name
        skill_path = skill_dir / "SKILL.md"
        if skill_path.exists() or (skills_dir / f"{safe_name}.md").exists():
            return f"Skill '{safe_name}' already exists. Not overwriting."

        try:
            skill_dir.mkdir(parents=True, exist_ok=True)
            frontmatter = {"name": safe_name, "description": description, "trigger": trigger}
            text = f"---\n{yaml.dump(frontmatter, allow_unicode=True, sort_keys=False)}---\n\n{content}"
            skill_path.write_text(text, encoding="utf-8")
        except Exception as e:
            return f"Error creating skill '{safe_name}': {e}"
        return f"Skill '{safe_name}' created at {skill_path}"
