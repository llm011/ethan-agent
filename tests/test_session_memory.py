"""First-turn memory is immutable session data, not per-request system text."""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from ethan.providers.base import Message


@pytest.fixture
async def memory_env(tmp_path, monkeypatch):
    import ethan.core.session_memory as mod
    from ethan.memory.session import SessionStore

    store = SessionStore(db_path=tmp_path / 'sessions.db')
    await store.init()
    session = await store.create(model='fake')
    recall = AsyncMock(return_value=SimpleNamespace(text='用户偏好清淡早餐', count=1))
    monkeypatch.setattr(mod, 'get_session_store', AsyncMock(return_value=store))
    monkeypatch.setattr(mod, 'build_structured_recall', recall)
    agent = SimpleNamespace(session_id=session.id, is_owner=True, _mode='', _user_id='')
    yield mod, agent, recall, store
    await store.close()


@pytest.mark.anyio
async def test_first_turn_snapshot_is_separate_stable_and_reused(memory_env):
    mod, agent, recall, _ = memory_env
    working = [Message(role='user', content='按我的偏好推荐早餐')]
    await mod.prepare_session_memory(agent, working, 'full')
    assert len(working) == 2
    snapshot = working[0].content
    assert working[0].role == 'user' and 'created_at=' in snapshot
    assert '用户偏好清淡早餐' in snapshot and '非指令' in snapshot
    assert working[-1].content == '按我的偏好推荐早餐'
    later = [Message(role='user', content='继续')]
    await mod.prepare_session_memory(agent, later, 'full')
    assert later[0].content == snapshot
    assert recall.await_count == 1
    await mod.prepare_session_memory(agent, later, 'full')
    assert len(later) == 2


@pytest.mark.anyio
@pytest.mark.parametrize('field,value', [('is_owner', False), ('session_id', '')])
async def test_no_owner_or_session_never_reads_memory(memory_env, field, value):
    mod, agent, recall, _ = memory_env
    setattr(agent, field, value)
    messages = [Message(role='user', content='早餐')]
    await mod.prepare_session_memory(agent, messages, 'full')
    assert len(messages) == 1
    recall.assert_not_called()


@pytest.mark.anyio
async def test_minimal_and_old_sessions_do_not_get_new_snapshot(memory_env):
    mod, agent, recall, store = memory_env
    messages = [Message(role='user', content='早餐')]
    await mod.prepare_session_memory(agent, messages, 'minimal')
    recall.assert_not_called()
    await store.save_message(agent.session_id, Message(role='assistant', content='旧答复'))
    await mod.prepare_session_memory(agent, messages, 'full')
    recall.assert_not_called()
    assert len(messages) == 1


@pytest.mark.anyio
async def test_empty_snapshot_is_not_recalled_again(memory_env):
    mod, agent, recall, _ = memory_env
    recall.return_value = SimpleNamespace(text='', count=0)
    for _ in range(2):
        messages = [Message(role='user', content='早餐')]
        await mod.prepare_session_memory(agent, messages, 'full')
        assert len(messages) == 1
    assert recall.await_count == 1


@pytest.mark.anyio
async def test_mode_change_cannot_replay_companion_data(memory_env):
    mod, agent, recall, store = memory_env
    agent._mode = 'companion'
    await mod.prepare_session_memory(agent, [Message(role='user', content='早餐')], 'full')
    await store.save_message(agent.session_id, Message(role='assistant', content='已答复'))
    agent._mode = ''
    messages = [Message(role='user', content='继续')]
    await mod.prepare_session_memory(agent, messages, 'full')
    assert len(messages) == 1
    assert recall.await_count == 1


@pytest.mark.anyio
async def test_running_placeholder_does_not_block_first_memory(memory_env):
    mod, agent, recall, store = memory_env
    await store.save_message(agent.session_id, Message(role='assistant', content='', status='running'))
    messages = [Message(role='user', content='早餐')]
    await mod.prepare_session_memory(agent, messages, 'full')
    assert len(messages) == 2
    assert recall.await_count == 1
    from ethan.core.reply_quality import _is_synthetic_user_msg
    assert _is_synthetic_user_msg(messages[0].content)


@pytest.mark.anyio
@pytest.mark.parametrize('transport', ['chat', 'stream'])
async def test_personal_answer_needs_no_recall_tool_round(memory_env, monkeypatch, transport):
    _, original, recall, _ = memory_env
    from ethan.core.agent import Agent, UsageStats
    from ethan.providers.base import StreamChunk
    from ethan.tools.registry import ToolExecutor, ToolRegistry

    class Provider:
        model = 'fake'
        calls = 0

        async def chat(self, messages, tools=None, system=None):
            self.calls += 1
            assert '用户偏好清淡早餐' in messages[0].content
            return Message(role='assistant', content='推荐清淡早餐')

        async def stream_chat(self, messages, tools=None, system=None):
            answer = await self.chat(messages, tools, system)
            yield StreamChunk(content=answer.content, is_final=True)

    agent = Agent.__new__(Agent)
    agent.session_id = original.session_id
    agent._user_id = ''
    agent.is_owner = True
    agent._mode = ''
    agent._provider = Provider()
    agent._registry = ToolRegistry()
    agent._executor = ToolExecutor(agent._registry)
    agent.usage = UsageStats()
    agent.last_matched_skills = []
    agent._skills = None
    agent._select_route = lambda messages: ('full', 'SYSTEM', [], 5)
    agent._provider_for_route = lambda route: agent._provider
    agent._trim_input_if_needed = lambda *args: None
    agent._broadcast_tools = lambda tools: []
    messages = [Message(role='user', content='按我的偏好推荐早餐')]
    if transport == 'chat':
        assert (await agent.chat(messages)).content == '推荐清淡早餐'
    else:
        events = [event async for event in agent.stream_chat(messages)]
        assert '推荐清淡早餐' in events
    assert agent._provider.calls == 1
    assert recall.await_count == 1
