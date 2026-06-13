import os
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field


CONFIG_DIR = Path.home() / ".ethan"
CONFIG_FILE = CONFIG_DIR / "config.yaml"


class ProviderConfig(BaseModel):
    api_key: str = ""
    base_url: Optional[str] = None
    proxy: Optional[str] = None  # provider 级别代理，覆盖全局


class ModelEntry(BaseModel):
    id: str
    provider: str
    description: str = ""
    alias: list[str] = Field(default_factory=list)  # 短名，如 ["flash", "gemini"]


class NetworkConfig(BaseModel):
    proxy: Optional[str] = None  # http://127.0.0.1:7890
    auth_token: str = ""  # API auth token for web UI


class LarkConfig(BaseModel):
    app_id: str = ""
    app_secret: str = ""
    verification_token: str = ""  # for event subscription verification
    encrypt_key: str = ""  # optional, for encrypted events


class RoutingConfig(BaseModel):
    """任务路由配置：匹配 fast_keywords 中任意关键词且消息长度 ≤ fast_max_length 时走 Fast Path。"""
    fast_keywords: list[str] = Field(default_factory=lambda: [
        "关*灯", "开*灯",
        "关*窗帘", "开*窗帘",
        "关*空调", "开*空调",
        "关*电视", "开*电视",
        "关*风扇", "开*风扇",
        "调*亮度", "调*温度", "调*音量",
        "播放音乐", "暂停", "下一首", "上一首",
    ])
    fast_max_length: int = 12  # 消息超过此长度不走 Fast Path（简单控制命令通常 ≤ 10 字）
    fast_skill_triggers: list[str] = Field(default_factory=list)  # 命中时强制走 Fast Path，不受长度限制（给 Skill 关联用）


class HeartbeatConfig(BaseModel):
    enabled: bool = True
    interval_minutes: int = 10


class DefaultsConfig(BaseModel):
    workspace: str = str(Path.home() / ".ethan")
    model: str = "claude-sonnet-4-6"
    agent_name: str = "Ethan"
    system_prompt: str = "You are Ethan, a helpful personal AI assistant. 请用中文回复。"
    language: str = "zh"
    max_tokens: int = 4096
    max_tool_iterations: int = 10
    routing: RoutingConfig = Field(default_factory=RoutingConfig)
    heartbeat: HeartbeatConfig = Field(default_factory=HeartbeatConfig)


class Config(BaseModel):
    providers: dict[str, ProviderConfig] = Field(default_factory=dict)
    models: list[ModelEntry] = Field(default_factory=list)
    network: NetworkConfig = Field(default_factory=NetworkConfig)
    defaults: DefaultsConfig = Field(default_factory=DefaultsConfig)
    lark: LarkConfig = Field(default_factory=LarkConfig)

    def get_model(self, model_id: str) -> Optional[ModelEntry]:
        for m in self.models:
            if m.id == model_id or model_id in m.alias:
                return m
        return None

    def get_provider_config(self, provider_key: str) -> Optional[ProviderConfig]:
        return self.providers.get(provider_key)

    def model_ids(self) -> list[str]:
        return [m.id for m in self.models]


# ── 持久化 ───────────────────────────────────────────────────────

def _default_config() -> dict:
    return {
        "providers": {
            "anthropic": {
                "api_key": os.environ.get("ANTHROPIC_AUTH_TOKEN", ""),
                "base_url": os.environ.get("ANTHROPIC_BASE_URL", None),
            },
            "openai_compat": {
                "api_key": os.environ.get("OPENAI_API_KEY", ""),
                "base_url": os.environ.get("OPENAI_BASE_URL", None),
            },
        },
        "models": [
            {"id": "claude-sonnet-4-6", "provider": "anthropic", "description": "Claude Sonnet 4.6"},
            {"id": "claude-opus-4-6",   "provider": "anthropic", "description": "Claude Opus 4.6"},
            {"id": "gemini-2.5-flash",  "provider": "openai_compat", "description": "Gemini 2.5 Flash"},
            {"id": "gemini-2.5-pro",    "provider": "openai_compat", "description": "Gemini 2.5 Pro"},
        ],
        "network": {
            "proxy": None,
        },
        "defaults": {
            "model": os.environ.get("AGENT_DEFAULT_MODEL", "gemini-2.5-flash"),
            "system_prompt": "You are Ethan, a helpful personal AI assistant. 请用中文回复。",
            "max_tokens": 4096,
            "max_tool_iterations": 10,
        },
    }


def load_config() -> Config:
    import yaml
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)

    if not CONFIG_FILE.exists():
        raw = _default_config()
        _write_raw(raw)
    else:
        with open(CONFIG_FILE) as f:
            raw = yaml.safe_load(f) or {}

    _apply_env_overrides(raw)
    return Config.model_validate(raw)


def save_config(config: Config) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    _write_raw(config.model_dump())


def _write_raw(data: dict) -> None:
    import yaml
    with open(CONFIG_FILE, "w") as f:
        yaml.dump(data, f, allow_unicode=True, default_flow_style=False, sort_keys=False)


def _apply_env_overrides(raw: dict) -> None:
    from dotenv import load_dotenv
    load_dotenv()

    providers = raw.setdefault("providers", {})

    mapping = {
        "anthropic":    ("ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_API_KEY", "ANTHROPIC_BASE_URL"),
        "openai_compat": ("OPENAI_API_KEY", None, "OPENAI_BASE_URL"),
    }
    for key, (env_key1, env_key2, env_base) in mapping.items():
        p = providers.setdefault(key, {})
        token = os.environ.get(env_key1, "") if env_key1 else ""
        fallback = os.environ.get(env_key2, "") if env_key2 else ""
        if token or fallback:
            p["api_key"] = token or fallback
        base = os.environ.get(env_base, "") if env_base else ""
        if base:
            p["base_url"] = base

    # 代理：环境变量 ETHAN_PROXY 覆盖
    proxy_env = os.environ.get("ETHAN_PROXY", "")
    if proxy_env:
        raw.setdefault("network", {})["proxy"] = proxy_env


# ── 单例 ────────────────────────────────────────────────────────

_config: Optional[Config] = None


def get_config() -> Config:
    global _config
    if _config is None:
        _config = load_config()
    return _config


def reload_config() -> Config:
    global _config
    _config = load_config()
    return _config
