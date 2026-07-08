"""FallbackProvider — wraps multiple providers and switches on network failures.

Retry classification:
  - Network errors (connect, timeout, remote protocol) → retriable, try next provider
  - HTTP 502/503/504 from upstream → retriable
  - Auth errors, bad request (4xx except 429) → non-retriable, raise immediately
  - Rate-limit (429) → retriable (different provider may have quota)

For stream_chat, fallback only kicks in if the error occurs before the first
chunk has been yielded.  Mid-stream failures are re-raised because the caller
has already seen partial output.
"""
from __future__ import annotations

import logging
from typing import AsyncIterator

from ethan.providers.base import BaseProvider, Message, StreamChunk, ToolDefinition
from ethan.providers.circuit_breaker import get_circuit_breaker

logger = logging.getLogger(__name__)


def _is_retriable(e: Exception) -> bool:
    """Return True if the exception represents a transient network/infra failure."""
    try:
        import httpx
        if isinstance(e, (httpx.ConnectError, httpx.TimeoutException,
                          httpx.RemoteProtocolError, httpx.ReadError)):
            return True
        if isinstance(e, httpx.HTTPStatusError) and e.response.status_code in (429, 502, 503, 504):
            return True
    except ImportError:
        pass

    try:
        from openai import APIConnectionError, APIStatusError
        if isinstance(e, APIConnectionError):
            return True
        if isinstance(e, APIStatusError) and e.status_code in (429, 502, 503, 504):
            return True
    except ImportError:
        pass

    try:
        import anthropic
        if isinstance(e, anthropic.APIConnectionError):
            return True
        if isinstance(e, anthropic.APIStatusError) and e.status_code in (429, 502, 503, 504):
            return True
    except ImportError:
        pass

    msg = str(e).lower()
    return any(k in msg for k in (
        "connection", "timeout", "fetch failed",
        "502", "503", "504",
        "network", "remote end closed", "eof",
    ))


class FallbackProvider(BaseProvider):
    """Tries providers in order; skips ones whose circuit is open."""

    def __init__(self, providers: list[tuple[str, BaseProvider]]) -> None:
        # providers: [(provider_key, provider_instance), ...]  primary first
        self._providers = providers

    @property
    def model(self) -> str:
        return self._providers[0][1].model

    async def chat(
        self,
        messages: list[Message],
        tools: list[ToolDefinition] | None = None,
        system: str | None = None,
    ) -> Message:
        breaker = get_circuit_breaker()
        last_err: Exception | None = None
        for key, provider in self._providers:
            if not breaker.is_available(key):
                logger.info("fallback: skipping %s (circuit open)", key)
                continue
            try:
                result = await provider.chat(messages, tools, system)
                breaker.record_success(key)
                if key != self._providers[0][0]:
                    logger.info("fallback: %s succeeded (primary was unavailable)", key)
                return result
            except Exception as e:
                if _is_retriable(e):
                    breaker.record_failure(key)
                    last_err = e
                    logger.warning("fallback: %s failed (%s), trying next provider", key, e)
                else:
                    raise
        raise last_err or RuntimeError("all providers unavailable")

    async def stream_chat(
        self,
        messages: list[Message],
        tools: list[ToolDefinition] | None = None,
        system: str | None = None,
    ) -> AsyncIterator[StreamChunk]:
        breaker = get_circuit_breaker()
        last_err: Exception | None = None
        for key, provider in self._providers:
            if not breaker.is_available(key):
                logger.info("fallback: skipping %s (circuit open)", key)
                continue
            try:
                started = False
                async for chunk in provider.stream_chat(messages, tools, system):
                    started = True
                    yield chunk
                breaker.record_success(key)
                if key != self._providers[0][0]:
                    logger.info("fallback: %s stream succeeded (primary was unavailable)", key)
                return
            except Exception as e:
                if _is_retriable(e) and not started:
                    breaker.record_failure(key)
                    last_err = e
                    logger.warning(
                        "fallback: %s stream failed before first chunk (%s), trying next provider",
                        key, e,
                    )
                else:
                    raise
        raise last_err or RuntimeError("all providers unavailable")
