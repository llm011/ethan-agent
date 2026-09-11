"""文本/标记型工具调用解析。

一些网关/中转不返回标准 tool_calls，而是把工具调用拼成字符串再下发，形状各异：
标记型 <tool_call>/<tool_use>、DeepSeek DSML、cliproxy 的 `call:tool{args}`。
本模块统一识别并从「展示正文」里剥掉，避免 JSON 原样漏给用户。

从 openai_compat.py 拆出，纯函数、无 provider 状态依赖；OpenAICompatProvider
在类上保留同名（含 staticmethod）转发，故对外行为与拆分前完全一致。
"""
from __future__ import annotations

import json
import re
import uuid

from ethan.providers.base import ToolCall

# 一些网关/中转不返回标准 tool_calls，而是把工具调用拼成字符串再用包裹符包起来下发。
# ethan 原本只识别 DSML（<｜｜DSML｜｜…）与 `call:tool{args}` 两种文本格式；GLM 兼容层、本地
# workbuddy 等会换包裹符。这里统一兜底识别，并把它们从「展示正文」里剥掉，避免 JSON 原样
# 漏给用户（表现为 assistant 消息里出现一段裸工具调用文本）。
_MARKED_TOOL_RE = re.compile(
    r'<\s*(?P<open>tool_call|tool_use)\s*[^>]*>\s*'
    r'(?P<body>\{[\s\S]*?\})\s*'
    r'</\s*(?P=open)\s*>',
    re.IGNORECASE,
)


def _strip_marked_tool_blocks(content: str) -> str:
    """把 <tool_call>/<tool_use> 包裹的工具调用片段从正文中剥掉，只留真正文。

    无论能否解析成工具调用，都先移除，防止序列化后的工具调用露出为可见正文。
    流被截断时闭合标签可能永远没到：未闭合的开头标签连带其后内容一并去掉。
    """
    if not content:
        return content
    stripped = _MARKED_TOOL_RE.sub("", content)
    m = re.search(r"<\s*(?:tool_call|tool_use)\b[^>]*>[\s\S]*$", stripped, re.IGNORECASE)
    if m:
        stripped = stripped[: m.start()]
    return stripped


def _buf_has_unclosed_marked_tool(content: str) -> bool:
    """判断文本缓冲区是否包含「尚未闭合」的标记型工具调用块。

    流式分片时 <tool_call>/<tool_use> 的开头标签可能先到、闭合标签后到，若按普通文本
    yield 出去就会露馅。检测到未闭合时持续缓冲，直到流结束再统一解析。
    """
    for tag in ("tool_call", "tool_use"):
        opens = len(re.findall(r'<\s*' + tag + r'\b', content, re.IGNORECASE))
        closes = len(re.findall(r'<\s*/\s*' + tag + r'\s*>', content, re.IGNORECASE))
        if opens > closes:
            return True
    return False


def parse_marked_text_tool_calls(content: str) -> list[ToolCall]:
    """解析以包裹符序列化的文本工具调用。

    兼容两种形状：
      - 直接 {"name": ..., "arguments": {...}}
      - 嵌套 {"function": {"name":..., "arguments":...}}
      解析失败静默跳过，不抛错。返回 ToolCall 列表（可能为空）。
    """
    results: list[ToolCall] = []
    for m in _MARKED_TOOL_RE.finditer(content or ""):
        raw = m.group("body").strip()
        try:
            obj = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            continue
        if not isinstance(obj, dict):
            continue
        name = obj.get("name") or obj.get("tool_name")
        # 注意用 None 判断而不是 or：无参工具的合法 arguments={} 是 falsy，
        # 用 or 会把它误当成缺失、整条调用被丢弃
        arguments = obj.get("arguments")
        if arguments is None:
            arguments = obj.get("input")
        if isinstance(obj.get("function"), dict):
            fn = obj["function"]
            name = name or fn.get("name")
            if arguments is None:
                arguments = fn.get("arguments")
        if not name or not isinstance(arguments, dict):
            continue
        results.append(ToolCall(
            id=f"call_{uuid.uuid4().hex[:8]}",
            name=str(name),
            arguments=arguments,
        ))
    return results


