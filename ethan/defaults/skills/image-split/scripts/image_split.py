#!/usr/bin/env python3
"""图片智能切割 — 按 x/y 网格切割或按尺寸自动切割，在空白间隙处分割避免切到文字。

Usage:
    # 手动网格切割
    python3 image_split.py <image_path> [--x N] [--y N] [--output-dir DIR]

    # 自动模式：>8000px 才切，每段目标 6000px
    python3 image_split.py <image_path> --auto [--threshold 8000] [--segment 6000] [--output-dir DIR]

依赖：Pillow (PIL)
"""
import argparse
import sys
from pathlib import Path

try:
    import numpy as np
    from PIL import Image
    Image.MAX_IMAGE_PIXELS = None  # 本工具就是处理大图的，放开 PIL 像素上限
except ImportError:
    print("错误：需要 Pillow 和 numpy。请运行：pip3 install Pillow numpy", file=sys.stderr)
    sys.exit(1)

# 最后一段短于此值则并入前一段（避免 1px 碎片，但不跳过 2000px 这种有效段）
MIN_TAIL = 100


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


def crop_and_save(img, x_positions, y_positions, stem, suffix, out_dir):
    """按指定的 x/y 位置切割并保存。

    x_positions / y_positions: 含首尾（0 和 宽/高）的位置数组。
    """
    results = []
    rows = len(y_positions) - 1
    cols = len(x_positions) - 1

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

    return results, rows, cols


def split_image(image_path: str, x_splits: int, y_splits: int, output_dir: str | None = None):
    """按 x/y 网格数切割（等分，在空白处微调）。

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

    # 计算垂直分割线位置（等分）
    y_positions = [0]
    if rows > 1:
        row_std = compute_row_std(img)
        for i in range(1, rows):
            ideal = int(h * i / rows)
            best = find_best_split(row_std, ideal)
            y_positions.append(best)
    y_positions.append(h)

    # 计算水平分割线位置（等分）
    x_positions = [0]
    if cols > 1:
        col_std = compute_col_std(img)
        for i in range(1, cols):
            ideal = int(w * i / cols)
            best = find_best_split(col_std, ideal)
            x_positions.append(best)
    x_positions.append(w)

    results, rows_n, cols_n = crop_and_save(img, x_positions, y_positions, stem, suffix, out_dir)

    # 输出结果
    print(f"切割完成：{cols}×{rows} = {len(results)} 片")
    for path, cw, ch in results:
        print(f"  {path} ({cw}x{ch})")


def auto_split(image_path: str, threshold: int = 8000, segment_size: int = 6000, output_dir: str | None = None):
    """按尺寸自动判断是否切割。

    - 宽和高均 ≤ threshold：不切
    - 超过 threshold 的维度：按 segment_size 间距切，最后一段太短（< segment_size/2）则并入前一段
    """
    img = Image.open(image_path)
    w, h = img.size
    src = Path(image_path)
    stem = src.stem
    suffix = src.suffix or ".png"
    out_dir = Path(output_dir) if output_dir else src.parent
    out_dir.mkdir(parents=True, exist_ok=True)

    split_y = h > threshold
    split_x = w > threshold

    if not split_x and not split_y:
        print(f"图片尺寸 {w}x{h}，均不超过 {threshold}px，无需切割。")
        return

    # 计算垂直分割线（按 segment_size 间距，最后一段太短则跳过）
    y_positions = [0]
    if split_y:
        row_std = compute_row_std(img)
        pos = segment_size
        while pos < h:
            remaining = h - pos
            if remaining < MIN_TAIL:
                # 剩余太短，并入最后一段
                break
            best = find_best_split(row_std, pos)
            # 防止和上一个分割点重合
            if best <= y_positions[-1]:
                best = y_positions[-1] + 1
            y_positions.append(best)
            pos += segment_size
    y_positions.append(h)

    # 计算水平分割线（同上）
    x_positions = [0]
    if split_x:
        col_std = compute_col_std(img)
        pos = segment_size
        while pos < w:
            remaining = w - pos
            if remaining < MIN_TAIL:
                break
            best = find_best_split(col_std, pos)
            if best <= x_positions[-1]:
                best = x_positions[-1] + 1
            x_positions.append(best)
            pos += segment_size
    x_positions.append(w)

    results, rows_n, cols_n = crop_and_save(img, x_positions, y_positions, stem, suffix, out_dir)

    dirs = []
    if split_y:
        dirs.append(f"高 {h}> {threshold}")
    if split_x:
        dirs.append(f"宽 {w} > {threshold}")
    print(f"自动切割完成：{w}x{h}（{', '.join(dirs)}）→ {cols_n}×{rows_n} = {len(results)} 片"
          f"（threshold={threshold}, segment={segment_size}）")
    for path, cw, ch in results:
        print(f"  {path} ({cw}x{ch})")


def main():
    parser = argparse.ArgumentParser(description="图片智能切割")
    parser.add_argument("image", help="源图片路径")
    parser.add_argument("--x", type=int, default=0, help="水平切割数（列数，默认 0 不切）")
    parser.add_argument("--y", type=int, default=2, help="垂直切割数（行数，默认 2）")
    parser.add_argument("--auto", action="store_true",
                        help="自动模式：尺寸超过 threshold 才切，每段目标 segment px")
    parser.add_argument("--threshold", type=int, default=8000,
                        help="自动模式触发阈值（默认 8000，≤ 此值不切）")
    parser.add_argument("--segment", type=int, default=6000,
                        help="自动模式每段目标尺寸（默认 6000）")
    parser.add_argument("--output-dir", help="输出目录（默认与源图片同目录）")
    args = parser.parse_args()

    if not Path(args.image).exists():
        print(f"错误：文件不存在 {args.image}", file=sys.stderr)
        sys.exit(1)

    if args.auto:
        auto_split(args.image, args.threshold, args.segment, args.output_dir)
    else:
        split_image(args.image, args.x, args.y, args.output_dir)


if __name__ == "__main__":
    main()
