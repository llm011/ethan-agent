#!/usr/bin/env python3
"""生成 lark-doc 训练样本（jsonl）。

lark-doc = 飞书云文档（Docx / Wiki）的内容读写：
  把某篇在线协作文档的正文拉出来读、新建一篇 docx/wiki 页、往文档里追加或
  改写某段、下载/插入文档里的图片、把整篇导出成 markdown 存本地、只读文档
  的某一节。对象始终是「云文档内容」，不是「发消息」也不是「登录配置」。

子语义：
  read     帮我读一下这篇云文档/这个 wiki 讲了啥/把在线文档内容拉出来
  create   新建一篇文档/起一个 docx/建个 wiki 页
  edit     在文档后面追加内容/改一下文档里某段/往文档插一段话
  image    把文档里的图片下载/往文档里插张图/文档图片附件导出
  export   把整篇在线文档导出成 markdown/存成本地 md 文件
  scope    只读文档某一节/局部读取某个章节/抓文档里某个部分
  boundary 强调「文档内容读写」而非「发消息/登录配置」，避开 lark-im / lark-shared 串档

铁律：绝不含以下子串（避开与 lark-im 串档）：
  飞书 | lark | 发消息 | 群聊 | im消息 | 消息 | 群成员 | 飞书群
（说「云文档」「在线文档」「这篇 docx」「wiki 页面」「知识库里的文档」，
  不带"飞书"字样，不说"发消息/群聊"。用户常给文档 URL/token，可含
  "这个链接的文档""这个 token 对应的文档"，但别带"飞书"。）
"""
from __future__ import annotations
import json
import random
from pathlib import Path
from collections import Counter

TRIGGERS = [
    "飞书", "lark", "发消息", "群聊", "im消息", "消息", "群成员", "飞书群",
]

