#!/usr/bin/env python3
"""用外部独立 test 集评测 LR 路由头。

router_train.jsonl 是独立手写的（query/answer 格式，措辞风格与生成器不同），
天然规避近重复泄漏。它有 11 类，与本数据集 9 类只重合 7 类：
  deepwiki lark-im channels companion-listen skills-manager lark-shared paper-analysis
本脚本只在这 7 类上评测；文件里我的模型不认识的 4 类（lark-doc/getnote/ui-card/
upload-cdn）按用户要求先忽略；模型独有的 legal-assistant/others 文件里也没有。

跑法：
  HF_ENDPOINT=https://hf-mirror.com HTTPS_PROXY=http://127.0.0.1:7898 \
  uv run --with scikit-learn --with onnxruntime --with transformers --with numpy \
    python paper_work/router_dataset/eval_external.py
"""
from __future__ import annotations
import json
from pathlib import Path

import numpy as np
import onnxruntime as ort
from sklearn.linear_model import LogisticRegression
from transformers import AutoTokenizer

ROOT = Path(__file__).resolve().parent
INT8 = ROOT.parent / "bge_onnx_quant" / "model_quant.onnx"
BASE_MODEL = "BAAI/bge-small-zh-v1.5"
QUERY_PREFIX = "为这个句子生成表示以用于检索相关文章："
CACHE = ROOT / "_emb_cache.npz"
EXTERNAL = Path("/Users/kunfenglai/Downloads/router_train.jsonl")

SKILLS = [
    "paper-analysis", "companion-listen", "deepwiki", "lark-im", "channels",
    "skills-manager", "lark-shared", "legal-assistant",
]
LABELS = SKILLS + ["others"]
LABEL2ID = {l: i for i, l in enumerate(LABELS)}

# 文件与模型重合的 7 类（评测口径）
OVERLAP = ["paper-analysis", "companion-listen", "deepwiki", "lark-im",
           "channels", "skills-manager", "lark-shared"]


class Encoder:
    def __init__(self, onnx_path):
        self.sess = ort.InferenceSession(str(onnx_path), providers=["CPUExecutionProvider"])
        self.tok = AutoTokenizer.from_pretrained(BASE_MODEL)
        self.input_names = {i.name for i in self.sess.get_inputs()}

    def encode(self, texts, batch_size=64):
        out = []
        for i in range(0, len(texts), batch_size):
            chunk = texts[i:i + batch_size]
            batch = self.tok(chunk, padding=True, truncation=True, max_length=64, return_tensors="np")
            feeds = {k: v for k, v in batch.items() if k in self.input_names}
            o = self.sess.run(None, feeds)[0]
            emb = o[:, 0, :]
            emb = emb / (np.linalg.norm(emb, axis=1, keepdims=True) + 1e-8)
            out.append(emb)
        return np.vstack(out)


def load_external():
    """返回 (texts, label_ids)，只保留重合 7 类。统计被忽略的类。"""
    texts, labels = [], []
    ignored = {}
    for line in open(EXTERNAL, encoding="utf-8"):
        r = json.loads(line)
        lab = r["answer"]
        if lab in LABEL2ID and lab in OVERLAP:
            texts.append(r["query"])
            labels.append(LABEL2ID[lab])
        else:
            ignored[lab] = ignored.get(lab, 0) + 1
    return texts, np.array(labels), ignored


def main():
    d = np.load(CACHE, allow_pickle=True)
    Xtr, ytr = d["train_X"], d["train_y"]
    print(f"train 缓存 {Xtr.shape}")

    clf = LogisticRegression(max_iter=2000, C=10.0, class_weight="balanced")
    clf.fit(Xtr, ytr)

    enc = Encoder(INT8)
    texts, yte, ignored = load_external()
    print(f"外部 test 重合 7 类共 {len(texts)} 条")
    print(f"被忽略（模型不认识的类）：{ignored}")
    Xte = enc.encode([QUERY_PREFIX + t for t in texts])

    proba = clf.predict_proba(Xte)
    pred = proba.argmax(1)
    maxp = proba.max(1)

    reject_id = LABEL2ID["others"]

    def report(floor):
        p2 = np.where(maxp < floor, reject_id, pred)
        ps, rs, fs = [], [], []
        present = sorted(set(yte.tolist()))
        print(f"\n=== FLOOR={floor:.2f} ===")
        print(f"{'skill':<18}{'P':>7}{'R':>7}{'F1':>7}{'n':>6}")
        for sid in present:
            tp = int(np.sum((p2 == sid) & (yte == sid)))
            fp = int(np.sum((p2 == sid) & (yte != sid)))
            fn = int(np.sum((p2 != sid) & (yte == sid)))
            p = tp / (tp + fp) if (tp + fp) else 0.0
            r = tp / (tp + fn) if (tp + fn) else 0.0
            f = 2 * p * r / (p + r) if (p + r) else 0.0
            ps.append(p); rs.append(r); fs.append(f)
            n = int(np.sum(yte == sid))
            print(f"{LABELS[sid]:<18}{p:>7.3f}{r:>7.3f}{f:>7.3f}{n:>6}")
        print(f"{'macro':<18}{np.mean(ps):>7.3f}{np.mean(rs):>7.3f}{np.mean(fs):>7.3f}")
        acc = float(np.mean(p2 == yte))
        rej_n = int(np.sum(p2 == reject_id))
        print(f"accuracy={acc:.3f}  被改判 others 的条数={rej_n}")
        return np.mean(fs)

    for fl in [0.0, 0.50, 0.55, 0.65]:
        report(fl)

    # 误判分析：FLOOR=0 时每个真实类被错判成了什么
    print("\n=== 误判流向（FLOOR=0）===")
    for sid in sorted(set(yte.tolist())):
        mask = (yte == sid) & (pred != sid)
        if not mask.any():
            continue
        wrong = pred[mask]
        from collections import Counter
        c = Counter(LABELS[w] for w in wrong)
        print(f"{LABELS[sid]:<18} 错 {int(mask.sum()):>3} → {dict(c.most_common())}")


if __name__ == "__main__":
    main()
