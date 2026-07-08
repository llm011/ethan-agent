from ethan.core.config import ProviderConfig, get_config
from ethan.providers.base import BaseProvider


def _build_single_provider(provider_key: str, model_id: str,
                            provider_cfg: ProviderConfig, proxy: str | None) -> BaseProvider:
    provider_type = getattr(provider_cfg, "type", None) or (
        "anthropic" if provider_key == "anthropic" else "openai_compat"
    )
    if provider_type == "anthropic":
        from ethan.providers.anthropic import AnthropicProvider
        return AnthropicProvider(provider_cfg=provider_cfg, model=model_id, proxy=proxy)
    else:
        from ethan.providers.openai_compat import OpenAICompatProvider
        return OpenAICompatProvider(provider_cfg=provider_cfg, model=model_id, proxy=proxy)


def create_provider(model: str | None = None) -> BaseProvider:
    """根据 model id 或 alias 从配置中查找对应 provider，创建并返回。

    如果模型配置了 fallback_providers，返回 FallbackProvider（依次尝试主 provider
    和各 fallback；主 provider 断路时自动跳过，按指数退避恢复探测）。
    """
    config = get_config()
    model_id = model or config.defaults.model
    proxy = config.network.proxy

    entry = config.get_model(model_id)
    if entry is not None:
        model_id = entry.id
        provider_key = entry.provider
    else:
        if "/" in model_id:
            provider_key, model_id = model_id.split("/", 1)
        elif model_id.startswith("claude"):
            provider_key = "anthropic"
        else:
            provider_key = "openai_compat"

    provider_cfg = config.get_provider_config(provider_key)
    if provider_cfg is None:
        raise ValueError(f"Provider '{provider_key}' not found in config. Run: ethan model add")

    effective_proxy = provider_cfg.proxy or proxy
    primary = _build_single_provider(provider_key, model_id, provider_cfg, effective_proxy)

    # Build fallback chain if configured
    fallback_keys: list[str] = getattr(entry, "fallback_providers", []) if entry else []
    if not fallback_keys:
        return primary

    pairs: list[tuple[str, BaseProvider]] = [(provider_key, primary)]
    for fb_key in fallback_keys:
        fb_cfg = config.get_provider_config(fb_key)
        if fb_cfg is None:
            import logging
            logging.getLogger(__name__).warning(
                "fallback provider '%s' not found in config, skipping", fb_key
            )
            continue
        fb_proxy = fb_cfg.proxy or proxy
        # Use the same model id; fallback provider must serve the same or equivalent model
        try:
            fb_provider = _build_single_provider(fb_key, model_id, fb_cfg, fb_proxy)
            pairs.append((fb_key, fb_provider))
        except Exception as exc:
            import logging
            logging.getLogger(__name__).warning(
                "failed to create fallback provider '%s': %s", fb_key, exc
            )

    if len(pairs) == 1:
        return primary

    from ethan.providers.fallback import FallbackProvider
    return FallbackProvider(pairs)
