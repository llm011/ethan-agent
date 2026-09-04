"""回归测试：网关把工具调用序列化成带包裹符的文本时，ethan 应解析成 ToolCall 并从正文剥离。

修复前这些 JSON 会被当成 assistant 正文原样显示（GLM 兼容层 / 本地 workbuddy 等网关的
包裹符不同，DSML 与 call:tool{args} 两个旧解析器覆盖不到），表现为消息里漏出一段裸工具调用。
"""
from ethan.providers.openai_compat import (
    _buf_has_unclosed_marked_tool,
    _strip_marked_tool_blocks,
    parse_marked_text_tool_calls,
)


def test_parse_marked_standard_shape():
    content = (
        '你看\n'
        '<tool_call> {"name": "shell", "arguments": {"command": "ls", "intent": "x"}} </tool_call>'
    )
    calls = parse_marked_text_tool_calls(content)
    assert len(calls) == 1
    assert calls[0].name == "shell"
    assert calls[0].arguments == {"command": "ls", "intent": "x"}


def test_parse_marked_tool_use_shape():
    content = '<tool_use> {"name": "shell", "arguments": {"command": "pwd"}} </tool_use>'
    calls = parse_marked_text_tool_calls(content)
    assert len(calls) == 1
    assert calls[0].name == "shell"
    assert calls[0].arguments == {"command": "pwd"}


def test_parse_marked_nested_function():
    content = '<tool_call> {"function": {"name": "shell", "arguments": {"command": "ls"}}} </tool_call>'
    calls = parse_marked_text_tool_calls(content)
    assert len(calls) == 1
    assert calls[0].name == "shell"
    assert calls[0].arguments == {"command": "ls"}


def test_strip_marked_blocks_keeps_prose():
    content = '我先查一下。\n<tool_call> {"name": "shell", "arguments": {"command": "ls"}} </tool_call>'
    stripped = _strip_marked_tool_blocks(content)
    assert stripped == "我先查一下。\n"
    assert parse_marked_text_tool_calls(stripped) == []


def test_buf_unclosed_detection():
    assert _buf_has_unclosed_marked_tool('<tool_call> {"name":"shell"') is True
    assert _buf_has_unclosed_marked_tool('<tool_call>{}</tool_call>') is False
    assert _buf_has_unclosed_marked_tool('普通文本') is False


def test_invalid_json_ignored():
    # 坏 JSON / 非对象不抛错、不误解析
    content = '<tool_call> {"name": "shell", "arguments": (bad} </tool_call>'
    assert parse_marked_text_tool_calls(content) == []
    assert _strip_marked_tool_blocks(content) == ""


# ---------------------------------------------------------------------------
# review 回归：闭合块 / 截断块不得漏为正文
# ---------------------------------------------------------------------------

def test_buffer_holds_closed_blocks_until_finish():
    """流式缓冲判定：已闭合的标记块也必须留在缓冲里（等 finish 统一解析），
    否则闭合标签到达瞬间 opens==closes，整块会走 else 分支当正文 yield 出去。"""
    from ethan.providers.openai_compat import _MARKED_TOOL_RE

    closed = '<tool_call> {"name": "shell", "arguments": {"command": "ls"}} </tool_call>'
    # _buf_has_unclosed_marked_tool 对闭合块返回 False —— 所以流式分支必须
    # 额外用 _MARKED_TOOL_RE.search 兜住这种情况
    assert _buf_has_unclosed_marked_tool(closed) is False
    assert _MARKED_TOOL_RE.search(closed) is not None


def test_strip_unclosed_truncated_block():
    """流被截断时闭合标签永远没到：半截块连带其后内容也要剥掉。"""
    content = '先看目录\n<tool_call> {"name": "shell", "arguments": {"comm'
    stripped = _strip_marked_tool_blocks(content)
    assert "tool_call" not in stripped
    assert stripped == "先看目录\n"
    assert parse_marked_text_tool_calls(stripped) == []


def test_parse_unclosed_block_returns_empty():
    assert parse_marked_text_tool_calls('<tool_call> {"name": "shell"') == []


def test_empty_arguments_not_dropped():
    """无参工具的合法 arguments={} 是 falsy，不能被 `or` 陷阱丢掉整条调用。"""
    content = '<tool_call> {"name": "get_time", "arguments": {}} </tool_call>'
    calls = parse_marked_text_tool_calls(content)
    assert len(calls) == 1
    assert calls[0].name == "get_time"
    assert calls[0].arguments == {}
