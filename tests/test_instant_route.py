"""Tests for the instant route (zero-tool short-circuit) logic.

Verifies classify_instant correctly identifies:
- Math expressions → eval result
- Time queries → system time
- Greetings/confirmations → greeting kind
- Short trivial text → direct kind
- And correctly REJECTS complex queries that need tools/full loop.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from ethan.core.routing import _safe_math_eval, classify_instant

# ---------------------------------------------------------------------------
# Fixture — mock config to avoid needing a real config file
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _mock_config():
    """Provide default RoutingConfig so fast_rule checks work without config file."""
    from ethan.core.config import DefaultsConfig, RoutingConfig

    routing = RoutingConfig()
    defaults = DefaultsConfig(routing=routing)
    cfg = MagicMock()
    cfg.defaults = defaults
    with patch("ethan.core.routing.get_config", return_value=cfg):
        yield


# ---------------------------------------------------------------------------
# 1. Math expressions — should eval directly
# ---------------------------------------------------------------------------

class TestMathInstant:
    def test_simple_subtraction(self):
        """用户原始 case: 9.11-9.8"""
        r = classify_instant("9.11-9.8")
        assert r is not None
        assert r.kind == "math"
        # 9.11 - 9.8 = -0.69（9.11 < 9.80）
        assert float(r.answer) == pytest.approx(-0.69, abs=1e-9)

    def test_addition(self):
        r = classify_instant("1+1")
        assert r is not None
        assert r.kind == "math"
        assert r.answer == "2"

    def test_multiplication(self):
        r = classify_instant("7 * 8")
        assert r is not None
        assert r.kind == "math"
        assert r.answer == "56"

    def test_division(self):
        r = classify_instant("100/7")
        assert r is not None
        assert r.kind == "math"
        assert float(r.answer) == pytest.approx(100 / 7, rel=1e-6)

    def test_power(self):
        """^ should be treated as exponent."""
        r = classify_instant("2^10")
        assert r is not None
        assert r.kind == "math"
        assert r.answer == "1024"

    def test_parentheses(self):
        r = classify_instant("(3+4)*2")
        assert r is not None
        assert r.kind == "math"
        assert r.answer == "14"

    def test_complex_expression(self):
        r = classify_instant("3.14 * 2 * 2")
        assert r is not None
        assert r.kind == "math"
        assert float(r.answer) == pytest.approx(12.56, abs=1e-6)

    def test_modulo(self):
        r = classify_instant("17%5")
        assert r is not None
        assert r.kind == "math"
        assert r.answer == "2"

    def test_negative_number(self):
        r = classify_instant("-5+3")
        assert r is not None
        assert r.kind == "math"
        assert r.answer == "-2"


# ---------------------------------------------------------------------------
# 2. Math safety — reject dangerous input
# ---------------------------------------------------------------------------

class TestMathSafety:
    def test_reject_function_call(self):
        """不能执行函数调用"""
        assert _safe_math_eval("__import__('os').system('ls')") is None

    def test_reject_variable_names(self):
        """不能包含变量名（正则阶段就过滤了）"""
        r = classify_instant("x + 1")
        # 含字母 → 正则不匹配 → 不会走 math
        assert r is None or r.kind != "math"

    def test_reject_division_by_zero(self):
        assert _safe_math_eval("1/0") is None


# ---------------------------------------------------------------------------
# 3. Time queries
# ---------------------------------------------------------------------------

class TestTimeInstant:
    def test_what_time_cn(self):
        r = classify_instant("现在几点")
        assert r is not None
        assert r.kind == "time"
        assert len(r.answer) > 0  # 有时间字符串

    def test_today_date(self):
        r = classify_instant("今天几号")
        assert r is not None
        assert r.kind == "time"

    def test_what_day(self):
        r = classify_instant("今天星期几")
        assert r is not None
        assert r.kind == "time"


# ---------------------------------------------------------------------------
# 4. Greetings / confirmations — LLM bare answer
# ---------------------------------------------------------------------------

class TestGreetingInstant:
    def test_hello_cn(self):
        r = classify_instant("你好")
        assert r is not None
        assert r.kind == "greeting"

    def test_hello_en(self):
        r = classify_instant("Hello")
        assert r is not None
        assert r.kind == "greeting"

    def test_thanks(self):
        r = classify_instant("谢谢")
        assert r is not None
        assert r.kind == "greeting"

    def test_ok(self):
        r = classify_instant("好的")
        assert r is not None
        assert r.kind == "greeting"

    def test_bye(self):
        r = classify_instant("再见")
        assert r is not None
        assert r.kind == "greeting"

    def test_continue(self):
        r = classify_instant("继续")
        assert r is not None
        assert r.kind == "greeting"


# ---------------------------------------------------------------------------
# 5. Short trivial text → direct
# ---------------------------------------------------------------------------

class TestDirectInstant:
    def test_short_statement(self):
        r = classify_instant("哈哈哈")
        assert r is not None
        assert r.kind == "direct"

    def test_emoji_like(self):
        r = classify_instant("666")
        # 纯数字也可能走 math，但 "666" 作为单数字不是表达式（无运算符）
        # 实际上纯数字也满足 math pattern，eval("666") = 666
        assert r is not None
        assert r.kind in ("math", "direct")


# ---------------------------------------------------------------------------
# 6. Should NOT be instant — complex queries need tools/full loop
# ---------------------------------------------------------------------------

class TestRejectInstant:
    def test_analyze_keyword(self):
        """含 FORCE_FULL 信号 → 不走 instant"""
        r = classify_instant("分析一下这段代码")
        assert r is None

    def test_write_code(self):
        r = classify_instant("帮我写一个排序算法")
        assert r is None

    def test_explain(self):
        r = classify_instant("解释一下什么是GPT")
        assert r is None

    def test_weather_query(self):
        """天气查询应命中 fast_rule，不走 instant"""
        r = classify_instant("今天天气怎么样")
        assert r is None

    def test_long_question(self):
        """超过20字的非简单问题不走 instant"""
        r = classify_instant("请问从北京到上海的高铁票价是多少钱啊？")
        assert r is None

    def test_question_mark_blocks_direct(self):
        """有问号的短文本不走 direct（可能是真问题）"""
        r = classify_instant("GDP是什么？")
        assert r is None

    def test_generate_keyword(self):
        r = classify_instant("generate a poem")
        assert r is None

    def test_summarize_keyword(self):
        r = classify_instant("summarize this")
        assert r is None
