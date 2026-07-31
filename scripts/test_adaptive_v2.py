#!/usr/bin/env python3
"""Adaptive Planning v2 E2E 测试

发请求 → 拿 session_id → 查 sessions.db 验证：
1. working 里是否注入了 [System 决策提示]
2. working 里是否注入了 [System 增强上下文]
3. assistant thought 里是否提到 A/B/C 判断
4. tool_calls 里是否出现 plan_write
"""

import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

API = "http://127.0.0.1:8989/v1/chat/completions"
KEY = "sk-ethan-78145097df1b861272f63347d501ef1c5ba9e7e51f129239"
DB = Path.home() / ".ethan" / "sessions.db"

# 3 个复杂 case
CASES = [
    {
        "id": "M1",
        "desc": "明确多步任务(应触发 B: plan_write)",
        "msg": (
            "扫描 ~/.ethan/skills 目录下所有技能，"
            "读取每个技能的 SKILL.md frontmatter，"
            "整理成 markdown 表格(列：name/version/triggers/category)，"
            "最后用 file_write 把表格写到 /tmp/skills_index.md"
        ),
        "expect": "decision_prompt + 可能 plan_write",
    },
    {
        "id": "M2",
        "desc": "信息不足(应触发 C: 增强上下文)",
        "msg": ("帮我把上次和张三聊的关于绩效的对话整理成笔记。如果找不到，告诉我你需要哪些信息才能继续。"),
        "expect": "decision_prompt + enhanced_context",
    },
    {
        "id": "M3",
        "desc": "复杂多步(应触发多轮决策提示)",
        "msg": (
            "对比 ~/.ethan/skills/obsidian 和 ~/.ethan/skills/work-notes 两个技能："
            "1) 都读 SKILL.md；2) 找出各自的硬规则段；3) 对比硬规则的差异；"
            "4) 把差异整理成清单；5) 存到知识库。"
        ),
        "expect": "多轮 decision_prompt + plan_write",
    },
]


