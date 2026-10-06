#!/usr/bin/env python3
"""Deterministic Edge TTS audio pipeline for the book-audio-digest skill.

与 article-to-video 的 video_pipeline.py 共用同一套 TTS 纪律（章节级 content-hash
缓存、原子发布、并发去重、指数退避重试），但只负责音频：合成 → 按章节拼接
（章节间插入静音）→ 合并字幕 → 产出 final.mp3 + subtitles.srt + run-status.json。

状态回显约定（SKILL 的后台合成 `nohup ... > render.log 2>&1` 依赖它）：
  - run-status.json 在开工时先落 `{"status": "running", "stage": ...}`，结束后改写为
    ok / error；失败时带 `stage`（哪一步炸的）+ `error`（可直接展示的原因）。
  - 进度走 **stderr**（stdout 只留给最终 JSON），逐节打印合成/缓存命中/重试，
    这样 1–3 分钟的合成期里 render.log 不是空的，轮询者能区分「在跑」和「挂了」。
  - 失败时清掉 final.mp3 / subtitles.srt 等旧产物：否则上一轮成功的音频会和新写的
    error 状态并存，「status 是 ok 且文件存在」的复核会拿陈年产物当本次交付。

用法：
  python audio_pipeline.py validate --manifest manifest.json
  python audio_pipeline.py run --manifest manifest.json --output-dir PROJECT_DIR

运行时依赖 edge-tts（用 uv 临时注入，不进主安装包）：
  uv run --isolated --no-project --with 'edge-tts>=7,<8' python audio_pipeline.py run ...
系统依赖 FFmpeg（拼接、静音生成、时长探测）。
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import re
import shutil
import subprocess
import sys
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROSODY_RE = re.compile(r"^[+-]\d+%$")
PITCH_RE = re.compile(r"^[+-]\d+Hz$")
ID_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
MAX_SECTIONS = 40
MAX_NARRATION_CHARS = 3000
MIN_TOTAL_DURATION_MS = 30_000
MAX_TOTAL_DURATION_MS = 7_200_000
# edge-tts 默认输出格式是 24kHz mono MP3；静音文件必须匹配，concat demuxer 才能直拼。
EDGE_SAMPLE_RATE = 24_000


class ManifestError(ValueError):
    pass


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _progress(message: str) -> None:
    """把进度写到 stderr：stdout 只留给最终 JSON，进度混进去会让解析方读坏。"""
    print(f"[audio-pipeline] {message}", file=sys.stderr, flush=True)


# 失败时可以安全删掉的旧产物：状态是 error 时它们绝不能看起来像本次结果。
MOOT_OUTPUTS = ("final.mp3", "subtitles.srt")


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


def normalize_manifest(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ManifestError("manifest root must be an object")
    title = _require_text(raw.get("title"), "title", maximum=120)

    voice_raw = raw.get("voice") or {}
    if not isinstance(voice_raw, dict):
        raise ManifestError("voice must be an object")
    voice = {
        "name": _require_text(voice_raw.get("name", "zh-CN-YunxiNeural"), "voice.name", maximum=100),
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

    gap_ms = raw.get("gapMs", 700)
    if not isinstance(gap_ms, int) or isinstance(gap_ms, bool) or not 0 <= gap_ms <= 5000:
        raise ManifestError("gapMs must be an integer between 0 and 5000")

    target_duration = raw.get("targetDurationSec")
    if target_duration is not None:
        if (
            not isinstance(target_duration, (int, float))
            or isinstance(target_duration, bool)
            or not 60 <= target_duration <= 3600
        ):
            raise ManifestError("targetDurationSec must be a number between 60 and 3600")

    sections_raw = raw.get("sections")
    if not isinstance(sections_raw, list) or not 1 <= len(sections_raw) <= MAX_SECTIONS:
        raise ManifestError(f"sections must contain between 1 and {MAX_SECTIONS} items")

    seen: set[str] = set()
    sections: list[dict[str, Any]] = []
    for index, item in enumerate(sections_raw):
        field = f"sections[{index}]"
        if not isinstance(item, dict):
            raise ManifestError(f"{field} must be an object")
        section_id = _require_text(item.get("id"), f"{field}.id", maximum=64)
        if not ID_RE.fullmatch(section_id):
            raise ManifestError(f"{field}.id must be kebab-case")
        if section_id in seen:
            raise ManifestError(f"duplicate section id: {section_id}")
        seen.add(section_id)
        narration = _require_text(item.get("narration"), f"{field}.narration", maximum=MAX_NARRATION_CHARS)
        sections.append({"id": section_id, "narration": narration})

    return {
        "title": title,
        "voice": voice,
        "gapMs": gap_ms,
        "targetDurationSec": float(target_duration) if target_duration is not None else None,
        "sections": sections,
    }


def load_manifest(path: Path) -> dict[str, Any]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ManifestError(f"manifest not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ManifestError(f"manifest is not valid JSON: {exc}") from exc
    return normalize_manifest(raw)


# ---------------------------------------------------------------------------
# SRT 解析/序列化（与 video_pipeline.py 同构，standalone 只依赖 stdlib）
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# TTS：content-hash 缓存 + 并发去重 + 重试 + 原子发布（纪律同 video_pipeline）
# ---------------------------------------------------------------------------


def _tts_cache_key(section: dict[str, Any], voice: dict[str, str]) -> str:
    payload = json.dumps({"narration": section["narration"], "voice": voice}, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]


def _valid_tts_cache(media_path: Path, srt_path: Path) -> bool:
    try:
        return media_path.stat().st_size >= 256 and bool(parse_srt(srt_path.read_text(encoding="utf-8")))
    except (OSError, UnicodeError, ValueError):
        return False


_inflight_tts: dict[str, asyncio.Future[None]] = {}


async def _synthesize_once(text: str, voice: dict[str, str], media_path: Path, srt_path: Path) -> None:
    try:
        import edge_tts
    except ImportError as exc:
        raise RuntimeError(
            "edge-tts is missing; run with: uv run --isolated --no-project --with 'edge-tts>=7,<8' python ..."
        ) from exc

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


async def _synthesize_section(
    section: dict[str, Any], voice: dict[str, str], cache_dir: Path, *, retries: int
) -> None:
    """单章节 TTS：校验缓存 → 带重试的合成 → 原子替换缓存文件。"""
    key = _tts_cache_key(section, voice)
    cached_audio = cache_dir / f"{key}.mp3"
    cached_srt = cache_dir / f"{key}.srt"
    if _valid_tts_cache(cached_audio, cached_srt):
        _progress(f"缓存命中 {section['id']}")
        return
    if key in _inflight_tts:
        _progress(f"等待重复文本的同一份合成结果 {section['id']}")
        await _inflight_tts[key]
        return
    loop = asyncio.get_running_loop()
    fut: asyncio.Future[None] = loop.create_future()
    _inflight_tts[key] = fut
    try:
        cached_audio.unlink(missing_ok=True)
        cached_srt.unlink(missing_ok=True)
        last_error: Exception | None = None
        _progress(f"合成中 {section['id']}（{len(section['narration'])} 字）")
        for attempt in range(1, retries + 1):
            nonce = uuid.uuid4().hex
            pending_audio = cache_dir / f".{key}.{nonce}.mp3.tmp"
            pending_srt = cache_dir / f".{key}.{nonce}.srt.tmp"
            try:
                await _synthesize_once(section["narration"], voice, pending_audio, pending_srt)
                if not _valid_tts_cache(pending_audio, pending_srt):
                    raise RuntimeError("Edge TTS produced an invalid cache entry")
                pending_audio.replace(cached_audio)
                pending_srt.replace(cached_srt)
                last_error = None
                _progress(f"合成完成 {section['id']}")
                break
            except Exception as exc:  # network/service failures are retriable
                last_error = exc
                pending_audio.unlink(missing_ok=True)
                pending_srt.unlink(missing_ok=True)
                if attempt < retries:
                    _progress(f"第 {attempt} 次失败，{attempt * 1.5:.1f}s 后重试 {section['id']}：{exc}")
                    await asyncio.sleep(attempt * 1.5)
        if last_error is not None:
            raise RuntimeError(f"TTS failed for section {section['id']}: {last_error}") from last_error
        if not fut.done():
            fut.set_result(None)
    except BaseException as exc:
        if not fut.done():
            fut.set_exception(exc)
            # 消费掉一次：无 awaiter（没人等这份重复合成）时，asyncio 会在 GC 时打
            # "Future exception was never retrieved" 噪声到 render.log，把真因淹没。
            fut.exception()
        raise
    finally:
        _inflight_tts.pop(key, None)


def synthesize_sections(manifest: dict[str, Any], output_dir: Path, *, retries: int = 3) -> list[dict[str, Any]]:
    cache_dir = output_dir / "work" / "tts-cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    _inflight_tts.clear()  # 上次 run 的 Future 属于旧事件循环，必须清掉

    async def _synthesize_all() -> list[BaseException | None]:
        return await asyncio.gather(
            *[_synthesize_section(s, manifest["voice"], cache_dir, retries=retries) for s in manifest["sections"]],
            return_exceptions=True,
        )

    results = asyncio.run(_synthesize_all())
    failed = [(i, r) for i, r in enumerate(results) if isinstance(r, BaseException)]
    if failed:
        for tmp in cache_dir.glob(".*.tmp"):
            tmp.unlink(missing_ok=True)
        # _synthesize_section 抛出的异常已经写了 "TTS failed for section <id>: …"，
        # 这里再包一层前缀会得到「TTS failed for section x: TTS failed for section x: 真因」
        # 这种看不出真因的报错。原样抛出，保留原始异常类型与信息。
        raise failed[0][1]

    artifacts: list[dict[str, Any]] = []
    for section in manifest["sections"]:
        key = _tts_cache_key(section, manifest["voice"])
        artifacts.append(
            {
                "id": section["id"],
                "audio": cache_dir / f"{key}.mp3",
                "srt": cache_dir / f"{key}.srt",
            }
        )
    return artifacts


# ---------------------------------------------------------------------------
# FFmpeg：静音生成、时长探测、拼接
# ---------------------------------------------------------------------------


def _run_command(command: list[str]) -> str:
    completed = subprocess.run(command, check=False, capture_output=True, text=True)
    if completed.returncode != 0:
        stderr = completed.stderr.strip()
        detail = f"\nstderr:\n{stderr}" if stderr else ""
        raise RuntimeError(f"command failed ({command[0]} ...): exit {completed.returncode}{detail}")
    return completed.stdout


def probe_duration_ms(path: Path) -> int:
    """ffprobe 探测音频时长（毫秒）。MP3 帧粒度带来的 ±30ms 误差对字幕偏移可忽略。"""
    out = _run_command(
        [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(path),
        ]
    )
    seconds = float(out.strip())
    if seconds <= 0:
        raise RuntimeError(f"invalid duration for {path}: {seconds}")
    return round(seconds * 1000)


def _escape_concat_path(path: Path) -> str:
    # concat 列表语法：file 'path'；单引号用 '\'' 转义
    return str(path).replace("'", "'\\''")


def generate_silence(work_dir: Path, gap_ms: int) -> Path:
    gap_path = work_dir / f"silence-{gap_ms}ms.mp3"
    if not gap_path.exists():
        _run_command(
            [
                "ffmpeg", "-y", "-v", "error",
                "-f", "lavfi", "-i", f"anullsrc=r={EDGE_SAMPLE_RATE}:cl=mono",
                "-t", f"{gap_ms / 1000:.3f}",
                "-c:a", "libmp3lame", "-q:a", "9",
                str(gap_path),
            ]
        )
    return gap_path


def concat_audio(
    manifest: dict[str, Any], artifacts: list[dict[str, Any]], output_dir: Path, silence_path: Path | None
) -> None:
    """按章节顺序拼接成 final.mp3（重编码保证参数一致；带 ID3 元数据便于车机显示）。"""
    list_path = output_dir / "work" / "concat-list.txt"
    lines: list[str] = []
    for index, artifact in enumerate(artifacts):
        lines.append(f"file '{_escape_concat_path(artifact['audio'])}'")
        if silence_path is not None and index < len(artifacts) - 1:
            lines.append(f"file '{_escape_concat_path(silence_path)}'")
    list_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    final_path = output_dir / "final.mp3"
    pending = output_dir / "work" / "final.pending.mp3"
    pending.unlink(missing_ok=True)
    _run_command(
        [
            "ffmpeg", "-y", "-v", "error",
            "-f", "concat", "-safe", "0",
            "-i", str(list_path),
            "-c:a", "libmp3lame", "-q:a", "2",
            "-metadata", f"title={manifest['title']}",
            "-metadata", "artist=Ethan",
            "-metadata", "album=深度听书笔记",
            str(pending),
        ]
    )
    if pending.stat().st_size < 8_192:
        raise RuntimeError("concatenated audio is suspiciously small")
    pending.replace(final_path)


def build_merged_subtitles(
    manifest: dict[str, Any], artifacts: list[dict[str, Any]], durations_ms: list[int]
) -> list[Subtitle]:
    """把各章节 SRT 按实际音频时长 + 章节间静音偏移合并成全局字幕。"""
    gap_ms = manifest["gapMs"]
    combined: list[Subtitle] = []
    offset = 0
    for artifact, duration_ms in zip(artifacts, durations_ms, strict=True):
        local = parse_srt(Path(artifact["srt"]).read_text(encoding="utf-8"))
        for item in local:
            combined.append(
                Subtitle(text=item.text, start_ms=offset + item.start_ms, end_ms=offset + item.end_ms)
            )
        offset += duration_ms + gap_ms
    return combined


# ---------------------------------------------------------------------------
# Pipeline 入口
# ---------------------------------------------------------------------------


def _clear_moot_outputs(output_dir: Path) -> None:
    """删掉上一轮可能残留的产物与半成品（失败路径专用）。"""
    for name in MOOT_OUTPUTS:
        (output_dir / name).unlink(missing_ok=True)
    work_dir = output_dir / "work"
    if work_dir.is_dir():
        for leftover in list(work_dir.glob("*.tmp")) + [work_dir / "final.pending.mp3"]:
            leftover.unlink(missing_ok=True)


def run_pipeline(manifest_path: Path, output_dir: Path) -> dict[str, Any]:
    manifest = load_manifest(manifest_path)
    output_dir.mkdir(parents=True, exist_ok=True)
    status_path = output_dir / "run-status.json"
    started_at = _now_iso()

    def _write(status: dict[str, Any]) -> dict[str, Any]:
        status_path.write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8")
        return status

    def _fail(error: str, stage: str) -> dict[str, Any]:
        # 先毁产物再写状态：反过来（先写 error、产物还在）会让「status ok 且文件存在」的
        # 复核步骤误把上一轮/本次的残缺音频当成可交付结果。
        _clear_moot_outputs(output_dir)
        _progress(f"失败（{stage}）：{error}")
        return _write(
            {
                "status": "error",
                "stage": stage,
                "error": error,
                "startedAt": started_at,
                "finishedAt": _now_iso(),
            }
        )

    # 先落 running 状态：否则整个合成期 status 文件根本不存在，轮询者分不清
    # 「还没开始」和「正在跑」（SKILL 的复核/进度回显都读这个文件）。
    _write(
        {
            "status": "running",
            "stage": "preflight",
            "title": manifest["title"],
            "sectionCount": len(manifest["sections"]),
            "targetDurationSec": manifest["targetDurationSec"],
            "startedAt": started_at,
        }
    )

    stage = "preflight"
    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        return _fail("FFmpeg (ffmpeg + ffprobe) is required for audio assembly", stage)

    try:
        stage = "synthesis"
        _progress(f"开始合成 {len(manifest['sections'])} 节（voice={manifest['voice']['name']}）")
        artifacts = synthesize_sections(manifest, output_dir)

        stage = "duration-probe"
        _progress("探测各章节时长…")
        durations_ms = [probe_duration_ms(artifact["audio"]) for artifact in artifacts]
        silence_path = None
        if manifest["gapMs"] > 0:
            silence_path = generate_silence(output_dir / "work", manifest["gapMs"])

        stage = "concat"
        _progress(f"拼接 {len(artifacts)} 节（章节间静音 {manifest['gapMs']}ms）…")
        concat_audio(manifest, artifacts, output_dir, silence_path)

        stage = "verify"
        final_path = output_dir / "final.mp3"
        total_duration_ms = probe_duration_ms(final_path)
        if not MIN_TOTAL_DURATION_MS <= total_duration_ms <= MAX_TOTAL_DURATION_MS:
            return _fail(
                f"final audio duration {total_duration_ms / 1000:.1f}s outside allowed range "
                f"[{MIN_TOTAL_DURATION_MS / 1000:.0f}s, {MAX_TOTAL_DURATION_MS / 1000:.0f}s]; "
                "请调整 manifest 的 sections 长度或 targetDurationSec 后重跑",
                stage,
            )

        stage = "subtitles"
        combined = build_merged_subtitles(manifest, artifacts, durations_ms)
        (output_dir / "subtitles.srt").write_text(serialize_srt(combined), encoding="utf-8")

        target = manifest["targetDurationSec"]
        status = {
            "status": "ok",
            "title": manifest["title"],
            "sectionCount": len(artifacts),
            "totalDurationMs": total_duration_ms,
            "voice": manifest["voice"],
            "outputs": {
                "audio": str(final_path),
                "subtitles": str(output_dir / "subtitles.srt"),
            },
        }
        if target is not None:
            status["targetDurationSec"] = target
            status["durationDeviationSec"] = round(total_duration_ms / 1000 - target, 1)
        status["startedAt"] = started_at
        status["finishedAt"] = _now_iso()
        _progress(
            f"完成：{total_duration_ms / 1000:.1f}s → {final_path}（字幕 {output_dir / 'subtitles.srt'}）"
        )
        return _write(status)
    except Exception as exc:
        return _fail(str(exc), stage)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Edge TTS audio assembly pipeline (book-audio-digest)")
    sub = parser.add_subparsers(dest="command", required=True)
    validate = sub.add_parser("validate", help="validate manifest without network access")
    validate.add_argument("--manifest", required=True, type=Path)
    run = sub.add_parser("run", help="synthesize and assemble audio")
    run.add_argument("--manifest", required=True, type=Path)
    run.add_argument("--output-dir", required=True, type=Path)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        if args.command == "validate":
            manifest = load_manifest(args.manifest)
            result = {
                "status": "ok",
                "title": manifest["title"],
                "sectionCount": len(manifest["sections"]),
                "gapMs": manifest["gapMs"],
                "targetDurationSec": manifest["targetDurationSec"],
                "estimatedChars": sum(len(s["narration"]) for s in manifest["sections"]),
            }
        else:
            result = run_pipeline(args.manifest.resolve(), args.output_dir.expanduser().resolve())
        print(json.dumps(result, ensure_ascii=False))
        return 0 if result.get("status") == "ok" else 1
    except Exception as exc:
        print(json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
