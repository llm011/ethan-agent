"""Skill 加载器 — 支持两种技能来源：

1. 内置技能（代码随附）：ethan/skills/builtin/<name>/SKILL.md
2. 用户技能（自行安装）：~/.ethan/skills/<name>/SKILL.md 或 ~/.ethan/skills/<name>.md（兼容旧格式）

加载顺序：内置先加载，用户技能可按同名覆盖内置。
每个技能目录下 references/*.md 可供 agent 按需读取，不注入 prompt。
"""
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import yaml

from ethan.core.config import CONFIG_DIR

# 内置技能目录（随代码发布，ethan/skills/<name>/SKILL.md）
BUILTIN_SKILLS_DIR = Path(__file__).parent
# 用户技能目录（~/.ethan/skills/）
USER_SKILLS_DIR = CONFIG_DIR / "skills"


@dataclass
class Skill:
    name: str
    description: str
    trigger: list[str]
    content: str
    source: Path
    builtin: bool = False  # True = 内置，False = 用户安装
    fast_path: bool = False  # True = 命中 trigger 时走 Fast Path（不受长度限制）


def _parse_frontmatter(text: str) -> tuple[dict, str]:
    """解析 YAML frontmatter，返回 (meta, body)。"""
    match = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)", text, re.DOTALL)
    if not match:
        return {}, text
    try:
        meta = yaml.safe_load(match.group(1)) or {}
    except yaml.YAMLError:
        meta = {}
    return meta, match.group(2).strip()


def load_skill_from_file(path: Path, builtin: bool = False) -> Optional[Skill]:
    """从单个 .md 文件加载 Skill（旧格式兼容）。"""
    text = path.read_text(encoding="utf-8")
    meta, content = _parse_frontmatter(text)
    if not meta and not content:
        return None

    name = meta.get("name", path.stem)
    description = meta.get("description", "")
    trigger_raw = meta.get("trigger", "")
    if isinstance(trigger_raw, str):
        triggers = [t.strip() for t in trigger_raw.split("|") if t.strip()]
    elif isinstance(trigger_raw, list):
        triggers = trigger_raw
    else:
        triggers = []

    fast_path = bool(meta.get("fast_path", False))

    return Skill(name=name, description=description, trigger=triggers,
                 content=content, source=path, builtin=builtin, fast_path=fast_path)


def load_skill_from_dir(skill_dir: Path, builtin: bool = False) -> Optional[Skill]:
    """从技能子目录加载 Skill（新格式：<name>/SKILL.md）。"""
    skill_md = skill_dir / "SKILL.md"
    if not skill_md.exists():
        return None
    skill = load_skill_from_file(skill_md, builtin=builtin)
    if skill:
        # name 默认用目录名
        if not skill.name or skill.name == "SKILL":
            skill.name = skill_dir.name
    return skill


def load_all_skills() -> list[Skill]:
    """加载所有技能，内置先加载，用户技能可按同名覆盖。"""
    skills: dict[str, Skill] = {}

    # 1. 加载内置技能（跳过 Python 模块文件和缓存）
    _SKIP = {"__pycache__", "__init__.py"}
    if BUILTIN_SKILLS_DIR.exists():
        for entry in sorted(BUILTIN_SKILLS_DIR.iterdir()):
            if entry.name in _SKIP or entry.suffix == ".py":
                continue
            skill = None
            if entry.is_dir():
                skill = load_skill_from_dir(entry, builtin=True)
            elif entry.suffix == ".md":
                skill = load_skill_from_file(entry, builtin=True)
            if skill:
                skills[skill.name] = skill

    # 2. 加载用户技能（同名则覆盖内置）
    if USER_SKILLS_DIR.exists():
        for entry in sorted(USER_SKILLS_DIR.iterdir()):
            skill = None
            if entry.is_dir() and not entry.name.endswith("-references"):
                skill = load_skill_from_dir(entry, builtin=False)
            elif entry.suffix == ".md":
                skill = load_skill_from_file(entry, builtin=False)
            if skill:
                skills[skill.name] = skill

    return list(skills.values())
