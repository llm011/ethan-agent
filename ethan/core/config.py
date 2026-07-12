import os
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field

CONFIG_DIR = Path(os.environ.get("ETHAN_DATA_DIR", "")) if os.environ.get("ETHAN_DATA_DIR") else Path.home() / ".ethan"
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
    vision: bool = True  # 是否支持图片输入（大多数现代模型支持，旧文本模型可手动设为 False）
    fallback_providers: list[str] = Field(default_factory=list)  # 主 provider 不可用时依次尝试的备选 provider key 列表


class NetworkConfig(BaseModel):
    proxy: Optional[str] = None  # http://127.0.0.1:7890
    auth_token: str = ""  # Web UI 浏览器登录 token（default profile 的 web_token）
    api_keys: list[str] = Field(default_factory=list)  # /v1/chat/completions API keys（default profile）


class WeChatConfig(BaseModel):
    enabled: bool = False  # 设为 true 后 ethan serve 自动启动 iLink 长轮询
    # 登录凭证由 ethan wechat login（或首次启动时扫码）自动写入
    # ~/.ethan/memory/wechat_credentials.json，无需手动填写。


class LarkConfig(BaseModel):
    app_id: str = ""
    app_secret: str = ""
    verification_token: str = ""  # for event subscription verification
    encrypt_key: str = ""  # optional, for encrypted events
    # 复杂(high/full)回复是否用卡片(interactive)发送以支持流式编辑。
    # True：full 档用卡片流式 patch；fast/medium 档始终用 post markdown 一次性发。
    # False：所有档位都用 post markdown 一次性发（无流式编辑，但有 thinking 表情指示）。
    use_card: bool = True
    # 主人识别（飞书按发消息者 open_id 认主人）。空 = 还没认主人，首条消息后会询问。
    owner_open_id: str = ""
    # 主会话：用于发通知 / 定时任务结果的 chat_id。空 = 未设。
    main_chat_id: str = ""
    # 群聊响应模式（开通 im:message.group_msg:readonly 后生效，bot 可收到全量群消息）：
    # mention_only - 只回复 @mention（默认；未开通全量权限时也能工作）
    # always       - 所有群消息都回复
    # keywords     - 消息含任一 group_keywords 才回复（支持 * 通配）
    # llm_filter   - 调小模型判断是否需要处理（额外延迟约 0.5-1s，但可过滤无关闲聊）
    group_response_mode: str = "mention_only"
    # keywords 模式的关键词列表，例如 ["ethan", "帮我*", "查一下*"]
    group_keywords: list[str] = Field(default_factory=list)
    # llm_filter 模式的自定义过滤提示词（空则用内置默认提示）
    group_llm_filter_hint: str = ""
    # bot 在飞书群里的显示名（mention_only 模式用于识别 @bot），空则任意 @ 都触发
    bot_name: str = ""


class FastRule(BaseModel):
    """一条快捷路由规则：命中任一关键字 → 走 Fast Path，并按需加载指定的工具/技能。

    设计意图：fast 档默认只挂基础系统工具（见 RoutingConfig.fast_base_tools）。
    某条规则命中时，在基础工具之上额外挂载本规则声明的 tools，并强制注入 skills。
    若挂载的工具/技能仍不足以完成任务，模型可自行调 find_tools 激活全部进阶工具兜底。
    """
    name: str = ""                                   # 规则显示名（UI 展示用，可空）
    keywords: list[str] = Field(default_factory=list)  # 命中任一即触发（支持 * 通配）
    tools: list[str] = Field(default_factory=list)     # 额外挂载的工具名
    skills: list[str] = Field(default_factory=list)    # 强制注入 prompt 的技能名


