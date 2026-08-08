"""DIDA（滴答清单）CLI wrapper tools — projects, tasks.

Internally calls the `dida-cli` command (https://www.npmjs.com/package/@suibiji/dida-cli)
to read/write tasks in the user's DIDi (didia365) account. The CLI must be
installed (`npm install -g @suibiji/dida-cli`) and logged in (`dida auth login`)
before these tools work.
"""
from __future__ import annotations

import asyncio
import json
import shutil

from ethan.tools.base import BaseTool

# dida 命令缺失时的友好安装/登录引导
_MISSING_BIN_HINT = (
    "滴答清单功能依赖 dida-cli，但当前环境未安装。\n"
    "安装：`npm install -g @suibiji/dida-cli`\n"
    "登录：`dida auth login`（浏览器 OAuth），或无浏览器环境用 `dida auth token <TOKEN>`"
    "（TOKEN 在网页版滴答清单「头像 → 设置 → 账户与安全 → API 口令」创建）。"
)


async def _run_dida(args: list[str], timeout: int = 30) -> str:
    """执行 dida 命令，验证 CLI 存在，返回文本输出或错误提示。"""
    if shutil.which("dida") is None:
        return f"Error: {_MISSING_BIN_HINT}"
    proc = await asyncio.create_subprocess_exec(
        "dida", *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        return f"dida 命令超时（{timeout}s）。"
    out_text = stdout.decode(errors="replace").strip()
    err_text = stderr.decode(errors="replace").strip()
    if proc.returncode != 0:
        # 未登录时 auth 相关命令会 stderr 提示
        if "未登录" in (out_text + err_text) or "login" in (out_text + err_text).lower():
            return f"dida 未登录（exit {proc.returncode}）：请先运行 `dida auth login` 授权。\n{err_text or out_text}"
        return f"dida error (exit {proc.returncode}): {err_text or out_text}"
    return out_text or "(no output)"

class DidaProjectListTool(BaseTool):
    """列出滴答清单（项目）。"""

    cacheable = False
    side_effect = False
    no_compress = False

    name = "dida_project_list"
    description = (
        "List the user's DIDi (didia365) projects/lists. Each project has an id "
        "(ObjectId) used as the --project argument when creating tasks. Returns "
        "project id, name, and kind."
    )
    parameters = {
        "type": "object",
        "properties": {
            "json_output": {
                "type": "boolean",
                "description": "Return the raw JSON from dida-cli instead of a formatted list.",
                "default": False,
            },
        },
        "required": [],
    }

    async def run(self, json_output: bool = False) -> str:
        # 始终请求 --json：dida-cli 未加 --json 时输出交互式表格，无法稳定解析。
        args = ["project", "list", "--json"]
        out = await _run_dida(args)
        if out.startswith("Error"):
            return out
        if json_output:
            return out or "没有找到清单。"
        # 默认格式化：id 和 name
        try:
            data = json.loads(out)
            if isinstance(data, list) and data:
                lines = []
                for p in data:
                    lines.append(f"- {p.get('id')}: {p.get('name', '(no name)')} (kind={p.get('kind', 'TASK')})")
                return "\n".join(lines)
        except (json.JSONDecodeError, ValueError):
            return out
        return "没有找到清单。"


class DidaTaskCreateTool(BaseTool):
    """在滴答清单创建任务。"""

    cacheable = False
    side_effect = True
    no_compress = False

    name = "dida_task_create"
    description = (
        "Create a task in the user's DIDi (didia365) list. Requires a --project id "
        "(see dida_project_list). Optionally set priority (0/1/3/5), due date "
        "(ISO 8601, e.g. 2026-08-10T09:00:00Z), tags (comma-separated), content, "
        "and reminders."
    )
    parameters = {
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "Task title (short)."},
            "project": {"type": "string", "description": "Project/list id (from dida_project_list)."},
            "content": {"type": "string", "description": "Longer task content/body."},
            "due_date": {"type": "string", "description": "Due date, ISO 8601 e.g. '2026-08-10T09:00:00Z'."},
            "start_date": {"type": "string", "description": "Start date, ISO 8601 (optional)."},
            "all_day": {"type": "boolean", "description": "Whether the task is all-day.", "default": False},
            "priority": {"type": "integer", "description": "Priority: 0=none, 1=low, 3=medium, 5=high.", "default": 0},
            "tags": {"type": "string", "description": "Comma-separated tags, e.g. '工作,紧急'."},
            "reminders": {"type": "string", "description": "Reminder triggers, comma-separated (e.g. 'TRIGGER:-PT60M')."},
            "repeat": {"type": "string", "description": "Repeat rule (RRULE format, e.g. 'RRULE:FREQ=DAILY')."},
        },
        "required": ["title", "project"],
    }

    async def run(
        self,
        title: str,
        project: str,
        content: str = "",
        due_date: str = "",
        start_date: str = "",
        all_day: bool = False,
        priority: int = 0,
        tags: str = "",
        reminders: str = "",
        repeat: str = "",
    ) -> str:
        args = ["task", "create", "--title", title, "--project", project, "--json"]
        if content:
            args += ["--content", content]
        if due_date:
            args += ["--due-date", due_date]
        if start_date:
            args += ["--start-date", start_date]
        if all_day:
            args.append("--all-day")
        if priority:
            args += ["--priority", str(priority)]
        if tags:
            args += ["--tags", tags]
        if reminders:
            args += ["--reminders", reminders]
        if repeat:
            args += ["--repeat", repeat]
        out = await _run_dida(args)
        if out.startswith("Error"):
            return out
        # 转成可读摘要
        try:
            data = json.loads(out)
            if isinstance(data, dict):
                return (
                    f"已创建任务：{data.get('title', title)}\n"
                    f"  任务 id: {data.get('id')}\n"
                    f"  清单 id: {data.get('projectId')}\n"
                    f"  截止: {data.get('dueDate', '无')}\n"
                    f"  优先级: {data.get('priority', 0)}"
                )
        except (json.JSONDecodeError, ValueError):
            pass
        return out


