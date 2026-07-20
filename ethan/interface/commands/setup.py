"""setup 子命令：交互式引导安装 & 配置（设置、插件、渠道）。

命令：
  ethan setup                 打开交互式引导菜单（箭头上下选择，回车确认）
"""
from __future__ import annotations

import typer
from rich.console import Console

console = Console()
app = typer.Typer(help="交互式引导安装 & 配置", invoke_without_command=True)


# ── 插件注册表 ────────────────────────────────────────────────────────────────
PRESET_PLUGINS: list[dict] = [
    {
        "name": "legal-assistant",
        "label": "法律专家",
        "description": "案件研判、诉讼分析、合同审查",
        "install_type": "skill",
        "install_source": "legal",  # 内置别名，走 git clone
    },
    {
        "name": "companion-listen",
        "label": "陪伴倾听",
        "description": "心理咨询陪伴（苏念角色，情绪支持与心理画像）",
        "install_type": "builtin_skill",
        "install_source": "companion-listen",
    },
    {
        "name": "tavily",
        "label": "AI 搜索",
        "description": "Tavily AI 搜索引擎（需 API Key）",
        "install_type": "plugin",
        "install_source": "tavily",
    },
    {
        "name": "searxng",
        "label": "自建搜索",
        "description": "SearXNG 自建搜索实例",
        "install_type": "plugin",
        "install_source": "searxng",
    },
    {
        "name": "computer-use",
        "label": "桌面自动化",
        "description": "截图/鼠标/键盘操控（基于 cua-driver）",
        "install_type": "optional_dep",
        "install_source": "computer",
        "pip_packages": ["cua-computer"],
        "post_install_hint": (
            "还需安装 cua-driver 后台服务：\n"
            "  curl -fsSL https://raw.githubusercontent.com/trycua/cua/main/libs/cua-driver/scripts/install.sh | bash\n"
            "  cua-driver install   # 注册开机自启\n"
            "  cua-driver serve     # 或手动启动"
        ),
    },
    {
        "name": "lark-channel",
        "label": "飞书渠道依赖",
        "description": "安装 lark-oapi + lark-cli 并同步已配置的飞书应用（无需重新填 app 凭证）",
        "install_type": "lark_channel",
        "install_source": "lark-channel",
    },
    # 注：embedding-router 已内置（onnxruntime/tokenizers/numpy 已在 dependencies 里），
    # BGE 模型首次使用时自动下载，不再作为插件提供。
]


@app.callback(invoke_without_command=True)
def setup_main(ctx: typer.Context) -> None:
    """交互式引导菜单：设置、插件、渠道。"""
    if ctx.invoked_subcommand is not None:
        return

    import sys

    from ethan.core.config import CONFIG_DIR, get_config

    first_run = not (CONFIG_DIR / "config.yaml").exists()

    # 初始化（首次运行时创建目录、config、默认技能等）
    get_config()

    if first_run:
        console.print()
        console.print("[bold green]✓ 初始化完成[/bold green]")
        console.print()
        console.print(f"  数据目录  {CONFIG_DIR}")
        console.print(f"  配置文件  {CONFIG_DIR / 'config.yaml'}")
        console.print(f"  系统文件  {CONFIG_DIR / 'system/'}")
        console.print(f"  默认技能  {CONFIG_DIR / 'skills/'}")
        console.print()

    # 非交互环境（无 TTY：docker / CI / 管道）不打开交互菜单，仅做幂等初始化
    if not sys.stdin.isatty():
        return

    if first_run:
        console.print("[dim]运行 [bold]ethan setup[/bold] 可随时进入配置菜单。[/dim]")
    else:
        _run_interactive_menu()


# ── 箭头键选择器（基于 prompt_toolkit）──────────────────────────────────────

