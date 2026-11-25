"""Session title policy and intermediate rendering helpers."""
from __future__ import annotations

import asyncio
import re
import time
import uuid
from pathlib import Path

from ethan.providers.base import Message


def _generate_id() -> str:
    ts = time.strftime("%Y%m%d_%H%M")
    short = uuid.uuid4().hex[:4]
    return f"s_{ts}_{short}"


def _slug_message_id(message_id: int) -> str:
    return f"msg_{message_id}.process.md"


def _intermediate_preview(text: str, limit: int = 120) -> str:
    text = re.sub(r"\s+", " ", (text or "")).strip()
    if len(text) <= limit:
        return text
    return text[:limit] + "…"


def _build_intermediate_markdown(msg: Message) -> str:
    parts: list[str] = ["# 过程记录"]
    if msg.tool_steps:
        for idx, step in enumerate(msg.tool_steps, start=1):
            title = step.get("tool") or f"step_{idx}"
            parts.append(f"\n## Step {idx} · {title}")
            if step.get("thought"):
                parts.append("\n### 工具调用前思考\n" + str(step["thought"]).strip())
            if step.get("injected"):
                injected = step["injected"]
                if isinstance(injected, list) and injected:
                    parts.append("\n### 用户补充信息\n" + "\n\n".join(f"- {m}" for m in injected))
            if step.get("args"):
                parts.append("\n### 参数\n```text\n" + str(step["args"]).strip() + "\n```")
            if step.get("result_preview"):
                parts.append("\n### 结果摘要\n" + str(step["result_preview"]).strip())
            if step.get("result_detail"):
                detail = str(step["result_detail"]).strip()
                fence = "````" if "```" in detail else "```"
                parts.append(f"\n### 结果详情\n{fence}\n" + detail + f"\n{fence}")
    elif msg.thought:
        parts.append("\n## 思考过程\n" + str(msg.thought).strip())
    return "\n".join(p for p in parts if p.strip()).strip() + "\n"


def _auto_title(messages: list[Message]) -> str:
    """从第一条用户消息提取占位标题（已清洗 markdown / 命令前缀）。"""
    import re

    for m in messages:
        if m.role == "user" and m.content:
            t = m.content.strip()
            # 去掉 markdown 标记（**粗体**、# 标题、`代码`、_斜体_、~删除~）
            t = re.sub(r"[*#`_~]", "", t)
            # 去掉命令前缀（/help xxx → xxx；/review url 保留 url 由 _rule_title 处理）
            t = re.sub(r"^/(?:help|new|model|token|btw|stop)\s+", "", t)
            # 剔除书名号/方头括号类装饰符号（用户原文可能就带《》），留纯文字
            t = strip_title_decoration(t)
            t = t.replace("\n", " ").strip()
            if not t:
                t = m.content.strip().replace("\n", " ")
            return t[:40] + ("…" if len(t) > 40 else "")
    return "新对话"


def _count_content(text: str) -> int:
    """中英文混合的内容量度：中文按字数，英文按单词数，取两者之和。

    例：
      "你好" → 2
      "hello world" → 2
      "你好 hello world" → 4
      "hi" → 1
    """
    import re

    if not text:
        return 0
    # 中日韩字符（含全角标点）每个算 1
    cjk = len(re.findall(r"[\u4e00-\u9fff\u3040-\u309f\u30a0-\u30ff\uac00-\ud7af]", text))
    # 去掉 CJK 后按空白拆分英文单词
    non_cjk = re.sub(r"[\u4e00-\u9fff\u3040-\u309f\u30a0-\u30ff\uac00-\ud7af]", " ", text)
    words = [w for w in non_cjk.split() if w and any(c.isalnum() for c in w)]
    return cjk + len(words)


SHORT_QUESTION_CHARS = 3


_TITLE_MAX_LEN = 20


_PR_URL_RE = re.compile(
    r"https?://github\.com/(?P<gh_repo>[^/\s]+/[^/\s]+)/pull/(?P<gh_num>\d+)"
    r"|https?://gitlab\.com/(?P<gl_repo>[^/\s]+/[^/\s]+)/-/merge_requests/(?P<gl_num>\d+)"
)


_PLACEHOLDER_RE = re.compile(
    r"<\s*(?:owner|repo|branch|pr|mr|n|number|编号|分支名|分支|仓库|数字)\s*>"
    r"|(?<![\w/])(?:owner|org)/repo(?![\w/])",
    re.IGNORECASE,
)


