"""高频卡片的固定模板：后端按结构化数据生成干净的 A2UI v0.9.1 envelope。

为什么走模板而非让模型实时拼原始 A2UI：模型反复产出「结构合法但样式翻车」的输出
——漏写 root 的 child、文本写成字面量 \\n、拿 Card 当序号徽章。模板把结构定死，
模型只填 typed 数据，这类问题一次性消掉。长尾/创意卡片仍可走 ui_card 的 messages 原始路径。

入口：build_card(card: dict) -> list[envelope]，按 card["type"] 路由到具体模板。
"""
from __future__ import annotations

CATALOG = "https://a2ui.org/specification/v0_9_1/catalogs/basic/catalog.json"


def _surface(sid: str) -> dict:
    return {"version": "v0.9.1", "createSurface": {"surfaceId": sid, "catalogId": CATALOG}}


def _components(sid: str, comps: list[dict]) -> dict:
    return {"version": "v0.9.1", "updateComponents": {"surfaceId": sid, "components": comps}}


def _text(v: str) -> str:
    """规整文本：把模型可能误传的字面量 \\n（反斜杠+n）还原成真换行，避免 markdown 不换行。"""
    if not isinstance(v, str):
        v = str(v)
    return v.replace("\\n", "\n")


def _build_compare(card: dict) -> list[dict]:
    """对比卡（表格式）：title + 列头行 + 每个指标一行（带行分隔线）。
    card = {title, columns:[名1,名2,...], rows:[{label, values:[v1,v2,...]}]}
    """
    sid = "compare"
    cols = card.get("columns") or []
    rows = card.get("rows") or []
    comps: list[dict] = [
        {"id": "root", "component": "Card", "child": "col"},
    ]
    col_children = ["title", "div0", "head"]
    comps.append({"id": "title", "component": "Text", "text": _text(card.get("title", "对比")), "variant": "h3"})
    comps.append({"id": "div0", "component": "Divider"})

    # 列头行：第一格空（指标列），其余是列名
    head_children = ["h-label"]
    comps.append({"id": "h-label", "component": "Text", "text": "", "weight": 1, "variant": "caption"})
    for ci, cname in enumerate(cols):
        hid = f"h-{ci}"
        head_children.append(hid)
        comps.append({"id": hid, "component": "Text", "text": _text(cname), "weight": 2, "variant": "h5"})
    comps.append({"id": "head", "component": "Row", "align": "start", "children": head_children})

    # 数据行：label + 各列值，行之间插分隔线
    for ri, row in enumerate(rows):
        rid = f"r-{ri}"
        row_children = [f"{rid}-label"]
        comps.append({"id": f"{rid}-label", "component": "Text", "text": _text(row.get("label", "")), "weight": 1, "variant": "h5"})
        values = row.get("values") or []
        for ci in range(len(cols)):
            vid = f"{rid}-c{ci}"
            row_children.append(vid)
            val = values[ci] if ci < len(values) else ""
            comps.append({"id": vid, "component": "Text", "text": _text(val), "weight": 2})
        comps.append({"id": rid, "component": "Row", "align": "start", "children": row_children})
        col_children.append(f"{rid}-div")
        comps.append({"id": f"{rid}-div", "component": "Divider"})
        col_children.append(rid)

    comps.append({"id": "col", "component": "Column", "children": col_children})
    return [_surface(sid), _components(sid, comps)]


def _build_rank(card: dict) -> list[dict]:
    """排行卡：title + 可选 desc + 每项一行（序号纯文本不套 Card + 名称 + 可选 score + 可选 desc）。
    card = {title, subtitle?, items:[{name, score?, desc?}]}
    序号由后端按下标生成，模型不用管。
    """
    sid = "rank"
    items = card.get("items") or []
    comps: list[dict] = [{"id": "root", "component": "Card", "child": "col"}]
    col_children = ["title"]
    comps.append({"id": "title", "component": "Text", "text": _text(card.get("title", "排行")), "variant": "h3"})
    if card.get("subtitle"):
        col_children.append("subtitle")
        comps.append({"id": "subtitle", "component": "Text", "text": _text(card["subtitle"]), "variant": "caption"})
    col_children.append("div0")
    comps.append({"id": "div0", "component": "Divider"})

    for i, it in enumerate(items):
        rid = f"i-{i}"
        # 行：序号(徽章样式，前端 catalog 渲染成带底色的圆) + 内容列 + 可选分数
        row_children = [f"{rid}-num", f"{rid}-body"]
        comps.append({"id": f"{rid}-num", "component": "Text", "text": f"{i + 1}", "variant": "rankBadge"})
        # 内容列：名称行 + 可选描述
        body_children = [f"{rid}-name"]
        name_text = _text(it.get("name", ""))
        comps.append({"id": f"{rid}-name", "component": "Text", "text": name_text, "variant": "h5", "weight": 1})
        if it.get("desc"):
            body_children.append(f"{rid}-desc")
            comps.append({"id": f"{rid}-desc", "component": "Text", "text": _text(it["desc"]), "variant": "caption"})
        comps.append({"id": f"{rid}-body", "component": "Column", "weight": 1, "children": body_children})
        if it.get("score") not in (None, ""):
            row_children.append(f"{rid}-score")
            comps.append({"id": f"{rid}-score", "component": "Text", "text": _text(it["score"]), "variant": "caption"})
        comps.append({"id": rid, "component": "Row", "align": "center", "children": row_children})
        col_children.append(rid)

    comps.append({"id": "col", "component": "Column", "children": col_children})
    return [_surface(sid), _components(sid, comps)]


