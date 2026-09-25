"""资产文件管理 — 图片/附件的本地持久化。

图片存储在 ~/.ethan/assets/images/{session_id}/{timestamp}_{idx}.{ext}
DB 只存相对路径（如 "s_20260723_abc1/1690000000_0.png"），不存 base64。
前端通过 /api/assets/images/{path} 访问。
"""
from __future__ import annotations

import base64
import hashlib
import io
import json
import logging
import os
import time
from pathlib import Path

from ethan.core.config import CONFIG_DIR

logger = logging.getLogger(__name__)

# 资产根目录
ASSETS_DIR = CONFIG_DIR / "assets"
IMAGES_DIR = ASSETS_DIR / "images"

# 长图切分阈值（高度超过此值则垂直切分，与 image-split 技能默认值一致）
_SPLIT_HEIGHT_THRESHOLD = 8000
_SPLIT_SEGMENT = 6000
# 切分结果缓存目录（按 sha256(raw) 索引，避免重复计算）
_SPLIT_CACHE_DIR = ASSETS_DIR / "image_split_cache"
# RGB565 缩略图缓存目录（低内存嵌入式设备直显用）
THUMBS_DIR = ASSETS_DIR / "thumbs"

# MIME → 扩展名
_MIME_TO_EXT: dict[str, str] = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/gif": ".gif",
    "image/webp": ".webp",
    "image/svg+xml": ".svg",
    "image/bmp": ".bmp",
}


def save_image(session_id: str, idx: int, data_b64: str, media_type: str) -> list[tuple[str, str]]:
    """将 base64 图片数据保存到本地文件，返回 [(相对路径, media_type), ...]。

    长图（高度 > 8000px）会先垂直切分为多段，每段独立保存为一个文件。
    切分后每段再走 _downscale_bytes 兜底（处理宽度超限等 edge case）。
    未切分的图片返回单元素列表，兼容旧调用方。

    落盘时自动缩放超过 API 限制（8000px）的图片，避免每轮 LLM 请求重复 decode+resize。
    缩放时保留原始格式：PNG→PNG（无损，保护截图文字），JPEG→JPEG q85（照片体积小）。

    返回的 media_type 可能与传入不同（如 PNG 缩放后仍为 PNG，但格式统一）。
    """
    raw = base64.b64decode(data_b64)

    # 先尝试垂直切分长图（返回 1 段或多段）
    segments = _split_image_vertical(raw, media_type)

    results: list[tuple[str, str]] = []
    ts = int(time.time() * 1000)  # 毫秒级时间戳
    rand = os.urandom(3).hex()    # 6 字符随机后缀防碰撞
    session_dir = IMAGES_DIR / session_id
    session_dir.mkdir(parents=True, exist_ok=True)

    for seg_idx, (seg_raw, seg_media_type) in enumerate(segments):
        # 每段独立缩放（处理宽度超限；切分后高度已 ≤ segment，通常无需再缩）
        downscaled, did_resize, out_media_type = _downscale_bytes(seg_raw, seg_media_type)
        if did_resize:
            seg_raw = downscaled
            seg_media_type = out_media_type
        ext = _MIME_TO_EXT.get(seg_media_type, ".png")
        # 多段时加 _segN 后缀，单段保持原命名
        suffix = f"_seg{seg_idx}" if len(segments) > 1 else ""
        filename = f"{ts}_{idx}_{rand}{suffix}{ext}"

        file_path = session_dir / filename
        file_path.write_bytes(seg_raw)
        results.append((f"{session_id}/{filename}", seg_media_type))

    return results


def load_image_b64(relative_path: str) -> str | None:
    """从相对路径读取图片文件，返回 base64 字符串。找不到文件返回 None。"""
    file_path = IMAGES_DIR / relative_path
    if not file_path.is_file():
        return None
    return base64.b64encode(file_path.read_bytes()).decode("ascii")


def image_file_path(relative_path: str) -> Path:
    """根据相对路径返回绝对文件路径（供 FileResponse 用）。"""
    return IMAGES_DIR / relative_path


