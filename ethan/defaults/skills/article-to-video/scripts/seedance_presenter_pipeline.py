#!/usr/bin/env python3
"""Seedance 2.0 dynamic presenter pipeline (BytePlus ModelArk via gateway).

Seedance 2.0 replaces the local ComfyUI H3 generator for scenes that need a
performing presenter: the deterministic stage render provides a first frame
(combined reference), Seedance animates the full frame with image-to-video,
and the generated segment is spliced back over the original timeline window.

Mode priority (see `mode` subcommand):
  explicit instruction (--prefer) > seedance (config.yaml) > h3 (H3_COMFYUI_URL) > static.

Config lives in `~/.ethan/config.yaml` under a top-level `seedance:` section
(gateway_url / api_key / edge_secret / models).  Secrets never appear in code.
This module intentionally depends only on the stdlib plus its sibling
`h3_presenter_pipeline` (probing, atomic writes, presenter identity).
"""

from __future__ import annotations

import argparse
import base64
import json
import math
import os
import re
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# 复用 H3 管线的探针/原子写/身份加载：同一目录下的兄弟模块，
# 以脚本方式运行时 sys.path[0] 即本目录，直接 import。
import h3_presenter_pipeline as h3

PipelineError = h3.PipelineError

SEEDANCE_SECTION = "seedance"
_MIN_DURATION, _MAX_DURATION = 4, 15
_PROMPT_CHAR_LIMIT = 500  # 官方提示词指南：中文提示词不超过 500 字
_SUPPORTED_RATIOS = {  # Seedance 2.0 支持的宽高比 → 宽/高
    "21:9": 21 / 9,
    "16:9": 16 / 9,
    "4:3": 4 / 3,
    "1:1": 1.0,
    "3:4": 3 / 4,
    "9:16": 9 / 16,
}
_720P_ONLY_MODEL_KEYS = ("video_fast", "video_mini")
_DATA_URI_PREFIX = "data:image/{};base64,"
_MAX_IMAGE_BYTES = 30 * 1024 * 1024  # 官方限制：单张图片 < 30MB（base64 前）

_TERMINAL_OK = ("succeeded", "success", "completed", "complete", "done")
_TERMINAL_FAIL = ("failed", "error", "cancelled", "canceled", "expired")


# ── 配置（config.yaml 的 seedance 段；密钥永不进代码） ─────────────────────


@dataclass(frozen=True)
class GatewayConfig:
    gateway_url: str
    api_key: str
    edge_secret: str
    models: dict[str, str]
    resolution: str = "1080p"
    generate_audio: bool = False

    def model_endpoint(self, key: str = "video") -> str:
        endpoint = self.models.get(key)
        if not endpoint:
            raise PipelineError(f"config.yaml seedance.models 里没有配置 {key!r}")
        return endpoint

    def resolution_for(self, model_key: str) -> str:
        """fast/mini 档最高 720p，请求 1080p 会被网关拒绝，自动降档并提示。"""
        if model_key in _720P_ONLY_MODEL_KEYS and self.resolution == "1080p":
            return "720p"
        return self.resolution

    def is_complete(self) -> bool:
        return bool(
            self.gateway_url and self.api_key and self.edge_secret and self.models.get("video")
        )


def config_yaml_path() -> Path:
    data_dir = os.environ.get("ETHAN_DATA_DIR")
    base = Path(data_dir).expanduser() if data_dir else Path.home() / ".ethan"
    return base / "config.yaml"


def _strip_yaml_value(raw: str) -> str:
    value = raw.strip()
    if " #" in value:  # 去掉行内注释（引号外裸值场景够用）
        value = value.split(" #", 1)[0].rstrip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        value = value[1:-1]
    return value.strip()