def _arrow_select(title: str, options: list[tuple[str, str]]) -> str | None:
    """箭头上下选择、回车确认的交互选择器。

    options: [(label, value), ...]
    返回选中的 value，Esc/q 返回 None。
    """
    import os

    os.system("clear" if os.name != "nt" else "cls")

    from prompt_toolkit.application import Application
    from prompt_toolkit.formatted_text import FormattedText
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.layout import HSplit, Layout, Window
    from prompt_toolkit.layout.controls import FormattedTextControl
    from prompt_toolkit.styles import Style

    sel = [0]
    result: list[str | None] = [None]

    kb = KeyBindings()

    @kb.add("up")
    @kb.add("k")
    def _up(event):
        sel[0] = (sel[0] - 1) % len(options)

    @kb.add("down")
    @kb.add("j")
    def _down(event):
        sel[0] = (sel[0] + 1) % len(options)

    @kb.add("enter")
    def _enter(event):
        result[0] = options[sel[0]][1]
        event.app.exit()

    @kb.add("escape")
    @kb.add("q")
    def _quit(event):
        result[0] = None
        event.app.exit()

    style = Style.from_dict({
        "title": "bold cyan",
        "arrow": "bold cyan",
        "selected": "bold",
        "dim": "dim",
    })

    def _get_text():
        lines: list[tuple[str, str]] = []
        lines.append(("class:title", f"  {title}\n"))
        lines.append(("", "\n"))
        for i, (label, _) in enumerate(options):
            if i == sel[0]:
                lines.append(("class:arrow", "  ❯ "))
                lines.append(("class:selected", f"{label}\n"))
            else:
                lines.append(("", "    "))
                lines.append(("class:dim", f"{label}\n"))
            lines.append(("", "\n"))  # 选项间空一行
        lines.append(("class:dim", "  ↑/↓ 选择  Enter 确认  Esc 返回"))
        return FormattedText(lines)

    layout = Layout(HSplit([
        Window(content=FormattedTextControl(_get_text), wrap_lines=True),
    ]))

    app_pt = Application(layout=layout, key_bindings=kb, style=style, full_screen=False)
    app_pt.run()
    return result[0]


# ── 第一层菜单 ────────────────────────────────────────────────────────────────

def _run_interactive_menu() -> None:
    """第一层菜单：设置 / 插件 / 渠道。循环直到 Esc 退出。"""
    options = [
        ("⚙️  设置 — 编辑核心配置（模型、代理、网络等）", "settings"),
        ("🧩 插件 — 安装/管理预设插件与技能", "plugins"),
        ("📡 渠道 — 配置消息渠道（飞书、微信等）", "channels"),
    ]

    while True:
        action = _arrow_select("Ethan Setup", options)
        if action is None:
            break
        elif action == "settings":
            _menu_settings()
        elif action == "plugins":
            _menu_plugins()
        elif action == "channels":
            _menu_channels()


# ── 设置 ──────────────────────────────────────────────────────────────────────

def _menu_settings() -> None:
    """设置子菜单：列出配置项，选择后进入对应编辑模式。"""
    from ethan.core.config import get_config, save_config
    from ethan.core.config_schema import EDITABLE_FIELDS, get_value

    config = get_config()
    changed = False

    while True:
        # 构造选项列表：标签 = 当前值
        options = []
        for f in EDITABLE_FIELDS:
            val = get_value(config, f.path)
            display_val = _format_value(val, f.kind)
            label = f"{f.label} = {display_val}"
            options.append((label, f.path))

        selected = _arrow_select("⚙️  设置", options)
        if selected is None:
            break

        # 找到对应字段
        field = next((f for f in EDITABLE_FIELDS if f.path == selected), None)
        if not field:
            continue

        cur_val = get_value(config, field.path)
        new_val = _edit_field(field, cur_val, config)
        if new_val is not None:
            from ethan.core.config_schema import set_value as _set
            _set(config, field.path, new_val)
            changed = True

    if changed:
        save_config(config)
        import os
        os.system("clear" if os.name != "nt" else "cls")
        console.print("[green]✓ 配置已保存[/green]")
        console.print()


def _format_value(val, kind: str) -> str:
    """格式化配置值用于显示。"""
    if val is None:
        return "(空)"
    if kind == "bool":
        return "开" if val else "关"
    return str(val)


def _edit_field(field, cur_val, config):
    """根据字段类型选择合适的编辑方式。返回新值或 None（取消）。"""
    if field.kind == "bool":
        return _toggle_bool(field, cur_val)
    elif field.kind == "choice":
        return _select_choice(field, cur_val)
    else:
        return _input_value(field, cur_val)


