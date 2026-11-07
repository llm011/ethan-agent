# 语音合成（TTS）配置

Ethan 的两个媒体技能——`article-to-video`（文章转视频）和 `book-audio-digest`（深度听书）——
需要把文字念出来。配音后端是**可配置**的：

| 后端 | 说明 | 依赖 |
| --- | --- | --- |
| `edge-tts`（默认） | 微软 Edge 在线语音，装完即用 | 首次运行自动装 `edge-tts` |
| `ethan-tts` | 本机跑的 [ethan-tts](https://github.com/jsongo/ethan-tts)（Qwen3-TTS） | 需要自己安装，仅 Apple Silicon |

**默认就是 `edge-tts`，不配置也能用。** 只有想用本机音色（更自然、可克隆、不联网）时才需要改配置。

---

## 快速开始：切到本地 ethan-tts

### 1. 先装好 ethan-tts

Ethan 不打包它，需要单独安装（仓库：[jsongo/ethan-tts](https://github.com/jsongo/ethan-tts)）：

```bash
git clone https://github.com/jsongo/ethan-tts.git
cd ethan-tts
uv tool install --python 3.12 --editable .
```

装完确认命令可用，并看一眼有哪些音色：

```bash
ethan-tts status --json     # server_running 应为 true（没有会自动拉起）
ethan-tts voices list       # 记下想用的音色 id 或名称
```

输出大概长这样（`id` 那一列就是配置里要填的值）：

```
preset:Vivian     薇薇安     custom   中文女声，清晰自然
preset:Serena     塞琳娜     custom   中文女声，温和流畅
preset:Uncle_Fu   傅叔叔     custom   中文男声，沉稳
voice:f3ea7d52…   老凌的声音  clone    我的声音
```

### 2. 改 `~/.ethan/config.yaml`

在文件里加一个顶层 `tts:` 段（没有就新建，注意顶格写、不要缩进到别的段下面）：

```yaml
tts:
  backend: ethan-tts
  voice: preset:Vivian
```

保存即可，**下次合成自动生效**，不用重启服务。

> `ETHAN_DATA_DIR` 环境变量生效时，配置文件在 `$ETHAN_DATA_DIR/config.yaml`。

### 3. 验证

```bash
cd ~/.ethan/skills/book-audio-digest/scripts
python3 audio_pipeline.py validate --manifest /path/to/manifest.json
```

输出里的 `tts` 字段会告诉你实际会用哪个后端、哪个音色、配置来自哪里：

```json
"tts": {"backend": "ethan-tts", "voice": "ethan-tts（preset:Vivian）", "source": "config"}
```

`source` 的含义：

| 值 | 来自 |
| --- | --- |
| `argument` | 命令行 `--backend` |
| `manifest` | manifest 里的 `voice.backend` |
| `config` | `~/.ethan/config.yaml` 的 `tts.backend` |
| `env` | 环境变量 `ETHAN_TTS_BACKEND` |
| `default` | 没配，用的默认 `edge-tts` |

---

## 配置项全表

`~/.ethan/config.yaml` 顶层 `tts:` 段：

| 字段 | 默认 | 说明 |
| --- | --- | --- |
| `backend` | `edge-tts` | `edge-tts` 或 `ethan-tts` |
| `voice` | `preset:Vivian` | ethan-tts 后端的音色，id 或名称都行（见 `ethan-tts voices list`） |
| `instruct` | 空 | ethan-tts 后端的语气指令，如「轻快一点」「沉稳一些」 |
| `base_url` | 空 | ethan-tts 服务地址，空=用 CLI 默认 `127.0.0.1:8765`；连远端实例时才需要 |
| `command` | 空 | ethan-tts 可执行文件路径，空=用 PATH 里的 `ethan-tts` |
| `timeout_sec` | `0` | 单次合成超时秒数，`0`=内置默认 300 秒；长文本可调大 |
| `autostart` | `true` | 服务没跑时是否让 CLI 自动在后台拉起 |

```yaml
# 完整示例：本地后端 + 指定音色 + 语气 + 放宽超时
tts:
  backend: ethan-tts
  voice: preset:Serena
  instruct: 语速平稳，像在讲一件有意思的事
  timeout_sec: 600
  autostart: true
```

---

## 三种临时切换方式

不想改配置文件时，这几种优先级更高（从高到低）：

**1. 命令行参数**（只影响这一次）

```bash
python3 ~/.ethan/skills/book-audio-digest/scripts/audio_pipeline.py run \
  --manifest manifest.json --output-dir out --backend ethan-tts
```

**2. manifest 里指定**（只影响这一个项目）

```json
{
  "title": "我的视频",
  "voice": {
    "backend": "ethan-tts",
    "ethan_voice": "preset:Serena",
    "rate": "+5%"
  },
  "scenes": [...]
}
```

**3. 环境变量**（只影响当前 shell）

```bash
ETHAN_TTS_BACKEND=ethan-tts ETHAN_TTS_VOICE=preset:Serena \
  python3 ~/.ethan/skills/book-audio-digest/scripts/audio_pipeline.py run ...
```

可用的环境变量：`ETHAN_TTS_BACKEND`、`ETHAN_TTS_VOICE`、`ETHAN_TTS_URL`、
`ETHAN_TTS_COMMAND`、`ETHAN_TTS_TIMEOUT_SEC`、`ETHAN_TTS_AUTOSTART`。

完整优先级：`--backend` > manifest `voice.backend` > `config.yaml` > 环境变量 > 默认 `edge-tts`。

> `edge` / `ethan` 这类简写仍可用（大小写、下划线都容忍），但**回显和落盘一律用规范名** `edge-tts` / `ethan-tts`。

---

## 语速和音色参数怎么对应

两个后端的参数不完全一样：

| 参数 | edge-tts | ethan-tts |
| --- | --- | --- |
| `voice.name` | 在线音色名（如 `zh-CN-YunxiNeural`） | **不生效**，用 `ethan_voice` |
| `voice.rate` | 直接传给服务（`+10%`） | 换算成保音高的语速倍率（`+10%` → `1.1×`） |
| `voice.volume` | 生效（`+0%`） | 不生效 |
| `voice.pitch` | 生效（`+0Hz`） | 不生效 |
| `voice.instruct` | 忽略 | 生效，语气指令 |

所以从 edge 切到 ethan 时，`rate` 可以直接沿用，`volume`/`pitch` 会被忽略（不会报错）。
ethan 想调整音色质感，用 `instruct` 或换一个 `voice`。

---

## 两个后端的差异

| | edge-tts | ethan-tts |
| --- | --- | --- |
| 运行位置 | 在线服务 | 本机推理 |
| 音频格式 | MP3 24kHz 单声道 | WAV 24kHz 单声道 |
| 字幕时间轴 | 真实词级边界，精确 | 按句比例分配 + 静音检测校正 |
| 断网可用 | 否 | 是 |
| 平台 | 任意 | 仅 Apple Silicon（MLX） |

**字幕精度说明**：ethan-tts 不返回词级时间戳，所以字幕边界是按句子字数比例估算，
再用 `ffmpeg` 的静音检测对齐到真实停顿。实测偏差在几十毫秒量级；
如果某段没有明显停顿（语速很平），会退化成纯比例分配，偏差可能到一两百毫秒——
但字幕文本始终完整、不重叠、不越界。

**缓存是分开的**：缓存键包含后端签名，切到 ethan 不会误用 edge 的旧音频，
切回 edge 也能命中原来那份，不用重新合成。

---

## 常见问题

**报「找不到命令 'ethan-tts'」**

说明配置写了 `backend: ethan-tts` 但本机没装。要么按上面第 1 步安装，要么把配置改回 `edge-tts`：

```yaml
tts:
  backend: edge-tts
```

**合成很慢 / 超时**

本地模型首次调用要加载权重（几秒到十几秒）。确认服务在跑：

```bash
ethan-tts status
```

长文本可以调大超时：

```yaml
tts:
  backend: ethan-tts
  timeout_sec: 900
```

**字幕整体偏早或偏晚**

该段可能没有明显句间停顿。把长句拆成几个短句（多加句号），静音检测就有落点可对齐。

**想临时切回在线**

`--backend edge-tts`，或把 `tts.backend` 改成 `edge-tts`，或临时 `ETHAN_TTS_BACKEND=edge-tts`。

**改了配置没生效**

先看 `validate` 输出里的 `tts.source` 字段：
- 如果显示 `manifest`，说明 manifest 里写了 `voice.backend`，它的优先级高于 config.yaml；
- 如果显示 `argument`，说明命令行带了 `--backend`。

---

## 相关文件

| 用途 | 路径 |
| --- | --- |
| 共享实现 | `ethan/defaults/skills/_shared/tts_backend.py` |
| 技能内说明 | `ethan/defaults/skills/article-to-video/references/tts-backends.md` |
| 配置模型 | `ethan/core/config.py` 的 `TtsConfig` |
| 测试 | `tests/test_tts_backend.py` |
