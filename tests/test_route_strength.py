from types import SimpleNamespace

import pytest

from ethan.core.config import RoutingConfig
from ethan.core.routing import evaluate_route


def skill(name='breakfast', *, triggers=('早餐',), fast=True, modes=(), channels=()):
    return SimpleNamespace(name=name, trigger=list(triggers), fast_path=fast,
                           modes=list(modes), channels=list(channels))


def registry(*items):
    return SimpleNamespace(all=lambda: list(items))


def test_strong_skill_trigger_preloads_name(monkeypatch):
    import ethan.core.routing as mod
    monkeypatch.setattr(mod, 'get_config', lambda: SimpleNamespace(
        defaults=SimpleNamespace(routing=RoutingConfig(fast_rules=[]))))
    decision = evaluate_route('推荐早餐', registry(skill()))
    assert decision.route == 'fast' and decision.strength == 'strong'
    assert decision.skill_names == ('breakfast',)
    assert decision.reason == 'skill_trigger'


def test_force_full_has_priority_but_keeps_strong_skill(monkeypatch):
    import ethan.core.routing as mod
    monkeypatch.setattr(mod, 'get_config', lambda: SimpleNamespace(
        defaults=SimpleNamespace(routing=RoutingConfig(fast_rules=[]))))
    decision = evaluate_route('分析早餐搭配', registry(skill()))
    assert decision.route == 'full' and decision.strength == 'strong'
    assert decision.skill_names == ('breakfast',)


def test_modes_channels_do_not_leak_strong_signal(monkeypatch):
    import ethan.core.routing as mod
    monkeypatch.setattr(mod, 'get_config', lambda: SimpleNamespace(
        defaults=SimpleNamespace(routing=RoutingConfig(fast_rules=[]))))
    decision = evaluate_route('早餐', registry(
        skill(channels=('lark',)), skill(name='private', modes=('companion',))),
        channel='web', mode='')
    assert decision.route == 'full' and decision.strength == 'weak'
    assert decision.skill_names == ()


def test_unknown_and_semantic_only_are_weak(monkeypatch):
    import ethan.core.routing as mod
    monkeypatch.setattr(mod, 'get_config', lambda: SimpleNamespace(
        defaults=SimpleNamespace(routing=RoutingConfig(fast_rules=[]))))
    decision = evaluate_route('随便说说', registry(skill()))
    assert decision.route == 'full' and decision.strength == 'weak'


def test_nonfast_skill_keeps_full(monkeypatch):
    import ethan.core.routing as mod
    monkeypatch.setattr(mod, 'get_config', lambda: SimpleNamespace(
        defaults=SimpleNamespace(routing=RoutingConfig(fast_rules=[]))))
    decision = evaluate_route('早餐', registry(skill(fast=False)))
    assert decision.route == 'full' and decision.strength == 'strong'


def test_fast_rule_is_medium_without_skill(monkeypatch):
    import ethan.core.routing as mod
    from ethan.core.config import FastRule
    monkeypatch.setattr(mod, 'get_config', lambda: SimpleNamespace(
        defaults=SimpleNamespace(routing=RoutingConfig(fast_rules=[
            FastRule(keywords=['天气'], skills=['weather'])]))))
    decision = evaluate_route('天气如何')
    assert decision.route == 'fast' and decision.strength == 'medium'
    assert decision.skill_names == ('weather',)


def test_wildcard_trigger_preserves_fast_route(monkeypatch):
    import ethan.core.routing as mod
    monkeypatch.setattr(mod, 'get_config', lambda: SimpleNamespace(
        defaults=SimpleNamespace(routing=RoutingConfig(fast_rules=[]))))
    decision = evaluate_route('关客厅灯', registry(skill(triggers=('关*灯',))))
    assert decision.route == 'fast'
    assert decision.skill_names == ('breakfast',)


@pytest.mark.parametrize('query,item,channel,mode,expected', [
    ('BREAKFAST', skill(triggers=('breakfast',)), 'web', '', 'strong'),
    ('早餐', skill(modes=('苏念',)), 'web', 'companion', 'strong'),
    ('早餐', skill(channels=('lark',)), 'web', '', 'weak'),
    ('早餐', skill(triggers=('',)), 'web', '', 'weak'),
])
def test_explicit_signals_normalize_and_filter(monkeypatch, query, item, channel, mode, expected):
    import ethan.core.routing as mod
    monkeypatch.setattr(mod, 'get_config', lambda: SimpleNamespace(
        defaults=SimpleNamespace(routing=RoutingConfig(fast_rules=[]))))
    assert evaluate_route(query, registry(item), channel=channel, mode=mode).strength == expected


