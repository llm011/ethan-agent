"""记忆列表接口的分页契约。

前端（Android / Web / Desktop）下滑加载更多完全依赖这些端点的
``total`` / ``limit`` / ``offset``，所以这里直接跑真实路由（store 指向临时 db），
锁住对外契约：

- ``/memory/facts`` 的 status 过滤**必须下推到 SQL**，再 LIMIT/OFFSET。
  这条是本次最关键的回归点：早先是「先取 1000 再在 Python 里过滤」，
  改错会静默漏数据（表现为「翻到头但条数比 total 少」）。
- ``/memory/records`` 的 ``type`` 支持逗号分隔多值，且多值共用**同一个 offset**。
- ``/memory/insights`` 与 ``/memory/insights/date/{d}`` 形状对齐。
- ``/memory/procedures`` 刻意不分页（位置下标删除后会整体前移），只补 total。
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ethan.interface.routers import memory as memory_mod
from ethan.interface.routers.deps import verify_token
from ethan.memory.records import MemoryEvidence, MemoryRecord, MemoryStatus
from ethan.memory.store import MemoryStore


def _make_record(idx: int, *, status: str = MemoryStatus.ACTIVE.value,
                 memory_type: str = "preference", domain: str = "general") -> MemoryRecord:
    """造一条可入库的记录。

    ``updated_at`` 用 idx 递增 —— list_memories 按 ``updated_at DESC`` 排序，
    这样分页顺序是确定的，测试才能断言「无重无漏」。
    """
    return MemoryRecord(
        id=f"mem-{idx:03d}",
        user_id="u",
        memory_type=memory_type,
        dimension="preference",
        memory_key=f"key-{idx}",
        content=f"fact-{idx}",
        structured_data={},
        scope_type="user",
        scope_id="self",
        memory_domain=domain,
        status=status,
        evidence_level="explicit",
        confidence=0.9,
        importance=0.5,
        sensitivity="normal",
        source_session_id="s",
        source_message_id="m",
        created_at=float(idx),
        updated_at=float(idx),
    )


def _make_evidence(record: MemoryRecord) -> MemoryEvidence:
    return MemoryEvidence(
        id=f"ev-{record.id}",
        memory_id=record.id,
        candidate_id="",
        evidence_level="explicit",
        source_session_id="s",
        source_message_id="m",
        source_role="user",
        source_quote="q",
        observed_at=0.0,
        extractor_version="v1",
        created_at=0.0,
    )


def _seed(store: MemoryStore, records: list[MemoryRecord]) -> None:
    """写库，返回写入顺序。active 记录强制要求 evidence，一起造上。"""
    for r in records:
        store.create_memory_with_evidence(r, [_make_evidence(r)])


@pytest.fixture()
def store(tmp_path):
    """给测试用的写库句柄（seed 用），与路由各自开自己的连接。

    路由的 `finally: store.close()` 会关掉自己那份连接，所以两边必须分开 ——
    共享一个实例的话第一个请求之后 seed 句柄就失效了。
    """
    return MemoryStore(db_path=tmp_path / "memory.db")


@pytest.fixture()
def client(tmp_path, monkeypatch):
    from ethan.interface.routers import memory as mod

    db = tmp_path / "memory.db"
    monkeypatch.setattr(mod, "_memory_store", lambda: MemoryStore(db_path=db))
    monkeypatch.setattr(mod, "_structured_store", lambda: MemoryStore(db_path=db))
    app = FastAPI()
    app.include_router(mod.router)
    app.dependency_overrides[verify_token] = lambda: "test-user"
    return TestClient(app, raise_server_exceptions=False)


# ── /memory/facts ──────────────────────────────────────────────────────────

def test_facts_paging_covers_all_without_gaps(client, store):
    """逐页翻完 facts，无重无漏，且每页 total 一致。"""
    _seed(store, [_make_record(i) for i in range(7)])

    seen: list[str] = []
    offset = 0
    while True:
        body = client.get("/memory/facts", params={"limit": 3, "offset": offset}).json()
        assert body["total"] == 7
        assert body["limit"] == 3
        assert body["offset"] == offset
        page = [f["id"] for f in body["facts"]]
        assert len(page) <= 3
        seen.extend(page)
        offset += len(page)
        if offset >= body["total"] or not page:
            break

    assert len(seen) == 7
    assert len(set(seen)) == 7, f"翻页出现重复：{seen}"


def test_facts_status_filter_applies_before_paging(client, store):
    """过滤必须发生在 LIMIT/OFFSET **之前**。

    造一批 forgotten 记录排在 active 之前（updated_at 更大）。如果实现还是
    「先取一页再过滤」，第一页就会被 forgotten 占满 → 返回空列表，
    这也是旧实现（limit=1000 后过滤）在数据量大时的症状。
    """
    # forgotten 的 updated_at 更大，会排在 active 前面
    _seed(store, [
        _make_record(i, status=MemoryStatus.FORGOTTEN.value) for i in range(100, 110)
    ])
    _seed(store, [_make_record(i) for i in range(3)])

    body = client.get("/memory/facts", params={"limit": 3, "offset": 0}).json()
    ids = [f["id"] for f in body["facts"]]

    assert body["total"] == 3, "forgotten 不应计入 total"
    assert len(ids) == 3, "forgotten 不应占掉分页名额"
    assert all(i.startswith("mem-00") for i in ids), ids


def test_facts_superseded_are_visible_and_counted(client, store):
    """superseded 仍在 facts 页可见（旧语义），且计入 total。"""
    _seed(store, [
        _make_record(0),
        _make_record(1, status=MemoryStatus.SUPERSEDED.value),
    ])
    body = client.get("/memory/facts").json()
    assert body["total"] == 2
    assert len(body["facts"]) == 2


def test_facts_domain_filter_excludes_companion(client, store):
    """companion 域不进 facts 页，也不应占分页名额。"""
    _seed(store, [
        _make_record(0),
        # companion 域强制要求 companion type（records.py 的不变式）
        _make_record(1, memory_type="companion", domain="companion"),
    ])
    body = client.get("/memory/facts", params={"limit": 1}).json()
    assert body["total"] == 1
    assert [f["id"] for f in body["facts"]] == ["mem-000"]


def test_facts_empty_list(client, store):
    body = client.get("/memory/facts").json()
    assert body["facts"] == []
    assert body["total"] == 0


def test_facts_offset_past_end_is_empty_not_error(client, store):
    _seed(store, [_make_record(i) for i in range(2)])
    body = client.get("/memory/facts", params={"offset": 50}).json()
    assert body["facts"] == []
    assert body["total"] == 2


# ── /memory/records ────────────────────────────────────────────────────────

def test_records_paging_reports_total(client, store):
    _seed(store, [_make_record(i, memory_type="preference") for i in range(5)])
    body = client.get("/memory/records", params={"limit": 2, "offset": 0}).json()
    assert body["total"] == 5
    assert body["limit"] == 2
    assert body["offset"] == 0
    assert len(body["items"]) == 2


def test_records_type_accepts_multiple_values_with_one_offset(client, store):
    """多 type 一次请求、一个 offset（Web「决定与约定」tab = decision+relationship）。

    分页语义必须是「合并后切页」：offset=2 时拿到的应该是合并序列的第三条起，
    而不是两个 type 各自跳过 2 条。
    """
    _seed(store, [_make_record(i, memory_type="decision") for i in range(4)])
    _seed(store, [_make_record(i, memory_type="relationship") for i in range(100, 104)])

    first = client.get(
        "/memory/records", params={"type": "decision,relationship", "limit": 3, "offset": 0}
    ).json()
    second = client.get(
        "/memory/records", params={"type": "decision,relationship", "limit": 3, "offset": 3}
    ).json()

    assert first["total"] == 8
    ids = [r["id"] for r in first["items"]] + [r["id"] for r in second["items"]]
    assert len(ids) == 6
    assert len(set(ids)) == 6, f"多 type 分页出现重复：{ids}"


def test_records_total_matches_filter(client, store):
    _seed(store, [
        _make_record(0, memory_type="decision"),
        _make_record(1, memory_type="preference"),
    ])
    body = client.get("/memory/records", params={"type": "decision"}).json()
    assert body["total"] == 1


# ── /memory/insights ───────────────────────────────────────────────────────

def test_insights_shape_is_stable(client):
    """insights 走向量库，这里只锁「形状不变」（total/limit/offset 齐全）。"""
    body = client.get("/memory/insights", params={"limit": 5, "offset": 0}).json()
    assert set(body) >= {"total", "items", "limit", "offset"}
    assert body["limit"] == 5
    assert body["offset"] == 0


def test_insights_by_date_shape_matches_list(client, monkeypatch):
    """by-date 分支要与列表分支形状对齐，前端两条分支才能共用分页逻辑。"""
    from ethan.memory import daily_consolidation

    async def _fake(d, limit=20, offset=0):
        return {"date": d.isoformat(), "total": 0, "items": [], "limit": limit, "offset": offset}

    monkeypatch.setattr(daily_consolidation, "get_memories_by_date", _fake)

    body = client.get("/memory/insights/date/2026-01-02", params={"limit": 7}).json()
    assert body["date"] == "2026-01-02"
    assert body["total"] == 0
    assert body["items"] == []
    assert body["limit"] == 7


def test_insights_by_date_rejects_bad_date(client):
    assert client.get("/memory/insights/date/not-a-date").status_code == 400


# ── /memory/procedures（刻意不分页）────────────────────────────────────────

def test_procedures_returns_all_and_total(client, tmp_path, monkeypatch):
    """流程不分页：全量返回 + total。

    分页在这里是不安全的 —— id 是 enumerate 出来的位置下标，删除后整体前移，
    客户端会拿陈旧下标去改**另一条**准则（见路由里的注释）。
    """
    import ethan.memory.procedures as procedures_mod

    path = tmp_path / "playbook.json"
    seed = procedures_mod.ProcedureStore(path=path)
    for i in range(5):
        seed.add(f"准则 {i}")

    monkeypatch.setattr(
        memory_mod, "_procedure_store",
        lambda user_id: procedures_mod.ProcedureStore(path=path),
    )

    body = client.get("/memory/procedures").json()
    assert body["total"] == 5
    assert len(body["procedures"]) == 5
    assert [p["id"] for p in body["procedures"]] == ["0", "1", "2", "3", "4"]


def test_procedures_delete_shifts_ids_documented(client, tmp_path, monkeypatch):
    """把「删除会让下标前移」这个事实钉住。

    这条不是在保护一个「好行为」，而是保护我们**知道**这个行为、因此不给它
    加分页的决定 —— 哪天有人给流程加了 offset 分页，这里会提醒他先做 uuid。
    """
    import ethan.memory.procedures as procedures_mod

    path = tmp_path / "playbook.json"
    seed = procedures_mod.ProcedureStore(path=path)
    seed.add("准则 A")
    seed.add("准则 B")
    seed.add("准则 C")

    monkeypatch.setattr(
        memory_mod, "_procedure_store",
        lambda user_id: procedures_mod.ProcedureStore(path=path),
    )

    assert client.delete("/memory/procedures/1").status_code == 200
    body = client.get("/memory/procedures").json()
    # 「准则 C」从下标 2 前移到 1 —— 分页边界会因此错位
    assert [p["rule"] for p in body["procedures"]] == ["准则 A", "准则 C"]
    assert body["total"] == 2
