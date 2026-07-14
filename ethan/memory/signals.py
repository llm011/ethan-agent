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


def extract_keywords(text: str, max_keywords: int = 6) -> list[str]:
    """从文本中提取关键词 — 简易 fallback（LLM 不可用时兜底）。

    策略：按标点/空格切分，保留有意义的片段。
    对 CJK 只做粗粒度切分（按标点断句后整段保留），不做无意义滑窗。
    """
    if not text or not text.strip():
        return []

    keywords: list[str] = []
    seen: set[str] = set()

    # 按标点/空格切分
    segments = re.split(r"[,，。！？!?\s;；：:、\n]+", text.strip())

    _stopwords = {
        "the", "and", "for", "are", "but", "not", "you", "all", "can", "had",
        "her", "was", "one", "our", "out", "has", "have", "from", "this", "that",
        "with", "your", "they", "will", "what", "about", "which", "when", "make",
        "like", "into", "them", "some", "than", "then", "been", "want", "just",
        "over", "such", "here", "there", "where", "would", "could", "should",
    }
    _cjk_stop_words = {"我", "你", "他", "她", "们", "的", "了", "是", "在", "也", "都", "就", "这", "那", "有", "不", "没"}

    for seg in segments:
        seg = seg.strip()
        if not seg or len(seg) < 2:
            continue
        # 去掉纯停用词片段
        low = seg.lower()
        if low in _stopwords:
            continue
        # CJK 片段：去掉首尾停用字
        if re.search(r"[\u4e00-\u9fff]", seg):
            cleaned = seg
            while cleaned and cleaned[0] in _cjk_stop_words:
                cleaned = cleaned[1:]
            while cleaned and cleaned[-1] in _cjk_stop_words:
                cleaned = cleaned[:-1]
            if len(cleaned) >= 2 and cleaned not in seen:
                keywords.append(cleaned)
                seen.add(cleaned)
        else:
            # Latin: 按空格分词过滤
            words = [w for w in low.split() if w not in _stopwords and len(w) >= 3]
            for w in words:
                if w not in seen:
                    keywords.append(w)
                    seen.add(w)
        if len(keywords) >= max_keywords:
            break

    return keywords[:max_keywords]


async def extract_keywords_llm(text: str, max_keywords: int = 6) -> list[str]:
    """用 lite 模型提取关键词 — 质量远优于规则切分。

    失败时 fallback 到 extract_keywords()。
    """
    if not text or not text.strip():
        return []

    try:
        from ethan.memory.consolidator import get_lite_model
        from ethan.providers.base import Message
        from ethan.providers.manager import create_provider

        model = get_lite_model()
        provider = create_provider(model)

        prompt = (
            f"从以下文本中提取 3-{max_keywords} 个关键词/短语，用于语义检索。\n"
            "要求：\n"
            "- 每个关键词 2-6 字，是有独立语义的词或短语\n"
            "- 不要拆成单字或无意义的字符组合\n"
            "- 用逗号分隔，只输出关键词列表，不要其他内容\n\n"
            f"文本：{text}"
        )

        resp = await provider.chat(
            [Message(role="user", content=prompt)],
            system="你是关键词提取工具。只输出逗号分隔的关键词列表。",
        )

        raw = resp.content.strip().strip("。.，,")
        # 解析逗号分隔的结果
        tags = [t.strip() for t in re.split(r"[,，、\n]+", raw) if t.strip()]
        # 过滤太短或太长的
        tags = [t for t in tags if 2 <= len(t) <= 20]
        return tags[:max_keywords]

    except Exception:
        return extract_keywords(text, max_keywords)


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
