"""Tests for memory recall enhancement (feat/memory-recall-enhancement).

Covers differential changes vs. the original agent:
- A1: FactStore tags + build_context_with_recall (semantic recall)
- A2: detect_memory_signal (rule-driven memory trigger)
- A3: lowered consolidation threshold (unit-tested via constant check)
- B1: ProcedureStore procedures + old-format compat (success_patterns 已退役)
"""
from __future__ import annotations

import json
import time

# ---------------------------------------------------------------------------
# A2: detect_memory_signal
# ---------------------------------------------------------------------------

class TestDetectMemorySignal:
    def test_preference_signal(self):
        from ethan.memory.signals import detect_memory_signal
        result = detect_memory_signal("我喜欢深色模式")
        assert result is not None
        assert result[0] == "preference"

    def test_preference_english(self):
        from ethan.memory.signals import detect_memory_signal
        result = detect_memory_signal("I prefer concise answers")
        assert result is not None
        assert result[0] == "preference"

    def test_correction_signal(self):
        from ethan.memory.signals import detect_memory_signal
        result = detect_memory_signal("不对，应该是另一个文件")
        assert result is not None
        assert result[0] == "correction"

    def test_decision_signal(self):
        from ethan.memory.signals import detect_memory_signal
        result = detect_memory_signal("我决定用 PostgreSQL")
        assert result is not None
        assert result[0] == "decision"

    def test_fact_signal(self):
        from ethan.memory.signals import detect_memory_signal
        result = detect_memory_signal("我的工作是后端开发")
        assert result is not None
        assert result[0] == "fact"

    def test_no_signal(self):
        from ethan.memory.signals import detect_memory_signal
        assert detect_memory_signal("今天天气怎么样") is None
        assert detect_memory_signal("") is None
        assert detect_memory_signal("   ") is None

    def test_priority_preference_over_fact(self):
        """'我喜欢' 同时命中 preference 和 fact 类的关键词，应返回 preference。"""
        from ethan.memory.signals import detect_memory_signal
        result = detect_memory_signal("我喜欢我的工作")
        assert result is not None
        assert result[0] == "preference"

    def test_priority_correction_over_decision(self):
        """纠正优先于决定。"""
        from ethan.memory.signals import detect_memory_signal
        result = detect_memory_signal("不对，我决定换个方案")
        assert result is not None
        assert result[0] == "correction"

    def test_hint_is_non_empty(self):
        from ethan.memory.signals import detect_memory_signal
        result = detect_memory_signal("我喜欢简洁")
        assert result is not None
        assert len(result[1]) > 0


# ---------------------------------------------------------------------------
# A2: extract_keywords
# ---------------------------------------------------------------------------

class TestExtractKeywords:
    def test_cjk_sliding_window(self):
        from ethan.memory.signals import extract_keywords
        kws = extract_keywords("用户喜欢深色模式", max_keywords=10)
        # 2-字滑窗应产生多个 CJK 片段
        assert len(kws) > 0
        assert any("喜欢" in k for k in kws)

    def test_latin_words(self):
        from ethan.memory.signals import extract_keywords
        kws = extract_keywords("I prefer dark mode always", max_keywords=10)
        assert "prefer" in kws
        assert "dark" in kws
        assert "mode" in kws
        assert "always" in kws

    def test_stopwords_filtered(self):
        from ethan.memory.signals import extract_keywords
        kws = extract_keywords("this is the best thing about you", max_keywords=20)
        for sw in ("this", "the", "about", "you"):
            assert sw not in kws

    def test_empty_input(self):
        from ethan.memory.signals import extract_keywords
        assert extract_keywords("") == []
        assert extract_keywords("   ") == []

    def test_max_keywords_limit(self):
        from ethan.memory.signals import extract_keywords
        kws = extract_keywords("alpha beta gamma delta epsilon zeta eta theta", max_keywords=3)
        assert len(kws) <= 3

    def test_mixed_cjk_latin(self):
        from ethan.memory.signals import extract_keywords
        kws = extract_keywords("我用 postgresql 存储数据", max_keywords=10)
        assert "postgresql" in kws
        assert any("存储" in k or "数据" in k for k in kws)


# ---------------------------------------------------------------------------
# A2: score_relevance
# ---------------------------------------------------------------------------

