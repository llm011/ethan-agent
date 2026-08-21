import importlib.util
import json
import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = (
    Path(__file__).parents[1]
    / "ethan"
    / "defaults"
    / "skills"
    / "article-to-video"
    / "scripts"
)


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS_DIR / f"{name}.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


h3 = _load("h3_presenter_pipeline")
seedance = _load("seedance_presenter_pipeline")


# ── config 解析 ────────────────────────────────────────────────────────────


def test_parse_seedance_section_handles_flat_keys_models_and_comments():
    text = "\n".join(
        [
            "providers:",
            "  anthropic:",
            "    api_key: sk-old",
            "seedance:",
            "  gateway_url: https://gw.example.com/v1   # staging",
            "  api_key: 'abc123'",
            '  edge_secret: "xyz"',
            "  resolution: \"1080p\"",
            "  generate_audio: false",
            "  models:",
            "    video: ep-1",
            "    video_fast: ep-2",
            "other:",
            "  key: value",
        ]
    )
    section = seedance.parse_seedance_section(text)
    assert section["gateway_url"] == "https://gw.example.com/v1"
    assert section["api_key"] == "abc123"
    assert section["edge_secret"] == "xyz"
    assert section["models"]["video"] == "ep-1"
    assert section["models"]["video_fast"] == "ep-2"
    assert "other" not in section  # 离开 seedance 段即停


def test_load_gateway_config_env_overrides_and_missing(tmp_path):
    config = tmp_path / "config.yaml"
    config.write_text(
        "seedance:\n  gateway_url: https://gw.example.com/v1/\n  api_key: from-file\n"
        "  edge_secret: from-file\n  models:\n    video: ep-1\n",
        encoding="utf-8",
    )
    loaded = seedance.load_gateway_config(config)
    assert loaded is not None and loaded.is_complete()
    assert loaded.gateway_url == "https://gw.example.com/v1"  # 去尾部斜杠

    monkey = pytest.MonkeyPatch()
    monkey.setenv("SEEDANCE_API_KEY", "from-env")
    try:
        loaded = seedance.load_gateway_config(config)
        assert loaded.api_key == "from-env"  # 环境变量优先
    finally:
        monkey.undo()

    empty = tmp_path / "missing.yaml"
    assert seedance.load_gateway_config(empty) is None


def test_resolution_for_downgrades_720p_only_models():
    config = seedance.GatewayConfig(
        gateway_url="https://gw", api_key="k", edge_secret="s",
        models={"video": "ep-1", "video_fast": "ep-2"}, resolution="1080p",
    )
    assert config.resolution_for("video") == "1080p"
    assert config.resolution_for("video_fast") == "720p"
    with pytest.raises(seedance.PipelineError):
        config.model_endpoint("video_mini")


# ── 模式优先级 ─────────────────────────────────────────────────────────────


def test_resolve_mode_priority_seedance_over_h3_over_static(monkeypatch, tmp_path):
    config_file = tmp_path / "config.yaml"
    monkeypatch.setattr(seedance, "config_yaml_path", lambda: config_file)
    monkeypatch.setattr(seedance, "_h3_configured", lambda: False)
    assert seedance.resolve_mode()[0] == "static"

    monkeypatch.setattr(seedance, "_h3_configured", lambda: True)
    assert seedance.resolve_mode()[0] == "h3"

    config_file.write_text(
        "seedance:\n  gateway_url: https://gw\n  api_key: k\n  edge_secret: s\n"
        "  models:\n    video: ep-1\n",
        encoding="utf-8",
    )
    assert seedance.resolve_mode() == ("seedance", "config.yaml seedance 段完整，优先级高于 h3")


def test_resolve_mode_prefer_wins_and_errors_when_unconfigured(monkeypatch, tmp_path):
    monkeypatch.setattr(seedance, "config_yaml_path", lambda: tmp_path / "none.yaml")
    monkeypatch.setattr(seedance, "_h3_configured", lambda: True)
    assert seedance.resolve_mode("h3")[0] == "h3"
    assert seedance.resolve_mode("static")[0] == "static"
    with pytest.raises(seedance.PipelineError):
        seedance.resolve_mode("seedance")  # 指定但未配置 → 报错不回退
    with pytest.raises(seedance.PipelineError):
        seedance.resolve_mode("bogus")


# ── prompt 构建 ────────────────────────────────────────────────────────────


