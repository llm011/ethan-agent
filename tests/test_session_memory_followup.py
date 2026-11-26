"""Offline contract regression: snapshots do not disable later owner recall.

Real Agent route, tool executor, checkpoint lifecycle and temporary SQLite;
provider behavior is a deterministic stub, not natural model-quality evidence.
"""
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from ethan.providers.base import Message, StreamChunk, ToolCall
from scripts.probe_session_memory_ab import CASES, SYSTEM, FakeProvider, SyntheticRecall, rubric, synthetic_environment


@pytest.fixture
def anyio_backend():
    return 'asyncio'


@pytest.mark.anyio
@pytest.mark.parametrize('transport', ['chat', 'stream'])
async def test_persisted_first_snapshot_allows_new_topic_explicit_recall(transport):
    from ethan.core.agent import Agent
    from ethan.core.session_memory import MARKER

    first, later = CASES[0], CASES[1]

    class FollowupProvider(FakeProvider):
        def __init__(self):
            super().__init__(first)
            self.requests = 0
            self.snapshots = []

        async def chat(self, messages, tools=None, system=None, max_tokens=None):
            self.requests += 1
            assert tools and [tool.name for tool in tools] == ['recall_memory']
            assert SYSTEM in system
            snapshots = [message.content for message in messages if message.content.startswith(MARKER)]
            assert len(snapshots) == 1 and first.profile in snapshots[0]
            assert later.profile not in snapshots[0]
            self.snapshots.append(snapshots[0])
            new_topic = any(message.role == 'user' and message.content == later.question for message in messages)
            if not new_topic:
                return await super().chat(messages, tools, system, max_tokens)
            assert any(message.role == 'assistant' and rubric(first, message.content)['passed']
                       for message in messages)  # Real completed first-turn history was reloaded.
            results = [message for message in messages if message.role == 'tool']
            if not results:
                assert not any(later.profile in message.content for message in messages)
                return Message('assistant', '', tool_calls=[
                    ToolCall('new-topic-recall', 'recall_memory', {'query': '出行偏好'})])
            assert len(results) == 1 and results[0].tool_call_id == 'new-topic-recall'
            assert results[0].content == later.profile
            assert any(call.id == results[0].tool_call_id for message in messages for call in message.tool_calls)
            return Message('assistant', json.dumps({'facts': later.facts, 'plan': later.fake_plan}, ensure_ascii=False))

        async def stream_chat(self, messages, tools=None, system=None):
            answer = await self.chat(messages, tools, system, 768)
            yield StreamChunk(answer.content, tool_calls=answer.tool_calls, usage=answer.usage, is_final=True)

    inner = FollowupProvider()
    async with synthetic_environment(first, 'B', inner) as (agent, provider, original_tool, local_recall, store):
        # Restore actual owner routing/broadcast, excluding recall in base_tools:
        # only Agent's owner injection can make the registered tool visible.
        agent._channel = 'test'
        agent._select_route = Agent._select_route.__get__(agent)
        agent._broadcast_tools = Agent._broadcast_tools.__get__(agent)
        agent._build_system = lambda *args, **kwargs: SYSTEM
        routing = SimpleNamespace(base_tools=['unregistered'], fast_base_tools=[], fast_rules=[])
        config = SimpleNamespace(defaults=SimpleNamespace(routing=routing, max_tool_iterations=3))
        agent._checkpoint_callback = None  # Use actual automatic checkpoint persistence.

        async def turn(question):
            user = Message('user', question)
            await store.save_message(agent.session_id, user)
            history = (await store.load(agent.session_id)).messages
            if transport == 'chat':
                answer = await agent.chat(history)
            else:
                text = ''.join([event async for event in agent.stream_chat(history) if isinstance(event, str)])
                answer = Message('assistant', text)
            # Same public SessionStore final-save contract as native producers;
            # claim_final_message updates the real checkpoint placeholder.
            await store.save_message(agent.session_id, answer)
            return answer

        with patch('ethan.core.agent.get_config', return_value=config), \
                patch('ethan.core.routing.get_config', return_value=config), \
                patch('ethan.memory.session.get_session_store', AsyncMock(return_value=store)):
            answer = await turn(first.question)
            assert rubric(first, answer.content)['passed']
            assert original_tool.calls == 0 and local_recall.call_count == 1
            async with store._db.execute(
                'SELECT content, created_at FROM session_memory_snapshots WHERE session_id=?',
                (agent.session_id,),
            ) as cursor:
                original_snapshot = await cursor.fetchone()
            history = (await store.load(agent.session_id)).messages
            assert any(message.role == 'assistant' and message.status == 'completed'
                       and rubric(first, message.content)['passed'] for message in history)

            # Only the explicit tool's backing data changes; snapshot is never fed
            # new preferences, and the provider cannot know them before execution.
            new_tool = SyntheticRecall(later.profile)
            agent._registry.register(new_tool)
            answer = await turn(later.question)
            assert rubric(later, answer.content)['passed']
            assert json.loads(answer.content)['facts'] == later.facts
            assert new_tool.calls == 1 and original_tool.calls == 0
            assert local_recall.call_count == 1 and provider.calls == inner.requests == 3
            assert not provider.failure
            assert inner.snapshots == [original_snapshot[0]] * 3
            async with store._db.execute(
                'SELECT content, created_at FROM session_memory_snapshots WHERE session_id=?',
                (agent.session_id,),
            ) as cursor:
                assert await cursor.fetchall() == [original_snapshot]
            persisted = (await store.load(agent.session_id)).messages
            assert any(message.role == 'assistant' and message.status == 'completed'
                       and rubric(later, message.content)['passed'] for message in persisted)
