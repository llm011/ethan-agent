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


# ── 实体分类（用于调用链路可视化） ────────────────────────────────

def classify_tool(name: str) -> str:
    """按工具名分类实体类型，用于可视化时区分不同调用实体。

    5 类用户视角分类（从原来的 14 类合并），不易混淆：
      file      - 文件操作（file_read/write/list）
      system    - 终端命令（shell）
      knowledge - 知识技能（skill_*, knowledge_*, memory_*, procedure_*, profile_*）
      search    - 搜索查寻（web_search, web_fetch, rg_search, fd_find）
      connect   - 外部互联（browser_*, lark_*, schedule_*, ui_card, config, delegate, meta 等）
    """
    if name.startswith("file_"):
        return "file"
    if name == "shell":
        return "system"
    if name.startswith("knowledge_") or name.startswith("skill_"):
        return "knowledge"
    if name.startswith("memory_") or name.startswith("procedure_") or name.startswith("profile_"):
        return "knowledge"
    if name in ("web_search", "web_fetch", "rg_search", "ripgrep", "fd", "fd_find"):
        return "search"
    return "connect"


def resolve_skill_category(tool_name: str, arguments: dict) -> str:
    """当工具调用是 skill_read/skill_list 时，解析目标 skill 的加载层级。

    返回 "default" | "discoverable" | "plugin" | ""（非 skill 工具或解析失败）。
    用于前端在卡片上展示「常驻/按需/插件」角标。
    """
    if tool_name not in ("skill_read", "skill_list"):
        return ""
    name = arguments.get("name", "")
    if not name:
        return ""
    try:
        from ethan.skills.loader import load_all_skills
        skills = load_all_skills()
        for s in skills:
            if s.name == name:
                return getattr(s, "category", "default")
    except Exception:
        pass
    return ""


def extract_entity_id(tool_name: str, arguments: dict) -> str:
    """从工具调用参数中提取关联实体 ID（如 browser session_id）。

    用于可视化时把同一 browser session 的多次操作聚合到一个浏览器实体节点上。
    """
    if tool_name.startswith("browser_"):
        sid = arguments.get("session") or arguments.get("session_id")
        return str(sid) if sid else ""
    return ""
