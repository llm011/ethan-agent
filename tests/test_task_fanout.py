"""task_fanout 工具测试：并行性、隔离性、分支失败隔离、轮次上限。"""

import asyncio
import time

from ethan.providers.base import Message, ToolCall
from ethan.tools.base import BaseTool
from ethan.tools.builtin.task_fanout import TaskFanoutTool
from ethan.tools.registry import ToolRegistry


def _run(coro):
    return asyncio.run(coro)


class FakeShellTool(BaseTool):
    """记录调用的假 shell，供子 agent 循环消费 tool_calls。"""

    name = "shell"
    description = "fake shell"
    cacheable = False
    parameters = {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]}

    def __init__(self):
        self.calls: list[str] = []

    async def run(self, command: str = "", **kwargs) -> str:
        self.calls.append(command)
        return f"ok:{command}"


class FakeProvider:
    """按 subtask 脚本返回响应：每个 task 先回一轮 tool_calls，再回最终文本。

    chat_delay 模拟 LLM 延迟，用 max_in_flight 验证并发度。
    fail_tasks 里的任务直接抛异常，验证分支失败隔离。
    """

    def __init__(self, chat_delay: float = 0.0, fail_tasks: set[str] | None = None):
        self.chat_delay = chat_delay
        self.fail_tasks = fail_tasks or set()
        self.in_flight = 0
        self.max_in_flight = 0

    async def chat(self, messages: list[Message], tools=None, system=None, max_tokens=None) -> Message:
        task_text = messages[0].content if messages else ""
        self.in_flight += 1
        self.max_in_flight = max(self.max_in_flight, self.in_flight)
        try:
            await asyncio.sleep(self.chat_delay)
            if any(f in task_text for f in self.fail_tasks):
                raise RuntimeError("boom")
            has_tool_round = any(m.role == "tool" for m in messages)
            if not has_tool_round:
                return Message(
                    role="assistant",
                    content="",
                    tool_calls=[
                        ToolCall(id=f"c{self.in_flight}", name="shell", arguments={"command": "gh api repos/x/y"})
                    ],
                )
            return Message(role="assistant", content=f"结论({task_text[:12]})")
        finally:
            self.in_flight -= 1

    async def close(self):
        pass


def _tool(provider: FakeProvider, shell: FakeShellTool) -> TaskFanoutTool:
    reg = ToolRegistry()
    reg.register(shell)
    return TaskFanoutTool(provider=provider, tools=reg)


def test_fanout_empty_subtasks_is_error():
    t = _tool(FakeProvider(), FakeShellTool())
    r = _run(t.run(subtasks=[]))
    assert r.is_error
    assert "subtasks 为空" in r.content


def test_fanout_runs_tool_loop_and_combines_results():
    provider = FakeProvider()
    shell = FakeShellTool()
    t = _tool(provider, shell)
    r = _run(
        t.run(
            subtasks=[
                {"id": "D-1", "task": "扫描维度一 diff=/tmp/a.diff"},
                {"id": "D-2", "task": "扫描维度二 diff=/tmp/a.diff"},
            ]
        )
    )
    assert not r.is_error
    # 两个子任务各跑了一轮工具 + 一轮结论
    assert len(shell.calls) == 2
    assert "### D-1" in r.content and "### D-2" in r.content
    assert "结论(扫描维度一" in r.content and "结论(扫描维度二" in r.content
    assert r.sub_steps and all(s["state"] == "done" for s in r.sub_steps)


def test_fanout_runs_in_parallel():
    delay = 0.4
    provider = FakeProvider(chat_delay=delay)
    t = _tool(provider, FakeShellTool())
    tasks = [{"id": f"T{i}", "task": f"子任务{i}号材料"} for i in range(4)]
    started = time.monotonic()
    r = _run(t.run(subtasks=tasks))
    elapsed = time.monotonic() - started
    assert not r.is_error
    # 串行至少 8 轮 × delay = 3.2s；并行（并发 4）两轮 ≈ 0.8s
    assert elapsed < 4 * delay, f"扇出未并行生效，耗时 {elapsed:.2f}s"
    assert provider.max_in_flight == 4


