#!/usr/bin/env python3
"""训练 LR 路由分类头并评测（BGE INT8 embedding → LogisticRegression，开集拒识）。

流程：
  1. 用 BGE INT8 ONNX 把 train/val/test 全部编码成 512 维向量（缓存到 .npz）。
  2. 在 train 上训练 9 类 LogisticRegression（others 作为真实一类，靠 trap 样本学边界）。
  3. val 扫 FLOOR：max_prob < FLOOR 的预测改判 others（额外拒识），选最优工作点。
  4. test 只跑一次，出 macro P/R/F1（8 个 skill 口径）+ others 拒识率。

数据位置（核心资产，不在本仓库）：
  train/ val/ test/ 的 *.jsonl 放在私有 repo
  https://github.com/llm011/ethan-memory-train-data 的 router/ 目录
  跑之前先把三个 split 目录拷到本目录下（或软链）。详见同目录 README.md。

跑法：
  uv run --with scikit-learn --with onnxruntime --with transformers --with numpy \
    python paper_work/router_dataset/train_lr_router.py
"""
from __future__ import annotations

import glob
import json
from pathlib import Path

import numpy as np
import onnxruntime as ort
from sklearn.linear_model import LogisticRegression
from transformers import AutoTokenizer

ROOT = Path(__file__).resolve().parent
INT8 = ROOT.parent / "bge_onnx_quant" / "model_quant.onnx"
FP32 = ROOT.parent / "bge_onnx" / "model.onnx"
BASE_MODEL = "BAAI/bge-small-zh-v1.5"
# 分类用的是 query，BGE query 要加指令前缀
QUERY_PREFIX = "为这个句子生成表示以用于检索相关文章："
CACHE = ROOT / "_emb_cache.npz"
# LR 头落盘到运行时包内（随包分发，~20KB）；ONNX 不落这里，运行时从 HF 下载
MAX_LENGTH = 144  # 必须与运行时 router.py encode 的 max_length 一致
# 长 query 头尾保留（与 ethan/skills/router.py _splice_long 完全一致）：
# 粘贴长文档时意图句常在结尾，纯头部截断会丢意图
SPLICE_HEAD = 76
SPLICE_TAIL = 40


def splice_long(text: str) -> str:
    if len(text) <= SPLICE_HEAD + SPLICE_TAIL + 3:
        return text
    return text[:SPLICE_HEAD] + "\n…\n" + text[-SPLICE_TAIL:]
LR_HEAD_OUT = ROOT.parents[1] / "ethan" / "skills" / "router_models" / "lr_head.npz"

SKILLS = [
    # 原有 8 类
    "paper-analysis", "companion-listen", "deepwiki", "lark-im", "channels",
    "skills-manager", "lark-shared", "legal-assistant",
    # 新扩 9 类
    "code-review", "computer-use", "getnote", "lark-doc",
    "upload-cdn", "use-browser",
    "finance-query", "travel-query", "ui-card",
    # ppt 技能（PR #116）：主题/要点/长 markdown → 演示材料
    "ppt-generate",
]
LABELS = SKILLS + ["others"]
LABEL2ID = {lbl: i for i, lbl in enumerate(LABELS)}


class Encoder:
    def __init__(self, onnx_path):
        self.sess = ort.InferenceSession(str(onnx_path), providers=["CPUExecutionProvider"])
        self.tok = AutoTokenizer.from_pretrained(BASE_MODEL)
        self.input_names = {i.name for i in self.sess.get_inputs()}

    def encode(self, texts, batch_size=64):
        out = []
        for i in range(0, len(texts), batch_size):
            chunk = [splice_long(t) for t in texts[i:i + batch_size]]
            batch = self.tok(chunk, padding=True, truncation=True, max_length=MAX_LENGTH, return_tensors="np")
            feeds = {k: v for k, v in batch.items() if k in self.input_names}
            o = self.sess.run(None, feeds)[0]
            emb = o[:, 0, :]
            emb = emb / (np.linalg.norm(emb, axis=1, keepdims=True) + 1e-8)
            out.append(emb)
        return np.vstack(out)


