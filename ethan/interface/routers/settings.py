"""settings 路由：agent/system/provider/channel 配置 + onboarding + upload + prompt preview。"""
import os
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel

from ethan.core.config import get_config, save_config, reload_config
from .deps import verify_token, create_agent

router = APIRouter()


# ── Onboarding ────────────────────────────────────────────────────


class OnboardingCompleteRequest(BaseModel):
    agent_name: str
    user_info: str


@router.get("/onboarding/status")
async def onboarding_status(user_id: str = Depends(verify_token)):
    from ethan.core.onboarding import is_first_time, ONBOARDING_MESSAGE
    first_time = is_first_time(user_id)
    return {"first_time": first_time, "message": ONBOARDING_MESSAGE if first_time else ""}


@router.post("/onboarding/complete")
async def onboarding_complete(req: OnboardingCompleteRequest, user_id: str = Depends(verify_token)):
    from ethan.core.config import CONFIG_DIR
    from ethan.core.onboarding import mark_onboarded
    from ethan.memory.facts import FactStore
    from ethan.core.paths import user_facts_path

    agent_name = req.agent_name.strip() or "Ethan"
    user_info = req.user_info.strip()
    mark_onboarded(user_id)

    if agent_name != "Ethan":
        identity_path = CONFIG_DIR / "system" / "identity.md"
        if identity_path.exists():
            content = identity_path.read_text(encoding="utf-8")
            identity_path.write_text(content.replace("Ethan", agent_name), encoding="utf-8")

    if user_info:
        store = FactStore(path=user_facts_path())
        store.add(user_info, confidence=1.0, source="onboarding", category="preference")

    return {"ok": True, "agent_name": agent_name}


# ── Upload ────────────────────────────────────────────────────────


@router.post("/upload", dependencies=[Depends(verify_token)])
async def upload_file(file: UploadFile = File(...)):
    import tempfile
    content = await file.read()
    suffix = Path(file.filename or "upload").suffix
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(content)
        path = tmp.name
    return {"path": path, "filename": file.filename, "size": len(content)}


# ── Agent settings ────────────────────────────────────────────────


class AgentSettingsPatch(BaseModel):
    workspace: str | None = None
    agent_name: str | None = None
    language: str | None = None
    default_model: str | None = None
    lite_model: str | None = None
    heartbeat_enabled: bool | None = None
    heartbeat_interval_minutes: int | None = None
    proxy: str | None = None
    max_tokens: int | None = None
    max_tool_iterations: int | None = None
    fast_keywords: list[str] | None = None
    fast_max_length: int | None = None
    fast_skill_triggers: list[str] | None = None


@router.get("/settings/agent", dependencies=[Depends(verify_token)])
async def get_agent_settings():
    config = get_config()
    return {
        "workspace": config.defaults.workspace,
        "agent_name": config.defaults.agent_name,
        "language": config.defaults.language,
        "default_model": config.defaults.model,
        "lite_model": config.defaults.lite_model,
        "heartbeat_enabled": config.defaults.heartbeat.enabled,
        "heartbeat_interval_minutes": config.defaults.heartbeat.interval_minutes,
        "proxy": config.network.proxy or "",
        "max_tokens": config.defaults.max_tokens,
        "max_tool_iterations": config.defaults.max_tool_iterations,
        "fast_keywords": config.defaults.routing.fast_keywords,
        "fast_max_length": config.defaults.routing.fast_max_length,
        "fast_skill_triggers": config.defaults.routing.fast_skill_triggers,
    }


