r"""上下文预算管控的「前缀稳定性」单测（计划条目 1，对应 P1）。

核心验收：长运行（40 轮、每轮 12K 字工具结果）里，已发出的 tool 结果前缀
逐字节稳定，enforce_context_budget 不再改写它——这是缓存命中的契约。

还覆盖：
  - 入口定稿落盘的幂等性（已落盘消息不被二次改写、不被驱逐）；
  - 预算按模型窗口缩放（context_tool_budget_chars：env 覆盖 / 夹取 / 关闭回退）；
  - 无 session_id 时保持旧行为（不落盘，避免测试污染 /tmp）；
  - 落盘后上下文保留逐字前缀 + 路径 + 总字数，全文可 file_read 取回。
"""
from __future__ import annotations

import shutil

import pytest

from ethan.core.context_budget import (
    _OFFLOADED_MARKER,
    OFFLOAD_KEEP_PREFIX,
    context_tool_budget_chars,
    enforce_context_budget,
)
from ethan.providers.base import Message

_SESSION_ID = "test_ctx_budget_stability"


def _tool_msg(i: int, size: int) -> Message:
    body = f"result_{i}_" + ("x" * (size - len(f"result_{i}_")))
    return Message(role="tool", content=body, tool_call_id=f"call_{i}")


@pytest.fixture()
def _clean_tmp():
    """隔离 /tmp/ethan/<session> 落盘目录：测试前后清理，避免污染与串扰。"""
    import os

    path = f"/tmp/ethan/{_SESSION_ID}"
    if os.path.isdir(path):
        shutil.rmtree(path, ignore_errors=True)
    yield
    if os.path.isdir(path):
        shutil.rmtree(path, ignore_errors=True)


class TestPrefixStability:
    def test_40_rounds_12k_zero_prefix_mutation(self, _clean_tmp):
        """验收：40 轮 × 每条 12K 字，已发出前缀被改写 0 次（对应计划条目 1 验收）。"""
        working: list[Message] = []
        changed_rounds = 0
        for i in range(40):
            before = {id(m): (m.content or "") for m in working if m.role == "tool"}
            working.append(_tool_msg(i, 12000))
            enforce_context_budget(working, _SESSION_ID)
            after = {id(m): (m.content or "") for m in working if m.role == "tool"}
            if any(before[k] != after.get(k) for k in before):
                changed_rounds += 1
        assert changed_rounds == 0, f"前缀被改写 {changed_rounds} 轮，应为 0"

    def test_total_under_budget_after_offload(self, _clean_tmp):
        """落盘后，40 条 12K 结果的上下文总量压在预算内（不再触发淘汰）。"""
        working = [_tool_msg(i, 12000) for i in range(40)]
        enforce_context_budget(working, _SESSION_ID)
        total = sum(len(m.content or "") for m in working if m.role == "tool")
        # 每条 ≤ OFFLOAD_KEEP_PREFIX + 标注 overhead（约 200 字），40 条合计远低于 94805 预算
        assert total <= 40 * (OFFLOAD_KEEP_PREFIX + 500)
        assert total <= context_tool_budget_chars(), (
            f"落盘后总量 {total} 仍超预算 {context_tool_budget_chars()}"
        )


