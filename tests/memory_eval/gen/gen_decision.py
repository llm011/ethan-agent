# -*- coding: utf-8 -*-
"""decision 域:补足到 200 条(现有 30,新增 170)。

8 个维度全覆盖;scope:方案类走 project,风格/约定类走 user_domain。
"""
from genlib import (Atom, Ids, single, noise, corr, multi, obs, rep,
                    unconfirmed, interleave)

D = "decision"
M = "decision"

PROJ = ["ethan-agent", "skill-router-eval", "memory-eval", "paper-reproduction",
        "data-pipeline", "web-frontend", "recsys-upgrade", "agent-benchmark",
        "mobile-app", "payment-service", "search-rerank", "lark-integration",
        "docs-site", "infra-migration"]
TECH = ["PostgreSQL", "Redis Stream", "Milvus", "Next.js", "FastAPI", "单体架构",
        "微服务", "K8s", "SQLite", "Kafka", "ClickHouse", "gRPC", "GraphQL", "Rust"]
REASON = ["生态成熟", "团队熟悉", "运维成本低", "性能足够", "迁移成本小", "社区活跃",
          "文档齐全", "招聘容易"]
PROB = ["重", "贵", "复杂", "慢", "小众", "难维护"]
COST = ["5 万", "两个人月", "三周时间", "两台机器", "一个人力", "十万行改动"]


def AP(dim, msg, quote, content, proj):
    return Atom(M, dim, msg, quote, content, scope=("project", proj))


def AU(dim, msg, quote, content, dom):
    return Atom(M, dim, msg, quote, content, scope=("user_domain", dom))


