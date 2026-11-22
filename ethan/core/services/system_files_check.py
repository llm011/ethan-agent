"""system/*.md 体积的每周体检 —— 只报告，不动手。

## 为什么需要

`~/.ethan/system/tools.md` 会持续增长：agent 踩坑后会把经验追加进去
（`agent.md` 的写入指引要求它这么做）。实测：

  · 一天能长 2-3K 字符
  · 历史上曾失控到 1.7M 字符（88.7% 是 2303 条心跳日志，形成自我增殖）
  · 每轮对话都全量注入 system prompt，工具循环里每次迭代都重复发送

`system_file_guard.py` 有截断兜底（超 200K 只保留头部），但那是「防止吃爆上下文」的
最后一道闸，不是治理 —— 到那一步时，文件尾部的经验已经读不到了。

## 为什么只报告、不自动归档

做过一次手工拆分（34K → 14K），发现**自动判断不可靠**：

  | 章节 | 按标题看像 | 实际是 |
  |---|---|---|
  | `生图公共池限流（2026-10-21）` | 带日期的日志 | 活规则：3张/60秒、降级链 |
  | `画图技能定型（2026-10-21）` | 带日期的日志 | 模型清单与路由配置 |
  | `cua-driver 直接调用（2026-08-28）` | 带日期的日志 | 绕过工具的操作路径 |

它们标题像事件记录，内容却是操作规范。**误归档的代价是 agent 在某个任务上
悄悄做错**（表现是「这次没做好」，不是报错），比多花几千 token 严重得多。

所以这里只算账、只建议，把决定权留给人。真要自动化，应该先积累足够多的
人工判断样本，再从中提炼可靠的判据。

## 触发方式

挂在 `_midnight_loop` 里，每天 0 点检查一次「距上次体检是否满 7 天」。
用时间戳节流而不是 cron 表达式 —— 简单、不依赖额外状态机，且重启后不会漏跑。
"""
from __future__ import annotations

import logging
import time
from pathlib import Path

logger = logging.getLogger(__name__)

# 体检周期（秒）。7 天。
CHECK_INTERVAL_SECONDS = 7 * 24 * 3600

# 单个 system 文件超过这个体积就值得看一眼（字符）。
# 参考：出厂 tools.md 模板约 4.7K；手工治理后的健康值约 14-16K。
WARN_CHARS = 30_000

# 超过这个体积强烈建议清理（字符）。此时已占 system prompt 一半以上。
URGENT_CHARS = 60_000

_STATE_FILENAME = "system_files_check.json"


def _state_path() -> Path:
    from ethan.core.paths import CONFIG_DIR

    return CONFIG_DIR / "state" / _STATE_FILENAME


def _load_last_check() -> float:
    """读取上次体检时间戳。任何异常都当作「从未检查过」。"""
    import json

    try:
        p = _state_path()
        if not p.exists():
            return 0.0
        data = json.loads(p.read_text(encoding="utf-8"))
        return float(data.get("last_check_ts") or 0.0)
    except Exception:
        return 0.0


def _save_last_check(ts: float) -> None:
    import json

    try:
        p = _state_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({"last_check_ts": ts}), encoding="utf-8")
    except Exception:
        logger.debug("[SystemFilesCheck] 保存体检时间戳失败", exc_info=True)


def _section_stats(path: Path) -> tuple[int, list[tuple[int, str]]]:
    """返回 (总字符数, [(章节字符数, 标题), ...])。"""
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines(keepends=True)
    heads = [(i, ln.rstrip()) for i, ln in enumerate(lines) if ln.startswith("## ")]
    if not heads:
        return len(text), []

    sections: list[tuple[int, str]] = []
    for idx, (start, title) in enumerate(heads):
        end = heads[idx + 1][0] if idx + 1 < len(heads) else len(lines)
        sections.append((len("".join(lines[start:end])), title.replace("## ", "")))
    return len(text), sections


def check_system_files(*, force: bool = False) -> dict | None:
    """体检 `~/.ethan/system/*.md`。

    返回体检结果 dict；若未到周期且非 force，返回 None（不做事）。
    只写一行日志，不发通知、不改任何 system 文件。
    """
    now = time.time()
    last = _load_last_check()
    if not force and (now - last) < CHECK_INTERVAL_SECONDS:
        return None

    from ethan.core.paths import system_dir

    sdir = system_dir()
    if not sdir.exists():
        _save_last_check(now)
        return None

    report: list[dict] = []
    for f in sorted(sdir.glob("*.md")):
        try:
            total, sections = _section_stats(f)
        except Exception:
            logger.debug("[SystemFilesCheck] 读取 %s 失败", f, exc_info=True)
            continue
        if total < WARN_CHARS:
            continue
        # 最大的几节：帮人快速判断「哪几块值得先看」
        top = sorted(sections, reverse=True)[:5]
        report.append({
            "file": f.name,
            "chars": total,
            "approx_tokens": total // 3,
            "level": "urgent" if total >= URGENT_CHARS else "warn",
            "top_sections": [{"chars": c, "title": t} for c, t in top],
        })

    _save_last_check(now)

    if not report:
        logger.info("[SystemFilesCheck] 每周体检：system/*.md 体积正常")
        return {"ok": True, "items": []}

    # 只打日志，不主动通知用户 —— 这条信息会在下次用户问起或看日志时被发现。
    for item in report:
        level = "URGENT" if item["level"] == "urgent" else "WARN"
        logger.warning(
            "[SystemFilesCheck] %s %s 已 %d 字符（≈%d tokens）",
            level,
            item["file"],
            item["chars"],
            item["approx_tokens"],
        )
        for sec in item["top_sections"]:
            logger.warning(
                "[SystemFilesCheck]   最大章节 %d 字符：%s",
                sec["chars"],
                sec["title"][:60],
            )
    logger.warning(
        "[SystemFilesCheck] 建议人工复核后归档。"
        "注意：标题带日期 ≠ 日志，有些是仍在用的操作规范（曾误判 4 节）。"
    )
    return {"ok": True, "items": report}
