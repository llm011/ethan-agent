#!/usr/bin/env python3
"""生成 others 训练样本（jsonl）——拒识类。

others 是开集里的「拒绝」类：分类器对它应输出低置信 → 走 LLM 兜底。
两部分构成：
  1) 纯无关（天气/算术/翻译/写代码/闲聊/常识/生活）——和任何 skill 都不沾边。
  2) 贴边陷阱（关键！）——表面和某 skill 像，实际不该路由过去。这些样本逼分类器
     学到「真正的业务意图」而非「领域词」。每个陷阱标注它在「碰瓷」哪个 skill。

子语义：
  A 天气/时间/常识      B 算术/计算            C 写代码/技术问答（≠deepwiki）
  D 闲聊/玩笑/陪聊边界    E 翻译/文字处理（≠paper转述）  F 生活/推荐/日常
  G 陷阱·碰 paper        H 陷阱·碰 deepwiki     I 陷阱·碰 lark/channels/shared
  J 陷阱·碰 skills-manager  K 陷阱·碰 legal     L 陷阱·碰 companion

注意：others 无 trigger 约束（它本就该避开所有 skill 的真实意图）；但陷阱样本要
刻意「贴边但不越界」——含领域词、不含真实业务诉求。
"""
from __future__ import annotations
import json
import random
from pathlib import Path
from collections import Counter

