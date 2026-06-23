"""skill_read / skill_list 工具 —— 让 Agent 高效读取已安装技能。

没有这两个工具时，Agent 只能 fd_find → file_list → file_read 一步步翻技能目录，
5 次调用才能读完一个技能。skill_read 一步返回 SKILL.md + 目录文件清单。
"""
from __future__ import annotations

from pathlib import Path

from ethan.tools.base import BaseTool


def _safe_segment(name: str) -> str:
    """ sanitize：只允许字母数字 _ - . /，禁路径穿越。"""
    safe = "".join(c for c in name if c.isalnum() or c in "-_./")
    safe = safe.strip("./")
    if not safe or ".." in safe:
        return ""
    return safe


class SkillReadTool(BaseTool):
    fast_path = False
    cacheable = True
    name = "skill_read"
    description = (
        "读取已安装技能的完整内容。用户让你执行/修改某个技能、或你要搞清楚某技能怎么用时调用——"
        "比逐个 file_read + file_list 高效得多（一步搞定）。"
        "默认返回 SKILL.md 主文件 + 技能目录下所有其它文件的清单；指定 file 可读某个具体文件（如 gen_image.py）。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "技能名，如 image-generate、lark-im",
            },
            "file": {
                "type": "string",
                "description": "可选。技能目录下的某个文件（如 gen_image.py、references/api.md）。省略则读 SKILL.md 主文件 + 列出其它文件。",
            },
        },
        "required": ["name"],
    }

    async def run(self, name: str, file: str = "") -> str:
        from ethan.core.paths import user_skills_dir

        safe = _safe_segment(name)
        if not safe:
            return f"Error: 无效的技能名: {name!r}"

        skills_dir = user_skills_dir()
        skill_dir = skills_dir / safe

        # 目录格式：skills/<name>/SKILL.md + 参考文件
        if skill_dir.is_dir():
            if file:
                file_safe = _safe_segment(file)
                if not file_safe:
                    return f"Error: 无效的文件名: {file!r}"
                target = skill_dir / file_safe
                if not target.is_file():
                    others = sorted(p.relative_to(skill_dir).as_posix()
                                    for p in skill_dir.rglob("*") if p.is_file())
                    return f"Error: 文件不存在: {file}\n目录下可用文件:\n" + \
                           "\n".join(f"- {f}" for f in others)
                return f"# {safe}/{file_safe}\n\n" + _read_truncated(target)

            # 默认：SKILL.md + 文件清单
            parts = []
            skill_md = skill_dir / "SKILL.md"
            if skill_md.is_file():
                parts.append(f"# {safe}/SKILL.md\n\n" + _read_truncated(skill_md))
            else:
                # 没有 SKILL.md，读目录里第一个 md
                mds = sorted(skill_dir.glob("*.md"))
                if mds:
                    parts.append(f"# {safe}/{mds[0].name}\n\n" + _read_truncated(mds[0]))

            others = sorted(p.relative_to(skill_dir).as_posix()
                            for p in skill_dir.rglob("*")
                            if p.is_file() and p.name != "SKILL.md")
            if others:
                hint = "\n".join(f"- {f}" for f in others)
                parts.append(f"\n## 目录下其它文件\n{hint}\n\n用 skill_read(name=\"{safe}\", file=\"...\") 读取")
            return "\n".join(parts) if parts else f"Error: 技能 {safe!r} 目录为空"

        # 旧格式：单文件 skills/<name>.md
        single = skills_dir / f"{safe}.md"
        if single.is_file():
            return f"# {safe}.md\n\n" + _read_truncated(single)

        # 没找到
        available = sorted(
            (p.name if p.is_file() else p.name + "/")
            for p in skills_dir.iterdir() if p.is_dir() or p.suffix == ".md"
        ) if skills_dir.is_dir() else []
        avail_str = ", ".join(available) or "(无)"
        return f"Error: 技能不存在: {name!r}\n已安装技能: {avail_str}"


class SkillListTool(BaseTool):
    fast_path = False
    cacheable = True
    name = "skill_list"
    description = (
        "列出所有已安装技能（名称 + 描述 + 触发词）。"
        "不确定有哪些技能、或用户问'你有什么技能'时调用。"
    )
    parameters = {
        "type": "object",
        "properties": {},
        "required": [],
    }

    async def run(self) -> str:
        from ethan.skills.loader import load_all_skills

        skills = load_all_skills()
        if not skills:
            return "(暂无已安装技能)"
        lines = ["已安装技能:", ""]
        for s in skills:
            trigger = ", ".join(s.trigger[:5]) if s.trigger else "—"
            lines.append(f"- {s.name}: {s.description}")
            lines.append(f"  触发: {trigger}")
        return "\n".join(lines)


def _read_truncated(path: Path, limit: int = 12000) -> str:
    text = path.read_text(encoding="utf-8", errors="replace")
    if len(text) > limit:
        text = text[:limit] + "\n...(truncated)"
    return text
