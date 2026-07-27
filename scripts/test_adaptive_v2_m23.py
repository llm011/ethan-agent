#!/usr/bin/env python3
"""Adaptive Planning v2 测试 - M2/M3 case

只发请求拿 session_id，分析从 docker logs 抓 logger 输出。
"""

import json
import subprocess
import sys
import time
import urllib.request

API = "http://127.0.0.1:8989/v1/chat/completions"
KEY = "sk-ethan-78145097df1b861272f63347d501ef1c5ba9e7e51f129239"

CASES = [
    {
        "id": "M2",
        "desc": "信息不足(应触发 C: 增强上下文)",
        "msg": "帮我把上次和张三聊的关于绩效的对话整理成笔记。如果找不到，告诉我你需要哪些信息才能继续。",
    },
    {
        "id": "M3",
        "desc": "复杂多步(应触发 B: plan_write)",
        "msg": "对比 ~/.ethan/skills/obsidian 和 ~/.ethan/skills/life-manager 两个技能：1) 都读 SKILL.md；2) 找出各自的硬规则段；3) 对比硬规则的差异；4) 把差异整理成清单；5) 存到知识库。",
    },
]


def call_api(message, timeout=300):
    body = json.dumps({"messages": [{"role": "user", "content": message}]}).encode()
    req = urllib.request.Request(
        API,
        data=body,
        headers={"Authorization": f"Bearer {KEY}", "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def analyze_docker_logs(sid, since_minutes=10):
    """从 docker logs 抓 session 相关的 logger 输出。"""
    result = subprocess.run(
        ["docker", "logs", "ethan-dev", "--since", f"{since_minutes}m"], capture_output=True, text=True, timeout=10
    )
    out = result.stdout + result.stderr
    lines = [
        line
        for line in out.splitlines()
        if sid in line
        or "[decision-prompt]" in line
        or "[enhanced-context]" in line
        or "[need-more-info]" in line
        or "stream_chat() iter=" in line
    ]
    return lines


def run_case(case):
    print(f"\n{'=' * 70}")
    print(f"[{case['id']}] {case['desc']}")
    print(f"消息: {case['msg'][:80]}...")
    print("-" * 70)

    t0 = time.time()
    resp = call_api(case["msg"])
    elapsed = time.time() - t0
    sid = resp.get("ethan", {}).get("session_id", "")
    content = resp.get("choices", [{}])[0].get("message", {}).get("content", "")
    tokens = resp.get("usage", {}).get("total_tokens", 0)

    print(f"⏱  耗时: {elapsed:.1f}s")
    print(f"🎫 session: {sid}")
    print(f"📊 tokens: {tokens}")
    print(f"📄 响应预览: {content[:300]}")

    # 等 1 秒让日志写完
    time.sleep(1)

    print("\n--- 调用过程日志 ---")
    logs = analyze_docker_logs(sid, since_minutes=int(elapsed / 60) + 2)
    decision_count = 0
    enhanced_count = 0
    need_info_count = 0
    iter_count = 0
    tools_seq = []
    for line in logs:
        if "[decision-prompt]" in line:
            decision_count += 1
        elif "[enhanced-context]" in line:
            enhanced_count += 1
        elif "[need-more-info]" in line:
            need_info_count += 1
        elif "stream_chat() iter=" in line:
            iter_count += 1
            # 提取工具名
            if "tools=[" in line:
                t = line.split("tools=[")[1].rstrip("]")
                tools_seq.append(t[:80])
        # 只打印关键行
        if any(k in line for k in ["decision-prompt", "enhanced-context", "need-more-info"]):
            print(f"  {line.split('  ', 1)[-1] if '  ' in line else line}")

    print("\n--- 统计 ---")
    print(f"总迭代轮数: {iter_count}")
    print(f"决策提示注入: {decision_count} 次")
    print(f"增强上下文注入: {enhanced_count} 次")
    print(f"need-more-info 检测: {need_info_count} 次")
    print(f"工具调用序列 ({len(tools_seq)} 个):")
    for i, t in enumerate(tools_seq[:15], 1):
        print(f"  iter{i}: {t}")
    if len(tools_seq) > 15:
        print(f"  ... +{len(tools_seq) - 15} more")

    return {
        "case": case["id"],
        "desc": case["desc"],
        "session_id": sid,
        "elapsed": round(elapsed, 1),
        "tokens": tokens,
        "iter_count": iter_count,
        "decision_count": decision_count,
        "enhanced_count": enhanced_count,
        "need_info_count": need_info_count,
        "tool_count": len(tools_seq),
        "resp_preview": content[:200],
    }


def main():
    results = []
    for case in CASES:
        r = run_case(case)
        results.append(r)
        time.sleep(2)

    print(f"\n{'=' * 70}")
    print("汇总")
    print("=" * 70)
    print(
        f"{'Case':<5} {'场景':<25} {'耗时':<8} {'tokens':<10} {'迭代':<6} {'决策提示':<10} {'增强上下文':<12} {'need-info':<10} {'工具数':<8}"
    )
    print("-" * 100)
    for r in results:
        print(
            f"{r['case']:<5} {r['desc'][:23]:<25} {r['elapsed']:<8} {r['tokens']:<10} "
            f"{r['iter_count']:<6} {r['decision_count']:<10} {r['enhanced_count']:<12} "
            f"{r['need_info_count']:<10} {r['tool_count']:<8}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
