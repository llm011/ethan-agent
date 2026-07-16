# -*- coding: utf-8 -*-
"""一键重新生成全部 golden 增量样本(幂等)。

用法: python3 gen_all.py
对每域:先剔除 golden 文件中 ID >= 生成起始值的行(上次生成的),再追加本次生成。
手写的原始样本(ID 小于起始值)不受影响。
"""
import json
from pathlib import Path

from genlib import Ids, validate, append_jsonl, DENIED
import gen_personal, gen_preference, gen_methodology, gen_activity, gen_decision, gen_companion

GOLDEN = Path(__file__).resolve().parent.parent / "golden"

JOBS = [
    # (模块, 文件名, 起始 id, 白名单, mtype, need_structured)
    (gen_personal, "personal_information.jsonl", 41,
     set(gen_personal.pools().keys()) - {"identity.age", "identity.gender",
                                         "identity.mbti", "identity.interests"},
     "personal_information", False),
    (gen_preference, "preference.jsonl", 31,
     set(gen_preference.pools().keys()), "preference", False),
    (gen_methodology, "methodology.jsonl", 31,
     set(gen_methodology.pools().keys()), "methodology", True),
    (gen_activity, "activity.jsonl", 31,
     set(gen_activity.pools().keys()), "activity", False),
    (gen_decision, "decision.jsonl", 31,
     set(gen_decision.pools().keys()), "decision", False),
    (gen_companion, "companion.jsonl", 51,
     set(gen_companion.pools().keys()), "companion", False),
]


def main():
    for mod, fname, start, dims, mtype, need_structured in JOBS:
        prefix = fname.replace(".jsonl", "")
        id_prefix = {"personal_information": "ext_personal", "preference": "ext_pref",
                     "methodology": "ext_meth", "activity": "ext_act",
                     "decision": "ext_dec", "companion": "ext_comp"}[prefix]
        cases = mod.build(Ids(id_prefix, start))
        errs = validate(cases, dims, mtype, need_structured=need_structured)
        if mtype == "companion":
            for c in cases:
                if c["scenario"] == "diagnostic_reject":
                    text = c["messages"][0]["content"].lower()
                    if not any(t.lower() in text for t in DENIED):
                        errs.append(f'{c["id"]}: diag 消息不含禁止词')
        if errs:
            print(f"{prefix} 校验失败:")
            for e in errs:
                print(" -", e)
            raise SystemExit(1)

        path = GOLDEN / fname
        kept = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            cid = json.loads(line)["id"]
            if int(cid.rsplit("_", 1)[1]) < start:
                kept.append(line)
        path.write_text("\n".join(kept) + "\n", encoding="utf-8")
        append_jsonl(path, cases)
        total = sum(1 for _ in open(path, encoding="utf-8"))
        print(f"{prefix}: 保留手写 {len(kept)} 条 + 生成 {len(cases)} 条 = {total}")


if __name__ == "__main__":
    main()
