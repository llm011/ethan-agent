#!/usr/bin/env python3
"""生成 lark-shared 训练样本（jsonl）。

lark-shared = lark-cli 命令行工具本身的配置/认证层：首次配置、登录授权、切换 user/bot
身份、权限/scope 报错处理、更新工具、登录态查看。

边界（与 channels / lark-im 分清）：
  lark-shared = 「lark-cli 这个工具登不登得上、用什么身份、权限够不够、要不要更新」；
  channels    = 「把飞书事件接进 Ethan、建长连接」这一接入层；
  lark-im     = 登录好之后「收发信息/管群」的业务操作。

子语义（现有 + 未来）：
  A 首次配置/初始化      B 登录授权/扫码授权      C 切 user/bot 身份
  D 权限不足/scope 报错   E 更新工具              F 看登录态/凭证状态
  G 多账号/token 过期/企业切换（future）

铁律：绝不含任一 trigger 原词子串：
  lark-cli | lark 命令行 | 飞书命令行 | 飞书 cli | auth login | 登录飞书工具
  | 切换身份 | 机器人身份 | bot 身份 | user 身份 | 权限错误 | 权限不够 | 授权失败
  | 更新 lark-cli | 登录态 | 登录状态 | 凭证
（用「命令行工具/这个工具/身份/权限不足/授权没成功/登录情况/令牌」等同义替换）
"""
from __future__ import annotations
import json
import random
from pathlib import Path
from collections import Counter

TRIGGERS = [
    "lark-cli", "lark 命令行", "飞书命令行", "飞书 cli", "auth login", "登录飞书工具",
    "切换身份", "机器人身份", "bot 身份", "user 身份", "权限错误", "权限不够", "授权失败",
    "更新 lark-cli", "登录态", "登录状态", "凭证",
]