class RoutingConfig(BaseModel):
    """任务路由配置：命中某条 fast_rule 的关键字 → 走 Fast Path（受限工具集 + 可选 lite 模型）。

    Fast 路由由 fast_rules 关键字驱动；未命中则走 Full Path。
    迭代上限统一用 defaults.max_tool_iterations，不分档——stuck detection 才是真正的兜底。
    """
    fast_base_tools: list[str] = Field(default_factory=lambda: [
        "shell", "file_read", "file_write", "skill_read", "skill_list", "find_tools",
        "schedule_create", "schedule_list", "schedule_remove",
    ])  # fast 档永远挂载的基础系统工具；find_tools 用于「规则工具不够时」兜底激活进阶工具
    base_tools: list[str] = Field(default_factory=lambda: [
        # 常用核心工具：full 档的初始广播集。
        # 长尾工具不在初始集里，模型按需调 find_tools 激活，避免白白广播 headers 和 schema。
        # browser 工具已移入初始集：扩展连上时直接可用；未连时模型调用后会得到
        # "扩展未连接"的明确报错，优于因 find_tools 激活失败陷入发现死循环超时。
        "shell", "web_search", "web_fetch", "get_weather", "generate_chart",
        "file_read", "file_write", "file_list",
        "skill_read", "skill_list", "find_tools",
        "rg_search", "fd_find",
        "knowledge_search", "knowledge_read",
        "memory_write", "procedure_write", "profile_update",
        "schedule_create", "schedule_list", "schedule_remove",
        "set_secret", "get_secret", "list_secrets",
        "skill_create", "install_skill",
        "browser_session", "browser_tab", "browser_page",
        "ui_card",
        # 飞书工具不再放在 base_tools：仅飞书渠道注册时才暴露（agent_factory.py）。
    ])
    fast_rules: list[FastRule] = Field(default_factory=lambda: [
        FastRule(
            name="智能家居控制",
            keywords=[
                "关*灯", "开*灯",
                "关*窗帘", "开*窗帘",
                "关*空调", "开*空调",
                "关*电视", "开*电视",
                "关*风扇", "开*风扇",
                "调*亮度", "调*温度", "调*音量",
                "播放音乐", "暂停", "下一首", "上一首",
            ],
            tools=["shell"],
            skills=["home-assistant-control"],
        ),
        FastRule(
            name="定时提醒",
            keywords=[
                "提醒我", "设置一个", "定时任务",
                "schedule", "reminder", "每天*点",
            ],
            tools=["schedule_create", "schedule_list", "schedule_remove"],
            skills=[],
        ),
        FastRule(
            name="快捷查询",
            keywords=[
                "查*票", "查*天气", "查*价格", "查*汇率",
                "今天天气", "明天天气", "天气怎么样",
                "*多少钱", "*什么价",
            ],
            tools=["web_search", "get_weather"],
            skills=[],
        ),
        FastRule(
            name="金融行情",
            keywords=[
                "A股", "股票", "上证", "深证", "指数", "行情",
                "大盘", "涨跌", "收盘", "开盘", "基金净值",
                "港股", "美股", "K线", "PE", "PB", "估值",
                "市值", "财报", "ROE", "市盈率", "板块",
                "茅台", "腾讯", "苹果", "AAPL", "TSLA",
                "利润表", "资产负债", "现金流", "EPS",
                "技术指标", "MA", "RSI", "MACD", "KDJ",
                "均线", "成交量", "ETF", "涨幅榜",
            ],
            tools=["shell", "web_search", "generate_chart"],
            skills=["finance-query"],
        ),
        FastRule(
            name="macOS App自动化",
            keywords=[
                "备忘录", "提醒事项", "日历*会议", "日历*日程",
                "滴答清单", "osascript", "AppleScript",
            ],
            tools=["shell"],
            skills=["macos-automation"],
        ),
        FastRule(
            name="出行查询",
            keywords=[
                "12306", "高铁", "火车", "动车", "车次", "列车",
                "北京到", "上海到", "广州到", "深圳到", "杭州到",
                "车票", "时刻表", "最早", "最晚",
            ],
            tools=["shell"],
            skills=["travel-query"],
        ),
    ])
    fast_use_lite_model: bool = True  # Fast Path 用 lite 模型（设备控制/状态查询等简单任务，省钱提速）


