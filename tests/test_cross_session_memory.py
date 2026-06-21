"""跨会话记忆验证脚本。

测试流程：
1. 备份现有 facts.json，避免污染真实记忆
2. 会话 1：告诉 Agent "我最喜欢的颜色是霓虹绿"，让它用 memory_write 记住
3. 验证 facts.json 是否写入
4. 会话 2（全新 Agent，无历史）：问 "我最喜欢什么颜色"，看是否能跨会话回忆
5. 恢复备份

运行：uv run python tests/test_cross_session_memory.py
"""
import asyncio
import json
import shutil

from ethan.core.agent import Agent
from ethan.providers.base import Message
from ethan.tools.registry import ToolRegistry
from ethan.skills.registry import SkillRegistry
from ethan.tools.builtin.memory_write import MemoryWriteTool
from ethan.memory.facts import FACTS_FILE


async def main():
    print("=" * 50)
    print("跨会话记忆验证")
    print("=" * 50)

    backup = FACTS_FILE.with_suffix(".json.bak")
    backed_up = False
    if FACTS_FILE.exists():
        shutil.copy2(FACTS_FILE, backup)
        backed_up = True
        FACTS_FILE.unlink()
    else:
        FACTS_FILE.parent.mkdir(parents=True, exist_ok=True)

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

        if not FACTS_FILE.exists():
            print("❌ FAIL: facts.json 未被写入")
            return
        facts = json.loads(FACTS_FILE.read_text(encoding="utf-8"))
        print("facts.json 内容:", json.dumps(facts, ensure_ascii=False))
        if not any("霓虹绿" in f.get("content", "") or "neon" in f.get("content", "").lower() for f in facts):
            print("❌ FAIL: facts.json 未包含霓虹绿")
            return
        print("✅ 偏好已写入 facts.json")

        print("\n--- 会话 2：全新 Agent，验证跨会话回忆 ---")
        agent2 = Agent(tool_registry=registry, skill_registry=skills, channel="test")
        resp = await agent2.chat([Message(role="user", content="我最喜欢什么颜色？")])
        print("Agent 回答:", resp.content)
        if "霓虹绿" in resp.content or "neon" in resp.content.lower() or "绿" in resp.content:
            print("✅ SUCCESS: 成功跨会话回忆出颜色偏好！")
        else:
            print("❌ FAIL: 未能回忆出颜色偏好")
    finally:
        if FACTS_FILE.exists():
            FACTS_FILE.unlink()
        if backed_up and backup.exists():
            shutil.move(str(backup), str(FACTS_FILE))
            print("\n已恢复原 facts.json")
        print("=" * 50)


if __name__ == "__main__":
    asyncio.run(main())
