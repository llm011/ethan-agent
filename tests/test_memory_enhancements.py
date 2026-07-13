"""Tests for memory recall enhancement (feat/memory-recall-enhancement).

Covers differential changes vs. the original agent:
- A1: FactStore tags + build_context_with_recall (semantic recall)
- A2: detect_memory_signal (rule-driven memory trigger)
- A3: lowered consolidation threshold (unit-tested via constant check)
- B1: ProcedureStore success_patterns + old-format compat
- B2: _build_suggestion_hint (FDE proactive suggestion injection)
"""
from __future__ import annotations

import json
import time
from unittest.mock import patch

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
        result = detect_memory_signal("我在字节跳动工作")
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
# A1: FactStore tags auto-extraction
# ---------------------------------------------------------------------------

class TestFactStoreTags:
    def test_auto_extract_tags_on_add(self, tmp_path):
        from ethan.memory.facts import FactStore
        store = FactStore(path=tmp_path / "facts.json")
        store.add("用户喜欢深色模式", confidence=0.9)
        assert len(store._facts) == 1
        # tags 应自动提取，非空
        assert len(store._facts[0].tags) > 0

    def test_explicit_tags_preserved(self, tmp_path):
        from ethan.memory.facts import FactStore
        store = FactStore(path=tmp_path / "facts.json")
        store.add("custom fact", tags=["manual_tag", "explicit"])
        assert "manual_tag" in store._facts[0].tags
        assert "explicit" in store._facts[0].tags

    def test_tags_merged_on_similar(self, tmp_path):
        from ethan.memory.facts import FactStore
        store = FactStore(path=tmp_path / "facts.json")
        store.add("用户喜欢深色模式", tags=["dark"])
        # 再次添加相似内容（会命中 _find_similar）
        store.add("用户喜欢深色模式", tags=["theme"])
        assert len(store._facts) == 1
        assert "dark" in store._facts[0].tags
        assert "theme" in store._facts[0].tags


# ---------------------------------------------------------------------------
# A1: FactStore.build_context_with_recall
# ---------------------------------------------------------------------------

class TestBuildContextWithRecall:
    def test_relevant_facts_prioritized(self, tmp_path):
        """有 tag 交集的 fact 应排在无交集的之前。"""
        from ethan.memory.facts import FactStore
        store = FactStore(path=tmp_path / "facts.json")
        store.add("用户在字节跳动工作", tags=["字节", "跳动", "工作"])
        store.add("用户喜欢深色模式", tags=["深色", "模式", "喜欢"])

        ctx = store.build_context_with_recall(query="字节跳动", max_facts=5)
        lines = ctx.strip().split("\n")
        # "字节跳动工作" 应排在 "深色模式" 前面
        assert lines[0] == "- 用户在字节跳动工作"

    def test_fallback_when_no_relevance(self, tmp_path):
        """无任何相关 fact 时，按 confidence 降序补齐。"""
        from ethan.memory.facts import FactStore
        store = FactStore(path=tmp_path / "facts.json")
        store.add("fact A", confidence=0.5, tags=["aaa"])
        store.add("fact B", confidence=0.9, tags=["bbb"])

        ctx = store.build_context_with_recall(query="完全不相关", max_facts=5)
        lines = ctx.strip().split("\n")
        # confidence 高的排前面
        assert lines[0] == "- fact B"

    def test_empty_store(self, tmp_path):
        from ethan.memory.facts import FactStore
        store = FactStore(path=tmp_path / "facts.json")
        assert store.build_context_with_recall(query="anything") == ""

    def test_empty_query(self, tmp_path):
        """空 query 时退化为 confidence 排序（与原 build_context 一致）。"""
        from ethan.memory.facts import FactStore
        store = FactStore(path=tmp_path / "facts.json")
        store.add("low confidence fact", confidence=0.3)
        store.add("high confidence fact", confidence=0.95)
        ctx = store.build_context_with_recall(query="", max_facts=5)
        lines = ctx.strip().split("\n")
        assert lines[0] == "- high confidence fact"

    def test_touch_updates_last_accessed(self, tmp_path):
        """命中的 fact 的 last_accessed 应被更新。"""
        from ethan.memory.facts import FactStore
        store = FactStore(path=tmp_path / "facts.json")
        store.add("用户喜欢深色模式", tags=["深色", "模式"])
        old_accessed = store._facts[0].last_accessed
        time.sleep(0.01)
        store.build_context_with_recall(query="深色模式", max_facts=5)
        assert store._facts[0].last_accessed > old_accessed


