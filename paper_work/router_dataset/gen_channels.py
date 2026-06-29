#!/usr/bin/env python3
"""生成 channels 训练样本（jsonl）。

channels = 消息渠道接入配置：飞书 WebSocket 长连接配置与使用，未来支持微信/Telegram/Slack。
注意：这是个窄技能，与 lark-im / lark-shared 边界要分清——
  channels = 「把外部渠道接进来、建长连接、配凭据、连通性」这一层基础设施；
  lark-im  = 接进来之后「收发信息/管群」的业务；
  lark-shared = lark-cli 工具本身的「登录/身份/权限」。

子语义（现有 + 未来）：
  A 配飞书长连接/建立连接   B 填 App 凭据/接入配置   C 连接状态/掉线排查
  D 重启服务让配置生效      E 新渠道接入（微信/TG/Slack）  F 渠道概念/能不能不用公网
  G 实时收发基座/事件流底座（说得清的：强调"实时事件流/长连接监听/收发底座"基础设施本质）

注（治串到 lark-shared）：外部 test 大量 channels 句被判 lark-shared。纯"实时对接/
配置在哪"无基础设施信号的属真两可，放弃；带"实时事件流/长连接监听/收发基座/推送底座/
监听外部平台发言"锚点的说得清——本质=搭实时收外部事件的长连接底座，区别于 cli 登录配置
(lark-shared)。G 子类强化这部分，说法自拟防泄漏。

铁律：绝不含任一 trigger 原词子串：
  渠道 | channel | 飞书配置 | lark配置 | 接入 | webhook | websocket | 消息渠道
（「接入」被屏蔽 → 用「接进来/对接/连上」；「飞书配置」整短语屏蔽，但「飞书」单独可用）
"""
from __future__ import annotations
import json
import random
from pathlib import Path
from collections import Counter

TRIGGERS = [
    "渠道", "channel", "飞书配置", "lark配置", "接入", "webhook", "websocket", "消息渠道",
]

