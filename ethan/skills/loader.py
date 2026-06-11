"""Skill 加载器 — 从 Markdown 文件加载 Skill。

Skill 文件格式：
---
name: weather-query
trigger: 天气|weather|气温
description: 查询天气的标准流程
---

Skill 正文内容...
"""
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import yaml

from ethan.core.config import CONFIG_DIR

SKILLS_DIR = CONFIG_DIR / "skills"


@dataclass
class Skill:
    name: str
    description: str
    trigger: list[str]  # 关键词列表
    content: str  # Markdown 正文
    source: Path  # 来源文件


def load_skill(path: Path) -> Optional[Skill]:
    """从单个 .md 文件加载 Skill。"""
    text = path.read_text(encoding="utf-8")

    # 解析 YAML frontmatter
    match = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)", text, re.DOTALL)
    if not match:
        return None

    try:
        meta = yaml.safe_load(match.group(1)) or {}
    except yaml.YAMLError:
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

    content = match.group(2).strip()

    return Skill(
        name=name,
        description=description,
        trigger=triggers,
        content=content,
        source=path,
    )


def load_all_skills(directory: Path = SKILLS_DIR) -> list[Skill]:
    """扫描目录加载所有 .md Skill 文件。"""
    skills = []
    if not directory.exists():
        return skills

    for path in sorted(directory.glob("*.md")):
        skill = load_skill(path)
        if skill:
            skills.append(skill)

    return skills
