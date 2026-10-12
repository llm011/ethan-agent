"""User tab output must be complete or explicitly bounded and recoverable."""
from __future__ import annotations

import asyncio
import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from ethan.tools.builtin import browser as B
from ethan.tools.builtin import browser_output
from ethan.tools.builtin.file import FileReadTool


def tabs(count=100):
    return [{"tabId": i, "windowId": 1, "groupId": -1,
             "title": '标题 "tabId"\\\n' * 100, "url": f"https://example.com/{i}"}
            for i in range(count)]


@pytest.fixture(autouse=True)
def isolate_output(monkeypatch, tmp_path):
    monkeypatch.setattr(B, "_USER_TABS_DIR", str(tmp_path / "tabs"))


def checked(raw):
    result = B._pack_user_tabs(raw)
    assert len(result) <= B._USER_TABS_MAX_CHARS
    return json.loads(result)


@pytest.mark.parametrize("raw", [{"tabs": []}, [], {"tabs": None}, {"tabs": [{"tabId": 1}], "ok": True}])
def test_small_preserves_payload(raw):
    payload = raw if isinstance(raw, dict) else {"tabs": raw}
    assert checked(raw) == {**payload, "total": len(payload.get("tabs") or [])}
    assert not Path(B._USER_TABS_DIR).exists()


def test_threshold_counts_total_metadata(monkeypatch):
    raw = {"tabs": [{"tabId": 1, "title": "x" * 1500}]}
    compact = json.dumps({**raw, "total": 1}, ensure_ascii=False, separators=(",", ":"))
    monkeypatch.setattr(B, "_USER_TABS_MAX_CHARS", len(compact))
    assert "truncated" not in checked(raw)
    monkeypatch.setattr(B, "_USER_TABS_MAX_CHARS", len(compact) - 1)
    out = checked(raw)
    assert out["truncated"] and out["returned"] == 0
    assert json.loads(Path(out["path"]).read_text()) == raw


def test_large_list_complete_file_and_exact_preview():
    raw = {"tabs": tabs(), "ok": True}
    out = checked(raw)
    assert out["truncated"] is True
    assert 0 < out["returned"] < out["total"] == 100
    assert out["returned"] == len(out["tabs"])
    assert out["tabs"] == raw["tabs"][:out["returned"]]
    assert out["has_more"] is True
    path = Path(out["path"])
    assert json.loads(path.read_text()) == raw
    assert path.stat().st_mode & 0o777 == 0o600
    assert "max_lines=100" in out["hint"] and "offset=1" in out["hint"]
    assert "limit" not in out["hint"]


def test_large_list_file_read_line_pages_reconstruct():
    raw = {"tabs": tabs(30)}
    out = checked(raw)
    path = Path(out["path"])
    line_count = len(path.read_text().splitlines())
    pieces = [asyncio.run(FileReadTool().run(out["path"], offset=i, max_lines=10))
              for i in range(1, line_count + 1, 10)]
    assert all(isinstance(piece, str) for piece in pieces)
    assert json.loads("\n".join(pieces)) == raw


@pytest.mark.parametrize("title", ['"\\\n' * 50000, "中" * 100000])
def test_single_giant_tab_is_not_partially_returned(title):
    raw = {"tabs": [{"tabId": 7, "title": title}]}
    out = checked(raw)
    assert out["tabs"] == [] and out["returned"] == 0 and out["total"] == 1
    assert out["truncated"] and out["has_more"]
    assert json.loads(Path(out["path"]).read_text()) == raw


def test_giant_tab_character_pages_reconstruct(monkeypatch):
    raw = {"tabs": [{"tabId": 7, "title": '"\\\n' * 10000}]}
    out = checked(raw)
    monkeypatch.setattr(B, "mark_authorized", lambda _: None)
    async def read_pages():
        chunks = []
        offset = 0
        tool = B.BrowserPageTool()
        while True:
            page = json.loads(await tool.run(
                "snapshot_read", path=out["path"], offset=offset, length=8000,
            ))
            chunks.append(page["snapshot"])
            if not page["has_more"]:
                return "".join(chunks)
            assert page["chunk_length"] > 0
            offset += page["chunk_length"]
    assert json.loads(asyncio.run(read_pages())) == raw


def test_failure_still_bounds_output(monkeypatch):
    def fail(_):
        raise OSError("disk full")
    monkeypatch.setattr(browser_output, "_persist_user_tabs", fail)
    raw = {"tabs": tabs()}
    out = checked(raw)
    assert out["truncated"] and out["has_more"]
    assert 0 < out["returned"] == len(out["tabs"]) < 100
    assert out["tabs"] == raw["tabs"][:out["returned"]]
    assert "path" not in out and "落盘失败" in out["hint"]
    giant = checked({"tabs": [{"tabId": 1, "title": "x" * 100000}]})
    assert giant["tabs"] == [] and giant["returned"] == 0


def test_directory_failure_does_not_return_all(monkeypatch, tmp_path):
    bad = tmp_path / "not-a-directory"
    bad.write_text("occupied")
    monkeypatch.setattr(B, "_USER_TABS_DIR", str(bad))
    out = checked({"tabs": tabs()})
    assert out["truncated"] and "path" not in out
    assert out["returned"] < out["total"]


def test_write_failure_removes_partial_file(monkeypatch):
    def fail(*args, **kwargs):
        args[1].write("partial")
        raise OSError("disk full")
    monkeypatch.setattr(browser_output.json, "dump", fail)
    out = checked({"tabs": tabs()})
    assert "path" not in out and out["truncated"]
    assert list(Path(B._USER_TABS_DIR).iterdir()) == []


def test_concurrent_files_do_not_collide():
    raws = [{"tabs": [{"tabId": i, "title": "x" * 50000}]} for i in range(20)]
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(checked, raws))
    assert len({out["path"] for out in results}) == len(raws)
    for raw, out in zip(raws, results):
        assert json.loads(Path(out["path"]).read_text()) == raw


def test_metadata_only_overflow():
    raw = {"tabs": [], "extra": "x" * 50000}
    out = checked(raw)
    assert out["truncated"] and out["total"] == out["returned"] == 0
    assert out["has_more"] is False
    assert json.loads(Path(out["path"]).read_text()) == raw


def test_tab_tool_calls_packer_through_legacy_patch(monkeypatch):
    raw = {"tabs": tabs()}
    calls = []
    async def fake_call(method, params, **kwargs):
        calls.append((method, params, kwargs))
        return raw
    monkeypatch.setattr(B, "_call", fake_call)
    monkeypatch.setattr(B, "mark_authorized", lambda _: None)
    result = asyncio.run(B.BrowserTabTool().run(action="user_list"))
    assert len(result) <= B._USER_TABS_MAX_CHARS
    assert json.loads(result)["truncated"] is True
    assert calls == [("tab_user_list", {}, {})]
    assert B.BrowserTabTool.no_compress is True


@pytest.mark.parametrize("module", ["browser_output", "browser_selectors", "browser_runtime",
                                    "browser_sessions", "browser_tabs", "browser_page", "browser_network"])
def test_implementations_import_before_facade(module):
    code = f"import ethan.tools.builtin.{module}; import ethan.tools.builtin.browser"
    subprocess.run([sys.executable, "-c", code], check=True, capture_output=True)
