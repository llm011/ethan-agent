"""UI Resources 路由：MCP Apps (SEP-1865) 资源发现与读取。

前端作为 MCP host，通过这两个端点获取 UI 模板：
- GET /api/ui-resources            → resources/list：列出所有已注册 ui:// 资源
- GET /api/ui-resources/read?uri=  → resources/read：读取单个资源的 HTML 内容 + _meta

工具执行结果里只携带 uri + data（见 ChartTool.mcp_app），HTML 模板由前端按 uri
拉取并缓存。模板与数据分离，正是 MCP Apps 的核心约定。
"""
from fastapi import APIRouter, HTTPException, Query

# 工具模块在导入时于顶层 register_ui_resource（如 chart.py）。显式导入这些模块，
# 确保 registry 在首个请求前已填充，不依赖 agent_factory 的加载顺序。
# 新增带 UI 资源的工具时，在此追加一行导入即可。
import ethan.tools.builtin.chart  # noqa: F401
from ethan.tools.ui_resources import get_ui_registry

router = APIRouter(prefix="/ui-resources")


@router.get("")
async def list_ui_resources():
    """SEP-1865 resources/list：返回所有已注册 UI 资源的元信息（不含 HTML）。"""
    registry = get_ui_registry()
    return {"resources": [r.to_mcp_resource() for r in registry.list_all()]}


@router.get("/read")
async def read_ui_resource(uri: str = Query(..., description="ui:// 资源 URI")):
    """SEP-1865 resources/read：返回单个资源的 HTML 内容 + _meta（CSP/permissions）。"""
    content = get_ui_registry().read(uri)
    if content is None:
        raise HTTPException(404, f"UI resource not found: {uri}")
    return content