# ── 用户头像 ──────────────────────────────────────────────────────
#
# 头像与「会话附图」分开存：附图是 sessions 的资产（~/.ethan/assets/images/<sid>/），
# 会随会话清理一起消失；头像是用户级资产，借 `_profile` 这个「伪 session」目录
# 放在同一棵树下（`images/_profile/img_avatar.png`）。
#
# 为什么必须放在 images/ 的子目录而不是根目录：唯一能服务 IMAGES_DIR 的路由是
# `/api/assets/images/{session_id}/{filename}`，路径里必须带一段 session_id；
# 而 `/api/images/{filename}` 服务的是 image_search 的下载目录 `/tmp/ethan_images/`，
# 不是这里。放在根目录会得到两条 404 的 URL（上传成功但三端都取不到图）。
# 文件名仍保留 `img_` 前缀 + 图片扩展名，与图片白名单惯例一致。

AVATAR_PREFIX = "img_avatar"
# 头像所在的「伪 session」目录名。下划线开头，不会与真实 session_id 冲突
# （session_id 形如 s_20260723_abc1）。
AVATAR_DIRNAME = "_profile"
# 头像展示尺寸很小（气泡里 28px、设置页预览 ~64px）。按视网膜屏 4x 留量、再给
# 任意 DPR 留点余量，512px 足够，也让每张头像稳定落在几十 KB。
AVATAR_MAX_DIM = 512
# 头像允许的扩展名
AVATAR_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}


def _avatar_dir() -> Path:
    """头像所在目录（`images/_profile/`）。"""
    return IMAGES_DIR / AVATAR_DIRNAME


def avatar_path() -> Path:
    """当前 profile 的头像文件路径（按扩展名在头像目录下搜索）。

    没有头像时返回一个不存在的 `img_avatar` 路径（供写入方使用），调用方用
    `avatar_url()` 判断「有没有头像」而不是这个函数的返回值。
    """
    return _find_avatar() or (_avatar_dir() / f"{AVATAR_PREFIX}.png")


def _find_avatar() -> Path | None:
    """扫描头像文件；存在多个扩展名时取修改时间最新的一个。"""
    avatar_dir = _avatar_dir()
    try:
        if not avatar_dir.is_dir():
            return None
    except OSError:
        return None
    best: Path | None = None
    for p in avatar_dir.glob(f"{AVATAR_PREFIX}.*"):
        try:
            if not p.is_file() or p.suffix.lower() not in AVATAR_EXTS:
                continue
            mtime = p.stat().st_mtime
        except OSError:
            continue
        if best is None or mtime > best.stat().st_mtime:
            best = p
    return best


def avatar_url() -> str:
    """当前 profile 的头像相对 URL（`assets/images/_profile/img_avatar.png`）。

    无头像返回空串。前缀 `assets/` 与前端 assetUrl() 拼成
    `/api/assets/images/_profile/<filename>` —— 该路由走 header/cookie/?token=
    三通道鉴权，`<img>` 标签也能直接取到。
    """
    p = _find_avatar()
    return f"assets/images/{AVATAR_DIRNAME}/{p.name}" if p else ""


