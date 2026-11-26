"""Offline-only tests: no configured provider construction, no paid calls."""
import json
from unittest.mock import AsyncMock, patch

import pytest

from scripts.probe_session_memory_ab import (
    CASES,
    MAX_CALLS,
    BoundedProvider,
    FakeProvider,
    output_diagnostics,
    rubric,
    run_case,
    run_probe,
    synthetic_environment,
)


@pytest.fixture
def anyio_backend():
    return 'asyncio'


@pytest.mark.anyio
@pytest.mark.parametrize('transport', ['chat', 'stream'])
@pytest.mark.parametrize('case', CASES, ids=lambda case: case.name)
async def test_six_ab_cases_real_agent_tool_pairing_and_counts(case, transport):
    for arm in ('A', 'B'):
        inner = FakeProvider(case, force_recall=arm == 'A')
        async with synthetic_environment(case, arm, inner) as (agent, provider, tool, recall, store):
            from ethan.providers.base import Message
            messages = [Message('user', case.question)]
            if transport == 'chat':
                answer = (await agent.chat(messages)).content
            else:
                answer = ''.join([event async for event in agent.stream_chat(messages) if isinstance(event, str)])
            assert rubric(case, answer)['passed']
            assert provider.calls == (2 if arm == 'A' else 1)
            assert tool.calls == (1 if arm == 'A' else 0)
            assert recall.call_count == (0 if arm == 'A' else 1)
            assert not provider.failure
            assert len(agent._registry.all()) == 1
            assert agent._registry.all()[0].side_effect is False
            wire = agent._wire_transcript
            calls = [call.id for message in wire for call in message.tool_calls]
            results = [message.tool_call_id for message in wire if message.role == 'tool']
            assert calls == results == (['synthetic-recall-1'] if arm == 'A' else [])
            assert sum(row['usage'].get('input', 0) for row in provider.records) == (30 if arm == 'A' else 20)
            assert all(row['latency_ms'] >= 0 for row in provider.records)
            async with store._db.execute('SELECT count(*) FROM messages') as cursor:
                assert (await cursor.fetchone())[0] == 0  # No transcript/reasoning logging.


@pytest.mark.anyio
async def test_actual_snapshot_persists_and_reuses_after_store_reopen():
    from ethan.core.session_memory import MARKER, prepare_session_memory
    from ethan.memory.session import SessionStore
    from ethan.providers.base import Message

    case = CASES[0]
    async with synthetic_environment(case, 'B', FakeProvider(case)) as (agent, _, _, recall, store):
        first = [Message('user', case.question)]
        await prepare_session_memory(agent, first, 'full')
        assert first[0].content.startswith(MARKER)
        await store.close()
        await store.init()
        reopened = SessionStore(db_path=store._db_path)
        await reopened.init()
        try:
            with patch('ethan.core.session_memory.get_session_store', AsyncMock(return_value=reopened)):
                second = [Message('user', '继续')]
                await prepare_session_memory(agent, second, 'full')
            assert second[0].content == first[0].content
            assert recall.call_count == 1
            async with reopened._db.execute('SELECT content FROM session_memory_snapshots') as cursor:
                assert (await cursor.fetchone())[0] == first[0].content
        finally:
            await reopened.close()


@pytest.mark.anyio
async def test_default_dry_never_constructs_live_provider():
    with patch('scripts.probe_session_memory_ab.configured_live_provider', side_effect=AssertionError('paid call forbidden')):
        report = await run_probe()
    assert report['mode'] == 'dry_fake' and report['passed']
    assert len(report['rows']) == 12 and len(report['pairs']) == 6
    assert all(pair['call_delta_B_minus_A'] == -1 for pair in report['pairs'])
    assert all(row['snapshots_persisted'] == (row['arm'] == 'B') for row in report['rows'])
    assert all('reasoning' not in json.dumps(row) and 'messages' not in json.dumps(row) for row in report['rows'])


@pytest.mark.parametrize('prefix,starts_think,contains_tag,starts_fence', [
    ('<think>secret-reasoning</think>', True, True, False),
    ('  <THINK>secret-reasoning</THINK>', True, True, False),
    ('```json\n', False, False, True),
    ('secret-reasoning</think>', False, True, False),
])
def test_anonymous_format_diagnostics_do_not_strip_or_leak_content(prefix, starts_think, contains_tag, starts_fence):
    case = CASES[0]
    text = prefix + json.dumps({'facts': case.facts, 'plan': case.fake_plan})
    result = rubric(case, text)
    diagnostic = output_diagnostics(text, result)
    assert diagnostic == {'starts_think': starts_think, 'contains_think_tag': contains_tag,
                          'starts_codefence': starts_fence, 'json_parse_success': False,
                          'content_chars': len(text), 'facts_exact': False, 'plan_safe': False}
    assert not result['passed'] and result['reason'] == 'invalid_json'
    assert 'secret-reasoning' not in json.dumps(diagnostic)
    assert all(type(value) in (bool, int) for value in diagnostic.values())


