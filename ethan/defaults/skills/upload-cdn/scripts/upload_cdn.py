#!/usr/bin/env python3
"""上传文件到 S3 兼容对象存储（Cloudflare R2 等）。

Usage:
    python upload_cdn.py <local_path> [object_key]

从环境变量读取凭证（由 ~/.ethan/.secrets/upload-cdn.env 自动注入）：
    CDN_ENDPOINT   - S3 endpoint URL
    CDN_ACCESS_KEY - Access Key ID
    CDN_SECRET_KEY - Secret Access Key
    CDN_BUCKET     - 存储桶名
    CDN_PUBLIC_URL - 公开访问 URL 前缀
    CDN_REGION     - 区域（默认 auto）

成功时 stdout 输出公开 URL，失败时 stderr 输出错误并以非0退出。
缓存：~/.ethan/upload-cdn-cache.db，相同 file_hash+object_key 直接返回已有 URL。
"""
import hashlib
import hmac
import os
import sqlite3
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


_CACHE_DB = Path.home() / ".ethan" / "upload-cdn-cache.db"


def _open_cache() -> "sqlite3.Connection | None":
    try:
        _CACHE_DB.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(_CACHE_DB))
        conn.execute(
            "CREATE TABLE IF NOT EXISTS cache "
            "(file_hash TEXT NOT NULL, object_key TEXT NOT NULL, "
            "cdn_url TEXT NOT NULL, uploaded_at TEXT NOT NULL, "
            "PRIMARY KEY (file_hash, object_key))"
        )
        conn.commit()
        return conn
    except Exception:
        return None


def _cache_get(file_hash: str, object_key: str) -> "str | None":
    conn = _open_cache()
    if not conn:
        return None
    try:
        row = conn.execute(
            "SELECT cdn_url FROM cache WHERE file_hash=? AND object_key=?",
            (file_hash, object_key),
        ).fetchone()
        return row[0] if row else None
    except Exception:
        return None
    finally:
        conn.close()


def _cache_set(file_hash: str, object_key: str, cdn_url: str) -> None:
    conn = _open_cache()
    if not conn:
        return
    try:
        conn.execute(
            "INSERT OR REPLACE INTO cache (file_hash, object_key, cdn_url, uploaded_at) "
            "VALUES (?,?,?,?)",
            (file_hash, object_key, cdn_url, datetime.now(tz=timezone.utc).isoformat()),
        )
        conn.commit()
    except Exception:
        pass
    finally:
        conn.close()


def _sign(key: bytes, msg: str) -> bytes:
    return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()


def _get_signing_key(secret: str, date: str, region: str, service: str) -> bytes:
    k = _sign(("AWS4" + secret).encode("utf-8"), date)
    k = _sign(k, region)
    k = _sign(k, service)
    return _sign(k, "aws4_request")


def upload(local_path: str, object_key: str) -> str:
    """Upload a file and return its public URL."""
    endpoint = os.environ.get("CDN_ENDPOINT", "").rstrip("/")
    access_key = os.environ.get("CDN_ACCESS_KEY", "")
    secret_key = os.environ.get("CDN_SECRET_KEY", "")
    bucket = os.environ.get("CDN_BUCKET", "")
    public_url = os.environ.get("CDN_PUBLIC_URL", "").rstrip("/")
    region = os.environ.get("CDN_REGION", "auto")

    missing = [k for k, v in [
        ("CDN_ENDPOINT", endpoint), ("CDN_ACCESS_KEY", access_key),
        ("CDN_SECRET_KEY", secret_key), ("CDN_BUCKET", bucket),
        ("CDN_PUBLIC_URL", public_url),
    ] if not v]
    if missing:
        raise EnvironmentError(f"缺少环境变量: {', '.join(missing)}\n请配置 ~/.ethan/.secrets/upload-cdn.env")

    data = Path(local_path).read_bytes()
    payload_hash = hashlib.sha256(data).hexdigest()

    # 命中缓存直接返回
    cached = _cache_get(payload_hash, object_key)
    if cached:
        print(f"  [cache] {object_key} → {cached}", file=sys.stderr)
        return cached

    content_type = _guess_content_type(local_path)

    now = datetime.now(tz=timezone.utc)
    date_time = now.strftime("%Y%m%dT%H%M%SZ")
    date = now.strftime("%Y%m%d")

    # Build URL
    key_encoded = urllib.parse.quote(object_key, safe="/")
    url = f"{endpoint}/{bucket}/{key_encoded}"
    parsed = urllib.parse.urlparse(url)
    host = parsed.netloc
    path = parsed.path

    # Canonical headers (sorted)
    headers = {
        "content-type": content_type,
        "host": host,
        "x-amz-content-sha256": payload_hash,
        "x-amz-date": date_time,
    }
    canonical_headers = "".join(f"{k}:{v}\n" for k, v in sorted(headers.items()))
    signed_headers = ";".join(sorted(headers.keys()))

    canonical_request = "\n".join([
        "PUT",
        path,
        "",  # query string
        canonical_headers,
        signed_headers,
        payload_hash,
    ])

    credential_scope = f"{date}/{region}/s3/aws4_request"
    string_to_sign = "\n".join([
        "AWS4-HMAC-SHA256",
        date_time,
        credential_scope,
        hashlib.sha256(canonical_request.encode()).hexdigest(),
    ])

    signing_key = _get_signing_key(secret_key, date, region, "s3")
    signature = hmac.new(signing_key, string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()

    authorization = (
        f"AWS4-HMAC-SHA256 Credential={access_key}/{credential_scope}, "
        f"SignedHeaders={signed_headers}, Signature={signature}"
    )

    req = urllib.request.Request(url, data=data, method="PUT")
    req.add_header("Authorization", authorization)
    req.add_header("Content-Type", content_type)
    req.add_header("Host", host)
    req.add_header("x-amz-content-sha256", payload_hash)
    req.add_header("x-amz-date", date_time)

    with urllib.request.urlopen(req) as resp:
        if resp.status not in (200, 204):
            raise RuntimeError(f"上传失败: HTTP {resp.status}")

    cdn_url = f"{public_url}/{object_key}"
    _cache_set(payload_hash, object_key, cdn_url)
    return cdn_url


def _guess_content_type(path: str) -> str:
    ext = Path(path).suffix.lower()
    return {
        ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
        ".gif": "image/gif", ".webp": "image/webp", ".svg": "image/svg+xml",
        ".pdf": "application/pdf", ".txt": "text/plain",
        ".json": "application/json", ".md": "text/markdown",
        ".zip": "application/zip",
    }.get(ext, "application/octet-stream")


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: upload_cdn.py <local_path> [object_key]", file=sys.stderr)
        sys.exit(1)

    local_path = sys.argv[1]
    object_key = sys.argv[2] if len(sys.argv) > 2 else Path(local_path).name

    if not Path(local_path).is_file():
        print(f"Error: 文件不存在: {local_path}", file=sys.stderr)
        sys.exit(1)

    try:
        url = upload(local_path, object_key)
        print(url)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