# ---------------------------------------------------------------------------
# B1: ProcedureStore success_patterns
# ---------------------------------------------------------------------------

class TestSuccessPatterns:
    def test_add_new_pattern(self, tmp_path):
        from ethan.memory.procedures import ProcedureStore
        store = ProcedureStore(path=tmp_path / "procedures.json")
        store.add_success_pattern("查京东订单", ["shell:jd_query", "file_write:save"])
        patterns = store.all_success_patterns()
        assert len(patterns) == 1
        assert patterns[0].scenario == "查京东订单"
        assert patterns[0].success_count == 1
        assert "shell:jd_query" in patterns[0].tool_sequence

    def test_merge_same_scenario(self, tmp_path):
        """相同 scenario 的 pattern 应合并，count 累加。"""
        from ethan.memory.procedures import ProcedureStore
        store = ProcedureStore(path=tmp_path / "procedures.json")
        store.add_success_pattern("查京东订单", ["shell:jd_query"])
        store.add_success_pattern("查京东订单", ["file_write:save"])
        patterns = store.all_success_patterns()
        assert len(patterns) == 1
        assert patterns[0].success_count == 2
        # 两个 tool 都应保留
        assert "shell:jd_query" in patterns[0].tool_sequence
        assert "file_write:save" in patterns[0].tool_sequence

    def test_different_scenarios_separate(self, tmp_path):
        from ethan.memory.procedures import ProcedureStore
        store = ProcedureStore(path=tmp_path / "procedures.json")
        store.add_success_pattern("查京东订单", ["shell:jd_query"])
        store.add_success_pattern("查淘宝订单", ["shell:tb_query"])
        assert len(store.all_success_patterns()) == 2

    def test_build_context_includes_success_patterns(self, tmp_path):
        from ethan.memory.procedures import ProcedureStore
        store = ProcedureStore(path=tmp_path / "procedures.json")
        store.add("不要用浏览器模拟登录")
        store.add_success_pattern("查京东订单", ["shell:jd_query", "file_write:save"])
        ctx = store.build_context()
        # 应同时包含纠正准则和成功路径
        assert "不要用浏览器模拟登录" in ctx
        assert "Success patterns" in ctx
        assert "查京东订单" in ctx
        assert "shell:jd_query" in ctx

    def test_build_context_empty(self, tmp_path):
        from ethan.memory.procedures import ProcedureStore
        store = ProcedureStore(path=tmp_path / "procedures.json")
        assert store.build_context() == ""


# ---------------------------------------------------------------------------
# B1: ProcedureStore old-format compatibility
# ---------------------------------------------------------------------------

class TestProcedureStoreCompat:
    def test_old_list_format_loads(self, tmp_path):
        """旧的纯 list 格式应正常加载为 procedures，不丢失数据。"""
        from ethan.memory.procedures import ProcedureStore
        old_data = [
            {"rule": "不要用浏览器模拟登录", "context": "", "created_at": 0, "hit_count": 1},
            {"rule": "文件路径用绝对路径", "context": "", "created_at": 0, "hit_count": 2},
        ]
        p = tmp_path / "procedures.json"
        p.write_text(json.dumps(old_data), encoding="utf-8")

        store = ProcedureStore(path=p)
        assert len(store.all()) == 2
        assert store.all()[0].rule == "不要用浏览器模拟登录"
        # success_patterns 应为空（旧格式没有）
        assert store.all_success_patterns() == []

    def test_new_format_roundtrip(self, tmp_path):
        """新格式（dict 含 procedures + success_patterns）应完整往返。"""
        from ethan.memory.procedures import ProcedureStore
        p = tmp_path / "procedures.json"
        store = ProcedureStore(path=p)
        store.add("测试准则")
        store.add_success_pattern("场景A", ["tool1"])
        store._save()

        # 重新加载
        store2 = ProcedureStore(path=p)
        assert len(store2.all()) == 1
        assert store2.all()[0].rule == "测试准则"
        assert len(store2.all_success_patterns()) == 1
        assert store2.all_success_patterns()[0].scenario == "场景A"

    def test_old_format_then_add_success_pattern(self, tmp_path):
        """旧格式文件加载后，添加 success_pattern 应正常保存为新格式。"""
        from ethan.memory.procedures import ProcedureStore
        old_data = [{"rule": "旧准则", "context": "", "created_at": 0, "hit_count": 1}]
        p = tmp_path / "procedures.json"
        p.write_text(json.dumps(old_data), encoding="utf-8")

        store = ProcedureStore(path=p)
        store.add_success_pattern("新场景", ["tool1"])
        store._save()

        # 文件应为新格式（dict）
        data = json.loads(p.read_text(encoding="utf-8"))
        assert isinstance(data, dict)
        assert "procedures" in data
        assert "success_patterns" in data
        assert len(data["procedures"]) == 1
        assert len(data["success_patterns"]) == 1


