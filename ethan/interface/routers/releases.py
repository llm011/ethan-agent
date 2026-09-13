"""releases 路由 — Android APK 的公开下载源。

`/api/releases/android/{tag}/app-release.apk` → APK 本体
`/api/releases/android/{tag}/app-release.apk.sha256` → 校验侧车

**为什么需要这个路由**：Android 客户端的自更新原本只有 GitHub Releases 一个源，
而 `release-assets.githubusercontent.com` 在国内可达性很差 —— 表现是「下载失败率
很高」，即使包只有 3.3 MB。客户端现在会依次尝试 CDN → 本服务 → GitHub，本路由就是
中间那一条：它和 app 本身走同一个域名，app 连得上，它就一定连得上。

**为什么是公开的（无鉴权）**：更新检查本身走的是公开的 GitHub API，本来就是匿名的；
下载环节再要求登录会出现「检测到新版本但装不了」这种最糟糕的组合。参照 `api.py` 里
`serve_spa` 的公开只读模式。

**带宽**：默认 **302 重定向到 CDN**，不自己扛流量。只有显式配了本地缓存目录并且
文件确实存在时才由本服务直接下发（给内网/离线环境留的口子）。
"""
from __future__ import annotations

import os
import re
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, RedirectResponse

router = APIRouter(prefix="/releases")

# CDN 镜像域名（和 CI 上传的目标一致）。可用环境变量覆盖，方便自建/测试。
CDN_PUBLIC_URL = os.environ.get("CDN_PUBLIC_URL", "https://cdn.lyb.pub").rstrip("/")

# 本地缓存目录（可选）。设了且文件存在就直接下发，否则 302 到 CDN。
_LOCAL_CACHE_DIR = os.environ.get("ETHAN_APK_CACHE_DIR", "").strip()

APK_FILENAME = "app-release.apk"
SHA256_FILENAME = "app-release.apk.sha256"
_ALLOWED_FILENAMES = {APK_FILENAME, SHA256_FILENAME}

# tag 白名单：`v1.2.3` / `v1.2.3-rc1` / `v1.2.3-beta.2`。
#
# **这是防目录穿越的关键**：tag 会拼进文件路径，`..%2f` 这类输入如果在拼接前没有
# 严格校验，就能读到缓存目录之外的任意文件。用白名单正则而不是「拒绝 ..」的黑名单
# —— 黑名单永远漏。
_TAG_RE = re.compile(r"^v\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$")


def _validate(tag: str, filename: str) -> None:
    if not _TAG_RE.match(tag):
        raise HTTPException(status_code=400, detail="invalid tag")
    if filename not in _ALLOWED_FILENAMES:
        raise HTTPException(status_code=404, detail="not found")


def _local_path(tag: str, filename: str) -> Path | None:
    """本地缓存里的文件路径；没配缓存目录或文件不存在则 None。

    注意 `_TAG_RE` 已经挡掉了 `/` 和 `..`，这里再 `.resolve()` 比对一次父目录 ——
    双保险，且成本可忽略。
    """
    if not _LOCAL_CACHE_DIR:
        return None
    base = Path(_LOCAL_CACHE_DIR).resolve()
    candidate = (base / tag / filename).resolve()
    if not candidate.is_relative_to(base):
        raise HTTPException(status_code=400, detail="invalid path")
    return candidate if candidate.is_file() else None


def _respond(tag: str, filename: str) -> FileResponse | RedirectResponse:
    local = _local_path(tag, filename)
    if local is not None:
        # 版本固化路径，内容永不改变 → 可长缓存。
        return FileResponse(
            str(local),
            media_type=(
                "application/vnd.android.package-archive"
                if filename == APK_FILENAME
                else "text/plain"
            ),
            headers={"Cache-Control": "public, max-age=31536000, immutable"},
        )
    return RedirectResponse(
        url=f"{CDN_PUBLIC_URL}/ethan/releases/android/{tag}/{filename}",
        status_code=302,
    )


@router.get("/android/{tag}/" + APK_FILENAME)
async def download_apk(tag: str):
    """APK 本体。

    302 到 CDN 时**不能带 `Cache-Control` 覆盖** —— 让 Cloudflare 那边决定；
    本地直发时才加长缓存头。
    """
    _validate(tag, APK_FILENAME)
    return _respond(tag, APK_FILENAME)


@router.get("/android/{tag}/" + SHA256_FILENAME)
async def download_apk_sha256(tag: str):
    """sha256 侧车文件（`sha256sum` 的输出格式）。"""
    _validate(tag, SHA256_FILENAME)
    return _respond(tag, SHA256_FILENAME)