class HeartbeatConfig(BaseModel):
    enabled: bool = True
    interval_minutes: int = 10
    # 画像每日压缩触发钟点（北京时间 0-23）。该点之后的首个心跳 tick 触发，每天一次。
    profile_consolidate_hour: int = 2


class DefaultsConfig(BaseModel):
    workspace: str = str(Path.home() / ".ethan")
    model: str = "claude-sonnet-4.6"
    lite_model: str = ""  # 轻量模型，用于记忆压缩/标题生成/skill 生成等（空则按主模型推断）
    agent_name: str = "Ethan"
    language: str = "zh"
    timezone: str = ""  # IANA 时区名（如 "Asia/Shanghai"）。空 = 自动探测系统时区。
    max_tokens: int = 8192
    max_tool_iterations: int = 100
    routing: RoutingConfig = Field(default_factory=RoutingConfig)
    heartbeat: HeartbeatConfig = Field(default_factory=HeartbeatConfig)


class WebSearchToolConfig(BaseModel):
    provider: str = "duckduckgo"  # "duckduckgo" | "tavily" | "searxng"
    api_key: str = ""  # tavily 用
    base_url: str = ""  # searxng 用，如 http://localhost:8888（自建）或第三方现成实例地址

class ToolsConfig(BaseModel):
    web_search: WebSearchToolConfig = Field(default_factory=WebSearchToolConfig)


class Config(BaseModel):
    providers: dict[str, ProviderConfig] = Field(default_factory=dict)
    models: list[ModelEntry] = Field(default_factory=list)
    network: NetworkConfig = Field(default_factory=NetworkConfig)
    defaults: DefaultsConfig = Field(default_factory=DefaultsConfig)
    lark: LarkConfig = Field(default_factory=LarkConfig)
    wechat: WeChatConfig = Field(default_factory=WeChatConfig)
    tools: ToolsConfig = Field(default_factory=ToolsConfig)
    users: list["UserConfig"] = Field(default_factory=list)  # 多用户体系；为空时自动生成 admin

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


# 多用户体系：UserConfig 前向引用在此解析（users.py 仅在函数内 import config，无循环）
from ethan.core.users import UserConfig  # noqa: E402

Config.model_rebuild()


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
            {"id": "claude-opus-4.8",   "provider": "anthropic", "description": "Claude Opus 4.8"},
            {"id": "claude-opus-4.7",   "provider": "anthropic", "description": "Claude Opus 4.7"},
            {"id": "claude-opus-4.6",   "provider": "anthropic", "description": "Claude Opus 4.6"},
            {"id": "claude-sonnet-4.6", "provider": "anthropic", "description": "Claude Sonnet 4.6"},
            {"id": "claude-haiku-4.5",  "provider": "anthropic", "description": "Claude Haiku 4.5（cheap model）"},
        ],
        "network": {
            "proxy": None,
        },
        "defaults": {
            "model": os.environ.get("AGENT_DEFAULT_MODEL", "claude-sonnet-4.6"),
            "lite_model": os.environ.get("AGENT_LITE_MODEL", ""),  # 轻量模型（记忆压缩/标题生成等后台任务用）；空则按主模型推断或与主模型相同
            "max_tokens": 8192,
            "max_tool_iterations": 100,
        },
    }


