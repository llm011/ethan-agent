"""镜像会话并发回归测试。

背景（真实事故）：一批并行的 delegate_coding（deep-review 的多维度扫描退化成 5 次
委派）全部落在同一个 (agent, cwd)，本应复用同一条 Ethan 镜像会话。但
MirrorSession.start 的「查映射 → 建会话 → 写映射」是无锁的读-改-写，并发协程
全部查不到别人刚写的映射，各建一条，用户侧表现为「同一个任务冒出 5 条会话」。

这里用一个「load 会 await 让出控制权」的假 store 精确复现该竞态：修复前 5 个并发
协程会建出 5 条会话；修复后（按 (agent, cwd) 加锁）只建 1 条。
"""
from __future__ import annotations

import asyncio
import weakref

import pytest

from ethan.acp import mirror as mirror_mod
from ethan.acp.session import _mirror_key, update_sessions


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def _isolated_data_dir(tmp_path, monkeypatch):
    """把 ETHAN_DATA_DIR 指到 tmp，避免污染真实 ~/.ethan/acp_sessions.json。

    同时重置模块级 asyncio.Lock：Lock 会绑定创建它的 event loop，而每个测试用例
    用 asyncio.run 起独立 loop，跨 loop 复用旧 Lock 会 raise。生产环境只有一个常驻
    loop，不存在这个问题。
    """
    monkeypatch.setenv("ETHAN_DATA_DIR", str(tmp_path))
    # config.CONFIG_DIR 在 import 时已定值，需同时 patch 模块属性
    import ethan.core.config as config_mod

    monkeypatch.setattr(config_mod, "CONFIG_DIR", tmp_path)
    # paths 通过 config.CONFIG_DIR 间接取
    import ethan.core.paths as paths_mod

    monkeypatch.setattr(paths_mod, "user_data_dir", lambda: tmp_path)

    # session.py 是 `from ethan.core.paths import user_data_dir`（按值导入），
    # 需 patch session 模块内的名字。
    import ethan.acp.session as acp_session_mod

    monkeypatch.setattr(acp_session_mod, "user_data_dir", lambda: tmp_path)

    # 重置跨 loop 的锁，避免 "attached to a different loop"
    monkeypatch.setattr(acp_session_mod, "_sessions_lock", asyncio.Lock())
    monkeypatch.setattr(acp_session_mod, "_mapping_locks", weakref.WeakValueDictionary())
    monkeypatch.setattr(acp_session_mod, "_mapping_locks_pinned", {})
    yield tmp_path


class FakeSession:
    def __init__(self, sid: str):
        self.id = sid


class FakeStore:
    """假 SessionStore：create 每次返回新 id，load 总是命中（模拟镜像会话存在）。

    load 里显式 await asyncio.sleep(0) 让出控制权——这正是原竞态的触发点：
    无锁时 N 个协程会在这里交错，全部查不到未写入的映射。
    """

    def __init__(self):
        self.created: list[str] = []
        self._n = 0
        self.messages: list[tuple[str, str]] = []

    async def create(self, model: str, source: str = "web", mode: str = "") -> FakeSession:
        self._n += 1
        sid = f"s_fake_{self._n}"
        self.created.append(sid)
        await asyncio.sleep(0)
        return FakeSession(sid)

    async def load(self, session_id: str):
        await asyncio.sleep(0)  # 关键：模拟真实 DB IO，暴露并发交错窗口
        return FakeSession(session_id)

    async def update_title(self, session_id: str, title: str) -> None:
        await asyncio.sleep(0)

    async def save_message(self, session_id: str, msg) -> int:
        self.messages.append((session_id, msg.content))
        await asyncio.sleep(0)
        return 1

    async def touch(self, session_id: str) -> None:
        await asyncio.sleep(0)


@pytest.fixture
def fake_store(monkeypatch):
    store = FakeStore()

    async def _get_store():
        return store

    import ethan.memory.session as session_store_mod

    monkeypatch.setattr(session_store_mod, "get_session_store", _get_store)
    # mirror.py 在函数内 `from ethan.memory.session import get_session_store`，patch 模块属性即可
    return store


def test_concurrent_mirror_start_creates_single_session(monkeypatch, fake_store):
    """5 个并发 start（同 agent+cwd）只应建 1 条镜像会话。"""

    async def _fanout():
        return await asyncio.gather(*(
            mirror_mod.MirrorSession.start(
                agent="claude", task=f"扫描维度{i}", cwd="/tmp/pr_322_ctx", user_id="",
            )
            for i in range(5)
        ))

    results = _run(_fanout())

    created = fake_store.created
    assert len(created) == 1, f"应只创建 1 条镜像会话，实际 {len(created)}: {created}"
    # 所有并发调用应拿到同一条会话 id
    assert {r.session_id for r in results} == {created[0]}


def test_sequential_start_reuses_session(fake_store):
    """串行多轮委派复用同一条镜像会话（多轮对话语义不能被修复破坏）。"""
    r1 = _run(mirror_mod.MirrorSession.start(
        agent="claude", task="第一轮", cwd="/tmp/proj", user_id="",
    ))
    r2 = _run(mirror_mod.MirrorSession.start(
        agent="claude", task="第二轮", cwd="/tmp/proj", user_id="",
    ))

    assert len(fake_store.created) == 1
    assert r1.session_id == r2.session_id


def test_different_cwd_creates_separate_sessions(fake_store):
    """不同 cwd 是独立镜像会话（按 (agent, cwd) 隔离，锁不能过度串成一条）。"""
    r1 = _run(mirror_mod.MirrorSession.start(
        agent="claude", task="A", cwd="/tmp/proj_a", user_id="",
    ))
    r2 = _run(mirror_mod.MirrorSession.start(
        agent="claude", task="B", cwd="/tmp/proj_b", user_id="",
    ))

    assert len(fake_store.created) == 2
    assert r1.session_id != r2.session_id


