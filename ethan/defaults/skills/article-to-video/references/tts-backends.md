# TTS 后端（edge-tts / ethan-tts）

`article-to-video` 和 `book-audio-digest` 两个技能共用 `ethan/defaults/skills/_shared/tts_backend.py`，
配音后端可配置：**默认仍是 edge-tts**（在线服务，零额外安装），可以切换成本机安装的
`ethan-tts`（Qwen3-TTS，Apple Silicon 本地推理）。

## 选择顺序

按优先级从高到低，第一个命中的生效：

1. 命令行 `--backend edge|ethan`（`run` 和 `validate` 都支持）
2. manifest 里的 `voice.backend`
3. `~/.ethan/config.yaml` 的 `tts.backend`（`ETHAN_DATA_DIR` 生效时读该目录）
4. 环境变量 `ETHAN_TTS_BACKEND`
5. 内置默认 `edge`

## 配置（config.yaml）

```yaml
tts:
  backend: ethan          # edge | ethan
  voice: preset:Vivian    # ethan 音色：id 或名称，见 ethan-tts voices list
  instruct: 轻快一点       # 可选，语气指令（仅 ethan）
  base_url: ""            # 可选，ethan-tts 服务地址，空=CLI 默认 127.0.0.1:8765
  command: ""             # 可选，ethan-tts 可执行文件，空=用 PATH 里的 ethan-tts
  timeout_sec: 0          # 可选，单次合成超时，0=默认 300s
```

`tts` 段已加入 `ethan/core/config.py` 的 `Config` 模型，所以 Web/Desktop 设置页保存配置时不会把它丢掉。

环境变量兜底（适合临时验证）：

```bash
ETHAN_TTS_BACKEND=ethan ETHAN_TTS_VOICE=preset:Serena \
  python3 ~/.ethan/skills/book-audio-digest/scripts/audio_pipeline.py run ...
```

## 两个后端的差异

| | edge-tts | ethan-tts |
| --- | --- | --- |
| 运行位置 | 在线服务 | 本机 CLI / 本地服务 |
| 依赖 | `edge-tts`（uv 临时注入） | 本机已安装 `ethan-tts` |
| 音频格式 | MP3 24kHz mono | WAV 24kHz mono |
| 字幕时间轴 | 真实词级 WordBoundary | 按句比例分配 + 静音检测校正 |
| 音色参数 | `name` / `rate` / `volume` / `pitch` | `ethan_voice` / `instruct` / `rate`（换算语速） |

字幕精度：ethan 后端没有词级时间戳，句子边界靠 `ffmpeg silencedetect` 校正，
实测与原音的句间停顿吻合在几十毫秒内；找不到合适停顿（或没有 ffmpeg）时回退到纯比例切分，
文本始终完整、不重叠、不越界。

缓存：两个管线的缓存键都包含后端签名（后端名 + 音色 + 语速等），
所以切后端不会误命中旧音频，切回去也能命中原来那份缓存。

## 长文本

`ethan-tts` 服务端单次上限 2000 字，共享层按 300 字左右切块（按标点切，不切断句子），
逐块合成后用 ffmpeg concat 拼成一个 WAV，字幕偏移按每块实测时长累加。
单块失败会走管线原有的重试与原子替换，不会留下半成品。

## 排查

| 现象 | 处理 |
| --- | --- |
| `找不到命令 'ethan-tts'` | 先装本地工具：`cd <ethan-tts 仓库> && uv tool install --python 3.12 --editable .` |
| 合成超时 | 确认本地服务在跑（`ethan-tts status`）、模型已加载；长文本调大 `tts.timeout_sec` |
| 字幕整体偏移 | 该段没有明显句间停顿，属于已知限制；可把长句拆成多句让静音检测有落点 |
| 想临时切回在线 | `--backend edge` 或把 `tts.backend` 改回 `edge` |
