#!/usr/bin/env python3
"""生成 ppt-generate 训练样本（jsonl）——演示材料生成（动作型）。

skill 边界：把「主题/要点/长文档(含整份 markdown)/数据」做成一套可讲的演示页
（胶片/片子/演示材料/路演材料），含生成、扩写、改版式。不碰：单张海报/网页/视频/
排版软件操作/胶片摄影（这些进 others 的 trap_ppt）。

子语义：
  A 主题生成        给一个主题做整份演示
  B 要点展开        给几条要点/大纲组织成页
  C 长md·请求在前    粘贴整份 markdown/长文档，转换请求在开头（截断后仍见意图）
  D 长md·请求在后    粘贴整份 markdown/长文档，转换请求在结尾（64 token 截断会丢
                     意图——hard example，考运行时的截断策略）
  E 长md·trigger    长文档 + 含 trigger 原词的请求（真实用户就是这么说的；运行时
                     LR 头是主路径，必须也能命中）
  F 数据汇报        给数据/表格做汇报片
  G 培训教学        培训材料/教学胶片（避开 trigger「课件」）
  H 路演发布答辩     BP/发布会/毕业答辩/提案
  I 美化改版        已有片子的换风格/精简/加页
  J 自然trigger说法  含 trigger 原词的短请求（高频真实说法，占小头）

trigger 规避：A-D、F-I 不得含 SKILL.md 任一 trigger 子串（PPT/ppt/pptx/幻灯片/
演示文稿/slides/presentation/deck/课件/keynote），脚本尾部有断言自检。
E/J 是刻意保留的 trigger 子集（约 10%），理由见上。
"""
from __future__ import annotations
import json
import random
from pathlib import Path
from collections import Counter

TRIGGERS = ["ppt", "pptx", "幻灯片", "演示文稿", "slides",
            "presentation", "deck", "课件", "keynote"]