def parse_seedance_section(text: str) -> dict[str, Any]:
    """极简解析 config.yaml 顶层 seedance 段（一层 key:value + 一层嵌套 dict）。

    独立脚本不能依赖 PyYAML，这里只解析我们自己的 schema；
    其他段落原样跳过。缩进异常或空值直接忽略，由 is_complete() 兜底。
    """
    section: dict[str, Any] = {}
    lines = text.splitlines()
    in_section = False
    section_indent = 0
    current_nested_key: str | None = None
    nested_indent = 0
    for line in lines:
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        indent = len(line) - len(line.lstrip(" "))
        stripped = line.strip()
        if not in_section:
            if stripped == f"{SEEDANCE_SECTION}:":
                in_section, section_indent = True, indent
            continue
        if indent <= section_indent:  # 离开 seedance 段
            break
        key, sep, rest = stripped.partition(":")
        if not sep:
            continue
        key, rest = key.strip(), rest.strip()
        if not key:
            continue
        if not rest:  # 嵌套 dict 的开始（如 models:）
            current_nested_key, nested_indent = key, indent
            section[key] = {}
            continue
        if current_nested_key is not None and indent > nested_indent:
            section.setdefault(current_nested_key, {})[key] = _strip_yaml_value(rest)
            continue
        current_nested_key = None
        section[key] = _strip_yaml_value(rest)
    return section


def load_gateway_config(path: Path | None = None) -> GatewayConfig | None:
    """读 config.yaml 的 seedance 段；环境变量可覆盖网关地址与密钥。"""
    path = path or config_yaml_path()
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    raw = parse_seedance_section(text)
    if not raw:
        return None
    models_raw = raw.get("models")
    models = {str(k): str(v) for k, v in models_raw.items()} if isinstance(models_raw, dict) else {}
    generate_audio = str(raw.get("generate_audio", "false")).strip().lower() in ("1", "true", "yes", "on")
    return GatewayConfig(
        gateway_url=(
            os.environ.get("SEEDANCE_GATEWAY_URL")
            or str(raw.get("gateway_url", ""))
        ).rstrip("/"),
        api_key=os.environ.get("SEEDANCE_API_KEY") or str(raw.get("api_key", "")),
        edge_secret=os.environ.get("SEEDANCE_EDGE_SECRET") or str(raw.get("edge_secret", "")),
        models=models,
        resolution=str(raw.get("resolution", "1080p")) or "1080p",
        generate_audio=generate_audio,
    )


def require_gateway_config(path: Path | None = None) -> GatewayConfig:
    config = load_gateway_config(path)
    if config is None or not config.is_complete():
        where = path or config_yaml_path()
        raise PipelineError(
            f"{where} 缺少可用的 seedance 配置段（需要 gateway_url/api_key/edge_secret/models.video）。"
            "参考 references/seedance-presenter-pipeline.md 完成配置。"
        )
    return config


# ── 模式优先级：显式指示 > seedance > h3 > 静态 ────────────────────────────


def _h3_configured() -> bool:
    if os.environ.get("H3_COMFYUI_URL"):
        return True
    data_dir = os.environ.get("ETHAN_DATA_DIR")
    base = Path(data_dir).expanduser() if data_dir else Path.home() / ".ethan"
    env_file = base / "skills" / "article-to-video" / "h3-comfyui.env"
    try:
        text = env_file.read_text(encoding="utf-8")
    except OSError:
        return False
    return any(
        re.match(r"^\s*(export\s+)?H3_COMFYUI_URL\s*=\s*\S", line)
        for line in text.splitlines()
    )


def resolve_mode(prefer: str | None = None) -> tuple[str, str]:
    """返回 (mode, reason)。显式指示最高；否则 seedance > h3 > static。"""
    if prefer is not None:
        if prefer not in ("seedance", "h3", "static"):
            raise PipelineError("--prefer 只支持 seedance / h3 / static")
        if prefer == "seedance":
            require_gateway_config()  # 指定了但没配置 → 明确报错，不静默回退
        if prefer == "h3" and not _h3_configured():
            raise PipelineError(
                "指定 h3 但未配置 H3_COMFYUI_URL（~/.ethan/skills/article-to-video/h3-comfyui.env）"
            )
        return prefer, "explicit instruction"
    config = load_gateway_config()
    if config is not None and config.is_complete():
        return "seedance", "config.yaml seedance 段完整，优先级高于 h3"
    if _h3_configured():
        return "h3", "H3_COMFYUI_URL 已配置（seedance 未配置）"
    return "static", "seedance 与 h3 均未配置"


# ── Prompt：Seedance 格式（≠ H3），带情绪表演 ─────────────────────────────


_POSITIVE_WORDS = ("涨", "升", "突破", "新高", "增长", "反弹", "利好", "盈利", "机会", "超预期", "回暖", "放大")
_NEGATIVE_WORDS = ("跌", "降", "亏", "风险", "警告", "警示", "下滑", "利空", "回调", "压力", "警惕", "缩水")

