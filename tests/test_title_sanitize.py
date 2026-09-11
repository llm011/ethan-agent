"""标题净化 `_sanitize_title` 的单元测试。

回归背景（PR #315 review 发现）：早期实现用 `re.sub(r"[*_`~#>]+", "", t)` 全局删除
markdown 字符，会把 `foo_bar` / `C# guide` / `A > B` 这类合法标题静默改坏。

修复后语义：只剥掉「包裹整个标题的」行内强调定界符与「行首的」块级标记
（heading `#` / quote `>`），保留标题内部的合法字符。
"""

from ethan.memory.session import _sanitize_title


def test_strip_wrapping_bold():
    assert _sanitize_title("**标题**") == "标题"
    assert _sanitize_title("*Creating a plan*") == "Creating a plan"
    assert _sanitize_title("`code title`") == "code title"
    assert _sanitize_title("~~删除线标题~~") == "删除线标题"


def test_strip_nested_wrapping():
    assert _sanitize_title("**`重要标题`**") == "重要标题"


def test_strip_leading_heading_and_quote():
    assert _sanitize_title("# 我的标题") == "我的标题"
    assert _sanitize_title("### 标题") == "标题"
    assert _sanitize_title("> 引用标题") == "引用标题"


def test_strip_think_block():
    assert _sanitize_title("<think>想想看</think>正式标题") == "正式标题"
    # 未闭合 <think> 被截断，其后内容全丢
    assert _sanitize_title("<think>推理中...") == ""
    # 兜底清残余碎片
    assert _sanitize_title("标题</think>") == "标题"


def test_preserve_internal_markdown_chars():
    """reviewer 明确点名：内部的 _ # > 等合法字符不应被删。"""
    assert _sanitize_title("foo_bar") == "foo_bar"
    assert _sanitize_title("C# guide") == "C# guide"
    assert _sanitize_title("A > B") == "A > B"
    assert _sanitize_title("snake_case_name") == "snake_case_name"
    assert _sanitize_title("issue #42 复盘") == "issue #42 复盘"
    assert _sanitize_title("x * y = z") == "x * y = z"


def test_strip_surrounding_quotes_and_whitespace():
    assert _sanitize_title('  "带引号标题"  ') == "带引号标题"
    assert _sanitize_title("“中文引号”") == "中文引号"


def test_empty_and_whitespace():
    assert _sanitize_title("") == ""
    assert _sanitize_title("   ") == ""


def test_combined_think_and_wrapping():
    """脏值组合：<think> + 包裹 markdown。"""
    assert _sanitize_title("<think>思考</think>**最终标题**") == "最终标题"
