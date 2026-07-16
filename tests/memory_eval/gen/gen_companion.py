# -*- coding: utf-8 -*-
"""companion 域:补足到 200 条(现有 50,新增 150)。

10 个维度全覆盖;正样本 mode=companion、scope=(mode,companion)。
负样本:companion_leak(非 companion 模式)×15 + diagnostic_reject(诊断词)×15。
禁止词与 extractors._COMPANION_DENIED_TERMS 对齐,正样本绝不出现。
"""
from genlib import (Atom, Ids, single, noise, corr, multi, obs, rep,
                    leak, diag, interleave)

D = "companion"
M = "companion"
SC = ("mode", "companion")


def CA(dim, msg, quote, content, level="explicit"):
    return Atom(M, dim, msg, quote, content, level=level, scope=SC)


def pools():
    P = {}
    P["companion.current_emotion"] = [
        CA("companion.current_emotion", "我最近压力好大，晚上睡不着。", "压力好大", "用户最近压力大、睡眠受影响", "observed"),
        CA("companion.current_emotion", "今天特别开心，项目终于上线了。", "特别开心", "用户今天因项目上线开心", "observed"),
        CA("companion.current_emotion", "这几天心里挺烦躁的。", "心里挺烦躁", "用户这几天心情烦躁", "observed"),
        CA("companion.current_emotion", "我现在特别低落，什么都不想干。", "特别低落", "用户当前情绪低落", "observed"),
        CA("companion.current_emotion", "最近总是心慌，静不下来。", "总是心慌", "用户最近心慌静不下来", "observed"),
        CA("companion.current_emotion", "我现在状态特别好，干劲十足。", "状态特别好", "用户当前状态积极", "observed"),
        CA("companion.current_emotion", "这周过得特别累，身心俱疲。", "身心俱疲", "用户这周身心俱疲", "observed"),
        CA("companion.current_emotion", "我有点慌，明天要述职。", "有点慌", "用户因明天述职发慌", "observed"),
        CA("companion.current_emotion", "我现在很平静，想通了一些事。", "很平静", "用户当前心情平静", "observed"),
        CA("companion.current_emotion", "这段时间情绪起伏挺大的。", "情绪起伏挺大", "用户这段时间情绪起伏大", "observed"),
        CA("companion.current_emotion", "我挺委屈的，明明不是我的问题。", "挺委屈", "用户感到委屈", "observed"),
        CA("companion.current_emotion", "最近老是提不起劲。", "提不起劲", "用户最近提不起劲", "observed"),
    ]
    P["companion.current_stressor"] = [
        CA("companion.current_stressor", "压力主要来自月底的述职。", "月底的述职", "用户压力源是月底述职"),
        CA("companion.current_stressor", "最让我头疼的是房贷。", "房贷", "用户压力源是房贷"),
        CA("companion.current_stressor", "最近的压力都是孩子上学的事。", "孩子上学的事", "用户压力源是孩子上学"),
        CA("companion.current_stressor", "我主要愁的是找工作的事。", "找工作的事", "用户压力源是找工作"),
        CA("companion.current_stressor", "老板天天催进度，我快扛不住了。", "老板天天催进度", "用户压力源是老板催进度"),
        CA("companion.current_stressor", "压力都来自家里催婚。", "家里催婚", "用户压力源是家里催婚"),
        CA("companion.current_stressor", "最烦的是跟同事的合作不顺。", "合作不顺", "用户压力源是与同事合作不顺"),
        CA("companion.current_stressor", "最近项目上线的事让我睡不好。", "项目上线的事", "用户压力源是项目上线"),
        CA("companion.current_stressor", "我愁的是爸妈的身体。", "爸妈的身体", "用户压力源是父母健康"),
        CA("companion.current_stressor", "主要是经济压力大，入不敷出。", "经济压力大", "用户压力源是经济入不敷出"),
        CA("companion.current_stressor", "让我紧张的是下周的面试。", "下周的面试", "用户压力源是下周面试"),
        CA("companion.current_stressor", "论文截稿是我现在最大的山。", "论文截稿", "用户压力源是论文截稿"),
    ]
    P["companion.emotional_event"] = [
        CA("companion.emotional_event", "上周被裁员了，到现在还没缓过来。", "上周被裁员了", "用户上周被裁员,至今未缓过来"),
        CA("companion.emotional_event", "前天跟爱人吵了一架，挺难受的。", "跟爱人吵了一架", "用户前天与爱人吵架"),
        CA("companion.emotional_event", "昨天小猫走了，我哭了一晚上。", "小猫走了", "用户的猫昨天离世"),
        CA("companion.emotional_event", "上个月体检查出问题，一直担心着。", "体检查出问题", "用户上月体检查出问题"),
        CA("companion.emotional_event", "上周答辩过了，心里一块石头落地。", "答辩过了", "用户上周答辩通过"),
        CA("companion.emotional_event", "前两天被朋友误会了，心里别扭。", "被朋友误会了", "用户被朋友误会"),
        CA("companion.emotional_event", "这周孩子高考完，全家都松了口气。", "孩子高考完", "用户孩子本周高考结束"),
        CA("companion.emotional_event", "上周末搬家累瘫了，现在还没收拾完。", "搬家累瘫了", "用户上周末搬家劳累"),
        CA("companion.emotional_event", "昨天求婚成功了，太激动了。", "求婚成功了", "用户昨天求婚成功"),
        CA("companion.emotional_event", "这周复查结果不太好，有点受打击。", "复查结果不太好", "用户本周复查结果不佳"),
        CA("companion.emotional_event", "前阵子投资亏了不少，一直郁闷。", "投资亏了不少", "用户投资亏损郁闷"),
        CA("companion.emotional_event", "昨天差点出车祸，现在想起来还后怕。", "差点出车祸", "用户昨天差点出车祸后怕"),
    ]
    P["companion.support_need"] = [
        CA("companion.support_need", "这次你听着就行，不用给方案。", "听着就行", "用户此次只想被倾听", "observed"),
        CA("companion.support_need", "我现在需要你帮我理理思路。", "帮我理理思路", "用户此刻希望梳理思路", "observed"),
        CA("companion.support_need", "陪我聊会儿，我一个人有点闷。", "陪我聊会儿", "用户此刻希望陪伴", "observed"),
        CA("companion.support_need", "你直接告诉我该怎么办吧。", "直接告诉我该怎么办", "用户此刻希望直接获得建议", "observed"),
        CA("companion.support_need", "先别安慰，让我把苦水倒完。", "让我把苦水倒完", "用户此刻想先倾诉完", "observed"),
        CA("companion.support_need", "你帮我分析下，是我错了吗？", "是我错了吗", "用户此刻想要客观分析", "observed"),
        CA("companion.support_need", "我就想找个人说说话。", "找个人说说话", "用户此刻想找人说话", "observed"),
        CA("companion.support_need", "给我打打气吧，明天面试。", "给我打打气", "用户此刻希望被鼓励", "observed"),
        CA("companion.support_need", "以后我烦的时候，先听我说十分钟再回应。", "先听我说十分钟再回应", "用户希望烦躁时先被倾听十分钟"),
        CA("companion.support_need", "别急着解决，陪我骂两句就行。", "陪我骂两句就行", "用户此刻只想宣泄", "observed"),
        CA("companion.support_need", "我需要你帮我把最坏的情况想一遍。", "把最坏的情况想一遍", "用户此刻想推演最坏情况", "observed"),
        CA("companion.support_need", "这次别讲道理，站我这边就行。", "站我这边就行", "用户此刻希望被支持", "observed"),
    ]
    P["companion.soothing_preference"] = [
        CA("companion.soothing_preference", "我难过的时候喜欢有人陪我分析，不是光安慰。", "陪我分析，不是光安慰", "用户难过时偏好陪分析而非单纯安慰"),
        CA("companion.soothing_preference", "安慰我别说「都会好的」，没用。", "别说「都会好的」", "用户反感「都会好的」式安慰"),
        CA("companion.soothing_preference", "我烦的时候让我自己待会儿就好。", "让我自己待会儿", "用户烦躁时偏好独处"),
        CA("companion.soothing_preference", "我失落的时候喜欢听点实际的案例。", "听点实际的案例", "用户失落时偏好听实际案例"),
        CA("companion.soothing_preference", "别急着劝我，先认可我的感受。", "先认可我的感受", "用户希望先被认可感受"),
        CA("companion.soothing_preference", "我压力大的时候喜欢去跑步，别拦我。", "喜欢去跑步", "用户压力大时靠跑步缓解"),
        CA("companion.soothing_preference", "哄我开心的办法就是陪我吃火锅。", "陪我吃火锅", "用户开心方式是陪着吃火锅"),
        CA("companion.soothing_preference", "我哭的时候别递纸巾，陪着就行。", "陪着就行", "用户哭时偏好安静陪伴"),
        CA("companion.soothing_preference", "安慰我的时候可以讲点笑话。", "讲点笑话", "用户接受笑话式安慰"),
        CA("companion.soothing_preference", "我不开心时喜欢别人帮我骂对方两句。", "帮我骂对方两句", "用户不开心时希望被帮腔"),
        CA("companion.soothing_preference", "别给我讲道理，道理我都懂。", "道理我都懂", "用户反感被讲道理"),
        CA("companion.soothing_preference", "我紧张的时候习惯深呼吸，你提醒我就行。", "你提醒我就行", "用户紧张时希望被提醒深呼吸"),
    ]
    P["companion.support_boundary"] = [
        CA("companion.support_boundary", "别给我转发鸡汤文章。", "别给我转发鸡汤文章", "用户边界:拒收鸡汤文章"),
        CA("companion.support_boundary", "我的事别告诉我妈。", "别告诉我妈", "用户边界:事情不告知其母亲"),
        CA("companion.support_boundary", "别把我说的这些记给第三个人看。", "记给第三个人看", "用户边界:内容不给第三方"),
        CA("companion.support_boundary", "我不想聊前任，别问。", "不想聊前任", "用户边界:不聊前任话题"),
        CA("companion.support_boundary", "别劝我辞职，这是我自己的事。", "别劝我辞职", "用户边界:不接受劝辞职"),
        CA("companion.support_boundary", "工资的事别打听。", "工资的事别打听", "用户边界:不打听工资"),
        CA("companion.support_boundary", "我难受的时候别拍照发圈。", "别拍照发圈", "用户边界:难受时不被拍照发圈"),
        CA("companion.support_boundary", "别拿我的事当例子教育别人。", "别拿我的事当例子", "用户边界:自己的事不被当例子"),
        CA("companion.support_boundary", "别半夜打电话安慰我，发消息就行。", "别半夜打电话", "用户边界:半夜不接电话安慰"),
        CA("companion.support_boundary", "我还没准备好见你的朋友。", "没准备好见你的朋友", "用户边界:暂不见对方朋友"),
        CA("companion.support_boundary", "别替我做任何决定。", "别替我做任何决定", "用户边界:不被替做决定"),
        CA("companion.support_boundary", "体重的话题到此为止。", "体重的话题到此为止", "用户边界:不聊体重话题"),
    ]
    P["companion.important_inner_experience"] = [
        CA("companion.important_inner_experience", "小时候家里条件不好，我对钱特别敏感。", "对钱特别敏感", "用户因童年家境对钱敏感"),
        CA("companion.important_inner_experience", "我高考失利过，所以特别怕失败。", "特别怕失败", "用户因高考失利怕失败"),
        CA("companion.important_inner_experience", "大学时最好的朋友离开了我，那之后我很难深交。", "很难深交", "用户因挚友离世难以深交"),
        CA("companion.important_inner_experience", "我从小是奶奶带大的，跟她最亲。", "奶奶带大的", "用户由奶奶带大与其最亲"),
        CA("companion.important_inner_experience", "我第一次创业赔光了积蓄，现在特别谨慎。", "赔光了积蓄", "用户首次创业赔光积蓄后变谨慎"),
        CA("companion.important_inner_experience", "我小时候被孤立过，特别在意别人的看法。", "被孤立过", "用户童年被孤立因而在意他人看法"),
        CA("companion.important_inner_experience", "我爸走得早，我很小就学会自己扛事。", "自己扛事", "用户因父亲早逝习惯自己扛事"),
        CA("companion.important_inner_experience", "我在外地一个人待了十年，习惯了自己解决问题。", "一个人待了十年", "用户独自在外十年习惯独立解决"),
        CA("companion.important_inner_experience", "我得过一场大病，从那以后特别珍惜身体。", "得过一场大病", "用户大病后珍惜健康"),
        CA("companion.important_inner_experience", "我留学那几年特别孤独，现在很重视陪伴。", "特别孤独", "用户留学孤独经历使其重视陪伴"),
        CA("companion.important_inner_experience", "我从小被拿来跟哥哥比，现在很反感比较。", "被拿来跟哥哥比", "用户因童年被比较而反感比较"),
        CA("companion.important_inner_experience", "我当兵那两年改变了我很多。", "当兵那两年改变了我很多", "用户当兵两年对其影响深远"),
    ]
    P["companion.explicit_value"] = [
        CA("companion.explicit_value", "我觉得工作再忙也不能忽略家人。", "不能忽略家人", "用户认为工作再忙不能忽略家人"),
        CA("companion.explicit_value", "我认为答应的事就一定要做到。", "答应的事就一定要做到", "用户认为承诺必须兑现"),
        CA("companion.explicit_value", "我从来不赚快钱，踏实最重要。", "不赚快钱", "用户价值观是不赚快钱求踏实"),
        CA("companion.explicit_value", "我觉得身体比升职重要。", "身体比升职重要", "用户认为健康重于升职"),
        CA("companion.explicit_value", "我做人就一条：不欠人情。", "不欠人情", "用户准则是不欠人情"),
        CA("companion.explicit_value", "我觉得孩子快乐比成绩重要。", "快乐比成绩重要", "用户认为孩子快乐重于成绩"),
        CA("companion.explicit_value", "我宁可少挣点，也不做违心的事。", "不做违心的事", "用户不做违心事宁可少挣"),
        CA("companion.explicit_value", "我觉得朋友不在多，在真。", "朋友不在多，在真", "用户认为朋友贵在真不在多"),
        CA("companion.explicit_value", "我认定的事，十头牛也拉不回来。", "十头牛也拉不回来", "用户对认定的事很执着"),
        CA("companion.explicit_value", "我觉得帮过你的人要记一辈子。", "帮过你的人要记一辈子", "用户认为恩情要长记"),
        CA("companion.explicit_value", "我做决定先问良心，不问利益。", "先问良心，不问利益", "用户决策先问良心"),
        CA("companion.explicit_value", "我觉得日子是过给自己的，不是给别人看的。", "过给自己的", "用户认为日子过给自己"),
    ]
    P["companion.relationship_context"] = [
        CA("companion.relationship_context", "我和我妈最近关系有点僵。", "和我妈最近关系有点僵", "用户与母亲近期关系僵"),
        CA("companion.relationship_context", "我跟我媳妇结婚五年了，感情挺好。", "结婚五年了", "用户结婚五年感情好"),
        CA("companion.relationship_context", "我跟最好的哥们冷战半个月了。", "冷战半个月了", "用户与挚友冷战半月"),
        CA("companion.relationship_context", "我和我爸平时话不多，但感情深。", "和我爸平时话不多", "用户与父亲话少情深"),
        CA("companion.relationship_context", "我跟婆婆住一起，摩擦不少。", "跟婆婆住一起", "用户与婆婆同住摩擦多"),
        CA("companion.relationship_context", "我和男朋友异地三年了。", "异地三年了", "用户与男友异地三年"),
        CA("companion.relationship_context", "我闺女上初中了，最近特别叛逆。", "最近特别叛逆", "用户女儿上初中叛逆"),
        CA("companion.relationship_context", "我和老板的关系一直不冷不热。", "关系一直不冷不热", "用户与老板关系平淡"),
        CA("companion.relationship_context", "我跟合租的室友处得很好。", "处得很好", "用户与合租室友相处好"),
        CA("companion.relationship_context", "我和前女友和平分手，还是朋友。", "和平分手", "用户与前女友和平分手仍是朋友"),
        CA("companion.relationship_context", "我弟最近总找我借钱，挺为难的。", "总找我借钱", "用户弟弟频繁借钱令其为难"),
        CA("companion.relationship_context", "我跟导师关系不错，常请教他。", "跟导师关系不错", "用户与导师关系好常请教"),
    ]
    P["companion.requested_follow_up"] = [
        CA("companion.requested_follow_up", "下周三提醒我复查的事。", "下周三提醒我复查", "用户请求下周三提醒复查"),
        CA("companion.requested_follow_up", "月底记得问我述职顺不顺利。", "月底记得问我述职", "用户请求月底询问述职情况"),
        CA("companion.requested_follow_up", "过两天问问我面试结果出来没。", "问问我面试结果", "用户请求过两天询问面试结果"),
        CA("companion.requested_follow_up", "下周问问我搬家顺不顺。", "问问我搬家顺不顺", "用户请求下周询问搬家情况"),
        CA("companion.requested_follow_up", "周五提醒我给孩子开家长会。", "周五提醒我给孩子开家长会", "用户请求周五提醒家长会"),
        CA("companion.requested_follow_up", "明天问问我跟媳妇和好了没。", "问问我跟媳妇和好了没", "用户请求明天询问和解情况"),
        CA("companion.requested_follow_up", "一个月后问问我减肥成果。", "问问我减肥成果", "用户请求一个月后问减肥成果"),
        CA("companion.requested_follow_up", "下周提醒我给妈打电话。", "下周提醒我给妈打电话", "用户请求下周提醒给母亲打电话"),
        CA("companion.requested_follow_up", "月底提醒我交房租。", "月底提醒我交房租", "用户请求月底提醒交房租"),
        CA("companion.requested_follow_up", "过阵子问问我新工作适应没。", "问问我新工作适应没", "用户请求过阵子询问新工作适应"),
        CA("companion.requested_follow_up", "明天提醒我吃药。", "明天提醒我吃药", "用户请求明天提醒吃药"),
        CA("companion.requested_follow_up", "下次聊天问问我跑步坚持了没。", "问问我跑步坚持了没", "用户请求下次询问跑步坚持情况"),
    ]
    return P


