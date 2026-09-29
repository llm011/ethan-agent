"""文档库（ethan/documents）测试：路径越界防护、元数据持久化、文件树、doc_save/doc_list 工具。

用 ETHAN_DOCUMENTS_DIR 指向 tmp_path 做隔离——绝不能碰用户真实的 ~/.ethan/documents。
"""
import asyncio
import os
import shutil
import tempfile
from pathlib import Path

import pytest

from ethan.documents import (
    Library,
    build_file_tree,
    count_documents,
    documents_root,
    list_flat,
    relative_to_root,
    resolve_in_root,
    sanitize_segment,
)


@pytest.fixture(autouse=True)
def _isolated_root(monkeypatch, tmp_path):
    """每个测试一个独立文档库根目录。

    刻意建在 /tmp 下而不是 pytest 的 tmp_path：doc_save 走 build_file_card，
    而 card 的 jail 只放行 home 与 /tmp（file_jail.resolve_jailed）。用
    /private/var/folders/... 会让卡片构建静默失败，测不到真实链路。
    """
    root = Path(tempfile.mkdtemp(prefix="ethan-doc-test-", dir="/tmp")) / "documents"
    monkeypatch.setenv("ETHAN_DOCUMENTS_DIR", str(root))
    yield root
    shutil.rmtree(root.parent, ignore_errors=True)


def _run(coro):
    return asyncio.run(coro)


# ── 路径安全（文档库的安全边界）─────────────────────────────────────

@pytest.mark.parametrize("evil", [
    "../../etc/passwd",
    "../../../root/.ssh/id_rsa",
    "/etc/passwd",
    "work/../../../etc/passwd",
    "..",
    "....//....//etc/passwd",
])
def test_resolve_in_root_blocks_traversal(evil):
    """越界路径必须被清洗回根目录内，绝不逃逸。"""
    root = documents_root()
    p = resolve_in_root(evil)
    assert p is not None, f"{evil} 应被清洗成根内路径而非返回 None"
    assert p.is_relative_to(root), f"{evil} 逃逸到 {p}"


def test_resolve_in_root_empty_returns_none():
    assert resolve_in_root("") is None
    assert resolve_in_root("///") is None


def test_sanitize_segment_strips_separators_and_unsafe_chars():
    assert sanitize_segment("a/b/c.md") == "c.md"
    assert sanitize_segment("..") == "_"
    assert sanitize_segment("") == "_"
    assert "/" not in sanitize_segment("a<b>c:d|e?f*g")
    # Windows 保留字符与控制字符都要清掉
    assert all(ch not in sanitize_segment(f"x{ch}y") for ch in '<>:"|?*')


# ── 元数据持久化 ──────────────────────────────────────────────────

def test_library_update_and_get():
    lib = Library()
    lib.update("work/a.md", favorite=True, session_id="s_1", message_id=42)
    meta = lib.get("work/a.md")
    assert meta.favorite is True
    assert meta.pinned is False
    assert meta.session_id == "s_1"
    assert meta.message_id == 42


def test_library_persists_across_instances():
    Library().update("life/b.md", pinned=True)
    # 新实例重新读盘（不共享内存缓存）
    assert Library().get("life/b.md").pinned is True


def test_library_rename_migrates_metadata():
    lib = Library()
    lib.update("work/old.md", favorite=True)
    lib.rename("work/old.md", "work/new.md")
    assert lib.get("work/new.md").favorite is True
    assert lib.get("work/old.md").favorite is False


def test_library_remove():
    lib = Library()
    lib.update("work/x.md", pinned=True)
    lib.remove("work/x.md")
    assert lib.get("work/x.md").pinned is False


def test_library_tolerates_corrupt_json():
    """坏 JSON 不能让整个文档页打不开。"""
    root = documents_root()
    root.mkdir(parents=True, exist_ok=True)
    (root / ".library.json").write_text("{ this is not json", encoding="utf-8")
    assert Library().all() == {}


def test_library_save_is_atomic_no_tmp_left():
    lib = Library()
    lib.update("work/a.md", favorite=True)
    root = documents_root()
    assert (root / ".library.json").exists()
    assert not list(root.glob("*.tmp"))


# ── 文件树 ────────────────────────────────────────────────────────

def _write(rel: str, content: str = "x") -> "object":
    p = resolve_in_root(rel)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return p


def test_build_file_tree_nested():
    _write("work/coze/每日MR/2026-09-30-mr.md")
    _write("life/note.md")
    tree = build_file_tree()
    names = {n.name for n in tree}
    assert names == {"work", "life"}
    work = next(n for n in tree if n.name == "work")
    assert work.is_dir and work.children[0].name == "coze"
    assert count_documents(tree) == 2


def test_build_file_tree_skips_hidden_and_unknown_exts():
    _write("work/a.md")
    _write("work/b.exe")           # 不在 DOC_EXTS
    root = documents_root()
    (root / ".hidden.md").write_text("x", encoding="utf-8")
    (root / ".library.json").write_text("{}", encoding="utf-8")
    tree = build_file_tree()
    assert count_documents(tree) == 1
    assert all(not n.name.startswith(".") for n in tree)


