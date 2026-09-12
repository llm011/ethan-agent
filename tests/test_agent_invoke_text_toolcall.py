"""Agent._parse_stream_text_tool_calls 要认 anthropic 风格 <invoke>/<parameter> 标记。

这是线上故障的直接回归：anthropic 格式代理 + deepseek 等非 Claude 模型时，
function calling 退化成把工具调用当正文下发（无 DSML 前缀的 anthropic 原生标记）。
provider 层不从 delta.tool_calls 里给工具调用，Agent 只能靠这个文本兜底解析；
认不出 → 这一轮没有工具可执行 → agent 停在半路不再运行。

同时确保：三种标记格式（DSML / invoke / call:tool{args}）互不干扰，优先级稳定。
"""
from ethan.core.agent import Agent

INVOKE_SAMPLE = (
    "我来帮你操作浏览器。\n"
    '<tool_calls>\n'
    '  <invoke name="browser_page">\n'
    '    <parameter name="action">mouse</parameter>\n'
    '    <parameter name="x">608</parameter>\n'
    '    <parameter name="y">412</parameter>\n'
    '  </invoke>\n'
    "</tool_calls>"
)


def _agent() -> Agent:
    """只测纯解析方法，不触发任何 IO：绕过 __init__。"""
    return object.__new__(Agent)


def test_parses_invoke_markup():
    calls = _agent()._parse_stream_text_tool_calls(INVOKE_SAMPLE)
    assert len(calls) == 1
    assert calls[0].name == "browser_page"
    assert calls[0].arguments == {"action": "mouse", "x": "608", "y": "412"}


def test_parses_multiple_invoke_blocks():
    content = (
        "<tool_calls>"
        '<invoke name="shell"><parameter name="command">ls -la</parameter></invoke>'
        '<invoke name="file_read"><parameter name="path">/tmp/a.txt</parameter></invoke>'
        "</tool_calls>"
    )
    calls = _agent()._parse_stream_text_tool_calls(content)
    assert [c.name for c in calls] == ["shell", "file_read"]
    assert calls[0].arguments == {"command": "ls -la"}


def test_invoke_without_outer_wrapper():
    """有的网关只发 <invoke>，不带外层 <tool_calls>。"""
    calls = _agent()._parse_stream_text_tool_calls(
        '<invoke name="shell"><parameter name="command">pwd</parameter></invoke>'
    )
    assert [c.name for c in calls] == ["shell"]
    assert calls[0].arguments == {"command": "pwd"}


def test_plain_text_yields_no_calls():
    """普通正文不能误判成工具调用（否则每轮都会凭空执行工具）。"""
    assert _agent()._parse_stream_text_tool_calls("你好，今天天气不错。") == []
    assert _agent()._parse_stream_text_tool_calls("") == []


def test_call_dialect_still_works():
    """既有的 `call:tool{args}` 形状不能被新分支回归掉。"""
    calls = _agent()._parse_stream_text_tool_calls(
        "call:default_api:shell{command:gh auth status,intent:检查权限}"
    )
    assert [c.name for c in calls] == ["shell"]
    assert calls[0].arguments["command"] == "gh auth status"
