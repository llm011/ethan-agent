---
name: image-split
description: "将图片按网格切割成多段。支持水平（x）和垂直（y）切割，智能在空白间隙处分割避免切到文字。适用于长截图拆分、图片分片等场景。"
trigger: "切割图片|图片切割|切成两半|切成多段|split image|图片太长"
version: 1.0.0
display_name: 图片智能切割
platforms: [macos, linux]
metadata:
  openclaw:
    requires:
      bins:
        - python3
---

# 图片智能切割

将图片按 x/y 网格切割成多段，智能在空白间隙处分割，避免切到文字内容。

## 参数说明

- `image_path`：源图片路径（必需）
- `x`：水平切割数（默认 0，即不做水平切割）
- `y`：垂直切割数（默认 2，即上下切成两半）
- `output_dir`：输出目录（默认与源图片同目录）

## 切割逻辑

- `x=0, y=2`：垂直方向切成 2 段（上半 + 下半）
- `x=2, y=0`：水平方向切成 2 段（左半 + 右半）
- `x=2, y=3`：切成 2×3 = 6 块

切割时会在目标分割线附近搜索空白区域（像素方差低的行/列），优先在空白间隙处切割。

## 调用方式

```bash
python3 ~/.ethan/skills/image-split/scripts/image_split.py <image_path> [--x N] [--y N] [--output-dir DIR]
```

## 输出

切割结果保存在源图片同目录（或指定目录），命名格式：`{原名}_r{行}_c{列}.png`。
如 y=2 时输出 `talk_r1_c1.png` 和 `talk_r2_c1.png`。

脚本 stdout 输出每个切片的路径和尺寸信息。
