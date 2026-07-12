"""飞书渠道依赖统一安装：lark-oapi Python 包 + lark-cli 二进制 + app 同步。

三条入口（Web API / `ethan channel add|set lark` / `ethan setup` 菜单 / `ethan plugin add lark-channel`）
发现缺依赖时都调本模块的 `ensure_lark_deps`，避免「配了却收不到消息」的常见坑。

设计要点：
- 检测优先级：lark-oapi 包 → lark-cli 二进制 → lark-cli 当前绑定的 app
- 安装策略：
  - lark-oapi：uv pip install / python -m pip install（与 setup._pip_install 一致）
  - lark-cli：macOS 走 `brew install larksuite/tap/lark-cli`；其他平台打印提示
  - app 同步：`lark-cli config init --app-id ... --app-secret-stdin`（secret 走 stdin）
- 状态查询：`get_lark_deps_status()` 返回当前状态快照，供 Web API 暴露
- 并发保护：进程级锁，避免 Web 端多次 PATCH 同时触发安装
"""
from __future__ import annotations

import importlib.util
import json
import logging
import shutil
import subprocess
import sys
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

logger = logging.getLogger(__name__)

# 进程级安装锁：同一进程内多次调用 ensure_lark_deps 串行化，避免重复 brew/pip
_INSTALL_LOCK = threading.Lock()

# 全局状态：最近一次安装的结果，供 Web API 状态查询用
_LATEST_STATUS: Optional[LarkDepsStatus] = None


@dataclass
class LarkDepsStatus:
    """飞书依赖就绪状态快照。"""
    lark_oapi_installed: bool = False
    lark_cli_installed: bool = False
    lark_cli_app_synced: bool = False  # lark-cli 已绑定任意 app
    lark_cli_app_matches: bool = False  # lark-cli 绑定的 app 与 config 一致
    installing: bool = False
    last_error: str = ""
    last_run_at: str = ""  # ISO 时间戳，空 = 从未跑过
    installed_by: str = ""  # "web" / "cli" / "setup" / "plugin"

    def to_dict(self) -> dict:
        return {
            "lark_oapi_installed": self.lark_oapi_installed,
            "lark_cli_installed": self.lark_cli_installed,
            "lark_cli_app_synced": self.lark_cli_app_synced,
            "lark_cli_app_matches": self.lark_cli_app_matches,
            "installing": self.installing,
            "last_error": self.last_error,
            "last_run_at": self.last_run_at,
            "installed_by": self.installed_by,
        }


def _now_iso() -> str:
    from datetime import datetime
    return datetime.now().isoformat(timespec="seconds")


def _detect_lark_oapi() -> bool:
    return importlib.util.find_spec("lark_oapi") is not None


def _detect_lark_cli() -> bool:
    return shutil.which("lark-cli") is not None


def _lark_cli_path() -> Optional[str]:
    return shutil.which("lark-cli")


def _lark_cli_current_app() -> Optional[str]:
    """读取 lark-cli 当前配置的第一个 app_id，没有返回 None。"""
    cfg = Path.home() / ".lark-cli" / "config.json"
    if not cfg.exists():
        return None
    try:
        data = json.loads(cfg.read_text(encoding="utf-8"))
        apps = data.get("apps") or []
        return apps[0].get("appId") if apps else None
    except Exception:
        return None


def get_lark_deps_status() -> LarkDepsStatus:
    """返回当前依赖状态快照（不触发安装）。"""
    from ethan.core.config import get_config
    cfg = get_config()
    configured_app_id = cfg.lark.app_id or ""

    current_app = _lark_cli_current_app()
    return LarkDepsStatus(
        lark_oapi_installed=_detect_lark_oapi(),
        lark_cli_installed=_detect_lark_cli(),
        lark_cli_app_synced=bool(current_app),
        lark_cli_app_matches=bool(current_app and configured_app_id and current_app == configured_app_id),
        installing=(_LATEST_STATUS.installing if _LATEST_STATUS else False),
        last_error=(_LATEST_STATUS.last_error if _LATEST_STATUS else ""),
        last_run_at=(_LATEST_STATUS.last_run_at if _LATEST_STATUS else ""),
        installed_by=(_LATEST_STATUS.installed_by if _LATEST_STATUS else ""),
    )


def _pip_install(packages: list[str]) -> tuple[bool, str]:
    """安装 Python 包（uv pip 优先，回退 pip）。返回 (成功, stderr/错误消息)。"""
    uv_bin = shutil.which("uv")
    if uv_bin:
        cmd = [uv_bin, "pip", "install", *packages]
    else:
        cmd = [sys.executable, "-m", "pip", "install", *packages]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
        if result.returncode == 0:
            return True, ""
        return False, result.stderr.strip()[-400:]
    except subprocess.TimeoutExpired:
        return False, f"pip install 超时（180s）：{' '.join(packages)}"
    except Exception as e:
        return False, f"pip install 异常：{e}"


def _brew_install_lark_cli() -> tuple[bool, str]:
    """通过 brew 安装 lark-cli（macOS 优先路径）。返回 (成功, 错误消息)。"""
    brew = shutil.which("brew")
    if not brew:
        return False, (
            "未检测到 Homebrew。请先安装 Homebrew：\n"
            "  /bin/bash -c \"$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)\"\n"
            "装完 Homebrew 后重新触发飞书渠道配置即可自动续装 lark-cli。"
        )
    try:
        result = subprocess.run(
            [brew, "install", "larksuite/tap/lark-cli"],
            capture_output=True, text=True, timeout=180,
        )
        if result.returncode == 0:
            return True, ""
        return False, result.stderr.strip()[-400:] or result.stdout.strip()[-400:]
    except subprocess.TimeoutExpired:
        return False, "brew install lark-cli 超时（180s）"
    except Exception as e:
        return False, f"brew install 异常：{e}"


