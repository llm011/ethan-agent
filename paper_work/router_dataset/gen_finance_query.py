#!/usr/bin/env python3
"""生成 finance-query 训练样本（jsonl）。

finance-query = 股票/指数/基金实时行情、K线历史、估值、财务三表、技术指标、板块排名。
覆盖 A股/港股/美股，直接 curl 免费 API。

子语义：
  A 实时价格/涨跌    B 历史走势/K线    C 估值/贵便宜
  D 财务数据         E 技术信号        F 热门行业/排名
  G 场内基金/指数    H 基金净值        I 多市场

铁律：绝不含任一 trigger 原词子串：
  A股 | 股票 | 上证 | 深证 | 指数 | 行情 | 大盘 | 涨跌 | 收盘 | 开盘 | 基金净值 |
  港股 | 美股 | K线 | PE | PB | 估值 | 市值 | 财报 | ROE | 市盈率 | 板块 | 涨幅榜 |
  茅台 | 腾讯 | 苹果 | AAPL | TSLA | 利润表 | 资产负债 | 现金流 | EPS | 技术指标 |
  MA | RSI | MACD | KDJ | 均线 | 成交量 | ETF
"""
from __future__ import annotations
import json
import random
from pathlib import Path
from collections import Counter

TRIGGERS = [
    "A股", "股票", "上证", "深证", "指数", "行情", "大盘", "涨跌", "收盘", "开盘",
    "基金净值", "港股", "美股", "K线", "PE", "PB", "估值", "市值", "财报", "ROE",
    "市盈率", "板块", "涨幅榜", "茅台", "腾讯", "苹果", "AAPL", "TSLA",
    "利润表", "资产负债", "现金流", "EPS", "技术指标", "MA", "RSI", "MACD",
    "KDJ", "均线", "成交量", "ETF",
]

# 个股泛指词（绕开具体公司名和"股票"原词）
T = [
    "这家公司", "这只票", "这个标的", "这支", "那家上市公司",
    "我持有的那个", "这家白酒龙头", "那家新能源车企", "那家互联网大厂",
    "这家半导体公司",
]

