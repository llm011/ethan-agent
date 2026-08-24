"""plugins 路由：插件列表/启用/禁用 + 服务重启。"""
from __future__ import annotations

import asyncio
import os

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from ethan.core.config import get_config, save_config

from .deps import verify_token

router = APIRouter()


# ── 类型定义 ──────────────────────────────────────────────────────


class PluginFieldOut(BaseModel):
    key: str
    label: str
    secret: bool = False
    default: str = ""
    hint: str = ""
    boolean: bool = False


class PluginOut(BaseModel):
    name: str
    label: str
    description: str
    category: str  # "config" | "preset" | "builtin"
    status: str  # "enabled" | "disabled" | "not_installed" | "always"
    fields: list[PluginFieldOut] = []
    config_path: str = ""
    current_values: dict[str, str] = {}


class AddPluginRequest(BaseModel):
    values: dict[str, str] = {}


class PluginActionResponse(BaseModel):
    ok: bool
    message: str
    restart_required: bool = False


class RestartResponse(BaseModel):
    ok: bool
    message: str


# ── 端点 ──────────────────────────────────────────────────────────


@router.get("/plugins", dependencies=[Depends(verify_token)])
async def list_plugins():
    """列出所有可用插件及状态。"""
    from ethan.interface.commands.plugin import PLUGIN_REGISTRY, _is_enabled, _resolve_config_obj
    from ethan.interface.commands.setup import PRESET_PLUGINS, _check_plugin_installed

    config = get_config()
    plugins: list[dict] = []

    for name, plugin in PLUGIN_REGISTRY.items():
        enabled = _is_enabled(config, plugin)
        fields = [
            PluginFieldOut(
                key=f.key,
                label=f.label,
                secret=f.secret,
                default=f.default or "",
                hint=f.hint or "",
                boolean=f.boolean,
            )
            for f in plugin.fields
        ]
        current_values: dict[str, str] = {}
        obj = _resolve_config_obj(config, plugin.config_path)
        if obj:
            for f in plugin.fields:
                val = getattr(obj, f.key, "")
                current_values[f.key] = str(val) if val else ""

        plugins.append(
            PluginOut(
                name=name,
                label=plugin.name,
                description=plugin.description,
                category="config",
                status="enabled" if enabled else "disabled",
                fields=fields,
                config_path=plugin.config_path,
                current_values=current_values,
            ).model_dump()
        )

    for p in PRESET_PLUGINS:
        if p["name"] in PLUGIN_REGISTRY:
            continue
        if p.get("install_type") == "plugin":
            continue
        installed = _check_plugin_installed(p)
        plugins.append(
            PluginOut(
                name=p["name"],
                label=p.get("label", p["name"]),
                description=p.get("description", ""),
                category="preset",
                status="enabled" if installed else "not_installed",
            ).model_dump()
        )

    plugins.append(
        PluginOut(
            name="duckduckgo",
            label="DuckDuckGo",
            description="DuckDuckGo 搜索（内置，零配置兜底）",
            category="builtin",
            status="always",
        ).model_dump()
    )

    return {"plugins": plugins}


@router.post("/plugins/{name}", dependencies=[Depends(verify_token)])
async def add_plugin(name: str, req: AddPluginRequest) -> PluginActionResponse:
    """启用/安装插件。"""
    from ethan.interface.commands.plugin import (
        PLUGIN_REGISTRY,
        _apply_plugin_config,
        _install_dida_cli,
    )
    from ethan.interface.commands.setup import PRESET_PLUGINS, _do_install

    plugin = PLUGIN_REGISTRY.get(name)
    if plugin:
        config = get_config()
        values = req.values
        if not values:
            for f in plugin.fields:
                if f.boolean:
                    values[f.key] = "true"
        _apply_plugin_config(config, plugin, values)
        save_config(config)
        if name == "dida" and values.get("enabled", "").lower() in ("1", "true", "yes", "on"):
            asyncio.get_event_loop().run_in_executor(None, _install_dida_cli)
        return PluginActionResponse(ok=True, message=f"插件 {name} 已启用", restart_required=True)

    preset = next((p for p in PRESET_PLUGINS if p["name"] == name), None)
    if preset:
        try:
            _do_install(preset)
        except Exception as e:  # noqa: BLE001
            return PluginActionResponse(ok=False, message=f"安装失败: {e}", restart_required=False)
        return PluginActionResponse(ok=True, message=f"插件 {name} 已安装", restart_required=True)

    return PluginActionResponse(ok=False, message=f"未知插件: {name}", restart_required=False)


@router.delete("/plugins/{name}", dependencies=[Depends(verify_token)])
async def remove_plugin(name: str) -> PluginActionResponse:
    """禁用/移除插件。"""
    from ethan.interface.commands.plugin import (
        PLUGIN_REGISTRY,
        _clear_plugin_config,
        _is_enabled,
    )

    plugin = PLUGIN_REGISTRY.get(name)
    if not plugin:
        return PluginActionResponse(ok=False, message=f"未知插件: {name}", restart_required=False)

    config = get_config()
    if not _is_enabled(config, plugin):
        return PluginActionResponse(ok=True, message=f"插件 {name} 当前未启用", restart_required=False)

    _clear_plugin_config(config, plugin)
    save_config(config)
    return PluginActionResponse(ok=True, message=f"插件 {name} 已移除", restart_required=True)


@router.post("/server/restart", dependencies=[Depends(verify_token)])
async def restart_server() -> RestartResponse:
    """重启服务进程（依赖 Docker restart policy 或 watchdog 自动拉起）。"""
    loop = asyncio.get_event_loop()
    loop.call_later(0.2, lambda: os._exit(0))
    return RestartResponse(ok=True, message="服务重启中...")
