#!/usr/bin/env python3
"""图片智能切割 — 按 x/y 网格切割图片，在空白间隙处分割避免切到文字。

Usage:
    python3 image_split.py <image_path> [--x N] [--y N] [--output-dir DIR]

依赖：Pillow (PIL)
"""
import argparse
import sys
from pathlib import Path

try:
    import numpy as np
    from PIL import Image
except ImportError:
    print("错误：需要 Pillow 和 numpy。请运行：pip3 install Pillow numpy", file=sys.stderr)
    sys.exit(1)


def find_best_split(arr_slice, target_pos: int, search_range: int = 200, min_gap: int = 3) -> int:
    """在 target_pos 附近 ±search_range 内搜索最佳空白分割线。

    arr_slice: 1D array，每个元素是对应行/列的像素标准差
    target_pos: 理想分割位置
    search_range: 搜索范围（像素）
    min_gap: 最小连续空白行/列数

    返回最佳分割位置（原始坐标）。
    """
    start = max(0, target_pos - search_range)
    end = min(len(arr_slice), target_pos + search_range)

    # 空白阈值：std < 5 视为空白
    threshold = 5
    blank = arr_slice[start:end] < threshold

    # 搜索最靠近 target_pos 的连续空白段
    best_pos = target_pos
    best_dist = float('inf')
    relative_target = target_pos - start

    i = 0
    while i < len(blank):
        if blank[i]:
            j = i
            while j < len(blank) and blank[j]:
                j += 1
            if j - i >= min_gap:
                mid = (i + j) // 2
                dist = abs(mid - relative_target)
                if dist < best_dist:
                    best_dist = dist
                    best_pos = mid + start
            i = j
        else:
            i += 1

    return best_pos


def compute_row_std(img: Image.Image) -> "np.ndarray":
    """计算每行的像素标准差。"""
    arr = np.array(img)
    if arr.ndim == 3:
        return arr.std(axis=(1, 2))
    return arr.std(axis=1)


def compute_col_std(img: Image.Image) -> "np.ndarray":
    """计算每列的像素标准差。"""
    arr = np.array(img)
    if arr.ndim == 3:
        return arr.std(axis=(0, 2))
    return arr.std(axis=0)


def split_image(image_path: str, x_splits: int, y_splits: int, output_dir: str | None = None):
    """切割图片。

    x_splits: 水平方向切割成多少列（0 或 1 表示不切）
    y_splits: 垂直方向切割成多少行（0 或 1 表示不切）
    """
    img = Image.open(image_path)
    w, h = img.size
    src = Path(image_path)
    stem = src.stem
    suffix = src.suffix or ".png"
    out_dir = Path(output_dir) if output_dir else src.parent
    out_dir.mkdir(parents=True, exist_ok=True)

    # 规范化：0 和 1 都表示不切
    cols = max(x_splits, 1)
    rows = max(y_splits, 1)

    if cols == 1 and rows == 1:
        print("x=0/1 且 y=0/1，无需切割。", file=sys.stderr)
        sys.exit(1)

    # 计算垂直分割线位置
    y_positions = [0]
    if rows > 1:
        row_std = compute_row_std(img)
        for i in range(1, rows):
            ideal = int(h * i / rows)
            best = find_best_split(row_std, ideal)
            y_positions.append(best)
    y_positions.append(h)

    # 计算水平分割线位置
    x_positions = [0]
    if cols > 1:
        col_std = compute_col_std(img)
        for i in range(1, cols):
            ideal = int(w * i / cols)
            best = find_best_split(col_std, ideal)
            x_positions.append(best)
    x_positions.append(w)

    # 切割并保存
    results = []
    for ri in range(rows):
        for ci in range(cols):
            left = x_positions[ci]
            right = x_positions[ci + 1]
            top = y_positions[ri]
            bottom = y_positions[ri + 1]

            crop = img.crop((left, top, right, bottom))
            if rows > 1 and cols > 1:
                name = f"{stem}_r{ri+1}_c{ci+1}{suffix}"
            elif rows > 1:
                name = f"{stem}_{ri+1}{suffix}"
            else:
                name = f"{stem}_{ci+1}{suffix}"

            out_path = out_dir / name
            crop.save(str(out_path))
            results.append((str(out_path), right - left, bottom - top))

    # 输出结果
    print(f"切割完成：{cols}×{rows} = {len(results)} 片")
    for path, cw, ch in results:
        print(f"  {path} ({cw}x{ch})")


def main():
    parser = argparse.ArgumentParser(description="图片智能切割")
    parser.add_argument("image", help="源图片路径")
    parser.add_argument("--x", type=int, default=0, help="水平切割数（列数，默认 0 不切）")
    parser.add_argument("--y", type=int, default=2, help="垂直切割数（行数，默认 2）")
    parser.add_argument("--output-dir", help="输出目录（默认与源图片同目录）")
    args = parser.parse_args()

    if not Path(args.image).exists():
        print(f"错误：文件不存在 {args.image}", file=sys.stderr)
        sys.exit(1)

    split_image(args.image, args.x, args.y, args.output_dir)


if __name__ == "__main__":
    main()
