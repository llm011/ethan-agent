#!/usr/bin/env python3
"""生成 code-review 训练样本（jsonl）。

code-review = 对一段代码变更 / PR / MR / diff 做系统性审查：
  把这次改动通读一遍、找里面有没有 bug/边界漏洞、有没有安全隐患、
  性能上有没有坑，最后给一份修改建议或评审意见。
  对象是「已有的一处变更」，不是「读懂整个开源仓库」，也不是「从零写一段新代码」。

子语义：
  A pr        帮我把这个 PR / 合并请求通读一遍、这个 MR 能不能合
  B diff      看看这次改动/这个补丁/这段提交改得对不对
  C bug       这段改动有没有埋 bug、逻辑对不对、有没有边界没考虑
  D security  这次变更有没有安全隐患、注入风险、越权
  E perf      这段新代码性能怎么样、有没有 N+1、会不会内存泄漏
  F suggest   帮我提点修改建议、哪里能优化、给个评审意见
  G boundary  强调「审查已有变更」而非「理解整个仓库」或「从零写代码」

铁律：绝不含 code-review 的任一 trigger 原词子串：
  code review | 代码审查 | review代码 | review一下 | 帮我看看代码 | 看下代码
  | 审查代码 | pr review | diff review | 检查代码 | 代码质量
（用同义替换：代码审查/审查代码→把这个改动过一遍；帮我看看代码→瞅瞅这段提交有没有问题；
  代码质量→这个 patch 靠不靠谱；合并请求帮我把把关）
"""
from __future__ import annotations
import json
import random
from pathlib import Path
from collections import Counter

TRIGGERS = [
    "code review", "代码审查", "review代码", "review一下", "帮我看看代码",
    "看下代码", "审查代码", "pr review", "diff review", "检查代码", "代码质量",
]

