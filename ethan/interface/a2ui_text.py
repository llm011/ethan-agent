"""A2UI envelope → Rich 文本降级渲染（供 REPL / 终端使用）。

Web 端用 @a2ui/react 渲染 A2UI 卡片；终端没有 DOM，这里把同一组 envelope
按邻接表还原成组件树，渲染成 rich 的 Panel / 文本。只覆盖 basic catalog 常用子集，
不支持的组件优雅降级为占位文本——目标是「看得懂」而非像素级还原。

入口：render_a2ui(envelopes) -> rich.console.Group | None
"""
from __future__ import annotations

from typing import Any

from rich.console import Group
from rich.markdown import Markdown as RichMarkdown
from rich.panel import Panel
from rich.rule import Rule
from rich.text import Text


def _resolve(value: Any, data: dict) -> str:
    """把 DynamicString 解析成字符串：字面量、{path}、或 {call:...} 函数调用（尽力而为）。"""
    if value is None:
        return ""
    if isinstance(value, (str, int, float, bool)):
        return str(value)
    if isinstance(value, dict):
        if "path" in value:
            return _json_pointer(data, value["path"])
        if "call" in value:
            return _eval_call(value, data)
    return str(value)


def _json_pointer(data: dict, pointer: str) -> str:
    """最小 JSON Pointer 解析。绝对路径从根取；相对路径在模板作用域内对当前 item 取。"""
    if not pointer:
        return ""
    if not pointer.startswith("/"):
        # 相对路径：仅在模板作用域（_ItemScope）内有意义，对当前 item 的字段取值
        if isinstance(data, _ItemScope):
            item = data.item
            cur: Any = item
            for seg in pointer.strip("/").split("/"):
                if isinstance(cur, dict) and seg in cur:
                    cur = cur[seg]
                else:
                    return ""
            return "" if isinstance(cur, (dict, list)) else str(cur)
        return ""
    cur = data
    for seg in pointer.strip("/").split("/"):
        if isinstance(cur, dict) and seg in cur:
            cur = cur[seg]
        elif isinstance(cur, list) and seg.isdigit() and int(seg) < len(cur):
            cur = cur[int(seg)]
        else:
            return ""
    if isinstance(cur, (dict, list)):
        return ""
    return str(cur)


def _eval_call(spec: dict, data: dict) -> str:
    """支持最常用的 formatString/formatCurrency/formatNumber，其余回退取 value。"""
    call = spec.get("call")
    args = spec.get("args", {}) or {}
    if call == "formatString":
        tmpl = _resolve(args.get("value"), data)
        # 替换 ${/path} 插值
        import re
        def sub(m):
            inner = m.group(1).strip()
            if inner.startswith("/"):
                return _json_pointer(data, inner)
            return m.group(0)
        return re.sub(r"\$\{([^}]+)\}", sub, tmpl)
    if call in ("formatCurrency", "formatNumber"):
        raw = _resolve(args.get("value"), data)
        try:
            num = float(raw)
            s = f"{num:,.2f}".rstrip("0").rstrip(".") if call == "formatNumber" else f"{num:,.2f}"
            if call == "formatCurrency":
                cur = args.get("currency", "")
                return f"{cur} {s}".strip()
            return s
        except (ValueError, TypeError):
            return raw
    # 其它函数：尽力取 value
    return _resolve(args.get("value"), data)


# variant → markdown 前缀
_HEADING = {"h1": "# ", "h2": "## ", "h3": "### ", "h4": "#### ", "h5": "##### "}