PRESENTER = {"id": None, "name": "Xiaoyu", "description": "silver-white long hair, blue eyes, business suit"}


def test_prompt_uses_seedance_format_not_h3_format():
    prompt = seedance.build_seedance_prompt(
        dialogue="快手股价突破新高。", presenter=PRESENTER, emotion="positive",
    )
    assert "参考图片1即首帧" in prompt
    assert "台词：{快手股价突破新高。}" in prompt  # { } = 台词（Seedance 括号语义）
    assert "请勿生成字幕" in prompt and "水印" in prompt  # 约束收尾
    assert "<Picture 1>" not in prompt  # 不再是 H3 的文内引用格式
    assert len(prompt) <= 500


def test_prompt_emotion_profiles_and_compact_fallback():
    positive = seedance.build_seedance_prompt(
        dialogue="涨", presenter=PRESENTER, emotion="positive"
    )
    negative = seedance.build_seedance_prompt(
        dialogue="跌", presenter=PRESENTER, emotion="negative"
    )
    assert "自信昂扬" in positive
    assert "沉稳关切" in negative

    long_dialogue = "风险" * 300  # 超长台词触发紧凑模板 + 截断
    compact = seedance.build_seedance_prompt(
        dialogue=long_dialogue, presenter=PRESENTER, emotion="neutral"
    )
    assert len(compact) <= 500
    assert "台词：{" in compact  # 紧凑模板仍保留台词段

    with pytest.raises(seedance.PipelineError):
        seedance.build_seedance_prompt(dialogue="  ", presenter=PRESENTER)


def test_prompt_generate_audio_toggle():
    silent = seedance.build_seedance_prompt(dialogue="测试", presenter=PRESENTER, generate_audio=False)
    voiced = seedance.build_seedance_prompt(dialogue="测试", presenter=PRESENTER, generate_audio=True)
    assert "声音：" not in silent  # 无声模式不带音频指令
    assert "声音：" in voiced and "(轻柔电子氛围垫乐" in voiced


def test_detect_emotion_keywords():
    assert seedance.detect_emotion("股价突破新高，盈利放大") == "positive"
    assert seedance.detect_emotion("注意风险，业绩下滑") == "negative"
    assert seedance.detect_emotion("今天介绍一个模型") == "neutral"
    assert seedance.detect_emotion("涨了但也跌了") == "neutral"  # 平手中性


def test_ratio_and_requested_duration():
    assert seedance._ratio_key(1080, 1920) == "9:16"
    assert seedance._ratio_key(1920, 1080) == "16:9"
    assert seedance._ratio_key(1000, 1000) == "1:1"
    assert seedance._requested_duration(4.0) == 4
    assert seedance._requested_duration(6.1) == 7  # 向上取整覆盖场景时长
    assert seedance._requested_duration(15.0) == 15
    for bad in (3.9, 15.1):
        with pytest.raises(seedance.PipelineError):
            seedance._requested_duration(bad)


# ── prepare ────────────────────────────────────────────────────────────────


PNG_1PX = bytes.fromhex(
    "89504e470d0a1a0a0000000d494844520000000100000001080600000"
    "01f15c4890000000d49444154789c626001000000ffff030000060005"
    "57bfabd40000000049454e44ae426082"
)


def _fake_probe(monkeypatch, width=1080, height=1920, duration=8.0, fps="30/1", audio=False):
    def probe(path, **kwargs):
        return h3.MediaInfo(str(path), width, height, duration_seconds=duration, fps=fps, has_audio=audio)

    monkeypatch.setattr(h3, "probe_media", probe)


