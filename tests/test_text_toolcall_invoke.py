"""回归测试：anthropic 兼容网关把原生 tool_use 降级成**正文文本**时，ethan 应认出它。

背景：经 anthropic 格式代理接非 Claude 模型（如 deepseek）时，function calling 会退化成
把工具调用当正文发下来，形状是不带 DSML 前缀的 anthropic 原生标记：

    <tool_calls>
      <invoke name="browser_page">
        <parameter name="action">mouse</parameter>
        <parameter name="x">608</parameter>
      </invoke>
    </tool_calls>

修复前：解析器只认 DSML（带 `｜｜DSML｜｜` 前缀）和 `<tool_call>{json}`，这种形状一个都
不匹配 → 这一轮无工具可执行、也没有正文可展示 → agent 静默停在半路（用户观察到的
「跑了 27/38 步后不再运行」）。现在要能解析成 ToolCall，并从展示正文里剥掉标记。
"""
from ethan.providers._text_toolcalls import (
    buf_has_unclosed_invoke,
    contains_invoke,
    parse_invoke_tool_calls,
    strip_invoke_tool_blocks,
)

SAMPLE = (
    "我来帮你操作浏览器。\n"
    '<tool_calls>\n'
    '  <invoke name="browser_page">\n'
    '    <parameter name="action">mouse</parameter>\n'
    '    <parameter name="x">608</parameter>\n'
    '    <parameter name="y">412</parameter>\n'
    '  </invoke>\n'
    "</tool_calls>\n"
)


def test_parse_invoke_single_call():
    calls = parse_invoke_tool_calls(SAMPLE)
    assert len(calls) == 1
    assert calls[0].name == "browser_page"
    assert calls[0].arguments == {"action": "mouse", "x": "608", "y": "412"}
    assert calls[0].id.startswith("call_")


def test_parse_invoke_multiple_calls_in_one_block():
    content = (
        "<tool_calls>"
        '<invoke name="shell"><parameter name="command">ls</parameter></invoke>'
        '<invoke name="get_time"><parameter name="tz">UTC</parameter></invoke>'
        "</tool_calls>"
    )
    calls = parse_invoke_tool_calls(content)
    assert [c.name for c in calls] == ["shell", "get_time"]
    assert calls[0].arguments == {"command": "ls"}
    assert calls[1].arguments == {"tz": "UTC"}


def test_parse_invoke_without_outer_wrapper():
    """有的网关只发 <invoke>，不带外层 <tool_calls>。"""
    calls = parse_invoke_tool_calls('<invoke name="shell"><parameter name="command">pwd</parameter></invoke>')
    assert len(calls) == 1
    assert calls[0].name == "shell"
    assert calls[0].arguments == {"command": "pwd"}


def test_parse_invoke_no_params_yields_empty_arguments():
    calls = parse_invoke_tool_calls('<tool_calls><invoke name="get_time"></invoke></tool_calls>')
    assert len(calls) == 1
    assert calls[0].name == "get_time"
    assert calls[0].arguments == {}


def test_parse_invoke_garbage_returns_empty():
    assert parse_invoke_tool_calls("") == []
    assert parse_invoke_tool_calls("普通文本，没有工具调用") == []


def test_strip_keeps_prose_around_markup():
    """标记前后的正文要保留——模型可能先写一句「我来帮你操作」。"""
    stripped = strip_invoke_tool_blocks(SAMPLE)
    assert stripped.strip() == "我来帮你操作浏览器。"
    assert "invoke" not in stripped
    assert "parameter" not in stripped


def test_strip_only_markup():
    stripped = strip_invoke_tool_blocks('<invoke name="shell"><parameter name="command">ls</parameter></invoke>')
    assert stripped.strip() == ""


def test_strip_unclosed_truncated_block():
    """流被截断、闭合标签永远没到：半截块连带其后内容一并剥掉。"""
    content = '我先看看\n<tool_calls>\n<invoke name="browser_page">\n<parameter name="action">click'
    stripped = strip_invoke_tool_blocks(content)
    assert "invoke" not in stripped
    assert stripped.strip() == "我先看看"


def test_contains_invoke_detection():
    assert contains_invoke(SAMPLE) is True
    assert contains_invoke("普通回答") is False
    assert contains_invoke("") is False


def test_buf_unclosed_invoke_detection():
    """流式缓冲判定：未闭合要缓冲（否则半截 XML 漏给用户），闭合后可安全解析。"""
    assert buf_has_unclosed_invoke('<tool_calls><invoke name="shell">') is True
    assert buf_has_unclosed_invoke('<invoke name="shell"><parameter name="c">ls</parameter></invoke>') is False
    assert buf_has_unclosed_invoke("普通文本") is False
    assert buf_has_unclosed_invoke("") is False


def test_markup_detected_by_parser_and_buffer_agree():
    """流式分支的缓冲条件（unclosed 或 含 <invoke）要与解析器判定一致，
    否则已闭合的块会在中途走 else 分支当正文漏出去。"""
    closed = '<invoke name="shell"><parameter name="command">ls</parameter></invoke>'
    assert parse_invoke_tool_calls(closed)  # 已闭合 → 能解析
    assert buf_has_unclosed_invoke(closed) is False
    assert contains_invoke(closed) is True  # 所以缓冲分支要额外用 contains_invoke 兜住
