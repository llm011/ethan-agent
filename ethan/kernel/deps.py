"""内核依赖的按需安装。

## 设计原则

**默认不装任何外部内核依赖。** 只有用户明确选中某个内核时，才触发对应 CLI 的安装。

理由：
- 外部内核依赖（`@anthropic-ai/claude-code`、`@deepseek-ai/dsh` 等）动辄几十上百 MB，
  每个用户都要装一遍纯属浪费——多数人只会用原生内核。
- 这些 CLI 还会各自维护自己的配置目录、凭证、会话库，装了就留下痕迹。
- 但**不能让用户自己去敲命令**：选了却因为没装而报错，是最差的体验。

所以流程是：用户在内核选择器里选中 → 后端检测缺失 → 自动安装 → 安装完重新检测
→ 可用则切换成功，失败则明确告诉用户原因并留在原内核。

参考 `ethan/interface/channels/lark/deps.py` 的模式（检测 → 装 → 状态快照 →
进程级锁防并发）。

## 安装方式

| 内核 | 命令 |
|---|---|
| claude_code | `npm install -g @anthropic-ai/claude-code` |
| dsh | `npm install -g @deepseek-ai/dsh` |
| codex | `npm install -g @openai/codex` |
| opencode | curl 脚本（官方安装方式） |
| pi | `npm install -g @mariozechner/pi-coding-agent` |

npm 全局安装可能需要 sudo（取决于 node prefix）。我们不擅自提权——检测到
权限错误时把确切命令给用户，由用户决定。
"""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
import threading
from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Optional

from ethan.kernel.runtime import KernelKind

logger = logging.getLogger(__name__)

# 进程级锁：Web 端可能连点多次/多端同时选内核，串行化避免重复 npm install
_INSTALL_LOCK = threading.Lock()

_LATEST: Optional["KernelDepsStatus"] = None


@dataclass
class KernelDepsSpec:
    """一个内核的依赖描述。"""

    kind: KernelKind
    # 用于 available() 探测的命令名
    binary: str
    # 安装命令（列表形式，直接喂 subprocess）
    install_cmd: list[str]
    # 给用户看的安装说明（失败时展示）
    hint: str = ""
    # 安装后需要额外做的事（如 opencode 装完在 ~/.opencode/bin，不在 PATH）
    extra_paths: tuple[str, ...] = ()


KERNEL_DEPS: dict[KernelKind, KernelDepsSpec] = {
    KernelKind.CLAUDE_CODE: KernelDepsSpec(
        kind=KernelKind.CLAUDE_CODE,
        binary="claude",
        install_cmd=["npm", "install", "-g", "@anthropic-ai/claude-code"],
        hint="需要 Node.js 与 npm",
    ),
    KernelKind.DSH: KernelDepsSpec(
        kind=KernelKind.DSH,
        binary="dsh",
        install_cmd=["npm", "install", "-g", "@deepseek-ai/dsh"],
        hint="需要 Node.js 与 npm；装好后还需配置 provider 凭证",
    ),
    KernelKind.CODEX: KernelDepsSpec(
        kind=KernelKind.CODEX,
        binary="codex",
        install_cmd=["npm", "install", "-g", "@openai/codex"],
        hint="需要 Node.js 与 npm，并已登录 OpenAI 账号",
    ),
    KernelKind.OPENCODE: KernelDepsSpec(
        kind=KernelKind.OPENCODE,
        binary="opencode",
        install_cmd=[
            "bash",
            "-lc",
            "curl -fsSL https://opencode.ai/install | bash",
        ],
        hint="官方安装脚本会装到 ~/.opencode/bin",
        extra_paths=("~/.opencode/bin",),
    ),
    KernelKind.PI: KernelDepsSpec(
        kind=KernelKind.PI,
        binary="pi",
        install_cmd=["npm", "install", "-g", "@mariozechner/pi-coding-agent"],
        hint="需要 Node.js 与 npm",
    ),
}


@dataclass
class KernelDepsStatus:
    """一次安装尝试的结果快照，供 Web API 查询。"""

    kind: str = ""
    installed: bool = False
    installing: bool = False
    last_error: str = ""
    last_run_at: str = ""
    install_command: str = ""
    hint: str = ""

    def to_dict(self) -> dict:
        return {
            "kind": self.kind,
            "installed": self.installed,
            "installing": self.installing,
            "last_error": self.last_error,
            "last_run_at": self.last_run_at,
            "install_command": self.install_command,
            "hint": self.hint,
        }


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


