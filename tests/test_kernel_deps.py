r"""内核依赖「按需安装」的测试。

核心行为要锁两条：

1. **默认不安装**：仅仅是注册/列出内核，绝不能触发任何 npm install。
2. **选中才安装**：用户选了一个缺依赖的内核 → 自动装；装失败 → **不写配置**，
   保留原内核并告知原因（不能留下「配置指向不可用内核」的脏状态）。
"""
from __future__ import annotations

import subprocess

import pytest

from ethan.kernel import deps as kdeps
from ethan.kernel.runtime import KernelKind


@pytest.fixture(autouse=True)
def _reset_deps_state(monkeypatch):
    """每个用例重置模块级状态，避免相互污染。"""
    monkeypatch.setattr(kdeps, "_LATEST", None)
    yield


# ── 依赖表完整性 ─────────────────────────────────────────────


def test_every_external_kind_has_deps_spec():
    """新增内核类型时必须同时声明依赖，否则「选中即安装」对它无效。"""
    for kind in KernelKind:
        if kind == KernelKind.ETHAN:
            continue
        assert kind in kdeps.KERNEL_DEPS, f"{kind.value} 缺少 KernelDepsSpec"


def test_deps_specs_have_install_command():
    for kind, spec in kdeps.KERNEL_DEPS.items():
        assert spec.install_cmd, f"{kind.value} 没有安装命令"
        assert spec.binary, f"{kind.value} 没有探测用的 binary"


def test_detect_ethan_always_available():
    """原生内核没有外部依赖，永远可用。"""
    ok, reason = kdeps.detect(KernelKind.ETHAN)
    assert ok is True
    assert reason == ""


# ── 默认不装 ─────────────────────────────────────────────────


def test_listing_kernels_does_not_install(monkeypatch):
    """获取内核列表只是探测，绝不能触发安装。"""
    called = []

    def _boom(*a, **kw):
        called.append(a)
        raise AssertionError("list_status / all_deps_status 不该触发安装")

    monkeypatch.setattr(subprocess, "run", _boom)

    from ethan.kernel.runtime import get_kernel_registry, reset_kernel_registry

    reset_kernel_registry()
    reg = get_kernel_registry()
    _ = reg.list_status()
    _ = kdeps.all_deps_status()
    assert called == []


def test_registry_import_does_not_install(monkeypatch):
    """连导入内核模块都不该跑安装命令。"""
    called = []
    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: called.append(a))

    from ethan.kernel.runtime import reset_kernel_registry

    reset_kernel_registry()
    from ethan.kernel.dsh_kernel import DSHKernel  # noqa: F401
    from ethan.kernel.pi_kernel import PiKernel  # noqa: F401

    assert called == []


# ── 已安装时幂等 ─────────────────────────────────────────────


def test_ensure_installed_skips_when_present(monkeypatch):
    """已装就直接返回，不重复 npm install。"""
    called = []
    monkeypatch.setattr(kdeps, "detect", lambda kind: (True, ""))
    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: called.append(a))

    status = kdeps.ensure_installed(KernelKind.CLAUDE_CODE)
    assert status.installed is True
    assert called == [], "已安装时不该执行安装命令"


def test_ensure_installed_ethan_is_noop(monkeypatch):
    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: pytest.fail("原生内核不该安装"))
    status = kdeps.ensure_installed(KernelKind.ETHAN)
    assert status.installed is True


# ── 缺失时自动安装 ───────────────────────────────────────────


class _Proc:
    def __init__(self, returncode=0, stderr=""):
        self.returncode = returncode
        self.stderr = stderr
        self.stdout = ""


def test_ensure_installed_runs_install_command(monkeypatch):
    """未装 → 真的执行安装命令，装完重新探测。"""
    state = {"installed": False}
    called = []

    def _fake_detect(kind):
        return (state["installed"], "" if state["installed"] else "未安装")

    def _fake_run(cmd, **kw):
        called.append(cmd)
        state["installed"] = True  # 模拟安装成功
        return _Proc()

    monkeypatch.setattr(kdeps, "detect", _fake_detect)
    monkeypatch.setattr(subprocess, "run", _fake_run)

    status = kdeps.ensure_installed(KernelKind.DSH)
    assert status.installed is True
    assert len(called) == 1
    assert "install" in called[0] and "-g" in called[0]
    assert "@deepseek-ai/dsh" in called[0]