def _pr_title_from_text(text: str) -> str | None:
    """从任意文本里找出第一个 PR/MR 链接并填充命名模板；没有链接返回 None。

    模板（对齐 naming.md）：
      GitHub PR  → `#<编号> <owner>/<repo> code review`
      GitLab MR  → `!<编号> <owner>/<repo> code review`

    链接可以出现在文本**任意位置**（行首的 `/review` 只是其中一种写法），
    从而不必把「模板该填什么值」交给模型去猜。
    """
    m = _PR_URL_RE.search(text)
    if not m:
        return None
    if m.group("gh_repo"):
        return f"#{m.group('gh_num')} {m.group('gh_repo')} code review"
    return f"!{m.group('gl_num')} {m.group('gl_repo')} code review"


_THINK_BLOCK_RE = re.compile(r"<think\b[^>]*>.*?</think\s*>", re.IGNORECASE | re.DOTALL)


_THINK_OPEN_RE = re.compile(r"<think\b[^>]*>.*$", re.IGNORECASE | re.DOTALL)


_THINK_TAG_RE = re.compile(r"</?think\b[^>]*>", re.IGNORECASE)


_MD_BLOCK_PREFIX_RE = re.compile(r"^\s*(?:#{1,6}\s+|>+\s*)+")


_MD_WRAP_RE = re.compile(r"^\s*([*_`~]{1,3})(.+?)\1\s*$", re.DOTALL)


_TITLE_BRACKET_RE = re.compile(r"[《〉〈》【】〖〗〔〕「」『』]")


def strip_title_decoration(text: str) -> str:
    """剔除标题里的书名号/方头括号类装饰符号并收敛空白，留纯文字。

    剔《》【】「」等符号 + 压连续空格 + strip 这套动作是公共逻辑，
    _sanitize_title / _auto_title / REPL 初始标题共用，别再各写一遍。
    """
    t = _TITLE_BRACKET_RE.sub("", text)
    return re.sub(r"\s{2,}", " ", t).strip()


def _sanitize_title(raw: str) -> str:
    """清洗模型返回的标题：去掉 <think> 思考块、包裹用的 markdown 标记、首尾引号/空白。

    某些 lite 模型/中转会把推理过程以内联 <think>...</think> 塞进正文，或输出
    markdown 标记（如 **标题**）；直接当标题会出现 "<think>**Creating a" 这类脏值。

    注意：只剥掉「包裹整个标题的」行内强调定界符和「行首的」块级标记，
    保留标题内部的合法字符——`foo_bar`、`C# guide`、`A > B` 不应被改动。
    书名号/方头括号类装饰符号（《》【】「」等）则全部剔除，列表里只剩装饰。
    """
    if not raw:
        return ""
    t = _THINK_BLOCK_RE.sub("", raw)  # 先去成对思考块
    t = _THINK_OPEN_RE.sub("", t)     # 再去未闭合的开标签及其后内容
    t = _THINK_TAG_RE.sub("", t)      # 兜底清掉残余标签碎片
    t = t.strip()
    t = _MD_BLOCK_PREFIX_RE.sub("", t)  # 去行首 heading/quote 标记
    # 反复剥掉成对包裹的强调定界符（如 **`标题`** 这类嵌套）
    while True:
        m = _MD_WRAP_RE.match(t)
        if not m:
            break
        t = m.group(2).strip()
    t = strip_title_decoration(t)  # 剔《》【】「」等装饰符号 + 压连续空格
    t = t.strip('"\'“”').strip()
    return t


_NAMING_RULES_CACHE: tuple[float, str] | None = None


def reload_naming_rules() -> None:
    """清空 naming.md 缓存，下次 _load_naming_rules 重新读盘。

    设置页保存命名规则后调用，无需重启进程即可生效。
    """
    global _NAMING_RULES_CACHE
    _NAMING_RULES_CACHE = None


def _naming_rules_path() -> Path:
    from ethan.core.paths import system_dir

    return system_dir() / "naming.md"


def _load_naming_rules() -> str:
    """读取 ~/.ethan/system/naming.md 的命名规则，带 mtime 缓存。

    文件不存在 / 为空 → 返回 ""（调用方据此退化到无规则的老 prompt）。
    """
    global _NAMING_RULES_CACHE

    p = _naming_rules_path()
    try:
        mtime = p.stat().st_mtime
    except OSError:
        _NAMING_RULES_CACHE = None
        return ""
    if _NAMING_RULES_CACHE is not None and _NAMING_RULES_CACHE[0] == mtime:
        return _NAMING_RULES_CACHE[1]
    try:
        content = p.read_text(encoding="utf-8").strip()
    except OSError:
        return ""
    _NAMING_RULES_CACHE = (mtime, content)
    return content


