"""量化 context budget 淘汰对「前缀稳定性」的破坏（P1 复现脚本）。

模拟 agent 主循环：每轮追加一条 tool 结果，调用 enforce_context_budget，
统计在多少轮里「之前已发出的内容」被改写成摘要（即前缀字节发生变化）。

前缀稳定占比 = 累计稳定轮数 / 总轮数；越接近 1 缓存越能命中。
对应计划文档第 3 节 P1 的机制模拟表。

用法：
    .venv/bin/python -m tests.bench_context_budget_stability
    # 指定每条结果大小与轮数：
    ETHAN_BENCH_RESULT_CHARS=12000 ETHAN_BENCH_ROUNDS=40 \
        .venv/bin/python -m tests.bench_context_budget_stability
"""
from __future__ import annotations

import os
import sys

from ethan.core.context_budget import enforce_context_budget
from ethan.providers.base import Message


def _make_result(i: int, size: int) -> Message:
    # 内容带轮次标记，便于检查是否被改写；真实结果无固定标记，这里只为观测
    body = f"result_{i}_" + ("x" * (size - len(f"result_{i}_")))
    return Message(role="tool", content=body, tool_call_id=f"call_{i}")


def run(result_chars: int = 12000, rounds: int = 40) -> dict:
    working: list[Message] = []
    changed_rounds = 0  # 本轮 enforce 改写了「之前已发出」的某条内容
    stable_rounds = 0
    session_id = "bench_sess"
    for i in range(rounds):
        # 记录本轮入参前，已有 tool 消息的内容指纹
        before = {id(m): (m.content or "") for m in working if m.role == "tool"}
        working.append(_make_result(i, result_chars))
        enforce_context_budget(working, session_id)
        after = {id(m): (m.content or "") for m in working if m.role == "tool"}
        # 只看「本轮之前就存在」的消息是否被改写
        mutated = any(before[k] != after.get(k) for k in before)
        if mutated:
            changed_rounds += 1
        else:
            stable_rounds += 1
    return {
        "result_chars": result_chars,
        "rounds": rounds,
        "changed_rounds": changed_rounds,
        "stable_ratio": round(stable_rounds / rounds, 3) if rounds else 0.0,
        "final_tool_count": sum(1 for m in working if m.role == "tool"),
    }


def main() -> int:
    result_chars = int(os.environ.get("ETHAN_BENCH_RESULT_CHARS", "12000"))
    rounds = int(os.environ.get("ETHAN_BENCH_ROUNDS", "40"))
    for size in (1500, 6000, result_chars):
        r = run(size, rounds)
        print(
            f"每条 {r['result_chars']:>6} 字 / {r['rounds']} 轮 → "
            f"改写前缀 {r['changed_rounds']} 轮，前缀稳定占比 {r['stable_ratio']:.1%}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
