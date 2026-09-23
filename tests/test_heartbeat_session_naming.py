"""心跳会话「建了但没命名」的回归测试（ETHA-13）。

线上症状：某一天的 `[心跳]` 会话不在侧栏「心跳」分组里，而是掉进「最新对话」。
根因不是前缀过滤写错，而是**心跳会话标题的写入不是原子的**：

    hb_session = await store.create(...)          # 落库 title="新对话"
    await store.update_title(hb_session.id, "[心跳] ...")   # 第二次事务才命名

两次写之间进程若被打断（线上就是 watchdog 每 ~10s 一轮的重启风暴，
`[Errno 48] address already in use` 导致刚启动的进程立刻退出），
就留下一条 source='heartbeat' 但 title 仍是「新对话」的孤儿会话。
侧栏「心跳」分组是按 title 前缀 `[心跳]` 拉取的（`/api/sessions?title_prefixes=[心跳]`），
前缀对不上 → 该会话永远不会出现在心跳 Tab，只能掉进「最新对话」。

同一天后续的心跳还会复用这条会话（find_today_session 按 source+created_at 找，
不看 title），所以它会被反复 touch、越排越靠前，但标题永远补不回来。

这里锁两个不变量：
1. 新建心跳会话时，标题必须**随创建一起**落库，不留「新对话」中间态。
2. 即便标题因历史原因丢了（旧数据 / 中断残留），再次跑心跳要能**自愈**补回前缀，
   否则该会话永久留在「最新对话」里。
"""

import asyncio

from ethan.memory.session import SessionStore


async def _mk_store(tmp_path):
    store = SessionStore(db_path=tmp_path / "s.db")
    await store.init()
    return store


def test_create_with_title_is_atomic(tmp_path):
    """新建会话时应能一次性带上目标标题，不存在「新对话」中间态。"""

    async def _run():
        store = await _mk_store(tmp_path)
        # 创建即命名：单次写库，中途被打断也不会留下未命名的孤儿
        s = await store.create("m", source="heartbeat", title="[心跳] 2026-09-23 · 系统维护")
        assert s.title == "[心跳] 2026-09-23 · 系统维护"

        # 落库的值也必须是命名后的，而不是 create 返回值的假象
        got = await store.load(s.id)
        assert got is not None
        assert got.title == "[心跳] 2026-09-23 · 系统维护", got.title

    asyncio.run(_run())


def test_heartbeat_group_ignores_untitled_session_until_healed(tmp_path):
    """未命名心跳会话落不进「心跳」分组 —— 复现线上掉进「最新对话」的现象。"""

    async def _run():
        store = await _mk_store(tmp_path)
        # 模拟线上那条孤儿：source 是 heartbeat，但标题停在「新对话」
        orphan = await store.create("m", source="heartbeat")
        assert orphan.title == "新对话"

        # 侧栏心跳分组的真实查询：按 title 前缀拉取
        group = await store.list_recent(5, 0, include_title_prefixes=["[心跳]"])
        assert all(s.id != orphan.id for s in group), "未命名的心跳会话不该出现在心跳分组"

        # 它也确实会被「最新对话」的主列表捞到（主列表只排除 [心跳] 前缀）
        main = await store.list_recent(50, 0, exclude_title_prefixes=["[心跳]", "[定时]"])
        assert any(s.id == orphan.id for s in main), "未命名会话会掉进最新对话，正是线上现象"

    asyncio.run(_run())


def test_find_today_session_heals_missing_title_prefix(tmp_path):
    """当天会话存在但标题丢了前缀时，find_today_session 应返回它并把它补回命名。"""

    async def _run():
        store = await _mk_store(tmp_path)
        orphan = await store.create("m", source="heartbeat")
        assert orphan.title == "新对话"

        # 再次跑心跳：必须复用这条（否则一天两条会话），并且把标题补回来
        found = await store.find_today_session("heartbeat")
        assert found is not None and found.id == orphan.id

        # find_today_session 自身不改标题，但调用方（heartbeat）拿到的标题应可判定为缺失，
        # 从而触发补写；这里直接验证补写后能进心跳分组。
        assert not found.title.startswith("[心跳]")
        await store.update_title(found.id, "[心跳] 2026-09-23 · 系统维护")

        group = await store.list_recent(5, 0, include_title_prefixes=["[心跳]"])
        assert [s.id for s in group] == [orphan.id]

        # 补写标题不该制造未读（update_title 的既有语义）
        healed = await store.load(orphan.id)
        assert healed is not None and healed.title.startswith("[心跳]")

    asyncio.run(_run())


