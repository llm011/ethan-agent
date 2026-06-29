"""飞书 WebSocket 事件监听器。

通过 `lark-cli event consume im.message.receive_v1` 建立长连接，
无需公网 IP 和 Webhook 配置，ethan serve 启动时自动开始监听。
"""
import asyncio
import json
import logging
import shutil
from collections import deque

logger = logging.getLogger(__name__)

_listener_task: asyncio.Task | None = None
_lark_chat_map: dict[str, str] = {}  # chat_id -> session_id, in-memory cache

# 飞书事件投递是 at-least-once：bot 未在超时窗口内 ack（长任务、断线重连重放）会重投同一条事件。
# 用 message_id 幂等去重，否则同一消息被处理多次（表现为重复回复 / 两份不同的 token 统计）。
_seen_message_ids: set[str] = set()
_seen_message_order: deque[str] = deque(maxlen=2000)


def _already_handled(message_id: str) -> bool:
    """命中返回 True（重复事件，应丢弃）；否则登记并返回 False。同事件循环内同步执行，无 await，天然原子。"""
    if not message_id:
        return False
    if message_id in _seen_message_ids:
        return True
    if len(_seen_message_order) == _seen_message_order.maxlen:
        _seen_message_ids.discard(_seen_message_order[0])  # deque 满，append 会丢最左，先同步移出 set
    _seen_message_order.append(message_id)
    _seen_message_ids.add(message_id)
    return False


def _lark_map_file():
    from pathlib import Path
    from ethan.core.config import CONFIG_DIR
    return CONFIG_DIR / "memory" / "lark_sessions.json"

def _load_lark_map():
    import json
    f = _lark_map_file()
    if f.exists():
        try:
            return json.loads(f.read_text())
        except Exception:
            pass
    return {}

def _save_lark_map(mapping: dict):
    import json
    f = _lark_map_file()
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(mapping, ensure_ascii=False))


def _lark_welcomed() -> bool:
    """是否已经向飞书发过首次配置欢迎语。每个部署只发一次，之后拉新群/清上下文都不再发。"""
    from ethan.core.config import CONFIG_DIR
    return (CONFIG_DIR / "memory" / ".lark_welcomed").exists()


def _mark_lark_welcomed() -> None:
    from ethan.core.config import CONFIG_DIR
    f = CONFIG_DIR / "memory" / ".lark_welcomed"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.touch()


async def _send_reaction(message_id: str) -> str | None:
    """给消息添加 THINKING 表情，返回 reaction_id 以便后续删除。"""
    try:
        proc = await asyncio.create_subprocess_exec(
            "lark-cli", "im", "reactions", "create",
            "--as", "bot",
            "--params", json.dumps({"message_id": message_id}),
            "--data", json.dumps({"reaction_type": {"emoji_type": "THINKING"}}),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=5)
        data = json.loads(stdout.decode(errors="replace"))
        return data.get("data", {}).get("reaction_id")
    except Exception:
        logger.debug("Failed to add reaction to %s", message_id, exc_info=True)
        return None


