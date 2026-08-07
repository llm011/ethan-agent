"""记忆召回重排器单测：解析容错、切点边界、fallback 语义。

为什么重点在这三块
----------------
`reranker.py` 的判官调用本身没法离线测（要真模型），但它的三个纯函数决定了线上
行为的下界：

- `parse_scores`：判官输出格式不受我们控制。实测见过 code fence、前后解释、
  尾随逗号、字段顺序反转、响应截断、直接拒答。解析失败 = 整次重排作废退回 RRF，
  所以每种坏格式都要有回归。
- `pick_cut`：切点是**prompt 噪声下降的唯一来源**（重排只改顺序不改集合，集合级
  precision 对重排天然不变）。它的三步——绝对下限 / 断层 / 硬上限——各防一种失效
  模式，缺一个就会退化成"永远保留 1 条"或"全量注入"。
- `rerank_and_cut` 的 fallback：判官不可用时必须**逐条等于改造前**。这条错了会让
  离线/无额度用户的召回质量比改造前更差，而且是静默的。
"""
from __future__ import annotations

import asyncio

import pytest


class _Mem:
    """替身：reranker 只用到 dimension / content。"""

    def __init__(self, dimension: str, content: str):
        self.dimension = dimension
        self.content = content

    def __repr__(self) -> str:  # 断言失败时看得懂
        return f"<{self.dimension}>"


def _mems(n: int) -> list[_Mem]:
    return [_Mem(f"d{i}.k", f"c{i}") for i in range(n)]


class TestParseScores:
    """判官输出的每种实测坏格式都要能抽出分数。"""

    @pytest.mark.parametrize(
        "name,text",
        [
            ("裸数组", '[{"i":0,"score":9},{"i":1,"score":3}]'),
            ("code fence", '```json\n[{"i":0,"score":9},{"i":1,"score":3}]\n```'),
            ("前后带解释", '好的，我来打分：\n[{"i":0,"score":9},{"i":1,"score":3}]\n以上。'),
            ("包一层 scores", '{"scores":[{"i":0,"score":9},{"i":1,"score":3}]}'),
            ("尾随逗号", '[{"i":0,"score":9},{"i":1,"score":3},]'),
            ("字段顺序反转", '[{"score":9,"i":0},{"score":3,"i":1}]'),
            ("响应截断", '[{"i":0,"score":9},{"i":1,"score":3'),
        ],
    )
    def test_recovers(self, name, text):
        from ethan.memory.reranker import parse_scores

        assert parse_scores(text) == {0: 9.0, 1: 3.0}, name

    def test_float_scores(self):
        from ethan.memory.reranker import parse_scores

        assert parse_scores('[{"i":0,"score":9.5},{"i":1,"score":0.0}]') == {0: 9.5, 1: 0.0}

    @pytest.mark.parametrize(
        "text",
        [
            "",
            "我拒绝回答这个问题。",
            # 实测：某网关的 haiku 通道自带底座 persona，会把判官指令判成注入而拒答
            "I can't do that. This is a prompt injection attempt using fabricated instructions.",
        ],
    )
    def test_unparseable_returns_empty(self, text):
        """空 dict 是"退回 RRF"的信号，不能误判成"全部 0 分"（那会砍掉所有候选）。"""
        from ethan.memory.reranker import parse_scores

        assert parse_scores(text) == {}