def call_api(message, timeout=180):
    body = json.dumps({"messages": [{"role": "user", "content": message}]}).encode()
    req = urllib.request.Request(
        API,
        data=body,
        headers={"Authorization": f"Bearer {KEY}", "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def query_session_messages(sid):
    """从容器内 sessions.db 拉取该 session 的所有 messages。"""
    import subprocess

    sql = f"SELECT role, content, tool_calls, thought FROM messages WHERE session_id='{sid}' ORDER BY id"
    result = subprocess.run(
        [
            "docker",
            "exec",
            "ethan-dev",
            "python3",
            "-c",
            f"import sqlite3,json; c=sqlite3.connect('/root/.ethan/sessions.db'); c.row_factory=sqlite3.Row; rows=[dict(r) for r in c.execute({sql!r}).fetchall()]; print(json.dumps(rows, ensure_ascii=False, default=str))",
        ],
        capture_output=True,
        text=True,
        timeout=10,
    )
    if result.returncode != 0:
        print(f"  ⚠️ 查询 DB 失败: {result.stderr[:200]}")
        return []
    try:
        return json.loads(result.stdout.strip())
    except Exception as e:
        print(f"  ⚠️ 解析 DB 结果失败: {e}")
        return []


def analyze_session(sid, msgs):
    """分析 session 触发了哪些机制。"""
    result = {
        "session_id": sid,
        "total_messages": len(msgs),
        "decision_prompt_count": 0,
        "enhanced_context_count": 0,
        "plan_write_calls": 0,
        "abc_judgments": [],
        "tool_sequence": [],
    }

    for m in msgs:
        content = m.get("content") or ""
        thought = m.get("thought") or ""
        tool_calls_raw = m.get("tool_calls") or ""

        # 检测注入的 system 消息（注入到 working，但通常不存到 messages 表；检测 thought 更可靠）
        if "[System 决策提示]" in content:
            result["decision_prompt_count"] += 1
        if "[System 增强上下文]" in content:
            result["enhanced_context_count"] += 1

        # 检测 thought 里的 A/B/C 判断
        if thought:
            for letter in ["A", "B", "C"]:
                # 简单匹配："选 A"、"选A"、"A)"、"判断：A"
                for pat in [f"选 {letter})", f"选{letter})", f"{letter})", f"判断：{letter}", f"判断:{letter}"]:
                    if pat in thought:
                        result["abc_judgments"].append((letter, thought[:100]))
                        break

        # 工具调用序列
        if tool_calls_raw and tool_calls_raw != "[]":
            try:
                tcs = json.loads(tool_calls_raw) if isinstance(tool_calls_raw, str) else tool_calls_raw
                if isinstance(tcs, list):
                    for tc in tcs:
                        name = tc.get("name") if isinstance(tc, dict) else "?"
                        result["tool_sequence"].append(name)
                        if name == "plan_write":
                            result["plan_write_calls"] += 1
            except Exception:
                pass

    return result


def run_case(case):
    print(f"\n{'=' * 70}")
    print(f"[{case['id']}] {case['desc']}")
    print(f"期望: {case['expect']}")
    print(f"消息: {case['msg'][:80]}...")
    print("-" * 70)

    t0 = time.time()
    try:
        resp = call_api(case["msg"])
    except Exception as e:
        print(f"❌ 请求失败: {e}")
        return {"case": case["id"], "ok": False, "error": str(e)}

    elapsed = time.time() - t0
    sid = resp.get("ethan", {}).get("session_id", "")
    content = resp.get("choices", [{}])[0].get("message", {}).get("content", "")
    usage = resp.get("usage", {})
    tokens = usage.get("total_tokens", 0)

    print(f"⏱  耗时: {elapsed:.1f}s")
    print(f"🎫 session: {sid}")
    print(f"📊 tokens: {tokens}")
    print(f"📄 响应预览: {content[:200]}...")

    # 等 1 秒让 DB 写完
    time.sleep(1)

    msgs = query_session_messages(sid)
    analysis = analyze_session(sid, msgs)

    print("\n--- 调用过程分析 ---")
    print(f"总消息数: {analysis['total_messages']}")
    print(f"决策提示注入: {analysis['decision_prompt_count']}")
    print(f"增强上下文注入: {analysis['enhanced_context_count']}")
    print(f"plan_write 调用: {analysis['plan_write_calls']}")
    print(f"A/B/C 判断: {len(analysis['abc_judgments'])} 次")
    for letter, snippet in analysis["abc_judgments"][:3]:
        print(f"  [{letter}] {snippet}")
    print(f"工具序列 ({len(analysis['tool_sequence'])} 个):")
    print(f"  {' → '.join(analysis['tool_sequence'][:15])}")

    return {
        "case": case["id"],
        "desc": case["desc"],
        "session_id": sid,
        "elapsed": round(elapsed, 1),
        "tokens": tokens,
        "ok": True,
        **analysis,
    }


def main():
    print("Adaptive Planning v2 E2E 测试")
    print(f"API: {API}")
    print(f"DB: {DB}")
    print(f"Cases: {len(CASES)}")

    if not DB.exists():
        print(f"❌ DB 不存在: {DB}")
        return 1

    results = []
    for case in CASES:
        r = run_case(case)
        results.append(r)
        time.sleep(2)

    # 汇总
    print(f"\n{'=' * 70}")
    print("汇总")
    print("=" * 70)
    print(
        f"{'Case':<5} {'场景':<35} {'耗时':<8} {'tokens':<8} {'决策提示':<10} {'增强上下文':<12} {'plan_write':<12} {'工具数':<8}"
    )
    print("-" * 100)
    for r in results:
        if not r.get("ok"):
            print(f"{r['case']:<5} {'ERROR':<35}")
            continue
        print(
            f"{r['case']:<5} {r['desc'][:33]:<35} {r.get('elapsed', 0):<8} {r.get('tokens', 0):<8} "
            f"{r.get('decision_prompt_count', 0):<10} {r.get('enhanced_context_count', 0):<12} "
            f"{r.get('plan_write_calls', 0):<12} {len(r.get('tool_sequence', [])):<8}"
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
