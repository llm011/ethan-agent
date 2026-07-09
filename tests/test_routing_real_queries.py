"""Tests for routing logic with real problematic user queries.

Verifies _get_route and _match_fast_rule produce correct route decisions
for queries that previously caused misrouting in production sessions.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from ethan.core.routing import _get_route, _match_fast_rule

# ---------------------------------------------------------------------------
# Fixtures — mock config to use default RoutingConfig (with smart-home fast_rules)
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _mock_config():
    """Provide default RoutingConfig so tests don't require a real config file."""
    from ethan.core.config import DefaultsConfig, RoutingConfig

    routing = RoutingConfig()  # includes default fast_rules (smart home) + medium_max_length=80
    defaults = DefaultsConfig(routing=routing)
    cfg = MagicMock()
    cfg.defaults = defaults
    with patch("ethan.core.routing.get_config", return_value=cfg):
        yield


# ---------------------------------------------------------------------------
# Skill triggers for use-browser (from real skill definition)
# ---------------------------------------------------------------------------

BROWSER_SKILL_TRIGGERS = [
    "浏览器", "打开网页", "网页操作", "自动填表", "网页截图",
    "点击页面", "输入文本", "操作我的浏览器", "我的浏览器",
    "本机 Chrome", "浏览器 cookie", "扩展工具", "真实 tab", "接管当前页面",
]


# ---------------------------------------------------------------------------
# Tests: browser skill trigger → fast route
# ---------------------------------------------------------------------------

class TestBrowserSkillTriggerRouting:
    """浏览器相关查询通过 skill_triggers 命中 → fast"""

    def test_browser_keyword_in_long_query(self):
        """'帮我用浏览器打开携程看下明天北京到上海的机票' 含 '浏览器' → fast"""
        query = "帮我用浏览器打开携程看下明天北京到上海的机票"
        route = _get_route(query, skill_triggers=BROWSER_SKILL_TRIGGERS)
        assert route == "fast", f"Expected 'fast' for browser query, got '{route}'"

    def test_open_webpage_trigger(self):
        """'打开网页 google.com 搜索一下' 含 '打开网页' → fast"""
        query = "打开网页 google.com 搜索一下"
        route = _get_route(query, skill_triggers=BROWSER_SKILL_TRIGGERS)
        assert route == "fast", f"Expected 'fast' for '打开网页' trigger, got '{route}'"

    def test_no_browser_trigger_short_query(self):
        """'查下明天北京到上海的机票' 无浏览器触发词，但命中'查*票' fast_rule → fast"""
        query = "查下明天北京到上海的机票"
        route = _get_route(query, skill_triggers=BROWSER_SKILL_TRIGGERS)
        assert route == "fast", f"Expected 'fast' for '查*票' fast_rule query, got '{route}'"


# ---------------------------------------------------------------------------
# Tests: FORCE_FULL_SIGNALS → full route (highest priority)
# ---------------------------------------------------------------------------

class TestForceFullSignals:
    """含强制 full 信号的查询 → full（即使有 skill trigger）"""

    def test_analyze_keyword(self):
        """'帮我分析下这个代码' 含 '分析' → full"""
        query = "帮我分析下这个代码"
        route = _get_route(query, skill_triggers=BROWSER_SKILL_TRIGGERS)
        assert route == "full", f"Expected 'full' for '分析' signal, got '{route}'"

    def test_force_full_overrides_skill_trigger(self):
        """即使含浏览器关键词，FORCE_FULL 信号仍然优先"""
        query = "帮我用浏览器分析这个网页的结构"
        route = _get_route(query, skill_triggers=BROWSER_SKILL_TRIGGERS)
        assert route == "full", f"FORCE_FULL should override skill trigger, got '{route}'"


# ---------------------------------------------------------------------------
# Tests: fast_rules (smart home) → fast route
# ---------------------------------------------------------------------------

class TestFastRulesSmartHome:
    """智能家居关键字命中 fast_rules → fast"""

    def test_turn_off_light(self):
        """'关客厅灯' 命中 '关*灯' → fast"""
        query = "关客厅灯"
        route = _get_route(query)
        assert route == "fast", f"Expected 'fast' for smart home command, got '{route}'"

    def test_match_fast_rule_returns_rule(self):
        """_match_fast_rule 对 '关客厅灯' 应返回智能家居规则"""
        query = "关客厅灯"
        rule = _match_fast_rule(query)
        assert rule is not None, "Expected a FastRule match for '关客厅灯'"
        assert rule.name == "智能家居控制"

    def test_turn_on_ac(self):
        """'开空调' 命中 '开*空调' → fast"""
        query = "开空调"
        route = _get_route(query)
        assert route == "fast"

    def test_adjust_brightness(self):
        """'调低亮度' 命中 '调*亮度' → fast"""
        query = "调低亮度"
        route = _get_route(query)
        assert route == "fast"


# ---------------------------------------------------------------------------
# Tests: short text, no triggers → medium
# ---------------------------------------------------------------------------

class TestMediumRoute:
    """短文本无任何触发词 → medium"""

    def test_weather_query(self):
        """'今天天气怎么样' 命中'天气怎么样' fast_rule → fast"""
        query = "今天天气怎么样"
        route = _get_route(query)
        assert route == "fast", f"Expected 'fast' for weather fast_rule query, got '{route}'"

    def test_short_general_query(self):
        """一般短问题走 medium"""
        query = "现在几点了"
        route = _get_route(query)
        assert route == "medium"


# ---------------------------------------------------------------------------
# Tests: skill trigger extraction logic (simulate agent behavior)
# ---------------------------------------------------------------------------

class TestSkillTriggerExtraction:
    """模拟 Agent._select_route 中 skill trigger 提取逻辑"""

    @pytest.mark.parametrize("query,expected_route", [
        ("帮我用浏览器打开百度", "fast"),         # '浏览器' trigger
        ("操作我的浏览器登录一下", "fast"),        # '操作我的浏览器' trigger
        ("网页截图保存到桌面", "fast"),            # '网页截图' trigger
        ("帮我在本机 Chrome 打开设置", "fast"),   # '本机 Chrome' trigger
        ("接管当前页面帮我填个表", "fast"),        # '接管当前页面' trigger
        ("查一下今天的新闻", "medium"),            # 无触发词，短文本
    ])
    def test_various_browser_triggers(self, query, expected_route):
        """各种浏览器 skill trigger 关键词均应命中 fast"""
        route = _get_route(query, skill_triggers=BROWSER_SKILL_TRIGGERS)
        assert route == expected_route, (
            f"Query={query!r}: expected '{expected_route}', got '{route}'"
        )

    def test_no_skill_triggers_passed(self):
        """skill_triggers=None 时，浏览器关键词不触发 fast"""
        query = "帮我用浏览器打开携程"
        route = _get_route(query, skill_triggers=None)
        # 无 skill_triggers、无 fast_rule 命中，长度 < 80 → medium
        assert route == "medium"

    def test_empty_skill_triggers(self):
        """skill_triggers=[] 时同 None"""
        query = "打开网页 google.com"
        route = _get_route(query, skill_triggers=[])
        assert route == "medium"
