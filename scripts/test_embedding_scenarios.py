"""扩展测试 BGE embedding 在 Ethan 实际场景下的效果。

覆盖三大使用场景：
1. memory consolidation 的 insight 去重（核心场景）
2. knowledge base 的语义搜索召回
3. fact_sync 镜像 vs 新 insight 的去重判定

每类跑多组 case，输出对比表，便于直接判读。
"""
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ethan.memory.embeddings import _hash_embed, _try_get_encoder

# ── 工具 ──────────────────────────────────────────────────────────

def cos(a, b) -> float:
    return sum(x * y for x, y in zip(a, b)) / (
        math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b)) + 1e-9
    )


def l2(a, b) -> float:
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b)))


# 两个 encoder：BGE 和 hash fallback
def bge_encode(text: str):
    enc = _try_get_encoder()
    if enc is None:
        return None
    return enc.encode(text)


def hash_encode(text: str):
    return _hash_embed(text)


# ── 场景 1：memory consolidation 的 insight 去重 ──────────────────
# 这些是 LLM 从 daily signals 精炼出来的"永久记忆"描述句
# 期望：相同意图的句子高相似（>0.7），不同意图低相似（<0.5）

MEMORY_DEDUP_CASES = [
    # (label, A, B, expected: high/medium/low, reason)
    ("偏好-同义改写",
     "用户偏好使用 pnpm 作为 Node.js 包管理器",
     "用户倾向使用 pnpm 做 Node 项目依赖管理",
     "high", "同义句，应判重"),

    ("偏好-完全不同主题",
     "用户偏好使用 pnpm 作为 Node.js 包管理器",
     "用户偏好用 Docker 容器化部署服务",
     "low", "不同主题"),

    ("技术约束-同义换词",
     "SQLite 不支持宿主机和容器跨进程并发写入",
     "SQLite 数据库无法在多进程间同时写入",
     "high", "同义约束"),

    ("工作流-同义",
     "代码改动通过新建 Git worktree 提交 PR",
     "修改代码走 worktree 分支并发起 Pull Request",
     "high", "同义工作流"),

    ("规范-字面近义不同",
     "敏感密钥统一存放于 ~/.ethan/.secrets/ 目录",
     "敏感配置统一放在 .local 目录并加入 .gitignore",
     "low", "都是敏感配置但目录和机制不同"),

    ("细节差异-频率",
     "每日 0 点触发记忆沉淀",
     "每小时触发一次记忆沉淀",
     "low", "只有频率不同，容易误判"),

    ("反义-喜欢 vs 讨厌",
     "用户喜欢 TUI 界面的 CLI 工具",
     "用户讨厌 TUI 界面的 CLI 工具",
     "low", "态度相反，但 BGE 可能误判"),

    ("概念上下位",
     "需要配置 basePath 才能部署到 GitHub Pages",
     "部署 Next.js 静态站点需要配置 basePath",
     "high", "上下位关系，语义相近"),

    ("完全无关",
     "今天天气不错适合散步",
     "需要配置 basePath 才能部署到 GitHub Pages",
     "low", "完全无关"),
]


# ── 场景 2：knowledge base 语义搜索 ──────────────────────────────
# 模拟知识库里存的笔记标题/内容 vs 用户的查询
# 期望：相关查询 cos > 0.5，无关查询 cos < 0.3

KB_SEARCH_CASES = [
    # (label, doc_text, query, expected, reason)
    ("文档-Docker 构建问题",
     "Docker 构建代理陷阱：宿主机 127.0.0.1 代理会导致容器内失败，需用 host.docker.internal",
     "docker build 为什么报 connection refused",
     "high", "用户描述症状，文档讲原因"),

    ("文档-SQLite 隔离",
     "SQLite 不支持跨进程并发写入，必须物理隔离数据库文件",
     "为什么 sessions.db 要分开存放",
     "high", "用户问现象，文档讲原理"),

    ("文档-技能同步",
     "_init_default_skills 会同步 references 目录下的新增或更新文件",
     "新增的 skill 参考文件怎么生效",
     "high", "用户问操作，文档讲机制"),

    ("文档-视频链接处理",
     "YouTube、Bilibili、抖音链接必须通过 getnote 技能处理",
     "抖音视频怎么提取笔记",
     "high", "用户问具体平台，文档讲通用规则"),

    ("文档-完全不相关",
     "Docker 构建代理陷阱：宿主机 127.0.0.1 代理会导致容器内失败",
     "小红书怎么发帖",
     "low", "完全无关领域"),

    ("文档-部分相关",
     "pnpm 11 在 CI 中遇到 ignoredBuiltDependencies 建议用 npx next build 绕过",
     "npm install 失败怎么办",
     "medium", "都是包管理问题但工具不同"),
]


