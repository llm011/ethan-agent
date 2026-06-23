"""config_get / config_set 工具 —— 让 Agent 读写自己的运行时配置。

Agent 不需要知道 config.yaml 在哪、结构如何；通过这两个工具就能查看和修改。
白名单见 ethan.core.config_schema.EDITABLE_FIELDS，敏感字段（api_key / auth_token）不可改。
"""
from __future__ import annotations

from ethan.core.config_schema import (
    EDITABLE_FIELDS,
    coerce,
    get_field,
    get_value,
    set_value,
)
from ethan.tools.base import BaseTool


class ConfigGetTool(BaseTool):
    fast_path = False
    cacheable = False
    name = "config_get"
    description = (
        "查看 Ethan Agent 自己的运行时配置。不带参数时列出所有可配置项及其当前值、类型、说明；"
        "带 key 参数时返回单个配置项的值。"
        "用户问'你的配置是什么'、'某个设置现在是多少'、或想改配置前先查看时调用。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "key": {
                "type": "string",
                "description": "可选。点分路径，如 defaults.max_tool_iterations。省略则列出全部。",
            },
        },
        "required": [],
    }

    async def run(self, key: str = "") -> str:
        from ethan.core.config import get_config
        config = get_config()

        if key:
            field = get_field(key)
            if not field:
                return (f"未知配置项: {key}\n"
                        f"可用项: {', '.join(f.path for f in EDITABLE_FIELDS)}")
            val = get_value(config, key)
            return f"{key}（{field.label}, {field.kind}）= {_fmt(val)}\n说明: {field.desc}"

        # 列出全部
        lines = ["可编辑配置项（用 config_set 修改，key 为点分路径）:", ""]
        for f in EDITABLE_FIELDS:
            val = get_value(config, f.path)
            lines.append(f"- {f.path}（{f.kind}）= {_fmt(val)}  # {f.desc}")
        return "\n".join(lines)


class ConfigSetTool(BaseTool):
    fast_path = False
    cacheable = False
    name = "config_set"
    description = (
        "修改 Ethan Agent 自己的运行时配置项，立即保存生效。"
        "用户要求改某个设置（如'把工具迭代上限设成 50'、'开启心跳'、'换模型'）时调用。"
        "key 必须是 config_get 列出的点分路径，value 须匹配类型（int/bool/str/choice）。"
        "敏感字段（api_key / auth_token / provider）不在此工具范围内，无法修改。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "key": {
                "type": "string",
                "description": "点分路径，如 defaults.max_tool_iterations / heartbeat.enabled / defaults.model",
            },
            "value": {
                "description": "新值。int 传数字，bool 传 true/false，choice 传可选值之一（如 zh），str 传字符串。",
            },
        },
        "required": ["key", "value"],
    }

    async def run(self, key: str, value) -> str:
        from ethan.core.config import get_config, save_config, reload_config

        field = get_field(key)
        if not field:
            return (f"不可修改的配置项: {key}\n"
                    f"仅支持: {', '.join(f.path for f in EDITABLE_FIELDS)}\n"
                    f"提示: provider / api_key / auth_token 等请通过 `ethan provider set` 或编辑 config.yaml 修改。")

        config = get_config()
        old = get_value(config, key)
        try:
            new = coerce(field, value)
        except ValueError as e:
            return f"Error: {e}"

        set_value(config, key, new)
        try:
            save_config(config)
            reload_config()
        except Exception as e:
            # 回滚
            set_value(config, key, old)
            return f"Error 保存失败（已回滚）: {e}"

        return (f"✓ 已更新 {field.label}\n"
                f"  {key}: {_fmt(old)} → {_fmt(new)}\n"
                f"  已写入 config.yaml 并立即生效。")


def _fmt(val) -> str:
    if val is None or val == "":
        return "(空)"
    if isinstance(val, bool):
        return "true" if val else "false"
    return str(val)