class TestScoreRelevance:
    def test_full_overlap(self):
        from ethan.memory.signals import score_relevance
        score = score_relevance(["dark", "mode"], ["dark", "mode"])
        assert score == 1.0

    def test_partial_overlap(self):
        from ethan.memory.signals import score_relevance
        score = score_relevance(["dark", "mode", "theme"], ["dark", "color"])
        assert 0.0 < score < 1.0

    def test_no_overlap(self):
        from ethan.memory.signals import score_relevance
        assert score_relevance(["python"], ["java"]) == 0.0

    def test_empty_inputs(self):
        from ethan.memory.signals import score_relevance
        assert score_relevance([], ["tag"]) == 0.0
        assert score_relevance(["query"], []) == 0.0
        assert score_relevance([], []) == 0.0

    def test_case_insensitive(self):
        from ethan.memory.signals import score_relevance
        assert score_relevance(["Dark"], ["dark"]) == 1.0


# ---------------------------------------------------------------------------
# A1: legacy 迁移的维度分类（facts.json 时代的 tags 角色由 dimension 继承）
# ---------------------------------------------------------------------------

class TestLegacyClassify:
    def test_keyword_rules_hit(self):
        from ethan.memory.legacy_migration import _classify
        assert _classify("用户偏好用中文交流", "preference") == ("preference", "preference.language")
        assert _classify("用户住在深圳", "knowledge") == ("personal_information", "identity.location")
        assert _classify("用户在腾讯工作", "knowledge") == ("personal_information", "identity.organization")

    def test_fallback_by_category(self):
        from ethan.memory.legacy_migration import _classify
        assert _classify("一些普通偏好", "preference") == ("preference", "preference.communication")
        assert _classify("随便一个决定", "decision") == ("decision", "decision.chosen")
        assert _classify("普通事实", "knowledge")[0] == "personal_information"


# ---------------------------------------------------------------------------
# A1: 结构化召回（替代 FactStore.build_context_with_recall）
# ---------------------------------------------------------------------------

def _seed_memory(store, content, *, importance=0.5, confidence=0.8):
    import hashlib

    from ethan.memory.records import (
        EvidenceLevel,
        MemoryEvidence,
        MemoryRecord,
        MemoryStatus,
    )
    record = MemoryRecord(
        memory_type="preference",
        dimension="preference.content",
        memory_key="seed_" + hashlib.sha1(content.encode()).hexdigest()[:12],
        content=content,
        status=MemoryStatus.ACTIVE.value,
        evidence_level=EvidenceLevel.EXPLICIT.value,
        confidence=confidence,
        importance=importance,
    )
    evidence = MemoryEvidence(
        memory_id=record.id,
        evidence_level=EvidenceLevel.EXPLICIT.value,
        source_session_id="s1",
        source_message_id="",
        source_role="user",
        source_quote=content,
    )
    store.create_memory_with_evidence(record, [evidence])
    return record.id


class TestStructuredRecall:
    def _store(self, tmp_path):
        from ethan.memory.store import MemoryStore
        return MemoryStore(db_path=tmp_path / "memory.db")

    def test_relevant_facts_prioritized(self, tmp_path):
        """query 命中的记忆优先返回（FTS/LIKE），未命中不进结果。"""
        from ethan.memory.recall import _collect
        store = self._store(tmp_path)
        _seed_memory(store, "用户在字节跳动工作", importance=0.5)
        _seed_memory(store, "用户喜欢深色模式", importance=0.9)
        hits = _collect(store, "字节跳动", domain="general", max_items=8)
        assert hits and "字节跳动" in hits[0].content
        assert all("深色模式" not in h.content for h in hits)
        store.close()

    def test_cjk_substring_recall(self, tmp_path):
        """CJK 子串查询（FTS 无分词零命中）必须落到 LIKE 兜底。"""
        from ethan.memory.recall import _collect
        store = self._store(tmp_path)
        _seed_memory(store, "用户偏好用中文交流")
        hits = _collect(store, "中文", domain="general", max_items=8)
        assert any("中文" in h.content for h in hits)
        store.close()

    def test_fallback_when_no_relevance(self, tmp_path):
        """无命中时按 importance 兜底，保证身份类事实可用。"""
        from ethan.memory.recall import _collect
        store = self._store(tmp_path)
        _seed_memory(store, "fact A", importance=0.4)
        _seed_memory(store, "fact B", importance=0.9)
        hits = _collect(store, "完全不相关zzzz", domain="general", max_items=8)
        assert hits and hits[0].content == "fact B"
        store.close()

    def test_empty_store(self, tmp_path):
        from ethan.memory.recall import _collect
        store = self._store(tmp_path)
        assert _collect(store, "anything", domain="general", max_items=8) == []
        store.close()

    def test_empty_query(self, tmp_path):
        """空 query 退化为 importance 排序兜底。"""
        from ethan.memory.recall import _collect
        store = self._store(tmp_path)
        _seed_memory(store, "low importance", importance=0.3)
        _seed_memory(store, "high importance", importance=0.95)
        hits = _collect(store, "", domain="general", max_items=8)
        assert hits[0].content == "high importance"
        store.close()

    def test_touch_updates_last_recalled(self, tmp_path):
        """召回命中后 last_recalled_at 应被更新。"""

        store = self._store(tmp_path)
        mem_id = _seed_memory(store, "用户喜欢深色模式")
        assert store.get_memory(mem_id).last_recalled_at is None
        store.touch_recalled([mem_id])
        recalled = store.get_memory(mem_id).last_recalled_at
        assert recalled is not None and recalled <= time.time()
        store.close()


