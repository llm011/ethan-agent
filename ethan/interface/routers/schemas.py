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
    direct: bool = False  # 直调 LLM：跳过 agent loop / 工具 / 技能，纯模型流式输出
    auto_consent: bool = False  # 超级权限：自动批准普通工具授权，高危命令仍弹窗确认（仅本地/私有网段生效，见 chat.py）
    runtime_context: str = ""  # 注入 agent 的运行时上下文提示（如定时任务环境说明）
    resume_summary: str = ""  # 「继续执行」场景：先流式输出这段进度反思总结给用户看，再启动 agent 生成（纯前端展示，不进模型上下文）


class ChatResponse(BaseModel):
    content: str
    model: str
    usage: dict
    session_id: str | None = None


class InjectRequest(BaseModel):
    """运行中补充信息：插入到下一轮调模型前的 working 列表末尾（prompt 结尾）。"""
    content: str