def test_valid_json_format_diagnostics_preserve_exact_rubric():
    case = CASES[0]
    text = json.dumps({'facts': case.facts, 'plan': ['牛奶']})
    diagnostic = output_diagnostics(text, rubric(case, text))
    assert diagnostic['json_parse_success'] and diagnostic['facts_exact'] and not diagnostic['plan_safe']
    assert not diagnostic['starts_think'] and not diagnostic['contains_think_tag']
    assert not diagnostic['starts_codefence'] and diagnostic['content_chars'] == len(text)


@pytest.mark.anyio
async def test_run_case_exposes_only_anonymous_format_diagnostics():
    from ethan.providers.base import Message

    class ThinkPolluted(FakeProvider):
        async def chat(self, *args, **kwargs):
            return Message('assistant', '<think>secret-reasoning</think>{"facts":{}}')
    row = await run_case(CASES[0], 'B', ThinkPolluted(CASES[0]))
    assert not row['passed'] and row['score'] == 0 and row['reason'] == 'invalid_json'
    assert row['output_diagnostics']['starts_think'] and not row['output_diagnostics']['json_parse_success']
    assert 'secret-reasoning' not in json.dumps(row)


@pytest.mark.parametrize('case', CASES, ids=lambda case: case.name)
def test_rubric_exact_facts_and_constraint_veto(case):
    valid = {'facts': case.facts, 'plan': case.fake_plan}
    assert rubric(case, json.dumps(valid))['score'] == 2
    assert not rubric(case, 'not json')['passed']
    wrong = {'facts': {}, 'plan': case.fake_plan}
    assert not rubric(case, json.dumps(wrong))['passed']
    violations = {
        'breakfast': ['杏仁', '牛奶'],
        'travel': [{'transport': '自驾', 'cost': 50}],
        'study': [{'subject': 'Python', 'minutes': 20}],
    }
    bad = rubric(case, json.dumps({'facts': case.facts, 'plan': violations[case.name]}))
    assert bad['facts_exact'] and not bad['plan_safe'] and not bad['passed']


@pytest.mark.parametrize('plan', [
    [{'transport': '公交', 'cost': 201}],
    [{'transport': '公交', 'cost': True}],
    [{'transport': '公交', 'cost': -1}],
    [{'transport': '公交', 'cost': float('nan')}],
])
def test_travel_budget_rubric_is_fail_closed(plan):
    assert not rubric(CASES[1], json.dumps({'facts': CASES[1].facts, 'plan': plan}))['passed']


def test_study_must_have_three_distinct_subjects_and_exact_minutes():
    case = CASES[2]
    for plan in [case.fake_plan[:2], [case.fake_plan[0]] * 3,
                 [{'subject': item['subject'], 'minutes': 10} for item in case.fake_plan]]:
        assert not rubric(case, json.dumps({'facts': case.facts, 'plan': plan}))['passed']


@pytest.mark.anyio
async def test_upstream_error_is_not_passed_or_logged():
    class Failing(FakeProvider):
        async def chat(self, *args, **kwargs):
            raise RuntimeError('secret-value upstream body must not be logged')
    row = await run_case(CASES[0], 'B', Failing(CASES[0]))
    assert row['calls'] == 1 and not row['passed'] and row['score'] == 0
    assert row['error_type'] == 'RuntimeError'
    assert 'secret-value' not in json.dumps(row)


@pytest.mark.anyio
async def test_timeout_cancels_provider_and_fails_closed():
    import asyncio
    cancelled = False
    class Slow(FakeProvider):
        async def chat(self, *args, **kwargs):
            nonlocal cancelled
            try:
                await asyncio.Event().wait()
            finally:
                cancelled = True
    row = await run_case(CASES[0], 'B', Slow(CASES[0]), timeout=0.01)
    assert cancelled and not row['passed'] and row['score'] == 0
    assert row['calls'] <= MAX_CALLS and row['error_type'] == 'TimeoutError'


@pytest.mark.anyio
async def test_call_limit_is_hard_even_when_agent_retries():
    from ethan.providers.base import Message, ToolCall
    class Repeating(FakeProvider):
        async def chat(self, *args, **kwargs):
            return Message('assistant', '', tool_calls=[ToolCall(str(id(args)), 'recall_memory', {'query': '偏好'})])
    row = await run_case(CASES[0], 'A', Repeating(CASES[0]))
    assert row['calls'] == MAX_CALLS and not row['passed'] and row['score'] == 0


