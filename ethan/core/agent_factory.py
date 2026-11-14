"""Agent 工厂 — 统一工具注册，消除 cli/deps/lark/heartbeat 四处重复。

toolset 三档：
  "full"      — 全量工具（web / repl）
  "lark"      — 飞书渠道（同 full，channel=lark）
  "heartbeat" — 心跳子集（只读 + 执行任务，不写记忆/skill）
"""
from __future__ import annotations

from ethan.core.agent import Agent
from ethan.core.context import set_user_id
from ethan.core.perf_monitor import get_perf_monitor
from ethan.skills.registry import SkillRegistry
from ethan.tools.builtin.acp import DelegateCodingTool
from ethan.tools.builtin.ask_user import AskUserTool
from ethan.tools.builtin.background_task import (
    BackgroundTaskListTool,
    BackgroundTaskStopTool,
    BackgroundTaskTool,
)
from ethan.tools.builtin.browser import BrowserClientTool, BrowserPageTool, BrowserSessionTool, BrowserTabTool
from ethan.tools.builtin.chart import ChartTool
from ethan.tools.builtin.code_assistant import CodeAssistantTool, CodeRunnerTool
from ethan.tools.builtin.config import ConfigGetTool, ConfigSetTool
from ethan.tools.builtin.decide import DecideTool
from ethan.tools.builtin.deliver_file import DeliverFileTool
from ethan.tools.builtin.desktop import DesktopCountdownTool, DesktopNotifyTool
from ethan.tools.builtin.dida_tools import (
    DidaProjectListTool,
    DidaTaskCompleteTool,
    DidaTaskCreateTool,
    DidaTaskListTool,
)
from ethan.tools.builtin.documents import DocListTool, DocSaveTool
from ethan.tools.builtin.file import FileEditTool, FileListTool, FileReadTool, FileWriteTool
from ethan.tools.builtin.find_tools import FindToolsTool
from ethan.tools.builtin.heartbeat import HeartbeatAddTool, HeartbeatListTool, HeartbeatRemoveTool
from ethan.tools.builtin.image_search import ImageSearchTool
from ethan.tools.builtin.install_skill import InstallSkillTool
from ethan.tools.builtin.knowledge import KnowledgeAddTool, KnowledgeEditTool, KnowledgeReadTool, KnowledgeSearchTool
from ethan.tools.builtin.lark_tools import (
    LarkAuthCompleteTool,
    LarkAuthStartTool,
    LarkCalendarEventsTool,
    LarkChatMessagesTool,
    LarkMessageSendTool,
)
from ethan.tools.builtin.lunar import LunarCalendarTool
from ethan.tools.builtin.memory_write import MemoryWriteTool
from ethan.tools.builtin.ocr import OcrTool
from ethan.tools.builtin.plan import PlanReadTool, PlanUpdateTool, PlanWriteTool
from ethan.tools.builtin.procedure_write import ProcedureWriteTool
from ethan.tools.builtin.profile_update import ProfileUpdateTool
from ethan.tools.builtin.recall_memory import RecallMemoryTool
from ethan.tools.builtin.schedule import ScheduleCreateTool, ScheduleListTool, SchedulePauseTool, ScheduleRemoveTool
from ethan.tools.builtin.search import FdTool, RipgrepTool
from ethan.tools.builtin.secrets import GetSecretTool, ListSecretsTool, SetSecretTool
from ethan.tools.builtin.shell import ShellTool
from ethan.tools.builtin.skill_create import SkillCreateTool
from ethan.tools.builtin.skill_read import SkillListTool, SkillReadTool
from ethan.tools.builtin.ui_card import UiCardTool
from ethan.tools.builtin.wait_for_user import WaitForUserTool
from ethan.tools.builtin.weather import WeatherTool
from ethan.tools.builtin.web import WebFetchTool
from ethan.tools.builtin.web_search import WebSearchTool
from ethan.tools.builtin.wechat_tools import WeChatMessageSendTool
from ethan.tools.registry import ToolRegistry

# 进程级 SkillRegistry 缓存：{user_id: (skills_dir_mtime, registry)}
# skills_dir mtime 变了（安装/删除 skill）才重建，避免每请求读 100+ 文件。
_SKILL_CACHE: dict[str, tuple[float, SkillRegistry]] = {}

# 进程级 ToolRegistry 缓存：{(toolset, channel, mode): registry}
# 同一配置下复用 registry，避免重复实例化工具
_TOOL_CACHE: dict[tuple[str, str, str], ToolRegistry] = {}


