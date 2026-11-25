import logging
import time  # noqa: F401 -- compatibility re-export
from datetime import datetime  # noqa: F401 -- compatibility re-export

from ethan.core.config import get_config
from ethan.core.context_budget import compress_previous_round_tools, enforce_context_budget  # noqa: F401
from ethan.core.context_limit import (  # noqa: F401 -- module patch seams
    effective_input_budget,
    is_input_length_error,
    total_input_chars,
    trim_for_retry,
    trim_to_limit,
)
from ethan.core.routing import _get_route, _match_fast_rule, classify_instant, evaluate_route  # noqa: F401
from ethan.core.tool_format import (  # noqa: F401 -- compatibility re-exports
    _detail,
    _format_args,
    _preview,
    _with_intent_param,
    classify_tool,
    extract_entity_id,
    resolve_skill_category,
)
from ethan.memory.procedures import ProcedureStore
from ethan.providers.base import Message, ToolCall
from ethan.providers.manager import create_provider
from ethan.skills.registry import SkillRegistry
from ethan.tools.base import ToolResult  # noqa: F401 -- compatibility re-export
from ethan.tools.registry import ToolExecutor, ToolRegistry

logger = logging.getLogger(__name__)


# 回复质量判定与错误分类已拆到 ethan/core/reply_quality.py（条目 7）。
# 这里 re-export 保持旧引用路径（agent._is_degenerate_reply / agent_mod._is_image_error）可用。
from ethan.core.reply_quality import (  # noqa: E402,F401
    _IMAGE_ERROR_PATTERNS,
    _SYNTHETIC_USER_PREFIXES,
    _empty_reply_fallback_text,
    _is_degenerate_reply,
    _is_image_error,
    _is_retriable_connect_error,
    _is_synthetic_user_msg,
    _save_msg_images_to_files,
    _strip_images_from_messages,
)


class UsageStats:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_tokens: int = 0

    def add(self, usage: dict | None) -> None:
        if not usage:
            return
        self.input_tokens += usage.get("input", 0)
        self.output_tokens += usage.get("output", 0)
        # cache_read + cache_creation 两者都算入 cache_tokens 展示
        self.cache_tokens += usage.get("cache", 0) + usage.get("cache_read", 0) + usage.get("cache_creation", 0)


