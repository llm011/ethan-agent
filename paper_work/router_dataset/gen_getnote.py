#!/usr/bin/env python3
"""生成 getnote 训练样本（jsonl）。

getnote = Get笔记 App：把个人的文字/图片随手存进去、搜索、管理个人知识收藏库。

子语义：
  A 存文字   B 存图片   C 搜索   D 列出清单   E 改/删   F 知识收藏归类
  G 连接/配置账号   H 边界（专治与 url-process 存链接 / paper-analysis 论文 /
    内置 knowledge 工具 串档 —— 强调「个人随手记的内容存取」而非「存网页链接」或「精读文档」）

铁律：绝不含任一 trigger 原词子串：
  笔记 | 记笔记 | 笔记本 | 我的笔记 | 记到笔记 | 存到笔记 | biji | get笔记
（"笔记"整个词被禁 → 用「记一下 / 帮我存下来 / 记录下来 / 存进我的小本本 /
  收藏这条 / 记到备忘里 / 随手记的地方 / 我存东西那个 / 知识收藏」等同义替换；
  注意「备忘录」是 computer-use 的词，别撞）
"""
from __future__ import annotations
import json
import random
from pathlib import Path
from collections import Counter

TRIGGERS = [
    "笔记", "记笔记", "笔记本", "我的笔记", "记到笔记", "存到笔记", "biji", "get笔记",
]

POOL: dict[str, list[str]] = {
    # ===== A. 存文字 =====
    "save_text": [
        "帮我把这段话存下来",
        "这句话挺好的，帮我记一下",
        "把这段文字收进去别丢了",
        "帮我记录下来这几句",
        "这段内容存进我的小本本",
        "帮我把这条收藏起来",
        "刚才这段先帮我存着",
        "把这句话记到我存东西那个地方",
        "这个观点不错，帮我记录下来",
        "帮我随手记一下这段文字",
        "把这段话收藏到我平时记东西的地方",
        "这条内容帮我留个底",
        "帮我把刚说的这几点存起来",
        "这段话我想留着，帮我记下来",
        "把这句金句收进我的收藏",
        "帮我存一下这段摘录",
        "这条先帮我记到备忘里",
        "把这段话攒起来别忘了",
        "帮我把这几行文字存进去",
        "这句话值得留着，帮我收一下",
        "把刚才那段帮我记录一下",
        "帮我把这条信息存到我常记东西的地方",
    ],
    # ===== B. 存图片 =====
    "save_image": [
        "把这张图也帮我存进去",
        "这张图片帮我收着",
        "帮我把这张截图记录下来",
        "这张图挺重要的，帮我存一下",
        "把这几张图收进我的收藏里",
        "帮我把这张照片也存着",
        "这张图帮我留个底别丢",
        "把这张图片攒到我存东西那个地方",
        "帮我把这张图收藏起来",
        "这张扫描件帮我存进去",
        "把这张图和刚才那段一起存了",
        "帮我把手机里这张图收着",
        "这张图片存到我平时记东西的地方",
        "把这张海报图帮我留着",
        "帮我随手存一下这张图",
        "这几张图都帮我收进去",
        "把这张图记录到我的收藏",
        "帮我把这张流程图存起来",
    ],
    # ===== C. 搜索 =====
    "search": [
        "我之前存的那些里帮我找找关于报销的",
        "翻翻我收过的东西里有没有那段话",
        "帮我搜一下我存过的关于旅行的内容",
        "我记录过一条讲理财的，帮我找出来",
        "在我平时记东西的地方搜下这个关键词",
        "帮我找找之前收藏的那条菜谱",
        "我存过一段代码片段，帮我翻出来",
        "搜一下我攒的内容里有没有提到这个人",
        "帮我在收藏里找那条关于装修的",
        "我之前留过一句话，忘了在哪，帮我搜",
        "翻翻我存东西那个地方有没有会议要点",
        "帮我找找我记录过的那个网址想法",
        "在我的收藏里查一下健身相关的",
        "我收过一张图，帮我搜出来",
        "帮我找找之前存的那段读书感想",
        "搜一下我攒的东西里有没有这个电话",
        "我记录过一个灵感，帮我翻找一下",
        "帮我在存的内容里搜关键词早餐",
        "之前收藏的那条育儿的，帮我找找",
        "帮我查查我存过哪些跟工作有关的",
    ],
    # ===== D. 列出清单 =====
    "list": [
        "看看我都存了些啥",
        "把我收藏的内容列一下",
        "我平时记东西那个地方都有啥，列出来",
        "帮我看看我攒了多少条",
        "列个清单看看我收过哪些",
        "把我最近存的都给我看看",
        "我都记录了些什么，帮我列列",
        "看下我存东西的地方现在有多少条",
        "帮我盘点下我收藏的内容",
        "把我存的东西按时间列出来",
        "看看我这阵子都收了些啥",
        "帮我把收藏清单拉出来",
        "我存过的图都有哪些，列一下",
        "看看我最近留的那些内容",
        "帮我列出我收藏里最新的几条",
        "把我攒的东西整个过一遍给我看",
        "我到底记录过多少条，帮我数数列列",
        "看下我收藏里都有哪些分类",
    ],
    # ===== E. 改/删 =====
    "edit_delete": [
        "把我之前存的那条改一下",
        "帮我更新一下之前收藏的内容",
        "那条记录过的删掉吧",
        "把我存错的那条修正一下",
        "帮我把之前留的那段补充几句",
        "这条收藏没用了，帮我删了",
        "把我攒的那条内容重新编辑下",
        "帮我把之前存的图换成新的",
        "那条重复的收藏帮我删一个",
        "把我记录过的那段话改个措辞",
        "帮我把过时的那条清掉",
        "之前存的那条信息有误，帮我更正",
        "把我收藏里那条标题改一下",
        "帮我把这几条旧的删掉",
        "那段留着的内容帮我加点东西进去",
        "把我存的那条日期改一下",
        "帮我把收藏里那条挪个位置",
        "之前收的那条帮我彻底删除",
    ],
    # ===== F. 知识收藏归类 =====
    "knowledge": [
        "把这条加到我的知识收藏库",
        "帮我给这条内容打个标签归类",
        "在我的收藏里建个新分类",
        "把这几条归到同一个类别下",
        "帮我给存的东西分分组",
        "这条内容归到学习那个分类里",
        "帮我把知识收藏整理成几个专题",
        "给这条收藏加个标签方便以后找",
        "把我攒的内容按主题归归类",
        "帮我建个专门放灵感的收藏夹",
        "这条存进工作相关的知识分类",
        "帮我把零散收藏的内容体系化整理下",
        "给我的知识收藏库加个新栏目",
        "把这批内容打上同一个标签",
        "帮我把收藏按项目分类管理",
        "这条归到生活小窍门那一类",
        "帮我把知识收藏里的标签重新梳理下",
        "给这段存的内容归个档",
    ],
    # ===== G. 连接/配置账号 =====
    "config": [
        "帮我连接一下我那个记东西的账号",
        "配置一下我存内容用的那个服务",
        "把我收藏用的账号登录一下",
        "帮我绑定我平时记东西那个 app",
        "设置一下同步到我的知识收藏库",
        "帮我把存东西的账号授权接上",
        "配一下我收藏内容用的那个工具",
        "帮我登录一下我攒东西的地方",
        "把我记录用的账户连上",
        "帮我开启一下收藏内容的自动同步",
        "配置下我存东西那个服务的密钥",
        "帮我重新连接一下收藏账号，掉线了",
        "设置一下默认存到哪个收藏分类",
        "帮我把这台设备也接到我的收藏账号",
        "配一下我知识收藏库的访问权限",
    ],
    # ===== H. 边界（防串 url-process / paper-analysis / 内置 knowledge 工具）=====
    # 信号：宾语是「我个人脑子里/手边随手冒出的内容」，动作是「存起来回头看」——
    # 不是存网页链接内容，不是精读论文文档，不是查内置知识库。说法自拟防泄漏。
    "boundary": [
        "我脑子里刚冒出来这句话，帮我存着别忘了",
        "把我刚才想到的那几点收起来回头看",
        "这是我自己琢磨出来的想法，帮我留一下",
        "刚开会随口说的重点，帮我收着别丢",
        "我临时想到个主意，帮我先存进去",
        "把我这段随手写的感想收起来",
        "刚才灵光一闪那句，帮我记录下来存着",
        "这是我个人的一点心得，帮我攒着",
        "把我脑子里过的这几条先存下来慢慢整理",
        "刚想到一句想说的话，帮我收进去",
        "这段是我自己总结的，帮我留个底回头翻",
        "把我随口念叨的这几点帮我存着",
        "我怕忘了，这个念头帮我先记下来收着",
        "刚散步想通的那件事，帮我存进去",
        "把我这点零碎的想法收起来以后看",
        "这是我私下记的一些感受，帮我留着",
        "刚才聊天里我说的那段，帮我自己存一份",
        "我心里冒出的这句提醒，帮我收着别忘",
    ],
}

