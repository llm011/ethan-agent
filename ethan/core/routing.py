import re

from ethan.core.config import get_config

# 强制走完整 Loop 的信号（不可配置，优先级最高）
_FORCE_FULL_SIGNALS = [
    "帮我写", "写一个", "写代码", "实现", "分析", "解释",
    "总结", "生成", "创建", "建立", "搭建",
    "重构", "优化代码", "调试", "debug", "修复", "定时任务",
    "提醒我", "设置一个", "schedule", "reminder",
    "write", "implement", "analyze", "explain", "generate", "create",
    "refactor", "summarize",
]


def _match_keyword(kw: str, text: str) -> bool:
    """关键词匹配，支持通配符 *。"""
    if "*" in kw:
        pattern = re.compile(kw.replace("*", ".*"))
        return bool(pattern.search(text))
    return kw in text


def _match_fast_rule(text: str, routing=None):
    """返回命中的 FastRule（按 fast_rules 顺序取第一条命中的），无命中返回 None。

    规则的任一关键字（支持 * 通配）出现在 text 中即命中。纯关键字驱动，不看字数。
    """
    if routing is None:
        routing = get_config().defaults.routing
    for rule in routing.fast_rules:
        for kw in rule.keywords:
            if _match_keyword(kw, text):
                return rule
    return None


def _get_route(text: str, skill_triggers: list[str] | None = None) -> str:
    """
    返回路由档位：'fast' | 'medium' | 'full'

    规则（按优先级）：
    1. 有 FORCE_FULL 信号 → full（最高优先）
    2. 命中 fast_path Skill 的 trigger 关键词 → fast
    3. 命中任一 fast_rule 的关键字 → fast（纯关键字驱动，不看字数，避免字数误杀）
    4. 长度 ≤ medium_max_length → medium
    5. 其余 → full
    """
    lower = text.lower()

    if any(sig in lower for sig in _FORCE_FULL_SIGNALS):
        return "full"

    routing = get_config().defaults.routing

    if skill_triggers:
        for kw in skill_triggers:
            if _match_keyword(kw, text):
                return "fast"

    if _match_fast_rule(text, routing) is not None:
        return "fast"

    if len(text.strip()) <= routing.medium_max_length:
        return "medium"

    return "full"