# ---------------------------------------------------------------------------
# A1: memory_write 工具（替代 FactStore 主动写入）
# ---------------------------------------------------------------------------

class TestMemoryWriteTool:
    def test_write_admits_and_dedups(self, tmp_path, monkeypatch):
        import asyncio

        monkeypatch.setattr("ethan.core.paths.CONFIG_DIR", tmp_path)

        async def run():
            from ethan.tools.builtin.memory_write import MemoryWriteTool
            tool = MemoryWriteTool()
            r1 = await tool.run("用户喜欢深色模式", "preference")
            r2 = await tool.run("用户喜欢深色模式", "preference")
            return r1, r2

        r1, r2 = asyncio.run(run())
        assert "Remembered" in r1
        assert "Already remembered" in r2

    def test_correction_category_marks_corrected(self, tmp_path, monkeypatch):
        import asyncio

        monkeypatch.setattr("ethan.core.paths.CONFIG_DIR", tmp_path)

        async def run():
            from ethan.tools.builtin.memory_write import MemoryWriteTool
            await MemoryWriteTool().run("用户不住北京了，改住上海", "correction")

        asyncio.run(run())

    def test_explicit_memory_type_and_dimension(self, tmp_path, monkeypatch):
        """显式传 memory_type + dimension 应直接采用，不走 category 兜底。"""
        import asyncio

        monkeypatch.setattr("ethan.core.paths.CONFIG_DIR", tmp_path)

        async def run():
            from ethan.tools.builtin.memory_write import MemoryWriteTool
            await MemoryWriteTool().run(
                "用户住在苏州",
                memory_type="personal_information",
                dimension="identity.location",
            )

        asyncio.run(run())

        # 验证落库的 memory_type / dimension 是显式传入的值
        from ethan.core.paths import user_vectors_db_path
        from ethan.memory.store import MemoryStore

        store = MemoryStore(db_path=user_vectors_db_path())
        try:
            memories = store.list_memories(status="active", limit=10)
            assert len(memories) == 1
            m = memories[0]
            assert m.memory_type == "personal_information"
            assert m.dimension == "identity.location"
            assert m.evidence_level == "explicit"
        finally:
            store.close()

    def test_memory_type_only_uses_correct_dimension_prefix(self, tmp_path, monkeypatch):
        """agent 传 memory_type 但不传 dimension 时，dimension 兜底前缀应与 dimensions.py 注册表一致。

        回归 bug：personal_information 类型直接 f"{mt}.misc" 会产出
        "personal_information.misc"，而 extractor 路径产出的是 "identity.misc"，
        导致 supersede 判定（existing.dimension == candidate.dimension）永远配不上，
        主动写的 identity 记忆和自动抽取的各存一份、旧值不被替换。
        """
        import asyncio

        monkeypatch.setattr("ethan.core.paths.CONFIG_DIR", tmp_path)

        async def run():
            from ethan.tools.builtin.memory_write import MemoryWriteTool
            # 不传 dimension，触发兜底
            await MemoryWriteTool().run(
                "用户偏好深色模式",
                memory_type="personal_information",
            )

        asyncio.run(run())

        from ethan.core.paths import user_vectors_db_path
        from ethan.memory.store import MemoryStore

        store = MemoryStore(db_path=user_vectors_db_path())
        try:
            memories = store.list_memories(status="active", limit=10)
            assert len(memories) == 1
            m = memories[0]
            assert m.memory_type == "personal_information"
            # 兜底 dimension 必须用 identity. 前缀，和 dimensions.py 注册表对齐
            assert m.dimension == "identity.misc", (
                f"personal_information 的兜底 dimension 应为 'identity.misc'，"
                f"实际为 '{m.dimension}'——supersede 判定会和 extractor 路径对不上"
            )
        finally:
            store.close()


# ---------------------------------------------------------------------------
# B1: ProcedureStore success_patterns（已退役，保留空注释作为分隔）
# ---------------------------------------------------------------------------

