# -*- coding: utf-8 -*-
"""activity 域:补足到 200 条(现有 30,新增 170)。

7 个维度全覆盖,scope 以 project 为主。槽位列表按项目对齐,
multi 场景可组合同项目的多个维度。
"""
from genlib import (Atom, Ids, single, noise, corr, multi, obs, rep,
                    unconfirmed, interleave)

D = "activity"
M = "activity"

PROJ = ["ethan-agent", "skill-router-eval", "memory-eval", "paper-reproduction",
        "data-pipeline", "web-frontend", "recsys-upgrade", "agent-benchmark",
        "mobile-app", "payment-service", "search-rerank", "lark-integration",
        "docs-site", "infra-migration"]
# 与 PROJ 对齐的职责/目标/阻塞/截止/等待/完成槽位
RESP = ["记忆提取链路", "评测体系", "golden 样本建设", "数据复现", "任务调度",
        "首屏性能", "召回策略", "基准设计", "推送模块", "对账逻辑",
        "排序特征", "消息卡片", "文档结构", "镜像构建"]
GOAL = ["跑通结构化记忆", "覆盖全维度 golden", "补齐到每域 200 条", "复现核心指标",
        "日批稳定运行", "首屏降到 1.5 秒", "召回率提升 3 个点", "拉出第一版榜单",
        "送达率到 99%", "对账零差错", "NDCG 提升 2 个点", "消息可交互",
        "上线新版式", "构建时间减半"]
BLOCK = ["依赖方没排期", "测试环境不稳定", "标注人力不够", "集群配额不足",
         "上游数据延迟", "设计稿没定", "老接口文档缺失", "评测机不够",
         "证书没批下来", "对账口径没对齐", "线上数据拿不到", "对方接口老变",
         "没人评审", "网络策略没开通"]
DDL = ["这周五", "月底", "下周三", "Q3 末", "双周内", "这月底",
       "下周一", "本季度末", "周五前", "月中", "下周五", "月底",
       "这周", "下月底"]
WAIT = ["法务审批", "客户反馈", "设计稿", "依赖方接口", "评测结果",
        "老板拍板", "安全审查", "数据交付", "预算批复", "第三方验收",
        "开源协议确认", "对方联调时间", "编辑排期", "机房窗口"]
DONE = ["第一期", "数据采集", "接口联调", "核心重构", "压测",
        "灰度验证", "榜单对齐", "离线链路", "推送通道", "历史数据迁移",
        "特征下线", "机器人注册", "旧站迁移", "流水线改造"]


def A(dim, msg, quote, content, proj):
    return Atom(M, dim, msg, quote, content, scope=("project", proj))


def pools():
    P = {}
    P["activity.project"] = (
        [A("activity.project", f"我现在主要在做{p}。", f"主要在做{p}", f"用户当前主要项目是{p}", p) for p in PROJ] +
        [A("activity.project", f"最近精力都在{p}上。", f"精力都在{p}上", f"用户最近精力在{p}项目", p) for p in PROJ[:8]] +
        [A("activity.project", f"我这季度 OKR 里挂着{p}。", f"OKR 里挂着{p}", f"用户本季度 OKR 包含{p}", p) for p in PROJ[8:10]]
    )
    P["activity.responsibility"] = (
        [A("activity.responsibility", f"在{p}里我负责{r}。", f"我负责{r}", f"用户在{p}负责{r}", p)
         for p, r in zip(PROJ[:12], RESP[:12])] +
        [A("activity.responsibility", f"{p}的{r}归我管。", f"{r}归我管", f"用户负责{p}的{r}", p)
         for p, r in zip(PROJ[8:14], RESP[8:14])] +
        [A("activity.responsibility", f"{p}的{r}是我兜底。", f"{r}是我兜底", f"用户在{p}兜底{r}", p)
         for p, r in zip(PROJ[:4], RESP[:4])]
    )
    P["activity.goal"] = (
        [A("activity.goal", f"{p}这周的目标是{g}。", f"目标是{g}", f"{p}本周目标是{g}", p)
         for p, g in zip(PROJ[:12], GOAL[:12])] +
        [A("activity.goal", f"做{p}就是为了{g}。", f"就是为了{g}", f"{p}的目标是{g}", p)
         for p, g in zip(PROJ[6:14], GOAL[6:14])] +
        [A("activity.goal", f"{p}下一步要做到{g}。", f"下一步要做到{g}", f"{p}下一步目标是{g}", p)
         for p, g in zip(PROJ[:4], GOAL[:4])]
    )
    P["activity.blocker"] = (
        [A("activity.blocker", f"{p}卡在{b}了。", f"卡在{b}", f"{p}当前卡在{b}", p)
         for p, b in zip(PROJ[:12], BLOCK[:12])] +
        [A("activity.blocker", f"现在最大的阻塞是{b}，{p}动不了。", f"最大的阻塞是{b}", f"{p}最大阻塞是{b}", p)
         for p, b in zip(PROJ[6:14], BLOCK[6:14])] +
        [A("activity.blocker", f"{p}就剩{b}这个坑了。", f"就剩{b}这个坑", f"{p}剩余阻塞是{b}", p)
         for p, b in zip(PROJ[:4], BLOCK[:4])]
    )
    P["activity.deadline"] = (
        [A("activity.deadline", f"{p}{d}前要上线。", f"{d}前要上线", f"{p}{d}前要上线", p)
         for p, d in zip(PROJ[:12], DDL[:12])] +
        [A("activity.deadline", f"{d}是{p}的硬 deadline。", f"{d}是{p}的硬 deadline", f"{p}硬 deadline 是{d}", p)
         for p, d in zip(PROJ[6:14], DDL[6:14])] +
        [A("activity.deadline", f"{p}最晚{d}得交付。", f"最晚{d}得交付", f"{p}最晚{d}交付", p)
         for p, d in zip(PROJ[:4], DDL[:4])]
    )
    P["activity.waiting"] = (
        [A("activity.waiting", f"{p}在等{w}。", f"在等{w}", f"{p}在等待{w}", p)
         for p, w in zip(PROJ[:12], WAIT[:12])] +
        [A("activity.waiting", f"{w}没下来之前，{p}动不了。", f"{w}没下来之前", f"{p}在等待{w}", p)
         for p, w in zip(PROJ[6:14], WAIT[6:14])] +
        [A("activity.waiting", f"{p}就差{w}了，到了就能动。", f"就差{w}了", f"{p}在等待{w}", p)
         for p, w in zip(PROJ[:4], WAIT[:4])]
    )
    P["activity.recent_completion"] = (
        [A("activity.recent_completion", f"{p}的{t}刚搞完。", f"{t}刚搞完", f"{p}的{t}刚完成", p)
         for p, t in zip(PROJ[:12], DONE[:12])] +
        [A("activity.recent_completion", f"昨天把{p}的{t}收尾了。", f"把{p}的{t}收尾了", f"用户昨天完成{p}的{t}", p)
         for p, t in zip(PROJ[6:14], DONE[6:14])] +
        [A("activity.recent_completion", f"{p}的{t}上周交付了。", f"{t}上周交付了", f"{p}的{t}上周已交付", p)
         for p, t in zip(PROJ[:4], DONE[:4])]
    )
    return P


