"""Lark CLI wrapper tools — calendar events, chat messages, message send, auth."""
from __future__ import annotations

import asyncio
import json
import logging

from ethan.tools.base import BaseTool

logger = logging.getLogger(__name__)

# 模块级存储：domain → device_code（跨工具调用传递）
# LarkAuthStartTool 写入，LarkAuthCompleteTool 读取后清除
_PENDING_DEVICE_CODES: dict[str, str] = {}


class LarkCalendarEventsTool(BaseTool):
    """Query Lark calendar events — agenda (today) or time range.

    Internally calls lark-cli calendar +agenda or calendar events instance_view.
    """

    cacheable = False
    side_effect = False
    no_compress = False  # Output is prose for model to read (agenda / event list)

    name = "lark_calendar_events"
    description = (
        "Query Lark calendar events. Use 'agenda' action for today's agenda, "
        "or 'list' action with start_time/end_time for a time range. "
        "Returns event list with title, time, location, attendees."
    )

    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["agenda", "list"],
                "description": "'agenda' for today's agenda, 'list' for time range query",
                "default": "agenda",
            },
            "start_time": {
                "type": "string",
                "description": "Start time for 'list' action (ISO 8601, e.g. '2026-07-03T00:00:00'). Ignored for 'agenda'.",
            },
            "end_time": {
                "type": "string",
                "description": "End time for 'list' action (ISO 8601, e.g. '2026-07-03T23:59:59'). Ignored for 'agenda'.",
            },
            "calendar_id": {
                "type": "string",
                "description": "Calendar ID (default: primary)",
                "default": "primary",
            },
        },
        "required": ["action"],
    }

    async def run(
        self,
        action: str = "agenda",
        start_time: str = "",
        end_time: str = "",
        calendar_id: str = "primary",
    ) -> str:
        try:
            if action == "agenda":
                # lark-cli calendar +agenda [--start ...] [--end ...] [--calendar-id ...]
                args = ["lark-cli", "calendar", "+agenda", "--as", "user"]
                if calendar_id and calendar_id != "primary":
                    args.extend(["--calendar-id", calendar_id])
                if start_time:
                    args.extend(["--start", start_time])
                if end_time:
                    args.extend(["--end", end_time])
            else:
                # lark-cli calendar events instance_view --params '{"calendar_id":"...","start_time":"...","end_time":"..."}'
                if not start_time or not end_time:
                    return "Error: 'list' action requires start_time and end_time"
                params = {
                    "calendar_id": calendar_id,
                    "start_time": start_time,
                    "end_time": end_time,
                }
                args = [
                    "lark-cli", "calendar", "events", "instance_view",
                    "--as", "user",
                    "--params", json.dumps(params),
                ]

            proc = await asyncio.create_subprocess_exec(
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=15)
            out_text = stdout.decode(errors="replace").strip()
            err_text = stderr.decode(errors="replace").strip()

            if proc.returncode != 0:
                return f"lark-cli error (exit {proc.returncode}): {err_text or out_text}"

            # Try to parse JSON and format for readability
            try:
                data = json.loads(out_text)
                if not data.get("ok") and data.get("code") not in (0, None):
                    return f"Lark API error: {data.get('msg', str(data))}"
                # Agenda: {"data": {"items": [...]}}; instance_view: similar
                events = data.get("data", {}).get("items", [])
                if not events:
                    return "No calendar events found."
                lines = []
                for ev in events:
                    title = ev.get("summary", ev.get("title", "(no title)"))
                    time_info = ev.get("start_time", "") or ev.get("time", "")
                    location = ev.get("location", "")
                    attendees = ev.get("attendees", [])
                    att_text = ", ".join(a.get("name", a.get("email", "")) for a in attendees) if attendees else ""
                    line = f"- {title}"
                    if time_info:
                        line += f" | {time_info}"
                    if location:
                        line += f" | {location}"
                    if att_text:
                        line += f" | Attendees: {att_text}"
                    lines.append(line)
                return "\n".join(lines)
            except json.JSONDecodeError:
                return out_text or "(no output)"

        except asyncio.TimeoutError:
            return "lark-cli command timed out (15s)"
        except Exception as e:
            return f"Error: {e}"


