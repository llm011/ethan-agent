"""语音后端（TTS / ASR）探测与一键配置的测试。

核心要锁三条：

1. **非 Apple Silicon 必须拒绝**，且**不能执行任何安装动作**——不能先装几百 MB
   再告诉用户跑不起来。
2. **预检复用 ethan-tts 自己的 doctor**，不另立一套判断标准。
3. **切换后端先校验再写配置**：拿不到可用后端时不能留下脏配置。
"""
from __future__ import annotations

import subprocess

import pytest

from ethan.core import voice_backends as vb


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    monkeypatch.setattr(vb, "_LATEST_SETUP", None)
    yield


# ── 平台判断 ─────────────────────────────────────────────────


def test_is_apple_silicon_true_on_mac_arm(monkeypatch):
    import platform
    import sys

    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(platform, "machine", lambda: "arm64")
    assert vb.is_apple_silicon() is True


@pytest.mark.parametrize(
    "plat,machine",
    [("linux", "x86_64"), ("darwin", "x86_64"), ("win32", "AMD64")],
)
def test_is_apple_silicon_false_elsewhere(monkeypatch, plat, machine):
    import platform
    import sys

    monkeypatch.setattr(sys, "platform", plat)
    monkeypatch.setattr(platform, "machine", lambda: machine)
    assert vb.is_apple_silicon() is False


# ── 非 Apple Silicon：拒绝且零安装 ───────────────────────────


def test_setup_refuses_on_non_apple_silicon_without_installing(monkeypatch):
    """最关键的一条：机器跑不了就立刻拒绝，绝不能先装再报错。"""
    calls: list = []

    def _spy(*a, **kw):
        calls.append(a)
        raise AssertionError("预检失败时不该执行任何子进程")

    monkeypatch.setattr(vb, "is_apple_silicon", lambda: False)
    monkeypatch.setattr(subprocess, "run", _spy)

    result = vb.setup_ethan_tts()
    assert result.ok is False
    assert "Apple Silicon" in result.message
    assert calls == [], "非 Apple Silicon 上执行了安装命令"


def test_probe_rejects_non_apple_silicon_early(monkeypatch):
    """第一层就否掉，不必再往下查 CLI / doctor。"""
    monkeypatch.setattr(vb, "is_apple_silicon", lambda: False)
    monkeypatch.setattr(vb, "_find_cli", lambda *_: pytest.fail("不该去找 CLI"))

    probe = vb.probe_ethan_tts()
    assert probe.available is False
    assert "Apple Silicon" in probe.reason
    assert probe.checks[0].name == "平台"


# ── 未安装 CLI ───────────────────────────────────────────────


def test_probe_reports_missing_cli(monkeypatch):
    monkeypatch.setattr(vb, "is_apple_silicon", lambda: True)
    monkeypatch.setattr(vb, "_find_cli", lambda *a: "")

    probe = vb.probe_ethan_tts()
    assert probe.available is False
    assert "未安装" in probe.reason
    # 要给出可操作的下一步
    fix = next(c for c in probe.checks if c.name == "安装").fix
    assert "pip install" in fix


# ── 复用 ethan-tts doctor ───────────────────────────────────


def test_probe_uses_doctor_checks(monkeypatch):
    """doctor 的检查项要原样带出来，别自己另立判断标准。"""
    monkeypatch.setattr(vb, "is_apple_silicon", lambda: True)
    monkeypatch.setattr(vb, "_find_cli", lambda *a: "/fake/ethan-tts")
    monkeypatch.setattr(vb, "_service_alive", lambda *a, **kw: True)

    payload = {
        "ok": True,
        "checks": [
            {"name": "平台", "status": "ok", "detail": "Darwin arm64", "fix": ""},
            {"name": "依赖", "status": "ok", "detail": "mlx 可用", "fix": ""},
            {"name": "默认模型", "status": "ok", "detail": "已就绪", "fix": ""},
        ],
    }
    import json as _json

    class _P:
        stdout = _json.dumps(payload)
        returncode = 0

    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: _P())

    probe = vb.probe_ethan_tts()
    assert probe.available is True
    assert probe.service_running is True
    names = [c.name for c in probe.checks]
    assert "依赖" in names and "默认模型" in names


def test_probe_not_available_when_doctor_has_error(monkeypatch):
    monkeypatch.setattr(vb, "is_apple_silicon", lambda: True)
    monkeypatch.setattr(vb, "_find_cli", lambda *a: "/fake/ethan-tts")
    monkeypatch.setattr(vb, "_service_alive", lambda *a, **kw: False)

    import json as _json

    class _P:
        stdout = _json.dumps({
            "ok": False,
            "checks": [
                {"name": "依赖", "status": "error", "detail": "mlx 缺失", "fix": "重装"},
            ],
        })
        returncode = 0

    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: _P())
    probe = vb.probe_ethan_tts()
    assert probe.available is False
    assert "依赖" in probe.reason


