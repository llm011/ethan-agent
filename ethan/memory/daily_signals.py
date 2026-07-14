"""日信号采集 — 跨 session 检测重复模式、错误总结、成功路径。

一次 lite 模型调用完成判断，宁缺勿滥。
采集结果写入 ~/.ethan/memory/daily/<YYYYMMDD>.jsonl。
"""
from __future__ import annotations

import json
import logging
import time
from datetime import date
from pathlib import Path

from ethan.core.paths import user_memory_dir

logger = logging.getLogger(__name__)


def _daily_dir() -> Path:
    """每次调用时按当前 user contextvar 求值，避免模块级缓存击穿 per-user 隔离。"""
    return user_memory_dir() / "daily"

_ANALYSIS_PROMPT = """\
以下是用户近期跨多个对话的消息摘要（按时间倒序）。请分析是否存在以下模式：

1. **重复洞察**：用户反复提出相同或类似的需求/问题（≥3 次），说明这可能是一个值得固化为自动化或快捷方式的需求。
2. **错误总结**：对话中出现了明显的失败或错误（工具调用失败、用户表达不满、结果错误），总结错误原因和应对方式。
3. **成功路径**：用户对某次交互的结果明确表示满意或认可，总结是什么场景、用了什么方法让用户满意。

要求：
- 宁缺勿滥。大部分情况下不会有值得记录的模式，如果没有就输出空 JSON 数组 []
- 只输出你非常确定的模式，不要强凑
- 不要把普通的一次性问答当作模式
- 重复洞察要求至少出现 3 次相似意图

输出格式（严格 JSON 数组，无其他文字）：
```json
[
  {"type": "repetition", "pattern": "模式描述", "count": 次数, "suggestion": "可执行的建议"},
  {"type": "error", "context": "错误场景", "resolution": "建议的改进"},
  {"type": "success_path", "scenario": "成功场景描述", "method": "成功的方法/工具链"}
]
```

如果没有发现任何有价值的模式，直接输出：[]

---
用户近期消息摘要：
{messages_text}
"""


def _daily_path(d: date | None = None) -> Path:
    d = d or date.today()
    return _daily_dir() / f"{d.strftime('%Y%m%d')}.jsonl"


def read_today_signals() -> list[dict]:
    """读取今日已采集的信号。"""
    path = _daily_path()
    if not path.exists():
        return []
    signals = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                signals.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return signals


def read_signals_by_date(d: date) -> list[dict]:
    """读取指定日期的信号。"""
    path = _daily_path(d)
    if not path.exists():
        return []
    signals = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                signals.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return signals


def _append_signals(signals: list[dict]) -> None:
    """追加信号到今日 JSONL。"""
    if not signals:
        return
    path = _daily_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        for sig in signals:
            sig["ts"] = time.time()
            f.write(json.dumps(sig, ensure_ascii=False) + "\n")


async def collect_signals() -> list[dict]:
    """跨 session 采集信号 — 读最近 5 个 session 的 user 消息，一次 lite 模型调用分析。

    返回采集到的信号列表（可能为空）。
    """
    try:
        from ethan.core.paths import user_sessions_db_path
        from ethan.memory.consolidator import get_lite_model
        from ethan.memory.session import SessionStore
        from ethan.providers.base import Message
        from ethan.providers.manager import create_provider

        # 读取最近 5 个 session 的 user 消息
        store = SessionStore(db_path=user_sessions_db_path())
        await store.init()
        try:
            sessions = await store.list_recent(limit=5)
            if len(sessions) < 2:
                return []  # 至少要有 2 个 session 才有跨 session 分析的意义

            messages_parts: list[str] = []
            for sess in sessions:
                full_sess = await store.get(sess.id)
                if not full_sess:
                    continue
                user_msgs = [
                    m.content[:200] for m in full_sess.messages
                    if m.role == "user" and m.content
                ]
                if user_msgs:
                    messages_parts.append(
                        f"[会话: {full_sess.title}]\n" + "\n".join(f"  - {m}" for m in user_msgs[-8:])
                    )
        finally:
            await store.close()

        if not messages_parts:
            return []

        messages_text = "\n\n".join(messages_parts)

        # 一次 lite 模型调用
        model = get_lite_model()
        provider = create_provider(model)
        prompt = _ANALYSIS_PROMPT.format(messages_text=messages_text)

        resp = await provider.chat(
            [Message(role="user", content=prompt)],
            system="你是一个行为模式分析工具。严格按 JSON 格式输出，不要输出任何解释文字。",
        )

        raw = (resp.content or "").strip()
        # 提取 JSON 部分
        if "```" in raw:
            # 去掉 markdown code fence
            import re
            match = re.search(r"```(?:json)?\s*\n?(.*?)```", raw, re.DOTALL)
            if match:
                raw = match.group(1).strip()

        signals = json.loads(raw)
        if not isinstance(signals, list):
            return []

        # 过滤有效信号
        valid = []
        for sig in signals:
            if not isinstance(sig, dict) or "type" not in sig:
                continue
            if sig["type"] not in ("repetition", "error", "success_path"):
                continue
            valid.append(sig)

        if valid:
            _append_signals(valid)
            logger.info("[DailySignals] Collected %d signal(s)", len(valid))

        return valid

    except json.JSONDecodeError:
        logger.warning("[DailySignals] LLM output not valid JSON")
        return []
    except Exception:
        logger.warning("[DailySignals] Signal collection failed", exc_info=True)
        return []