POOL: dict[str, list[str]] = {
    # ===== read 读取云文档正文 =====
    "read": [
        "帮我读一下这篇云文档到底讲了啥",
        "把这个在线文档的内容拉出来给我看看",
        "这个 wiki 页面写了些什么，帮我念一遍",
        "帮我把这篇 docx 的正文整理出来",
        "这个链接的文档内容帮我抓下来读读",
        "把知识库里那篇文档的要点提给我",
        "帮我看看这个 token 对应的文档说了什么",
        "这篇在线协作文档帮我通读一下讲讲重点",
        "把这个云文档里的正文全部取出来",
        "帮我读这个 wiki 里那一页的内容",
        "这个文档链接打开后写了啥，帮我看下",
        "帮我把这份在线文档的大意概括一下",
        "把这个 docx 里的文字内容读给我听",
        "这篇知识库文档帮我拉全文看看",
        "帮我获取这个链接文档的正文文本",
        "把在线文档里写的东西帮我梳理成要点",
        "这个 token 的文档内容帮我调出来看",
        "帮我读完这篇云文档告诉我结论",
        "把这个 wiki 页面的正文帮我导出来读",
        "帮我把这份在线文档从头到尾过一遍",
        "这个协作文档里都写了什么，拉出来给我",
        "帮我把这篇 docx 内容读出来做个摘要",
    ],
    # ===== create 新建文档 =====
    "create": [
        "帮我新建一篇云文档准备写点东西",
        "起一个空的 docx 我要往里写",
        "帮我建个 wiki 页面记录这个项目",
        "新开一篇在线文档取名叫周报",
        "帮我创建一个云文档标题写成会议纪要",
        "起一份新的在线文档我要开始记",
        "帮我在知识库里新建一页文档",
        "新建一个 docx 帮我把标题填好",
        "帮我开一篇空白云文档等下往里补内容",
        "创建一个 wiki 页帮我起个名字",
        "帮我建一份新的在线协作文档",
        "起个新文档命名成需求清单",
        "帮我在知识库新起一页写设计方案",
        "新建一篇 docx 标题就叫今日总结",
        "帮我开一个空的在线文档待会儿粘贴内容",
        "创建一份云文档准备放调研结果",
        "帮我起一个 wiki 页面存这次讨论",
        "新建个在线文档帮我把框架搭起来",
        "帮我建一篇文档标题写项目复盘",
        "起一份空白 docx 我马上要写东西进去",
        "帮我在知识库里创建一个新页面",
        "新开一篇云文档命名为测试记录",
    ],
    # ===== edit 编辑/追加文档内容 =====
    "edit": [
        "在这篇文档后面帮我追加一段内容",
        "帮我把这个 docx 里那段话改一改",
        "往这篇云文档里插一段话进去",
        "帮我在文档结尾补上一句总结",
        "把在线文档里第二段帮我重写一下",
        "帮我往这个 wiki 页里加个小标题",
        "在这篇文档中间帮我插入一段说明",
        "帮我把 docx 里那句错的改正过来",
        "往这份在线文档末尾追加今天的进展",
        "帮我在文档开头加一段引言",
        "把这个云文档里的某段替换成新内容",
        "帮我给这篇文档补一个结论段落",
        "在 wiki 页面那一节后面帮我续写几句",
        "帮我把在线文档里过时的那段删改一下",
        "往这篇 docx 里插一个新的段落",
        "帮我在文档最后加一行备注",
        "把这个链接文档里那段帮我扩充一下",
        "帮我在协作文档里补上遗漏的那一条",
        "往这个云文档追加一段会议要点",
        "帮我改一下文档里那个小标题的措辞",
        "在这份在线文档里插入一段代码说明",
        "帮我把 docx 那段内容重新组织下语言",
    ],
    # ===== image 文档图片下载/插入/导出 =====
    "image": [
        "把这篇文档里的图片帮我下载下来",
        "帮我往这个 docx 里插一张图",
        "把在线文档里的那几张配图导出来",
        "帮我把云文档里的图片附件保存到本地",
        "往这篇文档中间插入一张示意图",
        "帮我把 wiki 页里的图片全都下下来",
        "把这个链接文档里的插图提取出来",
        "帮我在 docx 指定位置放一张截图",
        "把在线文档里的图片附件批量导出",
        "帮我下载这篇协作文档里的所有配图",
        "往这个云文档末尾插一张流程图",
        "帮我把文档里那张表格图片存下来",
        "把这篇 docx 里的图都抠出来给我",
        "帮我给在线文档里补一张封面图",
        "把 wiki 页面里的图片保存成文件",
        "帮我把文档正文里的插图逐个下载",
        "往这份文档里插入我给你的这张图",
        "帮我导出这个云文档里的图片素材",
        "把在线文档里那张架构图取下来",
        "帮我在 docx 开头插一张 logo 图片",
    ],
    # ===== export 导出整篇为 markdown =====
    "export": [
        "把整篇在线文档帮我导出成 markdown",
        "帮我把这个云文档存成本地的 md 文件",
        "这篇 docx 帮我转成 markdown 保存下来",
        "把这个 wiki 页面导出成 md 文档",
        "帮我把整份在线文档下载成 markdown 格式",
        "这个链接的文档帮我导成 md 存到本地",
        "把云文档全文转成 markdown 给我",
        "帮我把这篇协作文档保存成 md 文件",
        "整篇 docx 帮我导出成 markdown 文本",
        "把这个 token 对应的文档转成 md",
        "帮我把知识库里那页导出成 markdown",
        "这篇在线文档帮我落地成本地 md",
        "把整个文档内容帮我保存成 markdown 文件",
        "帮我将这个云文档导出为 markdown 备份",
        "这个 wiki 页帮我转 markdown 存起来",
        "把这份在线文档整篇下成 md 格式给我",
        "帮我把 docx 全文导出成 markdown 归档",
        "这个链接文档帮我转成 md 文件收好",
        "把云文档从头到尾导出成 markdown",
        "帮我把这篇文档存成 md 放到本地目录",
    ],
    # ===== scope 局部读取某一节/章节 =====
    "scope": [
        "只帮我读这篇文档的第一节就行",
        "帮我把在线文档里那个章节单独抓出来",
        "只要这个 docx 里第三部分的内容",
        "帮我读文档里标题叫背景的那一段",
        "把这篇云文档的结论那节单独拉出来",
        "只局部读一下 wiki 页面里那个小节",
        "帮我抓文档里关于方案那一章的内容",
        "只要在线文档最后一节的文字给我",
        "帮我把 docx 里第二章单独读出来",
        "把这个链接文档中间那部分截取给我",
        "只读云文档里那个表格所在的小节",
        "帮我取这篇文档里概述那一段就好",
        "把 wiki 页里那个特定标题下的内容拉出",
        "只要在线文档开头那一节的正文",
        "帮我读一下文档里风险那一章讲了啥",
        "把这个 docx 里指定的那一小节抽出来",
        "只局部取一下文档里那个步骤清单",
        "帮我把云文档里附录那节单独读出",
        "只要这篇文档某个章节的内容不用全篇",
        "帮我抓在线文档里那个子标题下的段落",
    ],
    # ===== boundary 强调文档内容读写（区别于发消息/登录配置）=====
    "boundary": [
        "给我这个 docx 链接里的正文整理出来",
        "这篇在线协作文档帮我加个小标题",
        "我要的是这份云文档的内容不是别的",
        "帮我处理这个文档正文别去动其它东西",
        "只在这篇在线文档里读写内容就好",
        "帮我把这个链接文档的文字内容拿出来",
        "我给你的是文档地址，帮我读它的正文",
        "这个 token 是一篇云文档，帮我编辑内容",
        "帮我在这份在线文档里改正文，不是配置",
        "把这篇 docx 的段落内容帮我梳理清楚",
        "我要在云文档里写内容不是要设置什么",
        "帮我读这个协作文档的正文汇报给我",
        "这个链接指向一篇文档，帮我导出它内容",
        "帮我在在线文档里补正文，别管登录那些",
        "只针对这篇文档的文字做读取和修改",
        "给我这个 wiki 页的正文，不要别的操作",
        "帮我把这份在线文档的内容读全整理好",
        "我要编辑的是文档里的段落文字本身",
        "帮我围绕这个 docx 的正文做增删改",
        "这个链接是篇云文档，帮我把内容拉出来读",
    ],
}

