#!/usr/bin/env python3
"""Deterministic Edge TTS + Open Motion pipeline for the article-to-video skill."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import os
import re
import shutil
import signal
import subprocess
import sys
import time
import uuid
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

VISUAL_TYPES = {"kinetic-text", "steps", "stat", "quote", "summary", "candlestick"}
FPS_VALUES = {24, 25, 30, 60}
# 立绘硬车道常量 —— 这套几何的单源就在这里：build_timeline 把它注入 timeline.layout，
# open-motion-template/src/types.ts 只保留同名常量作为旧时间线（无 layout 字段）的回退。
# 渲染侧把 presenter 钳在 ceil(440 × scale) px 宽的车道内，内容列让出同一宽度。
PRESENTER_LANE_WIDTH = 440
PRESENTER_LANE_GAP = 24
PRESENTER_EDGE_INSET = 30
CONTENT_SIDE_PADDING = 78
DEFAULT_THEME = {
    "background": "#081120",
    "surface": "#111D32",
    "primary": "#6EE7F9",
    "secondary": "#A78BFA",
    "text": "#F8FAFC",
    # tone 色板（callouts/K线标注用）也在这里注入，TS 侧 toneColor 不再自带回退色。
    "accent": "#FACC15",
    "positive": "#EF4444",
    "negative": "#22C55E",
}
DOMAINS = {"general", "finance", "paper"}
# 金融主题里 positive=红、negative=绿（A 股红涨绿跌约定），蜡烛图涨红跌绿。
DOMAIN_THEMES: dict[str, dict[str, str]] = {
    "general": {},  # 空 = 沿用 DEFAULT_THEME
    "finance": {
        "background": "#0A0E1A",
        "surface": "#141A2E",
        "primary": "#FFD54A",
        "secondary": "#7DD3FC",
        "text": "#F8FAFC",
        "accent": "#FACC15",
        "positive": "#EF4444",
        "negative": "#22C55E",
    },
    "paper": {
        "background": "#0C0A1D",
        "surface": "#151030",
        "primary": "#A78BFA",
        "secondary": "#C084FC",
        "text": "#F8FAFC",
        "accent": "#F59E0B",
        "positive": "#34D399",
        "negative": "#F87171",
    },
}
THEME_FIELDS = frozenset(DEFAULT_THEME) | {"accent", "positive", "negative"}
CALLOUT_TONES = {"accent", "positive", "negative"}
COLOR_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")
ID_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
PROSODY_RE = re.compile(r"^[+-]\d+%$")
PITCH_RE = re.compile(r"^[+-]\d+Hz$")
PUBLISHED_OUTPUTS = ("final.mp4", "cover.png", "render-report.json", "deliverables.zip")


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


def _number(value: Any, field: str) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ManifestError(f"{field} must be a number")
    number = float(value)
    if not math.isfinite(number):
        raise ManifestError(f"{field} must be a finite number")
    return number


def _resolve_library_root(library_root: Path | None) -> Path:
    # 脚本跑在 uv --isolated 下，不能 import ethan；这里复制 ethan/core/config.py 的根目录约定。
    if library_root is not None:
        return library_root
    data_dir = os.environ.get("ETHAN_DATA_DIR")
    base = Path(data_dir).expanduser() if data_dir else Path.home() / ".ethan"
    return base / "assets" / "library"


def _presenter_hint(presenter_id: str) -> str:
    gen_script = Path(__file__).resolve().parent / "presenter_gen.py"
    return (
        f"create it with: python3 {gen_script} prompts {presenter_id}  "
        "# print the prompt pack, generate the images with GPT image 2, then: "
        f"python3 {gen_script} import {presenter_id} <image-dir>"
    )


def _load_presenter(presenter_raw: Any, library_root: Path) -> dict[str, Any]:
    if not isinstance(presenter_raw, dict):
        raise ManifestError("presenter must be an object")
    presenter_id = _require_text(presenter_raw.get("id"), "presenter.id", maximum=64)
    if not ID_RE.fullmatch(presenter_id):
        raise ManifestError("presenter.id must be kebab-case")
    presenter_dir = library_root / "presenters" / presenter_id
    char_path = presenter_dir / "character.json"
    try:
        character = json.loads(char_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ManifestError(
            f"presenter '{presenter_id}' not found in {library_root / 'presenters'} — "
            f"{_presenter_hint(presenter_id)}"
        ) from None
    except json.JSONDecodeError as exc:
        raise ManifestError(f"presenter '{presenter_id}' character.json is invalid JSON: {exc}") from None
    if not isinstance(character, dict):
        raise ManifestError(f"presenter '{presenter_id}' character.json must be an object")
    if character.get("status") != "ready":
        raise ManifestError(
            f"presenter '{presenter_id}' is not ready (status={character.get('status')!r}) — "
            f"finish image generation, then run: "
            f"python3 {Path(__file__).resolve().parent / 'presenter_gen.py'} import {presenter_id} <image-dir>"
        )
    poses_raw = character.get("poses")
    if not isinstance(poses_raw, dict) or not poses_raw:
        raise ManifestError(f"presenter '{presenter_id}' has no poses in character.json")
    poses: dict[str, str] = {}
    for name, rel in poses_raw.items():
        if not isinstance(name, str) or not ID_RE.fullmatch(name):
            raise ManifestError(f"presenter '{presenter_id}' pose names must be kebab-case")
        if not isinstance(rel, str) or not rel:
            raise ManifestError(f"presenter '{presenter_id}' pose '{name}' path must be a non-empty string")
        rel_path = Path(rel)
        if rel_path.is_absolute() or ".." in rel_path.parts:
            raise ManifestError(f"presenter '{presenter_id}' pose '{name}' path must stay inside the presenter dir")
        if not (presenter_dir / rel_path).is_file():
            raise ManifestError(
                f"presenter '{presenter_id}' pose image missing: {rel} — {_presenter_hint(presenter_id)}"
            )
        poses[name] = f"presenters/{presenter_id}/{rel_path.as_posix()}"
    default_pose = presenter_raw.get("defaultPose", "standing")
    if not isinstance(default_pose, str) or default_pose not in poses:
        raise ManifestError(f"presenter.defaultPose must be one of {sorted(poses)}")
    position = presenter_raw.get("position", "right")
    if position not in {"right", "left"}:
        raise ManifestError("presenter.position must be 'right' or 'left'")
    scale = presenter_raw.get("scale", 1.0)
    if not isinstance(scale, (int, float)) or isinstance(scale, bool) or not 0.6 <= float(scale) <= 1.4:
        raise ManifestError("presenter.scale must be a number between 0.6 and 1.4")
    voice = character.get("voice")
    if voice is not None and not isinstance(voice, dict):
        raise ManifestError(f"presenter '{presenter_id}' voice in character.json must be an object")
    return {
        "id": presenter_id,
        "position": position,
        "scale": float(scale),
        "defaultPose": default_pose,
        "cutout": bool(character.get("cutout", True)),
        "poses": poses,
        "voice": voice,
    }


def _normalize_candlestick(visual: dict[str, Any], visual_raw: dict[str, Any], field: str) -> int:
    """校验 candlestick 数据并写入 visual，返回序列长度供 markers 越界检查。"""
    closes_raw = visual_raw.get("closes")
    candles_raw = visual_raw.get("candles")
    if (closes_raw is None) == (candles_raw is None):
        raise ManifestError(f"{field}.visual must provide exactly one of closes or candles")
    if closes_raw is not None:
        if not isinstance(closes_raw, list) or not 8 <= len(closes_raw) <= 120:
            raise ManifestError(f"{field}.visual.closes must contain between 8 and 120 numbers")
        visual["closes"] = [_number(v, f"{field}.visual.closes[]") for v in closes_raw]
        series_len = len(visual["closes"])
    else:
        if not isinstance(candles_raw, list) or not 2 <= len(candles_raw) <= 60:
            raise ManifestError(f"{field}.visual.candles must contain between 2 and 60 items")
        candles: list[dict[str, float]] = []
        for candle_index, candle in enumerate(candles_raw):
            candle_field = f"{field}.visual.candles[{candle_index}]"
            if not isinstance(candle, dict):
                raise ManifestError(f"{candle_field} must be an object")
            values = {key: _number(candle.get(key), f"{candle_field}.{key}") for key in ("o", "h", "l", "c")}
            if values["h"] < max(values["o"], values["c"]) or values["l"] > min(values["o"], values["c"]):
                raise ManifestError(f"{candle_field} must satisfy h >= max(o, c) and l <= min(o, c)")
            candles.append(values)
        visual["candles"] = candles
        series_len = len(candles)
    bands_raw = visual_raw.get("bands")
    if bands_raw is not None:
        if not isinstance(bands_raw, dict):
            raise ManifestError(f"{field}.visual.bands must be an object")
        bands: dict[str, list[float]] = {}
        for band_name in ("upper", "middle", "lower"):
            band_raw = bands_raw.get(band_name)
            if band_raw is None:
                continue
            if not isinstance(band_raw, list) or not band_raw:
                raise ManifestError(f"{field}.visual.bands.{band_name} must be a non-empty list")
            band = [_number(v, f"{field}.visual.bands.{band_name}[]") for v in band_raw]
            if len(band) != series_len:
                raise ManifestError(
                    f"{field}.visual.bands.{band_name} must have the same length as the series ({series_len})"
                )
            bands[band_name] = band
        if bands:
            visual["bands"] = bands
    return series_len


def _normalize_markers(visual: dict[str, Any], visual_raw: dict[str, Any], field: str, series_len: int) -> None:
    markers_raw = visual_raw.get("markers")
    if markers_raw is None:
        return
    if not isinstance(markers_raw, list) or not 1 <= len(markers_raw) <= 4:
        raise ManifestError(f"{field}.visual.markers must contain between 1 and 4 items")
    markers: list[dict[str, Any]] = []
    for marker_index, marker in enumerate(markers_raw):
        marker_field = f"{field}.visual.markers[{marker_index}]"
        if not isinstance(marker, dict):
            raise ManifestError(f"{marker_field} must be an object")
        index = marker.get("index")
        if not isinstance(index, int) or isinstance(index, bool) or not 0 <= index < series_len:
            raise ManifestError(f"{marker_field}.index must be an integer within [0, {series_len})")
        tone = marker.get("tone", "accent")
        if tone not in CALLOUT_TONES:
            raise ManifestError(f"{marker_field}.tone must be one of {sorted(CALLOUT_TONES)}")
        position = marker.get("position", "above")
        if position not in {"above", "below"}:
            raise ManifestError(f"{marker_field}.position must be 'above' or 'below'")
        markers.append(
            {
                "index": index,
                "label": _require_text(marker.get("label"), f"{marker_field}.label", maximum=12),
                "tone": tone,
                "position": position,
            }
        )
    visual["markers"] = markers


def _presenter_overlap_warnings(
    presenter: dict[str, Any], scenes: list[dict[str, Any]], width: int
) -> list[str]:
    """立绘硬车道保证零重叠：内容列被挤没（<=0）直接报错，只是偏窄则给出布局建议。"""
    scale = float(presenter.get("scale", 1.0))
    lane_px = int(PRESENTER_LANE_WIDTH * scale + 0.999)  # ceil，与 TS 侧 presenterLanePx 一致
    content_px = width - CONTENT_SIDE_PADDING - (PRESENTER_EDGE_INSET + lane_px + PRESENTER_LANE_GAP)
    if content_px <= 0:
        # 极端组合（窄画布 + 大 scale）下内容列被立绘车道挤没，渲染必炸，直接拒绝。
        raise ManifestError(
            f"content column has no room left ({content_px}px at width={width} with presenter "
            f"scale={scale:g}): reduce presenter.scale, increase width, or hide the presenter per scene"
        )
    warnings: list[str] = []
    for scene in scenes:
        override = scene.get("presenter") or {}
        if override.get("visible") is False:
            continue
        visual = scene.get("visual") or {}
        visual_type = visual.get("type")
        if visual_type == "candlestick":
            warnings.append(
                f"scenes[{scene['id']}]: candlestick 与立绘同屏时图表仅约 {content_px}px 宽，"
                '建议该场景 presenter: {"visible": false} 用满全宽'
            )
        elif visual_type == "quote" and len(str(visual.get("quote") or "")) > 60:
            warnings.append(
                f"scenes[{scene['id']}]: 长引用（>60 字）与立绘同屏会排得过挤，"
                '建议该场景 presenter: {"visible": false}'
            )
        elif visual_type == "stat" and len(str(visual.get("value") or "")) > 8:
            warnings.append(
                f"scenes[{scene['id']}]: stat 值超过 8 字符，与立绘同屏时字号会被压缩，"
                "建议缩短 value 或隐藏立绘"
            )
    return warnings


def normalize_manifest(raw: Any, *, library_root: Path | None = None) -> dict[str, Any]:
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

    domain_raw = raw.get("domain", "general")
    if domain_raw is None:
        domain = "general"
    elif isinstance(domain_raw, str):
        domain = domain_raw.strip() or "general"
    else:
        raise ManifestError("domain must be a string or null")
    if domain not in DOMAINS:
        raise ManifestError(f"domain must be one of {sorted(DOMAINS)}")

    presenter = None
    if raw.get("presenter") is not None:
        presenter = _load_presenter(raw["presenter"], _resolve_library_root(library_root))

    voice_raw = raw.get("voice")
    voice_inherited = voice_raw is None and presenter is not None and bool(presenter.get("voice"))
    if voice_inherited:
        # 角色包自带音色：manifest 不显式指定 voice 时继承，让虚拟 IP 声音稳定。
        voice_raw = presenter["voice"]
    voice_raw = voice_raw or {}
    if not isinstance(voice_raw, dict):
        raise ManifestError("voice must be an object")
    try:
        voice = {
            "name": _require_text(voice_raw.get("name", "zh-CN-XiaoyiNeural"), "voice.name", maximum=100),
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
    except ManifestError as exc:
        if voice_inherited:
            # 报错要指向真正的修改位置：这个 voice 来自 presenter 的 character.json，
            # 不是 manifest 里显式写的。
            raise ManifestError(
                f"{exc} (inherited from presenter character.json — fix the voice "
                "object in the presenter's character.json, not the manifest)"
            ) from None
        raise

    theme_raw = raw.get("theme") or {}
    if not isinstance(theme_raw, dict):
        raise ManifestError("theme must be an object")
    theme = {**DEFAULT_THEME, **DOMAIN_THEMES.get(domain, {}), **theme_raw}
    for key, color in theme.items():
        if key not in THEME_FIELDS:
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
        elif visual_type == "candlestick":
            series_len = _normalize_candlestick(visual, visual_raw, field)
            _normalize_markers(visual, visual_raw, field, series_len)
        callouts_raw = item.get("callouts")
        callouts: list[dict[str, Any]] = []
        if callouts_raw is not None:
            if not isinstance(callouts_raw, list) or not 1 <= len(callouts_raw) <= 3:
                raise ManifestError(f"{field}.callouts must contain between 1 and 3 items")
            for callout_index, callout in enumerate(callouts_raw):
                callout_field = f"{field}.callouts[{callout_index}]"
                if not isinstance(callout, dict):
                    raise ManifestError(f"{callout_field} must be an object")
                tone = callout.get("tone", "accent")
                if tone not in CALLOUT_TONES:
                    raise ManifestError(f"{callout_field}.tone must be one of {sorted(CALLOUT_TONES)}")
                callouts.append(
                    {"text": _require_text(callout.get("text"), f"{callout_field}.text", maximum=12), "tone": tone}
                )
        scene_presenter_raw = item.get("presenter")
        scene_presenter: dict[str, Any] | None = None
        if scene_presenter_raw is not None:
            if presenter is None:
                raise ManifestError(f"{field}.presenter requires a top-level presenter")
            if not isinstance(scene_presenter_raw, dict):
                raise ManifestError(f"{field}.presenter must be an object")
            visible = scene_presenter_raw.get("visible", True)
            if not isinstance(visible, bool):
                raise ManifestError(f"{field}.presenter.visible must be a boolean")
            pose = scene_presenter_raw.get("pose")
            if pose is not None and (not isinstance(pose, str) or pose not in presenter["poses"]):
                raise ManifestError(f"{field}.presenter.pose must be one of {sorted(presenter['poses'])}")
            scene_presenter = {"pose": pose, "visible": visible}
        scene: dict[str, Any] = {
            "id": scene_id,
            "narration": narration,
            "headline": headline,
            "body": body.strip(),
            "visual": visual,
        }
        if callouts:
            scene["callouts"] = callouts
        if scene_presenter is not None:
            scene["presenter"] = scene_presenter
        scenes.append(scene)

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
        "domain": domain,
        "voice": voice,
        "theme": theme,
        "scenes": scenes,
    }
    if presenter is not None:
        # voice 只用于 TTS 继承，不进 timeline/渲染侧。
        result["presenter"] = {key: value for key, value in presenter.items() if key != "voice"}
        warnings = _presenter_overlap_warnings(presenter, scenes, width)
        if warnings:
            result["warnings"] = warnings
    if len(result["summary"]) > 200:
        raise ManifestError("summary must be at most 200 characters")
    return result


def load_manifest(path: Path, *, library_root: Path | None = None) -> dict[str, Any]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ManifestError(f"manifest not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ManifestError(f"manifest is not valid JSON: {exc}") from exc
    return normalize_manifest(raw, library_root=library_root)


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
            # tail-merge：若前块非标点结尾且 remaining 非标点开头，补一个空格防词粘连。
            prev_tail = chunks[-1][-1:] if chunks else ""
            next_head = remaining[0]
            need_space = prev_tail and next_head and prev_tail not in "，。！？；,.!?;" and next_head not in "，。！？；,.!?;"
            # 合并后长度要加上可能补的空格（+1 if need_space），不能只算两段原长。
            if chunks and len(chunks[-1]) + len(remaining) + (1 if need_space else 0) <= maximum:
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


# 同 key 的并发合成去重：多个场景 narration+voice 相同时只合成一次，后续 await 同一个 Future。
_inflight_tts: dict[str, asyncio.Future[None]] = {}


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
    # 同 key 并发去重：首个合成者创建 Future 并执行，后续者 await 同一个 Future 不重复合成。
    if key in _inflight_tts:
        await _inflight_tts[key]
        return
    loop = asyncio.get_running_loop()
    fut: asyncio.Future[None] = loop.create_future()
    _inflight_tts[key] = fut
    try:
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
        if not fut.done():
            fut.set_result(None)
    except BaseException as exc:
        if not fut.done():
            fut.set_exception(exc)
        raise
    finally:
        _inflight_tts.pop(key, None)


def synthesize_scenes(manifest: dict[str, Any], output_dir: Path, *, retries: int = 3) -> list[dict[str, Any]]:
    cache_dir = output_dir / "work" / "tts-cache"
    audio_dir = output_dir / "work" / "public" / "audio"
    subtitle_dir = output_dir / "work" / "scene-subtitles"
    for directory in (cache_dir, audio_dir, subtitle_dir):
        directory.mkdir(parents=True, exist_ok=True)

    # 所有场景在同一个事件循环里并发合成（单场景内仍带重试），不再每场景一次 asyncio.run。
    # return_exceptions=True 防止单场景失败级联取消其余协程（CancelledError 不会被
    # except Exception 捕获，会留下 .tmp 残留文件）。收集结果后如有失败则统一抛出。
    _inflight_tts.clear()  # 上次 run 的 Future 属于旧事件循环，必须清掉

    async def _synthesize_all() -> list[BaseException | None]:
        return await asyncio.gather(
            *[_synthesize_scene(scene, manifest["voice"], cache_dir, retries=retries) for scene in manifest["scenes"]],
            return_exceptions=True,
        )

    results = asyncio.run(_synthesize_all())
    failed = [(i, r) for i, r in enumerate(results) if isinstance(r, BaseException)]
    if failed:
        # 清理残留的 .tmp 文件
        for tmp in cache_dir.glob(".*.tmp"):
            tmp.unlink(missing_ok=True)
        idx, exc = failed[0]
        raise RuntimeError(f"TTS failed for scene {manifest['scenes'][idx]['id']}: {exc}") from exc

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
    timeline = {
        "title": manifest["title"],
        "summary": manifest["summary"],
        "width": manifest["width"],
        "height": manifest["height"],
        "fps": manifest["fps"],
        "totalDurationMs": offset,
        "domain": manifest.get("domain", "general"),
        "theme": manifest["theme"],
        # 立绘硬车道几何注入（单源在本文件顶部常量）：渲染侧 resolveLayout 直接消费，
        # validate 的 _presenter_overlap_warnings 也用同一组值，三处永不漂移。
        "layout": {
            "presenterLaneWidth": PRESENTER_LANE_WIDTH,
            "presenterLaneGap": PRESENTER_LANE_GAP,
            "presenterEdgeInset": PRESENTER_EDGE_INSET,
            "contentSidePadding": CONTENT_SIDE_PADDING,
        },
        "scenes": scenes,
        "captions": captions,
        "_combinedSubtitles": combined,
    }
    if manifest.get("presenter"):
        timeline["presenter"] = manifest["presenter"]
    return timeline


def stage_assets(manifest: dict[str, Any], output_dir: Path, *, library_root: Path | None = None) -> None:
    """把资产库里的 presenter 立绘铺到 work/public/ 下，供渲染时通过 HTTP 访问。

    poses 的值形如 presenters/<id>/poses/<name>.png，本身就是相对库根的路径。
    优先硬链接（同盘零拷贝），跨设备时回退 copy2。validate 已确认姿势文件存在。
    """
    presenter = manifest.get("presenter")
    if not presenter:
        return
    root = _resolve_library_root(library_root)
    for public_rel in presenter["poses"].values():
        src = root / public_rel
        dst = output_dir / "work" / "public" / public_rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.unlink(missing_ok=True)
        try:
            os.link(src, dst)
        except OSError:
            shutil.copy2(src, dst)


def _run_command(command: list[str], *, cwd: Path, timeout: float) -> None:
    # 捕获 stderr，失败时把 Node/Open Motion/pnpm 的诊断写进 run-status.json，
    # 否则只留 "non-zero exit status 1"，agent 无法定位渲染失败原因。
    # timeout 必传：渲染器内部（Playwright / Chromium / 本地 http server）任一环节
    # 挂死时必须超时终止，否则整条流水线无限期等待，且不留任何诊断。
    # 显式 encoding/errors 代替 text=True：后者跟随 locale（如 POSIX C locale 下按
    # ASCII 解码）遇到非 ASCII 输出直接 UnicodeDecodeError 崩溃。
    # 新会话/新进程组：渲染会 fork 出 Chromium 多代子进程，超时必须杀整个进程组，
    # 只杀父进程会留下孤儿 Chromium 继续吃 CPU/内存。
    popen_kwargs: dict[str, Any] = {}
    if os.name == "nt":
        popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        popen_kwargs["start_new_session"] = True
    process = subprocess.Popen(
        command,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        encoding="utf-8",
        errors="replace",
        **popen_kwargs,
    )
    try:
        _, stderr = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        # POSIX：SIGKILL 整个进程组（start_new_session 让渲染进程自成组长）；
        # 进程组已消失/无权限时容错退回只杀父进程，再 communicate() 收尸回收管道。
        if os.name == "nt":
            process.kill()
        else:
            try:
                os.killpg(os.getpgid(process.pid), signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                process.kill()
        try:
            process.communicate(timeout=30)
        except (subprocess.TimeoutExpired, OSError):
            pass
        # TimeoutExpired 的 stderr 是超时前已捕获的部分输出，保留它才能看出卡在哪一步。
        # 注意：即使传了 encoding，超时路径给回来的仍是 bytes（CPython 不在该路径解码），
        # 所以必须自己解码，否则这段诊断会被静默丢掉。
        raw = exc.stderr
        if isinstance(raw, (bytes, bytearray)):
            raw = raw.decode("utf-8", errors="replace")
        partial = (raw or "").strip()
        detail = f"\npartial stderr:\n{partial}" if partial else ""
        raise RuntimeError(
            f"command timed out after {timeout:.0f}s ({' '.join(command)}){detail}"
        ) from exc
    if process.returncode != 0:
        detail = f"\nstderr:\n{stderr.strip()}" if stderr and stderr.strip() else ""
        raise RuntimeError(f"command failed ({' '.join(command)}): exit {process.returncode}{detail}")
    # pnpm/node 正常输出走 stderr（进度日志），透传给上层日志，不静默吞掉。
    if stderr and stderr.strip():
        sys.stderr.write(stderr)


# pnpm install（含首次拉取 Playwright Chromium）与整轮渲染的上限。渲染侧
# renderFrames 自带 600s 帧捕获超时，外层留足 vite build + ffmpeg 编码的余量。
INSTALL_TIMEOUT_SEC = 1800.0
RENDER_TIMEOUT_SEC = 3600.0


def ensure_renderer(template_dir: Path) -> None:
    if shutil.which("node") is None or shutil.which("pnpm") is None:
        raise RuntimeError("Node.js and pnpm are required to render the video")
    marker = template_dir / "node_modules" / "@open-motion" / "core" / "package.json"
    if not marker.exists():
        _run_command(
            ["pnpm", "install", "--ignore-workspace", "--frozen-lockfile"],
            cwd=template_dir,
            timeout=INSTALL_TIMEOUT_SEC,
        )


def render_video(
    template_dir: Path,
    render_dir: Path,
    timeline_path: Path,
    public_dir: Path,
    *,
    target_duration_sec: float = 0.0,
) -> None:
    ensure_renderer(template_dir)
    render_dir.mkdir(parents=True, exist_ok=True)
    # 渲染超时随片长伸缩：长片按 6× 目标时长取上限（1800s 长片 → 10800s），
    # 短片仍以 RENDER_TIMEOUT_SEC 兜底；pnpm install 超时保持不变（ensure_renderer 内）。
    timeout = max(RENDER_TIMEOUT_SEC, int(target_duration_sec * 6))
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
        timeout=timeout,
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
    existing = [output_dir / name for name in PUBLISHED_OUTPUTS if (output_dir / name).exists()]
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
    for warning in manifest.get("warnings", []):
        print(f"WARNING: {warning}", file=sys.stderr)
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
        stage_assets(manifest, output_dir)
        artifacts = synthesize_scenes(manifest, output_dir)
        timeline = build_timeline(manifest, artifacts)
        combined = timeline.pop("_combinedSubtitles")
        timeline_path = output_dir / "timeline.json"
        _write_json_atomic(timeline_path, timeline)
        (output_dir / "subtitles.srt").write_text(serialize_srt(combined), encoding="utf-8")
        enforce_target_duration(manifest, timeline)

        render_dir = output_dir / "work" / "render-runs" / run_id
        template_dir = Path(__file__).resolve().parent.parent / "assets" / "open-motion-template"
        # 渲染超时按片长伸缩：优先用 manifest 校验过的 targetDurationSec，
        # 未设目标时长则用 timeline 实际总时长兜底。
        target_duration_sec = manifest["targetDurationSec"] or timeline["totalDurationMs"] / 1000
        render_video(
            template_dir,
            render_dir,
            timeline_path,
            output_dir / "work" / "public",
            target_duration_sec=target_duration_sec,
        )
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
        # 本次 run 的渲染目录里只有半成品（成功产物在成功路径已 replace 到 output_dir
        # 根），best-effort 清掉防止 render-runs 堆积垃圾；共享缓存（tts-cache/public/
        # previous-runs）不动，只清本次 run_id 的目录。
        shutil.rmtree(output_dir / "work" / "render-runs" / run_id, ignore_errors=True)
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
    parser = argparse.ArgumentParser(description="Generate a narrated Open Motion video from an article-to-video manifest")
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
            for warning in manifest.get("warnings", []):
                print(f"WARNING: {warning}", file=sys.stderr)
            result = {
                "status": "ok",
                "title": manifest["title"],
                "sceneCount": len(manifest["scenes"]),
                "targetDurationSec": manifest["targetDurationSec"],
                "durationToleranceSec": manifest["durationToleranceSec"],
                "warnings": manifest.get("warnings", []),
            }
        else:
            result = run_pipeline(args.manifest.resolve(), args.output_dir.expanduser().resolve())
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except Exception as exc:
        print(json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
