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


def _file_summary(path: Path, max_len: int = 70) -> str:
    """取 md/txt 文件的一句话摘要：首个非空、非 frontmatter、非标题井号的行。"""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""
    lines = text.splitlines()
    in_front = False
    for i, ln in enumerate(lines):
        s = ln.strip()
        if i == 0 and s == "---":
            in_front = True
            continue
        if in_front:
            if s == "---":
                in_front = False
            continue
        if not s or s.startswith("#") or s.startswith("```") or s.startswith("|"):
            continue
        # 去掉 markdown 强调符号，截断
        clean = s.lstrip("-*").strip()
        clean = clean.split("`")[0].strip()
        if clean:
            return clean[:max_len] + ("…" if len(clean) > max_len else "")
    return ""


def _build_file_tree(skill_dir: Path, skill_name: str, cap: int = 40) -> str:
    """列出技能目录下所有文件（不含 SKILL.md），按目录分组，md 文件附一句话摘要。

    返回的相对路径可直接用于 skill_read(name=..., file="<相对路径>") 一次读到位，
    避免 agent 用 list_files → read_file 逐层翻。文件过多时只给顶层结构 + 索引提示，
    避免一次性灌入巨量内容。
    """
    files = sorted(
        (p for p in skill_dir.rglob("*") if p.is_file() and p.name != "SKILL.md"),
        key=lambda p: p.relative_to(skill_dir).as_posix(),
    )
    if not files:
        return ""

    header = (
        f"用 skill_read(name=\"{skill_name}\", file=\"<相对路径>\") 直接读任一文件，"
        f"不要 list_files/read_file 逐层翻："
    )

    # 文件过多（如 bytedcli 这种含几十个子技能的 meta-skill）：只列顶层 + 索引提示
    if len(files) > cap:
        # 优先指向索引文件（约定 references/subskills-index.md）
        index_hint = ""
        idx = skill_dir / "references" / "subskills-index.md"
        if idx.is_file():
            index_hint = (
                f"\n  此技能文件较多（{len(files)} 个）。先读索引定位："
                f"\n    skill_read(name=\"{skill_name}\", file=\"references/subskills-index.md\")"
            )
        # 列出顶层目录，让 agent 知道结构
        top = sorted(
            {p.relative_to(skill_dir).parts[0] + ("/" if p.is_dir() else "") for p in skill_dir.iterdir()
             if p.name != "SKILL.md"},
        )
        top_str = "\n".join(f"  {t}" for t in top) or "  (无)"
        return (
            header + index_hint +
            f"\n  顶层结构：\n{top_str}"
            f"\n  想找具体文件用 fd_find(pattern=\"关键词\", path=\"技能目录\") 搜文件名，"
            f"再用 skill_read(name=\"{skill_name}\", file=\"...\") 读。"
        )

    # 文件不多：完整树 + 每个文件一句话摘要
    lines = [header]
    prev_dir = None
    for p in files:
        rel = p.relative_to(skill_dir).as_posix()
        d = rel.rsplit("/", 1)[0] if "/" in rel else ""
        if d != prev_dir:
            lines.append(f"  {d + '/' if d else '(根目录)'}")
            prev_dir = d
        summary = _file_summary(p) if p.suffix in (".md", ".txt") else ""
        suffix = f"  — {summary}" if summary else ""
        lines.append(f"    {p.name}{suffix}")
    return "\n".join(lines)


class SkillReadTool(BaseTool):
    fast_path = True
    cacheable = True
    no_compress = True  # 技能文档是给模型的指令，必须逐字，绝不压成摘要
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
                "description": "可选。技能目录下某个文件的相对路径（支持嵌套，如 references/api.md、references/subskills/x/references/y.md）。"
                "省略则读 SKILL.md 主文件 + 列出其它文件及一句话摘要，按摘要选中后用 file= 一次读到位，不要改用 list_files/read_file 逐层翻。",
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

            tree = _build_file_tree(skill_dir, safe)
            if tree:
                parts.append(f"\n## 目录下其它文件\n{tree}")
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
    fast_path = True
    cacheable = True
    no_compress = True  # 技能清单要逐字，别被摘要吃掉名称/触发词
    name = "skill_list"
    description = (
        "列出所有已安装技能（名称 + 描述 + 触发词）。"
        "找技能、不确定有哪些技能、或用户问'你有什么技能/能不能xxx'时调用。"
        "找某个技能请先调本工具看名称，再用 skill_read(name=...) 读，不要去 fd_find/list_files 翻技能目录。"
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
