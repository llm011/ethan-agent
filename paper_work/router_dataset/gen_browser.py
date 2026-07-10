#!/usr/bin/env python3
"""生成 use-browser 训练样本（jsonl）。

use-browser = 用浏览器完成网页上的实际操作：
  打开/跳转到某个站点某个页、在页面上点按钮填表单提交、给某页某区域截个图、
  读出页面上的内容/元素文字/表格、用已登录好的 Chrome 接着当前那个标签页带登录态干活、
  把一批链接挨个翻出来汇总多步串起来、写段脚本用代码控制页面自动跑一遍。

子语义：
  A nav        打开/跳转/导航到某站点某页
  B interact   点按钮/填表单/提交/勾选/下拉选择
  C screenshot 对某页面/某区域截个图
  D read       读取页面上的内容/某元素文字/表格数据
  E session    用已登录好的 Chrome / 接着当前开着的标签页 / 带登录态操作
  F batch      把多个页面数据挨个翻出来汇总 / 一批链接串起来多步处理
  G script     写段脚本自动跑一遍页面流程 / 用代码控制页面做条件判断
  H boundary   强调操作动作，区别于「文章总结」url-process 和「查开源仓库文档」deepwiki

铁律：绝不含 use/agent/dev 三个浏览器 skill 的任一 trigger 原词子串：
  浏览器 | 打开网页 | 网页操作 | 自动填表 | 网页截图 | 点击页面 | 输入文本
  | 操作我的浏览器 | 我的浏览器 | 本机 Chrome | 浏览器 cookie | 扩展工具
  | 真实 tab | 接管当前页面 | 抓取网页 | 爬网页 | 网页自动化脚本 | 批量抓取
  | 多步网页流程 | 遍历页面 | 登录网站 | 网页脚本 | playwright | 复杂网页流程
  | 多步网页操作 | 循环抓取 | browser script | scrape | automate web
（用同义绕开：用「Chrome / 那个站点 / 这个页面 / 这个网站 / 帮我在网上 / 在页面上」，
  动词「打开/跳转/填一下/点一下/截个图/读一下/翻页/自动跑一遍」，
  避开被禁连用子串——"网页操作""点击页面"不能连用，拆成"在这个站点上点一下那个按钮"）
"""
from __future__ import annotations
import json
import random
from pathlib import Path
from collections import Counter

TRIGGERS = [
    "浏览器", "打开网页", "网页操作", "自动填表", "网页截图", "点击页面", "输入文本",
    "操作我的浏览器", "我的浏览器", "本机 chrome", "浏览器 cookie", "扩展工具",
    "真实 tab", "接管当前页面", "抓取网页", "爬网页", "网页自动化脚本", "批量抓取",
    "多步网页流程", "遍历页面", "登录网站", "网页脚本", "playwright", "复杂网页流程",
    "多步网页操作", "循环抓取", "browser script", "scrape", "automate web",
]

