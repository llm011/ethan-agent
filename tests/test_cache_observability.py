"""Offline cache field coverage: a zero is evidence only when actually reported."""
import asyncio
import math
from types import SimpleNamespace as NS

import pytest

from ethan.core.agent import UsageStats
from ethan.core.stream_collector import StreamCollector
from ethan.memory.session import SessionStore
from ethan.providers._responses import parse_usage
from ethan.providers.base import Message


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
                     "cache_usage": {"cache_reported": reported}}


@pytest.mark.parametrize("invalid", [True, False, -1, "bad", math.nan, math.inf, -math.inf])
def test_invalid_standard_cache_is_not_reported_without_changing_old_value(invalid):
    usage = parse_usage(NS(prompt_tokens_details=NS(cached_tokens=invalid)))
    assert usage["cache_usage"] == {"cache_reported": False}
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
    assert parse_usage(usage)["cache_usage"]["cache_reported"] is reported


def test_observation_does_not_change_next_request_messages():
    from ethan.providers._responses import parse_choice
    from ethan.providers._transform import to_openai_messages
    choice = NS(message=NS(content="fixture answer", tool_calls=None, reasoning_content=None))
    response = parse_choice(choice, NS(prompt_tokens=7))
    assert response.usage["cache_usage"] == {"cache_reported": False}
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