def load_split(split):
    texts, labels = [], []
    for f in sorted(glob.glob(str(ROOT / split / "*.jsonl"))):
        for line in open(f, encoding="utf-8"):
            r = json.loads(line)
            texts.append(r["text"])
            labels.append(LABEL2ID[r["label"]])
    return texts, np.array(labels)


def build_embeddings():
    if CACHE.exists():
        d = np.load(CACHE, allow_pickle=True)
        return {k: d[k] for k in d.files}
    enc = Encoder(INT8)
    data = {}
    for split in ["train", "val", "test"]:
        texts, labels = load_split(split)
        print(f"编码 {split}: {len(texts)} 条...")
        emb = enc.encode([QUERY_PREFIX + t for t in texts])
        data[f"{split}_X"] = emb
        data[f"{split}_y"] = labels
    np.savez(CACHE, **data)
    return data


def macro_prf(y_true, y_pred, reject_id):
    """对 8 个 skill 算 macro P/R/F1；others 单独算拒识率。"""
    ps, rs, fs = [], [], []
    for sid in range(len(SKILLS)):
        tp = int(np.sum((y_pred == sid) & (y_true == sid)))
        fp = int(np.sum((y_pred == sid) & (y_true != sid)))
        fn = int(np.sum((y_pred != sid) & (y_true == sid)))
        p = tp / (tp + fp) if (tp + fp) else 0.0
        r = tp / (tp + fn) if (tp + fn) else 0.0
        f = 2 * p * r / (p + r) if (p + r) else 0.0
        ps.append(p)
        rs.append(r)
        fs.append(f)
    oth_mask = y_true == reject_id
    oth_total = int(np.sum(oth_mask))
    oth_reject = int(np.sum((y_pred == reject_id) & oth_mask))
    rej = oth_reject / oth_total if oth_total else 0.0
    return np.mean(ps), np.mean(rs), np.mean(fs), rej, (ps, rs, fs)