class LarkChatMessagesTool(BaseTool):
    """Query chat message history (user identity required).

    Internally calls lark-cli im +chat-messages-list --as user.
    Bot identity can only see @-mentioned messages; user identity sees all.
    """

    cacheable = False
    side_effect = False
    no_compress = False  # Output is prose for model to read

    name = "lark_chat_messages"
    description = (
        "Query chat message history. Uses user identity (--as user) to see all messages, "
        "not just @-mentions. Requires user token authorization in lark-cli config."
    )

    parameters = {
        "type": "object",
        "properties": {
            "chat_id": {
                "type": "string",
                "description": "Chat ID (oc_xxx). Required.",
            },
            "limit": {
                "type": "integer",
                "description": "Max messages to return (1-50, default 20)",
                "default": 20,
            },
            "start_time": {
                "type": "string",
                "description": "Start time filter (ISO 8601, optional)",
            },
            "end_time": {
                "type": "string",
                "description": "End time filter (ISO 8601, optional)",
            },
        },
        "required": ["chat_id"],
    }

    async def run(
        self,
        chat_id: str,
        limit: int = 20,
        start_time: str = "",
        end_time: str = "",
    ) -> str:
        try:
            args = [
                "lark-cli", "im", "+chat-messages-list",
                "--as", "user",
                "--chat-id", chat_id,
                "--page-size", str(min(max(limit, 1), 50)),
                "--format", "json",
            ]
            if start_time:
                args.extend(["--start", start_time])
            if end_time:
                args.extend(["--end", end_time])

            proc = await asyncio.create_subprocess_exec(
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=15)
            out_text = stdout.decode(errors="replace").strip()
            err_text = stderr.decode(errors="replace").strip()

            if proc.returncode != 0:
                return f"lark-cli error (exit {proc.returncode}): {err_text or out_text}"

            try:
                data = json.loads(out_text)
                if not data.get("ok") and data.get("code") not in (0, None):
                    return f"Lark API error: {data.get('msg', str(data))}"
                messages = data.get("data", {}).get("messages", [])
                if not messages:
                    return "No messages found."
                lines = []
                for msg in messages:
                    if msg.get("deleted"):
                        continue
                    sender = msg.get("sender", {}).get("name", "")
                    if not sender and msg.get("sender", {}).get("sender_type") == "app":
                        sender = "bot"
                    text = msg.get("content", "").strip()
                    time_str = msg.get("create_time", "")
                    line = f"[{time_str}] {sender}: {text}"
                    lines.append(line)
                return "\n".join(lines) or "(no messages)"
            except json.JSONDecodeError:
                return out_text or "(no output)"

        except asyncio.TimeoutError:
            return "lark-cli command timed out (15s)"
        except Exception as e:
            return f"Error: {e}"


