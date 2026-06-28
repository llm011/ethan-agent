"""对话模式（mode）注册表 —— 通用的 persona-mode 机制。

一个「mode」= 一个命名的人格/工作态。它声明：
  - 触发别名（前端/渠道传来的 mode 字符串）
  - UI 展示用的 label / icon
  - persona 正文来自哪个 skill（按目录名查找，找不到则不注入）
  - 该模式是否需要记忆抽取时额外抽心理画像（extract_psych）
  - 该模式依赖的技能（requires_skill）及缺失时的安装来源（install_source）

内核（agent / consolidator）只认这张表，不认任何具体人格。
新增一个垂类模式 = 往 MODES 里加一条数据，无需改动 agent.py / consolidator.py。
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Mode:
    key: str                          # 规范名（持久化/比较用）
    aliases: tuple[str, ...]          # 可解析为该模式的别名（含 key 本身）
    label: str = ""                   # UI 展示名
    icon: str = ""                    # UI 展示图标
    accent: str = "neutral"           # UI 主题色键（前端映射到 Tailwind 类，未知回退 neutral）
    persona_skills: tuple[str, ...] = ()  # persona 正文候选 skill 目录名，按序查找首个命中
    extract_psych: bool = False       # 记忆抽取时是否额外抽心理画像
    blurb: str = ""                   # 进入该模式时 UI 旁的一句话提示
    requires_skill: str = ""          # 该模式依赖的技能目录名；未安装时引导安装
    install_source: str = ""          # requires_skill 缺失时 install_skill 的来源（owner/repo/子目录）


# 唯一真相源：所有内置对话模式。
MODES: tuple[Mode, ...] = (
    Mode(
        key="陪伴",
        aliases=("陪伴", "counselor", "苏念"),
        label="苏念 · 陪伴倾听",
        icon="🌸",
        accent="pink",
        persona_skills=("companion-listen", "陪伴倾听"),
        extract_psych=True,
        blurb="正在以苏念的身份陪伴你，倾诉心事我会先看见你、接住你",
    ),
    Mode(
        key="法律",
        aliases=("法律", "legal", "法律专家", "法务"),
        label="法律专家",
        icon="⚖️",
        accent="blue",
        requires_skill="legal-assistant",
        install_source="llm011/ethan-legal-skill/skills/legal-assistant",
        blurb="已进入法律专家模式：可做案件研判、诉讼分析、合同审查、知产与法律文书",
    ),
)

# 默认（工作助手）模式：mode 为空或无法解析时回退到它。
DEFAULT_MODE = Mode(key="", aliases=("",), label="工作助手", icon="🛠️", accent="neutral")

_ALIAS_INDEX: dict[str, Mode] = {
    alias: m for m in MODES for alias in m.aliases
}


_ALIAS_INDEX_LOWER: dict[str, Mode] = {
    alias.lower(): m for m in MODES for alias in m.aliases
}


def resolve_mode(mode: str | None) -> Mode:
    """把任意 mode 字符串解析为 Mode；无法解析时返回 DEFAULT_MODE。

    用于运行时把已持久化的 mode 字符串还原成 Mode（容错优先）。
    """
    if not mode:
        return DEFAULT_MODE
    return _ALIAS_INDEX.get(mode.strip(), DEFAULT_MODE)


def match_mode(mode: str | None) -> Mode | None:
    """严格解析用户 /mode 切换意图：

    - 空字符串 / "default" / "默认" → DEFAULT_MODE（切回默认工作助手）
    - 命中某模式别名（大小写不敏感）→ 对应 Mode
    - 其它无法识别 → None（调用方据此「保持当前 mode 不变」）

    与 resolve_mode 的区别：未知输入不回退到默认，而是返回 None，
    避免用户拼错模式名时被意外切回默认。
    """
    if mode is None:
        return DEFAULT_MODE
    key = mode.strip()
    if not key or key.lower() in ("default", "默认"):
        return DEFAULT_MODE
    return _ALIAS_INDEX.get(key) or _ALIAS_INDEX_LOWER.get(key.lower())