def test_install_failure_reports_error(monkeypatch):
    monkeypatch.setattr(kdeps, "detect", lambda kind: (False, "未安装"))
    monkeypatch.setattr(
        subprocess, "run", lambda cmd, **kw: _Proc(returncode=1, stderr="boom\nfailed")
    )

    status = kdeps.ensure_installed(KernelKind.CLAUDE_CODE)
    assert status.installed is False
    assert "安装失败" in status.last_error
    assert status.installing is False


def test_permission_error_gives_actionable_hint(monkeypatch):
    """npm EACCES 时不能只说失败，要给出不用 sudo 的解法。"""
    monkeypatch.setattr(kdeps, "detect", lambda kind: (False, "未安装"))
    monkeypatch.setattr(
        subprocess, "run",
        lambda cmd, **kw: _Proc(returncode=1, stderr="npm ERR! EACCES permission denied"),
    )

    status = kdeps.ensure_installed(KernelKind.CLAUDE_CODE)
    assert "npm config set prefix" in status.last_error
    assert "sudo" in status.last_error


def test_missing_npm_gives_manual_command(monkeypatch):
    """连 npm 都没有时，把确切命令给用户，而不是抛 FileNotFoundError。"""
    monkeypatch.setattr(kdeps, "detect", lambda kind: (False, "未安装"))

    def _no_npm(cmd, **kw):
        raise FileNotFoundError("npm")

    monkeypatch.setattr(subprocess, "run", _no_npm)
    status = kdeps.ensure_installed(KernelKind.CLAUDE_CODE)
    assert status.installed is False
    assert "npm install -g" in status.last_error


def test_install_timeout(monkeypatch):
    monkeypatch.setattr(kdeps, "detect", lambda kind: (False, "未安装"))

    def _timeout(cmd, **kw):
        raise subprocess.TimeoutExpired(cmd, 1)

    monkeypatch.setattr(subprocess, "run", _timeout)
    status = kdeps.ensure_installed(KernelKind.CLAUDE_CODE, timeout=1)
    assert status.installed is False
    assert "超时" in status.last_error


def test_install_success_but_binary_still_missing(monkeypatch):
    """装完仍找不到 binary（PATH 没生效）要给明确提示，不能假装成功。"""
    monkeypatch.setattr(kdeps, "detect", lambda kind: (False, "不在 PATH"))
    monkeypatch.setattr(subprocess, "run", lambda cmd, **kw: _Proc())

    status = kdeps.ensure_installed(KernelKind.OPENCODE)
    assert status.installed is False
    assert "PATH" in status.last_error


# ── 状态快照 ─────────────────────────────────────────────────


def test_latest_status_tracks_attempt(monkeypatch):
    monkeypatch.setattr(kdeps, "detect", lambda kind: (True, ""))
    kdeps.ensure_installed(KernelKind.CLAUDE_CODE)
    latest = kdeps.latest_status()
    assert latest is not None
    assert latest.kind == "claude_code"
    assert latest.installed is True
    assert latest.last_run_at


def test_all_deps_status_shape():
    rows = kdeps.all_deps_status()
    assert rows
    for row in rows:
        assert set(row) >= {
            "kind", "binary", "installed", "reason", "install_command", "hint",
        }


# ── PATH 探测：daemon 进程看不到交互 shell 的 PATH ─────────────────


