"""高频卡片 → 飞书 interactive 卡片 JSON（schema 2.0）。

与 ui_card_templates.py 共享同一套结构化 card 数据（compare/rank/stats/timeline），
只是渲染目标不同：那边产 A2UI envelope（web 用 @a2ui/react），这边产飞书卡片 JSON。
ui_card 工具按渠道选用哪套模板（web/repl→A2UI，lark→飞书卡片）。

飞书卡片元素选型：以 markdown element 为主（飞书卡片对 markdown 支持最稳，含表格/加粗/
列表），统计卡用 column_set 做大数字并排。返回 dict（卡片结构），由 lark 发送层 json.dumps。
"""
from __future__ import annotations


def _text(v) -> str:
    """规整文本：还原模型可能误传的字面量 \\n 为真换行（与 A2UI 模板一致）。"""
    if not isinstance(v, str):
        v = str(v if v is not None else "")
    return v.replace("\\n", "\n")


def _md_hardbreak(text: str) -> str:
    """飞书 markdown：单 \n 会被折叠成空格。把孤立单 \n 转成硬换行 "  \n"，保留 \n\n 作段落。"""
    import re
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
    """对比卡 → markdown 表格。card = {title, columns:[名1,名2], rows:[{label, values:[v1,v2]}]}"""
    cols = card.get("columns") or []
    rows = card.get("rows") or []
    # 表头：首列空（指标列）+ 各对比列名
    header_cells = [""] + [_text(c) for c in cols]
    lines = ["| " + " | ".join(header_cells) + " |"]
    lines.append("| " + " | ".join(["---"] * len(header_cells)) + " |")
    for row in rows:
        label = _text(row.get("label", ""))
        values = row.get("values") or []
        cells = [f"**{label}**"]
        for ci in range(len(cols)):
            v = _text(values[ci]) if ci < len(values) else ""
            # 表格单元格内不能有换行，折叠成空格
            cells.append(v.replace("\n", " "))
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
    return _card(card.get("title", ""), [element])


def _build_timeline(card: dict) -> dict:
    """时间轴卡 → markdown 分节（每节点带 emoji 圆点）。card = {title, nodes:[{title, body?}]}"""
    nodes = card.get("nodes") or []
    blocks = []
    for n in nodes:
        block = f"🔹 **{_text(n.get('title', ''))}**"
        if n.get("body"):
            block += "\n" + _text(n["body"])
        blocks.append(block)
    return _card(card.get("title", "时间轴"), [_md("\n\n".join(blocks))])


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
