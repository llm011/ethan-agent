import importlib.util
import sys
from pathlib import Path

import pytest

SCRIPT = (
    Path(__file__).parents[1]
    / "ethan"
    / "defaults"
    / "skills"
    / "book-audio-digest"
    / "scripts"
    / "audio_pipeline.py"
)
SPEC = importlib.util.spec_from_file_location("book_audio_digest_pipeline", SCRIPT)
assert SPEC and SPEC.loader
pipeline = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = pipeline
SPEC.loader.exec_module(pipeline)


def sample_manifest():
    return {
        "title": "《测试》深度听书",
        "sections": [
            {"id": "opening", "narration": "这是开场白。"},
            {"id": "insight-1", "narration": "这是第一个洞察。"},
            {"id": "closing", "narration": "这是收尾。"},
        ],
    }


def test_normalize_manifest_adds_deterministic_defaults():
    result = pipeline.normalize_manifest(sample_manifest())

    assert result["voice"]["name"] == "zh-CN-YunxiNeural"
    assert result["voice"]["rate"] == "+0%"
    assert result["gapMs"] == 700
    assert result["targetDurationSec"] is None
    assert [s["id"] for s in result["sections"]] == ["opening", "insight-1", "closing"]


@pytest.mark.parametrize(
    "mutate, message",
    [
        (lambda v: v["sections"][1].update(id="opening"), "duplicate section id"),
        (lambda v: v["sections"][0].update(narration="  "), "narration"),
        (lambda v: v["sections"][0].update(id="Bad_Id"), "kebab-case"),
        (lambda v: v["voice"].update(rate="fast"), "voice.rate"),
        (lambda v: v["voice"].update(pitch="+5%"), "voice.pitch"),
        (lambda v: v.update(gapMs=-1), "gapMs"),
        (lambda v: v.update(targetDurationSec=10), "targetDurationSec"),
        (lambda v: v.update(sections=[]), "sections"),
        (lambda v: v.update(title=""), "title"),
    ],
)
def test_manifest_validation_rejects_invalid_values(mutate, message):
    value = sample_manifest()
    value.setdefault("voice", {}).setdefault("name", "zh-CN-YunxiNeural")
    mutate(value)

    with pytest.raises(pipeline.ManifestError, match=message):
        pipeline.normalize_manifest(value)


def test_srt_round_trip_and_merged_offsets(tmp_path):
    first = tmp_path / "first.srt"
    second = tmp_path / "second.srt"
    first.write_text("1\n00:00:00,100 --> 00:00:01,000\n第一句\n", encoding="utf-8")
    second.write_text("1\n00:00:00,200 --> 00:00:02,500\n第二句\n", encoding="utf-8")

    manifest = pipeline.normalize_manifest(sample_manifest())
    manifest["gapMs"] = 700
    artifacts = [
        {"id": "opening", "srt": first},
        {"id": "closing", "srt": second},
    ]
    merged = pipeline.build_merged_subtitles(manifest, artifacts, durations_ms=[10_000, 10_000])

    assert [m.text for m in merged] == ["第一句", "第二句"]
    # 第二章节字幕整体偏移 = 前一章节时长 10s + 章节间静音 0.7s
    assert merged[1].start_ms == 10_700 + 200
    assert merged[1].end_ms == 10_700 + 2_500

    serialized = pipeline.serialize_srt(merged)
    assert "00:00:10,900 --> 00:00:13,200" in serialized
    assert pipeline.parse_srt(serialized) == merged


def test_tts_cache_key_distinguishes_voice_and_text():
    base = {"id": "opening", "narration": "同一段文本"}
    voice_a = {"name": "zh-CN-YunxiNeural", "rate": "+0%", "volume": "+0%", "pitch": "+0Hz"}
    voice_b = dict(voice_a, rate="+5%")

    key_text_a = pipeline._tts_cache_key(base, voice_a)
    key_text_b = pipeline._tts_cache_key({**base, "narration": "另一段文本"}, voice_a)
    key_voice_b = pipeline._tts_cache_key(base, voice_b)

    assert key_text_a != key_text_b
    assert key_text_a != key_voice_b
    # 相同输入稳定复用缓存
    assert key_text_a == pipeline._tts_cache_key(base, voice_a)


def test_validate_cli_reports_estimated_chars(tmp_path, capsys):
    import json

    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(sample_manifest(), ensure_ascii=False), encoding="utf-8")

    argv = sys.argv
    try:
        sys.argv = ["audio_pipeline.py", "validate", "--manifest", str(manifest_path)]
        code = pipeline.main()
    finally:
        sys.argv = argv

    out = capsys.readouterr().out
    assert code == 0
    assert json.loads(out)["status"] == "ok"
    assert json.loads(out)["estimatedChars"] == 19  # 6+8+5 字（含标点）