def test_locate_finds_binary_outside_process_path(monkeypatch, tmp_path):
    """核心场景：服务进程 PATH 很短，但 CLI 装在 ~/.npm-global/bin 之类的目录。

    真实踩到过：命令行 `which claude` 正常，Web UI 却显示「未安装」——
    因为 `ethan serve` 被 launchd 拉起，PATH 里没有 nvm / npm-global。
    """
    import os

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    exe = fake_bin / "pi"
    exe.write_text("#!/bin/sh\necho ok\n")
    exe.chmod(0o755)

    # 进程 PATH 里没有它
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    # 候选目录只留我们的临时目录（否则会搜到开发者机器上真实的 pi）
    monkeypatch.setattr(kdeps, "_COMMON_BIN_DIRS", (str(fake_bin),))
    monkeypatch.setattr(kdeps, "_NVM_GLOB", str(tmp_path / "nope" / "*" / "bin"))

    assert kdeps.locate(KernelKind.PI) == str(exe)
    # 找到后必须把目录补进 PATH，否则后续 subprocess 起不来
    assert str(fake_bin) in os.environ["PATH"]


def test_locate_returns_none_when_really_missing(monkeypatch, tmp_path):
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    monkeypatch.setattr(kdeps, "_COMMON_BIN_DIRS", (str(tmp_path),))
    monkeypatch.setattr(kdeps, "_NVM_GLOB", str(tmp_path / "nope" / "*" / "bin"))
    assert kdeps.locate(KernelKind.PI) is None


def test_locate_finds_non_executable_file_as_missing(monkeypatch, tmp_path):
    """不是可执行文件的同名文件不能被当成 CLI。"""
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    (fake_bin / "pi").write_text("data")  # 无执行权限
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    monkeypatch.setattr(kdeps, "_COMMON_BIN_DIRS", (str(fake_bin),))
    monkeypatch.setattr(kdeps, "_NVM_GLOB", str(tmp_path / "nope" / "*" / "bin"))
    assert kdeps.locate(KernelKind.PI) is None


# ── Codex 内核：不能覆盖用户自己的 provider 配置 ──────────────


def test_codex_kernel_skips_provider_override(monkeypatch):
    """ACP 的 codex 层会强制改 provider（为委派场景设计）。

    作为**内核**用时必须尊重用户 ~/.codex/config.toml 里的配置，
    否则会报 `unknown provider for model gpt-5.5`（实测踩到）。
    """

    from ethan.acp.agent_codex import _codex_provider_overrides

    monkeypatch.delenv("ETHAN_CODEX_NO_PROVIDER_OVERRIDE", raising=False)
    monkeypatch.setenv("ETHAN_CODEX_NO_PROVIDER_OVERRIDE", "1")
    args, env, model = _codex_provider_overrides()
    assert args == [], "内核模式不该注入 provider 覆盖参数"
    assert env == {}
    assert model == ""


def test_codex_kernel_restores_env_after_run(monkeypatch):
    """跑完要恢复原值——委派工具（delegate_coding）还要用覆盖逻辑。"""
    import os

    from ethan.kernel.acp_kernel import CodexKernel
    from ethan.kernel.runtime import KernelRequest

    monkeypatch.delenv("ETHAN_CODEX_NO_PROVIDER_OVERRIDE", raising=False)

    captured = {}

    async def _fake_super_run(self, request, context=None):
        captured["during"] = os.environ.get("ETHAN_CODEX_NO_PROVIDER_OVERRIDE")
        yield "ok"

    monkeypatch.setattr(
        "ethan.kernel.claude_kernel.ACPKernelBase.run", _fake_super_run
    )

    async def go():
        return [e async for e in CodexKernel().run(KernelRequest())]

    import asyncio

    assert asyncio.run(go()) == ["ok"]
    assert captured["during"] == "1", "执行期间必须置位"
    assert "ETHAN_CODEX_NO_PROVIDER_OVERRIDE" not in os.environ, "执行完必须清理"


# ── working_dir：绝不能是根目录 ────────────────────────────


def test_kernel_working_dir_never_empty_when_workspace_set():
    """进程 cwd 是 "/" 时（launchd 拉起的常见情况），外部 CLI 会失败。

    实测：codex 报 `Not inside a trusted directory`。所以必须兜到 workspace。
    """
    from ethan.interface.routers.producers import _kernel_working_dir

    class _Agent:
        _working_dir = ""

    wd = _kernel_working_dir(_Agent())
    assert wd, "不应返回空串（会让外部 CLI 落到 /）"
    assert wd != "/"