_TITLE_SYSTEM_BASE = (
    "你是一个标题生成助手。你只能基于给出的文本总结标题，无法也无需访问任何链接或外部资源；"
    "标题不超过 20 个字，只输出标题本身，不加引号或标点，不要用《》【】「」等符号包裹。"
)


def _build_title_system_prompt() -> str:
    """标题生成的 system prompt：基础指令 + 用户可维护的命名规则（naming.md）。"""
    rules = _load_naming_rules()
    if not rules:
        return _TITLE_SYSTEM_BASE
    return f"{_TITLE_SYSTEM_BASE}\n\n# 命名规则（必须遵守）\n{rules}"


async def _generate_smart_title(messages: list[Message], retries: int = 3) -> str | None:
    """用廉价模型生成 ≤20 字的简洁标题；lite 模型可用时失败重试 retries 次。

    返回 None 表示「没生成出来」，调用方据此决定是否保留占位标题，绝不拿兜底值覆盖：
    - 没有可用的 lite 模型（create_provider 抛错）→ 回退到主模型再试一次；仍失败返回 None。
    - 模型可用但调用全部失败（超时/限流/endpoint 抖动）→ 退避重试后返回 None。
    """
    import re as _re

    from ethan.core.config import get_config
    from ethan.memory.consolidator import get_lite_model
    from ethan.providers.manager import create_provider

    # 外链脱敏：避免 lite 模型误以为需要访问外链而拒绝生成标题。
    # 但 PR/MR 链接必须**原样保留**——naming.md 的模板要用它填 owner/repo/编号，
    # 一旦变成 [链接] 模型就再也拿不到值，只能照抄规则文件里的示例占位符
    # （曾产生标题 "#100 owner/repo code"）。
    # 用「单个正则 + 回调」而不是两次 sub：两次 sub 时先跑 _PR_URL_RE 等于什么都没做，
    # 后面 _url_re 照样把 PR 链接吃掉。
    _scrub_re = _re.compile(
        rf"(?P<pr>{_PR_URL_RE.pattern})|(?P<other>https?://\S+)",
    )

    def _clean(text: str) -> str:
        # 逐个 URL 判断保留还是脱敏，同时给「非 URL 的正文」单独计长：链接本身不占
        # 100 字预算。这样第 100 字符正好落在 PR 链接中间时，链接仍被完整保留，不会
        # 被切半截。（旧写法 text[:100] 是先切残再匹配，半截 URL 匹配不上 _PR_URL_RE，
        # 于是被当普通外链脱敏，又回到模型拿不到 owner/repo 的老问题。）
        out: list[str] = []
        used = 0
        last = 0

        def _head(seg: str) -> str:
            """非 URL 正文按剩余预算截断。"""
            nonlocal used
            room = max(0, 100 - used)
            kept = seg[:room]
            used += len(kept)
            return kept

        for m in _scrub_re.finditer(text):
            out.append(_head(text[last:m.start()]))
            if used >= 100:
                break
            out.append(m.group(0) if m.group("pr") else "[链接]")
            last = m.end()
        out.append(_head(text[last:]))
        return "".join(out).strip()

    turns = [(m.role, _clean(m.content)) for m in messages if m.role in ("user", "assistant") and m.content][:6]
    if not turns:
        return None

    conv = "\n".join(f"{'用户' if r == 'user' else 'AI'}: {c}" for r, c in turns)
    # 长度等具体规则以 naming.md 为准，这里只给基础引导，避免与规则文件互相打架
    prompt = f"根据以下对话文本生成一个简洁的标题，只输出标题本身：\n\n{conv}"

    cfg = get_config()
    provider = None
    # 优先廉价 lite 模型；拿不到（未配置/不支持的供应商）时回退主模型，避免放弃命名
    for candidate in (get_lite_model(cfg.defaults.model), cfg.defaults.model):
        if not candidate:
            continue
        try:
            provider = create_provider(candidate)
            break
        except Exception:
            continue
    if provider is None:
        return None

    # 模型拒绝/跑偏时的典型开头（如 "I can't access external links"），视为生成失败
    _refusal_re = _re.compile(
        r"^(i can'?t|i cannot|i'm unable|i am unable|sorry|抱歉|对不起|无法|我不能)",
        _re.IGNORECASE,
    )

    for attempt in range(retries):
        try:
            resp = await provider.chat(
                [Message(role="user", content=prompt)],
                system=_build_title_system_prompt(),
                disable_thinking=True,
            )
            title = _sanitize_title(resp.content)
            # _PLACEHOLDER_RE 命中 = 模型把 naming.md 的模板占位符原样吐了回来，
            # 这不是标题，当作生成失败重试；全失败返回 None，调用方保留占位标题。
            if title and not _refusal_re.match(title) and not _PLACEHOLDER_RE.search(title):
                return title[:_TITLE_MAX_LEN]
        except Exception:
            pass
        if attempt < retries - 1:
            await asyncio.sleep(0.5 * (attempt + 1))
    return None


