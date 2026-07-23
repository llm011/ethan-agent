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
    auto_consent: bool = False  # 自动批准所有工具授权（仅本地回环请求生效，见 chat.py）


class ChatResponse(BaseModel):
    content: str
    model: str
    usage: dict
    session_id: str | None = None


class InjectRequest(BaseModel):
    """运行中补充信息：插入到下一轮调模型前的 working 列表末尾（prompt 结尾）。"""
    content: str
