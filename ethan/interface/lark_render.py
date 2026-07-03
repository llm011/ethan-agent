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

    - 工具名行：**icon label**（后可跟「 · _intent_」斜体 或「 · 参数摘要」纯文本兜底）
    - 结果行（✓ 开头）：成功 → italic text（轻量、不抢眼，多数情况一行扫过）
    - 结果行（✗ 开头）：失败 → code_block（灰底醒目，保留换行让错误堆栈可读）
    - thinking 行：italic text（弱化视觉权重，不与 bold 工具名抢焦点）
    - `---` 分隔行：hr（工具间分隔，比空行更明确）
    - 空行：空 element
    """
    import re
    rows = []
    for line in tool_text.split("\n"):
        line = line.rstrip()
        # 工具名行：**icon label**，其后可选「 · _intent_ (args)」或「 · args 兜底文本」。
        # group1=工具名, group2=intent(斜体), group3=args跟在intent后, group4=无intent时兜底args
        m = re.match(r'\*\*(.+?)\*\*(?:\s*·\s*_(.+?)_(?:\s*\(([^)]*)\))?)?(?:\s*·\s*(.+))?$', line)
        if m and any(emoji in m.group(1) for emoji in ("📖","💻","🔍","🌐","📁","✏️","🧠","💾","⏰","📋","✨","👤","📝","🔧")):
            row = [{"tag": "text", "text": m.group(1), "style": ["bold"]}]
            if m.group(2):  # intent（斜体）
                row.append({"tag": "text", "text": " · "})
                row.append({"tag": "text", "text": m.group(2), "style": ["italic"]})
                if m.group(3):  # args 跟在 intent 后面
                    row.append({"tag": "text", "text": f" ({m.group(3)})"})
            elif m.group(4):  # 无 intent 时兜底显示参数摘要（纯文本）
                row.append({"tag": "text", "text": " · " + m.group(4)})
            rows.append(row)
            continue
        # 分隔线（工具间）—— lark_oapi post 支持 hr tag（channel/outbound/markdown/to_post.py 与
        # channel/normalize/converters/post.py 均处理 tag=="hr"）。比空行更明确地切分工具组。
        if re.match(r'^[-=—]{3,}$', line):
            rows.append([{"tag": "hr"}])
            continue
        # 结果行：剥掉可能的 _ 包装，按 ✓/✗ 区分成功/失败。
        # 成功是多数、轻量不抢眼 → italic text；失败是少数、醒目有价值 → code_block 灰底，
        # 保留换行让错误堆栈可读（多行 code_block 由 lark_stream 拼成单行后整体塞进来）。
        stripped = line.lstrip().lstrip("`_").rstrip("`_")
        if stripped.startswith("✓"):
            rows.append([{"tag": "text", "text": stripped, "style": ["italic"]}])
            continue
        if stripped.startswith("✗"):
            # 失败结果：lark_stream 把换行转成字面量 \n 占位（便于塞进单行 tool_text），
            # 这里还原成真换行，让多行错误堆栈作为一个 code_block 整体渲染（灰底醒目）。
            # lark_stream 在末尾产生的 \n 已被它的切片逻辑剥掉，无需再处理。
            text = stripped.replace("\\n", "\n")
            rows.append([{"tag": "code_block", "language": "plain", "text": text}])
            continue
        # thinking 行（italic 弱化，不抢 bold 工具名焦点）
        if "thinking..." in line:
            rows.append([{"tag": "text", "text": "🤔 thinking...", "style": ["italic"]}])
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


def _strip_invalid_image_keys(text: str) -> str:
    """删掉不是飞书图片 key（img_ 开头）的 markdown 图片引用 ![alt](value)。

    飞书卡片只能渲染 img_xxx 形式的图片 key；HTTP URL / 本地路径等会被 CardKit 拒绝
    （200570）。HTTP URL 理论上应由上游换成 img_xxx，这里作兜底安全网，把任何未解析的图片引用整体剥掉。
    """
    import re
    if "![" not in text:
        return text

    def _repl(m):
        value = m.group(2)
        return m.group(0) if value.startswith("img_") else ""

    return re.sub(r'!\[([^\]]*)\]\(([^)\s]+)\)', _repl, text)


def _find_markdown_tables_outside_code_blocks(text: str) -> list:
    """返回正文里（代码块之外）的 markdown 表格列表，每项 {start, length, raw}。

    代码块里的示例表格不会被飞书解析成卡片表格元素，故排除——让计数和降级用同一份结果。
    表格定义：首行 |...|，紧跟一个分隔符行 |---|，后续为任意数据行。
    """
    import re
    code_ranges = [(m.start(), m.end()) for m in re.finditer(r'```[\s\S]*?```', text)]

    def _in_code(idx: int) -> bool:
        return any(s <= idx < e for s, e in code_ranges)

    table_re = re.compile(r'\|.+\|[\r\n]+\|[-:| ]+\|[\s\S]*?(?=\n\n|\n(?!\|)|$)')
    matches = []
    for m in table_re.finditer(text):
        if not _in_code(m.start()):
            matches.append({"start": m.start(), "length": m.end() - m.start(), "raw": m.group(0)})
    return matches


# 飞书卡片表格上限——4 张以上触发 230099/11310（实测）。前 N 张正常卡片渲染，超出降级。
FEISHU_CARD_TABLE_LIMIT = 3

# CardBuilder table 元素的默认分页大小。超出上限的 markdown 表格改用原生 table 元素后，
# page_size=10 是飞书 Card 2.0 table 元素允许的最大值（CardBuilder 会 clamp 到 1-10）。
# 更长表格由原生分页 UI 自动翻页。
_RICH_TABLE_PAGE_SIZE = 10


def _sanitize_text_for_card(text: str, table_limit: int = FEISHU_CARD_TABLE_LIMIT) -> str:
    """把超出 table_limit 的 markdown 表格降级为代码块，避免飞书卡片 230099/11310 错误。

    前 table_limit 张表格保持原样（可正常卡片渲染）；超出部分用 ``` 包裹，阻止飞书
    将其解析为卡片表格元素。代码块里的表格不计入。从后往前替换以保持前面的 index 不偏移。

    保留作为 fallback：CardBuilder rich 路径（`_render_card_content_rich`）失败时回退到此，
    保证不崩。rich 路径成功时不再走这里——超出表格改用原生 table 元素，不再降级成代码块。
    """
    matches = _find_markdown_tables_outside_code_blocks(text)
    if len(matches) <= table_limit:
        return text
    result = text
    for m in reversed(matches[table_limit:]):
        start, length, raw = m["start"], m["length"], m["raw"]
        replacement = "```\n" + raw + "```"
        result = result[:start] + replacement + result[start + length:]
    return result


def _optimize_markdown_style(text: str) -> str:
    """优化 markdown 样式以适配飞书卡片渲染（移植自 openclaw-lark markdown-style.ts）。

    - 标题降级：仅当原文含 H1~H3 时——H1 → H4，H2~H6 → H5（飞书卡片 H1/H2 显示过大）
    - 压缩 3+ 连续换行为 2 个
    - 剥离非 img_ 的图片引用（防 CardKit 200570）
    代码块内容不受影响（标题降级前先抽出代码块保护，处理完还原）。
    顺序：H2~H6→H5 必须在 H1→H4 之前，否则 H4 会被 #{2,6} 再次匹配成 H5。
    """
    import re
    try:
        mark = "\x00CB\x00"
        code_blocks: list[str] = []

        def _stash(m):
            idx = len(code_blocks)
            code_blocks.append(m.group(0))
            return f"{mark}{idx}{mark}"

        r = re.sub(r'```[^\n]*\n[\s\S]*?```', _stash, text)
        # 标题降级（仅当原文档含 h1~h3 时才执行）
        if re.search(r'^#{1,3} ', r, re.MULTILINE):
            r = re.sub(r'^#{2,6} (.+)$', r'##### \1', r, flags=re.MULTILINE)  # H2~H6 → H5
            r = re.sub(r'^# (.+)$', r'#### \1', r, flags=re.MULTILINE)        # H1 → H4
        # 还原代码块
        for i, block in enumerate(code_blocks):
            r = r.replace(f"{mark}{i}{mark}", block)
        # 压缩多余空行
        r = re.sub(r'\n{3,}', '\n\n', r)
        # 剥离非 img_ 图片引用
        r = _strip_invalid_image_keys(r)
        return r
    except Exception:
        return text


def _render_card_content(text: str) -> str:
    """把文本/markdown 渲染成飞书 interactive 卡片的 content JSON。

    飞书卡片 markdown element 遵循 CommonMark：
    - 单 \n 被折叠成空格（显示不换行）
    - 行尾两个空格 + \n 是硬换行（无额外间距）
    - \n\n 是段落分隔（有额外间距）
    预处理：先表格兜底 + 样式优化，再把孤立的单 \n 转为 "  \n"（硬换行），保留 \n\n 作段落。

    表格超 `FEISHU_CARD_TABLE_LIMIT` 张时走 `_render_card_content_rich`：超出部分改用
    CardBuilder 原生 table 元素（不再降级成代码块）。rich 路径失败时回退到此处的手拼 markdown
    + `_sanitize_text_for_card` 降级，保证不崩。
    """
    import json as _json, re as _re
    # 代码块外 markdown 表格超过上限 → 走 CardBuilder 原生 table 元素路径
    if len(_find_markdown_tables_outside_code_blocks(text)) > FEISHU_CARD_TABLE_LIMIT:
        rich = _render_card_content_rich(text)
        if rich is not None:
            return rich
        # rich 路径失败（import 失败 / build 失败）→ 回退到手拼 markdown + 降级
    text = _sanitize_text_for_card(text)
    text = _optimize_markdown_style(text)
    processed = _re.sub(r'(?<!\n)\n(?!\n)', '  \n', text)
    return _json.dumps({
        "schema": "2.0",
        "body": {"elements": [{"tag": "markdown", "content": processed}]},
    }, ensure_ascii=False)


def _parse_markdown_table(raw: str) -> tuple[list[str], list[list[str]]]:
    """把单个 markdown 表格解析成 (headers, rows)。

    - split 行，strip 空白
    - 每行必须以 `|` 开头和结尾，否则跳过（不属于表格行）
    - strip 首尾 `|` 后按 `|` 切分，每格 strip
    - 跳过分隔符行（`|---|:--:|---:|` 等）
    - 第一行非分隔符行 = headers，其余 = data rows
    无有效行时返回 ([], [])。
    """
    import re
    rows: list[list[str]] = []
    for ln in raw.strip().split("\n"):
        ln = ln.strip()
        if not ln or not ln.startswith("|") or not ln.endswith("|"):
            continue
        cells = [c.strip() for c in ln.strip("|").split("|")]
        # 分隔符行：每格都是 :-- / :-: / --: / --- 等纯装饰
        if cells and all(re.match(r"^:?-+:?$", c) for c in cells):
            continue
        rows.append(cells)
    if not rows:
        return [], []
    return rows[0], rows[1:]


def _split_around_tables(
    text: str, overflow: list[dict],
) -> list[tuple[str, str, str]]:
    """把 text 按 overflow 表格的位置切成有序片段。

    返回 [(kind, chunk, raw)] 列表，kind ∈ {"md","table"}：
    - "md"：表格之间的文本（chunk=文本，raw=""）
    - "table"：超出上限的表格（chunk=""，raw=表格原文）
    顺序按 text 中的位置。overflow 项含 {start, length, raw}，假设已按 start 排序且不重叠。
    """
    segments: list[tuple[str, str, str]] = []
    cursor = 0
    for m in overflow:
        s, e = m["start"], m["start"] + m["length"]
        if s > cursor:
            segments.append(("md", text[cursor:s], ""))
        segments.append(("table", "", m["raw"]))
        cursor = e
    if cursor < len(text):
        segments.append(("md", text[cursor:], ""))
    return segments


def _render_card_content_rich(text: str) -> str | None:
    """超 3 张表格时走 CardBuilder 原生 table 元素路径。失败返回 None（让调用方 fallback）。

    策略：代码块外的 markdown 表格，前 `FEISHU_CARD_TABLE_LIMIT` 张保留在 markdown 元素里
    （飞书原生渲染 markdown 表格，样式与正文一致），超出部分切出来用 `table()` 原生元素
    （不再降级成代码块）。表格之间的文本继续走 `markdown()` 元素。

    lazy import：`from lark_oapi.channel.card import new_card` 首次 ~10s（拉起 channel 子树），
    之后 Python 缓存。任何 import / build 异常都返回 None，由调用方回退到手拼 markdown +
    `_sanitize_text_for_card` 降级，保证渲染不崩。
    """
    import json as _json, re as _re
    try:
        from lark_oapi.channel.card import new_card
    except Exception:
        return None

    matches = _find_markdown_tables_outside_code_blocks(text)
    overflow = matches[FEISHU_CARD_TABLE_LIMIT:]
    if not overflow:
        return None  # 不该走 rich 路径，让调用方走手拼

    segments = _split_around_tables(text, overflow)
    try:
        c = new_card()
        for kind, chunk, raw in segments:
            if kind == "table":
                headers, rows = _parse_markdown_table(raw)
                if not headers:
                    # 解析失败：兜底降级成代码块，避免丢内容
                    c.code_block(raw, language="text")
                    continue
                c.table(headers, rows, page_size=_RICH_TABLE_PAGE_SIZE)
            else:
                # chunk 是表格之间的 markdown 文本，走和手拼路径一样的预处理
                # （样式优化 + 单 \n → 硬换行），保证前 3 张表格 + 正文渲染一致
                md = _optimize_markdown_style(chunk)
                md = _re.sub(r'(?<!\n)\n(?!\n)', '  \n', md)
                if md.strip():
                    c.markdown(md)
                # 全是空白的片段跳过——CardBuilder 不需要空 markdown 元素
        result = c.to_dict()
        return _json.dumps(result, ensure_ascii=False)
    except Exception:
        return None


def _render_post_content(text: str) -> str:
    """把多行文本渲染成飞书 post(富文本) 的 content JSON。

    post 的 text 标签是纯文本（不解析 markdown），但保留换行。
    适合 fast/medium 的简短回复。post 用 message.update 更新（流式编辑）。
    """
    import json as _json
    lines = text.split("\n") if text else [""]
    content = [[{"tag": "text", "text": line}] for line in lines]
    return _json.dumps({"zh_cn": {"content": content}}, ensure_ascii=False)
