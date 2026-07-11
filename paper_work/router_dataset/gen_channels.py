#!/usr/bin/env python3
"""生成 channels 训练样本（jsonl）。★三池独立版。"""
from __future__ import annotations
import json, random
from pathlib import Path
from collections import Counter

TRIGGERS = ["渠道","channel","飞书配置","lark配置","接入","webhook","websocket","消息渠道"]

POOL_TRAIN: dict[str, list[str]] = {
    "connect": [
        "帮我把飞书的长连接建起来",
        "怎么让飞书的事件推过来",
        "我想让 Ethan 收到飞书那边的事件",
        "飞书的持久连接怎么搭",
        "帮我打通飞书和本地服务的通道",
        "想让飞书通知实时推到我这边",
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
    "cred": [
        "飞书的 App ID 和密钥填在哪",
        "帮我把飞书应用的凭据配上",
        "在哪里填飞书自建应用的 key",
        "飞书的 appid 和 secret 怎么设置",
        "帮我在设置里加上飞书的应用信息",
        "飞书应用的密钥要配到哪个地方",
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
        "想把短信也作为来源连进来",
        "邮件能不能也对接进来",
        "支持把多个平台统一管理吗",
    ],
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
        "帮我把长连接监听服务起起来，实时收外部流",
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

POOL_VAL: dict[str, list[str]] = {
    "connect": [
        "帮我把飞书那边的事件通道给对通",
        "想让飞书来的东西实时流进本地服务",
        "飞书的长驻连接怎么配起来",
        "帮我把飞书事件推送的链路跑通",
        "怎么让服务持续接收飞书端的事件",
    ],
    "cred": [
        "飞书自建应用的鉴权参数填在哪个位置",
        "帮我把飞书应用的 ID 和密钥录到系统",
        "飞书那边给的凭据信息怎么配进去",
        "在哪个地方填飞书 app 的 secret",
        "帮我把飞书应用参数对上",
    ],
    "status": [
        "飞书这边的事件好像收不到了，帮我查一下",
        "帮我看下飞书的连接现在是不是正常",
        "怎么判断飞书事件流有没有断掉",
        "飞书推送延迟好大，帮我诊断一下",
        "连接日志有没有飞书断线的记录",
    ],
    "restart": [
        "改了飞书的凭据后服务要不要重跑",
        "帮我把服务拉起来让新配置生效",
        "配置更新完怎么让它立刻生效",
        "帮我重载一下应用新的飞书参数",
        "重启后飞书连接会自动重建吗",
    ],
    "newchan": [
        "钉钉能不能也对接进来",
        "企业微信有没有可能像飞书一样连上",
        "想扩展到其他平台，目前支持哪些",
        "Telegram 这种能不能接进来",
        "未来能不能把多个平台统一管起来",
    ],
    "concept": [
        "没有公网服务器也能收飞书事件吗",
        "长连接比回调有啥优势",
        "公司内网能不能正常跑这个对接",
        "这种对接方式需不需要固定 IP",
        "不暴露端口怎么收飞书的推送",
    ],
    "infra": [
        "帮我搭一套实时事件流的接收底座",
        "想让系统常驻在线持续收外部平台的通知",
        "帮我把承接实时推送的基础链路配通",
        "搭个监听底座，外部平台有动静就推进来",
        "我要个一直跑着的进程把外部事件引进系统",
    ],
}

POOL_TEST: dict[str, list[str]] = {
    "connect": [
        "想让 Ethan 能收到飞书那边的消息，但不知道怎么搭，帮我配一下",
        "我这台机器在内网，没公网，飞书那边怎么把事件推进来，帮我搞定",
        "飞书机器人建好了，但 Ethan 这边收不到，帮我把那条连接打通",
        "想让飞书群里的消息实时到 Ethan，现在还没配，帮我搞一下",
    ],
    "cred": [
        "飞书后台把 App ID 和 Secret 都拿到了，填哪儿啊，帮我配上",
        "建好飞书自建应用了，凭据要填到哪个地方，帮我录进去",
        "飞书的 appid 和密钥放哪里，我在设置里没找到，帮我填",
        "我有飞书应用的鉴权信息，但不知道往哪填，帮我对上",
    ],
    "status": [
        "之前飞书事件一直好好的，今天突然收不到了，帮我查查是不是断了",
        "感觉飞书这边好几分钟没动静了，连接是不是挂了，帮我看看",
        "飞书推送时断时续，一会儿有一会儿没，帮我诊断下啥原因",
        "日志里看到好多连接断开的记录，帮我排查一下飞书连接不稳定",
    ],
    "restart": [
        "我刚改了飞书的 App ID，服务现在不用我手动重启吗还是要",
        "配置改了以后一直没生效，是不是要重启服务，帮我操作一下",
        "凭据填好了但还是连不上，是不是要重启一下让它认，帮我搞",
        "帮我把服务重启一下，刚改的飞书参数还没生效",
    ],
    "newchan": [
        "我们有些同事用钉钉，能不能也把钉钉接进来让 Ethan 收",
        "我想把企业微信也接上，不知道支不支持，帮我看看",
        "除了飞书还能接哪些平台，我想连 Telegram 那边的",
        "以后能不能多接几个平台，飞书企业微信钉钉都支持吗",
    ],
    "concept": [
        "我家里没有固定公网 IP，能不能也跑这个对接，不想开端口",
        "公司防火墙很严，长连接能穿过去吗，帮我解释一下原理",
        "为什么用长连接而不是给飞书一个回调地址，有什么优势",
        "我只有内网服务器，飞书怎么把事件推进来，帮我说清楚",
    ],
    "infra": [
        "我想让后端一直跑着接飞书事件，不是一次性的，帮我把那套底座搭起来",
        "需要一个常驻进程实时把外部平台动静引进来，帮我配好这层基础设施",
        "想搭个能支持以后扩展多个平台的实时事件接收底座，帮我把架子建好",
        "要接的平台不只飞书，帮我搭一套通用的实时收发底座",
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
        out = list(items); rng.shuffle(out); return out
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
            rec = {"text": text, "label": "channels", "subcat": f"{code}-{name}"}
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")


def main():
    base = Path(__file__).resolve().parent
    seen: set = set()
    test_raw = dedupe(expand_pool(POOL_TEST), seen)
    val_raw = dedupe(expand_pool(POOL_VAL), seen)
    train_raw = dedupe(expand_pool(POOL_TRAIN), seen)

    test = cap_per_split(test_raw, 75, seed=20260711)
    val = cap_per_split(val_raw, 75, seed=20260712)
    train = cap_per_split(train_raw, 800, seed=20260713)

    write_jsonl(base / "train" / "channels.jsonl", train)
    write_jsonl(base / "val" / "channels.jsonl", val)
    write_jsonl(base / "test" / "channels.jsonl", test)
    print(f"train={len(train)} val={len(val)} test={len(test)}")
    for split_name, split in [("train", train), ("val", val), ("test", test)]:
        c = Counter(SUBCAT[cat][0] for _, cat in split)
        print(f"\n{split_name} 子语义分布（共 {len(split)}）：")
        for cat in SUBCAT:
            code = SUBCAT[cat][0]
            print(f"  {code}-{SUBCAT[cat][1]:<8} {c.get(code, 0):>3}")


if __name__ == "__main__":
    main()
