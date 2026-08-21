# H3 动态 Presenter 流水线

MiniMax H3 负责「小雨像一个人在讲」：身体动作、手势、表情、口型和原生中文声音。它**不**是中文字卡、金融数字或图表的最终渲染器。所有可读信息必须由 article-to-video 的确定性渲染结果恢复。

## 前置配置

本流水线由配置开关启用：在 `~/.ethan/skills/article-to-video/h3-comfyui.env` 写入 ComfyUI H3 workflow 地址（用户自建文件，不随技能分发；不是凭证，无需 `chmod 600`）：

```bash
H3_COMFYUI_URL=http://127.0.0.1:8188
```

`H3_COMFYUI_URL` 指运行 MiniMax H3 Reference to Video（Ref2VA）工作流的 ComfyUI 实例地址。SKILL.md 第 3 步的模式检测读不到该变量时走静态立绘流程，不进入本流水线。运行前可用 `curl -m 3 -s "$H3_COMFYUI_URL/system_stats"` 探活；连不上时提醒用户启动 ComfyUI。

最终分层顺序：

```text
clean-plate（确定性菜单 / 数据 / 背景）
  ↓
H3 presenter foreground（小雨、头发、手臂、手指）
  ↓
deterministic captions / callouts（可选）
  ↓
H3 native audio
```

## 镜头包

每个 H3 镜头必须独立保存以下文件，不要只保留一张压平图：

```text
<project>/h3-scenes/<scene-id>/
├── references/
│   ├── combined-reference.png  # Picture 1：小雨 + 舞台，供 H3 理解构图
│   ├── clean-plate.png         # 完全相同的舞台，但没有小雨，供最终恢复
│   └── character-reference.png # 可选 Picture 2：小雨身份锚点
├── h3-prompt.txt
└── scene.json
```

`combined-reference.png` 与 `clean-plate.png` 必须来自同一个 article-to-video 场景、尺寸一致、文字和数据位置一致。用渲染模板的 stills 模式成对导出（每场景取中后段一帧，clean-plate 只隐藏立绘图层、硬车道布局保持不变，两张图逐像素对齐）：

```bash
node ~/.ethan/skills/article-to-video/assets/open-motion-template/render.mjs \
  stills "$PROJECT/timeline.json" "$PROJECT/refs" "$PROJECT/work/public"
# 产出 $PROJECT/refs/<scene-id>-combined.png 与 <scene-id>-clean-plate.png
```

## 1. 准备镜头包

```bash
H3=ethan/defaults/skills/article-to-video/scripts/h3_presenter_pipeline.py

python3 "$H3" prepare \
  --scene-dir "$PROJECT/h3-scenes/kuaishou-summary" \
  --combined-reference "$PROJECT/refs/kuaishou-summary-combined.png" \
  --clean-plate "$PROJECT/refs/kuaishou-summary-clean-plate.png" \
  --character-reference "$PROJECT/refs/xiaoyu-character.png" \
  --presenter xiaoyu \
  --duration 6.5 \
  --dialogue '快手当前三十三点六四港元，估值仅八点一三倍，潜在上行还有百分之一百零九。' \
  --motion-plan $'0.0–1.5s: 小雨面对镜头微笑，摊手介绍面板。\n1.5–3.5s: 自然说话、眨眼、轻点头。\n3.5–5.5s: 连贯抬起手臂，食指指向估值卡。\n5.5–6.5s: 缓慢收手，回到安心的微笑。' \
  --screen-notes '快手全面投资分析；最新收盘价 33.64 HKD；TTM 市盈率 8.13x；目标上行空间 +109%。'
```

`--presenter` 可选：传入资产库角色 id 后，H3 prompt 的人物身份（名字、外观描述）以 `~/.ethan/assets/library/presenters/<id>/character.json` 为准；不传则用内置的「小雨」身份。动作计划多行文本用 `$'...\n...'`（ANSI-C 引用）或 `--motion-plan-file`，普通单引号不会解释 `\n`。

脚本会校验两张舞台图尺寸一致，写出 H3 Prompt 和 `scene.json`。H3 允许 4–15 秒；长视频按 5–8 秒独立镜头生成后再拼接，不要拿 H3 的尾帧直接作为下一镜头的画面事实来源。

## 2. 在 ComfyUI H3 Ref2VA 运行

打开 `H3_COMFYUI_URL` 指向的 ComfyUI 实例，在 `MiniMax H3 Reference to Video` 工作流中：

- Load Image 1 = `combined-reference.png`
- Load Image 2 = `character-reference.png`（没有第二图时仅连接第一图）
- Prompt = `h3-prompt.txt`
- 固定镜头，24fps，4–15 秒；建议先使用 0.6MP（约 1056×608）验证动作。

生成的 `raw-h3.mp4` 是人物表现的原始层。即使 H3 在画面里把中文改错，也不要返工菜单；下一步会由 Clean Plate 复原。

## 3. 制作人物前景遮罩

生产模式需要与 `raw-h3.mp4` 同帧数的灰度遮罩视频：

- 白色 = 小雨前景（头发、身体、袖子、手掌、手指）
- 黑色 = 舞台
- 灰色 = 抗锯齿边缘

建议用 SAM 2 / RVM / AE Roto Brush 跟踪「小雨全身」，而不是只框脸或身体。手臂和手指要包含在白色区域中，这样小雨能把手指伸到价格卡或图表前方。

`safe-boundary` 是无遮罩时的快速模式：它只覆盖左侧菜单，适用于人物始终在右侧车道、手不深入内容区的镜头。它不能替代人物遮罩。

## 4. 合成最终镜头

生产模式（推荐）：

```bash
python3 "$H3" compose \
  --scene-dir "$PROJECT/h3-scenes/kuaishou-summary" \
  --h3-video "$PROJECT/h3-scenes/kuaishou-summary/raw-h3.mp4" \
  --foreground-mask "$PROJECT/h3-scenes/kuaishou-summary/xiaoyu-mask.mp4" \
  --output "$PROJECT/h3-scenes/kuaishou-summary/final.mp4"
```

快速边界模式（仅验证期）：

```bash
python3 "$H3" compose \
  --scene-dir "$PROJECT/h3-scenes/kuaishou-summary" \
  --h3-video "$PROJECT/h3-scenes/kuaishou-summary/raw-h3.mp4" \
  --panel-edge-px 648 --feather-px 14 \
  --output "$PROJECT/h3-scenes/kuaishou-summary/final-preview.mp4"
```

输出尺寸默认取 `scene.json` 里 combined-reference 的原生尺寸（竖屏场景不再被压成 1280×720）；需要缩放时 `--width`/`--height` 必须成对传入。合成保留 H3 原生音轨，输出 H.264/AAC、`yuv420p`、faststart MP4，并在旁边写入 `.composition.json` 报告。

## 验收

```bash
python3 "$H3" verify \
  --scene-dir "$PROJECT/h3-scenes/kuaishou-summary" \
  --h3-video "$PROJECT/h3-scenes/kuaishou-summary/raw-h3.mp4"
```

人工复核：

- 菜单、中文、数字、图表全程稳定且与 clean plate 一致；
- 手指穿过菜单时位于菜单前景，边缘没有黑边/白边/闪烁；
- 眼睛、手、手臂没有重复或畸形；
- H3 语音为中文，音轨存在且与口型基本同步；
- 输出尺寸与 combined-reference 一致（或显式 `--width`/`--height` 覆盖值），帧率跟随 H3 源视频（建议 24fps）。