def save_avatar(data: bytes, media_type: str = "") -> str:
    """保存用户头像并返回新的相对 URL。旧头像先删再写，保证目录里只有一个。

    非图片、无法解码、或解码后不是图片的数据一律拒绝（ValueError），避免把任意
    文件塞进公共静态目录。GIF/SVG 之类可能带脚本或动画的格式统一转成 PNG 存。

    Pillow 缺失时同样拒绝（而不是原样落盘）：头像落在公开可访问的静态目录里，
    「没装解码库就跳过校验」等于给任意内容开了个后门；而且 pillow 已是正式依赖，
    这种环境不在支持范围内，宁可返回 400 让用户看到明确错误。
    """
    if not data:
        raise ValueError("empty avatar data")
    if len(data) > MAX_AVATAR_BYTES:
        raise ValueError(f"avatar too large (max {MAX_AVATAR_BYTES // 1024}KB)")

    ext = _MIME_TO_EXT.get(media_type.split(";")[0].strip().lower(), "")
    if not (ext and ext in AVATAR_EXTS):
        raise ValueError("unsupported image type")

    try:
        import io as _io  # noqa: PLC0415

        from PIL import Image  # noqa: PLC0415

        img = Image.open(_io.BytesIO(data))
        img.load()  # 触发真实解码：截断/损坏文件在这里就会抛
        # 统一存 PNG：a) 一张头像只可能有一个文件，免去扩展名歧义；
        # b) 避免把 GIF/SVG 原样落到静态目录；c) 头像带 alpha，PNG 比 JPEG 合适。
        if img.mode not in ("RGB", "RGBA"):
            img = img.convert("RGBA" if "A" in img.getbands() else "RGB")
        if max(img.size) > AVATAR_MAX_DIM:
            ratio = AVATAR_MAX_DIM / max(img.size)
            img = img.resize(
                (max(1, int(img.size[0] * ratio)), max(1, int(img.size[1] * ratio))),
                Image.LANCZOS,
            )
        buf = _io.BytesIO()
        img.save(buf, format="PNG", optimize=True)
        payload, ext = buf.getvalue(), ".png"
    except ImportError as exc:  # pragma: no cover — pillow 是正式依赖，正常装不上才走到
        raise ValueError("image support unavailable") from exc
    except Exception as exc:  # noqa: BLE001 — PIL 的各类解码异常统一转成 400
        raise ValueError("unsupported or corrupted image") from exc

    avatar_dir = _avatar_dir()
    avatar_dir.mkdir(parents=True, exist_ok=True)
    target = avatar_dir / f"{AVATAR_PREFIX}{ext}"
    # 清掉历史遗留的其他扩展名，否则 _find_avatar 可能取到旧文件
    for p in avatar_dir.glob(f"{AVATAR_PREFIX}.*"):
        if p != target:
            try:
                p.unlink()
            except OSError:
                logger.warning("failed to remove old avatar: %s", p, exc_info=True)
    target.write_bytes(payload)
    return f"assets/images/{AVATAR_DIRNAME}/{target.name}"


def delete_avatar() -> bool:
    """删除当前 profile 的头像，返回是否真的删掉了文件。"""
    removed = False
    for p in _avatar_dir().glob(f"{AVATAR_PREFIX}.*"):
        try:
            p.unlink()
            removed = True
        except OSError:
            logger.warning("failed to delete avatar: %s", p, exc_info=True)
    return removed


# 头像上传大小上限（前端也会拦一道，这里是后端的权威校验）
MAX_AVATAR_BYTES = 5 * 1024 * 1024


# RGB565 缩略图宽度边界：过小无意义，过大撑爆设备内存
_RGB565_MIN_W, _RGB565_MAX_W = 16, 480


def build_rgb565_thumbnail(src: Path, width: int) -> tuple[Path, int, int] | None:
    """生成 RGB565 小端裸像素缩略图（供 ESP32 等无解码器设备直接渲染）。

    宽度超过 width 的图按比例缩小；小图不放大。结果缓存到
    THUMBS_DIR/{session_id}/{filename}.{width}w.rgb565，尺寸存同名 .json，
    源文件更新（mtime 更新）时自动重建。Pillow/numpy 不可用或解码失败返回 None。
    """
    try:
        import numpy as np  # noqa: PLC0415
        from PIL import Image  # noqa: PLC0415

        width = min(max(width, _RGB565_MIN_W), _RGB565_MAX_W)
        cache_dir = THUMBS_DIR / src.parent.name
        cache_dir.mkdir(parents=True, exist_ok=True)
        cache = cache_dir / f"{src.name}.{width}w.rgb565"
        meta = cache_dir / f"{src.name}.{width}w.json"
        src_mtime = src.stat().st_mtime

        if cache.is_file() and meta.is_file() and cache.stat().st_mtime >= src_mtime:
            m = json.loads(meta.read_text())
            return cache, m["w"], m["h"]

        img = Image.open(src).convert("RGB")
        W, H = img.size
        if W > width:
            img = img.resize((width, max(1, round(H * width / W))), Image.LANCZOS)
        arr = np.asarray(img, dtype=np.uint8)
        r = (arr[..., 0].astype(np.uint16) >> 3) << 11
        g = (arr[..., 1].astype(np.uint16) >> 2) << 5
        b = arr[..., 2].astype(np.uint16) >> 3
        cache.write_bytes((r | g | b).astype("<u2").tobytes())
        w2, h2 = img.size
        meta.write_text(json.dumps({"w": w2, "h": h2}))
        logger.debug("rgb565 thumbnail: %s -> %dx%d (%s)", src.name, w2, h2, cache)
        return cache, w2, h2
    except Exception:
        logger.warning("rgb565 thumbnail failed: %s", src, exc_info=True)
        return None