# 外部 CLI 的常见安装位置。
#
# 为什么必须自己找而不能只信 `shutil.which`：**服务进程的 PATH 和我们交互式 shell
# 的 PATH 不一样**。`ethan serve` 常由 launchd / systemd / watchdog 拉起，PATH 往往只有
# /usr/bin:/bin:/opt/homebrew/bin 这几条，而 npm 全局包在 ~/.npm-global/bin、
# nvm 管理的 node 在 ~/.nvm/versions/node/<ver>/bin、opencode 在 ~/.opencode/bin。
#
# 实测踩到过：命令行里 `which claude` 正常，但 Web UI 的内核列表显示「未安装」——
# 因为服务进程根本看不到那个目录。这会让用户以为装失败，然后重复安装。
_COMMON_BIN_DIRS: tuple[str, ...] = (
    "~/.npm-global/bin",
    "~/.local/bin",
    "~/.bun/bin",
    "~/.opencode/bin",
    "~/.volta/bin",
    "~/.pnpm-global/bin",
    "/opt/homebrew/bin",
    "/usr/local/bin",
)

# nvm 的目录带版本号，需要 glob 展开
_NVM_GLOB = "~/.nvm/versions/node/*/bin"


def _candidate_dirs() -> list[str]:
    """所有可能藏着外部 CLI 的目录（已展开、去重、只保留存在的）。"""
    import glob

    out: list[str] = []
    for raw in _COMMON_BIN_DIRS:
        d = os.path.expanduser(raw)
        if os.path.isdir(d):
            out.append(d)
    for d in glob.glob(os.path.expanduser(_NVM_GLOB)):
        if os.path.isdir(d):
            out.append(d)
    # 版本号大的排前面（新版本优先），避免同时装了 v22/v24 时命中旧的
    out.sort(key=lambda p: ("node" in p, p), reverse=True)
    seen: set[str] = set()
    uniq: list[str] = []
    for d in out:
        if d not in seen:
            seen.add(d)
            uniq.append(d)
    return uniq


def _with_extra_paths(spec: KernelDepsSpec) -> None:
    """把内核自带的与常见的 bin 目录补进当前进程 PATH。

    这不仅是探测需要——找到之后**必须真的写进 os.environ["PATH"]**，
    否则后面 `subprocess` 起 CLI 时照样找不到可执行文件。
    """
    wanted: list[str] = []
    for p in spec.extra_paths:
        wanted.append(os.path.expanduser(p))
    wanted.extend(_candidate_dirs())

    cur = os.environ.get("PATH", "")
    cur_parts = cur.split(os.pathsep)
    prepend = [d for d in wanted if os.path.isdir(d) and d not in cur_parts]
    if prepend:
        os.environ["PATH"] = os.pathsep.join(prepend + [cur])


def locate(kind: KernelKind) -> str | None:
    """定位内核 CLI 的绝对路径；找不到返回 None。

    先用补全后的 PATH 走 `shutil.which`，再逐个候选目录直接找文件——后者能兜住
    「目录在候选表里但没进 PATH」的情况（`_with_extra_paths` 有幂等判断，
    理论上已经补过，这里再兜一层）。
    """
    spec = KERNEL_DEPS.get(kind)
    if spec is None:
        return None
    _with_extra_paths(spec)

    found = shutil.which(spec.binary)
    if found:
        return found

    for d in _candidate_dirs():
        cand = os.path.join(d, spec.binary)
        if os.path.isfile(cand) and os.access(cand, os.X_OK):
            # 找到了顺手把这个目录放进 PATH，供后续子进程启动
            cur = os.environ.get("PATH", "")
            if d not in cur.split(os.pathsep):
                os.environ["PATH"] = d + os.pathsep + cur
            return cand
    return None


def detect(kind: KernelKind) -> tuple[bool, str]:
    """检测内核 CLI 是否可用。返回 (可用, 原因)。"""
    spec = KERNEL_DEPS.get(kind)
    if spec is None:
        return True, ""  # 无依赖声明的内核（如原生）永远可用

    if locate(kind) is None:
        return False, f"未安装 {spec.binary}（{spec.hint}）" if spec.hint else f"未安装 {spec.binary}"
    return True, ""


