# -*- coding: utf-8 -*-
"""preference 域:补足到 200 条(现有 30,新增 170)。

11 个白名单维度全覆盖;negative_pref 场景走 preference.negative 维度。
"""
from genlib import (Atom, Ids, single, noise, corr, multi, obs, rep,
                    unconfirmed, interleave)

D = "preference"
M = "preference"

TOOLS = ["VSCode", "iTerm2", "Notion", "Excalidraw", "TablePlus", "Arc",
         "Obsidian", "Postman"]


def pools():
    P = {}
    comm = ["有事直接说，别绕弯子", "重要的事微信说，别打电话", "汇报先说结论，再讲过程",
            "讨论问题对事不对人", "有分歧当面说，别背后传话", "消息尽量一次性说完，别分好多条",
            "跟我同步进展用列表，别写大段", "约我之前先发个消息确认", "有坏消息也直说，别粉饰",
            "跨团队的事拉群同步，别只私聊", "电话里说完的事，再补一条文字记录",
            "评审意见写具体点，别只说「不太好」", "有进度当天同步，别过夜",
            "分歧升级前先私下对齐"]
    P["preference.communication"] = (
        [Atom(M, "preference.communication", f"{c}。", c, f"用户沟通偏好:{c}") for c in comm[:8]] +
        [Atom(M, "preference.communication", f"我的原则是:{c}。", f"原则是:{c}", f"用户沟通原则:{c}") for c in comm[8:14]]
    )
    P["preference.language"] = [
        Atom(M, "preference.language", "代码注释用英文写。", "注释用英文写", "用户要求代码注释用英文"),
        Atom(M, "preference.language", "文档统一用中文。", "文档统一用中文", "用户要求文档统一用中文"),
        Atom(M, "preference.language", "commit message 用英文。", "commit message 用英文", "用户要求 commit message 用英文"),
        Atom(M, "preference.language", "变量名用英文，注释用中文。", "变量名用英文", "用户要求变量名用英文"),
        Atom(M, "preference.language", "对外邮件用英文，内部用中文。", "对外邮件用英文", "用户对外邮件用英文"),
        Atom(M, "preference.language", "API 文档我写英文的。", "API 文档我写英文的", "用户的 API 文档用英文"),
        Atom(M, "preference.language", "命名别用拼音，用英文。", "别用拼音", "用户反对命名用拼音"),
        Atom(M, "preference.language", "周报用中文写就行。", "周报用中文写", "用户周报用中文"),
        Atom(M, "preference.language", "错误信息用英文，方便搜索。", "错误信息用英文", "用户要求错误信息用英文"),
        Atom(M, "preference.language", "注释里别写拼音缩写。", "别写拼音缩写", "用户反对注释写拼音缩写"),
        Atom(M, "preference.language", "日志级别名用英文大写。", "日志级别名用英文大写", "用户要求日志级别名英文大写"),
        Atom(M, "preference.language", "对外文案先写中文再翻译。", "先写中文再翻译", "用户对外文案先中文后翻译"),
    ]
    P["preference.tone"] = [
        Atom(M, "preference.tone", "跟我说话不用太客气，直接点。", "不用太客气，直接点", "用户希望对话直接不客套"),
        Atom(M, "preference.tone", "评审的时候语气软一点。", "语气软一点", "用户希望评审语气柔和"),
        Atom(M, "preference.tone", "回复别用太多感叹号。", "别用太多感叹号", "用户不喜欢过多感叹号"),
        Atom(M, "preference.tone", "别跟我说「您」，别扭。", "别跟我说「您」", "用户不希望被称「您」"),
        Atom(M, "preference.tone", "批评我的时候私下说。", "私下说", "用户希望批评私下进行"),
        Atom(M, "preference.tone", "正式场合称呼我全名。", "称呼我全名", "用户正式场合希望被称全名"),
        Atom(M, "preference.tone", "开玩笑可以，别拿体重开涮。", "别拿体重开涮", "用户不接受拿体重开玩笑"),
        Atom(M, "preference.tone", "讨论技术别用贬低别人的词。", "别用贬低别人的词", "用户要求技术讨论不贬低他人"),
        Atom(M, "preference.tone", "跟我汇报别铺垫太久。", "别铺垫太久", "用户汇报不喜欢长铺垫"),
        Atom(M, "preference.tone", "坏消息别绕，直接告诉我。", "坏消息别绕", "用户希望坏消息直说"),
        Atom(M, "preference.tone", "群里@我别加「收到请回复」。", "别加「收到请回复」", "用户不喜欢被要求回复收到"),
        Atom(M, "preference.tone", "夸我可以，别过头。", "别过头", "用户接受夸奖但不喜欢过度"),
    ]
    P["preference.tools"] = (
        [Atom(M, "preference.tools", f"我的主力工具是{t}。", f"主力工具是{t}", f"用户主力工具是{t}") for t in TOOLS] +
        [Atom(M, "preference.tools", f"{t}用了很多年，习惯了。", f"{t}用了很多年", f"用户长期使用{t}") for t in TOOLS]
    )
    habits = ["上午写代码，下午开会", "动手前先写个设计文档", "一次只做一件事",
              "下班前过一遍待办", "先跑通最小版本再迭代", "改代码前先写测试",
              "大块时间留给深度工作", "每天站会前更新看板", "重要决策写下来再执行",
              "周五下午留给自己看文档", "重要的事约在上午状态好", "开完会当场定下一步",
              "需求不清就先问清楚再动手", "每周一上午规划整周"]
    P["preference.work_habits"] = (
        [Atom(M, "preference.work_habits", f"我习惯{h}。", f"习惯{h}", f"用户工作习惯:{h}") for h in habits[:6]] +
        [Atom(M, "preference.work_habits", f"我一般{h}。", f"一般{h}", f"用户工作习惯:{h}") for h in habits[6:14]]
    )
    P["preference.schedule"] = [
        Atom(M, "preference.schedule", "别在早上十点前找我开会。", "别在早上十点前找我开会", "用户早上十点前不开会"),
        Atom(M, "preference.schedule", "我晚上十点后不看工作消息。", "十点后不看工作消息", "用户晚上十点后不看工作消息"),
        Atom(M, "preference.schedule", "周五下午我一般不排会。", "周五下午我一般不排会", "用户周五下午不排会"),
        Atom(M, "preference.schedule", "我习惯午休一小时，一点后找我。", "一点后找我", "用户午休到一点"),
        Atom(M, "preference.schedule", "周会放在周一上午。", "周会放在周一上午", "用户周会固定在周一上午"),
        Atom(M, "preference.schedule", "我周三下午固定健身，别排事。", "周三下午固定健身", "用户周三下午健身不排事"),
        Atom(M, "preference.schedule", "加班可以，提前一天说。", "提前一天说", "用户接受加班但需提前一天通知"),
        Atom(M, "preference.schedule", "早上六点到八点是我自己的学习时间。", "六点到八点是我自己的学习时间", "用户早上六到八点是学习时间"),
        Atom(M, "preference.schedule", "晚上九点后别打电话，发消息就行。", "九点后别打电话", "用户晚上九点后不接电话"),
        Atom(M, "preference.schedule", "午饭十二点半，别提前约事。", "十二点半", "用户午饭十二点半"),
        Atom(M, "preference.schedule", "每月最后一天我做复盘，别排会。", "最后一天我做复盘", "用户每月最后一天复盘"),
        Atom(M, "preference.schedule", "节假日前一天不排发布。", "前一天不排发布", "用户节假日前一天不发布"),
    ]
    P["preference.content"] = [
        Atom(M, "preference.content", "讲概念的时候多举例子。", "多举例子", "用户希望讲概念多举例子"),
        Atom(M, "preference.content", "给我代码的时候带上注释。", "带上注释", "用户要求代码带注释"),
        Atom(M, "preference.content", "解释问题时先给个大局观。", "先给个大局观", "用户希望先有大局观再展开"),
        Atom(M, "preference.content", "我喜欢看表格对比，别光文字。", "看表格对比", "用户偏好表格对比"),
        Atom(M, "preference.content", "引用资料给我附上链接。", "附上链接", "用户要求引用资料附链接"),
        Atom(M, "preference.content", "给我方案时带上风险分析。", "带上风险分析", "用户要求方案带风险分析"),
        Atom(M, "preference.content", "示例数据用中文的。", "示例数据用中文的", "用户要求示例数据用中文"),
        Atom(M, "preference.content", "别只给结论，推理过程也给我。", "推理过程也给我", "用户要求给推理过程"),
        Atom(M, "preference.content", "给我例子时贴近我的场景。", "贴近我的场景", "用户希望例子贴近其场景"),
        Atom(M, "preference.content", "专业术语第一次出现给个解释。", "第一次出现给个解释", "用户要求术语首现给解释"),
        Atom(M, "preference.content", "对比方案时告诉我你推荐哪个。", "推荐哪个", "用户希望对比方案时给推荐项"),
        Atom(M, "preference.content", "数据给出来源和口径。", "来源和口径", "用户要求数据带来源口径"),
    ]
    trade = ["宁可选简单可靠的方案，不要花哨的", "性能优先，代码丑点没关系",
             "先保证正确性，再谈优化", "我倾向买现成的服务，不自研",
             "稳定压倒一切，新特性可以等", "能复用就不重写",
             "宁多写代码，不引入新依赖", "短期能跑就行，别过度设计",
             "安全第一，便利性可以让步", "用户体验优先，实现复杂点也认",
             "时间紧就先砍范围不砍质量", "长期可维护优先于短期省事",
             "可控比炫酷重要", "能灰度就不全量"]
    P["preference.decision_tradeoff"] = [Atom(M, "preference.decision_tradeoff", f"{t}。", t, f"用户取舍偏好:{t}") for t in trade]
    P["preference.boundary"] = [
        Atom(M, "preference.boundary", "工作的事别拿到饭桌上说。", "别拿到饭桌上说", "用户饭桌上不谈工作"),
        Atom(M, "preference.boundary", "我的私人行程别同步给同事。", "私人行程别同步给同事", "用户私人行程不同步同事"),
        Atom(M, "preference.boundary", "周末别给我派活。", "周末别给我派活", "用户周末不接活"),
        Atom(M, "preference.boundary", "涉及钱的事必须我本人确认。", "必须我本人确认", "用户要求涉钱事项本人确认"),
        Atom(M, "preference.boundary", "别替我向别人承诺时间。", "别替我向别人承诺时间", "用户不许代其承诺时间"),
        Atom(M, "preference.boundary", "家里的事工作时间不谈。", "工作时间不谈", "用户工作时间不谈家事"),
        Atom(M, "preference.boundary", "我的简历别外发给任何人。", "简历别外发", "用户简历不许外发"),
        Atom(M, "preference.boundary", "家里人的信息别写进任何文档。", "家里人的信息别写进任何文档", "用户家人信息不入文档"),
        Atom(M, "preference.boundary", "工作账号不加私人好友。", "不加私人好友", "用户工作账号不加私人好友"),
        Atom(M, "preference.boundary", "下班后不谈工作，急事打电话。", "下班后不谈工作", "用户下班后不谈工作"),
    ]
    P["preference.response_verbosity"] = [
        Atom(M, "preference.response_verbosity", "回复简短点，三行以内。", "三行以内", "用户要求回复三行以内"),
        Atom(M, "preference.response_verbosity", "给我详细展开，别省。", "详细展开，别省", "用户要求回复详细展开"),
        Atom(M, "preference.response_verbosity", "先给结论，细节我问再说。", "先给结论", "用户要求先给结论"),
        Atom(M, "preference.response_verbosity", "代码直接给完整可跑的。", "给完整可跑的", "用户要求代码完整可跑"),
        Atom(M, "preference.response_verbosity", "解释要一步一步来。", "一步一步来", "用户要求解释分步进行"),
        Atom(M, "preference.response_verbosity", "别一次给太多，分步给。", "分步给", "用户要求内容分步给"),
        Atom(M, "preference.response_verbosity", "答案控制在 100 字内。", "100 字内", "用户要求答案 100 字内"),
        Atom(M, "preference.response_verbosity", "长回复开头先给个摘要。", "先给个摘要", "用户要求长回复先给摘要"),
        Atom(M, "preference.response_verbosity", "代码片段别超过五十行。", "别超过五十行", "用户要求代码片段不超过五十行"),
        Atom(M, "preference.response_verbosity", "先给要点，要不要展开看我问不问。", "先给要点", "用户要求先给要点再按需展开"),
        Atom(M, "preference.response_verbosity", "重要结论加粗标出来。", "加粗标出来", "用户要求重要结论加粗"),
        Atom(M, "preference.response_verbosity", "分点列，每点一行。", "每点一行", "用户要求分点每点一行"),
    ]
    P["preference.negative"] = [
        Atom(M, "preference.negative", f"{n}。", n, f"用户反感:{n}")
        for n in ["不要给我写鸡汤", "别用「赋能」这种词", "别在我没问的时候给建议",
                  "不要替我做决定", "别发语音，发文字", "不要半夜给我发消息",
                  "别用表情包回复正式问题", "不要把未验证的推断写成结论",
                  "别跟我说「你想想办法」", "不要在工作群发我的私事",
                  "别把我拉进无关的会议", "不要用红色标我的名字",
                  "不要省略关键步骤", "别拿我和别人比较",
                  "不要替我回邮件", "别在报告里写未经确认的数字",
                  "不要用「尽快」，给具体时间", "别跳过测试直接上线",
                  "不要把我的草稿直接发出去", "别在我专注的时候@我"]
    ]
    return P