# ── 场景 3：fact_sync 镜像 vs 新 insight 去重判定 ─────────────────
# 这是 daily_consolidation 的关键场景：先把 facts.json 同步进 memory.db（fact_sync），
# 然后新 insight 通过 L2 距离判断是否重复。
# 阈值 L2_DEDUP_THRESHOLD = 1.1（对应 cosine ≈ 0.4）
# 期望：重复 fact 的 L2 < 1.1，新 fact 的 L2 > 1.1

FACT_SYNC_CASES = [
    # (label, existing_fact, new_insight, should_dedup: True/False, reason)
    ("已有偏好-同义改写",
     "用户偏好使用 pnpm 作为 Node.js 包管理器",
     "用户倾向用 pnpm 管理 Node 依赖",
     True, "同义，应判重跳过"),

    ("已有偏好-不同领域",
     "用户偏好使用 pnpm 作为 Node.js 包管理器",
     "用户偏好用 Docker 容器化部署",
     False, "不同领域，应保留"),

    ("已有规范-字面相近",
     "敏感密钥统一存放于 ~/.ethan/.secrets/ 目录",
     "敏感密钥统一存放于 ~/.ethan/.secrets/ 下",
     True, "几乎完全相同，应判重"),

    ("已有规范-语义同义",
     "记忆沉淀宁缺勿滥，使用 embedding 去重",
     "长期记忆要精挑细选不要堆砌",
     True, "纯同义换词，应判重"),

    ("已有错误-不同错误",
     "Docker 构建用 127.0.0.1 代理会失败",
     "SQLite 跨进程并发写入会锁死",
     False, "两个不同错误，都应保留"),
]


# ── 执行测试 ──────────────────────────────────────────────────────

L2_DEDUP_THRESHOLD = 0.7  # 与 daily_consolidation.py 保持一致
COS_HIGH = 0.7
COS_LOW = 0.4


def eval_pair(a: str, b: str):
    """返回 (hash_cos, bge_cos, hash_l2, bge_l2)。BGE 不可用时 bge_* 为 None。"""
    ha, hb = hash_encode(a), hash_encode(b)
    h_cos, h_l2 = cos(ha, hb), l2(ha, hb)

    ba = bge_encode(a)
    bb = bge_encode(b)
    if ba is None or bb is None:
        return h_cos, None, h_l2, None
    return h_cos, cos(ba, bb), h_l2, l2(ba, bb)


def run_memory_dedup() -> None:
    print("\n" + "=" * 100)
    print("场景 1：memory consolidation 的 insight 去重")
    print("判定规则：high 期望 cos > 0.7，low 期望 cos < 0.4，medium 区间算误判")
    print("=" * 100)
    print(f"{'类别':<22} {'期望':<6} {'hash':>7} {'BGE':>7}  {'判定':<6} 句对")
    print("-" * 100)

    correct = 0
    total = len(MEMORY_DEDUP_CASES)
    for label, a, b, exp, reason in MEMORY_DEDUP_CASES:
        h_cos, b_cos, _, _ = eval_pair(a, b)
        bge_str = f"{b_cos:.3f}" if b_cos is not None else "  N/A"
        # 用 BGE 判定
        if b_cos is not None:
            pred = "high" if b_cos > COS_HIGH else ("low" if b_cos < COS_LOW else "medium")
        else:
            pred = "  ?"
        ok = "✓" if pred == exp else "✗"
        if pred == exp:
            correct += 1
        print(f"{label:<22} {exp:<6} {h_cos:>7.3f} {bge_str:>7}  {pred:<6}{ok} {a[:30]} ↔ {b[:30]}")

    print("-" * 100)
    print(f"BGE 准确率: {correct}/{total} ({correct * 100 // total}%)")