def test_prepare_scene_writes_prompt_and_metadata(monkeypatch, tmp_path):
    (tmp_path / "ref.png").write_bytes(PNG_1PX)
    _fake_probe(monkeypatch)
    config = seedance.GatewayConfig(
        gateway_url="https://gw", api_key="k", edge_secret="s",
        models={"video": "ep-video"}, resolution="1080p", generate_audio=False,
    )
    monkeypatch.setattr(seedance, "load_gateway_config", lambda path=None: config)

    result = seedance.prepare_scene(
        scene_dir=tmp_path / "scene",
        combined_reference=tmp_path / "ref.png",
        dialogue="快手股价突破新高。",
        duration_seconds=6.4,
        start_seconds=12.0,
    )
    scene_dir = tmp_path / "scene"
    metadata = json.loads((scene_dir / "scene.json").read_text(encoding="utf-8"))
    assert metadata["provider"] == "seedance"
    assert metadata["requestedDuration"] == 7  # ceil(6.4)
    assert metadata["ratio"] == "9:16"
    assert metadata["startSeconds"] == 12.0
    assert metadata["emotion"] == "positive"
    assert metadata["seedance"]["model"] == "ep-video"
    assert (scene_dir / "seedance-prompt.txt").is_file()
    assert (scene_dir / "references" / "combined-reference.png").is_file()
    assert metadata["references"]["cleanPlate"] is None  # clean-plate 可选

    for bad_duration in (3.0, 16.0):
        with pytest.raises(seedance.PipelineError):
            seedance.prepare_scene(
                scene_dir=tmp_path / "s2", combined_reference=tmp_path / "ref.png",
                dialogue="x" * 10, duration_seconds=bad_duration,
            )
    with pytest.raises(seedance.PipelineError):
        seedance.prepare_scene(
            scene_dir=tmp_path / "s3", combined_reference=tmp_path / "ref.png",
            dialogue="正常台词", duration_seconds=6.0, start_seconds=-1,
        )


# ── submit / poll ──────────────────────────────────────────────────────────


def _prepared_scene(tmp_path, monkeypatch):
    (tmp_path / "ref.png").write_bytes(PNG_1PX)
    _fake_probe(monkeypatch)
    config = seedance.GatewayConfig(
        gateway_url="https://gw", api_key="k", edge_secret="s",
        models={"video": "ep-video"}, resolution="1080p",
    )
    monkeypatch.setattr(seedance, "load_gateway_config", lambda path=None: config)
    seedance.prepare_scene(
        scene_dir=tmp_path / "scene", combined_reference=tmp_path / "ref.png",
        dialogue="测试台词", duration_seconds=5.0, start_seconds=3.0,
    )
    return tmp_path / "scene"


def test_submit_builds_i2v_payload_and_dry_run_hides_image(tmp_path, monkeypatch):
    scene_dir = _prepared_scene(tmp_path, monkeypatch)
    result = seedance.submit_task(scene_dir=scene_dir, dry_run=True)
    payload = result["payload"]
    assert payload["model"] == "ep-video"
    assert payload["duration"] == 5
    # content 顺序硬性要求：text → image_url；首帧带 role
    assert payload["content"][0]["type"] == "text"
    assert payload["content"][1]["type"] == "image_url"
    assert payload["content"][1]["role"] == "first_frame"
    assert "omitted" in payload["content"][1]["image_url"]["url"]  # dry-run 隐藏 base64
    assert payload["watermark"] is False
    # 真实传输走 base64 data URI（官方支持，无需公网托管）
    first_frame = Path(
        json.loads((scene_dir / "scene.json").read_text(encoding="utf-8"))["references"]["firstFrame"]
    )
    transport, value = seedance._image_transport(first_frame, None)
    assert transport == "base64" and value.startswith("data:image/png;base64,")


def test_submit_stores_task_id_in_scene(tmp_path, monkeypatch):
    scene_dir = _prepared_scene(tmp_path, monkeypatch)

    def fake_http(config, method, path, payload=None, timeout=60):
        assert method == "POST" and path == "/contents/generations/tasks"
        return {"id": "task-123"}

    monkeypatch.setattr(seedance, "_http_json", fake_http)
    result = seedance.submit_task(scene_dir=scene_dir)
    assert result["taskId"] == "task-123"
    metadata = json.loads((scene_dir / "scene.json").read_text(encoding="utf-8"))
    assert metadata["seedance"]["taskId"] == "task-123"
    assert metadata["seedance"]["status"] == "submitted"
    # 请求留档不含 base64 图片数据
    trace = json.loads((scene_dir / "seedance-request.json").read_text(encoding="utf-8"))
    assert "omitted" in trace["content"][1]["image_url"]["url"]


def test_submit_rejects_bad_image_url(tmp_path, monkeypatch):
    scene_dir = _prepared_scene(tmp_path, monkeypatch)
    with pytest.raises(seedance.PipelineError):
        seedance.submit_task(scene_dir=scene_dir, image_url="ftp://example.com/x.png")


