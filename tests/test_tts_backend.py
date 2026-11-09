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

    assert config.backend == tts.BACKEND_EDGE
    assert config.source == "default"
    assert config.cache_signature()["name"] == "zh-CN-YunxiNeural"


def test_config_yaml_selects_ethan_and_voice(tmp_path, monkeypatch):
    path = _write_config(
        tmp_path,
        "providers:\n  anthropic:\n    api_key: x\ntts:\n  backend: ethan\n  voice: preset:Serena\n  instruct: 温柔一点\n",
    )
    monkeypatch.setattr(tts.shutil, "which", lambda name: "/usr/local/bin/ethan-tts")

    config = tts.resolve_tts_config({"name": "zh-CN-YunxiNeural"}, config_path=path, env={})

    assert config.backend == tts.BACKEND_ETHAN
    assert config.source == "config"
    assert config.ethan_voice == "preset:Serena"
    assert config.ethan_instruct == "温柔一点"
    # ethan 后端的缓存签名不包含 edge 音色名，但包含本地音色。
    assert config.cache_signature()["voice"] == "preset:Serena"


def test_manifest_backend_overrides_config(tmp_path, monkeypatch):
    path = _write_config(tmp_path, "tts:\n  backend: ethan\n  voice: preset:Vivian\n")
    monkeypatch.setattr(tts.shutil, "which", lambda name: "/usr/local/bin/ethan-tts")

    config = tts.resolve_tts_config({"backend": "edge", "name": "zh-CN-XiaoyiNeural"}, config_path=path, env={})

    assert config.backend == tts.BACKEND_EDGE
    assert config.source == "manifest"


def test_explicit_argument_wins(tmp_path):
    path = _write_config(tmp_path, "tts:\n  backend: ethan\n")
    config = tts.resolve_tts_config({}, backend="edge", config_path=path, env={})

    assert config.backend == tts.BACKEND_EDGE
    assert config.source == "argument"


def test_env_var_is_used_before_default(tmp_path):
    config = tts.resolve_tts_config(
        {}, config_path=tmp_path / "missing.yaml", env={"ETHAN_TTS_BACKEND": "ethan"}
    )

    assert config.backend == tts.BACKEND_ETHAN
    assert config.source == "env"


def test_unknown_backend_warns_and_falls_back_to_edge(tmp_path):
    path = _write_config(tmp_path, "tts:\n  backend: azure\n")

    config = tts.resolve_tts_config({}, config_path=path, env={})

    assert config.backend == tts.BACKEND_EDGE
    assert any("azure" in warning for warning in config.warnings)


def test_missing_ethan_command_fails_fast(tmp_path, monkeypatch):
    path = _write_config(tmp_path, "tts:\n  backend: ethan\n")
    monkeypatch.setattr(tts.shutil, "which", lambda name: None)

    with pytest.raises(tts.TtsError, match="找不到命令"):
        tts.resolve_tts_config({}, config_path=path, env={})

    # validate 路径不该因为本机没装就报错，只给 warning。
    config = tts.resolve_tts_config({}, config_path=path, env={}, check_command=False)
    assert config.backend == tts.BACKEND_ETHAN
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

    assert config.backend == tts.BACKEND_ETHAN
    assert config.ethan_autostart is False
    assert config.media_suffix == ".wav"


