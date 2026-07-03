"""飞书工具调用 trace store + 敏感字段脱敏（移植自 openclaw-lark tool-use-trace-store.ts）。

lark_stream 在渲染工具进度气泡时，本可直接用 ToolEvent 里的 args_summary / result_preview
拼字符串——但那会把命令里的 token、URL query 里的 api_key 等敏感值原样刷进飞书卡片，
被群成员看到。这里提供一层中间层：

- 把工具调用步骤按 session（飞书 chat）存进内存 store，供后续重放/审计
- 入库前对所有参数值跑 sanitize：敏感 key（token/secret/password/…）→ [redacted]，
  命令行里的 --token=xxx / Authorization: Bearer xxx → [redacted]，URL query 里的
  api_key/token/secret/key → [redacted]，长文本按来源截断

lark_stream 当前直接用 chunk.args_summary 渲染，不强制改走 store；但把脱敏函数暴露出来，
让 lark_stream 在拼工具名行 / 结果行前先过一遍 sanitize，是从源头堵住泄漏的最小改动。
"""
from __future__ import annotations

import re

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

GENERIC_STRING_LIMIT = 512
RESULT_STRING_LIMIT = 1024
COMMAND_STRING_LIMIT = 4096
PATH_STRING_LIMIT = 2048

# 敏感字段名（参数 key 命中即整值 [redacted]，不看值内容）。
_SENSITIVE_KEY_RE = re.compile(
    r"secret|token|password|authorization|cookie|api[-_]?key|credential|"
    r"private[-_]?key|access[-_]?key|database[-_]?url|connection[-_]?string|"
    r"bearer|signing[-_]?key|encryption[-_]?key|session[-_]?id|client[-_]?secret|"
    r"auth[-_]?token",
    re.IGNORECASE,
)

# 行内敏感赋值：FOO=token123、--token=xxx、Authorization: Bearer xxx 等
# 行内 KEY=VALUE（不带空格的等号赋值）
_INLINE_ASSIGNMENT_RE = re.compile(
    r'(^|[\s"\'`])([A-Za-z_][A-Za-z0-9_]*)(=("[^"]*"|\'[^\']*\'|[^\s"\'`]+))'
)
# Authorization: Bearer xxx / Basic xxx / Token xxx
_AUTH_HEADER_SECRET_RE = re.compile(
    r"(Authorization\s*:\s*(?:Bearer|Basic|Token)\s+)([^\'\"\s]+)",
    re.IGNORECASE,
)
# -H/--header 'Key: value' 形式（带引号）
_QUOTED_HEADER_ARG_RE = re.compile(
    r'((?:^|[\s"\'`])(?:-H|--header)\s+)([\'"])([A-Za-z0-9_-]+)(\s*:\s*)([^\'"]*)(\2)'
)
# -H/--header Key:value 形式（不带引号）
_UNQUOTED_HEADER_ARG_RE = re.compile(
    r"((?:^|[\s\"\'`])(?:-H|--header)\s+)([A-Za-z0-9_-]+)(\s*:\s*)([^\s\"\'`]+)"
)
# --flag=xxx / -f xxx 形式（flag 名敏感时脱敏值）
_SECRET_FLAG_RE = re.compile(
    r'((?:^|[\s"\'`]))(--?[A-Za-z0-9][A-Za-z0-9-]*)(=|\s+)("[^"]*"|\'[^\']*\'|[^\s"\'`]+)'
)
# URL query 里的 api_key/token/secret/key 参数
_URL_SECRET_PARAM_RE = re.compile(r"([?&])(api_key|token|secret|key)=[^&]*", re.IGNORECASE)


def _is_sensitive_name(name: str) -> bool:
    return bool(_SENSITIVE_KEY_RE.search(name))


def _truncate_text(value: str, max_length: int) -> str:
    if len(value) <= max_length:
        return value
    return value[: max_length - 3] + "..."