POOL: dict[str, list[str]] = {
    # ===== A. 首次配置/初始化 =====
    "init": [
        "第一次用这个命令行工具，怎么配",
        "帮我把飞书的命令行工具初始化一下",
        "这个工具第一次用要做哪些设置",
        "怎么完成命令行工具的初始配置",
        "帮我跑一下首次配置流程",
        "刚装好工具，怎么开始配",
        "初始化的时候会弹授权链接吗",
        "帮我新建一个应用配置",
        "工具的初始设置在哪做",
        "第一次配置需要准备什么",
        "帮我把工具的基础配置走完",
        "config 初始化怎么操作",
        "刚装上这个工具不知道怎么起步",
        "帮我做下飞书工具的首次设置",
        "初始配置卡住了，帮我看看",
        "首次用要不要先建应用",
        "帮我把工具和飞书应用对接上",
        "初始化时让我填什么信息",
        "第一次设置需要应用的哪些参数",
        "帮我走一遍开箱配置",
        "工具装好了下一步配啥",
        "初次配置的官方流程是怎样的",
        "帮我把基础参数都设置好",
        "刚上手不知道先配哪一步",
    ],
    # ===== B. 登录授权/扫码授权 =====
    "login": [
        "帮我登录一下飞书工具",
        "怎么扫码授权这个工具",
        "我要登进去，给我个授权链接",
        "帮我发起一次授权",
        "扫码登录怎么弄",
        "我想用自己的账号登进去",
        "帮我生成登录的二维码",
        "授权链接帮我搞出来，我去扫",
        "怎么完成这个工具的登入",
        "帮我按某个权限范围去授权",
        "我授权完了，帮我接着完成登录",
        "想增量再授权几个权限",
        "登录要指定范围吗，帮我弄",
        "帮我重新登录一下，掉线了",
        "扫完码之后下一步怎么走",
        "帮我登入飞书账号",
        "授权页打不开，帮我重发链接",
        "我要授权日历相关的权限去登",
        "登录流程帮我跑一遍",
        "扫码后一直没反应怎么回事",
        "帮我用设备码方式完成登录",
        "授权范围选哪些比较好",
        "登进去要不要管理员同意",
        "帮我把登录这一步搞定",
        "想登一个新账号进来",
    ],
    # ===== C. 切 user/bot 身份 =====
    "identity": [
        "怎么切到用户的身份去操作",
        "帮我换成应用那个身份执行",
        "现在是用哪个身份在跑",
        "我想用个人账号的身份来操作",
        "切成应用自己的身份怎么弄",
        "用户身份和应用身份有啥区别",
        "帮我用机器人的身份发起请求",
        "这个操作该用哪个身份做",
        "我要以本人身份访问自己的资源",
        "怎么指定用应用方的身份",
        "用应用身份能看到我的个人日历吗",
        "帮我把执行身份换一下",
        "当前身份不对，帮我切过去",
        "这条命令用用户还是应用身份合适",
        "我想确认现在跑在哪个身份下",
        "帮我用个人身份去查云盘",
        "应用方身份能不能代我发东西",
        "切身份要重新登录吗",
        "我想固定用某个身份执行",
        "两种身份的权限范围一样吗",
        "帮我以应用方的角色跑这条",
        "用本人身份才看得到我的文档吧",
        "怎么知道该用哪种角色",
        "帮我把默认身份设成个人",
        "想临时换个身份试一下",
    ],
    # ===== D. 权限不足/scope 报错 =====
    "perm": [
        "提示权限不足，怎么办",
        "报错说缺少某个授权范围",
        "执行的时候说没权限，帮我解决",
        "这个操作提示要更多授权",
        "权限不足导致命令失败了",
        "报了个 scope 缺失的错",
        "怎么补上缺的那个权限",
        "提示要去后台开通权限",
        "权限被拒了，给我个后台链接",
        "差一个授权范围，帮我加上",
        "命令返回权限相关的错误",
        "帮我看看是不是少授权了",
        "应用身份报权限错，怎么处理",
        "用户身份缺权限要怎么补授权",
        "一直提示无权访问，帮我排查",
        "报错 403，是不是权限问题",
        "说我没有读取的授权范围",
        "帮我把缺的那个 scope 补授权",
        "权限被拦了，该去哪开通",
        "执行被拒，提示需要管理员授权",
        "提示当前角色无权操作",
        "缺写入权限，帮我处理下",
        "授权范围不够用，怎么扩",
        "报错说要更高的访问权限",
        "命令一直因为权限失败",
    ],
    # ===== E. 更新工具 =====
    "upgrade": [
        "这个命令行工具有新版本吗",
        "帮我把工具更到最新",
        "提示有更新，帮我升级一下",
        "工具旧了，怎么更新",
        "把这个飞书工具刷到最新版",
        "更新工具会连带技能一起更吗",
        "帮我检查下工具版本是不是最新",
        "看到更新提示了，帮我更一下",
        "工具升级完要重开吗",
        "怎么升级这个命令行工具",
        "帮我把工具和扩展一起更新",
        "当前版本太老了，升级下",
        "更新之后要重新打开吗",
        "帮我执行一下工具的更新",
        "有新版别忘了帮我升级",
        "工具提示该更新了，照做吧",
        "升级后旧配置还在吗",
        "帮我看下能不能一键更新",
        "更新会不会影响现有登录",
        "把工具升到官方最新稳定版",
        "更新命令是哪个",
        "帮我顺手把工具也更了",
        "升级失败了帮我看看",
        "更新完要不要重新登录",
        "工具版本落后好多，帮我刷新",
    ],
    # ===== F. 看登录态/令牌状态 =====
    "state": [
        "我现在登录了没",
        "帮我看下登录情况",
        "当前的登录有没有过期",
        "查一下我的登入状态",
        "我的令牌还有效吗",
        "帮我确认下还在不在登录中",
        "看看现在用的是哪个账号登的",
        "登录信息帮我查一下",
        "我的授权是不是失效了",
        "帮我看下令牌什么时候过期",
        "确认下我还能不能正常调用",
        "登录有没有掉，帮我看看",
        "查询下当前的登入信息",
        "帮我看我授权了哪些权限范围",
        "现在的会话还活着吗",
        "看下我当前用什么角色登的",
        "帮我查授权有没有快到期",
        "我登的是哪个企业",
        "令牌状态帮我看一眼",
        "确认下我还在登录有效期内",
        "帮我看下还剩多久要重登",
        "当前账号信息显示一下",
        "查查我有没有被登出",
        "帮我核对下登录的账号对不对",
        "看看现在授权范围够不够",
    ],
    # ===== G. 多账号/token 过期/企业切换 =====
    "multi": [
        "我想切换到另一个企业",
        "怎么在多个账号之间切",
        "令牌过期了怎么重新拿",
        "帮我换个公司的账号登",
        "我有两个组织，怎么切过去",
        "token 失效了帮我刷新",
        "想退出当前账号换一个",
        "怎么管理多个登录账号",
        "切到另一个租户怎么操作",
        "帮我把当前账号登出",
        "过期的授权怎么续上",
        "我想同时登几个账号",
        "换企业之后要重新授权吗",
        "帮我清掉旧账号的登录信息",
        "多个身份怎么快速切换",
        "我要登出再换个组织进",
        "令牌到期自动续不了怎么办",
        "帮我在两家公司账号间来回切",
        "切租户后权限会不会变",
        "想把默认登录账号改掉",
        "退出登录的命令是哪个",
        "帮我把过期的会话刷新一下",
        "换号之后旧的还保留吗",
        "怎么彻底注销当前账号",
        "多账号管理有没有更省事的办法",
    ],
}

SUBCAT = {
    "init": ("A", "初始化"),
    "login": ("B", "登录授权"),
    "identity": ("C", "切身份"),
    "perm": ("D", "权限不足"),
    "upgrade": ("E", "更新工具"),
    "state": ("F", "登录态"),
    "multi": ("G", "多账号"),
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
            rec = {"text": text, "label": "lark-shared", "subcat": f"{code}-{name}"}
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")


def main():
    base = Path(__file__).resolve().parent
    items = dedupe(expand())
    print(f"手写池展开+去重后：{len(items)} 条")
    train, val, test = stratified_split(items, 500, 75, 75, seed=20260629)
    write_jsonl(base / "train" / "lark-shared.jsonl", train)
    write_jsonl(base / "val" / "lark-shared.jsonl", val)
    write_jsonl(base / "test" / "lark-shared.jsonl", test)
    print(f"train={len(train)} val={len(val)} test={len(test)}")
    for name, split in [("train", train), ("val", val), ("test", test)]:
        c = Counter(SUBCAT[cat][0] for _, cat in split)
        print(f"\n{name} 子语义分布（共 {len(split)}）：")
        for cat in SUBCAT:
            code = SUBCAT[cat][0]
            print(f"  {code}-{SUBCAT[cat][1]:<6} {c.get(code, 0):>3}")


if __name__ == "__main__":
    main()