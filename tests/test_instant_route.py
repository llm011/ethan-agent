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

    def test_reject_pure_number(self):
        """纯数字（如端口号 8080）不应走 math 通道"""
        r = classify_instant("8080")
        assert r is None or r.kind != "math"

    def test_reject_large_exponent(self):
        """大数幂运算（9^9999999999）应被拦截，不能卡死"""
        assert _safe_math_eval("9**9999999999") is None

    def test_reject_large_exponent_caret(self):
        """用户输入 ^ 格式的大数幂不能走 math（防卡死）"""
        r = classify_instant("9^99999")
        # math 被拒绝，direct 已移除 → 返回 None
        assert r is None

    def test_reject_phone_number(self):
        """电话号码 138-1234-5678 不是算术"""
        r = classify_instant("138-1234-5678")
        assert r is None

    def test_reject_400_number(self):
        """400 电话 400-123-4567 不是算术"""
        r = classify_instant("400-123-4567")
        assert r is None

    def test_reject_serial_number(self):
        """编号 12-34-56 三段 dash 分隔不是算术"""
        r = classify_instant("12-34-56")
        assert r is None

    def test_reject_intl_phone(self):
        """国际电话 86-138-1234-5678"""
        r = classify_instant("86-138-1234-5678")
        assert r is None

    def test_allow_simple_subtraction(self):
        """两段 3-2 仍然是合法算术"""
        r = classify_instant("3-2")
        assert r is not None
        assert r.kind == "math"
        assert r.answer == "1"

    def test_allow_subtraction_two_segments(self):
        """两段 10-5 仍然是合法算术"""
        r = classify_instant("10-5")
        assert r is not None
        assert r.kind == "math"
        assert r.answer == "5"

    def test_reject_verification_code(self):
        """纯数字验证码 123456 无运算符 → 不走 math"""
        r = classify_instant("123456")
        assert r is None

    def test_reject_short_digit_answer(self):
        """纯数字 '3' 可能是选择题答案 → 不走 math"""
        r = classify_instant("3")
        assert r is None


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

    def test_bye(self):
        r = classify_instant("再见")
        assert r is not None
        assert r.kind == "greeting"

    def test_good_night(self):
        r = classify_instant("晚安")
        assert r is not None
        assert r.kind == "greeting"

    def test_never_mind(self):
        """'没事了' 是取消/告别，不需要工具"""
        r = classify_instant("没事了")
        assert r is not None
        assert r.kind == "greeting"

    def test_forget_it(self):
        """'算了' 是取消，不需要工具"""
        r = classify_instant("算了")
        assert r is not None
        assert r.kind == "greeting"

    def test_continue(self):
        """'继续' 需要上下文，不走 instant"""
        r = classify_instant("继续")
        assert r is None

    def test_hello_with_exclamation(self):
        """带感叹号：你好！"""
        r = classify_instant("你好！")
        assert r is not None
        assert r.kind == "greeting"

    def test_thanks_with_tilde(self):
        """带波浪号：谢谢~"""
        r = classify_instant("谢谢~")
        assert r is not None
        assert r.kind == "greeting"

    def test_hello_with_english_exclamation(self):
        """Hello!"""
        r = classify_instant("Hello!")
        assert r is not None
        assert r.kind == "greeting"

    def test_bye_with_period(self):
        """再见。"""
        r = classify_instant("再见。")
        assert r is not None
        assert r.kind == "greeting"


# ---------------------------------------------------------------------------
# 5. Confirmations should NOT be instant (moved out of greeting)
# ---------------------------------------------------------------------------

class TestConfirmationsNotInstant:
    """确认词可能是对上文动作的确认，需要工具执行 → 不走 instant。"""

    def test_ok_cn(self):
        """'好的' 可能确认'要帮你发邮件吗？' → 需要工具"""
        r = classify_instant("好的")
        assert r is None

    def test_ok_en(self):
        r = classify_instant("ok")
        assert r is None

    def test_ok_en_upper(self):
        r = classify_instant("OK")
        assert r is None

    def test_xing(self):
        """'行' 确认"""
        r = classify_instant("行")
        assert r is None

    def test_understood(self):
        """'明白'"""
        r = classify_instant("明白")
        assert r is None

    def test_got_it(self):
        """'了解'"""
        r = classify_instant("了解")
        assert r is None

    def test_received(self):
        """'收到'"""
        r = classify_instant("收到")
        assert r is None

    def test_hmm(self):
        """'嗯' 可能是确认执行"""
        r = classify_instant("嗯")
        assert r is None

    def test_hmm_double(self):
        """'嗯嗯'"""
        r = classify_instant("嗯嗯")
        assert r is None

    def test_ok_with_exclamation(self):
        """'好的！' 带标点也不应走 instant"""
        r = classify_instant("好的！")
        assert r is None


# ---------------------------------------------------------------------------
# 6. Short text that should NOT be instant (previously "direct" category, now removed)
# ---------------------------------------------------------------------------

class TestShortTextNotInstant:
    """短文本不再自动走 instant——只有精确匹配 greeting 才走。"""

    def test_hahaha(self):
        """'哈哈哈' 不在 greeting 列表 → 走正常路由"""
        r = classify_instant("哈哈哈")
        assert r is None

    def test_pure_number(self):
        """纯数字 '666' 无运算符 → 不走 math，也不走 direct"""
        r = classify_instant("666")
        assert r is None

    def test_business_progress(self):
        """'我上周的业务进展怎么样' — 需要查记录，不能直答"""
        r = classify_instant("我上周的业务进展怎么样")
        assert r is None

    def test_check_it(self):
        """'你查下呀' — 明确要求查询"""
        r = classify_instant("你查下呀")
        assert r is None

    def test_short_task(self):
        """'发个周报' — 需要工具"""
        r = classify_instant("发个周报")
        assert r is None

    def test_show_schedule(self):
        """'看看日程' — 需要查日历"""
        r = classify_instant("看看日程")
        assert r is None

    def test_short_question_no_mark(self):
        """'最近有啥消息' — 虽无问号但需要查数据"""
        r = classify_instant("最近有啥消息")
        assert r is None

    def test_read_doc(self):
        """'打开那个文档' — 需要工具"""
        r = classify_instant("打开那个文档")
        assert r is None


# ---------------------------------------------------------------------------
# 7. Should NOT be instant — complex queries need tools/full loop
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

    def test_retry_cn(self):
        """'重试下' 需要回到正常路由用工具重试"""
        r = classify_instant("重试下")
        assert r is None

    def test_retry_again(self):
        """'再试一次'"""
        r = classify_instant("再试一次")
        assert r is None

    def test_retry_en(self):
        """'retry'"""
        r = classify_instant("retry")
        assert r is None

    def test_redo(self):
        """'重来'"""
        r = classify_instant("重来")
        assert r is None

    def test_continue_context(self):
        """'接着做' 需要上下文"""
        r = classify_instant("接着做")
        assert r is None

    def test_before_reference(self):
        """'刚才那个' 引用上下文"""
        r = classify_instant("刚才那个")
        assert r is None
