#!/usr/bin/env python3
"""生成 paper-analysis 训练样本（jsonl）。

方法：句池由 LLM（我）亲自手写——口语/正式/错别字/省略/疑问混搭，覆盖
A–K 子语义。脚本只负责：①trigger 屏障 ②分层切分 train/val/test ③去重。
不使用模板填空（那样会泄漏句式骨架，分类器学到格式而非语义）。

铁律：绝不含任一 trigger 原词子串：
  精读论文 | 深度解读论文 | 解读论文 | 分析论文 | paper analysis | 论文精读
  | arxiv | arXiv | 读这篇论文 | map reduce 论文
"""
from __future__ import annotations
import json
import random
from pathlib import Path

TRIGGERS = [
    "精读论文", "深度解读论文", "解读论文", "分析论文", "paper analysis",
    "论文精读", "arxiv", "arXiv", "读这篇论文", "map reduce 论文",
]

# 论文指代（避免 trigger 子串）
P = [
    "这篇文献", "这篇 study", "这份 PDF", "这个 research", "这篇稿子",
    "这篇文章", "这份材料", "这篇预印本", "这份报告", "这篇研究",
    "这篇 manuscript", "这个 paper", "这份文档", "这篇正文",
]

# 子语义手写池：每条都是独立的真实用户表述。
# key = 子语义；value = 句子列表（句子里的 {p} 会被随机论文指代替换，制造更多变体）。
# 句子里也大量使用「这」「这篇」「这个」等无指代词，模拟真实口吻。
POOL: dict[str, list[str]] = {
    # ===== A. 概览/整体理解 =====
    "overview": [
        "这篇到底在讲啥啊，看不太懂",
        "帮我用一句话概括下这篇的核心",
        "这个 paper 主要解决了什么问题",
        "我不懂这个领域，能不能先给我讲讲背景",
        "这篇文章的研究动机是啥",
        "三句话总结下这篇吧",
        "值不值得我花时间读，先给个整体印象",
        "用大白话说说这篇是干嘛的",
        "这篇的 abstract 啥意思，帮我提炼下",
        "这篇的研究主题帮我定位下，属于哪个方向",
        "这个研究想回答的科学问题是啥",
        "帮我理一下这篇的整体脉络",
        "这篇算综述还是原创工作",
        "给我个 take-home message 就行",
        "这篇的核心主张是什么",
        "能不能画个整体框架图给我看看",
        "这篇的 problem statement 在哪",
        "快速浏览下，告诉我这篇讲啥的",
        "这篇开头那段引入看不太明白",
        "这篇跟那个热门方向啥关系",
        "这个研究是基础研究还是应用研究",
        "这篇的范畴有多大，只聚焦一个小点吗",
        "帮我把这篇拆成「问题—方案—结果」三段",
        "这篇的开门见山那句话是啥",
        "这个 paper 的一句话 elevator pitch",
        "这篇在讲哪个 benchmark 的事",
        "这篇是 theory 还是 empirical 的",
        "这研究背景里那个痛点具体是啥",
        "这篇为什么要做这个事",
        "一句话，这篇牛在哪",
    ],
    # ===== B. 方法/思路 =====
    "method": [
        "这篇用的什么方法啊",
        "核心算法是怎么设计的，讲细点",
        "技术路线能帮我捋一遍吗",
        "那个模型架构图看不懂，拆解下",
        "方法论有啥特别的地方",
        "这个思路是怎么想到的",
        "pipeline 具体分几步走",
        "那个核心公式啥意思，每个符号解释下",
        "训练策略是怎样的",
        "损失函数为什么这么定",
        "数学推导部分帮我看下对不对",
        "用的什么 backbone",
        "网络结构有多少层，参数量多大",
        "特征工程怎么做的",
        "方法上和直觉差在哪",
        "第3节方法部分帮我理解下",
        "inference 流程走一遍",
        "那个 trick 起作用的原理解释下",
        "这方法能迁移到别的任务吗",
        "这篇的核心 idea 一句话能说清吗",
        "方法那块太硬核了，软化讲一下",
        "这个 encoder decoder 怎么搭的",
        "attention 在这篇里是怎么用的",
        "正则化项是啥，起啥作用",
        "为啥不用更简单的方案，非得搞这么复杂",
        "这个方法的归纳偏置是什么",
        "训练数据怎么喂进去的",
        "预训练和微调是怎么分的",
        "那个 mask 机制具体咋操作",
        "方法的计算复杂度是多少",
    ],
    # ===== C. 实验/结果 =====
    "experiment": [
        "实验结果咋样，提升明显吗",
        "在哪些数据集上跑的",
        "baseline 都有哪些",
        "消融实验说明了啥",
        "主结果提升多少个点",
        "指标具体多少，别给我说「显著」",
        "实验那个大表帮我对一下数字",
        "ablation 每个模块贡献多少",
        "对比 SOTA 提升了多少",
        "实验设置公不公平",
        "困难样本上表现如何",
        "case study 有啥启发",
        "为啥用这个评测指标",
        "实验跑了几组超参",
        "误差分析在哪，讲了啥",
        "有没有统计显著性",
        "zero-shot 结果怎么样",
        "不同模型规模的 scaling 趋势",
        "实验环境啥配置",
        "实验结论可信吗，有没有水分",
        "那个对比表里加粗的是不是最好的",
        "training time 多长",
        "推理速度怎么样",
        "在长尾样本上是不是就崩了",
        "实验用的随机种子提了吗",
        "几个 baseline 是不是都调好了",
        "那个曲线图的拐点说明啥",
        "消融去掉 attention 是不是就掉很多",
        "实验有没有做鲁棒性测试",
        "结果方差大不大",
    ],
    # ===== D. 结论/贡献 =====
    "conclusion": [
        "主要贡献有哪几点",
        "最后得出啥结论",
        "解决了之前没人搞定的问题吗",
        "意义在哪，为啥重要",
        "对未来研究有啥启发",
        "声称的贡献成立吗",
        "take-away 是啥",
        "算不算里程碑工作",
        "实际价值多大",
        "结论会不会太强了",
        "对工业界有用吗",
        "理论贡献和工程贡献分别啥",
        "局限性作者自己提了吗",
        "只记一件事的话记啥",
        "对未来三年这个领域意味着啥",
        "这篇的贡献会被引用很多吗",
        "结论里有没有夸大其词",
        "这个工作的长期影响会怎样",
        "作者自己怎么看这个工作的不足",
        "这篇会不会开一个新的子方向",
    ],
    # ===== E. 结构/框架 =====
    "structure": [
        "这篇怎么组织的，列个目录",
        "一共几章，各章讲啥",
        "章节脉络梳理下",
        "图表现在第几页",
        "附录有内容吗",
        "正文和补充材料咋对应",
        "参考文献从第几页开始",
        "表格都在哪些位置",
        "多少页，篇幅分布如何",
        "结构符不符合常规规范",
        "关键章节直接定位给我",
        "方法和实验章节怎么衔接的",
        "这文章目录结构有点乱",
        "图表编号帮我列一下",
        "附录里的证明在哪个文件",
    ],
    # ===== F. 创新点 =====
    "novelty": [
        "创新点在哪，说人话",
        "相比老方法新在哪",
        "novelty 够发顶会吗",
        "最核心的一个创新是啥",
        "哪些技术是首次提出",
        "创新是渐进式还是颠覆式",
        "新点和已有工作重叠多吗",
        "创新被审稿人质疑过吗",
        "贡献列表里哪条最实在",
        "这个 novelty 是不是换个皮",
    ],
    # ===== G. 对比/前人工作 =====
    "related": [
        "和之前的方法比优势在哪",
        "related work 提到哪些流派",
        "是在谁的工作上改的",
        "和 Transformer 那条线啥关系",
        "前人工作有哪些代表作",
        "对比的经典方法各啥缺陷",
        "属于哪个技术演进路线",
        "和同期那篇有啥区别",
        "这个方法和 resnet 思路像不像",
        "前人踩过的坑这篇避开了吗",
    ],
    # ===== H. 复现/可用性 =====
    "reproduce": [
        "代码开源了吗，给个链接",
        "能复现吗，复现成本高不高",
        "checkpoint 在哪下",
        "数据集好搞到手吗",
        "有官方实现吗",
        "环境配置复杂吗",
        "方法工程上能落地吗",
        "复现需要多大显存",
        "官方 repo 维护得咋样",
        "第三方复现版本靠谱吗",
    ],
    # ===== I. 通俗转述/翻译 =====
    "plain": [
        "翻译成中文给我看",
        "用初中生能懂的话讲讲",
        "术语解释下，啥意思",
        "英文术语对应中文是啥",
        "不懂英文，讲啥了帮我翻",
        "数学符号看不懂，说人话",
        "中英对照给我",
        "那些缩写全称是啥",
        "把那个绕的句子拆成短句",
        "这段英文太学术了，口语化下",
    ],
    # ===== J. 批判/局限 =====
    "critique": [
        "有啥漏洞没",
        "假设合理吗",
        "实验有没有 cherry-picking",
        "局限性我该怎么评价",
        "结论会不会过强",
        "啥情况下这方法会失效",
        "有没有偷换概念",
        "统计 claim 严谨吗",
        "样本量够不够支撑结论",
        "作者是不是回避了反例",
    ],
    # ===== K. 指定来源 =====
    "source": [
        "帮我处理这个预印本链接",
        "我贴个编号 2401.00001，扒下来",
        "这是本地 PDF 路径，读一下",
        "这个 https 链接的麻烦看下",
        "我上传个文件，把内容理清楚",
        "这个 doi 对应的文章看下",
        "给个链接你帮我抓全文",
        "把这份 PDF 喂进去，出个解读",
        "我桌面有个 pdf，帮我拆开看",
        "这个仓库里那份 technical report 帮我读",
    ],
}


