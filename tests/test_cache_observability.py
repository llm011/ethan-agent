"""Offline cache field coverage: a zero is evidence only when actually reported."""
import asyncio
import math
from types import SimpleNamespace as NS

import pytest

from ethan.core.agent import UsageStats
from ethan.core.stream_collector import StreamCollector
from ethan.memory.session import SessionStore
from ethan.providers._responses import _valid_cache_count
from ethan.providers._responses import parse_usage as _parse_usage
from ethan.providers.base import Message


def parse_usage(usage):
    """Explicit raw annotations for pure fixtures; never trust SDK coerced types."""
    if not callable(getattr(usage, "model_dump", None)):
        details = getattr(usage, "prompt_tokens_details", None)
        usage._ethan_cache_reported = (_valid_cache_count(getattr(details, "cached_tokens", None))
                                       or _valid_cache_count(getattr(usage, "prompt_cache_hit_tokens", None)))
    return _parse_usage(usage)


@pytest.mark.parametrize("fields,cache,reported", [
    ({}, 0, False),
    ({"prompt_tokens_details": NS()}, 0, False),
    ({"prompt_tokens_details": NS(cached_tokens=None)}, 0, False),
    ({"prompt_tokens_details": NS(cached_tokens=0)}, 0, True),
    ({"prompt_tokens_details": NS(cached_tokens=12)}, 12, True),
    ({"prompt_cache_hit_tokens": 0}, 0, True),
    ({"prompt_cache_hit_tokens": 8}, 8, True),
    ({"prompt_cache_hit_tokens": None}, 0, False),
    ({"prompt_tokens_details": NS(cached_tokens=12), "prompt_cache_hit_tokens": 8}, 12, True),
    ({"prompt_tokens_details": NS(cached_tokens=8), "prompt_cache_hit_tokens": 12}, 12, True),
])
def test_standard_deepseek_missing_and_unchanged_max(fields, cache, reported):
    usage = parse_usage(NS(prompt_tokens=100, completion_tokens=4, **fields))
    assert usage == {"input": 100, "output": 4, "cache": cache,
                     "cache_usage": {"cache_reported": reported, "cache_presence_known": True}}


@pytest.mark.parametrize("invalid", [True, False, -1, "bad", math.nan, math.inf, -math.inf])
def test_invalid_standard_cache_is_not_reported_without_changing_old_value(invalid):
    usage = parse_usage(NS(prompt_tokens_details=NS(cached_tokens=invalid)))
    assert usage["cache_usage"] == {"cache_reported": False, "cache_presence_known": True}
    # Preserve the legacy value even when malformed; this is not billing cleanup.
    expected = invalid or 0
    assert usage["cache"] == expected or (isinstance(expected, float) and math.isnan(expected)
                                         and math.isnan(usage["cache"]))


@pytest.mark.parametrize("fields,reported", [
    ({}, False),
    ({"prompt_tokens_details": {"cached_tokens": 0}}, True),
    ({"prompt_tokens_details": {"cached_tokens": None}}, False),
    ({"prompt_cache_hit_tokens": 0}, True),
])
def test_openai_sdk_objects_preserve_field_presence(fields, reported):
    from openai.types.completion_usage import CompletionUsage
    usage = CompletionUsage(prompt_tokens=7, completion_tokens=2, total_tokens=9, **fields)
    # Even SDK direct construction lacks raw provenance, including apparent 0.
    assert parse_usage(usage)["cache_usage"] == {
        "cache_reported": False, "cache_presence_known": False}


def test_observation_does_not_change_next_request_messages():
    from ethan.providers._responses import parse_choice
    from ethan.providers._transform import to_openai_messages
    choice = NS(message=NS(content="fixture answer", tool_calls=None, reasoning_content=None))
    response = parse_choice(choice, NS(prompt_tokens=7))
    assert response.usage["cache_usage"] == {"cache_reported": False, "cache_presence_known": False}
    assert to_openai_messages([response], False, False) == [
        {"role": "assistant", "content": "fixture answer"}]


def test_mixed_coverage_is_fail_closed_and_counts_missing_usage():
    stats = UsageStats()
    stats.add(None)
    stats.add({"input": 3, "output": 1, "cache": 0})  # legacy: unknown, not reported
    stats.add(parse_usage(NS(prompt_tokens=7, prompt_cache_hit_tokens=0)))
    stats.add(parse_usage(NS(prompt_tokens=5)))
    result = stats.to_dict()
    assert result == {"input": 15, "output": 1, "cache": 0, "cache_usage": {
        "usage_samples": 4, "cache_reported_samples": 1, "cache_missing_samples": 1,
        "unknown_samples": 2, "usage_missing_samples": 1, "cache_reported": False}}
    assert StreamCollector().bind(NS(usage=stats)).usage_dict == result
    # Each snapshot is independent; readers cannot mutate the accumulator.
    result["cache_usage"]["usage_samples"] = 99
    assert stats.to_dict()["cache_usage"]["usage_samples"] == 4


def test_complete_zero_coverage_and_per_instance_isolation():
    stats = UsageStats()
    stats.add(parse_usage(NS(prompt_cache_hit_tokens=0)))
    stats.add(parse_usage(NS(prompt_tokens_details=NS(cached_tokens=0))))
    assert stats.to_dict()["cache_usage"]["cache_reported"] is True
    assert stats.to_dict()["cache_usage"]["cache_reported_samples"] == 2
    other = UsageStats()
    assert other.to_dict() == {"input": 0, "output": 0, "cache": 0}


