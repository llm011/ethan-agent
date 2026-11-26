"""Source-bound strict rubric regressions; never construct a live provider."""
import json

import pytest

from scripts.probe_session_memory_ab import (
    CASES,
    BoundedProvider,
    FakeProvider,
    output_diagnostics,
    rubric,
    rubric_diagnostics,
    run_probe,
)
from scripts.session_memory_rubric import DIAGNOSTIC_REASONS, RUBRIC_VERSION


def test_duplicate_root_plan_dangerous_last_wins_rejected():
    text = '{"facts":{"nuts":"禁止","lactose":"不耐受"},"plan":["杏仁"],"plan":["鸡蛋"]}'
    result = rubric(CASES[0], text)
    assert result['score'] == 0 and not result['passed']


def test_fractional_study_minutes_with_exact_total_rejected():
    case = CASES[2]
    plan = [{'subject': subject, 'minutes': minutes}
            for subject, minutes in zip(case.facts['subjects'], [6.5, 6.5, 7])]
    result = rubric(case, json.dumps({'facts': case.facts, 'plan': plan}))
    assert result['score'] == 1 and not result['plan_safe'] and not result['passed']


@pytest.fixture
def anyio_backend():
    return 'asyncio'


@pytest.mark.parametrize('case_index,text', [
    (0, '{"facts":{"nuts":"允许","nuts":"禁止","lactose":"不耐受"},"plan":["鸡蛋"]}'),
    (1, '{"facts":{"self_drive":false,"budget":200},"plan":[{"transport":"自驾","transport":"公交","cost":40}]}'),
    (2, '{"facts":{"time":"晚上","minutes":20,"subjects":["Python","英语","数学"]},"plan":[{"subject":"Python","minutes":0,"minutes":7},{"subject":"英语","minutes":7},{"subject":"数学","minutes":6}]}'),
    (0, '{"facts":{"nuts":"禁止","lactose":"不耐受"},"plan":["鸡蛋"],"extra":{"private":1,"private":2}}'),
])
def test_nested_duplicate_keys_fail_closed(case_index, text):
    result = rubric(CASES[case_index], text)
    assert result['reason'] == 'duplicate_json_key' and result['score'] == 0
    assert rubric_diagnostics(CASES[case_index], text) == {'reasons': ['duplicate_json_key']}
    assert not output_diagnostics(text, result)['json_parse_success']


@pytest.mark.parametrize('minutes', [[7.0, 7, 6], [True, 9, 10], [False, 10, 10], [0, 10, 10], [-1, 10, 11]])
def test_study_minutes_positive_integer_non_bool(minutes):
    case = CASES[2]
    plan = [{'subject': subject, 'minutes': value} for subject, value in zip(case.facts['subjects'], minutes)]
    text = json.dumps({'facts': case.facts, 'plan': plan})
    result = rubric(case, text)
    assert result['facts_exact'] and result['score'] == 1 and not result['plan_safe']


@pytest.mark.parametrize('index,key,value', [(1, 'budget', 200.0), (1, 'self_drive', 0),
                                           (2, 'minutes', 20.0), (2, 'minutes', True)])
def test_facts_remain_json_exact_not_python_equality(index, key, value):
    case = CASES[index]
    facts = {**case.facts, key: value}
    result = rubric(case, json.dumps({'facts': facts, 'plan': case.fake_plan}))
    assert not result['facts_exact'] and result['plan_safe'] and result['score'] == 1


def test_valid_integer_study_and_fractional_travel_costs_preserved():
    study, travel = CASES[2], CASES[1]
    assert rubric(study, json.dumps({'facts': study.facts, 'plan': study.fake_plan}))['score'] == 2
    assert rubric(travel, json.dumps({'facts': travel.facts,
                                    'plan': [{'transport': '公交', 'cost': 6.5}]}))['score'] == 2


@pytest.mark.parametrize('kind,expected', [
    ('shape', 'facts_shape'), ('keys', 'facts_keys'), ('type', 'facts_type'),
    ('value', 'facts_value'), ('schema', 'plan_schema'), ('vocabulary', 'plan_vocabulary'),
    ('duplicate', 'duplicate_json_key'),
])
def test_anonymous_diagnosis_private_canaries_indistinguishable(kind, expected):
    outputs = []
    for canary in ['arbitrary-private-key/value/id/path-A', 'different-private-key/value/id/path-B']:
        case = CASES[0]
        facts, plan = dict(case.facts), list(case.fake_plan)
        if kind == 'shape':
            facts = canary
        elif kind == 'keys':
            facts = {canary: canary}
        elif kind == 'type':
            facts['nuts'] = {canary: canary}
        elif kind == 'value':
            facts['nuts'] = canary
        elif kind == 'schema':
            plan = [{canary: canary}]
        elif kind == 'vocabulary':
            plan = [canary]
        text = json.dumps({'facts': facts, 'plan': plan})
        if kind == 'duplicate':
            text = '{"' + canary + '":"' + canary + '","' + canary + '":0}'
        diagnosis = rubric_diagnostics(case, text)
        assert diagnosis == {'reasons': [expected]}
        assert set(diagnosis['reasons']) <= DIAGNOSTIC_REASONS
        assert canary not in json.dumps(diagnosis)
        outputs.append(diagnosis)
    assert outputs[0] == outputs[1]