def run_kb_search() -> None:
    print("\n" + "=" * 100)
    print("场景 2：knowledge base 语义搜索召回")
    print("判定规则：high 期望 cos > 0.5，low 期望 cos < 0.3，medium 算边缘")
    print("=" * 100)
    print(f"{'类别':<24} {'期望':<6} {'hash':>7} {'BGE':>7}  {'判定':<6} 查询")
    print("-" * 100)

    correct = 0
    total = len(KB_SEARCH_CASES)
    for label, doc, query, exp, reason in KB_SEARCH_CASES:
        h_cos, b_cos, _, _ = eval_pair(doc, query)
        bge_str = f"{b_cos:.3f}" if b_cos is not None else "  N/A"
        if b_cos is not None:
            pred = "high" if b_cos > 0.5 else ("low" if b_cos < 0.3 else "medium")
        else:
            pred = "  ?"
        ok = "✓" if pred == exp else "✗"
        if pred == exp:
            correct += 1
        print(f"{label:<24} {exp:<6} {h_cos:>7.3f} {bge_str:>7}  {pred:<6}{ok} {query[:30]}")

    print("-" * 100)
    print(f"BGE 准确率: {correct}/{total} ({correct * 100 // total}%, medium 视为错误)")


def run_fact_sync_dedup() -> None:
    print("\n" + "=" * 100)
    print("场景 3：fact_sync 镜像 vs 新 insight 的 L2 去重判定")
    print(f"判定规则：L2 < {L2_DEDUP_THRESHOLD} 判为重复（跳过），否则保留")
    print("=" * 100)
    print(f"{'类别':<24} {'期望':<8} {'hash_L2':>8} {'BGE_L2':>8}  {'判定':<8} 说明")
    print("-" * 100)

    correct = 0
    total = len(FACT_SYNC_CASES)
    for label, existing, new, should_dedup, reason in FACT_SYNC_CASES:
        _, _, h_l2, b_l2 = eval_pair(existing, new)
        bge_str = f"{b_l2:.3f}" if b_l2 is not None else "    N/A"
        # 用 BGE L2 判定
        if b_l2 is not None:
            pred_dedup = b_l2 < L2_DEDUP_THRESHOLD
        else:
            pred_dedup = None
        pred_str = "dedup" if pred_dedup else ("keep" if pred_dedup is False else "?")
        expected_str = "dedup" if should_dedup else "keep"
        ok = "✓" if pred_dedup == should_dedup else "✗"
        if pred_dedup == should_dedup:
            correct += 1
        print(f"{label:<24} {expected_str:<8} {h_l2:>8.3f} {bge_str:>8}  {pred_str:<8}{ok} {reason}")

    print("-" * 100)
    print(f"BGE 准确率: {correct}/{total} ({correct * 100 // total}%)")


def main() -> None:
    print("=" * 100)
    print("BGE-small-zh INT8 ONNX 在 Ethan 实际场景下的效果测试")
    print("=" * 100)

    enc = _try_get_encoder()
    if enc is None:
        print("\n[警告] BGE encoder 不可用，只跑 hash fallback 对比")
    else:
        print(f"\nBGE encoder: {'✓ 可用' if enc else '✗ 不可用'}")

    run_memory_dedup()
    run_kb_search()
    run_fact_sync_dedup()

    print("\n" + "=" * 100)
    print("判读指南：")
    print("  - 场景 1（核心）：同义句能否识别为重复，避免重复存储 insight")
    print("  - 场景 2：用户查询能否语义匹配到相关文档（召回率）")
    print("  - 场景 3：fact_sync 镜像去重，L2 < 1.1 判为重复跳过")
    print("  - 'medium' 在所有场景都算误判（保守口径）")
    print("=" * 100)


if __name__ == "__main__":
    main()
