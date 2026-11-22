r"""`agent.md` 的写入指引 —— 决定 agent 把学到的东西往哪写。

## 为什么重要

`agent.md` 里的一句话决定了 agent 的行为：

    旧：「发现值得复用的 shell 命令 → 追加到 ~/.ethan/system/tools.md」

这条指引把**所有**学到的东西都导向 system 文件。后果实测：

  · tools.md 一天长 2-3K 字符
  · 历史上失控到 1.7M 字符（88.7% 是 2303 条心跳日志）
  · 记录里还自带「下轮继续这样记录」的自指引 → 自我增殖
  · 它每轮全量注入 system prompt，工具循环里每次迭代都重复发送

根因不是 agent 不听话，是**指引本身没有区分「通用规范」和「一次性经验」**。

## 契约

1. 必须按用途分流（通用规范 → tools.md；任务过程 → 知识库）
2. 必须给出可操作的判断标准（不能只说「别写日志」）
3. 必须点名禁止自指引（那是自我增殖的元凶）
4. 模板与运行时都要有（模板管新装，运行时管本机）
"""
from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = ROOT / "ethan/defaults/system/agent.md"


def _template() -> str:
    return TEMPLATE.read_text(encoding="utf-8")


# ── 分流表 ───────────────────────────────────────────────────


def test_has_routing_table():
    """必须有一张「什么内容写到哪」的表。"""
    src = _template()
    assert "学到东西往哪写" in src, "缺少写入分流的标题"
    # 表格要覆盖主要去处
    for target in ("tools.md", "knowledge_add", "memory_write", "skill_create"):
        assert target in src, f"分流表没提到 {target}"


def test_has_actionable_criterion():
    """判断标准必须可操作，不能只写「别写日志」这种抽象要求。"""
    src = _template()
    assert "判断口诀" in src, "缺少判断口诀"
    assert "换个完全无关的任务" in src, (
        "判断标准应该是「换个无关任务会不会用到」——这是可操作的自问"
    )


def test_gives_concrete_examples():
    """要有正反例，否则模型仍然不知道边界在哪。"""
    src = _template()
    # 正面例子：跨任务通用的
    assert "lark-cli" in src, "缺少「该写 tools.md」的正例"
    # 反面例子：一次性过程
    assert "cron 撞车" in src or "批次" in src, "缺少「不该写 tools.md」的反例"


# ── 禁止项 ───────────────────────────────────────────────────


def test_forbids_self_reference_directive():
    """必须点名禁止「下轮继续这样记录」——那是自我增殖的元凶。

    实测：tools.md 长到 1.7M 字符，88.7% 是心跳日志，且日志里自带
    「下轮继续这样记录」的指引，形成正反馈。
    """
    src = _template()
    assert "下轮继续这样记录" in src, "应明确点名这个自指引模式"
    assert "自我增殖" in src, "应说明为什么禁止（形成正反馈）"


def test_forbids_log_like_content():
    """禁止把运行日志/检查结果/状态快照写进 system 文件。"""
    src = _template()
    assert "运行日志" in src or "检查结果" in src
    assert "状态快照" in src


def test_mentions_historical_incident():
    """带上真实事故数字，比抽象警告有说服力。"""
    src = _template()
    assert "1.7M" in src, "应提到 1.7M 字符那次事故"


# ── 写入纪律 ─────────────────────────────────────────────────


def test_keeps_dedup_discipline():
    """「追加前先搜、合并更新」这条纪律要保留。"""
    src = _template()
    assert "合并更新" in src, "缺少去重纪律"
    assert "不要新增重复章节" in src


def test_heartbeat_discipline_kept():
    """heartbeat.md 只留任务定义，执行结果不回写。"""
    src = _template()
    assert "heartbeat.md" in src
    assert "执行结果不回写" in src


# ── 旧指引已移除 ─────────────────────────────────────────────


def test_old_misleading_directive_removed():
    """旧的「一律追加到 tools.md」必须删掉，否则和分流表矛盾。"""
    src = _template()
    assert "发现值得复用的 shell 命令 → 追加到" not in src, (
        "旧的单向指引还在 —— 它会让 agent 忽略分流表，继续无脑往 tools.md 塞"
    )


# ── 两处都要有 ───────────────────────────────────────────────


def test_runtime_file_also_updated():
    """本机运行时文件也要改 —— 模板只管新装，已装机器靠运行时。

    这条会在没有 ~/.ethan 的环境（如 CI）自动跳过。
    """
    runtime = Path.home() / ".ethan/system/agent.md"
    if not runtime.exists():
        pytest.skip("本机没有运行时 agent.md（CI 环境正常）")
    src = runtime.read_text(encoding="utf-8")
    assert "学到东西往哪写" in src, "运行时文件没同步更新，本机 agent 仍会无脑写 tools.md"
    assert "发现值得复用的 shell 命令 → 追加到" not in src


# ── 端到端 ───────────────────────────────────────────────────


def test_guidance_reaches_system_prompt():
    """新指引必须真的出现在 system prompt 里（而不是躺在文件里没人读）。"""
    from ethan.core.agent_factory import create_agent
    from ethan.providers.base import Message

    a = create_agent()
    prompt = a._build_system([Message(role="user", content="test")])
    assert "学到东西往哪写" in prompt
    assert "判断口诀" in prompt
    assert "发现值得复用的 shell 命令 → 追加到" not in prompt
