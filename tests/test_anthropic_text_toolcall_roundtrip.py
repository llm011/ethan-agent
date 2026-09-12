"""回环：从文本恢复出的工具调用，要能作为原生 tool_use 回传给 anthropic 端点。

这是「跑一半停住」修复的**第二半**。第一半是认出文本标记；但如果把恢复出的调用
再发给端点时形状不对，网关照样会 400/静默丢弃，多轮一样会断。

文本恢复的特征：
  - ToolCall.id 是本地合成的（call_xxxxxxxx），不是上游给的
  - arguments 全是字符串（XML 不带类型）
这里验证 _to_anthropic_messages 能把这种消息正常序列化成
assistant.tool_use + user.tool_result 的对，且 id 前后一致（回环闭环）。
"""
from ethan.providers.anthropic import AnthropicProvider
from ethan.providers.base import Message, ToolCall


def _provider() -> AnthropicProvider:
    return object.__new__(AnthropicProvider)


def test_text_recovered_toolcall_serializes_as_native_tool_use():
    """合成 id + 字符串参数也要能序列化成合法 tool_use 块。"""
    tc = ToolCall(id="call_abc12345", name="browser_page",
                  arguments={"action": "mouse", "x": "608", "y": "412"})
    msgs = [
        Message(role="user", content="点一下那个按钮"),
        Message(role="assistant", content="我来帮你操作浏览器。", tool_calls=[tc]),
    ]
    out = _provider()._to_anthropic_messages(msgs)

    assistant = out[-1]
    assert assistant["role"] == "assistant"
    blocks = assistant["content"]
    assert blocks[0] == {"type": "text", "text": "我来帮你操作浏览器。"}
    tu = blocks[1]
    assert tu["type"] == "tool_use"
    assert tu["id"] == "call_abc12345"
    assert tu["name"] == "browser_page"
    assert tu["input"] == {"action": "mouse", "x": "608", "y": "412"}


def test_tool_result_pairs_back_by_id():
    """工具结果要用同一个 id 回传，形成 tool_use ↔ tool_result 闭环。"""
    tc = ToolCall(id="call_abc12345", name="browser_page", arguments={"action": "mouse"})
    msgs = [
        Message(role="assistant", content="", tool_calls=[tc]),
        Message(role="tool", content="ok=true", tool_call_id="call_abc12345"),
    ]
    out = _provider()._to_anthropic_messages(msgs)

    assert out[0]["content"][0]["id"] == "call_abc12345"
    result_block = out[1]["content"][0]
    assert result_block["type"] == "tool_result"
    assert result_block["tool_use_id"] == "call_abc12345"
    assert result_block["content"] == "ok=true"


def test_multiple_recovered_calls_keep_distinct_ids():
    """一轮里恢复出多个调用时 id 不能撞车（否则结果回填会错位）。"""
    tcs = [
        ToolCall(id="call_1", name="shell", arguments={"command": "ls"}),
        ToolCall(id="call_2", name="shell", arguments={"command": "pwd"}),
    ]
    out = _provider()._to_anthropic_messages(
        [Message(role="assistant", content="", tool_calls=tcs)]
    )
    blocks = out[0]["content"]
    assert [b["id"] for b in blocks] == ["call_1", "call_2"]
    assert [b["input"]["command"] for b in blocks] == ["ls", "pwd"]
