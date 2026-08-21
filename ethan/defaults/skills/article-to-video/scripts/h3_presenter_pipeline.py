#!/usr/bin/env python3
"""Prepare and composite deterministic article-to-video scenes with MiniMax H3.

H3 is used only for presenter performance (body motion, expression, lip sync and
native audio).  The typography/data UI remains a deterministic clean plate.  A
production foreground-mask composition keeps Xiaoyu's hands in front of the UI;
the boundary mode is a quick fallback for shots whose presenter stays in a
dedicated right-side lane.

This module deliberately has no network dependency.  Uploading/queueing the
prepared references happens in the user's existing ComfyUI H3 workflow.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


class PipelineError(RuntimeError):
    """A recoverable H3 presenter pipeline error."""


@dataclass(frozen=True)
class MediaInfo:
    path: str
    width: int
    height: int
    duration_seconds: float | None = None
    fps: str | None = None
    has_audio: bool = False


# 内置 presenter 身份：未指定角色包时的默认「小雨」。
# 指定 prepare --presenter <id> 时，身份以资产库 presenters/<id>/character.json 的
# name/description 为唯一来源，不在这里重复维护角色外观。
DEFAULT_PRESENTER = {
    "name": "Xiaoyu",
    "description": (
        "face, silver-white long hair, blue eyes, blue X hair clip, "
        "black business suit, white shirt, blue tie and blue lanyard"
    ),
}

DEFAULT_MOTION_PLAN = """0.0–1.5s: {name} faces the camera with a warm smile and presents the dashboard with an open palm.
1.5–3.5s: Natural speaking with one blink, subtle breathing and a small confident nod.
3.5–5.5s: Smoothly raise a hand and point to the valuation card. Shoulder, elbow, wrist and index finger move continuously.
5.5–6.5s: Lower the hand slightly and return to a reassuring smile. Hair and outfit details have subtle secondary motion."""


def _run(command: list[str], *, capture: bool = True) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(command, check=False, text=True, capture_output=capture)
    except FileNotFoundError as exc:
        raise PipelineError(f"required executable not found: {command[0]}") from exc
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "unknown error").strip()
        raise PipelineError(f"command failed ({' '.join(command)}): {detail}")
    return result


def _require_file(path: Path, label: str) -> Path:
    resolved = path.expanduser().resolve()
    if not resolved.is_file():
        raise PipelineError(f"{label} does not exist or is not a file: {resolved}")
    return resolved


def _probe_json(path: Path) -> dict[str, Any]:
    result = _run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration:stream=codec_type,width,height,r_frame_rate",
            "-of",
            "json",
            str(path),
        ]
    )
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise PipelineError(f"ffprobe returned invalid JSON for {path}") from exc


def probe_media(path: Path) -> MediaInfo:
    """Return the first video stream and audio presence using ffprobe."""
    path = _require_file(path, "media")
    payload = _probe_json(path)
    streams = payload.get("streams") or []
    video = next((stream for stream in streams if stream.get("codec_type") == "video"), None)
    if not isinstance(video, dict):
        raise PipelineError(f"media has no video stream: {path}")
    width, height = video.get("width"), video.get("height")
    if not isinstance(width, int) or not isinstance(height, int) or width < 1 or height < 1:
        raise PipelineError(f"media has invalid video dimensions: {path}")
    duration_raw = (payload.get("format") or {}).get("duration")
    try:
        duration = float(duration_raw) if duration_raw is not None else None
    except (TypeError, ValueError):
        duration = None
    return MediaInfo(
        path=str(path),
        width=width,
        height=height,
        duration_seconds=duration,
        fps=video.get("r_frame_rate") if isinstance(video.get("r_frame_rate"), str) else None,
        has_audio=any(stream.get("codec_type") == "audio" for stream in streams),
    )


def _ratio(info: MediaInfo) -> float:
    return info.width / info.height


def _validate_reference_pair(combined: Path, clean_plate: Path) -> tuple[MediaInfo, MediaInfo]:
    combined_info = probe_media(combined)
    plate_info = probe_media(clean_plate)
    if (combined_info.width, combined_info.height) != (plate_info.width, plate_info.height):
        raise PipelineError(
            "combined-reference and clean-plate must have identical dimensions; "
            f"got {combined_info.width}x{combined_info.height} and {plate_info.width}x{plate_info.height}"
        )
    return combined_info, plate_info


def _read_text_argument(value: str | None, file_path: Path | None, label: str) -> str:
    if value and file_path:
        raise PipelineError(f"provide only one of --{label} or --{label}-file")
    if file_path:
        value = _require_file(file_path, f"{label} file").read_text(encoding="utf-8")
    if not isinstance(value, str) or not value.strip():
        raise PipelineError(f"{label} must be non-empty")
    return value.strip()


def _presenter_character_path(presenter_id: str) -> Path:
    # 与 presenter_gen.py 的 data_dir()/library_root() 约定保持一致
    # （脚本在 uv --isolated 下运行，不能 import ethan；为可独立拷贝也不 import 兄弟脚本）。
    data_dir = os.environ.get("ETHAN_DATA_DIR")
    base = Path(data_dir).expanduser() if data_dir else Path.home() / ".ethan"
    return base / "assets" / "library" / "presenters" / presenter_id / "character.json"


def _load_presenter_identity(presenter_id: str | None) -> dict[str, Any]:
    """H3 prompt 的 presenter 身份：默认内置小雨；传 id 时以角色包 character.json 为准。"""
    if presenter_id is None:
        return {"id": None, **DEFAULT_PRESENTER}
    path = _presenter_character_path(presenter_id)
    if not path.is_file():
        raise PipelineError(f"presenter 角色包不存在: {path}（先用 presenter_gen.py 建角色）")
    try:
        character = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise PipelineError(f"presenter character.json 无效: {path}") from exc
    description = character.get("description")
    if not isinstance(description, str) or not description.strip():
        raise PipelineError(f"presenter character.json 缺少 description: {path}")
    return {"id": presenter_id, "name": character.get("name") or presenter_id, "description": description.strip()}


def build_h3_prompt(
    *,
    dialogue: str,
    duration_seconds: float,
    motion_plan: str,
    has_character_reference: bool,
    screen_notes: str | None = None,
    presenter: dict[str, Any] | None = None,
) -> str:
    """Create a stable reference-to-video prompt with explicit ownership rules."""
    if not 4 <= duration_seconds <= 15:
        raise PipelineError("duration must be between 4 and 15 seconds for MiniMax H3")
    if not dialogue.strip():
        raise PipelineError("dialogue must be non-empty")
    if not motion_plan.strip():
        raise PipelineError("motion plan must be non-empty")

    identity = presenter or {"id": None, **DEFAULT_PRESENTER}
    name = str(identity["name"])
    description = str(identity["description"])
    identity_reference = (
        f"Use <Picture 2> only as {name}'s character identity reference: {description}."
        if has_character_reference
        else f"Use <Picture 1> as {name}'s identity reference as well as the composition reference."
    )
    notes = ""
    if screen_notes:
        notes = (
            "\nThe following dashboard facts are semantic anchors only; preserve their positions and meaning, "
            "but do not redraw or animate the typography:\n"
            f"{screen_notes.strip()}\n"
        )
    return f"""Create one continuous {duration_seconds:g}-second 2D anime finance-presenter video with native synchronized Mandarin Chinese speech.