POOL: dict[str, list[str]] = {
    # ===== A. 天气/时间/常识 =====
    "fact": [
        "今天几号星期几",
        "明天会下雨吗",
        "北京现在几点",
        "珠穆朗玛峰有多高",
        "光速是多少",
        "一年有多少天",
        "太阳系有几大行星",
        "水的沸点是多少度",
        "长城有多长",
        "明天的气温怎么样",
        "现在是什么季节",
        "一公里等于多少米",
        "世界上最大的海洋是哪个",
        "中国有多少个省",
        "今天适合穿什么",
        "这周末天气如何",
        "地球到月球多远",
        "明天日出几点",
        "现在国际油价多少",
        "圆周率是多少",
    ],
    # ===== B. 算术/计算 =====
    "math": [
        "一加一等于几",
        "帮我算下 35 乘 28",
        "100 的平方根是多少",
        "三分之一加四分之一等于多少",
        "帮我算个百分比，80 占 200 的几成",
        "12 的阶乘是多少",
        "把 5 公里换算成英里",
        "帮我算下这个月还款多少",
        "2 的十次方是多少",
        "帮我算下平均分",
        "一打是多少个",
        "摄氏 37 度等于华氏多少",
        "帮我算下折扣价",
        "这个比例换成小数是多少",
        "帮我算下复利",
        "三角形面积公式是啥",
        "帮我算下时差",
        "一吨等于多少斤",
        "帮我把这串数字求和",
        "黄金分割比例是多少",
    ],
    # ===== C. 写代码/技术问答（≠deepwiki）=====
    "code": [
        "帮我写个快速排序",
        "Python 怎么读取文件",
        "帮我写个冒泡排序的函数",
        "怎么用 js 发个网络请求",
        "帮我写段正则匹配邮箱",
        "SQL 怎么做分组统计",
        "帮我写个递归求斐波那契",
        "怎么在 python 里去重列表",
        "帮我写个 hello world",
        "解释下什么是闭包",
        "帮我把这段代码优化下",
        "怎么处理 json 解析",
        "帮我写个二分查找",
        "什么是时间复杂度",
        "帮我写段异步请求的代码",
        "怎么实现一个单例",
        "帮我 debug 这段逻辑",
        "解释下什么是装饰器",
        "帮我写个简单的爬虫脚本",
        "怎么用 git 回滚提交",
    ],
    # ===== D. 闲聊/玩笑/陪聊边界（不是情绪倾诉）=====
    "chat": [
        "讲个笑话",
        "陪我玩个成语接龙",
        "今天有啥新鲜事",
        "随便聊点啥",
        "你觉得猫好还是狗好",
        "说个冷知识",
        "来个脑筋急转弯",
        "你最喜欢什么颜色",
        "我们玩个文字游戏吧",
        "给我讲个故事",
        "周末有啥好玩的推荐",
        "你会做菜吗",
        "猜个谜语给你",
        "聊聊最近的热门电影",
        "你觉得 AI 会取代人类吗",
        "随便扯点有意思的",
        "给我出个智力题",
        "你喜欢听什么音乐",
        "来段绕口令",
        "讲个鬼故事吓吓我",
    ],
    # ===== E. 翻译/文字处理（≠paper 的术语转述）=====
    "text": [
        "把这句英文翻译成中文",
        "帮我润色这段话",
        "这个成语啥意思",
        "帮我写个生日祝福",
        "把这段话改得正式点",
        "帮我起个网名",
        "这个字怎么读",
        "帮我写副对联",
        "把这句话翻成日语",
        "帮我缩写这段文字",
        "给我推荐几个好听的英文名",
        "帮我写个朋友圈文案",
        "这段话有没有错别字",
        "帮我把这首诗解释下",
        "帮我写个请假条",
        "这个词的近义词有哪些",
        "帮我写段表白的话",
        "把这段中文翻成法语",
        "帮我取个公司名字",
        "这句古文什么意思",
    ],
    # ===== F. 生活/推荐/日常 =====
    "life": [
        "推荐一部好看的电影",
        "晚饭吃什么好",
        "推荐个减肥的方法",
        "怎么去除衣服上的油渍",
        "推荐几本好书",
        "感冒了吃什么好得快",
        "怎么挑西瓜",
        "推荐个旅游目的地",
        "怎么快速入睡",
        "买什么手机性价比高",
        "怎么养多肉植物",
        "推荐个健身计划",
        "怎么做红烧肉",
        "买车选油车还是电车",
        "怎么去除冰箱异味",
        "推荐个学英语的方法",
        "猫咪不吃饭怎么办",
        "怎么收纳衣柜",
        "周末适合去哪玩",
        "怎么挑选跑鞋",
    ],
    # ===== G. 陷阱·碰 paper-analysis（含论文词，但不是要精读分析）=====
    "trap_paper": [
        "帮我把论文格式排个版",
        "论文的参考文献格式怎么写",
        "帮我把论文查重一下",
        "论文摘要一般写多少字",
        "怎么投稿一篇论文",
        "论文用什么软件画图好",
        "帮我把论文导出成 word",
        "毕业论文一般多少页",
        "论文的致谢怎么写",
        "学术论文的字体要求是啥",
        "帮我把这篇论文打印出来",
        "论文答辩要注意什么",
        "怎么在论文里插入公式",
        "论文降重有什么技巧",
        "帮我把论文翻译成英文投稿",
    ],
    # ===== H. 陷阱·碰 deepwiki（含 github/仓库词，但不是查文档/架构）=====
    "trap_wiki": [
        "github 怎么注册账号",
        "怎么把代码推到 github",
        "git 和 github 有啥区别",
        "github 打不开怎么办",
        "怎么给 github 项目点 star",
        "github 的私有仓库要钱吗",
        "怎么 fork 一个仓库",
        "git clone 太慢怎么提速",
        "github actions 怎么收费",
        "怎么删除 github 上的仓库",
        "github 怎么改用户名",
        "开源项目怎么贡献代码",
        "怎么在 github 上找工作",
        "git 怎么解决冲突",
        "github copilot 好用吗",
    ],
    # ===== I. 陷阱·碰 lark-im/channels/lark-shared（含飞书词，但是平台使用问题）=====
    "trap_lark": [
        "飞书和钉钉哪个好用",
        "飞书会员多少钱一年",
        "飞书怎么注册公司账号",
        "飞书的视频会议怎么开",
        "飞书文档怎么导出 PDF",
        "飞书日历怎么同步到手机",
        "飞书怎么改头像",
        "飞书的妙记功能怎么用",
        "飞书电脑版在哪下载",
        "飞书怎么设置免打扰",
        "飞书多维表格怎么用",
        "飞书怎么申请加入公司",
        "飞书的审批流程怎么发起",
        "飞书怎么解绑手机号",
        "飞书打卡怎么操作",
    ],
    # ===== J. 陷阱·碰 skills-manager（含技能/能力词，但不是装卸管理）=====
    "trap_skill": [
        "怎么提升我的沟通技能",
        "学一门新技能要多久",
        "什么技能最值钱",
        "演讲技能怎么练",
        "职场必备技能有哪些",
        "怎么培养孩子的学习能力",
        "面试要展示什么技能",
        "时间管理是一种技能吗",
        "怎么提高记忆能力",
        "哪些技能适合自学",
        "领导力算不算一种能力",
        "怎么锻炼逻辑思维能力",
        "副业需要哪些技能",
        "怎么写技能在简历上",
        "团队协作能力怎么提升",
    ],
    # ===== K. 陷阱·碰 legal-assistant（含法律词，但是常识科普/不涉个案处理）=====
    "trap_legal": [
        "律师这个职业前景怎么样",
        "考法考难不难",
        "法学专业要学几年",
        "怎么成为一名律师",
        "律师一般收费多少",
        "法院上班时间是几点",
        "律师和法官有啥区别",
        "学法律出来能做什么工作",
        "法律专业考研难吗",
        "怎么查一个律师靠不靠谱",
        "法学院哪些学校好",
        "律师证怎么考",
        "法律援助是免费的吗",
        "陪审员是干嘛的",
        "法律和道德有什么关系",
    ],
    # ===== L. 陷阱·碰 companion-listen（含情绪词，但是知识询问/不是本人倾诉）=====
    "trap_companion": [
        "焦虑症有哪些表现",
        "怎么帮朋友走出失恋",
        "抑郁和抑郁症有什么区别",
        "心理咨询一般怎么收费",
        "失眠有哪些科学的改善方法",
        "怎么判断一个人是不是 emo",
        "情绪管理有哪些技巧",
        "孤独感从心理学怎么解释",
        "怎么安慰一个难过的人",
        "压力大对身体有哪些影响",
        "心理学上的共情是什么意思",
        "怎么帮父母缓解焦虑",
        "正念冥想真的有用吗",
        "为什么人会感到孤独",
        "如何科学地排解负面情绪",
    ],
}

