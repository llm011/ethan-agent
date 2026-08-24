"""Centralized httpx client factory.

Provides a single entry point for creating httpx.AsyncClient instances across
the codebase, applying shared defaults (proxy, trust_env) from config.
"""

from __future__ import annotations

import httpx


def create_http_client(
    *,
    timeout: float | httpx.Timeout = 15.0,
    follow_redirects: bool = False,
    proxy: str | None = None,
    use_config_proxy: bool = False,
    trust_env: bool = False,
    base_url: str = "",
    headers: dict[str, str] | None = None,
    **kwargs,
) -> httpx.AsyncClient:
    """Create an httpx.AsyncClient with sensible defaults.

    Args:
        timeout: Request timeout (seconds or httpx.Timeout).
        follow_redirects: Whether to follow redirects.
        proxy: Explicit proxy URL. Takes precedence over config.
        use_config_proxy: If True and no explicit proxy, read from config.
        trust_env: Whether to read HTTP_PROXY env vars (default False to avoid
                   container issues with loopback).
        base_url: Base URL for relative requests.
        headers: Extra default headers.
        **kwargs: Passed through to httpx.AsyncClient.
    """
    effective_proxy = proxy
    if not effective_proxy and use_config_proxy:
        try:
            from ethan.core.config import load_config
            effective_proxy = load_config().network.proxy or None
        except Exception:
            pass

    client_kwargs: dict = {
        "timeout": timeout,
        "follow_redirects": follow_redirects,
        "trust_env": trust_env,
        **kwargs,
    }
    if effective_proxy:
        client_kwargs["proxy"] = effective_proxy
    if base_url:
        client_kwargs["base_url"] = base_url
    if headers:
        client_kwargs["headers"] = headers

    return httpx.AsyncClient(**client_kwargs)
