#!/usr/bin/env python3
"""生成 computer-use 训练样本（jsonl）。

computer-use = 控制本机 macOS 桌面 GUI + 原生 App 自动化：
  给屏幕拍图看现状、用鼠标戳/拖、往输入框敲字/按快捷键、把某程序调出来、
  滚动窗口、让系统自带的记事/记日程那类原生 app 干活。

子语义：
  A capture   给当前屏幕/某窗口拍张图看看现在什么样
  B mouse     用鼠标戳某个位置/拖动某个东西/双击那个图标
  C keyboard  往输入框里敲字/按快捷键/回车确认
  D launch    把某个程序调出来/切到某个已开软件/退出某 app
  E scroll    往下滚一屏/滚到底/翻到某处
  F appscript 让系统自带的记事那个新建一条/记日程软件里排个会（原生 app 自动化）
  G boundary  区别于浏览器操作：对象是桌面原生程序/系统窗口而非网页

铁律：绝不含 computer-use + macos-automation 两个 skill 的任一 trigger 原词子串：
  截图 | 操作电脑 | 控制桌面 | 鼠标点击 | 键盘输入 | 打开应用 | 打开软件 | GUI
  | 桌面自动化 | computer use | take screenshot | click | type on screen
  | open app | desktop | scroll screen | drag | 滴答清单 | 提醒事项 | 日历
  | 备忘录 | 待办 | 创建会议 | 新建笔记 | AppleScript | osascript | 自动化
（用同义替换：截图→给屏幕拍一张；打开应用→把某某程序调出来；鼠标点击→用鼠标戳一下；
  键盘输入→敲几个字进去；日历/提醒事项/备忘录→我那个记日程的 app / 系统自带的记事那个 /
  定闹钟提醒那个）
"""
from __future__ import annotations
import json
import random
from pathlib import Path
from collections import Counter

TRIGGERS = [
    "截图", "操作电脑", "控制桌面", "鼠标点击", "键盘输入", "打开应用", "打开软件",
    "gui", "桌面自动化", "computer use", "take screenshot", "click", "type on screen",
    "open app", "desktop", "scroll screen", "drag", "滴答清单", "提醒事项", "日历",
    "备忘录", "待办", "创建会议", "新建笔记", "applescript", "osascript", "自动化",
]

