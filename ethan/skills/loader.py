"""Skill 加载器 — 从用户目录 ~/.ethan/skills/ 加载技能。

首次运行时，config.py 的 _init_default_skills() 会自动将内置默认技能
从 ethan/defaults/skills/ 复制到 ~/.ethan/skills/，之后 loader 只认 ~/.ethan/skills/。
这样 agent 运行完全不依赖源码目录。

每个技能目录结构：
    ~/.ethan/skills/<name>/SKILL.md          ← 技能主文件
    ~/.ethan/skills/<name>/references/*.md   ← 参考文件（不注入 prompt）

也支持旧格式：~/.ethan/skills/<name>.md（单文件）
"""
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml

from ethan.core.config import CONFIG_DIR

# 用户技能目录（~/.ethan/skills/）
USER_SKILLS_DIR = CONFIG_DIR / "skills"


@dataclass
class Skill:
    name: str
    description: str
    trigger: list[str]
    content: str
    source: Path
    fast_path: bool = False  # True = 命中 trigger 时走 Fast Path（不受长度限制）
    channels: list[str] = field(default_factory=list)  # 空列表 = 所有渠道
    modes: list[str] = field(default_factory=list)  # 空列表 = 所有对话模式可用；非空 = 仅在这些 mode 生效
    references: list[Path] = field(default_factory=list)  # skill_dir/references/*.md
    is_default: bool = False  # 是否为打包自带的默认 Skill（vs 用户安装的）


def _default_skill_names() -> set[str]:
    """读取打包的默认 Skill 名集合（ethan/defaults/skills/ 下的目录名）。

    运行时默认 Skill 已被复制到 ~/.ethan/skills/，无法通过路径区分；
    用这个集合判断某个 Skill 是否属于默认自带。
    """
    try:
        defaults_dir = Path(__file__).parent.parent / "defaults" / "skills"
        if not defaults_dir.is_dir():
            return set()
        return {
            p.name for p in defaults_dir.iterdir()
            if p.is_dir() and (p / "SKILL.md").exists()
        }
    except Exception:
        return set()


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


def load_skill_from_file(path: Path) -> Optional[Skill]:
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
    channels_raw = meta.get("channels", [])
    channels = channels_raw if isinstance(channels_raw, list) else []
    modes_raw = meta.get("modes", [])
    if isinstance(modes_raw, str):
        modes = [m.strip() for m in modes_raw.split("|") if m.strip()]
    elif isinstance(modes_raw, list):
        modes = [str(m).strip() for m in modes_raw if str(m).strip()]
    else:
        modes = []

    return Skill(name=name, description=description, trigger=triggers,
                 content=content, source=path, fast_path=fast_path,
                 channels=channels, modes=modes)


def load_skill_from_dir(skill_dir: Path) -> Optional[Skill]:
    """从技能子目录加载 Skill（新格式：<name>/SKILL.md）。"""
    skill_md = skill_dir / "SKILL.md"
    if not skill_md.exists():
        return None
    skill = load_skill_from_file(skill_md)
    if skill:
        if not skill.name or skill.name == "SKILL":
            skill.name = skill_dir.name
        # 扫 references/*.md（仅 .md，按文件名排序保证稳定），目录不存在就空列表。
        # 不读内容——摘要留给 registry 按需生成。
        refs_dir = skill_dir / "references"
        if refs_dir.is_dir():
            skill.references = sorted(refs_dir.glob("*.md"))
    return skill


def load_all_skills(user_id: str = "") -> list[Skill]:
    """从 per-user 技能目录加载所有技能。

    user_id 非空时读 ~/.ethan/users/<uid>/skills/（per-user 隔离）；
    user_id 为空时回退到全局 ~/.ethan/skills/（兼容 CLI/REPL 等无用户场景）。
    """
    from ethan.core.paths import user_skills_dir
    skills: dict[str, Skill] = {}
    default_names = _default_skill_names()

    skills_dir = user_skills_dir()
    if skills_dir.exists():
        for entry in sorted(skills_dir.iterdir()):
            skill = None
            if entry.is_dir() and not entry.name.endswith("-references"):
                skill = load_skill_from_dir(entry)
            elif entry.suffix == ".md":
                skill = load_skill_from_file(entry)
            if skill:
                skill.is_default = skill.name in default_names
                skills[skill.name] = skill

    return list(skills.values())