# 大多数 LLM provider 对图片单边尺寸限制 8000px（Anthropic/Kiro 等）
_MAX_IMAGE_DIM = 8000
# 附图给模型（vision）的经济尺寸：超过 ~1568px 后 Anthropic 按约 (w*h)/750 计
# token，缩到 1568px 内信息密度最高，再大纯属浪费上下文。
VISION_MAX_DIM = 1568


def _downscale_bytes(raw: bytes, media_type: str = "image/png", max_dim: int = _MAX_IMAGE_DIM) -> tuple[bytes, bool, str]:
    """如果图片任一边超过 max_dim，按比例缩小，保留原始格式。

    PNG→PNG（无损，保护截图文字），JPEG→JPEG q85（照片体积小）。
    返回 (新字节, 是否缩放, 输出 media_type)。
    Pillow 不可用或解析失败时返回原图，交由 agent 层兜底。
    """
    try:
        import io  # noqa: PLC0415

        from PIL import Image  # noqa: PLC0415

        img = Image.open(io.BytesIO(raw))
        w, h = img.size
        if w <= max_dim and h <= max_dim:
            return raw, False, media_type

        ratio = min(max_dim / w, max_dim / h)
        new_w, new_h = int(w * ratio), int(h * ratio)
        img = img.resize((new_w, new_h), Image.LANCZOS)

        buf = io.BytesIO()
        is_jpeg = media_type in ("image/jpeg", "image/jpg")
        if is_jpeg:
            # JPEG：RGB 化以兼容（RGBA 直接存 JPEG 会报错），q85 兼顾体积与质量
            if img.mode in ("RGBA", "P"):
                img = img.convert("RGB")
            img.save(buf, format="JPEG", quality=85)
            out_media_type = "image/jpeg"
        else:
            # PNG 无损（截图/文字首选）
            img.save(buf, format="PNG")
            out_media_type = "image/png"
        return buf.getvalue(), True, out_media_type
    except Exception:
        return raw, False, media_type


def downscale_image_b64(data_b64: str, media_type: str, max_dim: int = _MAX_IMAGE_DIM) -> tuple[str, bool, str]:
    """如果图片任一边超过 max_dim，按比例缩小，保留原始格式。

    返回 (新 base64, 是否缩放, 输出 media_type)。缩放时非 JPEG 一律重编码为 PNG
    （含 gif/webp），所以输出 media_type 必须取返回值——沿用入参会造成
    「PNG 字节 + image/gif 标注」的错配，API 端解码失败。
    Pillow 不可用或解析失败时返回原图，交由 agent 层的 reactive fallback 兜底。
    """
    raw = base64.b64decode(data_b64)
    downscaled, did_resize, out_media_type = _downscale_bytes(raw, media_type, max_dim)
    if not did_resize:
        return data_b64, False, media_type
    return base64.b64encode(downscaled).decode("ascii"), True, out_media_type


# ---------------------------------------------------------------------------
# 长图垂直切分
# ---------------------------------------------------------------------------


