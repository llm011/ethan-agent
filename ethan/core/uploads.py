"""聊天附件（非图片上传）的落盘、归属与读取。

与图片（`ethan/core/assets.py`）同一套思路：**文件落盘、DB 只存元数据**，
前端用 `assetUrl()` + `/api/assets/uploads/...` 访问。

布局（`user_uploads_dir()` = `<user_data_dir>/uploads`，default profile 即 `~/.ethan/uploads`）：

    uploads/
      _pending/<uuid8>_<safe_name>     ← 上传时还没有 session_id（新会话第一句）
      <session_id>/<uuid8>_<safe_name> ← 已归属某个会话

为什么不再用 `tempfile.NamedTemporaryFile`：落在 `/var/folders/...`（macOS）或
`/tmp` 下，既不在任何清理策略里，也不在 `file_jail` 的 home//tmp 允许范围内，
系统清理或重启后路径就失效，模型后续 `file_read` 直接读不到。

归属时机：`POST /api/chat` 里用户消息落库前调 `adopt_uploads()` 把 `_pending/`
下的文件搬进 `uploads/<session_id>/`，并返回改写后的元数据写进 `messages.files`。
"""
from __future__ import annotations

import mimetypes
import re
import shutil
import time
import uuid
from pathlib import Path

# 单文件上限（与前端提示保持一致；后端是权威校验）
MAX_UPLOAD_BYTES = 50 * 1024 * 1024
# 还没归属会话的暂存子目录名。下划线开头，不会与真实 session_id（s_…）冲突。
PENDING_DIRNAME = "_pending"
# 保留后缀的最大长度（防止 ".tar.gz.xxxxx" 这种超长尾巴）
_MAX_SUFFIX_LEN = 16


def uploads_root() -> Path:
    """当前 profile 的附件根目录（延迟导入 paths，避免 core 层的循环依赖）。"""
    from ethan.core.paths import user_uploads_dir

    root = user_uploads_dir()
    root.mkdir(parents=True, exist_ok=True)
    return root


_UNSAFE = re.compile(r'[\x00-\x1f\x7f/\\:*?"<>|]+')


def safe_name(name: str) -> str:
    """把用户给的原始文件名收敛成「只用于展示 + 拼后缀」的安全名。

    只保留 basename、去掉控制字符与路径分隔符，限长 120 字符；绝不参与目录拼接
    的安全判断（目录一律由 `session_id` 决定，文件名前面还有 uuid 前缀）。
    """
    base = Path(name or "upload").name
    base = _UNSAFE.sub("_", base).strip(" .") or "upload"
    if len(base) > 120:
        suffix = Path(base).suffix[:_MAX_SUFFIX_LEN]
        base = base[: 120 - len(suffix)] + suffix
    return base


def store_upload(data: bytes, filename: str, session_id: str | None = None) -> dict:
    """把上传字节写到当前 profile 的 uploads 目录，返回附件元数据。

    有 `session_id` 直接落到 `uploads/<session_id>/`；没有则先落 `uploads/_pending/`，
    等消息落库时由 `adopt_uploads()` 搬过去。
    """
    name = safe_name(filename)
    subdir = session_id or PENDING_DIRNAME
    seg_dir = uploads_root() / subdir
    seg_dir.mkdir(parents=True, exist_ok=True)
    stored = f"{uuid.uuid4().hex[:8]}_{name}"
    path = seg_dir / stored
    path.write_bytes(data)
    return {
        "name": name,
        "path": str(path),
        "rel_path": f"{subdir}/{stored}",
        "size": len(data),
        "media_type": mimetypes.guess_type(name)[0] or "application/octet-stream",
    }


