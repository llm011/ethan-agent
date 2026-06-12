from dataclasses import dataclass, field
from datetime import datetime

from ethan.core.config import get_config
from ethan.memory.facts import FactStore
from ethan.memory.procedures import ProcedureStore
from ethan.providers.base import Message
from ethan.providers.manager import create_provider
from ethan.skills.registry import SkillRegistry
from ethan.tools.base import ToolResult
from ethan.tools.registry import ToolExecutor, ToolRegistry


@dataclass
class UsageStats:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_tokens: int = 0

    def add(self, usage: dict | None) -> None:
        if not usage:
            return
        self.input_tokens += usage.get("input", 0)
        self.output_tokens += usage.get("output", 0)
        self.cache_tokens += usage.get("cache", 0)


class Agent:
    def __init__(
        self,
        tool_registry: ToolRegistry | None = None,
        skill_registry: SkillRegistry | None = None,
        model: str | None = None,
        system: str | None = None,
    ):
        config = get_config()
        self._provider = create_provider(model)
        self._registry = tool_registry or ToolRegistry()
        self._executor = ToolExecutor(self._registry)
        self._skills = skill_registry
        self._procedures = ProcedureStore()
        self._facts = FactStore()
        self._base_system = system or config.defaults.system_prompt
        self._max_iterations = config.defaults.max_tool_iterations
        self.usage = UsageStats()

    def _build_system(self, messages: list[Message]) -> str:
        """构建 system prompt，注入时间、长期记忆、Skills、Procedures。"""
        import os
        from pathlib import Path

        config = get_config()
        workspace = config.defaults.workspace
        system_dir = Path(workspace) / "system"
        
        identity_path = system_dir / "identity.md"
        soul_path = system_dir / "soul.md"
        format_path = system_dir / "format.md"

        identity_content = ""
        if identity_path.exists():
            identity_content = identity_path.read_text(encoding="utf-8").strip()

        soul_content = ""
        if soul_path.exists():
            soul_content = soul_path.read_text(encoding="utf-8").strip()

        format_content = ""
        if format_path.exists():
            format_content = format_path.read_text(encoding="utf-8").strip()

        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S %A")
        
        parts = []
        if identity_content:
            parts.append(f"<identity>\n{identity_content}\n</identity>")
        elif self._base_system:
            parts.append(self._base_system)
            
        if soul_content:
            parts.append(f"<operating_principles>\n{soul_content}\n</operating_principles>")
            
        if format_content:
            parts.append(f"<formatting_rules>\n{format_content}\n</formatting_rules>")
            
        parts.append(f"Current time: {now}")
        parts.append(f"Your workspace directory is {workspace}. System configurations and memories reside here.")

        # Long-term facts (cold memory) — injected for all interfaces
        facts_ctx = self._facts.build_context(max_facts=15)
        if facts_ctx:
            parts.append(f"<user_context>\n{facts_ctx}\n</user_context>")

        # Procedural memory
        proc_ctx = self._procedures.build_context()
        if proc_ctx:
            parts.append(f"<procedures>\n{proc_ctx}\n</procedures>")

        # Skills
        if self._skills and messages:
            last_user = ""
            for m in reversed(messages):
                if m.role == "user" and m.content:
                    last_user = m.content
                    break
            if last_user:
                skill_ctx = self._skills.build_context(last_user)
                if skill_ctx:
                    parts.append(f"<relevant_skills>\n{skill_ctx}\n</relevant_skills>")

        return "\n\n".join(parts)

    async def chat(self, messages: list[Message]) -> Message:
        """运行 ReAct loop，直到 LLM 返回非 tool_call 的回复。"""
        working = list(messages)
        tools = [t.to_definition() for t in self._registry.all()] or None
        system = self._build_system(working)

        for _ in range(self._max_iterations):
            response = await self._provider.chat(working, tools=tools, system=system)
            self.usage.add(response.usage)
            working.append(response)

            if not response.is_tool_call:
                return response

            results: list[ToolResult] = await self._executor.execute(response.tool_calls)
            for r in results:
                working.append(Message(
                    role="tool",
                    content=r.content,
                    tool_call_id=r.tool_call_id,
                ))

        return Message(role="assistant", content="[max tool iterations reached]")

    async def stream_chat(self, messages: list[Message]):
        """流式 ReAct loop。Yields str chunks and ToolEvent objects."""
        from ethan.providers.base import ToolEvent

        working = list(messages)
        tools = [t.to_definition() for t in self._registry.all()] or None
        system = self._build_system(working)

        for _ in range(self._max_iterations):
            full_content = ""
            final_chunk = None

            async for chunk in self._provider.stream_chat(
                working, tools=tools, system=system
            ):
                if chunk.content:
                    full_content += chunk.content
                    yield chunk.content
                if chunk.is_final:
                    final_chunk = chunk
                    self.usage.add(chunk.usage)

            tool_calls = final_chunk.tool_calls if final_chunk else []
            response = Message(role="assistant", content=full_content, tool_calls=tool_calls)
            working.append(response)

            if not response.is_tool_call:
                return

            # Emit tool events + execute
            for tc in tool_calls:
                args_summary = ", ".join(f"{k}={str(v)[:30]}" for k, v in list(tc.arguments.items())[:2])
                yield ToolEvent(tool_name=tc.name, args_summary=args_summary, state="start")

            results: list[ToolResult] = await self._executor.execute(tool_calls)

            for r, tc in zip(results, tool_calls):
                preview = r.content[:60].replace("\n", " ") if r.content else ""
                yield ToolEvent(tool_name=tc.name, args_summary="", state="done" if not r.is_error else "error", result_preview=preview)
                working.append(Message(
                    role="tool",
                    content=r.content,
                    tool_call_id=r.tool_call_id,
                ))
