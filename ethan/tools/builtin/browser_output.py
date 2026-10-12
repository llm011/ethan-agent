"""Browser output implementation; browser.py keeps compatibility exports."""
from __future__ import annotations

import itertools
import json
import time
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

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

_USER_TABS_MAX_CHARS = 24000  # user_list 返回值上限，超限即落盘 + 截断首段
_USER_TABS_DIR = "/tmp/ethan-tablist"


def _tab_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _persist_user_tabs(payload: dict) -> str:
    """写可按行分页的完整 JSON；独占创建、0600 权限，失败移除半成品。"""
    directory = Path(B._USER_TABS_DIR)
    directory.mkdir(parents=True, exist_ok=True)
    path: Path | None = None
    try:
        with NamedTemporaryFile(
            mode="w", encoding="utf-8", prefix="user_tabs_", suffix=".json",
            dir=directory, delete=False,
        ) as file:
            path = Path(file.name)
            # 不能写单行 JSON：file_read 的 offset/max_lines 是行分页参数。
            json.dump(payload, file, ensure_ascii=False, indent=2)
            file.write("\n")
        return str(path)
    except Exception:
        if path is not None:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
        raise


def _pack_user_tabs(raw: dict | list) -> str:
    """按最终 JSON 字符数限流；预览只含完整 tab，returned 精确计数。

    小清单保持原字段并补 total。超限将原清单完整落盘，预览含显式截断标志
    和读取指引。即使落盘失败或单个 tab 就超限，也绝不把超长内容回灌模型。
    """
    payload = raw if isinstance(raw, dict) else {"tabs": raw}
    tabs = payload.get("tabs") or []
    total = len(tabs)
    complete = _tab_json({**payload, "total": total})
    if len(complete) <= B._USER_TABS_MAX_CHARS:
        return complete

    out: dict[str, Any] = {
        "tabs": [], "total": total, "returned": 0, "truncated": True,
        "has_more": bool(total),
    }
    try:
        out["path"] = _persist_user_tabs(payload)
        out["hint"] = (
            "仅预览，不是全量。完整 JSON 已落盘；用 file_read(path=path, "
            "offset=1, max_lines=100) 按行分页，读完再整理。单行过长时可用 "
            "browser_page(action='snapshot_read', path=path, offset=0, length=8000) "
            "按字符分页（下一段 offset+=chunk_length）。"
        )
    except Exception:
        out["hint"] = (
            "清单过长且落盘失败；当前仅预览，不是全量。请改用 "
            "browser_tab(action='find_tab', query=关键词) 收窄定位，勿据此整理全部 tab。"
        )

    # 先扣除最终元数据与 JSON 转义后的条目长度，再加入完整条目。
    # returned 的位数也必须计入；不截断 JSON 文本，不粗数 tabId 字样。
    base_chars = len(_tab_json(out))
    encoded_tabs: list[str] = []
    tab_chars = 0
    for tab in tabs:
        encoded = _tab_json(tab)
        count = len(encoded_tabs) + 1
        size = base_chars + tab_chars + len(encoded) + (count - 1) + len(str(count)) - 1
        if size > B._USER_TABS_MAX_CHARS:
            break
        encoded_tabs.append(encoded)
        tab_chars += len(encoded)
    out["returned"] = len(encoded_tabs)
    out["has_more"] = len(encoded_tabs) < total
    # 将已序列化的对象拼入 []，避免对巨型列表反复序列化（线性开销）。
    header = _tab_json({k: v for k, v in out.items() if k != "tabs"})
    result = '{"tabs":[' + ",".join(encoded_tabs) + '],' + header[1:]
    if len(result) <= B._USER_TABS_MAX_CHARS:
        return result
    # 极长自定义落盘目录也可能使元数据超预算；不要因读取指引再次泄漏体积。
    fallback = {"tabs": [], "total": total, "returned": 0, "truncated": True,
                "has_more": bool(total), "hint": "清单过长；请用 find_tab 按关键词收窄。"}
    return _tab_json(fallback)


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

