"""secret 子命令组：管理 ~/.ethan/.secrets/ 下的密钥。

命令：
  ethan secret list                          列出已保存的密钥名（不显示值）
  ethan secret get <name>                    读取密钥值
  ethan secret set <name> <value>            写入单值密钥文件（最常用）
  ethan secret set-env <file> <KEY=value>... 写入/追加 .env 文件（多 key 场景）

存储约定（与 docs/secrets.md 对齐）：
- 单值密钥 → ~/.ethan/.secrets/<slug>，内容为 KEY=value。
  文件名自动 slugify（小写 + _ 转 -）。
  例：ethan secret set API_YUNTOKEN xxx → .secrets/api-yuntoken  内容: API_YUNTOKEN=xxx
  agent 用 get_secret("api-yuntoken") 读取，shell 用 $API_YUNTOKEN 注入。
- .env 密钥 → ~/.ethan/.secrets/<service>.env，每行 KEY=value。
  例：ethan secret set-env openai OPENAI_API_KEY=sk-xxx OPENAI_BASE_URL=...
  agent 用 get_secret("openai.env:OPENAI_API_KEY") 读取（list_secrets 会显示）。
  shell 自动注入所有密钥文件到子进程环境。

权限：.secrets/ 目录 0700，密钥文件 0600。
"""
from __future__ import annotations

import os
import stat

import typer
from rich.console import Console

from ethan.tools.builtin.secrets import _deslugify, _safe_name, _secrets_dir, _slugify

console = Console()
app = typer.Typer(help="管理密钥（~/.ethan/.secrets/）", invoke_without_command=True)


@app.callback(invoke_without_command=True)
def _default(ctx: typer.Context) -> None:
    if ctx.invoked_subcommand is None:
        console.print(ctx.get_help())
        raise typer.Exit()


@app.command("list")
def list_secrets() -> None:
    """列出已保存的密钥名（不显示值）。"""
    d = _secrets_dir()
    if not d.is_dir():
        console.print("[dim]（暂无密钥。用 ethan secret set <name> <value> 添加。）[/dim]")
        return
    names = sorted(p.relative_to(d).as_posix() for p in d.rglob("*") if p.is_file())
    if not names:
        console.print("[dim]（暂无密钥。用 ethan secret set <name> <value> 添加。）[/dim]")
        return
    console.print("[bold]已保存的密钥:[/bold]")
    for n in names:
        # 单值文件显示文件名；.env 文件显示 "file.env (KEY1, KEY2, ...)"
        full = d / n
        if full.suffix == ".env":
            keys = []
            for line in full.read_text(encoding="utf-8", errors="replace").splitlines():
                s = line.strip()
                if s and not s.startswith("#") and "=" in s:
                    keys.append(s.split("=", 1)[0])
            keys_str = ", ".join(keys) if keys else "(空)"
            console.print(f"  [cyan]{n}[/cyan]  [dim]{keys_str}[/dim]")
        else:
            console.print(f"  [cyan]{n}[/cyan]")


@app.command("get")
def get_secret(name: str = typer.Argument(..., help="密钥名，如 api-yuntoken / getnote 或 openai.env:OPENAI_API_KEY")) -> None:
    """读取密钥值（明文打印到终端）。

    支持：
    - 单值文件名（slug）：api-yuntoken → 读取 .secrets/api-yuntoken，解析 KEY=value 返回值
    - .env 文件的 KEY：openai.env:OPENAI_API_KEY → 读取 .secrets/openai.env 里 OPENAI_API_KEY 的值
    """
    # 解析 name：可能形如 "file.env:KEY"
    parts = name.split(":", 1)
    file_part = parts[0]
    key_part = parts[1] if len(parts) == 2 else None
    try:
        safe = _safe_name(file_part)
    except ValueError as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1)
    slug = _slugify(safe)
    d = _secrets_dir()
    # Try slugified name first, then original (backward compat)
    path = None
    for candidate in (slug, safe):
        p = d / candidate
        if p.is_file():
            path = p
            break
    if path is None:
        console.print(
            f"[red]密钥不存在: {slug}[/red]\n"
            f"[dim]用 ethan secret list 查看已有密钥，或 ethan secret set {file_part} <value> 创建。[/dim]"
        )
        raise typer.Exit(1)
    content = path.read_text(encoding="utf-8", errors="replace").strip()
    if key_part and path.suffix == ".env":
        # 从 .env 文件里取特定 KEY
        for line in content.splitlines():
            s = line.strip()
            if s.startswith("#") or "=" not in s:
                continue
            k, v = s.split("=", 1)
            if k.strip() == key_part:
                v = v.strip()
                if len(v) >= 2 and v[0] == v[-1] and v[0] in ("'", '"'):
                    v = v[1:-1]
                console.print(v)
                return
        console.print(f"[red]Key {key_part!r} 不在 {path.name} 里[/red]")
        raise typer.Exit(1)
    # 单值文件：尝试 KEY=value 格式（新格式），否则返回原始内容（旧格式）
    expected_key = _deslugify(path.name)
    prefix = f"{expected_key}="
    if content.startswith(prefix):
        console.print(content[len(prefix):].strip())
    else:
        console.print(content)


