#!/usr/bin/env python3
"""生成 skills-manager 训练样本（jsonl）。

skills-manager = 用 `npx skills` 管理 Agent 技能包：搜/装/卸/更/列。

子语义（现有 + 未来）：
  A 搜/找技能         B 安装技能（GitHub/npm/全局/项目）  C 卸载/删除技能
  D 更新/升级技能      E 列出已装/查看清单               F 概念/范围（内置 vs 用户、要不要重启）
  G 装完用不了/排错    H 从某来源装（给了 url/名字）

铁律：绝不含任一 trigger 原词子串：
  install skill | add skill | skills list | skills find | 安装技能 | 添加技能
  | 技能管理 | npx skills | skill 包 | search skills | 装技能 | 装个技能 | 卸载技能
  | 删除技能 | 升级技能 | 更新技能 | 技能包 | 能力包 | 找技能 | 搜技能 | 技能列表
  | 装能力 | 加能力
（几乎所有「技能+动词」组合都被屏蔽 → 用「能力/插件/扩展/本事/功能模块」等同义替换）
"""
from __future__ import annotations
import json
import random
from pathlib import Path
from collections import Counter

TRIGGERS = [
    "install skill", "add skill", "skills list", "skills find", "安装技能", "添加技能",
    "技能管理", "npx skills", "skill 包", "search skills", "装技能", "装个技能",
    "卸载技能", "删除技能", "升级技能", "更新技能", "技能包", "能力包", "找技能",
    "搜技能", "技能列表", "装能力", "加能力",
]

