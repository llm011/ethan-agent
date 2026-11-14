"""语音能力的后端管理：TTS / ASR 的探测、预检与一键配置。

## 设计意图

语音能力有两种来源，特点完全不同：

| 后端 | 依赖 | 优点 | 缺点 |
|---|---|---|---|
| edge-tts（在线） | 只有网络 | 零安装、跨平台 | 需要联网，音色/语气控制弱 |
| ethan-tts（本地） | macOS + Apple Silicon + MLX + 模型权重 | 离线、可克隆音色、可调语气 | **只能在 Apple Silicon 上跑** |

所以**不能默认启用本地后端**——大多数用户装不了。但也不能让用户自己折腾：
选了本地后端的人期望的是「点一下就配好」。

本模块的职责：
1. `probe()` —— 只读探测，告诉 UI 每个后端能不能用、为什么不能用
2. `setup()` —— 一键配置：装依赖 → 下模型 → 起服务
3. **预检不过就拒绝**，并给出可操作的原因（不是让用户在十分钟后收到一个语焉不详的失败）

## 为什么复用 ethan-tts 自己的 doctor

ethan-tts 已经有一个写得很好的 `doctor --json`：11 项检查（平台/Python/依赖/
数据目录/模型/服务/ffmpeg），每项都带 `status` + `detail` + **`fix` 建议**。

自己再写一套平台检测只会造成两套判断标准漂移（比如我们以为能跑、它以为不能）。
所以这里只做两件事：调它的 doctor、把结果翻译成配置动作。

## 平台硬约束

`ethan-tts` 依赖 `mlx-audio` + `mlx`，而 MLX 是 Apple 的框架，**只支持 Apple
Silicon**（`sys.platform == "darwin" and platform.machine() == "arm64"`）。
这个判断不需要问 ethan-tts：在装之前就能否掉，省掉用户几十秒的安装等待。
"""
from __future__ import annotations

import json
import logging
import platform
import shutil
import subprocess
import sys
import threading
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# ethan-tts 的 CLI 名与默认服务地址
ETHAN_TTS_CLI = "ethan-tts"
ETHAN_TTS_DEFAULT_URL = "http://127.0.0.1:8765"

# 一键安装用的包名（PyPI / GitHub 二选一，这里用 PyPI，最稳）
ETHAN_TTS_PACKAGE = "ethan-tts"

# 进程级锁：避免 Web 端连点导致并发安装/起服务
_SETUP_LOCK = threading.Lock()
_LATEST_SETUP: Optional["SetupResult"] = None


def is_apple_silicon() -> bool:
    """MLX 的运行前提。非 Apple Silicon 上本地 TTS 一律不可用。"""
    return sys.platform == "darwin" and platform.machine() == "arm64"


@dataclass
class CheckItem:
    name: str
    status: str  # ok | error | warn
    detail: str = ""
    fix: str = ""

    def to_dict(self) -> dict:
        return {"name": self.name, "status": self.status, "detail": self.detail, "fix": self.fix}


@dataclass
class BackendProbe:
    """一个语音后端的可用性快照。"""

    backend: str
    available: bool
    reason: str = ""
    # ethan-tts 特有：可执行文件路径、服务地址、服务是否在跑
    cli_path: str = ""
    service_url: str = ""
    service_running: bool = False
    checks: list[CheckItem] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "backend": self.backend,
            "available": self.available,
            "reason": self.reason,
            "cli_path": self.cli_path,
            "service_url": self.service_url,
            "service_running": self.service_running,
            "checks": [c.to_dict() for c in self.checks],
        }


@dataclass
class SetupResult:
    """一次一键配置的结果。"""

    backend: str = ""
    ok: bool = False
    installing: bool = False
    message: str = ""
    checks: list[CheckItem] = field(default_factory=list)
    started_at: str = ""

    def to_dict(self) -> dict:
        return {
            "backend": self.backend,
            "ok": self.ok,
            "installing": self.installing,
            "message": self.message,
            "checks": [c.to_dict() for c in self.checks],
            "started_at": self.started_at,
        }


# ── 探测 ─────────────────────────────────────────────────────


