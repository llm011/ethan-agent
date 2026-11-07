"""TTS 路由 — 阅读模式的「朗读」按钮。

前端不能直接 POST 到本机 ethan-tts 的 8765：那个服务可能根本没启动。这里做一层
代理，按需拉起本地 ethan-tts 服务，再把它的流式 WAV 原样转发给浏览器。

设计取舍：

1. **不常驻**。ethan-tts 服务只在第一次朗读时拉起，之后常驻到下次重启；模型按需
   加载（加载后常驻约 1.8 GB Metal），实测加载 6 秒、热态流式首包 0.4 秒。
2. **不经过 CLI**。`ethan-tts say --stream` 内部是 `response.read()` + 落盘，根本不
   往 stdout 吐音频，拿它做流式代理只能等整段合成完（实测 120s 超时、0 字节）。
   所以这里直接对服务的 `/api/tts/stream` 发请求，逐块转发。
3. **失败要能被前端看见**。StreamingResponse 一旦开始发 body 状态码就定了，中途
   出错只能让流异常结束；前端据此判定失败并提示，不会静默卡住。
"""
from __future__ import annotations

import json
import shutil
import subprocess
import time

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from ethan.core.config import load_config
from ethan.core.http_client import create_http_client
from ethan.interface.routers.deps import verify_token

router = APIRouter(prefix="/tts")

DEFAULT_CLI = "ethan-tts"
DEFAULT_BASE_URL = "http://127.0.0.1:8765"
# 冷启动 = 拉起服务 + 加载模型，实测 6–10 秒；给足余量，慢机器也不误判。
STARTUP_TIMEOUT_SEC = 120
READY_POLL_SEC = 0.15


class SpeakRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=8000)
    # 空 = 用 config.yaml 的 tts.voice，再空 = 服务端自己的默认音色
    voice: str = ""


def _tts_settings() -> tuple[str, str, str]:
    """读 config.yaml 的 tts 段，返回 (command, voice, base_url)。"""
    try:
        cfg = load_config()
        command = (cfg.tts.command or "").strip() or DEFAULT_CLI
        voice = (cfg.tts.voice or "").strip()
        base_url = (cfg.tts.base_url or "").strip() or DEFAULT_BASE_URL
        return command, voice, base_url.rstrip("/")
    except Exception:
        return DEFAULT_CLI, "", DEFAULT_BASE_URL


def _probe_running(command: str) -> bool:
    """问 CLI 服务在不在。解析 JSON 而不是匹配字符串——

    早期版本用 `'"server_running": true' in out.replace(" ", "")`：去掉空格后左边
    仍有空格，永远匹配不上，表现为「已就绪也判定超时」（实测卡满 120 秒）。
    """
    try:
        probe = subprocess.run(
            [command, "status", "--json", "--no-autostart"],
            check=False, capture_output=True, text=True, timeout=15,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False
    if probe.returncode != 0:
        return False
    try:
        return bool(json.loads(probe.stdout).get("server_running"))
    except (json.JSONDecodeError, AttributeError):
        return False


def _ensure_server(command: str, deadline: float) -> None:
    """确保 ethan-tts 服务在线；没在线就让 CLI 在后台拉起并等到就绪。

    CLI 的 `serve` 是幂等的：已经在跑会直接返回，不会重复起进程。
    """
    try:
        subprocess.run(
            [command, "serve", "--json"],
            check=False, capture_output=True, text=True, timeout=STARTUP_TIMEOUT_SEC,
        )
    except FileNotFoundError as exc:
        raise HTTPException(
            503,
            f"找不到命令 {command!r}，请先安装本地 ethan-tts（见 docs/tts.md），"
            "或把 config.yaml 的 tts.backend 改回 edge-tts",
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise HTTPException(504, f"{command} serve 超时（{STARTUP_TIMEOUT_SEC}s）") from exc

    while time.monotonic() < deadline:
        if _probe_running(command):
            return
        time.sleep(READY_POLL_SEC)
    raise HTTPException(504, "本地语音服务未能在预期时间内就绪")


@router.get("/status", dependencies=[Depends(verify_token)])
def tts_status() -> dict:
    """前端开面板时探一次：服务在不在、有没有装。不做拉起动作。"""
    command, voice, _ = _tts_settings()
    installed = shutil.which(command) is not None
    running = _probe_running(command) if installed else False
    return {"installed": installed, "running": running, "command": command, "voice": voice}


@router.post("/speak", dependencies=[Depends(verify_token)])
async def speak(req: SpeakRequest):
    """流式朗读：边合成边把 PCM 转给浏览器。"""
    command, default_voice, base_url = _tts_settings()
    voice = req.voice.strip() or default_voice
    deadline = time.monotonic() + STARTUP_TIMEOUT_SEC

    # 拉起服务 + 等模型可用，放在流开始之前，失败还能正常返回 5xx。
    import anyio

    await anyio.to_thread.run_sync(lambda: _ensure_server(command, deadline))

    payload = {"text": req.text}
    if voice:
        payload["voice_id"] = voice

    async def _emit():
        # 服务端是无限长的 WAV 流（RIFF/data 长度写 0xFFFFFFFF），按块转发即可。
        # trust_env=False：本机回环绝不能走系统代理（常见 127.0.0.1:7890 会把 ws/http 拦掉）
        async with create_http_client(timeout=300.0) as client:
            async with client.stream("POST", f"{base_url}/api/tts/stream", json=payload) as upstream:
                if upstream.status_code != 200:
                    body = (await upstream.aread()).decode(errors="replace")[:300]
                    raise RuntimeError(f"本地语音服务返回 {upstream.status_code}：{body}")
                async for chunk in upstream.aiter_raw():
                    if chunk:
                        yield chunk

    return StreamingResponse(
        _emit(),
        media_type="audio/wav",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )
