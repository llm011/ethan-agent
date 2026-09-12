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
    monkeypatch.setattr(acp_session_mod, "_mapping_locks", acp_session_mod.defaultdict(asyncio.Lock))
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
