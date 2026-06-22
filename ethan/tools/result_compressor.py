"""工具结果压缩器——超长输出先用廉价模型提炼，再喂给主模型。"""
import logging

from ethan.core.config import get_config
from ethan.memory.consolidator import get_lite_model
from ethan.providers.base import Message
from ethan.providers.manager import create_provider

logger = logging.getLogger(__name__)

MAX_RAW_LENGTH = 4000
COMPRESS_TARGET = 1200


async def maybe_compress(tool_name: str, result: str, context: str = "") -> str:
    """如果结果超长，用廉价模型压缩。否则原样返回。"""
    if len(result) <= MAX_RAW_LENGTH:
        return result

    cfg = get_config()
    cheap_model = get_lite_model(cfg.defaults.model)

    prompt = (
        f"以下是工具 `{tool_name}` 的执行结果：\n\n"
        f"<tool_output>\n{result[:8000]}\n</tool_output>\n\n"
        + (f"调用背景：{context}\n\n" if context else "")
        + f"请将以上内容提炼为不超过 {COMPRESS_TARGET} 字的摘要，"
        "保留所有关键信息、数据、错误信息。只输出摘要，不要解释。"
    )
    try:
        provider = create_provider(cheap_model)
        resp = await provider.chat(
            [Message(role="user", content=prompt)],
            system="你是一个工具输出摘要助手，负责提炼关键信息。",
        )
        compressed = resp.content.strip()
        logger.debug("[Compressor] %s: %d → %d chars", tool_name, len(result), len(compressed))
        return f"[摘要，原始输出 {len(result)} 字]\n{compressed}"
    except Exception as e:
        logger.warning("[Compressor] Failed for %s: %s", tool_name, e)
        return result[:MAX_RAW_LENGTH] + "\n...(truncated)"