_EMOTION_PROFILES: dict[str, dict[str, str]] = {
    "positive": {
        "mood": "自信昂扬：眉眼舒展，嘴角保持上扬的微笑，神态明亮有感染力",
        "beats": "讲到关键数字时抬起手掌指向左侧图表再自然收回，重点处轻微点头，语速平稳有力",
        "mood_short": "自信昂扬，微笑明亮",
        "beats_short": "重点处抬手指向左侧图表并轻微点头",
    },
    "negative": {
        "mood": "沉稳关切：眉峰微蹙后舒展，目光坚定，收尾带安抚神情",
        "beats": "先向镜头微微倾身提示要点，再抬手指向数据区，收尾时双手轻叠、放缓语速",
        "mood_short": "沉稳关切，目光坚定",
        "beats_short": "先倾身提示要点，再指向数据区，收尾放缓",
    },
    "neutral": {
        "mood": "亲切专业：自然微笑，眼神专注而放松",
        "beats": "以开放手势介绍左侧信息，讲到重点时指尖轻点方向，眨眼与呼吸自然",
        "mood_short": "亲切专业，自然微笑",
        "beats_short": "以开放手势介绍左侧信息，重点处指尖轻点方向",
    },
}


def detect_emotion(text: str) -> str:
    """按台词关键词判定情绪基调：正向/负向词命中多者胜出，平手或零命中为中性。"""
    positive = sum(text.count(word) for word in _POSITIVE_WORDS)
    negative = sum(text.count(word) for word in _NEGATIVE_WORDS)
    if positive > negative:
        return "positive"
    if negative > positive:
        return "negative"
    return "neutral"


def _clamp_text(value: str, limit: int) -> str:
    value = " ".join(value.split())  # 压平换行/连续空白
    return value if len(value) <= limit else value[: limit - 1] + "…"


def build_seedance_prompt(
    *,
    dialogue: str,
    presenter: dict[str, Any],
    emotion: str = "neutral",
    generate_audio: bool = False,
) -> str:
    """按 Seedance 2.0 官方提示词指南构建中文提示词（≤500 字）。

    与 H3 的差异：H3 是英文长文档（Reference ownership / Character integrity 等
    分节合同）；Seedance 是紧凑中文指令——精准主体 + 动作细节 + 情绪 + 镜头 +
    约束收尾，台词用 { } 包裹（官方括号语义：{ }=台词，【 】=想要字幕），
    结尾必须带"请勿生成字幕/水印"类约束。
    """
    if not dialogue.strip():
        raise PipelineError("dialogue must be non-empty")
    profile = _EMOTION_PROFILES.get(emotion) or _EMOTION_PROFILES["neutral"]
    name = str(presenter.get("name", "主播"))
    description = _clamp_text(str(presenter.get("description", "")), 60)

    lines = [
        f"参考图片1即首帧：画面右侧的虚拟主播{name}（{description}）面向镜头口播，左侧为金融数据看板。",
        f"情绪基调：{profile['mood']}。",
        f"表演：{profile['beats']}。目光以注视镜头为主，指向图表时短暂移开后回到镜头；口型随台词节奏自然开合。",
        "台词：{" + dialogue.strip() + "}",
    ]
    if generate_audio:
        lines.append("声音：清晰自然的中文口播，语气与台词情绪一致；(轻柔电子氛围垫乐，音量克制)。")
    lines.append("镜头：固定机位，全程不推拉不横移，构图始终与首帧一致。")
    lines.append("约束：保持首帧中看板文字、数字、图表样式与人物服饰发型位置不变；请勿生成字幕、水印或任何新增文字。")
    prompt = "\n".join(lines)
    if len(prompt) > _PROMPT_CHAR_LIMIT:  # 超字数预算 → 换紧凑情绪句式，再不行硬截断
        compact = [
            f"参考图片1即首帧：右侧虚拟主播{name}（{description}）面向镜头口播，左侧为金融看板。",
            f"情绪基调：{profile['mood_short']}。表演：{profile['beats_short']}，口型随台词开合。",
            "台词：{" + dialogue.strip() + "}",
            "镜头：固定机位，构图与首帧一致。",
            "约束：看板文字图表与人物保持首帧原样；请勿生成字幕与水印。",
        ]
        if generate_audio:
            compact.append("声音：清晰自然中文口播。")
        prompt = "\n".join(compact)
    return prompt[:_PROMPT_CHAR_LIMIT]