def _init_system_files(agent_name: str) -> None:
    """首次安装时将默认系统文件释放到 ~/.ethan/system/。只在目标文件不存在时创建，不覆盖用户已有配置。"""

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
            try:
                shutil.copytree(src, dst)
            except PermissionError:
                # macOS extended attributes may block copytree; fallback to manual copy
                dst.mkdir(parents=True, exist_ok=True)
                for f in src.rglob("*"):
                    rel = f.relative_to(src)
                    target = dst / rel
                    if f.is_dir():
                        target.mkdir(parents=True, exist_ok=True)
                    else:
                        target.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(f, target)


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
        # 128 位随机 token（32 字符十六进制），抗暴力破解
        config.network.auth_token = secrets.token_hex(16)
        need_save = True

    # default profile 隐式存在，users 为空时不再生成 admin 条目
    if need_save:
        save_config(config)

    # 同步 UserStore 单例（首次构建或 reload 后重建），注入 default profile tokens
    from ethan.core.users import UserStore, set_user_store
    store = UserStore(config.users)
    store.set_default_tokens(
        web_token=config.network.auth_token,
        api_keys=config.network.api_keys,
    )
    set_user_store(store)

    _init_system_files(config.defaults.agent_name)
    _init_default_skills()

    # 旧 users/<admin>/ 架构 → 新 profile 架构（default = 顶层）。幂等，放最后。
    try:
        from ethan.core.paths import migrate_to_profiles
        migrated = migrate_to_profiles(config)
        if migrated:
            save_config(config)
            # 重建 UserStore（config.users 变了）
            from ethan.core.users import UserStore, set_user_store
            store = UserStore(config.users)
            store.set_default_tokens(
                web_token=config.network.auth_token,
                api_keys=config.network.api_keys,
            )
            set_user_store(store)
    except Exception as e:  # 迁移失败不应阻断启动
        import sys
        print(f"[multiuser] migration skipped: {e}", file=sys.stderr)

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
    """环境变量作为 config.yaml 的兜底，不覆盖显式配置。

    设计原则：用户在 config.yaml 里显式写的 provider 字段优先；环境变量仅在
    config.yaml 没配该字段时填充。这样用户在 config.yaml 配了 api_key/base_url 后，
    即使 shell 里残留了 ANTHROPIC_BASE_URL 等环境变量（常见于同时用 Claude Code 的机器）
    也不会被篡改。
    """
    from dotenv import load_dotenv
    load_dotenv()

    providers = raw.setdefault("providers", {})

    mapping = {
        "anthropic":    ("ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_API_KEY", "ANTHROPIC_BASE_URL", "anthropic"),
        "openai_compat": ("OPENAI_API_KEY", None, "OPENAI_BASE_URL", "openai_compat"),
        "glm":           ("GLM_API_KEY", "ZHIPU_API_KEY", None, "anthropic"),
    }
    for key, (env_key1, env_key2, env_base, default_type) in mapping.items():
        p = providers.setdefault(key, {})
        if "type" not in p:
            p["type"] = default_type
        token = os.environ.get(env_key1, "") if env_key1 else ""
        fallback = os.environ.get(env_key2, "") if env_key2 else ""
        if (token or fallback) and not p.get("api_key"):
            p["api_key"] = token or fallback
        base = os.environ.get(env_base, "") if env_base else ""
        if base and not p.get("base_url"):
            p["base_url"] = base
    # glm 兼容层需关闭 cache_control（BigModel 不支持）
    if "glm" in providers and not providers["glm"].get("base_url"):
        providers["glm"]["base_url"] = "https://open.bigmodel.cn/api/anthropic"
        providers["glm"]["disable_prompt_cache"] = True

    # SearXNG web_search 后端（可选）：docker-compose 常用环境变量配置，免得手改 config.yaml。
    # 只在 config.yaml 未显式配置时填充；SEARXNG_BASE_URL 存在即视为想用 searxng，自动切 provider。
    tools = raw.setdefault("tools", {})
    ws = tools.setdefault("web_search", {})
    searxng_url = os.environ.get("SEARXNG_BASE_URL", "")
    if searxng_url and not ws.get("base_url"):
        ws["base_url"] = searxng_url
        if not ws.get("provider"):
            ws["provider"] = "searxng"

    # 代理：环境变量 ETHAN_PROXY 覆盖
    proxy_env = os.environ.get("ETHAN_PROXY", "")
    if proxy_env:
        raw.setdefault("network", {})["proxy"] = proxy_env

    # Web UI 登录 token：环境变量 ETHAN_AUTH_TOKEN 覆盖
    # （否则 load_config 会用 secrets.token_hex(6) 随机生成一个写进 config.yaml）
    auth_env = os.environ.get("ETHAN_AUTH_TOKEN", "")
    if auth_env:
        raw.setdefault("network", {})["auth_token"] = auth_env


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
