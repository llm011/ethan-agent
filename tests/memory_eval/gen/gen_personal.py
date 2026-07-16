# -*- coding: utf-8 -*-
"""personal_information 域:补足到 200 条(现有 40,新增 160)。

维度覆盖:14 个白名单维度 + 4 个 GAP 维度(age/gender/mbti/interests,
正确标记 gap_dimension=true,extractor 白名单应拒、留作追踪)。
"""
from genlib import (Atom, Ids, single, noise, corr, multi, obs, rep,
                    unconfirmed, interleave)

D = "personal_information"
M = "personal_information"

NAMES = ["阿哲", "小渔", "老周", "Monica", "阿凯", "小林", "Vivian", "大鹏",
         "思思", "Leo", "建国", "Yuki", "老白", "Kevin", "阿May", "Grace"]
CITIES = ["北京", "上海", "深圳", "杭州", "广州", "成都", "南京", "武汉",
          "西安", "苏州", "厦门", "长沙", "重庆", "青岛", "新加坡", "东京"]
JOBS = ["产品经理", "后端工程师", "算法工程师", "设计师", "数据分析师", "独立开发者",
        "大学老师", "咨询顾问", "运营经理", "全栈工程师", "研究员", "创业者"]
MAJORS = ["计算机", "数学", "心理学", "电子工程", "经济学", "统计学", "物理", "设计"]
SKILLS = ["Python", "搜索排序", "模型评测", "系统设计", "数据分析", "Rust",
          "前端性能优化", "推荐算法", "数据库调优", "技术写作"]
FIELDS = ["搜索引擎", "推荐系统", "移动端", "量化交易", "电商后台", "SaaS",
          "广告系统", "即时通讯"]
ORGS = ["一家创业公司", "字节", "腾讯", "一家外企", "高校实验室", "一家投资机构",
        "一家国企", "一家独角兽"]
TZS = ["Asia/Shanghai", "UTC+8", "America/Los_Angeles", "Europe/Berlin",
       "Asia/Tokyo", "UTC-5", "Australia/Sydney", "Asia/Singapore"]
GOALS = ["做自己的产品", "转型技术管理", "全职独立开发", "读一个博士学位",
         "出一本技术书", "带一支更大的团队", "做开源社区", "环游世界一年"]
HOBBIES = ["徒步", "摄影", "打游戏", "做饭", "看展", "跑步", "钓鱼", "拼乐高"]