def test_reset_session_forces_new_session(fake_store):
    """reset_session=True 强制新建一条（切换任务语义）。"""
    r1 = _run(mirror_mod.MirrorSession.start(
        agent="claude", task="任务一", cwd="/tmp/proj", user_id="",
    ))
    r2 = _run(mirror_mod.MirrorSession.start(
        agent="claude", task="任务二", cwd="/tmp/proj", user_id="", reuse=False,
    ))

    assert len(fake_store.created) == 2
    assert r1.session_id != r2.session_id


def test_concurrent_mapping_writes_do_not_lose_entries(tmp_path):
    """并发的映射写不应互相覆盖丢 key（原 _load→改→_save 读改写竞态）。"""

    async def _hammer():
        await asyncio.gather(*(
            update_sessions(lambda s, i=i: s.__setitem__(f"k{i}", i))
            for i in range(20)
        ))

    _run(_hammer())

    from ethan.acp.session import _load_sessions

    saved = _load_sessions()
    assert len([k for k in saved if k.startswith("k")]) == 20, saved


def test_mirror_key_isolated_by_agent():
    """同一 cwd 下不同 agent 是不同 key（claude/codex 不互相覆盖）。"""
    assert _mirror_key("/tmp/x", "claude") != _mirror_key("/tmp/x", "codex")


# ── review 反馈：文件损坏不再放大 / 非镜像入口也纳入锁 / 锁不无上限增长 ──

def test_corrupt_file_raises_instead_of_overwriting(tmp_path):
    """文件解析失败时应报错，而不是拿空 dict 覆盖掉原内容。

    否则「读失败返回 {} → mutate 加一个 key → 整份写回」会把原文件里其它映射全丢。
    """
    from ethan.acp.session import (
        SessionsFileCorruptError,
        _sessions_path,
        set_session,
    )

    p = _sessions_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    # 模拟半截写入：文件存在但不是合法 JSON
    p.write_text('{"claude::/old/proj": "sess_keep",  <<<truncated', encoding="utf-8")
    original = p.read_text(encoding="utf-8")

    with pytest.raises(SessionsFileCorruptError):
        _run(set_session("/tmp/new", "sess_new", user_id="", agent="claude"))

    # 关键：原文件必须原封不动（没有被空 dict 覆盖成只剩一个新 key）
    assert p.read_text(encoding="utf-8") == original, "损坏文件不该被覆盖写"


def test_corrupt_file_read_returns_none_not_crash(tmp_path):
    """读侧对损坏文件放宽：续接信息拿不到就当作无历史，不该让委派整个炸掉。"""
    from ethan.acp.session import _sessions_path, get_mirror_session, get_session

    p = _sessions_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("not json at all", encoding="utf-8")

    assert get_session("/tmp/x", agent="claude") is None
    assert get_mirror_session("/tmp/x", agent="claude") is None


def test_non_mirror_entry_points_share_file_lock(tmp_path):
    """clear_session（reset_session 走这里）不得覆盖掉并发的镜像映射写入。

    旧实现里 clear_session / set_session 是同步无锁读改写，与镜像映射共用同一份
    acp_sessions.json，会把并发写入的映射整份抹掉——本 PR 之前只堵了 mirror 那一半。
    """

    async def _hammer():
        async def _mirror_writer(n: int):
            for i in range(n):
                await update_sessions(lambda s, i=i: s.__setitem__(f"mirror::k{i}", i))
                await asyncio.sleep(0)

        async def _clear_writer(n: int):
            for _ in range(n):
                # reset_session 路径：反复清同一个 key，整份读改写
                await update_sessions(lambda s: s.pop("claude::/tmp/p", None))
                await asyncio.sleep(0)

        await asyncio.gather(_mirror_writer(15), _clear_writer(15))

    _run(_hammer())

    from ethan.acp.session import _load_sessions

    saved = _load_sessions()
    got = sorted(k for k in saved if k.startswith("mirror::k"))
    assert len(got) == 15, f"镜像映射被并发 clear 覆盖丢失：{got}"


def test_mapping_locks_are_reclaimed_not_unbounded(tmp_path):
    """锁表不该随 (agent, cwd) 数量无上限增长（弱引用 + 用后回收）。"""
    import gc

    from ethan.acp.session import _mapping_locks, _mapping_locks_pinned, mapping_lock

    async def _use_many(n: int):
        for i in range(n):
            async with mapping_lock(f"key_{i}"):
                pass

    _run(_use_many(200))
    gc.collect()

    # 临界区结束后不该还 pin 着任何锁
    assert _mapping_locks_pinned == {}, _mapping_locks_pinned
    # 弱引用表里的锁应已被回收（允许少量因解释器引用滞后残留）
    assert len(_mapping_locks) < 50, f"锁表未回收，残留 {len(_mapping_locks)} 把"


def test_mapping_lock_actually_mutually_excludes(tmp_path):
    """弱引用改造后互斥仍必须生效（不能因为锁被 GC 掉退化成无锁）。"""
    from ethan.acp.session import mapping_lock

    events: list[str] = []

    async def _worker(i: int):
        async with mapping_lock("same_key"):
            events.append(f"enter{i}")
            await asyncio.sleep(0)   # 让出：无锁时这里会交错
            events.append(f"exit{i}")

    async def _fanout():
        await asyncio.gather(*(_worker(i) for i in range(4)))

    _run(_fanout())

    # 必须严格成对出现（enter 后紧跟同号的 exit），否则说明临界区交错了
    pairs = [events[i:i + 2] for i in range(0, len(events), 2)]
    assert all(p[0] == f"enter{p[1][4:]}" for p in pairs), events
