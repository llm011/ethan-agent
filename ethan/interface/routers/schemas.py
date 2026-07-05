"""ChatRequest / ChatResponse Pydantic schemas for the chat router."""
from __future__ import annotations

from pydantic import BaseModel


class ChatRequest(BaseModel):
    messages: list[dict]
    model: str | None = None
    stream: bool = False
    session_id: str | None = None
    channel: str = "web"
    quote: dict | None = None  # {role, content}：引用某条历史消息，注入给模型但不入库
    mode: str = ""  # "" = 工作助手; 规范英文 key，如 "legal"/"companion"（见 core/modes.py）
    btw: bool = False  # /btw 顺带一问：不带历史，单轮轻量查询


class ChatResponse(BaseModel):
    content: str
    model: str
    usage: dict