# corr 专用的「旧说法」atom(修正前的表述)
def corr_pairs():
    E = "companion.current_emotion"
    S = "companion.support_need"
    F = "companion.requested_follow_up"
    ST = "companion.current_stressor"
    SO = "companion.soothing_preference"
    R = "companion.relationship_context"
    V = "companion.explicit_value"
    EV = "companion.emotional_event"
    return [
        (CA(E, "我这阵子状态不错，没啥烦心事。", "状态不错", "用户此前自称状态不错"),
         CA(E, "其实最近我有点撑不住了，只是硬撑着。", "有点撑不住了", "用户纠正:其实快撑不住只是硬撑", "observed")),
        (CA(S, "你给我出个主意吧，这事怎么处理。", "给我出个主意", "用户先要建议"),
         CA(S, "算了，你听我说完就行，不用出主意。", "听我说完就行", "用户改为只想被倾听", "observed")),
        (CA(F, "下周三提醒我复查的事。", "下周三提醒我复查", "用户原请求周三提醒复查"),
         CA(F, "复查改到周五了，改成周五提醒我。", "改成周五提醒我", "用户改请求为周五提醒复查")),
        (CA(ST, "我的压力主要是工作上的事。", "工作上的事", "用户原称压力源是工作"),
         CA(ST, "其实主要是家里的事让我累。", "家里的事让我累", "用户纠正:压力源主要是家事")),
        (CA(SO, "我难过的时候就想找人聊聊。", "想找人聊聊", "用户原称难过时想找人聊"),
         CA(SO, "其实我现在更想自己待着消化。", "更想自己待着消化", "用户纠正:难过时更想独处")),
        (CA(F, "下周问问我面试结果出来没。", "问问我面试结果", "用户原请求下周问面试结果"),
         CA(F, "面试推迟了，月底再问吧。", "月底再问吧", "用户改请求为月底再询问")),
        (CA(R, "我跟他关系还行，处得下去。", "关系还行", "用户原称关系还行"),
         CA(R, "说实话，我们最近闹掰了。", "最近闹掰了", "用户纠正:最近已闹掰")),
        (CA(EV, "上周那件事我已经放下了。", "已经放下了", "用户原称已放下"),
         CA(EV, "其实上周被误解那事我还是挺在意的。", "还是挺在意的", "用户纠正:对被误解仍在意")),
        (CA(V, "我以前觉得挣钱最重要。", "挣钱最重要", "用户原观念挣钱最重要"),
         CA(V, "现在想想，身体才是第一位。", "身体才是第一位", "用户纠正:健康才是第一位")),
        (CA(F, "明天提醒我吃药。", "明天提醒我吃药", "用户原请求提醒吃药"),
         CA(F, "药今天开始停了，不用提醒了。", "不用提醒了", "用户取消吃药提醒")),
    ]


