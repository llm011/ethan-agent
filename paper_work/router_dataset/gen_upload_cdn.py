#!/usr/bin/env python3
"""生成 upload-cdn 训练样本（jsonl）。

upload-cdn = 把本地文件（图片/文档/视频等）上传到 S3/R2 等对象存储，返回一个
可公开访问的 URL，便于分享/嵌入/给别人下载。

子语义：
  A 传图片上云       B 传文件/文档/视频上云   C 传完要一个能访问的网址
  D 弄成别人也能打开的分享链接              E 放到对象存储/存储桶（S3/R2）
  F 边界（专治与 getnote「存笔记」串档）

★ 三池独立（防近邻泄漏）：
  POOL_TRAIN：覆盖广、多变体，主训练用。
  POOL_VAL  ：换一批说法，中等难度，不与 train 模板重叠。
  POOL_TEST ：最口语、最贴近真实用户——刻意加背景/上下文/省略/隐式意图，部分故意写长。

铁律：三池所有样本绝不含任一 trigger 原词子串：
  上传CDN | 上传图床 | upload cdn | 上传到CDN | 上传文件到云 | 获取外链 | 公开链接 | 图片外链
"""
from __future__ import annotations
import json
import random
from pathlib import Path
from collections import Counter

TRIGGERS = [
    "上传CDN", "上传图床", "upload cdn", "上传到CDN", "上传文件到云",
    "获取外链", "公开链接", "图片外链",
]

# ===================== POOL_TRAIN =====================
POOL_TRAIN: dict[str, list[str]] = {
    "upload_img": [
        "把这张图片传上去",
        "帮我把这张截图传到云上",
        "这张照片传一下，我要拿去用",
        "把这几张图都传上去存着",
        "帮我把这张图弄到存储里",
        "这张海报传上去我要嵌到网页里",
        "把手机拍的这张图上传一下",
        "帮我把这个 png 传到云端",
        "这张设计稿传上去给别人看",
        "把相册里这张图传到服务器上",
        "帮我把这张示意图传上去",
        "这张 logo 图传一下我要放到文档里",
        "把这张二维码图传到云上",
        "帮我把这几张产品图批量传上去",
        "这张封面图传上去我等下要用",
        "把刚生成的这张图传到存储",
        "帮我把这张流程图弄到云端存起来",
        "这张背景图传上去嵌进邮件里",
        "把这张 jpg 传上去",
        "帮我把这张头像传到云上",
        "这张图我要贴到别处，先传上去",
        "把这张长截图传上去存着",
    ],
    "upload_file": [
        "把这个文件传上去",
        "帮我把这个 pdf 传到云端",
        "这个视频传一下存到云上",
        "把这份文档传上去存着",
        "帮我把这个压缩包传到存储里",
        "这个 excel 表格传上去",
        "把本地这个安装包传到云端",
        "帮我把这段录音传上去",
        "这个 ppt 传一下我要发出去",
        "把这个 zip 传到服务器上存着",
        "帮我把这个 mp4 传到云上",
        "这份报告传上去我等下要用",
        "把这个日志文件传上去",
        "帮我把这个数据集文件传到云端",
        "这个 docx 传一下存起来",
        "把导出的这个 csv 传上去",
        "帮我把这个字体文件传到存储",
        "这段视频剪好了传上去存着",
        "把这个备份文件传到云上",
        "帮我把整个文件夹打包传上去",
        "这个 apk 传一下存到云端",
        "把这个音频文件传上去",
    ],
    "get_url": [
        "传完给我个能访问的网址",
        "传上去之后要一个能打开的地址",
        "帮我传一下然后给个链接",
        "上传好给我个可以点开的网址",
        "传完之后返回一个访问地址给我",
        "把它传上去，我要拿到那个网址",
        "传好后给我一串能直接打开的 url",
        "上传完把生成的地址发我",
        "传上去顺便给我个能访问的链接",
        "我要的是传完之后那个网址",
        "帮我传了给个可以浏览器打开的地址",
        "传上去后把 url 复制给我",
        "上传后要一个能在网上访问到的地址",
        "传完给我个能直接下载的链接",
        "把文件传了然后要它的访问网址",
        "传上去之后那串 http 地址给我",
        "上传成功后返回一个可访问的链接",
        "帮我传一下，重点是那个网址",
        "传完之后要个能远程访问的地址",
        "把图传了给我个能引用的 url",
        "上传后生成一个别人能访问的地址给我",
        "传上去拿个网址回来",
    ],
    "share": [
        "帮我弄成别人也能打开的链接",
        "传上去给个可以分享出去的网址",
        "我要一个能发给同事的地址",
        "弄个别人点了也能看的链接",
        "传一下生成个能分享的地址",
        "要一个发出去让别人下载的链接",
        "帮我做成一个大家都能访问的网址",
        "传上去然后给我个能转发的地址",
        "弄个链接我要发到群里让人下载",
        "生成一个别人也能打开的访问地址",
        "传好后给个可以贴到聊天里的网址",
        "我想把这个分享出去，给我个地址",
        "弄成能让客户直接点开的链接",
        "传上去要个谁都能访问到的网址",
        "帮我生成个能发人的地址",
        "做个链接，别人也能下载到这个文件",
        "传完给我个能分享给外部的网址",
        "弄个地址我要嵌到分享页面里",
        "生成一个可以发出去的下载链接",
        "帮我搞成一个能转给别人的访问地址",
        "传上去给个别人也能打开的 url",
        "要个能贴到微信里让人点开的地址",
    ],
    "store": [
        "把这个文件放到对象存储",
        "帮我传到 R2 上",
        "这个传到云存储桶里",
        "把它放进 S3",
        "帮我上传到对象存储的桶里",
        "这份文件存到 R2 存储桶",
        "把图片放到我们的对象存储上",
        "传到云上的存储桶存着",
        "帮我把这个丢到 S3 桶里",
        "这个视频放到对象存储里存",
        "把备份传到 R2 存储",
        "帮我把文件同步到对象存储桶",
        "这个存到云端的存储服务上",
        "把它上传进 S3 的 bucket",
        "帮我推到对象存储那边",
        "这批文件都放到存储桶里去",
        "把文档存到 R2 上留个备份",
        "帮我把它落到对象存储里",
        "这个传到云存储服务保存",
        "把图放进对象存储的桶",
        "帮我上传到 bucket 里存好",
        "这个文件归档到 S3 存储桶",
    ],
    "boundary": [
        "这张截图我要贴到别的地方，帮我传上去拿个网址",
        "这个 pdf 想分享给同事，给我个能直接打开的地址",
        "不是存到我笔记里，我要一个能在网上访问的地址",
        "别记到笔记本，帮我传上去生成个能分享的网址",
        "我要的是能贴到网页的地址，不是存进个人笔记",
        "把这个图传上去要个 url，我不是要收藏到笔记",
        "这份文档要发到外部，给我个别人能打开的地址",
        "不用存笔记，帮我弄个能让人下载的链接就行",
        "我想把它嵌到博客里，所以要一个能访问的网址",
        "这个不是记录用的，传上去给我个可分享的地址",
        "帮我传上去拿个能引用的地址，别往笔记里塞",
        "这张图要放进 PPT，给我个能远程访问的网址",
        "不是保存到我的知识库，我要一个能发出去的链接",
        "想把这文件挂到网上让人点，给个可访问地址",
        "这个要给客户看，传上去生成一个能打开的网址",
        "别存成笔记条目，帮我传一下返回个 url",
        "我要拿去别的系统引用，所以需要一个访问地址",
        "这个截图发群里用，传上去给个别人能看的链接",
        "不是要记下来，是要一个能在网上打开的地址",
        "帮我把它变成一个网上能访问的地址，不用存笔记",
        "这份材料要对外分享，给我个可以转发的网址",
        "想让它有个能直接打开的链接，不是收进笔记",
    ],
}

