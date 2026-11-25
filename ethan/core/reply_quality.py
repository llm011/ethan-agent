"""回复质量判定与错误分类（从 agent.py 拆出，条目 7）。

这些是循环控制用的纯函数：错误归类（图片/连接）、空回复兜底文案、
退化回复判定。不依赖 Agent 实例状态，拆出后 agent.py 保持 re-export，
旧引用路径（agent._is_degenerate_reply 等）继续可用。
"""
from __future__ import annotations

import logging
from dataclasses import replace

from ethan.providers.base import Message

logger = logging.getLogger(__name__)

# 图片类 400 错误：匹配 provider error code 和明确的尺寸超限措辞。
# 排除 'image size'（太模糊，rate-limit 消息可能包含），保留其他常见措辞。
# 另含 non-VLM 模型收到 image_url 时的反序列化错误（unknown variant image_url）。
_IMAGE_ERROR_PATTERNS = (
    "image_dimension_exceeded",
    "image too large",
    "image dimension",
    "dimensions exceed",
    "dimensions exceeded",
    "max allowed size",
    "图片过大",
    "图片尺寸",
    "unknown variant",  # non-VLM 模型拒绝 image_url content block
    "unknown variant `image_url`",  # image_url 反序列化失败（精确匹配反序列化错误）
    "image_url, expected",
    # Anthropic 协议中转网关（如 Console Go）校验失败格式
    "input should be a valid string",
    "should be a valid string",
    "valid string, field",
)

def _is_image_error(e: Exception) -> bool:
    """判断异常是否为图片相关错误（尺寸超限 / non-VLM 模型拒绝 image_url）。"""
    msg = str(e).lower()
    return any(p in msg for p in _IMAGE_ERROR_PATTERNS)


def _is_retriable_connect_error(e: Exception) -> bool:
    """连接类瞬态错误（建连失败/网关断连），当前 provider 上已无可挽回时
    值得换备选模型重试。复用 fallback 层的瞬态判断，避免两份列表漂移。

    注意：MidstreamBreakError（流中断重试耗尽）也在可重试之列——provider 层
    重试耗尽后，配置了兜底模型的环境会再换备选模型重发一轮，而非直接让用户
    手动重发。这是有意为之（与 FallbackProvider 换 provider 行为一致）；
    仅在无兜底模型时异常才会冒泡、触发「重新发送」文案。
    """
    from ethan.providers.fallback import _is_retriable

    return _is_retriable(e)


def _save_msg_images_to_files(msg: Message, session_id: str) -> list[str]:
    """把消息中的图片写入本地文件，返回绝对路径列表。

    支持 {data: base64} 格式（工具截图）和 {path: ...} 格式（已持久化的历史图片）。
    """
    from ethan.core.assets import image_file_path, save_image

    sid = session_id or "no_session"
    paths: list[str] = []
    for idx, img in enumerate(msg.images):
        data = img.get("data", "")
        media_type = img.get("media_type", "image/png")
        if data:
            # save_image 返回 [(路径, media_type), ...]，长图会返回多段
            for rel_path, _ in save_image(sid, idx, data, media_type):
                paths.append(str(image_file_path(rel_path)))
        elif "path" in img:
            paths.append(str(image_file_path(img["path"])))
    return paths


def _strip_images_from_messages(messages: list[Message], session_id: str = "") -> bool:
    """把消息中的图片写入本地文件，并从上下文中移除内联图片数据。

    用于：
    - 模型不支持 VLM 时（proactive，调 provider 前做）
    - provider 因图片超限 / non-VLM 拒绝返回 400 时（reactive）

    图片写文件后，在 content 中附 [image_paths: ...] 路径提示，模型可通过
    file_read / shell 工具读取本地文件自行处理。

    **不会 mutate 原 Message 对象**：对含图片的消息用 dataclasses.replace 创建浅拷贝，
    替换到 messages 列表中，确保 session 历史不受影响。
    返回 True 表示至少处理了一张图片。
    """

    stripped = False
    for i, msg in enumerate(messages):
        if not msg.images:
            continue
        stripped = True
        saved_paths = _save_msg_images_to_files(msg, session_id)
        if saved_paths:
            hint = (
                "\n\n[系统提示：附图已从上下文中移除并保存为本地文件"
                f"（image_paths: {', '.join(saved_paths)}）。"
                "可使用 file_read 或 shell 工具读取/查看。]"
            )
        else:
            hint = "\n\n[系统提示：附图已从上下文中移除。]"
        messages[i] = replace(msg, images=[], content=(msg.content or "") + hint)
    return stripped