def test_probe_handles_doctor_crash(monkeypatch):
    """doctor 挂了不能抛异常，要变成一条可读的检查项。"""
    monkeypatch.setattr(vb, "is_apple_silicon", lambda: True)
    monkeypatch.setattr(vb, "_find_cli", lambda *a: "/fake/ethan-tts")
    monkeypatch.setattr(vb, "_service_alive", lambda *a, **kw: False)

    def _boom(*a, **kw):
        raise OSError("exec failed")

    monkeypatch.setattr(subprocess, "run", _boom)
    probe = vb.probe_ethan_tts()
    assert probe.available is False
    assert any(c.name == "自检" and c.status == "error" for c in probe.checks)


# ── ASR 与 TTS 的关系 ────────────────────────────────────────


def test_asr_follows_tts_availability(monkeypatch):
    """ASR 依赖同一个 ethan-tts 安装，TTS 不可用则 ASR 也不可用。"""
    unavailable = vb.BackendProbe(
        backend="ethan-tts", available=False, reason="平台不支持"
    )
    asr = vb.probe_asr(unavailable)
    assert asr.available is False
    assert "平台不支持" in asr.reason


def test_asr_available_when_tts_available():
    ok = vb.BackendProbe(backend="ethan-tts", available=True, service_running=True)
    asr = vb.probe_asr(ok)
    assert asr.available is True


# ── probe_all 结构 ───────────────────────────────────────────


def test_probe_all_shape():
    data = vb.probe_all()
    assert set(data) >= {"tts", "asr", "platform", "python"}
    assert set(data["tts"]) == {"edge-tts", "ethan-tts"}
    assert "apple_silicon" in data["platform"]


def test_edge_tts_always_available():
    """在线后端零安装，任何平台都该可用——它是本地后端不可用时的兜底。"""
    assert vb.probe_edge_tts().available is True


# ── 状态快照 ─────────────────────────────────────────────────


def test_latest_setup_tracks_attempt(monkeypatch):
    monkeypatch.setattr(vb, "is_apple_silicon", lambda: False)
    vb.setup_ethan_tts()
    latest = vb.latest_setup()
    assert latest is not None
    assert latest.backend == "ethan-tts"
    assert latest.ok is False
    assert latest.started_at


# ── 切换后端：先校验，再写配置 ───────────────────────────────


def test_select_refuses_and_keeps_config_when_unavailable(monkeypatch):
    """后端不可用时必须拒绝切换，且**不能改动配置**。

    若先写配置后校验，就会留下「配置指向不可用后端」的脏状态——之后每次朗读/
    识别都失败，用户还不知道为什么。
    """
    import asyncio

    from fastapi import HTTPException

    from ethan.core.config import get_config
    from ethan.interface.routers import tts as tts_router

    cfg = get_config()
    before_tts = cfg.tts.backend

    monkeypatch.setattr(
        vb,
        "probe_all",
        lambda *a, **kw: {
            "tts": {"ethan-tts": {"available": False, "reason": "假装不可用", "checks": []}},
            "asr": {"available": False, "reason": "假装不可用", "checks": []},
        },
    )

    with pytest.raises(HTTPException) as ei:
        asyncio.run(
            tts_router.select_voice_backend(tts_router.VoiceBackendSelect(tts="ethan-tts"))
        )
    assert ei.value.status_code == 409
    assert get_config().tts.backend == before_tts, "配置被污染了"


def test_select_rejects_unknown_backend():
    import asyncio

    from fastapi import HTTPException

    from ethan.interface.routers import tts as tts_router

    with pytest.raises(HTTPException) as ei:
        asyncio.run(
            tts_router.select_voice_backend(tts_router.VoiceBackendSelect(tts="no-such-thing"))
        )
    assert ei.value.status_code == 400


def test_select_accepts_edge_tts_without_probe(monkeypatch):
    """edge-tts 零依赖，切换不该触发任何探测/安装。"""
    import asyncio

    from ethan.core.config import get_config
    from ethan.interface.routers import tts as tts_router

    monkeypatch.setattr(
        vb, "probe_all", lambda *a, **kw: pytest.fail("切到 edge-tts 不该探测")
    )
    out = asyncio.run(
        tts_router.select_voice_backend(tts_router.VoiceBackendSelect(tts="edge-tts"))
    )
    assert out["ok"] is True
    assert get_config().tts.backend == "edge-tts"

    # 复原，避免影响其他用例读到的配置
    cfg = get_config()
    cfg.tts.backend = "ethan-tts"