def test_build_file_tree_omits_empty_dirs():
    root = documents_root()
    (root / "empty_dir").mkdir(parents=True, exist_ok=True)
    assert build_file_tree() == []


def test_build_file_tree_missing_root_is_empty():
    # root 尚未创建时返回空树，而不是抛异常
    assert build_file_tree() == []


def test_tree_carries_metadata():
    _write("work/a.md")
    Library().update("work/a.md", pinned=True, session_id="s_9", message_id=7)
    work = next(n for n in build_file_tree() if n.name == "work")
    d = work.children[0].to_dict()
    assert d["pinned"] is True and d["session_id"] == "s_9" and d["message_id"] == 7
    assert d["ext"] == "md"


def test_list_flat_sorted_by_mtime_desc():
    _write("a.md")
    _write("b.md")
    root = documents_root()
    os.utime(root / "a.md", (1000, 1000))
    os.utime(root / "b.md", (2000, 2000))
    flat = list_flat()
    assert [n.name for n in flat] == ["b.md", "a.md"]
    assert [n.name for n in list_flat(limit=1)] == ["b.md"]


def test_relative_to_root_roundtrip():
    p = _write("work/coze/x.md")
    rel = relative_to_root(p)
    assert rel == "work/coze/x.md"
    assert resolve_in_root(rel) == p


# ── doc_save / doc_list 工具 ───────────────────────────────────────

def test_doc_save_writes_into_library_and_returns_card():
    from ethan.tools.builtin.documents import DocSaveTool

    r = _run(DocSaveTool().run("work/coze/日报.md", "# 日报\n内容", title="每日报告", session_id="s_1"))
    assert not isinstance(r, str), r
    assert r.cards and r.cards[0]["type"] == "file"
    card = r.cards[0]
    assert card["kind"] == "md" and card["title"] == "每日报告"
    saved = documents_root() / "work/coze/日报.md"
    assert saved.read_text(encoding="utf-8") == "# 日报\n内容"
    # 来源会话写进元数据，供「定位到对话」
    assert Library().get("work/coze/日报.md").session_id == "s_1"


def test_doc_save_traversal_stays_in_library():
    """工具入口同样不能越界——路径经 sanitize 后落在库内。"""
    from ethan.tools.builtin.documents import DocSaveTool

    r = _run(DocSaveTool().run("../../evil.md", "x"))
    assert not isinstance(r, str)
    saved = [c for c in documents_root().rglob("*.md")]
    assert len(saved) == 1
    assert saved[0].is_relative_to(documents_root())


def test_doc_save_rejects_unsupported_ext():
    from ethan.tools.builtin.documents import DocSaveTool

    r = _run(DocSaveTool().run("work/a.exe", "x"))
    assert isinstance(r, str) and "Save failed" in r and "text documents" in r


def test_doc_save_overwrites_existing():
    """同主题续写：写同一路径应覆盖而非报错。"""
    from ethan.tools.builtin.documents import DocSaveTool

    _run(DocSaveTool().run("work/a.md", "v1"))
    _run(DocSaveTool().run("work/a.md", "v2"))
    assert (documents_root() / "work/a.md").read_text(encoding="utf-8") == "v2"
    assert count_documents(build_file_tree()) == 1


def test_doc_list_reports_saved_documents():
    from ethan.tools.builtin.documents import DocListTool, DocSaveTool

    _run(DocSaveTool().run("work/a.md", "x", title="甲"))
    out = _run(DocListTool().run())
    assert "work/a.md" in out
    assert "文档库共 1 个文档" in out


def test_doc_list_prefix_filter():
    from ethan.tools.builtin.documents import DocListTool, DocSaveTool

    _run(DocSaveTool().run("work/a.md", "x"))
    _run(DocSaveTool().run("life/b.md", "x"))
    out = _run(DocListTool().run(prefix="work"))
    assert "work/a.md" in out and "life/b.md" not in out


def test_doc_list_empty_library_message():
    from ethan.tools.builtin.documents import DocListTool

    out = _run(DocListTool().run())
    assert isinstance(out, str) and out.strip()


# ── HTTP 路由 ────────────────────────────────────────────────────

@pytest.fixture
def client():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from ethan.interface.routers import documents as documents_router

    app = FastAPI()
    app.include_router(documents_router.router, prefix="/api")
    app.dependency_overrides[documents_router.verify_token] = lambda: "u1"
    return TestClient(app)


def test_route_tree_and_content(client):
    _write("work/coze/a.md", "# 标题\n正文")
    r = client.get("/api/documents/tree")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 1
    assert body["tree"][0]["path"] == "work"

    r = client.get("/api/documents", params={"path": "work/coze/a.md"})
    assert r.status_code == 200
    assert r.json()["content"] == "# 标题\n正文"


def test_route_rejects_traversal(client):
    _write("a.md")
    r = client.get("/api/documents", params={"path": "../../../etc/passwd"})
    # 越界被清洗为库内路径 → 文件不存在（404），而不是吐出 /etc/passwd
    assert r.status_code in (400, 404)
    assert "root:" not in r.text


