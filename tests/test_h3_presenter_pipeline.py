import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = (
    Path(__file__).parents[1]
    / "ethan"
    / "defaults"
    / "skills"
    / "article-to-video"
    / "scripts"
    / "h3_presenter_pipeline.py"
)
SPEC = importlib.util.spec_from_file_location("h3_presenter_pipeline", SCRIPT)
assert SPEC and SPEC.loader
h3 = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = h3
SPEC.loader.exec_module(h3)


def info(path: Path, *, width: int = 1024, height: int = 576, audio: bool = False) -> object:
    return h3.MediaInfo(str(path), width, height, duration_seconds=6.5, fps="24/1", has_audio=audio)


def test_prompt_assigns_reference_ownership_and_exact_dialogue():
    prompt = h3.build_h3_prompt(
        dialogue="快手当前三十三点六四港元。",
        duration_seconds=6.5,
        motion_plan="0–6.5s: continuous natural pointing motion.",
        has_character_reference=True,
        screen_notes="最新收盘价 33.64 HKD",
    )

    assert "<Picture 1>" in prompt
    assert "<Picture 2>" in prompt
    assert "快手当前三十三点六四港元。" in prompt
    assert "do not add, translate, rewrite, duplicate, blur or animate" in prompt
    assert "最新收盘价 33.64 HKD" in prompt


def test_prompt_without_character_reference_does_not_claim_picture_two():
    prompt = h3.build_h3_prompt(
        dialogue="欢迎光临。",
        duration_seconds=5,
        motion_plan="0–5s: smile.",
        has_character_reference=False,
    )

    assert "Use <Picture 2>" not in prompt
    assert "Use <Picture 1> as Xiaoyu's identity" in prompt


@pytest.mark.parametrize("duration", [3.9, 15.1])
def test_prompt_rejects_unsupported_h3_duration(duration):
    with pytest.raises(h3.PipelineError, match="between 4 and 15"):
        h3.build_h3_prompt(
            dialogue="你好。",
            duration_seconds=duration,
            motion_plan="0–1s: smile.",
            has_character_reference=False,
        )


def test_prepare_scene_writes_reusable_reference_bundle(tmp_path, monkeypatch):
    combined = tmp_path / "combined.png"
    plate = tmp_path / "plate.png"
    character = tmp_path / "character.png"
    for path in (combined, plate, character):
        path.write_bytes(b"not-real-media")

    def fake_probe(path: Path):
        if path == character.resolve():
            return info(path, width=1000, height=800)
        return info(path)

    monkeypatch.setattr(h3, "probe_media", fake_probe)
    scene_dir = tmp_path / "shot-01"
    result = h3.prepare_scene(
        scene_dir=scene_dir,
        combined_reference=combined,
        clean_plate=plate,
        character_reference=character,
        dialogue="欢迎光临小雨的爱心小屋。",
        duration_seconds=6,
        motion_plan="0–6s: a gentle welcome.",
        screen_notes="快手全面投资分析",
    )

    assert Path(result["prompt"]).is_file()
    assert (scene_dir / "references" / "combined-reference.png").read_bytes() == b"not-real-media"
    payload = json.loads((scene_dir / "scene.json").read_text(encoding="utf-8"))
    assert payload["compositing"]["preferred"] == "foreground-mask"
    assert payload["references"]["picture2"].endswith("character-reference.png")


def test_filters_keep_the_foreground_mask_as_top_layer():
    mask_filter = h3._foreground_mask_filter(width=1280, height=720)
    boundary_filter = h3._safe_boundary_filter(width=1280, height=720, panel_edge_px=648, feather_px=14)

    assert "[presenter][mask]alphamerge[presenter-alpha]" in mask_filter
    assert "[plate][presenter-alpha]overlay" in mask_filter
    assert "panel-mask" in boundary_filter
    assert "if(lt(X,648),255" in boundary_filter


def test_compose_scene_prefers_foreground_mask_and_retains_audio(tmp_path, monkeypatch):
    scene_dir = tmp_path / "scene"
    refs = scene_dir / "references"
    refs.mkdir(parents=True)
    plate = refs / "clean-plate.png"
    h3_video = tmp_path / "raw-h3.mp4"
    matte = tmp_path / "xiaoyu-mask.mp4"
    for path in (plate, h3_video, matte):
        path.write_bytes(b"media")
    output = tmp_path / "final.mp4"
    commands: list[list[str]] = []

    def fake_probe(path: Path):
        if path == h3_video.resolve() or path == output.resolve():
            return info(path, width=1056 if path == h3_video.resolve() else 1280, height=608 if path == h3_video.resolve() else 720, audio=True)
        return info(path, width=1056, height=608)

    monkeypatch.setattr(h3, "probe_media", fake_probe)
    monkeypatch.setattr(h3, "_run", lambda command, capture=True: commands.append(command))
    result = h3.compose_scene(
        scene_dir=scene_dir,
        h3_video=h3_video,
        output=output,
        foreground_mask=matte,
        panel_edge_px=None,
        feather_px=18,
        width=1280,
        height=720,
    )

    assert result["mode"] == "foreground-mask"
    command = commands[0]
    assert "0:a?" in command
    assert "[presenter][mask]alphamerge[presenter-alpha]" in command[command.index("-filter_complex") + 1]
    assert output.with_suffix(".composition.json").is_file()


