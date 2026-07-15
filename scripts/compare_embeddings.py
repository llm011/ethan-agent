"""对比多种 embedding 模型在中文语义场景下的实际效果。

用法：
    uv run python scripts/compare_embeddings.py

第一次运行会自动下载所需模型（all-MiniLM-L6-v2 ~22MB, bge-small-zh-v1.5 ~95MB）。
"""
import math
import time
from typing import Callable

# ── 测试集 ──────────────────────────────────────────────────────
# 分 3 类：同义对、字面相似但语义不同、完全无关
TEST_PAIRS = [
    # (label, 句子A, 句子B, 期望相似度: high/medium/low)
    ("偏好同义",      "我喜欢用 pnpm 做 Node 项目", "我偏好使用 pnpm 作为包管理器", "high"),
    ("偏好反义",      "我喜欢用 pnpm",               "我讨厌 pnpm 总是出问题",       "low"),
    ("同义改写",      "SQLite 不支持跨进程并发写入", "SQLite 无法在多进程间并发写",   "high"),
    ("同义换词",      "记忆沉淀宁缺勿滥",            "长期记忆要精挑细选不要堆砌",   "high"),
    ("字面近语义远",  "我喜欢 pnpm",                  "我喜欢 npm pnpm yarn",         "low"),
    ("完全无关",      "今天天气不错",                "我偏好使用 pnpm",              "low"),
    ("技术近义",      "用 docker compose 启动服务",  "通过 docker-compose 拉起容器", "high"),
    ("细节差异",      "每天 0 点跑 consolidation",   "每小时跑一次 consolidation",  "low"),
]


def cosine_sim(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb + 1e-9)


def l2_dist(a: list[float], b: list[float]) -> float:
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b)))


def eval_model(name: str, encode_fn: Callable[[str], list[float]]) -> None:
    print(f"\n{'=' * 78}")
    print(f"模型: {name}")
    print(f"{'=' * 78}")
    print(f"{'类别':<14} {'期望':<6} {'cos':>7} {'L2':>7}  句对")
    print("-" * 78)

    correct = 0
    total = len(TEST_PAIRS)
    t0 = time.time()
    for label, a, b, expected in TEST_PAIRS:
        va, vb = encode_fn(a), encode_fn(b)
        cos = cosine_sim(va, vb)
        l2 = l2_dist(va, vb)
        # 判定逻辑：cos > 0.7 视为 high，< 0.4 视为 low
        pred = "high" if cos > 0.7 else ("low" if cos < 0.4 else "medium")
        ok = "✓" if pred == expected else "✗"
        if pred == expected:
            correct += 1
        print(f"{label:<14} {expected:<6} {cos:>7.3f} {l2:>7.3f} {ok} {a} ↔ {b}")

    elapsed = time.time() - t0
    print("-" * 78)
    print(f"准确率: {correct}/{total} ({correct * 100 // total}%)  总耗时: {elapsed:.2f}s")


def try_minilm():
    from sentence_transformers import SentenceTransformer
    m = SentenceTransformer("all-MiniLM-L6-v2")
    print("  → all-MiniLM-L6-v2: dim=384, params=22M, size≈22.7MB")
    return lambda s: m.encode(s).tolist()


def try_bge_small_zh():
    from sentence_transformers import SentenceTransformer
    m = SentenceTransformer("BAAI/bge-small-zh-v1.5")
    print("  → bge-small-zh-v1.5: dim=512, params=24M, size≈95MB")
    return lambda s: m.encode(s).tolist()


def try_bge_base_zh():
    """bge-base-zh-v1.5：1024 维，体积 ~400MB，作为质量上限参考。"""
    from sentence_transformers import SentenceTransformer
    m = SentenceTransformer("BAAI/bge-base-zh-v1.5")
    print("  → bge-base-zh-v1.5: dim=1024, params=102M, size≈400MB")
    return lambda s: m.encode(s).tolist()


def try_hash_fallback():
    """当前 Ethan 使用的兜底 hash embedding，作为基线。"""
    from ethan.memory.embeddings import _hash_embed
    print("  → hash_fallback (当前生产): dim=384, size=0")
    return _hash_embed


def main() -> None:
    print("=" * 78)
    print("中文 embedding 模型对比")
    print("=" * 78)
    print("测试集说明：")
    print("  - high: 同义改写，期望 cos > 0.7")
    print("  - low:  无关或反义，期望 cos < 0.4")
    print("  - medium 被视为错误判定")
    print()

    candidates = [
        ("hash_fallback (当前)", try_hash_fallback),
        ("all-MiniLM-L6-v2",    try_minilm),
        ("bge-small-zh-v1.5",   try_bge_small_zh),
        ("bge-base-zh-v1.5",    try_bge_base_zh),  # 质量上限参考，可选
    ]

    for name, loader in candidates:
        try:
            encode_fn = loader()
            eval_model(name, encode_fn)
        except Exception as e:
            print(f"\n[SKIP] {name}: {e}")

    print("\n" + "=" * 78)
    print("判读指南：")
    print("  - 关注 'high' 行：cos 越高越好（>0.7 算合格）")
    print("  - 关注 'low'  行：cos 越低越好（<0.4 算合格）")
    print("  - 当前 hash 兜底在 '同义换词' 上几乎必败（字面不重合）")
    print("=" * 78)


if __name__ == "__main__":
    main()
