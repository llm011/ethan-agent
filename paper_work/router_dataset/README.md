# Router Dataset（监督分类头训练集）

BGE embedding → LR 分类头的训练/验证/测试集。用于替换/对比现行的 multi-prototype 向量快筛。

## 结构

```
router_dataset/
├── train/   500/类  训练分类器权重（legal-assistant、companion-listen 语义更宽，可上浮到 600+）
├── val/      75/类  调 FLOOR / 正则 / 超参（可多次跑）
└── test/     75/类  最终评测，只在收尾跑一次，不据此调参
```

train 优先凑够 500/类；val/test 各 75/类固定，用来选超参与最终报数。

## 格式

每行一个样本，jsonl：

```json
{"text": "这篇 pdf 到底讲了啥", "label": "paper-analysis"}
```

文件名 = label 名，放在对应 split 目录下。

## 类别（9）与子语义规划

> 生成顺序：一类一类来。每类先把「现有子语义 + 未来可能子语义」列成子类别树，
> 再按子类别分配样本配额，避免简单均分、避免遗漏边界。

### paper-analysis（semantic）— 见 `gen_paper_analysis.py`
- A 概览/整体理解  B 方法/思路  C 实验/结果  D 结论/贡献
- E 结构/框架  F 创新点  G 对比/前人工作  H 复现/可用性
- I 通俗转述/翻译  J 批判/局限  K 指定来源（链接/编号/本地文件）
- 未来：复现踩坑、跨论文对比、引用图谱、作者谱系

### companion-listen（emotional）— 苏念陪伴
- 情绪低落/emo/崩溃  压力大/焦虑/失眠  委屈/想哭/不被理解
- 孤独/想找人说话  感情困扰/分手  职场人际/被针对  自我怀疑/迷茫/没动力
- 家庭矛盾  悲伤/丧亲  直接点名「苏念/陪我聊聊」
- 未来：节日孤独、深夜emo、产后、考前焦虑、空巢

### deepwiki（action）— GitHub 仓库文档/架构
- 查文档  看架构/目录结构  懂用法/API  找入口/快速上手
- 跨仓库对比  看某模块实现  技术选型参考  贡献者/issue 上下文
- 未来：release notes、迁移指南、对比竞品仓库

### lark-im（action）— 飞书即时通讯
- 发消息/回复  搜聊天记录  建群/管群  传文件/图片
- @提醒/加急  表情回复  撤回/转发  Pin/话题  群成员管理
- 未来：消息卡片、机器人发图、话题群、Feed 置顶

### channels（action）— 消息渠道接入
- 飞书 WebSocket 配置  webhook  接入/连通性排查
- App ID/Secret  重启服务  连接掉线
- 未来：微信、Telegram、Slack 接入

### skills-manager（action）— 技能包管理
- 装技能  卸载技能  更新技能  搜/找技能  列出已装
- 全局/项目安装  覆盖内置  能力包/扩展
- 未来：版本回滚、依赖冲突、技能市场

### lark-shared（action）— lark-cli 配置/认证
- auth login 登录  切 user/bot 身份  权限不足/scope 报错
- 更新 lark-cli  登录态/凭证  config init  二维码授权
- 未来：多账号、token 过期、企业切换

### legal-assistant（semantic，可上浮 600+）— 法律咨询
- 合同审查/起草  诉讼/起诉/应诉  知识产权（商标/专利/著作权）
- 文书起草（律师函/起诉状/答辩状）  法律检索（法规/案例）
- 证据/举证  劳动纠纷  婚姻家事  公司/股权  交通/侵权
- 数据可视化（证据链/关系图）  合规/风控
- 未来：跨境/涉外、税务、刑法咨询、AI 合规

### others（reject）— 拒识
- 纯无关（天气/算术/翻译/写代码/闲聊/常识）
- 贴边陷阱（论文排版≠paper、git 怎么用≠deepwiki、飞书网页登录≠lark-shared）

## 样本生成规则（防泄漏 + 防作弊）

1. **避开 trigger 原词子串**：query 不得包含对应 skill SKILL.md 里任一 trigger 的连续子串。
   否则关键词硬匹配就能命中，测的是关键词不是语义泛化，分类器会学到"含 trigger 词"的捷径。
2. **三 split 独立生成**：train/val/test 用不同种子和切入角度，避免近邻泄漏。
   - train：覆盖面广，多说法变体
   - val：中等难度
   - test：最贴近真实用户口吻（口语、含错别字、省略、不完整句）
3. **多语气/多长度/口语化**：每类样本要长短不一、口语/正式/疑问/命令混搭，
   避免分类器学到单一"生成风格"。
4. **贴边陷阱（others 重点）**：others 要含与各 skill 边界模糊但实际不属于的样本
   （如"论文格式排版"≠ paper-analysis，"git 怎么用"≠ deepwiki）。

## 分类器（计划）

- 特征：BGE-small-zh INT8 embedding（512 维）
- 模型：LogisticRegression（multinomial, L2）
- 拒识：max_prob < FLOOR → others（open-set）
- val 扫 FLOOR，test 只跑一次出最终 P/R/F1/拒识
