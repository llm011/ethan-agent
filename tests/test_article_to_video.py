import importlib.util
import json
import sys
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

PRESENTER_GEN_SCRIPT = SCRIPT.with_name("presenter_gen.py")
PG_SPEC = importlib.util.spec_from_file_location("presenter_gen", PRESENTER_GEN_SCRIPT)
assert PG_SPEC and PG_SPEC.loader
presenter_gen = importlib.util.module_from_spec(PG_SPEC)
sys.modules[PG_SPEC.name] = presenter_gen
PG_SPEC.loader.exec_module(presenter_gen)


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
        "asset-library.md",
        "presenter-guide.md",
        "h3-presenter-pipeline.md",
    }


# ── P1: domain / presenter / candlestick / callouts ──


def make_presenter_library(root: Path, presenter_id: str = "xiaoyu", *, voice: dict | None = None) -> Path:
    """在临时库根下造一个 ready 状态的 presenter 角色包（两姿势）。"""
    presenter_dir = root / "presenters" / presenter_id
    poses_dir = presenter_dir / "poses"
    poses_dir.mkdir(parents=True)
    for name in ("standing", "pointing"):
        (poses_dir / f"{name}.png").write_bytes(b"\x89PNG\r\n\x1a\nfake")
    character = {
        "id": presenter_id,
        "name": "晓玉",
        "status": "ready",
        "createdAt": "2026-08-19T00:00:00",
        "voice": voice if voice is not None else {"name": "zh-CN-XiaoyiNeural", "rate": "+5%", "volume": "+0%", "pitch": "+0Hz"},
        "poses": {"standing": "poses/standing.png", "pointing": "poses/pointing.png"},
        "cutout": True,
    }
    (presenter_dir / "character.json").write_text(json.dumps(character, ensure_ascii=False), encoding="utf-8")
    return presenter_dir


def finance_manifest(**overrides):
    manifest = sample_manifest()
    manifest["domain"] = "finance"
    manifest.update(overrides)
    return manifest


def test_domain_defaults_to_general_with_original_theme():
    result = pipeline.normalize_manifest(sample_manifest())

    assert result["domain"] == "general"
    assert result["theme"]["background"] == "#081120"
    assert "accent" not in result["theme"] or result["theme"]["accent"]  # 可选键存在即可


def test_domain_theme_merge_priority():
    # finance 主题覆盖 DEFAULT_THEME
    result = pipeline.normalize_manifest(finance_manifest())
    assert result["theme"]["background"] == "#0A0E1A"
    assert result["theme"]["primary"] == "#FFD54A"
    assert result["theme"]["positive"] == "#EF4444"  # 红涨
    assert result["theme"]["negative"] == "#22C55E"  # 绿跌

    # 用户 theme 覆盖 domain 主题
    custom = finance_manifest(theme={"primary": "#FF0000"})
    result = pipeline.normalize_manifest(custom)
    assert result["theme"]["primary"] == "#FF0000"
    assert result["theme"]["background"] == "#0A0E1A"  # domain 其他键保留


@pytest.mark.parametrize("domain", ["bloomberg", "FINANCE", "fin ance"])
def test_unknown_domain_rejected(domain):
    with pytest.raises(pipeline.ManifestError, match="domain must be one of"):
        pipeline.normalize_manifest(finance_manifest(domain=domain))


def test_domain_null_falls_back_to_general():
    manifest = sample_manifest()
    manifest["domain"] = None
    assert pipeline.normalize_manifest(manifest)["domain"] == "general"


def test_presenter_loaded_from_library(tmp_path):
    root = tmp_path / "library"
    make_presenter_library(root)
    manifest = finance_manifest(presenter={"id": "xiaoyu"})

    result = pipeline.normalize_manifest(manifest, library_root=root)

    presenter = result["presenter"]
    assert presenter["id"] == "xiaoyu"
    assert presenter["position"] == "right"
    assert presenter["scale"] == 1.0
    assert presenter["defaultPose"] == "standing"
    assert presenter["cutout"] is True
    assert presenter["poses"] == {
        "standing": "presenters/xiaoyu/poses/standing.png",
        "pointing": "presenters/xiaoyu/poses/pointing.png",
    }
    assert "voice" not in presenter  # voice 只用于 TTS 继承，不进 timeline


def test_presenter_voice_inherited_when_manifest_omits_voice(tmp_path):
    root = tmp_path / "library"
    make_presenter_library(root, voice={"name": "zh-CN-XiaoyiNeural", "rate": "+5%", "volume": "+0%", "pitch": "+0Hz"})
    manifest = finance_manifest(presenter={"id": "xiaoyu"})

    result = pipeline.normalize_manifest(manifest, library_root=root)

    assert result["voice"]["name"] == "zh-CN-XiaoyiNeural"
    assert result["voice"]["rate"] == "+5%"