def pools():
    P = {}
    P["decision.chosen"] = (
        [AP("decision.chosen", f"{p}定了，用{x}。", f"用{x}", f"{p}决定采用{x}", p)
         for p, x in zip(PROJ, TECH)] +
        [AP("decision.chosen", f"定了，{p}上{x}方案。", f"上{x}方案", f"{p}决定采用{x}", p)
         for p, x in zip(PROJ[:4], TECH[4:8])]
    )
    P["decision.rejected"] = (
        [AP("decision.rejected", f"{p}不用{x}了，太{pr}。", f"不用{x}了", f"{p}否决了{x},因为太{pr}", p)
         for p, x, pr in zip(PROJ[:10], TECH[:10], PROB * 2)] +
        [AP("decision.rejected", f"{x}方案否了，{pr}扛不住。", f"{x}方案否了", f"{p}否决了{x},{pr}扛不住", p)
         for p, x, pr in zip(PROJ[4:12], TECH[4:12], (PROB + PROB[:2]))] +
        [AP("decision.rejected", f"{p}放弃{x}路线。", f"放弃{x}路线", f"{p}放弃{x}路线", p)
         for p, x in zip(PROJ[:2], TECH[10:12])]
    )
    P["decision.rationale"] = (
        [AU("decision.rationale", f"选{x}是因为{r}。", f"选{x}是因为{r}", f"用户选{x}的理由是{r}", "technical_decision")
         for x, r in zip(TECH[:10], REASON + REASON[:2])] +
        [AU("decision.rationale", f"之所以上{x}，主要是{r}。", f"上{x}，主要是{r}", f"用户选{x}主要因为{r}", "technical_decision")
         for x, r in zip(TECH[4:12], REASON)] +
        [AU("decision.rationale", f"用{x}没别的原因，就是{r}。", f"就是{r}", f"用户选{x}纯粹因为{r}", "technical_decision")
         for x, r in zip(TECH[:2], REASON[2:4])]
    )
    P["decision.constraint"] = (
        [AP("decision.constraint", f"{p}预算不能超过{c}。", f"预算不能超过{c}", f"{p}预算约束为不超过{c}", p)
         for p, c in zip(PROJ[:10], COST + COST[:4])] +
        [AP("decision.constraint", f"{p}有个硬约束：{c}封顶。", f"硬约束：{c}封顶", f"{p}硬约束是{c}封顶", p)
         for p, c in zip(PROJ[4:12], (COST + COST[:2]))] +
        [AP("decision.constraint", f"{p}不能引入新的云服务，这是红线。", "不能引入新的云服务", f"{p}红线是不引入新云服务", p)
         for p in PROJ[:2]]
    )
    P["decision.commitment"] = (
        [AP("decision.commitment", f"我承诺{d}前{t}。", f"承诺{d}前{t}", f"用户承诺{d}前{t}", p)
         for p, d, t in zip(PROJ[:10],
                            ["周五", "月底", "下周三", "这周末", "月中", "下周一", "季度末", "双周内", "月底", "周五"],
                            ["给评测报告", "交设计稿", "上线灰度", "完成联调", "出复盘", "交付初版", "完成迁移", "交验收材料", "修完 P0", "给选型结论"])] +
        [AP("decision.commitment", f"{p}我来兜底，出问题找我。", f"我来兜底", f"用户承诺为{p}兜底", p)
         for p in PROJ[:6]] +
        [AP("decision.commitment", f"{p}这期一定交付，我立字据。", f"这期一定交付", f"用户承诺{p}本期交付", p)
         for p in PROJ[6:8]]
    )
    P["decision.agreement"] = (
        [AU("decision.agreement", f"说好了，{a}。", f"说好了，{a}", f"双方约定:{a}", dom)
         for a, dom in [
             ("review 只提最严重的三处", "code_review"),
             ("发布必须两人确认", "release"),
             ("需求变更先评审再改", "project_execution"),
             ("接口变更提前三天通知", "api_design"),
             ("线上问题半小时内响应", "incident_response"),
             ("文档随代码一起更新", "documentation"),
             ("评审 24 小时内给意见", "code_review"),
             ("站会不超过十五分钟", "collaboration"),
             ("新依赖先评估再引入", "coding"),
             ("测试环境每周重置", "testing")]] +
        [AU("decision.agreement", f"团队约定：{a}。", f"团队约定：{a}", f"团队约定:{a}", dom)
         for a, dom in [
             ("周五不发布", "release"),
             ("主分支保持可发布", "coding"),
             ("事故复盘对事不对人", "incident_response"),
             ("会议纪要当天发出", "collaboration"),
             ("大改动先写设计文档", "technical_planning"),
             ("线上配置变更双人复核", "devops")]] +
        [AU("decision.agreement", "就这么定了：灰度期间每天看一次数据。", "灰度期间每天看一次数据", "约定灰度期间每天看数据", "release"),
         AU("decision.agreement", "一致同意：接口先冻结再联调。", "接口先冻结再联调", "约定接口冻结后再联调", "api_design")]
    )
    P["decision.deadline"] = (
        [AP("decision.deadline", f"{p}选型{d}前必须定。", f"选型{d}前必须定", f"{p}选型须{d}前定", p)
         for p, d in zip(PROJ[:10], ["周五", "月底", "下周", "季度末", "月中", "下周一", "双周内", "月底", "周五", "下周"])] +
        [AP("decision.deadline", f"{d}前给结论，不定就按默认方案走。", f"{d}前给结论", f"{p}决策时限是{d}", p)
         for p, d in zip(PROJ[4:12], ["周五", "月底", "下周三", "月中", "下周一", "季度末", "双周内", "月底"])] +
        [AP("decision.deadline", f"{p}这事不能拖过{d}。", f"不能拖过{d}", f"{p}决策不能拖过{d}", p)
         for p, d in zip(PROJ[:2], ["本季度", "下个月"])]
    )
    P["decision.correction"] = (
        [AP("decision.correction", f"之前定的{x}作废，改{y}。", f"{x}作废，改{y}", f"{p}决策修正:{x}改为{y}", p)
         for p, x, y in zip(PROJ[:10], TECH[:10], TECH[4:14])] +
        [AP("decision.correction", f"收回昨天的决定，{p}还是用{x}。", f"还是用{x}", f"{p}修正决定:仍用{x}", p)
         for p, x in zip(PROJ[4:12], TECH[2:10])] +
        [AP("decision.correction", f"上次说的{x}不算数，{p}维持现状。", f"{x}不算数", f"{p}撤销采用{x}的决定", p)
         for p, x in zip(PROJ[:2], TECH[10:12])]
    )
    return P