def _ratio_key(width: int, height: int) -> str:
    target = width / height
    return min(_SUPPORTED_RATIOS, key=lambda key: abs(_SUPPORTED_RATIOS[key] - target))


def _requested_duration(duration_seconds: float) -> int:
    """Seedance 2.0 单镜头 4–15s：向上取整保证覆盖场景时长，compose 再精确裁齐。"""
    if not _MIN_DURATION <= duration_seconds <= _MAX_DURATION:
        raise PipelineError(
            f"duration must be between {_MIN_DURATION} and {_MAX_DURATION} seconds for Seedance 2.0, "
            f"got {duration_seconds:g}"
        )
    return min(_MAX_DURATION, max(_MIN_DURATION, math.ceil(duration_seconds)))


# ── prepare：场景包（首帧参考 + Seedance prompt + scene.json） ─────────────


def _load_scene(scene_dir: Path) -> dict[str, Any]:
    scene_dir = scene_dir.expanduser().resolve()
    metadata_path = h3._require_file(scene_dir / "scene.json", "scene metadata")
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PipelineError(f"invalid scene metadata: {metadata_path}") from exc
    if not isinstance(metadata, dict) or metadata.get("provider") != "seedance":
        raise PipelineError(f"scene.json 不是 seedance 场景包: {metadata_path}")
    return metadata


def _update_scene(scene_dir: Path, mutate: dict[str, Any]) -> None:
    metadata = _load_scene(scene_dir)
    metadata.update(mutate)
    h3._write_text_atomic(
        scene_dir / "scene.json", json.dumps(metadata, ensure_ascii=False, indent=2) + "\n"
    )


def prepare_scene(
    *,
    scene_dir: Path,
    combined_reference: Path,
    dialogue: str,
    duration_seconds: float,
    start_seconds: float = 0.0,
    clean_plate: Path | None = None,
    presenter_id: str | None = None,
    generate_audio: bool | None = None,
    resolution: str | None = None,
    model_key: str = "video",
) -> dict[str, Any]:
    """复制参考帧、生成 Seedance prompt 与 scene.json（不联网）。"""
    if not isinstance(dialogue, str) or not dialogue.strip():
        raise PipelineError("dialogue must be non-empty")
    if start_seconds < 0:
        raise PipelineError("start-seconds must be >= 0")
    config = load_gateway_config()
    if config is None:
        raise PipelineError("prepare 也需要 config.yaml 的 seedance 段（分辨率/音频/模型来源）")
    requested = _requested_duration(duration_seconds)

    combined_reference = h3._require_file(combined_reference, "combined reference (first frame)")
    combined_info = h3.probe_media(combined_reference)
    plate_dest = None
    if clean_plate is not None:
        clean_plate = h3._require_file(clean_plate, "clean plate")
        plate_info = h3.probe_media(clean_plate)
        if (plate_info.width, plate_info.height) != (combined_info.width, combined_info.height):
            raise PipelineError(
                "combined-reference and clean-plate must have identical dimensions; "
                f"got {combined_info.width}x{combined_info.height} and {plate_info.width}x{plate_info.height}"
            )
        plate_dest = h3._copy_asset(clean_plate, scene_dir / "references" / "clean-plate.png")

    identity = h3._load_presenter_identity(presenter_id)
    emotion = detect_emotion(dialogue)
    audio = config.generate_audio if generate_audio is None else generate_audio
    resolution = resolution or config.resolution_for(model_key)
    prompt = build_seedance_prompt(
        dialogue=dialogue, presenter=identity, emotion=emotion, generate_audio=audio
    )
    prompt_path = scene_dir / "seedance-prompt.txt"
    h3._write_text_atomic(prompt_path, prompt + "\n")
    first_frame_dest = h3._copy_asset(combined_reference, scene_dir / "references" / "combined-reference.png")
    payload = {
        "version": 1,
        "provider": "seedance",
        "startSeconds": start_seconds,
        "durationSeconds": duration_seconds,
        "requestedDuration": requested,
        "ratio": _ratio_key(combined_info.width, combined_info.height),
        "resolution": resolution,
        "generateAudio": audio,
        "emotion": emotion,
        "dialogue": dialogue,
        "presenter": {"id": identity["id"], "name": identity["name"]},
        "references": {
            "firstFrame": str(first_frame_dest),
            "cleanPlate": str(plate_dest) if plate_dest else None,
        },
        "referenceMedia": {"firstFrame": h3.asdict(combined_info)},
        "seedance": {
            "model": config.model_endpoint(model_key),
            "modelKey": model_key,
            "taskId": None,
            "status": "prepared",
        },
    }
    h3._write_text_atomic(scene_dir / "scene.json", json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    return {"sceneDir": str(scene_dir), "prompt": str(prompt_path), "metadata": str(scene_dir / "scene.json"), **payload}


# ── HTTP：网关客户端（密钥只出现在请求头，永不打印） ────────────────────────


def _headers(config: GatewayConfig) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {config.api_key}",
        "x-byteplus-gateway-secret": config.edge_secret,
        "Content-Type": "application/json",
    }