def redact_inline_secrets(value: str) -> str:
    """脱敏命令行/文本里的行内敏感赋值。

    覆盖：KEY=VALUE、Authorization: Bearer xxx、-H/--header 'Key: value' 或 Key:value、
    --secret=xxx / -s xxx（flag 名敏感时）、URL query 里的 api_key/token/secret/key。
    """
    if not value:
        return value

    def _assign_repl(m):
        prefix, key = m.group(1), m.group(2)
        return f"{prefix}{key}=[redacted]" if _is_sensitive_name(key) else m.group(0)

    value = _INLINE_ASSIGNMENT_RE.sub(_assign_repl, value)
    value = _AUTH_HEADER_SECRET_RE.sub(r"\1[redacted]", value)

    def _quoted_header_repl(m):
        prefix, quote, name, sep = m.group(1), m.group(2), m.group(3), m.group(4)
        if _is_sensitive_name(name) and not re.fullmatch(r"authorization", name, re.IGNORECASE):
            return f"{prefix}{quote}{name}{sep}[redacted]{quote}"
        return m.group(0)

    value = _QUOTED_HEADER_ARG_RE.sub(_quoted_header_repl, value)

    def _unquoted_header_repl(m):
        prefix, name, sep = m.group(1), m.group(2), m.group(3)
        if _is_sensitive_name(name) and not re.fullmatch(r"authorization", name, re.IGNORECASE):
            return f"{prefix}{name}{sep}[redacted]"
        return m.group(0)

    value = _UNQUOTED_HEADER_ARG_RE.sub(_unquoted_header_repl, value)

    def _flag_repl(m):
        prefix, flag, sep = m.group(1), m.group(2), m.group(3)
        normalized = re.sub(r"^-+", "", flag)
        if not _is_sensitive_name(normalized):
            return m.group(0)
        # 保留引号语义：原值带引号则 [redacted] 也带同款引号
        raw_val = m.group(4)
        if raw_val.startswith('"'):
            redacted = '"[redacted]"'
        elif raw_val.startswith("'"):
            redacted = "'[redacted]'"
        else:
            redacted = "[redacted]"
        return f"{prefix}{flag}{sep}{redacted}"

    value = _SECRET_FLAG_RE.sub(_flag_repl, value)
    value = _URL_SECRET_PARAM_RE.sub(r"\1\2=[redacted]", value)
    return value


def _is_command_like_key(key: str | None) -> bool:
    if not key:
        return False
    return bool(re.search(r"(?:^|_)(?:command|script)(?:$|_)", key.lower()))


def _resolve_string_limit(source: str | None, key: str | None) -> int:
    k = (key or "").lower()
    if re.search(r"(?:^|_)(?:command|script|description|prompt|task)(?:$|_)", k):
        return COMMAND_STRING_LIMIT
    if re.search(r"(?:^|_)(?:path|file|url|uri|cwd|folder|dir)(?:$|_)", k):
        return PATH_STRING_LIMIT
    if source == "result":
        return RESULT_STRING_LIMIT
    return GENERIC_STRING_LIMIT


def _redact_url_params(value: str) -> str:
    return _URL_SECRET_PARAM_RE.sub(r"\1\2=[redacted]", value)


def sanitize_trace_string(value: str, source: str | None = None, key: str | None = None) -> str:
    """对单个字符串值脱敏：先剥 URL query 敏感参数；命令类 key 再跑行内脱敏。"""
    if not value:
        return value
    redacted_url = _redact_url_params(value)
    if _is_command_like_key(key):
        return redact_inline_secrets(redacted_url)
    return redacted_url


def sanitize_trace_value(value, depth: int = 0, source: str | None = None, key: str | None = None):
    """递归脱敏工具参数/结果。dict 的敏感 key → [redacted]，字符串按来源截断 + 脱敏。

    - dict：遍历前 12 个 key，敏感 key 整值替换；其余递归
    - list：取前 8 项递归
    - 字符串：脱敏 + 按来源截断
    - 深度 ≥2 不再展开，返回 '[truncated]'
    """
    if value is None:
        return None
    if isinstance(value, str):
        return _truncate_text(sanitize_trace_string(value, source, key), _resolve_string_limit(source, key))
    if isinstance(value, (int, float, bool)):
        return value
    if depth >= 2:
        return "[truncated]"
    if isinstance(value, list):
        return [sanitize_trace_value(v, depth + 1, source=source) for v in value[:8]]
    if isinstance(value, dict):
        out = {}
        for k, v in list(value.items())[:12]:
            ks = str(k)
            out[ks] = "[redacted]" if _is_sensitive_name(ks) else sanitize_trace_value(
                v, depth + 1, source=source, key=ks
            )
        return out
    return _truncate_text(str(value), 180)


def sanitize_args_summary(args_summary: str) -> str:
    """对 lark_stream 已拼好的单行参数摘要（key=value, key=value）脱敏。

    lark_stream 当前直接把 chunk.args_summary 拼进工具名行。这是「已经是字符串」的
    简化路径——不走 dict 递归，直接对整行跑行内脱敏 + 截断，保证 --token=xxx 这类
    内联敏感值不泄漏。命令/路径类长值不截断（与 _format_args 的语义一致）。
    """
    if not args_summary:
        return ""
    return redact_inline_secrets(args_summary)