@router.patch("/settings/agent", dependencies=[Depends(verify_token)])
async def update_agent_settings(req: AgentSettingsPatch):
    config = get_config()
    if req.agent_name is not None:
        config.defaults.agent_name = req.agent_name
    if req.language is not None:
        config.defaults.language = req.language
    if req.default_model is not None:
        config.defaults.model = req.default_model
    if req.lite_model is not None:
        config.defaults.lite_model = req.lite_model or ""
    if req.workspace is not None:
        config.defaults.workspace = req.workspace
    if req.heartbeat_enabled is not None:
        config.defaults.heartbeat.enabled = req.heartbeat_enabled
    if req.heartbeat_interval_minutes is not None:
        config.defaults.heartbeat.interval_minutes = req.heartbeat_interval_minutes
    if req.proxy is not None:
        config.network.proxy = req.proxy or None
    if req.max_tokens is not None:
        config.defaults.max_tokens = req.max_tokens
    if req.max_tool_iterations is not None:
        config.defaults.max_tool_iterations = req.max_tool_iterations
    if req.fast_keywords is not None:
        config.defaults.routing.fast_keywords = req.fast_keywords
    if req.fast_max_length is not None:
        config.defaults.routing.fast_max_length = req.fast_max_length
    if req.fast_skill_triggers is not None:
        config.defaults.routing.fast_skill_triggers = req.fast_skill_triggers
    save_config(config)
    reload_config()
    return {"ok": True}


# ── System prompt settings ────────────────────────────────────────


class SystemSettingsPatch(BaseModel):
    identity: str | None = None
    soul: str | None = None
    agent: str | None = None
    tools: str | None = None
    heartbeat: str | None = None


@router.get("/settings/system", dependencies=[Depends(verify_token)])
async def get_system_settings():
    system_dir = Path(os.path.expanduser("~/.ethan/system"))
    files = {k: system_dir / f"{k}.md" for k in ("identity", "soul", "agent", "tools", "heartbeat")}
    return {k: (p.read_text(encoding="utf-8") if p.exists() else "") for k, p in files.items()}


@router.patch("/settings/system", dependencies=[Depends(verify_token)])
async def update_system_settings(req: SystemSettingsPatch):
    system_dir = Path(os.path.expanduser("~/.ethan/system"))
    system_dir.mkdir(parents=True, exist_ok=True)
    mapping = {
        "identity": req.identity,
        "soul": req.soul,
        "agent": req.agent,
        "tools": req.tools,
        "heartbeat": req.heartbeat,
    }
    for name, val in mapping.items():
        if val is None:
            continue
        if not val.strip():
            continue  # 空串视为不修改,避免误清空
        (system_dir / f"{name}.md").write_text(val, encoding="utf-8")
    return {"ok": True}


# ── User profile (我的画像) ────────────────────────────────────────


class UserProfilePatch(BaseModel):
    content: str  # 完整 user_profile.md 文本


@router.get("/settings/profile")
async def get_user_profile(user_id: str = Depends(verify_token)):
    """读取当前用户的 user_profile.md(不存在则生成含全部 section 的空模板)。"""
    from ethan.core.paths import user_profile_path
    from ethan.core.profile import ensure_profile
    content = ensure_profile(user_profile_path())
    return {"content": content}


@router.patch("/settings/profile")
async def update_user_profile(req: UserProfilePatch, user_id: str = Depends(verify_token)):
    """整篇覆盖写回当前用户的 user_profile.md。"""
    from ethan.core.paths import user_profile_path
    p = user_profile_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(req.content, encoding="utf-8")
    return {"ok": True}


# ── Provider settings ─────────────────────────────────────────────


@router.get("/settings/providers", dependencies=[Depends(verify_token)])
async def get_provider_settings():
    config = get_config()
    return {k: {"api_key": v.api_key, "base_url": v.base_url} for k, v in config.providers.items()}


@router.patch("/settings/providers", dependencies=[Depends(verify_token)])
async def update_provider_settings(req: dict[str, dict]):
    from ethan.core.config import ProviderConfig
    config = get_config()
    for k, v in req.items():
        if k not in config.providers:
            config.providers[k] = ProviderConfig()
        if "api_key" in v and v["api_key"] is not None:
            config.providers[k].api_key = v["api_key"]
        if "base_url" in v and v["base_url"] is not None:
            config.providers[k].base_url = v["base_url"]
    save_config(config)
    reload_config()
    return {"ok": True}


