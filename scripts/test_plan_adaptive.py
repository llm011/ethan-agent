#!/usr/bin/env python3
"""Adaptive Planning E2E 测试 — 调用 8989 completions API 跑 10 个 case。

每个 case 发请求 → 拿 session_id → 检查:
1. 响应是否正常返回
2. ~/.ethan/plans/<sid>.json 是否生成(plan_write 被调用的证据)
3. 响应内容里是否提到 plan/规划
"""

import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

API = "http://127.0.0.1:8989/v1/chat/completions"
KEY = "sk-ethan-78145097df1b861272f63347d501ef1c5ba9e7e51f129239"
PLANS_DIR = Path.home() / ".ethan" / "plans"

CASES = [
    # (id, 场景描述, 用户消息, 期望触发 plan)
    ("C1", "简单问候", "你好", False),
    ("C2", "简单知识查询(纯探路豁免)", "知识库里有没有关于 coze 的笔记?", False),
    ("C3", "单步文件读(纯探路豁免)", "读一下 /etc/hosts 文件内容", False),
    ("C4", "2步任务:列目录+读文件", "列一下 ~/.ethan/skills 目录有哪些技能,然后读第一个技能的 SKILL.md", True),
    ("C5", "多步任务:批量处理", "帮我把 ~/.ethan/skills 下 3 个技能的 SKILL.md 都读出来,汇总每个技能的 trigger", True),
    ("C6", "复杂任务:分析代码库", "分析 ethan/core/agent.py 的主循环结构,说说有哪些改进点", True),
    ("C7", "工具失败降级", "读取 /nonexistent/path/file.txt 看看内容", False),
    (
        "C8",
        "多文档整理(模拟 62 步会话)",
        "把 ~/.ethan/skills/obsidian/SKILL.md 和 life-manager/SKILL.md 都抓来,对比它们的 frontmatter 规范差异",
        True,
    ),
    ("C9", "简单写知识库", "往知识库存一条笔记:标题'测试',内容'adaptive planning 测试'", False),
    ("C10", "复杂多步:抓+整理+存", "把 obsidian SKILL.md 的硬规则段抓出来,整理成要点,存到知识库里", True),
]


def call_api(message: str, timeout: int = 120) -> dict:
    body = json.dumps(
        {
            "messages": [{"role": "user", "content": message}],
        }
    ).encode()
    req = urllib.request.Request(
        API,
        data=body,
        headers={
            "Authorization": f"Bearer {KEY}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


def check_plan_file(session_id: str) -> bool:
    if not session_id:
        return False
    safe_id = "".join(c if c.isalnum() or c in "-_" else "_" for c in session_id)
    return (PLANS_DIR / f"{safe_id}.json").exists()


def run_case(case_id, desc, message, expect_plan):
    print(f"\n{'=' * 60}")
    print(f"[{case_id}] {desc}")
    print(f"消息: {message[:80]}{'...' if len(message) > 80 else ''}")
    print(f"期望触发 plan: {expect_plan}")
    print("-" * 60)

    t0 = time.time()
    try:
        resp = call_api(message)
    except urllib.error.HTTPError as e:
        elapsed = time.time() - t0
        err_body = e.read().decode()[:200]
        print(f"❌ HTTP {e.code} ({elapsed:.1f}s): {err_body}")
        return {
            "case": case_id,
            "desc": desc,
            "ok": False,
            "error": f"HTTP {e.code}",
            "expect_plan": expect_plan,
            "got_plan": False,
        }
    except Exception as e:
        elapsed = time.time() - t0
        print(f"❌ 异常 ({elapsed:.1f}s): {e}")
        return {
            "case": case_id,
            "desc": desc,
            "ok": False,
            "error": str(e),
            "expect_plan": expect_plan,
            "got_plan": False,
        }

    elapsed = time.time() - t0
    session_id = resp.get("ethan", {}).get("session_id", "")
    content = resp.get("choices", [{}])[0].get("message", {}).get("content", "")
    usage = resp.get("usage", {})
    total_tokens = usage.get("total_tokens", 0)

    got_plan = check_plan_file(session_id)
    mentions_plan = "plan" in content.lower() or "规划" in content or "计划" in content

    print(f"⏱  耗时: {elapsed:.1f}s")
    print(f"🎫 session: {session_id}")
    print(f"📊 tokens: {total_tokens}")
    print(f"📝 plan 文件: {'✅ 生成' if got_plan else '❌ 未生成'}")
    print(f"💬 响应提到 plan: {'是' if mentions_plan else '否'}")
    print(f"📄 响应预览: {content[:200]}{'...' if len(content) > 200 else ''}")

    ok = True
    if expect_plan and not got_plan and not mentions_plan:
        ok = False
        print("⚠️  期望触发 plan 但既无 plan 文件也无提及")
    if not expect_plan and got_plan:
        ok = False
        print("⚠️  不期望触发 plan 但生成了 plan 文件")

    print(f"{'✅ PASS' if ok else '⚠️ CHECK'}")
    return {
        "case": case_id,
        "desc": desc,
        "ok": ok,
        "elapsed": round(elapsed, 1),
        "tokens": total_tokens,
        "session_id": session_id,
        "expect_plan": expect_plan,
        "got_plan": got_plan,
        "mentions_plan": mentions_plan,
        "content_preview": content[:150],
    }


def main():
    print("Adaptive Planning E2E 测试")
    print(f"API: {API}")
    print(f"Plans dir: {PLANS_DIR}")
    print(f"Cases: {len(CASES)}")

    PLANS_DIR.mkdir(parents=True, exist_ok=True)
    existing_plans = set(PLANS_DIR.glob("*.json"))
    print(f"已有 plan 文件: {len(existing_plans)}")

    results = []
    for case_id, desc, message, expect_plan in CASES:
        result = run_case(case_id, desc, message, expect_plan)
        results.append(result)
        time.sleep(1)

    print("\n" + "=" * 60)
    print("汇总")
    print("=" * 60)
    print(f"{'Case':<5} {'场景':<30} {'期望':<8} {'实际':<10} {'状态':<6} {'耗时':<8} {'tokens':<8}")
    print("-" * 80)
    for r in results:
        expect = "plan" if r.get("expect_plan") else "no-plan"
        got = "plan 文件" if r.get("got_plan") else ("提到" if r.get("mentions_plan") else "无")
        status = "✅" if r.get("ok") else "⚠️"
        elapsed = f"{r.get('elapsed', 0)}s"
        tokens = str(r.get("tokens", 0))
        print(f"{r['case']:<5} {r['desc'][:28]:<30} {expect:<8} {got:<10} {status:<6} {elapsed:<8} {tokens:<8}")

    pass_count = sum(1 for r in results if r.get("ok"))
    print(f"\n通过: {pass_count}/{len(results)}")

    new_plans = [p for p in PLANS_DIR.glob("*.json") if p not in existing_plans]
    if new_plans:
        print(f"\n新生成的 plan 文件 ({len(new_plans)}):")
        for p in new_plans:
            print(f"  {p.name}")

    return 0 if pass_count == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