class LarkMessageSendTool(BaseTool):
    """Send a message to a Lark chat or user.

    Internally calls lark-cli im +messages-send.
    This is for model-initiated sends (model decides content and target),
    not a replacement for send_lark_notification (SDK bot send).
    """

    cacheable = False
    side_effect = True  # Sends a message to external chat
    no_compress = True  # Returns message_id which model may need to reference

    name = "lark_message_send"
    description = (
        "Send a message to a Lark chat or user. Model decides content and target. "
        "Use --as bot (default) or --as user (requires user token). "
        "Returns message_id on success."
    )

    parameters = {
        "type": "object",
        "properties": {
            "chat_id": {
                "type": "string",
                "description": "Chat ID (oc_xxx). Use chat_id OR user_id, not both.",
            },
            "user_id": {
                "type": "string",
                "description": "User open_id (ou_xxx). Use user_id OR chat_id, not both.",
            },
            "content": {
                "type": "string",
                "description": "Message content (markdown supported). Required.",
            },
            "as_user": {
                "type": "boolean",
                "description": "Send as user identity (requires user token). Default: bot.",
                "default": False,
            },
        },
        "required": ["content"],
    }

    def consent_check(self, **kwargs) -> str | None:
        """Always ask for consent before sending a message to external chat."""
        chat_id = kwargs.get("chat_id", "")
        user_id = kwargs.get("user_id", "")
        as_user = kwargs.get("as_user", False)
        target = f"chat {chat_id}" if chat_id else f"user {user_id}" if user_id else "unknown target"
        identity = "user" if as_user else "bot"
        return f"Send Lark message as {identity} to {target}"

    async def run(
        self,
        content: str,
        chat_id: str = "",
        user_id: str = "",
        as_user: bool = False,
    ) -> str:
        if not chat_id and not user_id:
            return "Error: Must specify chat_id or user_id"
        if chat_id and user_id:
            return "Error: Specify chat_id OR user_id, not both"
        if not content:
            return "Error: content is required"

        try:
            args = [
                "lark-cli", "im", "+messages-send",
                "--as", "user" if as_user else "bot",
                "--markdown", content,
            ]
            if chat_id:
                args.extend(["--chat-id", chat_id])
            else:
                args.extend(["--user-id", user_id])

            proc = await asyncio.create_subprocess_exec(
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=15)
            out_text = stdout.decode(errors="replace").strip()
            err_text = stderr.decode(errors="replace").strip()

            if proc.returncode != 0:
                return f"lark-cli error (exit {proc.returncode}): {err_text or out_text}"

            try:
                data = json.loads(out_text)
                if not data.get("ok") and data.get("code") not in (0, None):
                    return f"Lark API error: {data.get('msg', str(data))}"
                message_id = data.get("data", {}).get("message_id", "")
                return f"Message sent. message_id: {message_id}" if message_id else "Message sent."
            except json.JSONDecodeError:
                return out_text or "Message sent (no JSON response)"

        except asyncio.TimeoutError:
            return "lark-cli command timed out (15s)"
        except Exception as e:
            return f"Error: {e}"


class LarkAuthStartTool(BaseTool):
    """Start Lark OAuth device flow — returns auth URL for user to visit.

    Runs `lark-cli auth login --domain {domain} --no-wait --json` to get
    device_code + auth URL. The device_code is stored internally for
    LarkAuthCompleteTool to pick up after the user finishes authorization.

    Typical flow:
      1. LLM calls lark_auth_start → gets auth URL
      2. LLM calls wait_for_user with the URL → user visits link, authorizes
      3. User clicks "done" → LLM calls lark_auth_complete → OAuth finished
    """

    cacheable = False
    side_effect = True
    no_compress = False

    name = "lark_auth_start"
    description = (
        "启动飞书 OAuth 设备码授权流程，返回授权链接。"
        "调用后会运行 lark-cli auth login --no-wait，拿到设备码和授权链接。"
        "接下来应该用 wait_for_user 工具把链接展示给用户，等用户完成授权后，"
        "再调用 lark_auth_complete 完成授权。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "domain": {
                "type": "string",
                "description": "授权的域（如 calendar、im、drive、sheets 等）",
            },
        },
        "required": ["domain"],
    }

    async def run(self, domain: str = "") -> str:
        if not domain:
            return "Error: domain is required (e.g. calendar, im, drive)"

        try:
            args = [
                "lark-cli", "auth", "login",
                "--domain", domain,
                "--no-wait",
                "--json",
            ]
            proc = await asyncio.create_subprocess_exec(
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=15)
            out_text = stdout.decode(errors="replace").strip()
            err_text = stderr.decode(errors="replace").strip()

            if proc.returncode != 0:
                return f"lark-cli error (exit {proc.returncode}): {err_text or out_text}"

            # 解析 JSON，提取 device_code 和 url
            try:
                data = json.loads(out_text)
            except json.JSONDecodeError:
                return f"Unexpected output (non-JSON): {out_text or err_text}"

            # 尝试多种可能的字段名
            device_code = (
                data.get("device_code")
                or data.get("deviceCode")
                or data.get("data", {}).get("device_code")
                or data.get("data", {}).get("deviceCode")
                or ""
            )
            url = (
                data.get("url")
                or data.get("auth_url")
                or data.get("verification_url")
                or data.get("data", {}).get("url")
                or data.get("data", {}).get("auth_url")
                or data.get("data", {}).get("verification_url")
                or ""
            )

            if not device_code:
                if data.get("ok") or data.get("code") in (0, None):
                    return f"Already authorized for domain '{domain}', or no device_code in response: {out_text}"
                return f"Failed to get device_code: {data.get('msg', str(data))}"

            # 存储 device_code 供 lark_auth_complete 使用
            _PENDING_DEVICE_CODES[domain] = device_code

            return (
                f"OAuth flow started for domain '{domain}'.\n"
                f"Auth URL: {url}\n"
                f"Device code stored. Next: use wait_for_user to show the URL to user, "
                f"then call lark_auth_complete with domain='{domain}' after user confirms."
            )

        except asyncio.TimeoutError:
            return "lark-cli auth login timed out (15s)"
        except Exception as e:
            return f"Error: {e}"


