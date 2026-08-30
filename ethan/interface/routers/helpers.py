"""Small pure helpers used across the chat router."""
from __future__ import annotations

import asyncio
import json
import logging
from typing import AsyncGenerator

from ethan.providers.base import MIDSTREAM_BREAK_KEYWORDS, Message, MidstreamBreakError

logger = logging.getLogger(__name__)


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
    # 中途断连且 provider 层自动重试已耗尽（全程未产出任何内容）→ 如实提示重试
    # 失败。此时说"已生成内容已保存"是不实文案，用户发「继续」也接不上任何内容。
    if isinstance(e, MidstreamBreakError):
        return "上游连接中断且自动重试失败，本次未产出任何内容。可直接重新发送，或在设置页切换 model 重试。"
    # 流式输出中途断连（上游/中转在生成过程中关闭了连接，含 TLS 记录层中断）。
    # 必须放在通用 connection 判断之前：这类错误消息里通常也含 "connection"
    # （如 "peer closed connection without sending complete message body"），
    # 先走通用分支会被误判成"中转不可达"，误导用户去切换模型而非发「继续」补全。
    # 关键词与 openai_compat 的 salvage/重试判断共用 MIDSTREAM_BREAK_KEYWORDS，
    # 防止两份列表漂移（历史 bug：broken pipe 只加了一侧）。
    if any(k in lower for k in MIDSTREAM_BREAK_KEYWORDS):
        return "上游连接在生成中途断开（多见于中转服务不稳或网络抖动）。已生成内容已保存，可直接发「继续」补全，或在设置页切换 model 重试。"
    # 网络层 fetch failed（多见于第三方中转服务挂了）——建立连接就失败，无任何内容产出
    if "fetch failed" in lower or "connection" in lower or "timeout" in lower:
        return f"请求上游服务失败（可能中转服务不可达）：{msg[:120]}。建议在设置页切换 model 重试。"
    # SQLite database locked — 瞬态并发冲突，任务本身已完成，不应暴露给用户
    if "database is locked" in lower:
        return ""
    return msg[:300]


def _is_db_locked(e: Exception) -> bool:
    return "database is locked" in str(e).lower()


async def _retry_on_locked(coro_fn, *args, retries: int = 3, delay: float = 0.5):
    """对 DB locked 错误静默重试，超时后仅记日志不抛给用户。"""
    for attempt in range(retries):
        try:
            return await coro_fn(*args)
        except Exception as e:
            if not _is_db_locked(e) or attempt == retries - 1:
                if _is_db_locked(e):
                    logger.warning("DB locked after %d retries, giving up: %s", retries, coro_fn.__name__)
                    return None
                raise
            await asyncio.sleep(delay * (attempt + 1))


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


def _find_quoted_message(history: list[Message], quote: dict) -> Message | None:
    """按 quote.message_id 精确找被引用的历史消息；无 message_id 时按 content 模糊兜底。"""
    mid = quote.get("message_id")
    if mid is not None:
        for m in history:
            if m.id == mid:
                return m
    qcontent = str(quote.get("content") or "").strip()
    if not qcontent:
        return None
    # 内容兜底：优先精确匹配，其次包含匹配
    for m in history:
        if (m.content or "").strip() == qcontent:
            return m
    for m in history:
        if qcontent and qcontent in (m.content or ""):
            return m
    return None


def _extract_file_paths(*texts: str) -> list[str]:
    """从工具参数/结果文本里粗提取常见文件路径（/tmp/ 等绝对路径），去重保序。"""
    import re

    seen: list[str] = []
    pat = re.compile(r"(?:/tmp|/var|/private|~|\.)/[^\s\"'`，,；;]+")
    for t in texts:
        if not t:
            continue
        for m in pat.finditer(t):
            p = m.group(0).rstrip("/,.;'\"")
            if p not in seen:
                seen.append(p)
    return seen


def _enrich_quote_for_minimal(history: list[Message], quote: dict, current_user: Message) -> Message:
    """精简模式专用：把引用消息拼到当前消息上，并附上该消息的 tool 调用列表与产出文件路径。

    与 _with_quote 的区别：
      - 引用消息不仅带正文，若它是 assistant 消息且执行过工具，则追加：
          * tool 调用列表（工具名 + 参数摘要）
          * 相关文件路径 + 简短描述（不读文件内容）
      - 找不到被引用消息时退回 _with_quote 的纯正文行为。
    """
    if not quote or not quote.get("content"):
        return current_user
    role_label = "用户" if quote.get("role") == "user" else "Ethan"
    quote_text = str(quote["content"]).replace("\n", "\n> ")
    parts = [f"> [引用 {role_label} 的消息]:\n> {quote_text}"]

    ref = _find_quoted_message(history, quote)
    if ref is not None:
        extras: list[str] = []
        # 1) tool 调用列表
        if ref.tool_calls:
            call_lines = [
                f"  - {tc.name}({_short_args(tc.arguments)})" for tc in ref.tool_calls[:20]
            ]
            extras.append("该消息执行过的工具调用：\n" + "\n".join(call_lines))
        # 2) 相关文件路径 + 简短描述（从 tool_steps 的 args / result 里粗提）
        file_lines: list[str] = []
        step_files: list[str] = []
        if ref.tool_steps:
            for step in ref.tool_steps:
                sargs = str(step.get("args") or "")
                sres = str(step.get("result_preview") or "") + " " + str(step.get("result_detail") or "")
                step_files.extend(_extract_file_paths(sargs, sres))
        args_blob = " ".join(_short_args(tc.arguments) for tc in (ref.tool_calls or []) if tc.arguments)
        step_files.extend(_extract_file_paths(args_blob))
        seen_files: list[str] = []
        for p in step_files:
            if p not in seen_files:
                seen_files.append(p)
        for p in seen_files[:20]:
            file_lines.append(f"  - {p}")
        if file_lines:
            extras.append(
                "该消息涉及的产出文件路径（可自行读取，勿把内容贴回）：\n" + "\n".join(file_lines)
            )
        if extras:
            parts.append("[引用消息的附加上下文]\n" + "\n".join(extras))

    parts.append(current_user.content or "")
    return Message(
        role=current_user.role,
        content="\n\n".join(parts),
        created_at=current_user.created_at,
        images=current_user.images,
    )