def _toggle_bool(field, cur_val: bool):
    """bool 类型：左右箭头切换。"""
    import os

    from prompt_toolkit.application import Application
    from prompt_toolkit.formatted_text import FormattedText
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.layout import HSplit, Layout, Window
    from prompt_toolkit.layout.controls import FormattedTextControl
    from prompt_toolkit.styles import Style

    os.system("clear" if os.name != "nt" else "cls")

    val = [bool(cur_val)]
    result = [None]

    kb = KeyBindings()

    @kb.add("left")
    @kb.add("right")
    @kb.add("h")
    @kb.add("l")
    def _toggle(event):
        val[0] = not val[0]

    @kb.add("enter")
    def _confirm(event):
        result[0] = val[0]
        event.app.exit()

    @kb.add("escape")
    @kb.add("q")
    def _cancel(event):
        event.app.exit()

    style = Style.from_dict({
        "title": "bold cyan", "on": "green bold", "off": "dim", "hint": "dim",
    })

    def _render():
        lines = [
            ("class:title", f"  {field.label}\n"),
            ("", "\n"),
            ("", "  "),
        ]
        if val[0]:
            lines.append(("class:on", "  ● 开  "))
            lines.append(("class:off", "  ○ 关  "))
        else:
            lines.append(("class:off", "  ○ 开  "))
            lines.append(("class:on", "  ● 关  "))
        lines.append(("", "\n\n"))
        lines.append(("class:hint", "  ←/→ 切换  Enter 确认  Esc 取消"))
        return FormattedText(lines)

    layout = Layout(HSplit([Window(content=FormattedTextControl(_render), wrap_lines=True)]))
    Application(layout=layout, key_bindings=kb, style=style, full_screen=False).run()
    return result[0]


def _select_choice(field, cur_val):
    """choice 类型：如果选项 ≤ 3 个用左右切换，否则用上下选择。"""
    choices = field.choices
    if not choices:
        return None

    if len(choices) <= 3:
        return _cycle_choice(field, cur_val, choices)
    else:
        options = [(c, c) for c in choices]
        selected = _arrow_select(field.label, options)
        return selected


def _cycle_choice(field, cur_val, choices: list[str]):
    """≤3 个选项用左右箭头循环切换。"""
    import os

    from prompt_toolkit.application import Application
    from prompt_toolkit.formatted_text import FormattedText
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.layout import HSplit, Layout, Window
    from prompt_toolkit.layout.controls import FormattedTextControl
    from prompt_toolkit.styles import Style

    os.system("clear" if os.name != "nt" else "cls")

    idx = [choices.index(cur_val) if cur_val in choices else 0]
    result = [None]

    kb = KeyBindings()

    @kb.add("left")
    @kb.add("h")
    def _prev(event):
        idx[0] = (idx[0] - 1) % len(choices)

    @kb.add("right")
    @kb.add("l")
    def _next(event):
        idx[0] = (idx[0] + 1) % len(choices)

    @kb.add("enter")
    def _confirm(event):
        result[0] = choices[idx[0]]
        event.app.exit()

    @kb.add("escape")
    @kb.add("q")
    def _cancel(event):
        event.app.exit()

    style = Style.from_dict({
        "title": "bold cyan", "active": "bold green", "inactive": "dim", "hint": "dim",
    })

    def _render():
        lines = [
            ("class:title", f"  {field.label}\n"),
            ("", "\n"),
            ("", "  "),
        ]
        for i, c in enumerate(choices):
            if i == idx[0]:
                lines.append(("class:active", f"  ● {c}  "))
            else:
                lines.append(("class:inactive", f"  ○ {c}  "))
        lines.append(("", "\n\n"))
        lines.append(("class:hint", "  ←/→ 切换  Enter 确认  Esc 取消"))
        return FormattedText(lines)

    layout = Layout(HSplit([Window(content=FormattedTextControl(_render), wrap_lines=True)]))
    Application(layout=layout, key_bindings=kb, style=style, full_screen=False).run()
    return result[0]


def _input_value(field, cur_val):
    """str/int 类型：进入文本输入。"""
    import os

    from prompt_toolkit import prompt as pt_prompt

    os.system("clear" if os.name != "nt" else "cls")

    console.print(f"  [bold cyan]{field.label}[/bold cyan]")
    if field.desc:
        console.print(f"  [dim]{field.desc}[/dim]")
    console.print(f"  [dim]当前值: {cur_val if cur_val is not None else '(空)'}[/dim]")
    console.print()

    try:
        raw = pt_prompt("  新值 (留空取消): ", default=str(cur_val) if cur_val is not None else "")
    except (EOFError, KeyboardInterrupt):
        return None

    raw = raw.strip()
    if not raw or raw == str(cur_val):
        return None

    # 类型转换
    from ethan.core.config_schema import coerce
    try:
        return coerce(field, raw)
    except ValueError as e:
        console.print(f"  [red]{e}[/red]")
        return None


