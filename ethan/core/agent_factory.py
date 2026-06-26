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
from ethan.tools.builtin.config import ConfigGetTool, ConfigSetTool
from ethan.tools.builtin.file import FileListTool, FileReadTool, FileWriteTool
from ethan.tools.builtin.knowledge import KnowledgeAddTool, KnowledgeSearchTool
from ethan.tools.builtin.memory_write import MemoryWriteTool
from ethan.tools.builtin.procedure_write import ProcedureWriteTool
from ethan.tools.builtin.profile_update import ProfileUpdateTool
from ethan.tools.builtin.schedule import ScheduleCreateTool, ScheduleListTool, ScheduleRemoveTool
from ethan.tools.builtin.search import FdTool, RipgrepTool
from ethan.tools.builtin.secrets import GetSecretTool, ListSecretsTool, SetSecretTool
from ethan.tools.builtin.shell import ShellTool
from ethan.tools.builtin.skill_create import SkillCreateTool
from ethan.tools.builtin.skill_read import SkillListTool, SkillReadTool
from ethan.tools.builtin.web import WebFetchTool
from ethan.tools.builtin.web_search import WebSearchTool
from ethan.tools.registry import ToolRegistry


def build_tool_registry(user_id: str = "", toolset: str = "full") -> ToolRegistry:
    """构建工具注册表。user_id 透传给需要它的工具（Schedule/Knowledge/Memory 等）。"""
    registry = ToolRegistry()
    # 基础工具（所有 toolset 共有）
    registry.register(ShellTool())
    registry.register(WebSearchTool())
    registry.register(WebFetchTool())
    registry.register(FileReadTool())
    registry.register(FileWriteTool())
    registry.register(FileListTool())

    if toolset == "heartbeat":
        # 心跳：只读 + 执行任务 + 调度 + 知识库，不写记忆/skill/profile
        registry.register(ScheduleCreateTool(user_id=user_id))
        registry.register(ScheduleListTool())
        registry.register(ScheduleRemoveTool())
        registry.register(KnowledgeSearchTool(user_id=user_id))
        registry.register(KnowledgeAddTool(user_id=user_id))
        return registry

    # full / lark：全量
    registry.register(RipgrepTool())
    registry.register(FdTool())
    registry.register(ScheduleCreateTool(user_id=user_id))
    registry.register(ScheduleListTool())
    registry.register(ScheduleRemoveTool())
    registry.register(KnowledgeSearchTool(user_id=user_id))
    registry.register(KnowledgeAddTool(user_id=user_id))
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
    registry = build_tool_registry(user_id=user_id, toolset=toolset)
    skills = SkillRegistry(user_id=user_id)
    skills.load()
    return Agent(tool_registry=registry, skill_registry=skills, model=model, channel=channel, user_id=user_id, mode=mode)
