"""交互式 /config 编辑器 —— 仿 Claude Code 的 settings 面板。

操作：
  ↑/↓ 或 k/j      选择项
  空格 / 回车      bool 切换 · choice 循环 · str/int 进入编辑
  回车（编辑中）   确认
  Esc（编辑中）    取消编辑
  q / Esc          退出
"""
from __future__ import annotations

from prompt_toolkit.application import Application
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.document import Document
from prompt_toolkit.filters import Condition
from prompt_toolkit.formatted_text import FormattedText
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import (
    ConditionalContainer,
    FormattedTextControl,
    HSplit,
    Layout,
    Window,
)
from prompt_toolkit.layout.controls import BufferControl
from prompt_toolkit.layout.dimension import D
from prompt_toolkit.styles import Style

from ethan.core.config_schema import (
    EDITABLE_FIELDS,
    coerce,
    get_field,
    get_value,
    set_value,
)

_STYLE = Style.from_dict({
    "title": "bold cyan",
    "hint": "dim",
    "arrow": "bold cyan",
    "sel": "bold",
    "von": "green bold",
    "voff": "dim",
    "vdim": "dim italic",
    "editlabel": "bold",
    "msg": "yellow bold",
    "editrow": "bg:#1a1a2e #ffffff",
})


async def run_config_editor(config) -> bool:
    """启动全屏配置编辑器。返回 True 表示有改动需要保存。"""
    # 用 list 包裹可变状态，供闭包修改
    sel = [0]
    editing = [False]
    edit_path: list[str | None] = [None]
    saved = [False]
    msg = [""]

    # ---- 编辑模式的 buffer ----
    edit_kb = KeyBindings()

    edit_buffer = Buffer(multiline=False)

    @edit_kb.add("enter")
    def _confirm(event):
        path = edit_path[0]
        field = get_field(path)
        text = edit_buffer.text.strip()
        try:
            new_val = coerce(field, text)
            old_val = get_value(config, path)
            set_value(config, path, new_val)
            saved[0] = True
            msg[0] = f"✓ {field.label}: {_short(old_val)} → {_short(new_val)}"
        except ValueError as e:
            msg[0] = f"✗ {e}"
        editing[0] = False
        edit_path[0] = None
        event.app.layout.focus(list_control)

    @edit_kb.add("escape")
    def _cancel(event):
        msg[0] = "已取消"
        editing[0] = False
        edit_path[0] = None
        event.app.layout.focus(list_control)

    # ---- 全局按键 ----
    kb = KeyBindings()
    not_editing = Condition(lambda: not editing[0])

    @kb.add("up", filter=not_editing)
    @kb.add("k", filter=not_editing)
    def _(event):
        if sel[0] > 0:
            sel[0] -= 1
        msg[0] = ""

    @kb.add("down", filter=not_editing)
    @kb.add("j", filter=not_editing)
    def _(event):
        if sel[0] < len(EDITABLE_FIELDS) - 1:
            sel[0] += 1
        msg[0] = ""

    def _activate(event):
        field = EDITABLE_FIELDS[sel[0]]
        if field.kind == "bool":
            old = get_value(config, field.path)
            set_value(config, field.path, not old)
            saved[0] = True
            msg[0] = f"✓ {field.label}: {_short(old)} → {_short(not old)}"
        elif field.kind == "choice":
            cur = get_value(config, field.path)
            idx = field.choices.index(cur) if cur in field.choices else -1
            nxt = field.choices[(idx + 1) % len(field.choices)]
            set_value(config, field.path, nxt)
            saved[0] = True
            msg[0] = f"✓ {field.label}: {_short(cur)} → {_short(nxt)}"
        else:
            # str/int → 进入编辑
            edit_path[0] = field.path
            cur_val = get_value(config, field.path)
            edit_buffer.reset(Document(
                text=str(cur_val),
                cursor_position=len(str(cur_val)),
            ))
            editing[0] = True
            msg[0] = ""
            event.app.layout.focus(edit_control)

    @kb.add("space", filter=not_editing)
    @kb.add("enter", filter=not_editing)
    def _(event):
        _activate(event)

    @kb.add("q", filter=not_editing)
    @kb.add("escape", filter=not_editing)
    def _(event):
        event.app.exit()

    # ---- 渲染 ----
    def _value_tokens(field, value):
        if field.kind == "bool":
            return [("class:von", "✓ on")] if value else [("class:voff", "✗ off")]
        if field.kind == "choice":
            return [("", str(value) + "  "),
                    ("class:vdim", f"({'/'.join(field.choices)})")]
        if value == "" or value is None:
            return [("class:vdim", "(空)")]
        return [("", str(value))]

    def _render_list():
        toks = []
        toks.append(("class:title", "  ⚙  Settings\n"))
        toks.append(("class:hint", "  ↑↓ 选择 · 空格/回车 切换或编辑 · q 退出\n\n"))
        for i, field in enumerate(EDITABLE_FIELDS):
            is_sel = i == sel[0]
            toks.append(("class:arrow" if is_sel else "",
                         "▶ " if is_sel else "  "))
            toks.append(("class:sel" if is_sel else "", field.label))
            pad = max(2, 34 - len(field.label))
            toks.append(("", " " * pad))
            toks.extend(_value_tokens(field, get_value(config, field.path)))
            if is_sel and field.desc:
                toks.append(("", "   "))
                toks.append(("class:hint", f"# {field.desc}"))
            toks.append(("", "\n"))
        return FormattedText(toks)

    list_control = FormattedTextControl(text=_render_list, focusable=True)
    edit_control = BufferControl(buffer=edit_buffer, key_bindings=edit_kb)

    def _edit_label():
        if editing[0] and edit_path[0]:
            field = get_field(edit_path[0])
            return FormattedText([
                ("class:editlabel", f"  {field.label}: "),
                ("class:hint", "（回车确认 · Esc 取消）"),
            ])
        return FormattedText([])

    layout = Layout(
        HSplit([
            Window(content=list_control),
            ConditionalContainer(
                Window(content=FormattedTextControl(text=_edit_label),
                       height=D.exact(1)),
                filter=Condition(lambda: editing[0]),
            ),
            ConditionalContainer(
                Window(content=edit_control, height=D.exact(1),
                       style="class:editrow"),
                filter=Condition(lambda: editing[0]),
            ),
            Window(content=FormattedTextControl(text=lambda: msg[0]),
                   height=D.exact(1)),
        ]),
    )
    layout.focus(list_control)

    app = Application(
        layout=layout,
        key_bindings=kb,
        style=_STYLE,
        full_screen=True,
    )
    await app.run_async()
    return saved[0]


def _short(val) -> str:
    if isinstance(val, bool):
        return "on" if val else "off"
    if val is None or val == "":
        return "(空)"
    return str(val)