def build(nid):
    cases = []
    P = pools()
    dims = list(P.keys())
    pool = interleave([P[d] for d in dims])

    # single_explicit:105 条
    for a in pool[:105]:
        cases.append(single(nid(), D, a))

    # noise:14 条
    for i, a in enumerate(pool[105:119]):
        cases.append(noise(nid(), D, a, i))

    # observed_single:12 条
    for a in pool[119:131]:
        cases.append(obs(nid(), D, a))

    # observed_repeat:8 条
    for i, a in enumerate(pool[131:139]):
        cases.append(rep(nid(), D, a, i))

    # correction:12 条(注意:这些是「事实陈述的纠正」,correction 维度本身也是主题之一)
    corr_pairs = [
        (P["decision.chosen"][0], P["decision.chosen"][1]),
        (P["decision.chosen"][2], P["decision.chosen"][3]),
        (P["decision.rejected"][0], P["decision.rejected"][1]),
        (P["decision.rationale"][0], P["decision.rationale"][1]),
        (P["decision.constraint"][0], P["decision.constraint"][1]),
        (P["decision.commitment"][0], P["decision.commitment"][1]),
        (P["decision.agreement"][0], P["decision.agreement"][1]),
        (P["decision.deadline"][0], P["decision.deadline"][1]),
        (P["decision.correction"][0], P["decision.correction"][1]),
        (P["decision.chosen"][4], P["decision.chosen"][5]),
        (P["decision.deadline"][2], P["decision.deadline"][3]),
        (P["decision.constraint"][2], P["decision.constraint"][3]),
    ]
    for i, (old, new) in enumerate(corr_pairs):
        cases.append(corr(nid(), D, old, new, i))

    # multi_fact_one_turn:10 条
    multi_sets = [
        [P["decision.chosen"][i], P["decision.rationale"][i]] for i in range(3)
    ] + [
        [P["decision.rejected"][i], P["decision.chosen"][i + 4]] for i in range(3)
    ] + [
        [P["decision.chosen"][6], P["decision.deadline"][6]],
        [P["decision.constraint"][4], P["decision.chosen"][8]],
        [P["decision.agreement"][2], P["decision.agreement"][3]],
        [P["decision.commitment"][2], P["decision.deadline"][4], P["decision.chosen"][10]],
    ]
    for atoms in multi_sets:
        cases.append(multi(nid(), D, atoms))

    # assistant_unconfirmed:9 条
    cases.append(unconfirmed(nid(), D,
        "选型你有什么建议？",
        "我建议用 PostgreSQL，生态最成熟。",
        "嗯，我再对比下。"))
    cases.append(unconfirmed(nid(), D,
        "这个方案你觉得行不行？",
        "我觉得可以，风险主要在迁移。",
        "我还没想好。"))
    cases.append(unconfirmed(nid(), D,
        "要不要引入 Kafka？",
        "以现在的量级，建议先不上。",
        "先放着吧。"))
    cases.append(unconfirmed(nid(), D,
        "前端框架选哪个好？",
        "团队熟悉 Next.js，建议用它。",
        "我再看看 Svelte。"))
    cases.append(unconfirmed(nid(), D,
        "要不要把服务拆成微服务？",
        "现阶段单体能扛，建议不拆。",
        "有道理也没道理，再议。"))
    cases.append(unconfirmed(nid(), D,
        "存储引擎换 ClickHouse 怎么样？",
        "分析场景适合，但运维成本高。",
        "成本高就算了。"))
    cases.append(unconfirmed(nid(), D,
        "deploy 用 K8s 有必要吗？",
        "几台机器用不上 K8s，docker compose 够。",
        "先不折腾。"))
    cases.append(unconfirmed(nid(), D,
        "要不要写个 RFC 再定？",
        "建议写，大改动值得。",
        "太正式了，先口头对齐。"))
    cases.append(unconfirmed(nid(), D,
        "第三方服务买还是自建？",
        "建议买，省心。",
        "预算不够，自建吧。"))

    return cases


if __name__ == "__main__":
    from genlib import validate
    cs = build(Ids("ext_dec", 31))
    assert len(cs) == 170, f"应生成 170 条,实际 {len(cs)}"
    errs = validate(cs, set(pools().keys()), M)
    if errs:
        print("校验失败:")
        for e in errs:
            print(" -", e)
        raise SystemExit(1)
    print(f"decision: {len(cs)} 条生成并校验通过")