@app.command("set")
def set_secret(
    name: str = typer.Argument(..., help="密钥名，如 API_YUNTOKEN / getnote / OPENAI_API_KEY（自动 slug 为文件名）"),
    value: str = typer.Argument(..., help="密钥值"),
) -> None:
    """写入单值密钥文件（最常用）。

    文件名自动 slugify（小写 + _ 转 -），文件内容为 KEY=value 格式。
    agent 用 get_secret(slug) 读取，shell 子进程自动以 $KEY 环境变量注入。

    \b
    示例：
      ethan secret set API_YUNTOKEN xxx         → .secrets/api-yuntoken  内容: API_YUNTOKEN=xxx
      ethan secret set getnote gk_xxxx           → .secrets/getnote      内容: getnote=gk_xxxx
      ethan secret set HOMEASSISTANT_TOKEN ha_abc  → .secrets/homeassistant-token  内容: HOMEASSISTANT_TOKEN=ha_abc
    """
    try:
        safe = _safe_name(name)
    except ValueError as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1)
    slug = _slugify(safe)
    path = _secrets_dir() / slug
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"{safe}={value}\n", encoding="utf-8")
    try:
        os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)  # 0600
    except OSError:
        pass
    console.print(f"[green]✓ 密钥已保存: {slug}[/green]")
    console.print(f"  [dim]路径: {path}[/dim]")
    console.print(f"  [dim]agent 读取: get_secret(\"{slug}\")[/dim]")
    console.print(f"  [dim]shell 注入: ${safe}[/dim]")


@app.command("set-env")
def set_env_secret(
    file: str = typer.Argument(..., help=".env 文件名（不带 .env 后缀也行），如 openai / github"),
    kv: list[str] = typer.Argument(..., help="KEY=value 键值对（可多个）"),
    append: bool = typer.Option(False, "--append/--overwrite", help="追加到已有文件 / 覆盖（默认）"),
) -> None:
    """写入 .env 文件（多 key 场景）。

    每行 KEY=value，shell 自动注入子进程环境，agent 用
    get_secret("<file>.env:<KEY>") 读取。

    \b
    示例：
      ethan secret set-env openai OPENAI_API_KEY=sk-xxx OPENAI_BASE_URL=https://api.openai.com/v1
      → .secrets/openai.env
      ethan secret set-env github GH_TOKEN=ghp_xxx --append
      → 追加到 .secrets/github.env
    """
    # 规范文件名：用户传 "openai" 或 "openai.env" 都统一成 "openai.env"
    base = file[:-4] if file.endswith(".env") else file
    try:
        safe_base = _safe_name(base)
    except ValueError as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1)
    safe = safe_base + ".env"
    path = _secrets_dir() / safe

    # 解析 KEY=value
    new_pairs: dict[str, str] = {}
    for item in kv:
        if "=" not in item:
            console.print(f"[red]无效的 KEY=value: {item!r}（缺少 =）[/red]")
            raise typer.Exit(1)
        k, v = item.split("=", 1)
        k = k.strip()
        if not k or not k[0].isalpha() and k[0] != "_":
            console.print(f"[red]无效的 KEY 名: {k!r}（必须以字母/下划线开头）[/red]")
            raise typer.Exit(1)
        new_pairs[k] = v

    # 合并已有内容（append 模式）
    existing: dict[str, str] = {}
    if append and path.is_file():
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            s = line.strip()
            if s and not s.startswith("#") and "=" in s:
                k, v = s.split("=", 1)
                existing[k.strip()] = v

    merged = {**existing, **new_pairs}
    text = "".join(f"{k}={v}\n" for k, v in merged.items())
    path.write_text(text, encoding="utf-8")
    try:
        os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass

    console.print(f"[green]✓ 密钥已保存: {safe}[/green]")
    console.print(f"  [dim]路径: {path}[/dim]")
    console.print(f"  [dim]Keys: {', '.join(new_pairs.keys())}[/dim]")
    for k in new_pairs:
        console.print(f"  [dim]agent 读取: get_secret(\"{safe}:{k}\")[/dim]")
