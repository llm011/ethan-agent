"""会话标题清洗（_sanitize_title）测试。

不变量：
- 去掉模型泄漏的 <think> 思考块（成对 / 未闭合 / 多段 / 尾随）。
- 只剥「包裹整个标题」的行内强调定界符和「行首」块级标记，
  保留标题内部的合法字符——foo_bar / C# guide / A > B 不应被改动。
- 去掉首尾引号与空白。
"""

import pytest

from ethan.memory.session import _sanitize_title


@pytest.mark.parametrize(
    "raw,want",
    [
        # <think> 思考块
        ("<think>**Creating a title</think>项目初始化", "项目初始化"),
        ("<think>a</think><think>b</think>真正标题", "真正标题"),
        ("正文<think>trailing think</think>", "正文"),
        # 未闭合 <think>（被截断）→ 其后内容全丢
        ("<think>reasoning that got cut off and never closed", ""),
        # 成对包裹的强调定界符：脱符号、留文字
        ("**标题**", "标题"),
        ("*斜体标题*", "斜体标题"),
        ("~~删除线~~", "删除线"),
        ("**`嵌套代码`**", "嵌套代码"),
        # 行首块级标记
        ("# 一级标题 markdown", "一级标题 markdown"),
        ("> 引用式标题", "引用式标题"),
        # 首尾引号 / 空白
        ('  "引号标题"  ', "引号标题"),
        # 干净标题原样保留
        ("AI 记忆系统", "AI 记忆系统"),
        ("", ""),
    ],
)
def test_sanitize_cleans_noise(raw, want):
    assert _sanitize_title(raw) == want


@pytest.mark.parametrize(
    "raw",
    [
        "foo_bar",       # 内部下划线不是成对强调
        "C# guide",      # # 不在行首，不是 heading
        "A > B",         # > 不在行首，不是 quote
        "a * b = c",     # 孤立星号不成对
        "x_y_z 变量命名",  # 多个内部下划线
    ],
)
def test_sanitize_preserves_legit_symbols(raw):
    """含合法符号的标题不应被误改（PR #315 review 反馈）。"""
    assert _sanitize_title(raw) == raw
