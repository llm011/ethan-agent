# 虚拟人角色包制作指南（GPT image 2 手动流程）

article-to-video 的虚拟人是「静态立绘 + 微动效」（入场弹簧、呼吸浮动、姿势切换交叉淡化），**不做唇形同步**。立绘图片由用户用 GPT image 2 手动生成，`presenter_gen.py` 负责出 prompt、导入、抠图、建角色包。

## 完整流程

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

## 一致性策略（重要）

1. **角色表锁定**：`prompts` 输出的所有姿势共享同一段角色描述（发型/瞳色/服装/配色），逐字粘贴，不要改写
2. **同一个 GPT image 2 会话**：先生成第一个姿势（standing），然后把这张图**传回该会话**作为参考，逐张说"同一角色、同样的脸/发型/服装，换成 XX 姿势"。会话内参考图编辑是 GPT image 2 一致性最强的手段
3. 某个姿势不满意用 `regen` 单独重来，不要整套重出

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
