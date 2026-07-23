"""Small pure helpers used across the chat router."""
from __future__ import annotations

import json
from typing import AsyncGenerator

from ethan.providers.base import Message


async def _setup_error_stream(message: str, session_id: str) -> AsyncGenerator[str, None]:
    """请求建立阶段就失败时，构造一个只含 error + done 的最小 SSE 流。

    让 stream 模式下的建立期错误走与生成期错误一致的前端渲染路径（error 气泡），
    而不是抛 500 让前端显示生硬的 "Chat failed: 500"。
    """
    yield f"data: {json.dumps({'error': message, 'session_id': session_id}, ensure_ascii=False)}\n\n"
    yield f"data: {json.dumps({'done': True, 'usage': {}}, ensure_ascii=False)}\n\n"


def _friendly_error(e: Exception, agent) -> str:
    """把 provider 鉴权 / 配置类错误转成给用户的友好提示，建议切换 model。"""
    msg = str(e)
    lower = msg.lower()
    # 鉴权缺失：空 api_key / 没配 token
    if "could not resolve authentication method" in lower or "未配置" in msg or "api_key" in lower and "not" in lower:
        model = getattr(agent, "_provider", None)
        model_id = getattr(model, "model", "") if model else ""
        return (
            f"当前模型 {model_id} 的 provider 未配置 api_key 或鉴权失败。"
            "请在设置页切换到已配置的模型，或在 ~/.ethan/config.yaml 的 providers 段补上对应 api_key。"
        )
    # Gemini 地区限制（大陆 IP 直接请求 Google API）
    if "user location is not supported" in lower or "failed_precondition" in lower:
        model = getattr(agent, "_provider", None)
        model_id = getattr(model, "model", "") if model else ""
        return (
            f"当前模型 {model_id} 的 API 不支持当前所在地区（Error 400 FAILED_PRECONDITION）。"
            "请在设置页切换到其他模型（如 Claude / OpenAI），或为服务端配置代理后重试。"
        )
    # 网络层 fetch failed（多见于第三方中转服务挂了）
    if "fetch failed" in lower or "connection" in lower or "timeout" in lower:
        return f"请求上游服务失败（可能中转服务不可达）：{msg[:120]}。建议在设置页切换 model 重试。"
    # 流式输出中途断连（上游/中转在生成过程中关闭了连接）
    if any(k in lower for k in ("unexpected eof", "peer closed", "incomplete chunked",
                                "remoteprotocolerror", "connection reset",
                                "stream ended", "incompleteread", "chunkedencodingerror")):
        return "上游连接在生成中途断开（多见于中转服务不稳）。以上内容已保存，可直接发「继续」补全，或在设置页切换 model 重试。"
    return msg[:300]


def _status_for_setup_error(e: Exception) -> int:
    """请求建立期异常 → HTTP 状态码。客户端可修正的错误映射为 4xx，其余 500。

    - 请求体结构非法（缺字段 / 类型不对）→ 422 Unprocessable Entity
    - 参数值非法 / provider 未配置或鉴权缺失（用户侧可修）→ 400 Bad Request
    - 其余（DB 初始化失败等服务端问题）→ 500 Internal Server Error

    保守起见只对明确的客户端类错误降级为 4xx，无法归类的一律 500，避免把真正的
    服务端故障误报成 client 错误。
    """
    # 请求体语义错误：解析 messages 时字段缺失 / 类型不对
    if isinstance(e, (KeyError, TypeError)):
        return 422
    if isinstance(e, ValueError):
        return 400
    # provider 未配置 / 鉴权缺失：用户侧配置问题，client 无需当作服务故障重试
    msg = str(e)
    lower = msg.lower()
    if ("could not resolve authentication method" in lower
            or "未配置" in msg
            or ("api_key" in lower and "not" in lower)):
        return 400
    return 500


def _with_quote(user_msg: Message, quote: dict | None) -> Message:
    """返回一份带「引用块」前缀的用户消息副本（仅发给模型，不入库）。

    quote 形如 {"role": "user"|"assistant", "content": "..."}。
    """
    if not quote or not quote.get("content"):
        return user_msg
    role_label = "用户" if quote.get("role") == "user" else "Ethan"
    quote_text = str(quote["content"]).replace("\n", "\n> ")
    prefixed = f"> [引用 {role_label} 的消息]:\n> {quote_text}\n\n{user_msg.content}"
    return Message(role=user_msg.role, content=prefixed, created_at=user_msg.created_at, images=user_msg.images)


def _persist_images_to_disk(msg: Message, session_id: str) -> list[str]:
    """将消息中的 base64 图片保存为本地文件，msg.images 就地替换为路径格式。

    原始格式: [{"data": "base64...", "media_type": "image/png"}]
    替换为:   [{"path": "session_id/ts_0.png", "media_type": "image/png"}]

    返回保存的文件绝对路径列表（供调用方给 LLM 提供路径提示）。
    """
    from ethan.core.assets import image_file_path, save_image

    persisted = []
    saved_paths: list[str] = []
    for idx, img in enumerate(msg.images):
        data = img.get("data", "")
        media_type = img.get("media_type", "image/png")
        if not data:
            persisted.append(img)
            continue
        path = save_image(session_id, idx, data, media_type)
        persisted.append({"path": path, "media_type": media_type})
        saved_paths.append(str(image_file_path(path)))

    msg.images = persisted
    return saved_paths


def _resolve_images_for_llm(messages: list[Message]) -> None:
    """将消息中 {path, media_type} 格式的图片解析为 {data, media_type}（LLM 需要 base64）。

    DB 存储的历史消息只保留路径引用，发送给 LLM 前需读回文件内容还原为 base64。
    已含 data 字段的（当前消息原始格式）直接保留不做处理。

    同时在消息末尾附加图片本地路径提示，让 agent 的工具模式能直接定位文件。
    """
    from ethan.core.assets import image_file_path, load_image_b64

    for msg in messages:
        if not msg.images:
            continue
        resolved = []
        file_paths: list[str] = []
        for img in msg.images:
            if "data" in img:
                resolved.append(img)
            elif "path" in img:
                b64 = load_image_b64(img["path"])
                if b64:
                    resolved.append({"data": b64, "media_type": img.get("media_type", "image/png")})
                    file_paths.append(str(image_file_path(img["path"])))
                # 文件不存在则跳过（不影响 LLM 调用）
            else:
                resolved.append(img)
        msg.images = resolved
        # 附加路径提示：让 agent 工具模式知道图片在本地文件系统的位置
        if file_paths and msg.role == "user" and msg.content:
            paths_hint = ", ".join(file_paths)
            msg.content = f"{msg.content}\n\n[image_paths: {paths_hint}]"
