"""可编辑配置项 schema —— config_get/config_set 工具与 /config 编辑器共用。

只有列在这里的字段才允许通过 config 工具修改（白名单），
避免 agent 误改 api_key / auth_token 等敏感字段。
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ConfigField:
    path: str                  # 点分路径，如 "defaults.max_tool_iterations"
    label: str                 # 人类可读名称（编辑器展示用）
    kind: str                  # "bool" | "int" | "str" | "choice"
    choices: list[str] = field(default_factory=list)
    desc: str = ""             # 给 agent 看的说明
    min_val: int | None = None  # int 类型的下限


EDITABLE_FIELDS: list[ConfigField] = [
    ConfigField("defaults.agent_name", "Agent 名称", "str",
                desc="Agent 的显示名称，如 Ethan"),
    ConfigField("defaults.language", "语言", "choice", ["zh", "en"],
                desc="回复所用语言"),
    ConfigField("defaults.model", "主模型", "str",
                desc="主对话模型 ID，如 claude-sonnet-4.6 / gemini-3.5-flash"),
    ConfigField("defaults.lite_model", "轻量模型", "str",
                desc="后台任务（记忆压缩、标题生成）用的轻量模型，留空则与主模型相同"),
    ConfigField("defaults.max_tokens", "最大输出 tokens", "int",
                desc="单次回复的最大 token 数", min_val=1),
    ConfigField("defaults.max_tool_iterations", "工具迭代上限", "int",
                desc="单次回复的最大工具调用轮次。stuck detection 在真正死循环前强制收尾", min_val=1),
    ConfigField("defaults.heartbeat.enabled", "心跳", "bool",
                desc="是否启用定时心跳（Agent 周期性自检/整理）"),
    ConfigField("defaults.heartbeat.interval_minutes", "心跳间隔（分钟）", "int",
                desc="心跳触发的间隔（分钟）", min_val=1),
    ConfigField("tools.web_search.provider", "Web 搜索提供方", "choice",
                ["duckduckgo", "tavily", "searxng"],
                desc="web_search 工具的搜索后端：duckduckgo（默认，免费）/ tavily（需 api_key）/ searxng（需 base_url，自建或现成实例）"),
    ConfigField("tools.web_search.base_url", "SearXNG 地址", "str",
                desc="provider=searxng 时使用，如 http://localhost:8888（自建 docker-compose）或现成 SearXNG 实例地址"),
    ConfigField("tools.knowledge.backend", "知识库后端", "choice", ["filesystem", "obsidian", "external"],
                desc="知识库存储后端：filesystem（默认本地 MD）/ obsidian（Obsidian Vault）/ external（外部 API）"),
    ConfigField("tools.knowledge.obsidian_vault_path", "Obsidian Vault 路径", "str",
                desc="Obsidian vault 根目录绝对路径（backend=obsidian 时必填）"),
    ConfigField("tools.knowledge.obsidian_folder", "Obsidian 知识库子目录", "str",
                desc="Vault 内用于知识库的子目录名（默认 Knowledge）"),
    ConfigField("tools.knowledge.external_base_url", "外部知识库 API 地址", "str",
                desc="外部知识库 REST API 的 base URL（backend=external 时必填）"),
    ConfigField("tools.knowledge.external_api_key", "外部知识库 API Key", "str",
                desc="外部知识库认证 key（backend=external 时必填）"),
]

# 路径 → field 的索引，便于工具快速查找
_FIELD_BY_PATH = {f.path: f for f in EDITABLE_FIELDS}


def get_field(path: str) -> ConfigField | None:
    return _FIELD_BY_PATH.get(path)


def is_editable(path: str) -> bool:
    return path in _FIELD_BY_PATH


def get_value(obj, path: str):
    """按点分路径读取属性值。属性不存在时返回 None。"""
    for p in path.split("."):
        obj = getattr(obj, p, None)
        if obj is None:
            return None
    return obj


def set_value(obj, path: str, val) -> None:
    """按点分路径设置属性值。"""
    parts = path.split(".")
    for p in parts[:-1]:
        obj = getattr(obj, p)
    setattr(obj, parts[-1], val)


def coerce(field: ConfigField, raw):
    """把原始输入转换为目标类型，失败抛 ValueError。"""
    if field.kind == "bool":
        if isinstance(raw, bool):
            return raw
        s = str(raw).strip().lower()
        if s in ("true", "1", "yes", "on", "y"):
            return True
        if s in ("false", "0", "no", "off", "n", ""):
            return False
        raise ValueError(f"无法识别的布尔值: {raw}")
    if field.kind == "int":
        v = int(raw)
        if field.min_val is not None and v < field.min_val:
            raise ValueError(f"{field.path} 不能小于 {field.min_val}")
        return v
    if field.kind == "choice":
        s = str(raw).strip()
        if s not in field.choices:
            raise ValueError(f"{field.path} 只能取 {field.choices} 之一")
        return s
    # str
    return str(raw).strip()
