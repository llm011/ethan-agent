import importlib.util
import json
import sys
import zipfile
from pathlib import Path

import pytest

from ethan.skills.loader import load_skill_from_dir

SCRIPT = (
    Path(__file__).parents[1]
    / "ethan"
    / "defaults"
    / "skills"
    / "article-to-video"
    / "scripts"
    / "video_pipeline.py"
)
SPEC = importlib.util.spec_from_file_location("article_to_video_pipeline", SCRIPT)
assert SPEC and SPEC.loader
pipeline = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = pipeline
SPEC.loader.exec_module(pipeline)


def sample_manifest():
    return {
        "title": "测试视频",
        "scenes": [
            {
                "id": "opening",
                "narration": "这是第一段旁白。",
                "headline": "第一幕",
                "visual": {"type": "kinetic-text", "keywords": ["主题", "变化"]},
            },
            {
                "id": "ending",
                "narration": "这是最后一段旁白。",
                "headline": "第二幕",
                "body": "补充说明",
                "visual": {"type": "summary", "items": ["第一点", "第二点"]},
            },
        ],
    }


def test_normalize_manifest_adds_deterministic_defaults():
    result = pipeline.normalize_manifest(sample_manifest())

    assert result["width"] == 1080
    assert result["height"] == 1920
    assert result["fps"] == 30
    assert result["voice"]["name"] == "zh-CN-XiaoxiaoNeural"
    assert result["theme"]["background"] == "#081120"
    assert result["scenes"][0]["body"] == ""
    assert result["targetDurationSec"] is None


@pytest.mark.parametrize(
    "mutate, message",
    [
        (lambda value: value["scenes"][1].update(id="opening"), "duplicate scene id"),
        (lambda value: value["scenes"][0].update(narration=""), "narration"),
        (lambda value: value["scenes"][0]["visual"].update(type="photo"), "visual.type"),
        (lambda value: value.update(fps=29), "fps"),
        (lambda value: value.update(durationToleranceSec=2), "requires targetDurationSec"),
    ],
)
def test_manifest_validation_rejects_invalid_values(mutate, message):
    value = sample_manifest()
    mutate(value)

    with pytest.raises(pipeline.ManifestError, match=message):
        pipeline.normalize_manifest(value)


def test_srt_round_trip_and_global_timeline(tmp_path):
    first = tmp_path / "first.srt"
    second = tmp_path / "second.srt"
    first.write_text("1\n00:00:00,100 --> 00:00:01,000\n第一句\n", encoding="utf-8")
    second.write_text("1\n00:00:00,050 --> 00:00:00,800\n第二句\n", encoding="utf-8")

    manifest = pipeline.normalize_manifest(sample_manifest())
    timeline = pipeline.build_timeline(manifest, [{"srt": first}, {"srt": second}])

    combined = timeline["_combinedSubtitles"]
    assert timeline["scenes"][0]["startMs"] == 0
    assert timeline["scenes"][0]["durationMs"] == 1350
    assert timeline["scenes"][1]["startMs"] == 1350
    assert combined[1].start_ms == 1400
    assert pipeline.parse_srt(pipeline.serialize_srt(combined)) == combined


def test_long_edge_tts_caption_is_paginated():
    source = [pipeline.Subtitle(text="AI Agent 不只回答问题，它还能理解目标，调用工具，并完成任务。", start_ms=100, end_ms=6400)]

    pages = pipeline.paginate_subtitles(source, maximum=22)

    assert len(pages) >= 2
    assert pages[0].start_ms == 100
    assert pages[-1].end_ms == 6400
    assert "".join(page.text for page in pages) == source[0].text
    assert all(len(page.text) <= 22 for page in pages)


def test_split_caption_text_preserves_english_spaces():
    # 英文/混排在空格处切分不能丢空格，tail-merge 也不能把单词粘成 helloworld。
    text = "The quick brown fox jumps over the lazy dog repeatedly"
    chunks = pipeline._split_caption_text(text, maximum=20)

    rejoined = " ".join(part for part in " ".join(chunks).split(" ") if part)
    # 切再拼回应能还原原句的词序列（不粘连、不丢词）。
    assert rejoined == text
    assert "helloworld" not in "".join(chunks).lower().replace(" ", "")


def test_paginate_subtitles_cursor_is_monotonic():
    # 短时长 + 多分片：round() 可能归零，cursor 必须仍单调推进，不产生重叠/倒退。
    source = [pipeline.Subtitle(text="aaaaaaaaaa bbbbbbbbbb cccccccccc dddddddddd", start_ms=0, end_ms=5)]
    pages = pipeline.paginate_subtitles(source, maximum=10)

    assert len(pages) >= 2
    for prev, cur in zip(pages, pages[1:]):
        assert cur.start_ms >= prev.end_ms, f"cursor went backwards: {prev} -> {cur}"
        assert cur.end_ms > cur.start_ms


def test_normalize_manifest_handles_null_fields():
    raw = sample_manifest()
    raw["summary"] = None
    raw["language"] = None
    raw["sourceUrl"] = None

    result = pipeline.normalize_manifest(raw)

    assert result["summary"] == ""
    assert result["language"] == "zh-CN"
    assert result["sourceUrl"] == ""


def test_enforce_target_duration_uses_narration_not_padding():
    value = sample_manifest()
    value["targetDurationSec"] = 30
    manifest = pipeline.normalize_manifest(value)

    # 旁白实际 30s（captions 末尾），但 totalDurationMs 含 2 场景 × 350ms padding = 30.7s。
    # 旧逻辑会误判超时（30.7 > 33? 否，但接近；构造更明确的边界：旁白 32s，padding 后 32.7s）。
    timeline = {
        "totalDurationMs": 32_700,  # 含 padding
        "captions": [{"text": "x", "startMs": 0, "endMs": 32_000}],  # 实际旁白 32s
    }
    # 32s 在 30±3s 内 → 通过；若用 totalDurationMs(32.7s) 则会误判失败。
    pipeline.enforce_target_duration(manifest, timeline)