# ── 插件 ──────────────────────────────────────────────────────────────────────

def _menu_plugins() -> None:
    """插件子菜单：列出预设插件，选择安装。"""
    installed_skills = _get_installed_skill_names()
    installed_plugins = _get_enabled_plugin_names()

    options = []
    for p in PRESET_PLUGINS:
        name = p["name"]
        if p["install_type"] == "optional_dep":
            installed = _is_optional_dep_installed(p)
        elif p["install_type"] == "skill":
            installed = name in installed_skills
        else:
            installed = name in installed_plugins
        mark = "✓" if installed else "✗"
        cn_label = p.get("label", name)
        label = f"{mark} {cn_label} ({name}) — {p['description']}"
        options.append((label, name))

    selected = _arrow_select("🧩 插件管理", options)
    if selected is None:
        _run_interactive_menu()
        return

    _install_plugin(selected)


def _install_plugin(name: str) -> None:
    """执行单个插件/技能安装，或对已安装的展示操作菜单。"""
    plugin = next((p for p in PRESET_PLUGINS if p["name"] == name), None)
    if not plugin:
        console.print(f"[red]未找到插件: {name}[/red]")
        return

    # 判断是否已安装
    installed = _check_plugin_installed(plugin)

    console.print()
    if installed:
        # 已安装 → 展示操作菜单
        options = [
            ("🔄 重新安装 / 升级", "reinstall"),
            ("ℹ️  查看信息", "info"),
        ]
        action = _arrow_select(f"{name} (已安装)", options)
        if action == "reinstall":
            _do_install(plugin)
        elif action == "info":
            console.print(f"[bold]{name}[/bold] — {plugin['description']}")
            console.print(f"[dim]类型: {plugin['install_type']}[/dim]")
            if plugin.get("post_install_hint"):
                console.print(f"[dim]{plugin['post_install_hint']}[/dim]")
            console.print()
    else:
        _do_install(plugin)


def _do_install(plugin: dict) -> None:
    """实际执行安装逻辑。"""
    name = plugin["name"]
    if plugin["install_type"] == "skill":
        console.print(f"[bold]安装技能: {name}[/bold]")
        console.print(f"[dim]{plugin['description']}[/dim]")
        console.print()
        _install_skill(plugin["install_source"])
    elif plugin["install_type"] == "builtin_skill":
        console.print(f"[bold]启用内置技能: {name}[/bold]")
        console.print(f"[dim]{plugin['description']}[/dim]")
        console.print()
        _install_builtin_skill(plugin)
    elif plugin["install_type"] == "optional_dep":
        console.print(f"[bold]安装可选依赖: {name}[/bold]")
        console.print(f"[dim]{plugin['description']}[/dim]")
        console.print()
        _install_optional_dep(plugin)
    elif plugin["install_type"] == "lark_channel":
        console.print(f"[bold]安装飞书渠道依赖: {name}[/bold]")
        console.print(f"[dim]{plugin['description']}[/dim]")
        console.print()
        _install_lark_channel_deps()
    else:
        console.print(f"[bold]配置插件: {name}[/bold]")
        console.print(f"[dim]{plugin['description']}[/dim]")
        console.print()
        _install_config_plugin(plugin["install_source"])

    # post_install 钩子：主步骤装完后执行（如拉取模型）
    hook = plugin.get("post_install")
    if hook == "router_pull":
        _post_install_router_pull()


def _check_plugin_installed(plugin: dict) -> bool:
    """统一检测插件是否已安装。"""
    name = plugin["name"]
    if plugin["install_type"] == "optional_dep":
        deps_ok = _is_optional_dep_installed(plugin)
        # 嵌入路由类：依赖 + 模型文件都就位才算"已安装"
        if plugin.get("post_install") == "router_pull":
            try:
                from ethan.skills.router import model_present
                return deps_ok and model_present()
            except Exception:
                return deps_ok
        return deps_ok
    elif plugin["install_type"] == "lark_channel":
        return _is_lark_channel_ready()
    elif plugin["install_type"] in ("skill", "builtin_skill"):
        return name in _get_installed_skill_names()
    else:
        return name in _get_enabled_plugin_names()


