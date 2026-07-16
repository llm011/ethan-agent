# -*- coding: utf-8 -*-
"""golden 样本生成共享框架。

Atom = 一条可从 user 消息中提取的事实(msg/quote/content/level/scope/structured)。
Composer = 把 Atom 包装成具体场景的 case(single/noise/correction/multi/observed/
repeat/unconfirmed/leak/diag)。

所有组合器保证:quote 始终是对应 user 消息的精确子串(生成后 validate 再兜底)。
"""
from __future__ import annotations

import json

VALID_EVIDENCE = {"observed", "inferred", "explicit", "corrected"}
VALID_SCOPE = {"user", "user_domain", "user_skill", "project", "mode"}

# 与 ethan/memory/extractors.py 的 _COMPANION_DENIED_TERMS 保持一致(中文部分)
DENIED = {
    "抑郁", "抑郁症", "焦虑症", "人格", "依恋", "创伤", "创伤后", "心理疾病",
    "双相", "强迫症", "分裂", "心理障碍", "诊断", "病理",
    "depression", "anxiety disorder", "personality disorder", "attachment style",
    "trauma", "ptsd", "bipolar", "ocd", "diagnosis", "clinical", "pathological",
}

# ── 闲聊填充(noise 用),不含任何可提取事实 ──
PRE = ["哈哈，", "说起来，", "对了，", "刚开完会。", "刚吃完饭，", "插一句，",
       "周末过得真快。", "刚刷到个视频，", "外面下雨了。", "忙了一上午，"]
POST = ["先这样。", "就这些。", "回头聊。", "你懂的。", "哈哈。", "先说这么多。",
        "就这样吧。", "待会再说。"]

CORR_PREFIX = ["不对，更正一下：", "记错了，应该是：", "更新一下：", "改成这样："]
ACK = ["好的，记下了。", "明白。", "好的。", "嗯嗯。"]


class Atom:
    """一条可提取事实。msg 为 user 原话,quote 必须是 msg 的子串。"""

    def __init__(self, mtype, dim, msg, quote, content, level="explicit",
                 scope=("user", "self"), key=None, structured=None, gap=False):
        self.mtype = mtype
        self.dim = dim
        self.msg = msg
        self.quote = quote
        self.content = content
        self.level = level
        self.scope = scope
        self.key = key or dim
        self.structured = structured
        self.gap = gap
        assert quote in msg, f"quote 不在 msg 中: {quote!r} / {msg!r}"

    def entry(self, mid, level=None):
        e = {
            "memory_type": self.mtype,
            "dimension": self.dim,
            "memory_key": self.key,
            "content": self.content,
            "evidence_level": level or self.level,
            "scope_type": self.scope[0],
            "scope_id": self.scope[1],
            "quote": self.quote,
            "message_id": mid,
            "gap_dimension": self.gap,
        }
        if self.structured is not None:
            e["structured"] = self.structured
        return e


def case(cid, domain, scenario, msgs, expected, mode="", note=None):
    d = {
        "id": cid, "domain": domain, "kind": "extraction", "scenario": scenario,
        "mode": mode,
        "messages": [{"id": i + 1, "role": r, "content": c}
                     for i, (r, c) in enumerate(msgs)],
        "expected": expected, "forbidden_domains": ["companion"],
    }
    if note:
        d["note"] = note
    return d


# ── 场景组合器 ──

def single(cid, domain, atom, note=None, scenario="single_explicit"):
    return case(cid, domain, scenario, [("user", atom.msg)],
                [atom.entry(1)], mode="companion" if domain == "companion" else "",
                note=note)


def noise(cid, domain, atom, i=0):
    msg = PRE[i % len(PRE)] + atom.msg + POST[(i * 3 + 1) % len(POST)]
    return case(cid, domain, "noise", [("user", msg)], [atom.entry(1)],
                mode="companion" if domain == "companion" else "",
                note="事实夹在闲聊中,抗干扰")


def corr(cid, domain, atom_old, atom_new, i=0):
    msgs = [("user", atom_old.msg), ("assistant", ACK[i % len(ACK)]),
            ("user", CORR_PREFIX[i % len(CORR_PREFIX)] + atom_new.msg)]
    return case(cid, domain, "correction", msgs,
                [atom_new.entry(3, level="corrected")],
                mode="companion" if domain == "companion" else "",
                note="用户纠正,最终事实以最后一次为准")


