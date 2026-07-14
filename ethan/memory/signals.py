"""记忆信号检测器 — 规则驱动，不依赖 LLM 自主判断。

借鉴 Palantir Context Layer 的"确定性与概率性分离"：
记忆的写入触发由系统规则确定性保证，LLM 只在"记什么内容"上做概率性判断。

规则命中时返回 (memory_category, hint) — hint 注入 system prompt 提醒 LLM 调 memory_write。
"""
from __future__ import annotations

import re

# 确定性规则：命中即触发，不靠 LLM 自觉
# 每条规则：(category, patterns, hint)
# patterns 用子串匹配（对 CJK 友好），不分大小写
_MEMORY_SIGNALS: list[tuple[str, list[str], str]] = [
    (
        "preference",
        [
            "喜欢", "偏好", "prefer", "always", "never", "习惯",
            "不要用", "不要这样", "改成", "换成", "以后都",
            "i prefer", "i like", "i always", "i never",
        ],
        "用户刚才的话里包含偏好/习惯信号，如果值得跨对话记住，请调 memory_write(category=\"preference\")。",
    ),
    (
        "decision",
        [
            "决定", "选择", "打算", "准备", "计划", "plan to",
            "going to", "decided", "i'll", "我打算", "我准备",
        ],
        "用户刚才的话里包含决定/计划信号，如果是跨对话有效的决定，请调 memory_write(category=\"decision\")。",
    ),
    (
        "fact",
        [
            "我叫", "我在做", "我的工作", "我的名字", "我住在",
            "i am a", "i work", "my name", "i'm from", "i live in",
        ],
        "用户刚才的话里包含个人事实信号，如果是值得记住的个人信息，请调 memory_write(category=\"knowledge\")。",
    ),
    (
        "correction",
        [
            "不对", "错了", "不是这样", "应该是", "不要这样",
            "wrong", "not like that", "should be", "i said",
        ],
        "用户刚才纠正了你。请调 procedure_write 把这条行为准则记下来，避免下次再犯。",
    ),
]


def detect_memory_signal(text: str) -> tuple[str, str] | None:
    """检测用户消息里的记忆信号。

    返回 (category, hint) 或 None。多条命中时按 preference > correction > decision > fact 优先级返回。
    """
    if not text or not text.strip():
        return None
    text_lower = text.lower()

    # 按优先级排序：偏好和纠正最重要，决定其次，事实最后
    priority_order = ["preference", "correction", "decision", "fact"]
    for cat in priority_order:
        for category, patterns, hint in _MEMORY_SIGNALS:
            if category != cat:
                continue
            for pat in patterns:
                if pat.lower() in text_lower:
                    return (category, hint)
    return None


def extract_keywords(text: str, max_keywords: int = 8) -> list[str]:
    """从文本中提取关键词（用于 fact tags 和 episodic 召回）。

    策略：
    1. CJK：按 2-4 字滑窗提取（对中文友好，不依赖分词库）
    2. Latin：按空格/标点分词，过滤停用词和短词
    """
    if not text or not text.strip():
        return []

    keywords: list[str] = []
    seen: set[str] = set()

    # Latin 分词
    latin_words = re.findall(r"[a-zA-Z]{3,}", text.lower())
    _stopwords = {
        "the", "and", "for", "are", "but", "not", "you", "all", "can", "had",
        "her", "was", "one", "our", "out", "has", "have", "from", "this", "that",
        "with", "your", "they", "will", "what", "about", "which", "when", "make",
        "like", "into", "them", "some", "than", "then", "been", "want", "just",
        "over", "such", "here", "there", "where", "would", "could", "should",
    }
    for w in latin_words:
        if w not in _stopwords and w not in seen:
            keywords.append(w)
            seen.add(w)
        if len(keywords) >= max_keywords:
            return keywords

    # CJK 滑窗：提取 2-4 字的 CJK 子串（跳过含停用字的 bigram）
    cjk_chunks = re.findall(r"[\u4e00-\u9fff]{2,}", text)
    _cjk_stop_chars = {"的", "了", "是", "在", "我", "你", "他", "她", "它", "们", "和", "与", "或", "也", "都", "就", "这", "那", "有", "不", "没", "对", "错"}
    for chunk in cjk_chunks:
        # 2-字滑窗：两个字都不是停用字才保留
        for i in range(len(chunk) - 1):
            piece = chunk[i:i + 2]
            if piece[0] in _cjk_stop_chars or piece[1] in _cjk_stop_chars:
                continue
            if piece not in seen:
                keywords.append(piece)
                seen.add(piece)
            if len(keywords) >= max_keywords:
                return keywords
        # 如果 chunk 较长，也取 3-4 字片段
        if len(chunk) >= 4:
            for length in (3, 4):
                for i in range(len(chunk) - length + 1):
                    piece = chunk[i:i + length]
                    if piece not in seen:
                        keywords.append(piece)
                        seen.add(piece)
                    if len(keywords) >= max_keywords:
                        return keywords

    return keywords


def score_relevance(query_keywords: list[str], tags: list[str]) -> float:
    """计算查询关键词与 fact tags 的相关性分数（0.0-1.0）。

    用于 fact 召回时排序：有 tag 交集的 fact 优先于纯 confidence 排序。
    """
    if not query_keywords or not tags:
        return 0.0
    qset = {k.lower() for k in query_keywords}
    tset = {t.lower() for t in tags}
    overlap = len(qset & tset)
    return min(overlap / max(len(qset), 1), 1.0)