def _sync_lark_cli_app(app_id: str, app_secret: str) -> tuple[bool, str]:
    """调 lark-cli config init 把 app 同步过去（secret 走 stdin 防泄露）。"""
    lark_cli = _lark_cli_path()
    if not lark_cli:
        return False, "lark-cli 未安装"
    if not app_id or not app_secret:
        return False, "缺少 app_id 或 app_secret"

    try:
        proc = subprocess.run(
            [lark_cli, "config", "init", "--app-id", app_id, "--app-secret-stdin", "--brand", "feishu"],
            input=app_secret.encode("utf-8"),
            capture_output=True,
            timeout=30,
        )
    except Exception as e:
        return False, f"lark-cli config init 异常：{e}"

    if proc.returncode == 0:
        return True, ""
    return False, proc.stderr.decode(errors="replace").strip()[-400:]


def ensure_lark_deps(
    app_id: str = "",
    app_secret: str = "",
    *,
    interactive: bool = False,
    triggered_by: str = "web",
    log: Optional[Callable[[str], None]] = None,
) -> LarkDepsStatus:
    """一站式确保飞书依赖就绪：装 lark-oapi + 装 lark-cli + 同步 app。

    幂等：已装的就跳过，绑定的 app 一致就跳过 sync。

    Args:
        app_id / app_secret: 飞书应用凭证。非空且 lark-cli 未绑定/绑定不一致时才会 sync。
        interactive: True 则在 CLI 控制台打印进度（用 rich console）；False 仅写日志。
        triggered_by: 触发来源标记（"web" / "cli" / "setup" / "plugin"），记入状态。
        log: 可选的日志回调（接收字符串），用于 Web API 收集安装过程信息。

    Returns:
        LarkDepsStatus：最终状态快照。
    """
    global _LATEST_STATUS

    def _emit(msg: str) -> None:
        if log:
            try:
                log(msg)
            except Exception:
                pass
        if interactive:
            try:
                from rich.console import Console
                Console().print(msg)
            except Exception:
                pass
        logger.info("[lark-deps] %s", msg)

    with _INSTALL_LOCK:
        # 初始状态
        status = LarkDepsStatus(
            lark_oapi_installed=_detect_lark_oapi(),
            lark_cli_installed=_detect_lark_cli(),
            lark_cli_app_synced=bool(_lark_cli_current_app()),
            installing=True,
            last_run_at=_now_iso(),
            installed_by=triggered_by,
        )
        _LATEST_STATUS = status
        errors: list[str] = []

        try:
            # 1. lark-oapi 包
            if status.lark_oapi_installed:
                _emit("[dim]✓ lark-oapi 已安装[/dim]")
            else:
                _emit("[yellow]→ 安装 lark-oapi Python 包…[/yellow]")
                ok, err = _pip_install(["lark-oapi"])
                if ok:
                    status.lark_oapi_installed = True
                    _emit("[green]✓ lark-oapi 安装成功[/green]")
                else:
                    errors.append(f"lark-oapi: {err}")
                    _emit(f"[red]✗ lark-oapi 安装失败：{err}[/red]")

            # 2. lark-cli 二进制
            if status.lark_cli_installed:
                _emit("[dim]✓ lark-cli 已安装[/dim]")
            else:
                _emit("[yellow]→ 安装 lark-cli 二进制（brew）…[/yellow]")
                ok, err = _brew_install_lark_cli()
                if ok:
                    status.lark_cli_installed = True
                    _emit("[green]✓ lark-cli 安装成功[/green]")
                else:
                    errors.append(f"lark-cli: {err}")
                    _emit(f"[red]✗ lark-cli 安装失败：\n{err}[/red]")

            # 3. app 同步（仅当 lark-cli 装好且凭证齐全）
            if status.lark_cli_installed and app_id and app_secret:
                current = _lark_cli_current_app()
                if current == app_id:
                    status.lark_cli_app_synced = True
                    status.lark_cli_app_matches = True
                    _emit(f"[dim]✓ lark-cli 已绑定同一应用（{app_id}）[/dim]")
                else:
                    if current:
                        _emit(f"[yellow]⚠ lark-cli 当前绑定的应用是 {current}，需要同步到 {app_id}[/yellow]")
                    else:
                        _emit("[yellow]→ lark-cli 还未绑定任何应用，开始同步…[/yellow]")
                    ok, err = _sync_lark_cli_app(app_id, app_secret)
                    if ok:
                        status.lark_cli_app_synced = True
                        status.lark_cli_app_matches = True
                        _emit(f"[green]✓ lark-cli app 同步成功（{app_id}）[/green]")
                        _emit("[dim]若需用户身份能力（以本人身份发消息），再跑：lark-cli auth login --domain im[/dim]")
                    else:
                        errors.append(f"sync: {err}")
                        _emit(f"[red]✗ lark-cli app 同步失败：{err}[/red]")

            status.last_error = "\n".join(errors)
            return status
        finally:
            status.installing = False
            _LATEST_STATUS = status