def _get_cached_skill_registry(user_id: str) -> SkillRegistry:
    """获取缓存的 SkillRegistry，使用增量 mtime 检测优化。
    
    性能优化：只检查目录本身的 mtime，不递归扫描所有文件。
    理由：技能文件很少频繁修改，目录 mtime 在新增/删除技能时也会更新。
    """
    from ethan.core.paths import user_skills_dir
    
    monitor = get_perf_monitor()
    with monitor.section("SkillRegistry.load"):
        # 快速路径：只检查目录 mtime，不遍历所有文件（原代码遍历 rglob("*") 很慢）
        skills_dir = user_skills_dir()
        try:
            current_mtime = skills_dir.stat().st_mtime if skills_dir.exists() else 0.0
        except OSError:
            current_mtime = 0.0

        cached = _SKILL_CACHE.get(user_id)
        if cached is not None and cached[0] == current_mtime:
            return cached[1]

        registry = SkillRegistry(user_id=user_id)
        registry.load()
        _SKILL_CACHE[user_id] = (current_mtime, registry)
        return registry


def _get_cached_tool_registry(toolset: str = "full", channel: str = "web", mode: str = "") -> ToolRegistry:
    """获取缓存的 ToolRegistry，避免重复构建。"""
    cache_key = (toolset, channel, mode)
    
    monitor = get_perf_monitor()
    with monitor.section("ToolRegistry.build"):
        if cache_key in _TOOL_CACHE:
            return _TOOL_CACHE[cache_key]
        
        registry = build_tool_registry(user_id="", toolset=toolset, channel=channel, mode=mode)
        _TOOL_CACHE[cache_key] = registry
        return registry


