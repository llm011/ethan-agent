# 虚拟人角色包制作指南（GPT image 2 手动流程）

article-to-video 的虚拟人是「静态立绘 + 微动效」（入场弹簧、呼吸浮动、姿势切换交叉淡化），配可选的 blink/talk 面部变体实现眨眼与说话口型（确定性调度 + 短交叉淡化，不是逐帧唇形同步）。立绘图片由用户用 GPT image 2 手动生成，`presenter_gen.py` 负责出 prompt、导入、抠图、建角色包。

## 推荐流程：单张设定集（角色零漂移）

一张图把**全部姿势 + 默认姿势的 blink/talk 变体**画成网格面板，同一次生成角色必然一致——彻底杜绝"每个姿势单独出图、脸和衣服对不上"的漂移问题：

```bash
GEN=ethan/defaults/skills/article-to-video/scripts/presenter_gen.py

# 1. 打印设定集 prompt（同时写入 pending 状态的 character.json）
python3 $GEN prompts xiaoyu --sheet

# 2. 用该 prompt 在 GPT image 2 出一张图（8 面板 3x3 网格），存为 sheet.png

# 3. 自动切分面板 + 变体对齐入库
python3 $GEN import-sheet xiaoyu sheet.png   --order standing,standing-blink,standing-talk,explaining,pointing,smiling,thinking,celebrating
```

`import-sheet` 做的事：

- **面板切分**：背景泛洪 → 前景连通域 → 阅读顺序（左→右、上→下）；被泛洪切开的手臂等小碎片会就近并回所属面板
- **变体对齐**：blink/talk 面板做 scale+平移 SSD 对齐（numpy 加速，缺失则原样粘贴），与基础姿势合成**同尺寸画布**；渲染端切换带 2 帧交叉淡化，1px 级对齐残差不会硬闪
- 切分数量与 `--order` 对不上时报面板诊断（面板粘连 → 重新出图并加大面板间距）
- GPT image 2 的 ChatGPT Images 2.0 支持一次生成多张角色/风格连贯的系列图，设定集网格正好吃这个能力

## 备用流程：逐姿势出图（姿势更精细时用）

```bash
GEN=ethan/defaults/skills/article-to-video/scripts/presenter_gen.py

# 1. 打印 prompt 包（同时写入 pending 状态的 character.json，锁定角色表/姿势/音色）
python3 $GEN prompts xiaoyu

# 2. 用户在 GPT image 2 里逐姿势出图（见下「一致性策略」），存到一个目录，如 ~/Downloads/xiaoyu/

# 3. 导入：匹配姿势 → 尺寸归一 → 品红底抠图 → 置 ready
python3 $GEN import xiaoyu ~/Downloads/xiaoyu/

# 4. 检查 / 单姿势重来
python3 $GEN show xiaoyu
python3 $GEN regen xiaoyu pointing   # 重新打印 pointing 的 prompt，重新出图后再 import
```

## 一致性策略（逐姿势流程，重要）

1. **角色表锁定**：`prompts` 输出的所有姿势共享同一段角色描述（发型/瞳色/服装/配色），逐字粘贴，不要改写
2. **同一个 GPT image 2 会话**：先生成第一个姿势（standing），然后把这张图**传回该会话**作为参考，逐张说"同一角色、同样的脸/发型/服装，换成 XX 姿势"。会话内参考图编辑是 GPT image 2 一致性最强的手段；即便如此，独立生成仍有轻微漂移，**优先用上面的单张设定集**
3. 某个姿势不满意用 `regen` 单独重来，不要整套重出

## 面部变体（可选：眨眼/口型）

`prompts` 输出的每个姿势后面附带两张**可选**变体 prompt（闭眼 / 张嘴说话）：

- 出图后存为 `<姿势名>-blink.png` / `<姿势名>-talk.png`（如 `standing-blink.png`），与姿势图放同一目录，`import` 自动按后缀识别入库
- 渲染端按确定性节律切换：眨眼窗约 140ms、间隔 2.2–5.5s 伪随机；有活跃字幕时以 ~110ms 拍的伪随机方波切换张嘴/闭嘴，字幕间隙自动闭嘴；变体切换带 2 帧交叉淡化（对齐残差沿轮廓的硬闪压成柔切）
- 变体是渐进增强：不出变体图、或某个姿势缺某张变体，都自动退化为静态立绘，不报错不阻塞
- 单独补某张变体：`python3 $GEN regen xiaoyu standing --variant blink` 重新打印该变体的 prompt

## 背景与抠图

- **GPT image 2 不支持透明背景**（`background: "transparent"` 报错；仅 gpt-image-1/1.5/gpt-5-image 系列支持）→ prompt 统一要求 `isolated on solid pure magenta background (#FF00FF)`
- `import` 时先做 alpha 嗅探（PNG 本身有 alpha 就直接用），无 alpha 则用 Pillow 边缘泛洪抠掉品红底
- 抠图失败不硬失败：`character.json` 标记 `cutout: false`，前端渲染为圆角卡片框样式

## 默认姿势清单

| 姿势 | 用途 |
|---|---|
| standing | 默认站姿 |
| explaining | 讲解（摊开手） |
| pointing | 指向屏幕/图表 |
| smiling | 微笑（开场/收尾） |
| thinking | 思考（抛问题） |
| celebrating | 庆祝（涨/达成） |

场景里用 `presenter: {"pose": "pointing"}` 切换；`{"visible": false}` 隐藏。

## API 自动生成（可选兜底）

配置 `ETHAN_IMAGE_GEN_API_KEY`（+ 可选 `ETHAN_IMAGE_GEN_BASE_URL` / `ETHAN_IMAGE_GEN_MODEL`）后可 `python3 $GEN create xiaoyu` 自动出图。模型名匹配 `gpt-image-1*` / `gpt-5-image*` 才发 transparent 参数；其他模型（含 gpt-image-2）走品红底 prompt + 同一套抠图。
