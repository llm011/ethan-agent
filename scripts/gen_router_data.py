"""为内置 skill 批量生成路由分类训练数据（query → skill 标签）。

输出 JSONL，每行 {"query": "...", "answer": "<skill-name>"}，用于训练/微调
embedding 语义路由器。用法：
    uv run python scripts/gen_router_data.py            # 全量（每 skill 500 条）
    uv run python scripts/gen_router_data.py --per 50   # 调试：每 skill 50 条
    uv run python scripts/gen_router_data.py --skills lark-im,ui-card

特性：调廉价模型 lite_model 批量生成、并发、去重、断点续跑（重入只补缺口）。
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
from pathlib import Path

from ethan.core.config import get_config
from ethan.memory.consolidator import get_lite_model
from ethan.providers.base import Message
from ethan.providers.manager import create_provider
from ethan.skills.loader import load_skill_from_dir

# 系统内置技能目录（仓库自带，非用户已安装的 ~/.ethan/skills/）
BUILTIN_SKILLS_DIR = Path(__file__).resolve().parent.parent / "ethan" / "defaults" / "skills"

OUT_DIR = Path.home() / "Downloads"
OUT_FILE = OUT_DIR / "router_train.jsonl"


def load_builtin_skills() -> list:
    """只加载仓库内置技能（ethan/defaults/skills/<name>/SKILL.md）。"""
    out = []
    for entry in sorted(BUILTIN_SKILLS_DIR.iterdir()):
        if entry.is_dir() and not entry.name.endswith("-references"):
            s = load_skill_from_dir(entry)
            if s:
                out.append(s)
    return out

BATCH = 25            # 每次 API 调用产出的 query 数
DEFAULT_TARGET = 500  # 每个 skill 目标条数
CONCURRENCY = 6       # 并发 API 调用上限
MAX_RETRY = 3

# 轮换的「角度」提示，逼出多样性（口吻 / 场景 / 句式）
_ANGLES = [
    "日常口语、随口一说的短句",
    "正式、完整描述需求的长句",
    "带具体实体（人名/文件名/项目名/群名等占位）的真实场景",
    "省略主语、口语化、可能有错别字或中英混排",
    "疑问句式（“能不能…”“怎么…”“帮我看看…”）",
    "祈使句式（“帮我…”“给我…”“去…”）",
]

_SYSTEM = "你是训练数据生成助手。只输出一个 JSON 数组，不要任何解释、不要 markdown 代码块。"


def _prompt(skill, angle: str, avoid: list[str]) -> str:
    triggers = "、".join(skill.trigger[:20]) if skill.trigger else "（无）"
    avoid_block = ""
    if avoid:
        sample = "\n".join(f"- {q}" for q in avoid[-30:])
        avoid_block = f"\n\n已生成过下面这些，请勿重复、换不同说法：\n{sample}"
    return (
        f"技能名：{skill.name}\n"
        f"技能用途：{skill.description.strip()[:400]}\n"
        f"参考触发词（仅供理解语义，**生成时务必避开这些字面词**）：{triggers}\n\n"
        f"请生成 {BATCH} 条「中文为主、可少量中英混排」的用户输入，这些输入都应当触发上述技能。\n"
        f"风格要求：{angle}。\n"
        "关键约束：\n"
        "1. 尽量不要直接包含上面的参考触发词原文，用自然的同义改写、口语说法，覆盖关键词匹配漏掉的表达。\n"
        "2. 每条都是用户会真实发给 AI 助手的话，长短不一，不要编号、不要引号包裹。\n"
        "3. 彼此之间表达方式要有差异，不要雷同。\n"
        f"{avoid_block}\n\n"
        '只输出 JSON 数组，形如 ["query1", "query2", ...]。'
    )


def _parse_array(text: str) -> list[str]:
    """从模型输出里抽出字符串数组，容忍 markdown 包裹/多余文本。"""
    s = text.strip()
    s = re.sub(r"^```(?:json)?\s*|\s*```$", "", s, flags=re.MULTILINE).strip()
    start, end = s.find("["), s.rfind("]")
    if start == -1 or end == -1 or end < start:
        return []
    try:
        arr = json.loads(s[start : end + 1])
    except Exception:
        return []
    return [str(x).strip() for x in arr if isinstance(x, str) and str(x).strip()]


def _norm(q: str) -> str:
    return re.sub(r"\s+", "", q.lower())


def _load_existing() -> dict[str, set[str]]:
    """读已有 JSONL，返回 {skill: {归一化 query}}，支持断点续跑。"""
    seen: dict[str, set[str]] = {}
    if not OUT_FILE.exists():
        return seen
    for line in OUT_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
            seen.setdefault(obj["answer"], set()).add(_norm(obj["query"]))
        except Exception:
            continue
    return seen


async def _gen_one_skill(skill, target: int, provider, sem, write_lock, existing_norm: set[str]):
    """为单个 skill 补到 target 条；边生成边追加写入。"""
    have = set(existing_norm)
    angle_i = 0
    miss_streak = 0
    target_new = target - len(existing_norm)
    if target_new <= 0:
        return 0
    new_count = 0
    while new_count < target_new and miss_streak < 8:
        angle = _ANGLES[angle_i % len(_ANGLES)]
        angle_i += 1
        prompt = _prompt(skill, angle, list(have))
        text = None
        async with sem:
            for attempt in range(MAX_RETRY):
                try:
                    resp = await provider.chat([Message(role="user", content=prompt)], system=_SYSTEM)
                    text = resp.content
                    break
                except Exception as e:
                    if attempt == MAX_RETRY - 1:
                        print(f"  [{skill.name}] API 失败（已重试 {MAX_RETRY} 次）：{e}")
                    else:
                        await asyncio.sleep(1.5 * (attempt + 1))
        if not text:
            miss_streak += 1
            continue
        rows = []
        for q in _parse_array(text):
            n = _norm(q)
            if not n or n in have:
                continue
            have.add(n)
            rows.append({"query": q, "answer": skill.name})
            new_count += 1
            if new_count >= target_new:
                break
        if not rows:
            miss_streak += 1
        else:
            miss_streak = 0
            async with write_lock:
                with OUT_FILE.open("a", encoding="utf-8") as f:
                    for r in rows:
                        f.write(json.dumps(r, ensure_ascii=False) + "\n")
            print(f"  [{skill.name}] +{len(rows)}  → {len(existing_norm) + new_count}/{target}")
    return new_count


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--per", type=int, default=DEFAULT_TARGET, help="每个 skill 目标条数")
    ap.add_argument("--skills", type=str, default="", help="逗号分隔，仅生成这些 skill；留空=全部")
    args = ap.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    cfg = get_config()
    model = get_lite_model(cfg.defaults.model)
    provider = create_provider(model)
    print(f"使用模型：{model}")

    skills = load_builtin_skills()
    if args.skills:
        want = {s.strip() for s in args.skills.split(",") if s.strip()}
        skills = [s for s in skills if s.name in want]
    print(f"目标 skill：{[s.name for s in skills]}  每个 {args.per} 条")

    existing = _load_existing()
    sem = asyncio.Semaphore(CONCURRENCY)
    write_lock = asyncio.Lock()

    tasks = [
        _gen_one_skill(s, args.per, provider, sem, write_lock, existing.get(s.name, set()))
        for s in skills
    ]
    results = await asyncio.gather(*tasks)
    total_new = sum(results)

    # 汇总
    final = _load_existing()
    print("\n=== 完成 ===")
    for s in skills:
        print(f"  {s.name}: {len(final.get(s.name, set()))}")
    print(f"本次新增 {total_new} 条，输出：{OUT_FILE}")


if __name__ == "__main__":
    asyncio.run(main())
