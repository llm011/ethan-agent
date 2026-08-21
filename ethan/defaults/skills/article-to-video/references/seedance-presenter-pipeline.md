# Seedance 2.0 动态 Presenter 管线

用 BytePlus ModelArk 的 Seedance 2.0（经 Glowix gateway）替代本地 ComfyUI H3，为 presenter 场景生成带情绪表演的动态视频。确定性舞台渲染提供首帧，Seedance 图生视频（首帧模式）生成整幅画面，再把生成段精确替换回成片时间窗。

- 脚本：`scripts/seedance_presenter_pipeline.py`（子命令 `mode / prepare / submit / poll / compose / verify`）
- 网关冒烟测试：仓库根 `scripts/test-all-models.mjs`
- 协议文档：创建任务 `docs.byteplus.com/en/docs/ModelArk/1520757`，查询任务 `…/1521309`，提示词指南见火山方舟《Seedance 2.0 系列提示词指南》

## 配置（config.yaml，密钥永不进代码）

`~/.ethan/config.yaml`（或 `ETHAN_DATA_DIR` 指定目录下的 `config.yaml`）顶层 `seedance:` 段：

```yaml
seedance:
  gateway_url: https://byteplus-gateway-staging.glowix.dev/v1
  api_key: '<GATEWAY_API_KEY>'
  edge_secret: '<CLOUDFLARE_EDGE_SECRET>'
  resolution: "1080p"        # video_fast/video_mini 自动降 720p
  generate_audio: false      # true 则生成原生语音（音轨会被 compose 丢弃，仅影响口型）
  models:
    video: ep-xxxx           # Seedance 2.0 质量档（默认，最高 1080p）
    video_fast: ep-xxxx      # Seedance 2.0 Fast（最高 720p）
    video_mini: ep-xxxx      # Seedance 2.0 Mini（最高 720p）
    image: ep-xxxx           # 冒烟测试用
    chat: ep-xxxx            # 冒烟测试用
```

- 环境变量覆盖：`SEEDANCE_GATEWAY_URL / SEEDANCE_API_KEY / SEEDANCE_EDGE_SECRET`。
- 文件权限建议 `chmod 600`。ethan 核心的 pydantic Config 忽略未知顶层键，加此段不影响主配置。
- 缺任一必要键时 `mode` 不会选中 seedance，`submit` 会报错并指向本文件。

## 模式优先级

```
用户显式指定（"用 seedance" / "用 h3" / "不要用大模型"）
  > seedance（config.yaml 配置完整）
  > h3（H3_COMFYUI_URL 或 h3-comfyui.env）
  > 静态立绘
```

`seedance_presenter_pipeline.py mode` 输出 `MODE: <seedance|h3|static>`；显式指示用 `--prefer` 传入，指定了但未配置会明确报错，**绝不静默回退**。

## 流程（每个 presenter 场景）

```bash
PIPE=~/.ethan/skills/article-to-video/scripts
# 0. 渲染完成后拿到 final.mp4 / timeline.json

# 1. 导出场景稳定帧（--first-frame 取场景 50% 处：揭示动画已完成、淡出未开始；
#    Seedance 会把整段画面冻结在首帧布局上，喂起点帧会让 UI 整段不完整）
node ~/.ethan/skills/article-to-video/assets/open-motion-template/render.mjs stills \
  "$PROJECT/timeline.json" "$PROJECT/work/seedance/stills" "$PROJECT/work/public" --first-frame

# 2. 准备场景包（不联网）：台词=场景旁白，时长/起点从 timeline.json 的 durationMs/startMs 换算
python3 "$PIPE/seedance_presenter_pipeline.py" prepare \
  --scene-dir "$PROJECT/work/seedance/scenes/<scene-id>" \
  --combined-reference "$PROJECT/work/seedance/stills/<scene-id>-combined.png" \
  --dialogue "<该场景旁白>" --duration <durationMs/1000> --start-seconds <startMs/1000> \
  --presenter <presenter-id>   # 缺省用内置小雨

# 3. 提交 + 轮询（真实计费；生成要几分钟，建议 nohup 后台跑 poll 看日志）
python3 "$PIPE/seedance_presenter_pipeline.py" submit --scene-dir <场景目录>
python3 "$PIPE/seedance_presenter_pipeline.py" poll --scene-dir <场景目录>   # 产出 raw-seedance.mp4

# 4. 替换回成片（音轨沿用原片 TTS；多场景按时间序串行替换，输出链式传递）
python3 "$PIPE/seedance_presenter_pipeline.py" compose \
  --scene-dir <场景目录> --stage-video "$PROJECT/final.mp4" --output "$PROJECT/final-seedance-<scene-id>.mp4"

# 5. 校验
python3 "$PIPE/seedance_presenter_pipeline.py" verify --scene-dir <场景目录> --video <场景目录>/raw-seedance.mp4
```

