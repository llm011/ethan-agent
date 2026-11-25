"""Crash-safe run state and wire transcript, committed before tool dispatch.

No checkpoint is an execution journal that permits automatic side-effect replay.
An unfinished call is always uncertain, even if cancellation was requested.
"""
from __future__ import annotations

import asyncio
import json
import time
from dataclasses import asdict, is_dataclass

from ethan.core.wire_transcript import complete_wire, restore_wire, wire_message  # noqa: F401
from ethan.providers.base import Message


def resume_context(checkpoint: dict) -> str:
    """Structured, bounded recovery context; unknown execution is not failure."""
    if not checkpoint:
        return ""
    fields = {k: checkpoint.get(k) for k in (
        "goal", "iteration", "phase", "completed_steps", "todos", "artifacts", "inflight"
    )}
    fields["completed_steps"] = (fields["completed_steps"] or [])[-10:]
    fields["inflight"] = (fields["inflight"] or [])[-20:]
    return (
        "\n\n运行检查点（结构化事实，不是重新执行指令）：\n"
        + json.dumps(fields, ensure_ascii=False)
        + "\n已完成步骤不要从头重做。inflight 的工具可能已经产生副作用，执行结果未知；"
        "禁止自动重放。先用只读查询/检查产物核实；无法核实就向用户明确说明未知状态。"
    )


class RunCheckpointRecorder:
    """Serialize concurrent completion hooks and write one transaction per event."""
    def __init__(self, store, session_id: str, message_id: int, messages: list[Message]):
        self.store = store
        self.session_id = session_id
        self.message_id = message_id
        self.history_len = len(messages)
        self.state = {
            "version": 2, "goal": next((m.content for m in reversed(messages) if m.role == "user"), ""),
            "iteration": 0, "phase": "created", "completed_steps": [],
            "todos": [], "artifacts": [], "inflight": [], "transcript": [],
        }
        self._lock = asyncio.Lock()

    async def __call__(self, payload: dict) -> None:
        async with self._lock:
            kind = payload.get("kind", "iteration")
            self.state["iteration"] = payload.get("iteration", payload.get("iter", self.state["iteration"]))
            self.state["phase"] = payload.get("phase", kind)
            self.state["updated_at"] = time.time()
            transcript = payload.get("messages", payload.get("transcript"))
            if transcript is not None:
                # loop sends complete working history. Persist only this run's wire
                # delta so UI history can expand it without duplicating user turns.
                delta = transcript if "messages" in payload else transcript[payload.get("history_len", self.history_len):]
                self.state["transcript"] = [wire_message(m) if isinstance(m, Message) else m for m in delta]
            call = payload.get("tool_call")
            if call is not None:
                call = asdict(call) if is_dataclass(call) else dict(call)
                cid = call["id"]
                inflight = self.state["inflight"]
                if kind in ("prepared", "started") and not any(c["id"] == cid for c in inflight):
                    inflight.append({**call, "state": "uncertain"})
                if kind == "cancelled":
                    for item in inflight:
                        if item["id"] == cid:
                            item["state"] = "cancelled_uncertain"
                if kind == "finished":
                    self.state["inflight"] = [c for c in inflight if c["id"] != cid]
                    result = payload.get("result")
                    content = getattr(result, "content", "") if result is not None else ""
                    error = bool(payload.get("had_error", getattr(result, "is_error", False)))
                    self.state["completed_steps"] = [s for s in self.state["completed_steps"] if s["id"] != cid]
                    self.state["completed_steps"].append({
                        "id": cid, "tool": call["name"],
                        "args_summary": json.dumps(call.get("arguments", {}), ensure_ascii=False)[:1000],
                        "result_summary": content[:2000], "state": "error" if error else "done",
                    })
                    args = call.get("arguments", {})
                    if call["name"] in ("todo_write", "update_plan") and not error:
                        self.state["todos"] = args.get("todos", args.get("plan", []))
                    if call["name"] == "plan_write" and not error:
                        self.state["todos"] = [{"idx": i + 1, "desc": str(step)[:500], "status": "pending", "note": ""}
                                               for i, step in enumerate(args.get("steps", [])[:30])]
                    if call["name"] == "plan_update" and not error:
                        for step in self.state["todos"]:
                            if isinstance(step, dict) and step.get("idx") == args.get("idx"):
                                step.update(status=args.get("status", "pending"), note=str(args.get("note", ""))[:500])
                    if call["name"] in ("deliver_file", "file_write", "write") and not error:
                        path = args.get("path", args.get("file_path"))
                        if path and path not in self.state["artifacts"]:
                            self.state["artifacts"].append(path)
            # prepared batch includes ALL calls, including not-yet-started ones.
            if kind == "prepared":
                for c in payload.get("tool_calls", []):
                    if not any(item["id"] == c["id"] for item in self.state["inflight"]):
                        self.state["inflight"].append({**c, "state": "uncertain"})
                for m in self.state["transcript"]:
                    for c in m.get("tool_calls", []):
                        if not any(s["id"] == c["id"] for s in self.state["completed_steps"] + self.state["inflight"]):
                            self.state["inflight"].append({**c, "state": "uncertain"})
            await self.store.persist_run_checkpoint(self.session_id, self.message_id, self.state)

    async def finish(self, status: str) -> None:
        await self({"kind": status, "phase": status})
