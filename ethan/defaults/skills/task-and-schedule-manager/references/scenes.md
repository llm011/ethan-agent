# 场景标签定义

## 概述

场景标签用于区分 Agent 管理的不同领域任务，避免工作/生活混淆，支持按场景过滤和统计。

所有通过 Agent 创建的定时任务、飞书任务、提醒都应携带场景标签。

## 标签枚举

| 标签 | 标识 | 说明 | 示例 |
|---|---|---|---|
| 工作 | `work` | 职场工作相关 | 安排需求、技术方案、CR、绩效 |
| 生活 | `life` | 日常生活事务 | 家务、购物、预约、缴费 |
| 健康 | `health` | 运动、医疗、作息 | 体检、运动计划、睡眠管理 |
| 学习 | `study` | 个人成长、学习 | 读书、课程、技能提升 |
| 理财 | `finance` | 投资、理财、账单 | 基金、保险、账单提醒 |
| 社交 | `social` | 人际关系维护 | 生日提醒、聚会、送礼 |

## 自动推断规则

Agent 根据以下信号自动推断场景标签：

| 信号 | 推断结果 |
|---|---|
| 提到团队成员姓名（team.yaml 中的人） | `work` |
| 提到项目名称 | `work` |
| 提到「技术方案」「需求」「上线」「review」 | `work` |
| 提到「买」「预约」「家里」「物业」 | `life` |
| 提到「锻炼」「跑步」「体检」「药」 | `health` |
| 提到「学」「看书」「课程」「论文」 | `study` |
| 提到「转账」「理财」「基金」「账单」 | `finance` |
| 无法推断时 | 询问用户 |

## 在飞书任务中的表现

飞书任务标题前缀格式：`[{scene}]`

示例：
- `[work] 设计产品插件架构`
- `[life] 预约周六搬家公司`
- `[health] 本周三次 5km 跑步`

## 在 scheduler 中的表现

定时任务的 metadata 中携带 scene 字段：

```yaml
metadata:
  scene: work
  category: timeline    # one_off / recurring / timeline
  source_timeline: perf_semi_annual  # 仅 timeline 类有
```

## 过滤与展示

用户可以通过以下方式按场景操作：

- 「看看我工作上的待办」→ 只展示 scene=work 的任务
- 「生活上还有什么没做的」→ 只展示 scene=life 的任务
- 「这周都安排了什么」→ 全场景展示，按 scene 分组

## 扩展

用户可以自定义新的场景标签，在 `~/.ethan/work/team.yaml` 中添加：

```yaml
custom_scenes:
  - id: "side_project"
    name: "副业"
    keywords: ["副业", "外包", "兼职"]
  - id: "parenting"
    name: "育儿"
    keywords: ["孩子", "学校", "辅导"]
```