Reference ownership:
Use <Picture 1> as the exact scene composition reference: {name} is on the right; the finance dashboard, menu, charts and deep navy technology stage are on the left.
{identity_reference}

Camera and layout:
The camera is completely locked. No zoom, pan, crop, reframing, cut or transition. Keep {name} on the right and retain the dashboard layout on the left. Treat the dashboard as a static presentation screen: do not add, translate, rewrite, duplicate, blur or animate its text, numbers, chart or logo. Do not put text over {name}.
{notes}
Character integrity:
{name} has exactly two eyes, two arms, two hands and five fingers on each hand. Preserve the same face, body proportions, hairstyle, outfit and accessories throughout. No duplicated limbs, warped hands, face morphing, costume changes or character duplication.

Performance timeline:
{motion_plan.strip()}

Dialogue:
{name} speaks clearly in a natural, expressive Mandarin voice. The mouth visibly synchronizes to this exact sentence and there is no other dialogue:
“{dialogue.strip()}”

Visual quality:
Polished 2D anime illustration, stable anatomy, sharp facial details, subtle natural blinking, restrained secondary motion in hair and outfit details, continuous arm motion, clean edges, no flicker, no generated captions and no low-resolution blur."""


def _copy_asset(source: Path, destination: Path) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    pending = destination.with_name(f".{destination.name}.{uuid.uuid4().hex}.tmp")
    shutil.copy2(source, pending)
    pending.replace(destination)
    return destination


def prepare_scene(
    *,
    scene_dir: Path,
    combined_reference: Path,
    clean_plate: Path,
    dialogue: str,
    duration_seconds: float,
    motion_plan: str | None,
    character_reference: Path | None = None,
    screen_notes: str | None = None,
    presenter_id: str | None = None,
) -> dict[str, Any]:
    """Create a self-contained H3 scene package for handoff to ComfyUI."""
    combined_reference = _require_file(combined_reference, "combined reference")
    clean_plate = _require_file(clean_plate, "clean plate")
    combined_info, plate_info = _validate_reference_pair(combined_reference, clean_plate)
    character_info = probe_media(character_reference) if character_reference else None
    if character_info and abs(_ratio(character_info) - _ratio(combined_info)) > 0.55:
        raise PipelineError("character reference aspect ratio is implausibly different from the scene reference")

    identity = _load_presenter_identity(presenter_id)
    motion = motion_plan or DEFAULT_MOTION_PLAN.format(name=identity["name"])

    scene_dir = scene_dir.expanduser().resolve()
    refs_dir = scene_dir / "references"
    combined_dest = _copy_asset(combined_reference, refs_dir / "combined-reference.png")
    plate_dest = _copy_asset(clean_plate, refs_dir / "clean-plate.png")
    character_dest: Path | None = None
    if character_reference:
        character_dest = _copy_asset(
            _require_file(character_reference, "character reference"), refs_dir / "character-reference.png"
        )
    prompt = build_h3_prompt(
        dialogue=dialogue,
        duration_seconds=duration_seconds,
        motion_plan=motion,
        has_character_reference=character_dest is not None,
        screen_notes=screen_notes,
        presenter=identity,
    )
    prompt_path = scene_dir / "h3-prompt.txt"
    prompt_path.parent.mkdir(parents=True, exist_ok=True)
    prompt_path.write_text(prompt + "\n", encoding="utf-8")
    payload = {
        "version": 1,
        "durationSeconds": duration_seconds,
        "dialogue": dialogue,
        "motionPlan": motion,
        "presenter": {"id": identity["id"], "name": identity["name"]},
        "references": {
            "picture1": str(combined_dest),
            "cleanPlate": str(plate_dest),
            "picture2": str(character_dest) if character_dest else None,
        },
        "referenceMedia": {
            "combined": asdict(combined_info),
            "cleanPlate": asdict(plate_info),
            "character": asdict(character_info) if character_info else None,
        },
        "compositing": {
            "preferred": "foreground-mask",
            "fallback": "safe-boundary",
            "layerOrder": ["clean-plate", "h3-presenter-foreground", "deterministic-captions", "audio"],
            "foregroundMaskContract": "A grayscale mask video matching H3 video frame count; white=presenter foreground, black=clean plate.",
        },
    }
    metadata_path = scene_dir / "scene.json"
    metadata_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"sceneDir": str(scene_dir), "prompt": str(prompt_path), "metadata": str(metadata_path), **payload}


def _fit_crop_body(width: int, height: int) -> str:
    """fit-and-crop 滤镜体（不含输入标签）：等比放大至覆盖目标尺寸后居中裁切。"""
    return f"scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height}"


def _safe_boundary_filter(*, width: int, height: int, panel_edge_px: int, feather_px: int) -> str:
    if not 0 < panel_edge_px < width:
        raise PipelineError(f"panel edge must be within (0, {width}), got {panel_edge_px}")
    if not 0 <= feather_px <= min(160, width - panel_edge_px):
        raise PipelineError("feather must be between 0 and 160 pixels and stay inside the frame")
    if feather_px == 0:
        expression = f"if(lt(X,{panel_edge_px}),255,0)"
    else:
        edge_end = panel_edge_px + feather_px
        slope = 255 / feather_px
        expression = f"if(lt(X,{panel_edge_px}),255,if(lt(X,{edge_end}),({edge_end}-X)*{slope:.8f},0))"
    return (
        f"[0:v]{_fit_crop_body(width, height)}[base];"
        f"[1:v]scale={width}:{height}[plate];"
        # 遮罩只与 X 坐标有关，是静态图：geq 求值一帧（d=0.04 → nullsrc 默认 25fps 下恰一帧）
        # 再 loop 无限重复，避免逐帧逐像素重算同一个表达式。
        f"nullsrc=s={width}x{height}:d=0.04,format=gray,geq=lum='{expression}',loop=loop=-1:size=1[panel-mask];"
        "[plate][panel-mask]alphamerge[panel];"
        "[base][panel]overlay=0:0:format=auto[outv]"
    )


def _foreground_mask_filter(*, width: int, height: int) -> str:
    return (
        f"[0:v]{_fit_crop_body(width, height)},format=rgba[presenter];"
        f"[1:v]{_fit_crop_body(width, height)},format=gray[mask];"
        f"[2:v]scale={width}:{height},format=rgba[plate];"
        "[presenter][mask]alphamerge[presenter-alpha];"
        "[plate][presenter-alpha]overlay=0:0:format=auto[outv]"
    )


def _scene_reference_dimensions(scene_dir: Path) -> tuple[int, int] | None:
    """从 scene.json 的 referenceMedia.combined 读场景原生尺寸（prepare 时写入）。"""
    try:
        metadata = json.loads((scene_dir / "scene.json").read_text(encoding="utf-8"))
        combined = metadata["referenceMedia"]["combined"]
        width, height = int(combined["width"]), int(combined["height"])
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError):
        return None
    return (width, height) if width > 0 and height > 0 else None


def compose_scene(
    *,
    scene_dir: Path,
    h3_video: Path,
    output: Path,
    foreground_mask: Path | None,
    panel_edge_px: int | None,
    feather_px: int,
    width: int | None = None,
    height: int | None = None,
) -> dict[str, Any]:
    """Composite a H3 performance over the deterministic clean plate.

    foreground_mask is the production path.  Its white regions are overlaid on
    the clean plate, so hands can cross and point at dashboard cards.  The
    boundary path is intentionally explicit because it cannot handle a hand
    travelling deep into the UI.

    width/height 不传时取 scene.json 里 combined-reference 的原生尺寸
    （合成不该默认把竖屏场景压成 1280x720）；传则必须成对传入。
    """
    scene_dir = scene_dir.expanduser().resolve()
    h3_video = _require_file(h3_video, "H3 video")
    clean_plate = _require_file(scene_dir / "references" / "clean-plate.png", "scene clean plate")
    if (foreground_mask is None) == (panel_edge_px is None):
        raise PipelineError("provide exactly one of foreground_mask or panel_edge_px")
    if (width is None) != (height is None):
        raise PipelineError("output width and height must be provided together")
    if width is None or height is None:
        dimensions = _scene_reference_dimensions(scene_dir)
        if dimensions is None:
            raise PipelineError(
                "scene.json has no referenceMedia.combined dimensions; pass --width and --height explicitly"
            )
        width, height = dimensions
    if width < 320 or height < 320 or width % 2 or height % 2:
        raise PipelineError("output width and height must be even integers >= 320")
    h3_info = probe_media(h3_video)
    plate_info = probe_media(clean_plate)
    if not h3_info.has_audio:
        raise PipelineError("H3 video has no audio stream; refusing to silently create a mute presenter video")
    if abs(_ratio(h3_info) - _ratio(plate_info)) > 0.08:
        raise PipelineError("H3 video and clean plate aspect ratios differ by more than 8%")

    output = output.expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    command = ["ffmpeg", "-y", "-i", str(h3_video)]
    mode: str
    if foreground_mask is not None:
        foreground_mask = _require_file(foreground_mask, "foreground mask")
        mask_info = probe_media(foreground_mask)
        if abs(_ratio(mask_info) - _ratio(h3_info)) > 0.03:
            raise PipelineError("foreground mask aspect ratio must match H3 video within 3%")
        command.extend(["-i", str(foreground_mask), "-loop", "1", "-i", str(clean_plate)])
        filter_graph = _foreground_mask_filter(width=width, height=height)
        mode = "foreground-mask"
    else:
        command.extend(["-loop", "1", "-i", str(clean_plate)])
        filter_graph = _safe_boundary_filter(
            width=width, height=height, panel_edge_px=int(panel_edge_px), feather_px=feather_px
        )
        mode = "safe-boundary"
    command.extend(
        [
            "-filter_complex",
            filter_graph,
            "-map",
            "[outv]",
            "-map",
            "0:a?",
            "-c:v",
            "libx264",
            # 合成内容是大面积静态 UI + 前景人物，medium 与 slow 视觉无差，编码快 ~2 倍。
            "-preset",
            "medium",
            "-crf",
            "16",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "copy",
            "-shortest",
            "-movflags",
            "+faststart",
            str(output),
        ]
    )
    _run(command, capture=True)
    result = probe_media(output)
    if (result.width, result.height) != (width, height) or not result.has_audio:
        raise PipelineError("composite verification failed: output dimensions or audio stream mismatch")
    report = {
        "status": "ok",
        "mode": mode,
        "video": asdict(result),
        "sourceVideo": asdict(h3_info),
        "cleanPlate": asdict(plate_info),
        "output": str(output),
    }
    report_path = output.with_suffix(".composition.json")
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def verify_scene(scene_dir: Path, h3_video: Path | None = None) -> dict[str, Any]:
    """Check the reference package and optionally a generated H3 result."""
    scene_dir = scene_dir.expanduser().resolve()
    metadata_path = _require_file(scene_dir / "scene.json", "scene metadata")
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise PipelineError(f"invalid scene metadata: {metadata_path}") from exc
    refs = metadata.get("references")
    if not isinstance(refs, dict):
        raise PipelineError("scene metadata has no references object")
    combined = _require_file(Path(str(refs.get("picture1"))), "combined reference")
    clean_plate = _require_file(Path(str(refs.get("cleanPlate"))), "clean plate")
    combined_info, plate_info = _validate_reference_pair(combined, clean_plate)
    result: dict[str, Any] = {
        "status": "ok",
        "combinedReference": asdict(combined_info),
        "cleanPlate": asdict(plate_info),
        "prompt": str(_require_file(scene_dir / "h3-prompt.txt", "H3 prompt")),
    }
    if h3_video:
        generated = probe_media(_require_file(h3_video, "H3 video"))
        if not generated.has_audio:
            raise PipelineError("H3 video has no native audio")
        result["h3Video"] = asdict(generated)
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Prepare and composite MiniMax H3 presenter scenes")
    subparsers = parser.add_subparsers(dest="command", required=True)

    prepare = subparsers.add_parser("prepare", help="write a self-contained H3 scene package")
    prepare.add_argument("--scene-dir", type=Path, required=True)
    prepare.add_argument("--combined-reference", type=Path, required=True)
    prepare.add_argument("--clean-plate", type=Path, required=True)
    prepare.add_argument("--character-reference", type=Path)
    prepare.add_argument("--presenter", help="资产库 presenter id；传入后 prompt 身份以角色包 character.json 为准")
    prepare.add_argument("--dialogue")
    prepare.add_argument("--dialogue-file", type=Path)
    prepare.add_argument("--motion-plan")
    prepare.add_argument("--motion-plan-file", type=Path)
    prepare.add_argument("--screen-notes")
    prepare.add_argument("--screen-notes-file", type=Path)
    prepare.add_argument("--duration", type=float, required=True)

    compose = subparsers.add_parser("compose", help="put a H3 presenter performance over a clean plate")
    compose.add_argument("--scene-dir", type=Path, required=True)
    compose.add_argument("--h3-video", type=Path, required=True)
    compose.add_argument("--output", type=Path, required=True)
    compose.add_argument("--foreground-mask", type=Path)
    compose.add_argument("--panel-edge-px", type=int)
    compose.add_argument("--feather-px", type=int, default=18)
    compose.add_argument("--width", type=int, help="默认取 scene.json 里 combined-reference 的原生宽度")
    compose.add_argument("--height", type=int, help="默认取 scene.json 里 combined-reference 的原生高度")

    verify = subparsers.add_parser("verify", help="validate a prepared scene package")
    verify.add_argument("--scene-dir", type=Path, required=True)
    verify.add_argument("--h3-video", type=Path)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        if args.command == "prepare":
            dialogue = _read_text_argument(args.dialogue, args.dialogue_file, "dialogue")
            # motion-plan 不传时由 prepare_scene 用 DEFAULT_MOTION_PLAN 按 presenter 名格式化。
            motion = _read_text_argument(args.motion_plan, args.motion_plan_file, "motion-plan") if (
                args.motion_plan or args.motion_plan_file
            ) else None
            notes = _read_text_argument(args.screen_notes, args.screen_notes_file, "screen-notes") if (
                args.screen_notes or args.screen_notes_file
            ) else None
            result = prepare_scene(
                scene_dir=args.scene_dir,
                combined_reference=args.combined_reference,
                clean_plate=args.clean_plate,
                character_reference=args.character_reference,
                dialogue=dialogue,
                duration_seconds=args.duration,
                motion_plan=motion,
                screen_notes=notes,
                presenter_id=args.presenter,
            )
        elif args.command == "compose":
            result = compose_scene(
                scene_dir=args.scene_dir,
                h3_video=args.h3_video,
                output=args.output,
                foreground_mask=args.foreground_mask,
                panel_edge_px=args.panel_edge_px,
                feather_px=args.feather_px,
                width=args.width,
                height=args.height,
            )
        else:
            result = verify_scene(args.scene_dir, args.h3_video)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except PipelineError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