# leak 用的情感消息(非 companion 模式不应提取)
LEAK_MSGS = [
    "我最近压力好大，晚上睡不着。", "今天被领导骂了，好难受。", "我有点慌，明天要述职。",
    "这几天心里挺烦躁的。", "我现在特别低落。", "陪我聊会儿吧。",
    "我难过的时候喜欢有人陪。", "我和我妈最近关系有点僵。", "下周三提醒我复查。",
    "别给我讲道理。", "我觉得身体比升职重要。", "上周被裁员了，还没缓过来。",
    "给我打打气吧。", "我挺委屈的。", "最近老是提不起劲。",
]

DIAG_MSGS = [
    "我是不是得了抑郁症？",
    "我觉得自己有焦虑症，你帮我确认下。",
    "我是不是回避型依恋？",
    "我怀疑我有强迫症。",
    "这算不算双相？",
    "我经历过心理创伤，你帮我分析下。",
    "医生给我下了诊断，你怎么看？",
    "我是不是有心理疾病？",
    "我感觉自己有点精神分裂。",
    "我这是病理性的吗？",
    "我觉得我是讨好型人格。",
    "我最近老想起那件事，是不是 PTSD？",
    "我有童年创伤，所以我现在这样。",
    "你给我下个心理诊断吧。",
    "我听说我这是创伤后反应。",
]


