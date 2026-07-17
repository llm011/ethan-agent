"""跨会话记忆验证脚本。

测试流程：
1. 备份现有 memory.db，避免污染真实记忆
2. 会话 1：告诉 Agent "我最喜欢的颜色是霓虹绿"，让它用 memory_write 记住
3. 验证 memories 表是否写入（结构化记忆，带证据行）
4. 会话 2（全新 Agent，无历史）：问 "我最喜欢什么颜色"，看是否能跨会话回忆
5. 恢复备份

运行：uv run python tests/test_cross_session_memory.py
"""
import asyncio
import shutil

from ethan.core.agent import Agent
from ethan.core.paths import user_vectors_db_path
from ethan.providers.base import Message
from ethan.tools.registry import ToolRegistry
from ethan.skills.registry import SkillRegistry
from ethan.tools.builtin.memory_write import MemoryWriteTool


async def main():
    print("=" * 50)
    print("跨会话记忆验证（结构化记忆）")
    print("=" * 50)

    db_path = user_vectors_db_path()
    backup = db_path.with_suffix(".db.bak")
    backed_up = False
    if db_path.exists():
        shutil.copy2(db_path, backup)
        backed_up = True

    try:
        registry = ToolRegistry()
        registry.register(MemoryWriteTool())
        skills = SkillRegistry()

        print("\n--- 会话 1：记录偏好 ---")
        agent1 = Agent(tool_registry=registry, skill_registry=skills, channel="test")
        await agent1.chat([Message(
            role="user",
            content="我最喜欢的颜色是霓虹绿。请用 memory_write 工具记住这个偏好。",
        )])

        from ethan.memory.store import MemoryStore
        store = MemoryStore()
        try:
            memories = store.list_memories(status="active", limit=200)
        finally:
            store.close()
        hit = [m for m in memories if "霓虹绿" in m.content or "neon" in m.content.lower()]
        if not hit:
            print("❌ FAIL: memories 表未包含霓虹绿")
            return
        mem = hit[0]
        print(f"✅ 偏好已写入 memories 表: [{mem.memory_type}/{mem.dimension}] {mem.content}")
        store = MemoryStore()
        try:
            evidence = store.list_evidence(mem.id)
        finally:
            store.close()
        print(f"   证据行 {len(evidence)} 条，evidence_level={mem.evidence_level}")

        print("\n--- 会话 2：全新 Agent，验证跨会话回忆 ---")
        agent2 = Agent(tool_registry=registry, skill_registry=skills, channel="test")
        resp = await agent2.chat([Message(role="user", content="我最喜欢什么颜色？")])
        print("Agent 回答:", resp.content)
        if "霓虹绿" in resp.content or "neon" in resp.content.lower() or "绿" in resp.content:
            print("✅ SUCCESS: 成功跨会话回忆出颜色偏好！")
        else:
            print("❌ FAIL: 未能回忆出颜色偏好")
    finally:
        if backed_up and backup.exists():
            shutil.move(str(backup), str(db_path))
            print("\n已恢复原 memory.db")
        print("=" * 50)


if __name__ == "__main__":
    asyncio.run(main())