def _find_cli(explicit: str = "") -> str:
    """找 ethan-tts 可执行文件。

    除了 PATH，还要看 uv tool / pipx 的常见位置——服务进程由 launchd 拉起时
    PATH 很短（这个坑在多内核那边已经踩过一次，见 ethan/kernel/deps.py）。
    """
    if explicit:
        return explicit if Path(explicit).exists() else ""
    found = shutil.which(ETHAN_TTS_CLI)
    if found:
        return found
    for cand in (
        "~/.local/bin/ethan-tts",
        "/opt/homebrew/bin/ethan-tts",
        "/usr/local/bin/ethan-tts",
    ):
        p = Path(cand).expanduser()
        if p.exists():
            return str(p)
    return ""


def _service_alive(url: str, timeout: float = 1.5) -> bool:
    import urllib.error
    import urllib.request

    try:
        with urllib.request.urlopen(f"{url.rstrip('/')}/health", timeout=timeout):
            return True
    except (urllib.error.URLError, OSError, ValueError):
        return False


def probe_edge_tts() -> BackendProbe:
    """在线后端：只需要能连网，没有本地依赖。"""
    return BackendProbe(
        backend="edge-tts",
        available=True,
        reason="",
        checks=[CheckItem("依赖", "ok", "在线服务，无需本地安装")],
    )


def probe_ethan_tts(cli_hint: str = "", base_url: str = "") -> BackendProbe:
    """本地后端：平台 → CLI → doctor 逐层查，任一层不过就明确拒绝。"""
    url = (base_url or ETHAN_TTS_DEFAULT_URL).rstrip("/")

    # 第一层：平台。这一层不通过就没必要往下查了，也省得用户白装一次。
    if not is_apple_silicon():
        return BackendProbe(
            backend="ethan-tts",
            available=False,
            reason=(
                f"当前平台是 {platform.system()} {platform.machine()}，"
                "本地语音合成依赖 MLX，仅支持 Apple Silicon（M 系列芯片 mac）"
            ),
            service_url=url,
            checks=[
                CheckItem(
                    "平台",
                    "error",
                    f"{platform.system()} {platform.machine()}",
                    "本地 TTS 不可用；改用 edge-tts（在线）作为语音后端",
                )
            ],
        )

    cli = _find_cli(cli_hint)
    if not cli:
        return BackendProbe(
            backend="ethan-tts",
            available=False,
            reason="未安装 ethan-tts CLI",
            service_url=url,
            checks=[
                CheckItem("平台", "ok", f"{platform.system()} {platform.machine()}"),
                CheckItem(
                    "安装",
                    "error",
                    "找不到 ethan-tts 命令",
                    f"点「一键配置」自动安装（pip install {ETHAN_TTS_PACKAGE}）",
                ),
            ],
        )

    checks: list[CheckItem] = [CheckItem("安装", "ok", cli)]

    # 关键判断顺序：**先看服务活没活**，再决定要不要信 doctor 的结论。
    #
    # 原因：用户常自配 `tts.command`（比如一个只实现 `say` 子命令的自制 shim
    # ——实测踩到：`ethan-tts-rest` 收到 doctor 会 exit=2）。这种 shim 完全能
    # 正常合成，只是不实现自检命令。若把 doctor 当唯一判据，会把「明明能用」
    # 的后端判成不可用，进而拒绝用户切换到它。
    running = _service_alive(url)

    doctor_unavailable = False
    try:
        # ethan-tts doctor --json 输出结构化检查结果，尽量复用它的判断标准，
        # 避免我们和它各有一套「能跑吗」的定义。
        proc = subprocess.run(
            [cli, "doctor", "--json"],
            capture_output=True,
            text=True,
            timeout=60,
        )
        data = json.loads(proc.stdout or "{}")
        raw_checks = data.get("checks") or []
        if not raw_checks:
            # 没有 checks 数组（自制 shim / 版本差异）→ 不是「检查失败」，
            # 而是「这个 CLI 不支持自检」。这种情况下别拿它当判据。
            doctor_unavailable = True
            checks.append(
                CheckItem(
                    "自检",
                    "warn",
                    str(data.get("error") or "该 CLI 不支持 doctor 子命令"),
                    "自检不可用，改用服务连通性判断",
                )
            )
        for raw in raw_checks:
            item = CheckItem(
                name=str(raw.get("name", "")),
                status=str(raw.get("status", "")),
                detail=str(raw.get("detail", "")),
                fix=str(raw.get("fix", "")),
            )
            checks.append(item)
    except (subprocess.SubprocessError, json.JSONDecodeError, OSError) as e:
        # 同上的道理：自检跑不起来 ≠ 后端不能用
        doctor_unavailable = True
        checks.append(CheckItem("自检", "warn", f"doctor 未执行：{e}", "改用服务连通性判断"))

    failed = [c for c in checks if c.status == "error"]

    # 可用性判定：
    #   · doctor 明确报错 → 不可用（有具体检查项失败，可信）
    #   · doctor 不可用（不支持/崩了）→ **以服务是否活着为准**
    #   · 都没问题 → 可用
    if failed:
        available = False
        reason = f"{len(failed)} 项检查未通过：{failed[0].name}（{failed[0].detail}）"
    elif doctor_unavailable:
        available = running
        reason = "" if running else "自检不可用，且服务未启动（试试点「一键配置」）"
    else:
        available = True
        reason = ""

    # 服务没跑但 doctor 说环境没问题 → 仍然算可用（能一键拉起）
    return BackendProbe(
        backend="ethan-tts",
        available=available,
        reason=reason,
        cli_path=cli,
        service_url=url,
        service_running=running,
        checks=checks,
    )