def _bare_agent(monkeypatch, *, owner, fast=True, channel='web', modes=()):
    from ethan.core.agent import Agent
    from ethan.providers.base import Message

    cfg = SimpleNamespace(defaults=SimpleNamespace(
        routing=RoutingConfig(fast_rules=[], base_tools=['shell'], fast_base_tools=['shell']),
        max_tool_iterations=37, workspace='/tmp/route-strength-test'))
    for module in ('ethan.core.agent', 'ethan.core.routing', 'ethan.core.system_prompt'):
        monkeypatch.setattr(f'{module}.get_config', lambda: cfg)
    monkeypatch.setattr('ethan.core.system_prompt._ocr_available', lambda: False)
    monkeypatch.setattr('ethan.memory.signals.detect_memory_signal', lambda text: None)
    item = skill(fast=fast, modes=modes)
    item.category = 'discoverable'
    item.description = 'breakfast workflow'
    item.content = 'USE_BREAKFAST_WORKFLOW shell schedule_list recall_memory deliver_file'
    skills = registry(item)
    skills.get = lambda name: item if name == item.name else None
    # Deliberately absent from legacy matching, e.g. a wildcard trigger or context cap.
    skills.match = lambda *args, **kwargs: []
    skills.build_context = lambda *args, **kwargs: ''
    skills.build_index_block = lambda: ([], [])
    tools = [SimpleNamespace(name=name, fast_path=False) for name in (
        'shell', 'schedule_list', 'recall_memory', 'deliver_file')]
    tool_registry = SimpleNamespace(all=lambda: tools,
                                    get=lambda name: next((t for t in tools if t.name == name), None))
    agent = object.__new__(Agent)
    agent._skills = skills
    agent._registry = tool_registry
    agent._channel = channel
    agent._mode = ''
    agent.is_owner = owner
    agent._system_files = {}
    agent._provider = SimpleNamespace(model='offline-test')
    agent._procedures = SimpleNamespace(build_context=lambda: '')
    agent.runtime_context = ''
    agent.last_matched_skills = []
    return agent, [Message(role='user', content='早餐')]


@pytest.mark.parametrize('fast', [True, False])
@pytest.mark.parametrize('owner', [True, False])
def test_strong_skills_preload_context_and_tools_without_granting_owner_access(monkeypatch, fast, owner):
    from ethan.core.context import ACTIVE_TOOLS, get_active_tools

    token = ACTIVE_TOOLS.set(set())
    try:
        agent, messages = _bare_agent(monkeypatch, owner=owner, fast=fast)
        assert agent.route_for(messages) == ('fast' if fast else 'full')
        route, system, tools, budget = agent._select_route(messages)
        assert route == agent._route_decision.route
        assert agent._route_decision.strength == 'strong'
        assert budget == 37
        assert 'USE_BREAKFAST_WORKFLOW' in system
        assert agent.last_matched_skills == ['breakfast']
        assert 'schedule_list' in get_active_tools()
        private = {'recall_memory', 'deliver_file'}
        if owner:
            assert private <= get_active_tools()
            assert private <= {t.name for t in tools}
        else:
            assert not private & get_active_tools()
            assert not private & {t.name for t in tools}
    finally:
        ACTIVE_TOOLS.reset(token)


def test_force_full_keeps_strong_context_and_budget(monkeypatch):
    from ethan.core.context import ACTIVE_TOOLS, get_active_tools
    from ethan.providers.base import Message

    token = ACTIVE_TOOLS.set(set())
    try:
        agent, _ = _bare_agent(monkeypatch, owner=False)
        route, system, _, budget = agent._select_route([Message(role='user', content='分析早餐搭配')])
        assert route == 'full' and budget == 37
        assert agent._route_decision.reason == 'force_full'
        assert 'USE_BREAKFAST_WORKFLOW' in system
        assert 'schedule_list' in get_active_tools()
        assert not {'recall_memory', 'deliver_file'} & get_active_tools()
    finally:
        ACTIVE_TOOLS.reset(token)


def test_route_for_respects_mode_filter(monkeypatch):
    agent, messages = _bare_agent(monkeypatch, owner=False, modes=('companion',))
    assert agent.route_for(messages) == 'full'
    assert agent._route_decision.skill_names == ()


def test_minimal_never_activates_strong_skill_tools(monkeypatch):
    from ethan.core.context import ACTIVE_TOOLS, get_active_tools

    token = ACTIVE_TOOLS.set(set())
    try:
        agent, messages = _bare_agent(monkeypatch, owner=True)
        agent._mode = 'minimal'
        route, system, tools, budget = agent._select_route(messages)
        assert route == 'minimal' and budget == 37
        assert 'USE_BREAKFAST_WORKFLOW' not in system
        assert not get_active_tools()
        assert not {'recall_memory', 'deliver_file'} & {t.name for t in tools}
    finally:
        ACTIVE_TOOLS.reset(token)