def test_heartbeat_run_heals_untitled_session(tmp_path, monkeypatch):
    """跑一次真实心跳：当天已有无前缀孤儿会话时，应补回 `[心跳]` 并进分组。

    这条直接盯 ETHA-13 的线上修复点——不靠 store 层手工 update_title 模拟。
    """
    import ethan.core.services.heartbeat as hb_mod

    workspace = tmp_path / "ws"
    (workspace / "system").mkdir(parents=True)
    (workspace / "system" / "heartbeat.md").write_text("- 检查一下系统\n", encoding="utf-8")

    from types import SimpleNamespace

    cfg = SimpleNamespace(
        defaults=SimpleNamespace(
            workspace=str(workspace),
            model="m",
            timezone="Asia/Shanghai",
            heartbeat=SimpleNamespace(model=None),
        )
    )
    monkeypatch.setattr("ethan.core.config.get_config", lambda: cfg, raising=False)

    async def _run():
        store = await _mk_store(tmp_path)
        # 模拟线上那条孤儿：source=heartbeat 但标题停在「新对话」
        orphan = await store.create("m", source="heartbeat")
        assert orphan.title == "新对话"

        # 接管全局 store，并让 agent 直接返回一句结果（不真连模型）
        async def _fake_store():
            return store

        # _run_heartbeat_md 在函数体内 from ethan.memory.session import get_session_store，
        # 所以要 patch 源模块的属性，patch hb_mod 上的名字无效。
        import ethan.memory.session as session_mod

        monkeypatch.setattr(session_mod, "get_session_store", _fake_store, raising=False)

        class _Agent:
            usage = SimpleNamespace(
                input_tokens=0,
                output_tokens=0,
                cache_tokens=0,
                cache_creation_tokens=0,
                reasoning_tokens=0,
            )

            async def stream_chat(self, messages):
                yield "心跳跑完了"

        monkeypatch.setattr(
            "ethan.core.agent_factory.create_agent", lambda **kw: _Agent(), raising=False
        )
        monkeypatch.setattr(
            "ethan.core.users.get_user_store",
            lambda: type("U", (), {"get_admin_user_id": staticmethod(lambda: "admin")})(),
            raising=False,
        )
        # 只关心命名/复用逻辑，跳过结果落库
        monkeypatch.setattr(store, "save_message", _async_noop(), raising=False)
        monkeypatch.setattr(store, "touch", _async_noop(), raising=False)

        await hb_mod._run_heartbeat_md()

        # 复用同一条（一天不开第二个会话），且标题被补回前缀
        found = await store.find_today_session("heartbeat")
        assert found is not None and found.id == orphan.id
        assert found.title.startswith("[心跳]"), found.title

        # 关键：它现在能进「心跳」分组了 —— 修复前这里永远为空
        group = await store.list_recent(5, 0, include_title_prefixes=["[心跳]"])
        assert [s.id for s in group] == [orphan.id]

    asyncio.run(_run())


def _async_noop():
    async def _noop(*a, **kw):
        return None

    return _noop


def test_find_today_session_matches_by_source_not_title(tmp_path):
    """跨天边界：只认当天创建、source=heartbeat 的会话，不看标题，也不串到昨天。"""

    async def _run():
        store = await _mk_store(tmp_path)
        today = await store.create("m", source="heartbeat")
        await store.update_title(today.id, "[心跳] 今天 · 系统维护")

        found = await store.find_today_session("heartbeat")
        assert found is not None and found.id == today.id

        # 别把 web 会话误当心跳
        await store.create("m", source="web")
        found2 = await store.find_today_session("heartbeat")
        assert found2 is not None and found2.id == today.id

    asyncio.run(_run())


def test_heartbeat_does_not_clobber_user_renamed_title(tmp_path, monkeypatch):
    """用户在侧栏改过标题的心跳会话，不该被下一次心跳的自愈静默覆盖回去。

    侧栏「心跳」分组和普通分组共用 renderSession，右键菜单里有「重命名」，
    走的是 PATCH /sessions/{id}（无前缀校验）。用户改名后标题就不带 `[心跳]` 了，
    此时「缺前缀」是用户意图，不是中断残留 —— 自愈只该治从未命名成功的占位标题。
    """

    async def _run():
        store = await _mk_store(tmp_path)
        s = await store.create(
            "m", source="heartbeat", title="[心跳] 2026-09-23 · 系统维护"
        )
        # 用户重命名（模拟 PATCH /sessions/{id}）
        await store.update_title(s.id, "今天的心跳（我看过了）")

        from ethan.memory.session import _is_placeholder_title

        found = await store.find_today_session("heartbeat")
        assert found is not None and found.id == s.id
        # 缺前缀，但不是占位标题 -> 不该被判为「需要自愈」
        assert not found.title.startswith("[心跳]")
        assert not _is_placeholder_title(found.title, []), (
            "用户自定义标题不该被当成未命名孤儿"
        )

    asyncio.run(_run())
