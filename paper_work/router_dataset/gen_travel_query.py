#!/usr/bin/env python3
"""生成 travel-query 训练样本（jsonl）。

travel-query = 12306 火车/高铁时刻查询：车次/时间/历时/票价/余票。

子语义：
  A 班次查询    B 历时    C 票价    D 余票    E 具体班次    F 边界（区别攻略/行程）

★ 三池独立（防近邻泄漏，这是本文件与旧版最大区别）：
  POOL_TRAIN：覆盖广、多变体、城市全展开，主训练用。
  POOL_VAL  ：换一批说法（中等难度），不与 train 的模板骨架重叠。
  POOL_TEST ：最口语、最贴近真实用户——刻意加背景/上下文/省略/隐式意图，
              句子长短不一，部分故意写长。绝不与 train 共用模板。
  三池分别手写，split() 不再从同一池切片，从根上消除「同模板换实体」的泄漏。

铁律：三池所有样本绝不含任一 trigger 原词子串：
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

# train 用全量城市（覆盖广）；val/test 用不同城市子集，进一步降低表层重合
CITIES_TRAIN_A = ["北京", "上海", "广州", "杭州", "成都", "西安", "武汉", "南京", "重庆", "深圳"]
CITIES_TRAIN_B = ["老家", "上海", "北京", "成都", "杭州", "西安", "武汉", "南京", "厦门", "长沙"]
CITIES_VAL_A = ["天津", "苏州", "青岛", "郑州", "长沙", "合肥"]
CITIES_VAL_B = ["宁波", "无锡", "济南", "昆明", "贵阳", "南昌"]
CITIES_TEST_A = ["珠海", "佛山", "常州", "洛阳", "烟台", "泉州"]
CITIES_TEST_B = ["徐州", "绍兴", "潍坊", "湖州", "岳阳", "赣州"]


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


# ===================== POOL_TRAIN：覆盖广、多变体 =====================
POOL_TRAIN: dict[str, list[str]] = {
    # A. 班次查询
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
    # B. 历时
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
    # C. 票价
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
    # D. 余票
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
    # E. 具体班次
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
    # F. 边界（区别 ui-card 的旅游攻略/行程规划）
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

# ===================== POOL_VAL：换说法、中等难度 =====================
POOL_VAL: dict[str, list[str]] = {
    "schedule": [
        "{a}往{b}方向今儿个还发不发",
        "看看{a}奔{b}都有几个点出发",
        "{a}到{b}这一路都有哪些趟次",
        "想知道{a}去{b}白天晚上分别有几班",
        "{a}至{b}的发班情况帮我瞅瞅",
    ],
    "duration": [
        "{a}奔{b}路上得耗多长",
        "{a}至{b}满打满算几个钟头",
        "{a}到{b}紧赶慢赶最少几小时",
        "想知道{a}去{b}路上时间长不长",
    ],
    "price": [
        "{a}奔{b}一张票大概啥价位",
        "{a}至{b}卧铺和坐票差价多大",
        "{a}到{b}最便宜的座位得掏多少",
        "想问{a}去{b}带娃半价大概多少",
    ],
    "availability": [
        "{a}奔{b}这两天位子紧不紧",
        "{a}至{b}临出发还抢得着不",
        "{a}到{b}节前是不是根本买不着",
        "想知道{a}去{b}还剩几个空座",
    ],
    "specific": [
        "{a}奔{b}天不亮那趟几点开",
        "{a}至{b}压轴那班几点收车",
        "{a}到{b}晌午前后有发的没",
        "想赶{a}去{b}下班后那趟，几点",
    ],
    "boundary": [
        "打算{a}回{b}，顺带看看有几趟、几点、多少钱",
        "{a}奔{b}想当天打个来回，早晚班都给我列列",
        "帮瞅瞅{a}至{b}陆路怎么走，趟次和价位都要",
    ],
}

# ===================== POOL_TEST：最口语、含背景/省略/隐式意图，部分故意写长 =====================
POOL_TEST: dict[str, list[str]] = {
    "schedule": [
        # 长句：带背景+隐式意图（其实是问班次）
        "下周要去{b}出差，我人在{a}，想早点看看那天从这边过去都有哪些点能走，方便安排会议",
        # 省略主语、口语
        "诶从{a}那边过去{b}，白天还有得坐没",
        "临时决定回{b}一趟，我这{a}这会儿出发的话赶得上哪班",
        "{a}这头想溜达去{b}，晚上那种夜里走的有安排没",
        "老板让我明天赶到{b}，我在{a}，你帮我扒拉扒拉都有几个点能出发呗",
    ],
    "duration": [
        "带着老人从{a}挪到{b}，我怕路上太折腾，想知道满打满算得在路上待多久",
        "{a}过去{b}，我想当天办完事就回，这一趟单程到底得耗几个钟头啊",
        "从{a}这边坐过去{b}，快的那种和慢的那种差多少时间",
        "{a}到{b}我寻思路上能不能睡一觉就到，大概几个小时",
    ],
    "price": [
        "预算有点紧，从{a}回一趟{b}最省的坐法大概得花多少",
        "{a}过去{b}，我想躺着睡过去，那种带铺的贵不贵，大概啥价",
        "一家三口从{a}去{b}，娃能半价的话我们仨总共大概多少钱",
        "{a}到{b}我图舒服想坐好点的，最高档那种比普通的贵出多少",
    ],
    "availability": [
        "过两天要从{a}赶回{b}奔丧，急，你帮我看看临时还抢不抢得到位子",
        "{a}去{b}赶上放假那几天，我这种手慢的还有戏没",
        "{a}这边过去{b}，下午那会儿走的还剩座没，别到时候只能站着",
        "想订{a}回{b}的，可这两天位子是不是早被抢光了",
    ],
    "specific": [
        "{a}去{b}，我想天没亮就出发好赶上早会，最早那趟几点开门走",
        "在{a}忙到挺晚，收工后想赶回{b}，最后一班大概几点，别错过了",
        "{a}过去{b}，我中午才能腾出手，那前后有没有能坐的",
        "{a}到{b}要是想当天去当天回，早晚这两头分别得几点",
    ],
    "boundary": [
        "打算周末从{a}回{b}看爸妈，你帮我合计合计有哪几趟、几点开、大概花多少，我好定",
        "{a}去{b}这一路我啥都不懂，你把能坐的、几点到、贵不贵一次给我说清楚呗",
        "临时要从{a}窜去{b}办点事，最好当天来回，你把早晚班和价钱都给我扒出来",
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


def _bad_city_trigger(exp: str) -> bool:
    """避免生成 "北京到"/"上海到"/"广州到"/"深圳到" 触发词。"""
    return any(f"{city}到" in exp for city in ["北京", "上海", "广州", "深圳"])


def expand_pool(pool, cities_a, cities_b) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for cat, sents in pool.items():
        for s in sents:
            if "{a}" in s or "{b}" in s:
                for a in cities_a:
                    for b in cities_b:
                        if a == b:
                            continue
                        exp = s.replace("{a}", a).replace("{b}", b)
                        if _bad_city_trigger(exp):
                            continue
                        out.append((exp, cat))
            else:
                out.append((s, cat))
    return out


def dedupe(items, seen=None):
    """去重 + trigger 校验；seen 用于跨池去重（test/val 优先占位，train 让路）。"""
    if seen is None:
        seen = set()
    out = []
    for text, cat in items:
        t = text.strip()
        if not t or t in seen:
            continue
        check_no_trigger(t)
        seen.add(t)
        out.append((t, cat))
    return out


def cap_per_split(items, target_n, seed):
    """打散后截断到目标量，尽量保持子语义均衡。"""
    rng = random.Random(seed)
    by_cat = {}
    for text, cat in items:
        by_cat.setdefault(cat, []).append((text, cat))
    for cat in by_cat:
        rng.shuffle(by_cat[cat])
    if len(items) <= target_n:
        out = list(items); rng.shuffle(out); return out
    # 按类配额轮转取，避免某类被砍光
    out, cats = [], list(by_cat.keys())
    idx = {c: 0 for c in cats}
    while len(out) < target_n:
        progressed = False
        for c in cats:
            if idx[c] < len(by_cat[c]) and len(out) < target_n:
                out.append(by_cat[c][idx[c]]); idx[c] += 1; progressed = True
        if not progressed:
            break
    rng.shuffle(out)
    return out


def write_jsonl(path, items):
    with open(path, "w", encoding="utf-8") as fh:
        for text, cat in items:
            code, name = SUBCAT[cat]
            rec = {"text": text, "label": "travel-query", "subcat": f"{code}-{name}"}
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")


def main():
    base = Path(__file__).resolve().parent
    # 先建 test/val（优先占位），再建 train（让路，避免任何跨池重复）
    seen: set = set()
    test_raw = dedupe(expand_pool(POOL_TEST, CITIES_TEST_A, CITIES_TEST_B), seen)
    val_raw = dedupe(expand_pool(POOL_VAL, CITIES_VAL_A, CITIES_VAL_B), seen)
    train_raw = dedupe(expand_pool(POOL_TRAIN, CITIES_TRAIN_A, CITIES_TRAIN_B), seen)

    test = cap_per_split(test_raw, 75, seed=20260711)
    val = cap_per_split(val_raw, 75, seed=20260712)
    train = cap_per_split(train_raw, 500, seed=20260713)

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
