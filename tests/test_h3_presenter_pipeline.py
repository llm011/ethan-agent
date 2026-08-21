import importlib.util
import json
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
