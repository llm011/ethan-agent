"""渠道命令解析（飞书 / 微信 共用）。

在消息渠道（飞书、微信等）里，以 `/` 开头的消息被当作命令，先于 Agent 处理。
本模块负责解析命令并执行对应动作，返回给渠道要回复的文本（None 表示不是命令，交 Agent 正常处理）。

设计原则：
- 命令逻辑与具体渠道解耦，渠道只需在 CommandContext 里填回调即可
- /new 等命令需要重置当前 chat 的会话上下文，由各渠道提供 reset_session 回调
- /compact 复用 ethan.core.session_ops.compact_session，各渠道只需提供 resolve_session_id 回调
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class CommandContext:
    """渠道执行命令所需的上下文。所有回调都是 async。"""
    chat_id: str                       # 渠道会话标识（飞书 chat_id / 微信 ilink_id 等）
    raw_text: str                      # 原始消息文本
    sender_id: str = ""                # 发消息者标识（飞书 open_id），用于认主人
    is_group_chat: bool = False        # 是否群聊（群聊禁止某些敏感命令如 /owner）
    # —— 会话管理回调 ——
    reset_session: callable = None     # async (chat_id) -> None：清空 chat→session 映射，下次新建
    resolve_session_id: callable | None = None   # async (chat_id) -> str|None：取当前 session_id
    new_session: callable | None = None          # async (chat_id) -> str：显式新建并返回 session_id
    list_sessions: callable | None = None        # async (chat_id) -> str：返回文本形式的最近会话列表
    resume_session: callable | None = None       # async (chat_id, session_id_or_prefix) -> str：切到指定 session，返回提示
    # —— 配置/信息回调 ——
    get_token: callable | None = None       # async () -> str
    get_model: callable | None = None       # async () -> str
    set_model: callable | None = None       # async (model_id) -> str
    compact_session: callable | None = None # async (chat_id) -> str：压缩当前会话历史，返回摘要/提示
    summary_session: callable | None = None # async (chat_id) -> str：结构化总结当前对话（只读）
    set_owner: callable | None = None       # async (chat_id, sender_id) -> str：认主人 + 设主会话
    get_mode: callable | None = None        # async (chat_id) -> str：取当前会话 mode（"" = 默认）
    set_mode: callable | None = None        # async (chat_id, mode_key) -> None：切换当前会话 mode
    stop_task: callable | None = None       # async (chat_id) -> bool：停止当前进行中的生成，返回是否真的停了
    extra_help: str = ""                    # 渠道额外的 help 行（如 web/REPL 专属命令提示）


# 命令名 → (描述, 是否需要参数)
COMMANDS = {
    "new": ("新建对话：清空当前上下文，下一条消息开始新会话", False),
    "btw": ("顺带一问：不带历史直接问，单轮轻量查询（用法 /btw <问题>）", True),
    "review": ("Code review：不带历史，强制加载 code-review 技能（用法 /review <PR/MR 链接>）", True),
    "compact": ("压缩历史：把之前的对话压成摘要，释放上下文", False),
    "summary": ("总结对话：对当前对话生成结构化总结", False),
    "sessions": ("列出最近的会话", False),
    "stop": ("停止当前进行中的回复", False),
    "resume": ("恢复指定会话（用法 /resume <id>）", True),
    "model": ("查看/切换模型（用法 /model [id]）", False),
    "mode": ("查看/切换对话模式（用法 /mode [名称]，不带参数或 default 切回默认）", False),
    "token": ("显示 Web 访问 token（用于浏览器登录）", False),
    "owner": ("认主人：把你设为主人、当前会话设为主会话", False),
    "command": ("管理自定义命令（用法 /command add <名> <描述> | list | remove <名>）", True),
    "help": ("显示可用命令", False),
}

# 内置命令名集合（由 COMMANDS 派生，供冲突检测使用；CLI 与飞书/微信渠道共用，避免不同步）
_BUILTIN = frozenset(COMMANDS)


def resolve_custom_command(text: str) -> str | None:
    """若 text 是自定义命令，返回展开后的 agent 输入；否则返回 None。

    /my-cmd extra args  →  "{stored_prompt}\nextra args"
    /my-cmd             →  "{stored_prompt}"
    """
    t = text.strip()
    if not t.startswith("/"):
        return None
    from ethan.core.custom_commands import load_commands
    parts = t[1:].split(None, 1)
    if not parts:
        return None
    name = parts[0].lower()
    cmds = load_commands()
    if name not in cmds:
        return None
    prompt = cmds[name]
    extra = parts[1].strip() if len(parts) > 1 else ""
    return f"{prompt}\n{extra}" if extra else prompt


async def handle_command(ctx: CommandContext) -> str | None:
    """处理 / 命令。返回回复文本；若不是命令返回 None（交 Agent 正常处理）。

    命令不区分大小写，参数以空格分隔。未知命令回 help。
    """
    text = ctx.raw_text.strip()
    if not text.startswith("/"):
        return None

    parts = text[1:].split(None, 1)
    if not parts:
        return None
    name = parts[0].lower()
    arg = parts[1].strip() if len(parts) > 1 else ""

    if name == "new":
        try:
            await ctx.reset_session(ctx.chat_id)
        except Exception:
            logger.exception("reset_session failed for chat %s", ctx.chat_id)
            return "⚠️ 清空上下文失败，请稍后再试。"
        return "🧹 已清空上下文，下一条消息开始新的对话。\n（输入 /help 查看可用命令）"

    if name == "compact":
        if ctx.compact_session is None:
            return "此渠道暂不支持压缩。"
        # 压缩需要当前会话；若没有映射，先不创建
        try:
            summary = await ctx.compact_session(ctx.chat_id)
        except Exception:
            logger.exception("compact_session failed for chat %s", ctx.chat_id)
            return "⚠️ 压缩失败，请稍后再试。"
        if not summary:
            return "⚠️ 当前没有可压缩的会话。"
        # summary 可能是「对话太短」「压缩失败」等提示，也可能是真实摘要
        if summary.startswith(("对话太短", "没有可压缩", "压缩失败", "会话不存在")):
            return summary
        preview = summary if len(summary) <= 200 else summary[:200] + "…"
        return f"🧠 已压缩历史对话。\n\n> {preview}\n\n继续聊吧，我记着要点~"

    if name == "summary":
        if ctx.summary_session is None:
            return "此渠道暂不支持总结。"
        try:
            result = await ctx.summary_session(ctx.chat_id)
        except Exception:
            logger.exception("summary_session failed for chat %s", ctx.chat_id)
            return "⚠️ 总结失败，请稍后再试。"
        if not result:
            return "⚠️ 当前没有可总结的会话。"
        # 提示性文案直接返回
        if result.startswith(("对话太短", "总结失败", "会话不存在")):
            return result
        return result

    if name == "sessions":
        if ctx.list_sessions is None:
            return "此渠道暂不支持列出会话。"
        try:
            listing = await ctx.list_sessions(ctx.chat_id)
        except Exception:
            logger.exception("list_sessions failed for chat %s", ctx.chat_id)
            return "⚠️ 获取会话列表失败。"
        return listing or "暂无会话。"

    if name == "stop":
        if ctx.stop_task is None:
            return "此渠道暂不支持停止。"
        try:
            stopped = await ctx.stop_task(ctx.chat_id)
        except Exception:
            logger.exception("stop_task failed for chat %s", ctx.chat_id)
            return "⚠️ 停止失败，请稍后再试。"
        return "🛑 已停止当前回复。" if stopped else "当前没有进行中的回复。"

    if name == "resume":
        if ctx.resume_session is None:
            return "此渠道暂不支持恢复会话。"
        if not arg:
            return "用法：/resume <session_id>\n（可用 /sessions 查看会话 id）"
        try:
            return await ctx.resume_session(ctx.chat_id, arg)
        except Exception:
            logger.exception("resume_session failed for chat %s id %s", ctx.chat_id, arg)
            return "⚠️ 恢复会话失败。"

    if name == "token":
        if ctx.get_token is None:
            return "此渠道暂不支持查看 token。"
        try:
            token = await ctx.get_token()
        except Exception:
            logger.exception("get_token failed")
            return "⚠️ 获取 token 失败。"
        return f"🔑 Web 访问 token：\n{token}\n\n浏览器打开 http://<本机IP>:8900 粘贴登录。"

    if name == "model":
        # 无参数：显示当前模型；有参数：尝试切换
        if arg and ctx.set_model is not None:
            try:
                return await ctx.set_model(arg)
            except Exception:
                logger.exception("set_model failed")
                return "⚠️ 切换模型失败。"
        if ctx.get_model is None:
            return "此渠道暂不支持查看模型。"
        try:
            current = await ctx.get_model()
        except Exception:
            return "⚠️ 读取模型配置失败。"
        if arg:
            return f"此渠道暂不支持直接切换模型，当前模型：{current}\n（可在 Web 设置页或 REPL /model 切换）"
        return f"当前模型：{current}"

    if name == "mode":
        from ethan.core.modes import MODES, match_mode
        if arg:
            target = match_mode(arg)
            if target is None:
                avail = "、".join(
                    f"{m.label or m.key}（{'/'.join(a for a in m.aliases if a)}）" for m in MODES
                )
                return (
                    f"未识别的模式：{arg}\n当前模式保持不变。\n\n"
                    f"可用模式：默认（default）、{avail}"
                )
            if ctx.set_mode is None:
                return "此渠道暂不支持切换模式。"
            try:
                await ctx.set_mode(ctx.chat_id, target.key)
            except Exception:
                logger.exception("set_mode failed for chat %s", ctx.chat_id)
                return "⚠️ 切换模式失败，请稍后再试。"
            if not target.key:
                return "🛠 已切回默认（工作助手）模式。"
            tip = f"\n{target.blurb}" if target.blurb else ""
            return f"{target.icon} 已切换到「{target.label or target.key}」模式。{tip}"
        # 无参数：显示当前模式 + 可选项
        current_key = ""
        if ctx.get_mode is not None:
            try:
                current_key = await ctx.get_mode(ctx.chat_id) or ""
            except Exception:
                current_key = ""
        from ethan.core.modes import resolve_mode
        cur = resolve_mode(current_key)
        avail = "、".join(
            ["默认（default）"] + [f"{m.label or m.key}（{'/'.join(a for a in m.aliases if a)}）" for m in MODES]
        )
        return (
            f"当前模式：{cur.label or '默认（工作助手）'}\n\n"
            f"切换：/mode <名称>（如 /mode 法律）；/mode default 切回默认。\n"
            f"可用模式：{avail}"
        )

    if name == "owner":
        if ctx.is_group_chat:
            return "⚠️ 认主人只能在私聊中操作，请私聊我发 /owner。"
        if ctx.set_owner is None:
            return "此渠道暂不支持认主人。"
        try:
            return await ctx.set_owner(ctx.chat_id, ctx.sender_id)
        except Exception:
            logger.exception("set_owner failed for chat %s", ctx.chat_id)
            return "⚠️ 认主人失败，请稍后再试。"

    if name == "command":
        return _handle_command_cmd(arg)

    if name == "help":
        lines = ["🛠 可用命令："]
        for cmd, (desc, _) in COMMANDS.items():
            lines.append(f"  /{cmd} — {desc}")
        # 列出自定义命令
        from ethan.core.custom_commands import load_commands
        custom = load_commands()
        if custom:
            lines.append("")
            lines.append("自定义命令：")
            for cname, cprompt in custom.items():
                preview = cprompt if len(cprompt) <= 50 else cprompt[:47] + "…"
                lines.append(f"  /{cname} — {preview}")
        if ctx.extra_help:
            lines.append("")
            lines.append(ctx.extra_help)
        lines.append("")
        lines.append("其它消息我会当作正常对话处理~")
        return "\n".join(lines)

    # 未知命令
    return (
        f"未知命令：/{name}\n\n"
        f"输入 /help 查看可用命令。"
    )


def _handle_command_cmd(arg: str) -> str:
    """/command add <name> [desc] | list | remove <name> 的渠道内处理。"""
    from ethan.core.custom_commands import load_commands, remove_command, save_command

    sub_parts = arg.strip().split(None, 2) if arg else []
    if not sub_parts:
        cmds = load_commands()
        if not cmds:
            return "暂无自定义命令。\n用法：/command add <名称> <描述>"
        lines = ["自定义命令列表："]
        for n, p in cmds.items():
            preview = p if len(p) <= 60 else p[:57] + "…"
            lines.append(f"  /{n} — {preview}")
        return "\n".join(lines)

    sub = sub_parts[0].lower()

    if sub == "list":
        cmds = load_commands()
        if not cmds:
            return "暂无自定义命令。"
        lines = ["自定义命令列表："]
        for n, p in cmds.items():
            preview = p if len(p) <= 60 else p[:57] + "…"
            lines.append(f"  /{n} — {preview}")
        return "\n".join(lines)

    if sub == "remove":
        if len(sub_parts) < 2:
            return "用法：/command remove <名称>"
        target = sub_parts[1]
        return f"✓ 已删除 /{target}" if remove_command(target) else f"命令 /{target} 不存在。"

    if sub == "add":
        if len(sub_parts) < 3:
            return "用法：/command add <名称> <描述>\n示例：/command add review-cn 用中文做 code review，重点关注安全和性能"
        cmd_name = sub_parts[1]
        desc = sub_parts[2].strip()
        if cmd_name.lower() in _BUILTIN:
            return f"'{cmd_name}' 与内置命令冲突，请换一个名字。"
        if not cmd_name.replace("-", "").replace("_", "").isalnum():
            return "命令名只允许字母、数字、连字符和下划线。"
        save_command(cmd_name, desc)
        return f"✓ 已保存 /{cmd_name}\n使用方式：/{cmd_name} <内容>  →  模型收到：\"{desc}\\n<内容>\""

    return "用法：/command add <名称> <描述> | /command list | /command remove <名称>"


def is_command(text: str) -> bool:
    """快速判断一段文本是否是 / 命令（供渠道提前拦截，避免加 thinking 表情等开销）。"""
    return bool(text) and text.strip().startswith("/")


def is_btw(text: str) -> bool:
    """是否是 /btw 顺带一问命令。"""
    t = text.strip().lower()
    return t == "/btw" or t.startswith("/btw ") or t.startswith("/btw\t")


def btw_question(text: str) -> str:
    """从 /btw <问题> 里提取问题部分（去掉 /btw 前缀）。"""
    t = text.strip()
    return t[4:].strip()  # len("/btw") == 4


def is_review(text: str) -> bool:
    """是否是 /review code review 命令。"""
    t = text.strip().lower()
    return t == "/review" or t.startswith("/review ") or t.startswith("/review\t")


def review_target(text: str) -> str:
    """从 /review <目标> 里提取目标部分（PR/MR 链接或描述）。"""
    t = text.strip()
    return t[7:].strip()  # len("/review") == 7