def test_legacy_anthropic_and_fake_collector_contract_unchanged():
    stats = UsageStats()
    stats.add({"input": 10, "output": 2, "cache_read": 3, "cache_creation": 4})
    stats.add(None)
    expected = {"input": 10, "output": 2, "cache": 7}
    assert stats.to_dict() == expected
    assert StreamCollector().bind(NS(usage=stats)).usage_dict == expected
    fake = NS(input_tokens=10, output_tokens=2, cache_tokens=7)
    assert StreamCollector().bind(NS(usage=fake)).usage_dict == expected
    assert StreamCollector().usage_dict == {"input": 0, "output": 0, "cache": 0}


@pytest.mark.parametrize("streaming", [False, True])
@pytest.mark.parametrize("field", ["standard", "deepseek"])
@pytest.mark.parametrize("raw,reported", [(0, True), (7, True), (False, False),
                                         (True, False), ("0", False), (None, False), (-1, False)])
def test_actual_sdk_raw_conversion_json_and_sse(streaming, field, raw, reported):
    import json

    import httpx

    from ethan.providers._usage_observation import ObservedAsyncOpenAI

    usage = {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12}
    if field == "standard":
        usage["prompt_tokens_details"] = {"cached_tokens": raw}
    else:
        usage["prompt_cache_hit_tokens"] = raw
    payload = {"id": "fixture", "created": 1, "model": "fixture", "usage": usage,
               "object": "chat.completion.chunk" if streaming else "chat.completion",
               "choices": [] if streaming else [{"index": 0, "finish_reason": "stop",
                                                  "message": {"role": "assistant", "content": "fixture"}}]}
    requests = []
    def handle(request):
        requests.append(json.loads(request.content))
        if streaming:
            return httpx.Response(200, headers={"content-type": "text/event-stream"},
                                  content=f"data: {json.dumps(payload)}\n\ndata: [DONE]\n\n")
        return httpx.Response(200, json=payload)

    async def run():
        async with ObservedAsyncOpenAI(api_key="fixture", max_retries=0,
                                      http_client=httpx.AsyncClient(transport=httpx.MockTransport(handle))) as client:
            response = await client.chat.completions.create(model="fixture", messages=[], stream=streaming)
            if streaming:
                chunks = [chunk async for chunk in response]
                assert len(chunks) == 1
                response = chunks[0]
            assert response.usage._ethan_cache_reported is reported
            if field == "deepseek" and isinstance(raw, str):
                with pytest.raises(TypeError):
                    _parse_usage(response.usage)  # Legacy numeric comparison is unchanged.
                return
            parsed = _parse_usage(response.usage)
            assert parsed["cache_usage"] == {"cache_reported": reported, "cache_presence_known": True}
            assert "_ethan_cache_reported" not in response.usage.model_dump()
            stats = UsageStats()
            stats.add(parsed)
            assert stats.to_dict()["cache_usage"]["cache_reported"] is reported
            assert requests == [{"messages": [], "model": "fixture", "stream": streaming}]
    asyncio.run(run())


def test_raw_hook_response_and_client_isolation():
    import httpx
    from openai.types.chat.chat_completion import ChatCompletion

    from ethan.providers._usage_observation import ObservedAsyncOpenAI

    async def run():
        async with ObservedAsyncOpenAI(api_key="fixture") as first, ObservedAsyncOpenAI(api_key="fixture") as second:
            def convert(client, value):
                data = {"id": "fixture", "created": 1, "model": "fixture", "object": "chat.completion",
                        "choices": [], "usage": {"prompt_tokens": 7, "completion_tokens": 2,
                                                  "total_tokens": 9, "prompt_tokens_details": value}}
                return client._process_response_data(data=data, cast_to=ChatCompletion,
                                                     response=httpx.Response(200)).usage
            valid = convert(first, {"cached_tokens": 0})
            missing = convert(first, None)
            invalid_other = convert(second, {"cached_tokens": False})
            assert valid._ethan_cache_reported is True
            assert missing._ethan_cache_reported is False
            assert invalid_other._ethan_cache_reported is False
            assert valid._ethan_cache_reported is True
    asyncio.run(run())


def test_sdk_without_hook_is_unknown_not_missing():
    from openai.types.completion_usage import CompletionUsage
    stats = UsageStats()
    stats.add(_parse_usage(CompletionUsage(prompt_tokens=7, completion_tokens=2, total_tokens=9,
                                          prompt_tokens_details={"cached_tokens": 0})))
    coverage = stats.to_dict()["cache_usage"]
    assert coverage["cache_reported"] is False
    assert coverage["unknown_samples"] == 1
    assert coverage["cache_missing_samples"] == 0


def test_metadata_save_update_load_and_legacy_json(tmp_path):
    async def run():
        store = SessionStore(tmp_path / "cache-observability.db")
        await store.init()
        try:
            session = await store.create("fake")
            legacy = {"input": 7, "output": 2, "cache": 0}
            row = await store.save_message(session.id, Message("assistant", "fixture", usage=legacy))
            assert (await store.load(session.id)).messages[0].usage == legacy
            stats = UsageStats()
            stats.add(parse_usage(NS(prompt_tokens=7)))
            usage = StreamCollector().bind(NS(usage=stats)).usage_dict
            await store.update_message(row, session.id, Message("assistant", "fixture", usage=usage))
            assert (await store.load(session.id)).messages[0].usage == usage
            await store.save_message(session.id, Message("assistant", "fixture second", usage=usage))
            loaded = await store.load(session.id)
            assert [m.usage for m in loaded.messages] == [usage, usage]
            assert all(isinstance(v, (int, bool)) for v in usage["cache_usage"].values())
        finally:
            await store.close()
    asyncio.run(run())