def _http_json(config: GatewayConfig, method: str, path: str, payload: dict[str, Any] | None = None, timeout: float = 60.0) -> Any:
    url = f"{config.gateway_url}{path}"
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(url, data=data, method=method, headers=_headers(config))
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read(8 * 1024 * 1024)
    except urllib.error.HTTPError as exc:
        try:
            detail = exc.read(4096).decode("utf-8", "replace").strip()
        except Exception:  # noqa: BLE001 - HTTPError.read 自身失败时保底
            detail = ""
        raise PipelineError(f"gateway HTTP {exc.code} on {method} {path}: {detail[:500]}") from exc
    except urllib.error.URLError as exc:
        raise PipelineError(f"cannot reach gateway {config.gateway_url}: {exc.reason}") from exc
    if not body:
        return None
    try:
        return json.loads(body.decode("utf-8", "replace"))
    except json.JSONDecodeError as exc:
        raise PipelineError(f"gateway returned invalid JSON on {method} {path}") from exc


def task_id_from(data: Any) -> str | None:
    value = data.get("id") if isinstance(data, dict) else None
    if not value and isinstance(data, dict):
        inner = data.get("data")
        if isinstance(inner, dict):
            value = inner.get("id") or inner.get("task_id")
    if not value and isinstance(data, dict):
        value = data.get("task_id")
    return value if isinstance(value, str) and value else None


def task_status_from(data: Any) -> str:
    if not isinstance(data, dict):
        return ""
    for source in (data, data.get("data")):
        if isinstance(source, dict) and isinstance(source.get("status"), str):
            return source["status"].lower()
    return ""


def video_url_from(data: Any) -> str | None:
    root = data.get("data") if isinstance(data, dict) and isinstance(data.get("data"), dict) else data
    if not isinstance(root, dict):
        return None
    content = root.get("content")
    contents = content if isinstance(content, list) else [content] if content else []
    candidates = [root, root.get("video"), root.get("result"), root.get("result", {}) if isinstance(root.get("result"), dict) else None, *contents]
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        for key in ("video_url", "output_video_url", "url"):
            if isinstance(candidate.get(key), str) and candidate[key]:
                return candidate[key]
    return None


def _image_transport(image_path: Path, image_url_override: str | None) -> tuple[str, str]:
    """返回 (transport, value)：外部 URL 或 base64 data URI。"""
    if image_url_override:
        if not image_url_override.startswith(("http://", "https://")):
            raise PipelineError("--image-url 必须是 http(s) 公网地址")
        return "url", image_url_override
    mime = image_path.suffix.lower().lstrip(".") or "png"
    if mime == "jpg":
        mime = "jpeg"
    if mime not in ("png", "jpeg", "webp", "bmp"):
        raise PipelineError(f"first-frame 参考不支持 {mime} 格式，请用 PNG")
    size = image_path.stat().st_size
    if size > _MAX_IMAGE_BYTES:
        raise PipelineError(
            f"first-frame 参考图 {size / 1024 / 1024:.1f}MB 超过 30MB 限制；"
            "请压缩或上传后用 --image-url 传入公网地址"
        )
    encoded = base64.b64encode(image_path.read_bytes()).decode("ascii")
    return "base64", _DATA_URI_PREFIX.format(mime) + encoded