# ---------------------------------------------------------------- 长文档池（14 份，markdown，内不含 trigger 词）
DOCS = {
    "msa": """# 订单系统微服务拆分方案
## 背景
单体应用部署周期 2 周，故障隔离差，大促期间扩容粒度粗。
## 拆分原则
- 按业务域划分：订单、库存、支付、履约、用户
- 每个服务独立数据库，禁止跨库 JOIN
- 同步调用只走查询，写路径全部走消息
## 里程碑
1. 第 1 月：订单域剥离，双跑验证
2. 第 2 月：库存与支付拆分
3. 第 3 月：履约拆分，单体下线
## 风险
分布式事务采用最终一致 + 补偿，需补全对账任务。""",
    "okr": """# Q3 产品 OKR 草案
## O1 提升新用户激活率
- KR1：注册到首次核心行为转化率从 31% 提到 45%
- KR2：新手引导完成率 ≥ 70%
- KR3：首日留存 ≥ 42%
## O2 商业化验证
- KR1：付费试点客户 20 家
- KR2：客单价 ≥ 3 万/年
- KR3：NDR 试点组 ≥ 105%
## 关键举措
 onboarding 改版、行业模板包、客户成功陪跑机制""",
    "minutes": """# 7月15日 增长例会纪要
## 参会
产品、运营、研发、设计
## 结论
1. 分享裂变系数 0.8，低于预期 1.2，下周上线双人成团玩法
2. 投放 ROI 1.4，继续压缩信息流预算 20%
3. 新客首单补贴从 15 元降到 8 元，观察两周
## 待办
- 张三：成团玩法需求文档，周三前
- 李四：补贴降级灰度方案，周五前
- 王五：整理近 30 日渠道质量报表""",
    "rag": """# RAG 检索链路优化记录
## 问题
badcase 分析 200 条：35% 召回缺失，28%  chunk 切分把表格切碎，18% 查询改写跑偏。
## 改动
- 召回：BM25 + 向量双路，RRF 融合，top-k 40 → 重排后取 8
- 切分：按标题层级切，表格整块保留，chunk 512 token 重叠 64
- 改写：HyDE + 多 query 扩展 3 路
## 效果
离线评测 hit@5 从 0.71 → 0.86，端到端答案正确率 +11%""",
    "market": """# 扫地机器人竞品对比（2026H1）
| 维度 | 我们 | 竞品A | 竞品B |
| 价格段 | 2499 | 2199 | 2999 |
| 导航 | LDS+视觉 | LDS | 视觉 |
| 基站功能 | 洗烘集尘 | 集尘 | 洗烘 |
| 月销（万台） | 3.2 | 5.8 | 2.1 |
## 结论
竞品A 以价换量，我们基站功能最全但声量弱；下半年主打扫地+拖地一体化卖点，渠道下沉到三四线。""",
    "fin": """# 2026 Q2 经营摘要
- 营收 4.2 亿，同比 +18%，环比 +6%
- 毛利率 41.2%，环比 -1.3pct，主因云资源涨价
- 销售费用率 22%，研发投入占比 19%
- 经营性现金流 0.6 亿，应收周转天数 74 天（+9 天）
## 关注点
大客户账期拉长，Q3 起预付款比例提到 40%；云成本优化专项目标降 15%。""",
    "retro": """# 618 大促项目复盘
## 目标 vs 实际
GMV 目标 1.2 亿，实际 1.05 亿，达成 87.5%。
## 做得好
- 预热期种草内容带来 32% 新客
- 库存预测准确率 94%，缺货率仅 1.8%
## 待改进
- 峰值 QPS 预估偏低，开卖 10 分钟排队
- 直播间脚本与货盘节奏脱节，转化波动大
## 行动
容量评估前置到 T-30 天；直播运营并入货盘排期会。""",
    "api": """# 消息推送 API 说明
## 鉴权
Header 携带 X-App-Key 与签名，签名算法 HMAC-SHA256(appSecret, timestamp+body)。
## 接口
POST /v1/messages：单发，支持文本/卡片/图片
POST /v1/messages/batch：批量，单次最多 1000 条
GET /v1/messages/{id}：查询回执状态
## 限流
默认 200 QPS，超限返回 429，指数退避重试。
## 回调
已读/未读事件通过 webhook 推送，需在控制台配置地址。""",
    "sec": """# 数据安全整改清单
1. 用户手机号落库必须加密（AES-256-GCM），9 月底前完成历史数据刷库
2. 日志平台脱敏：身份证、银行卡默认打码
3. 权限：生产库查询走工单审批，留存 180 天审计记录
4. 第三方 SDK 合规：统计类 SDK 升级到隐私合规版本
5. 渗透测试：每季度一次，高危漏洞 48 小时内修复
责任人与排期见附表。""",
    "train": """# 客服新人上岗培训大纲
## 第一周 产品与业务
- 产品线全览、典型客户场景、竞品差异
- 后台系统实操：工单、CRM、知识库
## 第二周 话术与案例
- 投诉处理五步：倾听-共情-确认-方案-跟进
- 10 个高频问题标准应答
## 考核
笔试 80 分合格 + 模拟接线 3 通 + 老带新旁听 2 天""",
    "lab": """# 实验记录：摘要模型对比
| 模型 | ROUGE-1 | ROUGE-L | 延迟 P95 | 成本/千篇 |
| baseline（7B） | 38.2 | 35.1 | 820ms | ¥14 |
| +领域微调 | 41.5 | 38.6 | 830ms | ¥14 |
| +蒸馏小模型 1.5B | 39.8 | 36.9 | 210ms | ¥3 |
## 结论
蒸馏模型指标掉 1.7 个点但成本降 79%，线上灰度 10% 观察用户采纳率。""",
    "ops": """# 线上故障应急手册（支付链路）
## 支付成功率下跌
1. 看渠道分流面板，定位是否单渠道故障 → 切备用渠道
2. 检查证书有效期与回调签名失败率
3. 数据库锁等待 > 200ms 时切只读分析
## 对账差异
T+1 对账差异 > 500 元触发告警，先查渠道账单拉取是否完整，再查本地状态机推进日志。
## 值班
一线 7×24 电话，二线研发 15 分钟内响应。""",
    "proposal": """# 智慧园区项目背景
客户园区占地 800 亩，入驻企业 120 家，现有安防、能耗、停车三套系统各自为政。
## 痛点
- 能耗数据人工抄表，月度汇总滞后
- 访客管理纸质登记，高峰期排队
- 设备告警分散，运维靠微信群
## 建设目标
统一物联平台 + 园区驾驶舱，一期覆盖能耗与访客两个场景，工期 5 个月，预算 380 万。""",
    "select": """# 消息队列选型对比
| 维度 | Kafka | RocketMQ | Pulsar |
| 吞吐 | 极高 | 高 | 高 |
| 延迟 | ms 级 | ms 级 | ms 级 |
| 事务消息 | 弱 | 强 | 一般 |
| 运维成本 | 中 | 中 | 高 |
| 社区生态 | 最成熟 | 国内活跃 | 增长中 |
## 建议
订单链路用 RocketMQ（事务消息刚需），日志链路继续 Kafka。""",
    "event": """# 七夕营销活动复盘
- 曝光 1200 万，进店 86 万，转化 4.1 万单
- 联名款售罄率 92%，常规款动销一般
- 小红书种草笔记 3400 篇，爆文率 3.2%
## 问题
赠品库存深度不够，活动第 2 天断赠，客服咨询量翻倍。
## 下次
赠品按主品 1.2 倍备货；爆文投流预算向腰部达人倾斜。""",
}