SUBCAT = {
    "read": ("A", "读取"),
    "create": ("B", "新建"),
    "edit": ("C", "编辑"),
    "image": ("D", "图片"),
    "export": ("E", "导出"),
    "scope": ("F", "局部"),
    "boundary": ("G", "文档边界"),
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
            rec = {"text": text, "label": "lark-doc", "subcat": f"{code}-{name}"}
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")


def main():
    base = Path(__file__).resolve().parent
    items = dedupe(expand())
    print(f"手写池展开+去重后：{len(items)} 条")
    train, val, test = stratified_split(items, 500, 75, 75, seed=20260711)
    write_jsonl(base / "train" / "lark-doc.jsonl", train)
    write_jsonl(base / "val" / "lark-doc.jsonl", val)
    write_jsonl(base / "test" / "lark-doc.jsonl", test)
    print(f"train={len(train)} val={len(val)} test={len(test)}")
    for name, split in [("train", train), ("val", val), ("test", test)]:
        c = Counter(SUBCAT[cat][0] for _, cat in split)
        print(f"\n{name} 子语义分布（共 {len(split)}）：")
        for cat in SUBCAT:
            code = SUBCAT[cat][0]
            print(f"  {code}-{SUBCAT[cat][1]:<6} {c.get(code, 0):>3}")


if __name__ == "__main__":
    main()