def check_no_trigger(text: str) -> None:
    low = text.lower()
    for t in TRIGGERS:
        if t.lower() in low:
            raise AssertionError(f"含 trigger 子串 [{t}]！→ {text}")


def expand() -> list[tuple[str, str]]:
    """展开手写池：每个模板句再随机换论文指代，扩充变体。返回 [(text, subcat)]。"""
    rng = random.Random(20260629)
    mood = set("吧呢嘛啊吗了呀哦呐")  # 句末语气词——已有则不再叠加
    out: list[tuple[str, str]] = []
    for cat, sents in POOL.items():
        for s in sents:
            if "{p}" in s:
                for paper in P:
                    out.append((s.replace("{p}", paper), cat))
            else:
                out.append((s, cat))
                # 无占位的轻微扰动：句末非语气词/标点时，加一个自然后缀
                tail = s.rstrip()[-1] if s.strip() else ""
                if tail and tail not in mood and tail not in "？。！，；":
                    for suf in ["呢", "啊", "吗", "？"]:
                        out.append((s + suf, cat))
    return out


def dedupe(items: list[tuple[str, str]]) -> list[tuple[str, str]]:
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
    """按子语义分层切分：保证每个子语义在 train/val/test 都有代表。
    items: [(text, cat)]；返回三个 [(text, cat)] 列表。"""
    rng = random.Random(seed)
    by_cat: dict[str, list[tuple[str, str]]] = {}
    for text, cat in items:
        by_cat.setdefault(cat, []).append((text, cat))
    for cat in by_cat:
        rng.shuffle(by_cat[cat])

    train, val, test = [], [], []
    total = len(items)
    for cat, texts in by_cat.items():
        n = len(texts)
        cval = max(1, round(n * val_n / total))
        ctest = max(1, round(n * test_n / total))
        cval = min(cval, n // 3)
        ctest = min(ctest, n // 3)
        i = 0
        test.extend(texts[i:i + ctest]); i += ctest
        val.extend(texts[i:i + cval]); i += cval
        train.extend(texts[i:])

    rng.shuffle(train); rng.shuffle(val); rng.shuffle(test)
    # 凑满目标数：不足则从剩余 train 池补
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


# 子语义 → (代码, 中文名)
SUBCAT = {
    "overview": ("A", "概览"),
    "method": ("B", "方法"),
    "experiment": ("C", "实验"),
    "conclusion": ("D", "结论"),
    "structure": ("E", "结构"),
    "novelty": ("F", "创新点"),
    "related": ("G", "对比"),
    "reproduce": ("H", "复现"),
    "plain": ("I", "转述"),
    "critique": ("J", "批判"),
    "source": ("K", "来源"),
}


def write_jsonl(path: Path, items: list[tuple[str, str]]) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        for text, cat in items:
            code, name = SUBCAT[cat]
            rec = {
                "text": text,
                "label": "paper-analysis",
                "subcat": f"{code}-{name}",
            }
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")


def main():
    base = Path(__file__).resolve().parent
    items = dedupe(expand())
    print(f"手写池展开+去重后：{len(items)} 条")

    train, val, test = stratified_split(items, 500, 75, 75, seed=20260629)
    write_jsonl(base / "train" / "paper-analysis.jsonl", train)
    write_jsonl(base / "val" / "paper-analysis.jsonl", val)
    write_jsonl(base / "test" / "paper-analysis.jsonl", test)
    print(f"train={len(train)} val={len(val)} test={len(test)}")

    from collections import Counter
    print("\n子语义代码对照：")
    for cat, (code, name) in SUBCAT.items():
        print(f"  {code} {name:<6} ({cat})")

    for name, split in [("train", train), ("val", val), ("test", test)]:
        c = Counter(SUBCAT[cat][0] for _, cat in split)
        print(f"\n{name} 子语义分布（共 {len(split)}）：")
        for code in sorted(SUBCAT.values(), key=lambda x: x[0]):
            pass
        for cat in SUBCAT:  # 按 A-K 顺序
            code = SUBCAT[cat][0]
            print(f"  {code}-{SUBCAT[cat][1]:<4} {c.get(code, 0):>3}")

    # 抽样打印：每个子语义各 2 条 train 样本，直观看到归属
    print("\n抽样（train，每子语义 2 条）：")
    by_cat = {}
    for text, cat in train:
        by_cat.setdefault(cat, []).append(text)
    for cat in SUBCAT:
        for t in by_cat.get(cat, [])[:2]:
            print(f"  [{SUBCAT[cat][0]}-{SUBCAT[cat][1]}] {t}")


if __name__ == "__main__":
    main()
