"""Plan 工具 — 让 agent 把多步任务的计划落盘到外部记忆。

跑 1-2 步后，如果任务还有多步要做的样子，agent 应该先 plan_write 列出步骤，
再逐步执行。plan 存在 ~/.ethan/plans/<session_id>.json，避免被 context_budget
截断，也方便后续在 UI 时间轴可视化。

三个工具：
  - plan_write(steps)  新建/覆盖 plan，steps 是字符串列表
  - plan_read()         读回当前 plan（含每步状态）
  - plan_update(idx, status, note)  更新某步状态

设计原则：极简，不阻塞主循环。plan 是"外部记忆"而非"硬 gate"——
agent 可以选择不 plan，只是失去了"先规划"的好处。
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from ethan.tools.base import BaseTool

# Plan 文件存放目录
_PLANS_DIR = Path.home() / ".ethan" / "plans"

# 单个 plan 最大步数，防止模型产出几百步的"伪 plan"
_MAX_STEPS = 30
# 单步描述最大长度
_MAX_STEP_LEN = 500


def _plans_dir() -> Path:
    """获取 plan 存储目录，确保存在。"""
    _PLANS_DIR.mkdir(parents=True, exist_ok=True)
    return _PLANS_DIR


def _session_plan_path(session_id: str) -> Path:
    """获取某会话的 plan 文件路径。

    session_id 由调用方传入；若为空则用一个 fallback 路径（兼容无 session 上下文的场景）。
    """
    safe_id = "".join(c if c.isalnum() or c in "-_" else "_" for c in (session_id or "default"))
    return _plans_dir() / f"{safe_id}.json"


def _load_plan(path: Path) -> dict:
    """加载 plan，不存在返回空结构。"""
    if not path.exists():
        return {"steps": [], "created": None, "updated": None}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"steps": [], "created": None, "updated": None}


def _save_plan(path: Path, plan: dict) -> None:
    plan["updated"] = time.strftime("%Y-%m-%d %H:%M:%S")
    path.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")


class PlanWriteTool(BaseTool):
    fast_path = True  # 常驻 fast 档：plan 是高频规划能力
    name = "plan_write"
    description = (
        "列出多步任务的执行计划，落盘为外部记忆。"
        "当你判断任务还有多步要做时（多个文件/多个分支/同类操作重复），"
        "先调本工具列步骤，再逐步执行，避免边想边做走重复路径。"
        "步骤是字符串列表，每步简明描述要做什么（含目标工具名）。"
        "调用后 plan 会落盘，后续轮次可 plan_read 读回，每步做完调 plan_update 标记。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "steps": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "执行步骤列表，按顺序。每步简明描述，含目标工具名，例如："
                    "'1. fetch 主 Wiki 拿原文（lark-cli docs）'、"
                    "'2. 解析引文 ID + 子文档链接（python）'、"
                    "'3. 批量 fetch 子文档（for 循环）'。"
                    "建议 3-10 步，超过 30 步会被截断。"
                ),
            },
            "session_id": {
                "type": "string",
                "description": "当前会话 ID，用于隔离不同会话的 plan。留空则用 default。",
                "default": "",
            },
        },
        "required": ["steps"],
    }

    def __init__(self, user_id: str = ""):
        self._user_id = user_id

    async def run(self, steps: list[str], session_id: str = "") -> str:
        if not isinstance(steps, list) or not steps:
            return "plan_write 失败：steps 必须是非空字符串列表"
        # 截断保护
        steps = [str(s)[:_MAX_STEP_LEN] for s in steps[:_MAX_STEPS]]
        path = _session_plan_path(session_id)
        plan = {
            "steps": [
                {"idx": i + 1, "desc": desc, "status": "pending", "note": ""}
                for i, desc in enumerate(steps)
            ],
            "created": time.strftime("%Y-%m-%d %H:%M:%S"),
            "updated": None,
        }
        _save_plan(path, plan)
        summary = "\n".join(f"  {i+1}. {desc}" for i, desc in enumerate(steps))
        return (
            f"✅ Plan 已落盘（{len(steps)} 步）：\n{summary}\n\n"
            f"接下来按步骤执行，每步做完调 plan_update(idx, status='done') 标记进度。"
            f"剩余步数多时，可在中途 plan_read 读回确认进度。"
        )


class PlanReadTool(BaseTool):
    fast_path = True
    name = "plan_read"
    description = (
        "读回当前会话的执行计划。plan_write 落盘后，后续轮次可用本工具读回进度。"
        "返回每步的 idx / desc / status / note，status 含 pending/done/skipped/failed。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "session_id": {
                "type": "string",
                "description": "当前会话 ID。留空则用 default。",
                "default": "",
            },
        },
        "required": [],
    }

    def __init__(self, user_id: str = ""):
        self._user_id = user_id

    async def run(self, session_id: str = "") -> str:
        path = _session_plan_path(session_id)
        plan = _load_plan(path)
        if not plan["steps"]:
            return "当前会话还没有 plan。如需规划，调 plan_write(steps=[...])。"
        lines = [f"📋 Plan（创建于 {plan.get('created') or '未知'}，更新于 {plan.get('updated') or '未更新'}）："]
        for step in plan["steps"]:
            mark = {"done": "✓", "pending": "○", "skipped": "↷", "failed": "✗"}.get(
                step.get("status", "pending"), "?"
            )
            note = f" — {step['note']}" if step.get("note") else ""
            lines.append(f"  {mark} {step['idx']}. {step['desc']}{note}")
        total = len(plan["steps"])
        done = sum(1 for s in plan["steps"] if s.get("status") == "done")
        lines.append(f"\n进度：{done}/{total}")
        return "\n".join(lines)


class PlanUpdateTool(BaseTool):
    fast_path = True
    name = "plan_update"
    description = (
        "更新某步执行状态。每步做完调本工具标记，便于后续追踪进度。"
        "status: done=完成 / skipped=跳过 / failed=失败 / pending=重置为未做。"
        "可选传 note 记录该步的产出或失败原因。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "idx": {
                "type": "integer",
                "description": "要更新的步骤编号（从 1 开始）",
            },
            "status": {
                "type": "string",
                "enum": ["done", "skipped", "failed", "pending"],
                "description": "新状态",
            },
            "note": {
                "type": "string",
                "description": "可选，该步的产出摘要或失败原因",
                "default": "",
            },
            "session_id": {
                "type": "string",
                "description": "当前会话 ID。留空则用 default。",
                "default": "",
            },
        },
        "required": ["idx", "status"],
    }

    def __init__(self, user_id: str = ""):
        self._user_id = user_id

    async def run(self, idx: int, status: str, note: str = "", session_id: str = "") -> str:
        if status not in ("done", "skipped", "failed", "pending"):
            return f"plan_update 失败：status 必须是 done/skipped/failed/pending，收到 {status}"
        path = _session_plan_path(session_id)
        plan = _load_plan(path)
        if not plan["steps"]:
            return "plan_update 失败：当前会话还没有 plan，请先 plan_write"
        if idx < 1 or idx > len(plan["steps"]):
            return f"plan_update 失败：idx 越界（1-{len(plan['steps'])}），收到 {idx}"
        step = plan["steps"][idx - 1]
        step["status"] = status
        if note:
            step["note"] = note[:200]
        _save_plan(path, plan)
        mark = {"done": "✓", "pending": "○", "skipped": "↷", "failed": "✗"}.get(status, "?")
        return f"已更新步骤 {idx} → {mark} {status}" + (f"（{note[:80]}）" if note else "")