def test_target_duration_defaults_tolerance_and_enforces_actual_timing():
    value = sample_manifest()
    value["targetDurationSec"] = 30
    manifest = pipeline.normalize_manifest(value)

    assert manifest["durationToleranceSec"] == 3
    pipeline.enforce_target_duration(manifest, {"totalDurationMs": 32_900})
    with pytest.raises(RuntimeError, match="actual narration duration"):
        pipeline.enforce_target_duration(manifest, {"totalDurationMs": 34_000})


def test_corrupt_tts_cache_is_rebuilt_atomically(tmp_path, monkeypatch):
    raw = sample_manifest()
    raw["scenes"] = raw["scenes"][:1]
    manifest = pipeline.normalize_manifest(raw)
    output_dir = tmp_path / "output"
    cache_dir = output_dir / "work" / "tts-cache"
    cache_dir.mkdir(parents=True)
    key = pipeline._tts_cache_key(manifest["scenes"][0], manifest["voice"])
    (cache_dir / f"{key}.mp3").write_bytes(b"broken")
    (cache_dir / f"{key}.srt").write_text("not an srt", encoding="utf-8")
    calls = []

    async def fake_synthesize(text, voice, media_path, srt_path):
        calls.append((text, voice["name"]))
        media_path.write_bytes(b"valid-audio" * 64)
        srt_path.write_text("1\n00:00:00,000 --> 00:00:01,000\n修复后的字幕\n", encoding="utf-8")

    monkeypatch.setattr(pipeline, "_synthesize_once", fake_synthesize)

    artifacts = pipeline.synthesize_scenes(manifest, output_dir, retries=1)

    assert len(calls) == 1
    assert Path(artifacts[0]["audio"]).stat().st_size >= 256
    assert pipeline.parse_srt(Path(artifacts[0]["srt"]).read_text(encoding="utf-8"))
    assert not list(cache_dir.glob("*.tmp"))


def test_failed_rerun_archives_previous_published_outputs(tmp_path, monkeypatch):
    manifest_path = tmp_path / "input.json"
    manifest_path.write_text(json.dumps(sample_manifest(), ensure_ascii=False), encoding="utf-8")
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    previous = {
        "final.mp4": b"old-video",
        "cover.png": b"old-cover",
        "render-report.json": b"old-report",
        "deliverables.zip": b"old-archive",
        "source.md": b"old-source",  # 非 PUBLISHED_OUTPUTS，但也要被归档清走
    }
    for name, content in previous.items():
        (output_dir / name).write_bytes(content)

    def fail_synthesis(manifest, destination):
        raise RuntimeError("tts offline")

    monkeypatch.setattr(pipeline, "synthesize_scenes", fail_synthesis)

    with pytest.raises(RuntimeError, match="tts offline"):
        pipeline.run_pipeline(manifest_path, output_dir)

    assert all(not (output_dir / name).exists() for name in previous)
    archived_dirs = list((output_dir / "work" / "previous-runs").iterdir())
    assert len(archived_dirs) == 1
    for name, content in previous.items():
        assert (archived_dirs[0] / name).read_bytes() == content
    status = json.loads((output_dir / "run-status.json").read_text(encoding="utf-8"))
    assert status["status"] == "error"
    assert status["error"] == "tts offline"


def test_publish_recovers_archived_source_md(tmp_path):
    """skill 先写 source.md 再调 run 的时序下，run 开头的归档会把它清走；
    publish 打包时应从归档目录复制回来，保证 deliverables.zip 内容完整。"""
    output_dir = tmp_path / "output"
    run_id = "20260816-000000-deadbeef"
    render_dir = output_dir / "work" / "render-runs" / run_id
    render_dir.mkdir(parents=True)
    timeline = {
        "width": 1080, "height": 1920, "fps": 30,
        "scenes": [{"id": "opening"}], "totalDurationMs": 60000, "captions": [],
    }
    (output_dir / "timeline.json").write_text(json.dumps(timeline), encoding="utf-8")
    (render_dir / "final.mp4").write_bytes(b"\x00\x00\x00\x1cftypisom" + b"\x00" * 10000)
    (render_dir / "cover.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 1000)
    (render_dir / "render-report.json").write_text(
        json.dumps({"width": 1080, "height": 1920, "fps": 30, "sceneCount": 1}), encoding="utf-8",
    )
    archive_dir = output_dir / "work" / "previous-runs" / run_id
    archive_dir.mkdir(parents=True)
    (archive_dir / "source.md").write_text("# 原文\n", encoding="utf-8")

    pipeline.publish_outputs(output_dir, run_id)

    assert (output_dir / "source.md").read_text(encoding="utf-8") == "# 原文\n"
    with zipfile.ZipFile(output_dir / "deliverables.zip") as bundle:
        assert "source.md" in bundle.namelist()
    assert (archive_dir / "source.md").is_file()  # 归档原件保留，不移动


def test_load_manifest_from_json_file(tmp_path):
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps(sample_manifest(), ensure_ascii=False), encoding="utf-8")

    loaded = pipeline.load_manifest(manifest)

    assert loaded["title"] == "测试视频"


def test_skill_metadata_and_references_are_discoverable():
    skill_dir = SCRIPT.parents[1]

    skill = load_skill_from_dir(skill_dir)

    assert skill is not None
    assert skill.name == "article-to-video"
    assert "文章转视频" in skill.trigger
    assert {path.name for path in skill.references} == {
        "manifest-schema.md",
        "script-guide.md",
        "visual-presets.md",
    }
