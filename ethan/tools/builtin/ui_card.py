"""ui_card 工具：把结构化信息以 A2UI 卡片形式展示给用户，而非纯文字分点。

参考 A2UI v0.9.1 协议（https://a2ui.org/specification/v0.9.1-a2ui/）。工具参数就是
一组 A2UI envelope（createSurface / updateComponents / updateDataModel / deleteSurface），
工具做轻量校验后把它们放进 ToolResult.ui 透传给前端（web 用 @a2ui/react 渲染、
REPL 走文本降级），并给模型回一句简短 ack——不把整坨 JSON 回灌进上下文。

格式不熟先 `skill_read('ui-card')` 看协议要点和示例。
"""
from __future__ import annotations

from ethan.tools.base import BaseTool, ToolResult

_ENVELOPE_KEYS = {"createSurface", "updateComponents", "updateDataModel", "deleteSurface"}


class UiCardTool(BaseTool):
    fast_path = False  # 按需经 find_tools 激活，省 fast 档 prompt
    cacheable = False
    no_compress = True
    side_effect = False
    name = "ui_card"
    description = (
        "把结构化信息（对比、状态、进度、列表、表单等）渲染成 A2UI 卡片展示给用户，"
        "比纯文字分点更直观。参数 messages 是 A2UI v0.9.1 的 envelope 数组。"
        "不确定格式先用 skill_read('ui-card') 看协议要点与示例。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "messages": {
                "type": "array",
                "description": (
                    "A2UI envelope 数组，按顺序处理。每条恰含一个键："
                    "createSurface(初始化 surface) / updateComponents(组件邻接表，须含 id='root') / "
                    "updateDataModel(数据) / deleteSurface。详见 skill_read('ui-card')。"
                ),
                "items": {"type": "object"},
            },
        },
        "required": ["messages"],
    }

    async def run(self, messages: list | None = None) -> ToolResult:
        envelopes = messages or []
        if not isinstance(envelopes, list) or not envelopes:
            return ToolResult(
                tool_call_id="",
                content="ui_card 失败：messages 必须是非空的 A2UI envelope 数组。先 skill_read('ui-card') 看格式。",
                is_error=True,
            )

        errors: list[str] = []
        surfaces: list[str] = []
        has_root = False
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
                if any(isinstance(c, dict) and c.get("id") == "root" for c in comps):
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

        surface_note = f"（surface: {', '.join(surfaces)}）" if surfaces else ""
        return ToolResult(
            tool_call_id="",
            content=f"已为用户渲染 A2UI 卡片{surface_note}，共 {len(envelopes)} 条消息。卡片已直接展示在界面上，无需再用文字复述卡片内容。",
            ui=envelopes,
        )
