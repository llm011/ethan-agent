import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from ethan.core.config import get_config
from ethan.core.context_budget import compress_previous_round_tools, enforce_context_budget
from ethan.core.routing import _get_route, _match_fast_rule, classify_instant
from ethan.core.tool_format import (
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
from ethan.tools.base import ToolResult
from ethan.tools.registry import ToolExecutor, ToolRegistry

logger = logging.getLogger(__name__)


# 图片类 400 错误：匹配 provider error code 和明确的尺寸超限措辞。
# 排除 'image size'（太模糊，rate-limit 消息可能包含），保留其他常见措辞。
# 另含 non-VLM 模型收到 image_url 时的反序列化错误（unknown variant image_url）。
_IMAGE_ERROR_PATTERNS = (
    "image_dimension_exceeded",
    "image too large",
    "image dimension",
    "dimensions exceed",
    "dimensions exceeded",
    "max allowed size",
    "图片过大",
    "图片尺寸",
    "unknown variant",  # non-VLM 模型拒绝 image_url content block
    "unknown variant `image_url`",  # image_url 反序列化失败（精确匹配反序列化错误）
    "image_url, expected",
    # Anthropic 协议中转网关（如 Console Go）校验失败格式
    "input should be a valid string",
    "should be a valid string",
    "valid string, field",
)


def _is_image_error(e: Exception) -> bool:
    """判断异常是否为图片相关错误（尺寸超限 / non-VLM 模型拒绝 image_url）。"""
    msg = str(e).lower()
    return any(p in msg for p in _IMAGE_ERROR_PATTERNS)


def _save_msg_images_to_files(msg: Message, session_id: str) -> list[str]:
    """把消息中的图片写入本地文件，返回绝对路径列表。

    支持 {data: base64} 格式（工具截图）和 {path: ...} 格式（已持久化的历史图片）。
    """
    from ethan.core.assets import image_file_path, save_image

    sid = session_id or "no_session"
    paths: list[str] = []
    for idx, img in enumerate(msg.images):
        data = img.get("data", "")
        media_type = img.get("media_type", "image/png")
        if data:
            # save_image 返回 [(路径, media_type), ...]，长图会返回多段
            for rel_path, _ in save_image(sid, idx, data, media_type):
                paths.append(str(image_file_path(rel_path)))
        elif "path" in img:
            paths.append(str(image_file_path(img["path"])))
    return paths


def _strip_images_from_messages(messages: list[Message], session_id: str = "") -> bool:
    """把消息中的图片写入本地文件，并从上下文中移除内联图片数据。

    用于：
    - 模型不支持 VLM 时（proactive，调 provider 前做）
    - provider 因图片超限 / non-VLM 拒绝返回 400 时（reactive）

    图片写文件后，在 content 中附 [image_paths: ...] 路径提示，模型可通过
    file_read / shell 工具读取本地文件自行处理。

    **不会 mutate 原 Message 对象**：对含图片的消息用 dataclasses.replace 创建浅拷贝，
    替换到 messages 列表中，确保 session 历史不受影响。
    返回 True 表示至少处理了一张图片。
    """
    from dataclasses import replace  # noqa: PLC0415

    stripped = False
    for i, msg in enumerate(messages):
        if not msg.images:
            continue
        stripped = True
        saved_paths = _save_msg_images_to_files(msg, session_id)
        if saved_paths:
            hint = (
                "\n\n[系统提示：附图已从上下文中移除并保存为本地文件"
                f"（image_paths: {', '.join(saved_paths)}）。"
                "可使用 file_read 或 shell 工具读取/查看。]"
            )
        else:
            hint = "\n\n[系统提示：附图已从上下文中移除。]"
        messages[i] = replace(msg, images=[], content=(msg.content or "") + hint)
    return stripped


def _empty_reply_fallback_text(reason: str, tool_call_count: int) -> str:
    """空回复兜底文案。reason: 'stuck' | 'nudge_exhausted' | 'varied' | 'finalize'。

    只有 finalize（max_iters 达限）才会提到步数限制；stuck/nudge_exhausted 在达限前
    触发，不应谎称步数限制。tool_call_count 为 0 时不报步数（零工具调用报步数无意义）。
    """
    n = tool_call_count
    if n == 0:
        # 零工具调用时报步数/轮数无意义，统一给一句中性兜底（保留原因描述）
        if reason == "stuck":
            return "在当前任务上尝试了多种策略仍未突破，未能生成最终回复。"
        if reason == "nudge_exhausted":
            return "模型多次返回空回复，未能生成最终回复。可能上下文过大或模型异常，请重试。"
        return "任务执行完毕但未生成回复。可能上下文过大或模型异常，请重试。"
    if reason == "varied":
        return f"已经连续执行了 {n} 轮批量操作，先到这里。你可以看看当前效果，需要继续的话告诉我。"
    if reason == "stuck":
        return (
            f"在当前任务上尝试了多种策略仍未突破，未能生成最终回复。已执行 {n} 轮工具调用。\n\n"
            "建议：检查工具调用是否有权限/网络问题，或拆分任务重试。"
        )
    if reason == "nudge_exhausted":
        return f"模型多次返回空回复，未能生成最终回复。已执行 {n} 轮工具调用。\n\n建议：精简上下文后重试，或拆分任务。"
    # finalize（max_iters 达限）——唯一提步数限制的原因
    return f"已达到最大执行步数限制。任务执行了 {n} 轮工具调用，未能生成最终回复。"


@dataclass
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
        self._load_system_files()

    @property
    def model(self) -> str:
        """当前使用的模型 ID（公开访问，避免外部直接读 _provider 私有属性）。"""
        return self._provider.model

    def _load_system_files(self) -> None:
        """启动时一次性读入 system 目录下的 md 文件，避免每次对话都做磁盘 I/O。"""
        from ethan.core.paths import user_profile_path

        cfg = get_config()
        workspace = cfg.defaults.workspace
        # system/*.md 全局共享（ethan 角色定义）；user_profile.md 按 profile 隔离
        system_dir = Path(workspace) / "system"
        for name in ("identity", "soul", "agent", "tools"):
            p = system_dir / f"{name}.md"
            if p.exists():
                content = p.read_text(encoding="utf-8").strip()
                content = content.replace("{workspace}", workspace)
                self._system_files[name] = content

        profile_p = user_profile_path()
        if profile_p.exists():
            self._system_files["user_profile"] = profile_p.read_text(encoding="utf-8").strip()

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
        skill_triggers = [kw for s in (self._skills.all() if self._skills else []) if s.fast_path for kw in s.trigger]
        return _get_route(last_user, skill_triggers=skill_triggers)

    def _select_route(self, messages: list[Message]) -> tuple[str, str, list, int]:
        """路由选择，返回 (route, system, tools_list, max_iters)。chat/stream_chat 共用。

        路由仅影响工具集和模型选择；迭代上限统一用 defaults.max_tool_iterations。
        """
        working = list(messages)
        last_user = self._get_last_user_text(working)
        skill_triggers = [kw for s in (self._skills.all() if self._skills else []) if s.fast_path for kw in s.trigger]
        route = _get_route(last_user, skill_triggers=skill_triggers)
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
        """极简 prompt 重试：只给最后一条 user 消息 + 禁工具，逼模型至少说一句话。

        返回非空内容字符串，或 None（重试失败/仍空）。供 _ensure_non_empty
        和 stream_chat 的各空回复兜底点共用。
        """
        try:
            last_user = next((m for m in reversed(working) if m.role == "user"), None)
            mini_msgs = [last_user] if last_user else []
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
        支持两种格式：
        1. Gemini call:xxx{args}
        2. DeepSeek DSML 标记
        """
        import re
        import uuid

        # 优先检测 DSML 格式
        from ethan.providers.openai_compat import OpenAICompatProvider

        dsml_results = OpenAICompatProvider._parse_dsml_tool_calls(content)
        if dsml_results:
            return dsml_results

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
        """运行对话。fast/full 两档路由，按关键词规则自动选择。"""
        from ethan.core.context import reset_active_tools

        self._executor.reset_cache()
        reset_active_tools()  # 清空本请求的 find_tools 激活集
        working = list(messages)
        from ethan.core.artifacts import inject_artifacts_prompt

        inject_artifacts_prompt(working)  # 注入本会话已生成/交付的文件清单，供后续轮次直接引用
        enforce_context_budget(working)  # 历史 tool result 也可能很大，进循环前先管控
        compress_previous_round_tools(working, self.session_id)  # 压缩上一轮 search/fetch 结果
        _route, system, tools_list, max_iters = self._select_route(working)
        provider = self._provider_for_route(_route)

        from ethan.core.loop_control import (
            LoopMonitor,
            decision_prompt_message,
            detect_implicit_decision,
            enhanced_context_message,
            extract_decision_choice,
            finalize_system_suffix,
            is_decision_call,
            reflection_followup_message,
            reflection_message,
            should_trigger_decision,
        )

        monitor = LoopMonitor()
        pending_suffix = ""  # 反思提示，仅附加到「下一轮」的 system，附完即清
        _need_enhanced_context = False  # 上一轮模型响应是否提到"需要更多信息"
        _decision_prompt_injected = False  # 本轮开头是否注入过决策提示（pop 用）
        _enhanced_context_injected = False  # 本轮开头是否注入过增强上下文（pop 用）
        _image_stripped = False  # 图片超限时剥离重试（只允许一次，避免循环）
        _inject_extra_rounds = 0  # 因处理运行中补充信息而追加的额外轮次（上限防死循环）
        MAX_INJECT_EXTRA_ROUNDS = 5  # 最多追加 5 轮处理连续补充信息

        for i in range(max_iters + MAX_INJECT_EXTRA_ROUNDS):
            # 上一轮注入的决策提示/增强上下文是临时 user 消息，本轮消费完后 pop 掉，避免污染 history
            if _decision_prompt_injected and working and working[-1].role == "user":
                working.pop()
                _decision_prompt_injected = False
            if _enhanced_context_injected and working and working[-1].role == "user":
                working.pop()
                _enhanced_context_injected = False
            # 每轮开头消费「运行中补充信息」：用户在工具调用过程中提交的补充内容，
            # append 到 working 末尾（即 prompt 结尾），下一轮调模型时立即可见。
            # 协议合规：Anthropic/OpenAI 都允许 tool 消息后跟 user 消息。
            from ethan.core.context import get_injected_messages as _drain_inject

            _injected = _drain_inject()
            if _injected:
                _inject_text = "\n\n".join(f"[用户运行中补充]：{m}" for m in _injected)
                # 若末尾已是 user 消息（首轮尚无 assistant/tool），合并而非追加，
                # 避免连续两条 user 消息导致部分网关 400。
                if working and working[-1].role == "user":
                    working[-1] = Message(
                        role="user",
                        content=(working[-1].content or "") + "\n\n" + _inject_text,
                        images=working[-1].images,
                    )
                else:
                    working.append(Message(role="user", content=_inject_text))
                logger.info("chat() iter=%d consumed %d injected message(s)", i, len(_injected))
                # 开头 drain 到补充时：若本轮即将进入 finalize（i 已到 max_iters-1+extra），
                # 主动递增 _inject_extra_rounds 推迟 finalize，给模型工具能力处理补充；
                # 已达上限则记 warning，避免静默丢弃。
                if i >= max_iters - 1 + _inject_extra_rounds:
                    if _inject_extra_rounds < MAX_INJECT_EXTRA_ROUNDS:
                        _inject_extra_rounds += 1
                        logger.info(
                            "chat() iter=%d 开头收到补充，递增 _inject_extra_rounds=%d 推迟 finalize",
                            i,
                            _inject_extra_rounds,
                        )
                    else:
                        logger.warning(
                            "chat() iter=%d 收到补充信息但追加轮次已达上限（%d），本轮仍会 finalize，补充可能未被完整处理",
                            i,
                            _inject_extra_rounds,
                        )
            # finalize 判断：
            # - i 抵达「原始最后一轮 + 已追加轮次」即正常 finalize，每追加 1 轮就在该轮内允许收尾
            # - 已达追加轮次上限：强制 finalize（兜底，避免模型持续调工具撞循环上限）
            finalize = False
            if i >= max_iters - 1 + _inject_extra_rounds:
                finalize = True
            if _inject_extra_rounds >= MAX_INJECT_EXTRA_ROUNDS:
                finalize = True  # 达到追加轮次上限，强制收尾
            if finalize:
                tools = None
                sys = system + finalize_system_suffix("max_iters")
            else:
                tools = self._broadcast_tools(tools_list)
                sys = system + pending_suffix if pending_suffix else system
            pending_suffix = ""

            try:
                response = await provider.chat(working, tools=tools, system=sys)
            except Exception as e:
                # 图片相关错误（尺寸超限 / non-VLM 拒绝 image_url）：写文件后重试一次
                if _is_image_error(e) and not _image_stripped:
                    _image_stripped = True
                    if _strip_images_from_messages(working, self.session_id):
                        logger.warning("图片相关错误，写文件后重试: %s", e)
                        response = await provider.chat(working, tools=tools, system=sys)
                    else:
                        raise
                else:
                    raise
            self.usage.add(response.usage)
            working.append(response)

            # 空响应（既无正文也无工具调用）= 模型静默放弃。
            # 移除空 assistant 消息，注入 nudge 重试一次（带工具）；仍空才 finalize 兜底。
            if not finalize and not response.is_tool_call and not (response.content or "").strip():
                working.pop()  # 移除空 assistant 消息
                logger.warning("chat() 空响应，注入 nudge 重试")
                nudge = Message(role="user", content="[继续。请根据已有信息回答问题，或继续使用工具完成任务。]")
                working.append(nudge)
                resp = await provider.chat(working, tools=tools, system=system)
                self.usage.add(resp.usage)
                working.pop()  # 移除 nudge
                if (resp.content or "").strip() or resp.is_tool_call:
                    working.append(resp)
                    if not resp.is_tool_call:
                        # 返回前检查是否有运行中补充信息刚进来，有则再跑一轮处理
                        _late_injected = _drain_inject()
                        if _late_injected and _inject_extra_rounds >= MAX_INJECT_EXTRA_ROUNDS:
                            logger.warning(
                                "chat() 空响应重试结束前 收到 %d 条补充但追加轮次已达上限，丢弃",
                                len(_late_injected),
                            )
                        if _late_injected and _inject_extra_rounds < MAX_INJECT_EXTRA_ROUNDS:
                            _inject_text = "\n\n".join(f"[用户运行中补充]：{m}" for m in _late_injected)
                            if working and working[-1].role == "assistant":
                                working.append(Message(role="user", content=_inject_text))
                            else:
                                working[-1] = Message(
                                    role="user",
                                    content=(working[-1].content or "") + "\n\n" + _inject_text,
                                    images=getattr(working[-1], "images", None) or [],
                                )
                            _inject_extra_rounds += 1
                            logger.info("chat() 结束前收到补充信息，追加第 %d 轮处理", _inject_extra_rounds)
                            _decision_prompt_injected = False
                            _enhanced_context_injected = False
                            continue
                        return resp
                    # 有工具调用 → 继续正常流程
                    response = resp
                    # fall through to tool execution below
                else:
                    # 重试仍空 → finalize 兜底
                    logger.warning("空响应重试仍无输出，执行 finalize 兜底")
                    sys = system + finalize_system_suffix("max_iters")
                    resp = await provider.chat(working, tools=None, system=sys)
                    self.usage.add(resp.usage)
                    # finalize 兜底返回前也检查补充信息
                    _late_injected = _drain_inject()
                    if _late_injected and _inject_extra_rounds >= MAX_INJECT_EXTRA_ROUNDS:
                        logger.warning(
                            "chat() finalize 兜底前 收到 %d 条补充但追加轮次已达上限，丢弃",
                            len(_late_injected),
                        )
                    if _late_injected and _inject_extra_rounds < MAX_INJECT_EXTRA_ROUNDS:
                        # 先把 finalize 的回复放入 working，让模型知道自己说了什么
                        resp = await self._ensure_non_empty(resp, working, monitor, "finalize")
                        if resp.content:
                            working.append(Message(role="assistant", content=resp.content))
                        working.append(
                            Message(
                                role="user",
                                content="\n\n".join(f"[用户运行中补充]：{m}" for m in _late_injected),
                            )
                        )
                        _inject_extra_rounds += 1
                        logger.info("chat() finalize 前收到补充信息，追加第 %d 轮处理", _inject_extra_rounds)
                        _decision_prompt_injected = False
                        _enhanced_context_injected = False
                        finalize = False  # 允许调工具处理补充
                        continue
                    return await self._ensure_non_empty(resp, working, monitor, "finalize")

            if not response.is_tool_call:
                # 决策提示轮模型用自然语言回应（没调 decide 也没调任何工具）
                # 移除污染消息，记 silent_count，注入 nudge 让模型重新选工具继续。
                if monitor.awaiting_decision_response and (response.content or "").strip() and not finalize:
                    working.pop()
                    monitor.silent_decision_count += 1
                    monitor.awaiting_decision_response = False
                    logger.warning(
                        "[decision-silent] iter=%d → 模型用正文回应决策提示（silent_count=%d），注入 nudge 重试",
                        i + 1,
                        monitor.silent_decision_count,
                    )
                    working.append(
                        Message(
                            role="user", content="[继续执行任务。请直接调用工具完成下一步，不要用文字描述你的决策。]"
                        )
                    )
                    continue
                # 返回前检查是否有运行中补充信息刚进来，有则再跑一轮处理
                _late_injected = _drain_inject()
                if _late_injected and _inject_extra_rounds >= MAX_INJECT_EXTRA_ROUNDS:
                    logger.warning(
                        "chat() 正常结束前 收到 %d 条补充但追加轮次已达上限，丢弃",
                        len(_late_injected),
                    )
                if _late_injected and _inject_extra_rounds < MAX_INJECT_EXTRA_ROUNDS:
                    _inject_text = "\n\n".join(f"[用户运行中补充]：{m}" for m in _late_injected)
                    # 若末尾已是 user 消息则合并，否则追加
                    if working and working[-1].role == "user":
                        working[-1] = Message(
                            role="user",
                            content=(working[-1].content or "") + "\n\n" + _inject_text,
                            images=working[-1].images,
                        )
                    else:
                        working.append(Message(role="user", content=_inject_text))
                    _inject_extra_rounds += 1
                    logger.info("chat() 正常结束前收到补充信息，追加第 %d 轮处理", _inject_extra_rounds)
                    _decision_prompt_injected = False
                    _enhanced_context_injected = False
                    continue
                return await self._ensure_non_empty(response, working, monitor, "finalize")

            # [decide 拦截] 决策提示轮的 decide tool_call 不执行、不进 working，只读 choice
            # 识别后：从 response.tool_calls 里筛掉 decide，剩余工具照常执行；
            # 如果除 decide 外没有别的 tool_call，模型本轮就是在做决策表达，下一轮继续。
            _intercepted_choice: str | None = None
            if is_decision_call(response.tool_calls):
                _intercepted_choice = extract_decision_choice(response.tool_calls)
                # 把 decide 从本轮 tool_calls 里去掉，避免下传给 executor
                remaining_tcs = [tc for tc in response.tool_calls if tc.name != "decide"]
                response = Message(
                    role=response.role,
                    content=response.content,
                    tool_calls=remaining_tcs,
                    usage=response.usage,
                )
                # response 已变，working 里也同步替换最后一条
                if working and working[-1] is not response:
                    working[-1] = response
                logger.info("[decision-choice] iter=%d → decide choice=%s", i + 1, _intercepted_choice)
                if monitor.awaiting_decision_response and _intercepted_choice == "C":
                    _need_enhanced_context = True
                    logger.info("[need-more-info] iter=%d → 模型选 C，下一轮将追加增强上下文", i + 1)
                monitor.awaiting_decision_response = False
            else:
                # [隐式决策检测] 模型没调 decide 但直接干活时，通过它调的工具反推决策
                # - 调 plan_write → 推断选 B（已规划）→ has_planned=True，后续决策提示间隔拉到 6 轮
                # - 调 find_tools → 推断选 C（需要更多工具/信息）→ 触发增强上下文
                # - 调其他任意工具 → 推断选 A（直接干活）→ silent_decision_count +1
                #   连续 2 次按 A 处理后，决策提示停止打扰（见 should_trigger_decision）
                if monitor.awaiting_decision_response:
                    implicit = detect_implicit_decision(response.tool_calls)
                    if implicit == "B":
                        logger.info("[decision-choice] iter=%d → 隐式选 B（调 plan_write）", i + 1)
                    elif implicit == "C":
                        _need_enhanced_context = True
                        logger.info(
                            "[decision-choice] iter=%d → 隐式选 C（调 find_tools），下一轮将追加增强上下文", i + 1
                        )
                    elif implicit == "A":
                        monitor.silent_decision_count += 1
                        _tools = [tc.name for tc in response.tool_calls][:3]
                        logger.info(
                            "[decision-choice] iter=%d → 隐式选 A（直接干活 %s）silent_count=%d",
                            i + 1,
                            _tools,
                            monitor.silent_decision_count,
                        )
                    monitor.awaiting_decision_response = False

            # 工具调用日志：记录每轮工具执行情况，便于 debug
            tool_summary = ", ".join(f"{tc.name}({_format_args(tc.arguments)})" for tc in response.tool_calls)
            logger.info("chat() iter=%d/%d tools=[%s]", i + 1, max_iters, tool_summary)

            if not response.is_tool_call:
                # 本轮只调了 decide（或空响应）→ 不执行工具、不进执行路径，直接到注入逻辑
                monitor.record([], had_error=False)
            else:
                results: list[ToolResult] = await self._executor.execute(response.tool_calls)
                had_error = any(getattr(r, "is_error", False) for r in results)
                for idx, r in enumerate(results):
                    rlen = len(r.content or "")
                    if r.is_error:
                        logger.warning(
                            "  └─ tool[%d] %s ERROR len=%d: %s",
                            idx,
                            response.tool_calls[idx].name if idx < len(response.tool_calls) else "?",
                            rlen,
                            (r.content or "")[:200],
                        )
                    else:
                        logger.info("  └─ tool[%d] ok len=%d", idx, rlen)
                for r in results:
                    working.append(
                        Message(
                            role="tool",
                            content=r.content,
                            tool_call_id=r.tool_call_id,
                            images=r.images or [],
                        )
                    )
                enforce_context_budget(working)  # 新 tool result 进上下文前管控体积，防撑爆
                compress_previous_round_tools(working, self.session_id)  # 压缩上一轮 search/fetch 结果
                monitor.record(response.tool_calls, had_error)

            # plan 工具调用感知：如果本轮调了 plan_write，标记已规划
            if any(tc.name == "plan_write" for tc in response.tool_calls):
                monitor.has_planned = True

            # [增强上下文] 模型选 C 时，本轮注入全量 skill + tool + 30 memory（role=user，下轮 pop）
            if _need_enhanced_context:
                skills_brief = self._build_all_skills_brief()
                tools_brief = self._build_all_tools_brief()
                _last_user = self._get_last_user_text(working) or ""
                memory_text = await self._build_extended_memory(_last_user, max_items=30)
                enhanced_msg = enhanced_context_message(skills_brief, memory_text, tools_brief)
                working.append(Message(role="user", content=enhanced_msg))
                _enhanced_context_injected = True
                _need_enhanced_context = False
                logger.info("[enhanced-context] iter=%d → 注入增强上下文", i + 1)

            # [决策提示] 第 2 轮 + 之后每 3 轮，追加决策提示（role=user，下一轮 pop）
            if should_trigger_decision(monitor, i):
                decision_msg = decision_prompt_message(monitor.has_planned)
                working.append(Message(role="user", content=decision_msg))
                _decision_prompt_injected = True
                monitor.decision_count += 1
                monitor.awaiting_decision_response = True
                logger.info("[decision-prompt] iter=%d → 注入决策提示 (count=%d)", i + 1, monitor.decision_count)

            # 反思后仍重复同一操作 → 二次强提醒，逼它换路
            if monitor.awaiting_reflection_followup:
                monitor.awaiting_reflection_followup = False
                if monitor.repeated_after_reflection():
                    pending_suffix = "\n\n[System: " + reflection_followup_message() + "]"
                    continue

            if monitor.is_stuck():
                if monitor._freq_limit_varied:
                    # 批量操作达到宽松上限（如整理 tab）→ 直接禁工具收尾，不走反思
                    sys = system + finalize_system_suffix("varied")
                    resp = await provider.chat(working, tools=None, system=sys)
                    self.usage.add(resp.usage)
                    resp = await self._ensure_non_empty(resp, working, monitor, "varied")
                    # varied 收尾前检查补充信息
                    _late_injected = _drain_inject()
                    if _late_injected and _inject_extra_rounds >= MAX_INJECT_EXTRA_ROUNDS:
                        logger.warning(
                            "chat() varied 收尾前 收到 %d 条补充但追加轮次已达上限，丢弃",
                            len(_late_injected),
                        )
                    if _late_injected and _inject_extra_rounds < MAX_INJECT_EXTRA_ROUNDS:
                        if resp.content:
                            working.append(Message(role="assistant", content=resp.content))
                        working.append(
                            Message(
                                role="user",
                                content="\n\n".join(f"[用户运行中补充]：{m}" for m in _late_injected),
                            )
                        )
                        _inject_extra_rounds += 1
                        logger.info("chat() varied 收尾前收到补充信息，追加第 %d 轮处理", _inject_extra_rounds)
                        _decision_prompt_injected = False
                        _enhanced_context_injected = False
                        finalize = False
                        continue
                    return resp
                if monitor.exhausted():
                    # 反思次数用尽仍卡住 → 收尾放弃：禁工具，让模型整理「已做/卡点/建议」
                    sys = system + finalize_system_suffix("stuck")
                    resp = await provider.chat(working, tools=None, system=sys)
                    self.usage.add(resp.usage)
                    resp = await self._ensure_non_empty(resp, working, monitor, "stuck")
                    # stuck 收尾前检查补充信息
                    _late_injected = _drain_inject()
                    if _late_injected and _inject_extra_rounds >= MAX_INJECT_EXTRA_ROUNDS:
                        logger.warning(
                            "chat() stuck 收尾前 收到 %d 条补充但追加轮次已达上限，丢弃",
                            len(_late_injected),
                        )
                    if _late_injected and _inject_extra_rounds < MAX_INJECT_EXTRA_ROUNDS:
                        if resp.content:
                            working.append(Message(role="assistant", content=resp.content))
                        working.append(
                            Message(
                                role="user",
                                content="\n\n".join(f"[用户运行中补充]：{m}" for m in _late_injected),
                            )
                        )
                        _inject_extra_rounds += 1
                        logger.info("chat() stuck 收尾前收到补充信息，追加第 %d 轮处理", _inject_extra_rounds)
                        _decision_prompt_injected = False
                        _enhanced_context_injected = False
                        finalize = False
                        continue
                    return resp
                last_result = results[-1].content if results else ""
                pending_suffix = "\n\n[System: " + reflection_message(monitor, last_result) + "]"
                monitor.mark_reflected()

        # 循环兜底返回前最后检查一次补充信息（已达轮次上限则不再追加，直接返回）
        _late_injected = _drain_inject()
        if _late_injected:
            logger.warning("chat() 达到轮次上限，丢弃 %d 条未处理补充信息", len(_late_injected))
        return Message(role="assistant", content="[max tool iterations reached]")

    async def stream_chat(self, messages: list[Message]):
        """流式对话。instant/fast/full 三档路由，按关键词规则自动选择。"""
        from ethan.core.context import reset_active_tools
        from ethan.providers.base import InjectEvent, SkillsMatchedEvent, ThinkingEvent, ToolEvent

        self._executor.reset_cache()
        reset_active_tools()  # 清空本请求的 find_tools 激活集
        working = list(messages)

        # 空回复兜底：先极简重试（每次 stream_chat 仅一次），仍空则合成原因专属文案。
        # 闭包捕获局部 _empty_retried，天然按调用隔离；nonlocal 保证只重试一次。
        _empty_retried = False

        async def _empty_reply(working_msgs: list[Message], rsn: str) -> str:
            nonlocal _empty_retried
            logger.warning("stream_chat() 返回空回复 (reason=%s)，尝试兜底", rsn)
            if not _empty_retried:
                _empty_retried = True
                retried = await self._minimal_retry(working_msgs)
                if retried:
                    return retried
            tc = [m for m in working_msgs if m.role == "assistant" and m.tool_calls]
            return _empty_reply_fallback_text(rsn, len(tc))

        # --- Instant Route: 极简问题零工具直答 ---
        last_user_text = self._get_last_user_text(working)
        instant = classify_instant(last_user_text) if last_user_text else None
        if instant:
            if instant.kind == "math":
                yield f"{instant.answer}"
                return
            if instant.kind == "time":
                yield f"现在是 {instant.answer}"
                return
            # greeting: LLM 裸答（无 tools、无 memory recall、极简 system）
            if instant.kind == "greeting":
                from ethan.core.timezone import get_local_timezone

                now = datetime.now(get_local_timezone()).strftime("%Y-%m-%d %H:%M:%S %A")
                minimal_system = (
                    f"{self._system_files.get('identity', 'You are a helpful assistant.')}\n"
                    f"Current time: {now}\n"
                    "简洁直接地回答，不需要调用任何工具。"
                )
                persona = self._persona_block()
                if persona:
                    minimal_system += f"\n{persona}"
                provider = self._provider
                async for chunk in provider.stream_chat(working, tools=None, system=minimal_system):
                    if chunk.reasoning:
                        yield ThinkingEvent(delta=chunk.reasoning)
                    if chunk.content:
                        yield chunk.content
                    if chunk.is_final:
                        self.usage.add(chunk.usage)
                return

        from ethan.core.artifacts import inject_artifacts_prompt

        inject_artifacts_prompt(working)  # 注入本会话已生成/交付的文件清单，供后续轮次直接引用
        enforce_context_budget(working)  # 历史 tool result 也可能很大，进循环前先管控
        compress_previous_round_tools(working, self.session_id)  # 压缩上一轮 search/fetch 结果
        _route, system, tools_list, max_iters = self._select_route(working)
        provider = self._provider_for_route(_route)

        # _select_route 内部已完成 Skill 匹配，yield 一次让消费者记录命中的 Skill 上下文
        if self.last_matched_skills:
            skills_info = []
            for name in self.last_matched_skills:
                sk = self._skills.get(name) if self._skills else None
                skills_info.append(
                    {
                        "name": name,
                        "is_default": getattr(sk, "is_default", False),
                        "category": getattr(sk, "category", "default"),
                    }
                )
            yield SkillsMatchedEvent(skills=skills_info)

        # 记忆召回已改为 recall_memory 工具按需调用，ToolEvent 由工具执行路径自动产生

        from ethan.core.loop_control import (
            LoopMonitor,
            decision_prompt_message,
            detect_implicit_decision,
            enhanced_context_message,
            extract_decision_choice,
            finalize_system_suffix,
            is_decision_call,
            reflection_followup_message,
            reflection_message,
            should_trigger_decision,
        )

        monitor = LoopMonitor()
        pending_suffix = ""  # 反思提示，仅附加到「下一轮」的 system，附完即清
        _need_enhanced_context = False  # 上一轮模型响应是否提到"需要更多信息"
        _decision_prompt_injected = False  # 本轮开头是否注入过决策提示（pop 用）
        _enhanced_context_injected = False  # 本轮开头是否注入过增强上下文（pop 用）
        _image_stripped = False  # 图片超限时剥离重试（只允许一次，避免循环）
        _inject_extra_rounds = 0  # 因处理运行中补充信息而追加的额外轮次（上限防死循环）
        MAX_INJECT_EXTRA_ROUNDS = 5  # 最多追加 5 轮处理连续补充信息
        _ssl_continue_used = False  # SSL 断连自动续接（仅允许一次）

        for i in range(max_iters + MAX_INJECT_EXTRA_ROUNDS):
            # 上一轮注入的决策提示/增强上下文是临时 user 消息，本轮消费完后 pop 掉，避免污染 history
            if _decision_prompt_injected and working and working[-1].role == "user":
                working.pop()
                _decision_prompt_injected = False
            if _enhanced_context_injected and working and working[-1].role == "user":
                working.pop()
                _enhanced_context_injected = False
            # 每轮开头消费「运行中补充信息」：用户在工具调用过程中提交的补充内容，
            # append 到 working 末尾（即 prompt 结尾），下一轮调模型时立即可见。
            # 协议合规：Anthropic/OpenAI 都允许 tool 消息后跟 user 消息。
            from ethan.core.context import get_injected_messages as _drain_inject

            _injected = _drain_inject()
            if _injected:
                _inject_text = "\n\n".join(f"[用户运行中补充]：{m}" for m in _injected)
                # 若末尾已是 user 消息（首轮尚无 assistant/tool），合并而非追加，
                # 避免连续两条 user 消息导致部分网关 400。
                if working and working[-1].role == "user":
                    working[-1] = Message(
                        role="user",
                        content=(working[-1].content or "") + "\n\n" + _inject_text,
                        images=working[-1].images,
                    )
                else:
                    working.append(Message(role="user", content=_inject_text))
                logger.info("stream_chat() iter=%d consumed %d injected message(s)", i, len(_injected))
                yield InjectEvent(messages=list(_injected))
                # 开头 drain 到补充时：若本轮即将进入 finalize（i 已到 max_iters-1+extra），
                # 主动递增 _inject_extra_rounds 推迟 finalize，给模型工具能力处理补充；
                # 已达上限则记 warning，避免静默丢弃。
                if i >= max_iters - 1 + _inject_extra_rounds:
                    if _inject_extra_rounds < MAX_INJECT_EXTRA_ROUNDS:
                        _inject_extra_rounds += 1
                        logger.info(
                            "stream_chat() iter=%d 开头收到补充，递增 _inject_extra_rounds=%d 推迟 finalize",
                            i,
                            _inject_extra_rounds,
                        )
                    else:
                        logger.warning(
                            "stream_chat() iter=%d 收到补充信息但追加轮次已达上限（%d），本轮仍会 finalize，补充可能未被完整处理",
                            i,
                            _inject_extra_rounds,
                        )
            # finalize 判断：
            # - i 抵达「原始最后一轮 + 已追加轮次」即正常 finalize，每追加 1 轮就在该轮内允许收尾
            # - 已达追加轮次上限：强制 finalize（兜底，避免模型持续调工具撞循环上限）
            finalize = False
            if i >= max_iters - 1 + _inject_extra_rounds:
                finalize = True
            if _inject_extra_rounds >= MAX_INJECT_EXTRA_ROUNDS:
                finalize = True  # 达到追加轮次上限，强制收尾
            if finalize:
                tools = None
                sys = system + finalize_system_suffix("max_iters")
            else:
                tools = self._broadcast_tools(tools_list)
                sys = system + pending_suffix if pending_suffix else system
            pending_suffix = ""
            full_content = ""
            final_chunk = None

            try:
                async for chunk in provider.stream_chat(working, tools=tools, system=sys):
                    if chunk.reasoning:
                        yield ThinkingEvent(delta=chunk.reasoning)
                    if chunk.content:
                        full_content += chunk.content
                        yield chunk.content
                    if chunk.is_final:
                        final_chunk = chunk
                        self.usage.add(chunk.usage)
            except Exception as e:
                # 图片相关错误（尺寸超限 / non-VLM 拒绝 image_url）：写文件后重试一次。
                # 图片已落盘，[image_paths: ...] 路径提示已在 content 中，
                # 模型可通过 file_read/shell 工具读取本地文件自行处理。
                if _is_image_error(e) and not _image_stripped and not full_content:
                    _image_stripped = True
                    if _strip_images_from_messages(working, self.session_id):
                        logger.warning("图片相关错误，写文件后重试: %s", e)
                        full_content = ""
                        final_chunk = None
                        async for chunk in provider.stream_chat(working, tools=tools, system=sys):
                            if chunk.reasoning:
                                yield ThinkingEvent(delta=chunk.reasoning)
                            if chunk.content:
                                full_content += chunk.content
                                yield chunk.content
                            if chunk.is_final:
                                final_chunk = chunk
                                self.usage.add(chunk.usage)
                    else:
                        raise  # 没有图片可剥离，不是图片问题
                # lite 模型（fast 档）可能偶发 503/鉴权失败，或 lite 模型在当前
                # provider 上不可用（如 OpenAI-compat base URL 不认识 gemini-flash-lite）。
                # 若还没产出任何内容，回退主模型重试本轮一次，并禁用 lite provider
                # 避免后续 fast 档重复踩坑。
                elif provider is not self._provider and not full_content:
                    logger.warning(
                        "fast 档 lite provider 调用失败，回退主模型重试（后续 fast 档将直接用主模型）", exc_info=True
                    )
                    provider = self._provider
                    self._lite_provider = self._provider  # 禁用 lite，后续 fast 档不再重试
                    full_content = ""
                    final_chunk = None
                    async for chunk in provider.stream_chat(working, tools=tools, system=sys):
                        if chunk.reasoning:
                            yield ThinkingEvent(delta=chunk.reasoning)
                        if chunk.content:
                            full_content += chunk.content
                            yield chunk.content
                        if chunk.is_final:
                            final_chunk = chunk
                            self.usage.add(chunk.usage)
                else:
                    raise

            tool_calls = final_chunk.tool_calls if final_chunk else []
            # Fallback：模型把工具调用写成文本时，从 content 解析
            if not tool_calls and full_content:
                parsed = self._parse_stream_text_tool_calls(full_content)
                if parsed:
                    tool_calls = parsed
                    # 保留 DSML/call 标记之前的正文作为 thought 内容
                    from ethan.providers.openai_compat import OpenAICompatProvider

                    if OpenAICompatProvider._contains_dsml(full_content):
                        # 截取 DSML 标记之前的文本
                        import re

                        dsml_start = re.search(r"<[｜|][｜|]DSML[｜|][｜|]", full_content)
                        full_content = full_content[: dsml_start.start()].rstrip() if dsml_start else ""
                    else:
                        full_content = ""
                    response = Message(role="assistant", content=full_content, tool_calls=tool_calls)
                else:
                    response = Message(role="assistant", content=full_content, tool_calls=tool_calls)
            else:
                response = Message(role="assistant", content=full_content, tool_calls=tool_calls)
            working.append(response)

            # SSL 断连自动续接：检测到 truncated 且为纯文本回复时，注入续接提示重新调模型
            if (
                final_chunk
                and final_chunk.truncated
                and not response.is_tool_call
                and full_content
                and not _ssl_continue_used
                and not finalize
            ):
                _ssl_continue_used = True
                logger.warning("stream_chat() iter=%d SSL truncated, auto-continuing", i + 1)
                working.append(
                    Message(
                        role="user",
                        content="[网络中断，请从断点继续你的回复，不要重复已说内容。]",
                    )
                )
                continue

            # 空响应（既无正文也无工具调用）= 模型静默放弃。
            # 修复：移除空 assistant 消息，注入 nudge 唤醒模型再重试一轮（带工具）。
            # 这样模型可以继续工具调用（SWE-bench 场景）或直接回答（GAIA 场景）。
            # 仍空则走 finalize 兜底。
            if not finalize and not response.is_tool_call and not full_content:
                working.pop()  # 移除空 assistant 消息
                logger.warning("模型返回空响应（iter=%d），注入 nudge 重试", i)
                nudge = Message(role="user", content="[继续。请根据已有信息回答问题，或继续使用工具完成任务。]")
                working.append(nudge)
                # 带工具重试：让模型可以选择继续调用工具或直接回答
                retry_content = ""
                retry_final = None
                async for chunk in self._provider.stream_chat(working, tools=tools, system=system):
                    if chunk.reasoning:
                        yield ThinkingEvent(delta=chunk.reasoning)
                    if chunk.content:
                        retry_content += chunk.content
                        yield chunk.content
                    if chunk.is_final:
                        retry_final = chunk
                        self.usage.add(chunk.usage)
                working.pop()  # 移除 nudge
                retry_tool_calls = retry_final.tool_calls if retry_final else []
                if retry_content or retry_tool_calls:
                    # 重试成功：把响应放回 working 继续正常流程
                    retry_resp = Message(role="assistant", content=retry_content, tool_calls=retry_tool_calls)
                    working.append(retry_resp)
                    if not retry_resp.is_tool_call:
                        # 返回前检查是否有运行中补充信息刚进来，有则再跑一轮处理
                        _late_injected = _drain_inject()
                        if _late_injected and _inject_extra_rounds >= MAX_INJECT_EXTRA_ROUNDS:
                            logger.warning(
                                "stream_chat() 空响应重试结束前 收到 %d 条补充但追加轮次已达上限，丢弃",
                                len(_late_injected),
                            )
                        if _late_injected and _inject_extra_rounds < MAX_INJECT_EXTRA_ROUNDS:
                            _inject_text = "\n\n".join(f"[用户运行中补充]：{m}" for m in _late_injected)
                            if working and working[-1].role == "assistant":
                                working.append(Message(role="user", content=_inject_text))
                            else:
                                working[-1] = Message(
                                    role="user",
                                    content=(working[-1].content or "") + "\n\n" + _inject_text,
                                    images=getattr(working[-1], "images", None) or [],
                                )
                            _inject_extra_rounds += 1
                            logger.info(
                                "stream_chat() 空响应重试结束前收到补充信息，追加第 %d 轮处理", _inject_extra_rounds
                            )
                            yield InjectEvent(messages=list(_late_injected))
                            _decision_prompt_injected = False
                            _enhanced_context_injected = False
                            tool_calls = []
                            response = retry_resp
                            continue  # 不进工具执行路径，直接下一轮
                        return
                    # 有工具调用 → 正常执行（跳到下一轮循环开头处理不太方便，直接 continue）
                    tool_calls = retry_tool_calls
                    response = retry_resp
                    # fall through to tool execution below
                else:
                    # 重试仍空 → finalize 兜底
                    logger.warning("空响应重试仍无输出，执行 finalize 兜底")
                    sys = system + finalize_system_suffix("max_iters")
                    fin_content = ""
                    async for chunk in self._provider.stream_chat(working, tools=None, system=sys):
                        if chunk.reasoning:
                            yield ThinkingEvent(delta=chunk.reasoning)
                        if chunk.content:
                            fin_content += chunk.content
                            yield chunk.content
                        if chunk.is_final:
                            self.usage.add(chunk.usage)
                    # finalize 兜底返回前也检查补充信息
                    _late_injected = _drain_inject()
                    if _late_injected and _inject_extra_rounds >= MAX_INJECT_EXTRA_ROUNDS:
                        logger.warning(
                            "stream_chat() finalize 兜底前 收到 %d 条补充但追加轮次已达上限，丢弃",
                            len(_late_injected),
                        )
                    if _late_injected and _inject_extra_rounds < MAX_INJECT_EXTRA_ROUNDS:
                        # 先处理空内容兜底，再放入 working
                        if not fin_content:
                            fin_content = await _empty_reply(working, "nudge_exhausted")
                            yield fin_content
                        # 把 finalize 的回复放入 working，让模型知道自己说了什么
                        working.append(Message(role="assistant", content=fin_content))
                        working.append(
                            Message(
                                role="user",
                                content="\n\n".join(f"[用户运行中补充]：{m}" for m in _late_injected),
                            )
                        )
                        _inject_extra_rounds += 1
                        logger.info(
                            "stream_chat() nudge_exhausted 前收到补充信息，追加第 %d 轮处理", _inject_extra_rounds
                        )
                        yield InjectEvent(messages=list(_late_injected))
                        _decision_prompt_injected = False
                        _enhanced_context_injected = False
                        finalize = False  # 允许调工具处理补充
                        tool_calls = []
                        response = Message(role="assistant", content=fin_content)
                        continue
                    if not fin_content:
                        yield await _empty_reply(working, "nudge_exhausted")
                    return

            if not response.is_tool_call:
                # 决策提示轮模型用自然语言回应（没调 decide 也没调任何工具）
                # 根因：模型把"我要选 B"写进正文而不是调 decide 工具。
                # 修复：移除这条污染消息，记 silent_count，注入 nudge 让模型重新选工具继续。
                # 避免：1) 决策思考泄露到正文；2) 流提前结束导致会话停住。
                if monitor.awaiting_decision_response and full_content and not finalize:
                    working.pop()  # 移除含决策思考的 assistant 消息
                    monitor.silent_decision_count += 1
                    monitor.awaiting_decision_response = False
                    logger.warning(
                        "[decision-silent] iter=%d → 模型用正文回应决策提示（silent_count=%d），注入 nudge 重试",
                        i + 1,
                        monitor.silent_decision_count,
                    )
                    nudge = Message(
                        role="user", content="[继续执行任务。请直接调用工具完成下一步，不要用文字描述你的决策。]"
                    )
                    working.append(nudge)
                    continue
                # finalize 轮可能因上下文过大模型返回空 → 兜底
                if finalize and not full_content:
                    full_content = await _empty_reply(working, "finalize")
                    yield full_content
                # 返回前检查是否有运行中补充信息刚进来，有则再跑一轮处理
                _late_injected = _drain_inject()
                if _late_injected and _inject_extra_rounds >= MAX_INJECT_EXTRA_ROUNDS:
                    logger.warning(
                        "stream_chat() 正常结束前 收到 %d 条补充但追加轮次已达上限，丢弃",
                        len(_late_injected),
                    )
                if _late_injected and _inject_extra_rounds < MAX_INJECT_EXTRA_ROUNDS:
                    _inject_text = "\n\n".join(f"[用户运行中补充]：{m}" for m in _late_injected)
                    # 若末尾已是 user 消息则合并，否则追加
                    if working and working[-1].role == "user":
                        working[-1] = Message(
                            role="user",
                            content=(working[-1].content or "") + "\n\n" + _inject_text,
                            images=working[-1].images,
                        )
                    else:
                        working.append(Message(role="user", content=_inject_text))
                    _inject_extra_rounds += 1
                    logger.info("stream_chat() 正常结束前收到补充信息，追加第 %d 轮处理", _inject_extra_rounds)
                    yield InjectEvent(messages=list(_late_injected))
                    _decision_prompt_injected = False
                    _enhanced_context_injected = False
                    continue
                return
            if finalize:
                # 收尾轮已禁工具并流式吐出总结；即便模型仍返回 tool_calls 也不执行，直接结束。
                # 但如果 finalize 轮没有任何内容产出，也需要兜底
                if not full_content:
                    full_content = await _empty_reply(working, "finalize")
                    yield full_content
                # finalize 结束前也检查补充信息
                _late_injected = _drain_inject()
                if _late_injected and _inject_extra_rounds >= MAX_INJECT_EXTRA_ROUNDS:
                    logger.warning(
                        "stream_chat() finalize 结束前 收到 %d 条补充但追加轮次已达上限，丢弃",
                        len(_late_injected),
                    )
                if _late_injected and _inject_extra_rounds < MAX_INJECT_EXTRA_ROUNDS:
                    _inject_text = "\n\n".join(f"[用户运行中补充]：{m}" for m in _late_injected)
                    # response（含 full_content）已在第 1382 行 append 到 working，直接追加补充即可
                    working.append(Message(role="user", content=_inject_text))
                    _inject_extra_rounds += 1
                    logger.info("stream_chat() finalize 轮结束前收到补充信息，追加第 %d 轮处理", _inject_extra_rounds)
                    yield InjectEvent(messages=list(_late_injected))
                    _decision_prompt_injected = False
                    _enhanced_context_injected = False
                    finalize = False  # 允许调工具处理补充
                    tool_calls = []
                    response = Message(role="assistant", content=full_content)
                    continue
                return

            # [decide 拦截] 决策提示轮的 decide tool_call 不执行、不进 working，只读 choice
            # 识别后：从 response.tool_calls 里筛掉 decide，剩余工具照常执行；
            # 如果除 decide 外没有别的 tool_call，模型本轮就是在做决策表达，下一轮继续。
            if is_decision_call(tool_calls):
                _intercepted_choice = extract_decision_choice(tool_calls)
                # 把 decide 从本轮 tool_calls 里去掉
                tool_calls = [tc for tc in tool_calls if tc.name != "decide"]
                response = Message(
                    role=response.role,
                    content=response.content,
                    tool_calls=tool_calls,
                    usage=response.usage,
                )
                # response 已变，working 里也同步替换最后一条
                if working and working[-1] is not response:
                    working[-1] = response
                logger.info("[decision-choice] iter=%d → decide choice=%s", i + 1, _intercepted_choice)
                if monitor.awaiting_decision_response and _intercepted_choice == "C":
                    _need_enhanced_context = True
                    logger.info("[need-more-info] iter=%d → 模型选 C，下一轮将追加增强上下文", i + 1)
                monitor.awaiting_decision_response = False
                # 如果筛掉 decide 后没有其他工具调用 → 不进执行路径
                if not tool_calls:
                    monitor.record([], had_error=False)
                    # 跳到注入逻辑（增强上下文/下一轮决策提示），不进授权检查
                    full_content = response.content or ""
                    if any(tc.name == "plan_write" for tc in []):
                        monitor.has_planned = True
                    if _need_enhanced_context:
                        skills_brief = self._build_all_skills_brief()
                        tools_brief = self._build_all_tools_brief()
                        _last_user = self._get_last_user_text(working) or ""
                        memory_text = await self._build_extended_memory(_last_user, max_items=30)
                        enhanced_msg = enhanced_context_message(skills_brief, memory_text, tools_brief)
                        working.append(Message(role="user", content=enhanced_msg))
                        _enhanced_context_injected = True
                        _need_enhanced_context = False
                        logger.info("[enhanced-context] iter=%d → 注入增强上下文", i + 1)
                    if should_trigger_decision(monitor, i):
                        decision_msg = decision_prompt_message(monitor.has_planned)
                        working.append(Message(role="user", content=decision_msg))
                        _decision_prompt_injected = True
                        monitor.decision_count += 1
                        monitor.awaiting_decision_response = True
                        logger.info(
                            "[decision-prompt] iter=%d → 注入决策提示 (count=%d, has_planned=%s)",
                            i + 1,
                            monitor.decision_count,
                            monitor.has_planned,
                        )
                    continue  # 直接下一轮，不走授权/执行
            else:
                # [隐式决策检测] 模型没调 decide 但直接干活时，通过它调的工具反推决策
                # - 调 plan_write → 推断选 B（已规划）→ has_planned=True，后续决策提示间隔拉到 6 轮
                # - 调 find_tools → 推断选 C（需要更多工具/信息）→ 触发增强上下文
                # - 调其他任意工具 → 推断选 A（直接干活）→ silent_decision_count +1
                #   连续 2 次按 A 处理后，决策提示停止打扰（见 should_trigger_decision）
                if monitor.awaiting_decision_response:
                    implicit = detect_implicit_decision(tool_calls)
                    if implicit == "B":
                        logger.info("[decision-choice] iter=%d → 隐式选 B（调 plan_write）", i + 1)
                    elif implicit == "C":
                        _need_enhanced_context = True
                        logger.info(
                            "[decision-choice] iter=%d → 隐式选 C（调 find_tools），下一轮将追加增强上下文", i + 1
                        )
                    elif implicit == "A":
                        monitor.silent_decision_count += 1
                        _tools = [tc.name for tc in tool_calls][:3]
                        logger.info(
                            "[decision-choice] iter=%d → 隐式选 A（直接干活 %s）silent_count=%d",
                            i + 1,
                            _tools,
                            monitor.silent_decision_count,
                        )
                    monitor.awaiting_decision_response = False

            # --- 授权检查：执行前对工具做（1）渠道硬策略 + （2）consent 确认 ---
            import asyncio as _aio

            from ethan.core.consent import get_consent_provider

            allowed_calls = []
            for tc in tool_calls:
                tool = self._registry.get(tc.name)

                # [ask_user 拦截] 非危险操作的用户确认/选择，不进 executor，阻塞等回复
                # TODO(风险: ask_user 飞书/微信等非 Web 渠道静默失效):
                #   AskUserProvider 只实现了 Web 消费端（SSE yield AskUserEvent → 前端 POST 回传）。
                #   飞书/微信渠道没有渲染卡片 + POST 回传的消费端，Agent 会 await 20s 后超时走 default，
                #   用户在三方渠道端完全无感知。需要在非 Web 渠道用飞书交互卡片/微信公众号菜单替换。
                if tc.name == "ask_user":
                    from ethan.core.ask_user import AskUserProvider

                    args = tc.arguments or {}
                    question = args.get("question", "")
                    options = args.get("options") or []
                    default = args.get("default", "")
                    timeout = 20

                    yield ToolEvent(
                        tool_name=tc.name,
                        tool_call_id=tc.id,
                        args_summary=question,
                        state="start",
                        skill_category=resolve_skill_category(tc.name, tc.arguments),
                    )

                    _ask_provider = AskUserProvider()
                    _ask_event, _ask_fut = _ask_provider.create(question, options, default, timeout)
                    yield _ask_event

                    try:
                        # 后端比前端倒计时多留 5s 余量：用户在倒计时最后几秒点击时，
                        # POST 有网络延迟，若与前端倒计时同刻超时会导致用户选择被丢弃
                        _ask_result = await _aio.wait_for(_ask_fut, timeout=timeout + 5)
                    except (_aio.CancelledError, _aio.TimeoutError):
                        _ask_result = default
                        _ask_provider.cancel_all()

                    yield ToolEvent(
                        tool_name=tc.name,
                        tool_call_id=tc.id,
                        args_summary=question,
                        state="done",
                        result_preview=f"用户选择：{_ask_result}",
                        skill_category=resolve_skill_category(tc.name, tc.arguments),
                    )
                    working.append(Message(role="tool", content=f"用户选择：{_ask_result}", tool_call_id=tc.id))
                    continue

                # [wait_for_user 拦截] 等待用户完成外部操作（OAuth/浏览器操作等），不进 executor，长超时阻塞
                if tc.name == "wait_for_user":
                    from ethan.core.wait_for_user import WaitForUserProvider

                    args = tc.arguments or {}
                    prompt = args.get("prompt", "")
                    input_type = args.get("input_type", "confirm")
                    placeholder = args.get("placeholder", "")
                    confirm_label = args.get("confirm_label", "已完成")
                    cancel_label = args.get("cancel_label", "取消")
                    # 容错解析 timeout：LLM 可能传非数字（如 "abc" 或 "300s"），兜底 300s
                    try:
                        timeout = min(int(args.get("timeout", 300)), 600)
                    except (TypeError, ValueError):
                        timeout = 300

                    yield ToolEvent(
                        tool_name=tc.name,
                        tool_call_id=tc.id,
                        args_summary=prompt,
                        state="start",
                        skill_category=resolve_skill_category(tc.name, tc.arguments),
                    )

                    _wfu_provider = WaitForUserProvider()
                    _wfu_event, _wfu_fut = _wfu_provider.create(
                        prompt,
                        input_type,
                        placeholder,
                        confirm_label,
                        cancel_label,
                        timeout,
                    )
                    yield _wfu_event

                    try:
                        # 后端比前端倒计时多留 5s 余量，避免用户最后时刻点击被超时丢弃
                        _wfu_result = await _aio.wait_for(_wfu_fut, timeout=timeout + 5)
                    except _aio.CancelledError:
                        _wfu_provider.cancel_all()
                        raise
                    except _aio.TimeoutError:
                        _wfu_result = "timeout"
                        _wfu_provider.cancel_all()

                    if _wfu_result == "timeout":
                        _wfu_preview = "等待超时"
                    elif _wfu_result == "cancel":
                        _wfu_preview = "用户取消"
                    elif _wfu_result == "done":
                        _wfu_preview = "用户确认完成"
                    else:
                        _wfu_preview = f"用户输入：{_wfu_result}"

                    yield ToolEvent(
                        tool_name=tc.name,
                        tool_call_id=tc.id,
                        args_summary=prompt,
                        state="done",
                        result_preview=_wfu_preview,
                        skill_category=resolve_skill_category(tc.name, tc.arguments),
                    )
                    working.append(Message(role="tool", content=_wfu_preview, tool_call_id=tc.id))
                    continue

                consent_provider = get_consent_provider()

                # (1) 渠道硬策略：如三方渠道认主人后，非主人不得执行 side_effect 工具。
                #     直接拒绝，不询问（三方渠道无交互确认 UI）。
                if consent_provider is not None:
                    side_effect = bool(getattr(tool, "side_effect", False)) if tool else False
                    deny = consent_provider.policy_check(tc.name, side_effect)
                    if deny:
                        # 静默拒绝：不 yield ToolEvent（不在 UI 展示报错），
                        # 只把拒绝原因回给模型让它调整回复。
                        working.append(Message(role="tool", content=deny, tool_call_id=tc.id))
                        continue

                # (2) consent 确认：工具自身声明需要授权时（如读密钥）走交互/拒绝流程。
                desc = tool.consent_check(**tc.arguments) if tool else None
                if desc:
                    # session 维度授权记忆：按 consent_scope 粒度（工具名 或 目录路径）记忆，
                    # 同会话内此 scope 已授权过则直接放行（目录授权后子目录免问）。
                    # 但 consent_always=True 的高危调用（如 rm -rf）绕过记忆，每次都问、且不记入放行。
                    from ethan.core.consent import AutoConsentProvider, is_granted, record_grant

                    sess_id = getattr(consent_provider, "session_id", "") if consent_provider else ""
                    scope = tool.consent_scope(**tc.arguments) if tool else tc.name
                    always = tool.consent_always(**tc.arguments) if tool else False
                    # 超级权限（auto_approve）模式只对「破坏性」调用保留强制弹窗
                    # （rm -rf / 格式化 / 写设备等，见 consent_destructive）；
                    # 其余高危（sudo / 管道执行 / env dump / secret 引用等）自动放行
                    # ——用户开启超级权限即接管这部分风险，避免 curl 等日常命令
                    # 被反复弹窗打断（2026-08-22 用户反馈）。
                    if always and getattr(consent_provider, "auto_approve", False):
                        always = bool(tool.consent_destructive(**tc.arguments)) if tool else always
                    if not always and is_granted(sess_id, scope):
                        allowed_calls.append(tc)
                        yield ToolEvent(
                            tool_name=tc.name,
                            tool_call_id=tc.id,
                            args_summary=_format_args(tc.arguments),
                            intent=str(tc.arguments.get("intent", "") or ""),
                            state="start",
                            entity_type=classify_tool(tc.name),
                            entity_id=extract_entity_id(tc.name, tc.arguments),
                            skill_category=resolve_skill_category(tc.name, tc.arguments),
                        )
                        continue
                    detail = _format_args(tc.arguments)
                    ok = True
                    consent_msg = ""  # 预初始化，避免 consent_provider is None 分支未赋值
                    consent_timed_out = False
                    consent_cancelled = False
                    if consent_provider is None:
                        ok = True
                    elif getattr(consent_provider, "auto_approve", False) and not always:
                        # 超级权限（web SuperConsentProvider）：非高危授权自动放行，不弹窗；
                        # 高危（always=True）仍走下方弹窗分支交还用户确认。
                        ok = True
                    elif consent_provider.streamed:
                        # Web：向流注入 ConsentEvent，await 前端响应（加超时兜底，
                        # 避免用户一直不点导致 producer 永久挂起、run 不结束）
                        event, fut = consent_provider.create(desc, tc.name, detail, always=always)
                        yield event
                        try:
                            from ethan.core.consent import ConsentResult

                            result = await _aio.wait_for(fut, timeout=300)
                            if isinstance(result, ConsentResult):
                                ok = result.allowed
                                consent_msg = result.message
                            else:
                                ok = bool(result)
                                consent_msg = ""
                        except _aio.TimeoutError:
                            ok = False
                            consent_msg = ""
                            consent_timed_out = True
                            # 超时即摘除注册：fut 已被 wait_for 取消，但条目仍在
                            # _pending/_REGISTRY——迟到的「允许」会让前端误以为已批准
                            # （实际早已按拒绝处理），且条目要等到 cancel_all 才清
                            consent_provider.expire(event.request_id)
                        except _aio.CancelledError:
                            # 「停止生成」等外层取消：非用户拒绝，单独标记，
                            # 避免模型误以为用户表达过否定意见而停下来追问
                            ok = False
                            consent_msg = ""
                            consent_cancelled = True
                    else:
                        ok = await consent_provider.request(desc, tc.name, detail, always=always)
                        consent_msg = ""
                    if not ok:
                        # 拒绝来源区分：无人值守自动拒绝 / 等待超时 / 生成取消 ≠ 用户主动拒绝。
                        # 统一标「用户拒绝」会误导模型以为用户表达过否定意见而停下来追问。
                        if consent_cancelled:
                            reject_text = "[授权请求已取消（本次生成已停止），操作未执行]"
                            reject_preview = "已取消"
                        elif consent_timed_out:
                            reject_text = "[授权确认等待超时（5 分钟无响应），本次操作已按拒绝处理]"
                            reject_preview = "授权超时"
                        elif isinstance(consent_provider, AutoConsentProvider):
                            reject_text = (
                                "[自动授权模式下高危命令不会自动批准，本次已拒绝。"
                                "如确需执行，请在交互渠道（Web/桌面端）发起并在弹窗中确认，"
                                "或告知用户手动执行]"
                            )
                            reject_preview = "高危命令·自动拒绝"
                        else:
                            reject_text = "[用户拒绝此操作]"
                            reject_preview = "用户拒绝"
                        if consent_msg:
                            reject_text += f"\n用户补充说明：{consent_msg}"
                        yield ToolEvent(
                            tool_name=tc.name,
                            tool_call_id=tc.id,
                            args_summary=_format_args(tc.arguments),
                            intent=str(tc.arguments.get("intent", "") or ""),
                            state="start",
                            entity_type=classify_tool(tc.name),
                            entity_id=extract_entity_id(tc.name, tc.arguments),
                            skill_category=resolve_skill_category(tc.name, tc.arguments),
                        )
                        yield ToolEvent(
                            tool_name=tc.name,
                            tool_call_id=tc.id,
                            args_summary="",
                            state="error",
                            result_preview=reject_preview,
                            skill_category=resolve_skill_category(tc.name, tc.arguments),
                        )
                        working.append(
                            Message(
                                role="tool",
                                content=reject_text,
                                tool_call_id=tc.id,
                            )
                        )
                        continue
                    # 授权通过：如有用户补充信息，暂存待拼入 tool 结果（不插 user 消息，避免破坏 LLM 消息协议）
                    if consent_msg:
                        if not hasattr(self, "_consent_msgs"):
                            self._consent_msgs = {}
                        self._consent_msgs[tc.id] = consent_msg
                    # 授权通过：记录到 session 维度（按 scope），后续同 scope 不再弹。
                    # 高危调用（always）不记入放行，下次同类仍单独询问。
                    if not always:
                        record_grant(sess_id, scope)
                allowed_calls.append(tc)
                yield ToolEvent(
                    tool_name=tc.name,
                    tool_call_id=tc.id,
                    args_summary=_format_args(tc.arguments),
                    intent=str(tc.arguments.get("intent", "") or ""),
                    state="start",
                    entity_type=classify_tool(tc.name),
                    entity_id=extract_entity_id(tc.name, tc.arguments),
                    skill_category=resolve_skill_category(tc.name, tc.arguments),
                )

            results: list[ToolResult] = await self._executor.execute(allowed_calls) if allowed_calls else []
            had_error = any(getattr(r, "is_error", False) for r in results)

            # 工具调用日志
            tool_summary = ", ".join(f"{tc.name}({_format_args(tc.arguments)})" for tc in allowed_calls)
            logger.info("stream_chat() iter=%d/%d tools=[%s]", i + 1, max_iters, tool_summary)
            for idx, r in enumerate(results):
                rlen = len(r.content or "")
                if r.is_error:
                    logger.warning(
                        "  └─ tool[%d] %s ERROR len=%d: %s",
                        idx,
                        allowed_calls[idx].name if idx < len(allowed_calls) else "?",
                        rlen,
                        (r.content or "")[:200],
                    )
                else:
                    logger.info("  └─ tool[%d] ok len=%d", idx, rlen)

            for r, tc in zip(results, allowed_calls):
                # content 原文进模型上下文（get_secret 取出的 key Agent 要能用）；
                # 但展示用的 preview/detail 一律过掩码，避免明文 secret 在 UI 里露出。
                from ethan.core.secrets_store import mask_text

                preview = mask_text(_preview(r.content)) if r.content else ""
                detail = mask_text(_detail(r.content)) if r.content else ""
                yield ToolEvent(
                    tool_name=tc.name,
                    tool_call_id=tc.id,
                    args_summary="",
                    state="cancelled" if getattr(r, "is_cancelled", False) else ("done" if not r.is_error else "error"),
                    result_preview=preview,
                    result_detail=detail,
                    sub_steps=getattr(r, "sub_steps", []) or [],
                    ui=getattr(r, "ui", None),
                    mcp_app=getattr(r, "mcp_app", None),
                    cards=getattr(r, "cards", None),
                    cards_meta=getattr(r, "cards_meta", None),
                    entity_type=classify_tool(tc.name),
                    entity_id=extract_entity_id(tc.name, tc.arguments),
                    skill_category=resolve_skill_category(tc.name, tc.arguments),
                )
                # 如果授权时用户有补充信息，拼到 tool 结果内容头部
                tool_content = r.content or ""
                consent_extra = getattr(self, "_consent_msgs", {}).pop(tc.id, None)
                if consent_extra:
                    tool_content = f"[用户在授权时补充]：{consent_extra}\n\n{tool_content}"
                working.append(
                    Message(
                        role="tool",
                        content=tool_content,
                        tool_call_id=r.tool_call_id,
                        images=r.images or [],
                    )
                )

            enforce_context_budget(working)  # 新 tool result 进上下文前管控体积，防撑爆
            compress_previous_round_tools(working, self.session_id)  # 压缩上一轮 search/fetch 结果
            monitor.record(tool_calls, had_error)
            # [DIAG] 签名诊断：iter / 工具名 / 签名 hash / 是否 stuck（info 级别，便于观察）
            if tool_calls:
                _sig = monitor._signatures[-1] if monitor._signatures else ""
                _sig_hash = hash(_sig) & 0xFFFFFF
                _eff_name = monitor._tool_names[-1] if monitor._tool_names else ""
                logger.info(
                    "[sig-debug] iter=%d tools=%s eff_name=%s sig_hash=%06x sig_len=%d stuck=%s",
                    i + 1,
                    [tc.name for tc in tool_calls],
                    _eff_name,
                    _sig_hash,
                    len(_sig),
                    monitor.is_stuck() if len(monitor._signatures) >= 3 else False,
                )

            # plan 工具调用感知：如果本轮调了 plan_write，标记已规划
            if any(tc.name == "plan_write" for tc in tool_calls):
                monitor.has_planned = True

            # [增强上下文] 如果 _need_enhanced_context（来自上轮 decide choice=C）→ 本轮注入
            # role=user（与决策提示一样临时 user 消息，下一轮 pop 掉，避免污染 history）
            if _need_enhanced_context:
                skills_brief = self._build_all_skills_brief()
                tools_brief = self._build_all_tools_brief()
                _last_user = self._get_last_user_text(working) or ""
                memory_text = await self._build_extended_memory(_last_user, max_items=30)
                enhanced_msg = enhanced_context_message(skills_brief, memory_text, tools_brief)
                working.append(Message(role="user", content=enhanced_msg))
                _enhanced_context_injected = True
                _need_enhanced_context = False
                logger.info("[enhanced-context] iter=%d → 注入增强上下文 (skills + tools + memory 30)", i + 1)

            # [决策提示] 第 2 轮 + 之后每 3 轮，在 working 末尾追加决策提示
            # （role=user，要求模型调 decide 工具表达 A/B/C，一气呵成调工具）
            # 注入后设 flag，下一轮开头检测模型响应是否选 C
            if should_trigger_decision(monitor, i):
                decision_msg = decision_prompt_message(monitor.has_planned)
                working.append(Message(role="user", content=decision_msg))
                _decision_prompt_injected = True
                monitor.decision_count += 1
                monitor.awaiting_decision_response = True  # 标记下一轮检测是否选 C
                logger.info(
                    "[decision-prompt] iter=%d → 注入决策提示 (count=%d, has_planned=%s)",
                    i + 1,
                    monitor.decision_count,
                    monitor.has_planned,
                )

            # 反思后仍重复同一操作 → 二次强提醒，逼它换路
            if monitor.awaiting_reflection_followup:
                monitor.awaiting_reflection_followup = False
                if monitor.repeated_after_reflection():
                    pending_suffix = "\n\n[System: " + reflection_followup_message() + "]"
                    continue

            if monitor.is_stuck():
                if monitor._freq_limit_varied:
                    # 批量操作达到宽松上限（如整理 tab）→ 直接禁工具收尾，不走反思
                    sys = system + finalize_system_suffix("varied")
                    varied_content = ""
                    async for chunk in self._provider.stream_chat(working, tools=None, system=sys):
                        if chunk.content:
                            varied_content += chunk.content
                            yield chunk.content
                        if chunk.is_final:
                            self.usage.add(chunk.usage)
                    if not varied_content:
                        varied_content = await _empty_reply(working, "varied")
                        yield varied_content
                    # varied 收尾前检查补充信息
                    _late_injected = _drain_inject()
                    if _late_injected and _inject_extra_rounds >= MAX_INJECT_EXTRA_ROUNDS:
                        logger.warning(
                            "stream_chat() varied 收尾前 收到 %d 条补充但追加轮次已达上限，丢弃",
                            len(_late_injected),
                        )
                    if _late_injected and _inject_extra_rounds < MAX_INJECT_EXTRA_ROUNDS:
                        if varied_content:
                            working.append(Message(role="assistant", content=varied_content))
                        working.append(
                            Message(
                                role="user",
                                content="\n\n".join(f"[用户运行中补充]：{m}" for m in _late_injected),
                            )
                        )
                        _inject_extra_rounds += 1
                        logger.info("stream_chat() varied 收尾前收到补充信息，追加第 %d 轮处理", _inject_extra_rounds)
                        yield InjectEvent(messages=list(_late_injected))
                        _decision_prompt_injected = False
                        _enhanced_context_injected = False
                        finalize = False
                        tool_calls = []
                        response = Message(role="assistant", content=varied_content)
                        continue
                    return
                if monitor.exhausted():
                    # 反思次数用尽仍卡住 → 收尾放弃：禁工具，让模型流式整理「已做/卡点/建议」
                    sys = system + finalize_system_suffix("stuck")
                    stuck_content = ""
                    async for chunk in self._provider.stream_chat(working, tools=None, system=sys):
                        if chunk.content:
                            stuck_content += chunk.content
                            yield chunk.content
                        if chunk.is_final:
                            self.usage.add(chunk.usage)
                    if not stuck_content:
                        stuck_content = await _empty_reply(working, "stuck")
                        yield stuck_content
                    # stuck 收尾前检查补充信息
                    _late_injected = _drain_inject()
                    if _late_injected and _inject_extra_rounds >= MAX_INJECT_EXTRA_ROUNDS:
                        logger.warning(
                            "stream_chat() stuck 收尾前 收到 %d 条补充但追加轮次已达上限，丢弃",
                            len(_late_injected),
                        )
                    if _late_injected and _inject_extra_rounds < MAX_INJECT_EXTRA_ROUNDS:
                        if stuck_content:
                            working.append(Message(role="assistant", content=stuck_content))
                        working.append(
                            Message(
                                role="user",
                                content="\n\n".join(f"[用户运行中补充]：{m}" for m in _late_injected),
                            )
                        )
                        _inject_extra_rounds += 1
                        logger.info("stream_chat() stuck 收尾前收到补充信息，追加第 %d 轮处理", _inject_extra_rounds)
                        yield InjectEvent(messages=list(_late_injected))
                        _decision_prompt_injected = False
                        _enhanced_context_injected = False
                        finalize = False
                        tool_calls = []
                        response = Message(role="assistant", content=stuck_content)
                        continue
                    return
                last_result = results[-1].content if results else ""
                pending_suffix = "\n\n[System: " + reflection_message(monitor, last_result) + "]"
                monitor.mark_reflected()

        # 正常情况下最后一轮（finalize）已禁工具并流式吐出收尾总结后 return，
        # 不会落到这里。保留一个兜底，极端竞态下也不至于静默结束。
        # 兜底返回前最后检查一次补充信息（已达轮次上限则不再追加，直接返回）
        _late_injected = _drain_inject()
        if _late_injected:
            logger.warning("stream_chat() 达到轮次上限，丢弃 %d 条未处理补充信息", len(_late_injected))
        return
