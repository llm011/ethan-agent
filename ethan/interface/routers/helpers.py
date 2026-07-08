"""Small pure helpers used across the chat router."""
from __future__ import annotations

from ethan.providers.base import Message


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


def _with_quote(user_msg: Message, quote: dict | None) -> Message:
    """返回一份带「引用块」前缀的用户消息副本（仅发给模型，不入库）。

    quote 形如 {"role": "user"|"assistant", "content": "..."}。
    """
    if not quote or not quote.get("content"):
        return user_msg
    role_label = "用户" if quote.get("role") == "user" else "Ethan"
    quote_text = str(quote["content"]).replace("\n", "\n> ")
    prefixed = f"> [引用 {role_label} 的消息]:\n> {quote_text}\n\n{user_msg.content}"
    return Message(role=user_msg.role, content=prefixed, created_at=user_msg.created_at)
