#!/usr/bin/env python3
"""Deterministic Edge TTS + Remotion pipeline for the article-to-video skill."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import re
import shutil
import subprocess
import sys
import time
import uuid
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

VISUAL_TYPES = {"kinetic-text", "steps", "stat", "quote", "summary"}
FPS_VALUES = {24, 25, 30, 60}
DEFAULT_THEME = {
    "background": "#081120",
    "surface": "#111D32",
    "primary": "#6EE7F9",
    "secondary": "#A78BFA",
    "text": "#F8FAFC",
}
COLOR_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")
ID_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
PROSODY_RE = re.compile(r"^[+-]\d+%$")
PITCH_RE = re.compile(r"^[+-]\d+Hz$")
PUBLISHED_OUTPUTS = ("final.mp4", "cover.png", "render-report.json", "deliverables.zip")
# source.md 由 skill 写入但不属于"产物"，归档时也要清走，避免上轮残留混进下轮 deliverables.zip。
ARCHIVE_EXTRA = ("source.md",)


class ManifestError(ValueError):
    pass


@dataclass(frozen=True)
class Subtitle:
    text: str
    start_ms: int
    end_ms: int


def _require_text(value: Any, field: str, *, maximum: int | None = None) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ManifestError(f"{field} must be a non-empty string")
    text = value.strip()
    if maximum is not None and len(text) > maximum:
        raise ManifestError(f"{field} must be at most {maximum} characters")
    return text


def _string_list(value: Any, field: str, *, maximum: int) -> list[str]:
    if not isinstance(value, list) or not value:
        raise ManifestError(f"{field} must be a non-empty list")
    if len(value) > maximum:
        raise ManifestError(f"{field} must contain at most {maximum} items")
    return [_require_text(item, f"{field}[]", maximum=80) for item in value]


def normalize_manifest(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ManifestError("manifest root must be an object")
    title = _require_text(raw.get("title"), "title", maximum=100)
    scenes_raw = raw.get("scenes")
    if not isinstance(scenes_raw, list) or not 1 <= len(scenes_raw) <= 50:
        raise ManifestError("scenes must contain between 1 and 50 items")

    width = raw.get("width", 1080)
    height = raw.get("height", 1920)
    fps = raw.get("fps", 30)
    if not isinstance(width, int) or not isinstance(height, int) or width < 320 or height < 320:
        raise ManifestError("width and height must be integers >= 320")
    if fps not in FPS_VALUES:
        raise ManifestError(f"fps must be one of {sorted(FPS_VALUES)}")

    target_duration = raw.get("targetDurationSec")
    duration_tolerance = raw.get("durationToleranceSec")
    if target_duration is not None:
        if not isinstance(target_duration, (int, float)) or isinstance(target_duration, bool):
            raise ManifestError("targetDurationSec must be a number")
        if not 5 <= target_duration <= 1800:
            raise ManifestError("targetDurationSec must be between 5 and 1800 seconds")
        if duration_tolerance is None:
            duration_tolerance = max(2, round(float(target_duration) * 0.1, 1))
        if not isinstance(duration_tolerance, (int, float)) or isinstance(duration_tolerance, bool):
            raise ManifestError("durationToleranceSec must be a number")
        if not 0.5 <= duration_tolerance <= target_duration:
            raise ManifestError("durationToleranceSec must be between 0.5 and targetDurationSec")
    elif duration_tolerance is not None:
        raise ManifestError("durationToleranceSec requires targetDurationSec")

    voice_raw = raw.get("voice") or {}
    if not isinstance(voice_raw, dict):
        raise ManifestError("voice must be an object")
    voice = {
        "name": _require_text(voice_raw.get("name", "zh-CN-XiaoxiaoNeural"), "voice.name", maximum=100),
        "rate": voice_raw.get("rate", "+0%"),
        "volume": voice_raw.get("volume", "+0%"),
        "pitch": voice_raw.get("pitch", "+0Hz"),
    }
    if not isinstance(voice["rate"], str) or not PROSODY_RE.fullmatch(voice["rate"]):
        raise ManifestError("voice.rate must look like +5% or -10%")
    if not isinstance(voice["volume"], str) or not PROSODY_RE.fullmatch(voice["volume"]):
        raise ManifestError("voice.volume must look like +0% or -10%")
    if not isinstance(voice["pitch"], str) or not PITCH_RE.fullmatch(voice["pitch"]):
        raise ManifestError("voice.pitch must look like +0Hz or -10Hz")

    theme_raw = raw.get("theme") or {}
    if not isinstance(theme_raw, dict):
        raise ManifestError("theme must be an object")
    theme = {**DEFAULT_THEME, **theme_raw}
    for key, color in theme.items():
        if key not in DEFAULT_THEME:
            raise ManifestError(f"unknown theme field: {key}")
        if not isinstance(color, str) or not COLOR_RE.fullmatch(color):
            raise ManifestError(f"theme.{key} must be a six-digit hex color")

    seen: set[str] = set()
    scenes: list[dict[str, Any]] = []
    for index, item in enumerate(scenes_raw):
        field = f"scenes[{index}]"
        if not isinstance(item, dict):
            raise ManifestError(f"{field} must be an object")
        scene_id = _require_text(item.get("id"), f"{field}.id", maximum=64)
        if not ID_RE.fullmatch(scene_id):
            raise ManifestError(f"{field}.id must be kebab-case")
        if scene_id in seen:
            raise ManifestError(f"duplicate scene id: {scene_id}")
        seen.add(scene_id)
        narration = _require_text(item.get("narration"), f"{field}.narration", maximum=1000)
        headline = _require_text(item.get("headline"), f"{field}.headline", maximum=80)
        body = item.get("body", "")
        if not isinstance(body, str) or len(body.strip()) > 200:
            raise ManifestError(f"{field}.body must be a string with at most 200 characters")
        visual_raw = item.get("visual") or {"type": "kinetic-text", "keywords": [headline]}
        if not isinstance(visual_raw, dict):
            raise ManifestError(f"{field}.visual must be an object")
        visual_type = visual_raw.get("type")
        if visual_type not in VISUAL_TYPES:
            raise ManifestError(f"{field}.visual.type must be one of {sorted(VISUAL_TYPES)}")
        visual: dict[str, Any] = {"type": visual_type}
        if visual_type == "kinetic-text":
            visual["keywords"] = _string_list(visual_raw.get("keywords"), f"{field}.visual.keywords", maximum=5)
        elif visual_type in {"steps", "summary"}:
            visual["items"] = _string_list(visual_raw.get("items"), f"{field}.visual.items", maximum=5)
        elif visual_type == "stat":
            visual["value"] = _require_text(visual_raw.get("value"), f"{field}.visual.value", maximum=24)
            visual["label"] = _require_text(visual_raw.get("label"), f"{field}.visual.label", maximum=80)
        elif visual_type == "quote":
            visual["quote"] = _require_text(visual_raw.get("quote"), f"{field}.visual.quote", maximum=160)
            attribution = visual_raw.get("attribution", "")
            if not isinstance(attribution, str) or len(attribution.strip()) > 80:
                raise ManifestError(f"{field}.visual.attribution must be a string with at most 80 characters")
            visual["attribution"] = attribution.strip()
        scenes.append(
            {
                "id": scene_id,
                "narration": narration,
                "headline": headline,
                "body": body.strip(),
                "visual": visual,
            }
        )

    summary_raw = raw.get("summary", "")
    if summary_raw is None:
        summary = ""
    elif isinstance(summary_raw, str):
        summary = summary_raw.strip()
    else:
        raise ManifestError("summary must be a string or null")
    language_raw = raw.get("language", "zh-CN")
    language = (language_raw.strip() if isinstance(language_raw, str) else "") or "zh-CN"
    if not isinstance(language_raw, str) and language_raw is not None:
        raise ManifestError("language must be a string or null")
    source_raw = raw.get("sourceUrl", "")
    if source_raw is None:
        source_url = ""
    elif isinstance(source_raw, str):
        source_url = source_raw.strip()
    else:
        raise ManifestError("sourceUrl must be a string or null")

    result = {
        "title": title,
        "summary": summary,
        "width": width,
        "height": height,
        "fps": fps,
        "targetDurationSec": float(target_duration) if target_duration is not None else None,
        "durationToleranceSec": float(duration_tolerance) if duration_tolerance is not None else None,
        "language": language,
        "sourceUrl": source_url,
        "voice": voice,
        "theme": theme,
        "scenes": scenes,
    }
    if len(result["summary"]) > 200:
        raise ManifestError("summary must be at most 200 characters")
    return result


def load_manifest(path: Path) -> dict[str, Any]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ManifestError(f"manifest not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ManifestError(f"manifest is not valid JSON: {exc}") from exc
    return normalize_manifest(raw)


def _parse_timestamp(value: str) -> int:
    match = re.fullmatch(r"(\d+):(\d{2}):(\d{2})[,.](\d{3})", value.strip())
    if not match:
        raise ValueError(f"invalid SRT timestamp: {value}")
    hours, minutes, seconds, millis = map(int, match.groups())
    return (((hours * 60) + minutes) * 60 + seconds) * 1000 + millis


def _format_timestamp(value: int) -> str:
    value = max(0, int(value))
    hours, remainder = divmod(value, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    seconds, millis = divmod(remainder, 1_000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{millis:03d}"


def parse_srt(text: str) -> list[Subtitle]:
    normalized = text.replace("\r\n", "\n").strip()
    if not normalized:
        return []
    subtitles: list[Subtitle] = []
    for block in re.split(r"\n\s*\n", normalized):
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        if len(lines) < 2:
            continue
        timing_index = 1 if re.fullmatch(r"\d+", lines[0]) else 0
        if timing_index >= len(lines) or "-->" not in lines[timing_index]:
            continue
        start_raw, end_raw = [part.strip() for part in lines[timing_index].split("-->", 1)]
        start_ms, end_ms = _parse_timestamp(start_raw), _parse_timestamp(end_raw)
        caption = " ".join(lines[timing_index + 1 :]).strip()
        if caption and end_ms > start_ms:
            subtitles.append(Subtitle(text=caption, start_ms=start_ms, end_ms=end_ms))
    return subtitles


def serialize_srt(subtitles: list[Subtitle]) -> str:
    blocks = []
    for index, item in enumerate(subtitles, 1):
        blocks.append(
            f"{index}\n{_format_timestamp(item.start_ms)} --> {_format_timestamp(item.end_ms)}\n{item.text}"
        )
    return "\n\n".join(blocks) + ("\n" if blocks else "")


def _split_caption_text(text: str, maximum: int) -> list[str]:
    pieces = [piece.strip() for piece in re.split(r"(?<=[，。！？；,.!?;])", text) if piece.strip()]
    chunks: list[str] = []
    for piece in pieces:
        remaining = piece
        while len(remaining) > maximum:
            split_at = remaining.rfind(" ", 0, maximum + 1)
            if split_at < maximum // 2:
                split_at = maximum
            # 切在空格上时空格作为分隔符被吞掉；硬切（无空格）时原样断开。
            # 两种情况都不 strip 已切出的 head，保证词内硬切不丢字符、空格切不粘词。
            chunks.append(remaining[:split_at].strip())
            remaining = remaining[split_at:].lstrip()
        if remaining:
            if chunks and len(chunks[-1]) + len(remaining) <= maximum:
                # tail-merge：若前块非标点结尾且 remaining 非标点开头，补一个空格防词粘连。
                prev_tail = chunks[-1][-1:]
                next_head = remaining[0]
                need_space = prev_tail and next_head and prev_tail not in "，。！？；,.!?;" and next_head not in "，。！？；,.!?;"
                chunks[-1] = chunks[-1] + (" " if need_space else "") + remaining
            else:
                chunks.append(remaining)
    return chunks or [text]


def paginate_subtitles(subtitles: list[Subtitle], *, maximum: int) -> list[Subtitle]:
    paginated: list[Subtitle] = []
    for subtitle in subtitles:
        chunks = _split_caption_text(subtitle.text, maximum)
        weights = [max(1, len(re.sub(r"\s+", "", chunk))) for chunk in chunks]
        total_weight = sum(weights)
        cursor = subtitle.start_ms
        for index, (chunk, weight) in enumerate(zip(chunks, weights, strict=True)):
            end_ms = (
                subtitle.end_ms
                if index == len(chunks) - 1
                else cursor + round((subtitle.end_ms - subtitle.start_ms) * weight / total_weight)
            )
            # 用 clamp 后的 end_ms 推进 cursor，避免 round() 归零时 cursor 倒退造成字幕重叠。
            clamped_end = max(cursor + 1, end_ms)
            paginated.append(Subtitle(text=chunk, start_ms=cursor, end_ms=clamped_end))
            cursor = clamped_end
    return paginated


def _tts_cache_key(scene: dict[str, Any], voice: dict[str, str]) -> str:
    payload = json.dumps({"narration": scene["narration"], "voice": voice}, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]


def _valid_tts_cache(media_path: Path, srt_path: Path) -> bool:
    try:
        return media_path.stat().st_size >= 256 and bool(parse_srt(srt_path.read_text(encoding="utf-8")))
    except (OSError, UnicodeError, ValueError):
        return False


async def _synthesize_once(text: str, voice: dict[str, str], media_path: Path, srt_path: Path) -> None:
    try:
        import edge_tts
    except ImportError as exc:
        raise RuntimeError("edge-tts is missing; run with: uv run --with 'edge-tts>=7,<8' python ...") from exc

    communicate = edge_tts.Communicate(
        text,
        voice["name"],
        rate=voice["rate"],
        volume=voice["volume"],
        pitch=voice["pitch"],
    )
    submaker = edge_tts.SubMaker()
    with media_path.open("wb") as audio_file:
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                audio_file.write(chunk["data"])
            elif chunk["type"] in {"WordBoundary", "SentenceBoundary"}:
                submaker.feed(chunk)
    srt_path.write_text(submaker.get_srt(), encoding="utf-8")
    if media_path.stat().st_size < 256:
        raise RuntimeError("Edge TTS returned an empty audio file")
    if not parse_srt(srt_path.read_text(encoding="utf-8")):
        raise RuntimeError("Edge TTS returned no subtitle boundaries")


async def _synthesize_scene(scene: dict[str, Any], voice: dict[str, str], cache_dir: Path, *, retries: int) -> None:
    """单场景 TTS：校验缓存 → 带重试的合成 → 原子替换缓存文件。协程化以支持并发。"""
    key = _tts_cache_key(scene, voice)
    cached_audio = cache_dir / f"{key}.mp3"
    cached_srt = cache_dir / f"{key}.srt"
    if _valid_tts_cache(cached_audio, cached_srt):
        return
    cached_audio.unlink(missing_ok=True)
    cached_srt.unlink(missing_ok=True)
    last_error: Exception | None = None
    for attempt in range(1, retries + 1):
        nonce = uuid.uuid4().hex
        pending_audio = cache_dir / f".{key}.{nonce}.mp3.tmp"
        pending_srt = cache_dir / f".{key}.{nonce}.srt.tmp"
        try:
            await _synthesize_once(scene["narration"], voice, pending_audio, pending_srt)
            if not _valid_tts_cache(pending_audio, pending_srt):
                raise RuntimeError("Edge TTS produced an invalid cache entry")
            pending_audio.replace(cached_audio)
            pending_srt.replace(cached_srt)
            last_error = None
            break
        except Exception as exc:  # network/service failures are retriable
            last_error = exc
            pending_audio.unlink(missing_ok=True)
            pending_srt.unlink(missing_ok=True)
            if attempt < retries:
                await asyncio.sleep(attempt * 1.5)
    if last_error is not None:
        raise RuntimeError(f"TTS failed for scene {scene['id']}: {last_error}") from last_error


def synthesize_scenes(manifest: dict[str, Any], output_dir: Path, *, retries: int = 3) -> list[dict[str, Any]]:
    cache_dir = output_dir / "work" / "tts-cache"
    audio_dir = output_dir / "work" / "public" / "audio"
    subtitle_dir = output_dir / "work" / "scene-subtitles"
    for directory in (cache_dir, audio_dir, subtitle_dir):
        directory.mkdir(parents=True, exist_ok=True)

    # 所有场景在同一个事件循环里并发合成（单场景内仍带重试），不再每场景一次 asyncio.run。
    async def _synthesize_all() -> None:
        await asyncio.gather(
            *[_synthesize_scene(scene, manifest["voice"], cache_dir, retries=retries) for scene in manifest["scenes"]]
        )

    asyncio.run(_synthesize_all())

    artifacts: list[dict[str, Any]] = []
    for scene in manifest["scenes"]:
        key = _tts_cache_key(scene, manifest["voice"])
        cached_audio = cache_dir / f"{key}.mp3"
        cached_srt = cache_dir / f"{key}.srt"
        scene_audio = audio_dir / f"{scene['id']}.mp3"
        scene_srt = subtitle_dir / f"{scene['id']}.srt"
        shutil.copy2(cached_audio, scene_audio)
        shutil.copy2(cached_srt, scene_srt)
        artifacts.append({"audio": scene_audio, "srt": scene_srt})
    return artifacts


def build_timeline(
    manifest: dict[str, Any], artifacts: list[dict[str, Any]], *, tail_padding_ms: int = 350
) -> dict[str, Any]:
    if len(artifacts) != len(manifest["scenes"]):
        raise ValueError("artifact count must match scene count")
    offset = 0
    scenes: list[dict[str, Any]] = []
    captions: list[dict[str, Any]] = []
    combined: list[Subtitle] = []
    for scene, artifact in zip(manifest["scenes"], artifacts, strict=True):
        timing_subtitles = parse_srt(Path(artifact["srt"]).read_text(encoding="utf-8"))
        if not timing_subtitles:
            raise RuntimeError(f"scene {scene['id']} has no subtitle timing")
        duration_ms = max(1200, timing_subtitles[-1].end_ms + tail_padding_ms)
        maximum_caption_length = 22 if manifest["height"] >= manifest["width"] else 34
        local_subtitles = paginate_subtitles(timing_subtitles, maximum=maximum_caption_length)
        timeline_scene = {
            **scene,
            "audio": f"audio/{scene['id']}.mp3",
            "startMs": offset,
            "durationMs": duration_ms,
        }
        scenes.append(timeline_scene)
        for item in local_subtitles:
            global_item = Subtitle(text=item.text, start_ms=offset + item.start_ms, end_ms=offset + item.end_ms)
            combined.append(global_item)
            captions.append({"text": global_item.text, "startMs": global_item.start_ms, "endMs": global_item.end_ms})
        offset += duration_ms
    return {
        "title": manifest["title"],
        "summary": manifest["summary"],
        "width": manifest["width"],
        "height": manifest["height"],
        "fps": manifest["fps"],
        "totalDurationMs": offset,
        "theme": manifest["theme"],
        "scenes": scenes,
        "captions": captions,
        "_combinedSubtitles": combined,
    }


def _run_command(command: list[str], *, cwd: Path) -> None:
    # 捕获 stderr，失败时把 Node/Remotion/pnpm 的诊断写进 run-status.json，
    # 否则只留 "non-zero exit status 1"，agent 无法定位渲染失败原因。
    completed = subprocess.run(command, cwd=cwd, check=False, capture_output=True, text=True)
    if completed.returncode != 0:
        stderr = completed.stderr.strip()
        detail = f"\nstderr:\n{stderr}" if stderr else ""
        raise RuntimeError(f"command failed ({' '.join(command)}): exit {completed.returncode}{detail}")
    # pnpm/node 正常输出走 stderr（进度日志），透传给上层日志，不静默吞掉。
    if completed.stderr.strip():
        sys.stderr.write(completed.stderr)


def ensure_renderer(template_dir: Path) -> None:
    if shutil.which("node") is None or shutil.which("pnpm") is None:
        raise RuntimeError("Node.js and pnpm are required to render the video")
    marker = template_dir / "node_modules" / "remotion" / "package.json"
    if not marker.exists():
        _run_command(["pnpm", "install", "--ignore-workspace", "--frozen-lockfile"], cwd=template_dir)


def render_video(template_dir: Path, render_dir: Path, timeline_path: Path, public_dir: Path) -> None:
    ensure_renderer(template_dir)
    render_dir.mkdir(parents=True, exist_ok=True)
    _run_command(
        [
            "node",
            str(template_dir / "render.mjs"),
            str(timeline_path),
            str(render_dir / "final.mp4"),
            str(render_dir / "cover.png"),
            str(render_dir / "render-report.json"),
            str(public_dir),
        ],
        cwd=template_dir,
    )


def verify_outputs(output_dir: Path, timeline: dict[str, Any]) -> dict[str, Any]:
    video = output_dir / "final.mp4"
    cover = output_dir / "cover.png"
    report_path = output_dir / "render-report.json"
    for path, minimum in ((video, 10_000), (cover, 1_000), (report_path, 10)):
        if not path.is_file() or path.stat().st_size < minimum:
            raise RuntimeError(f"invalid or missing output: {path}")
    # 只读头部 32 字节验 ftyp 标记，不要把整个 MP4 读进内存。
    with video.open("rb") as fh:
        header = fh.read(32)
    if b"ftyp" not in header:
        raise RuntimeError("final.mp4 does not contain an MP4 ftyp marker")
    with cover.open("rb") as fh:
        if not fh.read(8).startswith(b"\x89PNG\r\n\x1a\n"):
            raise RuntimeError("cover.png is not a PNG file")
    report = json.loads(report_path.read_text(encoding="utf-8"))
    expected = {
        "width": timeline["width"],
        "height": timeline["height"],
        "fps": timeline["fps"],
        "sceneCount": len(timeline["scenes"]),
    }
    for key, value in expected.items():
        if report.get(key) != value:
            raise RuntimeError(f"render report mismatch for {key}: expected {value}, got {report.get(key)}")
    return report


def package_deliverables(
    output_dir: Path,
    *,
    archive_path: Path | None = None,
    file_overrides: dict[str, Path] | None = None,
) -> Path:
    archive = archive_path or output_dir / "deliverables.zip"
    archive.parent.mkdir(parents=True, exist_ok=True)
    overrides = file_overrides or {}
    candidates = [
        "cover.png",
        "subtitles.srt",
        "manifest.json",
        "timeline.json",
        "source.md",
        "render-report.json",
    ]
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        for name in candidates:
            path = overrides.get(name, output_dir / name)
            if path.is_file():
                bundle.write(path, arcname=name)
    return archive


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    pending = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    pending.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    pending.replace(path)


def _archive_published_outputs(output_dir: Path, run_id: str) -> Path | None:
    existing = [output_dir / name for name in (PUBLISHED_OUTPUTS + ARCHIVE_EXTRA) if (output_dir / name).exists()]
    if not existing:
        return None
    archive_dir = output_dir / "work" / "previous-runs" / run_id
    archive_dir.mkdir(parents=True, exist_ok=True)
    for path in existing:
        path.replace(archive_dir / path.name)
    return archive_dir


def enforce_target_duration(manifest: dict[str, Any], timeline: dict[str, Any]) -> None:
    target = manifest.get("targetDurationSec")
    if target is None:
        return
    tolerance = manifest["durationToleranceSec"]
    # 用最后一条字幕的结束时间作为旁白实际时长，排除 build_timeline 每场景的 tail_padding，
    # 否则 N 场景的 padding 累加会让恰好达标的旁白被误判超时。
    captions = timeline.get("captions") or []
    actual_ms = captions[-1]["endMs"] if captions else timeline["totalDurationMs"]
    actual = actual_ms / 1000
    if abs(actual - target) > tolerance:
        raise RuntimeError(
            f"actual narration duration is {actual:.1f}s; target is {target:.1f}s ± {tolerance:.1f}s. "
            "Revise narration length and rerun with the same scene IDs."
        )


def run_pipeline(manifest_path: Path, output_dir: Path) -> dict[str, Any]:
    manifest = load_manifest(manifest_path)
    output_dir.mkdir(parents=True, exist_ok=True)
    run_id = f"{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}"
    previous_outputs = _archive_published_outputs(output_dir, run_id)
    status_path = output_dir / "run-status.json"
    _write_json_atomic(
        status_path,
        {"status": "running", "runId": run_id, "previousOutputs": str(previous_outputs) if previous_outputs else None},
    )
    try:
        normalized_manifest_path = output_dir / "manifest.json"
        _write_json_atomic(normalized_manifest_path, manifest)
        artifacts = synthesize_scenes(manifest, output_dir)
        timeline = build_timeline(manifest, artifacts)
        combined = timeline.pop("_combinedSubtitles")
        timeline_path = output_dir / "timeline.json"
        _write_json_atomic(timeline_path, timeline)
        (output_dir / "subtitles.srt").write_text(serialize_srt(combined), encoding="utf-8")
        enforce_target_duration(manifest, timeline)

        render_dir = output_dir / "work" / "render-runs" / run_id
        template_dir = Path(__file__).resolve().parent.parent / "assets" / "remotion-template"
        render_video(template_dir, render_dir, timeline_path, output_dir / "work" / "public")
        report = verify_outputs(render_dir, timeline)
        staged_archive = package_deliverables(
            output_dir,
            archive_path=render_dir / "deliverables.zip",
            file_overrides={
                "cover.png": render_dir / "cover.png",
                "render-report.json": render_dir / "render-report.json",
            },
        )
        staged_outputs = {
            "final.mp4": render_dir / "final.mp4",
            "cover.png": render_dir / "cover.png",
            "render-report.json": render_dir / "render-report.json",
            "deliverables.zip": staged_archive,
        }
        for name, staged_path in staged_outputs.items():
            staged_path.replace(output_dir / name)

        result = {
            "status": "ok",
            "video": str((output_dir / "final.mp4").resolve()),
            "cover": str((output_dir / "cover.png").resolve()),
            "subtitles": str((output_dir / "subtitles.srt").resolve()),
            "archive": str((output_dir / "deliverables.zip").resolve()),
            "durationMs": timeline["totalDurationMs"],
            "sceneCount": len(timeline["scenes"]),
            "render": report,
        }
        _write_json_atomic(status_path, {"status": "ok", "runId": run_id, **result})
        return result
    except Exception as exc:
        _write_json_atomic(
            status_path,
            {
                "status": "error",
                "runId": run_id,
                "error": str(exc),
                "previousOutputs": str(previous_outputs) if previous_outputs else None,
            },
        )
        raise


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate a narrated Remotion video from an article-to-video manifest")
    subparsers = parser.add_subparsers(dest="command", required=True)
    validate = subparsers.add_parser("validate", help="validate and normalize a manifest without network access")
    validate.add_argument("--manifest", type=Path, required=True)
    run = subparsers.add_parser("run", help="synthesize speech, render, verify, and package the video")
    run.add_argument("--manifest", type=Path, required=True)
    run.add_argument("--output-dir", type=Path, required=True)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        if args.command == "validate":
            manifest = load_manifest(args.manifest)
            result = {
                "status": "ok",
                "title": manifest["title"],
                "sceneCount": len(manifest["scenes"]),
                "targetDurationSec": manifest["targetDurationSec"],
                "durationToleranceSec": manifest["durationToleranceSec"],
            }
        else:
            result = run_pipeline(args.manifest.resolve(), args.output_dir.expanduser().resolve())
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except (ManifestError, RuntimeError, subprocess.CalledProcessError) as exc:
        print(json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