async def _remove_reaction(message_id: str, reaction_id: str) -> None:
    """删除之前添加的 THINKING 表情。"""
    try:
        proc = await asyncio.create_subprocess_exec(
            "lark-cli", "im", "reactions", "delete",
            "--as", "bot",
            "--params", json.dumps({"message_id": message_id, "reaction_id": reaction_id}),
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await asyncio.wait_for(proc.wait(), timeout=5)
    except Exception:
        pass


def _markdown_to_post_elements(text: str) -> list:
    """把 markdown 文本转换为飞书 post 消息的 content element 数组。

    post 是气泡样式，支持行内格式（加粗/斜体/代码/链接），不支持卡片块。
    适用于定时任务结果、通知等不需要流式编辑的场景。

    支持的语法：
    - **text** / __text__  → bold
    - *text* / _text_      → italic
    - `text`               → inline_code
    - [text](url)          → 链接
    - # / ## / ### 标题    → 加粗一行
    - > 引用               → "│ " 前缀普通文字
    - - / * 无序列表       → "• " 前缀
    - 1. 有序列表          → 数字保留
    - --- / *** 分隔线     → 一行 "────────────"
    - 空行                 → 空行元素
    """
    import re

    def _parse_inline(line: str) -> list:
        """把一行文本解析成 post inline element 列表。"""
        elements = []
        # 依次匹配：链接、inline code、加粗、斜体
        pattern = re.compile(
            r'\[([^\]]+)\]\(([^)]+)\)'   # [text](url)
            r'|`([^`]+)`'                 # `code`
            r'|\*\*([^*]+)\*\*'           # **bold**
            r'|__([^_]+)__'               # __bold__
            r'|\*([^*]+)\*'               # *italic*
            r'|_([^_]+)_'                 # _italic_
        )
        pos = 0
        for m in pattern.finditer(line):
            # 普通文字（match 前）
            if m.start() > pos:
                plain = line[pos:m.start()]
                if plain:
                    elements.append({"tag": "text", "text": plain})
            link_text, url, code, bold1, bold2, it1, it2 = m.groups()
            if url:
                elements.append({"tag": "a", "text": link_text, "href": url})
            elif code:
                elements.append({"tag": "text", "text": code, "style": ["inline_code"]})
            elif bold1 or bold2:
                elements.append({"tag": "text", "text": bold1 or bold2, "style": ["bold"]})
            elif it1 or it2:
                elements.append({"tag": "text", "text": it1 or it2, "style": ["italic"]})
            pos = m.end()
        if pos < len(line):
            elements.append({"tag": "text", "text": line[pos:]})
        if not elements:
            elements = [{"tag": "text", "text": ""}]
        return elements

    lines = text.split("\n")
    result = []
    for raw in lines:
        line = raw.rstrip()
        # 分隔线
        if re.match(r'^[-*_]{3,}$', line):
            result.append([{"tag": "text", "text": "────────────"}])
            continue
        # 标题
        m = re.match(r'^(#{1,3})\s+(.*)', line)
        if m:
            result.append([{"tag": "text", "text": m.group(2), "style": ["bold"]}])
            continue
        # 引用
        if line.startswith("> "):
            elems = _parse_inline(line[2:])
            elems[0]["text"] = "│ " + elems[0].get("text", "")
            result.append(elems)
            continue
        # 无序列表
        m = re.match(r'^[-*]\s+(.*)', line)
        if m:
            elems = _parse_inline(m.group(1))
            elems[0]["text"] = "• " + elems[0].get("text", "")
            result.append(elems)
            continue
        # 有序列表
        m = re.match(r'^(\d+\.\s+)(.*)', line)
        if m:
            elems = _parse_inline(m.group(2))
            elems[0]["text"] = m.group(1) + elems[0].get("text", "")
            result.append(elems)
            continue
        # 普通行（含空行）
        result.append(_parse_inline(line))

    return result


async def send_lark_notification(chat_id: str, text: str) -> bool:
    """向指定 chat_id 发一条 post 气泡通知（markdown 转 post elements）。

    适合定时任务结果、心跳通知等不需要流式编辑的场景。
    用 post 而不是卡片，外观是普通气泡，支持加粗/斜体/代码/链接格式。
    """
    import lark_oapi as lark
    from lark_oapi.api.im.v1 import CreateMessageRequest, CreateMessageRequestBody
    import json as _json
    from ethan.core.config import get_config

    cfg = get_config()
    lark_cfg = getattr(cfg, "lark", None)
    if not lark_cfg or not lark_cfg.app_id:
        return False
    client = (
        lark.Client.builder()
        .app_id(lark_cfg.app_id)
        .app_secret(lark_cfg.app_secret)
        .build()
    )
    content = _json.dumps({
        "zh_cn": {"title": "", "content": _markdown_to_post_elements(text)}
    }, ensure_ascii=False)
    req = (
        CreateMessageRequest.builder()
        .receive_id_type("chat_id")
        .request_body(
            CreateMessageRequestBody.builder()
            .receive_id(chat_id)
            .msg_type("post")
            .content(content)
            .build()
        )
        .build()
    )
    try:
        resp = await asyncio.to_thread(client.im.v1.message.create, req)
        if not resp.success():
            logger.warning("Lark notification failed: code=%s msg=%s", resp.code, resp.msg)
        return resp.success()
    except Exception:
        logger.exception("Failed to send Lark notification to %s", chat_id)
        return False


async def send_lark_image(chat_id: str, image_path: str, caption: str = "") -> bool:
    """向指定 chat_id 发一张图片（可选附文字说明）。

    流程：先 upload 图片拿 image_key，再发 image 消息。
    如果有 caption，额外发一条 post 气泡跟在图片后面。
    适合定时任务发图表/截图等场景。
    """
    import lark_oapi as lark
    from lark_oapi.api.im.v1 import (
        CreateMessageRequest, CreateMessageRequestBody,
        CreateImageRequest, CreateImageRequestBody,
    )
    import json as _json, os as _os
    from ethan.core.config import get_config

    cfg = get_config()
    lark_cfg = getattr(cfg, "lark", None)
    if not lark_cfg or not lark_cfg.app_id:
        return False
    client = (
        lark.Client.builder()
        .app_id(lark_cfg.app_id)
        .app_secret(lark_cfg.app_secret)
        .build()
    )

    path = _os.path.expanduser(image_path)
    if not _os.path.isfile(path):
        logger.warning("send_lark_image: file not found: %s", path)
        return False

    try:
        with open(path, "rb") as f:
            upload_req = (
                CreateImageRequest.builder()
                .request_body(
                    CreateImageRequestBody.builder()
                    .image_type("message")
                    .image(f)
                    .build()
                )
                .build()
            )
            upload_resp = await asyncio.to_thread(client.im.v1.image.create, upload_req)
        if not upload_resp.success() or not upload_resp.data:
            logger.warning("Lark image upload failed: %s %s", upload_resp.code, upload_resp.msg)
            return False
        image_key = upload_resp.data.image_key

        send_req = (
            CreateMessageRequest.builder()
            .receive_id_type("chat_id")
            .request_body(
                CreateMessageRequestBody.builder()
                .receive_id(chat_id)
                .msg_type("image")
                .content(_json.dumps({"image_key": image_key}))
                .build()
            )
            .build()
        )
        send_resp = await asyncio.to_thread(client.im.v1.message.create, send_req)
        if not send_resp.success():
            logger.warning("Lark image send failed: %s %s", send_resp.code, send_resp.msg)
            return False

        if caption:
            await send_lark_notification(chat_id, caption)
        return True
    except Exception:
        logger.exception("send_lark_image failed for %s", chat_id)
        return False


    """返回配置的飞书主会话 chat_id，未设则返回 None。"""
    from ethan.core.config import get_config
    lark_cfg = getattr(get_config(), "lark", None)
    return getattr(lark_cfg, "main_chat_id", "") or None


    """把文本/markdown 渲染成飞书 interactive 卡片的 content JSON。

    飞书卡片 markdown element 遵循 CommonMark：
    - 单 \n 被折叠成空格（显示不换行）
    - \n\n 是段落分隔（有额外间距）
    - 行尾两个空格 + \n 是硬换行（无额外间距）
    预处理：把孤立的单 \n 转为 "  \n"（硬换行），保留 \n\n 作段落。
    """
    import json as _json, re as _re
    # 把孤立单 \n（前后都不是 \n）换成行尾两空格 + \n（硬换行）
    processed = _re.sub(r'(?<!\n)\n(?!\n)', '  \n', text)
    return _json.dumps({
        "schema": "2.0",
        "body": {"elements": [{"tag": "markdown", "content": processed}]},
    }, ensure_ascii=False)


def _build_tool_elements(tool_text: str) -> list:
    """把工具进度文本直接构造成 post element 数组，不经过 markdown 解析。

    - 工具名行：**icon label** + plain (args)
    - 结果行（✓/✗ 开头）：code_block（灰色背景框，区分于正文）
    - thinking 行：plain 文字
    - 空行：空 element
    """
    import re
    rows = []
    for line in tool_text.split("\n"):
        line = line.rstrip()
        # 工具名行：**icon label**(args) 或 **icon label**`(args)`
        m = re.match(r'\*\*(.+?)\*\*[`]?\(([^)]*)\)[`]?', line)
        if m:
            rows.append([
                {"tag": "text", "text": m.group(1), "style": ["bold"]},
                {"tag": "text", "text": f"  ({m.group(2)})"},
            ])
            continue
        # 工具名行（无参数）：**icon label**
        m2 = re.match(r'\*\*(.+?)\*\*\s*$', line)
        if m2 and any(emoji in m2.group(1) for emoji in ("📖","💻","🔍","🌐","📁","✏️","🧠","💾","⏰","📋","✨","👤","📝","🔧")):
            rows.append([{"tag": "text", "text": m2.group(1), "style": ["bold"]}])
            continue
        # 结果行（✓/✗ 或 _✓ 等前缀）
        stripped = line.lstrip().lstrip("`_").rstrip("`_")
        if stripped.startswith(("✓", "✗")):
            rows.append([{"tag": "code_block", "language": "plain", "text": stripped}])
            continue
        # thinking 行
        if "thinking..." in line:
            rows.append([{"tag": "text", "text": "🤔 thinking..."}])
            continue
        # 空行或其他
        rows.append([{"tag": "text", "text": line}])
    return rows


def _render_tool_msg_content(tool_text: str) -> str:
    """把工具进度文本转成飞书 post content JSON（有样式）。"""
    import json as _json
    return _json.dumps({
        "zh_cn": {"title": "", "content": _build_tool_elements(tool_text)}
    }, ensure_ascii=False)


def _render_card_content(text: str) -> str:
    """把文本/markdown 渲染成飞书 interactive 卡片的 content JSON。

    飞书卡片 markdown element 遵循 CommonMark：
    - 单 \n 被折叠成空格（显示不换行）
    - 行尾两个空格 + \n 是硬换行（无额外间距）
    - \n\n 是段落分隔（有额外间距）
    预处理：把孤立的单 \n 转为 "  \n"（硬换行），保留 \n\n 作段落。
    """
    import json as _json, re as _re
    processed = _re.sub(r'(?<!\n)\n(?!\n)', '  \n', text)
    return _json.dumps({
        "schema": "2.0",
        "body": {"elements": [{"tag": "markdown", "content": processed}]},
    }, ensure_ascii=False)


def _render_post_content(text: str) -> str:
    """把多行文本渲染成飞书 post(富文本) 的 content JSON。

    post 的 text 标签是纯文本（不解析 markdown），但保留换行。
    适合 fast/medium 的简短回复。post 用 message.update 更新（流式编辑）。
    """
    import json as _json
    lines = text.split("\n") if text else [""]
    content = [[{"tag": "text", "text": line}] for line in lines]
    return _json.dumps({"zh_cn": {"content": content}}, ensure_ascii=False)


def _lark_client():
    """构建 lark_oapi client，未配置返回 None。"""
    import lark_oapi as lark
    from ethan.core.config import get_config
    lark_cfg = getattr(get_config(), "lark", None)
    if not lark_cfg or not lark_cfg.app_id:
        return None
    return (
        lark.Client.builder()
        .app_id(lark_cfg.app_id)
        .app_secret(lark_cfg.app_secret)
        .build()
    )


async def _send_message(chat_id: str, text: str, use_card: bool) -> tuple[str | None, str]:
    """发一条消息（卡片或 post），返回 (message_id, msg_type)。msg_type 为 'interactive' 或 'post'。

    use_card=True 发卡片（markdown 渲染，适合复杂回复）；False 发 post（纯文本，适合简短回复）。
    两种类型都支持后续流式编辑（卡片用 patch，post 用 update）。
    """
    from lark_oapi.api.im.v1 import CreateMessageRequest, CreateMessageRequestBody
    client = _lark_client()
    if client is None:
        return None, ""
    msg_type = "interactive" if use_card else "post"
    content = _render_card_content(text) if use_card else _render_post_content(text)
    req = (
        CreateMessageRequest.builder()
        .receive_id_type("chat_id")
        .request_body(
            CreateMessageRequestBody.builder()
            .receive_id(chat_id)
            .msg_type(msg_type)
            .content(content)
            .build()
        )
        .build()
    )
    try:
        resp = await asyncio.to_thread(client.im.v1.message.create, req)
        if resp.success() and resp.data:
            return resp.data.message_id, msg_type
        logger.warning("Lark create(%s) failed: code=%s msg=%s", msg_type, resp.code, resp.msg)
        return None, msg_type
    except Exception:
        logger.exception("Failed to send %s message to chat %s", msg_type, chat_id)
        return None, msg_type


async def _edit_message(message_id: str, text: str, use_card: bool) -> bool:
    """更新已发送消息的内容（流式追加效果）。

    卡片用 message.patch（更新卡片 API）；post 用 message.update（更新消息内容 API，需带 msg_type）。
    两者整体替换 content。失败返回 False（调用方决定是否重试/兜底）。
    """
    from lark_oapi.api.im.v1 import (
        PatchMessageRequest, PatchMessageRequestBody,
        UpdateMessageRequest, UpdateMessageRequestBody,
    )
    client = _lark_client()
    if client is None:
        return False

    try:
        if use_card:
            req = (
                PatchMessageRequest.builder()
                .message_id(message_id)
                .request_body(PatchMessageRequestBody.builder().content(_render_card_content(text)).build())
                .build()
            )
            resp = await asyncio.to_thread(client.im.v1.message.patch, req)
        else:
            req = (
                UpdateMessageRequest.builder()
                .message_id(message_id)
                .request_body(
                    UpdateMessageRequestBody.builder()
                    .msg_type("post")
                    .content(_render_post_content(text))
                    .build()
                )
                .build()
            )
            resp = await asyncio.to_thread(client.im.v1.message.update, req)
        if not resp.success():
            logger.debug("Lark edit(%s) failed: code=%s msg=%s", "card" if use_card else "post", resp.code, resp.msg)
        return resp.success()
    except Exception:
        logger.exception("Lark edit failed")
        return False


async def _delete_message(message_id: str) -> bool:
    """撤回/删除已发送消息。用于误发的卡片（如把 reasoning 误当答案发出后清理）。"""
    from lark_oapi.api.im.v1 import DeleteMessageRequest
    client = _lark_client()
    if client is None or not message_id:
        return False
    try:
        req = DeleteMessageRequest.builder().message_id(message_id).build()
        resp = await asyncio.to_thread(client.im.v1.message.delete, req)
        if not resp.success():
            logger.debug("Lark delete failed: code=%s msg=%s", resp.code, resp.msg)
        return resp.success()
    except Exception:
        logger.exception("Lark delete failed")
        return False


async def _send_reply(chat_id: str, text: str) -> str | None:
    """通过 lark-cli 回复消息，使用 --markdown 以正确渲染格式。
    返回发出的消息 message_id（从 JSON stdout 解析），失败时返回 None。
    """
    try:
        proc = await asyncio.create_subprocess_exec(
            "lark-cli", "im", "+messages-send",
            "--chat-id", chat_id,
            "--markdown", text,
            "--as", "bot",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=15)
        data = json.loads(stdout.decode(errors="replace"))
        return data.get("data", {}).get("message_id")
    except Exception:
        logger.exception("Failed to send Lark reply to chat %s", chat_id)
        return None


async def _handle_message(event_data: dict) -> None:
    """处理收到的消息事件，调用 Agent 并流式回复。

    lark-cli event consume 输出的是扁平结构：
    {"chat_id": "oc_xxx", "content": "text", "message_id": "om_xxx",
     "message_type": "text", "sender_id": "ou_xxx", ...}

    流式策略：
    - 积累 chunk 直到 ≥80 字符或距上次发送 ≥2 秒
    - 首次 flush：移除 THINKING 表情后发送第一条消息
    - 后续 flush：lark-cli 不支持 patch，直接追加新消息
    - 最终确保完整内容已发出
    """
    from ethan.core.agent import Agent
    from ethan.memory.session import SessionStore
    from ethan.providers.base import Message, ToolEvent, ThinkingEvent
    from ethan.skills.registry import SkillRegistry
    from ethan.tools.builtin.file import FileListTool, FileReadTool, FileWriteTool
    from ethan.tools.builtin.knowledge import KnowledgeAddTool, KnowledgeSearchTool
    from ethan.tools.builtin.memory_write import MemoryWriteTool
    from ethan.tools.builtin.procedure_write import ProcedureWriteTool
    from ethan.tools.builtin.profile_update import ProfileUpdateTool
    from ethan.tools.builtin.schedule import ScheduleCreateTool, ScheduleListTool, ScheduleRemoveTool
    from ethan.tools.builtin.skill_create import SkillCreateTool
    from ethan.tools.builtin.skill_read import SkillReadTool, SkillListTool
    from ethan.tools.builtin.secrets import SetSecretTool, GetSecretTool, ListSecretsTool
    from ethan.tools.builtin.shell import ShellTool
    from ethan.tools.builtin.web import WebFetchTool
    from ethan.tools.builtin.web_search import WebSearchTool
    from ethan.tools.builtin.search import RipgrepTool, FdTool
    from ethan.tools.registry import ToolRegistry

    # lark-cli 已经把 event 字段展平，直接从顶层读取
    if event_data.get("message_type") != "text":
        return

    # lark-cli 对 text 消息的 content 是预渲染的可读文本，直接用
    text = event_data.get("content", "").strip()
    if not text:
        return

    chat_id = event_data.get("chat_id", "")
    message_id = event_data.get("message_id", "")

    # 幂等去重：飞书 at-least-once 重投同一事件时直接丢弃，避免重复处理（重复回复 + 双份 token 统计）。
    if _already_handled(message_id):
        logger.info("[Lark] duplicate event dropped: message_id=%s", message_id)
        return

    # 发消息者 open_id（飞书按 open_id 认主人）。lark-cli 展平后字段名可能是
    # sender_id / open_id / sender_open_id，挨个兜底。
    sender_open_id = (
        event_data.get("sender_open_id")
        or event_data.get("open_id")
        or event_data.get("sender_id")
        or ""
    )

    if not chat_id:
        return

    # 主人判定：config.lark.owner_open_id 为空 = 还没认主人。
    from ethan.core.config import get_config as _gc
    _lark_cfg = getattr(_gc(), "lark", None)
    owner_open_id = getattr(_lark_cfg, "owner_open_id", "") if _lark_cfg else ""
    is_owner = bool(owner_open_id) and sender_open_id == owner_open_id
    owner_claimed = bool(owner_open_id)

    # ── /command：以 / 开头的命令先于 Agent 处理（不加思考表情，直接回复）──
    from ethan.interface.channel_commands import CommandContext, handle_command, is_command
    if is_command(text):
        async def _reset_lark_session(cid: str) -> None:
            """清空该飞书 chat 的会话映射，下次消息新建 session。"""
            if not _lark_chat_map:
                _lark_chat_map.update(_load_lark_map())
            if cid in _lark_chat_map:
                _lark_chat_map.pop(cid)
                _save_lark_map(_lark_chat_map)

        async def _get_web_token() -> str:
            from ethan.core.config import get_config
            return getattr(get_config().network, "auth_token", "") or ""

        async def _get_model() -> str:
            from ethan.core.config import get_config
            return get_config().defaults.model

        async def _resolve_lark_session(cid: str) -> str | None:
            if not _lark_chat_map:
                _lark_chat_map.update(_load_lark_map())
            return _lark_chat_map.get(cid)

        async def _list_lark_sessions(cid: str) -> str:
            from ethan.memory.session import SessionStore
            from ethan.core.paths import user_sessions_db_path
            from datetime import datetime
            store = SessionStore(db_path=user_sessions_db_path())
            await store.init()
            try:
                recent = await store.list_recent(5)
            finally:
                await store.close()
            if not recent:
                return "暂无会话。"
            current = _lark_chat_map.get(cid)
            lines = ["最近会话："]
            for s in recent:
                mark = " ← 当前" if s.id == current else ""
                t = datetime.fromtimestamp(s.updated_at).strftime("%m-%d %H:%M")
                sid = s.id if len(s.id) <= 16 else s.id[-12:]
                lines.append(f"• {sid}  {s.title}  {t}{mark}")
            lines.append("\n用 /resume <id> 恢复某个会话")
            return "\n".join(lines)

        async def _resume_lark_session(cid: str, sid_prefix: str) -> str:
            from ethan.memory.session import SessionStore
            from ethan.core.paths import user_sessions_db_path
            store = SessionStore(db_path=user_sessions_db_path())
            await store.init()
            try:
                recent = await store.list_recent(50)
            finally:
                await store.close()
            match = next((s for s in recent if s.id == sid_prefix or s.id.endswith(sid_prefix)), None)
            if not match:
                return f"找不到会话：{sid_prefix}\n用 /sessions 查看可用 id"
            if not _lark_chat_map:
                _lark_chat_map.update(_load_lark_map())
            _lark_chat_map[cid] = match.id
            _save_lark_map(_lark_chat_map)
            return f"✓ 已切换到会话：{match.title}\n（继续聊即可恢复上下文）"

        async def _compact_lark_session(cid: str) -> str:
            from ethan.core.session_ops import compact_session
            from ethan.memory.session import SessionStore
            from ethan.core.paths import user_sessions_db_path
            from ethan.core.config import get_config
            sid = _lark_chat_map.get(cid)
            if not sid:
                if not _lark_chat_map:
                    _lark_chat_map.update(_load_lark_map())
                sid = _lark_chat_map.get(cid)
            if not sid:
                return "当前没有进行中的会话，先聊几句再 /compact 吧~"
            store = SessionStore(db_path=user_sessions_db_path())
            await store.init()
            try:
                return await compact_session(store, sid, get_config().defaults.model)
            finally:
                await store.close()

        async def _set_lark_owner(cid: str, sid: str) -> str:
            """认主人：把发消息者 open_id 设为主人，当前 chat 设为主会话。"""
            from ethan.core.config import get_config, save_config, reload_config
            if not sid:
                return "⚠️ 没拿到你的 open_id，无法认主人。"
            cfg = get_config()
            cfg.lark.owner_open_id = sid
            cfg.lark.main_chat_id = cid
            save_config(cfg)
            reload_config()
            return (
                "👑 已认你为主人，并把当前会话设为主会话。\n"
                "今后通知和定时任务结果会发到这里；非主人的高风险指令我会先确认。"
            )

        async def _get_lark_mode(cid: str) -> str:
            sid = _lark_chat_map.get(cid)
            if not sid:
                if not _lark_chat_map:
                    _lark_chat_map.update(_load_lark_map())
                sid = _lark_chat_map.get(cid)
            if not sid:
                return ""
            from ethan.memory.session import SessionStore
            from ethan.core.paths import user_sessions_db_path
            store = SessionStore(db_path=user_sessions_db_path())
            await store.init()
            try:
                s = await store.load(sid)
                return getattr(s, "mode", "") or "" if s else ""
            finally:
                await store.close()

        async def _set_lark_mode(cid: str, mode_key: str) -> None:
            """切换当前飞书会话模式；无会话则新建一个带该模式的 session。"""
            from ethan.memory.session import SessionStore
            from ethan.core.paths import user_sessions_db_path
            from ethan.core.config import get_config as _gc
            if not _lark_chat_map:
                _lark_chat_map.update(_load_lark_map())
            sid = _lark_chat_map.get(cid)
            store = SessionStore(db_path=user_sessions_db_path())
            await store.init()
            try:
                if not sid:
                    s = await store.create(_gc().defaults.model, source="lark", mode=mode_key)
                    _lark_chat_map[cid] = s.id
                    _save_lark_map(_lark_chat_map)
                else:
                    await store.update_mode(sid, mode_key)
            finally:
                await store.close()

        cmd_ctx = CommandContext(
            chat_id=chat_id,
            raw_text=text,
            sender_id=sender_open_id,
            reset_session=_reset_lark_session,
            resolve_session_id=_resolve_lark_session,
            list_sessions=_list_lark_sessions,
            resume_session=_resume_lark_session,
            compact_session=_compact_lark_session,
            set_owner=_set_lark_owner,
            get_token=_get_web_token,
            get_model=_get_model,
            get_mode=_get_lark_mode,
            set_mode=_set_lark_mode,
        )
        reply = await handle_command(cmd_ctx)
        if reply:
            await _send_reply(chat_id, reply)
        return

    # 立刻加思考表情，保存 reaction_id 以便回复后删除
    reaction_id = await _send_reaction(message_id)

    # 查找或创建对应的 Session（lark 渠道归 admin）
    from ethan.core.users import get_user_store
    from ethan.core.paths import user_sessions_db_path
    lark_uid = get_user_store().get_admin_user_id()
    store = SessionStore(db_path=user_sessions_db_path())
    await store.init()

    try:
        from ethan.core.config import get_config
        cfg = get_config()
        prefix = f"lark:{chat_id}:"
        # Fast lookup: in-memory cache first, then persistent file
        if not _lark_chat_map:
            _lark_chat_map.update(_load_lark_map())
        session_id = _lark_chat_map.get(chat_id)

        if not session_id:
            session = await store.create(cfg.defaults.model, source="lark")
            # Set a clean title from the first user message
            from ethan.memory.session import _auto_title
            from ethan.providers.base import Message as _Msg
            auto = _auto_title([_Msg(role="user", content=text)])
            await store.update_title(session.id, auto)
            session_id = session.id
            _lark_chat_map[chat_id] = session.id
            _save_lark_map(_lark_chat_map)
            # 首次配置飞书时发一次欢迎语；之后拉新群、/new 清上下文都不再发（无用噪音）
            if not _lark_welcomed():
                welcome = "嘿！我是 Ethan，你的私人 AI 助手 👋\n\n我已经在这台 Mac mini 上常驻了，有任何事直接找我就行——写代码、查信息、控制设备、管理日程都行。\n\n你叫什么名字？让我记住你~"
                await _send_reply(chat_id, welcome)
                _mark_lark_welcomed()
            # Let reaction stay visible while user reads welcome, then process their actual message

        # 加载完整历史，用 WorkingMemory 重建热区（与 REPL/API 一致）
        session_obj = await store.load(session_id)
        history = session_obj.messages if session_obj else []
        session_mode = getattr(session_obj, "mode", "") or "" if session_obj else ""

        user_msg = Message(role="user", content=text)
        await store.save_message(session_id, user_msg)

        # 重建 WorkingMemory：热区最近 5 轮 + cold facts（per-user）
        # 飞书场景每条 assistant 消息体积较大（含工具/思考），5 轮够用且节省 token
        from ethan.memory.working import MemoryConfig, WorkingMemory
        from ethan.memory.facts import FactStore
        from ethan.core.paths import user_facts_path
        memory = WorkingMemory(config=MemoryConfig(hot_size=5))
        memory.cold_facts = FactStore(path=user_facts_path()).build_context()
        hist_ua = [m for m in history if m.role in ("user", "assistant")]
        pairs, i = [], 0
        while i < len(hist_ua) - 1:
            if hist_ua[i].role == "user" and hist_ua[i+1].role == "assistant":
                pairs.append((hist_ua[i], hist_ua[i+1]))
                i += 2
            else:
                i += 1
        for u, a in pairs[-memory.config.hot_size:]:
            memory.hot.append(u)
            memory.hot.append(a)
        context_messages = memory.build_context() + [user_msg]

        registry = ToolRegistry()
        from ethan.core.context import set_session_id
        from ethan.tools.builtin.browser import BrowserSessionTool, BrowserTabTool, BrowserPageTool
        set_session_id(session_id)  # browser 工具按对话隔离/授权
        for tool in [ShellTool(), WebSearchTool(), WebFetchTool(),
                     FileReadTool(), FileWriteTool(), FileListTool(),
                     RipgrepTool(), FdTool(),
                     ScheduleCreateTool(), ScheduleListTool(), ScheduleRemoveTool(),
                     KnowledgeSearchTool(), KnowledgeAddTool(),
                     MemoryWriteTool(), ProcedureWriteTool(), ProfileUpdateTool(), SkillCreateTool(),
                     SkillReadTool(), SkillListTool(),
                     SetSecretTool(), GetSecretTool(), ListSecretsTool(),
                     BrowserSessionTool(), BrowserTabTool(), BrowserPageTool()]:
            registry.register(tool)
        skills = SkillRegistry()
        skills.load()
        agent = Agent(tool_registry=registry, skill_registry=skills, channel="lark", mode=session_mode)

        # 注入主人/授权运行时上下文，配合 soul.md 的主人准则判断是否执行有副作用操作
        if not owner_claimed:
            agent.runtime_context = (
                "本渠道（飞书）还没有认主人。当前发消息的人身份未确认。"
                "对有副作用/高消耗的操作（改文件、删数据、执行 shell、花钱、对外发消息）要保守，先确认。"
            )
        elif is_owner:
            agent.runtime_context = "当前发消息的人是【主人】，可执行有副作用的操作（但危险红线操作仍需拒绝/二次确认）。"
        else:
            agent.runtime_context = (
                f"当前发消息的人【不是主人】（主人 open_id={owner_open_id[:8]}…）。"
                "默认只做只读/低风险/低消耗的事；涉及改文件、删数据、执行 shell、花钱、对外发消息等操作不要主动执行，"
                "说明需要主人授权。"
            )

        # 硬策略守卫：一旦认了主人（owner_claimed），后续就要校验——非主人不得执行 side_effect 工具。
        # 没认主人则不装守卫（permissive），仅靠上面的 runtime_context 软约束。
        # 守卫通过 ContextVar 作用于本条消息的 Agent 循环（每条飞书消息在独立 task 中处理，互不影响）。
        if owner_claimed:
            from ethan.core.consent import ChannelGuardProvider, set_consent_provider
            set_consent_provider(ChannelGuardProvider(is_owner=is_owner))

        # --- 两条消息策略 ---
        # - 工具进度（post 富文本，编辑更新）：首个工具触发时发出
        # - 最终回答（卡片，流式编辑）：首段缓冲到 ≥阈值再发，避免孤立 "I" 短卡片
        #
        # 关键防泄漏：工具调用前的 narration（如 "I will read..."）不能残留为最终答案。
        # 渠道无法预判一段文字后面是否还跟工具调用，所以采用「先发、必要时撤回」：
        # 一旦又出现工具调用（说明刚那段是工具前说明而非最终答案），撤回已发的答案卡片。
        import time as _lark_time

        tool_msg_id: str | None = None
        tool_text = ""          # 工具进度消息的内容
        answer_msg_id: str | None = None
        answer_text = ""        # 已提交到答案卡片的最终答案文字
        pending = ""            # 自上次工具事件以来缓冲的文字
        collected_tool_steps: list[dict] = []
        lark_tool_start_times: dict[str, float] = {}
        last_flush = _lark_time.time()
        answer_created = False  # 答案卡片是否已创建
        thinking_shown = False  # 是否已在工具消息里显示了 "🤔 thinking..."
        FLUSH_INTERVAL = 2.0
        ANSWER_BUFFER_THRESHOLD = 50  # 纯对话首段缓冲字数，避免孤立短卡片

        async def _update_tool_msg() -> None:
            nonlocal tool_msg_id, reaction_id
            if not tool_text:
                return
            content = _render_tool_msg_content(tool_text)
            if tool_msg_id is None:
                from lark_oapi.api.im.v1 import CreateMessageRequest, CreateMessageRequestBody
                client = _lark_client()
                if client is None:
                    return
                req = (
                    CreateMessageRequest.builder()
                    .receive_id_type("chat_id")
                    .request_body(
                        CreateMessageRequestBody.builder()
                        .receive_id(chat_id).msg_type("post").content(content).build()
                    ).build()
                )
                resp = await asyncio.to_thread(client.im.v1.message.create, req)
                if resp.success() and resp.data:
                    tool_msg_id = resp.data.message_id
                if reaction_id and message_id:
                    await _remove_reaction(message_id, reaction_id)
                    reaction_id = None
            else:
                from lark_oapi.api.im.v1 import UpdateMessageRequest, UpdateMessageRequestBody
                client = _lark_client()
                if client:
                    req = (
                        UpdateMessageRequest.builder()
                        .message_id(tool_msg_id)
                        .request_body(
                            UpdateMessageRequestBody.builder()
                            .msg_type("post")
                            .content(content)
                            .build()
                        )
                        .build()
                    )
                    await asyncio.to_thread(client.im.v1.message.update, req)

        async def _flush_answer(force: bool = False) -> None:
            nonlocal answer_msg_id, answer_text, pending, last_flush, answer_created, reaction_id
            if not pending:
                return
            # 首段缓冲到阈值再创建卡片，避免 "I" 这种孤立短卡片（force 时跳过该限制）
            if not answer_created and not force and len(pending) < ANSWER_BUFFER_THRESHOLD:
                return
            # 已创建卡片且非 force：按 FLUSH_INTERVAL 节流流式编辑
            if answer_created and not force and (_lark_time.time() - last_flush) < FLUSH_INTERVAL:
                return
            answer_text += pending
            pending = ""
            last_flush = _lark_time.time()
            if answer_msg_id is None:
                answer_created = True
                answer_msg_id, _ = await _send_message(chat_id, answer_text, use_card=True)
                # 发出首条回答后移除 reaction（若工具进度消息没发出过）
                if reaction_id and message_id:
                    await _remove_reaction(message_id, reaction_id)
                    reaction_id = None
            else:
                await _edit_message(answer_msg_id, answer_text, use_card=True)

        async for chunk in agent.stream_chat(context_messages):
            if isinstance(chunk, ThinkingEvent):
                # 模型思考：不打印 delta 原文（避免泄漏 reasoning），只在工具消息里挂一个占位。
                # 已有 reaction/工具进度时无需重复展示。
                if tool_msg_id is None and answer_msg_id is None and not thinking_shown:
                    tool_text = "🤔 thinking...\n"
                    await _update_tool_msg()
                    thinking_shown = True
                continue
            if isinstance(chunk, ToolEvent):
                if chunk.state == "start":
                    lark_tool_start_times[chunk.tool_name] = _lark_time.time()
                    collected_tool_steps.append({
                        "tool": chunk.tool_name,
                        "args": chunk.args_summary,
                        "state": "running",
                        "duration_ms": None,
                        "result_preview": "",
                    })
                    # 工具开始：丢弃本轮在工具调用前累积的 pending 文字。
                    # 这段文字是「工具前的 narration/思考」（如 "I will read...", 或流式残片 "}"），
                    # 不是最终答案——最终答案在「最后一次工具调用之后」的那一轮，由流结束时的
                    # force flush 提交。这样既不会把残片 "}" 发成卡片，也不会丢真正的回答。
                    pending = ""
                    thinking_shown = False
                    # icon + 人性化显示名映射
                    _TOOL_DISPLAY = {
                        "shell": "💻 terminal", "rg_search": "🔍 search", "fd_find": "🔍 find",
                        "file_read": "📖 read_file", "file_write": "✏️ write_file", "file_list": "📁 list_files",
                        "web_search": "🔍 web_search", "web_fetch": "🌐 web_fetch",
                        "knowledge_search": "🧠 knowledge_search", "knowledge_add": "💾 knowledge_add",
                        "memory_write": "🧠 memory_write", "procedure_write": "📝 procedure_write",
                        "profile_update": "👤 profile_update", "skill_create": "✨ skill_create",
                        "skill_read": "📖 skill_read", "skill_list": "📋 skill_list",
                        "schedule_create": "⏰ schedule_create", "schedule_list": "⏰ schedule_list",
                        "schedule_remove": "⏰ schedule_remove",
                    }
                    display_name = _TOOL_DISPLAY.get(chunk.tool_name, f"🔧 {chunk.tool_name}")
                    tool_name_line = f"**{display_name}**"
                    if chunk.args_summary:
                        tool_name_line += f"`({chunk.args_summary})`"
                    # 两个工具之间加空行
                    tool_text = (tool_text.rstrip() + "\n\n" + tool_name_line + "\n") if tool_text else tool_name_line + "\n"
                    await _update_tool_msg()
                else:  # done / error
                    duration_ms = int(
                        (_lark_time.time() - lark_tool_start_times.pop(chunk.tool_name, _lark_time.time())) * 1000
                    )
                    for step in reversed(collected_tool_steps):
                        if step["tool"] == chunk.tool_name and step["state"] == "running":
                            step["state"] = chunk.state
                            step["duration_ms"] = duration_ms
                            step["result_preview"] = chunk.result_preview or ""
                            break
                    mark = "✓" if chunk.state == "done" else "✗"
                    preview = (chunk.result_preview or "").replace("\n", " ").replace("`", "'")[:200]
                    result_line = f"_{mark} {preview}_" if preview else f"_{mark} {duration_ms}ms_"
                    tool_text = tool_text.rstrip() + "\n" + result_line
                    # 有其它工具仍在运行，追加 thinking 占位
                    running = [s for s in collected_tool_steps if s["state"] == "running"]
                    if running and not thinking_shown:
                        tool_text = tool_text.rstrip() + "\n🤔 thinking...\n"
                        thinking_shown = True
                    else:
                        tool_text += "\n"
                        thinking_shown = False
                    await _update_tool_msg()
                continue
            # 正文 chunk：进入最终回答阶段
            # 首个正文到来时若工具消息里有 "thinking..."，在工具消息末尾补一个空行分隔
            if pending == "" and tool_msg_id is not None and thinking_shown:
                tool_text = tool_text.rstrip() + "\n"
                await _update_tool_msg()
                thinking_shown = False
            pending += chunk
            await _flush_answer()

        # 流结束：flush 剩余回答
        await _flush_answer(force=True)

        # 末尾加 token 统计到回答卡片
        usage = agent.usage
        stats_parts = [f"↑{usage.input_tokens} ↓{usage.output_tokens}"]
        if usage.cache_tokens:
            stats_parts.append(f"⚡{usage.cache_tokens}")
        stats_line = "  ".join(stats_parts)

        if answer_msg_id:
            final_answer = (answer_text or "（没有找到相关内容）").rstrip() + f"\n\n---\n_{stats_line}_"
            await _edit_message(answer_msg_id, final_answer, use_card=True)
        elif tool_msg_id:
            # 只有工具调用没有正文（极少数情况），在工具消息末尾加 stats（保持 post 富文本样式）
            final_tool = tool_text.rstrip() + f"\n\n{stats_line}"
            from lark_oapi.api.im.v1 import UpdateMessageRequest, UpdateMessageRequestBody
            _tclient = _lark_client()
            if _tclient:
                _treq = (
                    UpdateMessageRequest.builder()
                    .message_id(tool_msg_id)
                    .request_body(
                        UpdateMessageRequestBody.builder()
                        .msg_type("post")
                        .content(_render_tool_msg_content(final_tool))
                        .build()
                    )
                    .build()
                )
                await asyncio.to_thread(_tclient.im.v1.message.update, _treq)
        else:
            # 没有任何输出（工具和正文都没有）
            await _send_message(chat_id, f"（没有找到相关内容）\n{stats_line}", use_card=False)

        # 确保 reaction 被清理（理论上前面已经清了）
        if reaction_id and message_id:
            await _remove_reaction(message_id, reaction_id)

        # 存库：只存最终答案正文（reasoning 已在工具阶段丢弃），减少 context token
        stored_content = (answer_text.strip() or tool_text.strip()) + f"\n\n{stats_line}"

        # 保存完整 assistant 消息到 session（带 usage + tool_steps）
        usage_dict = {
            "input": agent.usage.input_tokens,
            "output": agent.usage.output_tokens,
            "cache": agent.usage.cache_tokens,
        }
        response = Message(role="assistant", content=stored_content, usage=usage_dict, tool_steps=collected_tool_steps or [])
        await store.save_message(session_id, response)
        await store.touch(session_id)

    except Exception:
        logger.exception("Agent error handling Lark message")
        # 确保表情被清理
        if reaction_id and message_id:
            await _remove_reaction(message_id, reaction_id)
        await store.close()
        return

    await store.close()


async def _event_loop() -> None:
    """持续运行 lark-cli event consume，断线自动重连。"""
    lark_cli = shutil.which("lark-cli")
    if not lark_cli:
        logger.warning("[Lark] lark-cli not found — event listener not started")
        return

    from ethan.core.config import get_config
    cfg = get_config()
    lark_cfg = getattr(cfg, "lark", None)
    if not lark_cfg or not lark_cfg.app_id or not lark_cfg.app_secret:
        logger.info("[Lark] app_id/app_secret not configured — skipping event listener")
        return

    logger.info("[Lark] Starting WebSocket event listener via lark-cli...")

    backoff = 5
    while True:
        try:
            proc = await asyncio.create_subprocess_exec(
                lark_cli, "event", "consume", "im.message.receive_v1",
                "--as", "bot", "--quiet",
                stdin=asyncio.subprocess.PIPE,  # keep stdin open so lark-cli doesn't exit on EOF
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
            logger.info("[Lark] Connected to Feishu event bus (pid=%s)", proc.pid)
            backoff = 5  # reset backoff on successful connect

            async for line in proc.stdout:
                raw = line.decode(errors="replace").strip()
                if not raw:
                    continue
                try:
                    data = json.loads(raw)
                except json.JSONDecodeError:
                    continue

                # Events have nested structure: data.event.message
                event = data.get("event", data)
                asyncio.create_task(_handle_message(event))

            await proc.wait()
            logger.warning("[Lark] Event stream ended, reconnecting in %ss...", backoff)

        except asyncio.CancelledError:
            logger.info("[Lark] Event listener cancelled.")
            return
        except Exception:
            logger.exception("[Lark] Event listener crashed, reconnecting in %ss...", backoff)

        await asyncio.sleep(backoff)
        backoff = min(backoff * 2, 60)


def start_lark_listener() -> None:
    """在当前 event loop 中启动飞书事件监听器（FastAPI startup 时调用）。"""
    global _listener_task
    if _listener_task and not _listener_task.done():
        return
    _listener_task = asyncio.create_task(_event_loop())
    logger.info("[Lark] Event listener task created.")


def stop_lark_listener() -> None:
    """停止飞书事件监听器（FastAPI shutdown 时调用）。"""
    global _listener_task
    if _listener_task and not _listener_task.done():
        _listener_task.cancel()