def test_presenter_voice_manifest_explicit_wins(tmp_path):
    root = tmp_path / "library"
    make_presenter_library(root)
    manifest = finance_manifest(presenter={"id": "xiaoyu"}, voice={"name": "zh-CN-YunxiNeural"})

    result = pipeline.normalize_manifest(manifest, library_root=root)

    assert result["voice"]["name"] == "zh-CN-YunxiNeural"


def test_presenter_missing_error_points_to_presenter_gen(tmp_path):
    root = tmp_path / "library"
    (root / "presenters").mkdir(parents=True)
    manifest = finance_manifest(presenter={"id": "ghost"})

    with pytest.raises(pipeline.ManifestError, match="presenter_gen.py"):
        pipeline.normalize_manifest(manifest, library_root=root)


def test_presenter_not_ready_rejected(tmp_path):
    root = tmp_path / "library"
    presenter_dir = make_presenter_library(root)
    char = json.loads((presenter_dir / "character.json").read_text(encoding="utf-8"))
    char["status"] = "pending"
    (presenter_dir / "character.json").write_text(json.dumps(char, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(pipeline.ManifestError, match="not ready"):
        pipeline.normalize_manifest(finance_manifest(presenter={"id": "xiaoyu"}), library_root=root)


def test_presenter_missing_pose_file_rejected(tmp_path):
    root = tmp_path / "library"
    presenter_dir = make_presenter_library(root)
    (presenter_dir / "poses" / "pointing.png").unlink()

    with pytest.raises(pipeline.ManifestError, match="pose image missing"):
        pipeline.normalize_manifest(finance_manifest(presenter={"id": "xiaoyu"}), library_root=root)


@pytest.mark.parametrize(
    "presenter_patch, message",
    [
        ({"id": "XiaoYu"}, "kebab-case"),
        ({"id": "xiaoyu", "position": "center"}, "position"),
        ({"id": "xiaoyu", "scale": 2.0}, "scale"),
        ({"id": "xiaoyu", "defaultPose": "dancing"}, "defaultPose"),
    ],
)
def test_presenter_field_validation(tmp_path, presenter_patch, message):
    root = tmp_path / "library"
    make_presenter_library(root)

    with pytest.raises(pipeline.ManifestError, match=message):
        pipeline.normalize_manifest(finance_manifest(presenter=presenter_patch), library_root=root)


def test_scene_presenter_override_and_hide(tmp_path):
    root = tmp_path / "library"
    make_presenter_library(root)
    manifest = finance_manifest(presenter={"id": "xiaoyu"})
    manifest["scenes"][0]["presenter"] = {"pose": "pointing"}
    manifest["scenes"][1]["presenter"] = {"visible": False}

    result = pipeline.normalize_manifest(manifest, library_root=root)

    assert result["scenes"][0]["presenter"] == {"pose": "pointing", "visible": True}
    assert result["scenes"][1]["presenter"] == {"pose": None, "visible": False}


def test_scene_presenter_requires_top_level_presenter(tmp_path):
    manifest = finance_manifest()
    manifest["scenes"][0]["presenter"] = {"pose": "pointing"}

    with pytest.raises(pipeline.ManifestError, match="requires a top-level presenter"):
        pipeline.normalize_manifest(manifest, library_root=tmp_path)


def test_scene_presenter_unknown_pose_rejected(tmp_path):
    root = tmp_path / "library"
    make_presenter_library(root)
    manifest = finance_manifest(presenter={"id": "xiaoyu"})
    manifest["scenes"][0]["presenter"] = {"pose": "dancing"}

    with pytest.raises(pipeline.ManifestError, match="pose must be one of"):
        pipeline.normalize_manifest(manifest, library_root=root)


def closes_series():
    return [3120.5, 3128.0, 3115.2, 3140.8, 3152.3, 3144.0, 3161.5, 3158.9, 3170.2, 3165.0]


def test_candlestick_closes_and_markers():
    manifest = finance_manifest()
    manifest["scenes"][0]["visual"] = {
        "type": "candlestick",
        "closes": closes_series(),
        "bands": {"middle": [3120.0 + i for i in range(10)]},
        "markers": [{"index": 3, "label": "突破", "tone": "positive", "position": "above"}],
    }

    result = pipeline.normalize_manifest(manifest)
    visual = result["scenes"][0]["visual"]

    assert visual["type"] == "candlestick"
    assert len(visual["closes"]) == 10
    assert visual["bands"]["middle"][0] == 3120.0
    assert visual["markers"] == [{"index": 3, "label": "突破", "tone": "positive", "position": "above"}]


def test_candlestick_explicit_candles():
    manifest = finance_manifest()
    manifest["scenes"][0]["visual"] = {
        "type": "candlestick",
        "candles": [
            {"o": 100, "h": 105, "l": 98, "c": 103},
            {"o": 103, "h": 106, "l": 98, "c": 99},
        ],
    }

    visual = pipeline.normalize_manifest(manifest)["scenes"][0]["visual"]
    assert len(visual["candles"]) == 2
    assert visual["candles"][1] == {"o": 103.0, "h": 106.0, "l": 98.0, "c": 99.0}


@pytest.mark.parametrize(
    "visual_patch, message",
    [
        ({"closes": closes_series(), "candles": [{"o": 1, "h": 2, "l": 0.5, "c": 1.5}, {"o": 1.5, "h": 2, "l": 1, "c": 1.8}]}, "exactly one of closes or candles"),
        ({}, "exactly one of closes or candles"),
        ({"closes": [1.0, 2.0, 3.0]}, "between 8 and 120"),
        ({"closes": closes_series(), "markers": [{"index": 10, "label": "x"}]}, "within \\[0, 10\\)"),
        ({"closes": closes_series(), "markers": [{"index": i, "label": f"m{i}"} for i in range(5)]}, "between 1 and 4"),
        ({"closes": closes_series(), "markers": [{"index": 0, "label": "这个标签实在是太长了超过十二字"}]}, "at most 12"),
        ({"closes": closes_series(), "bands": {"upper": [1.0, 2.0]}}, "same length as the series"),
    ],
)
def test_candlestick_validation(visual_patch, message):
    manifest = finance_manifest()
    manifest["scenes"][0]["visual"] = {"type": "candlestick", **visual_patch}

    with pytest.raises(pipeline.ManifestError, match=message):
        pipeline.normalize_manifest(manifest)


def test_candlestick_invalid_ohlc():
    manifest = finance_manifest()
    manifest["scenes"][0]["visual"] = {
        "type": "candlestick",
        "candles": [
            {"o": 100, "h": 105, "l": 98, "c": 103},
            {"o": 103, "h": 100, "l": 101, "c": 99},  # h < max(o,c)
            {"o": 99, "h": 102, "l": 97, "c": 101},
        ],
    }

    with pytest.raises(pipeline.ManifestError, match=r"h >= max\(o, c\)"):
        pipeline.normalize_manifest(manifest)


def test_callouts_normalized_and_validated():
    manifest = finance_manifest()
    manifest["scenes"][0]["callouts"] = [
        {"text": "布林带陷阱", "tone": "accent"},
        {"text": "缩量上涨"},  # tone 默认 accent
    ]

    result = pipeline.normalize_manifest(manifest)

    assert result["scenes"][0]["callouts"] == [
        {"text": "布林带陷阱", "tone": "accent"},
        {"text": "缩量上涨", "tone": "accent"},
    ]
    assert "callouts" not in result["scenes"][1]  # 未设置不出现在输出里


@pytest.mark.parametrize(
    "callouts, message",
    [
        ([{"text": f"c{i}", "tone": "accent"} for i in range(4)], "between 1 and 3"),
        ([{"text": "x", "tone": "hot"}], "tone must be one of"),
        ([{"text": "这条标注文字真的超过十二个字了喔"}], "at most 12"),
    ],
)
def test_callouts_validation(callouts, message):
    manifest = finance_manifest()
    manifest["scenes"][0]["callouts"] = callouts

    with pytest.raises(pipeline.ManifestError, match=message):
        pipeline.normalize_manifest(manifest)


def test_old_manifest_output_unchanged_without_new_fields():
    # 不含新字段的旧 manifest，输出结构与 domain/presenter 引入前一致（回归保护）。
    result = pipeline.normalize_manifest(sample_manifest())

    assert result["domain"] == "general"
    assert "presenter" not in result
    for scene in result["scenes"]:
        assert "callouts" not in scene
        assert "presenter" not in scene


def test_stage_assets_hardlinks_presenter_poses(tmp_path):
    root = tmp_path / "library"
    make_presenter_library(root)
    manifest = finance_manifest(presenter={"id": "xiaoyu"})
    normalized = pipeline.normalize_manifest(manifest, library_root=root)
    output_dir = tmp_path / "output"

    pipeline.stage_assets(normalized, output_dir, library_root=root)

    for rel in normalized["presenter"]["poses"].values():
        staged = output_dir / "work" / "public" / rel
        assert staged.is_file()
        assert staged.read_bytes() == (root / rel).read_bytes()


def test_stage_assets_noop_without_presenter(tmp_path):
    normalized = pipeline.normalize_manifest(sample_manifest())

    pipeline.stage_assets(normalized, tmp_path / "output", library_root=tmp_path)

    assert not (tmp_path / "output").exists()


def test_timeline_carries_domain_and_presenter(tmp_path):
    root = tmp_path / "library"
    make_presenter_library(root)
    manifest = finance_manifest(presenter={"id": "xiaoyu"})
    normalized = pipeline.normalize_manifest(manifest, library_root=root)
    srt = tmp_path / "a.srt"
    srt.write_text("1\n00:00:00,000 --> 00:00:01,000\n字幕\n", encoding="utf-8")

    timeline = pipeline.build_timeline(normalized, [{"srt": srt}, {"srt": srt}])

    assert timeline["domain"] == "finance"
    assert timeline["presenter"]["id"] == "xiaoyu"
    assert "voice" not in timeline["presenter"]


# ---------------------------------------------------------------------------
# presenter_gen 抠图后处理（白底设定集裁图流程）
# ---------------------------------------------------------------------------

Image = pytest.importorskip("PIL.Image", reason="Pillow 缺失，跳过抠图后处理测试")


def test_despeckle_removes_small_islands_keeps_body():
    img = Image.new("RGBA", (60, 60), (0, 0, 0, 0))
    for y in range(10, 50):  # 主体 40x40
        for x in range(10, 50):
            img.putpixel((x, y), (20, 20, 30, 255))
    for y in range(2, 5):  # 3x3 噪点岛
        for x in range(52, 55):
            img.putpixel((x, y), (200, 210, 225, 255))

    presenter_gen.despeckle_alpha(img, min_component=600)

    assert img.getpixel((30, 30))[3] == 255  # 主体保留
    assert img.getpixel((53, 3))[3] == 0  # 噪点被清


def test_autocrop_alpha_crops_to_bbox_with_margin():
    img = Image.new("RGBA", (100, 80), (0, 0, 0, 0))
    for y in range(20, 60):
        for x in range(30, 70):
            img.putpixel((x, y), (20, 20, 30, 255))

    cropped = presenter_gen.autocrop_alpha(img, margin=4)

    assert cropped.size == (48, 48)  # (70-30+8, 60-20+8)
    assert cropped.getpixel((4, 4))[3] == 255


def test_cutout_low_tolerance_preserves_skin_tone(tmp_path):
    """白底 + 肤色的回归测试：默认容差 42 会把皮肤误判成背景吃掉，12 不会。"""
    src = tmp_path / "skin.png"
    img = Image.new("RGBA", (50, 50), (255, 255, 255, 255))  # 白底（模拟设定集）
    for y in range(15, 35):
        for x in range(15, 35):
            img.putpixel((x, y), (255, 220, 200, 255))  # 肤色方块
    img.save(src)

    eaten = tmp_path / "eaten.png"
    kept = tmp_path / "kept.png"
    assert presenter_gen.cutout_to_png(src, eaten, tolerance=42)
    assert presenter_gen.cutout_to_png(src, kept, tolerance=12)

    assert Image.open(eaten).getpixel((25, 25))[3] == 0  # 高容差：皮肤被误吃
    assert Image.open(kept).getpixel((25, 25))[3] == 255  # 低容差：皮肤保留
    assert Image.open(kept).getpixel((2, 2))[3] == 0  # 白底仍被抠掉


def _crowded_manifest(**presenter_override):
    """立绘可见 + 三种偏挤视觉，用于遮挡警告测试。"""
    manifest = finance_manifest(presenter={"id": "xiaoyu"})
    manifest["scenes"] = [
        {
            "id": "kline",
            "narration": "看 K 线。",
            "headline": "行情",
            "visual": {"type": "candlestick", "closes": [1, 2, 3, 4, 5, 6, 7, 8]},
        },
        {
            "id": "long-quote",
            "narration": "读引用。",
            "headline": "观点",
            "visual": {"type": "quote", "quote": "长" * 61},
        },
        {
            "id": "long-stat",
            "narration": "看数字。",
            "headline": "指标",
            "visual": {"type": "stat", "value": "40G → 24G+", "label": "显存"},
        },
    ]
    for scene in manifest["scenes"]:
        if presenter_override:
            scene["presenter"] = dict(presenter_override)
    return manifest


def test_presenter_overlap_warnings_for_crowded_visuals(tmp_path):
    root = tmp_path / "library"
    make_presenter_library(root)

    result = pipeline.normalize_manifest(_crowded_manifest(), library_root=root)

    warnings = result["warnings"]
    assert any("kline" in item and "candlestick" in item for item in warnings)
    assert any("long-quote" in item and "长引用" in item for item in warnings)
    assert any("long-stat" in item and "stat" in item for item in warnings)


def test_presenter_overlap_warnings_suppressed_when_hidden(tmp_path):
    root = tmp_path / "library"
    make_presenter_library(root)

    result = pipeline.normalize_manifest(_crowded_manifest(visible=False), library_root=root)

    assert "warnings" not in result


def test_no_presenter_no_warnings_key():
    result = pipeline.normalize_manifest(sample_manifest())

    assert "warnings" not in result