def _post_install_router_pull() -> None:
    """嵌入路由插件：依赖装完后拉取 BGE 模型（~24MB，首次）。"""
    try:
        from ethan.skills.router import ensure_model
    except Exception as e:
        console.print(f"[yellow]⚠ 无法导入路由模块（跳过模型拉取）：{e}[/yellow]")
        return
    console.print()
    console.print("[bold]拉取嵌入路由模型（~24MB，首次）…[/bold]")
    try:
        with console.status("[dim]下载 BGE 模型…[/dim]"):
            path = ensure_model(force=False)
    except Exception as e:  # 离线/网络失败等
        path = None
        console.print(f"[dim]拉取异常：{e}[/dim]")
    if path:
        console.print("[green]✓ 嵌入路由模型已就绪[/green]")
    else:
        console.print("[yellow]⚠ 模型自动拉取失败[/yellow]")
        console.print("  可稍后手动运行 [cyan]ethan router pull[/cyan] 重试（需联网）。")
    console.print()


def _is_lark_channel_ready() -> bool:
    """飞书渠道依赖是否就绪：lark-oapi + lark-cli 都装好。"""
    from ethan.interface.lark_deps import get_lark_deps_status
    s = get_lark_deps_status()
    return s.lark_oapi_installed and s.lark_cli_installed


def _install_lark_channel_deps() -> None:
    """安装飞书渠道依赖（lark-oapi + lark-cli + app sync）。

    从已保存的 config 读 app 凭证；若未配置则提示用户先跑渠道配置。
    """
    from ethan.core.config import get_config
    from ethan.interface.lark_deps import ensure_lark_deps

    cfg = get_config()
    app_id = cfg.lark.app_id or ""
    app_secret = cfg.lark.app_secret or ""

    if not app_id or not app_secret:
        console.print("[yellow]⚠ 未检测到飞书应用配置（app_id / app_secret）[/yellow]")
        console.print("  先运行 [cyan]ethan channel add lark[/cyan] 配置应用凭证，")
        console.print("  或在 Web 端「渠道」页面填入后，再回来安装依赖。")
        console.print("  依赖仍会尝试安装（仅 lark-oapi + lark-cli），但无法自动 sync app。")
        console.print()

    status = ensure_lark_deps(
        app_id, app_secret,
        interactive=True,
        triggered_by="plugin",
    )
    console.print()
    if status.lark_oapi_installed and status.lark_cli_installed and status.lark_cli_app_matches:
        console.print("[green]✓ 飞书渠道依赖全部就绪[/green]")
    elif status.lark_oapi_installed and status.lark_cli_installed:
        console.print("[green]✓ lark-oapi 与 lark-cli 已安装[/green]")
        if not app_id:
            console.print("[dim]app 未配置，跳过 sync。配好 app 后重跑本命令完成同步。[/dim]")
    else:
        console.print("[yellow]⚠ 部分依赖未就绪，详见上方输出[/yellow]")
        if status.last_error:
            console.print(f"[dim]{status.last_error}[/dim]")
    console.print()


def _install_skill(alias_or_source: str) -> None:
    """通过 install_skill 工具安装技能（支持 clone）。"""
    import asyncio

    from ethan.interface.commands.skill import SKILL_ALIASES
    from ethan.tools.builtin.install_skill import InstallSkillTool

    resolved = SKILL_ALIASES.get(alias_or_source.strip().lower(), alias_or_source)
    console.print(f"[dim]来源: {resolved}[/dim]")

    with console.status(f"[dim]安装中: {resolved}…[/dim]"):
        result = asyncio.run(InstallSkillTool().run(source=resolved, name=""))
    console.print(result)
    console.print()


def _install_builtin_skill(plugin: dict) -> None:
    """启用内置技能：从 defaults/skills/ 复制到用户 skills 目录。"""
    import shutil
    from pathlib import Path

    from ethan.core.paths import user_skills_dir

    name = plugin["name"]
    src = Path(__file__).resolve().parents[2] / "defaults" / "skills" / name
    if not src.exists():
        console.print(f"[red]内置技能目录不存在: {src}[/red]")
        return

    dest = user_skills_dir() / name
    dest.parent.mkdir(parents=True, exist_ok=True)

    if dest.exists():
        shutil.rmtree(dest)

    shutil.copytree(src, dest)

    # 安装特有依赖（如果有）
    pip_packages = plugin.get("pip_packages", [])
    if pip_packages:
        _pip_install(pip_packages)

    console.print(f"[green]✓ 已启用内置技能: {name}[/green]")
    if plugin.get("post_install_hint"):
        console.print(f"[dim]{plugin['post_install_hint']}[/dim]")
    console.print()


