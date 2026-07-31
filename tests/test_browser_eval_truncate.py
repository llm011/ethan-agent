"""Tests for browser_page eval 大结果截断（_truncate_eval_result）。

背景：browser_page eval 抓整页卡片列表时返回值动辄几十 KB，在 ReAct 循环里
逐轮回灌进上下文，是浏览器批量任务 token 爆炸的主因。策略与 snapshot 一致：
大结果落盘、返回体只带首段，模型按需 snapshot_read 翻页。
"""
from __future__ import annotations

import json

from ethan.tools.builtin import browser as B


def test_small_result_not_truncated():
    """小结果原样返回，不落盘。"""
    result = {"ok": True, "sessionId": "s1", "tabId": 1, "result": "short value"}
    out = json.loads(B._truncate_eval_result(result, "s1"))
    assert out["result"] == "short value"
    assert "result_truncated" not in out


def test_large_string_result_truncated_and_persisted():
    """大字符串结果截断首段并落盘，结构字段保留。"""
    big = "x\n" * 10000  # ~20000 chars
    result = {"ok": True, "sessionId": "s1", "tabId": 42, "page": {"url": "u"}, "result": big}
    out = json.loads(B._truncate_eval_result(result, "s1"))
    assert out["result_truncated"] is True
    assert out["result_has_more"] is True
    assert out["result_total_chars"] == len(big)
    assert len(out["result"]) <= B._EVAL_MAX_CHARS + 600  # 允许换行对齐余量
    # 结构字段原样保留，模型仍能拿到 ID
    assert out["ok"] is True and out["tabId"] == 42 and out["page"] == {"url": "u"}
    # 落盘文件存在且内容完整
    from pathlib import Path
    assert Path(out["result_path"]).read_text(encoding="utf-8") == big


def test_large_object_result_serialized_then_truncated():
    """result 是大对象/数组时，先 JSON 序列化再按字符截断。"""
    big_list = [{"title": f"视频{i}", "likes": i, "desc": "描述" * 50} for i in range(300)]
    result = {"ok": True, "sessionId": "s1", "result": big_list}
    out = json.loads(B._truncate_eval_result(result, "s1"))
    assert out["result_truncated"] is True
    assert isinstance(out["result"], str)  # 截断后是字符串首段
    from pathlib import Path
    # 落盘的是完整序列化后的 JSON 字符串
    persisted = Path(out["result_path"]).read_text(encoding="utf-8")
    assert json.loads(persisted) == big_list


def test_newline_alignment_pulls_full_content_not_truncated():
    """内容略超阈值但尾部换行让首段覆盖全部 → 不算截断，原样返回、不落盘。

    回归点：_chunk_text 向后对齐换行会把 end 拉到 ==total，若仍标 truncated
    会误导模型 snapshot_read 一个空续段并白白落盘一个文件。
    """
    # 总长 8200，在 8199 处放唯一换行（落在 8000 后的 search radius=500 内）
    display = ("a" * 8199) + "\n" + ("")  # len 8200, newline at index 8199
    assert len(display) == 8200
    result = {"ok": True, "sessionId": "s1", "result": display}
    out = json.loads(B._truncate_eval_result(result, "s1"))
    assert "result_truncated" not in out
    assert out["result"] == display


def test_result_has_more_true_when_truncated():
    """真正截断时 result_has_more 恒为 True（已由 chunk_len>=total 守卫兜底）。"""
    big = "z" * 20000  # 无换行，硬截断
    result = {"ok": True, "sessionId": "s1", "result": big}
    out = json.loads(B._truncate_eval_result(result, "s1"))
    assert out["result_truncated"] is True
    assert out["result_has_more"] is True
    assert out["result_chunk_length"] < out["result_total_chars"]


def test_persist_snapshot_unique_filenames_same_ms():
    """同一 session 连续落盘不撞名（进程内自增序号），避免互相覆盖污染分页。"""
    p1 = B._persist_snapshot("content-1", "s1")
    p2 = B._persist_snapshot("content-2", "s1")
    assert p1 != p2
    from pathlib import Path
    assert Path(p1).read_text(encoding="utf-8") == "content-1"
    assert Path(p2).read_text(encoding="utf-8") == "content-2"


def test_no_result_field_passthrough():
    """没有 result 字段（如 ok-only 返回）原样序列化，不报错。"""
    result = {"ok": True, "sessionId": "s1"}
    out = json.loads(B._truncate_eval_result(result, "s1"))
    assert out == result


def test_non_dict_passthrough():
    """result 不是 dict（异常返回）原样序列化。"""
    out = json.loads(B._truncate_eval_result(["a", "b"], "s1"))
    assert out == ["a", "b"]
