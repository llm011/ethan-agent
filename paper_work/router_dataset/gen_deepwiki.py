#!/usr/bin/env python3
"""生成 deepwiki 训练样本（jsonl）。

deepwiki = 通过 DeepWiki 查询 GitHub 公开仓库的文档/架构/用法（AI 问答）。

子语义（现有 + 未来）：
  A 查文档/看说明      B 看架构/目录结构    C 懂用法/API 怎么调
  D 找入口/快速上手    E 看某模块实现细节    F 跨仓库对比
  G 技术选型参考       H 看 issue/贡献背景   I release/迁移/版本变化
  J 排错/为什么这么设计 K 源码机制（硬码字锚点：线程/序列化/中间件/反射/连接池…）

注：K 子类专治「deepwiki 被 paper-analysis 吃掉」——本质是「问某代码仓库内部某机制
在源码里怎么实现」，区分信号是硬码字名词（论文不会问反射/连接池/事件总线）。措辞刻意
区别于外部 test，避免泄漏。

铁律：绝不含任一 trigger 原词子串：
  deepwiki | github docs | how does | look up docs | analyze repo
  | 分析仓库 | 查文档 | github 仓库 | 代码分析 | 开源项目
"""
from __future__ import annotations
import json
import random
from pathlib import Path
from collections import Counter

TRIGGERS = [
    "deepwiki", "github docs", "how does", "look up docs", "analyze repo",
    "分析仓库", "查文档", "github 仓库", "代码分析", "开源项目",
]

# 仓库指代（避开 trigger「github 仓库 / 开源项目」）
R = [
    "这个 repo", "这个项目", "这个库", "这套代码", "这个工程",
    "这个 package", "这个框架", "这个组件库", "这个 SDK", "这个轮子",
]