def _normalize(raw: dict | str, session_id: str) -> dict | None:
    """把请求里带的 files 项（dict 或老的裸文件名）统一成附件元数据。

    优先按 `rel_path` 定位到 uploads 下的真实文件；只有 `path` 也行（兼容前端
    直接传绝对路径）；两者都没有时返回 None（没有可下载的文件，只记名字没意义）。
    """
    if isinstance(raw, str):
        raw = {"name": raw}
    if not isinstance(raw, dict):
        return None
    name = safe_name(str(raw.get("name") or ""))
    rel = str(raw.get("rel_path") or "")
    path = str(raw.get("path") or "")
    root = uploads_root().resolve()
    resolved: Path | None = None
    if rel:
        try:
            on_disk = (root / rel).resolve()
            if on_disk.is_relative_to(root) and on_disk.is_file():
                resolved = on_disk
            else:
                rel = ""  # rel 越界或已失效 → 交给 path 兜底
        except OSError:
            rel, resolved = "", None
    if resolved is None and path:
        # 只认 path 也行（老前端 / 只传绝对路径）：必须在 uploads 根下，顺手反推 rel_path。
        # 注意这里不要求 is_file()——判断文件是否存在统一放到下面，找不到就整条丢弃。
        try:
            candidate = Path(path).expanduser().resolve()
            if candidate.is_relative_to(root):
                resolved = candidate
                rel = str(candidate.relative_to(root))
        except OSError:
            resolved = None
    if resolved is None or not resolved.is_file():
        return None
    size = raw.get("size")
    media_type = str(raw.get("media_type") or "") or mimetypes.guess_type(name)[0] or "application/octet-stream"
    return {
        "name": name or resolved.name,
        "path": str(resolved),
        "rel_path": rel or f"{session_id}/{resolved.name}",
        "size": int(size) if isinstance(size, int) else resolved.stat().st_size,
        "media_type": media_type,
    }


def adopt_uploads(session_id: str, raw_files: list | None) -> list[dict]:
    """把本次消息携带的附件归属到 `session_id`，返回规范化后的元数据列表。

    `_pending/` 下的文件搬进 `uploads/<session_id>/`（改写 path/rel_path）；
    已经在该会话目录下的原样返回；找不到文件的条目直接丢弃（宁可少一个 📎，
    也不要留一个点开 404 的坏链接）。任何搬迁失败都退回原路径，不阻断落库。
    """
    if not raw_files:
        return []
    target_dir = uploads_root() / session_id
    out: list[dict] = []
    for raw in raw_files:
        meta = _normalize(raw, session_id)
        if meta is None:
            continue
        src = Path(meta["path"])
        if src.parent.name == PENDING_DIRNAME:
            try:
                target_dir.mkdir(parents=True, exist_ok=True)
                dst = target_dir / src.name
                shutil.move(str(src), str(dst))
                meta["path"] = str(dst.resolve())
                meta["rel_path"] = f"{session_id}/{dst.name}"
            except OSError:
                # 搬不动就保留在 _pending/，至少还能下载；不阻断消息落库。
                pass
        out.append(meta)
    return out


def upload_file_path(rel_path: str) -> Path | None:
    """`rel_path` → uploads 下的真实文件路径；越界（`..`）或不存在返回 None。

    只做 jail 校验，不判断会话归属——归属由路由层按 URL 里的 session_id 决定，
    保证一个会话的附件不能被另一个会话的链接读到。
    """
    try:
        root = uploads_root().resolve()
        p = (root / rel_path).resolve()
    except OSError:
        return None
    if not p.is_relative_to(root) or not p.is_file():
        return None
    return p


def prune_pending(max_age_days: int = 7) -> int:
    """清掉 `_pending/` 里长期没被任何消息认领的上传（用户传了却没发送）。

    幂等、失败静默：只在启动时跑一次，删掉的都是没有 DB 引用的孤儿文件。
    """
    pending = uploads_root() / PENDING_DIRNAME
    if not pending.is_dir():
        return 0
    cutoff = time.time() - max_age_days * 86400
    removed = 0
    for p in pending.iterdir():
        try:
            if p.is_file() and p.stat().st_mtime < cutoff:
                p.unlink()
                removed += 1
        except OSError:
            continue
    return removed
