"""Agent 工厂 — 统一工具注册，消除 cli/deps/lark/heartbeat 四处重复。

toolset 三档：
  "full"      — 全量工具（web / repl）
  "lark"      — 飞书渠道（同 full，channel=lark）
  "heartbeat" — 心跳子集（只读 + 执行任务，不写记忆/skill）
"""
from __future__ import annotations

from ethan.core.agent import Agent
from ethan.core.context import set_user_id
from ethan.skills.registry import SkillRegistry
from ethan.tools.builtin.acp import DelegateCodingTool
from ethan.tools.builtin.background_task import (
    BackgroundTaskListTool,
    BackgroundTaskStopTool,
    BackgroundTaskTool,
)
from ethan.tools.builtin.browser import BrowserPageTool, BrowserSessionTool, BrowserTabTool
from ethan.tools.builtin.config import ConfigGetTool, ConfigSetTool
from ethan.tools.builtin.file import FileListTool, FileReadTool, FileWriteTool
from ethan.tools.builtin.find_tools import FindToolsTool
from ethan.tools.builtin.install_skill import InstallSkillTool
from ethan.tools.builtin.knowledge import KnowledgeAddTool, KnowledgeEditTool, KnowledgeReadTool, KnowledgeSearchTool
from ethan.tools.builtin.lark_tools import (
    LarkCalendarEventsTool,
    LarkChatMessagesTool,
    LarkMessageSendTool,
)
from ethan.tools.builtin.memory_write import MemoryWriteTool
from ethan.tools.builtin.procedure_write import ProcedureWriteTool
from ethan.tools.builtin.profile_update import ProfileUpdateTool
from ethan.tools.builtin.schedule import ScheduleCreateTool, ScheduleListTool, ScheduleRemoveTool
from ethan.tools.builtin.search import FdTool, RipgrepTool
from ethan.tools.builtin.secrets import GetSecretTool, ListSecretsTool, SetSecretTool
from ethan.tools.builtin.shell import ShellTool
from ethan.tools.builtin.skill_create import SkillCreateTool
from ethan.tools.builtin.skill_read import SkillListTool, SkillReadTool
from ethan.tools.builtin.ui_card import UiCardTool
from ethan.tools.builtin.weather import WeatherTool
from ethan.tools.builtin.web import WebFetchTool
from ethan.tools.builtin.web_search import WebSearchTool
from ethan.tools.registry import ToolRegistry

# 进程级 SkillRegistry 缓存：{user_id: (skills_dir_mtime, registry)}
# skills_dir mtime 变了（安装/删除 skill）才重建，避免每请求读 100+ 文件。
_SKILL_CACHE: dict[str, tuple[float, SkillRegistry]] = {}


def _get_cached_skill_registry(user_id: str) -> SkillRegistry:
    from ethan.core.paths import user_skills_dir
    skills_dir = user_skills_dir()
    try:
        if skills_dir.exists():
            mtimes = [skills_dir.stat().st_mtime]
            mtimes.extend(p.stat().st_mtime for p in skills_dir.rglob("*") if p.is_file())
            mtime = max(mtimes)
        else:
            mtime = 0.0
    except OSError:
        mtime = 0.0

    cached = _SKILL_CACHE.get(user_id)
    if cached is not None and cached[0] == mtime:
        return cached[1]

    registry = SkillRegistry(user_id=user_id)
    registry.load()
    _SKILL_CACHE[user_id] = (mtime, registry)
    return registry


def build_tool_registry(user_id: str = "", toolset: str = "full", channel: str = "web") -> ToolRegistry:
    """构建工具注册表。user_id 透传给需要它的工具（Schedule/Knowledge/Memory 等）。

    channel 决定渠道相关工具是否注册：ui_card 仅在能渲染 A2UI 的渠道（web/repl）注册，
    飞书/api 等无渲染器的渠道不暴露它，避免模型调了卡片却只能看到 ack 文字。
    """
    registry = ToolRegistry()
    # 基础工具（所有 toolset 共有）
    registry.register(ShellTool())
    registry.register(WebSearchTool())
    registry.register(WebFetchTool())
    registry.register(WeatherTool())
    registry.register(FileReadTool())
    registry.register(FileWriteTool())
    registry.register(FileListTool())

    if toolset == "heartbeat":
        # 心跳：只读 + 执行任务 + 调度 + 知识库，不写记忆/skill/profile
        registry.register(ScheduleCreateTool(user_id=user_id))
        registry.register(ScheduleListTool())
        registry.register(ScheduleRemoveTool())
        registry.register(KnowledgeSearchTool(user_id=user_id))
        registry.register(KnowledgeReadTool(user_id=user_id))
        registry.register(KnowledgeAddTool(user_id=user_id))
        return registry

    # full / lark：全量
    registry.register(RipgrepTool())
    registry.register(FdTool())
    registry.register(ScheduleCreateTool(user_id=user_id))
    registry.register(ScheduleListTool())
    registry.register(ScheduleRemoveTool())
    registry.register(BackgroundTaskTool(user_id=user_id))
    registry.register(BackgroundTaskListTool())
    registry.register(BackgroundTaskStopTool(user_id=user_id))
    registry.register(KnowledgeSearchTool(user_id=user_id))
    registry.register(KnowledgeReadTool(user_id=user_id))
    registry.register(KnowledgeAddTool(user_id=user_id))
    registry.register(KnowledgeEditTool(user_id=user_id))
    registry.register(MemoryWriteTool(user_id=user_id))
    registry.register(ProcedureWriteTool(user_id=user_id))
    registry.register(ProfileUpdateTool(user_id=user_id))
    registry.register(SkillCreateTool(user_id=user_id))
    registry.register(SkillReadTool())
    registry.register(SkillListTool())
    registry.register(DelegateCodingTool(user_id=user_id))
    registry.register(ConfigGetTool())
    registry.register(ConfigSetTool())
    registry.register(SetSecretTool())
    registry.register(GetSecretTool())
    registry.register(ListSecretsTool())
    registry.register(InstallSkillTool())
    registry.register(BrowserSessionTool())
    registry.register(BrowserTabTool())
    registry.register(BrowserPageTool())
    # Lark CLI wrapper tools — 模型主动调高频 lark-cli 命令（日历/群消息/发消息）
    registry.register(LarkCalendarEventsTool())
    registry.register(LarkChatMessagesTool())
    registry.register(LarkMessageSendTool())
    # ui_card 在能渲染卡片的渠道注册：web/repl 走 A2UI，lark 走飞书 interactive 卡片。
    # 同一套结构化 card 数据，按渠道选渲染目标（见 UiCardTool）。api 等无渲染器的渠道不暴露。
    if channel in ("web", "repl", "lark"):
        registry.register(UiCardTool(channel=channel))
    # computer_use：依赖 cua-computer 包 + cua-driver 后台服务（可选，包未安装时静默跳过）
    try:
        from ethan.tools.builtin.computer_use import ComputerUseTool  # noqa: PLC0415
        registry.register(ComputerUseTool())
    except ImportError:
        pass  # cua-computer 未安装，工具不可用
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
    """统一 Agent 创建入口。"""
    from ethan.core.paths import ensure_user_dirs
    if user_id:
        set_user_id(user_id)
    ensure_user_dirs()
    registry = build_tool_registry(user_id=user_id, toolset=toolset, channel=channel)
    skills = _get_cached_skill_registry(user_id)
    return Agent(tool_registry=registry, skill_registry=skills, model=model, channel=channel, user_id=user_id, mode=mode)
