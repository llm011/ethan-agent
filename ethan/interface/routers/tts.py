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
import threading
import time

import anyio
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from ethan.core.config import load_config
from ethan.core.http_client import create_http_client
from ethan.interface.routers.deps import verify_token

router = APIRouter(prefix="/tts")

# 并发朗读共用同一次「拉起」：用户等得不耐烦点第二下时，不该再叠一个 120 秒的
# `serve` + 轮询，而是等同一个正在进行的拉起结果。
_startup_lock = threading.Lock()
_startup_done = threading.Event()

DEFAULT_CLI = "ethan-tts"
DEFAULT_BASE_URL = "http://127.0.0.1:8765"
# 冷启动 = 拉起服务 + 加载模型，实测 6–10 秒；给足余量，慢机器也不误判。
STARTUP_TIMEOUT_SEC = 120
READY_POLL_SEC = 0.15
# 单次朗读的上游读超时：流式下这是「多久没收到新数据就算断」。
# 不设 300 秒——服务端卡死时用户要干等 5 分钟才见到错误，60 秒足够覆盖正常的长句生成。
STREAM_READ_TIMEOUT_SEC = 60.0


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

    并发去重：同一时刻只让一个线程真正拉起，其余线程等它的结果。
    CLI 的 `serve` 本身是幂等的（已经在跑会直接返回），但「等就绪」的轮询会
    被每个并发请求各跑一遍，白占 120 秒的协程。
    """
    with _startup_lock:
        if _startup_done.is_set():
            return
        # 失败不置位，下一个请求还可以重试（比如服务刚被 user 手动停掉）
        _ensure_server_once(command, deadline)
        _startup_done.set()


def _ensure_server_once(command: str, deadline: float) -> None:
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


def _voice_backends():
    """惰性拿 voice_backends 模块。

    不写成 `from ethan.core.voice_backends import probe_all` 的局部导入，是因为那样
    测试无法 patch（每次调用重新绑定局部名）。这里返回模块对象，调用方用
    `_voice_backends().probe_all(...)`，测试只需 patch 模块属性即可。
    """
    from ethan.core import voice_backends

    return voice_backends


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
    await anyio.to_thread.run_sync(lambda: _ensure_server(command, deadline))

    payload = {"text": req.text}
    if voice:
        payload["voice_id"] = voice

    async def _emit():
        # 服务端是无限长的 WAV 流（RIFF/data 长度写 0xFFFFFFFF），按块转发即可。
        # trust_env=False：本机回环绝不能走系统代理（常见 127.0.0.1:7890 会把 ws/http 拦掉）
        async with create_http_client(timeout=STREAM_READ_TIMEOUT_SEC) as client:
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


# ── 语音后端管理（TTS / ASR 可配置 + 一键配置）────────────────────────
#
# 与上面 /status 的区别：/status 是「当前选中的后端在跑吗」，
# 这组是「有哪些后端可选、能不能用、怎么一键配好」。


class VoiceSetupRequest(BaseModel):
    backend: str = "ethan-tts"
    auto_start: bool = True


@router.get("/backends", dependencies=[Depends(verify_token)])
async def voice_backends() -> dict:
    """列出所有语音后端及其可用性。

    只读探测：DSH 本地后端的 probe 会跑 `ethan-tts doctor`（约 1-2s），
    丢线程池避免卡事件循环——同样的坑在 list_skills 里踩过一次。
    """
    import asyncio

    from ethan.core.config import get_config

    cfg = get_config()
    data = await asyncio.to_thread(_voice_backends().probe_all, cfg.tts.command, cfg.tts.base_url)
    data["current"] = {"tts": cfg.tts.backend, "asr": cfg.asr.backend}
    return data


@router.post("/setup", dependencies=[Depends(verify_token)])
async def setup_voice_backend(req: VoiceSetupRequest) -> dict:
    """一键配置本地语音后端。

    预检不过会**直接拒绝**且不执行任何安装/下载——在注定跑不起来的机器上装
    几百 MB 模型权重，用户白等十几分钟还拿不到有效信息（见 voice_backends 模块注释）。

    安装是重操作（下 MLX + 模型），丢线程池。
    """
    import asyncio


    if req.backend != "ethan-tts":
        raise HTTPException(400, f"不支持一键配置的后端：{req.backend}")

    result = await asyncio.to_thread(
        _voice_backends().setup_ethan_tts, auto_start=req.auto_start
    )
    payload = result.to_dict()
    if not result.ok:
        # 409 而不是 500：这是「环境不满足」而非服务端故障，前端要展示原因
        payload["detail"] = result.message
        return JSONResponse(status_code=409, content=payload)
    return payload


@router.get("/setup/status", dependencies=[Depends(verify_token)])
def setup_voice_status() -> dict:
    """上一次一键配置的进度（前端轮询用）。"""

    latest = _voice_backends().latest_setup()
    return latest.to_dict() if latest else {"ok": False, "message": "尚未执行过配置"}


class VoiceBackendSelect(BaseModel):
    tts: str = ""  # 空=不改
    asr: str = ""


@router.post("/select", dependencies=[Depends(verify_token)])
async def select_voice_backend(req: VoiceBackendSelect) -> dict:
    """切换 TTS / ASR 后端。

    与内核选择同一条原则：**先确认可用，再写配置**。若先写配置后校验，装不上就
    留下「配置指向不可用后端」的脏状态，之后每次朗读/识别都失败。
    """
    import asyncio

    from ethan.core.config import get_config, reload_config, save_config

    cfg = get_config()
    notes: list[str] = []

    if req.tts:
        if req.tts not in ("edge-tts", "ethan-tts"):
            raise HTTPException(400, f"未知 TTS 后端：{req.tts}")
        if req.tts == "ethan-tts":
            data = await asyncio.to_thread(_voice_backends().probe_all, cfg.tts.command, cfg.tts.base_url)
            probe = data["tts"]["ethan-tts"]
            if not probe["available"]:
                raise HTTPException(
                    409,
                    detail={
                        "message": "本地语音后端不可用，未切换",
                        "reason": probe["reason"],
                        "checks": probe["checks"],
                    },
                )
        cfg.tts.backend = req.tts
        notes.append(f"tts → {req.tts}")

    if req.asr:
        if req.asr not in ("off", "ethan-tts"):
            raise HTTPException(400, f"未知 ASR 后端：{req.asr}")
        if req.asr == "ethan-tts":
            data = await asyncio.to_thread(_voice_backends().probe_all, cfg.tts.command, cfg.tts.base_url)
            probe = data["asr"]
            if not probe["available"]:
                raise HTTPException(
                    409,
                    detail={
                        "message": "本地语音识别不可用，未切换",
                        "reason": probe["reason"],
                        "checks": probe["checks"],
                    },
                )
        cfg.asr.backend = req.asr
        notes.append(f"asr → {req.asr}")

    save_config(cfg)
    reload_config()
    return {"ok": True, "tts": cfg.tts.backend, "asr": cfg.asr.backend, "notes": notes}
