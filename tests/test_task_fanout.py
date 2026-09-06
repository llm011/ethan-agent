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