@pytest.mark.parametrize('plan,reason', [
    ([{'subject': 'Python', 'minutes': 20}], 'plan_count'),
    ([{'subject': subject, 'minutes': 10} for subject in ['Python', '英语', '数学']], 'plan_total'),
    ([{'subject': subject, 'minutes': value} for subject, value in zip(['Python', '英语', '数学'], [6.5, 6.5, 7])], 'plan_non_integer_minutes'),
])
def test_fixed_study_diagnostic_reasons(plan, reason):
    assert rubric_diagnostics(CASES[2], json.dumps({'facts': CASES[2].facts, 'plan': plan})) == {'reasons': [reason]}


@pytest.mark.anyio
@pytest.mark.parametrize('baseline_mode', ['controlled', 'natural'])
async def test_new_report_version_and_safe_per_call_metadata(baseline_mode):
    report = await run_probe(baseline_mode=baseline_mode)
    assert report['rubric_version'] == RUBRIC_VERSION == 'v2' and report['passed']
    for row in report['rows']:
        assert row['rubric_diagnostics'] == {'reasons': []}
        metrics = row['call_metrics']
        assert all(type(call['tools_available']) is bool and call['tools_available'] for call in metrics)
        assert [call['returned_tool_count'] for call in metrics] == ([1, 0] if row['arm'] == 'A' else [0])
        assert all(type(call['returned_tool_count']) is int for call in metrics)


@pytest.mark.anyio
@pytest.mark.parametrize('transport', ['chat', 'stream'])
@pytest.mark.parametrize('has_tools', [False, True])
async def test_provider_metadata_private_tool_fields_and_partial_errors(transport, has_tools):
    from ethan.providers.base import Message, StreamChunk, ToolCall
    canary = 'private-name-args-id-user-path-error'
    tool = ToolCall(canary, 'recall_memory', {canary: canary})

    class Partial(FakeProvider):
        async def chat(self, *args, **kwargs):
            return Message('assistant', canary, tool_calls=[tool], error=canary)

        async def stream_chat(self, *args, **kwargs):
            yield StreamChunk(canary, tool_calls=[tool])
            raise RuntimeError(canary)

    provider = BoundedProvider(Partial(CASES[0]))
    with pytest.raises(RuntimeError):
        if transport == 'chat':
            await provider.chat([], tools=[{canary: canary}] if has_tools else None)
        else:
            async for _ in provider.stream_chat([], tools=[{canary: canary}] if has_tools else None):
                pass
    record = provider.records[0]
    assert record['tools_available'] is has_tools
    assert record['returned_tool_count'] == 0  # Errors do not claim a complete response count.
    assert record['error_type'] == 'RuntimeError' and canary not in json.dumps(record)


@pytest.mark.anyio
@pytest.mark.parametrize('transport', ['chat', 'stream'])
@pytest.mark.parametrize('has_tools', [False, True])
async def test_successful_response_tool_count_and_request_flag(transport, has_tools):
    from ethan.providers.base import Message, StreamChunk, ToolCall
    calls = [ToolCall('private-id', 'recall_memory', {'private-key': 'private-value'})]

    class Returning(FakeProvider):
        async def chat(self, *args, **kwargs):
            return Message('assistant', '', tool_calls=calls)

        async def stream_chat(self, *args, **kwargs):
            yield StreamChunk('', tool_calls=calls)
            yield StreamChunk('', is_final=True)

    provider = BoundedProvider(Returning(CASES[0]))
    tools = [{}] if has_tools else []
    if transport == 'chat':
        await provider.chat([], tools=tools)
    else:
        async for _ in provider.stream_chat([], tools=tools):
            pass
    record = provider.records[0]
    assert record['tools_available'] is has_tools and record['returned_tool_count'] == 1
    assert record['error_type'] is None and 'private' not in json.dumps(record)


@pytest.mark.parametrize('text,reason', [('bad-private-text', 'invalid_json'), ('[]', 'invalid_schema')])
def test_anonymous_parse_reasons(text, reason):
    assert rubric_diagnostics(CASES[0], text) == {'reasons': [reason]}
