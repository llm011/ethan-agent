#!/usr/bin/env python3
"""按子语义（subcat）切片验证 LR 路由器 —— train_lr_router.py 的补充诊断。

train_lr_router.py 只报 per-skill 的 P/R/F1，看不出一个 skill 内部哪种子语义在掉。
本脚本把 val+test 按样本里的 subcat 字段切片，定位弱势子语义，决定补哪类样本。

当前覆盖两类检查：
  1. ppt-generate 各子语义命中率（重点看长md类 C/D/E —— 考头尾截断是否生效）
  2. others 的 V-陷阱·演示 拒识率（胶片摄影/排版/视频/how-to/长md+总结翻译，
     必须全部判 others；漏一个就是 ppt 类在劫持真实流量）

跑法：
  uv run --with onnxruntime --with transformers --with numpy \
    python paper_work/router_dataset/eval_subcat.py
"""
import json
from pathlib import Path

import numpy as np
import onnxruntime as ort
from transformers import AutoTokenizer

ROOT = Path(__file__).resolve().parent
# 与 train_lr_router.py / ethan/skills/router.py 完全一致的头尾截断
HEAD_C, TAIL_C, MAXL = 76, 40, 144


def splice(t: str) -> str:
    return t if len(t) <= HEAD_C + TAIL_C + 3 else t[:HEAD_C] + "\n…\n" + t[-TAIL_C:]


head = np.load(ROOT.parents[1] / "ethan/skills/router_models/lr_head.npz", allow_pickle=True)
coef, intercept, labels = head["coef"], head["intercept"], [str(l) for l in head["labels"]]
floor = float(head["floor"])
tok = AutoTokenizer.from_pretrained("BAAI/bge-small-zh-v1.5")
sess = ort.InferenceSession(str(ROOT.parent / "bge_onnx_quant/model_quant.onnx"), providers=["CPUExecutionProvider"])
names = {i.name for i in sess.get_inputs()}


def encode(texts):
    out = []
    for i in range(0, len(texts), 64):
        b = tok([("为这个句子生成表示以用于检索相关文章：" + splice(t)) for t in texts[i:i + 64]],
                padding=True, truncation=True, max_length=MAXL, return_tensors="np")
        o = sess.run(None, {k: v for k, v in b.items() if k in names})[0]
        e = o[:, 0, :]
        e /= (np.linalg.norm(e, axis=1, keepdims=True) + 1e-8)
        out.append(e)
    return np.vstack(out)


def predict(rows):
    X = encode([r["text"] for r in rows])
    logits = X @ coef.T + intercept
    e = np.exp(logits - logits.max(1, keepdims=True))
    proba = e / e.sum(1, keepdims=True)
    pred = proba.argmax(1)
    maxp = proba.max(1)
    pred = np.where(maxp < floor, labels.index("others"), pred)
    return pred, maxp


print("=== ppt-generate per-subcat（val+test 合并）===")
rows = [json.loads(l) for s in ["val", "test"] for l in open(ROOT / s / "ppt-generate.jsonl", encoding="utf-8")]
pred, maxp = predict(rows)
stats = {}
for r, p, mp in zip(rows, pred, maxp):
    stats.setdefault(r["subcat"], []).append((labels[p] == "ppt-generate", labels[p], mp, r["text"][:40]))
for sub, items in sorted(stats.items()):
    ok = sum(1 for x in items if x[0])
    print(f"{sub:<18} {ok}/{len(items)}")
    for o, pl, mp, snip in items:
        if not o:
            print(f"   ✗ → {pl} (p={mp:.2f}) {snip}")

print("\n=== others trap_ppt 陷阱（应全部拒识为 others）===")
rows = [json.loads(l) for s in ["val", "test"] for l in open(ROOT / s / "others.jsonl", encoding="utf-8")]
rows = [r for r in rows if r.get("subcat", "").startswith("V-")]
pred, maxp = predict(rows)
ok = sum(1 for p in pred if labels[p] == "others")
print(f"trap_ppt 拒识 {ok}/{len(rows)}")
for r, p, mp in zip(rows, pred, maxp):
    if labels[p] != "others":
        print(f"   ✗ → {labels[p]} (p={mp:.2f}) {r['text'][:50]}")
# 长md陷阱单独看（没有这批负例时分类器把「粘贴长文档」本身当 ppt 信号）
longmd = [r for r in rows if "\n" in r["text"]]
pred2, _ = predict(longmd)
ok2 = sum(1 for p in pred2 if labels[p] == "others")
print(f"其中长md陷阱 拒识 {ok2}/{len(longmd)}")
for r, p in zip(longmd, pred2):
    if labels[p] != "others":
        print(f"   ✗长md → {labels[p]}: {r['text'][:40]}...")