def test_compose_requires_exactly_one_masking_strategy(tmp_path, monkeypatch):
    scene_dir = tmp_path / "scene"
    refs = scene_dir / "references"
    refs.mkdir(parents=True)
    plate = refs / "clean-plate.png"
    h3_video = tmp_path / "raw-h3.mp4"
    for path in (plate, h3_video):
        path.write_bytes(b"media")
    monkeypatch.setattr(h3, "probe_media", lambda path: info(path, width=1056, height=608, audio=path == h3_video.resolve()))

    with pytest.raises(h3.PipelineError, match="exactly one"):
        h3.compose_scene(
            scene_dir=scene_dir,
            h3_video=h3_video,
            output=tmp_path / "final.mp4",
            foreground_mask=None,
            panel_edge_px=None,
            feather_px=18,
            width=1280,
            height=720,
        )


def test_parse_frame_rate_handles_common_and_broken_inputs():
    assert h3._parse_frame_rate("24/1") == 24.0
    assert h3._parse_frame_rate("30000/1001") == pytest.approx(30000 / 1001)
    assert h3._parse_frame_rate(None) == 25.0
    assert h3._parse_frame_rate("0/0") == 25.0
    assert h3._parse_frame_rate("24/0") == 25.0
    assert h3._parse_frame_rate("not-a-rate") == 25.0
    assert h3._parse_frame_rate("12/34/56") == 25.0


def test_prepare_rejects_invalid_presenter_id(tmp_path, monkeypatch):
    combined = tmp_path / "combined.png"
    plate = tmp_path / "plate.png"
    combined.write_bytes(b"not-real-media")
    plate.write_bytes(b"not-real-media")
    monkeypatch.setattr(h3, "probe_media", lambda path: info(path))

    with pytest.raises(h3.PipelineError, match="invalid presenter id"):
        h3.prepare_scene(
            scene_dir=tmp_path / "scene",
            combined_reference=combined,
            clean_plate=plate,
            dialogue="欢迎光临。",
            duration_seconds=6,
            motion_plan=None,
            presenter_id="../evil",
        )
    assert not (tmp_path / "scene" / "references").exists()


def test_prepare_validates_inputs_before_copying_assets(tmp_path, monkeypatch):
    combined = tmp_path / "combined.png"
    plate = tmp_path / "plate.png"
    combined.write_bytes(b"not-real-media")
    plate.write_bytes(b"not-real-media")
    monkeypatch.setattr(h3, "probe_media", lambda path: info(path))

    with pytest.raises(h3.PipelineError, match="between 4 and 15"):
        h3.prepare_scene(
            scene_dir=tmp_path / "scene",
            combined_reference=combined,
            clean_plate=plate,
            dialogue="欢迎光临。",
            duration_seconds=3.9,
            motion_plan=None,
        )
    # 校验前置：duration 非法时连 scene 目录都不该建出来。
    assert not (tmp_path / "scene").exists()


def test_verify_scene_reports_missing_picture2(tmp_path, monkeypatch):
    scene_dir = tmp_path / "scene"
    refs_dir = scene_dir / "references"
    refs_dir.mkdir(parents=True)
    (refs_dir / "combined-reference.png").write_bytes(b"not-real-media")
    (refs_dir / "clean-plate.png").write_bytes(b"not-real-media")
    (scene_dir / "h3-prompt.txt").write_text("prompt", encoding="utf-8")
    metadata = {
        "references": {
            "picture1": str(refs_dir / "combined-reference.png"),
            "cleanPlate": str(refs_dir / "clean-plate.png"),
            # 声称有 picture2，但文件并不存在 → verify 必须失败。
            "picture2": str(refs_dir / "character-reference.png"),
        }
    }
    (scene_dir / "scene.json").write_text(json.dumps(metadata), encoding="utf-8")
    monkeypatch.setattr(h3, "probe_media", lambda path: info(path))

    with pytest.raises(h3.PipelineError, match="character reference"):
        h3.verify_scene(scene_dir)


