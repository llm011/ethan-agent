r"""多内核抽象层的测试。

覆盖四件事（这是「多核」能不能真的工作、默认行为会不会被破坏的关键）：

1. **默认路径零变化**：`kernel.default` 未配置时必须是 EthanKernel 原样转发。
2. **事件契约对齐**：外部内核产出的事件必须能被 `producers.py` 那套 isinstance
   判断识别——否则上层要改，也就失去「适配层」的意义。
3. **选择与回退**：显式 > task_rules > default > Ethan 兜底；选到不可用的内核
   必须自动降级，不能让整轮对话失败。
4. **runner 的鸭子类型**：`collector.bind(runner)` 会读 `runner.usage`；
   上游还会读 `runner.model` / `session_id` / `_registry` 等，都要能拿到。
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass

import pytest

from ethan.kernel.dispatch import KernelRunner, KernelUsage, build_runner
from ethan.kernel.runtime import (
    KernelContext,
    KernelKind,
    KernelRegistry,
    KernelRequest,
    KernelRuntime,
    get_kernel_registry,
    reset_kernel_registry,
)
from ethan.providers.base import Message, ToolEvent


@dataclass
class _FakeStub:
    """测试用假 Agent（鸭子类型）。"""

    usage: object
    model: str = "fake-model"
    session_id: str = "sess-1"
    runtime_context: str = ""
    _channel: str = "web"
    _user_id: str = ""
    _mode: str = ""
    _registry: object = None
    _skills: object = None


class _FakeUsage:
    input_tokens = 10
    output_tokens = 20
    cache_tokens = 5
    total = 30


# ── KernelKind 解析 ─────────────────────────────────────────


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("ethan", KernelKind.ETHAN),
        ("ETHAN", KernelKind.ETHAN),
        ("claude_code", KernelKind.CLAUDE_CODE),
        ("claude-code", KernelKind.CLAUDE_CODE),  # 连字符也接受
        ("CLAUDE_CODE", KernelKind.CLAUDE_CODE),
        ("dsh", None),  # 不存在，走 default
    ],
)
def test_kind_parse(raw, expected):
    if expected is None:
        assert KernelKind.parse(raw, default=KernelKind.ETHAN) == KernelKind.ETHAN
    else:
        assert KernelKind.parse(raw) == expected


def test_kind_parse_strict_raises():
    with pytest.raises(ValueError):
        KernelKind.parse("nope")


# ── 注册表选择与回退 ─────────────────────────────────────────


class _Unavailable(KernelRuntime):
    kind = KernelKind.CODEX
    display_name = "不可用内核"

    def available(self):
        return False, "故意不可用"


class _Available(KernelRuntime):
    kind = KernelKind.OPENCODE
    display_name = "可用内核"

    async def run(self, request, context=None):
        yield "ok"


def _registry_with(*runtimes) -> KernelRegistry:
    reg = KernelRegistry()
    for rt in runtimes:
        reg.register(rt)
    return reg


def test_resolve_explicit_wins():
    reg = _registry_with(_Available())
    assert reg.resolve(explicit="opencode").kind == KernelKind.OPENCODE


def test_resolve_falls_back_to_ethan_when_unavailable():
    """选了没装的内核绝不能抛异常——必须降级到可用的。"""
    ethan = _Available()
    ethan.kind = KernelKind.ETHAN
    ethan.display_name = "Ethan"
    reg = _registry_with(ethan, _Unavailable())
    chosen = reg.resolve(explicit="codex")
    assert chosen.kind == KernelKind.ETHAN


def test_resolve_task_rules():
    ethan = _Available()
    ethan.kind = KernelKind.ETHAN
    reg = _registry_with(ethan, _Available())
    chosen = reg.resolve(
        task_kind="coding",
        task_rules={"coding": "opencode"},
        default="ethan",
    )
    assert chosen.kind == KernelKind.OPENCODE


def test_resolve_explicit_beats_task_rules():
    ethan = _Available()
    ethan.kind = KernelKind.ETHAN
    reg = _registry_with(ethan, _Available())
    chosen = reg.resolve(
        explicit="ethan",
        task_kind="coding",
        task_rules={"coding": "opencode"},
    )
    assert chosen.kind == KernelKind.ETHAN


def test_resolve_ignores_unknown_kernel_name():
    ethan = _Available()
    ethan.kind = KernelKind.ETHAN
    reg = _registry_with(ethan)
    # 配置里写了不存在的内核名，应该记警告并继续兜底，而不是崩
    assert reg.resolve(explicit="totally_unknown").kind == KernelKind.ETHAN


def test_registry_list_status_shape():
    reg = _registry_with(_Available(), _Unavailable())
    status = {item["kind"]: item for item in reg.list_status()}
    assert status["opencode"]["available"] is True
    assert status["codex"]["available"] is False
    assert "capabilities" in status["codex"]


# ── 内置内核注册 ─────────────────────────────────────────────


def test_builtin_kernels_registered():
    reset_kernel_registry()
    reg = get_kernel_registry()
    kinds = {k.value for k in reg.all()}
    assert "ethan" in kinds, "原生内核必须始终注册"


def test_ethan_kernel_always_available():
    reg = get_kernel_registry()
    ethan = reg.get(KernelKind.ETHAN)
    assert ethan is not None
    ok, reason = ethan.available()
    assert ok is True
    assert reason == ""


def test_external_kernels_declare_no_ethan_context():
    """外部 runtime 有自己的系统提示词/工具，声明 ethan_context=False 是有意的取舍。"""
    reg = get_kernel_registry()
    for kind in (KernelKind.CLAUDE_CODE, KernelKind.CODEX, KernelKind.OPENCODE):
        rt = reg.get(kind)
        if rt is None:
            continue
        assert rt.capabilities.ethan_context is False
        assert rt.capabilities.consent is False


def test_external_kernel_unavailable_when_cli_missing(monkeypatch):
    """CLI 不在时 available() 必须明确返回 False + 原因（含安装提示）。"""
    import shutil

    from ethan.kernel.claude_kernel import ClaudeCodeKernel

    monkeypatch.setattr(shutil, "which", lambda _: None)
    ok, reason = ClaudeCodeKernel().available()
    assert ok is False
    assert "claude" in reason


# ── runner 鸭子类型 ─────────────────────────────────────────


def test_runner_proxies_usage_and_model():
    stub = _FakeStub(usage=_FakeUsage())
    rt = KernelRuntime()
    runner = KernelRunner(rt, stub, model="m1", channel="web")
    assert runner.model == "m1"
    assert runner.session_id == "sess-1"


def test_runner_passthrough_unknown_attributes():
    stub = _FakeStub(usage=_FakeUsage(), _channel="lark")
    runner = KernelRunner(KernelRuntime(), stub)
    # 上游会读 agent._channel / _registry 之类，必须透传
    assert runner._channel == "lark"


def test_runner_raises_for_unknown_attr_without_agent():
    runner = KernelRunner(KernelRuntime(), None)
    with pytest.raises(AttributeError):
        _ = runner.nonexistent_thing


def test_runner_model_reports_kernel_name_for_external():
    """外部内核的真实模型由 CLI 决定，报内核名比谎报一个模型 id 诚实。"""
    rt = KernelRuntime()
    rt.kind = KernelKind.CLAUDE_CODE
    rt.display_name = "Claude Code"
    runner = KernelRunner(rt, _FakeStub(usage=_FakeUsage()), model="deepseek")
    assert runner.model == "Claude Code"


def test_kernel_usage_shape_matches_agent_usage():
    u = KernelUsage()
    u.input_tokens, u.output_tokens, u.cache_tokens = 1, 2, 3
    assert u.total == 3
    assert u.dict() == {"input": 1, "output": 2, "cache": 3}


# ── 默认路径：ethan 内核原样转发 ─────────────────────────────


def test_default_kernel_is_ethan():
    """未配置 kernel 时必须是原生内核——这是「不破坏现有行为」的底线。"""
    stub = _FakeStub(usage=_FakeUsage())
    runner = build_runner(stub, channel="web")
    assert runner.kernel_kind == "ethan"


def test_ethan_kernel_forwards_events_unchanged():
    """EthanKernel 的职责就是原样转发，任何转换都算行为漂移。"""
    from ethan.kernel.ethan_kernel import EthanKernel

    seen_events = [
        "hello",
        ToolEvent(tool_name="t", args_summary="a", state="start"),
        "world",
    ]

    class _Agent:
        usage = _FakeUsage()

        async def stream_chat(self, messages):
            for e in seen_events:
                yield e

    kernel = EthanKernel()
    # 直接给 context，避免真的去 create_agent
    ctx = KernelContext(tool_registry=object())

    async def collect():
        out = []
        async for e in kernel.run(KernelRequest(messages=[]), ctx):
            out.append(e)
        return out

    import ethan.kernel.ethan_kernel as ek

    original_build = ek.EthanKernel._build_agent
    ek.EthanKernel._build_agent = lambda self, req, ctx: _Agent()
    try:
        out = asyncio.run(collect())
    finally:
        ek.EthanKernel._build_agent = original_build

    assert out == seen_events, "EthanKernel 改动了事件流，这是行为漂移"


# ── 外部内核事件映射 ─────────────────────────────────────────


def test_acp_events_map_to_stream_chat_vocabulary(monkeypatch):
    """ACP 的 step/text 必须映射成 ToolEvent / str，否则 providers 那层认不出来。"""
    import ethan.acp as acp_mod
    from ethan.acp.models import ACPResult
    from ethan.kernel.claude_kernel import ClaudeCodeKernel

    step = {"tool": "Read", "args": "x.py", "state": "running", "result_preview": ""}

    async def fake_delegate(prompt, cwd=None, prefer="auto", timeout=180, resume=True,
                            reset_session=False, user_id="", mirror=True, on_event=None):
        await on_event("step", step)
        await on_event("text", "先看看文件")
        step["state"] = "done"
        step["result_preview"] = "content"
        await on_event("step", step)
        return ACPResult(success=True, output="先看看文件", agent="claude")

    monkeypatch.setattr(acp_mod, "delegate", fake_delegate)

    async def collect():
        out = []
        async for e in ClaudeCodeKernel().run(
            KernelRequest(messages=[Message(role="user", content="看下代码")])
        ):
            out.append(e)
        return out

    events = asyncio.run(collect())
    types = [type(e).__name__ for e in events]
    assert "ToolEvent" in types
    assert any(isinstance(e, str) for e in events)

    tool_events = [e for e in events if isinstance(e, ToolEvent)]
    assert tool_events[0].state == "start"
    assert tool_events[-1].state == "done"
    # start/done 必须共用同一个 tool_call_id，前端才能配对
    assert tool_events[0].tool_call_id == tool_events[-1].tool_call_id


def test_acp_kernel_reports_error_as_text(monkeypatch):
    """ACP 抛异常时不能让消费者永久阻塞，要转成可见的错误文本。"""
    import ethan.acp as acp_mod
    from ethan.kernel.claude_kernel import ClaudeCodeKernel

    async def boom(*a, **kw):
        raise RuntimeError("cli 挂了")

    monkeypatch.setattr(acp_mod, "delegate", boom)

    async def collect():
        return [e async for e in ClaudeCodeKernel().run(
            KernelRequest(messages=[Message(role="user", content="hi")])
        )]

    events = asyncio.run(collect())
    assert any(isinstance(e, str) and "cli 挂了" in e for e in events)


def test_acp_kernel_skips_duplicate_final_text(monkeypatch):
    """流式已经吐过的内容，最终 result 不能再完整输出一遍（用户会看到两遍）。"""
    import ethan.acp as acp_mod
    from ethan.acp.models import ACPResult
    from ethan.kernel.claude_kernel import ClaudeCodeKernel

    async def fake_delegate(prompt, cwd=None, prefer="auto", timeout=180, resume=True,
                            reset_session=False, user_id="", mirror=True, on_event=None):
        await on_event("text", "完整回答")
        return ACPResult(success=True, output="完整回答", agent="claude")

    monkeypatch.setattr(acp_mod, "delegate", fake_delegate)

    async def collect():
        return [e async for e in ClaudeCodeKernel().run(
            KernelRequest(messages=[Message(role="user", content="hi")])
        )]

    texts = [e for e in asyncio.run(collect()) if isinstance(e, str)]
    assert "".join(texts).count("完整回答") == 1


# ── 消息历史展开 ─────────────────────────────────────────────


def test_prompt_single_turn_is_raw():
    from ethan.kernel.claude_kernel import ClaudeCodeKernel

    k = ClaudeCodeKernel()
    prompt = k._build_prompt(
        KernelRequest(messages=[Message(role="user", content="修个 bug")])
    )
    assert prompt == "修个 bug", "单轮不该加历史前缀，会干扰 CLI 理解"


def test_prompt_multi_turn_includes_history():
    from ethan.kernel.claude_kernel import ClaudeCodeKernel

    k = ClaudeCodeKernel()
    prompt = k._build_prompt(
        KernelRequest(messages=[
            Message(role="user", content="第一问"),
            Message(role="assistant", content="第一答"),
            Message(role="user", content="第二问"),
        ])
    )
    assert "第一问" in prompt and "第一答" in prompt and "第二问" in prompt


def test_prompt_skips_tool_messages():
    """tool 消息是 Ethan 侧中间产物，喂给外部 CLI 会干扰它。"""
    from ethan.kernel.claude_kernel import ClaudeCodeKernel

    k = ClaudeCodeKernel()
    prompt = k._build_prompt(
        KernelRequest(messages=[
            Message(role="user", content="问"),
            Message(role="tool", content="TOOL_OUTPUT_SHOULD_NOT_APPEAR"),
        ])
    )
    assert "TOOL_OUTPUT_SHOULD_NOT_APPEAR" not in prompt


def test_prompt_empty_messages():
    from ethan.kernel.claude_kernel import ClaudeCodeKernel

    assert ClaudeCodeKernel()._build_prompt(KernelRequest(messages=[])) == ""


# ── 可观测性 ─────────────────────────────────────────────────


def test_runner_collects_stats():
    """统计是「对比不同内核」的唯一数据来源，必须真的记录。"""

    class _Rt(KernelRuntime):
        kind = KernelKind.ETHAN

        async def run(self, request, context=None):
            yield ToolEvent(tool_name="a", args_summary="", state="start")
            yield "text"
            yield ToolEvent(tool_name="a", args_summary="", state="done")

    stub = _FakeStub(usage=_FakeUsage())
    runner = KernelRunner(_Rt(), stub, model="m")

    async def go():
        return [e async for e in runner.stream_chat([])]

    asyncio.run(go())
    stats = runner.last_stats
    assert stats is not None
    assert stats.kernel == "ethan"
    assert stats.tool_calls == 1, "只该数 start，done 不重复计数"
    assert stats.input_tokens == 10
    assert stats.error == ""


def test_runner_records_error_in_stats():
    class _Rt(KernelRuntime):
        kind = KernelKind.ETHAN

        async def run(self, request, context=None):
            raise RuntimeError("炸了")
            yield  # pragma: no cover

    runner = KernelRunner(_Rt(), None)

    async def go():
        return [e async for e in runner.stream_chat([])]

    with pytest.raises(RuntimeError):
        asyncio.run(go())
    assert runner.last_stats is not None
    assert "炸了" in runner.last_stats.error


# ── 关键不变量：必须复用调用方的 agent 实例 ──────────────────────


def test_ethan_kernel_reuses_caller_agent_not_a_new_one():
    """EthanKernel 必须用 context.agent，绝不能自己新建。

    这个 bug 后果很严重且隐蔽：新建的 Agent 会丢掉 session_id / runtime_context /
    is_owner / _executor.current_run / 已加载的 system_files，表现为
    「会话串了、工具取消失效、记忆召回错人」，而且不会报错——只会「行为不对」。

    （真实踩到的场景：MCP 入口用 fake agent 测试时，EthanKernel 忽略它去
    create_agent 建了一个真 agent，导致测试里出现真实模型的回复。）
    """
    from ethan.kernel.ethan_kernel import EthanKernel

    used = []

    class _Agent:
        usage = _FakeUsage()
        session_id = "keep-me"

        async def stream_chat(self, messages):
            used.append(self)
            yield "ok"

    agent = _Agent()
    kernel = EthanKernel()

    async def collect():
        ctx = KernelContext(agent=agent)
        return [e async for e in kernel.run(KernelRequest(messages=[]), ctx)]

    out = asyncio.run(collect())
    assert out == ["ok"]
    assert used == [agent], "EthanKernel 没有复用传入的 agent 实例"


def test_runner_passes_agent_into_context():
    """dispatch 层必须把原 agent 放进 KernelContext，否则上一层的修复无效。"""
    from ethan.kernel.ethan_kernel import EthanKernel

    captured = {}

    class _Spy(EthanKernel):
        async def run(self, request, context=None):
            captured["agent"] = getattr(context, "agent", None)
            async for e in super().run(request, context):
                yield e

    class _Agent:
        usage = _FakeUsage()
        session_id = "s"

        async def stream_chat(self, messages):
            yield "x"

    agent = _Agent()
    runner = KernelRunner(_Spy(), agent)

    async def go():
        return [e async for e in runner.stream_chat([])]

    asyncio.run(go())
    assert captured["agent"] is agent