POOL: dict[str, list[str]] = {
    # ===== A. 查文档/看说明 =====
    "doc": [
        "帮我看下{r}的官方说明",
        "{r}的使用手册在哪",
        "{r}的文档怎么写的，帮我读读",
        "想看下{r}的 readme 讲了啥",
        "{r}有没有详细的说明书",
        "帮我把{r}的文档要点提炼下",
        "{r}的配置项文档在哪能看",
        "想知道{r}文档里关于鉴权那块咋说的",
        "帮我查下{r}的参数说明",
        "{r}的官方教程帮我找下",
        "{r}文档里有没有讲缓存的部分",
        "帮我看看{r}的 API 文档",
        "{r}的说明文档太长了，帮我抓重点",
        "想了解{r}文档里的错误码含义",
        "{r}有没有中文文档",
    ],
    # ===== B. 看架构/目录结构 =====
    "arch": [
        "{r}的整体架构是怎样的",
        "帮我捋一下{r}的目录结构",
        "{r}是怎么组织代码的",
        "想了解{r}的模块划分",
        "{r}的核心模块有哪些",
        "帮我画一下{r}的架构图",
        "{r}各个文件夹分别干啥的",
        "{r}的分层设计是怎样的",
        "想知道{r}的数据流是怎么走的",
        "{r}的整体设计思路是什么",
        "帮我理一下{r}的依赖关系",
        "{r}内部各组件怎么协作的",
        "{r}的入口到底层调用链是啥",
        "想搞清楚{r}的整体骨架",
        "{r}是单体还是模块化的",
    ],
    # ===== C. 懂用法/API 怎么调 =====
    "usage": [
        "{r}这个函数怎么用",
        "帮我看看{r}的接口怎么调",
        "{r}的这个方法参数都是啥意思",
        "想知道{r}怎么初始化",
        "{r}这个类该怎么实例化",
        "帮我搞懂{r}的调用方式",
        "{r}的常用 api 帮我列几个",
        "{r}这个配置该怎么传",
        "想看{r}的典型用法示例",
        "{r}怎么集成到我的项目里",
        "帮我看下{r}的最简用法",
        "{r}的回调函数怎么写",
        "{r}这个钩子啥时候触发",
        "想知道{r}怎么做异步调用",
        "{r}的链式调用怎么用",
    ],
    # ===== D. 找入口/快速上手 =====
    "start": [
        "{r}我该从哪开始看",
        "帮我快速上手{r}",
        "{r}的入门门槛高不高",
        "想十分钟搞懂{r}怎么用",
        "{r}第一步该装什么",
        "帮我写个{r}的 hello world",
        "{r}的快速开始在哪",
        "新手用{r}该看哪几个文件",
        "{r}最小可运行例子怎么搭",
        "帮我找{r}的 getting started",
        "{r}跑起来要哪些前置条件",
        "想知道{r}怎么本地跑起来",
        "{r}的 demo 在哪",
        "帮我理出上手{r}的最短路径",
        "{r}入门看哪块最快",
    ],
    # ===== E. 看某模块实现细节 =====
    "impl": [
        "{r}的这个功能是怎么实现的",
        "帮我看看{r}的调度逻辑怎么写的",
        "{r}内部那个缓存是怎么做的",
        "想了解{r}的并发是怎么处理的",
        "{r}的这个算法实现细节是啥",
        "帮我读读{r}的核心实现",
        "{r}的错误处理是怎么设计的",
        "{r}这块性能优化是咋做的",
        "想看{r}底层是怎么存数据的",
        "{r}的状态管理怎么实现的",
        "帮我看下{r}的解析逻辑",
        "{r}的这个中间件怎么运作的",
        "想搞懂{r}的事件机制实现",
        "{r}的连接池是怎么写的",
        "帮我深挖下{r}的渲染流程",
    ],
    # ===== F. 跨仓库对比 =====
    "compare": [
        "帮我对比下这两个库哪个好",
        "{r}和另一个比有啥优势",
        "想知道这几个框架的区别",
        "这两套方案选哪个更合适",
        "帮我比一比这两个的性能",
        "{r}和竞品的设计差在哪",
        "想了解这两个项目的取舍",
        "这几个工具我该选哪个",
        "帮我横向对比下这几个方案",
        "{r}相比同类有啥不一样",
        "这两个库的生态哪个更成熟",
        "帮我看看哪个更适合我的场景",
        "想对比下两者的上手难度",
        "这几个轮子各自的坑帮我说说",
        "{r}和老牌方案比新在哪",
    ],
    # ===== G. 技术选型参考 =====
    "select": [
        "我想做个项目，{r}合适吗",
        "选型阶段帮我评估下{r}",
        "{r}适合我们这种规模吗",
        "我这个需求用{r}靠不靠谱",
        "{r}的社区活跃度怎么样",
        "想知道{r}维护得勤不勤",
        "{r}还在更新吗，值不值得用",
        "{r}有没有大厂在生产用",
        "帮我判断{r}够不够稳定",
        "{r}的坑多不多，敢上生产吗",
        "我这场景{r}能撑得住吗",
        "想了解{r}的长期可维护性",
        "{r}的 star 多不多，靠谱吗",
        "帮我看{r}适不适合长期投入",
        "{r}的依赖会不会太重",
    ],
    # ===== H. 看 issue/贡献背景 =====
    "issue": [
        "{r}有没有人提过这个 bug",
        "帮我看下{r}相关的 issue 讨论",
        "{r}这个问题官方怎么回复的",
        "想知道{r}有没有已知缺陷",
        "{r}的贡献者都讨论过啥",
        "帮我查下{r}这个功能的讨论历史",
        "{r}社区有没有吐槽过这个点",
        "想了解{r}为啥这个功能一直没做",
        "{r}的 roadmap 在哪能看",
        "帮我看{r}最近有哪些热门讨论",
        "{r}这个报错别人遇到过吗",
        "想知道{r}的维护者怎么看这个建议",
        "帮我找{r}里关于这个特性的争论",
        "{r}有没有 pr 在做这个",
        "{r}这个限制官方有没有计划解决",
    ],
    # ===== I. release/迁移/版本变化 =====
    "version": [
        "{r}新版本改了啥",
        "帮我看{r}的更新日志",
        "{r}从旧版升新版要改哪些",
        "想知道{r}这次大版本的破坏性变更",
        "{r}的迁移指南在哪",
        "{r}最新版稳定吗",
        "帮我对比{r}两个版本的差异",
        "{r}哪个版本最值得用",
        "想了解{r}弃用了哪些 api",
        "{r}升级会不会踩坑",
        "帮我看{r}的版本兼容性",
        "{r}的 changelog 帮我提炼下",
        "想知道{r}下个版本有啥新东西",
        "{r}旧项目还能用老版本吗",
        "帮我理下{r}升级的注意事项",
    ],
    # ===== J. 排错/为什么这么设计 =====
    "why": [
        "{r}为什么要这么设计",
        "想搞懂{r}这个设计的初衷",
        "{r}这块为啥不用更简单的做法",
        "帮我理解{r}这个怪异行为的原因",
        "{r}为什么默认是这个配置",
        "想知道{r}这个限制是出于啥考虑",
        "{r}这个报错到底为啥出现",
        "帮我从源码角度解释{r}这个现象",
        "{r}为啥要分这么多层",
        "想了解{r}这样取舍的理由",
        "{r}这个 api 为啥要这样命名",
        "帮我搞懂{r}背后的设计哲学",
        "{r}为什么不支持那个特性",
        "想知道{r}这个默认值怎么来的",
        "{r}这种实现方式有什么讲究",
    ],
    # ===== K. 源码机制（硬码字锚点，治 deepwiki↔paper 串档）=====
    # 本质：问「这个代码仓库内部某机制在源码层面怎么落地」。硬码字名词（线程池/
    # 序列化/反射/连接池/事件总线/熔断…）是论文绝不会出现的强区分信号。说法全部
    # 自拟，刻意不与外部 test 重合。
    "mechanism": [
        "{r}里那套线程池是按什么策略回收空闲线程的",
        "想顺着源码看{r}的序列化和反序列化走的哪条分支",
        "{r}用反射的地方多吗，这部分代码大概落在哪几层",
        "帮我顺一下{r}建立数据库连接池、复用连接的那段实现",
        "{r}内部消息总线派发事件时，订阅方是怎么被回调到的",
        "{r}做并发控制靠的是锁还是无锁队列，源码里怎么体现",
        "{r}的缓存到了上限按哪种淘汰规则把旧数据踢出去",
        "想知道{r}把数据落到磁盘那一步底层调了什么存储引擎",
        "{r}这套依赖注入的容器是在哪个阶段完成对象装配的",
        "帮我定位{r}做协议编解码、拆包粘包的那段核心代码",
        "{r}内部那个状态机是怎么从一个状态迁到下一个的",
        "{r}请求失败后重试和熔断的判定逻辑写在源码哪块",
        "想搞清{r}是怎么把限流阈值落到每个请求上的实现细节",
        "{r}做内存回收时，对象什么时候才真正被释放掉",
        "帮我追到{r}路由分发那一层，看请求按什么规则被派到处理器",
        "{r}里异步任务排队和调度那部分的源码逻辑帮我捋一遍",
        "{r}的日志埋点是在调用链哪些位置插进去的",
        "想顺源码看懂{r}处理跨线程数据可见性用了什么手段",
    ],
}

