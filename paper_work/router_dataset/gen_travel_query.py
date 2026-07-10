#!/usr/bin/env python3
"""生成 travel-query 训练样本（jsonl）。

travel-query = 12306 火车/高铁时刻查询：车次/时间/历时/票价/余票。

子语义：
  A 班次查询    B 历时    C 票价    D 余票    E 具体班次    F 边界（区别攻略/行程）

铁律：绝不含任一 trigger 原词子串：
  12306 | 高铁 | 火车 | 动车 | 车次 | 列车 | 车票 | 时刻表 |
  北京到 | 上海到 | 广州到 | 深圳到
  以及 G/D/K 后紧跟纯数字的车次号格式（如 G1234/D101/K5）。
"""
from __future__ import annotations
import json
import random
import re
from pathlib import Path
from collections import Counter

TRIGGERS = [
    "12306", "高铁", "火车", "动车", "车次", "列车", "车票", "时刻表",
    "北京到", "上海到", "广州到", "深圳到",
]

CITIES_A = ["北京", "上海", "广州", "杭州", "成都", "西安", "武汉", "南京", "重庆", "深圳"]
CITIES_B = ["老家", "上海", "北京", "成都", "杭州", "西安", "武汉", "南京", "厦门", "长沙"]


def _has_train_number(text: str) -> bool:
    """检查是否含 G/D/K 后跟纯数字（如 G1234）的车次号。"""
    return bool(re.search(r'[GDKgdk]\d+', text))


def check_no_trigger(text: str) -> None:
    low = text.lower()
    for t in TRIGGERS:
        if t.lower() in low:
            raise AssertionError(f"含 trigger 子串 [{t}]！→ {text}")
    if _has_train_number(text):
        raise AssertionError(f"含车次号格式！→ {text}")


TEMPLATES: dict[str, list[str]] = {
    # ===== A. 班次查询（从A去B有哪些班次/几点发车）=====
    "schedule": [
        "从{a}去{b}有哪些班次可以选",
        "{a}回{b}今天还有班吗",
        "从{a}出发去{b}几点有车",
        "{a}到{b}最早的那班几点走",
        "从{a}前往{b}周末有几趟",
        "{a}去{b}今天有哪些班次",
        "帮我看下从{a}到{b}有没有直达的",
        "从{a}到{b}晚上还有班吗",
        "{a}发往{b}的班次有几趟",
        "从{a}出发去{b}的班帮我查一下",
        "帮我看下{a}到{b}今天的班次",
        "从{a}坐车去{b}有哪些选择",
        "{a}启程去{b}有没有夜间班",
        "帮我查{a}出发到{b}的时间段",
        "从{a}去{b}最晚的一班几点",
    ],
    # ===== B. 历时（坐多久/几个小时）=====
    "duration": [
        "从{a}去{b}要坐多久",
        "{a}到{b}全程需要几个小时",
        "从{a}出发到{b}大概要多长时间",
        "帮我看下{a}到{b}要跑多久",
        "{a}到{b}快的班要多久",
        "坐车从{a}到{b}最快几小时",
        "从{a}去{b}来回当天能回来吗",
        "从{a}去{b}时间最短的班要多久",
        "帮我查{a}去{b}全程时间",
        "从{a}出发{b}大概几小时后到",
    ],
    # ===== C. 票价（多少钱/软卧硬座各多少）=====
    "price": [
        "从{a}去{b}的票多少钱",
        "帮我查下{a}到{b}的票价",
        "{a}去{b}二等和一等价格差多少",
        "从{a}坐车去{b}软卧要多少钱",
        "{a}去{b}买硬座多少",
        "帮我看下{a}到{b}各个座位类型的价格",
        "从{a}去{b}商务座贵多少",
        "{a}到{b}学生有优惠吗价格是多少",
        "帮我查{a}出发去{b}坐普通座多少",
        "从{a}到{b}不同舱位各是什么价",
    ],
    # ===== D. 余票（还有没有票/抢得到吗）=====
    "availability": [
        "从{a}去{b}这天还有没有票",
        "帮我查下{a}到{b}周末有没有余票",
        "{a}到{b}现在还能买到票吗",
        "帮我看下从{a}去{b}节假日期间票好不好抢",
        "从{a}到{b}这个时间段还有票吗",
        "帮我查下{a}去{b}近期余票情况",
        "{a}去{b}下午的还有票吗",
        "帮我看下{a}到{b}还剩多少票",
        "从{a}去{b}早班还有座吗",
        "{a}出发去{b}旺季好买票吗",
    ],
    # ===== E. 具体班次时间（最早/最晚/当天来回）=====
    "specific": [
        "{a}到{b}最早的班几点出发",
        "帮我找{a}去{b}最晚的一班",
        "从{a}去{b}有没有当天来回的",
        "帮我看{a}到{b}中午有没有班",
        "{a}去{b}下午有哪些班可以赶",
        "帮我查从{a}到{b}早上七点前有没有出发的",
        "{a}去{b}傍晚有班吗",
        "帮我查{a}到{b}凌晨还有没有最后一班",
        "从{a}去{b}能不能当天出发当天回来",
        "{a}去{b}白天的班有几趟",
    ],
    # ===== F. 边界（区别 ui-card 的旅游攻略/行程规划）=====
    "boundary": [
        "我想订下周从{a}回{b}的班次，帮我看看有哪些趟",
        "帮我查一下从{a}出发去{b}的交通班次和时间",
        "从{a}去{b}有哪些坐车选项，几点能到",
        "帮我查下从{a}到{b}可以选哪趟，价格怎么样",
        "{a}到{b}当天能来回吗，帮我查下最早最晚的班",
        "帮我看下从{a}出发去{b}今天有哪些发车时间",
        "我要从{a}去{b}，帮我查下班次和票价",
        "从{a}坐车去{b}有没有直达的，大概几点能到",
        "帮我查下{a}去{b}这周末的发车情况和价格",
        "从{a}到{b}的陆路班次帮我查一下",
    ],
}