POOL: dict[str, list[str]] = {
    # ===== A. 实时价格/涨跌 =====
    "price": [
        "{t}现在多少钱一股",
        "{t}今天是涨还是跌",
        "{t}最新价多少",
        "帮我看下{t}盘中怎么样",
        "{t}今天幅度大吗",
        "{t}刚才最高涨到多少",
        "帮我查下{t}当前报价",
        "{t}今天有没有异动",
        "现在市场上{t}是什么价格",
        "{t}今天开得怎么样",
        "帮我看下{t}实时价",
        "{t}最新成交在哪个价位",
        "帮我查下{t}今天的价格",
        "{t}此刻是多少",
        "看下{t}现在的报价",
        "{t}盘中最低跌到多少了",
        "{t}现在比昨天贵还是便宜",
        "帮我看看{t}今天收益怎么样",
        "{t}今天下午怎么走的",
        "给我查下{t}当前价格",
    ],
    # ===== B. 历史走势/K线 =====
    "kline": [
        "{t}最近一个月的走势怎么样",
        "帮我看下{t}过去一年的价格曲线",
        "{t}历史上最高价是多少",
        "{t}最近半年涨了多少",
        "帮我查下{t}近三个月的波动",
        "{t}今年以来表现怎么样",
        "{t}历史走势帮我看一下",
        "帮我查{t}过去五年的价格变化",
        "{t}在什么时候跌得最惨",
        "{t}最近的高点在哪里",
        "帮我看看{t}的价格趋势",
        "{t}上周涨了多少",
        "查一下{t}近两周的走势",
        "{t}最近的低点是什么时候",
        "帮我看下{t}从年初到现在的表现",
        "{t}历史数据帮我拉一份",
        "{t}上个月整体是涨还是跌",
        "帮我看下{t}最近的走势变化",
        "{t}近期波动大吗",
        "查下{t}近一个季度的数据",
    ],
    # ===== C. 估值/贵不贵 =====
    "valuation": [
        "{t}现在贵不贵",
        "帮我看下{t}值不值这个价",
        "{t}市场给它估了多少",
        "{t}现在处于历史高位吗",
        "帮我判断下{t}是贵还是便宜",
        "{t}和同行相比贵吗",
        "{t}目前的价格合理吗",
        "帮我看看{t}定价是否合理",
        "{t}现在是高估还是低估",
        "{t}比起同类算贵吗",
        "帮我评估{t}现在的价格",
        "{t}还有上涨空间吗",
        "{t}是否已经泡沫化",
        "帮我看下{t}的价格水位",
        "{t}目前处于高位还是低位",
        "{t}和历史均值比怎么样",
        "帮我判断一下{t}现在的性价比",
        "{t}算不算在安全边际之内",
        "帮我看看{t}值不值得买",
        "{t}市场怎么给它定价的",
    ],
    # ===== D. 财务数据 =====
    "financials": [
        "{t}一年赚了多少钱",
        "帮我查下{t}的营收情况",
        "{t}去年的利润是多少",
        "{t}负债高不高",
        "帮我看下{t}的经营状况",
        "{t}每股挣了多少",
        "{t}赚不赚钱",
        "帮我查下{t}的盈利能力",
        "{t}手里有多少现金",
        "{t}债务情况怎么样",
        "帮我看看{t}的财务健康度",
        "{t}上季度赚了多少",
        "查下{t}最新的业绩",
        "{t}的毛利率怎么样",
        "帮我看下{t}资产情况",
        "{t}有没有净亏损",
        "{t}盈利增长了多少",
        "帮我看下{t}收入规模",
        "{t}的净利润率是多少",
        "帮我查下{t}最近一期的报告",
    ],
    # ===== E. 技术信号（避开 MA/RSI/MACD/KDJ/均线/成交量）=====
    "indicator": [
        "{t}现在是超买还是超卖状态",
        "帮我看下{t}短期和长期价格平均值的位置",
        "{t}的买卖力量现在哪边强",
        "帮我判断{t}目前的技术形态",
        "{t}短期均值和长期均值交叉了吗",
        "{t}量能最近放大了吗",
        "帮我看下{t}的技术走势",
        "{t}价格动能怎么样",
        "帮我判断{t}是否处于上升通道",
        "{t}近期有没有出现转折信号",
        "帮我看看{t}的趋势强弱",
        "{t}最近交易量有变化吗",
        "帮我分析{t}目前的走势特征",
        "{t}是否到了支撑位附近",
        "帮我判断{t}当前的强弱信号",
        "{t}短期内动能强吗",
        "帮我看看{t}的压力位在哪",
        "{t}有反弹信号吗",
        "帮我看看{t}的市场情绪指标",
        "{t}是否处于超跌区域",
    ],
    # ===== F. 热门行业/排名（避开板块/涨幅榜）=====
    "ranking": [
        "今天哪些行业涨得最猛",
        "哪个赛道最近最热",
        "今天涨幅最大的是哪类",
        "帮我看看最近领涨的是哪个方向",
        "今天哪些方向跌得最惨",
        "哪类企业最近表现最好",
        "今天哪个方向资金流入多",
        "帮我看下最近最强势的行业",
        "今天什么领域涨得比较好",
        "哪些行业今天在拉升",
        "帮我看最近热门的方向",
        "今天哪些行业跌得比较多",
        "帮我看下资金今天偏爱哪个方向",
        "最近什么方向是主线",
        "今天大部分企业是涨还是跌",
        "帮我看看今天强势的一批",
        "哪些细分领域今天表现不错",
        "今天什么题材在活跃",
        "帮我看下今天的热门赛道",
        "最近哪些行业持续走强",
    ],
    # ===== G. 场内基金/指数（避开 ETF/指数/成交量）=====
    "instrument": [
        "这只跟踪一篮子的场内产品今天怎么样",
        "帮我看这个追踪科技的场内基金表现",
        "这个被动跟踪的产品最新价多少",
        "帮我查下这个宽基产品今天的溢价",
        "这类跟踪宽幅市场的产品近期怎样",
        "帮我看下这个行业主题的场内产品",
        "这个复制某行业的基金最新净值是多少",
        "帮我看这个追踪债券的产品走势",
        "这只跟踪沪深宽指的产品今天怎么走",
        "帮我查下主要的宽基产品今日表现",
        "这类被动复制的产品溢价率多少",
        "帮我查这个追踪能源的场内产品",
        "这个跟踪消费的被动产品今天涨了吗",
        "帮我看下宽幅被动产品今天的情况",
        "这个黄金相关的场内品种今天多少",
        "帮我查一下医药主题场内产品近期走势",
    ],
    # ===== H. 基金净值（避开"基金净值"连用）=====
    "fund": [
        "我买的那个基金今天涨了吗",
        "帮我查下那个主动管理的基金今天怎样",
        "我持有的基金这几天收益咋样",
        "帮我看下那个固收类基金最新情况",
        "这只偏股型的基金最近走势",
        "帮我查下那个混合型的基金今日",
        "我买的那个偏债的品种今天是涨了还是跌了",
        "帮我看看这个基金经理管的产品表现",
        "这个主题基金近一个月怎么样",
        "帮我查下我买的那个权益类产品",
        "那个债券型的最近有没有涨",
        "帮我看我持有的基金最近表现",
        "这只明星经理管的产品今天怎样",
        "帮我查那个年化收益还不错的基金",
        "我那个被动增强的今天怎么走",
        "帮我看下那个低波动策略的产品近况",
    ],
    # ===== I. 多市场（港/美/内地，避开港股/美股/A股原词）=====
    "market": [
        "美国那边的市场今天怎么样",
        "帮我看下香港上市的这家公司",
        "内地这只最近表现怎么样",
        "帮我查下这家在港交所上市的公司",
        "那家在纳斯达克交易的科技公司今天",
        "帮我看下在美国交易的这家中概股",
        "这家同时在两地上市的公司差价多少",
        "帮我查下在香港交易的这家内地企业",
        "美国市场那边今天的大型科技公司怎样",
        "帮我看下在纽约交易所挂牌的这家",
        "香港那边今天整体是涨还是跌",
        "帮我看这家在纽交所上市的车企",
        "内地市场今天整体走势如何",
        "帮我查下这家在海外上市的企业今天",
        "在香港交易的那家车企今天多少",
        "帮我查在美国上市的这家电商公司",
    ],
}