def submit_task(*, scene_dir: Path, model_key: str | None = None, image_url: str | None = None, dry_run: bool = False) -> dict[str, Any]:
    scene_dir = scene_dir.expanduser().resolve()
    metadata = _load_scene(scene_dir)
    prompt = h3._require_file(scene_dir / "seedance-prompt.txt", "seedance prompt").read_text(encoding="utf-8").strip()
    first_frame = h3._require_file(Path(metadata["references"]["firstFrame"]), "first-frame reference")
    config = require_gateway_config()
    model_key = model_key or metadata["seedance"].get("modelKey", "video")
    transport, value = _image_transport(first_frame, image_url)
    payload = {
        "model": config.model_endpoint(model_key),
        # content 数组顺序是官方硬性要求：text → image_url → video_url → audio_url
        "content": [
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": value}, "role": "first_frame"},
        ],
        "generate_audio": bool(metadata.get("generateAudio", False)),
        "ratio": metadata["ratio"],
        "resolution": metadata.get("resolution") or config.resolution_for(model_key),
        "duration": int(metadata["requestedDuration"]),
        "watermark": False,
    }
    trace_payload = json.loads(json.dumps(payload))
    trace_payload["content"][1]["image_url"]["url"] = f"<{transport}:{len(value)} chars omitted>"
    if dry_run:
        return {"status": "dry-run", "payload": trace_payload}
    h3._write_text_atomic(scene_dir / "seedance-request.json", json.dumps(trace_payload, ensure_ascii=False, indent=2) + "\n")
    response = _http_json(config, "POST", "/contents/generations/tasks", payload, timeout=120)
    task_id = task_id_from(response)
    if not task_id:
        raise PipelineError(f"gateway 未返回任务 ID: {json.dumps(response, ensure_ascii=False)[:400]}")
    _update_scene(scene_dir, {"seedance": {**metadata["seedance"], "taskId": task_id, "status": "submitted"}})
    return {"status": "submitted", "taskId": task_id, "model": payload["model"], "duration": payload["duration"]}


def _download(url: str, destination: Path, timeout: float = 600.0) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": "ethan-seedance-pipeline/1"})
    destination.parent.mkdir(parents=True, exist_ok=True)
    pending = destination.with_name(f".{destination.name}.tmp")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response, pending.open("wb") as handle:
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                handle.write(chunk)
        os.replace(pending, destination)
    except (urllib.error.URLError, OSError) as exc:
        raise PipelineError(f"下载生成视频失败 ({url[:80]}…): {exc}") from exc
    finally:
        if pending.exists():
            pending.unlink(missing_ok=True)


def poll_task(*, scene_dir: Path, timeout_seconds: float = 900.0, interval_seconds: float = 10.0) -> dict[str, Any]:
    scene_dir = scene_dir.expanduser().resolve()
    metadata = _load_scene(scene_dir)
    task_id = (metadata.get("seedance") or {}).get("taskId")
    if not task_id:
        raise PipelineError("scene.json 里没有 taskId；先运行 submit")
    config = require_gateway_config()
    deadline = time.monotonic() + timeout_seconds
    status = ""
    while True:
        response = _http_json(config, "GET", f"/contents/generations/tasks/{task_id}", timeout=30)
        status = task_status_from(response)
        if status in _TERMINAL_OK:
            video_url = video_url_from(response)
            if not video_url:
                raise PipelineError(f"任务成功但未找到视频 URL: {json.dumps(response, ensure_ascii=False)[:400]}")
            output = scene_dir / "raw-seedance.mp4"
            _download(video_url, output)
            info = h3.probe_media(output)
            expected = float(metadata["durationSeconds"])
            if info.duration_seconds is None or info.duration_seconds < expected - 0.5:
                raise PipelineError(
                    f"生成视频时长 {info.duration_seconds}s 覆盖不了场景时长 {expected:g}s"
                )
            _update_scene(
                scene_dir,
                {"seedance": {**metadata["seedance"], "status": "downloaded", "videoUrl": video_url}},
            )
            return {
                "status": "ok",
                "taskId": task_id,
                "video": h3.asdict(info),
                "output": str(output),
            }
        if status in _TERMINAL_FAIL:
            detail = ""
            if isinstance(response, dict):
                for source in (response, response.get("data")):
                    if isinstance(source, dict) and source.get("error"):
                        detail = str(source["error"])
                        break
            raise PipelineError(f"Seedance 任务失败 status={status}: {detail[:300]}")
        if time.monotonic() >= deadline:
            raise PipelineError(f"轮询超时（{timeout_seconds:g}s），最后状态 {status or 'unknown'}（task={task_id}）")
        print(f"task={task_id} status={status or 'unknown'}，{interval_seconds:g}s 后重试", file=sys.stderr)
        time.sleep(interval_seconds)


