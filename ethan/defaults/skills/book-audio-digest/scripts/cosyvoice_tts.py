#!/usr/bin/env python3
"""CosyVoice2 TTS 合成 helper — 跑在独立 venv（torch 等重依赖），由 audio_pipeline.py 以子进程调用。

与 edge-tts 路径产出同构的缓存布局（work/tts-cache/{key}.mp3 + {key}.srt），
下游拼接/字幕逻辑零改动。句级缓存：单句重跑不重复合成整节。

用法（由 audio_pipeline.py 自动调用，一般不手工跑）:
  COSYVOICE_PYTHON ~/.ethan/cosyvoice-venv/bin/python \\
  cosyvoice_tts.py --manifest manifest.json --output-dir OUT_DIR
"""
import argparse
import hashlib
import json
import logging
import re
import subprocess
import sys
from pathlib import Path

COSYVOICE_REPO = Path.home() / ".ethan" / "CosyVoice"
MODEL_DIR = COSYVOICE_REPO / "pretrained_models" / "CosyVoice2-0.5B"
SENT_GAP_MS = 120  # 句间停顿：CosyVoice 逐句合成无跨句连读，补一个自然停顿
SAMPLE_RATE = 24000

# 与 audio_pipeline._tts_cache_key 对齐（engine 纳入 key，避免跨引擎撞缓存）
def cache_key(engine: str, narration: str, voice: dict) -> str:
    payload = json.dumps({"engine": engine, "narration": narration, "voice": voice},
                         ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]


_SENT_SPLIT_RE = re.compile(r"(?<=[。！？!?；;])\s*")

def split_sentences(text: str) -> list[str]:
    parts = [p.strip() for p in _SENT_SPLIT_RE.split(text) if p.strip()]
    # 合并过短的碎片（如"那怎么办？"独立成句可以，但"嗯。"并入前句）——保留 >=6 字或独立问句
    merged: list[str] = []
    for p in parts:
        if merged and len(p) < 6 and not p.endswith(("？", "?", "！", "!")):
            merged[-1] += p
        else:
            merged.append(p)
    return merged or [text]


def srt_format(ms: int) -> str:
    ms = max(0, int(ms))
    h, r = divmod(ms, 3_600_000)
    m, r = divmod(r, 60_000)
    s, ms2 = divmod(r, 1_000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms2:03d}"


