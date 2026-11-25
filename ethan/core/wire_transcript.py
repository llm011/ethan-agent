"""Exact per-round wire message persistence and protocol-safe replay."""
from dataclasses import asdict

from ethan.providers.base import Message, ToolCall


def wire_message(message: Message) -> dict:
    return {
        "role": message.role, "content": message.content,
        "reasoning": message.reasoning or "",
        "tool_calls": [asdict(call) for call in message.tool_calls],
        "tool_call_id": message.tool_call_id,
        "images": message.images or [], "files": message.files,
    }


def restore_wire(messages: list[dict]) -> list[Message]:
    return [Message(
        role=m["role"], content=m.get("content", ""), reasoning=m.get("reasoning") or None,
        tool_calls=[ToolCall(**c) for c in m.get("tool_calls", [])],
        tool_call_id=m.get("tool_call_id"), images=m.get("images", []), files=m.get("files"),
    ) for m in messages]


def complete_wire(messages: list[dict]) -> list[dict]:
    """Only return protocol-valid rounds, never invented results for uncertain calls."""
    result = []
    index = 0
    while index < len(messages):
        message = messages[index]
        calls = message.get("tool_calls") or []
        if message.get("role") == "assistant" and calls:
            ids = {c["id"] for c in calls}
            tools = []
            pos = index + 1
            while pos < len(messages) and messages[pos].get("role") == "tool":
                tools.append(messages[pos])
                pos += 1
            if {m.get("tool_call_id") for m in tools} == ids and len(tools) == len(ids):
                result.extend([message, *tools])
            index = pos
        else:
            if message.get("role") != "tool":
                result.append(message)
            index += 1
    return result
