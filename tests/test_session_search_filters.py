"""会话搜索（search/count_search）与筛选参数合成、分页语义测试。

回归背景（PR #304 深度 review 发现）：/sessions 的 q 分支直接 store.search(q, limit)，
无视 title_prefixes / has_images / hide_* / mode / source / offset —— 搜索词 + 分类筛选
组合静默失效，且搜索翻页会重复拿同一批数据。

修复后语义：
- search/count_search 支持与 list_recent 一致的会话级过滤（source/mode/标题前缀/含图），
  过滤条件在 SQL 层与搜索词 AND 合成
- search 支持 offset 分页（标题命中 + 内容命中合并排序后切片）
- count_search 的 total 与 search 结果数一致
"""

import asyncio

from ethan.memory.session import SessionStore
from ethan.providers.base import Message


async def _mk_store(tmp_path):
    store = SessionStore(db_path=tmp_path / "s.db")
    await store.init()
    return store


async def _seed(store) -> dict[str, str]:
    """造 4 个会话：定时/心跳/带图/普通，内容都含关键词「苹果」便于按 q 命中。"""
    ids = {}
    sched = await store.create("m", source="web", mode="")
    await store.update_title(sched.id, "[定时] 我的计划")
    await store.save_message(sched.id, Message(role="user", content="帮我排期苹果项目"))
    ids["sched"] = sched.id

    hb = await store.create("m", source="web", mode="")
    await store.update_title(hb.id, "[心跳] 今日系统维护")
    await store.save_message(hb.id, Message(role="assistant", content="苹果项目无异常"))
    ids["hb"] = hb.id

    img = await store.create("m", source="web", mode="")
    await store.update_title(img.id, "产品原型讨论")
    await store.save_message(img.id, Message(
        role="user", content="这是苹果项目的原型",
        images=[{"data": "aGVsbG8=", "media_type": "image/png"}],
    ))
    ids["img"] = img.id

    plain = await store.create("m", source="web", mode="")
    await store.update_title(plain.id, "普通闲聊")
    await store.save_message(plain.id, Message(role="user", content="最近苹果便宜了吗"))
    ids["plain"] = plain.id
    return ids


def test_search_plain_still_works(tmp_path):
    """回归：无过滤参数时 search 行为不变（标题/内容都能命中）。"""
    async def _run():
        store = await _mk_store(tmp_path)
        ids = await _seed(store)
        hits = await store.search("苹果", 50)
        got = {s.id for s in hits}
        assert got == {ids["sched"], ids["hb"], ids["img"], ids["plain"]}, "纯搜索应命中全部含「苹果」会话"
        # 标题命中（搜索词只在标题里的会话）也正常
        await store.update_title(ids["plain"], "苹果熟了没")
        hits2 = await store.search("苹果熟了", 50)
        assert any(s.id == ids["plain"] for s in hits2), "标题命中会话应返回"

    asyncio.run(_run())


def test_search_with_include_prefix(tmp_path):
    """搜索词 + 分类（include_title_prefixes=[定时]）：只返回该前缀且含关键词的会话。"""
    async def _run():
        store = await _mk_store(tmp_path)
        ids = await _seed(store)
        hits = await store.search("苹果", 50, include_title_prefixes=["[定时]"])
        got = {s.id for s in hits}
        assert got == {ids["sched"]}, f"只应命中定时会话，实际 {got}"

    asyncio.run(_run())


def test_search_excludes_hidden_prefixes(tmp_path):
    """搜索词 + hide（exclude_title_prefixes=[心跳,定时]）：排除系统会话。"""
    async def _run():
        store = await _mk_store(tmp_path)
        ids = await _seed(store)
        hits = await store.search("苹果", 50, exclude_title_prefixes=["[定时]", "[心跳]"])
        got = {s.id for s in hits}
        assert got == {ids["img"], ids["plain"]}, f"应排除定时/心跳会话，实际 {got}"

    asyncio.run(_run())


def test_search_with_has_images(tmp_path):
    """搜索词 + 图片（has_images=True）：只返回含图会话。"""
    async def _run():
        store = await _mk_store(tmp_path)
        ids = await _seed(store)
        hits = await store.search("苹果", 50, has_images=True)
        got = {s.id for s in hits}
        assert got == {ids["img"]}, f"只应命中带图会话，实际 {got}"

    asyncio.run(_run())


def test_search_respects_offset_pagination(tmp_path):
    """搜索分页：offset 生效，翻页不重复不遗漏。"""
    async def _run():
        store = await _mk_store(tmp_path)
        ids = await _seed(store)
        total_ids = {ids["sched"], ids["hb"], ids["img"], ids["plain"]}
        page1 = await store.search("苹果", 50, offset=0)
        assert len(page1) == 4, f"第一页应返回全部 4 条，实际 {len(page1)}"
        # 小页宽验证切片：limit=2 取两页应覆盖全部且无重复
        p1 = await store.search("苹果", 2, offset=0)
        p2 = await store.search("苹果", 2, offset=2)
        p3 = await store.search("苹果", 2, offset=4)
        got = {s.id for s in p1 + p2 + p3}
        assert len(p1) == 2 and len(p2) == 2 and len(p3) == 0, \
            f"分页大小异常 p1={len(p1)} p2={len(p2)} p3={len(p3)}"
        assert got == total_ids, f"翻页应覆盖全部且无重复，实际 {got}"
        assert {s.id for s in p1}.isdisjoint({s.id for s in p2}), "两页不应有重复会话"

    asyncio.run(_run())


def test_count_search_matches_filtered_search(tmp_path):
    """count_search 与 search 在相同过滤条件下的总数一致。"""
    async def _run():
        store = await _mk_store(tmp_path)
        ids = await _seed(store)
        # 无过滤
        hits = await store.search("苹果", 50)
        total = await store.count_search("苹果")
        assert total == len(hits) == 4, f"total={total} hits={len(hits)}"
        # 定时前缀
        hits = await store.search("苹果", 50, include_title_prefixes=["[定时]"])
        total = await store.count_search("苹果", include_title_prefixes=["[定时]"])
        assert total == len(hits) == 1
        # 含图
        hits = await store.search("苹果", 50, has_images=True)
        total = await store.count_search("苹果", has_images=True)
        assert total == len(hits) == 1
        # 组合：排除定时/心跳 + 含图
        hits = await store.search("苹果", 50, exclude_title_prefixes=["[定时]", "[心跳]"], has_images=True)
        total = await store.count_search("苹果", exclude_title_prefixes=["[定时]", "[心跳]"], has_images=True)
        assert total == len(hits) == 1 and hits[0].id == ids["img"]

    asyncio.run(_run())
