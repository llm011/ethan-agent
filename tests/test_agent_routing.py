"""Tests for Agent._provider_for_route — verifies complex-skill override logic.

When route is "fast" and fast_use_lite_model is enabled:
- If last_matched_skills contains a complex skill (use-browser, agent-browser,
  computer-use), _provider_for_route should return the main provider (not lite).
- If last_matched_skills is empty or has no complex skills, it should return
  the lite provider.

When route is "medium" or "full", it always returns the main provider.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Helpers — build a minimally-mocked Agent with controllable providers
# ---------------------------------------------------------------------------

def _make_agent(last_matched_skills: list[str] | None = None):
    """Create a bare Agent-like object with only the fields _provider_for_route needs."""
    from ethan.core.agent import Agent

    # Patch heavy __init__ to avoid disk/network I/O
    with patch.object(Agent, "__init__", lambda self, *a, **kw: None):
        agent = Agent()

    # Wire up minimum state
    agent._provider = MagicMock(name="main_provider")
    agent._provider.model = "claude-main"

    agent._lite_provider = MagicMock(name="lite_provider")
    agent._lite_provider.model = "gemini-flash"

    agent.last_matched_skills = last_matched_skills or []
    agent._model = "claude-main"
    return agent


def _routing_config(fast_use_lite: bool = True):
    """Return a mock config whose defaults.routing.fast_use_lite_model == fast_use_lite."""
    cfg = MagicMock()
    cfg.defaults.routing.fast_use_lite_model = fast_use_lite
    return cfg


# ---------------------------------------------------------------------------
# Tests: fast route + complex skill → main provider
# ---------------------------------------------------------------------------

class TestProviderForRouteFastWithComplexSkills:
    """fast 路由 + 浏览器/桌面类 skill → 应返回主 provider"""

    @pytest.mark.parametrize("skill", ["use-browser", "agent-browser", "computer-use"])
    @patch("ethan.core.agent.get_config")
    def test_complex_skill_overrides_lite(self, mock_get_config, skill):
        mock_get_config.return_value = _routing_config(fast_use_lite=True)
        agent = _make_agent(last_matched_skills=[skill])

        result = agent._provider_for_route("fast")

        assert result is agent._provider, (
            f"Expected main provider when skill={skill!r}, got lite"
        )

    @patch("ethan.core.agent.get_config")
    def test_multiple_skills_with_one_complex(self, mock_get_config):
        mock_get_config.return_value = _routing_config(fast_use_lite=True)
        agent = _make_agent(last_matched_skills=["home-assistant-control", "use-browser"])

        result = agent._provider_for_route("fast")

        assert result is agent._provider


# ---------------------------------------------------------------------------
# Tests: fast route + no complex skill → lite provider
# ---------------------------------------------------------------------------

class TestProviderForRouteFastWithoutComplexSkills:
    """fast 路由 + 无复杂 skill → 应返回 lite provider"""

    @patch("ethan.core.agent.get_config")
    def test_empty_skills_returns_lite(self, mock_get_config):
        mock_get_config.return_value = _routing_config(fast_use_lite=True)
        agent = _make_agent(last_matched_skills=[])

        result = agent._provider_for_route("fast")

        assert result is agent._lite_provider

    @patch("ethan.core.agent.get_config")
    def test_non_complex_skill_returns_lite(self, mock_get_config):
        mock_get_config.return_value = _routing_config(fast_use_lite=True)
        agent = _make_agent(last_matched_skills=["home-assistant-control", "daily-report"])

        result = agent._provider_for_route("fast")

        assert result is agent._lite_provider


# ---------------------------------------------------------------------------
# Tests: medium/full route → always main provider
# ---------------------------------------------------------------------------

class TestProviderForRouteNonFast:
    """medium / full 路由 → 永远返回主 provider"""

    @pytest.mark.parametrize("route", ["medium", "full"])
    @patch("ethan.core.agent.get_config")
    def test_non_fast_returns_main(self, mock_get_config, route):
        mock_get_config.return_value = _routing_config(fast_use_lite=True)
        agent = _make_agent(last_matched_skills=[])

        result = agent._provider_for_route(route)

        assert result is agent._provider

    @pytest.mark.parametrize("route", ["medium", "full"])
    @patch("ethan.core.agent.get_config")
    def test_non_fast_with_complex_skill_still_returns_main(self, mock_get_config, route):
        mock_get_config.return_value = _routing_config(fast_use_lite=True)
        agent = _make_agent(last_matched_skills=["use-browser"])

        result = agent._provider_for_route(route)

        assert result is agent._provider


# ---------------------------------------------------------------------------
# Tests: fast_use_lite_model disabled → always main provider
# ---------------------------------------------------------------------------

class TestProviderForRouteLiteDisabled:
    """fast_use_lite_model=False → fast 路由也返回主 provider"""

    @patch("ethan.core.agent.get_config")
    def test_lite_disabled_returns_main(self, mock_get_config):
        mock_get_config.return_value = _routing_config(fast_use_lite=False)
        agent = _make_agent(last_matched_skills=[])

        result = agent._provider_for_route("fast")

        assert result is agent._provider