def probe_all(cli_hint: str = "", base_url: str = "") -> dict:
    """TTS 两个后端 + ASR 的可用性总览（供设置页渲染）。"""
    tts_local = probe_ethan_tts(cli_hint, base_url)
    return {
        "tts": {
            "edge-tts": probe_edge_tts().to_dict(),
            "ethan-tts": tts_local.to_dict(),
        },
        "asr": probe_asr(tts_local).to_dict(),
        "platform": {
            "system": platform.system(),
            "machine": platform.machine(),
            "apple_silicon": is_apple_silicon(),
        },
        "python": sys.version.split()[0],
    }


# ── ASR ──────────────────────────────────────────────────────


def probe_asr(tts_probe: BackendProbe) -> BackendProbe:
    """ASR 探测。

    当前只有一个可选后端：ethan-tts 内置的本地识别（`stt.py` + ASR_MODELS）。
    它和 TTS 共用同一个 ethan-tts 安装与 MLX 运行时，所以可用性判断可以直接复用
    TTS 的探测结果——没必要再跑一次 doctor。

    做成独立函数而不是合并进 TTS，是因为后续要加云端 ASR（DeepSeek ASR 等）
    时，这里就是挂载点，调用方不需要改。
    """
    if not tts_probe.available:
        return BackendProbe(
            backend="ethan-tts",
            available=False,
            reason=f"本地语音识别依赖 ethan-tts：{tts_probe.reason}",
            service_url=tts_probe.service_url,
            checks=tts_probe.checks,
        )
    return BackendProbe(
        backend="ethan-tts",
        available=True,
        cli_path=tts_probe.cli_path,
        service_url=tts_probe.service_url,
        service_running=tts_probe.service_running,
        checks=tts_probe.checks,
    )


# ── 一键配置 ─────────────────────────────────────────────────