# ---------------------------------------------------------------- 主题/要点/数据池
TOPICS = [
    "人工智能发展趋势", "公司明年战略规划", "新能源汽车市场格局", "团队下半年 OKR",
    "产品路线图", "数字化转型路径", "大模型在企业落地", "私域流量运营",
    "供应链降本方案", "双碳政策对我们的影响", "跨境电商出海", "短视频账号冷启动",
    "招聘体系搭建", "绩效考核改革", "企业文化手册", "信息安全意识",
    "年度财务预算", "客户成功体系", "SaaS 定价策略", "开源社区运营",
    "数据治理体系", "云原生架构演进", "DevOps 落地实践", "AIGC 营销玩法",
    "智能手表新品", "医疗信息化方案", "社区团购模式", "乡村振兴项目进展",
    "城市更新改造方案", "Z 世代消费洞察", "银发经济机会", "宠物经济赛道",
    "预制菜行业分析", "咖啡连锁扩张计划", "充电桩布局规划", "半导体国产化进展",
    "商业航天产业链", "低空经济政策", "具身智能技术", "Transformer 架构科普",
    "向量数据库选型", "推荐系统召回策略", "搜索排序算法演进", "风控规则引擎",
]

BULLET_SETS = [
    "1. 市场规模三年翻两番 2. 头部玩家集中度提升 3. 我们的切入点在细分场景",
    "1. 现状：手工流程效率低 2. 目标：自动化覆盖 80% 3. 路径：先试点后推广",
    "1. 用户留存连续三月下滑 2. 核心是新手期流失 3. 方案：重做引导流程",
    "1. 营收同比 +18% 2. 毛利率承压 3. 费用管控见效 4. 下半年聚焦现金流",
    "1. 故障平均恢复 47 分钟 2. 70% 故障源于变更 3. 举措：灰度+回滚一键化",
    "1. 招聘完成率 82% 2. 关键技术岗缺口 6 人 3. 渠道：内推占比提到 40%",
    "1. 老客户贡献 65% 营收 2. 续约率 88% 3. 增购空间集中在数据模块",
    "1. 日活突破 50 万 2. 次留 41% 3. 内容供给是瓶颈 4. 引入 MCN 合作",
    "1. 交付延期率 15% 2. 主因是需求变更 3. 对策：变更评审+冻结窗口",
    "1. 客诉环比下降 22% 2. 物流时效仍是短板 3. 新增两个区域仓",
    "1. 训练成本超预期 40% 2. 数据清洗占大头 3. 改用合成数据补 30%",
    "1. 搜索无结果率 8% 2. 长尾词覆盖不足 3. 上线 query 改写与同义词库",
    "1. 门店坪效分化严重 2. 前 20% 门店贡献 55% 流水 3. 尾部门店转型快闪",
    "1. 插件月活 12 万 2. 付费转化 2.8% 3. 定价从买断改订阅试点",
    "1. 代码评审平均耗时 2.3 天 2. 大 CR 是瓶颈 3. 推行小步提交规范",
    "1. 会员复购率 34% 2. 权益感知弱 3. 重做会员等级与积分体系",
    "1. 跨境物流时效 12 天 2. 差评 30% 来自物流 3. 海外仓试点两个国家",
    "1. 能耗同比 +12% 2. 空调系统占 55% 3. 改造后预计省 18%",
]