def wav_duration_ms(wav_path: Path) -> int:
    import torchaudio
    info = torchaudio.info(str(wav_path))
    return round(info.num_frames / info.sample_rate * 1000)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()

    logging.basicConfig(level=logging.WARNING)
    manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    output_dir = Path(args.output_dir)
    cache_dir = output_dir / "work" / "tts-cache"
    sent_cache_dir = output_dir / "work" / "cv-sent-cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    sent_cache_dir.mkdir(parents=True, exist_ok=True)

    sys.path.insert(0, str(COSYVOICE_REPO))
    matcha = COSYVOICE_REPO / "third_party" / "Matcha-TTS"
    if matcha.exists():
        sys.path.insert(0, str(matcha))

    import numpy as np  # noqa: E402
    import soundfile as sf  # noqa: E402
    import torch  # noqa: E402
    import torchaudio  # noqa: E402

    def _sf_load(filepath, *args, **kwargs):
        # torchaudio>=2.6 的 load 需要 torchcodec（Mac 上 dylib 兼容性差），soundfile 等价替代
        data, sr = sf.read(filepath, dtype="float32", always_2d=True)
        return torch.from_numpy(np.array(data).T).contiguous(), sr

    torchaudio.load = _sf_load
    from cosyvoice.cli.cosyvoice import AutoModel  # noqa: E402

    model = AutoModel(model_dir=str(MODEL_DIR))

    spk_id = manifest["voice"]["name"]
    available = model.list_available_spks()
    if spk_id not in available:
        # 非预置音色 → zero-shot 注册：manifest.voice.promptWav + promptText，
        # 或全局音色库 ~/.ethan/cosyvoice-voices/{spk}.wav + {spk}.txt
        prompt_wav = manifest["voice"].get("promptWav") or str(
            Path.home() / ".ethan" / "cosyvoice-voices" / f"{spk_id}.wav")
        wav_path = Path(prompt_wav).expanduser()
        # promptText：指向存在的 .txt 文件则读文件，否则视为文本内容本身
        prompt_txt_raw = manifest["voice"].get("promptText") or str(
            Path.home() / ".ethan" / "cosyvoice-voices" / f"{spk_id}.txt")
        txt_path = Path(prompt_txt_raw).expanduser()
        prompt_text = txt_path.read_text(encoding="utf-8").strip() if txt_path.exists() else str(prompt_txt_raw).strip()
        if not (wav_path.exists() and prompt_text):
            print(json.dumps({"status": "error",
                              "error": f"voice '{spk_id}' is not a preset and has no zero-shot prompt pair "
                                       f"({wav_path} / {prompt_txt_raw})",
                              "available": available}, ensure_ascii=False))
            return 1
        if model.add_zero_shot_spk(prompt_text, str(wav_path), spk_id) is not True:
            print(json.dumps({"status": "error", "error": f"add_zero_shot_spk failed for '{spk_id}'"},
                             ensure_ascii=False))
            return 1
        print(f"[cosyvoice] registered zero-shot spk '{spk_id}'", file=sys.stderr)

    voice = manifest["voice"]
    artifacts = []
    for section in manifest["sections"]:
        key = cache_key("cosyvoice", section["narration"], voice)
        mp3_path = cache_dir / f"{key}.mp3"
        srt_path = cache_dir / f"{key}.srt"
        if mp3_path.exists() and srt_path.exists() and mp3_path.stat().st_size >= 256:
            artifacts.append({"id": section["id"], "audio": str(mp3_path), "srt": str(srt_path)})
            continue

        sentences = split_sentences(section["narration"])
        sent_wavs: list[Path] = []
        for idx, sent in enumerate(sentences):
            sent_key = hashlib.sha256(f"{spk_id}|{sent}".encode("utf-8")).hexdigest()[:24]
            wav_path = sent_cache_dir / f"{sent_key}.wav"
            if not (wav_path.exists() and wav_path.stat().st_size >= 1024):
                pending = wav_path.with_suffix(".tmp.wav")
                got_any = False
                for chunk in model.inference_zero_shot(sent, "", "", zero_shot_spk_id=spk_id, stream=False):
                    sf.write(str(pending), chunk["tts_speech"].numpy().T, model.sample_rate)
                    got_any = True
                    break  # 非 stream 模式只有一块；保守取首块
                if not got_any or pending.stat().st_size < 1024:
                    print(json.dumps({"status": "error",
                                      "error": f"empty synthesis for sentence {idx} of {section['id']}"},
                                     ensure_ascii=False))
                    return 1
                pending.replace(wav_path)
            sent_wavs.append(wav_path)

        # 拼接句 wav + 句间静音 → 单 wav → mp3
        gap = torch.zeros(1, int(SAMPLE_RATE * SENT_GAP_MS / 1000))
        pieces, srt_entries, cursor_ms = [], [], 0
        for i, w in enumerate(sent_wavs):
            audio, sr = _sf_load(str(w))
            if audio.shape[0] > 1:
                audio = audio.mean(dim=0, keepdim=True)
            if sr != SAMPLE_RATE:
                audio = torchaudio.functional.resample(audio, sr, SAMPLE_RATE)
            pieces.append(audio)
            dur_ms = round(audio.shape[1] / SAMPLE_RATE * 1000)
            srt_entries.append((cursor_ms, cursor_ms + dur_ms, sentences[i]))
            cursor_ms += dur_ms + SENT_GAP_MS
            if i < len(sent_wavs) - 1:
                pieces.append(gap)
        merged = torch.cat(pieces, dim=1)
        merged_wav = cache_dir / f".{key}.merged.wav"
        sf.write(str(merged_wav), merged.numpy().T, SAMPLE_RATE)

        mp3_path_unlink = mp3_path.with_suffix(".tmp.mp3")
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(merged_wav),
                        "-ar", str(SAMPLE_RATE), "-ac", "1", "-c:a", "libmp3lame", "-q:a", "2",
                        str(mp3_path_unlink)], check=True)
        mp3_path_unlink.replace(mp3_path)
        merged_wav.unlink(missing_ok=True)

        blocks = [f"{i + 1}\n{srt_format(s)} --> {srt_format(e)}\n{t}"
                  for i, (s, e, t) in enumerate(srt_entries)]
        srt_path.write_text("\n\n".join(blocks) + "\n", encoding="utf-8")

        artifacts.append({"id": section["id"], "audio": str(mp3_path), "srt": str(srt_path)})
        print(f"[cosyvoice] section {section['id']} done ({len(sentences)} sentences)", file=sys.stderr)

    print(json.dumps({"status": "ok", "artifacts": artifacts}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