def pools():
    P = {}
    P["identity.preferred_name"] = (
        [Atom(M, "identity.preferred_name", f"你就叫我{n}吧。", f"你就叫我{n}", f"用户希望被叫做{n}") for n in NAMES[:8]] +
        [Atom(M, "identity.preferred_name", f"以后叫我{n}就行。", f"叫我{n}", f"用户希望被叫做{n}") for n in NAMES[8:14]]
    )
    P["identity.pronouns"] = [
        Atom(M, "identity.pronouns", "称呼我用「她」就好。", "称呼我用「她」", "用户希望被用「她」称呼"),
        Atom(M, "identity.pronouns", "我的代词是 they/them，麻烦了。", "代词是 they/them", "用户代词是 they/them"),
        Atom(M, "identity.pronouns", "叫我「他」就行。", "叫我「他」", "用户希望被用「他」称呼"),
        Atom(M, "identity.pronouns", "我对外一般用 he/him。", "用 he/him", "用户代词是 he/him"),
    ]
    P["identity.language"] = [
        Atom(M, "identity.language", "我们平时用中文交流就行。", "用中文交流", "用户日常交流用中文"),
        Atom(M, "identity.language", "跟我说话请用英文，我在练口语。", "请用英文", "用户希望对话用英文"),
        Atom(M, "identity.language", "我工作里主要用粤语。", "主要用粤语", "用户工作主要用粤语"),
        Atom(M, "identity.language", "文档给我英文版没问题，我看得懂。", "给我英文版没问题", "用户阅读英文文档无障碍"),
        Atom(M, "identity.language", "技术讨论用中文，术语可以夹英文。", "技术讨论用中文", "用户技术讨论用中文、术语可夹英文"),
        Atom(M, "identity.language", "回复我可以中日混着来，都看得懂。", "中日混着来", "用户可接受中日混排回复"),
    ]
    P["identity.location"] = (
        [Atom(M, "identity.location", f"我住在{c}。", f"住在{c}", f"用户住在{c}") for c in CITIES[:6]] +
        [Atom(M, "identity.location", f"我现在人在{c}。", f"人在{c}", f"用户人在{c}") for c in CITIES[6:12]] +
        [Atom(M, "identity.location", f"我 base 在{c}。", f"base 在{c}", f"用户 base 在{c}") for c in CITIES[12:16]]
    )
    P["identity.timezone"] = (
        [Atom(M, "identity.timezone", f"我时区是{t}。", f"时区是{t}", f"用户时区是{t}") for t in TZS[:5]] +
        [Atom(M, "identity.timezone", f"约时间注意下，我在{t}。", f"我在{t}", f"用户时区是{t}") for t in TZS[5:8]]
    )
    P["identity.occupation"] = (
        [Atom(M, "identity.occupation", f"我是{j}。", f"我是{j}", f"用户是{j}") for j in JOBS[:6]] +
        [Atom(M, "identity.occupation", f"我的工作是{j}。", f"工作是{j}", f"用户的工作是{j}") for j in JOBS[6:12]]
    )
    P["identity.role"] = [
        Atom(M, "identity.role", "我在团队里负责技术选型。", "负责技术选型", "用户在团队里负责技术选型"),
        Atom(M, "identity.role", "团队里项目管理是我在盯。", "项目管理是我在盯", "用户在团队里盯项目管理"),
        Atom(M, "identity.role", "代码评审一般由我兜底。", "代码评审一般由我兜底", "用户在团队里兜底代码评审"),
        Atom(M, "identity.role", "我负责跟客户对接需求。", "负责跟客户对接需求", "用户负责对接客户需求"),
        Atom(M, "identity.role", "新人入职都是我带的。", "新人入职都是我带的", "用户负责带新人"),
        Atom(M, "identity.role", "发布前的验收归我管。", "发布前的验收归我管", "用户负责发布前验收"),
    ]
    P["identity.organization"] = (
        [Atom(M, "identity.organization", f"我在{o}工作。", f"在{o}工作", f"用户在{o}工作") for o in ORGS[:5]] +
        [Atom(M, "identity.organization", f"我目前就职于{o}。", f"就职于{o}", f"用户就职于{o}") for o in ORGS[5:8]]
    )
    P["identity.education"] = (
        [Atom(M, "identity.education", f"我学的是{m}。", f"学的是{m}", f"用户学的是{m}") for m in MAJORS[:5]] +
        [Atom(M, "identity.education", f"我{m}专业出身。", f"{m}专业出身", f"用户是{m}专业出身") for m in MAJORS[5:8]] +
        [Atom(M, "identity.education", "我硕士毕业，工作五年了。", "硕士毕业", "用户硕士学历"),
         Atom(M, "identity.education", "我读过在职 MBA。", "读过在职 MBA", "用户读过在职 MBA")]
    )
    P["identity.professional_background"] = (
        [Atom(M, "identity.professional_background", f"我做过{f}，后来转的行。", f"做过{f}", f"用户做过{f}") for f in FIELDS[:5]] +
        [Atom(M, "identity.professional_background", f"我在{f}领域待了快十年。", f"在{f}领域待了快十年", f"用户在{f}领域有近十年经验") for f in FIELDS[5:8]]
    )
    P["identity.expertise"] = (
        [Atom(M, "identity.expertise", f"我擅长{s}，有问题可以问我。", f"擅长{s}", f"用户擅长{s}") for s in SKILLS[:6]] +
        [Atom(M, "identity.expertise", f"聊聊{s}吧，这块我熟。", f"{s}吧，这块我熟", f"用户熟悉{s}") for s in SKILLS[6:10]]
    )
    P["identity.relationship"] = [
        Atom(M, "identity.relationship", "我有个三岁的女儿。", "有个三岁的女儿", "用户有个三岁的女儿"),
        Atom(M, "identity.relationship", "我和女朋友一起住。", "和女朋友一起住", "用户和女朋友一起住"),
        Atom(M, "identity.relationship", "我老婆是儿科医生。", "老婆是儿科医生", "用户的爱人是儿科医生"),
        Atom(M, "identity.relationship", "家里养了只橘猫，很皮。", "养了只橘猫", "用户家里养了只橘猫"),
        Atom(M, "identity.relationship", "我跟我妈住一起，方便照顾她。", "跟我妈住一起", "用户和母亲同住方便照顾"),
        Atom(M, "identity.relationship", "我儿子今年上小学了。", "儿子今年上小学了", "用户的儿子今年上小学"),
    ]
    P["identity.accessibility"] = [
        Atom(M, "identity.accessibility", "我看屏幕需要大号字体。", "需要大号字体", "用户看屏幕需要大号字体"),
        Atom(M, "identity.accessibility", "我对颜色不敏感，图表别只用颜色区分。", "对颜色不敏感", "用户对颜色不敏感,图表需颜色外编码"),
        Atom(M, "identity.accessibility", "我听力不太好，重要的事请文字发我。", "重要的事请文字发我", "用户听力不好,重要事项需文字同步"),
        Atom(M, "identity.accessibility", "我用屏幕阅读器，链接文字写清楚点。", "用屏幕阅读器", "用户使用屏幕阅读器,链接文字需清晰"),
    ]
    P["identity.long_term_goal"] = (
        [Atom(M, "identity.long_term_goal", f"我长期想做{g}。", f"长期想做{g}", f"用户长期目标是{g}") for g in GOALS[:5]] +
        [Atom(M, "identity.long_term_goal", f"三年内我想{g}。", f"三年内我想{g}", f"用户三年内想{g}") for g in GOALS[5:8]]
    )
    return P


