"""update 命令：自动更新 ethan-agent 到最新版本。

命令：
  ethan update                  更新到最新稳定版（最新 tag）
  ethan update --channel dev    更新到 main 最新 commit
  ethan update --to v0.2.0      更新到指定版本/tag/commit
  ethan update --check          只检查是否有更新，不执行
  ethan update --no-restart     更新后不自动重启 serve 进程
"""
import subprocess
import sys
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console

console = Console()
app = typer.Typer(help="更新 ethan-agent 到最新版本", invoke_without_command=True)

GITHUB_REMOTE = "https://github.com/llm011/ethan-agent.git"
GITEE_REMOTE  = "https://gitee.com/llm011/ethan-agent.git"
FETCH_TIMEOUT = 10  # seconds


def _repo_root() -> Optional[Path]:
    """返回 git 仓库根目录，若不是 git 安装方式则返回 None。"""
    # update.py 位于 ethan/interface/commands/，向上四级到仓库根
    candidate = Path(__file__).resolve().parent.parent.parent.parent
    if (candidate / ".git").exists():
        return candidate
    return None


def _run(cmd: list[str], cwd: Optional[Path] = None, timeout: int = 60) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)


def _current_ref(repo: Path) -> str:
    """返回当前 HEAD 的简短 commit hash。"""
    r = _run(["git", "rev-parse", "--short", "HEAD"], cwd=repo)
    return r.stdout.strip()


def _current_tag(repo: Path) -> Optional[str]:
    """返回当前 HEAD 对应的 tag（精确匹配），无则返回 None。"""
    r = _run(["git", "tag", "--points-at", "HEAD"], cwd=repo)
    tags = [t for t in r.stdout.strip().splitlines() if t]
    return tags[-1] if tags else None


def _latest_tag(repo: Path) -> Optional[str]:
    """返回远端最新 tag（按版本排序）。"""
    r = _run(["git", "tag", "--sort=-version:refname"], cwd=repo)
    tags = [t for t in r.stdout.strip().splitlines() if t]
    return tags[0] if tags else None


def _fetch(repo: Path) -> bool:
    """尝试 fetch，先 GitHub 后 Gitee fallback，返回是否成功。"""
    for remote_url in (GITHUB_REMOTE, GITEE_REMOTE):
        console.print(f"[dim]fetch {remote_url} ...[/dim]")
        try:
            r = _run(
                ["git", "fetch", "--tags", "--force", remote_url],
                cwd=repo,
                timeout=FETCH_TIMEOUT,
            )
            if r.returncode == 0:
                return True
            console.print(f"[dim]fetch 失败（returncode={r.returncode}），尝试下一个源...[/dim]")
        except subprocess.TimeoutExpired:
            console.print(f"[dim]fetch 超时（>{FETCH_TIMEOUT}s），尝试下一个源...[/dim]")
    return False


def _head_of_main(repo: Path) -> Optional[str]:
    """返回远端 origin/main 最新 commit hash。"""
    r = _run(["git", "rev-parse", "FETCH_HEAD"], cwd=repo)
    if r.returncode == 0:
        return r.stdout.strip()
    # fallback: ls-remote
    for remote_url in (GITHUB_REMOTE, GITEE_REMOTE):
        try:
            r = _run(
                ["git", "ls-remote", remote_url, "HEAD"],
                timeout=FETCH_TIMEOUT,
            )
            if r.returncode == 0 and r.stdout.strip():
                return r.stdout.strip().split()[0]
        except subprocess.TimeoutExpired:
            pass
    return None


def _checkout(repo: Path, target: str) -> bool:
    r = _run(["git", "checkout", target], cwd=repo)
    if r.returncode != 0:
        console.print(f"[red]checkout 失败：{r.stderr.strip()}[/red]")
        return False
    return True


def _sync_deps(repo: Path) -> bool:
    """重新同步依赖（优先 uv，fallback pip）。"""
    # 检测 uv 是否可用
    uv = _run(["which", "uv"])
    if uv.returncode == 0:
        r = _run(["uv", "sync", "--no-dev"], cwd=repo, timeout=120)
    else:
        r = _run([sys.executable, "-m", "pip", "install", "-e", "."], cwd=repo, timeout=120)
    if r.returncode != 0:
        console.print(f"[red]依赖同步失败：{r.stderr.strip()[-500:]}[/red]")
        return False
    return True


def _get_pypi_latest_version() -> Optional[str]:
    import urllib.request
    import json
    try:
        req = urllib.request.Request("https://pypi.org/pypi/ethan-agent/json")
        with urllib.request.urlopen(req, timeout=5) as res:
            data = json.loads(res.read().decode())
            return data["info"]["version"]
    except Exception:
        return None

def _pip_upgrade() -> bool:
    """PyPI 安装方式：pip install --upgrade ethan-agent。"""
    console.print("[dim]pip install --upgrade ethan-agent ...[/dim]")
    r = _run([sys.executable, "-m", "pip", "install", "--upgrade", "ethan-agent"], timeout=120)
    if r.returncode != 0:
        console.print(f"[red]pip upgrade 失败：{r.stderr.strip()[-500:]}[/red]")
        return False
    return True


def _find_serve_pid() -> Optional[int]:
    """找到正在运行的 ethan serve 进程 PID。"""
    try:
        r = _run(["pgrep", "-f", "ethan.*serve"])
        pids = [int(p) for p in r.stdout.strip().splitlines() if p.strip().isdigit()]
        return pids[0] if pids else None
    except Exception:
        return None