def _render_component(cid: str, comps: dict, data: dict, seen: set) -> Any:
    """递归把单个组件渲染成 rich renderable。seen 防环。"""
    if cid in seen:
        return Text(f"[…循环引用 {cid}]", style="dim red")
    seen = seen | {cid}
    comp = comps.get(cid)
    if comp is None:
        return Text(f"[缺失组件 {cid}]", style="dim")

    ctype = comp.get("component", "")

    if ctype == "Text":
        txt = _resolve(comp.get("text"), data)
        variant = comp.get("variant", "body")
        if variant in _HEADING or any(m in txt for m in ("**", "`", "- ", "#")):
            return RichMarkdown(_HEADING.get(variant, "") + txt)
        if variant == "caption":
            return Text(txt, style="dim")
        return Text(txt)

    if ctype == "Icon":
        return Text(f"[{comp.get('name', 'icon') if isinstance(comp.get('name'), str) else _resolve(comp.get('name'), data)}]", style="dim cyan")

    if ctype in ("Image", "Video", "AudioPlayer"):
        url = _resolve(comp.get("url"), data)
        label = {"Image": "🖼", "Video": "🎬", "AudioPlayer": "🔊"}[ctype]
        return Text(f"{label} {url}", style="dim blue underline")

    if ctype == "Divider":
        return Rule(style="dim")

    if ctype in ("Column", "List"):
        return Group(*_render_children(comp, comps, data, seen))

    if ctype == "Timeline":
        # 时间轴：每个节点前缀 │ ● 模拟连线 + 圆点
        out = []
        for child in _render_children(comp, comps, data, seen):
            out.append(Group(Text("│ ●", style="cyan"), child, Text("│", style="dim")))
        return Group(*out)

    if ctype == "Row":
        # 终端里 Row 也按行堆叠（不做真正横排），用 " · " 连接纯文本子项更紧凑
        children = _render_children(comp, comps, data, seen)
        return Group(*children)

    if ctype == "Card":
        child_id = comp.get("child")
        inner = _render_component(child_id, comps, data, seen) if child_id else Text("")
        return Panel(inner, border_style="dim", padding=(0, 1))

    if ctype == "Button":
        label_id = comp.get("child")
        label = _resolve(comps.get(label_id, {}).get("text"), data) if label_id else ""
        return Text(f"[ {label or '按钮'} ]", style="bold")

    if ctype == "CheckBox":
        label = _resolve(comp.get("label"), data)
        checked = _resolve(comp.get("value"), data) in ("True", "true", "1")
        return Text(f"{'[x]' if checked else '[ ]'} {label}")

    if ctype == "TextField":
        label = _resolve(comp.get("label"), data)
        val = _resolve(comp.get("value"), data)
        return Text(f"{label}: {val or '___'}", style="dim")

    if ctype == "Tabs":
        return Group(*_render_children(comp, comps, data, seen))

    # 未知组件：降级展示类型 + 可能的文本
    txt = _resolve(comp.get("text") or comp.get("label"), data)
    return Text(f"[{ctype}]{(' ' + txt) if txt else ''}", style="dim")


def _render_children(comp: dict, comps: dict, data: dict, seen: set) -> list:
    """处理 children（id 数组 或 模板 {path, componentId}）和 child（单个）。"""
    out = []
    children = comp.get("children")
    if isinstance(children, list):
        for ch in children:
            out.append(_render_component(ch, comps, data, seen))
    elif isinstance(children, dict) and "componentId" in children:
        # 模板列表：对 path 指向的数组每项渲染一次模板（相对路径在 _ItemScope 内解析）
        tpl = children["componentId"]
        path = children.get("path", "")
        for item in _get_list(data, path):
            out.append(_render_component(tpl, comps, _ItemScope(data, item), seen))
    child = comp.get("child")
    if child:
        out.append(_render_component(child, comps, data, seen))
    return out or [Text("")]


def _get_list(data: dict, pointer: str) -> list:
    if not pointer.startswith("/"):
        return []
    cur: Any = data
    for seg in pointer.strip("/").split("/"):
        if isinstance(cur, dict) and seg in cur:
            cur = cur[seg]
        else:
            return []
    return cur if isinstance(cur, list) else []


class _ItemScope(dict):
    """模板作用域：相对路径解析到当前 item，绝对路径仍走根数据。"""
    def __init__(self, root: dict, item: Any):
        super().__init__(root)
        self.item = item


def render_a2ui(envelopes: list) -> Group | None:
    """把一组 A2UI envelope 渲染成 rich Group（多个 surface 纵向堆叠）。无可渲染内容返回 None。"""
    if not envelopes or not isinstance(envelopes, list):
        return None

    # 按 surfaceId 聚合组件与数据
    surfaces: dict[str, dict] = {}
    order: list[str] = []
    for env in envelopes:
        if not isinstance(env, dict):
            continue
        if "createSurface" in env:
            sid = (env["createSurface"] or {}).get("surfaceId", "")
            if sid and sid not in surfaces:
                surfaces[sid] = {"comps": {}, "data": {}}
                order.append(sid)
        elif "updateComponents" in env:
            body = env["updateComponents"] or {}
            sid = body.get("surfaceId", "")
            s = surfaces.setdefault(sid, {"comps": {}, "data": {}})
            if sid not in order:
                order.append(sid)
            for c in body.get("components", []) or []:
                if isinstance(c, dict) and c.get("id"):
                    s["comps"][c["id"]] = c
        elif "updateDataModel" in env:
            body = env["updateDataModel"] or {}
            sid = body.get("surfaceId", "")
            s = surfaces.setdefault(sid, {"comps": {}, "data": {}})
            if sid not in order:
                order.append(sid)
            path = body.get("path", "/") or "/"
            value = body.get("value")
            if path in ("/", ""):
                if isinstance(value, dict):
                    s["data"] = value
            else:
                _set_pointer(s["data"], path, value)

    blocks = []
    for sid in order:
        s = surfaces.get(sid, {})
        comps = s.get("comps", {})
        if "root" not in comps:
            continue
        blocks.append(_render_component("root", comps, s.get("data", {}), set()))
    if not blocks:
        return None
    return Group(*blocks)


def _set_pointer(data: dict, pointer: str, value: Any) -> None:
    segs = pointer.strip("/").split("/")
    cur = data
    for seg in segs[:-1]:
        cur = cur.setdefault(seg, {})
        if not isinstance(cur, dict):
            return
    if segs:
        cur[segs[-1]] = value