# ---------------------------------------------------------------------------
# B2: _build_suggestion_hint
# ---------------------------------------------------------------------------

class TestSuggestionHint:
    """测试 Agent._build_suggestion_hint 的过滤逻辑。"""

    def _make_agent(self):
        from ethan.core.agent import Agent
        with patch.object(Agent, "__init__", lambda self, *a, **kw: None):
            agent = Agent()
        return agent

    def test_no_suggestions_file(self, tmp_path):
        agent = self._make_agent()
        with patch("ethan.core.config.CONFIG_DIR", tmp_path):
            assert agent._build_suggestion_hint() is None

    def test_pending_suggestion_returned(self, tmp_path):
        agent = self._make_agent()
        mem_dir = tmp_path / "memory"
        mem_dir.mkdir()
        suggestions = [{
            "pattern": "每天早上问天气",
            "count": 4,
            "suggestion": "可以设置定时天气播报",
            "created_at": time.time(),
            "rejected": False,
        }]
        (mem_dir / "suggestions.json").write_text(
            json.dumps(suggestions, ensure_ascii=False), encoding="utf-8"
        )
        with patch("ethan.core.config.CONFIG_DIR", tmp_path):
            hint = agent._build_suggestion_hint()
        assert hint is not None
        assert "每天早上问天气" in hint
        assert "proactive_suggestion" in hint

    def test_rejected_suggestion_filtered(self, tmp_path):
        agent = self._make_agent()
        mem_dir = tmp_path / "memory"
        mem_dir.mkdir()
        suggestions = [{
            "pattern": "已拒绝的建议",
            "count": 5,
            "suggestion": "不应出现",
            "created_at": time.time(),
            "rejected": True,
        }]
        (mem_dir / "suggestions.json").write_text(
            json.dumps(suggestions, ensure_ascii=False), encoding="utf-8"
        )
        with patch("ethan.core.config.CONFIG_DIR", tmp_path):
            assert agent._build_suggestion_hint() is None

    def test_expired_suggestion_filtered(self, tmp_path):
        """超过 7 天的建议应被过滤。"""
        agent = self._make_agent()
        mem_dir = tmp_path / "memory"
        mem_dir.mkdir()
        suggestions = [{
            "pattern": "过期建议",
            "count": 3,
            "suggestion": "不应出现",
            "created_at": time.time() - 8 * 86400,  # 8 天前
            "rejected": False,
        }]
        (mem_dir / "suggestions.json").write_text(
            json.dumps(suggestions, ensure_ascii=False), encoding="utf-8"
        )
        with patch("ethan.core.config.CONFIG_DIR", tmp_path):
            assert agent._build_suggestion_hint() is None

    def test_only_most_recent_returned(self, tmp_path):
        """多条 pending 建议时，只返回最近 1 条。"""
        agent = self._make_agent()
        mem_dir = tmp_path / "memory"
        mem_dir.mkdir()
        now = time.time()
        suggestions = [
            {"pattern": "旧建议", "count": 3, "suggestion": "旧的", "created_at": now - 100, "rejected": False},
            {"pattern": "新建议", "count": 5, "suggestion": "新的", "created_at": now, "rejected": False},
        ]
        (mem_dir / "suggestions.json").write_text(
            json.dumps(suggestions, ensure_ascii=False), encoding="utf-8"
        )
        with patch("ethan.core.config.CONFIG_DIR", tmp_path):
            hint = agent._build_suggestion_hint()
        assert hint is not None
        assert "新建议" in hint
        assert "旧建议" not in hint


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
        """Web 路径的 _maybe_consolidate 触发条件是 user_turns % 5。"""
        import inspect

        from ethan.interface.routers import tasks
        source = inspect.getsource(tasks)
        # 确保源码里用的是 % 5 而不是 % 10
        assert "% 5" in source
        assert "% 10" not in source