POOL: dict[str, list[str]] = {
    # ===== A. nav 打开/跳转/导航到某站点某页 =====
    "nav": [
        "帮我用 Chrome 打开一下那个站点的首页",
        "跳转到那个网站的登录入口那一页",
        "帮我导航到这个网站的商品详情那页",
        "在 Chrome 里帮我打开这个链接的第二页",
        "帮我把那个站点的搜索结果那页调出来",
        "跳到这个网站里设置那栏对应的那页",
        "帮我在 Chrome 里跳转到订单列表那一页",
        "打开那个站点然后帮我进到个人中心那页",
        "帮我导航到这个网站后台的数据面板那页",
        "在 Chrome 里帮我打开这个站点的帮助文档那页",
        "跳到那个网站结算那一步的页面",
        "帮我打开这个站点里评论区那一页看看",
        "在 Chrome 里帮我进到那个网站的下载页面",
        "帮我跳转到这个网站里我的收藏那页",
        "打开那个站点帮我切到消息通知那一页",
        "帮我在 Chrome 里导航到这个网站的分类页",
        "跳到那个网站表单填写那一步的页面",
        "帮我打开这个站点然后进到发布内容那页",
        "在 Chrome 里帮我跳到那个网站的对账页面",
        "帮我导航到这个网站里售后申请那一页",
        "打开那个站点帮我翻到列表的下一页",
        "帮我在 Chrome 里进到这个网站的实名认证那页",
    ],
    # ===== B. interact 点按钮/填表单/提交/勾选/下拉 =====
    "interact": [
        "在这个站点上帮我点一下那个提交的按钮",
        "帮我把这个表单里的姓名那栏填一下",
        "在那个页面上帮我勾一下同意条款的框",
        "帮我在这个站点里把下拉框选成上海",
        "在页面上帮我点一下右上角那个登录的按钮",
        "帮我把这个表单的手机号那格填进去",
        "在这个网站上帮我点一下加入购物车",
        "帮我在那个页面里把数量改成三再点确认",
        "在这个站点上帮我把搜索框填好再点搜索",
        "帮我在页面上点一下那个下一步的按钮",
        "把这个表单里的地址那栏帮我填了",
        "在那个页面上帮我勾选前三条然后提交",
        "帮我在这个站点里把日期那个下拉挑成今天",
        "在页面上帮我点一下那个红色的确认按钮",
        "帮我把这个表单的备注框里填一句话",
        "在这个网站上帮我把开关拨到打开那一档",
        "帮我在那个页面里点一下展开更多选项",
        "把这个站点上的验证码那格帮我填进去",
        "在页面上帮我选中那个单选项再点保存",
        "帮我在这个表单里把邮箱那栏填好提交掉",
        "在那个站点上帮我点一下收藏那个小星星",
        "帮我把这个页面里的城市下拉换成北京",
    ],
    # ===== C. screenshot 对某页/某区域截个图 =====
    "screenshot": [
        "帮我给这个页面截个图发我看看",
        "把那个站点当前这一屏帮我截下来",
        "帮我对页面上那个表格区域截个图",
        "给这个网站的详情那块帮我截一张图",
        "帮我把这个页面顶部那条截个图存着",
        "在那个站点上帮我截一下报错提示那块",
        "帮我给这个页面完整地截一张长图",
        "把页面右侧那个栏帮我截个图给我",
        "帮我截一下这个站点结算那一步的画面",
        "给这个网站弹出来的那个框截张图我看",
        "帮我把页面上那张图表区域截下来",
        "在这个站点里帮我对那段文字截个图",
        "帮我给当前这个页面截图留个记录",
        "把那个网站的列表这一块帮我截一张",
        "帮我截一下页面底部那个提示条",
        "给这个页面中间那个卡片帮我截个图",
        "帮我对这个站点的价格那栏截一张图",
        "把页面上那个二维码区域帮我截下来",
        "帮我给这个网站的首页截个整屏图",
        "在那个页面上帮我截一下表单填完的样子",
    ],
    # ===== D. read 读取页面内容/元素文字/表格 =====
    "read": [
        "帮我把这个页面上那段正文的文字读出来",
        "在那个站点上帮我读一下那个价格是多少",
        "帮我把页面里那张表格的数据读出来给我",
        "读一下这个网站详情页里的规格参数",
        "帮我把这个页面标题那行字取出来",
        "在那个站点上帮我看看库存那栏写的啥",
        "帮我读出这个页面评论区前几条内容",
        "把这个网站列表里每一项的名字读给我",
        "帮我读一下页面上那个按钮上写的文字",
        "在这个站点里帮我把联系方式那块读出来",
        "帮我把这个页面里的日期和金额读出来",
        "读一下那个网站公告栏最新那条写了啥",
        "帮我把页面上那个表格的表头读给我",
        "在这个站点上帮我读出那段说明文字",
        "帮我看看这个页面里那个状态显示的是啥",
        "把这个网站详情里的发货地读出来给我",
        "帮我读一下页面右下角那行小字",
        "在那个站点里帮我把那几个数字取出来",
        "帮我读出这个页面表单已经填了哪些内容",
        "把这个网站里那份列表整个读一遍给我",
    ],
    # ===== E. session 用已登录好的 Chrome / 接当前标签页 / 带登录态 =====
    "session": [
        "用我已经登录好的 Chrome 帮我在那个站点上操作",
        "接着我现在开着的那个标签页帮我往下点",
        "帮我用登录态在这个网站里进到订单那页",
        "就用我当前这个已登录的会话帮我提交表单",
        "在我登录好的那个站点里帮我改一下资料",
        "接着当前打开的那个标签页帮我截个图",
        "用我这边已经登录的 Chrome 帮我读页面数据",
        "带着我的登录态在这个网站里下个单",
        "帮我在我已登录好的那个站点上点确认",
        "就用当前开着的这个标签页继续帮我填表",
        "用我登录着的会话帮我在这个网站发条内容",
        "接着我现在这个已登录的页面帮我翻下一页",
        "在我已经登录进去的那个站点里帮我查订单",
        "用我这个 Chrome 里已有的登录态帮我操作后台",
        "帮我在当前打开的那个标签页上点一下退出",
        "就着我登录好的那个网站帮我把地址改掉",
        "用我已登录的会话帮我在这个站点上勾选几项",
        "接着我现在这个标签页帮我把表单提交了",
        "带我的登录态去那个网站把消息标记成已读",
        "用我登录好的 Chrome 帮我在这个页面上点收藏",
        "在当前这个已登录的标签页里帮我读一下余额",
    ],
    # ===== F. batch 多个页面数据挨个汇总 / 一批链接多步串起来 =====
    "batch": [
        "把这几个链接挨个翻出来把数据汇总给我",
        "帮我一个个页面过一遍把标题都收集起来",
        "这一批链接帮我逐个打开读出价格再汇总",
        "帮我把这十来个页面里的内容依次收拢起来",
        "挨个翻这几页把每页那个数字都记下来",
        "帮我把这组链接一条条打开各截一张图",
        "这一串页面帮我依次进去把表格都取出来",
        "帮我把好几个站点的同一栏数据挨个汇到一起",
        "逐页帮我读一下把结果拼成一张表给我",
        "帮我把这批链接一个接一个走完再汇总结论",
        "挨个进这几个页面帮我把联系方式都收集了",
        "帮我把分好几页的列表一页页翻完拼起来",
        "这几个页面帮我顺着依次操作再把结果凑齐",
        "帮我把这组网址逐条打开各读一段汇给我",
        "一页一页帮我翻完把每条记录都攒下来",
        "帮我依次进这几个站点把库存数各记一下",
        "把这批链接挨个走一遍再把统计汇总出来",
        "帮我逐个打开这些页面把评论都收拢过来",
        "这几页数据帮我一页页取出来合成一份",
        "帮我把好几个页面串起来依次填表再提交",
    ],
    # ===== G. script 写脚本自动跑一遍 / 用代码控制页面做判断 =====
    "script": [
        "帮我写段脚本自动在这个站点上跑一遍这个流程",
        "用代码控制这个页面按条件判断该点哪个按钮",
        "帮我写个脚本让它自己在这个网站里翻页读数据",
        "拿代码帮我把这个站点上的填表提交自动跑起来",
        "帮我用脚本让这个页面遇到弹窗就自动关掉继续",
        "写点代码帮我在这个网站上判断有货就自动下单",
        "帮我用脚本把这个站点的登录到提交一条龙跑完",
        "用代码控制页面每翻一页就把数据存下来",
        "帮我写个脚本让它在这个网站里循环点下一步",
        "拿代码帮我判断这个页面出现某个字就停下截图",
        "帮我用脚本自动在这个站点上重复提交几十次表单",
        "写段代码让这个页面按我给的规则自动操作",
        "帮我用脚本把这个网站上的一套动作录下来重放",
        "用代码控制这个站点该勾选就勾选该提交就提交",
        "帮我写个脚本定时去这个页面刷新看有没有变化",
        "拿代码帮我在这个网站里按条件自动切换选项",
        "帮我用脚本让页面加载完就自动把表单填好发出去",
        "写点代码帮我控制这个站点一步步走完整个流程",
        "帮我用脚本判断这个页面某个价格低于阈值就下单",
        "用代码帮我把这个网站上的翻页读数写成自动的",
    ],
    # ===== H. boundary 强调操作动作，区别 url-process / deepwiki =====
    "boundary": [
        "在这个站点里帮我把那个下拉框选成上海再点确认",
        "不是让你总结这篇文章，是帮我在这个页面上点提交",
        "别光读，帮我在这个网站上把那个开关拨开",
        "在这个页面上帮我把数量填成二再点结算",
        "不用给我讲解，帮我在这个站点里点一下购买",
        "在这个网站上帮我把筛选条件挑好再点应用",
        "别去查文档，帮我在这个页面上把表单交了",
        "在这个站点里帮我先勾同意再点下一步走完",
        "不是要文章摘要，是帮我在这个页面点收藏",
        "在这个网站上帮我把地址改成新的再保存",
        "帮我在这个页面上把下拉挑成北京然后提交",
        "别只读内容，帮我在这个站点里点那个确认键",
        "在这个页面上帮我把验证码填了再点登录进去",
        "不用解释仓库，帮我在这个站点上点开设置那栏",
        "在这个网站里帮我把选项切成月付再点确定",
        "帮我在这个页面上把那三项勾上然后一起提交",
        "别做总结，帮我在这个站点里把那个按钮点了",
        "在这个页面上帮我把时间选成明天再点预约",
        "不是查资料，是帮我在这个网站上真的下单",
        "在这个站点里帮我把开关关掉再点保存生效",
    ],
}