_PROTECTED_PREFIXES = ("[定时]", "[后台]", "[心跳]")


def _rule_title(text: str) -> str | None:
    """消息里出现 PR/MR 链接时，直接解析出确定性标题（无需 LLM），格式对齐 naming.md。

    链接可以在**任意位置**，不要求 `/review` 前缀也不要求行首——用户常写成
    「帮我 review 这个 PR <链接>」。这样模板的值由代码从链接里填，模型不必猜。

    GitHub: `帮我 review 这个 PR https://github.com/llm011/ethan-agent/pull/100`
      → `#100 llm011/ethan-agent code review`
    GitLab: `https://gitlab.com/larksuite/cli/-/merge_requests/42 这个改得对吗`
      → `!42 larksuite/cli code review`

    命中返回标题，没有链接则返回 None（如 `/review <分支名>`，交由模型按 naming.md 兜底）。

    注意：**不做 20 字截断**。命名模板天然长于 20 字（`#100 llm011/ethan-agent code
    review` 就是 35 字符），硬切只会得到 `#100 llm011/ethan-agent code` 这类残句——
    这正是模板占位符标题那次的成因。≤20 字是给模型的 prompt 约束，规则路径不适用。
    """
    return _pr_title_from_text(text)


def _is_placeholder_title(current_title: str, messages: list[Message]) -> bool:
    """判断当前标题是否仍是「从未成功命名过」的占位/截断标题。"""
    if current_title in ("", "新对话"):
        return True
    return current_title == _auto_title(messages)


async def decide_title(messages: list[Message], current_title: str = "") -> str | None:
    """统一的标题策略，返回应设置的标题；返回 None 表示本轮不改标题。

    - 第 1 轮：/review 链接直接按规则取名（零 LLM 成本）；否则首条问题内容量 ≥3
      （中文按字、英文按单词）直接生成智能标题；太短则先用清洗后的原文占位。
    - 第 2 轮：仍是占位标题时补生成智能标题，失败保留占位。
    - 第 3 轮起：**仅当标题仍是占位**（从未成功命名过，如多轮都生成失败）才继续尝试；
      已有成功标题则不再改动，避免用户突然看到标题变化。用户可用 🔄 按钮手动重试。
    """
    # 保护特殊标题（定时/后台/心跳等），不被自动标题覆盖
    if any(current_title.startswith(p) for p in _PROTECTED_PREFIXES):
        return None

    user_msgs = [m for m in messages if m.role == "user" and m.content]
    n = len(user_msgs)
    if n == 1:
        first = user_msgs[0].content.strip()
        # /review 命令：直接从 URL 解析出 "#xx owner/repo code review" 规则标题
        rule = _rule_title(first)
        if rule:
            return rule
        if _count_content(first) >= SHORT_QUESTION_CHARS:
            return await _generate_smart_title(messages) or _auto_title(messages)
        return _auto_title(messages)
    if n == 2:
        first = user_msgs[0].content.strip()
        if _count_content(first) < SHORT_QUESTION_CHARS:
            return await _generate_smart_title(messages) or _auto_title(messages)
        # 首条够长但 round 1 智能标题失败（或被 API 路径用首条消息当了初始标题）：
        # 仍是占位/截断标题时再试一次智能生成；已有好标题则跳过
        if _is_placeholder_title(current_title, messages):
            return await _generate_smart_title(messages) or _auto_title(messages)
        return None
    # 第 3 轮起：只要标题还是占位（从未成功命名）就继续补，避免永久卡在占位标题
    if _is_placeholder_title(current_title, messages):
        return await _generate_smart_title(messages) or None
    return None