POOL: dict[str, list[str]] = {
    # ===== A. 搜/找能力 =====
    "find": [
        "帮我看看有哪些现成的扩展能装",
        "搜一下有没有处理 PDF 的插件",
        "想找个能查天气的功能模块",
        "有没有现成的本事可以加给 agent",
        "帮我搜搜社区里有啥好用的扩展",
        "想找个翻译用的插件",
        "有没有能操作数据库的现成模块",
        "帮我查查有没有爬虫相关的扩展",
        "市面上有哪些可以装的小工具",
        "想看看有没有发邮件的功能可以加",
        "帮我找个能画图的扩展",
        "有没有现成的本事能处理表格",
        "搜下有没有股票行情的插件",
        "想找个能识别图片的模块",
        "帮我看看有没有日程管理的扩展",
        "有没有能连接 notion 的现成功能",
        "帮我搜搜跟 github 相关的插件",
        "想找个语音转文字的扩展",
        "有没有能做数据可视化的模块",
        "帮我看看有哪些热门的扩展可以加",
        "想找个能定时提醒的扩展",
        "有没有现成的本事能读取网页",
        "帮我搜搜跟 excel 处理相关的模块",
        "想找个能管理待办的插件",
        "有没有能调用地图的扩展",
        "帮我看看有没有 OCR 识别的功能",
        "想找个能压缩文件的小工具",
        "有没有处理音频的现成扩展",
    ],
    # ===== B. 安装能力 =====
    "install": [
        "帮我把这个扩展装上",
        "给 agent 加一个新本事",
        "我想装一个处理图片的插件",
        "把这个 github 上的扩展装进来",
        "帮我装个能查文档的功能模块",
        "想给它添个发邮件的本事",
        "把这个工具装到全局所有项目都能用",
        "只在当前项目装这个扩展",
        "帮我从 npm 装一个插件",
        "我找到一个好用的扩展，帮我装上",
        "给 agent 装个画图的能力",
        "想把这个第三方模块加进来",
        "帮我装一下这个社区做的扩展",
        "把这个本事装成全局的",
        "我想给它扩充一个新功能",
        "帮我安装一下那个翻译插件",
        "把这个能力添加到 agent 上",
        "想装个能操作 excel 的扩展",
        "帮我把这个仓库里的扩展装进来",
        "给我的 agent 加上爬虫的本事",
        "帮我装个能读 PDF 的扩展",
        "想给它加个连数据库的能力",
        "把这个能发短信的插件装上",
        "帮我装一个做思维导图的模块",
        "想给 agent 添个查快递的本事",
        "把这个语音合成的扩展装进来",
        "帮我装个能跑定时任务的功能",
        "想加个能抓股价的扩展",
        "把这个 OCR 插件装上试试",
    ],
    # ===== C. 卸载/删除能力 =====
    "remove": [
        "帮我把这个扩展卸了",
        "不想要这个本事了，删掉",
        "把那个没用的插件移除",
        "帮我把之前装的那个功能模块删了",
        "这个扩展太占地方，卸载吧",
        "把这个用不上的能力去掉",
        "帮我清掉那个出问题的插件",
        "想把这个扩展彻底删除",
        "把之前加的那个本事撤掉",
        "帮我移除这个不需要的模块",
        "这个插件有 bug，先卸了",
        "把那个重复的扩展删掉一个",
        "帮我把测试用的那个能力清掉",
        "不用的扩展帮我都卸了",
        "把这个旧的功能模块删除",
    ],
    # ===== D. 更新/升级能力 =====
    "update": [
        "帮我把这个扩展更到最新版",
        "这个插件有新版本，升一下",
        "把所有装的本事都更新一遍",
        "帮我升级那个翻译扩展",
        "这个功能模块旧了，更新下",
        "把这个扩展拉到最新",
        "帮我检查下有没有可以更新的插件",
        "想把这个能力升到新版本",
        "把过时的扩展都刷新一下",
        "帮我更新一下那个画图模块",
        "这个插件能更新吗，帮我更一下",
        "把所有扩展统一升级",
        "帮我把那个本事同步到最新版",
        "想给这个扩展打个补丁更新",
        "把装的所有插件都拉新",
    ],
    # ===== E. 列出已装/查看清单 =====
    "list": [
        "帮我看看现在都装了哪些扩展",
        "列一下已经加进来的本事",
        "现在 agent 有哪些功能模块",
        "帮我看下装了几个插件",
        "把已安装的扩展都列出来",
        "想知道现在有哪些能力可用",
        "帮我查下都加了哪些扩展",
        "现在装了哪些第三方插件",
        "列个清单看看 agent 的本事",
        "帮我看看已经装上的功能有哪些",
        "想确认下那个扩展装没装上",
        "把当前的扩展清单给我看看",
        "帮我盘点下装了哪些能力",
        "现在有几个扩展在用",
        "帮我列出全局和项目各装了啥",
    ],
    # ===== F. 概念/范围 =====
    "concept": [
        "内置的本事和我自己装的有啥区别",
        "装的扩展放在哪个目录",
        "装完要不要重启才能用",
        "全局装和项目装有什么不一样",
        "我自己装的会覆盖内置的吗",
        "装扩展需要什么环境",
        "这些扩展是从哪来的",
        "装完下次对话就能自动用上吗",
        "扩展装在用户目录还是项目目录",
        "重名的扩展谁优先生效",
        "装第三方扩展安全吗",
        "用户装的和系统自带的怎么区分",
        "扩展不用了会自动清理吗",
        "装的本事会同步到别的设备吗",
        "这个扩展机制是怎么工作的",
    ],
    # ===== G. 装完用不了/排错 =====
    "trouble": [
        "装了那个扩展但好像没生效",
        "插件装上了却调不出来",
        "装完报错了，帮我看看",
        "那个本事装了但 agent 不认",
        "扩展装好了重启也没用",
        "装的插件提示找不到，咋回事",
        "新加的能力没出现在列表里",
        "装扩展的时候失败了",
        "插件装一半卡住了",
        "装好的扩展用起来报错",
        "明明装了怎么还是不能用",
        "扩展装了但功能不对",
        "装的时候提示缺环境，怎么办",
        "插件冲突了，帮我排查",
        "装完之后老的功能也坏了",
    ],
    # ===== H. 从某来源装 =====
    "source": [
        "这个 github 链接的扩展帮我装上",
        "我给你个仓库地址，装里面那个本事",
        "从这个 npm 包装个插件进来",
        "这个 url 的扩展帮我加进项目",
        "我找到一个开源扩展，地址给你帮我装",
        "把这个仓库里指定名字的扩展装上",
        "从这个地址装个全局的能力",
        "这个作者做的插件帮我装一下",
        "我有个扩展的包名，帮我装",
        "从社区那个仓库里挑个扩展装上",
        "这个链接里有好几个扩展，装我要的那个",
        "帮我按这个地址把扩展拉下来装",
        "我贴个 repo，装它提供的本事",
        "从这个开源地址装个工具进来",
        "这个 npm 上的插件帮我加进来",
    ],
    # ===== I. 集成/挂载到 agent 或系统（治串到 deepwiki/lark-shared/channels）=====
    # 本质：把外部来源（代码平台/网上/npm）的「工具/能力」装载挂载到我的 agent / 系统 /
    # 工作流。区分信号：宾语是「给 agent 用的能力扩展」，动作是「集成/挂载/加载」——
    # 不是查仓库文档(deepwiki)，不是 cli 登录配置(lark-shared)。说法自拟，防泄漏。
    "integrate": [
        "把托管在代码平台上的那个工具组件整合进我的助手",
        "我想给当前这套工作流挂载一个外部的处理能力",
        "帮我把网上公开的那个辅助程序加载到运行环境里",
        "能不能把代码仓库里那套功能逻辑集成到我的助理",
        "帮我把这个第三方处理模块装载到对话系统里用",
        "想把社区做的那个增强项接到我的 agent 上",
        "把远程仓库里的功能套件部署进我的运行环境",
        "帮我给系统接一个能处理文档的外部组件",
        "想把那个开源的自动化逻辑引入到我的工作流里",
        "把网上看到的那个好用的能力挂到我的助手上",
        "帮我把一个外部脚本工具集成进当前的任务序列",
        "想给现在的对话逻辑添一个新的流程控制扩展",
        "把代码平台上那个分析组件封装成我助手的一项能力",
        "帮我从远端拉一套工具逻辑装载到本地的运行环境",
        "想让我的 agent 多一个外接的处理本事，帮我接上",
        "把这个公开的组件库引入到我的开发环境里用",
        "帮我把别人写好的那套增强逻辑挂载进系统",
        "想把一个外部来源的能力模块整合到当前助理",
    ],
}