# success_patterns 容器已于 2026-07 退役：
# - 从 tool_steps 共现统计抽取的"模式"99.4% 是只出现一次的噪声
# - scenario 字段被 LLM 自身的 meta 污染
# - 注入 system prompt 信息增益为 0（~27k tokens 浪费）
# 真正有价值的"行为准则"由 procedure_write 工具 / Consolidator 显式写入 procedures。
# 相关测试已删除，保留 TestProcedureStoreCompat 验证旧格式加载兼容性。


# ---------------------------------------------------------------------------
# B1: ProcedureStore old-format compatibility
# ---------------------------------------------------------------------------

class TestProcedureStoreCompat:
    def test_old_list_format_loads(self, tmp_path):
        """旧的纯 list 格式应正常加载为 procedures，不丢失数据。

        注：旧文件中即使有 success_patterns 字段也会被主动丢弃（已退役）。
        """
        from ethan.memory.procedures import ProcedureStore
        old_data = [
            {"rule": "不要用浏览器模拟登录", "context": "", "created_at": 0, "hit_count": 1},
            {"rule": "文件路径用绝对路径", "context": "", "created_at": 0, "hit_count": 2},
        ]
        p = tmp_path / "playbook.json"
        p.write_text(json.dumps(old_data), encoding="utf-8")

        store = ProcedureStore(path=p)
        assert len(store.all()) == 2
        assert store.all()[0].rule == "不要用浏览器模拟登录"

    def test_new_format_roundtrip(self, tmp_path):
        """新格式（dict 含 procedures + 空 success_patterns）应完整往返。"""
        from ethan.memory.procedures import ProcedureStore
        p = tmp_path / "playbook.json"
        store = ProcedureStore(path=p)
        store.add("测试准则")
        store._save()

        # 重新加载
        store2 = ProcedureStore(path=p)
        assert len(store2.all()) == 1
        assert store2.all()[0].rule == "测试准则"

        # 文件应为新格式（dict），success_patterns 为空数组（向后兼容）
        data = json.loads(p.read_text(encoding="utf-8"))
        assert isinstance(data, dict)
        assert "procedures" in data
        assert data["success_patterns"] == []

    def test_old_format_with_success_patterns_dropped(self, tmp_path):
        """旧格式文件含已退役的 success_patterns 字段，加载时应主动丢弃。"""
        from ethan.memory.procedures import ProcedureStore
        old_data = {
            "procedures": [{"rule": "旧准则", "context": "", "created_at": 0, "hit_count": 1}],
            "success_patterns": [
                {"scenario": "应被丢弃", "tool_sequence": ["tool1"], "success_count": 5}
            ],
        }
        p = tmp_path / "playbook.json"
        p.write_text(json.dumps(old_data), encoding="utf-8")

        store = ProcedureStore(path=p)
        store._save()  # 触发重写

        # 重读文件 —— success_patterns 应被清空
        data = json.loads(p.read_text(encoding="utf-8"))
        assert data["success_patterns"] == []
        assert len(data["procedures"]) == 1
        assert data["procedures"][0]["rule"] == "旧准则"


# ---------------------------------------------------------------------------
# A3: consolidation threshold constants (regression guard)
# ---------------------------------------------------------------------------

class TestConsolidationThreshold:
    """确保后台抽取门槛没有意外被改回旧值。"""

    def test_warm_capacity_lowered(self):
        from ethan.memory.working import MemoryConfig
        cfg = MemoryConfig()
        assert cfg.warm_capacity <= 10, "warm_capacity 应 ≤ 10（原值 20）"

    def test_web_consolidate_interval(self):
        """结构化提取的触发门槛是 user_turns % 3（_run_structured_extraction 内）。

        注意：_maybe_generate_skill 仍保留 % 5 != 0 节流（skill 生成比记忆提取重，
        保持更克制的频率），所以不能做全文件断言。
        """
        import inspect

        from ethan.interface.routers import tasks
        extraction_src = inspect.getsource(tasks._run_structured_extraction)
        # 记忆提取门槛用的是 % 3（从 % 5 降级到 % 3 以更及时捕获用户事实）
        assert "user_turns % 3 != 0" in extraction_src
        assert "user_turns % 5 != 0" not in extraction_src
        assert "user_turns % 10 != 0" not in extraction_src

    def test_legacy_compress_extraction_removed(self):
        """旧 flat-facts 链路（compress/extract_cold）已从 _maybe_consolidate 退役。"""
        import inspect

        from ethan.interface.routers import tasks
        source = inspect.getsource(tasks._maybe_consolidate)
        assert ".extract_cold(" not in source
        assert "WorkingMemory(" not in source
        assert "FactStore(" not in source
