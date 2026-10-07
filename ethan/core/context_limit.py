"""发送前的「全量输入长度」预检与裁剪——防止历史累积撑爆上游上下文窗口。

背景（线上 badcase）：`context_budget` 只管控 tool result 的体积，user/assistant
正文与 system 不受预算约束。会话长期累积后，单次请求的输入总长度超过上游
（阿里云百炼/DashScope 系）的硬限制，直接 400：

    InternalError.Algo.InvalidParameter: Range of input length should be [1, 997952]

用户侧表现为「对话突然挂掉」且报错晦涩（provider_error 原文透传）。

本模块两层防护（`agent.chat` / `agent.stream_chat` 主循环接入）：
  1. 发送前预检（proactive）：`total_input_chars()` 估算本次请求的输入总量，
     超过 `effective_input_budget()` 就用 `trim_to_limit()` 裁剪——保留 system
     与最近的历史，从最旧的轮次开始丢（在 user 消息边界切割，保证不拆散
     tool_call/tool 配对），并在开头插入一条截断提示供模型知悉。
  2. 400 兜底（reactive）：上游仍返回长度越界时（如英文内容 char≈token 的
     估算偏差导致预检没拦住），`is_input_length_error()` 识别该类错误，
     agent 层用更激进的预算（默认减半）再裁剪并重试一次；重试仍失败则
     抛出用户可读的中文错误，不再透传 provider_error 原文。

长度估算说明：上游限制单位是 token，但服务端拿不到 tokenizer，这里用字符数
做保守代理——中文约 1 字 ≈ 1 token，英文约 4 字符 ≈ 1 token，即估算只会
「提前裁」不会「漏拦」。图片不按 base64 实长计（一张截图的 base64 可达 MB 级，
但上游按固定 token 价计），按每张固定估算值计入。

阈值可配置（环境变量，env 赢过内置默认，语义与 ETHAN_SERVER_PORT 等一致）：
  - ETHAN_MAX_INPUT_CHARS：上游输入上限（字符），默认 997952；设为 0 关闭预检与裁剪。
  - ETHAN_INPUT_LIMIT_MARGIN_PCT：安全余量百分比，默认 5（预算 = 上限 × 95%）。

裁剪只动 `working`（agent loop 的浅拷贝列表，按引用替换/丢弃元素），
不改写 Message 对象、不触碰 session 持久化历史——与 context_budget 同一手：
下一轮对话 session 原样加载，是否再裁由当轮的预检决定。
"""
from __future__ import annotations

import json
import os

from ethan.providers.base import Message

# 上游（DashScope 系）对输入总长度的硬限制，来自报错原文
# `Range of input length should be [1, 997952]`。
UPSTREAM_INPUT_LENGTH_LIMIT = 997952

# 默认安全余量（%）：预检预算 = 上限 × (1 - margin)，给估算偏差留空间。
DEFAULT_MARGIN_PCT = 5

# 每张图片的长度估算（字符）。上游按图片分辨率计固定 token（一张 1568px 截图
# 约 1.5-3K tokens），不按 base64 实长计——按实长会把带图会话全部误判为超限。
_IMAGE_ESTIMATE_CHARS = 4000

_ENV_MAX_CHARS = "ETHAN_MAX_INPUT_CHARS"
_ENV_MARGIN_PCT = "ETHAN_INPUT_LIMIT_MARGIN_PCT"

# 截断提示（模型面向）：插在裁剪后列表开头，让模型知悉早期历史被省略。
# 前缀需与 agent._SYNTHETIC_USER_PREFIXES 中的登记保持一致（合成消息在
# _minimal_retry 等挑选 user 消息的场景要被排除）。
TRIM_NOTICE_PREFIX = "[会话历史已截断"
TRIM_NOTICE = (
    TRIM_NOTICE_PREFIX
    + "：因本次上下文超过模型输入上限，较早的 {count} 条历史消息已被省略（约 {omitted} 字）。"
    "以下是被保留的最近上下文，请基于此继续任务；如需更早的信息，请向用户说明。]"
)

# 上游长度越界 400 的识别特征。除 DashScope 原文外，兼顾 OpenAI / Anthropic
# 风格的同族报错（各中转网关透传的错误体都会落在 str(e) 里）。
_INPUT_LENGTH_ERROR_PATTERNS = (
    "range of input length should be",  # DashScope: Range of input length should be [1, 997952]
    "input length should be",
    "context_length_exceeded",  # OpenAI error code
    "maximum context length",  # OpenAI: This model's maximum context length is ...
    "prompt is too long",  # Anthropic: prompt is too long: N tokens > M maximum
    "input tokens exceed",  # 部分网关写法
)


def is_input_length_error(e: Exception) -> bool:
    """判断异常是否为「输入超过模型上下文上限」类 400 错误。"""
    msg = str(e).lower()
    return any(p in msg for p in _INPUT_LENGTH_ERROR_PATTERNS)


