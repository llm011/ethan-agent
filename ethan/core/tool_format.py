from ethan.providers.base import ToolDefinition

# 这些参数值可能很长（用户输入/代码），需要截断避免刷屏
_TRUNCATE_ARGS = {"content", "text", "code", "prompt", "body", "description", "new_content", "value"}


def _format_args(arguments: dict, max_items: int = 3) -> str:
    """格式化工具参数为单行摘要。路径/命令等不截断，content/text 等长文本截断。

    跳过 intent——它单独作为「调用意图」展示（见 _with_intent_param），不混进参数行。
    """
    parts = []
    items = [(k, v) for k, v in arguments.items() if k != "intent"][:max_items]
    for k, v in items:
        s = str(v).replace("\n", " ")
        if k in _TRUNCATE_ARGS:
            if len(s) > 80:
                s = s[:80] + "…"
        elif len(s) > 150:
            # 超长路径/命令：保留头尾
            s = s[:100] + "…" + s[-40:]
        parts.append(f"{k}={s}")
    return ", ".join(parts)


# 工具调用意图（intent）：注入一个可选 string 参数，让模型用几个字说明每次调用目的，
# 供前端/飞书在工具调用旁显示（如「💻 terminal · 查 MR 状态」）。
#
# ⚠️ 这是标准 JSON Schema 参数（不是自定义顶层字段），所有 OpenAI 兼容 / Anthropic 模型都支持；
# 不放进 required，弱模型/中转即便不填也只回退到旧的 args 摘要，绝不报错（切模型也安全）。
_INTENT_DESC = "用不超过12个字说明本次调用目的（给用户看，会显示在工具调用旁）。例如：查 MR 状态 / 读配置文件 / 搜飞书文档"


def _with_intent_param(td: ToolDefinition) -> ToolDefinition:
    """给工具定义注入一个可选 intent 参数（模型填，用于展示调用意图）。

    不改原对象：deep copy parameters、追加 description，避免污染 registry 里共享的工具定义。
    """
    import copy
    params = copy.deepcopy(td.parameters) if isinstance(td.parameters, dict) else {}
    params.setdefault("type", "object")
    props = params.get("properties")
    if not isinstance(props, dict):
        props = {}
        params["properties"] = props
    props["intent"] = {"type": "string", "description": _INTENT_DESC}
    return ToolDefinition(
        name=td.name,
        description=td.description + "\n\n调用前请在 intent 参数里用一句话说明本次目的。",
        parameters=params,
    )


def _preview(content: str, max_lines: int = 3, max_chars: int = 200) -> str:
    """工具结果的紧凑预览：取前几行、总长度封顶，单行化。"""
    if not content:
        return ""
    lines = [ln.strip() for ln in content.splitlines() if ln.strip()][:max_lines]
    text = " ⏎ ".join(lines)
    if len(text) > max_chars:
        text = text[:max_chars] + "…"
    return text


def _detail(content: str, max_chars: int = 2000) -> str:
    """工具结果的详细版本（前端展开看），保留多行，封顶避免 SSE 过大。

    工具结果超过 4000 字会被 result_compressor 压缩，所以这里 2000 字够用。
    """
    if not content:
        return ""
    if len(content) > max_chars:
        return content[:max_chars] + f"\n…(共 {len(content)} 字，已截断)"
    return content
