#!/usr/bin/env python3
"""Pluggable TTS backend shared by the media skills (article-to-video / book-audio-digest).

Historically both pipelines hardcoded `edge-tts` (an online service). This module
keeps that as the default and adds a locally installed `ethan-tts` CLI
(Qwen3-TTS on Apple Silicon) as an alternative, chosen by configuration.

Selection (first match wins):

1. `--backend` CLI argument / explicit `backend=` parameter
2. `voice.backend` in the manifest
3. `tts.backend` in `~/.ethan/config.yaml` (`ETHAN_DATA_DIR` respected)
4. `ETHAN_TTS_BACKEND` environment variable
5. `edge`

Contract: `synthesize(text, config, media_path, srt_path)` writes one media file
and one non-empty SRT next to it. The pipelines keep their content-hash cache,
retry and atomic-publish discipline; only the synthesis call is delegated here.

Difference between backends: edge-tts reports real WordBoundary events, so its
SRT is exact. ethan-tts returns audio only, so its SRT is derived by splitting
the known narration sentences proportionally across the measured audio duration.

Standalone by design: only the stdlib is imported at module load, so the
pipelines keep running via `uv run --isolated --no-project`.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import wave
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# 规范名带 -tts 后缀，与包名一致（`pip install edge-tts` / `ethan-tts` CLI）。
# `edge` / `ethan` 作为简写别名继续接受，但落盘与回显一律用规范名。
BACKEND_EDGE = "edge-tts"
BACKEND_ETHAN = "ethan-tts"
DEFAULT_BACKEND = BACKEND_EDGE
BACKENDS = (BACKEND_EDGE, BACKEND_ETHAN)
CONFIG_SECTION = "tts"
ENV_BACKEND = "ETHAN_TTS_BACKEND"
ENV_DATA_DIR = "ETHAN_DATA_DIR"
DEFAULT_ETHAN_CLI = "ethan-tts"
DEFAULT_ETHAN_VOICE = "preset:Vivian"
MIN_AUDIO_BYTES = 256
# ethan-tts 服务端单次请求上限 2000 字（settings.max_chars）；长旁白按句切块后拼接。
# 切块不宜过大：本地推理是串行的，一次塞 1000+ 字会让单次调用跑几十秒，中途失败
# 整段重来；按 3–4 句一块，进度可回显、重试代价也小。
ETHAN_CHUNK_CHARS = 300


class TtsError(RuntimeError):
    """A recoverable synthesis error (retriable by the caller)."""


@dataclass(frozen=True)
class Subtitle:
    text: str
    start_ms: int
    end_ms: int


@dataclass(frozen=True)
class TtsConfig:
    backend: str = DEFAULT_BACKEND
    # ethan-tts 相关
    ethan_command: str = DEFAULT_ETHAN_CLI
    ethan_voice: str = DEFAULT_ETHAN_VOICE
    ethan_base_url: str = ""
    ethan_instruct: str = ""
    ethan_timeout_sec: float = 300.0
    # CLI 默认会在服务没跑时后台拉起；关掉它适合"我只连远端实例"的场景。
    ethan_autostart: bool = True
    # edge-tts 音色参数（ethan 后端只沿用 rate 换算成语速倍率）
    voice_name: str = ""
    rate: str = "+0%"
    volume: str = "+0%"
    pitch: str = "+0Hz"
    source: str = "default"
    # rate 是否来自 config.yaml（而非 manifest）；诊断"改了配置没生效"时用得上。
    rate_from_config: bool = False
    warnings: list[str] = field(default_factory=list)

    def cache_signature(self) -> dict[str, Any]:
        """进缓存键的稳定签名：换后端/换音色必须重合成，不能复用旧音频。"""
        if self.backend == BACKEND_ETHAN:
            return {
                "backend": BACKEND_ETHAN,
                "voice": self.ethan_voice,
                "instruct": self.ethan_instruct,
                "rate": self.rate,
                "base_url": self.ethan_base_url,
            }
        return {
            "backend": BACKEND_EDGE,
            "name": self.voice_name,
            "rate": self.rate,
            "volume": self.volume,
            "pitch": self.pitch,
        }

    def describe(self) -> str:
        if self.backend == BACKEND_ETHAN:
            return f"ethan-tts（{self.ethan_voice}）"
        return f"edge-tts（{self.voice_name}）"

    @property
    def media_suffix(self) -> str:
        return ".wav" if self.backend == BACKEND_ETHAN else ".mp3"


# ---------------------------------------------------------------------------
# 配置解析：manifest > config.yaml > 环境变量 > 内置默认
# ---------------------------------------------------------------------------


def config_yaml_path() -> Path:
    data_dir = os.environ.get(ENV_DATA_DIR)
    base = Path(data_dir).expanduser() if data_dir else Path.home() / ".ethan"
    return base / "config.yaml"


def _strip_yaml_value(raw: str) -> str:
    value = raw.strip()
    if " #" in value:  # 去掉行内注释（引号外裸值场景够用）
        value = value.split(" #", 1)[0].rstrip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        value = value[1:-1]
    return value.strip()


def parse_tts_section(text: str) -> dict[str, str]:
    """极简解析 config.yaml 顶层 tts: 段（只支持一层 key: value）。

    独立脚本不能依赖 PyYAML；其他段落原样跳过，缩进异常直接忽略，
    解析不出的字段回落到默认值，不让配置问题阻断合成。
    """
    section: dict[str, str] = {}
    in_section = False
    section_indent = 0
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        indent = len(line) - len(line.lstrip(" "))
        stripped = line.strip()
        if not in_section:
            if stripped == f"{CONFIG_SECTION}:":
                in_section, section_indent = True, indent
            continue
        if indent <= section_indent:  # 离开 tts 段
            break
        key, sep, rest = stripped.partition(":")
        if not sep:
            continue
        key, rest = key.strip(), rest.strip()
        if key and rest:
            section[key] = _strip_yaml_value(rest)
    return section


def load_tts_section(path: Path | None = None) -> dict[str, str]:
    path = path or config_yaml_path()
    try:
        return parse_tts_section(path.read_text(encoding="utf-8"))
    except OSError:
        return {}


_BACKEND_ALIASES = {
    # 规范名
    "edge-tts": BACKEND_EDGE,
    "ethan-tts": BACKEND_ETHAN,
    # 简写/历史写法，继续接受
    "edge": BACKEND_EDGE,
    "edgetts": BACKEND_EDGE,
    "ethan": BACKEND_ETHAN,
    "ethantts": BACKEND_ETHAN,
    "local": BACKEND_ETHAN,
}


def _parse_bool(value: Any, *, default: bool) -> bool:
    if value is None or value == "":
        return default
    return str(value).strip().lower() not in {"0", "false", "no", "off"}


def _normalize_backend(value: str, *, origin: str, warnings: list[str]) -> str | None:
    normalized = value.strip().lower().replace("_", "-")
    resolved = _BACKEND_ALIASES.get(normalized)
    if resolved is None:
        warnings.append(
            f"未知的 TTS 后端 {value!r}（来自 {origin}），已忽略；可选 {' / '.join(BACKENDS)}"
        )
    return resolved


def _parse_timeout(value: Any, *, default: float = 300.0, warnings: list[str] | None = None) -> float:
    """解析单次合成超时秒数；0、负数、非数字一律回落到默认值。

    极简 YAML 解析器不转类型，`timeout_sec: 0` 拿到的是字符串 "0"（truthy），
    直接 float() 会得到 0.0 —— 传给 subprocess 会让每次合成立刻 TimeoutExpired。
    文档承诺「0 = 用内置默认」，这里兜住。
    """
    if value is None or value == "":
        return default
    try:
        seconds = float(str(value).strip())
    except (TypeError, ValueError):
        if warnings is not None:
            warnings.append(f"tts.timeout_sec={value!r} 不是数字，已按默认 {default:.0f}s 处理")
        return default
    if seconds <= 0:
        return default
    return seconds


def _parse_percent(value: str, field_name: str, warnings: list[str]) -> int:
    if isinstance(value, str) and re.fullmatch(r"[+-]?\d+%", value.strip()):
        return int(value.strip().rstrip("%"))
    # field_name 由调用方传入，所以要能表达"这个值是从哪读来的"——
    # 用户配的是 tts.rate，提示里再写 voice.rate 会让人找错地方。
    warnings.append(f"{field_name}={value!r} 不是 +N% / -N% 形式，已按 +0% 处理")
    return 0


def rate_to_speed(
    rate: str, *, warnings: list[str] | None = None, source: str = "voice.rate"
) -> float:
    """edge-tts 的 +10% 语速 ≈ ethan-tts 的 1.1×（ffmpeg atempo 保音高）。

    source 只影响告警文案：值来自 config.yaml 的 tts.rate 时传 "tts.rate"，
    免得用户照着 "voice.rate" 去 manifest 里找。
    """
    percent = _parse_percent(rate, source, warnings if warnings is not None else [])
    return max(0.5, min(2.0, round(1.0 + percent / 100.0, 3)))


def resolve_tts_config(
    voice: dict[str, Any] | None = None,
    *,
    backend: str | None = None,
    rate: str | None = None,
    config_path: Path | None = None,
    env: dict[str, str] | None = None,
    check_command: bool = True,
) -> TtsConfig:
    """把 manifest / config.yaml / 环境变量合成一份最终 TTS 配置。

    `check_command=False` 用于 validate 等只做校验、不该因为本机没装 ethan-tts
    就报错的路径（仍会返回 backend=ethan 并给出 warning）。
    """
    warnings: list[str] = []
    environment = dict(os.environ if env is None else env)
    section = load_tts_section(config_path)
    raw_voice = voice or {}

    source = "default"
    chosen: str | None = None
    if backend and backend.strip():
        chosen, source = _normalize_backend(backend, origin="--backend", warnings=warnings), "argument"
    if chosen is None and isinstance(raw_voice.get("backend"), str) and raw_voice["backend"].strip():
        chosen, source = _normalize_backend(
            raw_voice["backend"], origin="manifest voice.backend", warnings=warnings
        ), "manifest"
    if chosen is None and section.get("backend"):
        chosen, source = _normalize_backend(
            section["backend"], origin="config.yaml tts.backend", warnings=warnings
        ), "config"
    if chosen is None and environment.get(ENV_BACKEND, "").strip():
        chosen, source = _normalize_backend(
            environment[ENV_BACKEND], origin=ENV_BACKEND, warnings=warnings
        ), "env"
    if chosen is None:
        chosen, source = DEFAULT_BACKEND, "default"

    config = TtsConfig(
        backend=chosen,
        ethan_command=str(
            section.get("command") or environment.get("ETHAN_TTS_COMMAND") or DEFAULT_ETHAN_CLI
        ).strip(),
        ethan_voice=str(
            raw_voice.get("ethan_voice")
            or section.get("voice")
            or environment.get("ETHAN_TTS_VOICE")
            or DEFAULT_ETHAN_VOICE
        ).strip(),
        ethan_base_url=str(
            section.get("base_url") or environment.get("ETHAN_TTS_URL") or ""
        ).strip(),
        ethan_instruct=str(raw_voice.get("instruct") or section.get("instruct") or "").strip(),
        ethan_timeout_sec=_parse_timeout(
            section.get("timeout_sec") or environment.get("ETHAN_TTS_TIMEOUT_SEC"),
            warnings=warnings,
        ),
        ethan_autostart=_parse_bool(
            section.get("autostart") or environment.get("ETHAN_TTS_AUTOSTART"), default=True
        ),
        voice_name=str(raw_voice.get("name") or ""),
        # 语速优先级：--rate > config.yaml 的 tts.rate > manifest 的 voice.rate > +0%。
        # config 优先是刻意的：定时任务每次由模型生成 manifest，几乎总会带上一句
        # `"rate": "-5%"`（听书默认语速）。若让 manifest 优先，用户在 config 里
        # 设的语速会被静默吃掉——和「配了 tts 段却没生效」是同一类坑。
        # 想对单个项目调语速时，用 --rate 或临时清掉 tts.rate。
        rate=str(rate or section.get("rate") or raw_voice.get("rate") or "+0%"),
        rate_from_config=bool(section.get("rate")) and not rate,
        volume=str(raw_voice.get("volume") or "+0%"),
        pitch=str(raw_voice.get("pitch") or "+0Hz"),
        source=source,
        warnings=warnings,
    )

    if config.backend == BACKEND_ETHAN:
        if shutil.which(config.ethan_command) is None:
            message = (
                f"TTS 后端配置为 ethan（来自 {source}），但本机找不到命令 {config.ethan_command!r}；"
                "请先安装本地 ethan-tts（uv tool install --editable .），"
                "或在 config.yaml 的 tts 段把 backend 改回 edge"
            )
            if check_command:
                raise TtsError(message)
            warnings.append(message)
    return config


# ---------------------------------------------------------------------------
# 时间轴：把已知句子对齐到实测音频长度
# ---------------------------------------------------------------------------


def _sentence_spans(text: str) -> list[str]:
    parts = re.split(r"(?<=[。！？；!?;\n])", text)
    spans = [part for part in parts if part and part.strip()]
    if len(spans) <= 1:  # 没有句末标点：退化为按逗号切，保证至少两段字幕
        parts = re.split(r"(?<=[，,、：:])", text)
        spans = [part for part in parts if part and part.strip()]
    return spans or ([text.strip()] if text.strip() else [])


def _speech_weight(sentence: str) -> int:
    """非空白字符数作为时长权重；纯标点句给 1，避免 0 权重把时间全压到别处。"""
    return max(1, len(re.sub(r"\s+", "", sentence)))


def build_subtitles(text: str, duration_ms: int) -> list[Subtitle]:
    """按句子长度比例把 [0, duration_ms] 切开。

    ethan-tts 不返回词级时间戳，这是唯一无损的做法：字幕边界与语音的实际
    落点可能有几十到一两百毫秒偏差，但文本完整、不重叠、不越界。
    """
    spans = _sentence_spans(text)
    if not spans or duration_ms <= 0:
        return []
    weights = [_speech_weight(sentence) for sentence in spans]
    total = sum(weights)
    subtitles: list[Subtitle] = []
    cursor = 0
    for index, (sentence, weight) in enumerate(zip(spans, weights, strict=True)):
        end = duration_ms if index == len(spans) - 1 else cursor + round(duration_ms * weight / total)
        end = max(cursor + 1, min(end, duration_ms))
        subtitles.append(Subtitle(text=sentence.strip(), start_ms=cursor, end_ms=end))
        cursor = end
    return subtitles


_SILENCE_START_RE = re.compile(r"silence_start: ([0-9.]+)")
_SILENCE_END_RE = re.compile(r"silence_end: ([0-9.]+)")


def detect_silences(path: Path, *, threshold_db: float = -45.0, min_ms: int = 140) -> list[tuple[int, int]]:
    """用 ffmpeg silencedetect 找出停顿区间（毫秒）。

    只用于把字幕边界对齐到真实语音落点；失败（没有 ffmpeg / 解码错误）时返回空列表，
    调用方回退到按字数比例切分，不影响合成本身。
    """
    if shutil.which("ffmpeg") is None:
        return []
    completed = subprocess.run(
        [
            "ffmpeg", "-v", "info", "-i", str(path),
            "-af", f"silencedetect=noise={threshold_db}dB:d={min_ms / 1000:.3f}",
            "-f", "null", "-",
        ],
        check=False, capture_output=True, text=True,
    )
    if completed.returncode != 0:
        return []
    starts = [float(value) for value in _SILENCE_START_RE.findall(completed.stderr)]
    ends = [float(value) for value in _SILENCE_END_RE.findall(completed.stderr)]
    silences: list[tuple[int, int]] = []
    for index, start in enumerate(starts):
        end = ends[index] if index < len(ends) else None
        if end is None or end < start:
            continue
        silences.append((round(start * 1000), round(end * 1000)))
    return silences


def align_subtitles(text: str, duration_ms: int, media_path: Path | None = None) -> list[Subtitle]:
    """按字数比例切分后，用真实静音边界校正句子边界。

    ethan-tts 没有词级时间戳；纯按字数分配在中英混排（"ethan tts" 这种按字母念）
    上会偏出约一秒。静音检测能给出真实的句间停顿，所以：先按比例算出「期望边界」，
    再从检测到的静音里挑最接近的那一个，并保持边界单调、留足剩余候选。
    任何一步对不上就保留比例结果——宁可略偏，也不给出乱序或越界的时间轴。
    """
    base = build_subtitles(text, duration_ms)
    if media_path is None or len(base) < 2:
        return base
    silences = detect_silences(media_path)
    if not silences:
        return base

    # 候选边界 = 每段静音的开始时刻；片头静音不该被当成句间停顿。
    candidates = [start for start, _ in silences if start > 100]
    boundaries: list[int] = []
    cursor = 0
    for index in range(1, len(base)):
        expected = base[index].start_ms
        remaining = len(base) - index
        best: int | None = None
        for candidate in candidates:
            if candidate <= cursor + 60:  # 一句至少要有 60ms 语音，防止边界贴在一起
                continue
            if len([c for c in candidates if c > candidate]) < remaining - 1:
                continue  # 给后面的句子留够候选，避免后段被抢空
            if best is None or abs(candidate - expected) < abs(best - expected):
                best = candidate
        if best is None or abs(best - expected) > max(1500, duration_ms // 4):
            return base  # 偏差过大（比如检测到的是噪声）就整体放弃校正
        boundaries.append(best)
        cursor = best

    subtitles: list[Subtitle] = []
    start = 0
    for index, item in enumerate(base):
        end = boundaries[index] if index < len(boundaries) else duration_ms
        subtitles.append(Subtitle(text=item.text, start_ms=start, end_ms=max(start + 1, end)))
        start = end
    return subtitles


def _format_timestamp(value: int) -> str:
    value = max(0, int(value))
    hours, remainder = divmod(value, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    seconds, millis = divmod(remainder, 1_000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{millis:03d}"


def serialize_srt(subtitles: list[Subtitle]) -> str:
    blocks = [
        f"{index}\n{_format_timestamp(item.start_ms)} --> {_format_timestamp(item.end_ms)}\n{item.text}"
        for index, item in enumerate(subtitles, 1)
    ]
    return "\n\n".join(blocks) + ("\n" if blocks else "")


def merge_subtitles(chunks: list[tuple[str, int]]) -> list[Subtitle]:
    """按 (文本, 时长) 逐块生成字幕并累加偏移，供长文本分块合成后拼接时间轴。"""
    merged: list[Subtitle] = []
    offset = 0
    for text, duration_ms in chunks:
        for item in build_subtitles(text, duration_ms):
            merged.append(Subtitle(text=item.text, start_ms=item.start_ms + offset, end_ms=item.end_ms + offset))
        offset += duration_ms
    return merged


# ---------------------------------------------------------------------------
# 探测音频时长（WAV 直接读头，其他格式交给 ffprobe）
# ---------------------------------------------------------------------------


def _wav_duration_ms(path: Path) -> int | None:
    try:
        with wave.open(str(path), "rb") as handle:
            frames, rate = handle.getnframes(), handle.getframerate()
        if rate <= 0:
            return None
        return round(frames / rate * 1000)
    except (wave.Error, OSError, EOFError):
        return None


def probe_duration_ms(path: Path) -> int:
    duration = _wav_duration_ms(path)
    if duration is not None and duration > 0:
        return duration
    if shutil.which("ffprobe") is None:
        raise TtsError(f"无法读取 {path.name} 的时长（需要 ffprobe）")
    completed = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        check=False, capture_output=True, text=True,
    )
    if completed.returncode != 0:
        raise TtsError(f"ffprobe 读取 {path.name} 失败：{completed.stderr.strip()[:200]}")
    try:
        seconds = float(completed.stdout.strip())
    except ValueError as exc:
        raise TtsError(f"{path.name} 的时长不是数字：{completed.stdout.strip()[:80]}") from exc
    if seconds <= 0:
        raise TtsError(f"{path.name} 的时长为 {seconds}")
    return round(seconds * 1000)


# ---------------------------------------------------------------------------
# edge-tts（默认后端）
# ---------------------------------------------------------------------------


async def _edge_synthesize(text: str, config: TtsConfig, media_path: Path, srt_path: Path) -> None:
    try:
        import edge_tts
    except ImportError as exc:
        raise TtsError(
            "edge-tts is missing; run with: uv run --with 'edge-tts>=7,<8' python ..."
        ) from exc

    communicate = edge_tts.Communicate(
        text, config.voice_name, rate=config.rate, volume=config.volume, pitch=config.pitch
    )
    submaker = edge_tts.SubMaker()
    with media_path.open("wb") as audio_file:
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                audio_file.write(chunk["data"])
            elif chunk["type"] in {"WordBoundary", "SentenceBoundary"}:
                submaker.feed(chunk)
    srt_path.write_text(submaker.get_srt(), encoding="utf-8")
    if media_path.stat().st_size < MIN_AUDIO_BYTES:
        raise TtsError("Edge TTS returned an empty audio file")
    if not srt_path.read_text(encoding="utf-8").strip():
        raise TtsError("Edge TTS returned no subtitle boundaries")


# ---------------------------------------------------------------------------
# ethan-tts（本地 Qwen3-TTS CLI）
# ---------------------------------------------------------------------------


def _split_for_ethan(text: str, maximum: int = ETHAN_CHUNK_CHARS) -> list[str]:
    """按句末标点累积切块，单块不超过 maximum；没有标点的超长文本硬切。"""
    spans = _sentence_spans(text)
    chunks: list[str] = []
    current = ""
    for sentence in spans:
        while len(sentence) > maximum:
            if current:
                chunks.append(current)
                current = ""
            chunks.append(sentence[:maximum])
            sentence = sentence[maximum:]
        if len(current) + len(sentence) > maximum and current:
            chunks.append(current)
            current = ""
        current += sentence
    if current.strip():
        chunks.append(current)
    return chunks or [text]


def _ethan_say(config: TtsConfig, text: str, media_path: Path, *, speed: float) -> None:
    command = [
        config.ethan_command, "say", text,
        "--json",
        "-o", str(media_path),
        "--format", "wav",
    ]
    if not config.ethan_autostart:
        command.append("--no-autostart")
    if config.ethan_voice:
        command += ["--voice", config.ethan_voice]
    if config.ethan_instruct:
        command += ["--instruct", config.ethan_instruct]
    if config.ethan_base_url:
        command += ["--base", config.ethan_base_url]
    if abs(speed - 1.0) > 1e-9:
        command += ["--speed", f"{speed:.2f}"]
    try:
        completed = subprocess.run(
            command, check=False, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=config.ethan_timeout_sec,
        )
    except FileNotFoundError as exc:
        raise TtsError(f"找不到命令 {config.ethan_command!r}，请先安装本地 ethan-tts") from exc
    except subprocess.TimeoutExpired as exc:
        raise TtsError(
            f"ethan-tts 合成超时（{config.ethan_timeout_sec:.0f}s）；"
            "长文本请确认本地服务在跑、模型已加载"
        ) from exc
    if completed.returncode != 0:
        detail = (completed.stdout or completed.stderr or "").strip()
        raise TtsError(f"ethan-tts 失败（exit {completed.returncode}）：{detail[:300]}")
    if not media_path.is_file() or media_path.stat().st_size < MIN_AUDIO_BYTES:
        raise TtsError("ethan-tts 没有产出有效音频")


def _concat_wavs(parts: list[Path], target: Path, work_dir: Path) -> None:
    """把同参数的 WAV 片段拼成一个（concat demuxer，PCM16/24k/mono 直拼）。"""
    list_path = work_dir / f".{target.stem}.concat.txt"
    list_path.write_text(
        "\n".join(f"file '{str(part).replace(chr(39), chr(39) + chr(92) + chr(39) + chr(39))}'" for part in parts)
        + "\n",
        encoding="utf-8",
    )
    completed = subprocess.run(
        [
            "ffmpeg", "-y", "-v", "error",
            "-f", "concat", "-safe", "0", "-i", str(list_path),
            "-c:a", "pcm_s16le", str(target),
        ],
        check=False, capture_output=True, text=True,
    )
    list_path.unlink(missing_ok=True)
    if completed.returncode != 0 or not target.is_file():
        raise TtsError(f"拼接 WAV 失败：{completed.stderr.strip()[:200]}")


def _ethan_synthesize(text: str, config: TtsConfig, media_path: Path, srt_path: Path) -> None:
    # 非法 rate 要报出来而不是静默按 1.0× 跑：用户明明写了 +10% 却没变快，
    # 不给提示的话只能靠猜。来源名按实际读取位置给。
    rate_warnings: list[str] = []
    speed = rate_to_speed(
        config.rate,
        warnings=rate_warnings,
        source="tts.rate" if config.rate_from_config else "voice.rate",
    )
    for warning in rate_warnings:
        print(f"WARNING: {warning}", file=sys.stderr)
    chunks = _split_for_ethan(text)
    with tempfile.TemporaryDirectory(prefix="ethan-tts-") as tmp:
        work_dir = Path(tmp)
        parts: list[Path] = []
        spans: list[tuple[str, int]] = []
        for index, chunk in enumerate(chunks):
            part = work_dir / f"part-{index:03d}.wav"
            _ethan_say(config, chunk, part, speed=speed)
            parts.append(part)
            spans.append((chunk, probe_duration_ms(part)))
        if len(parts) == 1:
            shutil.copy2(parts[0], media_path)
        else:
            _concat_wavs(parts, media_path, work_dir)

    duration_ms = probe_duration_ms(media_path)
    if sum(item[1] for item in spans) and len(parts) > 1:
        duration_ms = min(duration_ms, sum(item[1] for item in spans))
    subtitles = align_subtitles(text, duration_ms, media_path)
    if not subtitles:
        raise TtsError("ethan-tts 音频缺少可用的字幕时间轴")
    # 用实际音频总时长收口最后一条字幕，避免拼接误差让字幕越过片尾。
    last = subtitles[-1]
    if last.end_ms > duration_ms:
        subtitles[-1] = Subtitle(text=last.text, start_ms=min(last.start_ms, duration_ms - 1), end_ms=duration_ms)
    srt_path.write_text(serialize_srt(subtitles), encoding="utf-8")


# ---------------------------------------------------------------------------
# 对外接口
# ---------------------------------------------------------------------------


async def synthesize(text: str, config: TtsConfig, media_path: Path, srt_path: Path) -> None:
    """合成一段文本到 media_path，并把 SRT 写到 srt_path（两者都必须有效）。

    调用方负责重试、原子替换与并发去重；这里失败一律抛 TtsError。
    """
    if config.backend == BACKEND_ETHAN:
        # CLI 是阻塞子进程，丢到线程里，保持与 edge 一致的并发语义。
        await asyncio.to_thread(_ethan_synthesize, text, config, media_path, srt_path)
        return
    await _edge_synthesize(text, config, media_path, srt_path)


def synthesize_sync(text: str, config: TtsConfig, media_path: Path, srt_path: Path) -> None:
    """同步入口，给非 asyncio 调用方（demo 脚本、排查工具）用。"""
    asyncio.run(synthesize(text, config, media_path, srt_path))


def list_ethan_voices(config: TtsConfig) -> list[dict[str, Any]]:
    """列出 ethan-tts 可用音色（edge 后端返回空列表）。"""
    if config.backend != BACKEND_ETHAN:
        return []
    command = [config.ethan_command, "voices", "list", "--json"]
    if not config.ethan_autostart:
        command.append("--no-autostart")
    if config.ethan_base_url:
        command += ["--base", config.ethan_base_url]
    completed = subprocess.run(command, check=False, capture_output=True, text=True, timeout=60)
    if completed.returncode != 0:
        raise TtsError(f"读取 ethan-tts 音色失败：{(completed.stderr or completed.stdout).strip()[:200]}")
    try:
        return json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise TtsError("ethan-tts voices list 返回的不是 JSON") from exc


def ensure_silence_file(work_dir: Path, gap_ms: int, *, suffix: str = ".mp3", sample_rate: int = 24_000) -> Path:
    """生成章节间静音片段。格式必须与章节音频一致，concat demuxer 才能直拼。"""
    gap_path = work_dir / f"silence-{gap_ms}ms{suffix}"
    if gap_path.exists():
        return gap_path
    work_dir.mkdir(parents=True, exist_ok=True)
    codec = ["-c:a", "pcm_s16le"] if suffix == ".wav" else ["-c:a", "libmp3lame", "-q:a", "9"]
    completed = subprocess.run(
        [
            "ffmpeg", "-y", "-v", "error",
            "-f", "lavfi", "-i", f"anullsrc=r={sample_rate}:cl=mono",
            "-t", f"{gap_ms / 1000:.3f}",
            *codec, str(gap_path),
        ],
        check=False, capture_output=True, text=True,
    )
    if completed.returncode != 0 or not gap_path.exists():
        raise TtsError(f"生成静音失败：{completed.stderr.strip()[:200]}")
    return gap_path


__all__ = [
    "BACKEND_EDGE",
    "BACKEND_ETHAN",
    "BACKENDS",
    "DEFAULT_BACKEND",
    "DEFAULT_ETHAN_VOICE",
    "Subtitle",
    "TtsConfig",
    "TtsError",
    "align_subtitles",
    "build_subtitles",
    "detect_silences",
    "config_yaml_path",
    "ensure_silence_file",
    "list_ethan_voices",
    "load_tts_section",
    "merge_subtitles",
    "parse_tts_section",
    "probe_duration_ms",
    "rate_to_speed",
    "resolve_tts_config",
    "serialize_srt",
    "synthesize",
    "synthesize_sync",
]