SUBCAT = {
    "schedule":    ("A", "班次查询"),
    "duration":    ("B", "历时"),
    "price":       ("C", "票价"),
    "availability":("D", "余票"),
    "specific":    ("E", "具体班次"),
    "boundary":    ("F", "边界"),
}


def expand() -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for cat, sents in TEMPLATES.items():
        for s in sents:
            if "{a}" in s or "{b}" in s:
                for a in CITIES_A:
                    for b in CITIES_B:
                        if a == b:
                            continue
                        # 避免生成 "北京到"/"上海到"/"广州到"/"深圳到"
                        exp = s.replace("{a}", a).replace("{b}", b)
                        bad = any(
                            f"{city}到" in exp
                            for city in ["北京", "上海", "广州", "深圳"]
                        )
                        if bad:
                            continue
                        out.append((exp, cat))
            else:
                out.append((s, cat))
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
            rec = {"text": text, "label": "travel-query", "subcat": f"{code}-{name}"}
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")


def main():
    base = Path(__file__).resolve().parent
    items = dedupe(expand())
    assert len(items) >= 650, f"样本不足: {len(items)} < 650"
    print(f"手写池展开+去重后：{len(items)} 条")
    train, val, test = stratified_split(items, 500, 75, 75, seed=20260711)
    write_jsonl(base / "train" / "travel-query.jsonl", train)
    write_jsonl(base / "val" / "travel-query.jsonl", val)
    write_jsonl(base / "test" / "travel-query.jsonl", test)
    print(f"train={len(train)} val={len(val)} test={len(test)}")
    for split_name, split in [("train", train), ("val", val), ("test", test)]:
        c = Counter(SUBCAT[cat][0] for _, cat in split)
        print(f"\n{split_name} 子语义分布（共 {len(split)}）：")
        for cat in SUBCAT:
            code = SUBCAT[cat][0]
            print(f"  {code}-{SUBCAT[cat][1]:<8} {c.get(code, 0):>3}")


if __name__ == "__main__":
    main()
