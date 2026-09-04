"""Tests for build_rgb565_thumbnail — 嵌入式设备直显缩略图。

覆盖：尺寸/字节长度正确性、RGB 值打包、小图不放大、缓存命中、源更新后重建。
"""
from __future__ import annotations

import struct
from pathlib import Path

import pytest

from ethan.core import assets as assets_mod
from ethan.core.assets import build_rgb565_thumbnail

pytest.importorskip("PIL")
pytest.importorskip("numpy")
from PIL import Image  # noqa: E402


def _make_png(path: Path, w: int, h: int, color=(255, 0, 0)) -> None:
    Image.new("RGB", (w, h), color).save(path, format="PNG")


def test_dimensions_and_packing(tmp_path, monkeypatch):
    thumbs = tmp_path / "thumbs"
    monkeypatch.setattr(assets_mod, "THUMBS_DIR", thumbs)
    src = tmp_path / "s1" / "img.png"
    src.parent.mkdir(parents=True)
    _make_png(src, 480, 100, color=(255, 0, 0))

    result = build_rgb565_thumbnail(src, 240)
    assert result is not None
    cache, w, h = result
    assert (w, h) == (240, 50)
    assert cache.stat().st_size == 240 * 50 * 2

    data = cache.read_bytes()
    # 第一个像素：纯红 RGB565 = 0xF800（小端字节序）
    first = struct.unpack("<H", data[:2])[0]
    assert first == 0xF800


def test_small_image_not_upscaled(tmp_path, monkeypatch):
    thumbs = tmp_path / "thumbs"
    monkeypatch.setattr(assets_mod, "THUMBS_DIR", thumbs)
    src = tmp_path / "s1" / "small.png"
    src.parent.mkdir(parents=True)
    _make_png(src, 100, 40)

    _, w, h = build_rgb565_thumbnail(src, 240)
    assert (w, h) == (100, 40)


def test_cache_hit_and_rebuild(tmp_path, monkeypatch):
    thumbs = tmp_path / "thumbs"
    monkeypatch.setattr(assets_mod, "THUMBS_DIR", thumbs)
    src = tmp_path / "s1" / "img.png"
    src.parent.mkdir(parents=True)
    _make_png(src, 1000, 100)

    cache1, w1, _ = build_rgb565_thumbnail(src, 240)
    mtime1 = cache1.stat().st_mtime
    # 二次调用命中缓存：同一文件、mtime 不变
    cache2, w2, _ = build_rgb565_thumbnail(src, 240)
    assert cache1 == cache2 and cache2.stat().st_mtime == mtime1 and w1 == w2

    # 源更新（mtime 推后）→ 重建
    import os
    import time

    future = time.time() + 10
    os.utime(src, (future, future))
    cache3, _, _ = build_rgb565_thumbnail(src, 240)
    assert cache3.stat().st_mtime >= mtime1


def test_corrupt_source_returns_none(tmp_path, monkeypatch):
    thumbs = tmp_path / "thumbs"
    monkeypatch.setattr(assets_mod, "THUMBS_DIR", thumbs)
    src = tmp_path / "s1" / "bad.png"
    src.parent.mkdir(parents=True)
    src.write_bytes(b"not an image")
    assert build_rgb565_thumbnail(src, 240) is None