首帧参考图默认 base64 data URI 直传（官方支持，单图 <30MB），无需公网托管；超大图先压缩，或上传后 `submit --image-url <公网地址>`。`submit --dry-run` 只打印请求体（base64 省略）不联网。

## 与 H3 的 Prompt 差异（重要）

| | H3 | Seedance 2.0 |
|---|---|---|
| 语言/长度 | 英文长文档（分节合同） | 紧凑中文指令，**≤500 字** |
| 结构 | Reference ownership / Camera / Character integrity / Timeline / Dialogue / Quality 分节 | 精准主体 + 情绪基调 + 表演细节 + 台词 + 镜头 + 约束收尾 |
| 台词 | 引号段落，要求原生中文语音 | `{台词}` 大括号（官方括号语义：`{ }`=台词、`【 】`=想要的字幕、`( )`=音乐、`< >`=音效） |
| 参考素材 | `<Picture 1/2>` 文内引用 | `content` 数组传图（首帧 role=first_frame），prompt 只描述"参考图片1即首帧" |
| 收尾约束 | 视觉质量段 | 必须以"请勿生成字幕、水印或新增文字"类约束收尾 |

`prepare` 内置情绪判定（台词关键词 → 情绪基调 + 表演节拍，可 `--dialogue-file` 传全文后自动检测）：

| 情绪 | 触发词示例 | 表演基调 |
|---|---|---|
| positive | 涨/突破/新高/利好/超预期 | 自信昂扬：眉眼舒展、微笑明亮，重点处抬手指向图表、轻微点头 |
| negative | 跌/风险/警告/下滑/利空 | 沉稳关切：眉峰微蹙后舒展，先倾身提示要点、收尾双手轻叠安抚 |
| neutral | （默认） | 亲切专业：自然微笑、开放手势，重点处指尖轻点方向 |

所有情绪共享：目光以注视镜头为主、指向图表时短暂移开、口型随台词节奏开合——这是 presenter 情感交互的基本盘，台词关键词只调节情绪色彩。生成结果情绪不达标时，重跑 `prepare`（可改台词措辞触发其他情绪档）→ `submit`。

## 硬约束与已知边界

- 单镜头 **4–15s**：场景时长超界会在 prepare 报错（先在 manifest 阶段拆场景）。
- `compose` 按场景时间窗精确替换：fps 对齐原片、生成段缩放裁切到原片尺寸、音轨整体沿用原片，音画同步由"总时长不变"保证；时长不足 0.5s 容差会拒绝。
- 生成视频 URL **24 小时有效**，poll 下载后本地留档 `raw-seedance.mp4`。
- 场景内舞台文字/图表由首帧锁定，prompt 约束"保持不变"，但极端运镜仍可能微调字形——正式交付前用 `verify` + 人工抽帧复核。
- `MODE: seedance` 时不要同时跑 H3 流程；改主意为 h3 时在对话里说"用 h3"即可（`mode --prefer h3` 会校验配置）。

## 排障

| 症状 | 原因/处理 |
|---|---|
| `mode` 报 seedance 未配置 | config.yaml 段不完整（gateway_url/api_key/edge_secret/models.video 必填）；等号后不要跟行内注释 |
| `gateway HTTP 4xx` | 看 stderr 返回体；401/403 查 api_key 与 edge_secret，400 常见为 resolution 与模型档不符（fast/mini 已自动降 720p） |
| `gateway HTTP 403` 且返回体含 `code: 1010` | Cloudflare Browser Integrity Check 封禁非浏览器 UA（与凭证无关）；管线已内置浏览器 UA（`_BROWSER_UA`），若仍出现说明 UA 过期，更新该常量即可 |
| poll 轮询期间网络抖动 / 网关 5xx / 429 | 已自动按间隔递增重试（上限 60s）直到 deadline；只有 4xx 永久错误会立刻中止 |
| poll 超时 | 默认 900s，`--timeout` 调大；任务失败会带平台 error 信息 |
| compose 报像素格式/concat 错误 | 已在 splice filter 各段归一 `format=yuv420p`（Seedance 可能返回 10bit）；仍报错时用 `ffprobe` 查 raw-seedance.mp4 的 pix_fmt |
| 参考图格式问题 | prepare 按魔数嗅探真实格式落盘（jpg 也会以 `.jpg` 存并按 `image/jpeg` 传输）；不支持的格式直接报错 |
| 首帧图 >30MB | 压缩（1080x1920 PNG 正常 <3MB）或 `--image-url` 公网地址 |
| 替换后音画错位 | 检查 `--start-seconds/--duration` 是否与 timeline.json 一致（startMs/durationMs ÷1000） |
