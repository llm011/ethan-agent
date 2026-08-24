import importlib.util
import json
import struct
import sys
import zlib
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
    # 默认音色与 presenter_gen.DEFAULT_VOICE 统一为 Xiaoyi（本分支既有改动）。
    assert result["voice"]["name"] == "zh-CN-XiaoyiNeural"
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
        "seedance-presenter-pipeline.md",
    }


# ── P1: domain / presenter / candlestick / callouts ──


def make_presenter_library(
    root: Path, presenter_id: str = "xiaoyu", *, voice: dict | None = None, variants: bool = False
) -> Path:
    """在临时库根下造一个 ready 状态的 presenter 角色包（两姿势，可选变体）。"""
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
    if variants:
        # 变体只挂在 standing 上：覆盖"部分姿势有变体"的真实情况
        for variant in ("blink", "talk"):
            (poses_dir / f"standing-{variant}.png").write_bytes(b"\x89PNG\r\n\x1a\nfake")
        character["variants"] = {
            "standing": {"blink": "poses/standing-blink.png", "talk": "poses/standing-talk.png"}
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


def test_presenter_variants_loaded_from_library(tmp_path):
    root = tmp_path / "library"
    make_presenter_library(root, variants=True)
    manifest = finance_manifest(presenter={"id": "xiaoyu"})

    result = pipeline.normalize_manifest(manifest, library_root=root)

    assert result["presenter"]["variants"] == {
        "standing": {
            "blink": "presenters/xiaoyu/poses/standing-blink.png",
            "talk": "presenters/xiaoyu/poses/standing-talk.png",
        }
    }


def test_presenter_variants_omitted_when_absent(tmp_path):
    # 旧 character.json 没有变体：payload 不出现 variants 键（渲染端退化为静态立绘）。
    root = tmp_path / "library"
    make_presenter_library(root)
    manifest = finance_manifest(presenter={"id": "xiaoyu"})

    result = pipeline.normalize_manifest(manifest, library_root=root)

    assert "variants" not in result["presenter"]


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


@pytest.mark.parametrize(
    "variants_patch, message",
    [
        ("not-an-object", "must be an object"),
        ({"dancing": {"blink": "poses/standing-blink.png"}}, "not a known pose"),
        ({"standing": {}}, "non-empty object"),
        ({"standing": {"wink": "poses/standing-blink.png"}}, "blink' or 'talk"),
        ({"standing": {"blink": "poses/ghost.png"}}, "variant image missing"),
        ({"standing": {"blink": "../standing.png"}}, "stay inside"),
        ({"standing": {"blink": "/tmp/evil.png"}}, "stay inside"),
    ],
)
def test_presenter_variants_validation(tmp_path, variants_patch, message):
    # 变体是可选的，但一旦出现就与 poses 同级防护：结构/路径/文件存在性全查。
    root = tmp_path / "library"
    presenter_dir = make_presenter_library(root)
    (presenter_dir / "poses" / "standing-blink.png").write_bytes(b"\x89PNG\r\n\x1a\nfake")
    char = json.loads((presenter_dir / "character.json").read_text(encoding="utf-8"))
    char["variants"] = variants_patch
    (presenter_dir / "character.json").write_text(json.dumps(char, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(pipeline.ManifestError, match=message):
        pipeline.normalize_manifest(finance_manifest(presenter={"id": "xiaoyu"}), library_root=root)


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


def test_stage_assets_stages_variant_images(tmp_path):
    root = tmp_path / "library"
    make_presenter_library(root, variants=True)
    manifest = finance_manifest(presenter={"id": "xiaoyu"})
    normalized = pipeline.normalize_manifest(manifest, library_root=root)
    output_dir = tmp_path / "output"

    pipeline.stage_assets(normalized, output_dir, library_root=root)

    for entry in normalized["presenter"]["variants"].values():
        for rel in entry.values():
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


def test_timeline_carries_presenter_variants(tmp_path):
    root = tmp_path / "library"
    make_presenter_library(root, variants=True)
    manifest = finance_manifest(presenter={"id": "xiaoyu"})
    normalized = pipeline.normalize_manifest(manifest, library_root=root)
    srt = tmp_path / "a.srt"
    srt.write_text("1\n00:00:00,000 --> 00:00:01,000\n字幕\n", encoding="utf-8")

    timeline = pipeline.build_timeline(normalized, [{"srt": srt}, {"srt": srt}])

    assert timeline["presenter"]["variants"]["standing"] == {
        "blink": "presenters/xiaoyu/poses/standing-blink.png",
        "talk": "presenters/xiaoyu/poses/standing-talk.png",
    }


# ---------------------------------------------------------------------------
# presenter_gen 变体文件匹配（纯函数，不需要 Pillow）
# ---------------------------------------------------------------------------


def test_split_variant_files_separates_variants_from_poses(tmp_path):
    files = [
        tmp_path / "standing.png",
        tmp_path / "standing-blink.png",
        tmp_path / "standing-talk.png",
        tmp_path / "pointing.png",
        tmp_path / "random.png",
    ]

    base, variants = presenter_gen.split_variant_files(files, ["standing", "pointing"])

    assert base == [tmp_path / "standing.png", tmp_path / "pointing.png", tmp_path / "random.png"]
    assert variants == {
        ("standing", "blink"): tmp_path / "standing-blink.png",
        ("standing", "talk"): tmp_path / "standing-talk.png",
    }


def test_split_variant_files_pose_name_wins_over_variant_suffix(tmp_path):
    # 用户自定义了 standing-blink 姿势名时，同名文件是姿势不是变体。
    files = [tmp_path / "standing-blink.png"]

    base, variants = presenter_gen.split_variant_files(files, ["standing-blink"])

    assert base == files
    assert variants == {}


def test_match_pose_files_variants_never_fill_poses(tmp_path):
    # 变体文件必须从姿势匹配池剔除：否则 "standing" in "standing-blink" 的
    # 包含匹配会把闭眼图误配给 standing 姿势本体。
    for name in ("standing.png", "standing-blink.png"):
        (tmp_path / name).write_bytes(b"x")

    assigned, variants = presenter_gen.match_pose_files(tmp_path, ["standing"])

    assert assigned == {"standing": tmp_path / "standing.png"}
    assert variants == {("standing", "blink"): tmp_path / "standing-blink.png"}


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


def _write_alpha_png(path: Path) -> None:
    # RGBA + 至少一个透明像素：png_has_alpha 像素级验证通过，import 走归一而非抠图。
    img = Image.new("RGBA", (40, 60), (255, 0, 255, 255))
    img.putpixel((0, 0), (0, 0, 0, 0))
    img.save(path)


def test_cmd_import_variants_written_to_character(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("ETHAN_DATA_DIR", str(tmp_path))
    presenter_dir = tmp_path / "assets" / "library" / "presenters" / "xiaoyu"
    presenter_dir.mkdir(parents=True)
    character = {
        "id": "xiaoyu",
        "name": "晓玉",
        "status": "pending",
        "sheet": "cute anime presenter",
        "posesPrompts": {"standing": "stand", "pointing": "point"},
    }
    (presenter_dir / "character.json").write_text(json.dumps(character, ensure_ascii=False), encoding="utf-8")
    images = tmp_path / "images"
    images.mkdir()
    for name in ("standing.png", "standing-blink.png", "standing-talk.png", "pointing.png"):
        _write_alpha_png(images / name)

    presenter_gen.cmd_import("xiaoyu", images)

    saved = json.loads((presenter_dir / "character.json").read_text(encoding="utf-8"))
    assert saved["status"] == "ready"
    assert saved["variants"] == {
        "standing": {"blink": "poses/standing-blink.png", "talk": "poses/standing-talk.png"}
    }
    assert (presenter_dir / "poses" / "standing-blink.png").is_file()
    assert (presenter_dir / "poses" / "standing-talk.png").is_file()

    # 导入的角色包直接被 pipeline 接受（变体贯通到 timeline 数据）
    manifest = finance_manifest(presenter={"id": "xiaoyu"})
    normalized = pipeline.normalize_manifest(manifest, library_root=tmp_path / "assets" / "library")
    assert normalized["presenter"]["variants"]["standing"]["blink"] == (
        "presenters/xiaoyu/poses/standing-blink.png"
    )


def test_cmd_import_without_variants_degrades_to_static(tmp_path, monkeypatch):
    # 目录里没有变体图：character.json 的 variants 写成空 dict，pipeline 侧不出现该键。
    monkeypatch.setenv("ETHAN_DATA_DIR", str(tmp_path))
    presenter_dir = tmp_path / "assets" / "library" / "presenters" / "xiaoyu"
    presenter_dir.mkdir(parents=True)
    character = {
        "id": "xiaoyu",
        "name": "晓玉",
        "status": "pending",
        "sheet": "cute anime presenter",
        "posesPrompts": {"standing": "stand", "pointing": "point"},
    }
    (presenter_dir / "character.json").write_text(json.dumps(character, ensure_ascii=False), encoding="utf-8")
    images = tmp_path / "images"
    images.mkdir()
    for name in ("standing.png", "pointing.png"):
        _write_alpha_png(images / name)

    presenter_gen.cmd_import("xiaoyu", images)

    saved = json.loads((presenter_dir / "character.json").read_text(encoding="utf-8"))
    assert saved["variants"] == {}
    manifest = finance_manifest(presenter={"id": "xiaoyu"})
    normalized = pipeline.normalize_manifest(manifest, library_root=tmp_path / "assets" / "library")
    assert "variants" not in normalized["presenter"]


# ---------------------------------------------------------------------------
# presenter_gen 设定集切分与变体对齐（import-sheet）
# ---------------------------------------------------------------------------


def _block_pattern(rng, height: int, width: int, block: int = 40):
    """大色块图案：SSD 对齐搜索需要结构化内容（纯色/噪声都会让 SSD 平坦）。"""
    import numpy as np

    rows = (height + block - 1) // block
    cols = (width + block - 1) // block
    arr = rng.integers(0, 255, (rows, cols, 3), dtype=np.uint8)
    return np.repeat(np.repeat(arr, block, axis=0), block, axis=1)[:height, :width]


def test_build_sheet_prompt_panels_and_grid():
    character = {"sheet": "BASE SHEET TEXT", "posesPrompts": {"standing": "stand phrase", "pointing": "point phrase"}}

    prompt, panels = presenter_gen.build_sheet_prompt(character)

    # 全部基础姿势 + 默认姿势（第一个）的 blink/talk 变体，阅读顺序
    assert panels == ["standing", "standing-blink", "standing-talk", "pointing"]
    assert "BASE SHEET TEXT" in prompt
    assert "4 separate panels" in prompt
    assert "2x2 grid" in prompt


def test_split_sheet_reading_order_and_alpha(tmp_path):
    # 2x2 布局；第二行故意整体更低、行内 y 错位（行分组按垂直重叠，不按绝对 y）
    sheet = tmp_path / "sheet.png"
    img = Image.new("RGB", (800, 620), (255, 0, 255))
    from PIL import ImageDraw

    draw = ImageDraw.Draw(img)
    draw.rectangle([40, 30, 380, 290], fill=(120, 30, 30))     # row1 col1
    draw.rectangle([420, 60, 760, 320], fill=(30, 120, 30))    # row1 col2（更低仍同行）
    draw.rectangle([40, 380, 380, 590], fill=(30, 30, 120))    # row2 col1
    draw.rectangle([420, 410, 760, 610], fill=(120, 120, 30))  # row2 col2
    img.save(sheet)

    panels = presenter_gen.split_sheet(sheet)

    assert len(panels) == 4
    colors = [img.convert("RGB").getpixel((5, 5)) for _, img in panels]
    assert colors == [(120, 30, 30), (30, 120, 30), (30, 30, 120), (120, 120, 30)]
    # 品红底被抠成透明：面板角内不透明、角外（bbox 收紧后不存在）无残留
    assert panels[0][1].getpixel((0, 0))[3] == 255


def test_split_sheet_ignores_small_specks(tmp_path):
    sheet = tmp_path / "sheet.png"
    img = Image.new("RGB", (800, 400), (255, 0, 255))
    from PIL import ImageDraw

    draw = ImageDraw.Draw(img)
    draw.rectangle([40, 40, 380, 340], fill=(120, 30, 30))
    draw.rectangle([420, 40, 760, 340], fill=(30, 120, 30))
    draw.rectangle([600, 370, 604, 374], fill=(255, 255, 255))  # 5x5 噪点
    img.save(sheet)

    panels = presenter_gen.split_sheet(sheet)

    assert len(panels) == 2


def test_split_sheet_merges_disconnected_fragments(tmp_path):
    # 抬手姿势：手臂与身体之间被背景隔开（泛洪切成两块连通域）→ 碎片就近并回同一面板
    sheet = tmp_path / "sheet.png"
    img = Image.new("RGB", (900, 400), (255, 0, 255))
    from PIL import ImageDraw

    draw = ImageDraw.Draw(img)
    draw.rectangle([40, 40, 380, 340], fill=(120, 30, 30))    # 面板1 身体
    draw.rectangle([385, 100, 410, 170], fill=(200, 30, 30))  # 断开的手臂碎片（更近面板1）
    draw.rectangle([480, 40, 860, 340], fill=(30, 120, 30))   # 面板2（尺寸相近，不并）
    img.save(sheet)

    panels = presenter_gen.split_sheet(sheet)

    assert len(panels) == 2
    # 手臂并入面板1：bbox = 身体 ∪ 手臂（ImageDraw 端点含闭）；面板2 原样
    assert panels[0][0] == (40, 40, 411, 341)
    assert panels[1][0] == (480, 40, 861, 341)


def test_split_sheet_uses_native_alpha(tmp_path):
    # 自带透明背景的 PNG 设定集：直接用 alpha 通道，不走泛洪
    img = Image.new("RGBA", (400, 200), (0, 0, 0, 0))
    img.paste(Image.new("RGBA", (120, 150), (10, 200, 30, 255)), (20, 20))
    img.paste(Image.new("RGBA", (120, 150), (30, 220, 40, 255)), (240, 30))
    sheet = tmp_path / "sheet.png"
    img.save(sheet)

    panels = presenter_gen.split_sheet(sheet)

    assert len(panels) == 2
    assert panels[0][0] == (20, 20, 140, 170)


def test_align_variant_recovers_translation():
    np = pytest.importorskip("numpy")
    pattern = Image.fromarray(_block_pattern(np.random.default_rng(42), 260, 300), "RGB").convert("RGBA")
    base = Image.new("RGBA", (340, 300), (0, 0, 0, 0))
    base.paste(pattern, (0, 0))
    shifted = Image.new("RGBA", (340, 300), (0, 0, 0, 0))
    shifted.paste(pattern, (13, 9))

    scale, dx, dy = presenter_gen.align_variant(base, shifted)

    # 变体内容右移 13、下移 9 → 对齐偏移 (-13, -9)
    assert abs(scale - 1.0) < 1e-9
    assert (dx, dy) == (-13, -9)


def test_compose_pose_group_aligns_variants():
    np = pytest.importorskip("numpy")
    pattern = Image.fromarray(_block_pattern(np.random.default_rng(7), 280, 180), "RGB").convert("RGBA")
    base_canvas = Image.new("RGBA", (200, 300), (0, 0, 0, 0))
    base_canvas.paste(pattern, (10, 10))
    var_canvas = Image.new("RGBA", (220, 320), (0, 0, 0, 0))
    var_canvas.paste(pattern, (16, 14))  # 基础图内容右移 6、下移 4
    group = {
        "": ((10, 10, 190, 290), base_canvas.crop((10, 10, 190, 290))),
        "blink": ((16, 14, 196, 294), var_canvas.crop((16, 14, 196, 294))),
    }

    out = presenter_gen._compose_pose_group(group)

    # 同尺寸画布 + 内容像素级重合（bbox 完全一致）
    assert out[""].size == out["blink"].size
    assert out[""].getbbox() == out["blink"].getbbox()


def _make_pending_sheet_character(tmp_path: Path, presenter_id: str) -> Path:
    presenter_dir = tmp_path / "assets" / "library" / "presenters" / presenter_id
    presenter_dir.mkdir(parents=True)
    character = {
        "id": presenter_id,
        "name": "设定集娘",
        "status": "pending",
        "sheet": "cute anime presenter",
        "posesPrompts": {"standing": "stand", "pointing": "point"},
    }
    (presenter_dir / "character.json").write_text(json.dumps(character, ensure_ascii=False), encoding="utf-8")
    return presenter_dir


def test_cmd_import_sheet_end_to_end(tmp_path, monkeypatch):
    pytest.importorskip("numpy")  # 对齐路径需要 numpy；缺失时整链降级，这里测对齐路径
    monkeypatch.setenv("ETHAN_DATA_DIR", str(tmp_path))
    presenter_dir = _make_pending_sheet_character(tmp_path, "sheetgirl")
    # 品红底 2x2：standing / standing-blink / standing-talk / pointing（阅读顺序）
    sheet = tmp_path / "sheet.png"
    img = Image.new("RGB", (800, 620), (255, 0, 255))
    from PIL import ImageDraw

    draw = ImageDraw.Draw(img)
    draw.rectangle([40, 30, 380, 290], fill=(120, 140, 160))
    draw.rectangle([420, 30, 760, 290], fill=(120, 140, 160))
    draw.rectangle([40, 330, 380, 590], fill=(150, 120, 170))
    draw.rectangle([420, 330, 760, 590], fill=(160, 130, 120))
    img.save(sheet)

    presenter_gen.cmd_import_sheet(
        "sheetgirl", sheet, order=["standing", "standing-blink", "standing-talk", "pointing"]
    )

    saved = json.loads((presenter_dir / "character.json").read_text(encoding="utf-8"))
    assert saved["status"] == "ready"
    assert saved["cutout"] is True
    assert set(saved["poses"]) == {"standing", "pointing"}
    assert set(saved["variants"]["standing"]) == {"blink", "talk"}
    # 组内同尺寸画布（渲染端 contain-fit 同缩放、切换零跳动的关键）
    standing = Image.open(presenter_dir / "poses" / "standing.png")
    blink = Image.open(presenter_dir / "poses" / "standing-blink.png")
    talk = Image.open(presenter_dir / "poses" / "standing-talk.png")
    assert standing.size == blink.size == talk.size
    # 导入的角色包直接被 pipeline 接受（变体贯通到 timeline 数据）
    manifest = finance_manifest(presenter={"id": "sheetgirl"})
    normalized = pipeline.normalize_manifest(manifest, library_root=tmp_path / "assets" / "library")
    assert normalized["presenter"]["variants"]["standing"]["blink"] == (
        "presenters/sheetgirl/poses/standing-blink.png"
    )


def test_cmd_import_sheet_order_validation(tmp_path, monkeypatch):
    monkeypatch.setenv("ETHAN_DATA_DIR", str(tmp_path))
    _make_pending_sheet_character(tmp_path, "sheetgirl")
    sheet = tmp_path / "sheet.png"
    Image.new("RGB", (100, 100), (255, 0, 255)).save(sheet)

    with pytest.raises(SystemExit, match="无法识别"):
        presenter_gen.cmd_import_sheet("sheetgirl", sheet, order=["standing", "dancing"])
    with pytest.raises(SystemExit, match="重复名字"):
        presenter_gen.cmd_import_sheet("sheetgirl", sheet, order=["standing", "standing"])
    with pytest.raises(SystemExit, match="缺少基础姿势"):
        presenter_gen.cmd_import_sheet("sheetgirl", sheet, order=["standing", "standing-blink"])
    # 纯品红图切不出面板 → 数量不匹配诊断
    with pytest.raises(SystemExit, match="面板"):
        presenter_gen.cmd_import_sheet("sheetgirl", sheet, order=["standing", "pointing"])


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


# ---------------------------------------------------------------------------
# P2 修复回归：非有限数值 / png_has_alpha / CLI id 校验 / 极端窄画布 / voice 继承报错
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_candlestick_non_finite_numbers_rejected(bad):
    # NaN/Infinity 能通过 isinstance(float) 检查，但渲染成 K 线必炸，必须在校验层拦下。
    manifest = finance_manifest()
    closes = closes_series()
    closes[0] = bad
    manifest["scenes"][0]["visual"] = {"type": "candlestick", "closes": closes}

    with pytest.raises(pipeline.ManifestError, match="finite"):
        pipeline.normalize_manifest(manifest)


def test_png_has_alpha_fully_opaque_rgba_is_false(tmp_path):
    # RGBA 但全不透明：会被误判已抠图、品红底直接进成片，必须返回 False 走抠图路径。
    path = tmp_path / "opaque.png"
    Image.new("RGBA", (8, 8), (255, 0, 255, 255)).save(path)

    assert presenter_gen.png_has_alpha(path) is False


def test_png_has_alpha_transparent_rgba_is_true(tmp_path):
    path = tmp_path / "transparent.png"
    img = Image.new("RGBA", (8, 8), (255, 0, 255, 255))
    img.putpixel((0, 0), (255, 0, 255, 0))
    img.save(path)

    assert presenter_gen.png_has_alpha(path) is True


def test_png_has_alpha_ignores_trns_bytes_inside_chunk_data(tmp_path):
    # 回归：旧实现按 b"tRNS" 子串匹配，chunk 数据区里碰巧出现的 tRNS 字节会误报有 alpha。
    path = tmp_path / "fake-trns.png"
    Image.new("RGB", (8, 8), (255, 0, 255)).save(path)
    data = path.read_bytes()
    payload = b"comment\x00this chunk data mentions tRNS but is not a real tRNS chunk"
    chunk = struct.pack(">I", len(payload)) + b"tEXt" + payload
    chunk += struct.pack(">I", zlib.crc32(b"tEXt" + payload) & 0xFFFFFFFF)
    ihdr_end = 8 + 4 + 4 + 13 + 4  # 签名 8B + IHDR（长度 4B + 类型 4B + 数据 13B + CRC 4B）
    path.write_bytes(data[:ihdr_end] + chunk + data[ihdr_end:])

    assert presenter_gen.png_has_alpha(path) is False


def test_png_has_alpha_palette_with_transparency_is_true(tmp_path):
    path = tmp_path / "palette.png"
    img = Image.new("P", (8, 8), 1)
    img.putpalette([255, 0, 255] * 256)
    img.save(path, transparency=1)  # 索引 1 透明，且全图都是索引 1

    assert presenter_gen.png_has_alpha(path) is True


@pytest.mark.parametrize(
    "argv",
    [
        ["presenter_gen.py", "show", "../evil"],
        ["presenter_gen.py", "import", "../evil", "/nonexistent-dir"],
        ["presenter_gen.py", "regen", "../evil", "standing"],
        ["presenter_gen.py", "prompts", "x/y"],
    ],
)
def test_cli_rejects_non_kebab_case_presenter_id(monkeypatch, argv):
    # main() 分发前统一校验 id，堵住 ../x 之类的路径逃逸（import/regen/show 此前不校验）。
    monkeypatch.setattr(sys, "argv", argv)

    with pytest.raises(SystemExit) as exc_info:
        presenter_gen.main()

    assert "kebab-case" in str(exc_info.value.code)


def test_extreme_narrow_canvas_with_presenter_rejected(tmp_path):
    # 宽 320（下限）+ scale 1.4（上限）：内容列被立绘车道挤成负数，直接拒绝而不是只警告。
    root = tmp_path / "library"
    make_presenter_library(root)
    manifest = finance_manifest(presenter={"id": "xiaoyu", "scale": 1.4})
    manifest["width"] = 320
    manifest["height"] = 320
    manifest["scenes"][0]["visual"] = {"type": "candlestick", "closes": closes_series()}

    with pytest.raises(pipeline.ManifestError, match="no room left"):
        pipeline.normalize_manifest(manifest, library_root=root)


def test_presenter_voice_inherited_error_points_to_character_json(tmp_path):
    # voice 继承自 character.json 时报错要指向真正的修改位置，而不是 manifest。
    root = tmp_path / "library"
    make_presenter_library(
        root, voice={"name": "zh-CN-XiaoyiNeural", "rate": "fast", "volume": "+0%", "pitch": "+0Hz"}
    )
    manifest = finance_manifest(presenter={"id": "xiaoyu"})

    with pytest.raises(pipeline.ManifestError, match="inherited from presenter character.json"):
        pipeline.normalize_manifest(manifest, library_root=root)


def test_manifest_explicit_voice_error_keeps_original_message(tmp_path):
    # manifest 显式写的 voice 校验失败：报错保持原样，不带 inherited 字样。
    root = tmp_path / "library"
    make_presenter_library(root)
    manifest = finance_manifest(presenter={"id": "xiaoyu"}, voice={"rate": "fast"})

    with pytest.raises(pipeline.ManifestError, match="voice.rate must look like") as exc_info:
        pipeline.normalize_manifest(manifest, library_root=root)

    assert "inherited" not in str(exc_info.value)