SUBCAT = {
    "fact": ("A", "常识"),
    "math": ("B", "算术"),
    "code": ("C", "写代码"),
    "chat": ("D", "闲聊"),
    "text": ("E", "文字处理"),
    "life": ("F", "生活"),
    "trap_paper": ("G", "陷阱·paper"),
    "trap_wiki": ("H", "陷阱·wiki"),
    "trap_lark": ("I", "陷阱·飞书"),
    "trap_skill": ("J", "陷阱·技能"),
    "trap_legal": ("K", "陷阱·法律"),
    "trap_companion": ("L", "陷阱·陪伴"),
}


def expand() -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    mood = set("吧呢嘛啊吗了呀哦呐")
    for cat, sents in POOL.items():
        for s in sents:
            out.append((s, cat))
            tail = s.rstrip()[-1] if s.strip() else ""
            if tail and tail not in mood and tail not in "？。！，；":
                for suf in ["呢", "啊", "吗", "？"]:
                    out.append((s + suf, cat))
    return out


def dedupe(items):
    seen, out = set(), []
    for text, cat in items:
        t = text.strip()
        if not t or t in seen:
            continue
        seen.add(t)
        out.append((t, cat))
    return out


def stratified_split(items, train_n, val_n, test_n, seed):
    rng = random.Random(seed)
    by_cat = {}
    for text, cat in items:
        by_cat.setdefault(cat, []).append((text, cat))
    for cat in by_cat:
        rng.shuffle(by_cat[cat])
    train, val, test = [], [], []
    total = len(items)
    for cat, texts in by_cat.items():
        n = len(texts)
        cval = min(max(1, round(n * val_n / total)), n // 3)
        ctest = min(max(1, round(n * test_n / total)), n // 3)
        i = 0
        test.extend(texts[i:i + ctest]); i += ctest
        val.extend(texts[i:i + cval]); i += cval
        train.extend(texts[i:])
    rng.shuffle(train); rng.shuffle(val); rng.shuffle(test)
    used = set(t for t, _ in val) | set(t for t, _ in test)
    pool_extra = [it for it in train if it[0] not in used]
    placed = set()
    for need, bucket in [(val_n, val), (test_n, test)]:
        i = 0
        while len(bucket) < need and i < len(pool_extra):
            if pool_extra[i][0] not in placed:
                bucket.append(pool_extra[i]); placed.add(pool_extra[i][0])
            i += 1
    used = set(t for t, _ in val) | set(t for t, _ in test)
    train = [it for it in train if it[0] not in used][:train_n]
    return train, val, test


def write_jsonl(path, items):
    with open(path, "w", encoding="utf-8") as fh:
        for text, cat in items:
            code, name = SUBCAT[cat]
            rec = {"text": text, "label": "others", "subcat": f"{code}-{name}"}
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")


def main():
    base = Path(__file__).resolve().parent
    items = dedupe(expand())
    print(f"手写池展开+去重后：{len(items)} 条")
    train, val, test = stratified_split(items, 500, 75, 75, seed=20260629)
    write_jsonl(base / "train" / "others.jsonl", train)
    write_jsonl(base / "val" / "others.jsonl", val)
    write_jsonl(base / "test" / "others.jsonl", test)
    print(f"train={len(train)} val={len(val)} test={len(test)}")
    for name, split in [("train", train), ("val", val), ("test", test)]:
        c = Counter(SUBCAT[cat][0] for _, cat in split)
        print(f"\n{name} 子语义分布（共 {len(split)}）：")
        for cat in SUBCAT:
            code = SUBCAT[cat][0]
            print(f"  {code}-{SUBCAT[cat][1]:<8} {c.get(code, 0):>3}")


if __name__ == "__main__":
    main()