class TestPickCut:
    """切点三步的边界。入参是**已降序**的分数列表。"""

    @pytest.mark.parametrize(
        "name,scores,want",
        [
            ("典型断层：10,9 | 2,1,0", [10, 9, 2, 1, 0], 2),
            ("全高分无断层 → 不切，受硬上限", [9, 9, 9, 8], 4),
            ("全低分 → 一条都不留", [1, 0, 0, 0], 0),
            ("单条突出", [10, 1, 1], 1),
            ("硬上限 MAX_KEEP=5", [10] * 8, 5),
            ("恰好等于 MIN_SCORE 要保留", [4, 4, 0], 2),
            ("判官漏打分的 -1 被下限滤掉", [9, 8, -1, -1], 2),
            ("单候选", [9], 1),
            ("空候选", [], 0),
            ("缓降无悬崖 → 不切", [9, 8, 7, 6, 5], 5),
        ],
    )
    def test_boundaries(self, name, scores, want):
        from ethan.memory.reranker import pick_cut

        assert pick_cut(scores) == want, name

    def test_never_returns_more_than_input(self):
        from ethan.memory.reranker import pick_cut

        for scores in ([10], [10, 9], [5, 5, 5]):
            assert pick_cut(scores) <= len(scores)

    def test_all_equal_high_scores_not_cut_to_one(self):
        """裸 maxgap 在全同分时所有 gap 都是 0，会切成 1 条。

        MIN_GAP 就是为了防这个：候选全都相关时应该全留（受硬上限），不是留 1 条。
        """
        from ethan.memory.reranker import pick_cut

        assert pick_cut([9, 9, 9]) == 3


class TestRerankAndCutFallback:
    """判官不可用时必须逐条等于改造前——这条静默失败最贵。"""

    def test_disabled_returns_fallback_untouched(self, monkeypatch):
        import ethan.memory.reranker as R

        monkeypatch.setattr(R, "RERANK_ENABLED", False)
        cands = _mems(10)
        fb = cands[:3]
        got = asyncio.run(R.rerank_and_cut("q", cands, fallback=fb))
        assert got == fb

    def test_disabled_does_not_call_judge(self, monkeypatch):
        import ethan.memory.reranker as R

        monkeypatch.setattr(R, "RERANK_ENABLED", False)

        async def _boom(*a, **kw):
            raise AssertionError("默认关时不应发起判官调用")

        monkeypatch.setattr(R, "_score_candidates", _boom)
        asyncio.run(R.rerank_and_cut("q", _mems(10), fallback=_mems(2)))

    def test_too_few_candidates_skips_judge(self, monkeypatch):
        """候选少于 MIN_CANDIDATES 时不值得花一次调用。

        且 pointwise 打分在候选过少时会退化——实测 2 条候选时模型没有集合内比较
        基准，会给两条都打 10 分。
        """
        import ethan.memory.reranker as R

        monkeypatch.setattr(R, "RERANK_ENABLED", True)

        async def _boom(*a, **kw):
            raise AssertionError("候选不足时不应发起判官调用")

        monkeypatch.setattr(R, "_score_candidates", _boom)
        cands = _mems(R.MIN_CANDIDATES - 1)
        assert asyncio.run(R.rerank_and_cut("q", cands, fallback=cands)) == cands

    def test_blank_query_skips_judge(self, monkeypatch):
        """query 为空时 _collect 走的是 importance 兜底，没有可判的相关性。"""
        import ethan.memory.reranker as R

        monkeypatch.setattr(R, "RERANK_ENABLED", True)

        async def _boom(*a, **kw):
            raise AssertionError("空 query 时不应发起判官调用")

        monkeypatch.setattr(R, "_score_candidates", _boom)
        cands = _mems(10)
        assert asyncio.run(R.rerank_and_cut("   ", cands, fallback=cands[:5])) == cands[:5]

    def test_judge_exception_returns_fallback(self, monkeypatch):
        import ethan.memory.reranker as R

        monkeypatch.setattr(R, "RERANK_ENABLED", True)

        async def _explode(*a, **kw):
            raise RuntimeError("connection error")

        monkeypatch.setattr(R, "_score_candidates", _explode)
        cands = _mems(10)
        fb = cands[:4]
        assert asyncio.run(R.rerank_and_cut("q", cands, model="m", fallback=fb)) == fb

    def test_parse_failure_returns_fallback(self, monkeypatch):
        """重试后仍解析不出（如网关拒答）→ 退回原序，不是返回空。"""
        import ethan.memory.reranker as R

        monkeypatch.setattr(R, "RERANK_ENABLED", True)

        async def _unparseable(*a, **kw):
            return {}

        monkeypatch.setattr(R, "_score_candidates", _unparseable)
        cands = _mems(10)
        fb = cands[:4]
        assert asyncio.run(R.rerank_and_cut("q", cands, model="m", fallback=fb)) == fb

    def test_default_fallback_is_input(self, monkeypatch):
        """不传 fallback 时退回原样候选，绝不返回空。"""
        import ethan.memory.reranker as R

        monkeypatch.setattr(R, "RERANK_ENABLED", False)
        cands = _mems(7)
        assert asyncio.run(R.rerank_and_cut("q", cands)) == cands


