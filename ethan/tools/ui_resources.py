"""Tool UI Resource 注册与管理。

工具可在执行结果里携带 UI 资源引用，由前端负责渲染：
- 每个 UI 资源通过 ui:// URI 标识
- 工具结果只携带 {uri, data}，HTML 模板由前端按 URI 拉取并缓存
- 模板 HTML 通过 /api/ui-resources/read?uri= 读取
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# 内置 UI 模板目录
_TEMPLATES_DIR = Path(__file__).parent.parent / "defaults" / "ui-templates"


@dataclass
class UIResourceMeta:
    """UI 资源元信息：CSP + permissions + visual config。"""
    csp: dict[str, list[str]] = field(default_factory=dict)
    permissions: dict[str, dict] = field(default_factory=dict)
    prefers_border: bool = True


@dataclass
class UIResource:
    """工具 UI 资源声明：uri + HTML 模板 + 元信息。"""
    uri: str  # e.g. "ui://ethan/chart"
    name: str  # human-readable
    description: str = ""
    mime_type: str = "text/html"
    # HTML 内容来源：template_file 从 defaults/ui-templates/ 加载，或 html 直接指定
    template_file: str = ""  # 相对于 ui-templates/ 的文件名
    html: str = ""  # 直接指定 HTML 内容（优先级低于 template_file）
    meta: UIResourceMeta = field(default_factory=UIResourceMeta)

    def read_html(self) -> str:
        """读取 HTML 内容。"""
        if self.template_file:
            path = _TEMPLATES_DIR / self.template_file
            if path.exists():
                return path.read_text(encoding="utf-8")
        return self.html

    def to_mcp_resource(self) -> dict[str, Any]:
        """输出 resources/list 格式（uri + name + description + mimeType）。"""
        return {
            "uri": self.uri,
            "name": self.name,
            "description": self.description,
            "mimeType": self.mime_type,
        }

    def to_mcp_content(self) -> dict[str, Any]:
        """输出 resources/read 格式（含 HTML 内容和 _meta CSP 信息）。"""
        meta: dict[str, Any] = {}
        if self.meta.csp:
            meta["csp"] = self.meta.csp
        if self.meta.permissions:
            meta["permissions"] = self.meta.permissions
        meta["prefersBorder"] = self.meta.prefers_border

        return {
            "uri": self.uri,
            "mimeType": self.mime_type,
            "text": self.read_html(),
            "_meta": {"ui": meta},
        }


class UIResourceRegistry:
    """管理所有 UI 资源。"""

    def __init__(self):
        self._resources: dict[str, UIResource] = {}

    def register(self, resource: UIResource) -> None:
        self._resources[resource.uri] = resource

    def get(self, uri: str) -> UIResource | None:
        return self._resources.get(uri)

    def list_all(self) -> list[UIResource]:
        return list(self._resources.values())

    def read(self, uri: str) -> dict[str, Any] | None:
        """resources/read — 返回资源内容或 None（uri 未注册时）。"""
        res = self.get(uri)
        if res is None:
            return None
        return res.to_mcp_content()


# 全局单例
_registry = UIResourceRegistry()


def get_ui_registry() -> UIResourceRegistry:
    return _registry


def register_ui_resource(resource: UIResource) -> None:
    _registry.register(resource)