class LarkAuthCompleteTool(BaseTool):
    """Complete Lark OAuth device flow — poll for authorization result.

    Runs `lark-cli auth login --device-code {code}` to complete the OAuth flow.
    The device_code is retrieved from the internal store populated by
    LarkAuthStartTool.
    """

    cacheable = False
    side_effect = True
    no_compress = False

    name = "lark_auth_complete"
    description = (
        "完成飞书 OAuth 授权。从 lark_auth_start 保存的设备码继续，"
        "运行 lark-cli auth login --device-code 完成授权。"
        "应在用户通过 wait_for_user 确认已完成授权后调用。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "domain": {
                "type": "string",
                "description": "授权的域（必须与 lark_auth_start 使用的 domain 一致）",
            },
        },
        "required": ["domain"],
    }

    async def run(self, domain: str = "") -> str:
        if not domain:
            return "Error: domain is required"

        device_code = _PENDING_DEVICE_CODES.pop(domain, None)
        if not device_code:
            return (
                f"Error: No pending device_code for domain '{domain}'. "
                f"Make sure lark_auth_start was called first with the same domain."
            )

        try:
            args = [
                "lark-cli", "auth", "login",
                "--device-code", device_code,
            ]
            proc = await asyncio.create_subprocess_exec(
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            # 授权完成可能需要轮询等待，给更长超时
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)
            out_text = stdout.decode(errors="replace").strip()
            err_text = stderr.decode(errors="replace").strip()

            if proc.returncode != 0:
                # 把 device_code 放回去，允许重试
                _PENDING_DEVICE_CODES[domain] = device_code
                return f"lark-cli error (exit {proc.returncode}): {err_text or out_text}"

            # 解析结果
            try:
                data = json.loads(out_text)
                if data.get("ok") or data.get("code") in (0, None):
                    return f"Authorization completed successfully for domain '{domain}'."
                return f"Authorization may have failed: {data.get('msg', str(data))}"
            except json.JSONDecodeError:
                return f"Authorization completed for domain '{domain}'. Output: {out_text or err_text}"

        except asyncio.TimeoutError:
            # 超时可能是用户还没完成授权，把 device_code 放回去允许重试
            _PENDING_DEVICE_CODES[domain] = device_code
            return (
                "lark-cli auth login timed out (30s). "
                "User may not have completed authorization yet. "
                "Please ask the user to complete authorization and retry."
            )
        except Exception as e:
            _PENDING_DEVICE_CODES[domain] = device_code
            return f"Error: {e}"