@pytest.mark.parametrize('provider_type', ['openai_compat', 'openai_compact', 'openai', '', None])
def test_configured_provider_uses_manager_compat_aliases_without_paid_calls(provider_type):
    from types import SimpleNamespace

    from scripts.probe_session_memory_ab import configured_live_provider

    entry = SimpleNamespace(provider='buddy-proxy', id='deepseek-v4.1-flash', vision=None)
    provider_config = SimpleNamespace(type=provider_type, proxy=None)
    config = SimpleNamespace(defaults=SimpleNamespace(model='buddy-proxy/deepseek-v4.1-flash'),
                             network=SimpleNamespace(proxy=None), get_model=lambda model: entry,
                             get_provider_config=lambda key: provider_config)
    sentinel = object()
    with patch('ethan.core.config.get_config', return_value=config), \
            patch('ethan.providers.manager._build_single_provider', return_value=sentinel) as build:
        assert configured_live_provider() is sentinel
    build.assert_called_once_with('buddy-proxy', 'deepseek-v4.1-flash', provider_config, None, vision=None)
    assert provider_config.type == provider_type  # Alias acceptance must not rewrite configuration.


@pytest.mark.parametrize('key,provider_type', [('buddy-proxy', 'anthropic'), ('anthropic', None)])
def test_configured_anthropic_transport_refused_before_construction(key, provider_type):
    from types import SimpleNamespace

    from scripts.probe_session_memory_ab import configured_live_provider

    config = SimpleNamespace(defaults=SimpleNamespace(model='configured'),
                             get_model=lambda model: SimpleNamespace(provider=key, id='model'),
                             get_provider_config=lambda key: SimpleNamespace(type=provider_type))
    with patch('ethan.core.config.get_config', return_value=config), \
            patch('ethan.providers.manager._build_single_provider', side_effect=AssertionError('must not construct')):
        with pytest.raises(ValueError, match='OpenAI-compatible'):
            configured_live_provider()


@pytest.mark.anyio
async def test_live_request_seam_is_bounded_and_closed_without_paid_calls():
    from types import SimpleNamespace
    from unittest.mock import Mock

    instances = []

    def create():
        index = len(instances)
        case, arm = CASES[index // 2], 'A' if index % 2 == 0 else 'B'

        class LocalSDK(FakeProvider):
            def __init__(self):
                super().__init__(case, force_recall=arm == 'A')
                self.requests = []
                self._client = SimpleNamespace(
                    chat=SimpleNamespace(completions=SimpleNamespace(create=self.sdk_create)), close=AsyncMock())
                self._create_with_retry = AsyncMock(side_effect=AssertionError('hidden retry path'))

            async def sdk_create(self, **kwargs):
                self.requests.append({key: value for key, value in kwargs.items() if key != 'messages'})
                return await super().chat(kwargs['messages'], kwargs['tools'], kwargs['system'], kwargs['max_tokens'])

            async def chat(self, messages, tools=None, system=None, max_tokens=None):
                return await self._create_with_retry({'messages': messages, 'tools': tools,
                                                       'system': system, 'max_tokens': max_tokens})

        inner = LocalSDK()
        instances.append(inner)
        return inner

    with patch('scripts.probe_session_memory_ab.configured_live_provider', Mock(side_effect=create)):
        report = await run_probe(live=True)
    assert report['passed'] and len(report['rows']) == 6
    for index, inner in enumerate(instances):
        inner._client.close.assert_awaited_once()
        assert len(inner.requests) == (2 if index % 2 == 0 else 1)
        assert all(request['max_tokens'] == 768 and 'temperature' not in request for request in inner.requests)
        assert inner.requests[0].get('tool_choice') == (
            {'type': 'function', 'function': {'name': 'recall_memory'}} if index % 2 == 0 else None)
        if index % 2 == 0:
            assert 'tool_choice' not in inner.requests[1]


@pytest.mark.anyio
async def test_live_stream_refused_before_provider_creation():
    with patch('scripts.probe_session_memory_ab.configured_live_provider', side_effect=AssertionError('paid call forbidden')):
        with pytest.raises(ValueError, match='live stream'):
            await run_probe(live=True, transport='stream')


@pytest.mark.anyio
async def test_error_status_and_unknown_tool_fail_closed():
    from ethan.providers.base import Message, ToolCall
    for answer in [Message('assistant', 'ok', status='interrupted'),
                   Message('assistant', 'ok', error='upstream failed'),
                   Message('assistant', '', tool_calls=[ToolCall('x', 'shell', {})])]:
        class Invalid(FakeProvider):
            async def chat(self, *args, **kwargs):
                return answer
        bounded = BoundedProvider(Invalid(CASES[0]))
        with pytest.raises(RuntimeError):
            await bounded.chat([])
        assert bounded.failure and bounded.calls == 1