# ===================== POOL_VAL：换说法、中等难度 =====================
POOL_VAL: dict[str, list[str]] = {
    "upload_img": [
        "这张图往云上送一下",
        "截图帮我弄到存储那边",
        "把这个图档推到云端",
        "这几张图批量丢到存储里",
        "帮我把这张贴图挂到服务器上",
    ],
    "upload_file": [
        "把这份文件往云端推一下",
        "帮我把这个包丢到存储那边",
        "这个录音往云上传一下",
        "把这份材料弄到云端保存",
        "帮我把这个大文件同步上去",
    ],
    "get_url": [
        "传完给个能访问的地址就行",
        "帮我拿回那个 url",
        "上传后返回个网址给我",
        "传好把地址抛给我",
        "需要那个可以直接打开的链接",
    ],
    "share": [
        "做成个能发出去的链接",
        "生成个能让别人下载的地址",
        "要个能转发的网址",
        "弄个人家也能点开的链接",
        "给我个能对外发的地址",
    ],
    "store": [
        "往 S3 那边丢一份",
        "帮我同步到对象存储桶",
        "推到 R2 存储那边去",
        "把这个塞进 bucket 里",
        "同步到云存储服务保存",
    ],
    "boundary": [
        "我要的是网上能打开的地址，不是本地笔记那种",
        "要给对方发的，传上去给个别人能看的链接",
        "不是收藏备忘，我要个能贴到外面的网址",
        "这个要放到外部系统里用，所以要个可访问地址",
        "别存笔记了，我要的是个对外可用的 url",
    ],
}

