#!/usr/bin/env python3
"""生成 ui-card 训练样本（jsonl）。

ui-card = 用 ui_card 工具生成结构化 UI 卡片（对比/排行/统计/时间轴/清单/进度）。

子语义：
  A 对比展示    B 排名展示    C 数据统计    D 时间顺序可视化
  E 要点列举    F 进度/状态   G 边界（区别查数据本身）

铁律：绝不含任一 trigger 原词子串：
  卡片 | 对比卡 | 状态卡 | 统计卡 | 时间轴 | 时间线 | timeline |
  旅游攻略 | 行程 | 攻略 | 进度 | 排行 | 榜单 | 清单 | 列一下
"""
from __future__ import annotations
import json
import random
from pathlib import Path
from collections import Counter

TRIGGERS = [
    "卡片", "对比卡", "状态卡", "统计卡", "时间轴", "时间线", "timeline",
    "旅游攻略", "行程", "攻略", "进度", "排行", "榜单", "清单", "列一下",
]


def check_no_trigger(text: str) -> None:
    low = text.lower()
    for t in TRIGGERS:
        if t.lower() in low:
            raise AssertionError(f"含 trigger 子串 [{t}]！→ {text}")


POOL: dict[str, list[str]] = {
    # ===== A. 对比展示 =====
    "compare": [
        "把这几个方案的优缺点做成一张对比图",
        "帮我把这两个产品并排对比一下做成展示",
        "这几个选项帮我整理成对比形式给我看",
        "把这三个方案的差异做成可视化的对比",
        "帮我把这几个选择的区别做成一目了然的图",
        "把这些工具的特性并排展示出来",
        "帮我做一个这几个配置项的对比图",
        "这几个产品的参数对比帮我可视化一下",
        "把这两种方案的利弊做成对比样式展示",
        "帮我把这些选项的异同整理成图表形式",
        "这几个技术方案帮我做个并排比较展示",
        "把这些候选项的关键指标做成对比样式",
        "帮我整理成可视化的横向对比给我看",
        "这三个版本的功能差异帮我做个对比展示",
        "把这几款产品的核心差异可视化出来",
        "帮我把这几个报价的差别做成对比图",
        "这几个策略的优劣帮我做成直观的对比",
        "把这几个人选的背景做成并排对比展示",
        "帮我整理几个方向的差异做成对比看",
        "这两种做法的区别帮我做成对比样式",
    ],
    # ===== B. 排名展示 =====
    "rank": [
        "帮我把这些按评分排个名次做成展示图",
        "把这几个按热度排个先后做成可视化",
        "帮我把这些候选人按综合分数排名展示",
        "这些选项按重要程度排个先后给我看",
        "帮我做一个这几个城市按某指标的排名展示",
        "把这几款产品按性价比排名可视化",
        "帮我把这些功能按优先级排个先后展示",
        "这几个方案按可行性高低排名给我看",
        "帮我把这些建议按实用程度排个名次",
        "把这些候选方案从好到差排一下做成展示",
        "帮我给这几个选项做一个优先级排名图",
        "这几家公司按规模做个高低排序展示",
        "帮我把这些任务按紧急程度排名可视化",
        "把这些城市按某指标从高到低展示出来",
        "帮我做一个评测结果的排名展示",
        "这些功能模块按使用频率排个名次",
        "帮我把这几个竞品按某维度排名展示",
        "这些建议按重要性帮我做个排序展示",
        "帮我把这几个选手的得分做成排名图",
        "把这几个策略从最推荐到最不推荐排列展示",
    ],
    # ===== C. 数据统计展示 =====
    "stat": [
        "把这几个数字帮我做成数据展示图",
        "帮我把这些指标整理成统计展示",
        "这几个数据帮我做成直观的图表展示",
        "把这些关键数字做成一个数据面板",
        "帮我把这几项指标做成可视化展示",
        "这些统计数字帮我整理成图表样式",
        "把这几个核心指标做成展示看板",
        "帮我把这些数据做成一目了然的展示",
        "这几个数量帮我做成数字展示图",
        "把这些百分比做成可视化的比例展示",
        "帮我把这几项数字整理成视觉化展示",
        "这几个维度的数据帮我做成图表",
        "把这些统计结果做成直观的展示",
        "帮我整理一下这些数字做成展示样式",
        "这几项数据帮我做成面板展示",
        "把这些指标汇总做成可视化展示图",
        "帮我把这几个比率做成比例展示",
        "这些数据点帮我做成一目了然的图",
        "把这几个核心数字用图表方式展示",
        "帮我整理这些统计数字做成展示图",
    ],
    # ===== D. 时间顺序可视化（避开时间轴/时间线/timeline）=====
    "timeline_view": [
        "把这几件事按发生顺序做成可视化",
        "帮我把这些事件的先后顺序做成图示",
        "这个事情的发展脉络帮我可视化出来",
        "把这些步骤按时间顺序做成流程展示",
        "帮我把这几个节点的顺序做成可视化图",
        "这件事的发展过程帮我做成顺序展示",
        "把这些关键节点按顺序排列可视化",
        "帮我把事件的先后关系做成图表展示",
        "这个项目的里程碑帮我做成顺序可视化",
        "把这些阶段按先后做成流程样式展示",
        "帮我把这几个事件的发展顺序展示出来",
        "这些历史事件按顺序帮我做成可视化",
        "把项目各阶段按时间先后做成图示",
        "帮我把这几个步骤的顺序做成流程图",
        "这个事情的来龙去脉帮我做成顺序展示",
        "把这几个重要节点的时间顺序可视化",
        "帮我把这个过程的各个阶段做成顺序图",
        "这几件事的发展脉络帮我整理成图表",
        "把这些重要时间节点按序展示出来",
        "帮我把事情发展的各个阶段做成图示",
    ],
    # ===== E. 要点列举展示（避开清单/列一下）=====
    "list_view": [
        "把这些要点帮我做成结构化展示",
        "帮我把这几条信息整理成图表样式",
        "这些内容帮我做成有条理的可视化展示",
        "把这些要素做成结构清晰的展示图",
        "帮我把这几个点整理成可视化样式",
        "这些选项帮我做成结构化的展示",
        "把这几条建议做成一目了然的图示",
        "帮我把这些内容整理成展示样式",
        "这几个方面帮我做成有结构的可视化",
        "把这些要点整合成图表样式展示出来",
        "帮我把这几条内容做成展示图",
        "这几项功能帮我整理成结构化展示",
        "把这些信息做成整洁的可视化展示",
        "帮我把这几项内容做成有层次的展示",
        "这些细节帮我整理成图表样式",
        "把这几个维度的内容做成结构化展示",
        "帮我把这些信息点做成可视化样式",
        "这些要素帮我做成一目了然的展示",
        "把这几条内容整理成展示图形式",
        "帮我把这些项目做成结构清晰的图表",
    ],
    # ===== F. 进度/状态展示（避开进度/状态卡）=====
    "progress_view": [
        "把项目各阶段的完成情况做成展示",
        "帮我把这几项任务的完成度可视化",
        "这几个目标的达成率帮我做成展示图",
        "把这些工作的完成情况做成可视化",
        "帮我整理一下各项任务的推进情况展示",
        "这几件事的当前情况帮我做成展示",
        "把这些项目的最新情况做成一目了然的展示",
        "帮我把这几项工作的当前阶段可视化",
        "这些任务各到哪一步了帮我做成展示图",
        "把这几个事项的推进情况整理成展示",
        "帮我把这几个目标的完成比例可视化",
        "这几项工作的完成度帮我做成可视化展示",
        "把各个模块的完成情况整理成图表展示",
        "帮我把这几件事的当前状况做成展示图",
        "这几个阶段各完成了多少帮我可视化",
        "把这些里程碑的达成情况做成展示",
        "帮我把各项任务的推进情况整理成图表",
        "这些指标的完成情况帮我做成可视化",
        "把这几个目标达成了多少做成展示图",
        "帮我把各模块的推进情况可视化展示",
    ],
    # ===== G. 边界（区别「查数据」vs「展示数据」）=====
    "boundary": [
        "这几个方案的优缺点帮我摆成一张对比图给我看",
        "我有这些数字了，帮我做成一张好看的展示",
        "把我列的这几项内容做成结构化的图表展示",
        "这些信息我都有了，帮我整理成可视化的格式",
        "我列的这几个选项，帮我做成对比样式展示",
        "这几个数据点我已经准备好了，做成图表展示",
        "帮我把这段文字里的要点做成结构化展示图",
        "这几个方向我都整理好了，做成可视化给我看",
        "把我提供的这些信息做成整洁的图表展示",
        "这些内容都有了，帮我做成好看的可视化样式",
        "我这里有几个选项，帮我做成并排对比的展示",
        "把这几条我整理好的内容做成展示图形式",
        "帮我把这段描述转成结构化的可视化展示",
        "这几项我都列好了，做成图表样式展示给我",
        "把我给你的这些信息做成有条理的展示图",
    ],
}

