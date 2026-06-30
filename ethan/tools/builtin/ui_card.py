"""ui_card 工具：把结构化信息以 A2UI 卡片形式展示给用户，而非纯文字分点。

两条路径：
1. card 参数（推荐）：高频卡片（对比/排行/统计/时间轴）走固定模板，模型只填结构化
   数据，样式由 ui_card_templates.py 的后端模板保证——避免模型实时拼原始 A2UI 时反复
   翻车（漏 child、字面量 \\n、Card 当徽章）。
2. messages 参数（高级）：自定义场景才用，手写 A2UI v0.9.1 envelope，工具做连通性校验。

参考 A2UI v0.9.1 协议（https://a2ui.org/specification/v0.9.1-a2ui/）。校验后放进
ToolResult.ui 透传前端（web 用 @a2ui/react、REPL 走文本降级），给模型只回简短 ack。
格式不熟先 `skill_read('ui-card')`。
"""
from __future__ import annotations

from ethan.tools.base import BaseTool, ToolResult

_ENVELOPE_KEYS = {"createSurface", "updateComponents", "updateDataModel", "deleteSurface"}

# 容器组件的子引用字段：用于从 root 遍历组件树做连通性检查
_CHILD_KEY = "child"        # 单个：Card / Button
_CHILDREN_KEY = "children"  # 数组或模板对象：Row / Column / List / Timeline


def _child_ids(comp: dict) -> list[str]:
    """提取一个组件引用的所有子组件 id（含模板对象的 componentId）。"""
    ids: list[str] = []
    ch = comp.get(_CHILD_KEY)
    if isinstance(ch, str):
        ids.append(ch)
    children = comp.get(_CHILDREN_KEY)
    if isinstance(children, list):
        for c in children:
            if isinstance(c, str):
                ids.append(c)
            elif isinstance(c, dict) and isinstance(c.get("id"), str):
                ids.append(c["id"])
    elif isinstance(children, dict) and isinstance(children.get("componentId"), str):
        ids.append(children["componentId"])  # 模板列表
    return ids


def _find_orphans(comp_index: dict[str, dict]) -> list[str]:
    """从 root BFS，返回 root 触达不到的组件 id（孤儿）。无 root 或全连通返回 []。"""
    if "root" not in comp_index:
        return []
    seen = {"root"}
    stack = ["root"]
    while stack:
        cur = comp_index.get(stack.pop())
        if not cur:
            continue
        for cid in _child_ids(cur):
            if cid not in seen and cid in comp_index:
                seen.add(cid)
                stack.append(cid)
    return [cid for cid in comp_index if cid not in seen]



