"""Browser output implementation; browser.py keeps compatibility exports."""
from __future__ import annotations

import itertools
import json
import time
from pathlib import Path

from .browser_compat import browser as B

# snapshot 分页：完整内容落盘 /tmp，prompt 里只带首段，agent 按需翻页读取。
_SNAPSHOT_DIR = Path("/tmp/ethan-snapshots")
_SNAPSHOT_CHUNK_CHARS = 10000  # 每段目标字符数，在换行符处对齐截断
_SNAPSHOT_NEWLINE_SEARCH_RADIUS = 500  # 截断点附近向前搜索换行符的范围


_PERSIST_SEQ = itertools.count()


def _persist_snapshot(content: str, session: str) -> str:
    """完整 snapshot 文本落盘，返回文件路径。

    文件名带一个进程内自增序号，避免同一 session 在同一毫秒内两次落盘
    （如一次 snapshot + 一次 eval 截断，或两次快速 eval）撞名互相覆盖、
    污染后续 snapshot_read 的分页。
    """
    B._SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    safe = (session or "unknown").replace("/", "_").replace("\\", "_")
    path = B._SNAPSHOT_DIR / f"{safe}-{int(time.time() * 1000)}-{next(B._PERSIST_SEQ)}.txt"
    path.write_text(content, encoding="utf-8")
    return str(path)


# eval 返回值截断：结构化 JSON（如整页视频/笔记卡片列表）动辄几十 KB，
# 在 ReAct 循环里被逐轮回灌进上下文，是浏览器批量任务 token 爆炸的主因
# （实测抖音 Top10 单 case input 高达 ~300 万 token）。策略与 snapshot 一致：
# 完整结果落盘，prompt 只带首段，模型按需用 snapshot_read 翻页读取。
_EVAL_MAX_CHARS = 8000  # eval 返回值（result 字段）超过此长度即落盘 + 截断首段


def _truncate_eval_result(result, session: str) -> str:
    """eval 结果过大时：完整落盘，返回体只保留 result 首段 + 读取指引。

    只截断 `result`（脚本返回值）这一个字段，ok/sessionId/tabId/page 等结构字段
    原样保留，模型仍能拿到 ID 做后续操作。result 非字符串时先 JSON 序列化再按字符截断。
    """
    if not isinstance(result, dict) or "result" not in result:
        return json.dumps(result, ensure_ascii=False)
    value = result["result"]
    if isinstance(value, str):
        display = value
    else:
        try:
            display = json.dumps(value, ensure_ascii=False)
        except (TypeError, ValueError):
            display = str(value)
    total = len(display)
    if total <= B._EVAL_MAX_CHARS:
        # 未超阈值原样返回。非字符串 value 这里会被 json.dumps 再序列化一次
        # （measure 时一次、这里一次），但仅发生在 <=8000 字符的小结果上，
        # 开销可忽略，不值得为省这一次序列化引入占位符替换之类的复杂度。
        return json.dumps(result, ensure_ascii=False)
    # 先切首段：_chunk_text 会向后对齐到换行符，若内容尾部有换行，end 可能被拉到
    # == total，首段其实已覆盖全部。这种情况不算截断，直接原样返回，避免落盘 +
    # 误导模型去 snapshot_read 一个空续段。
    chunk, chunk_len = B._chunk_text(display, 0, B._EVAL_MAX_CHARS)
    if chunk_len >= total:
        return json.dumps(result, ensure_ascii=False)
    # 真正超长：落盘完整结果，返回体只带首段
    path = B._persist_snapshot(display, session)
    out = dict(result)
    out["result"] = chunk
    out["result_truncated"] = True
    out["result_path"] = path
    out["result_total_chars"] = total
    out["result_chunk_length"] = chunk_len
    out["result_has_more"] = True  # 已通过上面的 chunk_len>=total 守卫，走到这里必有后续
    return json.dumps(out, ensure_ascii=False)


def _chunk_text(content: str, offset: int, length: int) -> tuple[str, int]:
    """从 offset 取 length 字符，在末尾附近找换行符对齐截断。

    找不到换行符（前后 _SNAPSHOT_NEWLINE_SEARCH_RADIUS 字符内都没有）就硬截断。
    返回 (chunk, actual_length)。
    """
    total = len(content)
    if offset >= total:
        return "", 0
    end = min(offset + length, total)
    if end < total:
        search_start = max(offset, end - B._SNAPSHOT_NEWLINE_SEARCH_RADIUS)
        search_end = min(total, end + B._SNAPSHOT_NEWLINE_SEARCH_RADIUS)
        newline_pos = content.rfind("\n", search_start, search_end)
        if newline_pos > offset:
            end = newline_pos + 1
    chunk = content[offset:end]
    return chunk, end - offset