SUBCAT = {
    "compare":       ("A", "对比展示"),
    "rank":          ("B", "排名展示"),
    "stat":          ("C", "数据统计"),
    "timeline_view": ("D", "时间顺序"),
    "list_view":     ("E", "要点列举"),
    "progress_view": ("F", "进度状态"),
    "boundary":      ("G", "边界"),
}


def expand() -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    mood = set("吧呢嘛啊吗了呀哦呐")
    for cat, sents in POOL.items():
        for s in sents:
            out.append((s, cat))
            tail = s.rstrip()[-1] if s.strip() else ""
            if tail and tail not in mood and tail not in "？。！，；":
                for suf in ["呢", "啊", "吗", "？"]:
                    out.append((s + suf, cat))
    return out


def dedupe(items):
    seen, out = set(), []
    for text, cat in items:
        t = text.strip()
        if not t or t in seen:
            continue
        check_no_trigger(t)
        seen.add(t)
        out.append((t, cat))
    return out


def stratified_split(items, train_n, val_n, test_n, seed):
    rng = random.Random(seed)
    by_cat = {}
    for text, cat in items:
        by_cat.setdefault(cat, []).append((text, cat))
    for cat in by_cat:
        rng.shuffle(by_cat[cat])
    train, val, test = [], [], []
    total = len(items)
    for cat, texts in by_cat.items():
        n = len(texts)
        cval = min(max(1, round(n * val_n / total)), n // 3)
        ctest = min(max(1, round(n * test_n / total)), n // 3)
        i = 0
        test.extend(texts[i:i + ctest]); i += ctest
        val.extend(texts[i:i + cval]); i += cval
        train.extend(texts[i:])
    rng.shuffle(train); rng.shuffle(val); rng.shuffle(test)
    used = set(t for t, _ in val) | set(t for t, _ in test)
    pool_extra = [it for it in train if it[0] not in used]
    placed = set()
    for need, bucket in [(val_n, val), (test_n, test)]:
        i = 0
        while len(bucket) < need and i < len(pool_extra):
            if pool_extra[i][0] not in placed:
                bucket.append(pool_extra[i]); placed.add(pool_extra[i][0])
            i += 1
    used = set(t for t, _ in val) | set(t for t, _ in test)
    train = [it for it in train if it[0] not in used][:train_n]
    return train, val, test


def write_jsonl(path, items):
    with open(path, "w", encoding="utf-8") as fh:
        for text, cat in items:
            code, name = SUBCAT[cat]
            rec = {"text": text, "label": "ui-card", "subcat": f"{code}-{name}"}
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")


def main():
    base = Path(__file__).resolve().parent
    items = dedupe(expand())
    assert len(items) >= 650, f"样本不足: {len(items)} < 650"
    print(f"手写池展开+去重后：{len(items)} 条")
    train, val, test = stratified_split(items, 650, 75, 75, seed=20260711)
    write_jsonl(base / "train" / "ui-card.jsonl", train)
    write_jsonl(base / "val" / "ui-card.jsonl", val)
    write_jsonl(base / "test" / "ui-card.jsonl", test)
    print(f"train={len(train)} val={len(val)} test={len(test)}")
    for split_name, split in [("train", train), ("val", val), ("test", test)]:
        c = Counter(SUBCAT[cat][0] for _, cat in split)
        print(f"\n{split_name} 子语义分布（共 {len(split)}）：")
        for cat in SUBCAT:
            code = SUBCAT[cat][0]
            print(f"  {code}-{SUBCAT[cat][1]:<8} {c.get(code, 0):>3}")


if __name__ == "__main__":
    main()