# ── compose：把生成段落精确替换回成片时间窗（音频沿用原片 TTS） ────────────


def _splice_filter(start: float, duration: float, total: float, width: int, height: int, fps: str) -> str:
    end = start + duration
    parts = []
    labels = []
    if start > 0.001:
        parts.append(f"[0:v]trim=duration={start:.3f},setpts=PTS-STARTPTS[pre]")
        labels.append("[pre]")
    parts.append(
        f"[1:v]fps={fps},scale={width}:{height}:force_original_aspect_ratio=increase,"
        f"crop={width}:{height},trim=duration={duration:.3f},setpts=PTS-STARTPTS[seg]"
    )
    labels.append("[seg]")
    if end < total - 0.001:
        parts.append(f"[0:v]trim=start={end:.3f},setpts=PTS-STARTPTS[post]")
        labels.append("[post]")
    parts.append(f"{''.join(labels)}concat=n={len(labels)}:v=1:a=0[outv]")
    return ";".join(parts)


def compose_scene(*, scene_dir: Path, stage_video: Path, output: Path) -> dict[str, Any]:
    """用 raw-seedance.mp4 替换 stage 视频的 [start, start+duration) 窗口。

    视频段精确对齐（fps/缩放/裁切/裁时长），音轨整体沿用原片（TTS 与字幕
    节奏不变），因此音画同步由"总时长不变"保证。
    """
    scene_dir = scene_dir.expanduser().resolve()
    metadata = _load_scene(scene_dir)
    raw = h3._require_file(scene_dir / "raw-seedance.mp4", "seedance video")
    stage = h3.probe_media(h3._require_file(stage_video, "stage video"))
    if stage.duration_seconds is None:
        raise PipelineError("stage video has no duration")
    start = float(metadata["startSeconds"])
    duration = float(metadata["durationSeconds"])
    if start < 0 or start + duration > stage.duration_seconds + 0.05:
        raise PipelineError(
            f"场景时间窗 [{start:g}, {start + duration:g}s) 超出成片时长 {stage.duration_seconds:g}s"
        )
    raw_info = h3.probe_media(raw)
    if raw_info.duration_seconds is not None and raw_info.duration_seconds < duration - 0.5:
        raise PipelineError(
            f"生成视频 {raw_info.duration_seconds:g}s 短于场景时长 {duration:g}s，无法替换"
        )
    fps = h3._frame_rate_option(stage.fps)
    output = output.expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    command = [
        "ffmpeg", "-y",
        "-i", str(stage.path),
        "-i", str(raw),
        "-filter_complex", _splice_filter(start, duration, stage.duration_seconds, stage.width, stage.height, fps),
        "-map", "[outv]", "-map", "0:a?",
        "-c:v", "libx264", "-preset", "medium", "-crf", "16", "-pix_fmt", "yuv420p",
        "-c:a", "copy", "-movflags", "+faststart",
        str(output),
    ]
    h3._run(command, capture=True)
    result = h3.probe_media(output)
    if (result.width, result.height) != (stage.width, stage.height):
        raise PipelineError("splice verification failed: output dimensions mismatch")
    if result.duration_seconds is None or abs(result.duration_seconds - stage.duration_seconds) > 0.35:
        raise PipelineError(
            f"splice verification failed: duration {result.duration_seconds}s != stage {stage.duration_seconds}s"
        )
    if stage.has_audio and not result.has_audio:
        raise PipelineError("splice verification failed: audio stream lost")
    report = {
        "status": "ok",
        "mode": "scene-splice",
        "window": {"startSeconds": start, "durationSeconds": duration},
        "video": h3.asdict(result),
        "stageVideo": h3.asdict(stage),
        "seedanceVideo": h3.asdict(raw_info),
        "output": str(output),
    }
    h3._write_text_atomic(
        output.with_name(output.stem + ".composition.json"),
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
    )
    return report