SUBCAT = {
    "find": ("A", "搜找"),
    "install": ("B", "安装"),
    "remove": ("C", "卸载"),
    "update": ("D", "更新"),
    "list": ("E", "列出"),
    "concept": ("F", "概念"),
    "trouble": ("G", "排错"),
    "source": ("H", "指定来源"),
    "integrate": ("I", "集成挂载"),
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
            rec = {"text": text, "label": "skills-manager", "subcat": f"{code}-{name}"}
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")


def main():
    base = Path(__file__).resolve().parent
    items = dedupe(expand())
    print(f"手写池展开+去重后：{len(items)} 条")
    train, val, test = stratified_split(items, 800, 75, 75, seed=20260629)
    write_jsonl(base / "train" / "skills-manager.jsonl", train)
    write_jsonl(base / "val" / "skills-manager.jsonl", val)
    write_jsonl(base / "test" / "skills-manager.jsonl", test)
    print(f"train={len(train)} val={len(val)} test={len(test)}")
    for name, split in [("train", train), ("val", val), ("test", test)]:
        c = Counter(SUBCAT[cat][0] for _, cat in split)
        print(f"\n{name} 子语义分布（共 {len(split)}）：")
        for cat in SUBCAT:
            code = SUBCAT[cat][0]
            print(f"  {code}-{SUBCAT[cat][1]:<6} {c.get(code, 0):>3}")


if __name__ == "__main__":
    main()