def test_poll_terminal_mapping_and_download(tmp_path, monkeypatch):
    scene_dir = _prepared_scene(tmp_path, monkeypatch)
    monkeypatch.setattr(seedance, "_http_json", lambda *a, **k: {"id": "t1", "status": "queued"})
    metadata = json.loads((scene_dir / "scene.json").read_text(encoding="utf-8"))
    metadata["seedance"]["taskId"] = "t1"
    h3._write_text_atomic(
        scene_dir / "scene.json", json.dumps(metadata, ensure_ascii=False, indent=2) + "\n"
    )

    states = iter(
        [
            {"data": {"status": "running"}},
            {"data": {"status": "succeeded", "content": {"video_url": "https://cdn/x.mp4"}}},
        ]
    )
    monkeypatch.setattr(seedance, "_http_json", lambda *a, **k: next(states))
    monkeypatch.setattr(seedance.time, "sleep", lambda seconds: None)

    def fake_download(url, destination, timeout=600):
        destination.write_bytes(PNG_1PX)  # 内容无所谓，probe 已被 fake

    monkeypatch.setattr(seedance, "_download", fake_download)
    result = seedance.poll_task(scene_dir=scene_dir, timeout_seconds=5)
    assert result["status"] == "ok"
    assert result["taskId"] == "t1"

    # 失败终态直接报错
    monkeypatch.setattr(seedance, "_http_json", lambda *a, **k: {"data": {"status": "failed", "error": "boom"}})
    with pytest.raises(seedance.PipelineError, match="boom"):
        seedance.poll_task(scene_dir=scene_dir, timeout_seconds=5)


def test_poll_requires_task_id(tmp_path, monkeypatch):
    scene_dir = _prepared_scene(tmp_path, monkeypatch)
    with pytest.raises(seedance.PipelineError, match="taskId"):
        seedance.poll_task(scene_dir=scene_dir)


# ── compose ────────────────────────────────────────────────────────────────


def test_compose_builds_splice_command_and_verifies(monkeypatch, tmp_path):
    scene_dir = _prepared_scene(tmp_path, monkeypatch)
    raw = scene_dir / "raw-seedance.mp4"
    raw.write_bytes(b"fake")
    stage = tmp_path / "final.mp4"
    stage.write_bytes(b"fake")

    probes = {
        str(stage): h3.MediaInfo(str(stage), 1080, 1920, duration_seconds=60.0, fps="30/1", has_audio=True),
        str(raw): h3.MediaInfo(str(raw), 720, 1280, duration_seconds=5.4, fps="24/1", has_audio=False),
    }

    def probe(path, **kwargs):
        return probes[str(path)]

    monkeypatch.setattr(h3, "probe_media", probe)

    output = tmp_path / "out.mp4"
    probes[str(output)] = h3.MediaInfo(str(output), 1080, 1920, duration_seconds=60.0, fps="30/1", has_audio=True)

    commands = []

    def fake_run(command, **kwargs):
        commands.append(command)
        return subprocess_result()

    monkeypatch.setattr(h3, "_run", fake_run)
    report = seedance.compose_scene(scene_dir=scene_dir, stage_video=stage, output=output)
    assert report["mode"] == "scene-splice"
    assert report["window"] == {"startSeconds": 3.0, "durationSeconds": 5.0}

    cmd = commands[0]
    graph = cmd[cmd.index("-filter_complex") + 1]
    # 场景窗口 [3, 8)：前段 3s + 生成段 5s + 后段自 8s 起；段内对齐原片 fps/尺寸/时长
    assert "trim=duration=3.000" in graph
    assert "trim=start=8.000" in graph
    assert "fps=30/1" in graph
    assert "scale=1080:1920" in graph
    assert "trim=duration=5.000" in graph
    assert "concat=n=3" in graph
    # 音轨整体沿用原片
    assert "0:a?" in cmd
    assert (tmp_path / "out.composition.json").is_file()


def subprocess_result():
    import subprocess as _subprocess

    return _subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")


def test_compose_rejects_window_beyond_stage(monkeypatch, tmp_path):
    scene_dir = _prepared_scene(tmp_path, monkeypatch)
    (scene_dir / "raw-seedance.mp4").write_bytes(b"fake")
    stage = tmp_path / "final.mp4"
    stage.write_bytes(b"fake")
    monkeypatch.setattr(
        h3, "probe_media",
        lambda path, **kw: h3.MediaInfo(str(path), 1080, 1920, duration_seconds=4.0, fps="30/1", has_audio=True),
    )
    with pytest.raises(seedance.PipelineError, match="超出成片时长"):
        seedance.compose_scene(scene_dir=scene_dir, stage_video=stage, output=tmp_path / "o.mp4")


