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
from ethan.tools.builtin.acp import DelegateCodingTool
from ethan.tools.builtin.shell import ShellTool
from ethan.tools.builtin.search import RipgrepTool, FdTool
from ethan.tools.builtin.web import WebFetchTool
from ethan.tools.builtin.web_search import WebSearchTool
from ethan.tools.registry import ToolRegistry


async def verify_token(request: Request) -> str:
    """Bearer token 鉴权（用于内部管理 API），返回 user_id。

    解析顺序：
      1. config.users[].web_token → user_id（多账号体系主路径）
      2. fallback: config.network.auth_token → admin（兼容旧单 token 部署）
    """
    from ethan.core.users import get_user_store
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Unauthorized")
    token = auth.removeprefix("Bearer ").strip()

    user_store = get_user_store()
    user_id = user_store.resolve_web_token(token)

    if user_id is None:
        # 兼容旧 auth_token → admin
        config = get_config()
        if config.network.auth_token and token == config.network.auth_token:
            user_id = user_store.get_admin_user_id()
        else:
            raise HTTPException(status_code=401, detail="Unauthorized")

    request.state.user_id = user_id  # 供无法注入参数的中间场景使用
    return user_id


def create_agent(model: str | None = None, channel: str = "web", user_id: str = "") -> Agent:
    from ethan.core.paths import ensure_user_dirs
    ensure_user_dirs(user_id)

    registry = ToolRegistry()
    registry.register(ShellTool())
    registry.register(WebSearchTool())
    registry.register(RipgrepTool())
    registry.register(FdTool())
    registry.register(WebFetchTool())
    registry.register(FileReadTool())
    registry.register(FileWriteTool())
    registry.register(FileListTool())
    registry.register(ScheduleCreateTool(user_id=user_id))
    registry.register(ScheduleListTool())
    registry.register(ScheduleRemoveTool())
    registry.register(KnowledgeSearchTool(user_id=user_id))
    registry.register(KnowledgeAddTool(user_id=user_id))
    registry.register(MemoryWriteTool(user_id=user_id))
    registry.register(ProcedureWriteTool(user_id=user_id))
    registry.register(ProfileUpdateTool(user_id=user_id))
    registry.register(SkillCreateTool(user_id=user_id))
    registry.register(DelegateCodingTool(user_id=user_id))

    skills = SkillRegistry(user_id=user_id)
    skills.load()

    return Agent(tool_registry=registry, skill_registry=skills, model=model, channel=channel, user_id=user_id)
