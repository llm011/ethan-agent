"""Task Fanout Tool — 并行扇出 N 个独立子 agent，各自带只读工具循环跑完再汇合。

解决的问题：deep-review 这类「多镜头扫描 + 对抗式验证」流程天然是 N 个互相隔离、
可并行的子任务。此前 skill 写的是 Claude Code 式 Task 工具（ethan 不存在），模型只能
退化成自己串行跑几十个单工具轮次——每轮都付一次 LLM 首包 + 解码延迟（provider 侧
TTFB 可达 10-30s），31 步串行实测 25 分钟。

实现：每个 subtask 一个独立的轻量 agent 循环（无流式、无路由、无记忆/技能匹配）：
  provider.chat → 执行 tool_calls（shell/file_read/rg_search）→ 回填 → 下一轮，
  直到无工具调用或达到 max_turns。N 个循环 asyncio.gather 并发，信号量限流。
  子 agent 互不可见（独立 registry / 独立 executor 缓存），保证「独立视角」纪律。

安全口径（与主 agent 授权的区别）：扇出由主 agent 发起即视为已授权，子循环没有用户在场、
不弹 consent 弹窗。正因如此，子 agent 的执行面被刻意收窄：
  · 工具面只读向（shell / file_read / rg_search），不注册 file_write / browser 等重武器；
  · shell 命令执行前逐条过危险扫描——命中主循环「必弹授权」档位（破坏性 rm -rf / 提权 /
    下载管道执行 / env dump / secret 环境变量引用等，即 ShellTool.consent_always 的档位）
    直接拒绝，不静默放行；没有授权弹窗通道，这类命令在子 agent 里一律不可执行。
主 agent 对 task_fanout 本身走常规 consent，side_effect=True 让渠道主人守卫仍然生效。
"""

from __future__ import annotations

import asyncio
import logging
import time

from ethan.providers.base import Message
from ethan.tools.base import BaseTool, ToolResult
from ethan.tools.registry import ToolExecutor, ToolRegistry

logger = logging.getLogger(__name__)

# 子 agent 可用工具：只读向。shell 仅限查询类命令（深度 review 的 gh api 上下文补全 /
# 对抗式验证都靠它），不给 file_write / browser 等有副作用的工具。
SUBAGENT_TOOLS = ("shell", "file_read", "rg_search")

SUBAGENT_SYSTEM = (
    "你是一个执行单一子任务的独立扫描/验证 agent。规则：\n"
    "1. 只做分配给你的子任务，看不到也无需关心其他子任务。\n"
    "2. 只读不写：不修改文件、不运行项目代码、不 git clone / git checkout。\n"
    "3. 工具只用来查证（shell 仅限 gh api / grep / sed / ls 等只读命令），能少调就少调。\n"
    "4. 不要向用户提问。查不到的材料在结论里注明「缺失」。\n"
    "5. 直接输出最终结论（结构化、简洁），不要输出过程叙述。"
)

MAX_SUBTURNS_CAP = 16  # 单个子 agent 的轮次硬上限（防失控递归查证）
DEFAULT_MAX_TURNS = 8
DEFAULT_CONCURRENCY = 4
PER_CHAT_TIMEOUT_S = 300  # 单次 model chat 的墙钟超时（不是分支级兜底，见 _run_subagent）
BRANCH_BUDGET_S = 900  # 单个分支（整个子 agent 循环）的墙钟硬上限：兜底信号量排队+多轮 chat+工具
DEFAULT_RESULT_BUDGET = 50_000  # 最终汇合 content 的总预算（字符），超了按分支比例截断
TOOL_RESULT_CHAR_CAP = 24_000  # 子循环内单条工具结果截断，防撑爆子 agent 上下文
MAX_SUBTASKS = 24  # 一次扇出的子任务数上限