class UiCardTool(BaseTool):
    fast_path = False  # 按需经 find_tools 激活，省 fast 档 prompt
    cacheable = False
    no_compress = True
    side_effect = False
    name = "ui_card"

    def __init__(self, channel: str = "web"):
        # 渠道决定 card 路径的渲染目标：web/repl → A2UI envelope；lark → 飞书 interactive 卡片。
        # 二者共享同一套结构化 card 数据，只是末端协议不同（见 ui_card_templates / lark_card_templates）。
        self._channel = channel

    description = (
        "把结构化信息渲染成 A2UI 卡片展示给用户，比纯文字分点更直观。\n"
        "优先用 card 参数（固定模板，样式稳定）：对比/排行/统计/时间轴这几类高频卡片，"
        "只需按 type 填结构化数据，无需懂 A2UI 协议。type 取值：\n"
        "- compare（对比表格）：{title, columns:[名1,名2], rows:[{label, values:[v1,v2]}]}\n"
        "- rank（排行榜）：{title, subtitle?, items:[{name, score?, desc?}]}（序号自动生成，别自己加）\n"
        "- stats（统计指标）：{title?, metrics:[{label, value, trend?}]}\n"
        "- timeline（时间轴/行程/进度）：{title, nodes:[{title, body?}]}\n"
        "文本里换行用真换行，别写反斜杠n。\n"
        "仅当用户明确要「自定义/更花哨」的卡片、上述模板不够用时，才改用 messages 参数手写 "
        "A2UI v0.9.1 envelope（先 skill_read('ui-card') 看协议）。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "card": {
                "type": "object",
                "description": (
                    "固定模板卡片（推荐）。必含 type（compare/rank/stats/timeline），"
                    "其余字段见工具说明。样式由后端保证，模型只填数据。"
                ),
            },
            "messages": {
                "type": "array",
                "description": (
                    "【高级】自定义 A2UI envelope 数组，仅当固定模板不够用时才用。"
                    "每条恰含一个键：createSurface / updateComponents(须含 id='root') / "
                    "updateDataModel / deleteSurface。详见 skill_read('ui-card')。"
                ),
                "items": {"type": "object"},
            },
        },
    }

    async def run(self, card: dict | None = None, messages: list | None = None) -> ToolResult:
        # 优先走固定模板（card）：样式稳定，模型只填结构化数据。
        # 按渠道选渲染目标：lark → 飞书卡片 JSON；web/repl → A2UI envelope。
        if card:
            if self._channel == "lark":
                from ethan.tools.builtin.lark_card_templates import build_lark_card
                try:
                    lark_card = build_lark_card(card)
                except ValueError as e:
                    return ToolResult(
                        tool_call_id="",
                        content=f"ui_card 模板失败：{e}",
                        is_error=True,
                    )
                return ToolResult(
                    tool_call_id="",
                    content=f"已为用户渲染 {card.get('type')} 卡片。卡片已直接展示在界面上，无需再用文字复述卡片内容。",
                    ui=[{"lark_card": lark_card}],
                )
            from ethan.tools.builtin.ui_card_templates import build_card
            try:
                envelopes = build_card(card)
            except ValueError as e:
                return ToolResult(
                    tool_call_id="",
                    content=f"ui_card 模板失败：{e}",
                    is_error=True,
                )
            return ToolResult(
                tool_call_id="",
                content=f"已为用户渲染 {card.get('type')} 卡片。卡片已直接展示在界面上，无需再用文字复述卡片内容。",
                ui=envelopes,
            )

        # messages（裸 A2UI）：飞书卡片体系与 A2UI 协议差异大，不做硬翻译，提示改用 card。
        if self._channel == "lark":
            return ToolResult(
                tool_call_id="",
                content="飞书渠道暂不支持自定义 A2UI（messages），请改用 card 参数（compare/rank/stats/timeline 固定模板）。",
                is_error=True,
            )

        envelopes = messages or []
        if not isinstance(envelopes, list) or not envelopes:
            return ToolResult(
                tool_call_id="",
                content="ui_card 失败：请用 card 参数（推荐，填 type+数据），或 messages 传 A2UI envelope 数组。先 skill_read('ui-card') 看格式。",
                is_error=True,
            )

        errors: list[str] = []
        surfaces: list[str] = []
        has_root = False
        comp_index: dict[str, dict] = {}  # id → 组件，用于连通性检查
        for i, env in enumerate(envelopes):
            if not isinstance(env, dict):
                errors.append(f"#{i} 不是对象")
                continue
            kind_keys = _ENVELOPE_KEYS & set(env.keys())
            if len(kind_keys) != 1:
                errors.append(f"#{i} 须恰含一个 envelope 键（{'/'.join(sorted(_ENVELOPE_KEYS))}），实得 {sorted(set(env.keys()) - {'version'})}")
                continue
            kind = next(iter(kind_keys))
            body = env.get(kind) or {}
            sid = body.get("surfaceId") if isinstance(body, dict) else None
            if kind == "createSurface" and sid:
                surfaces.append(sid)
            if kind == "updateComponents" and isinstance(body, dict):
                comps = body.get("components") or []
                for c in comps:
                    if isinstance(c, dict) and c.get("id"):
                        comp_index[c["id"]] = c
                        if c["id"] == "root":
                            has_root = True

        if errors:
            return ToolResult(
                tool_call_id="",
                content="ui_card 校验未通过：\n" + "\n".join(errors) + "\n请修正后重试，或 skill_read('ui-card') 看示例。",
                is_error=True,
            )
        if not has_root:
            return ToolResult(
                tool_call_id="",
                content="ui_card 校验未通过：updateComponents 里必须有一个 id='root' 的根组件。skill_read('ui-card') 看示例。",
                is_error=True,
            )

        # 连通性检查：从 root BFS，发现 root 触达不到的孤儿组件 → 报错退回让模型修
        orphans = _find_orphans(comp_index)
        if orphans:
            return ToolResult(
                tool_call_id="",
                content=(
                    f"ui_card 校验未通过：组件 {orphans} 没有被 root 引用到（孤儿）。"
                    "容器要用 child（Card）或 children（Row/Column/List/Timeline）把它们连进树里。"
                    "skill_read('ui-card') 看示例。"
                ),
                is_error=True,
            )

        surface_note = f"（surface: {', '.join(surfaces)}）" if surfaces else ""
        return ToolResult(
            tool_call_id="",
            content=f"已为用户渲染 A2UI 卡片{surface_note}，共 {len(envelopes)} 条消息。卡片已直接展示在界面上，无需再用文字复述卡片内容。",
            ui=envelopes,
        )