SUBCAT = {
    "price":      ("A", "实时价格"),
    "kline":      ("B", "历史走势"),
    "valuation":  ("C", "估值"),
    "financials": ("D", "财务数据"),
    "indicator":  ("E", "技术信号"),
    "ranking":    ("F", "热门行业"),
    "instrument": ("G", "场内产品"),
    "fund":       ("H", "基金"),
    "market":     ("I", "多市场"),
}


def check_no_trigger(text: str) -> None:
    low = text.lower()
    for t in TRIGGERS:
        if t.lower() in low:
            raise AssertionError(f"含 trigger 子串 [{t}]！→ {text}")


def expand() -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    mood = set("吧呢嘛啊吗了呀哦呐")
    for cat, sents in POOL.items():
        for s in sents:
            if "{t}" in s:
                for tgt in T:
                    exp = s.replace("{t}", tgt)
                    out.append((exp, cat))
                    tail = exp.rstrip()[-1] if exp.strip() else ""
                    if tail and tail not in mood and tail not in "？。！，；":
                        out.append((exp + "？", cat))
            else:
                out.append((s, cat))
                tail = s.rstrip()[-1] if s.strip() else ""
                if tail and tail not in mood and tail not in "？。！，；":
                    out.append((s + "？", cat))
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
            rec = {"text": text, "label": "finance-query", "subcat": f"{code}-{name}"}
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")


def main():
    base = Path(__file__).resolve().parent
    items = dedupe(expand())
    assert len(items) >= 650, f"样本不足: {len(items)} < 650"
    print(f"手写池展开+去重后：{len(items)} 条")
    train, val, test = stratified_split(items, 650, 75, 75, seed=20260711)
    write_jsonl(base / "train" / "finance-query.jsonl", train)
    write_jsonl(base / "val" / "finance-query.jsonl", val)
    write_jsonl(base / "test" / "finance-query.jsonl", test)
    print(f"train={len(train)} val={len(val)} test={len(test)}")
    for split_name, split in [("train", train), ("val", val), ("test", test)]:
        c = Counter(SUBCAT[cat][0] for _, cat in split)
        print(f"\n{split_name} 子语义分布（共 {len(split)}）：")
        for cat in SUBCAT:
            code = SUBCAT[cat][0]
            print(f"  {code}-{SUBCAT[cat][1]:<8} {c.get(code, 0):>3}")


if __name__ == "__main__":
    main()
