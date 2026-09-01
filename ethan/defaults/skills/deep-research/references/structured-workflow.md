# 大规模结构化调研工作流（来自 workbuddy Deep-Research-skills）

> 本文档是 deep-research 技能「模式二」的完整操作说明，融合自 workbuddy 生态的
> [Deep-Research-skills](https://github.com/Weizhena/Deep-Research-skills)（MIT）。
> 已适配 ethan 的实际工具（background_task / skill_read / scripts/validate_json.py）。

## 适用场景

需要**系统性盘点多个并列对象、每个对象按统一字段收集数据**的横向调研：
- 学术综述 / benchmark 对比 / 技术选型横评 / 竞品盘点 / 行业格局梳理

## 完整流程

### Phase 1：拆解（outline.yaml + fields.yaml）

1. 基于已有知识，把话题拆成 items（调研对象列表）+ fields（统一字段框架）。
2. 写入两个文件（用模板创建）：
   - `<topic>/outline.yaml`：items + execution 配置（batch_size / items_per_agent / output_dir）
   - `<topic>/fields.yaml`：field_categories → fields（name / description / required / detail_level）
3. 展示给用户确认（AskUserQuestion）：items 增删、字段补全、时间范围、并行度。

### Phase 2：并行深挖（background_task）

每个 item 一个后台调研任务，prompt 固定模板：

```
调研 <item 完整信息>，输出结构化 JSON 到 <results>/<item_slug>.json

## 字段定义
读取 <fields_path> 获取所有字段定义

## 输出要求
1. 按 fields.yaml 定义的字段输出 JSON
2. 不确定的字段值标注 [不确定]
3. JSON 末尾添加 uncertain 数组，列出所有不确定的字段名
4. 所有字段值使用中文输出

## 验证
完成后运行：python <skill_dir>/scripts/validate_json.py -f <fields_path> -j <output_path>
验证通过才算完成。
```

**断点续传**：
- `results/` 下已存在的 `.json` 视为已完成，跳过。
- 按 batch_size 分批，一批跑完、用户同意再起下一批。
- 中断后重跑：只补缺失/失败的 item，不重复已完成的。

**后台任务**：用 `background_task`（title + prompt）发起并行调研，不阻塞当前对话；
用 `background_task_list` 看进度、`background_task_stop` 终止。

### Phase 3：汇总报告

1. 读全部 `<item>.json` + fields.yaml。
2. 生成 `report.md`：
   - 开头：总览表（每个 item 一行 + 用户选的摘要字段，如 stars / score / date）
   - 正文：按 item 分节，按 field_categories 逐字段展示
   - 跳过值含 `[不确定]` 的字段；uncertain 数组的字段标注"未确认"
   - 多出的字段（fields.yaml 没定义的）归入「其他信息」
3. 用 AskUserQuestion 确认总览表要展示哪些摘要字段。

## 关键纪律

- **字段覆盖**：必填字段缺失即视为失败，用 validate_json.py 把关。
- **不确定性透明**：不确定的值标 `[不确定]` + 进 uncertain 数组，不硬编造。
- **来源可溯**：每个量化数据带来源链接。
- **用户确认**：拆解、批次、摘要字段三步都要用户确认，人在回路。