# ===================== POOL_TEST：最口语、含背景/隐式意图 =====================
POOL_TEST: dict[str, list[str]] = {
    "upload_img": [
        "刚截了个图，帮我传上去，等下要发群里的",
        "设计同学给了张图，我得放到邮件里，先传上去拿个链接",
        "这张截图发微信图片质量太差，帮我传到云上引用好一点",
        "手里有张产品图，要嵌到官网里，帮我传一下",
        "拍了张报销凭证，传上去我再从链接下载",
    ],
    "upload_file": [
        "刚导出了一份报告，需要发给客户，帮我传上去生成个链接",
        "视频渲染完了挺大，直接发消息传不了，帮我传到云上",
        "这个 apk 打包好了，要给测试同学下，帮我传一下拿个地址",
        "有份 pdf 材料要在微信群里共享，传上去给个能下载的链接",
        "备份文件想存云上，帮我传到存储桶保存一份",
    ],
    "get_url": [
        "传完把那个地址直接甩给我就行，我知道怎么用",
        "不用说别的，传好给个 http 链接就完事了",
        "我就要那个 url，传完复制过来",
        "文件传好后把那个可以访问的地址返回给我，我要粘贴到文档里",
        "传上去之后把生成的访问地址告诉我一下",
    ],
    "share": [
        "这份合同要发给外部律师，帮我传上去弄个谁都能打开的链接",
        "产品录屏要发到社群里，帮我传上去生成个可以转发的地址",
        "同事让我把设计稿共享给他，传上去给个他能直接下载的链接就行",
        "这个包要给外包同学下，帮我搞个别人能点开的地址",
        "要挂到公告邮件里，传上去给个人家能访问的地址",
    ],
    "store": [
        "这批备份文件放 S3 就行，帮我传过去",
        "帮我把这个丢到 R2 存储桶里，不用给我网址",
        "往对象存储同步一份留底，帮我传过去",
        "想把静态资源都放到 bucket 里，帮我上传这批",
        "这个归档文件推到 S3 里存着就行",
    ],
    "boundary": [
        "这是要对外发布的设计稿，帮我传上去生成个能分享的链接，不是存我自己笔记的那种",
        "合同要发给对方律师，传上去给个别人能打开的地址，别存成我的备忘条目",
        "这张示意图要贴进 wiki，所以需要个能在外部访问的 url，不是本地收藏那种",
        "我要把这个放到外部文档里引用，需要个能远程访问的地址",
        "这个材料要发到客户那边，传上去给我个对外可访问的链接就行",
    ],
}

SUBCAT = {
    "upload_img": ("A", "传图片"),
    "upload_file": ("B", "传文件"),
    "get_url": ("C", "要网址"),
    "share": ("D", "分享链接"),
    "store": ("E", "对象存储"),
    "boundary": ("F", "边界"),
}


def check_no_trigger(text: str) -> None:
    low = text.lower()
    for t in TRIGGERS:
        if t.lower() in low:
            raise AssertionError(f"含 trigger 子串 [{t}]！→ {text}")


def expand_pool(pool: dict) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    mood = set("吧呢嘛啊吗了呀哦呐")
    for cat, sents in pool.items():
        for s in sents:
            out.append((s, cat))
            tail = s.rstrip()[-1] if s.strip() else ""
            if tail and tail not in mood and tail not in "？。！，；":
                for suf in ["呢", "啊", "吗", "？"]:
                    out.append((s + suf, cat))
    return out


def dedupe(items, seen=None):
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
    rng = random.Random(seed)
    by_cat: dict[str, list] = {}
    for text, cat in items:
        by_cat.setdefault(cat, []).append((text, cat))
    for cat in by_cat:
        rng.shuffle(by_cat[cat])
    if len(items) <= target_n:
        out = list(items)
        rng.shuffle(out)
        return out
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
            rec = {"text": text, "label": "upload-cdn", "subcat": f"{code}-{name}"}
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")


def main():
    base = Path(__file__).resolve().parent
    seen: set = set()
    test_raw = dedupe(expand_pool(POOL_TEST), seen)
    val_raw = dedupe(expand_pool(POOL_VAL), seen)
    train_raw = dedupe(expand_pool(POOL_TRAIN), seen)

    test = cap_per_split(test_raw, 75, seed=20260711)
    val = cap_per_split(val_raw, 75, seed=20260712)
    train = cap_per_split(train_raw, 500, seed=20260713)

    write_jsonl(base / "train" / "upload-cdn.jsonl", train)
    write_jsonl(base / "val" / "upload-cdn.jsonl", val)
    write_jsonl(base / "test" / "upload-cdn.jsonl", test)
    print(f"train={len(train)} val={len(val)} test={len(test)}")
    for split_name, split in [("train", train), ("val", val), ("test", test)]:
        c = Counter(SUBCAT[cat][0] for _, cat in split)
        print(f"\n{split_name} 子语义分布（共 {len(split)}）：")
        for cat in SUBCAT:
            code = SUBCAT[cat][0]
            print(f"  {code}-{SUBCAT[cat][1]:<6} {c.get(code, 0):>3}")


if __name__ == "__main__":
    main()