SUBCAT = {
    "save_text": ("A", "存文字"),
    "save_image": ("B", "存图片"),
    "search": ("C", "搜索"),
    "list": ("D", "列出"),
    "edit_delete": ("E", "改删"),
    "knowledge": ("F", "知识归类"),
    "config": ("G", "配置"),
    "boundary": ("H", "边界"),
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
            rec = {"text": text, "label": "getnote", "subcat": f"{code}-{name}"}
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")


def main():
    base = Path(__file__).resolve().parent
    items = dedupe(expand())
    print(f"手写池展开+去重后：{len(items)} 条")
    train, val, test = stratified_split(items, 500, 75, 75, seed=20260711)
    write_jsonl(base / "train" / "getnote.jsonl", train)
    write_jsonl(base / "val" / "getnote.jsonl", val)
    write_jsonl(base / "test" / "getnote.jsonl", test)
    print(f"train={len(train)} val={len(val)} test={len(test)}")
    for name, split in [("train", train), ("val", val), ("test", test)]:
        c = Counter(SUBCAT[cat][0] for _, cat in split)
        print(f"\n{name} 子语义分布（共 {len(split)}）：")
        for cat in SUBCAT:
            code = SUBCAT[cat][0]
            print(f"  {code}-{SUBCAT[cat][1]:<6} {c.get(code, 0):>3}")


if __name__ == "__main__":
    main()
