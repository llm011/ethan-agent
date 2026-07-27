#!/usr/bin/env python3
"""Adaptive Planning v3 测试 - decide 工具拦截 + 反思触发

5 个 case 覆盖：
  T1 多步任务（应触发 B: plan_write + decide(choice=B)）
  T2 信息模糊（应触发 C: decide(choice=C) + 增强上下文）
  T3 单步可完成（应触发 A: decide(choice=A) 直接收尾）
  T4 卡死场景（连续同工具不同参数 → 反思触发）
  T5 跨目录多文件操作（B + 多次 file_read）

只发请求拿 session_id，分析从 docker logs 抓 logger 输出。
"""

import json
import subprocess
import time
import urllib.request

API = "http://127.0.0.1:8989/v1/chat/completions"
KEY = "sk-ethan-78145097df1b861272f63347d501ef1c5ba9e7e51f129239"

CASES = [
    {
        "id": "T1",
        "desc": "多步任务（应触发 B: plan_write + decide choice=B）",
        "msg": (
            "对比 ~/.ethan/skills/obsidian 和 ~/.ethan/skills/life-manager 两个技能："
            "1) 都读 SKILL.md；2) 找出各自的硬规则段；3) 对比硬规则的差异；"
            "4) 把差异整理成清单；5) 存到知识库。"
        ),
    },
    {
        "id": "T2",
        "desc": "信息模糊（应触发 C: decide choice=C + 增强上下文）",
        "msg": (
            "帮我把上次和张三聊的关于绩效的对话整理成笔记。"
            "如果找不到，告诉我你需要哪些信息才能继续。"
        ),
    },
    {
        "id": "T3",
        "desc": "单步可完成（应触发 A: decide choice=A 直接收尾）",
        "msg": (
            "读 ~/.ethan/config.yaml，告诉我里面默认配置的 model 是什么。"
            "只需要回答 model 字段值即可，不要做其他事。"
        ),
    },
    {
        "id": "T4",
        "desc": "卡死场景（连续同工具不同参数 → 6 次后应触发反思）",
        "msg": (
            "在 /tmp 下创建 10 个测试文件 t1.txt 到 t10.txt，"
            "每个文件写不同的内容（数字 1-10），然后逐个读回内容验证。"
            "必须每个文件单独 file_write 创建，不能用 shell 批量。"
        ),
    },
    {
        "id": "T5",
        "desc": "跨目录多文件操作（B + 多次 file_read）",
        "msg": (
            "扫描 ~/.ethan/skills/ 下所有 SKILL.md，"
            "找出每个 skill 的 name 字段和 trigger 关键词，"
            "汇总成一张表（skill名 | trigger数 | 主要触发词），"
            "存到知识库里。"
        ),
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
        ["docker", "logs", "ethan-dev", "--since", f"{since_minutes}m"],
        capture_output=True, text=True, timeout=10,
    )
    out = result.stdout + result.stderr
    lines = []
    for line in out.splitlines():
        if any(k in line for k in [
            "[decision-prompt]", "[enhanced-context]", "[need-more-info]",
            "[decision-choice]", "stream_chat() iter=", "[sig-debug]",
            "is_stuck", "reflection", "reflection-followup",
        ]):
            lines.append(line)
    return lines


def run_case(case):
    print(f"\n{'=' * 70}")
    print(f"[{case['id']}] {case['desc']}")
    print(f"消息: {case['msg'][:80]}...")
    print("-" * 70)

    t0 = time.time()
    try:
        resp = call_api(case["msg"])
    except Exception as e:
        print(f"❌ API 调用失败: {e}")
        return None
    elapsed = time.time() - t0
    sid = resp.get("ethan", {}).get("session_id", "")
    content = resp.get("choices", [{}])[0].get("message", {}).get("content", "")
    tokens = resp.get("usage", {}).get("total_tokens", 0)

    print(f"⏱  耗时: {elapsed:.1f}s")
    print(f"🎫 session: {sid}")
    print(f"📊 tokens: {tokens}")
    print(f"📄 响应预览: {content[:300]}")

    time.sleep(1)
    print("\n--- 调用过程日志 ---")
    logs = analyze_docker_logs(sid, since_minutes=int(elapsed / 60) + 2)
    decision_count = 0
    enhanced_count = 0
    need_info_count = 0
    decision_choice = []
    iter_count = 0
    tools_seq = []
    stuck_count = 0
    reflection_count = 0
    explicit_choices = []   # decide tool_call 拦截的 choice
    implicit_choices = []   # 隐式决策检测结果（A/B/C）
    silent_count = 0        # 最后一次 silent_decision_count
    for line in logs:
        if "[decision-prompt]" in line:
            decision_count += 1
        elif "[enhanced-context]" in line:
            enhanced_count += 1
        elif "[need-more-info]" in line:
            need_info_count += 1
        elif "[decision-choice]" in line:
            # 区分显式 decide choice 和隐式 A/B/C
            if "decide choice=" in line:
                explicit_choices.append(line.split("decide choice=")[-1].strip()[:5])
            elif "隐式选 A" in line:
                implicit_choices.append("A")
                # 抓 silent_count 数字
                if "silent_count=" in line:
                    try:
                        silent_count = int(line.split("silent_count=")[-1].strip().split()[0])
                    except Exception:
                        pass
            elif "隐式选 B" in line:
                implicit_choices.append("B")
            elif "隐式选 C" in line:
                implicit_choices.append("C")
            decision_choice.append(line)
        elif "stream_chat() iter=" in line or "chat() iter=" in line:
            iter_count += 1
            if "tools=[" in line:
                t = line.split("tools=[")[1].rstrip("]")
                tools_seq.append(t[:80])
        elif "is_stuck" in line or "reflection" in line.lower():
            stuck_count += 1
            if "reflection" in line.lower():
                reflection_count += 1
        # 只打印关键行
        if any(k in line for k in [
            "decision-prompt", "enhanced-context", "need-more-info",
            "decision-choice", "is_stuck", "reflection",
        ]):
            print(f"  {line.split('  ', 1)[-1] if '  ' in line else line}")

    # 验证 decide 文本标记是否泄漏到用户响应
    leak_markers = ["决策:", "决策：", "决策: A", "决策: B", "决策: C"]
    leaked = [m for m in leak_markers if m in content]

    print("\n--- 统计 ---")
    print(f"总迭代轮数: {iter_count}")
    print(f"决策提示注入: {decision_count} 次")
    print(f"显式 decide 拦截: {len(explicit_choices)} 次 → {explicit_choices}")
    print(f"隐式决策检测: {len(implicit_choices)} 次 → {implicit_choices}")
    print(f"  其中 A (沉默干活): {implicit_choices.count('A')} 次，最终 silent_count={silent_count}")
    print(f"增强上下文注入: {enhanced_count} 次")
    print(f"need-more-info 检测: {need_info_count} 次")
    print(f"stuck/reflection: stuck={stuck_count} reflection={reflection_count}")
    print(f"工具调用序列 ({len(tools_seq)} 个):")
    for i, t in enumerate(tools_seq[:15], 1):
        print(f"  iter{i}: {t}")
    if len(tools_seq) > 15:
        print(f"  ... +{len(tools_seq) - 15} more")

    if leaked:
        print(f"⚠️  决策标记泄漏到用户响应: {leaked}")
    else:
        print("✅ 决策标记未泄漏到用户响应")

    return {
        "case": case["id"],
        "desc": case["desc"],
        "session_id": sid,
        "elapsed": round(elapsed, 1),
        "tokens": tokens,
        "iter_count": iter_count,
        "decision_count": decision_count,
        "explicit_choices": explicit_choices,
        "implicit_choices": implicit_choices,
        "silent_count": silent_count,
        "enhanced_count": enhanced_count,
        "need_info_count": need_info_count,
        "stuck_count": stuck_count,
        "reflection_count": reflection_count,
        "tool_count": len(tools_seq),
        "leaked_markers": leaked,
        "resp_preview": content[:200],
    }


def main():
    results = []
    for case in CASES:
        r = run_case(case)
        if r:
            results.append(r)
        time.sleep(2)

    print(f"\n{'=' * 70}")
    print("汇总")
    print("=" * 70)
    print(f"{'case':<6}{'耗时':<8}{'token':<8}{'iter':<6}{'决策':<6}{'显式':<6}{'隐式':<10}{'silent':<8}{'增强':<6}{'stuck':<6}{'反思':<6}{'泄漏':<6}")
    for r in results:
        implicit_summary = "/".join(r.get("implicit_choices", [])) or "-"
        print(f"{r['case']:<6}{r['elapsed']:<8.1f}{r['tokens']:<8}{r['iter_count']:<6}"
              f"{r['decision_count']:<6}{len(r.get('explicit_choices', [])):<6}"
              f"{implicit_summary:<10}{r.get('silent_count', 0):<8}"
              f"{r['enhanced_count']:<6}{r['stuck_count']:<6}{r['reflection_count']:<6}"
              f"{'⚠️' if r['leaked_markers'] else '✅':<6}")

    # 持久化结果
    out_path = "/tmp/adaptive_v3_results.json"
    with open(out_path, "w") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"\n详细结果已写入 {out_path}")


if __name__ == "__main__":
    main()