def main():
    data = build_embeddings()
    Xtr, ytr = data["train_X"], data["train_y"]
    Xva, yva = data["val_X"], data["val_y"]
    Xte, yte = data["test_X"], data["test_y"]
    print(f"train {Xtr.shape}  val {Xva.shape}  test {Xte.shape}")

    reject_id = LABEL2ID["others"]
    clf = LogisticRegression(max_iter=2000, C=10.0, class_weight="balanced")
    clf.fit(Xtr, ytr)

    def predict_with_floor(X, floor):
        proba = clf.predict_proba(X)
        pred = proba.argmax(1)
        maxp = proba.max(1)
        # 低置信 → 改判 others
        pred = np.where(maxp < floor, reject_id, pred)
        return pred

    # val 扫 FLOOR（综合 F1 与拒识）
    print("\n=== val FLOOR 扫描 ===")
    print(f"{'FLOOR':>6} {'macroP':>8}{'macroR':>8}{'macroF1':>9}{'拒识':>8}")
    best = None
    for floor in [x / 100 for x in range(0, 95, 5)]:
        pred = predict_with_floor(Xva, floor)
        p, r, f, rej, _ = macro_prf(yva, pred, reject_id)
        combo = f * 0.85 + rej * 0.15
        if best is None or combo > best[0]:
            best = (combo, floor, f, rej)
        if floor % 0.1 < 1e-9 or floor in (0.45, 0.55, 0.65):
            print(f"{floor:>6.2f} {p:>8.2f}{r:>8.2f}{f:>9.2f}{rej*100:>7.1f}%")
    _, bfloor, bf, brej = best
    print(f"\n推荐工作点：FLOOR={bfloor:.2f}  val macroF1={bf:.2f}  拒识={brej*100:.1f}%")

    # val per-skill 明细（最优 FLOOR 下，用于诊断哪类需要补样本）
    print(f"\n=== val per-skill @ FLOOR={bfloor:.2f} ===")
    pred_va = predict_with_floor(Xva, bfloor)
    pv, rv, fv, rejv, (pvs, rvs, fvs) = macro_prf(yva, pred_va, reject_id)
    print(f"macro  P={pv:.3f}  R={rv:.3f}  F1={fv:.3f}   others 拒识={rejv*100:.1f}%")
    print(f"\n{'skill':<18}{'P':>7}{'R':>7}{'F1':>7}")
    for i, s in enumerate(SKILLS):
        flag = "  ⚠️" if fvs[i] < 0.85 else ""
        print(f"{s:<18}{pvs[i]:>7.2f}{rvs[i]:>7.2f}{fvs[i]:>7.2f}{flag}")

    # test 只跑一次
    print("\n=== test 最终评测 @ FLOOR={:.2f} ===".format(bfloor))
    pred = predict_with_floor(Xte, bfloor)
    p, r, f, rej, (ps, rs, fs) = macro_prf(yte, pred, reject_id)
    print(f"macro  P={p:.3f}  R={r:.3f}  F1={f:.3f}   others 拒识={rej*100:.1f}%")
    print(f"\n{'skill':<18}{'P':>7}{'R':>7}{'F1':>7}")
    for i, s in enumerate(SKILLS):
        flag = "  ⚠️" if fs[i] < 0.85 else ""
        print(f"{s:<18}{ps[i]:>7.2f}{rs[i]:>7.2f}{fs[i]:>7.2f}{flag}")

    # test 混淆矩阵（仅显示有错误的格子，用于定位串档对）
    print("\n=== test 混淆矩阵（非对角线 > 0 的串档格子）===")
    cm = np.zeros((len(LABELS), len(LABELS)), dtype=int)
    for true_id, pred_id in zip(yte, pred):
        cm[true_id][pred_id] += 1
    all_labels = LABELS  # skill + others
    print(f"{'真\\预':<20}", end="")
    for lbl in all_labels:
        print(f"{lbl[:10]:>12}", end="")
    print()
    has_confusion = False
    for i, true_lbl in enumerate(all_labels):
        row_errors = [(j, cm[i][j]) for j in range(len(all_labels)) if i != j and cm[i][j] > 0]
        if row_errors:
            has_confusion = True
            print(f"{true_lbl:<20}", end="")
            for j in range(len(all_labels)):
                v = cm[i][j]
                print(f"{'·' if v == 0 else v:>12}", end="")
            print()
    if not has_confusion:
        print("  （无串档，对角线完美）")

    # 也报 FLOOR=0（纯分类，others 当一类）的 test 结果做对照
    print("\n=== 对照：FLOOR=0（纯分类，无额外拒识）===")
    pred0 = predict_with_floor(Xte, 0.0)
    p0, r0, f0, rej0, _ = macro_prf(yte, pred0, reject_id)
    print(f"macro  P={p0:.3f}  R={r0:.3f}  F1={f0:.3f}   others 拒识={rej0*100:.1f}%")

    # 目标判定
    print("\n" + ("✅ 达到 88% 目标" if f >= 0.88 else f"⚠️ macroF1={f:.3f} 未达 88%，需补样本/调参"))

    # 落盘 LR 头到运行时包内（随包分发）
    save_lr_head(clf, bfloor)


def save_lr_head(clf, floor):
    """把 LR 头序列化到 ethan/skills/router_models/lr_head.npz。

    运行时只需 numpy 即可复现 predict_proba：softmax(emb·coefᵀ + intercept)。
    labels 按 clf.classes_ 顺序映射回标签名，与 coef 行一一对应。
    """
    labels = [LABELS[c] for c in clf.classes_]
    LR_HEAD_OUT.parent.mkdir(parents=True, exist_ok=True)
    np.savez(
        LR_HEAD_OUT,
        coef=clf.coef_.astype(np.float32),
        intercept=clf.intercept_.astype(np.float32),
        labels=np.array(labels),
        query_prefix=QUERY_PREFIX,
        max_length=MAX_LENGTH,
        floor=float(floor),
        emb_dim=clf.coef_.shape[1],
    )
    print(f"\n✅ LR 头已落盘：{LR_HEAD_OUT}  (coef={clf.coef_.shape}, floor={floor:.2f}, labels={labels})")


if __name__ == "__main__":
    main()