POOL: dict[str, list[str]] = {
    # ===== A. pr 把 PR / 合并请求过一遍、能不能合 =====
    "pr": [
        "帮我把这个 PR 通读一遍看能不能合",
        "这个合并请求你帮我把把关再放行",
        "我提了个 PR，麻烦你过一遍给个意见",
        "这个 MR 能不能合，你帮我掂量掂量",
        "帮我把这个合并请求里的改动都过一遍",
        "这个 PR 我不太放心，你帮我盯一盯",
        "同事那个合并请求，帮我评一评能不能进主干",
        "这个 PR 提交上去之前你先帮我把关一下",
        "麻烦把这个合并请求从头到尾捋一遍",
        "这个 MR 里改了不少东西，帮我逐个看下靠不靠谱",
        "帮我把这个待合并的分支改动通读评一遍",
        "这个 PR 我想合了，你先帮我确认没问题",
        "合并请求发你了，帮我挑挑里面的毛病",
        "这个 PR 里的几处改动帮我逐条过一遍",
        "帮我评审下这个合并请求，看有没有拦路的问题",
        "这个 MR 合进去会不会有风险，帮我看看",
        "我这个 PR 想请你把把关再点同意",
        "帮我把这个合并请求里所有文件的变化都过一遍",
        "这个 PR 提交人是新来的，帮我盯细一点",
        "麻烦帮我把这个合并请求评审下给个结论",
        "这个 MR 你觉得能直接合还是得先改改",
        "帮我把这次这个合并请求整体捋一遍给意见",
        "这个 PR 里的改动帮我确认下能不能上",
    ],
    # ===== B. diff 这次改动/补丁/提交改得对不对 =====
    "diff": [
        "帮我把这个改动过一遍看改得对不对",
        "瞅瞅这段提交有没有问题",
        "这个 patch 靠谱吗，帮我看看",
        "这次改动帮我从头到尾捋一遍",
        "这个补丁改得对不对，你帮我确认下",
        "帮我把这次的 diff 逐行看看有没有改错",
        "这段提交我不确定改对了没，帮我过一眼",
        "这次改的这几行你帮我瞧瞧有没有毛病",
        "帮我把这个补丁里改动的地方都过一遍",
        "这次提交动了不少地方，帮我逐处确认下",
        "这个改动帮我核一核是不是符合预期",
        "帮我把这段变更前后对比着看看改得妥不妥",
        "这次的修改帮我通读一遍有没有漏改的",
        "这个 patch 里的每处改动帮我都过一下",
        "帮我看看这次改动有没有把别的地方带坏",
        "这段提交改得干不干净，帮我瞄一眼",
        "帮我把这次变更的每个文件都过一遍",
        "这个改动合不合理，你帮我掂量下",
        "帮我把这次提交的内容整体捋顺看有没有坑",
        "这次改的这块你帮我确认改法对不对",
        "帮我把这个补丁通读评一遍",
        "这次变更帮我逐条过一遍看有没有改歪",
    ],
    # ===== C. bug 有没有埋 bug、逻辑对不对、边界 =====
    "bug": [
        "这段改动有没有埋 bug，帮我找找",
        "帮我看看这次改的逻辑对不对",
        "这段新写的有没有边界情况没考虑到",
        "帮我瞧瞧这里会不会有空指针的坑",
        "这次改动的判断条件写反了没，帮我核一下",
        "帮我看看这段循环会不会越界",
        "这个改法有没有漏掉异常没处理",
        "帮我确认下这次改动在极端输入下会不会挂",
        "这段提交里的边界值处理得对不对",
        "帮我找找这次改动里潜在的逻辑漏洞",
        "这里改完之后并发下会不会出问题，帮我看看",
        "帮我瞅瞅这个改动有没有把 null 情况漏了",
        "这次改的分支判断齐不齐，有没有落下的情况",
        "帮我看看这段改动会不会有除零那类的坑",
        "这个补丁里有没有一眼能看出来的 bug",
        "帮我核对下这次改动的返回值对不对",
        "这段改动在空列表的时候会不会报错，帮我想想",
        "帮我看看这次改的地方有没有竞态问题",
        "这里的循环终止条件对不对，帮我确认",
        "帮我找找这次提交里逻辑上站不住脚的地方",
        "这段改动会不会在边界上多算或少算一次",
        "帮我看看这个改法有没有把原来的判断改错",
    ],
    # ===== D. security 安全隐患、注入、越权 =====
    "security": [
        "这次变更有没有安全隐患，帮我看看",
        "帮我瞧瞧这段改动会不会有注入风险",
        "这里拼 SQL 的改法会不会被注入，帮我核一下",
        "帮我看看这次改动有没有越权的口子",
        "这段提交把用户输入直接用了，安不安全帮我判断",
        "帮我确认下这次改动没把密钥写进代码里",
        "这个改法会不会泄露敏感信息，帮我看看",
        "帮我瞅瞅这段改动的鉴权是不是漏了一环",
        "这次变更有没有可能被绕过校验，帮我想想",
        "帮我看看这里对外接口的改动有没有暴露风险",
        "这段改动把权限判断挪了位置，会不会出漏洞",
        "帮我核一下这次改的地方有没有路径穿越的风险",
        "这个改动接收外部参数，帮我看看有没有过滤干净",
        "帮我瞧瞧这次提交会不会引入 XSS 那类问题",
        "这里改完之后 token 校验还在不在，帮我确认",
        "帮我看看这段改动有没有把敏感字段直接返回出去",
        "这次变更对文件上传的处理安不安全，帮我判断",
        "帮我核对下这次改动有没有反序列化的隐患",
        "这段改动的加密用法对不对，帮我看看",
        "帮我瞅瞅这次改的登录逻辑会不会被绕过",
        "这里对外部请求的改动有没有 SSRF 风险，帮我想想",
        "帮我确认这次变更没有把内部接口无意暴露出去",
    ],
    # ===== E. perf 性能、N+1、内存泄漏 =====
    "perf": [
        "这段新代码性能怎么样，帮我看看",
        "帮我瞧瞧这次改动会不会有 N+1 查询",
        "这里改完会不会内存泄漏，帮我核一下",
        "帮我看看这段循环里的查询是不是太频繁了",
        "这次改动的复杂度会不会一下子高上去",
        "帮我确认下这段改动没在热点路径上做重活",
        "这个改法会不会每次都重复算一遍，帮我看看",
        "帮我瞅瞅这次改动有没有该加缓存没加的地方",
        "这段提交里有没有可以合并的重复请求，帮我找找",
        "帮我看看这里改完之后有没有大对象没释放",
        "这次变更会不会拖慢接口响应，帮我判断",
        "帮我核一下这段改动的数据库调用是不是太多",
        "这个改法在数据量大的时候扛不扛得住，帮我想想",
        "帮我瞧瞧这次改动有没有不必要的全表扫描",
        "这段新写的会不会频繁触发 GC，帮我看看",
        "帮我看看这里改完之后连接有没有及时关掉",
        "这次改动里有没有能提前退出省一轮循环的地方",
        "帮我确认下这段改动没在锁里做耗时操作",
        "这里的批处理改法效率高不高，帮我掂量下",
        "帮我瞅瞅这次提交有没有把 IO 放进了循环里",
        "这段改动会不会导致重复加载同一份数据，帮我看看",
        "帮我看看这次改的地方能不能少几次网络往返",
    ],
    # ===== F. suggest 提修改建议、哪里能优化、评审意见 =====
    "suggest": [
        "帮我给这次改动提点修改建议",
        "这段提交哪里还能优化，帮我说说",
        "帮我对这个改动给份评审意见",
        "这次改的地方有没有更好的写法，帮我出出主意",
        "帮我看看这段改动哪块可以再收拾收拾",
        "这个补丁你觉得还有哪里能改进，帮我列列",
        "帮我给这次变更挑几条值得改的地方",
        "这段改动的命名和结构帮我提点意见",
        "帮我看看这次改的能不能拆得更清楚些",
        "这个改法有没有更简洁的方式，帮我建议下",
        "帮我给这段提交写几句评审反馈",
        "这次改动里哪些可以顺手重构，帮我点一点",
        "帮我看看这段改动的注释和可读性还能怎么提",
        "这个 patch 你给我几条改进建议吧",
        "帮我评一评这次改动，顺便说说哪能更好",
        "这段改动的错误处理帮我提点建议怎么补",
        "帮我看看这次变更有没有可以抽成函数的重复块",
        "这个改动的接口设计帮我给点评审意见",
        "帮我挑挑这段提交里值得打磨的细节",
        "这次改的地方帮我说说哪里能更稳妥些",
        "帮我给这个改动列几条上线前该改的点",
        "这段新代码的可维护性帮我提点改进思路",
    ],
    # ===== G. boundary 审查已有变更（区别于读懂仓库/从零写码）=====
    "boundary": [
        "这个同事提的改动我不放心，帮我挑挑毛病",
        "这次上线的变更帮我评审下风险点",
        "不是让你重写，就把这次的改动帮我把把关",
        "我不用你从头写，就这段已有的改动帮我过一遍",
        "别去啃整个仓库，就盯这次提交的这几处变化",
        "这次发版前的改动帮我逐条评审下有没有隐患",
        "只看这次动过的地方就行，帮我评一评稳不稳",
        "这个改动是别人写的，帮我审一审再决定合不合",
        "不用理解整个项目，就这次 diff 帮我把关",
        "这次改动风险大不大，帮我单独评估下再放行",
        "就这次提交里改的这块，帮我确认能不能上线",
        "别帮我写新功能，先把这次已有的变更评审掉",
        "这次热修的改动帮我快速过一遍看有没有雷",
        "同事临时塞的这个改动，帮我盯一盯别出事",
        "只针对这次的变更给意见，其他历史代码先别动",
        "这个改动要紧急上，帮我评审下有没有拦路问题",
        "不是让你读懂全仓库，就评这次改的这几个文件",
        "这次回滚补丁帮我审一审改得对不对再合",
        "就这段刚提交的变更，帮我判断下能不能放行",
        "帮我把这次改动单独拎出来评审，别扯别的模块",
    ],
}

