"""统计 BGE embedding 的 L2 距离分布，为新阈值提供数据支撑。

对归一化向量：L2² = 2(1 - cos_sim)，所以 L2 ∈ [0, 2]
- L2 = 0   → cos = 1.0（完全相同）
- L2 = 0.5 → cos = 0.875
- L2 = 1.0 → cos = 0.5
- L2 = 1.414 → cos = 0.0
- L2 = 2.0 → cos = -1.0（完全相反）
"""
import asyncio
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ethan.memory.embeddings import _try_get_encoder


def cos(a, b) -> float:
    return sum(x * y for x, y in zip(a, b)) / (
        math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b)) + 1e-9
    )


def l2(a, b) -> float:
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b)))


# ── 三类样本对，统计 L2 分布 ──────────────────────────────────────

# 完全相同（应判重）
IDENTICAL = [
    "用户偏好使用 pnpm 作为 Node.js 包管理器",
    "敏感密钥统一存放于 ~/.ethan/.secrets/ 目录",
    "每日 0 点触发记忆沉淀",
]

# 同义改写（应判重）
SYNONYM_PAIRS = [
    ("用户偏好使用 pnpm 作为 Node.js 包管理器", "用户倾向用 pnpm 管理 Node 依赖"),
    ("SQLite 不支持宿主机和容器跨进程并发写入", "SQLite 数据库无法在多进程间同时写入"),
    ("代码改动通过新建 Git worktree 提交 PR", "修改代码走 worktree 分支并发起 Pull Request"),
    ("记忆沉淀宁缺勿滥，使用 embedding 去重", "长期记忆要精挑细选不要堆砌"),
    ("需要配置 basePath 才能部署到 GitHub Pages", "部署 Next.js 静态站点需要配置 basePath"),
    ("每日 0 点触发记忆沉淀", "每天零点跑记忆整理"),
    ("敏感密钥统一存放于 ~/.ethan/.secrets/ 目录", "API Key 等敏感信息放在 ~/.ethan/.secrets/ 下"),
    ("视频链接必须通过 getnote 技能处理", "YouTube/Bilibili 链接走 getnote 而非 web_fetch"),
]

# 相似但不同主题（应保留）
SIMILAR_DIFFERENT_TOPIC = [
    ("用户偏好使用 pnpm 作为 Node.js 包管理器", "用户偏好用 Docker 容器化部署服务"),
    ("用户偏好使用 pnpm 作为 Node.js 包管理器", "用户偏好使用 npm 做 Node 项目"),
    ("Docker 构建用 127.0.0.1 代理会失败", "SQLite 跨进程并发写入会锁死"),
    ("每日 0 点触发记忆沉淀", "每小时触发一次记忆检查"),
    ("敏感密钥统一存放于 ~/.ethan/.secrets/ 目录", "敏感配置统一放在 .local 目录并加入 .gitignore"),
]

# 完全无关（应保留）
UNRELATED = [
    ("今天天气不错适合散步", "需要配置 basePath 才能部署到 GitHub Pages"),
    ("我喜欢吃火锅", "SQLite 不支持跨进程并发写入"),
    ("用户偏好使用 pnpm", "小红书发帖要注意内容规范"),
]


async def stats_pairs(pairs, label, bge_enc):
    """统计一组 pair 的 L2 距离和 cos。"""
    print(f"\n{label}:")
    print(f"  {'L2':>6}  {'cos':>6}  句对")
    l2_list, cos_list = [], []
    for a, b in pairs:
        ba = bge_enc.encode(a)
        bb = bge_enc.encode(b)
        if ba is None or bb is None:
            print("  BGE 不可用")
            return [], []
        d_l2 = l2(ba, bb)
        d_cos = cos(ba, bb)
        l2_list.append(d_l2)
        cos_list.append(d_cos)
        print(f"  {d_l2:>6.3f}  {d_cos:>6.3f}  {a[:30]} ↔ {b[:30]}")
    if l2_list:
        print("  ────────────────────────────────────────────")
        print(f"  L2  范围: [{min(l2_list):.3f}, {max(l2_list):.3f}]  均值: {sum(l2_list)/len(l2_list):.3f}")
        print(f"  cos 范围: [{min(cos_list):.3f}, {max(cos_list):.3f}]  均值: {sum(cos_list)/len(cos_list):.3f}")
    return l2_list, cos_list


