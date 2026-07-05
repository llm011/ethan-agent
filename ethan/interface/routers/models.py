"""models 路由：model 列表 CRUD + provider 模型发现。

config.models 是用户显式配置的 model 列表（id + provider + description + alias）。
provider 发现：调 provider 的 /models 接口（OpenAI 兼容）拉候选，用户勾选后写入 config。
"""
from fastapi import APIRouter, Depends
from pydantic import BaseModel

from ethan.core.config import get_config, reload_config, save_config

from .deps import verify_token

router = APIRouter()


class ModelEntry(BaseModel):
    id: str
    provider: str
    description: str = ""
    alias: list[str] = []


@router.get("/models", dependencies=[Depends(verify_token)])
async def list_models():
    config = get_config()
    return {"models": [m.model_dump() for m in config.models]}


@router.post("/models", dependencies=[Depends(verify_token)])
async def add_model(req: ModelEntry):
    config = get_config()
    # 去重：同 id 同 provider 不重复加
    for m in config.models:
        if m.id == req.id and m.provider == req.provider:
            return {"ok": False, "error": "model already exists"}
    config.models.append(_to_config_model(req))
    save_config(config)
    reload_config()
    return {"ok": True}


@router.put("/models/{provider}/{model_id}", dependencies=[Depends(verify_token)])
async def update_model(provider: str, model_id: str, req: ModelEntry):
    config = get_config()
    for i, m in enumerate(config.models):
        if m.id == model_id and m.provider == provider:
            config.models[i] = _to_config_model(req)
            save_config(config)
            reload_config()
            return {"ok": True}
    return {"ok": False, "error": "model not found"}


@router.delete("/models/{provider}/{model_id}", dependencies=[Depends(verify_token)])
async def delete_model(provider: str, model_id: str):
    config = get_config()
    before = len(config.models)
    config.models = [m for m in config.models if not (m.id == model_id and m.provider == provider)]
    if len(config.models) == before:
        return {"ok": False, "error": "model not found"}
    save_config(config)
    reload_config()
    return {"ok": True}


class DiscoverRequest(BaseModel):
    provider: str  # config.providers 里的 key


@router.post("/models/discover", dependencies=[Depends(verify_token)])
async def discover_models(req: DiscoverRequest):
    """从 provider 的 /models 接口（OpenAI 兼容）拉取候选 model id。

    Anthropic provider 不支持 /models 列表，会返回其已知模型清单的硬编码兜底。
    """
    import httpx
    config = get_config()
    provider_cfg = config.providers.get(req.provider)
    if not provider_cfg:
        return {"ok": False, "error": f"provider '{req.provider}' not found"}

    base_url = (provider_cfg.base_url or "").rstrip("/")
    api_key = provider_cfg.api_key
    discovered: list[dict] = []

    if req.provider == "anthropic" or (provider_cfg.type == "anthropic"):
        # Anthropic 无公开 /models 列表端点，返回兜底清单
        discovered = [
            {"id": "claude-opus-4.8", "provider": req.provider, "description": "Claude Opus 4.8"},
            {"id": "claude-opus-4.7", "provider": req.provider, "description": "Claude Opus 4.7"},
            {"id": "claude-opus-4.6", "provider": req.provider, "description": "Claude Opus 4.6"},
            {"id": "claude-sonnet-4.6", "provider": req.provider, "description": "Claude Sonnet 4.6"},
            {"id": "claude-haiku-4.5", "provider": req.provider, "description": "Claude Haiku 4.5"},
        ]
    else:
        # OpenAI 兼容：GET /v1/models（或 base_url 自带 /v1 则直接 /models）
        url = f"{base_url}/models" if base_url.endswith("/v1") else f"{base_url}/v1/models"
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(url, headers={"Authorization": f"Bearer {api_key}"})
                resp.raise_for_status()
                data = resp.json()
            for item in data.get("data", []):
                mid = item.get("id") or ""
                if mid:
                    discovered.append({"id": mid, "provider": req.provider, "description": mid})
        except Exception as e:
            return {"ok": False, "error": f"failed to fetch /models: {e}", "url": url}

    # 标记哪些已在 config 中
    existing = {(m.id, m.provider) for m in config.models}
    for d in discovered:
        d["exists"] = (d["id"], d["provider"]) in existing
    return {"ok": True, "models": discovered}


def _to_config_model(req: ModelEntry):
    from ethan.core.config import ModelEntry as CfgModelEntry
    return CfgModelEntry(id=req.id, provider=req.provider, description=req.description, alias=req.alias)