def build_tool_registry(user_id: str = "", toolset: str = "full", channel: str = "web", mode: str = "") -> ToolRegistry:
    """构建工具注册表。user_id 透传给需要它的工具（Schedule/Knowledge/Memory 等）。

    channel 决定渠道相关工具是否注册：ui_card 仅在能渲染 A2UI 的渠道（web/repl）注册，
    飞书/api 等无渲染器的渠道不暴露它，避免模型调了卡片却只能看到 ack 文字。
    """
    registry = ToolRegistry()
    # ── 精简模式：只注册 MINIMAL_TOOLS 固定白名单，不注册记忆/定时/委派等长尾工具 ──
    from ethan.core.modes import MINIMAL_TOOLS, resolve_mode

    if resolve_mode(mode).minimal:
        _minimal_instances: dict[str, object] = {
            "file_read": FileReadTool(),
            "file_write": FileWriteTool(),
            "file_edit": FileEditTool(),
            "file_list": FileListTool(),
            "rg_search": RipgrepTool(),
            "fd_find": FdTool(),
            "shell": ShellTool(),
            "web_search": WebSearchTool(),
            "web_fetch": WebFetchTool(),
            "skill_read": SkillReadTool(),
            "skill_list": SkillListTool(),
        }
        for _name in MINIMAL_TOOLS:
            _inst = _minimal_instances.get(_name)
            if _inst is not None:
                registry.register(_inst)
        # find_tools 元工具：持有 registry 引用，供模型在极少数需要长尾能力时临时激活。
        registry.register(FindToolsTool(registry))
        return registry

    # 基础工具（所有 toolset 共有）
    registry.register(ShellTool())
    # 代码助手：code_analyze 只读静态检查；code_run 委托 ShellTool 执行，
    # 继承 shell 的授权弹窗 / secret 注入 / 进程组清理（见 code_assistant 模块注释）。
    registry.register(CodeAssistantTool())
    registry.register(CodeRunnerTool())
    registry.register(WebSearchTool())
    # image_search：开启 image_search_enabled 即注册。
    # Wallhaven 是主力来源，不依赖 SearXNG；SearXNG 仅作补充（配置了 base_url 才用）。
    try:
        from ethan.core.config import get_config as _get_cfg
        _ws_cfg = _get_cfg().tools.web_search
        if _ws_cfg.image_search_enabled:
            registry.register(ImageSearchTool())
    except Exception:
        pass  # 配置未加载时不阻塞工具注册
    registry.register(WebFetchTool())
    # OCR：只有配了 DeepSeek API Key 才注册。没 key 时注册它等于给模型一个
    # 必然失败的工具，会诱导它去尝试（agent 不知道没配 key），反而拖慢任务。
    try:
        from ethan.core.config import get_config as _get_ocr_cfg

        if (_get_ocr_cfg().tools.web_fetch.api_key or "").strip():
            registry.register(OcrTool())
    except Exception:
        # 配置读不到就不注册。注意这里**不要**裸吞后静默：OCR 是可选项，
        # 但真出问题时（比如字段改名）应该能从日志看出来，而不是永远悄悄消失。
        import logging as _logging

        _logging.getLogger(__name__).debug("OCR 工具未注册（配置读取失败）", exc_info=True)
    registry.register(WeatherTool())
    registry.register(LunarCalendarTool())
    registry.register(ChartTool())
    registry.register(FileReadTool())
    registry.register(FileWriteTool())
    registry.register(FileEditTool())
    registry.register(FileListTool())
    registry.register(DeliverFileTool())
    registry.register(DocSaveTool())
    registry.register(DocListTool())
    # DIDA（滴答清单）CLI wrapper tools — 仅 DIDA_ENABLED=true 时注册（可选插件）。
    # 依赖 dida-cli 已安装并登录（docker 通过挂载 ~/.config/dida-cli 共享登录态）。
    # 未启用时工具不注册，不影响其他工具。
    try:
        from ethan.core.config import get_config as _get_cfg
        if _get_cfg().tools.dida.enabled:
            registry.register(DidaProjectListTool())
            registry.register(DidaTaskCreateTool())
            registry.register(DidaTaskListTool())
            registry.register(DidaTaskCompleteTool())
    except Exception:
        pass  # 配置未加载或未启用时不注册 dida 工具
    # Agenda（日程）工具 — 仅 tools.agenda.enabled=true 时注册（日程页面开关控制，
    # 特殊插件机制：调度与通知不依赖此开关，只有 agent 对话操作能力受控）。
    # 名称已列入 RoutingConfig.base_tools 白名单，注册即广播进提示词（full 档）。
    try:
        from ethan.core.config import get_config as _get_cfg
        if _get_cfg().tools.agenda.enabled:
            from ethan.tools.builtin.agenda import (
                AgendaAddTool,
                AgendaListTool,
                AgendaRemoveTool,
                AgendaUpdateTool,
            )
            registry.register(AgendaAddTool())
            registry.register(AgendaUpdateTool())
            registry.register(AgendaRemoveTool())
            registry.register(AgendaListTool())
    except Exception:
        pass  # 配置未加载或未启用时不注册 agenda 工具
    # flomo 已改为技能目录下的 flomo.py 脚本，通过 shell 工具调用，不再注册为 builtin tool。
    # 详见 ethan/defaults/skills/flomo/SKILL.md 和 flomo.py。

    if toolset == "heartbeat":
        # 心跳：只读 + 执行任务 + 调度 + 知识库 + plan + skill_read，不写记忆/skill/profile
        # skill_read 让 heartbeat agent 能按需拉取 [agent:xxx] 任务的完整 SKILL.md 和 references
        registry.register(DecideTool())
        registry.register(ScheduleCreateTool(user_id=user_id))
        registry.register(ScheduleListTool())
        registry.register(SchedulePauseTool())
        registry.register(ScheduleRemoveTool())
        registry.register(KnowledgeSearchTool(user_id=user_id))
        registry.register(KnowledgeReadTool(user_id=user_id))
        registry.register(KnowledgeAddTool(user_id=user_id))
        registry.register(PlanWriteTool(user_id=user_id))
        registry.register(PlanReadTool(user_id=user_id))
        registry.register(PlanUpdateTool(user_id=user_id))
        registry.register(SkillReadTool())
        return registry

    # full / lark：全量
    registry.register(DecideTool())
    # ask_user：依赖 SSE + POST 消费端（AskUserProvider），仅 web/repl 注册。
    # acp/lark 等无消费端的渠道不给模型这个工具（否则只会 20s 超时走默认且用户无感知）。
    if channel in ("web", "repl"):
        registry.register(AskUserTool())
    registry.register(RipgrepTool())
    registry.register(FdTool())
    registry.register(ScheduleCreateTool(user_id=user_id))
    registry.register(ScheduleListTool())
    registry.register(SchedulePauseTool())
    registry.register(ScheduleRemoveTool())
    registry.register(BackgroundTaskTool(user_id=user_id))
    registry.register(BackgroundTaskListTool())
    registry.register(BackgroundTaskStopTool(user_id=user_id))
    registry.register(KnowledgeSearchTool(user_id=user_id))
    registry.register(KnowledgeReadTool(user_id=user_id))
    registry.register(KnowledgeAddTool(user_id=user_id))
    registry.register(KnowledgeEditTool(user_id=user_id))
    registry.register(MemoryWriteTool(user_id=user_id))
    registry.register(RecallMemoryTool(mode=mode))
    registry.register(ProcedureWriteTool(user_id=user_id))
    registry.register(ProfileUpdateTool(user_id=user_id))
    registry.register(PlanWriteTool(user_id=user_id))
    registry.register(PlanReadTool(user_id=user_id))
    registry.register(PlanUpdateTool(user_id=user_id))
    registry.register(SkillCreateTool(user_id=user_id))
    registry.register(SkillReadTool())
    registry.register(SkillListTool())
    registry.register(DelegateCodingTool(user_id=user_id))
    from ethan.tools.builtin.task_fanout import TaskFanoutTool
    registry.register(TaskFanoutTool(user_id=user_id))
    registry.register(ConfigGetTool())
    registry.register(ConfigSetTool())
    registry.register(HeartbeatAddTool())
    registry.register(HeartbeatRemoveTool())
    registry.register(HeartbeatListTool())
    registry.register(SetSecretTool())
    registry.register(GetSecretTool())
    registry.register(ListSecretsTool())
    registry.register(InstallSkillTool())
    registry.register(BrowserClientTool())
    registry.register(BrowserSessionTool())
    registry.register(BrowserTabTool())
    registry.register(BrowserPageTool())
    registry.register(DesktopCountdownTool())
    registry.register(DesktopNotifyTool())
    # Lark CLI wrapper tools — 仅飞书渠道注册，非飞书渠道不暴露给模型
    if channel == "lark":
        registry.register(LarkCalendarEventsTool())
        registry.register(LarkChatMessagesTool())
        registry.register(LarkMessageSendTool())
        registry.register(LarkAuthStartTool())
        registry.register(LarkAuthCompleteTool())
    # WeChat tools — 仅微信渠道注册
    if channel == "wechat":
        registry.register(WeChatMessageSendTool())
    # ui_card 在能渲染卡片的渠道注册：web/repl 走 A2UI，lark 走飞书 interactive 卡片。
    # 同一套结构化 card 数据，按渠道选渲染目标（见 UiCardTool）。api 等无渲染器的渠道不暴露。
    if channel in ("web", "repl", "lark", "schedule"):
        registry.register(UiCardTool(channel=channel))
    # wait_for_user 依赖前端 SSE + POST 交互，仅 web/repl 可消费
    if channel in ("web", "repl"):
        registry.register(WaitForUserTool())
    # computer_use：依赖 cua-computer 包 + cua-driver 后台服务（可选，包未安装时静默跳过）
    try:
        from ethan.tools.builtin.computer_use import ComputerUseTool  # noqa: PLC0415
        registry.register(ComputerUseTool())
    except ImportError:
        pass  # cua-computer 未安装，工具不可用
    # MCP 外部工具：配置了 tools.mcp.servers 才注册（可选）。连接失败只跳过该 server，
    # 不阻塞其余工具；未配置时不产生任何开销。工具名带 server 前缀（如 dida365_*）。
    try:
        from ethan.tools.mcp_client import get_mcp_manager
        for mcp_tool in get_mcp_manager().get_tools():
            registry.register(mcp_tool)
    except Exception:
        pass  # MCP 不可用时静默跳过，不影响工具注册
    # 工具发现元工具：fast 档只广播常驻工具，模型需要长尾能力时用它检索并激活。
    # 持有 registry 引用以便检索；放最后确保它能看到上面注册的全部工具。
    registry.register(FindToolsTool(registry))
    return registry


def create_agent(
    model: str | None = None,
    channel: str = "web",
    user_id: str = "",
    toolset: str = "full",
    mode: str = "",
) -> Agent:
    """统一 Agent 创建入口。使用缓存避免重复构建 ToolRegistry。"""
    from ethan.core.paths import ensure_user_dirs
    if user_id:
        set_user_id(user_id)
    ensure_user_dirs()
    
    # 优先使用缓存的 ToolRegistry（除非有 user_id 需要透传）
    if not user_id or toolset == "full":
        registry = _get_cached_tool_registry(toolset=toolset, channel=channel, mode=mode)
    else:
        # user_id 非空时，部分工具需要 user_id，必须重新构建
        registry = build_tool_registry(user_id=user_id, toolset=toolset, channel=channel, mode=mode)
    
    skills = _get_cached_skill_registry(user_id)
    return Agent(tool_registry=registry, skill_registry=skills, model=model, channel=channel, user_id=user_id, mode=mode)
