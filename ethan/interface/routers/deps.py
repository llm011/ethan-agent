"""共享依赖：鉴权、Agent 工厂。"""
from fastapi import Depends, HTTPException, Request

from ethan.core.agent import Agent
from ethan.core.config import get_config
from ethan.skills.registry import SkillRegistry
from ethan.tools.builtin.file import FileListTool, FileReadTool, FileWriteTool
from ethan.tools.builtin.knowledge import KnowledgeAddTool, KnowledgeSearchTool
from ethan.tools.builtin.memory_write import MemoryWriteTool
from ethan.tools.builtin.procedure_write import ProcedureWriteTool
from ethan.tools.builtin.profile_update import ProfileUpdateTool
from ethan.tools.builtin.schedule import ScheduleCreateTool, ScheduleListTool, ScheduleRemoveTool
from ethan.tools.builtin.skill_create import SkillCreateTool
from ethan.tools.builtin.shell import ShellTool
from ethan.tools.builtin.search import RipgrepTool, FdTool
from ethan.tools.builtin.web import WebFetchTool
from ethan.tools.builtin.web_search import WebSearchTool
from ethan.tools.registry import ToolRegistry


async def verify_token(request: Request):
    """Bearer token 鉴权（用于内部管理 API）。"""
    config = get_config()
    token = config.network.auth_token
    if not token:
        return
    auth = request.headers.get("Authorization", "")
    if auth != f"Bearer {token}":
        raise HTTPException(status_code=401, detail="Unauthorized")


def create_agent(model: str | None = None, channel: str = "web") -> Agent:
    registry = ToolRegistry()
    registry.register(ShellTool())
    registry.register(WebSearchTool())
    registry.register(RipgrepTool())
    registry.register(FdTool())
    registry.register(WebFetchTool())
    registry.register(FileReadTool())
    registry.register(FileWriteTool())
    registry.register(FileListTool())
    registry.register(ScheduleCreateTool())
    registry.register(ScheduleListTool())
    registry.register(ScheduleRemoveTool())
    registry.register(KnowledgeSearchTool())
    registry.register(KnowledgeAddTool())
    registry.register(MemoryWriteTool())
    registry.register(ProcedureWriteTool())
    registry.register(ProfileUpdateTool())
    registry.register(SkillCreateTool())

    skills = SkillRegistry()
    skills.load()

    return Agent(tool_registry=registry, skill_registry=skills, model=model, channel=channel)
