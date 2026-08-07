---
name: deep-research
description: "深度调研/对比分析/研究报告：多轮检索 + 数据缺口回填 + 图表可视化 + 决策导向报告"
version: 1.0.0
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
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [Research, Analysis, Report, Comparison, Decision]
    related_skills: [arxiv, paper-analysis, llm-wiki]
source: internal (hermes agent)
---
# 深度调研

把调研做成**能帮人做决策的报告**，不是资料堆砌。读者看完知道选什么、为什么。

## 调研方法论（3 阶段，按序执行）

**本 skill 命中时，agent.md「搜索收敛原则」由下列数据清单替代——按清单逐项补全，不受 2-3 次限制。**

### ① 广度扫描（2-3 次搜索）
宽泛关键词勾勒全貌（如"X vs Y 对比"、"X 参数 性能 价格"）。目标：列出对比维度清单。

### ② 深度补全（逐维度抓一手来源）
每个维度抓**官方/权威原始页面**，不要只看二手博客：
- 参数 → 官方 spec / model card / HuggingFace
- 定价 → 官方 API pricing 页
- 性能 → 官方 blog + 权威榜单（Artificial Analysis、SWE-bench leaderboard、Arena）
- 市场 → 第三方统计（OpenRouter、头部媒体）

### ③ 数据缺口回填（质量关键，不可跳过）
对照下方清单逐项检查，**每项都要有数据，或标注"经 ≥3 处来源核实确未公开"**：
- 搜不到 ≠ 不存在。换角度：官方英文文档、API pricing、HuggingFace、第三方实测、GitHub README。
- 同一数据交叉验证 ≥2 源；冲突取权威源并标注分歧。
- **禁止**只搜 1-2 次就写"未公开/未披露"——至少试过官方定价页 + 2 个第三方来源后才可下此结论。

## 报告模板（决策优先 + 可视化）

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
- [ ] 决策矩阵覆盖主要场景？
- [ ] "未公开"的数据是否多源核实过？

完整 annotated 示例见 `references/report-template.md`（用 skill_read 查阅）。
