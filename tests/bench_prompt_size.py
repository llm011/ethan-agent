"""system prompt 体积基准 — 唯一可信的「瘦身」验收指标。

背景：v2 PR 里那个 `integration_check.py` 用 `'get_context_manager' in 文件文本`
判断「集成成功」，5/5 全绿却什么都没做。本文件用**实测字符数**替代它：跑一遍真实的
`build_system_prompt`，按 xml 块拆开输出体积，任何回归都会在数字上暴露。

用法：
    python -m tests.bench_prompt_size
    python -m tests.bench_prompt_size --json

也可以直接 import `measure_prompt()` 在别的测试里做断言。
"""
from __future__ import annotations

import json
import re
import sys

# 各块的体积上限（字符）。超了说明又有人往 system prompt 里塞东西。
# 阈值不是「刚好卡住当前值」，而是留了合理余量的护栏——调高前先想清楚是不是
# 该把内容挪出 prompt（tools.md → 知识库，技能描述 → skill_list 按需取）。
#
# 实测基线（2026-11-14，full 档，中性 query，见 `python -m tests.bench_prompt_size`）：
#   TOTAL 51,954 字符 ≈ 17.3K tokens；tools_reference 34,317 占 66%。
# 注意：这些阈值是「防止继续增长」的护栏，**不代表 prompt 已经够小**。
# tools.md 的结构性拆分属于 P1 待办（见 ETHAN_V2_RESTRUCTURE_PLAN.md），
# 由另一条分支负责，不在本护栏的范围内。
BUDGETS: dict[str, int] = {
    # tools.md 是「工具怎么用」的操作手册，全文注入每轮 prompt。它天然分两类内容：
    #   通用工具知识（gws/lark-cli/shell/HA/生图…）~13K —— 每轮都该有
    #   任务专属 playbook（EigenFlux 批次、book-audio-digest、SSDExt）~21K —— 只在做那个任务时需要
    # 当前仍是未拆分的 34.3K 全量，上限按实测值留少量余量设定。
    "tools_reference": 36_000,
    "available_skills": 6_000,
    "agent_protocols": 6_000,
    "soul": 4_000,
    "behavioral_guidelines": 5_000,
}
TOTAL_BUDGET = 55_000


def measure_prompt(query: str = "帮我 debug 这段代码", channel: str = "repl") -> dict:
    """构建一次真实 system prompt 并按 xml 块统计体积。"""
    from ethan.core.agent import Message
    from ethan.core.agent_factory import create_agent

    agent = create_agent(channel=channel)
    prompt = agent._build_system([Message(role="user", content=query)])

    blocks: dict[str, int] = {}
    # 同名块累加（历史实现里 available_skills 曾出现两块，现已合并为一块；
    # 这里仍按累加统计，配合下面的 block_counts 断言守住「不重复」）。
    for m in re.finditer(r"<([a-z_]+)>(.*?)</\1>", prompt, re.S):
        name = m.group(1)
        blocks[name] = blocks.get(name, 0) + len(m.group(2))
    # 每个标签应只出现一次；重复说明又有人拼了第二个同名块。
    block_counts = {name: prompt.count(f"<{name}>\n") for name in blocks}

    return {
        "total": len(prompt),
        "approx_tokens": len(prompt) // 3,
        "blocks": blocks,
        "block_counts": block_counts,
        "prompt": prompt,
    }


def check(measured: dict | None = None) -> list[str]:
    """返回超预算项的描述；全部达标返回空列表。"""
    data = measured or measure_prompt()
    problems: list[str] = []
    for name, cap in BUDGETS.items():
        got = data["blocks"].get(name, 0)
        if got > cap:
            problems.append(f"{name}: {got} 字符 > 上限 {cap}（超出 {got - cap}）")
    if data["total"] > TOTAL_BUDGET:
        problems.append(f"总计: {data['total']} 字符 > 上限 {TOTAL_BUDGET}")
    return problems


def main(argv: list[str]) -> int:
    data = measure_prompt()
    if "--json" in argv:
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return 0 if not check(data) else 1

    print("system prompt 体积实测")
    print("=" * 52)
    print(f"{'block':30s} {'chars':>8s} {'预算':>8s}")
    for name, size in sorted(data["blocks"].items(), key=lambda kv: -kv[1]):
        cap = BUDGETS.get(name)
        marker = ""
        if cap:
            marker = "  ✅" if size <= cap else "  ❌ 超"
        print(f"{name:30s} {size:8d} {cap if cap else '-':>8} {marker}")
    print("-" * 52)
    total_marker = "✅" if data["total"] <= TOTAL_BUDGET else "❌ 超"
    print(f"{'TOTAL':30s} {data['total']:8d} {TOTAL_BUDGET:>8}  {total_marker}")
    print(f"{'≈ tokens':30s} {data['approx_tokens']:8d}")

    problems = check(data)
    if problems:
        print("\n超预算项：")
        for p in problems:
            print(f"  • {p}")
        return 1
    print("\n全部在预算内。")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