def multi(cid, domain, atoms, note=None):
    msg = " ".join(a.msg for a in atoms)
    return case(cid, domain, "multi_fact_one_turn", [("user", msg)],
                [a.entry(1) for a in atoms],
                mode="companion" if domain == "companion" else "",
                note=note or f"一条消息 {len(atoms)} 条事实")


def obs(cid, domain, atom, note=None):
    return case(cid, domain, "observed_single", [("user", atom.msg)],
                [atom.entry(1, level="observed")],
                mode="companion" if domain == "companion" else "",
                note=note or "observed 单 session,预期 pending 不晋升")


def rep(cid, domain, atom, i=0):
    msgs = [("user", atom.msg), ("assistant", ACK[i % len(ACK)]),
            ("user", "跟之前说的一样，" + atom.msg)]
    return case(cid, domain, "observed_repeat", msgs,
                [atom.entry(3, level="inferred")],
                mode="companion" if domain == "companion" else "",
                note="同一事实重复出现,inferred")


def unconfirmed(cid, domain, q, proposal, dodge, note=None):
    msgs = [("user", q), ("assistant", proposal), ("user", dodge)]
    return case(cid, domain, "assistant_unconfirmed", msgs, [],
                note=note or "assistant 提议未被用户确认,预期 NOOP 不写入")


def leak(cid, atom, mode=""):
    return case(cid, "companion", "companion_leak", [("user", atom.msg)], [],
                mode=mode, note=f"非 companion 模式(mode={mode!r}),情感内容不提取")


def diag(cid, msg):
    return case(cid, "companion", "diagnostic_reject", [("user", msg)], [],
                mode="companion", note="含诊断/标签词,禁止提取")


# ── 校验 + 写盘 ──

def validate(cases, dims, mtype, need_structured=False):
    errors = []
    for c in cases:
        user_msgs = {m["id"]: m["content"] for m in c["messages"] if m["role"] == "user"}
        if c["expected"] and c["domain"] == "companion" and c["mode"] != "companion":
            errors.append(f'{c["id"]}: companion 正样本但 mode!=companion')
        for e in c["expected"]:
            if e["gap_dimension"]:
                if e["dimension"] in dims:
                    errors.append(f'{c["id"]}: GAP 维度却在白名单 {e["dimension"]}')
            elif e["dimension"] not in dims:
                errors.append(f'{c["id"]}: 维度不在白名单 {e["dimension"]}')
            if e["memory_type"] != mtype:
                errors.append(f'{c["id"]}: memory_type 错 {e["memory_type"]}')
            if e["evidence_level"] not in VALID_EVIDENCE:
                errors.append(f'{c["id"]}: evidence 非法 {e["evidence_level"]}')
            if e["scope_type"] not in VALID_SCOPE:
                errors.append(f'{c["id"]}: scope 非法 {e["scope_type"]}')
            for t in DENIED:
                if t.lower() in e["content"].lower() or t.lower() in e["quote"].lower():
                    errors.append(f'{c["id"]}: 含禁止词 {t}')
            if need_structured and not e.get("structured"):
                errors.append(f'{c["id"]}: methodology 缺 structured')
            src = user_msgs.get(e["message_id"])
            if src is None or e["quote"] not in (src or ""):
                errors.append(f'{c["id"]}: quote 非精确子串 {e["quote"][:24]!r}')
    return errors


def append_jsonl(path, cases):
    with open(path, "a", encoding="utf-8") as f:
        for c in cases:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")


def interleave(pools):
    """多个维度池轮转交错,保证切片后各维度覆盖均匀。"""
    out = []
    i = 0
    while any(len(p) > i for p in pools):
        for p in pools:
            if i < len(p):
                out.append(p[i])
        i += 1
    return out


class Ids:
    """顺序分配 case id: Ids('ext_pref', 31) -> ext_pref_0031, ext_pref_0032, ..."""

    def __init__(self, prefix, start):
        self.prefix = prefix
        self.n = start - 1

    def __call__(self):
        self.n += 1
        return f"{self.prefix}_{self.n:04d}"