SUBCAT = {
    "doc": ("A", "查文档"),
    "arch": ("B", "架构"),
    "usage": ("C", "用法"),
    "start": ("D", "上手"),
    "impl": ("E", "实现"),
    "compare": ("F", "对比"),
    "select": ("G", "选型"),
    "issue": ("H", "讨论"),
    "version": ("I", "版本"),
    "why": ("J", "设计意图"),
    "mechanism": ("K", "源码机制"),
}


def check_no_trigger(text: str) -> None:
    low = text.lower()
    for t in TRIGGERS:
        if t.lower() in low:
            raise AssertionError(f"含 trigger 子串 [{t}]！→ {text}")


def expand() -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for cat, sents in POOL.items():
        for s in sents:
            if "{r}" in s:
                for repo in R:
                    out.append((s.replace("{r}", repo), cat))
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
            rec = {"text": text, "label": "deepwiki", "subcat": f"{code}-{name}"}
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")


def main():
    base = Path(__file__).resolve().parent
    items = dedupe(expand())
    print(f"手写池展开+去重后：{len(items)} 条")
    train, val, test = stratified_split(items, 800, 75, 75, seed=20260629)
    write_jsonl(base / "train" / "deepwiki.jsonl", train)
    write_jsonl(base / "val" / "deepwiki.jsonl", val)
    write_jsonl(base / "test" / "deepwiki.jsonl", test)
    print(f"train={len(train)} val={len(val)} test={len(test)}")
    for name, split in [("train", train), ("val", val), ("test", test)]:
        c = Counter(SUBCAT[cat][0] for _, cat in split)
        print(f"\n{name} 子语义分布（共 {len(split)}）：")
        for cat in SUBCAT:
            code = SUBCAT[cat][0]
            print(f"  {code}-{SUBCAT[cat][1]:<6} {c.get(code, 0):>3}")


if __name__ == "__main__":
    main()