def verify_scene(scene_dir: Path, video: Path | None = None) -> dict[str, Any]:
    scene_dir = scene_dir.expanduser().resolve()
    metadata = _load_scene(scene_dir)
    first_frame = h3._require_file(Path(metadata["references"]["firstFrame"]), "first-frame reference")
    prompt = h3._require_file(scene_dir / "seedance-prompt.txt", "seedance prompt")
    result: dict[str, Any] = {
        "status": "ok",
        "firstFrame": h3.asdict(h3.probe_media(first_frame)),
        "prompt": str(prompt),
        "taskId": (metadata.get("seedance") or {}).get("taskId"),
    }
    if video:
        info = h3.probe_media(h3._require_file(video, "seedance video"))
        expected = float(metadata["durationSeconds"])
        if info.duration_seconds is not None and info.duration_seconds < expected - 0.5:
            raise PipelineError(
                f"seedance video {info.duration_seconds:g}s 覆盖不了场景时长 {expected:g}s"
            )
        result["video"] = h3.asdict(info)
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Seedance 2.0 dynamic presenter pipeline")
    subparsers = parser.add_subparsers(dest="command", required=True)

    mode = subparsers.add_parser("mode", help="解析动态 presenter 模式（seedance > h3 > static）")
    mode.add_argument("--prefer", choices=["seedance", "h3", "static"], help="用户显式指定的模式")

    prepare = subparsers.add_parser("prepare", help="写自包含 seedance 场景包（不联网）")
    prepare.add_argument("--scene-dir", type=Path, required=True)
    prepare.add_argument("--combined-reference", type=Path, required=True, help="场景首帧（presenter+舞台）")
    prepare.add_argument("--clean-plate", type=Path, help="可选：无人物参考帧（备将来遮罩合成用）")
    prepare.add_argument("--presenter", help="资产库 presenter id")
    prepare.add_argument("--dialogue")
    prepare.add_argument("--dialogue-file", type=Path)
    prepare.add_argument("--duration", type=float, required=True, help="场景时长（秒，4-15）")
    prepare.add_argument("--start-seconds", type=float, default=0.0, help="场景在成片中的起点（秒）")
    prepare.add_argument("--model", default="video", help="config models 键：video/video_fast/video_mini")
    prepare.add_argument("--generate-audio", choices=["true", "false"], help="覆盖 config 的 generate_audio")

    submit = subparsers.add_parser("submit", help="提交图生视频任务（首帧 + prompt）")
    submit.add_argument("--scene-dir", type=Path, required=True)
    submit.add_argument("--model", help="覆盖 prepare 时的 models 键")
    submit.add_argument("--image-url", help="首帧公网地址（默认走 base64，无需上传）")
    submit.add_argument("--dry-run", action="store_true", help="只打印请求体，不联网")

    poll = subparsers.add_parser("poll", help="轮询任务并下载 raw-seedance.mp4")
    poll.add_argument("--scene-dir", type=Path, required=True)
    poll.add_argument("--timeout", type=float, default=900.0)
    poll.add_argument("--interval", type=float, default=10.0)

    compose = subparsers.add_parser("compose", help="把生成段落替换回成片时间窗")
    compose.add_argument("--scene-dir", type=Path, required=True)
    compose.add_argument("--stage-video", type=Path, required=True)
    compose.add_argument("--output", type=Path, required=True)

    verify = subparsers.add_parser("verify", help="校验场景包与生成结果")
    verify.add_argument("--scene-dir", type=Path, required=True)
    verify.add_argument("--video", type=Path)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        if args.command == "mode":
            mode_value, reason = resolve_mode(args.prefer)
            print(f"MODE: {mode_value}")
            print(json.dumps({"mode": mode_value, "reason": reason}, ensure_ascii=False))
            return 0
        if args.command == "prepare":
            dialogue = h3._read_text_argument(args.dialogue, args.dialogue_file, "dialogue")
            generate_audio = None if args.generate_audio is None else args.generate_audio == "true"
            result = prepare_scene(
                scene_dir=args.scene_dir,
                combined_reference=args.combined_reference,
                clean_plate=args.clean_plate,
                dialogue=dialogue,
                duration_seconds=args.duration,
                start_seconds=args.start_seconds,
                presenter_id=args.presenter,
                generate_audio=generate_audio,
                model_key=args.model,
            )
        elif args.command == "submit":
            result = submit_task(scene_dir=args.scene_dir, model_key=args.model, image_url=args.image_url, dry_run=args.dry_run)
        elif args.command == "poll":
            result = poll_task(scene_dir=args.scene_dir, timeout_seconds=args.timeout, interval_seconds=args.interval)
        elif args.command == "compose":
            result = compose_scene(scene_dir=args.scene_dir, stage_video=args.stage_video, output=args.output)
        else:
            result = verify_scene(args.scene_dir, args.video)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except PipelineError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