def test_fanout_respects_concurrency_cap():
    provider = FakeProvider(chat_delay=0.05)
    t = _tool(provider, FakeShellTool())
    tasks = [{"id": f"T{i}", "task": f"子任务{i}号材料"} for i in range(6)]
    _run(t.run(subtasks=tasks, concurrency=2))
    assert provider.max_in_flight <= 2


def test_fanout_branch_error_does_not_kill_batch():
    provider = FakeProvider(fail_tasks={"坏"})
    t = _tool(provider, FakeShellTool())
    r = _run(
        t.run(
            subtasks=[
                {"id": "good", "task": "正常任务"},
                {"id": "bad", "task": "坏任务会炸"},
            ]
        )
    )
    assert not r.is_error  # 单分支失败不拖垮整批
    assert "### good" in r.content and "结论(正常任务" in r.content
    assert "失败" in r.content
    states = {s["tool"]: s["state"] for s in r.sub_steps}
    assert states["fanout:good"] == "done"
    assert states["fanout:bad"] == "error"


class GuardedShellTool(FakeShellTool):
    """模拟真实 ShellTool 的高危扫描档位：consent_always 对破坏性/secret 引用返回 True。

    用于验证子 agent 在无授权弹窗时对这类命令直接拒绝、不静默执行。
    """

    def consent_always(self, command: str = "", **kwargs) -> bool:
        return "rm -rf" in command or "$SECRET" in command or command.startswith("sudo")


def test_fanout_rejects_dangerous_shell_without_executing():
    seen_tool_results = []

    class TwoRoundProvider(FakeProvider):
        async def chat(self, messages, tools=None, system=None, max_tokens=None):
            # 第一轮让模型发一个破坏性 shell + 一个只读 shell，第二轮回到文本
            if not any(m.role == "tool" for m in messages):
                return Message(
                    role="assistant",
                    content="",
                    tool_calls=[
                        ToolCall(id="bad", name="shell", arguments={"command": "rm -rf /tmp/x"}),
                        ToolCall(id="good", name="shell", arguments={"command": "gh api repos/x/y"}),
                    ],
                )
            # 第二轮（查证后）：把子 agent 看到的工具结果存下来，供断言拒绝反馈确实回填
            seen_tool_results.extend(m.content for m in messages if m.role == "tool")
            return Message(role="assistant", content="结论(已查证)")

    shell = GuardedShellTool()
    reg = ToolRegistry()
    reg.register(shell)
    t = TaskFanoutTool(provider=TwoRoundProvider(), tools=reg)
    r = _run(t.run(subtasks=[{"id": "S", "task": "扫描任务"}], max_turns=5))
    assert not r.is_error
    # 破坏性命令被执行器拒绝、从未进入 shell.run（不在 calls 里）；只读命令照常执行
    assert any("gh api" in c for c in shell.calls)
    assert not any("rm -rf" in c for c in shell.calls)
    assert len(shell.calls) == 1  # 只执行了那条只读命令
    # 拒绝反馈确实回填给了模型（不是静默丢弃）
    assert any("拒绝执行" in t for t in seen_tool_results)


def test_fanout_missing_conclusion_marked_error_not_done():
    """轮次耗尽、最终无 tools 收尾也拿不到结论 → 分支标 error 而非 done。"""

    class EmptyProvider(FakeProvider):
        async def chat(self, messages, tools=None, system=None, max_tokens=None):
            # 始终返回空文本（模拟子 agent 跑不出任何内容）
            return Message(role="assistant", content="", tool_calls=[])

    shell = FakeShellTool()
    reg = ToolRegistry()
    reg.register(shell)
    t = TaskFanoutTool(provider=EmptyProvider(), tools=reg)
    r = _run(t.run(subtasks=[{"id": "E", "task": "空任务"}], max_turns=3))
    states = {s["tool"]: s["state"] for s in r.sub_steps}
    assert states["fanout:E"] == "error"  # 占位符不冒充 done
    assert "空响应" in r.content