def build(nid):
    cases = []
    P = pools()
    dims_non_neg = [d for d in P if d != "preference.negative"]
    pool = interleave([P[d] for d in dims_non_neg])

    # single_explicit:102 条
    for a in pool[:102]:
        cases.append(single(nid(), D, a))

    # noise:12 条
    for i, a in enumerate(pool[102:114]):
        cases.append(noise(nid(), D, a, i))

    # observed_single:8 条
    for a in pool[114:122]:
        cases.append(obs(nid(), D, a))

    # observed_repeat:5 条
    for i, a in enumerate(pool[122:127]):
        cases.append(rep(nid(), D, a, i))

    # correction:10 条(同维度新旧值)
    corr_dims = ["preference.communication", "preference.language", "preference.tone",
                 "preference.tools", "preference.work_habits", "preference.schedule",
                 "preference.content", "preference.decision_tradeoff",
                 "preference.boundary", "preference.response_verbosity"]
    for i, d in enumerate(corr_dims):
        cases.append(corr(nid(), D, P[d][0], P[d][1], i))

    # multi_fact_one_turn:8 条
    multi_sets = [
        [P["preference.communication"][2], P["preference.response_verbosity"][2]],
        [P["preference.tools"][0], P["preference.work_habits"][0]],
        [P["preference.language"][0], P["preference.content"][1]],
        [P["preference.schedule"][0], P["preference.boundary"][2]],
        [P["preference.tone"][0], P["preference.communication"][0]],
        [P["preference.decision_tradeoff"][2], P["preference.work_habits"][4]],
        [P["preference.content"][3], P["preference.response_verbosity"][7]],
        [P["preference.schedule"][1], P["preference.tone"][2], P["preference.communication"][5]],
    ]
    for atoms in multi_sets:
        cases.append(multi(nid(), D, atoms))

    # negative_pref:20 条
    for a in P["preference.negative"]:
        cases.append(single(nid(), D, a, scenario="negative_pref"))

    # assistant_unconfirmed:5 条
    cases.append(unconfirmed(nid(), D,
        "你觉得我汇报风格要不要改？",
        "我建议你汇报时先讲背景再讲结论，显得更稳。",
        "嗯，我考虑下。"))
    cases.append(unconfirmed(nid(), D,
        "我在想要不要换笔记软件。",
        "推荐你试试 Notion，协作方便。",
        "迁移成本太高，先不折腾。"))
    cases.append(unconfirmed(nid(), D,
        "早上开会好还是下午开会好？",
        "按你的节奏，上午开会效率更高。",
        "不一定，看情况吧。"))
    cases.append(unconfirmed(nid(), D,
        "回复客户要不要正式一点？",
        "建议用书面语，显得更专业。",
        "我们客户都挺熟的，随意点也行。"))
    cases.append(unconfirmed(nid(), D,
        "要不要每天写日报？",
        "写日报能帮你梳理进度，建议坚持。",
        "太形式化了，我不想写。"))

    return cases


if __name__ == "__main__":
    from genlib import validate
    cs = build(Ids("ext_pref", 31))
    assert len(cs) == 170, f"应生成 170 条,实际 {len(cs)}"
    errs = validate(cs, set(pools().keys()), M)
    if errs:
        print("校验失败:")
        for e in errs:
            print(" -", e)
        raise SystemExit(1)
    print(f"preference: {len(cs)} 条生成并校验通过")