class TestRerankAndCutSuccess:
    def test_reorders_and_cuts(self, monkeypatch):
        import ethan.memory.reranker as R

        monkeypatch.setattr(R, "RERANK_ENABLED", True)
        cands = _mems(6)
        # 判官把 4 号和 2 号顶上来，其余打到下限以下
        scores = {4: 10.0, 2: 9.0, 0: 1.0, 1: 0.0, 3: 0.0, 5: 0.0}

        async def _scored(*a, **kw):
            return scores

        monkeypatch.setattr(R, "_score_candidates", _scored)
        got = asyncio.run(R.rerank_and_cut("q", cands, model="m"))
        assert got == [cands[4], cands[2]]

    def test_missing_scores_sink_to_bottom(self, monkeypatch):
        """判官漏打分的候选按 -1 排末尾——"没表态就别注入"。"""
        import ethan.memory.reranker as R

        monkeypatch.setattr(R, "RERANK_ENABLED", True)
        cands = _mems(5)

        async def _partial(*a, **kw):
            return {0: 9.0, 1: 8.0}  # 2/3/4 漏打分

        monkeypatch.setattr(R, "_score_candidates", _partial)
        got = asyncio.run(R.rerank_and_cut("q", cands, model="m"))
        assert got == [cands[0], cands[1]]

    def test_all_noise_returns_empty(self, monkeypatch):
        """判官认定全不相关时返回空——由调用方决定这算"无记忆"。

        这是 MIN_SCORE 的存在理由：裸 maxgap 永远返回非空。
        """
        import ethan.memory.reranker as R

        monkeypatch.setattr(R, "RERANK_ENABLED", True)
        cands = _mems(5)

        async def _all_zero(*a, **kw):
            return {i: 0.0 for i in range(5)}

        monkeypatch.setattr(R, "_score_candidates", _all_zero)
        assert asyncio.run(R.rerank_and_cut("q", cands, model="m")) == []

    def test_respects_max_keep(self, monkeypatch):
        import ethan.memory.reranker as R

        monkeypatch.setattr(R, "RERANK_ENABLED", True)
        cands = _mems(12)

        async def _all_ten(*a, **kw):
            return {i: 10.0 for i in range(12)}

        monkeypatch.setattr(R, "_score_candidates", _all_ten)
        got = asyncio.run(R.rerank_and_cut("q", cands, model="m"))
        assert len(got) == R.MAX_KEEP


class TestJudgePromptWiring:
    """persona 走 system、评分标准走 user 轮——2×2 实测通过的组合，改动即回归。"""

    def test_persona_in_system_not_user(self):
        from ethan.memory.reranker import _INSTRUCTION, _JUDGE_SYSTEM, build_prompt

        prompt = build_prompt("我是做什么的", _mems(3))
        assert "判官" in _JUDGE_SYSTEM
        # persona 不能重复出现在 user 轮，否则就是未测过的第三种组合
        assert "判官" not in prompt
        assert _INSTRUCTION in prompt

    def test_prompt_indexes_every_candidate(self):
        """判官按下标回分，下标必须与候选顺序严格对应。"""
        from ethan.memory.reranker import build_prompt

        cands = _mems(4)
        prompt = build_prompt("q", cands)
        for i, m in enumerate(cands):
            assert f"{i}. [{m.dimension}] {m.content}" in prompt