def test_fanout_final_summary_after_turns_exhausted():
    """max_turns 全耗在工具查证上时，补一次无 tools 收尾让模型做最终总结。"""
    shell = FakeShellTool()

    class AlwaysToolProvider(FakeProvider):
        def __init__(self):
            super().__init__()
            self.chats = []

        async def chat(self, messages, tools=None, system=None, max_tokens=None):
            # tools=None → 收尾总结，返回文本；否则模拟仍在发工具调用
            if tools is None:
                return Message(role="assistant", content="最终总结：问题定位到 utils.py")
            return Message(
                role="assistant",
                content="",
                tool_calls=[ToolCall(id="c", name="shell", arguments={"command": "true"})],
            )

    provider = AlwaysToolProvider()
    reg = ToolRegistry()
    reg.register(shell)
    t = TaskFanoutTool(provider=provider, tools=reg)
    r = _run(t.run(subtasks=[{"id": "V", "task": "验证任务"}], max_turns=2))
    states = {s["tool"]: s["state"] for s in r.sub_steps}
    assert states["fanout:V"] == "done"
    assert "最终总结：问题定位到 utils.py" in r.content  # 拿到真实结论而非占位符
    assert "无结论" not in r.content


def test_fanout_result_budget_truncates_combined_content():
    """汇合 content 受总预算约束：超长分支结论被截断，避免撑爆主 agent 上下文。"""
    shell = FakeShellTool()

    class BigConclusionProvider(FakeProvider):
        async def chat(self, messages, tools=None, system=None, max_tokens=None):
            if not any(m.role == "tool" for m in messages):
                return Message(
                    role="assistant",
                    content="",
                    tool_calls=[ToolCall(id="c", name="shell", arguments={"command": "true"})],
                )
            return Message(role="assistant", content="结论 " + "X" * 100_000)

    reg = ToolRegistry()
    reg.register(shell)
    t = TaskFanoutTool(provider=BigConclusionProvider(), tools=reg)
    r = _run(t.run(subtasks=[{"id": "B", "task": "大结论"}], max_turns=3, result_budget=8_000))
    assert len(r.content) < 8_000 + 2_000  # 总预算兜底（含头/每分支开销余量）
    assert "截断" in r.content


def test_fanout_cancel_closes_provider_in_finally(monkeypatch):
    """整批被取消（主会话中断）时，自建 provider 的 close 在 try/finally 里执行，不泄漏连接。"""
    closed = []

    class HangingProvider(FakeProvider):
        async def chat(self, messages, tools=None, system=None, max_tokens=None):
            await asyncio.sleep(3600)  # 挂住，等外部取消

        async def close(self):
            closed.append(True)

    def fake_create_provider():
        return HangingProvider()

    # provider=None → run() 内部走 create_provider() 且 close_provider=True，
    # 这样才能验证「自建 provider 由工具负责关」的 finally 语义。
    monkeypatch.setattr("ethan.providers.manager.create_provider", fake_create_provider)
    shell = FakeShellTool()
    reg = ToolRegistry()
    reg.register(shell)
    t = TaskFanoutTool(tools=reg)  # provider 不注入

    async def scenario():
        task = asyncio.create_task(t.run(subtasks=[{"id": "H", "task": "挂住任务"}]))
        await asyncio.sleep(0.05)  # 让 run() 进入 chat 挂起
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass  # 期待取消冒泡

    _run(scenario())
    assert closed  # finally 关掉了自建 provider


def test_fanout_respects_max_turns():
    class AlwaysToolProvider(FakeProvider):
        async def chat(self, messages, tools=None, system=None, max_tokens=None):
            return Message(
                role="assistant",
                content="",
                tool_calls=[ToolCall(id="c", name="shell", arguments={"command": "true"})],
            )

    shell = FakeShellTool()
    t = _tool(AlwaysToolProvider(), shell)
    r = _run(t.run(subtasks=[{"id": "loop", "task": "无限查证任务"}], max_turns=3))
    assert len(shell.calls) == 3  # 恰好 max_turns 轮后停
    assert "轮次上限" in r.content