DATA_SNIPPETS = [
    "一月销量 3200，二月 4100，三月 4800，四月 5300，五月 6100",
    "Q1 新客 2.1 万，Q2 2.8 万，获客成本从 85 降到 62 元",
    "华东占比 38%，华南 27%，华北 19%，其他 16%",
    "NPS 从 31 提升到 45，投诉量环比下降 18%",
    "研发投入 1.2 亿，占营收 19%，专利新增 43 件",
    "日活 52 万，周活 180 万，月活 410 万，次留 41%，7 留 23%",
    "A 渠道 ROI 2.1，B 渠道 1.4，C 渠道 0.8",
    "客单价 268 元，复购率 34%，连带率 1.7",
    "故障数 Q1 23 起，Q2 11 起，MTTR 从 47 分钟降到 19 分钟",
    "招聘需求 45 人，到岗 37 人，关键技术岗缺口 6 人",
    "测试覆盖率从 58% 提到 76%，线上缺陷密度降了四成",
    "直播观看 86 万，成交 4.1 万单，客单价 312 元",
    "仓库周转天数 28 天，缺货率 1.8%，滞销占比 6%",
    "课程完课率 63%，好评率 4.7，复购意向 41%",
]

TRAIN_TOPICS = [
    "新员工入职安全教育", "客服话术标准培训", "销售铁军训练营", "中层管理者领导力",
    "代码规范与评审流程", "数据分析入门", "产品经理方法论", "合规与反商业贿赂",
    "消防安全演练", "财务报销制度", "项目管理 PMP 精要", "商务谈判技巧",
    "大模型应用开发入门", "跨境电商运营实操",
]

SCENARIOS = [
    "下周见投资人，我们的 SaaS 项目要融 A 轮",
    "新产品发布会，面向媒体和渠道商",
    "硕士毕业答辩，方向是图神经网络",
    "给政府汇报智慧园区建设方案",
    "竞标一个数据中台项目，对手有三家",
    "公司年会，我代表部门做年度总结",
    "给客户 CIO 汇报系统上云方案",
    "行业大会上分享我们的推荐系统实践",
    "内部立项评审，申请 200 万预算",
    "渠道招商大会，讲加盟政策",
    "给校招生做公司介绍",
    "季度经营分析会，向董事会汇报",
    "申报专精特新企业，需要评审材料",
    "hackathon 决赛路演，我们的项目是 AI 笔记",
    "博士开题报告，方向是存算一体芯片",
    "给客户高层做季度服务回顾",
]