def _split_image_vertical(raw: bytes, media_type: str) -> list[tuple[bytes, str]]:
    """如果图片高度超过阈值，垂直切分为多段；否则返回原图单段。

    切分时在目标分割线 ±200px 内搜索空白行（像素标准差低），优先在空白处切割，
    避免切到文字。逻辑移植自 image-split 技能的 auto_split（仅垂直方向）。

    结果按 sha256(raw) 缓存到 _SPLIT_CACHE_DIR，同一张图不重复计算。
    Pillow/numpy 不可用或解析失败时返回原图，交由 _downscale_bytes 兜底。
    """
    try:
        from PIL import Image  # noqa: PLC0415

        Image.MAX_IMAGE_PIXELS = None  # 本工具就是处理大图的

        img = Image.open(io.BytesIO(raw))
        w, h = img.size
        if h <= _SPLIT_HEIGHT_THRESHOLD:
            return [(raw, media_type)]

        key = hashlib.sha256(raw).hexdigest()[:16]
        cache_dir = _SPLIT_CACHE_DIR / key
        meta_file = cache_dir / "meta.json"

        # 命中缓存：直接读段文件
        if meta_file.is_file():
            meta = json.loads(meta_file.read_text())
            segments: list[tuple[bytes, str]] = []
            for seg_name in meta["segments"]:
                seg_bytes = (cache_dir / seg_name).read_bytes()
                segments.append((seg_bytes, meta["media_type"]))
            if segments:
                logger.debug("image split cache hit: %s → %d segments", key, len(segments))
                return segments

        # 未命中：执行切分
        segments = _do_vertical_split(img, media_type, w, h)
        if len(segments) <= 1:
            return [(raw, media_type)]

        # 写缓存
        cache_dir.mkdir(parents=True, exist_ok=True)
        seg_names: list[str] = []
        for i, (seg_bytes, seg_mt) in enumerate(segments):
            ext = _MIME_TO_EXT.get(seg_mt, ".png")
            seg_name = f"{i}{ext}"
            (cache_dir / seg_name).write_bytes(seg_bytes)
            seg_names.append(seg_name)
        meta_file.write_text(json.dumps({
            "media_type": segments[0][1],
            "segments": seg_names,
            "original_size": [w, h],
            "threshold": _SPLIT_HEIGHT_THRESHOLD,
            "segment_size": _SPLIT_SEGMENT,
        }, ensure_ascii=False))
        logger.info("image split: %dx%d → %d segments (cached at %s)", w, h, len(segments), key)
        return segments
    except Exception:
        logger.warning("image split failed, falling back to original", exc_info=True)
        return [(raw, media_type)]


def _do_vertical_split(img, media_type: str, w: int, h: int) -> list[tuple[bytes, str]]:
    """垂直切分图片，在空白间隙处切割。返回 [(段字节, media_type), ...]。"""
    import numpy as np  # noqa: PLC0415

    arr = np.array(img)
    if arr.ndim == 3:
        row_std = arr.std(axis=(1, 2))
    else:
        row_std = arr.std(axis=1)

    # 按 _SPLIT_SEGMENT 间距计算分割位置
    positions = [0]
    pos = _SPLIT_SEGMENT
    while pos < h:
        remaining = h - pos
        if remaining < 100:
            break
        best = _find_best_split_line(row_std, pos)
        if best <= positions[-1]:
            best = positions[-1] + 1
        positions.append(best)
        pos += _SPLIT_SEGMENT
    positions.append(h)

    # 最后一段 <100px 则并入前段（避免 LLM 收到几乎全空的图片）
    if len(positions) > 2 and (positions[-1] - positions[-2]) < 100:
        positions.pop(-2)

    is_jpeg = media_type in ("image/jpeg", "image/jpg")
    segments: list[tuple[bytes, str]] = []
    for i in range(len(positions) - 1):
        top, bottom = positions[i], positions[i + 1]
        crop = img.crop((0, top, w, bottom))
        buf = io.BytesIO()
        if is_jpeg:
            if crop.mode in ("RGBA", "P"):
                crop = crop.convert("RGB")
            crop.save(buf, format="JPEG", quality=90)
            seg_mt = "image/jpeg"
        else:
            crop.save(buf, format="PNG")
            seg_mt = "image/png"
        segments.append((buf.getvalue(), seg_mt))
    return segments


def _find_best_split_line(row_std, target_pos: int, search_range: int = 200, min_gap: int = 3) -> int:
    """在 target_pos 附近 ±search_range 内搜索最佳空白分割线。

    row_std: 每行像素标准差的 1D 数组
    返回最佳分割位置（原始坐标）。
    """
    start = max(0, target_pos - search_range)
    end = min(len(row_std), target_pos + search_range)
    blank = row_std[start:end] < 5  # std < 5 视为空白

    best_pos = target_pos
    best_dist = float("inf")
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