def parse_dsml_tool_calls(content: str) -> list[ToolCall]:
    """解析 DeepSeek DSML 格式的工具调用文本。

    DeepSeek 模型偶尔会在 content 中以自有标记格式输出 tool calls：
        <｜｜DSML｜｜tool_calls> <｜｜DSML｜｜invoke name="tool"> <｜｜DSML｜｜parameter name="key" string="true">value</｜｜DSML｜｜parameter> ...
    """
    import re
    import uuid

    # 全角和半角竖线都匹配
    sep = r'[｜|]'
    tag = sep + sep + r'DSML' + sep + sep

    if "DSML" not in content:
        return []

    results = []
    # 匹配每个 invoke 块
    invoke_pattern = re.compile(
        r'<' + tag + r'invoke\s+name="([^"]+)"[^>]*>(.*?)</' + tag + r'invoke>',
        re.DOTALL
    )
    param_pattern = re.compile(
        r'<' + tag + r'parameter\s+name="([^"]+)"[^>]*>(.*?)</' + tag + r'parameter>',
        re.DOTALL
    )

    for inv_match in invoke_pattern.finditer(content):
        tool_name = inv_match.group(1)
        body = inv_match.group(2)
        args = {}
        for p_match in param_pattern.finditer(body):
            args[p_match.group(1)] = p_match.group(2).strip()
        results.append(ToolCall(
            id=f"call_{uuid.uuid4().hex[:8]}",
            name=tool_name,
            arguments=args,
        ))

    return results


def contains_dsml(content: str) -> bool:
    return "DSML" in content and ("｜｜DSML｜｜" in content or "||DSML||" in content)


def parse_text_tool_calls(content: str) -> list[ToolCall]:
    """从文本中解析 `call:<tool_name>{<args>}` 格式的工具调用。

    某些中转 API（如 cliproxy 转发 Gemini）在 function calling 退化时，
    会把工具调用序列化成文本而非标准 tool_calls 字段。格式示例：
        call:default_api:shell{command:gh auth status,intent:检查权限}

    其中 default_api 是 provider 前缀，实际工具名是冒号后的部分。
    args 不是标准 JSON（key 不带引号），需要宽松解析。
    """
    import re
    import uuid

    # 匹配 call:<prefix>:<tool_name>{<args>} 或 call:<tool_name>{<args>}
    pattern = re.compile(
        r'call:\w+:(?P<tool>\w+)\{(?P<args>[^}]*)\}'
        r'|call:(?P<tool2>\w+)\{(?P<args2>[^}]*)\}'
    )
    results = []
    for m in pattern.finditer(content):
        tool_name = m.group("tool") or m.group("tool2") or ""
        args_str = m.group("args") or m.group("args2") or ""
        if not tool_name:
            continue

        # 宽松解析 args：key:value,key:value 格式
        # value 可能包含逗号（如 shell 命令），用贪心匹配到最后一个 value
        args = {}
        # 尝试按 key:value 拆分，但 value 里可能含逗号
        # 策略：找到所有 key: 模式，然后取到下一个 key: 之前的内容作为 value
        key_pattern = re.compile(r'(\w+):')
        key_positions = [(km.start(), km.group(1)) for km in key_pattern.finditer(args_str)]
        for i, (pos, key) in enumerate(key_positions):
            val_start = pos + len(key) + 1  # 跳过 "key:"
            if i + 1 < len(key_positions):
                val_end = key_positions[i + 1][0]
            else:
                val_end = len(args_str)
            val = args_str[val_start:val_end].rstrip(',').strip()
            args[key] = val

        if args:
            results.append(ToolCall(
                id=f"call_{uuid.uuid4().hex[:8]}",
                name=tool_name,
                arguments=args,
            ))

    return results
