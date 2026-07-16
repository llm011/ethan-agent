"""UI Resources 路由：工具 UI 模板的发现与读取。

工具执行后，结果里只携带 uri + data；HTML 模板由前端按 uri 从这里拉取并缓存。
模板与数据分离，让模板只传输一次而数据随每条消息走。

端点：
- GET /api/ui-resources            → 列出所有已注册 ui:// 资源的元信息
- GET /api/ui-resources/read?uri=  → 读取单个资源的 HTML 内容 + _meta (CSP 等)

注：字段命名（uri/mimeType/text/_meta）与 MCP Resources 规范保持兼容，
    方便将来接入真正的 MCP Server 时无缝迁移，但当前走普通 REST，不是 MCP 协议。
"""
from fastapi import APIRouter, Depends, HTTPException, Query

# 工具模块在导入时于顶层 register_ui_resource（如 chart.py）。显式导入这些模块，
# 确保 registry 在首个请求前已填充，不依赖 agent_factory 的加载顺序。
# 新增带 UI 资源的工具时，在此追加一行导入即可。
import ethan.tools.builtin.chart  # noqa: F401
from ethan.tools.ui_resources import get_ui_registry

from .deps import verify_token

router = APIRouter(prefix="/ui-resources", dependencies=[Depends(verify_token)])


@router.get("")
async def list_ui_resources():
    """列出所有已注册 UI 资源的元信息（不含 HTML）。"""
    registry = get_ui_registry()
    return {"resources": [r.to_mcp_resource() for r in registry.list_all()]}


@router.get("/read")
async def read_ui_resource(uri: str = Query(..., description="ui:// 资源 URI")):
    """读取单个资源的 HTML 内容 + _meta（CSP/permissions）。"""
    content = get_ui_registry().read(uri)
    if content is None:
        raise HTTPException(404, f"UI resource not found: {uri}")
    return content