def gap_atoms():
    """GAP 维度:extractor 暂不支持,标记 gap_dimension=true 留作追踪。"""
    out = []
    for n in [28, 34, 41, 25, 38]:
        out.append(Atom(M, "identity.age", f"我今年{n}岁。", f"今年{n}岁", f"用户今年{n}岁", gap=True))
    for g in ["男生", "女生", "男生", "女生", "男生"]:
        out.append(Atom(M, "identity.gender", f"我是{g}。", f"我是{g}", f"用户是{g}", gap=True))
    for t in ["INTJ", "ENFP", "ISTP", "INFJ", "ENTP"]:
        out.append(Atom(M, "identity.mbti", f"我是{t}，测过好几次了。", f"我是{t}", f"用户是{t}", gap=True))
    for h in HOBBIES[:5]:
        out.append(Atom(M, "identity.interests", f"我平时喜欢{h}。", f"喜欢{h}", f"用户平时喜欢{h}", gap=True))
    return out


def build(nid):
    cases = []
    P = pools()
    pool = interleave(list(P.values()))

    # single_explicit:97 条(各维度轮转)
    for a in pool[:97]:
        cases.append(single(nid(), D, a))

    # noise:12 条
    for i, a in enumerate(pool[97:109]):
        cases.append(noise(nid(), D, a, i))

    # correction:10 条(同维度新旧值)
    corr_pairs = [
        (P["identity.preferred_name"][0], P["identity.preferred_name"][1]),
        (P["identity.location"][0], P["identity.location"][1]),
        (P["identity.location"][2], P["identity.location"][3]),
        (P["identity.occupation"][0], P["identity.occupation"][1]),
        (P["identity.timezone"][0], P["identity.timezone"][1]),
        (P["identity.organization"][0], P["identity.organization"][1]),
        (P["identity.language"][0], P["identity.language"][1]),
        (P["identity.expertise"][0], P["identity.expertise"][1]),
        (P["identity.education"][0], P["identity.education"][1]),
        (P["identity.long_term_goal"][0], P["identity.long_term_goal"][1]),
    ]
    for i, (old, new) in enumerate(corr_pairs):
        cases.append(corr(nid(), D, old, new, i))

    # multi_fact_one_turn:8 条(跨维度组合)
    multi_sets = [
        [P["identity.preferred_name"][2], P["identity.location"][4]],
        [P["identity.occupation"][2], P["identity.organization"][2]],
        [P["identity.timezone"][2], P["identity.location"][5]],
        [P["identity.education"][2], P["identity.occupation"][3]],
        [P["identity.expertise"][2], P["identity.role"][0]],
        [P["identity.relationship"][0], P["identity.location"][6]],
        [P["identity.language"][0], P["identity.timezone"][3]],
        [P["identity.preferred_name"][3], P["identity.occupation"][4], P["identity.location"][7]],
    ]
    for atoms in multi_sets:
        cases.append(multi(nid(), D, atoms))

    # observed_single:6 条
    for a in pool[109:115]:
        cases.append(obs(nid(), D, a))

    # observed_repeat:4 条
    for i, a in enumerate(pool[115:119]):
        cases.append(rep(nid(), D, a, i))

    # assistant_unconfirmed:3 条
    cases.append(unconfirmed(nid(), D,
        "你觉得我要不要换个英文名？",
        "我建议你用 Calvin，显得更专业。",
        "嗯，我再想想。"))
    cases.append(unconfirmed(nid(), D,
        "我在考虑要不要搬去杭州。",
        "杭州互联网机会多，你可以重点考虑。",
        "还早呢，先不定。"))
    cases.append(unconfirmed(nid(), D,
        "你说我要不要读个 MBA？",
        "按你的路径，读个在职 MBA 对转型有帮助。",
        "成本太高了，容我想想。"))

    # GAP:20 条
    for a in gap_atoms():
        cases.append(single(nid(), D, a))

    return cases


if __name__ == "__main__":
    from genlib import validate
    DIMS = set(pools().keys()) - {"identity.age", "identity.gender",
                                  "identity.mbti", "identity.interests"}
    cs = build(Ids("ext_personal", 41))
    assert len(cs) == 160, f"应生成 160 条,实际 {len(cs)}"
    errs = validate(cs, DIMS, M)
    if errs:
        print("校验失败:")
        for e in errs:
            print(" -", e)
        raise SystemExit(1)
    print(f"personal_information: {len(cs)} 条生成并校验通过")
