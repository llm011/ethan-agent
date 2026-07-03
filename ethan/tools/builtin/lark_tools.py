"""Lark CLI wrapper tools — calendar events, chat messages, message send."""
from __future__ import annotations

import asyncio
import json
from typing import Any

from ethan.tools.base import BaseTool


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