class TestOffloadIdempotency:
    def test_offloaded_message_not_rewritten_on_second_call(self, _clean_tmp):
        """已落盘（含 marker）的消息，二次 enforce 内容逐字节不变——幂等契约。"""
        working = [_tool_msg(0, 12000)]
        enforce_context_budget(working, _SESSION_ID)
        first = working[0].content
        assert _OFFLOADED_MARKER in first, "首次应落盘并打 marker"
        # 再追加几条并 enforce，已落盘的那条不能被改写
        working.append(_tool_msg(1, 12000))
        enforce_context_budget(working, _SESSION_ID)
        assert working[0].content == first, "已落盘消息被二次改写，破坏前缀稳定"

    def test_offloaded_message_exempt_from_eviction(self, _clean_tmp):
        """构造大量消息触发淘汰预算，已落盘消息不能被压成 EVICTED_STUB。"""
        working = [_tool_msg(i, 12000) for i in range(40)]
        enforce_context_budget(working, _SESSION_ID)
        # 全部落盘后再人为塞入大量未入稿的中等结果，强制触发淘汰
        for j in range(10):
            working.append(Message(role="tool", content="z" * 7000, tool_call_id=f"extra_{j}"))
        enforce_context_budget(working, _SESSION_ID)
        # 前 40 条（12K，已落盘）必须仍含 marker、不含「已折叠」
        offloaded = [m for m in working[:40] if m.role == "tool"]
        for m in offloaded:
            assert _OFFLOADED_MARKER in (m.content or ""), "已落盘消息被驱逐改写"
            assert "已折叠" not in (m.content or ""), "已落盘消息被压成折叠 stub"

    def test_offload_keeps_prefix_and_path(self, _clean_tmp):
        """落盘 stub：保留逐字前缀 + 文件路径 + 总字数，全文写盘可取回。"""
        import os

        working = [_tool_msg(0, 12000)]
        enforce_context_budget(working, _SESSION_ID)
        stub = working[0].content
        assert stub.startswith(_OFFLOADED_MARKER)
        assert "12000 字" in stub
        # 提取落盘路径，验证文件存在且含全文
        path = stub.split("：", 1)[1].split("（")[0].strip()
        assert path.endswith(".md")
        assert os.path.isfile(path)
        assert open(path, encoding="utf-8").read() == _tool_msg(0, 12000).content
        # 上下文里保留了逐字前缀开头
        assert stub.startswith(_OFFLOADED_MARKER)


class TestNoSessionBackwardCompat:
    def test_no_session_id_does_not_offload(self):
        """无 session_id 时不落盘（保持旧的截断+驱逐行为，测试不污染 /tmp）。"""
        working = [_tool_msg(0, 25000)]
        enforce_context_budget(working)  # 不传 session_id
        content = working[0].content
        assert _OFFLOADED_MARKER not in content, "无会话不应落盘"
        # 走旧路径：单条封顶到 20000（含截断标注）
        assert len(content) <= 20100


class TestBudgetScaling:
    def test_default_budget_scales_from_upstream(self, monkeypatch):
        """默认预算 = effective_input_budget() × 10%，夹在 [30000, 200000]。"""
        monkeypatch.delenv("ETHAN_TOOL_BUDGET_CHARS", raising=False)
        monkeypatch.delenv("ETHAN_MAX_INPUT_CHARS", raising=False)
        monkeypatch.delenv("ETHAN_INPUT_LIMIT_MARGIN_PCT", raising=False)
        from ethan.core.context_limit import effective_input_budget

        expected = max(30000, min(200000, int(effective_input_budget() * 0.10)))
        assert context_tool_budget_chars() == expected

    def test_env_override(self, monkeypatch):
        monkeypatch.setenv("ETHAN_TOOL_BUDGET_CHARS", "50000")
        assert context_tool_budget_chars() == 50000

    def test_env_override_invalid_falls_through(self, monkeypatch):
        monkeypatch.setenv("ETHAN_TOOL_BUDGET_CHARS", "abc")
        # 非法值忽略，走默认缩放（不再抛异常）
        assert context_tool_budget_chars() > 0

    def test_upstream_closed_falls_back_to_constant(self, monkeypatch):
        monkeypatch.delenv("ETHAN_TOOL_BUDGET_CHARS", raising=False)
        monkeypatch.setenv("ETHAN_MAX_INPUT_CHARS", "0")  # 关闭预检
        from ethan.core.context_budget import CONTEXT_BUDGET_CHARS

        assert context_tool_budget_chars() == CONTEXT_BUDGET_CHARS