# ── Channels ──────────────────────────────────────────────────────


class ChannelPatchRequest(BaseModel):
    channel_id: str
    config: dict


@router.get("/channels", dependencies=[Depends(verify_token)])
async def get_channels():
    config = get_config()
    return {
        "channels": [
            {
                "id": "lark",
                "name": "飞书 (Feishu/Lark)",
                "enabled": bool(config.lark.app_id and config.lark.app_secret),
                "config": {"app_id": config.lark.app_id, "app_secret": config.lark.app_secret},
            }
        ]
    }


@router.patch("/channels", dependencies=[Depends(verify_token)])
async def patch_channel(req: ChannelPatchRequest):
    config = get_config()
    if req.channel_id == "lark":
        if "app_id" in req.config:
            config.lark.app_id = req.config["app_id"]
        if "app_secret" in req.config:
            config.lark.app_secret = req.config["app_secret"]
        save_config(config)
        reload_config()
        return {"ok": True}
    raise HTTPException(400, f"Unknown channel: {req.channel_id}")


# ── System prompt preview ─────────────────────────────────────────


@router.get("/system-prompt-preview", dependencies=[Depends(verify_token)])
async def system_prompt_preview(model: str | None = None):
    from ethan.providers.base import Message
    agent = create_agent(model)
    dummy_messages = [Message(role="user", content="(preview)")]
    system = agent._build_system(dummy_messages, fast=False)
    approx_tokens = len(system) // 2
    tools = agent._registry.all()
    tool_count = len(tools)
    return {
        "system_prompt": system,
        "tools": [{"name": t.name, "description": t.description, "parameters": t.parameters, "fast_path": t.fast_path} for t in tools],
        "approx_tokens": approx_tokens,
        "approx_tools_tokens": tool_count * 70,
        "tool_count": tool_count,
        "approx_total_tokens": approx_tokens + tool_count * 70,
        "chars": len(system),
    }


# ── Tool tiers (路由档位 → 实时工具集) ─────────────────────────────


@router.get("/tool-tiers", dependencies=[Depends(verify_token)])
async def tool_tiers(model: str | None = None):
    """实时计算三档路由各自广播给模型的工具集。

    与 agent._select_route 的取值规则保持一致：
      - fast 档：只广播 fast_path=True 的常驻工具；长尾工具靠模型调 find_tools 激活
      - medium / full 档：全量工具直接可见
    所以前端不写死任何清单，每次按当前注册表实时算。
    """
    agent = create_agent(model)
    tools = sorted(agent._registry.all(), key=lambda t: t.name)

    def info(t) -> dict:
        return {
            "name": t.name,
            "description": t.description,
            "fast_path": bool(t.fast_path),
            "side_effect": bool(getattr(t, "side_effect", False)),
            "no_compress": bool(getattr(t, "no_compress", False)),
        }

    fast_tools = [info(t) for t in tools if t.fast_path]
    all_tools = [info(t) for t in tools]
    routing = get_config().defaults.routing

    return {
        "tiers": [
            {
                "key": "fast",
                "label": "Fast 档",
                "desc": (
                    "短消息、或命中常驻技能/关键词触发词时进入。只广播下列常驻工具，"
                    "其余长尾能力需模型主动调 find_tools 激活后才可用。"
                ),
                "tools": fast_tools,
            },
            {
                "key": "medium",
                "label": "Medium 档",
                "desc": "中等长度消息。全量工具直接可见，迭代上限较 fast 高。",
                "tools": all_tools,
            },
            {
                "key": "full",
                "label": "Full 档",
                "desc": "长消息、复杂任务、或命中 FORCE_FULL 信号时进入。全量工具直接可见。",
                "tools": all_tools,
            },
        ],
        "fast_count": len(fast_tools),
        "total_count": len(all_tools),
        "fast_max_length": routing.fast_max_length,
        "medium_max_length": routing.medium_max_length,
    }
