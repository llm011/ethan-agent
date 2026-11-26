"""Per-response cache presence before SDK coercion; no raw payload is retained.

Imported lazily with OpenAI client construction. Both JSON and SSE responses use
this SDK conversion seam; transport, validation, errors and retries stay native.
"""
from openai import AsyncOpenAI

from ethan.providers._responses import _valid_cache_count


class ObservedAsyncOpenAI(AsyncOpenAI):
    def _process_response_data(self, *, data, cast_to, response):
        result = super()._process_response_data(data=data, cast_to=cast_to, response=response)
        raw_usage = data.get("usage") if isinstance(data, dict) else None
        usage = getattr(result, "usage", None)
        if isinstance(raw_usage, dict) and usage is not None:
            details = raw_usage.get("prompt_tokens_details")
            cached = details.get("cached_tokens") if isinstance(details, dict) else None
            reported = (_valid_cache_count(cached)
                        or _valid_cache_count(raw_usage.get("prompt_cache_hit_tokens")))
            # Private observation on this response only, excluded from SDK JSON
            # and request history. Never copy raw response content or identifiers.
            try:
                object.__setattr__(usage, "_ethan_cache_reported", reported)
            except (AttributeError, TypeError):
                pass  # Unattachable SDK objects remain unknown, not zero-cache proof.
        return result