# ---------------------------------------------------------------- 模板
T_TOPIC = [
    "帮我围绕「{t}」做一份演示材料，要能直接拿去讲",
    "以「{t}」为主题帮我准备一套胶片，十页左右",
    "我要讲「{t}」，帮我把演示的页面内容做出来",
    "围绕{t}帮我搞一套汇报用的片子",
    "帮我做一份关于{t}的演示，结构清晰一点",
    "下周要讲{t}，演示材料帮我准备下",
]
T_BULLETS = [
    "把这几条要点帮我组织成一套演示页：\n{b}",
    "以下要点帮我扩成一份可以讲的胶片：\n{b}",
    "根据这些内容帮我排成一页一页的演示材料：\n{b}",
    "帮我把下面的提纲做成演示：\n{b}",
]
T_MD_FRONT = [
    "把下面这份内容整理成一套胶片：\n{doc}",
    "帮我把以下材料做成演示页，可以直接讲的那种：\n{doc}",
    "以下内容帮我转成汇报用的片子：\n{doc}",
    "把这份文档排成一页一页的演示材料：\n{doc}",
    "下面这个 markdown 帮我做成能投屏讲的胶片：\n{doc}",
]
T_MD_BACK = [
    "{doc}\n把以上内容做成一套胶片",
    "{doc}\n以上材料帮我转成演示页",
    "{doc}\n帮我把上面这些整理成汇报用的片子",
    "{doc}\n上面这份文档做成演示材料吧",
    "{doc}\n这些内容帮我排成一页一页的",
]
T_MD_TRIGGER = [
    "把下面的 markdown 做成PPT：\n{doc}",
    "{doc}\n以上内容帮我生成PPT",
    "把这份 md 转成幻灯片：\n{doc}",
]
T_DATA = [
    "把这些数据做成汇报用的胶片，重点突出趋势：{d}",
    "帮我根据下面这组数据做几页演示，给老板看：{d}",
    "以下数据帮我整理成演示材料，配上图表说明：{d}",
]
T_TRAIN = [
    "帮我做一份「{t}」的培训胶片，给内部员工讲",
    "我要做一场{t}，培训用的演示材料帮我准备一下",
    "围绕{t}帮我出一套教学演示页",
]
T_SCENE = [
    "{s}，帮我做一套演示材料",
    "{s}，演示用的胶片帮我准备一下",
    "{s}，帮我把要讲的页面内容做出来",
]
T_RESTYLE = [
    "我这份胶片太素了，帮我换成深色科技风",
    "帮我把这套演示材料精简一下，每页别那么多字",
    "这版汇报片子风格太老气了，帮我改成年轻一点的视觉",
    "帮我在现有演示后面补三页未来规划",
    "这份材料是给技术看的，帮我改一版给业务高管看的",
    "帮我把这份胶片里的数据页都换成图表展示",
    "演示时间从 30 分钟压到 10 分钟，帮我压缩这套片子",
    "帮我把这套材料改成英文版，海外客户看",
    "这页太满了，帮我拆成两页",
    "统一一下整套胶片的字体和配色",
    "帮我把干巴巴的文字页改得图文并茂一点",
    "这套片子缺个目录页和结尾页，帮我补上",
    "老板说要更有结论感，帮我把每页标题都改成观点句",
    "帮我给这份演示配一套商务蓝的模板",
    "把这份材料里过时的数据页换成我新发你的数据",
    "帮我把这份胶片调成适合投影暗场看的配色",
    "这套片子页数太多了，帮我合并同类页压到十页",
    "帮我给汇报片加一页竞品对比",
    "这份演示缺数据来源标注，帮我补上出处行",
    "帮我把结尾页改成行动号召而不是谢谢观看",
    "帮我在这套材料开头加一页核心结论摘要",
    "这套胶片想改成竖版手机上看，帮我调下版式",
]
T_TRIGGER_NATURAL = [
    "帮我做个PPT，主题是年终总结",
    "做个PPT介绍我们公司的产品",
    "帮我生成一份项目复盘的PPT",
    "能不能帮我把这篇报告做成PPT",
    "帮我写一个介绍大模型的PPT",
    "生成一个产品发布会的PPT",
    "帮我把这些要点做成PPT",
    "做个季度汇报PPT，十页以内",
    "我要做一个关于团队协作的PPT",
    "帮我弄一份毕业答辩的PPT",
    "把这篇文章的内容做成幻灯片",
    "帮我生成一套销售培训幻灯片",
    "做一份公司介绍的演示文稿",
    "帮我写个路演演示文稿",
    "这份文档帮我转成演示文稿",
    "帮我做 slides 介绍我们的 API",
    "generate slides about our quarterly results",
    "帮我把会议纪要做成 slides",
    "做个 keynote 风格的发布材料",  # 注意：keynote 本身是 trigger
    "帮我准备一份课件，给新人讲安全规范",
    "做一份产品培训课件",
    "把这份操作手册改成课件形式",
    "帮我生成下周公开课的课件",
    "做个PPT给小孩讲垃圾分类",
    "帮我做一份婚礼现场的幻灯片",
    "生成PPT：新能源汽车行业分析",
    "帮我把论文答辩的内容整理成PPT",
    "做一个介绍我们团队的PPT",
    "帮我写PPT大纲：企业数字化转型",
    "把这份财报做成PPT给投资人看",
    "帮我做一个招聘宣讲PPT",
    "帮我生成一份安全培训的演示文稿",
    "帮我做个PPT复盘上半年的项目",
    "把我们的产品手册做成PPT",
    "做个PPT给领导汇报这个月的数据",
]

# 各子语义池上限（分层抽样前截断）：压住模板膨胀的 topic，抬长md/场景类占比
POOL_CAP = {
    "topic": 190, "bullets": 80, "md_front": 100, "md_back": 80,
    "md_trigger": 40, "data": 60, "training": 60, "scene": 70,
    "restyle": 40, "trigger_natural": 60,
}