class TaskFanoutTool(BaseTool):
    fast_path = False  # 扇出是多轮委托场景，不在 fast path 加载
    cacheable = False
    side_effect = True  # 子 agent 含 shell，保守标副作用，渠道主人守卫仍生效
    name = "task_fanout"
    description = (
        "并行扇出多个独立子任务，每个子任务在一个隔离的轻量子 agent（带 shell/file_read/rg_search "
        "只读工具）里完整执行后汇合返回。适用：code review 深度模式的多维度扫描与对抗式验证、"
        "多方案独立评估等「N 个互相独立、可并行、需工具查证」的场景。"
        "子 agent 之间互相不可见，每个子任务必须自包含全部材料路径与输出要求。"
        "这类子任务逐个串行跑会让墙钟时间成倍放大——务必在一次调用里把所有子任务全部发起。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "subtasks": {
                "type": "array",
                "description": f"子任务清单（2-{MAX_SUBTASKS} 个），全部并行执行。",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string", "description": "短标识，如 D-正确性 / V-F1"},
                        "task": {"type": "string", "description": "完整子任务指令（自包含）"},
                    },
                    "required": ["id", "task"],
                },
            },
            "max_turns": {
                "type": "integer",
                "description": f"每个子 agent 的最大工具轮次（默认 {DEFAULT_MAX_TURNS}，上限 {MAX_SUBTURNS_CAP}）",
                "default": DEFAULT_MAX_TURNS,
            },
            "concurrency": {
                "type": "integer",
                "description": f"并行上限（默认 {DEFAULT_CONCURRENCY}）",
                "default": DEFAULT_CONCURRENCY,
            },
        },
        "required": ["subtasks"],
    }

    def __init__(self, user_id: str = "", provider=None, tools: ToolRegistry | None = None):
        self._user_id = user_id
        # provider / tools 可注入（测试用）；默认运行时取全局默认模型与全量注册表
        self._injected_provider = provider
        self._injected_tools = tools

    def _resolve_tools(self) -> ToolRegistry:
        if self._injected_tools is not None:
            source: ToolRegistry = self._injected_tools
        else:
            from ethan.core.agent_factory import build_tool_registry

            source = build_tool_registry(user_id=self._user_id)
        registry = ToolRegistry()
        for name in SUBAGENT_TOOLS:
            tool = source.get(name)
            if tool is not None:
                registry.register(tool)
        return registry

    async def run(
        self,
        subtasks: list[dict],
        max_turns: int = DEFAULT_MAX_TURNS,
        concurrency: int = DEFAULT_CONCURRENCY,
        result_budget: int = DEFAULT_RESULT_BUDGET,
    ) -> ToolResult:
        items = [s for s in (subtasks or []) if isinstance(s, dict) and s.get("task")]
        if not items:
            return ToolResult(tool_call_id="", content="task_fanout：subtasks 为空，未执行。", is_error=True)
        if len(items) > MAX_SUBTASKS:
            items = items[:MAX_SUBTASKS]
        max_turns = max(1, min(int(max_turns or DEFAULT_MAX_TURNS), MAX_SUBTURNS_CAP))
        concurrency = max(1, min(int(concurrency or DEFAULT_CONCURRENCY), len(items)))

        registry = self._resolve_tools()
        if not registry.all():
            return ToolResult(tool_call_id="", content="task_fanout：子 agent 工具集为空，未执行。", is_error=True)
        defs = [t.to_definition() for t in registry.all()]

        provider = self._injected_provider
        close_provider = False
        if provider is None:
            from ethan.providers.manager import create_provider

            provider = create_provider()
            close_provider = True

        sem = asyncio.Semaphore(concurrency)
        budget = max(8_000, int(result_budget or DEFAULT_RESULT_BUDGET))

        async def guarded(sid: str, task_text: str) -> dict:
            async with sem:
                started = time.monotonic()
                status, content = "done", ""
                try:
                    # 分支级墙钟硬上限：整个子 agent 循环（信号量排队 + 多轮 chat + 工具）
                    # 超过 BRANCH_BUDGET_S 即终止，避免慢分支（provider 慢 + 子 agent 多轮
                    # 查证）无限拖住整批 gather。
                    content, has_conclusion = await asyncio.wait_for(
                        self._run_subagent(provider, defs, registry, task_text, max_turns),
                        timeout=BRANCH_BUDGET_S,
                    )
                    # 只跑出占位符（空响应 / 轮次耗尽仍无结论）的分支标 error，
                    # 让主 agent 区分「正常完成」与「没跑出结果」，不至于把占位符当结论用。
                    status = "done" if has_conclusion else "error"
                    if not has_conclusion:
                        logger.warning("task_fanout 子任务 %s 无结论（占位符）", sid)
                except asyncio.TimeoutError:
                    content = "(子任务超时被终止)"
                    status = "timeout"
                except Exception as e:
                    # 单分支失败不拖垮整批。整批取消（CancelledError 继承 BaseException，
                    # 不进 except Exception）会自然冒泡，由外层 try/finally 关 provider。
                    logger.warning("task_fanout 子任务 %s 失败: %s", sid, e)
                    content = f"(子任务执行失败：{e})"
                    status = "error"
                elapsed_ms = int((time.monotonic() - started) * 1000)
                logger.info("task_fanout[%s] %s %dms len=%d", sid, status, elapsed_ms, len(content))
                return {"id": sid, "status": status, "elapsed_ms": elapsed_ms, "content": content}

        try:
            # return_exceptions=True：让单个分支被取消（如被分支预算终止）时，其它已完成
            # 分支的结果不被 gather 丢掉；真正的整批取消（CancelledError）仍会冒泡。
            outs = await asyncio.gather(
                *(guarded(s.get("id") or f"T{i + 1}", s["task"]) for i, s in enumerate(items)),
                return_exceptions=True,
            )
            outs = [
                o
                if isinstance(o, dict)
                else {"id": f"T{i + 1}", "status": "error", "elapsed_ms": 0, "content": f"(子任务异常：{o})"}
                for i, o in enumerate(outs)
            ]
        finally:
            if close_provider:
                await provider.close()

        ok = sum(1 for o in outs if o["status"] == "done")
        # 汇合 content 设总预算：24 个分支 × 完整结论（甚至带大段工具结果）轻松撑爆主 agent
        # 单条工具结果上限，这里按分支数分预算，超预算对每分支结论再截断。
        header = f"## 扇出完成：{ok}/{len(outs)} 成功\n"
        usable = max(budget - len(header) - 80 * len(outs), 8_000)
        parts = [header]
        for o in outs:
            body = o["content"]
            if len(body) > usable:
                half = usable // 2
                body = f"{body[:half]}\n…(分支结论过长，已按总预算截断)…\n{body[-half:]}"
            parts.append(f"### {o['id']}\n状态：{o['status']} · 耗时 {o['elapsed_ms'] / 1000:.1f}s\n\n{body}\n")
        sub_steps = [
            {
                "tool": f"fanout:{o['id']}",
                "state": "done" if o["status"] == "done" else "error",
                "duration_ms": o["elapsed_ms"],
            }
            for o in outs
        ]
        return ToolResult(tool_call_id="", content="\n".join(parts), sub_steps=sub_steps)

    async def _run_subagent(
        self,
        provider,
        defs: list,
        registry: ToolRegistry,
        task_text: str,
        max_turns: int,
    ) -> tuple[str, bool]:
        """跑一个子 agent 循环，返回 (content, has_conclusion)。

        has_conclusion=False 表示产出的是占位符（空响应 / 轮次耗尽仍无结论），
        由调用方标记成 error，让主 agent 能区分「分支正常完成」与「分支没跑出结果」。
        """
        executor = ToolExecutor(registry)
        messages: list[Message] = [Message(role="user", content=task_text)]
        final = ""
        exhausted = False  # 是否因跑满 max_turns 仍停留在工具调用而退出循环
        try:
            for _ in range(max_turns):
                resp = await asyncio.wait_for(
                    provider.chat(messages, tools=defs or None, system=SUBAGENT_SYSTEM),
                    timeout=PER_CHAT_TIMEOUT_S,
                )
                if not resp.is_tool_call:
                    content = (resp.content or "").strip()
                    return (content or "(子 agent 空响应)", bool(content))
                if resp.content:
                    final = resp.content
                messages.append(resp)
                # 子 agent 无授权弹窗通道：执行 shell 前逐条过 ShellTool 的高危扫描档位
                # （破坏性 / 提权 / 管道执行 / env dump / secret 环境变量引用）。
                # 命中即拒绝并回填给模型，绝不静默执行——这类命令在主循环里必弹窗，
                # 子循环里没有用户可拍板，只能拒绝。
                rejected, results = await self._exec_tool_calls(executor, registry, resp.tool_calls)
                for r in rejected:
                    messages.append(Message(role="tool", content=r.content, tool_call_id=r.tool_call_id))
                for r in results:
                    content = r.content or ""
                    if len(content) > TOOL_RESULT_CHAR_CAP:
                        half = TOOL_RESULT_CHAR_CAP // 2
                        content = f"{content[:half]}\n…(中段过长已截断)…\n{content[-half:]}"
                    messages.append(Message(role="tool", content=content, tool_call_id=r.tool_call_id))
            exhausted = True
        except asyncio.TimeoutError:
            raise

        # 跑满 max_turns 仍停留在工具调用（每轮都在查证，没轮到总结）：
        # 补一次无 tools 的收尾 chat，让模型基于已回填的工具材料做最终总结。
        if exhausted:
            try:
                final_resp = await asyncio.wait_for(
                    provider.chat(messages, tools=None, system=SUBAGENT_SYSTEM),
                    timeout=PER_CHAT_TIMEOUT_S,
                )
                summary = (final_resp.content or "").strip()
                if summary:
                    return (summary, True)
            except asyncio.TimeoutError:
                raise
        return ((final.strip() + "\n(达到子 agent 轮次上限，以上是当前结论)") if final.strip() else "(达到轮次上限，无结论)", bool(final.strip()))

    async def _exec_tool_calls(self, executor, registry, tool_calls):
        """把一次 resp 的 tool_calls 拆成「被高危拒绝的」与「正常执行的」两组。

        返回 (rejected: list[ToolResult], results: list[ToolResult])。
        shell 命令命中 ShellTool.consent_always（高危档位）→ 拒绝；其余照常执行。
        """
        shell_tool = registry.get("shell") if registry else None
        reject = []
        allow = []
        for tc in tool_calls:
            if tc.name == "shell" and shell_tool is not None and getattr(shell_tool, "consent_always", None):
                try:
                    need_consent = shell_tool.consent_always(**tc.arguments)
                except Exception:
                    need_consent = False
                if need_consent:
                    cmd = (tc.arguments or {}).get("command", "")[:200]
                    reject.append(
                        ToolResult(
                            tool_call_id=tc.id,
                            content=f"拒绝执行该 shell 命令（子 agent 无授权弹窗，高危命令不可执行）：{cmd}",
                            is_error=True,
                        )
                    )
                    continue
            allow.append(tc)
        if not allow:
            return reject, []
        return reject, await executor.execute(allow)
