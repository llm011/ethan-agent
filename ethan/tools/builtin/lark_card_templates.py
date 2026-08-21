"""高频卡片 → 飞书 interactive 卡片 JSON（schema 2.0）。

与 ui_card_templates.py 共享同一套结构化 card 数据（compare/rank/stats/timeline），
只是渲染目标不同：那边产 A2UI envelope（web 用 @a2ui/react），这边产飞书卡片 JSON。
ui_card 工具按渠道选用哪套模板（web/repl→A2UI，lark→飞书卡片）。

飞书卡片元素选型：以 markdown element 为主（飞书卡片对 markdown 支持最稳，含表格/加粗/
列表），统计卡用 column_set 做大数字并排。返回 dict（卡片结构），由 lark 发送层 json.dumps。
"""
from __future__ import annotations

import re


def _text(v) -> str:
    """规整文本：还原模型可能误传的字面量 \\n 为真换行（与 A2UI 模板一致）。"""
    if not isinstance(v, str):
        v = str(v if v is not None else "")
    return v.replace("\\n", "\n")


def _md_hardbreak(text: str) -> str:
    """飞书 markdown：单 \\n 会被折叠成空格。把孤立单 \\n 转成硬换行 "  \\n"，保留 \\n\\n 作段落。"""
    return re.sub(r"(?<!\n)\n(?!\n)", "  \n", text)


def _card(title: str, elements: list[dict]) -> dict:
    """组装 schema 2.0 卡片：有标题走 header，否则首元素当标题。"""
    card: dict = {"schema": "2.0", "body": {"elements": elements}}
    if title:
        card["header"] = {
            "title": {"tag": "plain_text", "content": _text(title)},
            "template": "blue",
        }
    return card


def _md(content: str) -> dict:
    return {"tag": "markdown", "content": _md_hardbreak(_text(content))}


def _hr() -> dict:
    return {"tag": "hr"}


def _build_compare(card: dict) -> dict:
    """对比卡 → markdown 表格。

    格式自适应（按数据自动检测归一，与 ui_card_templates 一致）：
    - 标准新格式：columns 包含所有列名，rows:[{values:[v1,v2,...]}]，label 不用传
    - label 旧格式：columns 不含第一列名，rows:[{label, values:[v2,v3,...]}]
    - 模型混用法：columns 含所有列名，rows:[{label, values:[...]}]（label 作第一列值）

    核心保证：最终列数一致，数据行单元格数严格等于列数，杜绝列错位。
    """
    raw_cols = [_text(c) for c in (card.get("columns") or [])]
    raw_rows = card.get("rows") or []

    def _trim_trailing_empty(vals: list) -> list:
        i = len(vals)
        while i > 0 and (vals[i - 1] is None or (isinstance(vals[i - 1], str) and vals[i - 1].strip() == "")):
            i -= 1
        return vals[:i]

    label_rows = [r for r in raw_rows if isinstance(r, dict) and "label" in r]
    unlabeled_rows = [r for r in raw_rows if isinstance(r, dict) and "label" not in r]
    is_legacy = bool(label_rows) and not unlabeled_rows and all(
        len(_trim_trailing_empty(r.get("values") or [])) == len(raw_cols) for r in label_rows
    )

    if is_legacy:
        col_names = [""] + raw_cols
        n_cols = len(col_names)
        def row_values(row: dict) -> list[str]:
            return [_text(row.get("label", ""))] + [_text(v) for v in (row.get("values") or [])]
    else:
        col_names = list(raw_cols)
        n_cols = len(col_names)
        def row_values(row: dict) -> list[str]:
            vals = [_text(v) for v in (row.get("values") or [])]
            if "label" in row:
                vals = [_text(row.get("label", ""))] + vals[:n_cols - 1]
            return vals

    if n_cols == 0:
        return _card(card.get("title", "对比"), [])

    # 表头
    header_cells = col_names
    lines = ["| " + " | ".join(header_cells) + " |"]
    lines.append("| " + " | ".join(["---"] * n_cols) + " |")
    for row in raw_rows:
        if not isinstance(row, dict):
            continue
        vals = row_values(row)
        # 归一化：不足补空，多余截断
        if len(vals) < n_cols:
            vals = vals + [""] * (n_cols - len(vals))
        elif len(vals) > n_cols:
            vals = vals[:n_cols]
        cells = []
        for ci, v in enumerate(vals):
            cell_text = v.replace("\n", " ")
            if ci == 0 and cell_text:
                cell_text = f"**{cell_text}**"
            cells.append(cell_text)
        lines.append("| " + " | ".join(cells) + " |")
    return _card(card.get("title", "对比"), [{"tag": "markdown", "content": "\n".join(lines)}])


