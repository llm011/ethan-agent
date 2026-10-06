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


# ---------------------------------------------------------------------------
# 状态回显 / 失败清理：深度听书后台合成期间的「在跑 vs 挂了」可观测性
# ---------------------------------------------------------------------------


def _write_manifest(tmp_path) -> Path:
    import json

    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(sample_manifest(), ensure_ascii=False), encoding="utf-8")
    return manifest_path


def test_run_pipeline_failure_clears_stale_outputs_and_records_stage(tmp_path, monkeypatch):
    """失败时旧产物必须消失：否则「status ok + 文件存在」的复核会把陈年音频当本次交付。"""
    import json

    manifest_path = _write_manifest(tmp_path)
    stale_audio = tmp_path / "final.mp3"
    stale_audio.write_bytes(b"\xff" * 9_000)
    stale_srt = tmp_path / "subtitles.srt"
    stale_srt.write_text("1\n00:00:00,000 --> 00:00:01,000\n上一轮的旧字幕\n", encoding="utf-8")

    def boom(manifest, output_dir):
        raise RuntimeError("TTS failed for section insight-1: 网络不可达")

    monkeypatch.setattr(pipeline, "synthesize_sections", boom)

    status = pipeline.run_pipeline(manifest_path, tmp_path)

    assert status["status"] == "error"
    assert status["stage"] == "synthesis"
    assert "insight-1" in status["error"]
    assert not stale_audio.exists(), "失败后不得留下上一轮的 final.mp3"
    assert not stale_srt.exists(), "失败后不得留下上一轮的 subtitles.srt"

    on_disk = json.loads((tmp_path / "run-status.json").read_text(encoding="utf-8"))
    assert on_disk["status"] == "error"
    assert on_disk["stage"] == "synthesis"
    assert on_disk["startedAt"] and on_disk["finishedAt"]


def test_run_pipeline_marks_running_before_synthesis(tmp_path, monkeypatch):
    """进度回显：合成期 status 不能是「文件不存在」，否则分不清没开始和在跑。"""
    import json

    manifest_path = _write_manifest(tmp_path)
    seen: dict = {}

    def capture(manifest, output_dir):
        seen.update(json.loads((output_dir / "run-status.json").read_text(encoding="utf-8")))
        raise RuntimeError("stop here")

    monkeypatch.setattr(pipeline, "synthesize_sections", capture)
    pipeline.run_pipeline(manifest_path, tmp_path)

    assert seen["status"] == "running"
    assert seen["sectionCount"] == 3
    assert seen["title"] == "《测试》深度听书"


def test_synthesis_failure_error_has_single_prefix_and_progress(tmp_path, monkeypatch, capsys):
    """错误信息不得叠前缀（真因会被埋掉），且逐节进度要落 stderr（render.log）。"""
    manifest = pipeline.normalize_manifest(sample_manifest())

    async def failing_once(text, voice, media_path, srt_path):
        raise RuntimeError("Edge TTS returned an empty audio file")

    monkeypatch.setattr(pipeline, "_synthesize_once", failing_once)

    with pytest.raises(RuntimeError) as excinfo:
        pipeline.synthesize_sections(manifest, tmp_path, retries=1)

    message = str(excinfo.value)
    assert message.count("TTS failed for section") == 1
    assert "opening" in message
    assert "Edge TTS returned an empty audio file" in message

    stderr = capsys.readouterr().err
    assert "[audio-pipeline]" in stderr
    assert "合成中 opening" in stderr
    assert not list((tmp_path / "work" / "tts-cache").glob(".*.tmp")), "失败的临时文件要清掉"


def test_synthesis_retry_logs_attempt_before_sleeping(tmp_path, monkeypatch, capsys):
    """重试也要有进度回声，否则限流退避期间 render.log 看起来像卡死。"""
    manifest = pipeline.normalize_manifest(sample_manifest())
    manifest["sections"] = manifest["sections"][:1]
    calls = {"n": 0}

    async def flaky_once(text, voice, media_path, srt_path):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("HTTP 499")
        media_path.write_bytes(b"\xff" * 512)
        srt_path.write_text("1\n00:00:00,000 --> 00:00:02,000\n好\n", encoding="utf-8")

    monkeypatch.setattr(pipeline, "_synthesize_once", flaky_once)

    async def _no_sleep(_seconds):
        return None

    monkeypatch.setattr(pipeline.asyncio, "sleep", _no_sleep)

    artifacts = pipeline.synthesize_sections(manifest, tmp_path, retries=3)

    stderr = capsys.readouterr().err
    assert "第 1 次失败" in stderr
    assert "缓存命中" not in stderr
    assert artifacts[0]["audio"].exists() and artifacts[0]["srt"].exists()