class Agent:
    def __init__(
        self,
        tool_registry: ToolRegistry | None = None,
        skill_registry: SkillRegistry | None = None,
        model: str | None = None,
        system: str | None = None,
        channel: str = "",
        user_id: str = "",
        mode: str = "",
    ):
        from ethan.core.context import set_user_id
        from ethan.core.paths import user_procedures_path

        config = get_config()
        if user_id:
            set_user_id(user_id)
        self._user_id = user_id or ""
        self._model = model
        self._provider = create_provider(model)
        self._lite_provider = None  # 懒加载：fast 路由用的 lite 模型 provider
        self._registry = tool_registry or ToolRegistry()
        self._executor = ToolExecutor(self._registry)
        self._skills = skill_registry
        self._procedures = ProcedureStore(path=user_procedures_path())
        self._max_iterations = config.defaults.max_tool_iterations
        self.usage = UsageStats()
        self.last_matched_skills: list[str] = []
        self._channel = channel
        self._mode = mode or ""
        self._system_files: dict[str, str] = {}
        # 渠道运行时上下文（如飞书主人身份），每次请求前可设置，注入 system prompt 末尾
        self.runtime_context: str = ""
        # 是否为主人：非主人时跳过记忆召回（隐私保护），由渠道层（如 lark_agent）设置
        self.is_owner: bool = True
        # 当前会话 ID（由路由层设置），用于 web_fetch 结果存文件的目录隔离
        self.session_id: str = ""
        # 运行检查点（条目 6）：每轮工具执行后更新的结构化运行快照。中断/超时时由
        # 路由层写入 messages.run_checkpoint，续跑时读回注入，避免从零重新推理。
        self._run_checkpoint: dict = {}
        self._load_system_files()

    @property
    def model(self) -> str:
        """当前使用的模型 ID（公开访问，避免外部直接读 _provider 私有属性）。"""
        return self._provider.model

    def _load_system_files(self) -> None:
        """启动时一次性读入 system 目录下的 md 文件，避免每次对话都做磁盘 I/O。"""
        from ethan.core.paths import system_dir as _system_dir
        from ethan.core.paths import user_profile_path

        cfg = get_config()
        workspace = cfg.defaults.workspace
        # system/*.md 全局共享（ethan 角色定义）；user_profile.md 按 profile 隔离
        # 这些文件全文进每次请求的 system prompt，超限截断（只拦读不改盘），
        # 防止 agent 自写/心跳追加把文件养到 MB 级吃掉整个上下文（线上 badcase：
        # tools.md 被心跳日志养到 1.7M 字符 ≈ 100 万 token）。
        from ethan.core.system_file_guard import guard_system_file_content

        system_dir = _system_dir()
        for name in ("identity", "soul", "agent", "tools"):
            p = system_dir / f"{name}.md"
            if p.exists():
                content = p.read_text(encoding="utf-8").strip()
                content = content.replace("{workspace}", workspace)
                self._system_files[name] = guard_system_file_content(content, name)

        profile_p = user_profile_path()
        if profile_p.exists():
            content = profile_p.read_text(encoding="utf-8").strip()
            self._system_files["user_profile"] = guard_system_file_content(content, "user_profile")

    def reload_system_files(self) -> None:
        """Settings 更新后调用，重新加载 system 文件缓存。"""
        self._load_system_files()


    def _build_schedule_context(self, workspace: str) -> str:
        from ethan.core.system_prompt import build_schedule_context
        return build_schedule_context(workspace)

    def _get_last_user_text(self, messages: list[Message]) -> str:
        from ethan.core.system_prompt import get_last_user_text
        return get_last_user_text(messages)

    def _persona_text(self, skill_names: tuple[str, ...]) -> str:
        from ethan.core.system_prompt import get_persona_text
        return get_persona_text(skill_names, self._skills)

    def _persona_block(self) -> str | None:
        from ethan.core.system_prompt import build_persona_block
        return build_persona_block(self._mode, self._skills)

    def _mode_identity_block(self) -> str | None:
        from ethan.core.system_prompt import build_mode_identity_block
        return build_mode_identity_block(self._mode)

    def _mode_install_hint(self, messages: list[Message] | None = None) -> str | None:
        from ethan.core.system_prompt import build_mode_install_hint
        return build_mode_install_hint(self._mode, self._skills, messages)

    def _build_previous_run_summary(self, messages: list[Message]) -> str | None:
        from ethan.core.system_prompt import build_previous_run_summary
        return build_previous_run_summary(messages)

    def _build_system(self, messages: list[Message], fast: bool = False, fast_rule=None) -> str:
        """构建 system prompt。委托给 system_prompt 模块。"""
        from ethan.core.system_prompt import build_system_prompt
        return build_system_prompt(
            messages=messages,
            fast=fast,
            fast_rule=fast_rule,
            system_files=self._system_files,
            provider_model=self._provider.model,
            skills=self._skills,
            procedures=self._procedures,
            registry=self._registry,
            channel=self._channel,
            mode=self._mode,
            is_owner=self.is_owner,
            runtime_context=self.runtime_context,
            last_matched_skills_out=self.last_matched_skills,
        )


    def route_for(self, messages: list[Message]) -> str:
        """返回路由档位 'fast' | 'full'，供渠道决定回复策略（如飞书 card vs post）。"""
        last_user = self._get_last_user_text(list(messages))
        self._route_decision = evaluate_route(last_user, self._skills, channel=self._channel, mode=self._mode)
        return self._route_decision.route

    def _select_route(self, messages: list[Message]) -> tuple[str, str, list, int]:
        """路由选择，返回 (route, system, tools_list, max_iters)。chat/stream_chat 共用。

        路由仅影响工具集和模型选择；迭代上限统一用 defaults.max_tool_iterations。
        """
        working = list(messages)
        # ── 精简模式：固定只用 MINIMAL_TOOLS 白名单工具、极简 system prompt ──
        # 不走 fast/full 的 keyword 路由，也不用 owner 专属的 recall_memory/deliver_file
        # （精简模式刻意「无记忆、不交付」）。
        from ethan.core.modes import resolve_mode

        if resolve_mode(self._mode).minimal:
            from ethan.core.modes import MINIMAL_TOOLS

            tools_list = [t for t in self._registry.all() if t.name in MINIMAL_TOOLS]
            system = self._build_system(working, fast=False)
            return "minimal", system, tools_list, get_config().defaults.max_tool_iterations

        last_user = self._get_last_user_text(working)
        self._route_decision = evaluate_route(last_user, self._skills, channel=self._channel, mode=self._mode)
        route = self._route_decision.route
        if self._route_decision.strength == "strong" and self._skills:
            from ethan.core.context import activate_tools

            skill_text = "\n".join(getattr(self._skills.get(name), "content", "")
                                   for name in self._route_decision.skill_names)
            referenced = [tool.name for tool in self._registry.all() if tool.name in skill_text]
            # Strong signals do not grant owner-only capabilities.
            if not self.is_owner:
                referenced = [name for name in referenced if name not in {"recall_memory", "deliver_file"}]
            activate_tools(referenced)
        routing = get_config().defaults.routing
        max_iters = get_config().defaults.max_tool_iterations
        if route == "fast":
            rule = _match_fast_rule(last_user, routing)
            wanted = set(routing.fast_base_tools) | (set(rule.tools) if rule else set())
            tools_list = [t for t in self._registry.all() if t.name in wanted]
            system = self._build_system(working, fast=True, fast_rule=rule)
        else:
            system = self._build_system(working, fast=False)
            wanted = set(routing.base_tools) if routing.base_tools else None
            tools_list = [t for t in self._registry.all() if t.name in wanted] if wanted else self._registry.all()
        # recall_memory / deliver_file：仅 owner 可用，按需调用（不在 config base_tools 里，
        # 避免非 owner 广播）。deliver_file 会把 home 下任意文件推成对外文件卡片，且
        # side_effect=False（ChannelGuardProvider 拦不住），无条件广播会让飞书非主人会话
        # 诱导模型交付任意文件——故与 recall_memory 同款，只在 owner 会话注入。
        # 放在 tools_list 前部，模型在需要时被使用的概率最大。
        if self.is_owner:
            for _name in ("deliver_file", "recall_memory"):
                _tool = self._registry.get(_name)
                if _tool and _tool not in tools_list:
                    tools_list.insert(0, _tool)
        return route, system, tools_list, max_iters

    async def _minimal_retry(self, working: list[Message]) -> str | None:
        """极简 prompt 重试：原始任务 + 最后一条真实 user 消息 + 禁工具，逼模型至少说一句话。

        只发「最后一条 user 消息」的老实现有个隐含假设——它就是用户当前的问题。
        但运行中注入的补充信息 / nudge 会被 append 成独立的 user 消息，成为 working
        里的最后一条 user；超大上下文触发空回复兜底时，模型只看到一行孤立的注入
        指令（如「[用户运行中补充]：别弄混了」），原始任务和历史全不在场，只能回复
        「没有任务上下文」（真实案例：PR review 会话跑了 18 步后失忆）。
        修复：过滤掉合成消息，取首条真实 user（原始任务）+ 末条真实 user，同一条则只发一条。

        返回非空内容字符串，或 None（重试失败/仍空）。供 _ensure_non_empty
        和 stream_chat 的各空回复兜底点共用。
        """
        try:
            real_users = [
                m for m in working if m.role == "user" and not _is_synthetic_user_msg(m.content or "")
            ]
            if not real_users:
                # 全是合成消息（极端情况）：退回旧的取法，至少给模型点什么
                last_user = next((m for m in reversed(working) if m.role == "user"), None)
                mini_msgs = [last_user] if last_user else []
            elif len(real_users) == 1:
                mini_msgs = [real_users[0]]
            else:
                first, last = real_users[0], real_users[-1]
                mini_msgs = [first] if first is last else [first, last]
            mini_sys = "请用中文简洁回答用户的问题。如果任务已完成，请总结你做了什么。如果遇到问题，请说明卡在哪里。"
            resp = await self._provider.chat(mini_msgs, tools=None, system=mini_sys)
            self.usage.add(resp.usage)
            return (resp.content or "").strip() or None
        except Exception:
            logger.warning("极简 prompt 重试失败", exc_info=True)
            return None

    async def _ensure_non_empty(self, response: Message, working: list[Message], monitor, reason: str) -> Message:
        """确保返回给用户的回复非空。

        当模型在 finalize / stuck / nudge_exhausted 轮返回空内容时（常见于超大上下文
        导致模型静默放弃），用极简 prompt 再试一次；仍空则合成原因专属兜底文案。

        reason: 触发原因，写入日志便于排查，也决定兜底文案措辞。
        """
        content = (response.content or "").strip()
        if content:
            return response

        logger.warning("chat() 返回空回复 (reason=%s)，尝试极简 prompt 重试", reason)
        retried = await self._minimal_retry(working)
        if retried:
            return Message(role="assistant", content=retried)

        logger.warning("极简重试仍空，合成兜底 (reason=%s)", reason)
        tool_calls = [m for m in working if m.role == "assistant" and m.tool_calls]
        return Message(role="assistant", content=_empty_reply_fallback_text(reason, len(tool_calls)))

    def _parse_stream_text_tool_calls(self, content: str) -> list:
        """stream_chat 中从文本解析工具调用。

        流式模式下，如果模型把工具调用写成文本，它会作为 delta.content
        流式返回，不会出现在 delta.tool_calls 里。此方法在 final chunk 后做一次检测。
        支持三种格式：
        1. Gemini call:xxx{args}
        2. DeepSeek DSML 标记
        3. Anthropic 风格 <invoke name="…"><parameter …>（无 DSML 前缀）
           —— 部分 anthropic 兼容网关在 function calling 退化时把原生 tool_use
           当正文文本下发。若不识别，这一轮就没有工具可执行，表现为「跑到一半不动了」。
        """
        import re
        import uuid

        # 优先检测 DSML 格式
        from ethan.providers.openai_compat import OpenAICompatProvider

        dsml_results = OpenAICompatProvider._parse_dsml_tool_calls(content)
        if dsml_results:
            return dsml_results

        # Anthropic 风格 invoke/parameter 标记（文本工具调用降级）
        from ethan.providers._text_toolcalls import parse_invoke_tool_calls

        invoke_results = parse_invoke_tool_calls(content)
        if invoke_results:
            return invoke_results

        pattern = re.compile(
            r"call:\w+:(?P<tool>\w+)\{(?P<args>[^}]*)\}"
            r"|call:(?P<tool2>\w+)\{(?P<args2>[^}]*)\}"
        )
        results = []
        for m in pattern.finditer(content):
            tool_name = m.group("tool") or m.group("tool2") or ""
            args_str = m.group("args") or m.group("args2") or ""
            if not tool_name:
                continue
            args = {}
            key_pattern = re.compile(r"(\w+):")
            key_positions = [(km.start(), km.group(1)) for km in key_pattern.finditer(args_str)]
            for i, (pos, key) in enumerate(key_positions):
                val_start = pos + len(key) + 1
                if i + 1 < len(key_positions):
                    val_end = key_positions[i + 1][0]
                else:
                    val_end = len(args_str)
                val = args_str[val_start:val_end].rstrip(",").strip()
                args[key] = val
            if args:
                results.append(
                    ToolCall(
                        id=f"call_{uuid.uuid4().hex[:8]}",
                        name=tool_name,
                        arguments=args,
                    )
                )
        return results

    def _broadcast_tools(self, tools_list: list):
        """每轮广播给模型的工具定义 = 基础 tools_list + 本请求 find_tools 已激活的长尾工具。

        每个定义注入 intent 参数（_with_intent_param）：让模型用几个字说明每次调用目的，
        供前端/飞书显示。标准 schema 参数，切模型安全；缺失时回退旧 args 摘要。
        """
        from ethan.core.context import get_active_tools

        base_names = {t.name for t in tools_list}
        active = get_active_tools()
        extra = [t for t in self._registry.all() if t.name in active and t.name not in base_names]
        defs = [t.to_definition() for t in (tools_list + extra)]
        return [_with_intent_param(d) for d in defs] or None

    def _build_all_skills_brief(self) -> str:
        """构建全量 skill 简表（含 frontmatter：name/description/trigger/category）。

        仅在模型主动要"更多信息"时调用，避免每轮 token 爆炸。
        """
        if not self._skills:
            return ""
        lines = []
        for s in self._skills.all():
            triggers = " | ".join(s.trigger[:5]) if s.trigger else ""
            cat = getattr(s, "category", "default")
            desc = (s.description or "")[:120]
            line = f"- {s.name} [{cat}]: {desc}"
            if triggers:
                line += f" | triggers: {triggers}"
            lines.append(line)
        return "\n".join(lines)

    async def _build_extended_memory(self, query: str, max_items: int = 30) -> str:
        """增强上下文用的记忆召回。

        仅在模型主动要"更多信息"时调用。max_items 是**候选预算**（宽召回），实际注入
        条数由判官切点或 `INJECT_MAX` 决定——这条路径本就最容易被噪声淹，30 条里通常
        只有 2-3 条与当前问题相关，所以**不要**把 fallback_keep 顶到 max_items，
        那等于把整个候选池原样灌进 prompt。
        """
        if not self.is_owner:
            return ""
        try:
            from ethan.memory.recall import build_structured_recall_async

            recall_result = await build_structured_recall_async(
                query=query,
                mode=self._mode,
                max_items=max_items,
            )
            return recall_result.text if recall_result else ""
        except Exception:
            return ""

    def _build_all_tools_brief(self) -> str:
        """构建全量工具简表（name + 一句话 desc，不含 schema）。

        仅在模型主动要"更多信息"时调用，避免每轮 token 爆炸。
        完整 schema 模型需要时可调 find_tools 拉取。
        """
        lines = []
        for t in self._registry.all():
            desc = (t.description or "")[:80]
            fast_tag = " [fast]" if getattr(t, "fast_path", False) else ""
            lines.append(f"- {t.name}{fast_tag}: {desc}")
        return "\n".join(lines)

    def _provider_for_route(self, route: str):
        """按路由档位选 provider。fast 档且开启 fast_use_lite_model 时用 lite 模型
        （设备控制/状态查询等简单任务，省钱提速），否则用主模型。lite provider 懒加载。

        例外：浏览器操作类 skill 触发了 fast 路由时，仍用主模型——
        lite 模型（如 gemini-flash）对复杂工具编排的指令遵循能力不足，
        会导致绕路（delegate_coding → Playwright → 超时）。

        创建 lite provider 失败时回退主模型，绝不返回 None。
        """
        routing = get_config().defaults.routing
        if route == "fast" and getattr(routing, "fast_use_lite_model", False):
            # 浏览器/桌面控制等复杂 skill 命中时，用主模型保证指令遵循
            _complex_skills = {"use-browser", "agent-browser", "computer-use"}
            if _complex_skills & set(self.last_matched_skills):
                return self._provider
            if self._lite_provider is None:
                try:
                    from ethan.memory.consolidator import get_lite_model

                    lite_model = get_lite_model(self._model)
                    # lite 与主模型相同则不必新建，直接复用主 provider
                    if lite_model and lite_model != self._provider.model:
                        self._lite_provider = create_provider(lite_model)
                    else:
                        self._lite_provider = self._provider
                except Exception:
                    logger.warning("创建 lite provider 失败，fast 档回退主模型", exc_info=True)
                    self._lite_provider = self._provider
            return self._lite_provider or self._provider
        return self._provider

    def _get_timeout_fallback(self, current_provider):
        """Get a fallback provider when the current one times out mid-stream."""
        from ethan.providers.fallback import FallbackProvider

        if isinstance(current_provider, FallbackProvider):
            next_p = current_provider.get_next_provider()
            if next_p is not None:
                return next_p

        fb_model = get_config().defaults.fallback_model
        if not fb_model:
            return None
        try:
            fb = create_provider(fb_model)
            if fb.model != current_provider.model:
                return fb
        except Exception:
            logger.warning("创建 timeout fallback provider 失败: %s", fb_model, exc_info=True)
        return None

    def _trim_input_if_needed(self, working: list[Message], system: str) -> int:
        """发送前全量输入长度预检：超预算就裁剪旧历史（proactive 防线）。

        `context_budget` 只管控 tool result 体积，user/assistant 正文与 system
        不设防——会话长期累积后单次请求可能超过上游硬限制（DashScope 系
        `Range of input length should be [1, 997952]`，直接 400）。这里按
        `effective_input_budget()`（默认留 5% 余量，环境变量可调）预检，
        超限即从最旧的轮次裁起，保 system + 最近历史。

        就地替换 working 列表内容（working 是 loop 的浅拷贝，session 历史
        不受影响）。返回被省略的字符数（0 = 未触发裁剪）。
        """
        budget = effective_input_budget()
        raw = total_input_chars(working, system)
        if not budget or raw <= budget:
            return 0
        trimmed, omitted = trim_to_limit(working, system, budget)
        if omitted:
            working[:] = trimmed
            logger.warning("输入超预算（%d 字 > 预算 %d 字），发送前裁剪较早历史 %d 字", raw, budget, omitted)
        return omitted

    async def _request_consent(self, description: str, tool: str, detail: str = "") -> bool:
        """请求用户授权。根据 channel 走不同 provider：
        - 无 provider（如 heartbeat）：放行
        - TUI：阻塞式 y/N
        - Web：yield ConsentEvent 后 await Future（由 stream_chat 处理，见下）
        Web 的流式注入在 stream_chat 内联处理（因为只有 generator 能 yield），
        这里只兜底处理非流式 chat() 的情况。
        """
        from ethan.core.consent import get_consent_provider

        provider = get_consent_provider()
        if provider is None:
            return True
        if provider.streamed:
            # 流式路径在 stream_chat 里内联处理；此处为非流式兜底，无法注入事件，默认放行
            return True
        return await provider.request(description, tool, detail)

    async def chat(self, messages: list[Message]) -> Message:
        """Return the terminal provider Message through the shared chat transport."""
        from ethan.core.agent_generation import ChatTransport
        from ethan.core.agent_loop import run_loop

        result = None
        async for event in run_loop(self, messages, ChatTransport()):
            if isinstance(event, Message):
                result = event
        result = result or Message(role="assistant", content="[max tool iterations reached]")
        result._wire_transcript = list(self._wire_transcript)
        return result

    async def stream_chat(self, messages: list[Message]):
        """Emit every generation round and interaction through the stream transport."""
        from ethan.core.agent_generation import StreamTransport
        from ethan.core.agent_loop import run_loop

        async for event in run_loop(self, messages, StreamTransport()):
            yield event