POOL: dict[str, list[str]] = {
    # ===== A. capture 给屏幕/窗口拍张图看现状 =====
    "capture": [
        "给屏幕拍一张我看看现在是什么样",
        "帮我把当前画面拍下来发我",
        "把现在这个窗口拍个图给我瞧瞧",
        "看不清现在屏上啥情况，帮我拍一张",
        "把整个屏幕的样子记录成一张图",
        "现在屏上有个弹窗，帮我拍下来",
        "拍一下当前这个软件的界面给我",
        "帮我留个当前屏幕的影像看看进度",
        "把最上面那个窗口的样子拍给我",
        "现在这一屏帮我抓个图存着",
        "拍张当前画面，我想看现在停在哪了",
        "帮我把这个报错框拍个图我瞅瞅",
        "屏上那行提示帮我拍下来发过来",
        "把现在这个界面存成一张图片",
        "帮我看看屏幕现在长啥样，拍一张",
        "当前这个页面的样子帮我抓一张图",
        "拍一下现在活动的那个窗口",
        "帮我把桌面现在的画面记录一张",
        "现在屏上显示的内容帮我拍个图",
        "把这个对话框的样子拍下来给我",
        "帮我抓一张现在屏幕的实时画面",
        "拍下当前这个程序停在的那一屏",
    ],
    # ===== B. mouse 鼠标戳/拖/双击 =====
    "mouse": [
        "用鼠标帮我戳一下右上角那个按钮",
        "帮我在那个图标上戳两下把它点开",
        "把这个文件用鼠标拖到旁边那个文件夹里",
        "帮我用鼠标戳一下确定那个按钮",
        "在屏幕中间那个位置帮我戳一下",
        "把这个窗口用鼠标拽到左边去",
        "帮我在那个图标上双戳一下打开它",
        "用鼠标把这个滑块往右拨一点",
        "帮我戳一下左下角那个小三角",
        "把这条内容用鼠标选中拖走",
        "在那个下拉框上帮我戳一下展开",
        "用鼠标戳中屏幕上那个红点",
        "帮我把这个图标拽到程序坞上",
        "在关闭那个叉上帮我戳一下",
        "用鼠标把这两个东西之间连一下线",
        "帮我戳一下屏幕正中央那个开始",
        "把这块区域用鼠标框选出来",
        "在那个复选框上帮我戳一下勾上",
        "用鼠标把进度条拖到一半的位置",
        "帮我戳右键调出那个菜单",
        "把这个窗口边缘用鼠标拉大一点",
        "在那个链接位置帮我用鼠标戳一下",
    ],
    # ===== C. keyboard 敲字/快捷键/回车 =====
    "keyboard": [
        "往那个输入框里帮我敲几个字进去",
        "帮我在搜索栏敲上我要找的关键词",
        "在这个框里替我敲一段文字",
        "帮我按一下回车确认",
        "敲个保存的快捷键帮我存一下",
        "帮我按住那个组合键把它复制走",
        "在名字那栏敲上张三帮我填了",
        "帮我敲一串数字进这个格子",
        "按撤销的快捷键帮我退回上一步",
        "在这个框里敲完之后帮我按确认",
        "帮我用快捷键把这段全选了",
        "往密码框里敲上我给你的那串字符",
        "帮我按一下全选再按删除",
        "在这个位置敲几个字母进去",
        "帮我用键盘把光标挪到行尾",
        "敲个粘贴的快捷键把内容放进来",
        "帮我在标题栏敲上今天的日期",
        "按下那个组合键帮我切换输入法",
        "帮我往这个多行框里敲一段话",
        "在弹出的框里敲个是然后确认",
        "帮我用键盘按方向键往下挪一格",
        "敲个刷新的快捷键帮我重载一下",
    ],
    # ===== D. launch 调出程序/切换/退出 =====
    "launch": [
        "帮我把那个记事的程序调出来",
        "把音乐那个软件给我唤起来",
        "帮我切到已经开着的那个聊天窗口",
        "把后台那个程序切到前面来",
        "帮我退出那个卡住的程序",
        "把访达给我调出来",
        "帮我启动一下那个写代码的软件",
        "切到我刚才开的那个表格程序",
        "把这个不用的程序帮我关掉",
        "帮我唤起系统设置那个界面",
        "把那个看图的软件调到最前面",
        "帮我重启一下那个没响应的程序",
        "把终端那个程序给我叫出来",
        "帮我切换到另一个已经开着的软件",
        "把这个程序最小化收起来",
        "帮我把计算器那个小程序调出来",
        "退出当前这个软件帮我关干净",
        "把邮件那个程序唤到前台",
        "帮我在程序坞上把那个软件启动起来",
        "切到我上一个用的那个窗口",
        "帮我把这个程序彻底关掉重开",
        "把系统偏好那个面板调出来给我",
    ],
    # ===== E. scroll 滚动窗口/翻页 =====
    "scroll": [
        "帮我把这个窗口往下滚一屏",
        "在这个页面里往下多滚一点",
        "帮我一直滚到最底下",
        "把这个列表往上翻回顶部",
        "帮我往下翻，找到那条记录停下",
        "在这个长文档里往下滚几屏",
        "帮我把内容滚到中间那部分",
        "往下拉一直拉到看见提交按钮",
        "帮我把这一屏往右边挪一点",
        "在这个框里帮我慢慢往下滚",
        "把这个页面翻到最上面去",
        "帮我往下滚看看后面还有啥",
        "在侧边栏里往下翻到底",
        "帮我把画面往下带一屏继续看",
        "滚到能看见那个表格的地方",
        "帮我在聊天记录里往上翻旧的",
        "把这个窗口内容往下带到结尾",
        "帮我一屏一屏往下过一遍",
        "在这个界面里往下翻到设置那栏",
        "帮我把长图往下滑看完整个",
    ],
    # ===== F. appscript 原生 app 自动化（避开禁词）=====
    "appscript": [
        "让系统自带的记事那个新建一条内容记下来",
        "在我那个记日程的 app 里帮我排个会",
        "帮我在定闹钟提醒那个 app 里加一项",
        "让记事那个程序帮我存一段文字",
        "在我记日程那个软件里安排明天上午一个事项",
        "帮我在系统自带的记事里开一条新的写点东西",
        "让定时提醒那个 app 帮我加个下午三点的提醒",
        "在我那个记事程序里把这段话保存进去",
        "帮我在记日程的软件里把这周五占个时间段",
        "让系统的记事那个新起一条把要点列进去",
        "在提醒那个 app 里帮我建个明早的提醒",
        "帮我用记日程那个软件排个下周一的碰头时间",
        "让记事程序帮我记下这几条要点",
        "在定闹钟提醒那个 app 里加条买菜的提醒",
        "帮我在系统记事里新开一页写会议纪要",
        "让记日程那个 app 帮我把周四那个时间段标上",
        "在我那个提醒 app 里加个晚上八点的事项",
        "帮我让记事程序把这段内容存成新的一条",
        "在记日程软件里帮我把这个约见排进去",
        "让系统自带记事那个新建一条待记的东西",
        "帮我在提醒那个程序里设一条每天早上的提醒",
        "让我那个记日程 app 帮我腾个明天下午的空档排事",
    ],
    # ===== G. boundary 桌面原生对象（区别于网页/浏览器）=====
    "boundary": [
        "帮我把访达里那个下载文件夹打开",
        "在系统设置里帮我把音量调低一点",
        "帮我在访达里找到那个文件夹展开看看",
        "去系统设置里把亮度帮我调高",
        "帮我把桌面上那个文件夹的窗口打开",
        "在系统偏好里帮我把 Wi-Fi 关一下",
        "帮我在访达里把这个文件夹重命名",
        "去系统设置那里把蓝牙帮我打开",
        "帮我把程序坞里那个文件夹展开",
        "在访达窗口里帮我切到列表视图",
        "帮我在系统设置里把深色模式开起来",
        "去访达里把这个文件夹拖到收藏栏",
        "帮我把系统那个音量面板调出来拉一下",
        "在系统设置里帮我改一下屏保时间",
        "帮我把访达侧边栏里那个位置点开",
        "去系统偏好里把通知帮我关一段时间",
        "帮我在本机的文件管理器里新建个文件夹",
        "在系统设置里帮我把键盘重复速率调快",
        "帮我把桌面右上角那个系统菜单拉下来",
        "去访达里帮我把这个文件夹里的东西按大小排",
    ],
}

