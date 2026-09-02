---
name: deep-research
description: "深度调研/对比分析/研究报告：多轮检索 + 数据缺口回填 + 图表可视化 + 决策导向报告；也支持大规模多对象结构化调研（outline.yaml 拆解 + 断点续传 + 并行后台 agent + JSON 字段校验），后者来自 workbuddy 生态的 Deep-Research-skills"
version: 1.2.0
author: Hermes Agent
license: MIT
trigger:
  - 深度调研
  - 调研
  - 对比分析
  - 研究报告
  - 深度对比
  - 全面对比
  - 深度分析
  - deep research
  - market research
  - industry research
  - 结构化调研
  - 多对象调研
  - 大规模调研
  - research outline
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [Research, Analysis, Report, Comparison, Decision]
    related_skills: [arxiv, paper-analysis, llm-wiki]
source: internal (hermes agent) + workbuddy Deep-Research-skills
---
# 深度调研

把调研做成**能帮人做决策的报告**，不是资料堆砌。读者看完知道选什么、为什么。

## 输入识别（先判断再动手）

收到调研请求后，先识别类型再选策略：

| 类型 | 特征 | 策略 |
|------|------|------|
| **对比决策** | "X vs Y"、"哪个好"、"选哪个" | 走完整对比模板（速览表 + 决策矩阵） |
| **单主题深挖** | "调研 X 方案"、"X 怎么做" | 跳过对比速览，改为：现状→方案→优劣→建议 |
| **多候选选型** | 3+ 候选对象 | 对比速览扩展为多列，决策矩阵保留 |

**维度确认**：如果用户指定了维度（"从性能和价格两方面"），只深挖这些维度；未指定则由广度扫描自动发现。

**附带材料**：用户给了文档/链接作为输入时，先提取其中的关键信息作为调研起点，减少重复搜索已知内容。

## 调研方法论（3 阶段，按序执行）

**本 skill 命中时，agent.md「搜索收敛原则」由下列数据清单替代——按清单逐项补全，不受 2-3 次限制。**

**渐进交付**：调研过程中保持用户可感知的进度：
- 广度扫描后：输出"已识别 N 个维度：[维度列表]，开始逐项深挖"
- 每完成 1-2 个维度的深度补全：简短告知进展（如"定价和性能数据已收集完毕"）
- 缺口回填阶段如果耗时较长：说明正在核实哪些数据点

### ① 广度扫描（2-3 次搜索）
宽泛关键词勾勒全貌（如"X vs Y 对比"、"X 参数 性能 价格"）。目标：列出对比维度清单。

### ② 深度补全（逐维度抓一手来源）
每个维度抓**官方/权威原始页面**，不要只看二手博客：
- 参数 → 官方 spec / model card / HuggingFace
- 定价 → 官方 API pricing 页
- 性能 → 官方 blog + 权威榜单（Artificial Analysis、SWE-bench leaderboard、Arena）
- 市场 → 第三方统计（OpenRouter、头部媒体）

**搜索策略**：
- 语言：先英文搜（覆盖面广），再中文补充本地化信息（定价、合规、国内生态）
- 时效：优先近 6 个月来源；超过 1 年的数据需注明时间并标记可能过时
- 每维度 2-4 次搜索为上限，达到后进入下一维度
- 并行搜索：同一阶段内的多个维度可并行发起搜索请求

**矛盾数据处理**：来源间数据冲突时——①标注冲突（"A 称 X，B 称 Y"）②采信优先级：官方文档 > 权威榜单 > 第三方实测 > 媒体报道

### ③ 数据缺口回填（质量关键，不可跳过）
对照下方清单逐项检查，**每项都要有数据，或标注"经 ≥3 处来源核实确未公开"**：
- 搜不到 ≠ 不存在。换角度：官方英文文档、API pricing、HuggingFace、第三方实测、GitHub README。
- 同一数据交叉验证 ≥2 源；冲突取权威源并标注分歧。
- **禁止**只搜 1-2 次就写"未公开/未披露"——至少试过官方定价页 + 2 个第三方来源后才可下此结论。

## 报告模板

根据输入识别的类型选模板。所有模板共享原则：**决策优先 + 数据可视 + 来源可溯**。

### 模板 A：对比决策（默认）

```
# {标题}

## 执行摘要（3-5 句，决策导向）
结论先行：推荐什么、关键数据**加粗**、点出 1 个反直觉发现。

## 对比速览（1 张表，全维度）
| 维度 | A | B | 差异 |
覆盖：参数/上下文/定价/开源/多模态/发布时间

## 关键维度深挖（每节配图表 + 内联引用）
### 定价与成本
- 价格表 + generate_chart(horizontalBar)
- ≥1 个成本场景计算（如 100K 输入 + 30K 输出总成本）
### 性能
- benchmark 表 + generate_chart(bar)
### 其他关键差异（按主题选）

## 选型决策矩阵
| 场景 | 推荐 | 理由 |（覆盖 5-8 个典型场景）

## 一句话结论
```

### 模板 B：单主题深挖

```
# {主题} 调研报告

## 执行摘要（3-5 句）
核心结论 + 关键数据 + 1 个意外发现或常见误区。

## 现状与背景
当前主流方案/做法是什么，痛点在哪。

## 方案梳理（每个方案配数据）
### 方案 1: {名称}
原理、适用场景、关键指标、局限性。
### 方案 2: {名称}
...

## 关键数据（配图表）
量化对比或趋势数据 + generate_chart

## 实践建议
| 场景 | 推荐方案 | 理由 |

## 一句话结论
```

