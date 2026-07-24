"""截图回传(方案 Q5):CDP base64 → 落专属目录 → 返回路径,渠道无关。

  - 飞书:复用 send_lark_image(只认本地路径),零改动。
  - Web:经 /api/browser/shot/{name} 文件路由读取。
不用 /tmp(macOS 默认不自动清,Docker 容器内更无清理),落 user_data_dir/browser-shots,
由 idle sweep 顺带按龄清理 + 总量上限。
"""
from __future__ import annotations

import base64
import json
import logging
import time
from pathlib import Path

logger = logging.getLogger("ethan.browser")

_MAX_AGE_SECONDS = 30 * 60  # 截图保留 30min(需活到飞书上传完成)
_MAX_FILES = 200  # 总量上限


def shots_dir() -> Path:
    from ethan.core.paths import user_data_dir
    d = user_data_dir() / "browser-shots"
    d.mkdir(parents=True, exist_ok=True)
    return d


async def save_screenshot(result: dict | None) -> str:
    """把 CDP 截图结果落盘,返回 JSON {path, format}。

    扩展返回的是整个 page 结果,截图数据在嵌套的 result["screenshot"]["data"]。
    同时兼容顶层直接给 data 的形式。
    默认 webp 格式（比 png 小 60-70%,CDP 原生支持）。
    """
    result = result or {}
    shot = result.get("screenshot")
    src = shot if isinstance(shot, dict) else result
    data_b64 = src.get("data") or src.get("base64") or src.get("dataUrl")
    fmt = src.get("format") or result.get("format", "webp")
    if not data_b64:
        return json.dumps({"error": "扩展未返回截图数据", "raw": result}, ensure_ascii=False)
    # 兼容 data:image/png;base64,xxx 形式
    if isinstance(data_b64, str) and "," in data_b64 and data_b64.strip().startswith("data:"):
        data_b64 = data_b64.split(",", 1)[1]
    try:
        raw = base64.b64decode(data_b64)
    except (ValueError, TypeError) as e:
        return json.dumps({"error": f"截图解码失败: {e}"}, ensure_ascii=False)

    d = shots_dir()
    name = f"shot-{int(time.time() * 1000)}.{fmt}"
    path = d / name
    path.write_bytes(raw)
    return json.dumps({"path": str(path), "name": name, "format": fmt}, ensure_ascii=False)


def cleanup_shots() -> None:
    """删超龄截图 + 超出总量上限的最旧文件。由 idle sweep 调用。"""
    try:
        d = shots_dir()
    except Exception:
        return
    now = time.time()
    files = sorted(d.glob("shot-*"), key=lambda p: p.stat().st_mtime)
    for p in list(files):
        try:
            if now - p.stat().st_mtime > _MAX_AGE_SECONDS:
                p.unlink(missing_ok=True)
                files.remove(p)
        except OSError:
            pass
    # 总量上限:删最旧的
    excess = len(files) - _MAX_FILES
    for p in files[:max(0, excess)]:
        try:
            p.unlink(missing_ok=True)
        except OSError:
            pass