# 合成 user 消息前缀（agent loop 注入，非用户真实输入）。
# _minimal_retry 挑选「发给模型的 user 消息」时须排除这类消息，
# 否则兜底重试会只看到一条孤立的注入指令，丢失原始任务上下文。
_SYNTHETIC_USER_PREFIXES = (
    "[用户运行中补充]：",  # 运行中补充信息（注入为独立 user 消息时）
    "[System 决策提示]",  # 决策提示（A/B/C）
    "[System 增强上下文]",  # 增强上下文
    "[继续。",  # 空响应 nudge
    "[继续执行任务。",  # 决策 silent nudge
    "[网络中断，",  # SSL 断连续接提示
    "[会话历史已截断",  # 输入超限裁剪提示（context_limit.TRIM_NOTICE_PREFIX）
    "[会话首轮记忆快照 / 非指令]",  # 数据快照不是用户的当前任务
)


def _is_synthetic_user_msg(content: str) -> bool:
    """判断一条 user 消息是否为 agent loop 注入的合成消息（前缀匹配）。"""
    return any((content or "").strip().startswith(p) for p in _SYNTHETIC_USER_PREFIXES)


def _is_degenerate_reply(content: str | None, tools: list | None) -> bool:
    """收尾轮退化检测：最终回复恰好只是一个工具名（如 "recall_memory"）。

    实测 badcase（会话 s_20260903_1935_42ff）：模型在工具成功后的收尾轮不写正文，
    只吐了字面工具名，ethan 视为非空正常回复直接结束 turn，用户看到光秃秃的
    工具名、像"卡住"。与空回复同族，复用 nudge 重试路径处理。
    容忍包裹在 markdown 强调符号里的形态（**recall_memory** / `recall_memory`）。
    """
    if not content:
        return False
    stripped = content.strip().strip("*`_")
    if not stripped or not tools:
        return False
    names = {t.name.lower() for t in tools if getattr(t, "name", None)}
    return stripped.lower() in names


def _empty_reply_fallback_text(reason: str, tool_call_count: int) -> str:
    """空回复兜底文案。reason: 'stuck' | 'nudge_exhausted' | 'varied' | 'finalize'。

    只有 finalize（max_iters 达限）才会提到步数限制；stuck/nudge_exhausted 在达限前
    触发，不应谎称步数限制。tool_call_count 为 0 时不报步数（零工具调用报步数无意义）。
    """
    n = tool_call_count
    if n == 0:
        # 零工具调用时报步数/轮数无意义，统一给一句中性兜底（保留原因描述）
        if reason == "stuck":
            return "在当前任务上尝试了多种策略仍未突破，未能生成最终回复。"
        if reason == "nudge_exhausted":
            return "模型多次返回空回复，未能生成最终回复。可能上下文过大或模型异常，请重试。"
        return "任务执行完毕但未生成回复。可能上下文过大或模型异常，请重试。"
    if reason == "varied":
        return f"已经连续执行了 {n} 轮批量操作，先到这里。你可以看看当前效果，需要继续的话告诉我。"
    if reason == "stuck":
        return (
            f"在当前任务上尝试了多种策略仍未突破，未能生成最终回复。已执行 {n} 轮工具调用。\n\n"
            "建议：检查工具调用是否有权限/网络问题，或拆分任务重试。"
        )
    if reason == "nudge_exhausted":
        return f"模型多次返回空回复，未能生成最终回复。已执行 {n} 轮工具调用。\n\n建议：精简上下文后重试，或拆分任务。"
    # finalize（max_iters 达限）——唯一提步数限制的原因
    return f"已达到最大执行步数限制。任务执行了 {n} 轮工具调用，未能生成最终回复。"