SUBCAT = {
    "capture": ("A", "拍图"),
    "mouse": ("B", "鼠标"),
    "keyboard": ("C", "键盘"),
    "launch": ("D", "启动"),
    "scroll": ("E", "滚动"),
    "appscript": ("F", "原生脚本"),
    "boundary": ("G", "桌面边界"),
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
            rec = {"text": text, "label": "computer-use", "subcat": f"{code}-{name}"}
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")


def main():
    base = Path(__file__).resolve().parent
    items = dedupe(expand())
    print(f"手写池展开+去重后：{len(items)} 条")
    train, val, test = stratified_split(items, 500, 75, 75, seed=20260711)
    write_jsonl(base / "train" / "computer-use.jsonl", train)
    write_jsonl(base / "val" / "computer-use.jsonl", val)
    write_jsonl(base / "test" / "computer-use.jsonl", test)
    print(f"train={len(train)} val={len(val)} test={len(test)}")
    for name, split in [("train", train), ("val", val), ("test", test)]:
        c = Counter(SUBCAT[cat][0] for _, cat in split)
        print(f"\n{name} 子语义分布（共 {len(split)}）：")
        for cat in SUBCAT:
            code = SUBCAT[cat][0]
            print(f"  {code}-{SUBCAT[cat][1]:<6} {c.get(code, 0):>3}")


if __name__ == "__main__":
    main()
