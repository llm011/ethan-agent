"""标题净化 `_sanitize_title` 的单元测试。

回归背景（PR #315 review 发现）：早期实现用 `re.sub(r"[*_`~#>]+", "", t)` 全局删除
markdown 字符，会把 `foo_bar` / `C# guide` / `A > B` 这类合法标题静默改坏。

修复后语义：只剥掉「包裹整个标题的」行内强调定界符与「行首的」块级标记
（heading `#` / quote `>`），保留标题内部的合法字符。
"""

from ethan.memory.session import _sanitize_title, strip_title_decoration


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


def test_strip_cjk_bracket_marks():
    """书名号/方头括号类装饰符号全部剔除，留纯文字（用户反馈：列表里《》只剩装饰）。"""
    assert _sanitize_title("《三体》读后感") == "三体读后感"
    assert _sanitize_title("【重要】部署文档更新") == "重要部署文档更新"
    assert _sanitize_title("「配置中心」迁移方案") == "配置中心迁移方案"
    assert _sanitize_title("读《三体》和《球状闪电》的感想") == "读三体和球状闪电的感想"
    assert _sanitize_title("『嵌套』标题") == "嵌套标题"
    # 圆括号有实义，不剔除
    assert _sanitize_title("标题（草稿）") == "标题（草稿）"
    # 剔除后不留连续空格
    assert _sanitize_title("《a》 《b》 新功能") == "a b 新功能"


def test_strip_title_decoration_helper():
    """公共小函数：剔符号 + 压空格 + strip（_sanitize/_auto/REPL 初始标题共用）。"""
    assert strip_title_decoration("《三体》 读后  感") == "三体 读后 感"
    assert strip_title_decoration("  a\\n\\nb  ") == "a\\n\\nb"
    # 单个换行不归它管（\\s{2,} 才压），交给调用方 replace("\\n", " ")
    assert strip_title_decoration("a\\nb") == "a\\nb"
    assert strip_title_decoration("") == ""