def test_compose_head_scene_omits_pre_segment(monkeypatch, tmp_path):
    scene_dir = _prepared_scene(tmp_path, monkeypatch)  # start=3.0 → 改成 0
    metadata = json.loads((scene_dir / "scene.json").read_text(encoding="utf-8"))
    metadata["startSeconds"] = 0.0
    h3._write_text_atomic(
        scene_dir / "scene.json", json.dumps(metadata, ensure_ascii=False, indent=2) + "\n"
    )
    (scene_dir / "raw-seedance.mp4").write_bytes(b"fake")
    stage = tmp_path / "final.mp4"
    stage.write_bytes(b"fake")
    # 场景窗口 [0,5)，成片恰 5s → 只有 [seg]，无 pre/post
    monkeypatch.setattr(
        h3, "probe_media",
        lambda path, **kw: h3.MediaInfo(str(path), 1080, 1920, duration_seconds=5.0, fps="30/1", has_audio=True),
    )
    monkeypatch.setattr(h3, "_run", lambda command, **kw: subprocess_result())
    seedance.compose_scene(scene_dir=scene_dir, stage_video=stage, output=tmp_path / "o.mp4")


def test_load_scene_rejects_non_seedance_package(tmp_path):
    (tmp_path / "scene.json").write_text('{"provider": "h3"}', encoding="utf-8")
    with pytest.raises(seedance.PipelineError, match="seedance"):
        seedance._load_scene(tmp_path)
    (tmp_path / "scene.json").unlink()
    with pytest.raises(seedance.PipelineError):  # scene.json 缺失
        seedance._load_scene(tmp_path)


# ── 瞬态错误分类与 poll 重试 ────────────────────────────────────────────────


def _http_error(code: int):
    import urllib.error

    return urllib.error.HTTPError(
        url="https://gw/x", code=code, msg="err", hdrs=None, fp=None
    )


def test_http_json_classifies_transient_and_permanent(monkeypatch):
    import urllib.error

    config = seedance.GatewayConfig(
        gateway_url="https://gw", api_key="k", edge_secret="s", models={"video": "ep"}
    )

    def fake_urlopen_raising(exc):
        def urlopen(request, timeout=None):
            raise exc

        return urlopen

    # 5xx / 429 / 网络不可达 → 瞬态（可重试）
    for exc in (_http_error(502), _http_error(429),
                urllib.error.URLError("connection reset")):
        monkeypatch.setattr(
            seedance.urllib.request, "urlopen", fake_urlopen_raising(exc)
        )
        with pytest.raises(seedance.TransientGatewayError):
            seedance._http_json(config, "GET", "/x")
    # 4xx 永久错误 → 普通 PipelineError
    monkeypatch.setattr(
        seedance.urllib.request, "urlopen", fake_urlopen_raising(_http_error(401))
    )
    with pytest.raises(seedance.PipelineError) as excinfo:
        seedance._http_json(config, "GET", "/x")
    assert not isinstance(excinfo.value, seedance.TransientGatewayError)