def _env_int(name: str, default: int) -> int:
    raw = (os.environ.get(name) or "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def upstream_limit() -> int:
    """上游输入长度上限（字符）。环境变量可覆盖；0 表示关闭预检。"""
    return _env_int(_ENV_MAX_CHARS, UPSTREAM_INPUT_LENGTH_LIMIT)


def margin_pct() -> int:
    """安全余量百分比。环境变量可覆盖；非法值回落默认。"""
    return _env_int(_ENV_MARGIN_PCT, DEFAULT_MARGIN_PCT)


def effective_input_budget() -> int:
    """发送前预检的实际预算（字符）= 上限 × (1 - 余量%)。0 表示功能关闭。"""
    limit = upstream_limit()
    if limit <= 0:
        return 0
    margin = margin_pct()
    if margin <= 0:
        return limit
    return int(limit * (1 - margin / 100))


def msg_chars(m: Message) -> int:
    """估算一条消息序列化后的字符量（content + tool_calls + reasoning + 图片估算）。"""
    n = len(m.content or "")
    for tc in m.tool_calls or []:
        n += len(tc.name or "")
        try:
            n += len(json.dumps(tc.arguments, ensure_ascii=False))
        except (TypeError, ValueError):
            n += len(str(tc.arguments))
    n += len(m.reasoning or "")
    n += len(m.images or []) * _IMAGE_ESTIMATE_CHARS
    return n


def total_input_chars(messages: list[Message], system: str = "") -> int:
    """估算本次请求的输入总量（system + 全部消息）。"""
    return len(system or "") + sum(msg_chars(m) for m in messages)


def _trim_notice(count: int, omitted: int) -> str:
    return TRIM_NOTICE.format(count=count, omitted=omitted)


def trim_to_limit(
    messages: list[Message],
    system: str = "",
    budget: int = 0,
) -> tuple[list[Message], int]:
    """把 messages 裁到 budget（字符）以内，返回 (新列表, 被省略的字符数)。

    策略：从最新消息向前保留，预算耗尽即在「user 消息边界」切割——
    从 user 消息开始的历史是协议安全的（不会出现开头就是孤儿 tool 消息、
    或 tool_call 与其 result 被拆散）；对 DashScope 等要求首条非 system
    消息为 user 的网关也兼容。

    - 本身未超预算 → 原样返回（omitted=0），不产生任何拷贝。
    - 预算不够容纳「从某条 user 消息起到末尾」的最短前缀（如首条 user 消息
      本身巨长）→ 尽力而为：返回仍从该 user 消息起的列表（omitted 按实际
      省略量），由调用方的 reactive 兜底报错。
    - 裁剪发生时在列表开头插入截断提示（user 角色，见 TRIM_NOTICE）。
    - 不 mutate 原 Message 对象与原列表（session 历史不受影响）。
    """
    if budget <= 0 or not messages:
        return messages, 0

    total = total_input_chars(messages, system)
    if total <= budget:
        return messages, 0

    # 提示与 system 先从预算里扣掉（提示长度自身也占输入）
    notice = _trim_notice(0, 0)
    avail = budget - len(system or "") - len(notice)
    if avail <= 0:
        # system 本身就把预算吃满：没有可保留的历史，只留最后一条尽力而为
        return [messages[-1]], total - msg_chars(messages[-1])

    # 从末尾向前累计，找到放得下的最晚起点
    kept_from = len(messages)
    acc = 0
    for i in range(len(messages) - 1, -1, -1):
        size = msg_chars(messages[i])
        if acc + size > avail and kept_from < len(messages):
            break
        acc += size
        kept_from = i

    # 切割点对齐到 user 消息边界（向前多丢几条是安全的，只会更小不会更大）
    start = kept_from
    while start < len(messages) and messages[start].role != "user":
        start += 1
    if start >= len(messages):
        # 保留区间里没有 user 消息（如一整段连续 tool 链）：退回首条 user 消息，
        # 保证协议安全优先于预算
        start = len(messages)
        for i, m in enumerate(messages):
            if m.role == "user":
                start = i
                break

    if start <= 0:
        # 一条都丢不掉（首条就是 user 且整体超预算）：尽力而为原样返回
        return messages, 0

    omitted = sum(msg_chars(m) for m in messages[:start])
    kept = list(messages[start:])
    kept.insert(0, Message(role="user", content=_trim_notice(start, omitted)))
    return kept, omitted


def trim_for_retry(
    messages: list[Message],
    system: str = "",
    budget: int = 0,
) -> tuple[list[Message], int]:
    """400 兜底重试前的激进裁剪：预算减半，给估算偏差（英文 char≈token×4 等）
    留出真实效果空间——预检没拦住的场景多半是单位偏差，按原预算裁大概率还超。"""
    return trim_to_limit(messages, system, budget // 2)