def sanitize_result_preview(preview: str) -> str:
    """对工具结果预览脱敏 + 截断到 RESULT_STRING_LIMIT。

    结果里常含回显的命令/URL，跑一遍行内脱敏防泄漏；超长按结果上限截断。
    """
    if not preview:
        return ""
    return _truncate_text(redact_inline_secrets(preview), RESULT_STRING_LIMIT)


# ---------------------------------------------------------------------------
# Trace store（按 session key 存结构化步骤，供重放/审计；当前 lark_stream 未强依赖）
# ---------------------------------------------------------------------------

_TRACE_TTL_S = 30 * 60
_MAX_SESSION_TRACES = 128
_MAX_STEPS_PER_SESSION = 256

_session_traces: dict[str, dict] = {}


def _now_ms() -> int:
    import time
    return int(time.time() * 1000)


def _prune_trace_store() -> None:
    now = _now_ms()
    for k in [k for k, v in _session_traces.items() if now - v.get("updated_at", 0) > _TRACE_TTL_S * 1000]:
        _session_traces.pop(k, None)
    if len(_session_traces) <= _MAX_SESSION_TRACES:
        return
    overflow = len(_session_traces) - _MAX_SESSION_TRACES
    for k, _ in sorted(_session_traces.items(), key=lambda kv: kv[1].get("updated_at", 0))[:overflow]:
        _session_traces.pop(k, None)


def start_trace_run(session_key: str) -> None:
    """开始一轮工具 trace（一条飞书消息对应一轮）。重置该 session 的步骤列表。"""
    if not session_key:
        return
    _prune_trace_store()
    _session_traces[session_key] = {"next_seq": 1, "updated_at": _now_ms(), "steps": []}


def clear_trace_run(session_key: str) -> None:
    _session_traces.pop(session_key, None)


def record_tool_start(session_key: str, tool_name: str, params: dict | None = None,
                      tool_call_id: str = "") -> None:
    """记录工具开始。params 会经 sanitize_trace_value 脱敏后存。"""
    if not session_key or not tool_name:
        return
    state = _session_traces.get(session_key)
    if not state:
        return
    steps = state["steps"]
    if len(steps) >= _MAX_STEPS_PER_SESSION:
        steps.pop(0)
    steps.append({
        "id": str(state["next_seq"]),
        "seq": state["next_seq"],
        "tool": tool_name,
        "tool_call_id": tool_call_id or None,
        "params": sanitize_trace_value(params, 0, source="params") if params else None,
        "status": "running",
        "started_at": _now_ms(),
    })
    state["next_seq"] += 1
    state["updated_at"] = _now_ms()


def record_tool_end(session_key: str, tool_name: str, result=None, error: str = "",
                     duration_ms: int | None = None, tool_call_id: str = "",
                     params: dict | None = None) -> None:
    """记录工具结束。把 matching 的 running 步骤标完成；找不到则追加一条。"""
    if not session_key or not tool_name:
        return
    state = _session_traces.get(session_key)
    if not state:
        return
    steps = state["steps"]
    # 找最后一个同 tool_name（或同 tool_call_id）的 running 步骤
    idx = -1
    for i in range(len(steps) - 1, -1, -1):
        s = steps[i]
        if s["status"] != "running":
            continue
        if tool_call_id and s.get("tool_call_id") == tool_call_id:
            idx = i
            break
        if s["tool"] == tool_name:
            idx = i
    now = _now_ms()
    if idx >= 0:
        s = steps[idx]
        s["status"] = "error" if error else "success"
        s["result"] = sanitize_trace_value(result, 0, source="result")
        s["error"] = _truncate_text(error, 160) if error else None
        s["duration_ms"] = duration_ms
        s["finished_at"] = now
    else:
        steps.append({
            "id": str(state["next_seq"]),
            "seq": state["next_seq"],
            "tool": tool_name,
            "tool_call_id": tool_call_id or None,
            "params": sanitize_trace_value(params, 0, source="params") if params else None,
            "result": sanitize_trace_value(result, 0, source="result"),
            "error": _truncate_text(error, 160) if error else None,
            "duration_ms": duration_ms,
            "status": "error" if error else "success",
            "started_at": now,
            "finished_at": now,
        })
        state["next_seq"] += 1
    state["updated_at"] = now


def get_trace_steps(session_key: str) -> list[dict]:
    """读取该 session 的工具步骤（TTL 过期则清空返回 []）。"""
    if not session_key:
        return []
    state = _session_traces.get(session_key)
    if not state:
        return []
    if _now_ms() - state.get("updated_at", 0) > _TRACE_TTL_S * 1000:
        _session_traces.pop(session_key, None)
        return []
    return [dict(s) for s in state["steps"]]


def _reset_for_testing() -> None:
    """test-only：清空 store。"""
    _session_traces.clear()