def _build_rank(card: dict) -> dict:
    """排行卡 → markdown 编号列表。card = {title, subtitle?, items:[{name, score?, desc?}]}"""
    items = card.get("items") or []
    elements: list[dict] = []
    if card.get("subtitle"):
        elements.append(_md(f"_{_text(card['subtitle'])}_"))
        elements.append(_hr())
    blocks = []
    for i, it in enumerate(items):
        name = _text(it.get("name", ""))
        score = it.get("score")
        head = f"**{i + 1}. {name}**"
        if score not in (None, ""):
            head += f"  `{_text(score)}`"
        block = head
        if it.get("desc"):
            block += "\n" + _text(it["desc"])
        blocks.append(block)
    elements.append(_md("\n\n".join(blocks)))
    return _card(card.get("title", "排行"), elements)


def _build_stats(card: dict) -> dict:
    """统计卡 → column_set 大数字并排。card = {title?, metrics:[{label, value, trend?}]}"""
    metrics = card.get("metrics") or []
    columns = []
    for m in metrics:
        parts = [f"<font color='grey'>{_text(m.get('label', ''))}</font>",
                 f"**{_text(m.get('value', ''))}**"]
        if m.get("trend"):
            parts.append(f"<font color='grey'>{_text(m['trend'])}</font>")
        columns.append({
            "tag": "column",
            "width": "weighted",
            "weight": 1,
            "vertical_align": "top",
            "elements": [{"tag": "markdown", "content": "\n".join(parts)}],
        })
    element = {"tag": "column_set", "flex_mode": "stretch", "columns": columns}
    return _card(card.get("title", "统计"), [element])


def _extract_body_items(node: dict) -> list[str] | None:
    """从节点抽取分点文本；复用 ui_card_templates 的实现，保持一致性。"""
    from ethan.tools.builtin.ui_card_templates import _extract_body_items as _ui_extract
    return _ui_extract(node)


def _build_timeline(card: dict) -> dict:
    """时间轴卡 → markdown 分节（每节点带 emoji 圆点）。card = {title, nodes:[{title, body?, items?}]}

    body/items 支持 str | list[str]：list 转成 `- xxx` 飞书 md 无序列表，
    单条时直接当段落，与旧视觉完全一致。
    """
    nodes = card.get("nodes") or []
    blocks = []
    for n in nodes:
        block = f"🔹 **{_text(n.get('title', ''))}**"
        items = _extract_body_items(n)
        if items:
            if len(items) == 1:
                block += "\n" + items[0]
            else:
                bullets = "\n".join(f"- {t}" for t in items)
                block += "\n" + bullets
        blocks.append(block)
    return _card(card.get("title", "时间轴"), [_md(_md_hardbreak("\n\n".join(blocks)))])


_BUILDERS = {
    "compare": _build_compare,
    "rank": _build_rank,
    "stats": _build_stats,
    "timeline": _build_timeline,
}


def supported_types() -> list[str]:
    return list(_BUILDERS)


def build_lark_card(card: dict) -> dict:
    """按 card['type'] 路由到飞书卡片模板，返回卡片 dict。type 不支持时抛 ValueError。"""
    if not isinstance(card, dict):
        raise ValueError("card 必须是对象")
    t = card.get("type")
    builder = _BUILDERS.get(t)
    if builder is None:
        raise ValueError(f"不支持的 card.type: {t!r}，支持 {supported_types()}")
    return builder(card)
