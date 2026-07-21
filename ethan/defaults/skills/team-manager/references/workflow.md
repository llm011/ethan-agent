# 任务委派流程与 Checkpoint 拆分指南

## 委派流程 SOP

### Phase 1: 解析任务

从用户输入中提取：

| 字段 | 说明 | 必须 |
|---|---|---|
| `assignee` | 被委派人姓名 | ✅ |
| `title` | 任务标题（简洁概括） | ✅ |
| `description` | 任务详细描述 | ✅ |
| `deliverables` | 期望产出物 | ✅ |
| `deadline` | 总 DDL | 需确认 |
| `scene` | 场景标签 | 自动推断或询问 |
| `project` | 关联项目 | 可选 |
| `context` | 背景信息/参考资料 | 可选 |

### Phase 2: 确认 DDL

如果用户没有明确 DDL：
1. 根据任务复杂度建议一个合理的时间范围
2. 询问用户确认或调整

DDL 建议参考：
- 简单调研/文档：2-3 个工作日
- 技术方案设计：5-8 个工作日
- 功能开发（小）：3-5 个工作日
- 功能开发（中）：1-2 周
- 复杂项目/重构：2-4 周

### Phase 3: 拆分 Checkpoint

#### 通用拆分模板

**技术方案类**:
```
1. 调研 & 信息收集（20-30% 时间）
   - 产出：调研结论文档/要点整理
   - 提醒：阶段结束前 1 天

2. 方案设计 & 初稿（30-40% 时间）
   - 产出：技术方案文档 V1
   - 提醒：启动时 + 结束前 1 天

3. 评审 & 对齐（15-20% 时间）
   - 产出：评审会议 + 修改后方案
   - 提醒：提前约会议 + 结束前确认
```

**功能开发类**:
```
1. 方案确认（10-15%）
   - 产出：技术方案/设计文档对齐
   
2. 核心实现（50-60%）
   - 产出：核心代码完成 + 自测通过
   - 提醒：中间节点确认进度

3. 联调 & 测试（20-25%）
   - 产出：联调通过 + 提测
   
4. 上线 & 验证（5-10%）
   - 产出：灰度/全量上线
```

**文档/调研类**:
```
1. 信息收集（40-50%）
   - 产出：原始资料整理

2. 整理 & 输出（40-50%）
   - 产出：最终文档

3. 分享/同步（10%）
   - 产出：完成分享
```

### Phase 4: 创建飞书任务

调用 `lark-task` 创建：

1. **主任务**：
   - 标题：`[{scene}] {任务标题}`
   - 描述：包含背景、期望产出、各阶段说明
   - 到期日：总 DDL
   - 指派人：被委派人
   - 关注人：管理者（你）

2. **子任务**（每个 checkpoint 一个）：
   - 标题：阶段名称
   - 到期日：阶段 DDL
   - 描述：该阶段的期望产出

3. **提醒设置**：
   - 飞书任务原生的到期提醒
   - 额外的 Agent 定时提醒（通过 scheduler）

### Phase 5: 设置提醒序列

为每个 checkpoint 创建提醒：

```yaml
reminders:
  - timing: "checkpoint_start"
    message: "今天 {阶段名} 开始，目标产出：{产出物}"
    
  - timing: "checkpoint_end - 1d"  
    message: "明天 {阶段名} 截止，产出物：{产出物}。如果有阻塞请及时同步"
    
  - timing: "need_coordination"  # 需要约人/会议时
    message: "记得提前约 {相关人} 的时间做 {事项}"
    
  - timing: "total_ddl - 2d"
    message: "后天整体交付截止，请确认：{checklist}"
```

## 任务状态管理

### 状态流转

```
created → in_progress → [checkpoint_1_done] → ... → completed
                    ↘ delayed (需要延期)
                    ↘ cancelled (取消)
```

### 管理者可执行的操作

| 指令 | 效果 |
|---|---|
| 「延期 N 天」 | 更新 DDL，调整后续 checkpoint |
| 「跳过 XX 阶段」 | 标记为跳过，不影响后续 |
| 「取消这个任务」 | 关闭飞书任务，记录原因 |
| 「进度怎样了」 | 查看当前状态 + 已完成的 checkpoint |
| 「加个 checkpoint」 | 在现有阶段间插入新节点 |

## 与 Scheduler 集成

提醒通过 Agent 的 scheduler 模块实现：

```python
# 概念示例（非实际代码）
schedule.create(
    name="task_remind_{task_id}_{checkpoint}",
    cron="0 10 {date} * *",  # 当天上午 10 点
    message="提醒 {assignee}：{reminder_content}",
    metadata={
        "scene": "work",
        "category": "one_off",
        "task_id": "xxx",
        "type": "task_checkpoint"
    }
)
```

## 联动记录

任务完成时自动生成 case：

```json
{
  "date": "2026-07-31",
  "source": "manual",
  "tags": ["产出", "需求交付"],
  "content": "按时完成产品插件架构技术方案设计，方案在团队评审中获得一致认可",
  "project": "插件体系",
  "ref": "lark_task_id_xxx"
}
```

任务延期时：

```json
{
  "date": "2026-07-31",
  "source": "manual",
  "tags": ["风险"],
  "content": "插件架构方案设计延期 3 天，原因：依赖的 API 文档不全需要额外调研",
  "project": "插件体系",
  "context": "延期有合理原因，非能力问题"
}
```
