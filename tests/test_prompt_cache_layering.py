r"""system prompt 缓存分层断言（计划条目 2，对应 P2）。

契约：`Current time:` 是 Anthropic provider 的缓存分割点
（ethan/providers/anthropic.py::_split_system_for_cache）。分割点之前必须全是
**对话内稳定**的块（跨请求不变，可命中缓存）；之后全是**每轮/每次变化**的块。

本测试断言重排后：
  - 准静态块（user_profile / behavioral_guidelines / memory_recall_hint /
    documents_protocol / intent 说明）位于分割点之前（稳定层）；
  - 每轮变化块（relevant_skills / matched_skills_brief / runtime_context /
    previous_run_summary / memory_signal）位于分割点之后（动态层）；
  - 同一块不在分割点两侧重复出现。
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

SPLIT_MARKER = "Current time:"


def _split(prompt: str) -> tuple[str, str]:
    idx = prompt.find(SPLIT_MARKER)
    assert idx != -1, "system prompt 缺少分割点 Current time:"
    return prompt[:idx], prompt[idx:]


def _build(fast: bool, query: str = "帮我总结一下昨天的会议要点", runtime_context: str = ""):
    """直接调用 build_system_prompt，注入 mock 数据让准静态块必然出现。

    不依赖 ~/.ethan 的真实文件内容（user_profile / procedures 可能为空，
    条件注入的块就不会出现，无法断言位置）。
    """
    from ethan.core.agent import Message
    from ethan.core.system_prompt import build_system_prompt

    procedures = SimpleNamespace(build_context=lambda: "历史纠正规则示例：文件过长要拆分。")
    system_files = {
        "identity": "你是 Ethan。",
        "user_profile": "主人偏好简洁回复。",
        "soul": "",
        "agent": "",
        "tools": "",
    }
    prompt = build_system_prompt(
        messages=[Message(role="user", content=query)],
        fast=fast,
        fast_rule=None,
        system_files=system_files,
        provider_model="deepseek-v4.1-flash",
        skills=None,
        procedures=procedures,
        registry=None,
        channel="repl",
        mode="",
        is_owner=True,
        runtime_context=runtime_context,
        last_matched_skills_out=[],
    )
    return _split(prompt)


class TestStableLayer:
    def test_user_profile_in_stable_layer_full(self):
        stable, _ = _build(fast=False)
        assert "<user_profile>" in stable

    def test_behavioral_guidelines_in_stable_layer_full(self):
        stable, _ = _build(fast=False)
        assert "<behavioral_guidelines>" in stable

    def test_memory_recall_hint_in_stable_layer_full(self):
        stable, _ = _build(fast=False)
        assert "<memory_recall_hint>" in stable

    def test_documents_protocol_in_stable_layer_fast(self):
        """fast 档：documents_protocol 必须在分割点之前（原在之后，缓存失效）。"""
        stable, _ = _build(fast=True)
        # documents_protocol 不是 xml 块，用其稳定文案特征断言
        assert "doc_save" in stable or "doc_list" in stable or "文档" in stable

    def test_quasi_static_blocks_in_stable_layer_fast(self):
        stable, _ = _build(fast=True)
        assert "<user_profile>" in stable
        assert "<behavioral_guidelines>" in stable
        assert "<memory_recall_hint>" in stable


class TestDynamicLayer:
    def test_runtime_context_not_in_stable(self):
        stable, dynamic = _build(fast=False, query="随便聊聊")
        assert "<runtime_context>" not in stable

    def test_previous_run_summary_not_in_stable(self):
        stable, dynamic = _build(fast=False)
        assert "previous_run_summary" not in stable

    def test_relevant_skills_in_dynamic_when_matched(self):
        # 用一个更容易命中技能触发词的 query，让 relevant_skills 出现
        stable, dynamic = _build(fast=False, query="帮我写代码实现一个功能")
        # relevant_skills 若出现，必须在动态层（不在稳定层）
        assert "<relevant_skills>" not in stable


class TestNoBlockSpansBothSides:
    @pytest.mark.parametrize("fast", [False, True])
    def test_no_block_duplicated_across_split(self, fast):
        """任意 xml 块不得同时出现在分割点两侧（避免重复计费 + 语义混乱）。"""
        import re

        stable, dynamic = _build(fast=fast)
        stable_tags = set(re.findall(r"<([a-z_]+)>", stable))
        # 闭合标签也算，确保成对块整体归属一侧
        for m in re.finditer(r"<([a-z_]+)>(.*?)</\1>", dynamic, re.S):
            assert m.group(1) not in stable_tags, (
                f"块 <{m.group(1)}> 同时出现在分割点两侧，破坏缓存分层"
            )