## 图表（必须生成 ≥1 张）
用 `generate_chart` 工具，数据来自调研结果（不要编造）：
- 定价对比 → `horizontalBar`（便宜的在上方直观）
- benchmark 对比 → `bar`（多系列分组）
- 市场份额/排名 → `bar`
- 趋势 → `line`

## 内联引用（必须）
每个量化数据后标来源，格式：`` ¥1/百万token `https://...` `` 或 `[来源](url)`。
web_search 返回卡片的 url 就是引用源，不要丢弃。

## 成稿前自检
- [ ] 执行摘要能独立支撑决策？
- [ ] 关键数据都有来源？
- [ ] ≥1 张图表？
- [ ] 决策矩阵/实践建议覆盖主要场景？
- [ ] "未公开"的数据是否多源核实过？
- [ ] 输出模板匹配输入类型（对比 vs 单主题）？

完整 annotated 示例见 `references/report-template.md`（用 skill_read 查阅）。

---

# 模式二：大规模结构化调研（来自 workbuddy）

> **来源**：本模式融合自 workbuddy 生态的 [Deep-Research-skills](https://github.com/Weizhena/Deep-Research-skills)（homepage: `https://github.com/Weizhena/Deep-Research-skills`），MIT 许可。与上面的「决策导向报告」互补：**决策导向**适合「X vs Y / 选哪个」这类给结论的报告；**结构化调研**适合「需要系统性盘点 N 个对象、每个对象按统一字段收集」的横向调研（学术综述、benchmark 对比、技术选型横评、竞品盘点）。

## 何时走模式二

当调研对象是**多个并列实体**、且每个都要按**同一套字段**收集数据时，用结构化流水线。典型：盘点 10 个 Agent 框架、对比 8 个向量库、综述某方向 20 篇论文、横向评估 5 家云厂商。

对象 ≤2 个、只要一个结论 → 走上面的决策导向模式，不要用本模式（重了）。

## 结构化流水线（4 步，按序）

```
Step 1 拆解：把话题拆成 items（调研对象）+ fields（统一字段），写入 outline.yaml / fields.yaml
Step 2 确认：展示 outline 给用户，确认 items 是否增减、字段是否齐全、并行度
Step 3 深挖：每个 item 一个后台调研任务（background_task 并行），逐字段收集数据，产出 <item>.json
Step 4 汇总：读全部 JSON，按 fields.yaml 结构汇总成 report.md
```

### Step 1：拆解话题

基于已有知识列出：
- **items**：该领域的主要研究对象（如具体产品、框架、论文、公司）
- **fields**：每个对象要收集的字段（基本信息/技术特性/性能指标/定价/生态…），标注 required 与否

写入两个文件（模板见 `references/structured-outline-template.yaml` 和 `references/structured-fields-template.yaml`，用 skill_read 查阅）：

**outline.yaml**：
```yaml
topic: 调研主题
items:
  - name: 对象A
    category: 分类
    description: 一句话说明为什么纳入
execution:
  batch_size: 3        # 每批并行调研几个对象
  items_per_agent: 1   # 每个后台任务负责几个对象
  output_dir: ./results
```

**fields.yaml**：
```yaml
field_categories:
  - category: 基本信息
    fields:
      - name: release_date
        description: 发布日期
        required: true
        detail_level: 简要
```

### Step 2：确认

把生成的 outline.yaml / fields.yaml 展示给用户，用 AskUserQuestion 确认：
- items 是否要增删？
- 字段框架是否够？
- 时间范围（近 6 个月 / 不限…）？
- 每批并行几个后台任务？

### Step 3：深挖（断点续传 + 并行）

每个 item 发起一个 `background_task`，prompt 里写明：调研对象、要读的 fields.yaml 路径、输出 `<item_slug>.json` 路径、字段值中文、不确定标 `[不确定]` 并进 `uncertain` 数组。

**断点续传**：`results/` 下已存在的 `.json` 视为已完成，跳过；中断后重跑只补缺的 item。一批跑完、用户同意后再起下一批。

每个后台任务产出 JSON 后，用 `scripts/validate_json.py` 校验字段覆盖率：
```bash
python <skill_dir>/scripts/validate_json.py -f <topic>/fields.yaml -j <results>/<item>.json
```
必填字段缺失（coverage < 100% 或 missing_required 非空）即视为失败，需补调研重跑。

### Step 4：汇总报告

读全部 `<item>.json`，按 fields.yaml 的 field_categories 结构汇总为 `report.md`：
- 开头给总览表（每个 item 一行 + 关键摘要字段，如 stars/score/date）
- 正文按 item 分节，逐字段展示
- 值含 `[不确定]` 的字段跳过或标注"未确认"
- 多出的、fields.yaml 没定义的字段归入「其他信息」

## 脚本与模板

- `scripts/validate_json.py` — 校验 JSON 是否覆盖 fields.yaml 全部必填字段（用法见上）
- `references/structured-outline-template.yaml` — outline.yaml 模板
- `references/structured-fields-template.yaml` — fields.yaml 模板（含常用字段分类，可扩展）
- 完整工作流说明见 `references/structured-workflow.md`（用 skill_read 查阅）