def build(nid):
    cases = []
    P = pools()
    dims = list(P.keys())
    pool = interleave([P[d] for d in dims])

    # single_explicit:110 条
    for a in pool[:110]:
        cases.append(single(nid(), D, a))

    # noise:14 条
    for i, a in enumerate(pool[110:124]):
        cases.append(noise(nid(), D, a, i))

    # observed_single:12 条
    for a in pool[124:136]:
        cases.append(obs(nid(), D, a))

    # observed_repeat:8 条
    for i, a in enumerate(pool[136:144]):
        cases.append(rep(nid(), D, a, i))

    # correction:12 条(deadline/blocker/goal 变更多见)
    corr_pairs = [
        (P["activity.deadline"][0], P["activity.deadline"][1]),
        (P["activity.deadline"][2], P["activity.deadline"][3]),
        (P["activity.blocker"][0], P["activity.blocker"][1]),
        (P["activity.goal"][0], P["activity.goal"][1]),
        (P["activity.project"][0], P["activity.project"][1]),
        (P["activity.responsibility"][0], P["activity.responsibility"][1]),
        (P["activity.waiting"][0], P["activity.waiting"][1]),
        (P["activity.recent_completion"][0], P["activity.recent_completion"][1]),
        (P["activity.deadline"][4], P["activity.deadline"][5]),
        (P["activity.blocker"][2], P["activity.blocker"][3]),
        (P["activity.goal"][2], P["activity.goal"][3]),
        (P["activity.project"][2], P["activity.project"][3]),
    ]
    for i, (old, new) in enumerate(corr_pairs):
        cases.append(corr(nid(), D, old, new, i))

    # multi_fact_one_turn:9 条(同项目多维,索引对齐即同项目)
    multi_sets = [
        [P["activity.project"][i], P["activity.goal"][i]] for i in range(3)
    ] + [
        [P["activity.blocker"][i], P["activity.waiting"][i]] for i in range(3)
    ] + [
        [P["activity.project"][4], P["activity.deadline"][4], P["activity.responsibility"][4]],
        [P["activity.recent_completion"][5], P["activity.goal"][5]],
        [P["activity.blocker"][5], P["activity.deadline"][5]],
    ]
    for atoms in multi_sets:
        cases.append(multi(nid(), D, atoms))

    # assistant_unconfirmed:5 条
    cases.append(unconfirmed(nid(), D,
        "我手头项目有点多，你看怎么排？",
        "建议你把 ethan-agent 列为最高优先级。",
        "我再想想，几个都挺急。"))
    cases.append(unconfirmed(nid(), D,
        "这个项目 deadline 是不是太紧了？",
        "建议你和老板争取延期一周。",
        "先试试吧，不一定会延。"))
    cases.append(unconfirmed(nid(), D,
        "我被卡在依赖方那里了，咋办？",
        "建议升级给双方老板协调。",
        "先私下催催，不想闹大。"))
    cases.append(unconfirmed(nid(), D,
        "要不要把这周的迭代砍一半？",
        "建议砍范围保质量。",
        "我再评估下，不一定砍。"))
    cases.append(unconfirmed(nid(), D,
        "我刚做完一个大版本，接下来干啥好？",
        "建议先复盘再排新需求。",
        "歇两天再说。"))

    return cases


if __name__ == "__main__":
    from genlib import validate
    cs = build(Ids("ext_act", 31))
    assert len(cs) == 170, f"应生成 170 条,实际 {len(cs)}"
    errs = validate(cs, set(pools().keys()), M)
    if errs:
        print("校验失败:")
        for e in errs:
            print(" -", e)
        raise SystemExit(1)
    print(f"activity: {len(cs)} 条生成并校验通过")