def _short_args(arguments: dict, limit: int = 120) -> str:
    """把工具参数压缩成单行摘要（去 intent，截断）。"""
    if not arguments:
        return ""
    d = dict(arguments)
    d.pop("intent", None)
    s = json.dumps(d, ensure_ascii=False, sort_keys=True, default=str)
    return s[:limit] + ("…" if len(s) > limit else "")


def _persist_images_to_disk(msg: Message, session_id: str) -> tuple[list[str], list[str]]:
    """将消息中的 base64 图片保存为本地文件，msg.images 就地替换为路径格式。

    原始格式: [{"data": "base64...", "media_type": "image/png"}]
    替换为:   [{"path": "session_id/ts_0.png", "media_type": "image/png"}]

    长图（高度 > 8000px）会被自动垂直切分为多段，每段独立保存为一个文件。
    切分后 msg.images 会展开为多条 path 记录，同源分段共享 split_group 字段
    （值为原始图片索引），供 _resolve_images_for_llm 识别并给 LLM 加顺序提示。

    返回 (保存的文件绝对路径列表, 切分提示列表)。
    切分提示如 "图片1因过长切分为3段（按顺序展示）"，无切分时为空列表。
    """
    from ethan.core.assets import image_file_path, save_image

    persisted = []
    saved_paths: list[str] = []
    split_hints: list[str] = []
    for idx, img in enumerate(msg.images):
        data = img.get("data", "")
        media_type = img.get("media_type", "image/png")
        if not data:
            persisted.append(img)
            continue
        # save_image 返回 [(路径, media_type), ...]，长图会返回多段
        segments = save_image(session_id, idx, data, media_type)
        if len(segments) > 1:
            split_hints.append(f"图片{idx + 1}因过长切分为{len(segments)}段（按顺序展示）")
        for seg_path, seg_media_type in segments:
            entry: dict = {"path": seg_path, "media_type": seg_media_type}
            if len(segments) > 1:
                entry["split_group"] = idx
            persisted.append(entry)
            saved_paths.append(str(image_file_path(seg_path)))

    msg.images = persisted
    return saved_paths, split_hints


def _resolve_images_for_llm(messages: list[Message]) -> None:
    """将消息中 {path, media_type} 格式的图片解析为 {data, media_type}（LLM 需要 base64）。

    DB 存储的历史消息只保留路径引用，发送给 LLM 前需读回文件内容还原为 base64。
    已含 data 字段的（当前消息原始格式）直接保留不做处理。

    同时在消息末尾附加图片本地路径提示，让 agent 的工具模式能直接定位文件。
    当前消息的 base64 图片（data 字段）可能超限，需缩放；
    历史消息的 path 图片落盘时已缩放（save_image），但兼容旧数据仍调用 downscale 做安全网
    （对已缩放的图片 Pillow 只检查尺寸即返回，开销极低）。

    若消息中含 split_group 标记（长图切分的多段），附加顺序提示让 LLM 理解分段关系。
    """
    from ethan.core.assets import downscale_image_b64, image_file_path, load_image_b64

    for msg in messages:
        if not msg.images:
            continue
        resolved = []
        file_paths: list[str] = []
        # 收集 split_group → 段数，用于给 LLM 加顺序提示
        split_groups: dict[int, int] = {}
        for img in msg.images:
            if "data" in img:
                # 当前消息的原始 base64 图片，落盘前缩放一次
                data, downscaled = downscale_image_b64(img["data"], img.get("media_type", "image/png"))
                resolved.append({"data": data, "media_type": img.get("media_type", "image/png")})
            elif "path" in img:
                # 历史消息：落盘时已缩放，但兼容旧数据（升级前未缩放）仍调用 downscale 做安全网
                b64 = load_image_b64(img["path"])
                if b64:
                    media_type = img.get("media_type", "image/png")
                    data, downscaled = downscale_image_b64(b64, media_type)
                    entry: dict = {"data": data, "media_type": media_type}
                    # 保留 split_group 标记，后续用于生成顺序提示
                    sg = img.get("split_group")
                    if sg is not None:
                        entry["split_group"] = sg
                        split_groups[sg] = split_groups.get(sg, 0) + 1
                    resolved.append(entry)
                    file_paths.append(str(image_file_path(img["path"])))
                # 文件不存在则跳过（不影响 LLM 调用）
            else:
                resolved.append(img)
        msg.images = resolved
        # 附加路径提示：让 agent 工具模式知道图片在本地文件系统的位置
        if file_paths and msg.role == "user" and msg.content:
            paths_hint = ", ".join(file_paths)
            msg.content = f"{msg.content}\n\n[image_paths: {paths_hint}]"
            # 如果有切分的长图，追加顺序提示
            multi_seg = {g: n for g, n in split_groups.items() if n > 1}
            if multi_seg:
                parts = [f"图片{g + 1}切分为{n}段（按顺序展示）" for g, n in sorted(multi_seg.items())]
                msg.content = f"{msg.content}\n[image_split: {'; '.join(parts)}]"