SUBCAT = {
    "pr": ("A", "合并请求"),
    "diff": ("B", "改动"),
    "bug": ("C", "缺陷"),
    "security": ("D", "安全"),
    "perf": ("E", "性能"),
    "suggest": ("F", "建议"),
    "boundary": ("G", "审查边界"),
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
            rec = {"text": text, "label": "code-review", "subcat": f"{code}-{name}"}
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")


def main():
    base = Path(__file__).resolve().parent
    items = dedupe(expand())
    print(f"手写池展开+去重后：{len(items)} 条")
    train, val, test = stratified_split(items, 500, 75, 75, seed=20260711)
    write_jsonl(base / "train" / "code-review.jsonl", train)
    write_jsonl(base / "val" / "code-review.jsonl", val)
    write_jsonl(base / "test" / "code-review.jsonl", test)
    print(f"train={len(train)} val={len(val)} test={len(test)}")
    for name, split in [("train", train), ("val", val), ("test", test)]:
        c = Counter(SUBCAT[cat][0] for _, cat in split)
        print(f"\n{name} 子语义分布（共 {len(split)}）：")
        for cat in SUBCAT:
            code = SUBCAT[cat][0]
            print(f"  {code}-{SUBCAT[cat][1]:<6} {c.get(code, 0):>3}")


if __name__ == "__main__":
    main()
