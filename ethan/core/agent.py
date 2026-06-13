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

import re

# 强制走完整 Loop 的信号（不可配置，优先级最高）
_FORCE_FULL_SIGNALS = [
    "帮我写", "写一个", "写代码", "实现", "分析", "解释", "为什么",
    "怎么", "如何", "总结", "生成", "创建", "建立", "搭建",
    "重构", "优化代码", "调试", "debug", "修复", "定时任务",
    "提醒我", "设置一个", "schedule", "reminder",
    "write", "implement", "analyze", "explain", "generate", "create",
    "why", "how to", "refactor", "summarize",
]


def _match_keyword(kw: str, text: str) -> bool:
    """关键词匹配，支持通配符 *。"""
    if "*" in kw:
        pattern = re.compile(kw.replace("*", ".*"))
        return bool(pattern.search(text))
    return kw in text


def _is_fast_path(text: str) -> bool:
    """
    任务路由判断。规则：
    1. 有 FORCE_FULL 信号 → Full Path（最高优先）
    2. 命中 config.routing.fast_skill_triggers 中任意关键词 → Fast Path（不受长度限制）
    3. 命中 config.routing.fast_keywords 且长度 ≤ fast_max_length → Fast Path
       关键词支持简单通配符 * (e.g. "关*灯" 匹配 "关客厅灯")
    4. 其余 → Full Path
    """
    lower = text.lower()

    # 强制走完整路径
    if any(sig in lower for sig in _FORCE_FULL_SIGNALS):
        return False

    routing = get_config().defaults.routing

    # Skill 关联触发词：命中即走 Fast Path，不受长度限制
    for kw in routing.fast_skill_triggers:
        if _match_keyword(kw, text):
            return True

    # 普通快捷关键词：还需满足长度限制
    if len(text.strip()) > routing.fast_max_length:
        return False

    for kw in routing.fast_keywords:
        if _match_keyword(kw, text):
            return True

    return False


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

    def _build_schedule_context(self, workspace: str) -> str:
        """读取 APScheduler SQLite 数据库，返回当前活跃定时任务摘要（不需要启动 scheduler）。"""
        from pathlib import Path
        import sqlite3, json, datetime as dt
        db_path = Path(workspace) / "scheduler.db"
        if not db_path.exists():
            return ""
        try:
            con = sqlite3.connect(str(db_path))
            rows = con.execute(
                "SELECT id, next_run_time, job_state FROM apscheduler_jobs"
            ).fetchall()
            con.close()
            if not rows:
                return ""
            lines = []
            for job_id, next_run_ts, job_state_blob in rows:
                next_run = "paused"
                if next_run_ts:
                    try:
                        next_run = dt.datetime.fromtimestamp(next_run_ts).strftime("%Y-%m-%d %H:%M")
                    except Exception:
                        pass
                # Extract prompt from kwargs if available
                prompt = ""
                try:
                    state = __import__('pickle').loads(job_state_blob)
                    prompt = state.get("kwargs", {}).get("prompt", "")[:60]
                except Exception:
                    pass
                line = f"- {job_id}: next={next_run}"
                if prompt:
                    line += f", task=\"{prompt}\""
                lines.append(line)
            return "\n".join(lines)
        except Exception:
            return ""

    def _get_last_user_text(self, messages: list[Message]) -> str:
        for m in reversed(messages):
            if m.role == "user" and m.content:
                return m.content
        return ""

    def _build_system(self, messages: list[Message], fast: bool = False) -> str:
        """构建 system prompt。fast=True 时使用极简版本减少 token。"""
        from pathlib import Path

        config = get_config()
        workspace = config.defaults.workspace
        system_dir = Path(workspace) / "system"

        identity_content = self._base_system
        if (system_dir / "identity.md").exists():
            identity_content = (system_dir / "identity.md").read_text(encoding="utf-8").strip()

        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S %A")

        if fast:
            # Fast Path: 极简 Prompt — 身份 + 时间 + 少量记忆 + 相关 Skill
            parts = [identity_content, f"Current time: {now}"]
            facts_ctx = self._facts.build_context(max_facts=5)
            if facts_ctx:
                parts.append(f"<user_context>\n{facts_ctx}\n</user_context>")
            last_user = self._get_last_user_text(messages)
            if self._skills and last_user:
                skill_ctx = self._skills.build_context(last_user)
                if skill_ctx:
                    parts.append(f"<relevant_skills>\n{skill_ctx}\n</relevant_skills>")
            return "\n\n".join(parts)

        # Full Path: 完整 Prompt
        soul_content = ""
        if (system_dir / "soul.md").exists():
            soul_content = (system_dir / "soul.md").read_text(encoding="utf-8").strip()
            soul_content = soul_content.replace("{workspace}", workspace)

        tools_content = ""
        if (system_dir / "tools.md").exists():
            tools_content = (system_dir / "tools.md").read_text(encoding="utf-8").strip()
            tools_content = tools_content.replace("{workspace}", workspace)

        identity_content = identity_content.replace("{workspace}", workspace)

        parts = [f"<identity>\n{identity_content}\n</identity>"]
        if soul_content:
            parts.append(f"<operating_principles>\n{soul_content}\n</operating_principles>")
        if tools_content:
            parts.append(f"<tools_reference>\n{tools_content}\n</tools_reference>")
        parts.append(f"Current time: {now}")
        parts.append(f"Your workspace directory is {workspace}. System configurations and memories reside here.")

        # Inject active scheduled tasks so Agent always knows them
        schedule_ctx = self._build_schedule_context(workspace)
        if schedule_ctx:
            task_count = schedule_ctx.count("\n- ") + 1
            parts.append(f"You have {task_count} active scheduled task(s). Call schedule_list to view details.")

        # Inject skills list so Agent knows its own capabilities
        if self._skills:
            skills_list = self._skills.all()
            if skills_list:
                skill_lines = [f"- {s.name}: {s.description}" for s in skills_list]
                parts.append(f"<available_skills>\n" + "\n".join(skill_lines) + "\n</available_skills>")

        facts_ctx = self._facts.build_context(max_facts=15)
        if facts_ctx:
            parts.append(f"<user_context>\n{facts_ctx}\n</user_context>")

        proc_ctx = self._procedures.build_context()
        if proc_ctx:
            parts.append(f"<procedures>\n{proc_ctx}\n</procedures>")

        last_user = self._get_last_user_text(messages)
        if self._skills and last_user:
            skill_ctx = self._skills.build_context(last_user)
            if skill_ctx:
                parts.append(f"<relevant_skills>\n{skill_ctx}\n</relevant_skills>")

        return "\n\n".join(parts)

    async def chat(self, messages: list[Message]) -> Message:
        """运行对话。Fast Path 使用简化 system prompt，Full Path 使用完整 prompt，两者均支持工具。"""
        working = list(messages)
        last_user = self._get_last_user_text(working)
        fast = _is_fast_path(last_user)
        system = self._build_system(working, fast=fast)
        if fast:
            tools_list = [t for t in self._registry.all() if t.fast_path]
        else:
            tools_list = self._registry.all()
        tools = [t.to_definition() for t in tools_list] or None

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
        """流式对话。Fast Path 使用简化 system prompt，Full Path 使用完整 prompt，两者均支持工具。"""
        from ethan.providers.base import ToolEvent

        working = list(messages)
        last_user = self._get_last_user_text(working)
        fast = _is_fast_path(last_user)
        system = self._build_system(working, fast=fast)
        if fast:
            tools_list = [t for t in self._registry.all() if t.fast_path]
        else:
            tools_list = self._registry.all()
        tools = [t.to_definition() for t in tools_list] or None

        for _ in range(self._max_iterations):
            full_content = ""
            final_chunk = None

            async for chunk in self._provider.stream_chat(working, tools=tools, system=system):
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
