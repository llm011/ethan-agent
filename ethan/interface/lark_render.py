"""飞书消息渲染：把文本/markdown/工具进度转成飞书各类消息的 content JSON。

纯函数，无 IO、无网络。三种目标格式：
- post（富文本气泡）：`_render_post_content` / `_markdown_to_post_elements` / `_build_tool_elements`
- interactive 卡片：`_render_card_content`
被 lark_send / lark_stream 复用。
"""
from __future__ import annotations


def _markdown_to_post_elements(text: str) -> list:
    """把 markdown 文本转换为飞书 post 消息的 content element 数组。

    post 是气泡样式，支持行内格式（加粗/斜体/代码/链接），不支持卡片块。
    适用于定时任务结果、通知等不需要流式编辑的场景。

    支持的语法：
    - **text** / __text__  → bold
    - *text* / _text_      → italic
    - `text`               → inline_code
    - [text](url)          → 链接
    - # / ## / ### 标题    → 加粗一行
    - > 引用               → "│ " 前缀普通文字
    - - / * 无序列表       → "• " 前缀
    - 1. 有序列表          → 数字保留
    - --- / *** 分隔线     → 一行 "────────────"
    - 空行                 → 空行元素
    """
    import re

    def _parse_inline(line: str) -> list:
        """把一行文本解析成 post inline element 列表。"""
        elements = []
        # 依次匹配：链接、inline code、加粗、斜体
        pattern = re.compile(
            r'\[([^\]]+)\]\(([^)]+)\)'   # [text](url)
            r'|`([^`]+)`'                 # `code`
            r'|\*\*([^*]+)\*\*'           # **bold**
            r'|__([^_]+)__'               # __bold__
            r'|\*([^*]+)\*'               # *italic*
            r'|_([^_]+)_'                 # _italic_
        )
        pos = 0
        for m in pattern.finditer(line):
            # 普通文字（match 前）
            if m.start() > pos:
                plain = line[pos:m.start()]
                if plain:
                    elements.append({"tag": "text", "text": plain})
            link_text, url, code, bold1, bold2, it1, it2 = m.groups()
            if url:
                elements.append({"tag": "a", "text": link_text, "href": url})
            elif code:
                elements.append({"tag": "text", "text": code, "style": ["inline_code"]})
            elif bold1 or bold2:
                elements.append({"tag": "text", "text": bold1 or bold2, "style": ["bold"]})
            elif it1 or it2:
                elements.append({"tag": "text", "text": it1 or it2, "style": ["italic"]})
            pos = m.end()
        if pos < len(line):
            elements.append({"tag": "text", "text": line[pos:]})
        if not elements:
            elements = [{"tag": "text", "text": ""}]
        return elements

    lines = text.split("\n")
    result = []
    for raw in lines:
        line = raw.rstrip()
        # 分隔线
        if re.match(r'^[-*_]{3,}$', line):
            result.append([{"tag": "text", "text": "────────────"}])
            continue
        # 标题
        m = re.match(r'^(#{1,3})\s+(.*)', line)
        if m:
            result.append([{"tag": "text", "text": m.group(2), "style": ["bold"]}])
            continue
        # 引用
        if line.startswith("> "):
            elems = _parse_inline(line[2:])
            elems[0]["text"] = "│ " + elems[0].get("text", "")
            result.append(elems)
            continue
        # 无序列表
        m = re.match(r'^[-*]\s+(.*)', line)
        if m:
            elems = _parse_inline(m.group(1))
            elems[0]["text"] = "• " + elems[0].get("text", "")
            result.append(elems)
            continue
        # 有序列表
        m = re.match(r'^(\d+\.\s+)(.*)', line)
        if m:
            elems = _parse_inline(m.group(2))
            elems[0]["text"] = m.group(1) + elems[0].get("text", "")
            result.append(elems)
            continue
        # 普通行（含空行）
        result.append(_parse_inline(line))

    return result


def _build_tool_elements(tool_text: str) -> list:
    """把工具进度文本直接构造成 post element 数组，不经过 markdown 解析。

    - 工具名行：**icon label** + plain (args)
    - 结果行（✓/✗ 开头）：code_block（灰色背景框，区分于正文）
    - thinking 行：plain 文字
    - 空行：空 element
    """
    import re
    rows = []
    for line in tool_text.split("\n"):
        line = line.rstrip()
        # 工具名行：**icon label**(args) 或 **icon label**`(args)`
        m = re.match(r'\*\*(.+?)\*\*[`]?\(([^)]*)\)[`]?', line)
        if m:
            rows.append([
                {"tag": "text", "text": m.group(1), "style": ["bold"]},
                {"tag": "text", "text": f"  ({m.group(2)})"},
            ])
            continue
        # 工具名行（无参数）：**icon label**
        m2 = re.match(r'\*\*(.+?)\*\*\s*$', line)
        if m2 and any(emoji in m2.group(1) for emoji in ("📖","💻","🔍","🌐","📁","✏️","🧠","💾","⏰","📋","✨","👤","📝","🔧")):
            rows.append([{"tag": "text", "text": m2.group(1), "style": ["bold"]}])
            continue
        # 结果行（✓/✗ 或 _✓ 等前缀）
        stripped = line.lstrip().lstrip("`_").rstrip("`_")
        if stripped.startswith(("✓", "✗")):
            rows.append([{"tag": "code_block", "language": "plain", "text": stripped}])
            continue
        # thinking 行
        if "thinking..." in line:
            rows.append([{"tag": "text", "text": "🤔 thinking..."}])
            continue
        # 空行或其他
        rows.append([{"tag": "text", "text": line}])
    return rows


def _render_tool_msg_content(tool_text: str) -> str:
    """把工具进度文本转成飞书 post content JSON（有样式）。"""
    import json as _json
    return _json.dumps({
        "zh_cn": {"title": "", "content": _build_tool_elements(tool_text)}
    }, ensure_ascii=False)


def _render_card_content(text: str) -> str:
    """把文本/markdown 渲染成飞书 interactive 卡片的 content JSON。

    飞书卡片 markdown element 遵循 CommonMark：
    - 单 \n 被折叠成空格（显示不换行）
    - 行尾两个空格 + \n 是硬换行（无额外间距）
    - \n\n 是段落分隔（有额外间距）
    预处理：把孤立的单 \n 转为 "  \n"（硬换行），保留 \n\n 作段落。
    """
    import json as _json, re as _re
    processed = _re.sub(r'(?<!\n)\n(?!\n)', '  \n', text)
    return _json.dumps({
        "schema": "2.0",
        "body": {"elements": [{"tag": "markdown", "content": processed}]},
    }, ensure_ascii=False)


def _render_post_content(text: str) -> str:
    """把多行文本渲染成飞书 post(富文本) 的 content JSON。

    post 的 text 标签是纯文本（不解析 markdown），但保留换行。
    适合 fast/medium 的简短回复。post 用 message.update 更新（流式编辑）。
    """
    import json as _json
    lines = text.split("\n") if text else [""]
    content = [[{"tag": "text", "text": line}] for line in lines]
    return _json.dumps({"zh_cn": {"content": content}}, ensure_ascii=False)