SUBCAT = {
    "nav": ("A", "导航"),
    "interact": ("B", "交互"),
    "screenshot": ("C", "截图"),
    "read": ("D", "读取"),
    "session": ("E", "登录态"),
    "batch": ("F", "批量"),
    "script": ("G", "脚本"),
    "boundary": ("H", "浏览边界"),
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
            rec = {"text": text, "label": "use-browser", "subcat": f"{code}-{name}"}
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")


def main():
    base = Path(__file__).resolve().parent
    items = dedupe(expand())
    print(f"手写池展开+去重后：{len(items)} 条")
    train, val, test = stratified_split(items, 500, 75, 75, seed=20260711)
    write_jsonl(base / "train" / "use-browser.jsonl", train)
    write_jsonl(base / "val" / "use-browser.jsonl", val)
    write_jsonl(base / "test" / "use-browser.jsonl", test)
    print(f"train={len(train)} val={len(val)} test={len(test)}")
    for name, split in [("train", train), ("val", val), ("test", test)]:
        c = Counter(SUBCAT[cat][0] for _, cat in split)
        print(f"\n{name} 子语义分布（共 {len(split)}）：")
        for cat in SUBCAT:
            code = SUBCAT[cat][0]
            print(f"  {code}-{SUBCAT[cat][1]:<6} {c.get(code, 0):>3}")


if __name__ == "__main__":
    main()