def ensure_installed(
    kind: KernelKind | str,
    *,
    on_log: Callable[[str], None] | None = None,
    timeout: int = 300,
) -> KernelDepsStatus:
    """确保内核依赖就绪；缺失则**自动安装**。

    这是「用户选了就触发安装」的落点。调用方（Web 路由 / CLI）只需调它一次。

    幂等：已安装直接返回成功，不重复 npm install。
    并发安全：进程级锁，多端同时触发只会真装一次。
    """
    global _LATEST

    kind_enum = KernelKind.parse(kind)
    spec = KERNEL_DEPS.get(kind_enum)
    status = KernelDepsStatus(
        kind=kind_enum.value,
        last_run_at=_now_iso(),
        install_command=" ".join(spec.install_cmd) if spec else "",
        hint=spec.hint if spec else "",
    )

    if spec is None:
        # 原生内核没有外部依赖
        status.installed = True
        _LATEST = status
        return status

    ok, _reason = detect(kind_enum)
    if ok:
        status.installed = True
        _LATEST = status
        return status

    def _log(msg: str) -> None:
        logger.info("[kernel-install] %s", msg)
        if on_log:
            try:
                on_log(msg)
            except Exception:  # noqa: BLE001 - 日志回调不该影响安装
                pass

    with _INSTALL_LOCK:
        # 拿到锁后重新检测：可能等待期间别的请求已经装好了
        ok, _reason = detect(kind_enum)
        if ok:
            status.installed = True
            _LATEST = status
            return status

        status.installing = True
        _LATEST = status
        _log(f"开始安装 {kind_enum.value}: {' '.join(spec.install_cmd)}")

        try:
            proc = subprocess.run(
                spec.install_cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except FileNotFoundError:
            status.installing = False
            status.last_error = (
                f"找不到 {spec.install_cmd[0]} 命令。{spec.hint or ''} "
                f"请手动执行：{' '.join(spec.install_cmd)}"
            )
            _LATEST = status
            _log(status.last_error)
            return status
        except subprocess.TimeoutExpired:
            status.installing = False
            status.last_error = f"安装超时（{timeout}s）。可手动执行：{' '.join(spec.install_cmd)}"
            _LATEST = status
            _log(status.last_error)
            return status

        status.installing = False

        if proc.returncode != 0:
            stderr = (proc.stderr or "").strip()
            # npm 全局安装常见的权限问题：给出可操作的建议，不擅自 sudo
            if "EACCES" in stderr or "permission denied" in stderr.lower():
                status.last_error = (
                    "npm 全局安装权限不足。可选择：\n"
                    "  · 配置 npm 全局目录到用户目录（推荐）："
                    "npm config set prefix ~/.npm-global\n"
                    f"  · 或用管理员权限手动执行：sudo {' '.join(spec.install_cmd)}"
                )
            else:
                tail = stderr.splitlines()[-3:] if stderr else []
                status.last_error = (
                    f"安装失败（exit={proc.returncode}）"
                    + ("：" + " / ".join(tail) if tail else "")
                )
            _LATEST = status
            _log(status.last_error)
            return status

        # 装完重新探测：有的 CLI 装到非 PATH 目录，需要 extra_paths 兜住
        ok, reason = detect(kind_enum)
        status.installed = ok
        if not ok:
            status.last_error = (
                f"安装命令成功但找不到 {spec.binary}。{reason or ''} "
                f"可能需要重启终端让 PATH 生效。"
            )
        _LATEST = status
        _log(f"{kind_enum.value} 安装{'成功' if ok else '后仍不可用'}")
        return status


def latest_status() -> KernelDepsStatus | None:
    """最近一次安装尝试的状态（供 UI 轮询进度）。"""
    return _LATEST


def all_deps_status() -> list[dict]:
    """所有外部内核的依赖就绪状态。"""
    out = []
    for kind, spec in KERNEL_DEPS.items():
        ok, reason = detect(kind)
        out.append({
            "kind": kind.value,
            "binary": spec.binary,
            "installed": ok,
            "reason": reason,
            "install_command": " ".join(spec.install_cmd),
            "hint": spec.hint,
        })
    return out