SUBCAT = {
    "topic": ("A", "主题生成"),
    "bullets": ("B", "要点展开"),
    "md_front": ("C", "长md·请求在前"),
    "md_back": ("D", "长md·请求在后"),
    "md_trigger": ("E", "长md·trigger"),
    "data": ("F", "数据汇报"),
    "training": ("G", "培训教学"),
    "scene": ("H", "路演发布答辩"),
    "restyle": ("I", "美化改版"),
    "trigger_natural": ("J", "自然trigger"),
}


def expand() -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    mood = set("吧呢嘛啊吗了呀哦呐")

    def add_short(text: str, cat: str):
        out.append((text, cat))
        tail = text.rstrip()[-1] if text.strip() else ""
        if tail and tail not in mood and tail not in "？。！，；：" and len(text) < 60:
            for suf in ["呢", "啊", "？"]:
                out.append((text + suf, cat))

    for t in TOPICS:
        for tpl in T_TOPIC:
            add_short(tpl.format(t=t), "topic")
    for b in BULLET_SETS:
        for tpl in T_BULLETS:
            out.append((tpl.format(b=b), "bullets"))
    docs = list(DOCS.values())
    for doc in docs:
        for tpl in T_MD_FRONT:
            out.append((tpl.format(doc=doc), "md_front"))
        for tpl in T_MD_BACK:
            out.append((tpl.format(doc=doc), "md_back"))
        for tpl in T_MD_TRIGGER:
            out.append((tpl.format(doc=doc), "md_trigger"))
    for d in DATA_SNIPPETS:
        for tpl in T_DATA:
            add_short(tpl.format(d=d), "data")
    for t in TRAIN_TOPICS:
        for tpl in T_TRAIN:
            add_short(tpl.format(t=t), "training")
    for s in SCENARIOS:
        for tpl in T_SCENE:
            add_short(tpl.format(s=s), "scene")
    for s in T_RESTYLE:
        add_short(s, "restyle")
    for s in T_TRIGGER_NATURAL:
        add_short(s, "trigger_natural")
    return out


def dedupe(items):
    seen, out = set(), []
    for text, cat in items:
        if text not in seen:
            seen.add(text)
            out.append((text, cat))
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
            rec = {"text": text, "label": "ppt-generate", "subcat": f"{code}-{name}"}
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")


def check_triggers(items):
    """trigger-free 子语义不得含 trigger 子串（大小写不敏感）。"""
    free = {"topic", "bullets", "md_front", "md_back", "data", "training", "scene", "restyle"}
    bad = []
    for text, cat in items:
        if cat in free:
            low = text.lower()
            for tg in TRIGGERS:
                if tg.lower() in low:
                    bad.append((cat, tg, text[:50]))
    return bad


def main():
    base = Path(__file__).resolve().parent
    items = dedupe(expand())
    # 按 POOL_CAP 分层截断，再进分层抽样（否则模板多的子语义挤占配额）
    rng = random.Random(20260722)
    by_cat: dict[str, list] = {}
    for text, cat in items:
        by_cat.setdefault(cat, []).append((text, cat))
    items = []
    for cat, pool in by_cat.items():
        rng.shuffle(pool)
        items.extend(pool[: POOL_CAP.get(cat, len(pool))])
    rng.shuffle(items)
    print(f"模板展开+去重+截断后：{len(items)} 条")
    bad = check_triggers(items)
    if bad:
        for cat, tg, snip in bad[:10]:
            print(f"  ⚠️ trigger 泄漏 [{cat}] 含「{tg}」: {snip}")
        raise SystemExit(f"trigger-free 子语义含 {len(bad)} 处 trigger，修掉再来")
    train, val, test = stratified_split(items, 500, 75, 75, seed=20260722)
    write_jsonl(base / "train" / "ppt-generate.jsonl", train)
    write_jsonl(base / "val" / "ppt-generate.jsonl", val)
    write_jsonl(base / "test" / "ppt-generate.jsonl", test)
    print(f"train={len(train)} val={len(val)} test={len(test)}")
    for name, split in [("train", train), ("val", val), ("test", test)]:
        c = Counter(SUBCAT[cat][0] for _, cat in split)
        print(f"\n{name} 子语义分布（共 {len(split)}）：")
        for cat, (code, cname) in SUBCAT.items():
            print(f"  {code}-{cname:<14} {c.get(code, 0):>3}")


if __name__ == "__main__":
    main()
