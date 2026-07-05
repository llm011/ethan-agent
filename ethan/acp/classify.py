"""ACP task classification: complexity signals and heuristics."""

_CODING_COMPLEXITY_SIGNALS = [
    "implement", "refactor", "create", "write a", "build",
    "debug", "fix the bug", "add feature", "重构", "实现", "开发",
    "写一个", "创建", "修复", "新增功能", "优化代码",
]

_SIMPLE_SIGNALS = [
    "explain", "what is", "how does", "describe", "summarize",
    "解释", "什么是", "怎么", "描述", "总结",
]


def is_complex_coding_task(prompt: str) -> bool:
    """Heuristic: decide if this is a complex coding task worth delegating."""
    text = prompt.lower()

    # Simple questions → handle locally
    for sig in _SIMPLE_SIGNALS:
        if sig in text:
            return False

    # Complexity signals
    has_complexity = any(sig in text for sig in _CODING_COMPLEXITY_SIGNALS)
    if not has_complexity:
        return False

    # Code-related keywords (broad)
    has_code_keyword = any(kw in text for kw in [
        "python", "code", "function", "class", "script", "file", "api", "app",
        "test", "module", "database", "server", "client", "代码", "函数", "类",
        "脚本", "接口", "应用", "模块", "数据库",
    ])

    # Medium-length prompts with complexity + code = complex
    if has_complexity and has_code_keyword:
        return True

    # Long prompts with complexity signals are likely complex
    if has_complexity and len(prompt) > 80:
        return True

    return False