POOL: dict[str, list[str]] = {
    # ===== A. 配飞书长连接/建立连接 =====
    "connect": [
        "帮我把飞书的长连接建起来",
        "怎么让飞书的事件推过来",
        "我想让 Ethan 收到飞书那边的事件",
        "飞书的持久连接怎么搭",
        "帮我打通飞书和本地服务的通道",
        "想让飞书消息实时推到我这边",
        "飞书那边的事件怎么订阅过来",
        "帮我配一下飞书的长链路",
        "我要让机器人持续监听飞书事件",
        "飞书的事件流怎么连进来",
        "帮我建立飞书到本地的双向连接",
        "想用长连接的方式收飞书事件",
        "飞书的实时推送怎么开通",
        "帮我把飞书事件监听跑起来",
        "我想让飞书的来信走长连接进来",
        "帮我开通飞书的事件实时接收",
        "飞书那边的动静怎么同步到本地",
        "想让本地服务一直挂着等飞书事件",
        "帮我把飞书的事件通道连通",
        "飞书的来往信息怎么实时同步进来",
        "我想搭一条飞书到 Ethan 的实时链路",
        "帮我让飞书事件源源不断推进来",
        "飞书的长连保持在线怎么弄",
        "想让飞书来的东西自动进系统",
        "帮我把飞书侧的事件订阅打通",
    ],
    # ===== B. 填 App 凭据/接入配置 =====
    "cred": [
        "飞书的 App ID 和密钥填在哪",
        "帮我把飞书应用的凭据配上",
        "在哪里填飞书自建应用的 key",
        "我想把飞书的应用凭据录进去",
        "飞书的 appid 和 secret 怎么设置",
        "帮我在设置里加上飞书的应用信息",
        "飞书应用的密钥要配到哪个地方",
        "我想把飞书的应用凭据录进去",
        "帮我把飞书企业应用的参数配好",
        "飞书那边的凭据怎么对接进系统",
        "想知道飞书应用配置填哪些字段",
        "帮我录入飞书应用的 ID 和 Secret",
        "飞书的鉴权信息配在哪个面板",
        "我把飞书应用建好了，凭据填哪",
        "帮我把飞书的应用密钥设进去",
        "飞书后台拿到的 key 填到系统哪里",
        "帮我把飞书机器人的凭据对上",
        "应用的 secret 配置在哪个设置项",
        "想把飞书的凭据保存到系统里",
        "飞书企业应用的密钥怎么录进来",
        "帮我配置飞书应用的鉴权参数",
        "飞书的 app 凭据填错了怎么改",
        "在哪改飞书应用的 ID 和密钥",
        "帮我核对下填的飞书凭据对不对",
        "飞书的应用凭据怎么安全地存进去",
    ],
    # ===== C. 连接状态/掉线排查 =====
    "status": [
        "飞书的连接是不是断了",
        "帮我看下飞书那条长连接还在不在",
        "怎么检查飞书连接的状态",
        "飞书事件突然收不到了，咋回事",
        "帮我排查下飞书连不上的问题",
        "飞书的实时推送好像挂了",
        "连接老是掉，帮我看看原因",
        "怎么确认飞书事件监听是正常的",
        "飞书那边的信息收不到了帮我查查",
        "帮我看下长连接的健康状态",
        "飞书连接一会儿就断，怎么稳住",
        "想确认飞书事件流有没有正常工作",
        "帮我诊断下飞书连接异常",
        "飞书的监听进程是不是死了",
        "连接状态怎么查，老是不稳定",
        "飞书事件延迟很大，帮我看看",
        "怎么知道飞书的长连有没有掉线",
        "帮我看看连接日志有没有报错",
        "飞书连上又断，反复横跳怎么办",
        "帮我确认下事件订阅还活着没",
        "飞书来信延迟好几分钟正常吗",
        "连接断了能不能自动重连",
        "帮我看下最近的连接断开记录",
        "飞书事件偶尔丢，帮我查原因",
        "怎么监控飞书连接是否在线",
    ],
    # ===== D. 重启服务让配置生效 =====
    "restart": [
        "改完配置要不要重启才生效",
        "帮我重启下服务让飞书设置生效",
        "配好凭据后怎么让它生效",
        "重启服务的命令是啥",
        "我改了设置，怎么让它跑起来",
        "帮我把服务重启一下",
        "配置更新后需要重新加载吗",
        "怎么让新的飞书设置立即生效",
        "帮我 restart 一下让改动生效",
        "改了参数服务没反应，要重启吗",
        "重启之后飞书连接会自动恢复吗",
        "帮我重新启动服务应用新配置",
        "配置改了得手动重启服务吧",
        "怎么平滑重启不丢连接",
        "帮我重载下服务让设置生效",
        "改完配置服务要不要重新拉起",
        "重启后之前的连接还在吗",
        "帮我停一下再起来让配置刷新",
        "新填的凭据要重启才认吗",
        "怎么不停机让配置热更新",
    ],
    # ===== E. 新渠道接入（微信/TG/Slack）=====
    "newchan": [
        "以后能不能把微信也连进来",
        "想把 Telegram 连上 Ethan",
        "Slack 能对接吗",
        "支不支持微信公众号对接",
        "我想让企业微信的信息也进来",
        "未来能不能支持 Slack 的事件",
        "Telegram 机器人怎么连进来",
        "想把 Discord 也对接上",
        "除了飞书还能连哪些平台",
        "微信能不能像飞书那样连进来",
        "想连上 WhatsApp 行不行",
        "QQ 能对接进来吗",
        "以后会支持钉钉对接吗",
        "Slack 的信息怎么打通到这边",
        "想让多个聊天平台都连进来",
        "能不能同时连飞书和企业微信",
        "未来支持小程序对接吗",
        "想把短信也作为一个来源连进来",
        "邮件能不能也对接进来",
        "支持把多个平台统一管理吗",
    ],
    # ===== F. 渠道概念/能不能不用公网 =====
    "concept": [
        "我没有公网 IP 也能收飞书信息吗",
        "不开端口怎么接收外部事件",
        "这种长连接是怎么穿透内网的",
        "为什么不用回调地址而用长连接",
        "没有服务器公网怎么对接飞书",
        "长连接和回调有啥区别",
        "我在家用的网络能不能跑这个对接",
        "不暴露公网安全吗",
        "这种连进来的方式需要域名吗",
        "为什么推荐用长连接而不是公网回调",
        "内网环境能不能正常连飞书",
        "这种连法对网络有啥要求",
        "不用公网也能稳定收事件吗",
        "长连接断了会自动重连吗",
        "这个对接方式的原理是啥",
        "没有固定 IP 会不会影响连接",
        "长连接占资源多吗",
        "这种方式比公网回调更安全吗",
        "对接需不需要在路由器上开端口",
        "公司内网防火墙严能用吗",
    ],
    # ===== G. 实时收发基座/事件流底座（治串到 lark-shared，说得清部分）=====
    # 本质：搭一条"实时收外部平台事件、长连接监听、收发底座"的基础设施。区分信号：
    # 实时事件流/长连接监听/收发基座/推送底座/监听外部平台发言。区别于 cli 登录配置
    # (lark-shared)。纯"配置在哪/实时对接"无基础设施锚点的两可句不收。说法自拟防泄漏。
    "infra": [
        "帮我在后端把那套实时收发的底座搭起来",
        "想让程序长连着，实时把外部平台的发言读进来",
        "搭一个能时刻在线、源源不断收事件的监听底座",
        "帮我把实时监听外部协作平台发言的那层搭好",
        "我要一条一直挂着的实时事件流，把来信推进系统",
        "想让系统常驻在线，实时承接外部平台推来的事件",
        "帮我把实时推送的收发基座先跑通",
        "搭个持续监听的底座，外部平台一有动静就推进来",
        "我想留一套实时事件流的底座，以后好接更多平台",
        "帮我把长连接监听服务起起来，实时收外部消息流",
        "想让后端一直监听外部群组的实时发言并送进来",
        "把实时承接外部事件的那层基础链路给我搭好",
        "帮我跑一个常驻进程，实时把外部平台来信收进系统",
        "想搭那种支持实时收发、随时扩展新平台的事件底座",
        "帮我把实时读取协作平台发言的监听底座配通",
        "我要个一直在线的事件接收基座，把外部动静实时同步",
        "搭一条实时链路，让外部平台的事件不间断流进来",
        "帮我把承接实时推送的底层收发服务建起来",
    ],
}