def _install_config_plugin(plugin_name: str) -> None:
    """通过 plugin add 流程安装配置型插件。"""
    from ethan.interface.commands.plugin import add_plugin

    try:
        add_plugin(plugin_name)
    except SystemExit:
        pass
    console.print()


def _install_optional_dep(plugin: dict) -> None:
    """安装可选依赖型插件。"""
    packages = plugin.get("pip_packages", [])
    if not packages:
        console.print("[red]无包可安装[/red]")
        return

    success = _pip_install(packages)
    if not success:
        return

    # 后续操作提示
    hint = plugin.get("post_install_hint")
    if hint:
        console.print()
        console.print("[bold yellow]后续步骤:[/bold yellow]")
        for line in hint.split("\n"):
            console.print(f"  {line}")
    console.print()


def _pip_install(packages: list[str]) -> bool:
    """安装 Python 包（优先 uv pip，回退 pip）。返回是否成功。"""
    import shutil
    import subprocess
    import sys

    pkg_str = " ".join(packages)
    console.print(f"[dim]安装 Python 包: {pkg_str}[/dim]")

    uv_bin = shutil.which("uv")
    if uv_bin:
        cmd = [uv_bin, "pip", "install", *packages]
    else:
        cmd = [sys.executable, "-m", "pip", "install", *packages]

    try:
        with console.status(f"[dim]{' '.join(cmd[:3])} {pkg_str}…[/dim]"):
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=120,
            )
        if result.returncode == 0:
            console.print(f"[green]✓ {pkg_str} 安装成功[/green]")
            return True
        else:
            console.print(f"[red]安装失败:[/red] {result.stderr.strip()}")
            return False
    except subprocess.TimeoutExpired:
        console.print("[red]安装超时（120s）[/red]")
        return False


def _is_optional_dep_installed(plugin: dict) -> bool:
    """检查可选依赖的 Python 包是否已安装。"""
    import importlib.util

    packages = plugin.get("pip_packages", [])
    for pkg in packages:
        # cua-computer → 实际 import 名是 computer
        import_name = _pip_to_import(pkg)
        if importlib.util.find_spec(import_name) is None:
            return False
    return True


def _pip_to_import(pip_name: str) -> str:
    """将 pip 包名映射为 import 名（先剥离版本限定符如 >=1.18.0）。"""
    import re
    # 字符集含 [ ：剥离版本限定的同时，也切掉 extras 语法 package[extra]，
    # 避免 importlib.import_module("rich[markup]") 抛 ModuleNotFoundError。
    bare = re.split(r"[\[<>=!~ ]", pip_name.strip(), maxsplit=1)[0].strip()
    mapping = {
        "cua-computer": "computer",
    }
    return mapping.get(bare, bare.replace("-", "_"))


# ── 渠道 ──────────────────────────────────────────────────────────────────────

def _menu_channels() -> None:
    """渠道子菜单：列出可配置渠道。循环直到 Esc 返回。"""
    from ethan.core.config import get_config

    while True:
        config = get_config()
        lark_ok = bool(config.lark.app_id and config.lark.app_secret)
        wechat_ok = bool(config.wechat.enabled)

        options = [
            (f"{'✓' if lark_ok else '✗'} 飞书 (Lark) — {'已配置' if lark_ok else '未配置'}", "lark"),
            (f"{'✓' if wechat_ok else '✗'} 微信 (WeChat) — {'已启用' if wechat_ok else '未启用'}", "wechat"),
        ]

        selected = _arrow_select("📡 渠道配置", options)
        if selected is None:
            break

        if selected == "lark":
            _setup_lark()
        elif selected == "wechat":
            _setup_wechat()


