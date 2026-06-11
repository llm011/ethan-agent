"""FastAPI HTTP 接口 — 提供 REST API 和 SSE 流式输出。"""
import asyncio
import json
from typing import AsyncGenerator

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from ethan import __version__
from ethan.core.agent import Agent
from ethan.core.config import get_config
from ethan.providers.base import Message
from ethan.skills.registry import SkillRegistry
from ethan.tools.builtin.file import FileListTool, FileReadTool, FileWriteTool
from ethan.tools.builtin.shell import ShellTool
from ethan.tools.builtin.web import WebFetchTool
from ethan.tools.builtin.web_search import WebSearchTool
from ethan.tools.registry import ToolRegistry

app = FastAPI(title="Ethan Agent API", version=__version__)


def _create_agent(model: str | None = None) -> Agent:
    registry = ToolRegistry()
    registry.register(ShellTool())
    registry.register(WebSearchTool())
    registry.register(WebFetchTool())
    registry.register(FileReadTool())
    registry.register(FileWriteTool())
    registry.register(FileListTool())

    skills = SkillRegistry()
    skills.load()

    return Agent(tool_registry=registry, skill_registry=skills, model=model)


class ChatRequest(BaseModel):
    messages: list[dict]  # [{"role": "user", "content": "..."}]
    model: str | None = None
    stream: bool = False


class ChatResponse(BaseModel):
    content: str
    model: str
    usage: dict | None = None


@app.get("/health")
async def health():
    return {"status": "ok", "version": __version__}


@app.get("/models")
async def list_models():
    config = get_config()
    return {"models": [m.model_dump() for m in config.models]}


@app.post("/chat")
async def chat(req: ChatRequest):
    agent = _create_agent(req.model)
    messages = [Message(role=m["role"], content=m["content"]) for m in req.messages]

    if req.stream:
        return StreamingResponse(
            _stream_response(agent, messages),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    response = await agent.chat(messages)
    return ChatResponse(
        content=response.content,
        model=agent._provider.model,
        usage={"input": agent.usage.input_tokens, "output": agent.usage.output_tokens, "cache": agent.usage.cache_tokens},
    )


async def _stream_response(agent: Agent, messages: list[Message]) -> AsyncGenerator[str, None]:
    """SSE 格式流式输出。"""
    try:
        async for chunk in agent.stream_chat(messages):
            data = json.dumps({"content": chunk}, ensure_ascii=False)
            yield f"data: {data}\n\n"
    except Exception as e:
        yield f"data: {json.dumps({'error': str(e)})}\n\n"

    # 发送结束信号
    done_data = json.dumps({
        "done": True,
        "model": agent._provider.model,
        "usage": {"input": agent.usage.input_tokens, "output": agent.usage.output_tokens, "cache": agent.usage.cache_tokens},
    }, ensure_ascii=False)
    yield f"data: {done_data}\n\n"


def run_server(host: str = "0.0.0.0", port: int = 8900):
    """启动 API 服务。"""
    import uvicorn
    uvicorn.run(app, host=host, port=port)