def test_verify_scene_reports_missing_picture1_field(tmp_path):
    scene_dir = tmp_path / "scene"
    scene_dir.mkdir(parents=True)
    (scene_dir / "scene.json").write_text(
        json.dumps({"references": {"picture1": None, "cleanPlate": "/tmp/plate.png"}}),
        encoding="utf-8",
    )

    # 报错必须明确说缺 picture1 字段，而不是拼出 "/None" 这样的路径。
    with pytest.raises(h3.PipelineError, match="picture1 is missing"):
        h3.verify_scene(scene_dir)


FFMPEG = shutil.which("ffmpeg")
FFPROBE = shutil.which("ffprobe")
requires_ffmpeg = pytest.mark.skipif(
    FFMPEG is None or FFPROBE is None, reason="ffmpeg not available"
)


def _run_ffmpeg(command: list[str]) -> None:
    result = subprocess.run(command, check=False, capture_output=True, text=True)
    assert result.returncode == 0, f"ffmpeg failed: {result.stderr}"


def _make_h3_source(path: Path, duration: float = 2.0) -> None:
    """造一个带音轨的 24fps 测试源（compose 要求 H3 视频必须有原生音轨）。"""
    _run_ffmpeg(
        [
            FFMPEG,
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"testsrc=duration={duration}:size=640x480:rate=24",
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency=440:duration={duration}",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-shortest",
            str(path),
        ]
    )


def _make_gray_mask(path: Path, duration: float = 2.0) -> None:
    _run_ffmpeg(
        [
            FFMPEG,
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"color=c=gray:size=640x480:rate=24:duration={duration}",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(path),
        ]
    )


def _make_clean_plate(path: Path) -> None:
    _run_ffmpeg(
        [
            FFMPEG,
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=navy:size=640x480",
            "-frames:v",
            "1",
            str(path),
        ]
    )


def _make_scene(tmp_path: Path) -> Path:
    scene_dir = tmp_path / "scene"
    refs_dir = scene_dir / "references"
    refs_dir.mkdir(parents=True)
    _make_clean_plate(refs_dir / "clean-plate.png")
    return scene_dir


@requires_ffmpeg
def test_compose_real_ffmpeg_matches_source_frame_rate(tmp_path):
    h3_video = tmp_path / "raw-h3.mp4"
    _make_h3_source(h3_video)
    mask = tmp_path / "xiaoyu-mask.mp4"
    _make_gray_mask(mask)
    scene_dir = _make_scene(tmp_path)

    # foreground-mask（生产模式）
    output_fg = tmp_path / "final-fg.mp4"
    result_fg = h3.compose_scene(
        scene_dir=scene_dir,
        h3_video=h3_video,
        output=output_fg,
        foreground_mask=mask,
        panel_edge_px=None,
        feather_px=18,
        width=640,
        height=480,
    )
    assert result_fg["status"] == "ok"
    assert result_fg["mode"] == "foreground-mask"
    assert output_fg.is_file()
    output_info = h3.probe_media(output_fg)
    # 输出帧率必须等于 H3 源帧率，不能被 25fps 的 clean plate 静图抬高。
    assert output_info.fps == "24/1"
    assert h3._parse_frame_rate(output_info.fps) == pytest.approx(24.0)
    assert (tmp_path / "final-fg.composition.json").is_file()

    # safe-boundary（快速预览模式）
    output_boundary = tmp_path / "final-boundary.mp4"
    result_boundary = h3.compose_scene(
        scene_dir=scene_dir,
        h3_video=h3_video,
        output=output_boundary,
        foreground_mask=None,
        panel_edge_px=324,
        feather_px=14,
        width=640,
        height=480,
    )
    assert result_boundary["status"] == "ok"
    assert result_boundary["mode"] == "safe-boundary"
    assert h3.probe_media(output_boundary).fps == "24/1"


@requires_ffmpeg
def test_compose_rejects_mask_duration_mismatch(tmp_path):
    h3_video = tmp_path / "raw-h3.mp4"
    _make_h3_source(h3_video)
    short_mask = tmp_path / "short-mask.mp4"
    _make_gray_mask(short_mask, duration=1.0)
    scene_dir = _make_scene(tmp_path)

    # 1 秒 mask 配 2 秒源 → 时长差超 0.1s，必须拒绝合成。
    with pytest.raises(h3.PipelineError, match="duration must match the H3 video within 0.1s"):
        h3.compose_scene(
            scene_dir=scene_dir,
            h3_video=h3_video,
            output=tmp_path / "final.mp4",
            foreground_mask=short_mask,
            panel_edge_px=None,
            feather_px=18,
            width=640,
            height=480,
        )