def _build_stats(card: dict) -> list[dict]:
    """统计卡：title? + 一组指标（横向并排，每个 = 标签 + 大数值 + 可选趋势）。
    card = {title?, metrics:[{label, value, trend?}]}
    """
    sid = "stats"
    metrics = card.get("metrics") or []
    comps: list[dict] = [{"id": "root", "component": "Card", "child": "col"}]
    col_children: list[str] = []
    if card.get("title"):
        col_children += ["title", "div0"]
        comps.append({"id": "title", "component": "Text", "text": _text(card["title"]), "variant": "h3"})
        comps.append({"id": "div0", "component": "Divider"})

    row_children = []
    for i, m in enumerate(metrics):
        mid = f"m-{i}"
        row_children.append(mid)
        cell = [f"{mid}-label", f"{mid}-value"]
        comps.append({"id": f"{mid}-label", "component": "Text", "text": _text(m.get("label", "")), "variant": "caption"})
        comps.append({"id": f"{mid}-value", "component": "Text", "text": _text(m.get("value", "")), "variant": "h2"})
        if m.get("trend"):
            cell.append(f"{mid}-trend")
            comps.append({"id": f"{mid}-trend", "component": "Text", "text": _text(m["trend"]), "variant": "caption"})
        comps.append({"id": mid, "component": "Column", "weight": 1, "children": cell})
    col_children.append("row")
    comps.append({"id": "row", "component": "Row", "justify": "spaceBetween", "children": row_children})

    comps.append({"id": "col", "component": "Column", "children": col_children})
    return [_surface(sid), _components(sid, comps)]


def _build_timeline(card: dict) -> list[dict]:
    """时间轴卡：title + Timeline（每个节点 = 标题 + 可选正文）。
    card = {title, nodes:[{title, body?}]}
    """
    sid = "timeline"
    nodes = card.get("nodes") or []
    comps: list[dict] = [{"id": "root", "component": "Card", "child": "col"}]
    col_children = ["title", "tl"]
    comps.append({"id": "title", "component": "Text", "text": _text(card.get("title", "时间轴")), "variant": "h3"})

    node_ids = []
    for i, n in enumerate(nodes):
        nid = f"n-{i}"
        node_ids.append(nid)
        node_children = [f"{nid}-t"]
        comps.append({"id": f"{nid}-t", "component": "Text", "text": _text(n.get("title", "")), "variant": "h4"})
        if n.get("body"):
            node_children.append(f"{nid}-b")
            comps.append({"id": f"{nid}-b", "component": "Text", "text": _text(n["body"])})
        comps.append({"id": nid, "component": "Column", "children": node_children})
    comps.append({"id": "tl", "component": "Timeline", "children": node_ids})

    comps.append({"id": "col", "component": "Column", "children": col_children})
    return [_surface(sid), _components(sid, comps)]


_BUILDERS = {
    "compare": _build_compare,
    "rank": _build_rank,
    "stats": _build_stats,
    "timeline": _build_timeline,
}


def supported_types() -> list[str]:
    return list(_BUILDERS)


def build_card(card: dict) -> list[dict]:
    """按 card['type'] 路由到模板，返回 A2UI envelope 列表。type 不支持时抛 ValueError。"""
    if not isinstance(card, dict):
        raise ValueError("card 必须是对象")
    t = card.get("type")
    builder = _BUILDERS.get(t)
    if builder is None:
        raise ValueError(f"不支持的 card.type: {t!r}，支持 {supported_types()}")
    return builder(card)