def setup_ethan_tts(
    *,
    auto_start: bool = True,
    on_log: Optional[callable] = None,
    timeout: int = 900,
) -> SetupResult:
    """一键配置本地语音后端：预检 → 安装 → 下载模型 → 起服务。

    **预检不过直接返回失败，不执行安装**。理由：本地 TTS 的安装要下 MLX 和几百 MB
    模型权重，在注定跑不起来的机器上装完再报错，用户白等十几分钟还得不到有效信息。
    先花 0 秒告诉他「你这台机器不行」才是对的。

    幂等：装好了就跳过安装，只补缺失环节（比如服务没起）。
    """
    global _LATEST_SETUP

    result = SetupResult(
        backend="ethan-tts",
        started_at=datetime.now().isoformat(timespec="seconds"),
    )

    def _log(msg: str) -> None:
        logger.info("[tts-setup] %s", msg)
        if on_log:
            try:
                on_log(msg)
            except Exception:  # noqa: BLE001 - 日志回调不该影响流程
                pass

    # ① 平台预检：不能跑就别装
    if not is_apple_silicon():
        result.ok = False
        result.message = (
            f"无法在此机器上运行本地语音合成：当前是 {platform.system()} "
            f"{platform.machine()}，MLX 只支持 Apple Silicon。"
            "建议改用 edge-tts（在线后端，零安装）。"
        )
        result.checks = [CheckItem("平台", "error", platform.machine(), "改用 edge-tts")]
        _LATEST_SETUP = result
        _log(result.message)
        return result

    with _SETUP_LOCK:
        # ② 已装则跳过安装
        probe = probe_ethan_tts()
        if probe.available:
            result.checks = probe.checks
            _log("ethan-tts 已就绪，跳过安装")
        else:
            result.installing = True
            _LATEST_SETUP = result

            # 还没装 CLI：先装包
            if not probe.cli_path:
                _log(f"安装 {ETHAN_TTS_PACKAGE} ...")
                if not _pip_install_ethan_tts(_log, timeout):
                    result.installing = False
                    result.ok = False
                    result.message = (
                        f"安装 {ETHAN_TTS_PACKAGE} 失败。可手动执行："
                        f"pip install {ETHAN_TTS_PACKAGE}"
                    )
                    _LATEST_SETUP = result
                    return result
                probe = probe_ethan_tts()
                result.checks = probe.checks
                if not probe.available:
                    result.installing = False
                    result.ok = False
                    result.message = probe.reason or "安装后自检仍未通过"
                    _LATEST_SETUP = result
                    return result

            result.installing = False

        # ③ 模型权重：ethan-tts 的 setup 会检查并下载
        cli = probe.cli_path
        if cli:
            _log("检查模型权重 ...")
            try:
                subprocess.run(
                    [cli, "setup"],
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                )
            except (subprocess.SubprocessError, OSError) as e:
                _log(f"setup 执行异常（继续尝试起服务）：{e}")

        # ④ 起服务
        if auto_start and cli:
            probe_now = probe_ethan_tts()
            if not probe_now.service_running:
                _log("启动本地语音服务 ...")
                try:
                    subprocess.run(
                        [cli, "serve", "--background"] if _supports_background(cli) else [cli, "serve"],
                        capture_output=True,
                        text=True,
                        timeout=120,
                    )
                except (subprocess.SubprocessError, OSError) as e:
                    _log(f"起服务异常：{e}")

        final = probe_ethan_tts()
        result.ok = final.available
        result.checks = final.checks
        result.message = (
            "本地语音后端已就绪"
            if final.available
            else (final.reason or "配置未完成")
        )
        _LATEST_SETUP = result
        _log(result.message)
        return result


def _supports_background(cli: str) -> bool:
    """ethan-tts serve 是否支持 --background（不同版本可能不同）。"""
    try:
        proc = subprocess.run([cli, "serve", "--help"], capture_output=True, text=True, timeout=15)
        return "--background" in (proc.stdout or "")
    except (subprocess.SubprocessError, OSError):
        return False


def _pip_install_ethan_tts(on_log: callable, timeout: int) -> bool:
    """装 ethan-tts。优先 uv（快且隔离），退回 pip。"""
    uv = shutil.which("uv") or str(Path.home() / ".local/bin/uv")
    if Path(uv).exists():
        cmd = [uv, "tool", "install", ETHAN_TTS_PACKAGE]
    else:
        cmd = [sys.executable, "-m", "pip", "install", ETHAN_TTS_PACKAGE]
    on_log(f"执行：{' '.join(cmd)}")
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        on_log(f"安装超时（{timeout}s）")
        return False
    except OSError as e:
        on_log(f"安装失败：{e}")
        return False
    if proc.returncode != 0:
        tail = (proc.stderr or "").strip().splitlines()[-3:]
        on_log("安装失败：" + " / ".join(tail))
        return False
    return True


def latest_setup() -> Optional[SetupResult]:
    return _LATEST_SETUP