def _setup_lark() -> None:
    """引导配置飞书 — 使用 setup 自有交互，支持 Esc 取消。"""
    import os

    from prompt_toolkit import prompt as pt_prompt

    from ethan.core.config import get_config, save_config

    os.system("clear" if os.name != "nt" else "cls")

    config = get_config()
    console.print("[bold cyan]📡 飞书（Lark）渠道配置[/bold cyan]")
    console.print()
    console.print("前置准备（在飞书开放平台 https://open.feishu.cn 创建企业自建应用）：")
    console.print("  1. [凭证与基础信息] → 获取 App ID 和 App Secret")
    console.print("  2. [事件与回调] → 选择 [长连接] 模式")
    console.print("  3. 订阅事件（[red]三项都要勾[/red]，否则启动会报 validation 错）：")
    console.print("       • im.message.receive_v1          — 接收消息（必选）")
    console.print("       • im.message.reaction.created_v1 — 消息被加表情（可选但建议）")
    console.print("       • card.action.trigger            — [red]交互卡片按钮回调[/red]（不勾则按钮点击无效、日志频繁报错）")
    console.print("  4. [权限管理] 开通：im:message 等")
    console.print("  5. lark-oapi 与 lark-cli 会在保存配置后自动安装")
    console.print()
    console.print("[dim]Ctrl+C 或留空回车可取消[/dim]")
    console.print()

    fields = [
        ("app_id", "App ID", True),
        ("app_secret", "App Secret", True),
        ("verification_token", "Verification Token", False),
        ("encrypt_key", "Encrypt Key", False),
    ]

    values = {}
    for key, label, required in fields:
        cur = getattr(config.lark, key, "") or ""
        hint = "(必填)" if required else "(可选，回车跳过)"
        try:
            val = pt_prompt(f"  {label} {hint}: ", default=cur)
        except (EOFError, KeyboardInterrupt):
            console.print("\n[dim]已取消[/dim]")
            return
        val = val.strip()
        if required and not val:
            console.print("[yellow]必填项为空，已取消[/yellow]")
            return
        values[key] = val

    # 保存
    for k, v in values.items():
        setattr(config.lark, k, v)
    save_config(config)
    console.print()
    console.print("[green]✓ 飞书配置已保存[/green]")

    # 统一调用 ensure_lark_deps：装 lark-oapi + 装 lark-cli + sync app
    from ethan.interface.lark_deps import ensure_lark_deps
    console.print()
    console.print("[bold]依赖就绪检查与安装[/bold]")
    status = ensure_lark_deps(
        values.get("app_id", ""),
        values.get("app_secret", ""),
        interactive=True,
        triggered_by="setup",
    )
    console.print()
    if status.lark_oapi_installed and status.lark_cli_installed and status.lark_cli_app_matches:
        console.print("[green]✓ 飞书依赖全部就绪[/green]")
    else:
        console.print("[yellow]⚠ 部分依赖未就绪，详见上方输出[/yellow]")
        if status.last_error:
            console.print(f"[dim]{status.last_error}[/dim]")
    console.print("[dim]重启 ethan serve 后生效。[/dim]")
    console.print()
    try:
        pt_prompt("[dim]按 Enter 返回...[/dim]")
    except (EOFError, KeyboardInterrupt):
        pass


def _setup_wechat() -> None:
    """引导配置微信。"""
    import os

    from prompt_toolkit import prompt as pt_prompt

    os.system("clear" if os.name != "nt" else "cls")

    console.print("[bold cyan]📡 微信渠道配置[/bold cyan]")
    console.print()
    console.print("微信渠道通过 iLink 协议接入，请执行：")
    console.print("  [cyan]ethan wechat login[/cyan]")
    console.print()
    console.print("[dim]登录后再执行 `ethan wechat enable` 启用。[/dim]")
    console.print()
    try:
        pt_prompt("[dim]按 Enter 返回...[/dim]")
    except (EOFError, KeyboardInterrupt):
        pass


# ── 辅助函数 ──────────────────────────────────────────────────────────────────

def _get_installed_skill_names() -> set[str]:
    """获取已安装的用户 skill 名称集合。"""
    from ethan.core.paths import user_skills_dir
    skills_dir = user_skills_dir()
    if not skills_dir.exists():
        return set()
    names = set()
    for p in skills_dir.iterdir():
        if p.is_dir() and (p / "SKILL.md").exists():
            names.add(p.name)
        elif p.suffix == ".md" and p.stem != "README":
            names.add(p.stem)
    return names


def _get_enabled_plugin_names() -> set[str]:
    """获取已启用的 config 插件名称集合。"""
    from ethan.core.config import get_config
    from ethan.interface.commands.plugin import PLUGIN_REGISTRY, _is_enabled

    config = get_config()
    enabled = set()
    for name, plugin in PLUGIN_REGISTRY.items():
        if _is_enabled(config, plugin):
            enabled.add(name)
    return enabled