def test_ethan_say_builds_expected_command(tmp_path, monkeypatch):
    """命令拼装回归：音色、语速、超时与 --no-autostart 都要传到位。"""
    config = tts.TtsConfig(
        backend=tts.BACKEND_ETHAN, ethan_voice="preset:Serena", ethan_instruct="轻快一点",
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


def test_short_aliases_normalize_to_canonical_names(tmp_path, monkeypatch):
    """`edge` / `ethan` 是兼容别名，但对外一律回显规范名 `edge-tts` / `ethan-tts`。"""
    monkeypatch.setattr(tts.shutil, "which", lambda name: "/usr/local/bin/ethan-tts")

    assert tts.resolve_tts_config({}, backend="edge", config_path=tmp_path / "none.yaml", env={}).backend \
        == tts.BACKEND_EDGE
    assert tts.resolve_tts_config({}, backend="ethan", config_path=tmp_path / "none.yaml", env={}).backend \
        == tts.BACKEND_ETHAN
    # 大小写、下划线、无连字符等写法都要归一到规范名
    for alias in ("EDGE-TTS", "Edge_TTS", "edgetts"):
        assert tts.resolve_tts_config({}, backend=alias, config_path=tmp_path / "none.yaml", env={}).backend \
            == tts.BACKEND_EDGE
    for alias in ("ETHAN-TTS", "Ethan_TTS", "ethantts", "local"):
        assert tts.resolve_tts_config({}, backend=alias, config_path=tmp_path / "none.yaml", env={}).backend \
            == tts.BACKEND_ETHAN


def test_canonical_names_are_the_documented_ones():
    """规范名必须带 -tts 后缀（与包名一致），别被误改回简写。"""
    assert tts.DEFAULT_BACKEND == "edge-tts"
    assert set(tts.BACKENDS) == {"edge-tts", "ethan-tts"}


def test_timeout_zero_falls_back_to_default(tmp_path, monkeypatch):
    """`timeout_sec: 0` 文档承诺「用内置默认」，不能真的把 0 传给 subprocess。"""
    monkeypatch.setattr(tts.shutil, "which", lambda name: "/usr/local/bin/ethan-tts")
    path = _write_config(tmp_path, "tts:\n  backend: ethan-tts\n  timeout_sec: 0\n")

    config = tts.resolve_tts_config({}, config_path=path, env={})

    assert config.ethan_timeout_sec == tts.TtsConfig().ethan_timeout_sec


@pytest.mark.parametrize("raw", ["0", "-5", "abc", ""])
def test_invalid_timeout_falls_back_to_default(tmp_path, monkeypatch, raw):
    monkeypatch.setattr(tts.shutil, "which", lambda name: "/usr/local/bin/ethan-tts")
    path = _write_config(tmp_path, f"tts:\n  backend: ethan-tts\n  timeout_sec: {raw}\n")

    config = tts.resolve_tts_config({}, config_path=path, env={})

    assert config.ethan_timeout_sec == tts.TtsConfig().ethan_timeout_sec


def test_valid_timeout_is_kept(tmp_path, monkeypatch):
    monkeypatch.setattr(tts.shutil, "which", lambda name: "/usr/local/bin/ethan-tts")
    path = _write_config(tmp_path, "tts:\n  backend: ethan-tts\n  timeout_sec: 900\n")

    assert tts.resolve_tts_config({}, config_path=path, env={}).ethan_timeout_sec == 900.0


def test_config_rate_overrides_manifest(tmp_path, monkeypatch):
    """config.yaml 的 tts.rate 要压过 manifest 的 voice.rate。

    定时任务每次由模型生成 manifest，几乎总带 `"rate": "-5%"`。若让 manifest
    优先，用户在 config 里设的语速会被静默吃掉（和「配了 tts 段没生效」同类）。
    """
    monkeypatch.setattr(tts.shutil, "which", lambda name: "/usr/local/bin/ethan-tts")
    path = _write_config(tmp_path, "tts:\n  backend: ethan-tts\n  rate: +10%\n")

    config = tts.resolve_tts_config({"rate": "-5%"}, config_path=path, env={})

    assert config.rate == "+10%"
    assert config.rate_from_config is True
    assert tts.rate_to_speed(config.rate) == 1.1


def test_manifest_rate_used_when_config_absent(tmp_path, monkeypatch):
    monkeypatch.setattr(tts.shutil, "which", lambda name: "/usr/local/bin/ethan-tts")
    path = _write_config(tmp_path, "tts:\n  backend: ethan-tts\n")

    config = tts.resolve_tts_config({"rate": "-5%"}, config_path=path, env={})

    assert config.rate == "-5%"
    assert config.rate_from_config is False


def test_explicit_rate_argument_wins(tmp_path, monkeypatch):
    """--rate 是最高优先级，用于单次覆盖全局配置。"""
    monkeypatch.setattr(tts.shutil, "which", lambda name: "/usr/local/bin/ethan-tts")
    path = _write_config(tmp_path, "tts:\n  backend: ethan-tts\n  rate: +10%\n")

    config = tts.resolve_tts_config({"rate": "-5%"}, rate="+20%", config_path=path, env={})

    assert config.rate == "+20%"


def test_rate_defaults_to_zero_percent(tmp_path, monkeypatch):
    monkeypatch.setattr(tts.shutil, "which", lambda name: "/usr/local/bin/ethan-tts")
    path = _write_config(tmp_path, "tts:\n  backend: ethan-tts\n")

    assert tts.resolve_tts_config({}, config_path=path, env={}).rate == "+0%"


def test_concat_wavs_handles_tmp_target(tmp_path):
    """拼接目标常以 .tmp 结尾（管线先写临时文件再原子 replace），必须能成功。

    回归背景：ffmpeg 靠扩展名推断容器，`.tmp` 结尾直接报
    "Unable to choose an output format"。这个 bug 只在单节文本超过
    ETHAN_CHUNK_CHARS、需要分块拼接时触发——短文本走不到，所以测试也没覆盖，
    结果今早定时任务（每节 400–500 字）整条降级成了 edge-tts。
    """
    import shutil
    import subprocess

    if shutil.which("ffmpeg") is None:
        pytest.skip("需要 ffmpeg")

    parts = []
    for index in (1, 2):
        part = tmp_path / f"part{index}.wav"
        subprocess.run(
            ["ffmpeg", "-y", "-v", "error", "-f", "lavfi",
             "-i", "sine=frequency=440:duration=0.3", "-ar", "24000", "-ac", "1",
             "-c:a", "pcm_s16le", str(part)],
            check=True, capture_output=True,
        )
        parts.append(part)

    target = tmp_path / "merged.wav.tmp"  # 关键：.tmp 结尾
    tts._concat_wavs(parts, target, tmp_path)

    assert target.is_file() and target.stat().st_size > 1000
    # 拼接后应接近两段之和（0.6s）
    assert tts.probe_duration_ms(target) >= 500


def test_chunk_size_keeps_single_call_under_timeout():
    """分块大小 × 本地推理速度必须远离 CLI 超时线。

    回归背景：块大小 300 字、克隆音色约 0.4s/字 → 单块 120s；再叠上并发排队，
    实测单次调用顶到 300s 超时，重试整块重来，11 分钟才出 3 节。
    """
    config = tts.TtsConfig()
    # 克隆音色实测约 0.4s/字（236 字 ≈ 94s），留 1.5 倍安全系数
    estimated_seconds = tts.ETHAN_CHUNK_CHARS * 0.4 * 1.5
    assert estimated_seconds < config.ethan_timeout_sec, (
        f"分块 {tts.ETHAN_CHUNK_CHARS} 字预计耗时 {estimated_seconds:.0f}s，"
        f"已逼近或超过超时 {config.ethan_timeout_sec:.0f}s"
    )


def test_concurrency_is_bounded():
    """并发上限必须有限：服务端是串行队列，无限并发只会让排队无限长。"""
    import importlib.util
    import sys

    script = (
        Path(__file__).parents[1]
        / "ethan" / "defaults" / "skills" / "book-audio-digest" / "scripts" / "audio_pipeline.py"
    )
    spec = importlib.util.spec_from_file_location("audio_pipeline_conc", script)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)

    assert 1 <= module.ETHAN_CONCURRENCY <= 5, (
        "并发过高会让排队长度随节数线性增长；过低则喂不满服务端"
    )