def _restart_serve(repo: Optional[Path]) -> None:
    """重启 ethan serve 进程。"""
    import os, signal, time

    pid = _find_serve_pid()
    if pid:
        console.print(f"[dim]发送 SIGTERM 到 ethan serve (pid={pid})...[/dim]")
        try:
            os.kill(pid, signal.SIGTERM)
            time.sleep(1)
        except ProcessLookupError:
            pass

    console.print("[dim]重启 ethan serve ...[/dim]")
    cwd = str(repo) if repo else None
    # 后台启动，不阻塞当前进程，同时丢弃输出防止污染终端
    subprocess.Popen(
        [sys.executable, "-m", "ethan.interface.cli", "serve"],
        cwd=cwd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    console.print("[green]✓ ethan serve 已重启（后台运行）[/green]")


@app.callback(invoke_without_command=True)
def update(
    ctx: typer.Context,
    channel: Optional[str] = typer.Option(
        None, "--channel", "-c",
        help="更新渠道：stable（默认，最新 tag）或 dev（main HEAD）",
    ),
    to: Optional[str] = typer.Option(
        None, "--to",
        help="指定版本/tag/commit，如 v0.2.0",
    ),
    check: bool = typer.Option(
        False, "--check",
        help="只检查是否有更新，不执行",
    ),
    restart: bool = typer.Option(
        True, "--restart/--no-restart",
        help="更新完成后是否重启 serve 进程",
    ),
) -> None:
    """更新 ethan-agent 到最新版本。"""
    if ctx.invoked_subcommand is not None:
        return

    repo = _repo_root()
    current_ref = _current_ref(repo) if repo else None
    current_tag = _current_tag(repo) if repo else None

    if repo is None:
        import importlib.metadata
        try:
            current_display = importlib.metadata.version("ethan-agent")
        except Exception:
            current_display = "[pip install]"
    else:
        current_display = current_tag or current_ref

    console.print(f"当前版本：[cyan]{current_display}[/cyan]")

    # ── PyPI 安装方式 ────────────────────────────────────────────
    if repo is None:
        latest = _get_pypi_latest_version()
        if latest and current_display != "[pip install]" and latest == current_display and not to:
            console.print("[green]已是最新版本，无需更新。[/green]")
            return

        if latest and not to:
            console.print(f"可更新到：[cyan]{latest}[/cyan]")

        if check:
            console.print("[yellow]运行 `pip install --upgrade ethan-agent` 更新。[/yellow]")
            return
        if to:
            console.print(f"[dim]pip install ethan-agent=={to.lstrip('v')} ...[/dim]")
            ok = _run(
                [sys.executable, "-m", "pip", "install", f"ethan-agent=={to.lstrip('v')}"],
                timeout=120,
            ).returncode == 0
        else:
            ok = _pip_upgrade()
        if ok:
            # Re-check version to confirm
            try:
                new_display = importlib.metadata.version("ethan-agent")
            except Exception:
                new_display = "新版本"
            if new_display == current_display and not to:
                console.print("[green]已是最新版本。[/green]")
            else:
                console.print(f"[green]✓ 更新完成：{current_display} → {new_display}[/green]")
                from ethan.core.config import get_config
                token = get_config().network.auth_token
                console.print("[yellow]💡 更新已生效。运行 `ethan` 开始对话，或运行 `ethan web` 打开网页界面。[/yellow]")
                if token:
                    console.print(f"[dim]   (你的 Web 登录 Token 是: [cyan]{token}[/cyan])[/dim]")
            if restart:
                _restart_serve(None)
        else:
            raise typer.Exit(1)
        return

    # ── git clone 安装方式 ───────────────────────────────────────
    console.print(f"仓库路径：[dim]{repo}[/dim]")

    console.print("正在获取最新版本信息...")
    if not _fetch(repo):
        console.print("[red]无法连接远端，请检查网络。[/red]")
        raise typer.Exit(1)

    # 确定目标版本
    if to:
        target = to
    elif channel == "dev":
        target = "FETCH_HEAD"
    else:
        target = _latest_tag(repo) or "FETCH_HEAD"

    # 解析目标 commit
    r = _run(["git", "rev-parse", "--short", target], cwd=repo)
    target_ref = r.stdout.strip() if r.returncode == 0 else target

    if target_ref == current_ref and not to:
        console.print("[green]已是最新版本，无需更新。[/green]")
        return

    tag_display = target if target != "FETCH_HEAD" else f"main@{target_ref}"
    console.print(f"可更新到：[cyan]{tag_display}[/cyan]  ({target_ref})")

    if check:
        return

    # 执行更新
    console.print(f"正在切换到 [cyan]{tag_display}[/cyan]...")
    if not _checkout(repo, target):
        raise typer.Exit(1)

    console.print("正在同步依赖...")
    if not _sync_deps(repo):
        raise typer.Exit(1)

    new_ref = _current_ref(repo)
    new_tag = _current_tag(repo)
    new_display = new_tag or new_ref
    console.print(f"[green]✓ 更新完成：{current_display} → {new_display}[/green]")
    from ethan.core.config import get_config
    token = get_config().network.auth_token
    console.print("[yellow]💡 更新已生效。运行 `ethan` 开始对话，或运行 `ethan web` 打开网页界面。[/yellow]")
    if token:
        console.print(f"[dim]   (你的 Web 登录 Token 是: [cyan]{token}[/cyan])[/dim]")

    if restart and _find_serve_pid():
        _restart_serve(repo)
    elif restart:
        console.print("[dim]（serve 未在运行，跳过重启）[/dim]")
