"""阅读模式朗读路由（/api/tts）单元测试。

重点覆盖两个曾经踩过的坑：

1. **就绪探测**。早期用 `'"server_running": true' in out.replace(" ", "")` 匹配
   CLI 的 JSON：去掉空格后左边仍有空格，永远匹配不上，表现为「服务明明起来了
   却判定超时」，实测卡满 120 秒。这里钉住「正常 JSON 必须判定为在跑」。
2. **不能在 speak 里同步阻塞事件循环**。拉起服务是同步 subprocess，必须丢到
   线程池；否则整个 API 服务在朗读启动的几秒里完全不响应其他请求。
"""
import json
import subprocess

import pytest

from ethan.interface.routers import tts as tts_router


def _complete(stdout: str, returncode: int = 0):
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr="")


def test_probe_running_parses_json(monkeypatch):
    """带空格的正常 JSON 必须被识别为「在跑」（回归：字符串匹配版本永远 False）。"""
    payload = json.dumps({"url": "http://127.0.0.1:8765", "server_running": True, "models": []}, indent=2)
    monkeypatch.setattr(tts_router.subprocess, "run", lambda *a, **k: _complete(payload))
    assert tts_router._probe_running("ethan-tts") is True


def test_probe_running_false_when_stopped(monkeypatch):
    payload = json.dumps({"server_running": False})
    monkeypatch.setattr(tts_router.subprocess, "run", lambda *a, **k: _complete(payload))
    assert tts_router._probe_running("ethan-tts") is False


def test_probe_running_survives_bad_output(monkeypatch):
    """CLI 输出被污染（比如混进 warning）时报 False，不能把 500 抛给前端。"""
    monkeypatch.setattr(tts_router.subprocess, "run", lambda *a, **k: _complete("not json at all"))
    assert tts_router._probe_running("ethan-tts") is False


def test_probe_running_handles_missing_cli(monkeypatch):
    def boom(*args, **kwargs):
        raise FileNotFoundError

    monkeypatch.setattr(tts_router.subprocess, "run", boom)
    assert tts_router._probe_running("ethan-tts") is False


def test_ensure_server_raises_503_when_cli_missing(monkeypatch):
    """没装 ethan-tts 时给可操作的提示，而不是干等到超时。"""
    def boom(*args, **kwargs):
        raise FileNotFoundError

    monkeypatch.setattr(tts_router.subprocess, "run", boom)
    with pytest.raises(tts_router.HTTPException) as exc:
        tts_router._ensure_server("ethan-tts", deadline=0)
    assert exc.value.status_code == 503
    assert "ethan-tts" in exc.value.detail


def test_ensure_server_returns_once_running(monkeypatch):
    """serve 幂等返回后，只要 state 说在跑就直接放行，不再空转等待。"""
    calls = []

    def fake_run(argv, **kwargs):
        calls.append(argv)
        return _complete(json.dumps({"server_running": True}))

    monkeypatch.setattr(tts_router.subprocess, "run", fake_run)
    tts_router._ensure_server("ethan-tts", deadline=__import__("time").monotonic() + 5)
    assert any("serve" in argv for argv in calls)


def test_speak_request_rejects_empty_text():
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        tts_router.SpeakRequest(text="")


def test_tts_settings_falls_back_to_defaults(monkeypatch):
    """config.yaml 读不到时不能抛，用 CLI 默认值——否则朗读按钮直接不可用。"""
    def boom():
        raise RuntimeError("config broken")

    monkeypatch.setattr(tts_router, "load_config", boom)
    command, voice, base_url = tts_router._tts_settings()
    assert command == tts_router.DEFAULT_CLI
    assert voice == ""
    assert base_url == tts_router.DEFAULT_BASE_URL