def test_route_patch_metadata_and_move(client):
    _write("work/a.md")
    r = client.patch("/api/documents", params={"path": "work/a.md"},
                     json={"favorite": True, "pinned": True})
    assert r.status_code == 200
    assert Library().get("work/a.md").pinned is True

    r = client.post("/api/documents/move", json={"path": "work/a.md", "new_path": "life/b.md"})
    assert r.status_code == 200
    assert (documents_root() / "life/b.md").exists()
    # 收藏/置顶跟随移动
    assert Library().get("life/b.md").pinned is True


def test_route_delete(client):
    p = _write("work/a.md")
    r = client.delete("/api/documents", params={"path": "work/a.md"})
    assert r.status_code == 200
    assert not p.exists()
    assert count_documents(build_file_tree()) == 0


def test_route_delete_missing_404(client):
    assert client.delete("/api/documents", params={"path": "work/nope.md"}).status_code == 404


def test_route_root(client):
    body = client.get("/api/documents/root").json()
    assert body["root"] == str(documents_root())


def test_route_recent(client):
    _write("a.md")
    body = client.get("/api/documents/recent", params={"limit": 10}).json()
    assert len(body["items"]) == 1


# ── 可达性（回归：曾「注册了但从不广播」+「协议只进 fast 分支」）──────────
#
# doc_save 的存在意义就是「别把产出丢到 /tmp」。如果它既不在广播清单里、
# 提示词又只在一条分支介绍它，模型根本调不到，/tmp 问题会原样复发。
# 这两条曾经同时成立，所以单独钉住。


def test_doc_tools_are_broadcast_in_both_tiers():
    from ethan.core.config import get_config

    routing = get_config().defaults.routing
    for tier, names in (("full", routing.base_tools), ("fast", routing.fast_base_tools)):
        assert "doc_save" in names, f"{tier} 档没广播 doc_save → 模型只能退回 file_write"
        assert "doc_list" in names, f"{tier} 档没广播 doc_list"


def test_documents_protocol_injected_in_both_prompt_branches():
    """fast 与 full 两条 prompt 分支都要提到 doc_save。"""
    from ethan.core.system_prompt import _documents_protocol

    block = _documents_protocol()
    assert "doc_save" in block and "doc_list" in block
    # 「不要写到 /tmp」是这套机制的立意，不能丢
    assert "/tmp" in block

    from ethan.core.system_prompt import build_system_prompt
    from ethan.memory.procedures import ProcedureStore
    from ethan.providers.base import Message
    from ethan.skills.registry import SkillRegistry

    reg = _registry_with_doc_tools()
    for fast in (True, False):
        prompt = build_system_prompt(
            messages=[Message(role="user", content="帮我整理一份报告")],
            fast=fast, system_files={}, provider_model="m",
            skills=SkillRegistry(), procedures=ProcedureStore(), registry=reg,
            channel="web", mode="default", is_owner=True,
            runtime_context="", last_matched_skills_out=[],
        )
        assert "<documents_protocol>" in prompt, f"fast={fast} 分支漏注入"
        assert "doc_save" in prompt, f"fast={fast} 分支没告诉模型有 doc_save"


def _registry_with_doc_tools():
    from ethan.tools.builtin.documents import DocListTool, DocSaveTool
    from ethan.tools.registry import ToolRegistry

    reg = ToolRegistry()
    reg.register(DocSaveTool())
    reg.register(DocListTool())
    return reg


def test_doc_tool_names_match_registered_names():
    """广播清单里的名字必须与注册名逐字一致——拼错是静默失效。"""
    reg = _registry_with_doc_tools()
    for name in ("doc_save", "doc_list"):
        tool = reg.get(name)
        assert tool is not None, f"注册表里取不到 {name}"
        assert tool.name == name


def test_documents_root_is_per_profile(monkeypatch):
    """命名 profile 的文档库必须隔离，default profile 保持历史路径。"""
    from ethan.core.context import set_user_id

    monkeypatch.delenv("ETHAN_DOCUMENTS_DIR", raising=False)
    try:
        set_user_id("")
        assert documents_root() == Path.home() / ".ethan" / "documents"
        set_user_id("alice")
        assert documents_root() == Path.home() / ".ethan" / "profiles" / "alice" / "documents"
    finally:
        set_user_id("")


def test_env_override_wins_over_profile(monkeypatch):
    """ETHAN_DOCUMENTS_DIR 优先于 profile（测试隔离靠它）。"""
    from ethan.core.context import set_user_id

    set_user_id("alice")
    try:
        assert documents_root() == Path(os.environ["ETHAN_DOCUMENTS_DIR"]).resolve()
        assert "profiles" not in str(documents_root())
    finally:
        set_user_id("")


def test_doc_save_declares_side_effect():
    """写文件是有副作用的：三方渠道非主人会话须被 ChannelGuardProvider 拦下。"""
    from ethan.tools.builtin.documents import DocListTool, DocSaveTool

    assert DocSaveTool.side_effect is True
    # doc_list 只读，不该被拦
    assert DocListTool.side_effect is False