class DidaTaskListTool(BaseTool):
    """查询滴答清单任务（可选搜索/按清单过滤）。"""

    cacheable = False
    side_effect = False
    no_compress = False

    name = "dida_task_list"
    description = (
        "Query tasks in the user's DIDi (didia365) account. Can search by keyword, "
        "filter by project(s), tag(s), due-date window, or status (0=open, 2=completed). "
        "Returns matching tasks with id, title, project, due date, priority, status."
    )
    parameters = {
        "type": "object",
        "properties": {
            "keyword": {"type": "string", "description": "Search keyword (optional)."},
            "projects": {"type": "string", "description": "Comma-separated project ids to filter (optional)."},
            "tags": {"type": "string", "description": "Comma-separated tags to filter (optional)."},
            "status": {"type": "string", "description": "Status filter: 0=open, 2=completed (optional)."},
            "due_from": {"type": "string", "description": "Due date window start, ISO 8601 (optional)."},
            "due_to": {"type": "string", "description": "Due date window end, ISO 8601 (optional)."},
        },
        "required": [],
    }

    async def run(
        self,
        keyword: str = "",
        projects: str = "",
        tags: str = "",
        status: str = "",
        due_from: str = "",
        due_to: str = "",
    ) -> str:
        args = ["task", "search" if keyword else "filter", "--json"]
        if keyword:
            args = ["task", "search", keyword, "--json"]
            if projects:
                args += ["--projects", projects]
            if tags:
                args += ["--tags", tags]
            if status:
                args += ["--status", status]
            if due_from:
                args += ["--due-from", due_from]
            if due_to:
                args += ["--due-to", due_to]
        else:
            args = ["task", "filter", "--json"]
            if projects:
                args += ["--projects", projects]
            if tags:
                args += ["--tag", tags]
            if status:
                args += ["--status", status]
            if due_from:
                args += ["--start-date", due_from]
            if due_to:
                args += ["--end-date", due_to]
        out = await _run_dida(args)
        if out.startswith("Error"):
            return out
        try:
            data = json.loads(out)
            tasks = data if isinstance(data, list) else data.get("tasks", [])
            if not tasks:
                return "没有找到匹配的任务。"
            lines = []
            for t in tasks:
                if isinstance(t, dict):
                    lines.append(
                        f"- {t.get('id')}: {t.get('title', '(no title)')} "
                        f"[project={t.get('projectId', '?')} due={t.get('dueDate', '无')} "
                        f"priority={t.get('priority', 0)} status={t.get('status', 0)}]"
                    )
            return "\n".join(lines) or "没有找到匹配的任务。"
        except (json.JSONDecodeError, ValueError):
            return out


class DidaTaskCompleteTool(BaseTool):
    """完成滴答清单任务。"""

    cacheable = False
    side_effect = True
    no_compress = False

    name = "dida_task_complete"
    description = (
        "Mark a DIDi (didia365) task as completed. Requires the project id and task id "
        "(both from dida_task_list / dida_project_list)."
    )
    parameters = {
        "type": "object",
        "properties": {
            "project": {"type": "string", "description": "Project/list id containing the task."},
            "task_id": {"type": "string", "description": "The task id to complete."},
        },
        "required": ["project", "task_id"],
    }

    async def run(self, project: str, task_id: str) -> str:
        out = await _run_dida(["task", "complete", project, task_id])
        if out.startswith("Error"):
            return out
        return f"已完成任务 {task_id}。\n{out}" if out else f"已完成任务 {task_id}。"