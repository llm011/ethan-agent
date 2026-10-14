"""system/*.md 单文件体积护栏——防止 agent 自写文件膨胀进每次请求的 system prompt。

背景（线上 badcase）：`agent.md` 指引「发现值得复用的 shell 命令 → 追加到
`~/.ethan/system/tools.md`」，心跳任务把每轮检查结果也追加进该文件，且记录里
自带「下轮继续这样记录」的自指引，形成自我增殖。tools.md 涨到 1.7M 字符
（约 100 万 token，88.7% 是 2303 条心跳日志），而它经 `<tools_reference>` 注入
每一次 LLM 请求的 system prompt——单次请求 prompt 直接逼近上游上限，cache
永远 miss，每个会话每轮请求都全额计费。

防线设计（只拦读、不改写磁盘）：
  - 加载时单文件超过 SYSTEM_FILE_MAX_CHARS（默认 200K 字符 ≈ 100K token）
    就截断保留头部（工具参考类内容的价值密度集中在先写的部分），尾部丢弃，
    并附一段截断标记让模型知悉。
  - 磁盘原文件不动：截断是读侧兜底，不影响用户手改；真正的治理是把日志类
    内容从 system 文件里挪走（见 agent.md 的写入指引与心跳 prompt 护栏）。
  - 超限打 warning 日志，方便从日志侧发现膨胀源头。

阈值可调（环境变量）：ETHAN_SYSTEM_FILE_MAX_CHARS，0 = 关闭护栏（不推荐）。
"""
from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)

# 单个 system 文件注入 system prompt 的字符上限。默认 200K 字符：
# 出厂 tools.md 模板约 4K，正常累积的「值得复用的命令」类内容数十 K 封顶；
# 200K 已是正常量的 5-10 倍余量，同时把最坏情况的 prompt 占用压在
# ~100K token（上游上限的 1/10），单个文件失控不会再吃掉整个上下文。
DEFAULT_SYSTEM_FILE_MAX_CHARS = 200_000

_ENV_MAX = "ETHAN_SYSTEM_FILE_MAX_CHARS"


def system_file_max_chars() -> int:
    """单文件注入上限（字符）。环境变量可覆盖；0 表示关闭护栏。"""
    raw = (os.environ.get(_ENV_MAX) or "").strip()
    if not raw:
        return DEFAULT_SYSTEM_FILE_MAX_CHARS
    try:
        return int(raw)
    except ValueError:
        return DEFAULT_SYSTEM_FILE_MAX_CHARS


# 截断标记（模型面向）：说明只保留了头部，尾部内容被丢弃。
_TRUNCATED_NOTICE = (
    "\n\n[⚠️ 本文件已超过 {limit} 字符的安全上限，为避免撑爆上下文，"
    "仅保留前 {kept} 字符，{omitted} 字符被省略。"
    "文件大概率已被运行日志类内容污染——请勿继续向本文件追加记录；"
    "如需排查完整内容请直接 file_read 原文件。]"
)


def guard_system_file_content(content: str, name: str) -> str:
    """单文件体积护栏：超限截断保留头部。未超限原样返回。

    name 仅用于日志定位（identity/soul/agent/tools/user_profile）。
    """
    limit = system_file_max_chars()
    if limit <= 0 or len(content) <= limit:
        return content
    kept = content[:limit]
    omitted = len(content) - len(kept)
    notice = _TRUNCATED_NOTICE.format(limit=limit, kept=limit, omitted=omitted)
    logger.warning(
        "system 文件 %s 超限（%d 字符 > 上限 %d），注入前截断 %d 字符（磁盘文件未改动）",
        name, len(content), limit, omitted,
    )
    out = kept + notice
    # 小阈值下标记本身可能比省下的还长，护栏意义是「不让注入变大」
    return out if len(out) < len(content) else kept
