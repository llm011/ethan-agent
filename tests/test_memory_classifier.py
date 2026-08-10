"""classifier.py 单元测试：规则分类、LLM 解析容错、memory role 推断。"""
from __future__ import annotations

import asyncio

import pytest


class TestClassifyQueryIntent:
    """规则分类器基本路径：高置信 > 中置信 > unknown。"""

    @pytest.mark.parametrize(
        "query,expected",
        [
            ("我是谁", "identity"),
            ("我叫什么名字", "identity"),
            ("我的职业是什么", "identity"),
            ("最近在忙什么", "activity"),
            ("手头项目是哪个", "activity"),
            ("为什么选了 SQLite", "decision"),
            ("之前的决定是什么", "decision"),
            ("回答的时候要注意什么", "preference"),
            ("我喜欢什么格式", "preference"),
            ("上次怎么调试的", "procedure"),
            ("技术方案该怎么比较", "procedure"),
            ("我心情怎么样", "emotion"),
            ("我上次跟你说我怎么了", "emotion"),
            ("最近状态怎么样", "emotion"),
        ],
    )
    def test_high_confidence(self, query, expected):
        from ethan.memory.classifier import classify_query_intent

        assert classify_query_intent(query) == expected

    @pytest.mark.parametrize(
        "query,expected",
        [
            ("我是小明", "identity"),
            ("我叫小红", "identity"),
            ("我决定用 Rust", "decision"),
            ("最近还好吗", "emotion"),
            ("比较一下两个方案", "procedure"),
            ("我怎么了", "emotion"),
        ],
    )
    def test_medium_confidence(self, query, expected):
        from ethan.memory.classifier import classify_query_intent

        assert classify_query_intent(query) == expected

    @pytest.mark.parametrize(
        "query",
        [
            "今天天气如何",
            "帮我写段代码",
            "随便聊聊",
            "你好",
        ],
    )
    def test_unknown(self, query):
        from ethan.memory.classifier import classify_query_intent

        assert classify_query_intent(query) == "unknown"

    def test_emotion_before_procedure(self):
        """'我上次跟你说我怎么了' 同时含 '上次怎么' 和 '我怎么了'，应命中 emotion。"""
        from ethan.memory.classifier import classify_query_intent

        assert classify_query_intent("我上次跟你说我怎么了") == "emotion"


class TestParseIntent:
    """LLM 输出解析容错。"""

    @pytest.mark.parametrize(
        "text,expected",
        [
            ("identity", "identity"),
            ("identity\n", "identity"),
            ("activity。", "activity"),
            ("  decision  ", "decision"),
            # 带标点
            ("preference!", "preference"),
            # 带解释文本（但 intent 在第一行）
            ("emotion\n因为用户在问情绪", "emotion"),
        ],
    )
    def test_clean_output(self, text, expected):
        from ethan.memory.classifier import _parse_intent

        assert _parse_intent(text) == expected

    @pytest.mark.parametrize(
        "text",
        [
            "not identity",
            "This is not a decision question",
            "no, this is unknown",
            "不是identity",
        ],
    )
    def test_negation_returns_unknown(self, text):
        from ethan.memory.classifier import _parse_intent

        assert _parse_intent(text) == "unknown"

    def test_empty_returns_unknown(self):
        from ethan.memory.classifier import _parse_intent

        assert _parse_intent("") == "unknown"
        assert _parse_intent("   ") == "unknown"

    def test_garbage_returns_unknown(self):
        from ethan.memory.classifier import _parse_intent

        assert _parse_intent("I refuse to classify this.") == "unknown"


class TestInferMemoryRole:
    """dimension → memory_role 推断。"""

    @pytest.mark.parametrize(
        "dimension,expected",
        [
            ("identity.preferred_name", "identity"),
            ("identity.occupation", "identity"),
            ("activity.project", "activity"),
            ("decision.chosen", "decision"),
            ("preference.communication", "preference"),
            ("methodology.execution_strategy", "methodology"),
            ("methodology.decision_process", "methodology"),
            ("skill.tooling", "skill_experience"),
            ("relationship.agreement", "relationship"),
            ("companion.current_emotion", "task_context"),
            ("unknown_garbage", "task_context"),
            ("", "task_context"),
        ],
    )
    def test_prefix_mapping(self, dimension, expected):
        from ethan.memory.classifier import infer_memory_role

        assert infer_memory_role(dimension) == expected


class TestIntentRoleMap:
    """INTENT_ROLE_MAP 完整性：每个 intent 映射到合法 role 或 None。"""

    def test_all_intents_mapped(self):
        from ethan.memory.classifier import INTENT_ROLE_MAP, MEMORY_ROLES

        for intent, role in INTENT_ROLE_MAP.items():
            if role is not None:
                assert role in MEMORY_ROLES, f"intent={intent} maps to invalid role={role}"

    def test_unknown_maps_to_none(self):
        from ethan.memory.classifier import INTENT_ROLE_MAP

        assert INTENT_ROLE_MAP["unknown"] is None


class TestClassifyQueryIntentAsync:
    """异步入口：规则先行，LLM 兜底（默认关）。"""

    def test_sync_rule_hit_skips_llm(self, monkeypatch):
        import ethan.memory.classifier as C

        monkeypatch.setattr(C, "CLASSIFY_LLM_ENABLED", True)

        async def _boom(*a, **kw):
            raise AssertionError("规则命中时不应调 LLM")

        monkeypatch.setattr(C, "classify_query_intent_llm", _boom)
        result = asyncio.run(C.classify_query_intent_async("我是谁"))
        assert result == "identity"

    def test_unknown_without_llm_returns_unknown(self, monkeypatch):
        import ethan.memory.classifier as C

        monkeypatch.setattr(C, "CLASSIFY_LLM_ENABLED", False)
        result = asyncio.run(C.classify_query_intent_async("今天天气如何"))
        assert result == "unknown"
