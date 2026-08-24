#!/usr/bin/env python3
"""presenter_gen.py — article-to-video 虚拟人角色包管理。

角色包 = ~/.ethan/assets/library/presenters/<id>/ 下的 character.json + poses/*.png，
跨视频项目复用（虚拟 IP）。主路径是手动出图：

  1. prompts  打印一整套可直接粘贴的 prompt（角色表 + 逐姿势 prompt + 同会话参考图指引），
              同时把锁定的角色表写入 character.json（status=pending）
  2. 用户在自己的 GPT image 2 会话里出图（先生成姿势 1，再把它传回同一会话做参考逐张换姿势）
  3. import   导入图片目录：尺寸归一 → alpha 嗅探 → 无 alpha 则 Pillow 抠品红底 → status=ready

更省事的单图路径（推荐，杜绝角色漂移）：prompts --sheet 打印"设定集"prompt
（一张图出全部姿势 + 默认姿势变体，同一次生成角色必然一致），import-sheet
自动切分面板并把变体对齐到基础图同尺寸画布（渲染端短交叉淡化切换，零硬闪）。

可选兜底：create 子命令在配了 ETHAN_IMAGE_GEN_* 时走 OpenAI 兼容端点自动生成
（仅 gpt-image-1*/gpt-5-image* 支持 transparent 背景；GPT image 2 等走品红底 + 抠图）。

纯标准库；仅抠图/缩放需要 Pillow（缺失时自动 pip 安装，装不上则 cutout=false 降级，
前端用圆角卡片框渲染，不硬失败）。
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import shutil
import struct
import subprocess
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
TIMEOUT = 180
MAX_EDGE = 1536
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp"}
ID_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")

# 默认角色属性与姿势短语都是英文：图像模型对英文 prompt 遵循度更高。
DEFAULT_DESCRIPTION = (
    "long dark brown hair, warm brown eyes, white floral blouse with a large bow tie, "
    "soft warm color palette, confident subtle smile"
)
DEFAULT_VOICE = {"name": "zh-CN-XiaoyiNeural", "rate": "+0%", "volume": "+0%", "pitch": "+0Hz"}
DEFAULT_POSES: dict[str, str] = {
    "standing": "standing with hands naturally folded in front, gentle confident smile",
    "explaining": "one hand raised with open palm as if explaining something",
    "pointing": "right hand raised pointing toward the left side, as if pointing at a chart",
    "smiling": "bright cheerful smile with a slight head tilt",
    "thinking": "one finger on chin, thoughtful curious expression",
    "celebrating": "both fists raised slightly in celebration, big happy smile",
}
SHEET_TEMPLATE = (
    "Japanese anime style, half-body portrait illustration of an attractive young woman "
    "financial news presenter, {description}, front three-quarter view, clean cel shading, "
    "crisp edges, upper body centered with headroom, isolated on solid pure magenta "
    "background (#FF00FF), flat uniform background, no text, no watermark, no logo"
)
# 支持 background:"transparent" 的模型前缀（GPT image 2 会拒绝该参数，不能发）。
TRANSPARENT_MODEL_PREFIXES = ("gpt-image-1", "gpt-5-image")

# 面部变体（可选"活人感"素材）：每个姿势可再出 blink/talk 两张变体图，
# 渲染端按确定性节律切换（带短交叉淡化），实现眨眼与说话口型。变体是可选的——
# 缺了就退化为静态立绘，不阻塞任何流程。
POSE_VARIANTS: dict[str, str] = {
    "blink": "both eyes gently and fully closed, like a soft natural blink",
    "talk": "mouth softly open mid-sentence as if speaking, relaxed natural lip shape, eyes still open",
}
VARIANT_PROMPT_TEMPLATE = (
    "Same character as the reference image — identical face shape, hairstyle, hair color, "
    "eyes, outfit, art style, camera framing, body pose, character position and scale. "
    "Keep the solid pure magenta background (#FF00FF). Only change: {change}. "
    "Everything else stays identical. Half-body portrait, no text, no watermark."
)

# 设定集切分时小于该面积的前景连通域视为噪点丢弃（面板残渣/水印碎块）。
SHEET_MIN_COMPONENT = 1500


# ---------------------------------------------------------------------------
# 路径与配置
# ---------------------------------------------------------------------------

def data_dir() -> Path:
    override = os.environ.get("ETHAN_DATA_DIR")
    return Path(override).expanduser() if override else Path.home() / ".ethan"


def library_root() -> Path:
    return data_dir() / "assets" / "library"


def presenter_dir(presenter_id: str) -> Path:
    return library_root() / "presenters" / presenter_id


# secrets 目录解析缓存：config_value 高频调用，避免每次全量扫描磁盘（进程内解析一次）。
_secrets_cache: dict[str, str] | None = None


def _load_secrets() -> dict[str, str]:
    """扫 ~/.ethan/.secrets/ 下所有文件的 KEY=value（镜像 secrets_store 格式），首个命中优先。"""
    global _secrets_cache
    if _secrets_cache is None:
        cache: dict[str, str] = {}
        secrets_dir = data_dir() / ".secrets"
        if secrets_dir.is_dir():
            for path in sorted(secrets_dir.iterdir()):
                if not path.is_file():
                    continue
                try:
                    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
                        stripped = line.strip()
                        if stripped.startswith("#") or "=" not in stripped:
                            continue
                        key, _, raw = stripped.partition("=")
                        if key.strip():
                            cache.setdefault(key.strip(), raw.strip().strip("'\""))
                except OSError:
                    continue
        _secrets_cache = cache
    return _secrets_cache


def config_value(name: str) -> str | None:
    """env 优先，再兜底扫 ~/.ethan/.secrets/ 下所有文件的 KEY=value（镜像 secrets_store 格式）。"""
    value = os.environ.get(name)
    if value:
        return value
    return _load_secrets().get(name)


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _validate_character(presenter_id: str, character: object) -> None:
    """character.json 字段防护：缺字段/类型不对时友好报错退出，不让裸 KeyError 冒 traceback。"""
    path = presenter_dir(presenter_id) / "character.json"

    def _fail(field: str) -> None:
        print(f"[error] character.json 缺少字段 {field}: {path}（先运行 prompts 子命令重建）", file=sys.stderr)
        raise SystemExit(1)

    if not isinstance(character, dict):
        _fail("顶层对象（JSON object）")
    name = character.get("name")
    if not isinstance(name, str) or not name.strip():
        _fail("name（非空字符串）")
    sheet = character.get("sheet")
    if not isinstance(sheet, str) or not sheet.strip():
        _fail("sheet（非空字符串）")
    poses_prompts = character.get("posesPrompts")
    if not isinstance(poses_prompts, dict) or not poses_prompts:
        _fail("posesPrompts（非空对象）")


def _load_character(presenter_id: str) -> dict:
    path = presenter_dir(presenter_id) / "character.json"
    if not path.is_file():
        raise SystemExit(f"[error] 角色不存在: {path}（先运行 prompts 子命令）")
    try:
        character = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"[error] character.json 不是合法 JSON: {exc}", file=sys.stderr)
        raise SystemExit(1) from None
    _validate_character(presenter_id, character)
    return character


def _save_character(presenter_id: str, character: dict) -> None:
    _write_json(presenter_dir(presenter_id) / "character.json", character)


# ---------------------------------------------------------------------------
# prompt 包
# ---------------------------------------------------------------------------

def build_sheet(description: str) -> str:
    return SHEET_TEMPLATE.format(description=description.strip())


def build_pose_prompt(sheet: str, pose_phrase: str, *, first: bool) -> str:
    if first:
        return f"{sheet}. Pose: {pose_phrase}."
    return (
        "Same character as the reference image — identical face, hairstyle, hair color, "
        f"eyes, outfit and art style. Keep the solid pure magenta background (#FF00FF). "
        f"Only change the pose and expression to: {pose_phrase}. Half-body portrait, no text."
    )


def build_sheet_prompt(character: dict) -> tuple[str, list[str]]:
    """设定集 prompt + 面板名清单（阅读顺序：左→右、上→下）。

    一张图出全部基础姿势 + 默认姿势（第一个姿势）的 blink/talk 变体。变体只给
    默认姿势：面板过多会掉生成质量，而默认姿势是渲染时的 defaultPose，快切最
    频繁，对齐收益最大。
    """
    poses: dict[str, str] = character["posesPrompts"]
    panels: list[tuple[str, str]] = []
    for index, (name, phrase) in enumerate(poses.items()):
        panels.append((name, phrase))
        if index == 0:
            for variant, change in POSE_VARIANTS.items():
                panels.append((f"{name}-{variant}", f"{phrase}, but with {change}"))
    cols = max(1, math.ceil(math.sqrt(len(panels))))
    rows = math.ceil(len(panels) / cols)
    described = "; ".join(
        f"row {index // cols + 1} column {index % cols + 1}: {text}" for index, (_, text) in enumerate(panels)
    )
    prompt = (
        f"{character['sheet']}. Arrange as ONE character reference sheet: the same character in "
        f"{len(panels)} separate panels in a {rows}x{cols} grid, reading order left to right then "
        f"top to bottom ({described}). Every panel shows the same character with identical face, "
        "hairstyle, outfit, art style, camera framing and character scale; generous blank space "
        "between panels; panels never touch or overlap; no text, no labels, no numbers, no "
        "borders, no grid lines, no watermark."
    )
    return prompt, [name for name, _ in panels]


def print_sheet_prompt(presenter_id: str, character: dict) -> None:
    prompt, panels = build_sheet_prompt(character)
    print(f"\n=== 角色「{character['name']}」({presenter_id}) 设定集 prompt（单张出图，推荐） ===\n")
    print("一张图出全部姿势 + 默认姿势的 blink/talk 变体：同一次生成角色必然一致，")
    print("import-sheet 会自动切分面板并把变体对齐到基础图（切换不跳）。\n")
    print(f"----- 设定集（{len(panels)} 面板）-----\n{prompt}\n")
    print("出图存为 sheet.png，然后运行：")
    print(f"  python3 {Path(__file__).resolve()} import-sheet {presenter_id} sheet.png --order {','.join(panels)}\n")
    print("面板顺序 = 阅读顺序（左→右、上→下）；切分数量对不上会报面板诊断，")
    print("按报错调整 --order 或重新出图（加大面板间距）。\n")
    print("=" * 60 + "\n")


def print_prompt_pack(presenter_id: str, character: dict) -> None:
    poses: dict[str, str] = character["posesPrompts"]
    sheet: str = character["sheet"]
    names = list(poses)
    print(f"\n=== 角色「{character['name']}」({presenter_id}) 出图 prompt 包 ===\n")
    print("操作流程（关键：全程在同一个 GPT image 2 会话里，保证角色一致）：\n")
    print(f"  1. 粘贴下面的【姿势 1 / {names[0]}】prompt，生成第一张图")
    print("  2. 满意后，把这张图发回同一个会话作为参考图，再粘贴【姿势 2】的 prompt")
    print("  3. 之后每个姿势都带上第一张参考图 + 对应 prompt，逐张生成")
    print(f"  4. 全部存进一个目录，文件名改成 <姿势名>.png（如 {names[0]}.png）")
    print(f"  5. 运行: python3 {Path(__file__).resolve()} import {presenter_id} <图片目录>\n")
    print("提示：背景必须是纯品红（#FF00FF），纯色才能自动抠图；")
    print("      某张不满意就在同会话里让它重画，或事后用 regen 子命令重打该姿势的 prompt。")
    print("可选（推荐）：每个姿势满意后再出 blink/talk 两张变体图（闭眼/张嘴说话），")
    print("      成片里会有眨眼和口型，立绘更生动。文件名 <姿势名>-blink.png / <姿势名>-talk.png；")
    print("      不出也行，导入时自动降级为静态立绘。\n")
    for index, (name, phrase) in enumerate(poses.items()):
        label = f"姿势 {index + 1} / {name}"
        prompt = build_pose_prompt(sheet, phrase, first=index == 0)
        print(f"----- {label} -----\n{prompt}\n")
        for variant, change in POSE_VARIANTS.items():
            variant_prompt = VARIANT_PROMPT_TEMPLATE.format(change=change)
            print(f"----- {label} 变体 {variant}（可选，存为 {name}-{variant}.png）-----\n{variant_prompt}\n")
    print("=" * 60 + "\n")


# ---------------------------------------------------------------------------
# PNG alpha 嗅探与抠图
# ---------------------------------------------------------------------------

def _png_header_has_alpha(path: Path) -> bool:
    """stdlib 读 PNG 头 64KB：色类型 6=RGBA、4=灰度+alpha，或 chunk 链里存在 tRNS 块。

    IHDR 固定在偏移 25，tRNS 按规范必须出现在第一个 IDAT 之前（64KB 足以覆盖），
    嗅探不必读入整文件。chunk 链按 struct 解析 4 字节长度 + 4 字节类型逐块推进
    （遇 IDAT 即停），不做 `b"tRNS" in data` 子串匹配——chunk 数据区里碰巧出现的
    tRNS 字节会误报；每步 offset 至少前进 12 字节且以 64KB 窗口为界，畸形长度
    不会死循环。非 PNG 返回 False。
    """
    try:
        with path.open("rb") as fh:
            data = fh.read(65536)
    except OSError:
        return False
    if not data.startswith(b"\x89PNG\r\n\x1a\n") or len(data) < 33:
        return False
    if data[25] in (4, 6):
        return True
    offset = 8  # 跳过 8 字节签名；每个 chunk = 4B 长度 + 4B 类型 + 数据 + 4B CRC
    while offset + 8 <= len(data):
        (length,) = struct.unpack_from(">I", data, offset)
        chunk_type = data[offset + 4 : offset + 8]
        if chunk_type == b"tRNS":
            return True
        if chunk_type == b"IDAT":
            return False
        offset += 12 + length
    return False


def png_has_alpha(path: Path) -> bool:
    """PNG 是否真的带透明：头部判定 + Pillow 像素级验证。

    头部有 alpha 只是必要条件——RGBA 但全不透明的图会被误判已抠图，品红底
    直接进成片。Pillow 可导入且图片能打开时，用 alpha 通道最小值 < 255 验证
    确实存在透明像素；Pillow 不可用或图片打不开时保守沿用头部判定。
    """
    if not _png_header_has_alpha(path):
        return False
    try:
        from PIL import Image
    except ImportError:
        return True
    try:
        with Image.open(path) as img:
            # convert("RGBA") 兼容 P 模式带 tRNS（调色板透明色真正落到像素上）。
            return img.convert("RGBA").getchannel("A").getextrema()[0] < 255
    except Exception:  # noqa: BLE001 — 打不开/读不了时保守沿用头部判定
        return True


def _is_valid_image(path: Path) -> bool:
    """断点续跑前的产物校验：文件存在、size>0，且 Pillow 能 open+verify。任何异常返回 False。"""
    try:
        if not path.is_file() or path.stat().st_size <= 0:
            return False
    except OSError:
        return False
    try:
        from PIL import Image
    except ImportError:
        # Pillow 缺失做不了深度校验：宁可保守认为已生成的图有效（重新生图有
        # API 费用），不能把用户已生成的姿势图全删了重来。
        return True
    try:
        with Image.open(path) as img:
            img.verify()
        return True
    except Exception:  # noqa: BLE001
        return False


def _pip_install(*packages: str) -> bool:
    print(f"  [info] 安装依赖 {' '.join(packages)} ...", file=sys.stderr)
    in_venv = sys.prefix != getattr(sys, "base_prefix", sys.prefix)
    cmd = [sys.executable, "-m", "pip", "install", "--quiet", *([] if in_venv else ["--user"]), *packages]
    try:
        subprocess.check_call(cmd, timeout=300)
        import site

        user_site = site.getusersitepackages()
        if user_site not in sys.path:
            sys.path.append(user_site)
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"  [warn] 自动安装失败: {exc}", file=sys.stderr)
        return False


def _pillow():
    for attempt in range(2):
        try:
            from PIL import Image

            return Image
        except ImportError:
            if attempt == 0 and _pip_install("pillow"):
                continue
            return None
    return None


def _match_mask(raw: bytes, pixel_count: int, key: tuple[int, ...], tolerance_sq: int) -> bytearray:
    """背景色匹配掩码：dr²+dg²+db² ≤ tolerance² 的像素置 1。

    有 numpy 时向量化（1536² 图从 ~2s 降到 ~20ms），没有则回退逐像素循环；
    numpy 不做自动安装——它只是加速件，不是功能依赖。
    """
    try:
        import numpy as np
    except ImportError:
        np = None
    if np is not None:
        rgb = np.frombuffer(raw, dtype=np.uint8).reshape(pixel_count, 4)[:, :3].astype(np.int32)
        diff = rgb - np.array(key, dtype=np.int32)
        return bytearray(np.asarray((diff * diff).sum(axis=1) <= tolerance_sq, dtype=np.uint8).tobytes())
    matches = bytearray(pixel_count)
    kr, kg, kb = key
    for i in range(pixel_count):
        offset = i * 4
        dr = raw[offset] - kr
        dg = raw[offset + 1] - kg
        db = raw[offset + 2] - kb
        if dr * dr + dg * dg + db * db <= tolerance_sq:
            matches[i] = 1
    return matches


def _edge_background_key(img) -> tuple[int, int, int]:
    """四边等距采样取每通道中位色，作为泛洪背景 key（对 JPEG 边缘噪声稳）。"""
    width, height = img.size
    pixels = img.load()
    step_x = max(1, width // 60)
    step_y = max(1, height // 60)
    samples = []
    for x in range(0, width, step_x):
        samples.append(pixels[x, 0][:3])
        samples.append(pixels[x, height - 1][:3])
    for y in range(0, height, step_y):
        samples.append(pixels[0, y][:3])
        samples.append(pixels[width - 1, y][:3])
    return tuple(sorted(c[i] for c in samples)[len(samples) // 2] for i in range(3))  # type: ignore[return-value]


def _flood_background(width: int, height: int, matches: bytearray) -> bytearray:
    """从四边 BFS 出与边缘连通的背景掩码（1=背景）。

    入队即标记 visited 并预过滤非背景：出队的不必是合法背景像素。
    队列长度 = 背景连通域大小（旧写法每像素最多入队 4 次再靠出队去重）。
    """
    visited = bytearray(width * height)
    border: list[int] = []
    for x in range(width):
        border.extend((x, x + (height - 1) * width))
    for y in range(height):
        border.extend((y * width, width - 1 + y * width))
    queue: list[int] = []
    for index in border:
        if not visited[index] and matches[index]:
            visited[index] = 1
            queue.append(index)
    head = 0
    while head < len(queue):
        index = queue[head]
        head += 1
        x, y = index % width, index // width
        if x > 0 and not visited[index - 1] and matches[index - 1]:
            visited[index - 1] = 1
            queue.append(index - 1)
        if x < width - 1 and not visited[index + 1] and matches[index + 1]:
            visited[index + 1] = 1
            queue.append(index + 1)
        if y > 0 and not visited[index - width] and matches[index - width]:
            visited[index - width] = 1
            queue.append(index - width)
        if y < height - 1 and not visited[index + width] and matches[index + width]:
            visited[index + width] = 1
            queue.append(index + width)
    return visited


def cutout_to_png(src: Path, dst: Path, *, tolerance: int = 42, cleanup: bool = False) -> bool:
    """边缘泛洪抠图：以边缘采样色为 key，从四边 BFS 把背景像素 alpha 置 0。

    品红底（或任何近纯色底）都适用；发丝等复杂边缘可能有少量残留，动漫立绘可接受。
    白底/浅色底要把 tolerance 降到 10-15（默认 42 会把肤色/白发误判成背景），
    并配合 cleanup=True 去掉残留的小色块和外围空白。
    """
    Image = _pillow()
    if Image is None:
        return False
    try:
        img = Image.open(src).convert("RGBA")
        if max(img.size) > MAX_EDGE:
            img.thumbnail((MAX_EDGE, MAX_EDGE), Image.LANCZOS)
        width, height = img.size
        key = _edge_background_key(img)

        # 走原始字节（getdata/putdata 在 Pillow 12+ 已弃用）：匹配掩码 + BFS + putalpha。
        matches = _match_mask(img.tobytes(), width * height, key, (tolerance * 3) ** 2)
        background = _flood_background(width, height, matches)
        alpha = bytes(0 if background[index] else 255 for index in range(width * height))
        img.putalpha(Image.frombytes("L", (width, height), alpha))
        if cleanup:
            img = despeckle_alpha(img)
            img = autocrop_alpha(img)
        dst.parent.mkdir(parents=True, exist_ok=True)
        img.save(dst, "PNG")
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"  [warn] 抠图失败 {src.name}: {exc}", file=sys.stderr)
        return False


def despeckle_alpha(img, min_component: int = 600):
    """清除独立小色块：BFS 找 alpha>0 连通域，小于 min_component 的整块置透明。

    用于清理低容差泛洪后残留的卡片边框、标签角、噪点（白底设定集裁图常见）。
    阈值按立绘主体的 ~0.5% 设定，细发丝若与主体断开且小于阈值会被一并清掉。
    """
    from PIL import Image

    width, height = img.size
    alpha = img.getchannel("A").tobytes()
    out = bytearray(alpha)
    visited = bytearray(width * height)
    # 起点候选只看不透明像素：抠图后背景占大头，全图 Python 循环白扫一遍。
    # 有 numpy 用 nonzero，没有则 range + 循环内 out[start]==0 过滤（语义相同）。
    try:
        import numpy as np
    except ImportError:
        np = None
    candidates = (
        np.nonzero(np.frombuffer(alpha, dtype=np.uint8))[0].tolist() if np is not None else range(width * height)
    )
    for start in candidates:
        if visited[start] or out[start] == 0:
            continue
        component = []
        queue = [start]
        visited[start] = 1
        head = 0
        while head < len(queue):
            index = queue[head]
            head += 1
            component.append(index)
            x, y = index % width, index // width
            if x > 0 and not visited[index - 1] and out[index - 1]:
                visited[index - 1] = 1
                queue.append(index - 1)
            if x < width - 1 and not visited[index + 1] and out[index + 1]:
                visited[index + 1] = 1
                queue.append(index + 1)
            if y > 0 and not visited[index - width] and out[index - width]:
                visited[index - width] = 1
                queue.append(index - width)
            if y < height - 1 and not visited[index + width] and out[index + width]:
                visited[index + width] = 1
                queue.append(index + width)
        if len(component) < min_component:
            for index in component:
                out[index] = 0
    img.putalpha(Image.frombytes("L", (width, height), bytes(out)))
    return img


def autocrop_alpha(img, margin: int = 4):
    """按 alpha 包围盒裁掉外围空白（留 margin 边距）。"""
    bbox = img.getchannel("A").getbbox()
    if bbox is None:
        return img
    left, top, right, bottom = bbox
    left = max(0, left - margin)
    top = max(0, top - margin)
    right = min(img.width, right + margin)
    bottom = min(img.height, bottom + margin)
    return img.crop((left, top, right, bottom))


def normalize_image(src: Path, dst: Path) -> bool:
    """已带 alpha 的图：仅做尺寸归一后转 PNG；无 Pillow 时原样拷贝。"""
    Image = _pillow()
    if Image is None:
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        return True
    try:
        img = Image.open(src)
        if max(img.size) > MAX_EDGE:
            img.thumbnail((MAX_EDGE, MAX_EDGE), Image.LANCZOS)
        dst.parent.mkdir(parents=True, exist_ok=True)
        img.save(dst, "PNG")
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"  [warn] 图片处理失败 {src.name}: {exc}", file=sys.stderr)
        return False


# ---------------------------------------------------------------------------
# import-sheet：单张设定集 → 自动切分面板 + 变体对齐
# ---------------------------------------------------------------------------

def _foreground_components(alpha: bytes, width: int, height: int, min_size: int) -> list[tuple[int, int, int, int]]:
    """alpha>0 连通域 → 外接框列表（未排序）。面积 < min_size 的连通域当噪点丢弃。

    纯 Python BFS（与 despeckle_alpha 同模式）：设定集导入是一次性操作，
    2MP 图几秒可接受。有 numpy 时用 nonzero 只遍历前景起点。
    """
    try:
        import numpy as np
    except ImportError:
        np = None
    candidates = (
        np.nonzero(np.frombuffer(alpha, dtype=np.uint8))[0].tolist()
        if np is not None
        else range(width * height)
    )
    visited = bytearray(width * height)
    boxes: list[tuple[int, int, int, int]] = []
    for start in candidates:
        if visited[start] or alpha[start] == 0:
            continue
        queue = [start]
        visited[start] = 1
        head = 0
        min_x = max_x = start % width
        min_y = max_y = start // width
        size = 0
        while head < len(queue):
            index = queue[head]
            head += 1
            size += 1
            x, y = index % width, index // width
            if x < min_x:
                min_x = x
            elif x > max_x:
                max_x = x
            if y < min_y:
                min_y = y
            elif y > max_y:
                max_y = y
            if x > 0 and not visited[index - 1] and alpha[index - 1]:
                visited[index - 1] = 1
                queue.append(index - 1)
            if x < width - 1 and not visited[index + 1] and alpha[index + 1]:
                visited[index + 1] = 1
                queue.append(index + 1)
            if y > 0 and not visited[index - width] and alpha[index - width]:
                visited[index - width] = 1
                queue.append(index - width)
            if y < height - 1 and not visited[index + width] and alpha[index + width]:
                visited[index + width] = 1
                queue.append(index + width)
        if size >= min_size:
            boxes.append((min_x, min_y, max_x + 1, max_y + 1))
    return boxes


def _merge_fragments(
    boxes: list[tuple[int, int, int, int]], *, gap: int = 110, ratio: float = 0.35
) -> list[tuple[int, int, int, int]]:
    """小碎片并入邻近大面板：抬手/张开手臂的姿势常被背景泛洪切成身体 + 手臂
    两块（间隙或轮廓断线）。碎片特征是尺寸远小于面板（max 边 < ratio×目标
    max 边）且紧挨着某个大面板（bbox 间隙 < gap 或相交）；真面板之间尺寸相
    近、间距大，不会被误并。小并大、就近优先，迭代到稳定。
    """
    def _bbox_gap(a, b) -> int:
        dx = max(b[0] - a[2], a[0] - b[2], 0)
        dy = max(b[1] - a[3], a[1] - b[3], 0)
        return max(dx, dy)

    def _max_edge(b) -> int:
        return max(b[2] - b[0], b[3] - b[1])

    merged = [list(b) for b in boxes]
    changed = True
    while changed:
        changed = False
        merged.sort(key=lambda b: (b[2] - b[0]) * (b[3] - b[1]))
        for index, small in enumerate(merged):
            best: tuple[int, int] | None = None  # (gap, 目标下标)
            for other in range(len(merged)):
                if other == index:
                    continue
                big = merged[other]
                if _max_edge(small) >= ratio * _max_edge(big):
                    continue  # 尺寸相近 → 是对面板，不是碎片
                g = _bbox_gap(small, big)
                if g < gap and (best is None or g < best[0]):
                    best = (g, other)
            if best is not None:
                big = merged[best[1]]
                big[0], big[1] = min(big[0], small[0]), min(big[1], small[1])
                big[2], big[3] = max(big[2], small[2]), max(big[3], small[3])
                merged.pop(index)
                changed = True
                break
    return [tuple(b) for b in merged]  # type: ignore[return-value]


def _reading_order(boxes: list[tuple[int, int, int, int]]) -> list[tuple[int, int, int, int]]:
    """阅读顺序排序：按垂直重叠分行（重叠 > 30% 面板高算同行），行内按 x。

    不按绝对 y 排：生成模型经常把同一行的面板画得一高一低。
    """
    rows: list[list[tuple[int, int, int, int]]] = []
    for box in sorted(boxes, key=lambda b: b[1]):
        if rows:
            row = rows[-1]
            row_top = min(b[1] for b in row)
            row_bottom = max(b[3] for b in row)
            overlap = min(row_bottom, box[3]) - max(row_top, box[1])
            if overlap > 0.3 * (box[3] - box[1]):
                row.append(box)
                continue
        rows.append([box])
    ordered: list[tuple[int, int, int, int]] = []
    for row in rows:
        ordered.extend(sorted(row, key=lambda b: b[0]))
    return ordered


def split_sheet(src: Path, *, tolerance: int = 42) -> list[tuple[tuple[int, int, int, int], object]]:
    """设定集大图 → [(bbox, 带前景 alpha 的 RGBA 裁剪图)]，阅读顺序（左→右、上→下）。

    背景判定：PNG 自带真 alpha 直接用 alpha 通道；否则边缘泛洪（品红底）。
    前景连通域 = 各面板角色；小碎片（被泛洪切开的手臂等）就近并入大面板。
    bbox 保留设定集坐标系——同组姿势/变体共享坐标系，是后续对齐的基础。
    """
    Image = _pillow()
    if Image is None:
        raise SystemExit("[error] 设定集切分需要 Pillow（pip install pillow）")
    if not src.is_file():
        raise SystemExit(f"[error] 设定集图片不存在: {src}")
    try:
        img = Image.open(src).convert("RGBA")
    except Exception as exc:  # noqa: BLE001
        raise SystemExit(f"[error] 设定集图片无法打开: {src} ({exc})") from None
    if max(img.size) > 2048:
        img.thumbnail((2048, 2048), Image.LANCZOS)
    width, height = img.size
    if png_has_alpha(src):
        raw_alpha = img.getchannel("A").tobytes()
        alpha = bytes(255 if value >= 128 else 0 for value in raw_alpha)
    else:
        key = _edge_background_key(img)
        matches = _match_mask(img.tobytes(), width * height, key, (tolerance * 3) ** 2)
        background = _flood_background(width, height, matches)
        alpha = bytes(0 if background[index] else 255 for index in range(width * height))
    panels: list[tuple[tuple[int, int, int, int], object]] = []
    components = _merge_fragments(_foreground_components(alpha, width, height, SHEET_MIN_COMPONENT))
    for x0, y0, x1, y1 in _reading_order(components):
        crop = img.crop((x0, y0, x1, y1))
        mask = b"".join(alpha[y * width + x0 : y * width + x1] for y in range(y0, y1))
        crop.putalpha(Image.frombytes("L", (x1 - x0, y1 - y0), mask))
        panels.append(((x0, y0, x1, y1), crop))
    return panels


def _ssd_at(base_rgb, base_a, var_rgb, var_a, dx: int, dy: int, *, min_overlap: float):
    """平移 (dx,dy) 处的重叠加权 SSD；重叠太小返回 None。

    约定：variant(x - dx, y - dy) ≈ base(x, y)，即变体内容平移 (dx,dy) 后与
    基础图重合（合成画布时直接用这个偏移）。
    """
    H, W = base_a.shape
    h, w = var_a.shape
    x0, x1 = max(0, dx), min(W, w + dx)
    y0, y1 = max(0, dy), min(H, h + dy)
    if x1 - x0 < 8 or y1 - y0 < 8:
        return None
    weight = base_a[y0:y1, x0:x1] * var_a[y0 - dy : y1 - dy, x0 - dx : x1 - dx]
    total = float(weight.sum())
    if total <= 0 or total < min_overlap:
        return None
    diff = base_rgb[y0:y1, x0:x1] - var_rgb[y0 - dy : y1 - dy, x0 - dx : x1 - dx]
    return float((weight * (diff * diff).sum(axis=2)).sum()) / total


_ALIGN_SCALES = (0.94, 0.97, 1.0, 1.03, 1.06)


def align_variant(base_img, variant_img, *, search: int = 48):
    """估计 (scale, dx, dy)：变体内容缩放 scale 倍后平移 (dx,dy) 与 base 内容像素级重合。

    两个面板都是 bbox 收紧的裁剪图，面板在设定集里的摆放位置差已被 bbox 归
    一化吸收，这里只测生成模型造成的组内漂移（小幅平移 + 缩放）。约定：
    variant 缩放后其内容平移 (dx,dy)（绕自身左上角缩放）与 base 内容重合，
    调用方据此把变体粘到「基础图 bbox 原点 + (dx,dy)」。两阶段搜索：1/4 分
    辨率粗搜（缩放 × 平移，0 为中心），全分辨率 ±6 精修。变体与基础图只差
    眼/嘴，SSD 最小值就是正确对齐。numpy 不可用返回 None（调用方退化为
    原样粘贴——仍远好于独立生成的两张图）。
    """
    try:
        import numpy as np
    except ImportError:
        return None
    from PIL import Image

    def _arrays(img, size):
        resized = img.resize(size, Image.LANCZOS) if img.size != size else img
        arr = np.asarray(resized.convert("RGBA"), dtype=np.float64)
        return arr[..., :3], arr[..., 3] / 255.0

    W, H = base_img.size
    w, h = variant_img.size
    coarse = 4
    base_rgb_c, base_a_c = _arrays(base_img, (max(8, W // coarse), max(8, H // coarse)))
    threshold_c = 0.05 * min(float(base_a_c.sum()), float(base_a_c.size))
    best: tuple[float, float, int, int] | None = None
    radius = max(4, search // coarse)
    center_x = center_y = 0  # 漂移围绕 0 搜索：bbox 归一化后面板位置差已吸收
    for scale in _ALIGN_SCALES:
        vw = max(8, int(w * scale / coarse))
        vh = max(8, int(h * scale / coarse))
        var_rgb_c, var_a_c = _arrays(variant_img, (vw, vh))
        for dy in range(center_y - radius, center_y + radius + 1):
            for dx in range(center_x - radius, center_x + radius + 1):
                score = _ssd_at(base_rgb_c, base_a_c, var_rgb_c, var_a_c, dx, dy, min_overlap=threshold_c)
                if score is not None and (best is None or score < best[0]):
                    best = (score, scale, dx * coarse, dy * coarse)
    if best is None:
        return None
    _, scale, dx, dy = best
    # 全分辨率精修：固定 scale，在粗搜偏移附近 ±6 平移
    var_rgb, var_a = _arrays(variant_img, (max(8, int(w * scale)), max(8, int(h * scale))))
    base_rgb, base_a = _arrays(base_img, (W, H))
    threshold = 0.05 * min(float(base_a.sum()), float(var_a.sum()))
    refined = (best[0], dx, dy)
    for oy in range(-6, 7):
        for ox in range(-6, 7):
            score = _ssd_at(base_rgb, base_a, var_rgb, var_a, dx + ox, dy + oy, min_overlap=threshold)
            if score is not None and score < refined[0]:
                refined = (score, dx + ox, dy + oy)
    return scale, refined[1], refined[2]


def _paste_on_canvas(img, x: int, y: int, size: tuple[int, int]):
    from PIL import Image

    canvas = Image.new("RGBA", size, (0, 0, 0, 0))
    canvas.paste(img, (x, y), img)
    return canvas


def _compose_pose_group(group: dict) -> dict:
    """一组姿势面板（""=基础图，其余键为变体名）→ 同尺寸画布的 RGBA 集合。

    变体先做 scale+平移对齐（align_variant），变换后的外接框与基础图外接框
    取并集作为画布——组内所有图画布完全一致，前端 contain-fit 缩放相同，
    渲染端切换零跳动（配短交叉淡化后残差也不硬闪）。画布超 MAX_EDGE 时整组等比缩放
    （组内同因子，对齐保持）。
    """
    from PIL import Image

    base_bbox, base_img = group[""]
    canvas = list(base_bbox)
    transforms: dict[str, tuple[float, float, float]] = {}
    for key, (bbox, img) in group.items():
        if key == "":
            continue
        scale, dx, dy = align_variant(base_img, img) or (1.0, 0, 0)
        # 粘贴位置 = 基础图 bbox 原点 + 漂移；变体绕自身左上角缩放后粘到这里
        px0, py0 = base_bbox[0] + dx, base_bbox[1] + dy
        px1, py1 = px0 + img.size[0] * scale, py0 + img.size[1] * scale
        canvas[0] = min(canvas[0], px0)
        canvas[1] = min(canvas[1], py0)
        canvas[2] = max(canvas[2], px1)
        canvas[3] = max(canvas[3], py1)
        transforms[key] = (scale, px0, py0)
    cx0, cy0 = int(round(canvas[0])), int(round(canvas[1]))
    cx1, cy1 = int(round(canvas[2])), int(round(canvas[3]))
    size = (max(1, cx1 - cx0), max(1, cy1 - cy0))
    out = {"": _paste_on_canvas(base_img, int(base_bbox[0] - cx0), int(base_bbox[1] - cy0), size)}
    for key, (scale, px0, py0) in transforms.items():
        w, h = group[key][1].size
        resized = group[key][1].resize(
            (max(1, int(round(w * scale))), max(1, int(round(h * scale)))), Image.LANCZOS
        )
        out[key] = _paste_on_canvas(resized, int(round(px0)) - cx0, int(round(py0)) - cy0, size)
    if max(size) > MAX_EDGE:
        ratio = MAX_EDGE / max(size)
        resized_size = (max(1, int(size[0] * ratio)), max(1, int(size[1] * ratio)))
        out = {key: img.resize(resized_size, Image.LANCZOS) for key, img in out.items()}
    return out


# ---------------------------------------------------------------------------
# import：导入用户出图
# ---------------------------------------------------------------------------

def split_variant_files(
    files: list[Path], pose_names: list[str]
) -> tuple[list[Path], dict[tuple[str, str], Path]]:
    """把 <pose>-<variant>.ext 变体文件从普通姿势候选里分离出来。

    词干精确等于某个姿势名的文件优先当普通姿势（用户可能自定义出
    standing-blink 这种姿势名，此时它是姿势不是变体）；其余再按
    <pose>-<blink|talk> 拆分。不分离的话，变体文件会被后续"包含匹配"
    误配给姿势（"standing" in "standing-blink" 为真），或被"按顺序补齐"
    吃掉。"""
    pose_set = set(pose_names)
    base_files: list[Path] = []
    variant_files: dict[tuple[str, str], Path] = {}
    for path in files:
        stem = path.stem.lower()
        if stem in pose_set:
            base_files.append(path)
            continue
        matched = next(
            (
                (pose, variant)
                for pose in pose_names
                for variant in POSE_VARIANTS
                if stem == f"{pose}-{variant}"
            ),
            None,
        )
        if matched:
            variant_files[matched] = path
        else:
            base_files.append(path)
    return base_files, variant_files


def match_pose_files(
    image_dir: Path, pose_names: list[str]
) -> tuple[dict[str, Path], dict[tuple[str, str], Path]]:
    """文件名匹配姿势：精确词干 → 包含匹配 → 剩余文件按排序补齐剩余姿势。

    返回 (姿势→文件, (姿势, 变体)→文件)。变体文件先被分离出候选池，
    绝不参与姿势匹配；变体是可选的，缺了不报错。
    """
    files = sorted(p for p in image_dir.iterdir() if p.is_file() and p.suffix.lower() in IMAGE_EXTS)
    base_files, variant_files = split_variant_files(files, pose_names)
    assigned: dict[str, Path] = {}
    used: set[Path] = set()
    for name in pose_names:
        for path in base_files:
            if path not in used and path.stem.lower() == name:
                assigned[name] = path
                used.add(path)
                break
    for name in pose_names:
        if name in assigned:
            continue
        for path in base_files:
            if path not in used and name in path.stem.lower():
                assigned[name] = path
                used.add(path)
                break
    remaining_poses = [name for name in pose_names if name not in assigned]
    remaining_files = [path for path in base_files if path not in used]
    for name, path in zip(remaining_poses, remaining_files):
        assigned[name] = path
        print(f"  [info] {path.name} 按顺序匹配到姿势 {name}", file=sys.stderr)
    return assigned, variant_files


def cmd_import(presenter_id: str, image_dir: Path, *, tolerance: int = 42, cleanup: bool = False) -> None:
    character = _load_character(presenter_id)
    pose_names = list(character.get("posesPrompts") or DEFAULT_POSES)
    if not image_dir.is_dir():
        raise SystemExit(f"[error] 图片目录不存在: {image_dir}")
    assigned, variant_files = match_pose_files(image_dir, pose_names)
    missing = [name for name in pose_names if name not in assigned]
    if missing:
        raise SystemExit(f"[error] 目录里没有可匹配的图片，缺少姿势: {', '.join(missing)}")

    dest_dir = presenter_dir(presenter_id) / "poses"
    poses: dict[str, str] = {}
    all_cutout = True

    def _process(src: Path, dst: Path) -> tuple[bool, bool]:
        """单图导入：有 alpha 归一，无 alpha 抠品红底（失败原样拷贝降级）。

        返回 (处理成功, 是否抠图成功)。抠图失败不硬失败：cutout=False，
        前端用卡片框渲染。
        """
        if png_has_alpha(src):
            return normalize_image(src, dst), True
        print(f"  [info] {src.name} 无 alpha，尝试抠图 ...", file=sys.stderr)
        if cutout_to_png(src, dst, tolerance=tolerance, cleanup=cleanup):
            return True, True
        return normalize_image(src, dst), False

    for name, src in assigned.items():
        dst = dest_dir / f"{name}.png"
        ok, cut = _process(src, dst)
        if not ok:
            raise SystemExit(f"[error] 处理失败: {src}")
        all_cutout = all_cutout and cut
        poses[name] = f"poses/{name}.png"
        print(f"  [ok] {name} <- {src.name}{'' if cut else '（未抠图，卡片框降级）'}")

    # 变体是可选的：只导入目录里实际出现的变体文件
    variants: dict[str, dict[str, str]] = {}
    for (pose_name, variant), src in sorted(variant_files.items()):
        dst = dest_dir / f"{pose_name}-{variant}.png"
        ok, cut = _process(src, dst)
        if not ok:
            raise SystemExit(f"[error] 处理失败: {src}")
        all_cutout = all_cutout and cut
        variants.setdefault(pose_name, {})[variant] = f"poses/{pose_name}-{variant}.png"
        print(f"  [ok] {pose_name}-{variant} <- {src.name}")

    character["poses"] = poses
    character["variants"] = variants
    character["cutout"] = all_cutout
    character["status"] = "ready"
    character["source"] = character.get("source") or "manual"
    _save_character(presenter_id, character)
    variant_note = f"；变体: {sum(len(v) for v in variants.values())} 张" if variants else ""
    print(f"\n[ok] 角色「{character['name']}」已就绪: {presenter_dir(presenter_id)}")
    print(f"     姿势: {', '.join(poses)}{variant_note}；抠图: {'是' if all_cutout else '否（卡片框渲染）'}")
    print(f"     现在可以在 manifest 里引用: \"presenter\": {{\"id\": \"{presenter_id}\"}}")


def _parse_panel_name(name: str, pose_names: list[str]) -> tuple[str, str | None]:
    """面板名 → (姿势, 变体|None)。姿势名本身是 kebab-case，必须整体匹配。"""
    for pose in pose_names:
        if name == pose:
            return pose, None
        for variant in POSE_VARIANTS:
            if name == f"{pose}-{variant}":
                return pose, variant
    raise SystemExit(f"[error] 无法解析面板名: {name}")


def cmd_import_sheet(presenter_id: str, sheet_path: Path, *, order: list[str], tolerance: int = 42) -> None:
    """单张设定集 → 自动切分面板 + 变体对齐 → ready 角色包。

    --order 是面板名的阅读顺序清单（左→右、上→下），prompts --sheet 打印的
    提示里带现成的。变体面板与基础姿势面板同组对齐成同尺寸画布，切换
    零跳动。切分数量与 --order 不符时报面板诊断（粘连→重新出图加大间距）。
    """
    character = _load_character(presenter_id)
    pose_names = list(character.get("posesPrompts") or DEFAULT_POSES)
    valid = set(pose_names) | {f"{name}-{variant}" for name in pose_names for variant in POSE_VARIANTS}
    unknown = [name for name in order if name not in valid]
    if unknown:
        raise SystemExit(
            f"[error] --order 里的名字无法识别: {', '.join(unknown)}"
            f"（姿势: {', '.join(pose_names)}；变体: <姿势>-blink / <姿势>-talk）"
        )
    if len(order) != len(set(order)):
        raise SystemExit("[error] --order 存在重复名字")
    missing = [name for name in pose_names if name not in order]
    if missing:
        raise SystemExit(f"[error] --order 缺少基础姿势: {', '.join(missing)}")
    panels_raw = split_sheet(sheet_path, tolerance=tolerance)
    if len(panels_raw) != len(order):
        detail = ", ".join(f"{x1 - x0}x{y1 - y0}@({x0},{y0})" for (x0, y0, x1, y1), _ in panels_raw)
        raise SystemExit(
            f"[error] 设定集切出 {len(panels_raw)} 个面板，但 --order 有 {len(order)} 个名字。"
            f"面板: {detail or '（无）'}。面板粘连/数量对不上请重新出图（加大面板间距），"
            "或按实际面板增删 --order 条目"
        )
    panels = dict(zip(order, panels_raw))
    groups: dict[str, dict] = {}
    for name, panel in panels.items():
        pose, variant = _parse_panel_name(name, pose_names)
        groups.setdefault(pose, {})[variant or ""] = panel

    dest_dir = presenter_dir(presenter_id) / "poses"
    dest_dir.mkdir(parents=True, exist_ok=True)
    poses: dict[str, str] = {}
    variants: dict[str, dict[str, str]] = {}
    for pose in pose_names:
        images = _compose_pose_group(groups[pose])
        for key, img in images.items():
            name = pose if key == "" else f"{pose}-{key}"
            img.save(dest_dir / f"{name}.png", "PNG")
            print(f"  [ok] {name}（{img.size[0]}x{img.size[1]}）")
        poses[pose] = f"poses/{pose}.png"
        pose_variants = {key: f"poses/{pose}-{key}.png" for key in images if key}
        if pose_variants:
            variants[pose] = pose_variants
    character["poses"] = poses
    character["variants"] = variants
    character["cutout"] = True
    character["status"] = "ready"
    character["source"] = character.get("source") or "sheet"
    _save_character(presenter_id, character)
    total = sum(len(v) for v in variants.values())
    print(f"\n[ok] 角色「{character['name']}」已就绪: {presenter_dir(presenter_id)}")
    print(f"     姿势: {', '.join(poses)}；变体: {total} 张（已对齐同尺寸画布）；抠图: 是")
    print(f"     现在可以在 manifest 里引用: \"presenter\": {{\"id\": \"{presenter_id}\"}}")


# ---------------------------------------------------------------------------
# prompts / regen
# ---------------------------------------------------------------------------

def _validate_id(presenter_id: str) -> None:
    if not ID_RE.fullmatch(presenter_id):
        raise SystemExit(f"[error] 角色 id 必须是 kebab-case: {presenter_id}")


def _parse_pose_overrides(raw: str | None) -> dict[str, str]:
    if not raw:
        return dict(DEFAULT_POSES)
    poses: dict[str, str] = {}
    for item in raw.split(","):
        name = item.strip()
        if not name:
            continue
        if not ID_RE.fullmatch(name):
            raise SystemExit(f"[error] 姿势名必须是 kebab-case: {name}")
        if name not in DEFAULT_POSES:
            print(f"  [warn] 未知姿势 {name}，使用泛化姿势短语", file=sys.stderr)
        poses[name] = DEFAULT_POSES.get(name, f"in a {name} pose")
    if not poses:
        raise SystemExit("[error] --poses 解析后为空")
    return poses


def _new_character(presenter_id: str, args: argparse.Namespace, *, source: str | None, attribution: str) -> dict:
    """构造 pending 状态的角色元数据（prompts 手动出图 / create API 出图共用骨架）。"""
    description = (args.description or DEFAULT_DESCRIPTION).strip()
    return {
        "id": presenter_id,
        "name": args.name or presenter_id,
        "status": "pending",
        "createdAt": datetime.now().isoformat(timespec="seconds"),
        "description": description,
        "sheet": build_sheet(description),
        "posesPrompts": _parse_pose_overrides(args.poses),
        "voice": DEFAULT_VOICE,
        "poses": {},
        "cutout": True,
        "source": source,
        "attribution": attribution,
    }


def cmd_prompts(presenter_id: str, args: argparse.Namespace) -> None:
    _validate_id(presenter_id)
    existing = presenter_dir(presenter_id) / "character.json"
    if existing.is_file() and not args.force:
        raise SystemExit(f"[error] 角色 {presenter_id} 已存在（--force 可覆盖重建）")
    character = _new_character(presenter_id, args, source=None, attribution="user-generated with GPT image 2")
    _save_character(presenter_id, character)
    if getattr(args, "sheet", False):
        print_sheet_prompt(presenter_id, character)
    else:
        print_prompt_pack(presenter_id, character)


def cmd_regen(presenter_id: str, pose: str, variant: str | None = None) -> None:
    character = _load_character(presenter_id)
    poses_prompts: dict[str, str] = character.get("posesPrompts") or {}
    if pose not in poses_prompts:
        raise SystemExit(f"[error] 未知姿势 {pose}，可选: {', '.join(poses_prompts)}")
    if variant is not None:
        if variant not in POSE_VARIANTS:
            raise SystemExit(f"[error] 未知变体 {variant}，可选: {', '.join(POSE_VARIANTS)}")
        print(f"在同一会话里带上【{pose}】姿势的立绘作为参考图，粘贴：\n")
        print(VARIANT_PROMPT_TEMPLATE.format(change=POSE_VARIANTS[variant]))
        print(f"\n生成后覆盖 <图片目录>/{pose}-{variant}.png 并重新运行 import。")
        return
    print("在同一会话里带上第一张立绘参考图，粘贴：\n")
    print(build_pose_prompt(character["sheet"], poses_prompts[pose], first=False))
    print(f"\n生成后覆盖 <图片目录>/{pose}.png 并重新运行 import。")


# ---------------------------------------------------------------------------
# create：API 自动生成（可选兜底）
# ---------------------------------------------------------------------------

def _image_gen_request(prompt: str, dest: Path, *, transparent_ok: bool) -> bool:
    api_key = config_value("ETHAN_IMAGE_GEN_API_KEY")
    if not api_key:
        print("[error] 未配置 ETHAN_IMAGE_GEN_API_KEY（env 或 ~/.ethan/.secrets/）", file=sys.stderr)
        return False
    base = (config_value("ETHAN_IMAGE_GEN_BASE_URL") or "https://api.openai.com/v1").rstrip("/")
    model = config_value("ETHAN_IMAGE_GEN_MODEL") or "gpt-image-1"
    payload: dict = {"model": model, "prompt": prompt, "n": 1, "size": "1024x1536"}
    if transparent_ok:
        payload["background"] = "transparent"
        payload["output_format"] = "png"
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        f"{base}/images/generations",
        data=body,
        headers={"User-Agent": UA, "Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        item = (data.get("data") or [{}])[0]
        dest.parent.mkdir(parents=True, exist_ok=True)
        if item.get("b64_json"):
            import base64

            dest.write_bytes(base64.b64decode(item["b64_json"]))
            return True
        if item.get("url"):
            with urllib.request.urlopen(
                urllib.request.Request(item["url"], headers={"User-Agent": UA}), timeout=TIMEOUT
            ) as resp:
                dest.write_bytes(resp.read())
            return True
        print(f"  [warn] 生图响应无 b64_json/url: {str(data)[:200]}", file=sys.stderr)
        return False
    except Exception as exc:  # noqa: BLE001
        print(f"  [warn] 生图失败: {exc}", file=sys.stderr)
        return False


def cmd_create(presenter_id: str, args: argparse.Namespace) -> None:
    _validate_id(presenter_id)
    model = (config_value("ETHAN_IMAGE_GEN_MODEL") or "gpt-image-1").lower()
    transparent_ok = model.startswith(TRANSPARENT_MODEL_PREFIXES) and not model.startswith("gpt-image-2")
    if not transparent_ok:
        print(f"  [info] 模型 {model} 不支持透明背景，走品红底 + 导入抠图", file=sys.stderr)
    if not (presenter_dir(presenter_id) / "character.json").is_file() or args.force:
        _save_character(
            presenter_id, _new_character(presenter_id, args, source="api", attribution=f"generated via {model}")
        )
    character = _load_character(presenter_id)
    staging = presenter_dir(presenter_id) / "work" / "raw"
    prompts = {
        name: build_pose_prompt(character["sheet"], phrase, first=index == 0)
        for index, (name, phrase) in enumerate(character["posesPrompts"].items())
    }
    pending = []
    for name, prompt in prompts.items():
        staged = staging / f"{name}.png"
        if staged.exists() and _is_valid_image(staged):
            continue
        if staged.exists():
            # exists() 即跳过会永久跳过坏文件（0 字节/截断），先删掉再重新生成。
            print(f"  [warn] 已生成的 {name}.png 无效，删除重新生成", file=sys.stderr)
            staged.unlink()
        pending.append((name, prompt))
    if pending:
        # 逐姿势 HTTP 生图（单张最长 TIMEOUT 秒）：串行 6 张最坏 ~18 分钟，
        # 并行后总耗时 ≈ 最慢的一张。重跑安全：已存在的 dest 不进 pending。

        def _generate(item: tuple[str, str]) -> tuple[str, bool]:
            name, prompt = item
            print(f"  [info] 生成姿势 {name} ...", file=sys.stderr)
            return name, _image_gen_request(prompt, staging / f"{name}.png", transparent_ok=transparent_ok)

        with ThreadPoolExecutor(max_workers=min(4, len(pending))) as pool:
            failed = [name for name, ok in pool.map(_generate, pending) if not ok]
        if failed:
            raise SystemExit(f"[error] 姿势 {', '.join(failed)} 生成失败，可重试（已生成的会跳过）")
    cmd_import(presenter_id, staging)


# ---------------------------------------------------------------------------
# list / show
# ---------------------------------------------------------------------------

def cmd_list() -> None:
    root = library_root() / "presenters"
    if not root.is_dir():
        print(f"[ok] 还没有角色（库目录: {root}）")
        return
    rows = []
    for char_path in sorted(root.glob("*/character.json")):
        try:
            character = json.loads(char_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        poses = character.get("poses") or {}
        rows.append(
            f"  {character.get('id', char_path.parent.name):<16} "
            f"status={character.get('status', '?'):<8} "
            f"poses={len(poses):<3} cutout={character.get('cutout', '?')} "
            f"voice={(character.get('voice') or {}).get('name', '-')}"
        )
    print(f"角色库: {root}\n" + ("\n".join(rows) if rows else "  （空）"))


def cmd_show(presenter_id: str) -> None:
    character = _load_character(presenter_id)
    print(json.dumps(character, ensure_ascii=False, indent=2))
    if character.get("status") != "ready":
        print_prompt_pack(presenter_id, character)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="article-to-video 虚拟人角色包管理（GPT image 2 手动出图 + 导入）")
    sub = parser.add_subparsers(dest="command", required=True)

    def _common(p: argparse.ArgumentParser) -> None:
        p.add_argument("id", help="角色 id（kebab-case，如 xiaoyu）")
        p.add_argument("--description", help="角色外观描述（英文，覆盖默认属性）")
        p.add_argument("--poses", help="逗号分隔的姿势清单（默认 6 个标准姿势）")
        p.add_argument("--name", help="角色显示名（默认同 id）")
        p.add_argument("--force", action="store_true", help="覆盖已有角色包")

    prompts_cmd = sub.add_parser("prompts", help="打印出图 prompt 包并初始化角色（pending）")
    _common(prompts_cmd)
    prompts_cmd.add_argument(
        "--sheet", action="store_true", help="打印单张设定集 prompt（一张图出全部姿势+默认姿势变体）"
    )
    _common(sub.add_parser("create", help="可选兜底：调 OpenAI 兼容端点自动生成"))

    import_cmd = sub.add_parser("import", help="导入出图目录，抠图并置为 ready")
    import_cmd.add_argument("id")
    import_cmd.add_argument("dir", type=Path, help="图片目录（文件名按姿势名匹配）")
    import_cmd.add_argument("--tolerance", type=int, default=42,
                            help="抠图容差：品红底默认 42；白底/浅色底（设定集裁图）建议 10-15")
    import_cmd.add_argument("--cleanup", action="store_true",
                            help="抠图后去除残留小色块并按内容裁边（白底裁图建议开启）")

    sheet_cmd = sub.add_parser("import-sheet", help="导入单张设定集大图：自动切分面板并对齐变体")
    sheet_cmd.add_argument("id")
    sheet_cmd.add_argument("sheet", type=Path, help="设定集图片路径")
    sheet_cmd.add_argument("--order", required=True, help="面板名清单（阅读顺序：左→右、上→下），逗号分隔")
    sheet_cmd.add_argument("--tolerance", type=int, default=42, help="背景泛洪容差（品红底默认 42）")

    regen = sub.add_parser("regen", help="重新打印单个姿势/变体的 prompt")
    regen.add_argument("id")
    regen.add_argument("pose")
    regen.add_argument("--variant", choices=sorted(POSE_VARIANTS), help="出变体图 prompt（blink/talk）")

    sub.add_parser("list", help="列出角色库")
    show = sub.add_parser("show", help="查看角色详情")
    show.add_argument("id")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    # 所有带 id 的子命令统一做 kebab-case 校验，堵住 ../x 之类的路径逃逸
    # （此前 import/regen/show 只拿 id 拼 presenter_dir，未校验就落盘）。
    if getattr(args, "id", None) is not None:
        _validate_id(args.id)
    if args.command == "prompts":
        cmd_prompts(args.id, args)
    elif args.command == "create":
        cmd_create(args.id, args)
    elif args.command == "import":
        cmd_import(args.id, args.dir.expanduser().resolve(), tolerance=args.tolerance, cleanup=args.cleanup)
    elif args.command == "import-sheet":
        order = [name.strip() for name in args.order.split(",") if name.strip()]
        cmd_import_sheet(args.id, args.sheet.expanduser().resolve(), order=order, tolerance=args.tolerance)
    elif args.command == "regen":
        cmd_regen(args.id, args.pose, variant=getattr(args, "variant", None))
    elif args.command == "list":
        cmd_list()
    elif args.command == "show":
        cmd_show(args.id)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
