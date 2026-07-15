"""Get笔记 异步任务后台轮询。

在 _run_generation 末尾、emit done 之前调用：
1. 从 agent 回复文本中提取 getnote task_id
2. 后台轮询 task/progress 直到 success/failed
3. 成功后调 note/detail 拿内容，作为独立消息推送给前端

设计要点：
- 完全同步 HTTP（urllib），避免引入 aiohttp 依赖
- 绕过宿主机代理（ProxyHandler({})），避免容器内 127.0.0.1:7890 不可达
- 以 status 字段为准判断成功/失败，忽略 error_msg 残留值
  （实测：success 状态下 error_msg 可能残留"生成笔记失败，请手动重试"）
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import urllib.request
from pathlib import Path

logger = logging.getLogger(__name__)

GETNOTE_BASE = "https://openapi.biji.com"
SECRETS_PATH = Path.home() / ".ethan" / ".secrets" / "getnote.env"


def _load_credentials() -> tuple[str, str]:
    """从环境变量或 ~/.ethan/.secrets/getnote.env 读取凭证。"""
    api_key = os.environ.get("GETNOTE_API_KEY", "")
    client_id = os.environ.get("GETNOTE_CLIENT_ID", "")
    if api_key and client_id:
        return api_key, client_id
    if SECRETS_PATH.exists():
        for line in SECRETS_PATH.read_text().splitlines():
            line = line.strip()
            if line.startswith("GETNOTE_API_KEY="):
                api_key = line.split("=", 1)[1].strip().strip('"').strip("'")
            elif line.startswith("GETNOTE_CLIENT_ID="):
                client_id = line.split("=", 1)[1].strip().strip('"').strip("'")
    return api_key, client_id


def _http(url: str, method: str = "GET", data: dict | None = None,
          api_key: str = "", client_id: str = "") -> dict:
    """同步 HTTP 请求（绕过代理）。"""
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = api_key
    if client_id:
        headers["X-Client-ID"] = client_id
    body = json.dumps(data).encode() if data else None
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    with opener.open(req, timeout=30) as resp:
        return json.loads(resp.read().decode())


def extract_task_id(text: str) -> str | None:
    """从 agent 回复文本中提取 getnote task_id。

    覆盖常见格式：
    - task_id: abc123
    - task_id=abc123
    - task_id: `abc123`
    - "task_id":"abc123"
    """
    if not text:
        return None
    match = re.search(r'task_id["\']?\s*[:=]\s*["\']?`*([a-f0-9]{20,})`*', text, re.IGNORECASE)
    return match.group(1) if match else None


async def poll_getnote_task(
    task_id: str,
    on_progress=None,
    max_polls: int = 5,
    interval: int = 30,
) -> dict | None:
    """轮询 getnote task 进度，成功后返回 note 内容。

    Args:
        task_id: getnote 异步任务 ID
        on_progress: 回调 async (status, note_id) -> None
        max_polls: 最大轮询次数（默认 5 次 = 最多 150s）
        interval: 轮询间隔秒数（默认 30s）

    Returns:
        {"note_id", "content", "title"} 或 None（失败/超时）
        detail 拉取失败时返回 {"note_id", "content": "", "title": "",
                              "detail_failed": True, "task_id": ...}
    """
    api_key, client_id = _load_credentials()
    if not api_key or not client_id:
        logger.warning("getnote 凭证缺失，跳过后台轮询")
        return None

    progress_url = f"{GETNOTE_BASE}/open/api/v1/resource/note/task/progress"
    detail_url = f"{GETNOTE_BASE}/open/api/v1/resource/note/detail"

    for i in range(max_polls):
        await asyncio.sleep(interval)
        try:
            resp = await asyncio.to_thread(
                _http, progress_url, "POST",
                {"task_id": task_id}, api_key, client_id,
            )
        except Exception as e:
            logger.warning("getnote progress 请求失败 (第%d次): %s", i + 1, e)
            continue

        if not resp.get("success"):
            logger.warning("getnote progress 返回失败: %s", resp)
            continue

        result = resp.get("result", {})
        # 以 status 字段为准，忽略 error_msg 残留值
        # （实测：success 状态下 error_msg 可能残留"生成笔记失败，请手动重试"）
        status = result.get("status", "")
        note_id = result.get("note_id") or result.get("id") or ""

        if on_progress:
            try:
                await on_progress(status, note_id)
            except Exception:
                pass

        if status == "success" and note_id:
            # 拉取笔记详情
            try:
                detail = await asyncio.to_thread(
                    _http, f"{detail_url}?note_id={note_id}",
                    "GET", None, api_key, client_id,
                )
                if detail.get("success"):
                    note = detail.get("result", {})
                    return {
                        "note_id": str(note_id),
                        "content": note.get("content", ""),
                        "title": note.get("title", ""),
                    }
            except Exception as e:
                logger.exception("getnote detail 请求失败: %s", e)
            return {"note_id": str(note_id), "content": "", "title": "", "detail_failed": True, "task_id": task_id}

        if status in ("failed", "error"):
            logger.warning("getnote 任务失败: %s", result)
            return None

        # processing / pending -> 继续轮询

    logger.warning("getnote 轮询超时 (%d 次 x %ds)", max_polls, interval)
    return None
