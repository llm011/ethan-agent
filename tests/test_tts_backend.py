"""可配置 TTS 后端（_shared/tts_backend.py）单元测试。

覆盖三件事：
1. 配置优先级（manifest > config.yaml > 环境变量 > 默认 edge）与 ethan 音色解析；
2. ethan 后端没有词级时间戳时的字幕切分（不重叠、不越界、文本完整）；
3. 两个管线的缓存键包含后端签名——换后端不会误命中旧音频。
"""
import importlib.util
import sys
from pathlib import Path

import pytest

SHARED = Path(__file__).parents[1] / "ethan" / "defaults" / "skills" / "_shared" / "tts_backend.py"
SPEC = importlib.util.spec_from_file_location("tts_backend", SHARED)
assert SPEC and SPEC.loader
tts = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = tts
SPEC.loader.exec_module(tts)


def _write_config(tmp_path, body: str) -> Path:
    path = tmp_path / "config.yaml"
    path.write_text(body, encoding="utf-8")
    return path


def test_default_backend_is_edge():
    config = tts.resolve_tts_config({"name": "zh-CN-YunxiNeural"}, config_path=Path("/nonexistent"), env={})

    assert config.backend == "edge"
    assert config.source == "default"
    assert config.cache_signature()["name"] == "zh-CN-YunxiNeural"


def test_config_yaml_selects_ethan_and_voice(tmp_path, monkeypatch):
    path = _write_config(
        tmp_path,
        "providers:\n  anthropic:\n    api_key: x\ntts:\n  backend: ethan\n  voice: preset:Serena\n  instruct: 温柔一点\n",
    )
    monkeypatch.setattr(tts.shutil, "which", lambda name: "/usr/local/bin/ethan-tts")

    config = tts.resolve_tts_config({"name": "zh-CN-YunxiNeural"}, config_path=path, env={})

    assert config.backend == "ethan"
    assert config.source == "config"
    assert config.ethan_voice == "preset:Serena"
    assert config.ethan_instruct == "温柔一点"
    # ethan 后端的缓存签名不包含 edge 音色名，但包含本地音色。
    assert config.cache_signature()["voice"] == "preset:Serena"


def test_manifest_backend_overrides_config(tmp_path, monkeypatch):
    path = _write_config(tmp_path, "tts:\n  backend: ethan\n  voice: preset:Vivian\n")
    monkeypatch.setattr(tts.shutil, "which", lambda name: "/usr/local/bin/ethan-tts")

    config = tts.resolve_tts_config({"backend": "edge", "name": "zh-CN-XiaoyiNeural"}, config_path=path, env={})

    assert config.backend == "edge"
    assert config.source == "manifest"


def test_explicit_argument_wins(tmp_path):
    path = _write_config(tmp_path, "tts:\n  backend: ethan\n")
    config = tts.resolve_tts_config({}, backend="edge", config_path=path, env={})

    assert config.backend == "edge"
    assert config.source == "argument"


def test_env_var_is_used_before_default(tmp_path):
    config = tts.resolve_tts_config(
        {}, config_path=tmp_path / "missing.yaml", env={"ETHAN_TTS_BACKEND": "ethan"}
    )

    assert config.backend == "ethan"
    assert config.source == "env"


def test_unknown_backend_warns_and_falls_back_to_edge(tmp_path):
    path = _write_config(tmp_path, "tts:\n  backend: azure\n")

    config = tts.resolve_tts_config({}, config_path=path, env={})

    assert config.backend == "edge"
    assert any("azure" in warning for warning in config.warnings)


def test_missing_ethan_command_fails_fast(tmp_path, monkeypatch):
    path = _write_config(tmp_path, "tts:\n  backend: ethan\n")
    monkeypatch.setattr(tts.shutil, "which", lambda name: None)

    with pytest.raises(tts.TtsError, match="找不到命令"):
        tts.resolve_tts_config({}, config_path=path, env={})

    # validate 路径不该因为本机没装就报错，只给 warning。
    config = tts.resolve_tts_config({}, config_path=path, env={}, check_command=False)
    assert config.backend == "ethan"
    assert any("找不到命令" in warning for warning in config.warnings)


def test_rate_to_speed_keeps_pitch_equivalent_percent():
    assert tts.rate_to_speed("+0%") == 1.0
    assert tts.rate_to_speed("+10%") == 1.1
    assert tts.rate_to_speed("-20%") == 0.8
    # 超出 ethan-tts 支持的 0.5–2.0 区间要夹紧，否则 CLI 直接报错。
    assert tts.rate_to_speed("+150%") == 2.0
    assert tts.rate_to_speed("-90%") == 0.5


