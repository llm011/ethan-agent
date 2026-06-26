"""用户画像更新工具 — 操作 user_profile.md 的指定章节。

section 体系与 consolidator 后台自动抽取共用 ethan.core.profile,保持一致。
章节(完整列表见 ethan.core.profile.SECTIONS):
- 基础特征(名字/年龄/性格/兴趣)
- 身份与背景 / 目标与方向 / 工作与沟通方式
- 心理与情绪(情绪模式/压力源/什么能安抚/重要内心感受/价值观)
- 个人语言与激励 / 与 Agent 的约定
"""
from ethan.core.profile import SECTIONS as _SECTIONS
from ethan.core.profile import ensure_profile, update_profile_section
from ethan.tools.base import BaseTool


class ProfileUpdateTool(BaseTool):
    fast_path = False
    side_effect = True
    name = "profile_update"
    description = (
        "Update the user's long-term profile document with narrative context that doesn't fit "
        "as a standalone fact. Use for personal info (name/age/personality/hobbies), emotional "
        "patterns, stressors, what soothes the user, mottos, goals, communication preferences, "
        "and special agreements between user and agent. "
        f"Sections: {' | '.join(_SECTIONS)}"
    )
    parameters = {
        "type": "object",
        "properties": {
            "section": {
                "type": "string",
                "description": f"Which profile section to update. One of: {' / '.join(_SECTIONS)}",
            },
            "entry": {
                "type": "string",
                "description": "The entry to add (written as a short sentence or phrase)",
            },
            "mode": {
                "type": "string",
                "description": "'append' (default) adds a new bullet; 'overwrite' replaces the section; 'merge' updates a similar existing bullet or adds new",
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
        content = ensure_profile(profile_path)
        updated = update_profile_section(content, section, entry, mode)
        profile_path.write_text(updated, encoding="utf-8")
        return f"Profile updated [{section}]: {entry}"
