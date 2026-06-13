from ethan.core.config import get_config
from ethan.providers.base import BaseProvider


def create_provider(model: str | None = None) -> BaseProvider:
    """根据 model id 或 alias 从配置中查找对应 provider，创建并返回。"""
    config = get_config()
    model_id = model or config.defaults.model
    proxy = config.network.proxy

    entry = config.get_model(model_id)
    if entry is not None:
        # alias 命中时，用真实的 model id 去调 API
        model_id = entry.id
        provider_key = entry.provider
    elif model_id.startswith("claude"):
        provider_key = "anthropic"
    else:
        provider_key = "openai_compat"

    provider_cfg = config.get_provider_config(provider_key)
    if provider_cfg is None:
        raise ValueError(f"Provider '{provider_key}' not found in config. Run: ethan model add")

    # provider 级别代理优先，全局兜底
    effective_proxy = provider_cfg.proxy or proxy

    if provider_key == "anthropic":
        from ethan.providers.anthropic import AnthropicProvider  # lazy: avoids top-level SDK import
        return AnthropicProvider(provider_cfg=provider_cfg, model=model_id, proxy=effective_proxy)
    else:
        from ethan.providers.openai_compat import OpenAICompatProvider  # lazy: avoids top-level SDK import
        return OpenAICompatProvider(provider_cfg=provider_cfg, model=model_id, proxy=effective_proxy)