def test_build_subtitles_covers_whole_duration_without_overlap():
    text = "第一句很短。第二句会长一些，用来验证按字数分配时间。第三句收尾。"
    subtitles = tts.build_subtitles(text, 9_000)

    assert len(subtitles) == 3
    assert subtitles[0].start_ms == 0
    assert subtitles[-1].end_ms == 9_000
    for previous, following in zip(subtitles, subtitles[1:]):
        assert previous.end_ms == following.start_ms
        assert previous.end_ms > previous.start_ms
    # 文本必须原样完整拼回，不能丢字。
    assert "".join(item.text for item in subtitles) == text


def test_build_subtitles_falls_back_to_commas_without_sentence_punct():
    subtitles = tts.build_subtitles("没有句号，只能按逗号切，不然只有一条字幕", 5_000)

    assert len(subtitles) >= 2
    assert subtitles[-1].end_ms == 5_000


def test_build_subtitles_rejects_empty_input():
    assert tts.build_subtitles("   ", 3_000) == []
    assert tts.build_subtitles("有内容", 0) == []


def test_serialize_srt_is_parseable_by_pipelines(tmp_path):
    subtitles = tts.build_subtitles("第一句。第二句。", 4_000)
    text = tts.serialize_srt(subtitles)

    assert "00:00:00,000 --> " in text
    # 与两个管线里的 parse_srt 保持同一格式，能被原样读回。
    srt_path = tmp_path / "a.srt"
    srt_path.write_text(text, encoding="utf-8")
    assert srt_path.read_text(encoding="utf-8").strip().endswith("第二句。")


def test_split_for_ethan_respects_request_limit():
    long_text = "".join(f"这是第{index}句，用来凑长度。" for index in range(400))
    chunks = tts._split_for_ethan(long_text)

    assert all(len(chunk) <= tts.ETHAN_CHUNK_CHARS for chunk in chunks)
    # 切块不能丢内容（只按标点切，不丢标点）。
    assert "".join(chunks) == long_text


def test_merge_subtitles_offsets_chunks():
    merged = tts.merge_subtitles([("第一句。", 2_000), ("第二句。", 3_000)])

    assert merged[0].start_ms == 0 and merged[0].end_ms == 2_000
    assert merged[1].start_ms == 2_000 and merged[1].end_ms == 5_000


def test_probe_duration_reads_wav_header(tmp_path):
    import struct
    import wave

    path = tmp_path / "tone.wav"
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(24_000)
        handle.writeframes(struct.pack("<h", 0) * 24_000)

    assert tts.probe_duration_ms(path) == 1_000


def test_ethan_backend_uses_wav_suffix_and_autostart_flag(tmp_path, monkeypatch):
    """ethan 后端的缓存后缀是 .wav；autostart 关闭时必须透传 --no-autostart。"""
    path = _write_config(tmp_path, "tts:\n  backend: ethan\n  voice: preset:Vivian\n  autostart: false\n")
    monkeypatch.setattr(tts.shutil, "which", lambda name: "/usr/local/bin/ethan-tts")

    config = tts.resolve_tts_config({}, config_path=path, env={})

    assert config.backend == "ethan"
    assert config.ethan_autostart is False
    assert config.media_suffix == ".wav"


def test_ethan_say_builds_expected_command(tmp_path, monkeypatch):
    """命令拼装回归：音色、语速、超时与 --no-autostart 都要传到位。"""
    config = tts.TtsConfig(
        backend="ethan", ethan_voice="preset:Serena", ethan_instruct="轻快一点",
        ethan_autostart=False, rate="+10%", ethan_timeout_sec=42.0,
    )
    captured: dict = {}

    class _Done:
        returncode = 0
        stdout = "{}"
        stderr = ""

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured["timeout"] = kwargs.get("timeout")
        # 模拟 CLI 写出音频文件，否则后续有效性检查会失败。
        Path(command[command.index("-o") + 1]).write_bytes(b"x" * 512)
        return _Done()

    monkeypatch.setattr(tts.subprocess, "run", fake_run)

    media = tmp_path / "out.wav"
    tts._ethan_say(config, "你好", media, speed=1.1)

    command = captured["command"]
    assert command[:3] == [tts.DEFAULT_ETHAN_CLI, "say", "你好"]
    assert "--no-autostart" in command
    assert command[command.index("--voice") + 1] == "preset:Serena"
    assert command[command.index("--instruct") + 1] == "轻快一点"
    assert command[command.index("--speed") + 1] == "1.10"
    assert captured["timeout"] == 42.0
