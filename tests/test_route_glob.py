"""Literal glob routing and fresh default-skill installation regressions."""
import os
import subprocess
import sys
from pathlib import Path

import pytest

from ethan.core.routing import _match_keyword


@pytest.mark.parametrize("keyword,text,expected", [
    ("关*灯", "请关客厅灯", True),
    ("关*灯", "关灯", True),
    ("关*灯", "关客厅空调", False),
    ("记一下.*(是谁", "test", False),
    ("记一下.*(是谁", "记一下.张三(是谁", True),
    ("[abc]*", "abc", False),
    ("[abc]*", "prefix [abc] suffix", True),
    ("a+b*", "abbbbb", False),
    ("a+b*", "a+b suffix", True),
    ("a.b*", "axb", False),
    ("a.b*", "a.b suffix", True),
    ("file(1)*.md", "file(1)-draft.md", True),
    ("file(1)*.md", "file1-draftXmd", False),
    ("foo?*", "foooo", False),
    (r"path\*", "path\\file", True),
    ("literal[", "prefix literal[", True),
    ("a**b", "a middle b", True),
])
def test_keyword_only_star_is_wildcard(keyword, text, expected):
    assert _match_keyword(keyword, text) is expected


def test_fast_rule_uses_literal_glob():
    from ethan.core.config import FastRule, RoutingConfig
    from ethan.core.routing import _match_fast_rule

    rule = FastRule(keywords=["file(1)*.md"])
    routing = RoutingConfig(fast_rules=[rule])
    assert _match_fast_rule("file(1)-draft.md", routing) is rule
    assert _match_fast_rule("file1-draftXmd", routing) is None


@pytest.mark.parametrize("fast", [False, True])
def test_fresh_default_skills_route_and_system_prompt(tmp_path, fast):
    """Fresh process prevents config/path caches from touching production data."""
    root = Path(__file__).resolve().parents[1]
    data = tmp_path / "fresh-install"
    env = dict(os.environ, ETHAN_DATA_DIR=str(data), ETHAN_NO_WATCHDOG="1",
               PYTHONPATH=str(root), HF_HUB_OFFLINE="1")
    script = f'''
from types import SimpleNamespace
from unittest.mock import patch
from ethan.core.config import get_config
from ethan.core.context import ACTIVE_TOOLS
from ethan.core.agent_factory import create_agent
from ethan.core.routing import evaluate_route
from ethan.providers.base import Message
from ethan.skills.registry import SkillRegistry

get_config()
with patch.object(SkillRegistry, "_build_router", lambda self: None), \\
     patch("ethan.core.agent.create_provider", return_value=SimpleNamespace(model="offline-test")):
    agent = create_agent(channel="web")
people = agent._skills.get("people-kb")
assert people and "记一下.*(是谁" in people.trigger
assert people.source.is_relative_to({str(data)!r})
# Every shipped trigger is evaluated, including the previously invalid fragment.
for query in ("test", "debug", "这个人", "关客厅灯"):
    decision = evaluate_route(query, agent._skills, channel="web")
    assert decision.route in {{"fast", "full"}}
    token = ACTIVE_TOOLS.set(set())
    try:
        prompt = agent._build_system([Message(role="user", content=query)], fast={fast!r})
        assert "Current time:" in prompt
    finally:
        ACTIVE_TOOLS.reset(token)
print("fresh default skills and prompt passed")
'''
    result = subprocess.run([sys.executable, "-c", script], cwd=root, env=env,
                            capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "fresh default skills and prompt passed" in result.stdout