SUBCAT = {
    "connect": ("A", "建连接"),
    "cred": ("B", "填凭据"),
    "status": ("C", "状态排查"),
    "restart": ("D", "重启生效"),
    "newchan": ("E", "新平台"),
    "concept": ("F", "原理概念"),
    "infra": ("G", "收发底座"),
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
            rec = {"text": text, "label": "channels", "subcat": f"{code}-{name}"}
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")


def main():
    base = Path(__file__).resolve().parent
    items = dedupe(expand())
    print(f"手写池展开+去重后：{len(items)} 条")
    train, val, test = stratified_split(items, 800, 75, 75, seed=20260629)
    write_jsonl(base / "train" / "channels.jsonl", train)
    write_jsonl(base / "val" / "channels.jsonl", val)
    write_jsonl(base / "test" / "channels.jsonl", test)
    print(f"train={len(train)} val={len(val)} test={len(test)}")
    for name, split in [("train", train), ("val", val), ("test", test)]:
        c = Counter(SUBCAT[cat][0] for _, cat in split)
        print(f"\n{name} 子语义分布（共 {len(split)}）：")
        for cat in SUBCAT:
            code = SUBCAT[cat][0]
            print(f"  {code}-{SUBCAT[cat][1]:<6} {c.get(code, 0):>3}")


if __name__ == "__main__":
    main()