def test_poll_retries_transient_then_succeeds(tmp_path, monkeypatch):
    scene_dir = _prepared_scene(tmp_path, monkeypatch)
    metadata = json.loads((scene_dir / "scene.json").read_text(encoding="utf-8"))
    metadata["seedance"]["taskId"] = "t-retry"
    h3._write_text_atomic(
        scene_dir / "scene.json", json.dumps(metadata, ensure_ascii=False, indent=2) + "\n"
    )

    calls = iter(
        [
            seedance.TransientGatewayError("cannot reach gateway: reset"),
            seedance.TransientGatewayError("gateway HTTP 502 on GET /x: bad gw"),
            {"data": {"status": "succeeded", "content": {"video_url": "https://cdn/x.mp4"}}},
        ]
    )

    def fake_http(config, method, path, payload=None, timeout=60):
        first = next(calls)
        if isinstance(first, Exception):
            raise first
        return first

    monkeypatch.setattr(seedance, "_http_json", fake_http)
    monkeypatch.setattr(seedance.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(
        seedance, "_download", lambda url, destination, timeout=600: destination.write_bytes(PNG_1PX)
    )
    result = seedance.poll_task(scene_dir=scene_dir, timeout_seconds=30)
    assert result["status"] == "ok"  # 抖动两次后成功，任务没有作废


def test_poll_transient_error_aborts_at_deadline(tmp_path, monkeypatch):
    scene_dir = _prepared_scene(tmp_path, monkeypatch)
    metadata = json.loads((scene_dir / "scene.json").read_text(encoding="utf-8"))
    metadata["seedance"]["taskId"] = "t-dead"
    h3._write_text_atomic(
        scene_dir / "scene.json", json.dumps(metadata, ensure_ascii=False, indent=2) + "\n"
    )
    monkeypatch.setattr(
        seedance, "_http_json",
        lambda *a, **k: (_ for _ in ()).throw(seedance.TransientGatewayError("down")),
    )
    monkeypatch.setattr(seedance.time, "sleep", lambda seconds: None)
    # 递增时钟：deadline=5，下一次读数 5 → 到点放弃（恒定假时钟会死循环）
    ticks = iter(range(0, 100, 5))
    monkeypatch.setattr(seedance.time, "monotonic", lambda: next(ticks))
    with pytest.raises(seedance.PipelineError, match="持续不可用"):
        seedance.poll_task(scene_dir=scene_dir, timeout_seconds=5)


# ── 图片格式嗅探（#4：不信任文件后缀） ─────────────────────────────────────


JPEG_1PX = bytes.fromhex("ffd8ffe000104a46494600010100000100010000ffd9")


def test_sniff_image_detects_real_format(tmp_path):
    jpg_named_png = tmp_path / "ref.png"
    jpg_named_png.write_bytes(JPEG_1PX)
    assert seedance._sniff_image(jpg_named_png) == ("jpg", "jpeg")
    png = tmp_path / "real.png"
    png.write_bytes(PNG_1PX)
    assert seedance._sniff_image(png) == ("png", "png")
    bogus = tmp_path / "bogus.png"
    bogus.write_bytes(b"not an image at all")
    with pytest.raises(seedance.PipelineError, match="图片格式"):
        seedance._sniff_image(bogus)


def test_prepare_stores_jpeg_reference_with_real_extension(monkeypatch, tmp_path):
    (tmp_path / "ref.png").write_bytes(JPEG_1PX)  # jpg 字节流顶着 png 名字
    _fake_probe(monkeypatch)
    config = seedance.GatewayConfig(
        gateway_url="https://gw", api_key="k", edge_secret="s",
        models={"video": "ep-video"}, resolution="1080p",
    )
    monkeypatch.setattr(seedance, "load_gateway_config", lambda path=None: config)
    seedance.prepare_scene(
        scene_dir=tmp_path / "scene", combined_reference=tmp_path / "ref.png",
        dialogue="测试台词", duration_seconds=5.0,
    )
    scene_dir = tmp_path / "scene"
    metadata = json.loads((scene_dir / "scene.json").read_text(encoding="utf-8"))
    stored = Path(metadata["references"]["firstFrame"])
    assert stored.name == "combined-reference.jpg"
    # base64 传输按真实 mime 编码，不会再出现 jpg→data:image/png
    transport, value = seedance._image_transport(stored, None)
    assert transport == "base64" and value.startswith("data:image/jpeg;base64,")


# ── splice filter 与 dry-run ────────────────────────────────────────────────


def test_splice_filter_normalizes_pixel_format():
    graph = seedance._splice_filter(3.0, 5.0, 60.0, 1080, 1920, "30/1")
    # 三段链尾都归一 yuv420p：Seedance 可能返回 10bit，直接 concat 会格式不匹配
    assert graph.count("format=yuv420p") == 3
    head_graph = seedance._splice_filter(0.0, 5.0, 5.0, 1080, 1920, "30/1")
    assert head_graph.count("format=yuv420p") == 1  # 只有 [seg]


def test_submit_dry_run_skips_base64_encoding(tmp_path, monkeypatch):
    scene_dir = _prepared_scene(tmp_path, monkeypatch)

    def fail_transport(*args, **kwargs):
        raise AssertionError("dry-run 不应读取/编码整图")

    monkeypatch.setattr(seedance, "_image_transport", fail_transport)
    result = seedance.submit_task(scene_dir=scene_dir, dry_run=True)
    assert result["status"] == "dry-run"
    assert "omitted" in result["payload"]["content"][1]["image_url"]["url"]