async def main():
    print("=" * 80)
    print("BGE embedding L2 距离分布统计")
    print("=" * 80)
    print("公式：L2² = 2(1 - cos)，所以 L2 ∈ [0, 2]")
    print("  L2=0.3 → cos=0.955")
    print("  L2=0.5 → cos=0.875")
    print("  L2=0.7 → cos=0.755")
    print("  L2=0.9 → cos=0.595")
    print("  L2=1.1 → cos=0.395  ← 旧阈值")
    print("  L2=1.414 → cos=0.0")

    bge_enc = _try_get_encoder()
    if bge_enc is None:
        print("\n[错误] BGE encoder 不可用")
        return

    # 自比对（完全相同）
    print("\n" + "─" * 80)
    print("自比对（完全相同，应判重）:")
    print("─" * 80)
    self_l2 = []
    for text in IDENTICAL:
        v = bge_enc.encode(text)
        d = l2(v, v)
        self_l2.append(d)
    print("  L2 = 0.000（自身比对，理论值为 0）")

    # 同义对
    syn_l2, syn_cos = await stats_pairs(SYNONYM_PAIRS, "同义改写（应判重）", bge_enc)

    # 相似但不同主题
    sim_l2, sim_cos = await stats_pairs(SIMILAR_DIFFERENT_TOPIC, "相似但不同主题（应保留）", bge_enc)

    # 完全无关
    un_l2, un_cos = await stats_pairs(UNRELATED, "完全无关（应保留）", bge_enc)

    # ── 阈值建议 ──────────────────────────────────────────────
    print("\n" + "=" * 80)
    print("阈值建议")
    print("=" * 80)

    if not syn_l2 or not sim_l2:
        print("数据不足，无法给出建议")
        return

    # 找一个能区分"同义"和"相似但不同"的阈值
    # 阈值应 > 同义的最大 L2（避免漏判）
    # 阈值应 < 相似但不同的最小 L2（避免误判）
    syn_max = max(syn_l2)
    sim_min = min(sim_l2)

    print(f"  同义改写 L2 最大值: {syn_max:.3f}")
    print(f"  相似但不同 L2 最小值: {sim_min:.3f}")

    if syn_max < sim_min:
        # 有清晰分隔区间
        mid = (syn_max + sim_min) / 2
        print("\n  ✓ 有清晰分隔区间！")
        print(f"    同义区间上限: {syn_max:.3f}")
        print(f"    不同区间下限: {sim_min:.3f}")
        print(f"    建议阈值: {mid:.3f}（区间中点）")
        print(f"    对应 cos: {1 - (mid**2)/2:.3f}")
    else:
        # 有重叠，需要权衡
        print(f"\n  ⚠ 有重叠区间！同义最大 {syn_max:.3f} > 相似最小 {sim_min:.3f}")
        # 计算不同阈值下的准确率
        print("\n  不同阈值下的表现:")
        print(f"  {'阈值':>6}  {'cos':>6}  {'同义判重率':>10}  {'不同保留率':>10}  {'综合':>6}")
        for threshold in [0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0, 1.1]:
            syn_correct = sum(1 for x in syn_l2 if x < threshold) / len(syn_l2)
            sim_correct = sum(1 for x in sim_l2 if x >= threshold) / len(sim_l2)
            overall = (syn_correct + sim_correct) / 2
            cos_val = 1 - (threshold**2) / 2
            mark = " ←" if threshold in [0.7, 0.8] else ""
            print(f"  {threshold:>6.2f}  {cos_val:>6.3f}  {syn_correct*100:>9.0f}%  {sim_correct*100:>9.0f}%  {overall*100:>5.0f}%{mark}")

    print("\n" + "=" * 80)
    print("结论:")
    print("  旧阈值 L2 < 1.1（cos ≈ 0.4）太宽松")
    print("  当前阈值: L2 < 0.7（cos ≈ 0.755）")
    print("  依据: 同义改写 L2 通常 < 0.7，不同主题 L2 通常 > 0.7")
    print("=" * 80)


if __name__ == "__main__":
    asyncio.run(main())