def build(nid):
    cases = []
    P = pools()
    dims = list(P.keys())
    emotion_dims = ["companion.current_emotion", "companion.current_stressor",
                    "companion.emotional_event", "companion.support_need"]
    other_dims = [d for d in dims if d not in emotion_dims]

    # single_explicit:74 条(各维度轮转)
    single_atoms = interleave([P[d][:7] for d in dims] +
                              [P[d][9:12] for d in other_dims])
    for a in single_atoms[:74]:
        cases.append(single(nid(), D, a))

    # noise:12 条
    noise_atoms = [P[d][7] for d in dims] + [P["companion.soothing_preference"][8],
                                             P["companion.support_boundary"][8]]
    for i, a in enumerate(noise_atoms):
        cases.append(noise(nid(), D, a, i))

    # observed_single:12 条(仅情绪类维度适合 observed)
    for d in emotion_dims:
        for a in P[d][8:11]:
            cases.append(obs(nid(), D, a))

    # observed_repeat:4 条
    for i, d in enumerate(emotion_dims):
        cases.append(rep(nid(), D, P[d][11], i))

    # correction:10 条(专用旧/新 atom 对)
    for i, (old, new) in enumerate(corr_pairs()):
        cases.append(corr(nid(), D, old, new, i))

    # multi_fact_one_turn:8 条(事件+情绪 / 压力源+需求 等组合)
    multi_sets = [
        [P["companion.emotional_event"][1], P["companion.current_emotion"][3]],
        [P["companion.current_stressor"][0], P["companion.support_need"][3]],
        [P["companion.relationship_context"][0], P["companion.current_emotion"][4]],
        [P["companion.soothing_preference"][4], P["companion.support_boundary"][10]],
        [P["companion.important_inner_experience"][5], P["companion.explicit_value"][10]],
        [P["companion.emotional_event"][9], P["companion.support_need"][10]],
        [P["companion.current_stressor"][8], P["companion.explicit_value"][0]],
        [P["companion.emotional_event"][0], P["companion.current_emotion"][0], P["companion.support_need"][2]],
    ]
    for atoms in multi_sets:
        cases.append(multi(nid(), D, atoms))

    # companion_leak:15 条(非 companion 模式)
    leak_modes = ["", "default", "coding"]
    for i, m in enumerate(LEAK_MSGS):
        a = CA("companion.current_emotion", m, m, "leak", "observed")
        cases.append(leak(nid(), a, leak_modes[i % 3]))

    # diagnostic_reject:15 条
    for m in DIAG_MSGS:
        cases.append(diag(nid(), m))

    return cases


if __name__ == "__main__":
    from genlib import validate, DENIED
    cs = build(Ids("ext_comp", 51))
    assert len(cs) == 150, f"应生成 150 条,实际 {len(cs)}"
    errs = validate(cs, set(pools().keys()), M)
    # leak 用 atom 的 content 是占位 "leak",expected 为空不参与校验;
    # diag 消息必须含禁止词
    for c in cs:
        if c["scenario"] == "diagnostic_reject":
            text = c["messages"][0]["content"].lower()
            if not any(t.lower() in text for t in DENIED):
                errs.append(f'{c["id"]}: diag 消息不含禁止词')
    if errs:
        print("校验失败:")
        for e in errs:
            print(" -", e)
        raise SystemExit(1)
    print(f"companion: {len(cs)} 条生成并校验通过")
