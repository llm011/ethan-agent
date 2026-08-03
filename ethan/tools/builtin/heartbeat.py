"""heartbeat_add / heartbeat_remove / heartbeat_list 工具 —— 让 Agent 管理 heartbeat.md 任务。

Agent 通过这三个工具增删查 heartbeat 任务，不裸写文件。
格式由工具保证符合规范（编号 + 类型标记 + 指令），自动去重。
"""
from __future__ import annotations

import re
from pathlib import Path

from ethan.tools.base import BaseTool

# 匹配有效任务行：<编号> <[类型]> [指令]；# 开头和空行自动过滤。指令可空（如 [agent:work-notes]）
_TASK_RE = re.compile(r"^(\d+)\s+\[([^\]]+)\]\s*(.*)$")
# 无编号的旧格式行（向后兼容）：[类型] 指令 或 纯命令
_LEGACY_RE = re.compile(r"^\[([^\]]+)\]\s*(.*)$")


def _hb_path() -> Path:
    """返回 heartbeat.md 路径。文件不存在则返回 None。"""
    from ethan.core.config import get_config
    workspace = get_config().defaults.workspace
    p = Path(workspace) / "system" / "heartbeat.md"
    return p


def _parse_tasks(content: str) -> list[dict]:
    """解析 heartbeat.md 内容，返回任务列表。

    每个任务: {"id": int|None, "type": str, "command": str, "raw": str}
    # 开头和空行跳过。
    """
    tasks = []
    for line in content.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        m = _TASK_RE.match(stripped)
        if m:
            tasks.append({
                "id": int(m.group(1)),
                "type": m.group(2),
                "command": m.group(3).strip(),
                "raw": line,
            })
            continue
        # 旧格式兼容
        m = _LEGACY_RE.match(stripped)
        if m:
            tasks.append({
                "id": None,
                "type": m.group(1),
                "command": m.group(2).strip(),
                "raw": line,
            })
            continue
        # 纯命令（无类型标记，视为 script）
        tasks.append({
            "id": None,
            "type": "script",
            "command": stripped,
            "raw": line,
        })
    return tasks


def _next_id(tasks: list[dict]) -> int:
    """返回下一个可用编号（现有最大 +1，从 1 开始）。"""
    ids = [t["id"] for t in tasks if t["id"] is not None]
    return max(ids) + 1 if ids else 1


def _serialize(tasks: list[dict], header: str) -> str:
    """把任务列表序列化回 heartbeat.md 内容（保留 header 注释）。"""
    lines = [header]
    for t in tasks:
        tid = t["id"] if t["id"] is not None else ""
        lines.append(f"{tid}  [{t['type']}] {t['command']}".strip())
    return "\n".join(lines) + "\n"


def _read_header(content: str) -> str:
    """提取文件顶部的 # 注释行作为 header（保留规范说明）。"""
    header_lines = []
    for line in content.splitlines():
        if line.startswith("#"):
            header_lines.append(line)
        elif line.strip():
            break  # 遇到第一个非注释非空行停止
    return "\n".join(header_lines)


class HeartbeatAddTool(BaseTool):
    fast_path = False
    cacheable = False
    name = "heartbeat_add"
    description = (
        "向 heartbeat.md 追加一条心跳任务。"
        "task_type=agent 时 task 参数写 skill-name（如 work-notes），heartbeat 触发时走该技能流程；"
        "task_type=script 时 task 参数写 shell 命令。"
        "自动分配编号并去重（相同 task_type+task 已存在则不重复添加）。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "task_type": {
                "type": "string",
                "enum": ["agent", "script"],
                "description": "任务类型。agent=走技能流程，script=执行 shell 命令。",
            },
            "task": {
                "type": "string",
                "description": "agent 类型填 skill-name（如 work-notes）；script 类型填命令或脚本路径。",
            },
        },
        "required": ["task_type", "task"],
    }

    async def run(self, task_type: str, task: str) -> str:
        p = _hb_path()
        if not p.exists():
            return f"heartbeat.md 不存在：{p}"

        content = p.read_text(encoding="utf-8")
        header = _read_header(content)
        tasks = _parse_tasks(content)

        # 去重：相同 task_type+task 已存在则跳过
        type_label = task_type if task_type == "script" else f"agent:{task}"
        for t in tasks:
            existing_type = t["type"]
            if task_type == "agent":
                if existing_type == f"agent:{task}":
                    return f"已存在相同任务（id={t['id']}），未重复添加"
            else:
                if existing_type == "script" and t["command"] == task:
                    return f"已存在相同任务（id={t['id']}），未重复添加"

        new_id = _next_id(tasks)
        command = "" if task_type == "agent" else task
        new_task = {
            "id": new_id,
            "type": type_label,
            "command": command if task_type == "script" else "",
            "raw": f"{new_id}  [{type_label}] {command}".strip(),
        }
        tasks.append(new_task)
        p.write_text(_serialize(tasks, header), encoding="utf-8")
        return f"已添加 heartbeat 任务（id={new_id}）：[{type_label}] {command}".strip()


class HeartbeatRemoveTool(BaseTool):
    fast_path = False
    cacheable = False
    name = "heartbeat_remove"
    description = "按编号移除 heartbeat.md 中的一条心跳任务。用 heartbeat_list 查编号。"
    parameters = {
        "type": "object",
        "properties": {
            "task_id": {
                "type": "integer",
                "description": "要移除的任务编号（见 heartbeat_list 输出）。",
            },
        },
        "required": ["task_id"],
    }

    async def run(self, task_id: int) -> str:
        p = _hb_path()
        if not p.exists():
            return f"heartbeat.md 不存在：{p}"

        content = p.read_text(encoding="utf-8")
        header = _read_header(content)
        tasks = _parse_tasks(content)

        removed = None
        remaining = []
        for t in tasks:
            if t["id"] == task_id:
                removed = t
            else:
                remaining.append(t)
        if removed is None:
            return f"未找到编号 {task_id} 的任务。用 heartbeat_list 查看现有任务。"

        p.write_text(_serialize(remaining, header), encoding="utf-8")
        return f"已移除任务（id={task_id}）：{removed['raw'].strip()}"


class HeartbeatListTool(BaseTool):
    fast_path = False
    cacheable = False
    name = "heartbeat_list"
    description = "列出 heartbeat.md 中当前所有心跳任务及其编号。"
    parameters = {
        "type": "object",
        "properties": {},
        "required": [],
    }

    async def run(self) -> str:
        p = _hb_path()
        if not p.exists():
            return f"heartbeat.md 不存在：{p}"

        content = p.read_text(encoding="utf-8")
        tasks = _parse_tasks(content)
        if not tasks:
            return "heartbeat.md 中暂无任务。用 heartbeat_add 添加。"

        lines = [f"共 {len(tasks)} 条 heartbeat 任务：", ""]
        for t in tasks:
            tid = t["id"] if t["id"] is not None else "?"
            cmd = f" {t['command']}" if t["command"] else ""
            lines.append(f"  {tid}  [{t['type']}]{cmd}")
        return "\n".join(lines)
