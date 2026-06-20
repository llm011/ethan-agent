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
    type: str = "openai_compat"  # "anthropic" | "openai_compat"
    disable_prompt_cache: bool = False  # 第三方 Anthropic 兼容服务不支持 cache_control 时设为 true


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
        "定时任务", "有哪些任务", "任务列表", "什么任务", "定时提醒",
    ])
    fast_max_length: int = 12  # 消息超过此长度不走 Fast Path（简单控制命令通常 ≤ 10 字）
    fast_skill_triggers: list[str] = Field(default_factory=list)  # 命中时强制走 Fast Path，不受长度限制（给 Skill 关联用）
    medium_max_length: int = 80   # 超过 fast_max_length 且不超过此值走 Medium Path
    medium_max_iters: int = 15    # Medium Path 最多迭代次数，应对短文本但重搜索的任务


class HeartbeatConfig(BaseModel):
    enabled: bool = True
    interval_minutes: int = 10


class DefaultsConfig(BaseModel):
    workspace: str = str(Path.home() / ".ethan")
    model: str = "claude-sonnet-4-6"
    agent_name: str = "Ethan"
    language: str = "zh"
    max_tokens: int = 4096
    max_tool_iterations: int = 10
    routing: RoutingConfig = Field(default_factory=RoutingConfig)
    heartbeat: HeartbeatConfig = Field(default_factory=HeartbeatConfig)


class WebSearchToolConfig(BaseModel):
    provider: str = "duckduckgo"
    api_key: str = ""

class ToolsConfig(BaseModel):
    web_search: WebSearchToolConfig = Field(default_factory=WebSearchToolConfig)

class Config(BaseModel):
    providers: dict[str, ProviderConfig] = Field(default_factory=dict)
    models: list[ModelEntry] = Field(default_factory=list)
    network: NetworkConfig = Field(default_factory=NetworkConfig)
    defaults: DefaultsConfig = Field(default_factory=DefaultsConfig)
    lark: LarkConfig = Field(default_factory=LarkConfig)
    tools: ToolsConfig = Field(default_factory=ToolsConfig)

    def get_model(self, model_id: str) -> Optional[ModelEntry]:
        # 检查是否为数字索引
        if model_id.isdigit():
            idx = int(model_id) - 1
            if 0 <= idx < len(self.models):
                return self.models[idx]

        # 格式支持: "my-provider/gemini-1.5"
        target_provider = None
        target_model = model_id
        if "/" in model_id:
            parts = model_id.split("/", 1)
            target_provider = parts[0]
            target_model = parts[1]

        for m in self.models:
            # 如果指定了 provider，强制匹配
            if target_provider and m.provider != target_provider:
                continue
            if m.id == target_model or target_model in m.alias:
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
                "api_key": os.environ.get("ANTHROPIC_API_KEY", "") or os.environ.get("ANTHROPIC_AUTH_TOKEN", ""),
                "base_url": os.environ.get("ANTHROPIC_BASE_URL", None),
                "type": "anthropic",
            },
            "openai_compat": {
                "api_key": os.environ.get("OPENAI_API_KEY", ""),
                "base_url": os.environ.get("OPENAI_BASE_URL", None),
                "type": "openai_compat",
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
            "max_tokens": 4096,
            "max_tool_iterations": 10,
        },
    }


def _init_system_files(agent_name: str) -> None:
    """首次安装时将默认系统文件释放到 ~/.ethan/system/。只在目标文件不存在时创建，不覆盖用户已有配置。"""
    import shutil

    defaults_dir = Path(__file__).parent.parent / "defaults" / "system"
    if not defaults_dir.exists():
        return

    system_dir = CONFIG_DIR / "system"
    system_dir.mkdir(parents=True, exist_ok=True)

    for src in defaults_dir.glob("*.md"):
        dst = system_dir / src.name
        if not dst.exists():
            content = src.read_text(encoding="utf-8")
            content = content.replace("{agent_name}", agent_name)
            dst.write_text(content, encoding="utf-8")


def _init_default_skills() -> None:
    """首次安装时将默认技能释放到 ~/.ethan/skills/。只在目标不存在时创建，不覆盖用户已有技能。"""
    import shutil

    defaults_dir = Path(__file__).parent.parent / "defaults" / "skills"
    if not defaults_dir.exists():
        return

    skills_dir = CONFIG_DIR / "skills"
    skills_dir.mkdir(parents=True, exist_ok=True)

    for src in defaults_dir.iterdir():
        if not src.is_dir():
            continue
        dst = skills_dir / src.name
        if not dst.exists():
            shutil.copytree(src, dst)


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
    config = Config.model_validate(raw)

    need_save = False
    if not config.network.auth_token:
        import secrets
        config.network.auth_token = secrets.token_hex(6)
        need_save = True

    if need_save:
        save_config(config)

    _init_system_files(config.defaults.agent_name)
    _init_default_skills()
    return config


def save_config(config: Config) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)

    # 手动序列化，保留 type 字段，但去除其他可选/空字段
    data = config.model_dump(exclude_defaults=True, exclude_none=True)

    # 由于 exclude_defaults 会把等于默认值的字段去掉（比如 type="openai_compat"），
    # 但我们需要明确持久化 type，所以对于存在于 config.providers 中的，强制把 type 写进去
    if "providers" in data:
        for k, p in config.providers.items():
            if k in data["providers"]:
                data["providers"][k]["type"] = p.type

    _write_raw(data)


def _write_raw(data: dict) -> None:
    import yaml
    with open(CONFIG_FILE, "w") as f:
        yaml.dump(data, f, allow_unicode=True, default_flow_style=False, sort_keys=False)


def _apply_env_overrides(raw: dict) -> None:
    from dotenv import load_dotenv
    load_dotenv()

    providers = raw.setdefault("providers", {})

    mapping = {
        "anthropic":    ("ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_API_KEY", "ANTHROPIC_BASE_URL", "anthropic"),
        "openai_compat": ("OPENAI_API_KEY", None, "OPENAI_BASE_URL", "openai_compat"),
    }
    for key, (env_key1, env_key2, env_base, default_type) in mapping.items():
        p = providers.setdefault(key, {})
        if "type" not in p:
            p["type"] = default_type
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
