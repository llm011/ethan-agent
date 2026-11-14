"""Kernel Runtime — 可插拔 Agent 运行时的统一适配层。

## 为什么是「事件流」而不是「ABC」

上一版 `ethan/kernel/` 抽象成了 `execute_task(task_id, prompt, context) -> Any`，
这个接口包不住真实需求：agent 运行时要做的是**多轮工具循环 + 流式事件 + 中途授权**，
一个返回最终 `Any` 的函数表达不了「工具跑到一半要问用户」这类事。所以那套代码写了
1318 行，全部是 TODO + `return {"status": "success"}` 的假数据，零引用。

本层换一个思路：**不抽象执行流程，只抽象事件词表。**

关键事实：项目里早就存在一个稳定的事件契约——`Agent.stream_chat()` 的产出：

    str                 正文增量
    ThinkingEvent       思考中
    ToolEvent           工具 start/done/error
    InjectEvent         运行中补充信息
    SkillsMatchedEvent  命中的技能
    ConsentEvent        请求授权（consumer 弹窗，await Future）
    AskUserEvent        / WaitForUserEvent  中断式交互

上游 `producers.py` 消费这套事件 → 转 SSE → 前端 `ToolTimeline` 渲染。
ACP 层（`ethan/acp/`）也已经证明了这条路可行——它跑 Claude Code / Codex /
OpenCode 三个外部 CLI，`on_event(type, data)` 只产 `step` / `text` 两种事件，
`mirror.py` 里几十行就映射成了同一套 SSE 词表。

所以本层做的事：**任何内核（原生 Ethan、Claude Code、未来的其他 runtime）只要按
`stream_chat` 的事件词表产出，上层就完全不用改。** 适配成本被压到最小。

## 分工

    KernelRuntime          只管「接收 messages，产出事件流」
      ├── EthanKernel      直接委托现有 Agent（零行为变化，默认）
      └── ClaudeCodeKernel 委托 ACP → claude CLI，把 step/text 映射成事件

工具、技能、记忆、授权策略这些**不属于内核**——它们由 Ethan 侧统一提供，
内核如果需要（比如工具要暴露给外部 CLI）通过 `KernelContext` 拿。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, AsyncIterator, Optional

logger = logging.getLogger(__name__)


class KernelKind(str, Enum):
    """已知内核类型。

    用 str 枚举而非纯字符串：配置里写 "claude_code" 能直接比较，
    序列化到 JSON / 写进 config.yaml 也不需要额外转换。
    """

    ETHAN = "ethan"                # 原生 Ethan 运行时（默认，永远可用的兜底）
    CLAUDE_CODE = "claude_code"    # Claude Code CLI（经 ACP）
    CODEX = "codex"                # Codex CLI（经 ACP）
    OPENCODE = "opencode"          # OpenCode CLI（经 ACP）

    @classmethod
    def parse(cls, raw: str, default: "KernelKind" = None) -> "KernelKind":
        """宽松解析：接受枚举值、枚举名、大小写混写。无法识别时返回 default。"""
        if isinstance(raw, cls):
            return raw
        text = (raw or "").strip().lower().replace("-", "_")
        for kind in cls:
            if text in (kind.value, kind.name.lower()):
                return kind
        if default is not None:
            return default
        raise ValueError(f"unknown kernel: {raw!r} (known: {[k.value for k in cls]})")


@dataclass
class KernelCapabilities:
    """内核能力声明——用于路由决策和 UI 展示，不参与执行。

    写清楚每个内核能做什么、不能做什么，比让调用方去 `hasattr` 探测可靠得多。
    """

    streaming: bool = True       # 是否支持流式增量输出
    tools: bool = True           # 是否有工具调用能力
    # 是否支持「执行中途向用户请求授权」。Claude Code 走 `--dangerously-skip-permissions`，
    # 它自己的权限模型和 Ethan 的 consent 是两套东西，无法对齐 → False。
    consent: bool = True
    # 是否沿用 Ethan 的技能/记忆/系统提示词。外部 runtime 有自己的系统提示词，
    # 强行注入会打架 → False 的内核只接收原始用户输入。
    ethan_context: bool = True
    # 会话续接能力（同一 cwd 下多轮对话延续上下文）
    resumable: bool = False


@dataclass
class KernelRequest:
    """一次内核调用的输入。

    刻意只放「内核真正需要的东西」：`session` 侧的 user_id / channel / mode 放这里，
    但工具注册表、技能注册表这类重对象走 `KernelContext`——因为外部内核用不上它们。
    """

    messages: list = field(default_factory=list)
    user_id: str = ""
    channel: str = ""
    mode: str = ""
    session_id: str = ""
    # 工作目录：外部 coding runtime 靠它定位项目；原生内核靠它做相对路径解析
    working_dir: str = ""
    # 任务类型提示，供「按任务选内核」的路由用（如 "coding" / "chat" / "research"）
    task_kind: str = ""


@dataclass
class KernelContext:
    """内核可选的 Ethan 侧资源。外部内核可以完全不碰这些字段。"""

    # 调用方已经建好的 Agent 实例。
    #
    # 这个字段至关重要：Agent 上挂着一堆**请求级状态**——session_id、runtime_context、
    # is_owner、_executor.current_run（外部取消工具调用要靠它）、已加载的 system_files、
    # 复用的 tool/skill registry。EthanKernel 必须直接用这个实例，绝不能自己新建一个，
    # 否则这些状态全丢，表现为「会话串了 / 工具取消不生效 / 记忆召回错人」。
    agent: Any = None
    tool_registry: Any = None
    skill_registry: Any = None
    system_prompt: str = ""
    runtime_context: str = ""
    # 授权提供者：内核需要用户授权时通过它拿决策（外部内核通常不用）
    consent_provider: Any = None


@dataclass
class KernelStats:
    """单次调用的可观测数据——用于「对比不同内核效果/性能」。"""

    kernel: str = ""
    elapsed_ms: int = 0
    tool_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    error: str = ""

    def to_dict(self) -> dict:
        return {
            "kernel": self.kernel,
            "elapsed_ms": self.elapsed_ms,
            "tool_calls": self.tool_calls,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "error": self.error,
        }


class KernelRuntime:
    """内核运行时基类。

    只有一个必须实现的方法：`run()`。它接收 `KernelRequest`，产出
    **与 `Agent.stream_chat` 同构的事件流**（str / ThinkingEvent / ToolEvent / ...）。

    刻意不把 `run()` 设成 abstractmethod：基类本身要能作为「什么都不做」的占位
    被实例化来测试上层，缺失实现时应该给出清晰错误而不是 TypeError。
    """

    kind: KernelKind = KernelKind.ETHAN
    display_name: str = "Ethan"
    capabilities: KernelCapabilities = KernelCapabilities()

    def available(self) -> tuple[bool, str]:
        """能否在当前环境运行。返回 (可用, 不可用原因)。

        调用方在切换内核前必须先问这个——用户选了 claude_code 但机器上没装
        `claude` CLI 时，应该明确告知并回退，而不是跑到一半报错。
        """
        return True, ""

    async def run(
        self,
        request: KernelRequest,
        context: KernelContext | None = None,
    ) -> AsyncIterator[Any]:
        """产出事件流。子类必须覆写。"""
        raise NotImplementedError(f"{type(self).__name__} 未实现 run()")
        # 让类型检查器知道这是异步生成器
        yield  # pragma: no cover

    async def close(self) -> None:
        """释放资源。默认无事可做。"""
        return None


class KernelRegistry:
    """内核注册表 + 选择逻辑。

    选择顺序（见 `resolve`）：
      1. 显式指定（请求级 / 会话级）—— 用户手动切了就听用户的
      2. 按任务类型的规则（config 里的 `kernel.task_rules`）
      3. 全局默认（`kernel.default`）
      4. 兜底：Ethan 原生（永远可用）

    任何一步选出的内核若 `available()` 为 False，就告警并继续往下退——
    **绝不能因为选了个没装的内核而让整个对话失败。**
    """

    def __init__(self) -> None:
        self._runtimes: dict[KernelKind, KernelRuntime] = {}

    def register(self, runtime: KernelRuntime) -> None:
        self._runtimes[runtime.kind] = runtime

    def get(self, kind: KernelKind) -> KernelRuntime | None:
        return self._runtimes.get(kind)

    def all(self) -> dict[KernelKind, KernelRuntime]:
        return dict(self._runtimes)

    def resolve(
        self,
        explicit: KernelKind | str | None = None,
        task_kind: str = "",
        task_rules: dict[str, str] | None = None,
        default: KernelKind | str | None = None,
    ) -> KernelRuntime:
        """按优先级选出可用内核。总有返回值（最差回退到原生）。"""
        candidates: list[KernelKind] = []

        def _push(raw) -> None:
            if raw is None or raw == "":
                return
            try:
                kind = KernelKind.parse(raw)
            except ValueError:
                logger.warning("配置里有未知内核名 %r，已忽略", raw)
                return
            if kind not in candidates:
                candidates.append(kind)

        _push(explicit)
        if task_kind and task_rules:
            _push(task_rules.get(task_kind))
        _push(default)
        _push(KernelKind.ETHAN)  # 兜底

        for kind in candidates:
            runtime = self._runtimes.get(kind)
            if runtime is None:
                logger.warning("内核 %s 未注册，跳过", kind.value)
                continue
            ok, reason = runtime.available()
            if not ok:
                logger.warning("内核 %s 不可用（%s），跳过", kind.value, reason)
                continue
            return runtime

        # 理论上到不了这里（ETHAN 是兜底），防御性返回一个空运行时
        logger.error("没有任何可用内核，返回占位运行时")
        return KernelRuntime()

    def list_status(self) -> list[dict]:
        """供 UI / 诊断：列出所有已注册内核及其可用性。"""
        out = []
        for kind, rt in self._runtimes.items():
            ok, reason = rt.available()
            out.append({
                "kind": kind.value,
                "name": rt.display_name,
                "available": ok,
                "reason": reason,
                "capabilities": {
                    "streaming": rt.capabilities.streaming,
                    "tools": rt.capabilities.tools,
                    "consent": rt.capabilities.consent,
                    "ethan_context": rt.capabilities.ethan_context,
                    "resumable": rt.capabilities.resumable,
                },
            })
        return out


# 进程级单例
_registry: Optional[KernelRegistry] = None


def get_kernel_registry() -> KernelRegistry:
    """取全局内核注册表，首次调用时注册内置内核。"""
    global _registry
    if _registry is not None:
        return _registry

    from ethan.kernel.ethan_kernel import EthanKernel

    registry = KernelRegistry()
    registry.register(EthanKernel())

    # 外部 runtime 按需注册：导入失败（缺依赖/缺 CLI）不该影响启动，
    # 由各自 available() 报告原因。
    try:
        from ethan.kernel.claude_kernel import ClaudeCodeKernel

        registry.register(ClaudeCodeKernel())
    except Exception:  # pragma: no cover - 环境差异
        logger.debug("ClaudeCodeKernel 注册失败", exc_info=True)

    for kind, module_path, class_name in (
        (KernelKind.CODEX, "ethan.kernel.acp_kernel", "CodexKernel"),
        (KernelKind.OPENCODE, "ethan.kernel.acp_kernel", "OpenCodeKernel"),
    ):
        try:
            import importlib

            mod = importlib.import_module(module_path)
            registry.register(getattr(mod, class_name)())
        except Exception:  # pragma: no cover - 环境差异
            logger.debug("%s 注册失败", kind.value, exc_info=True)

    _registry = registry
    return _registry


def reset_kernel_registry() -> None:
    """清空单例（测试用）。"""
    global _registry
    _registry = None
