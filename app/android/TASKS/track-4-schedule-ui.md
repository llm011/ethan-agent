# Track 4: Schedule UI 增强

> 状态：⬜ 待认领 · 优先级：P1 · 前置依赖：Track 1 已合并

## 目标

补齐 Schedule 的「立即触发」「创建任务」「Timeline 时间线」三大能力。

## 独占文件清单（只能改这些）

- `app/android/app/src/main/kotlin/com/ethan/agent/ui/schedule/ScheduleScreen.kt`
- `app/android/app/src/main/kotlin/com/ethan/agent/ui/schedule/ScheduleViewModel.kt`

**严禁触碰**：
- `data/EthanRepository.kt`、`core/model/`、`core/network/`（Track 1 管）
- `ui/components/`（Track 7 管）
- 其他 UI 模块

## 当前实现

ScheduleScreen 已有：
- 列表卡片显示 name、trigger、nextRunTime、status
- 暂停/恢复（toggleJob，调 PATCH）
- 删除
- 查看关联对话（跳转 Chat）

**缺失**：
- ❌ 不能手动触发
- ❌ 不能创建任务（PRD 明确说不提供，但 Web 已有，建议补）
- ❌ 没有 Timeline 时间线

## 缺失功能（本 Track 任务）

### 1. 立即触发（P0）

后端：`POST /api/schedule/{id}/trigger`（Track 1 已加 Repository 方法）

需求：
- 每个 job 卡片加「立即触发」按钮（图标 `Icons.Filled.PlayArrow`）
- 点击后调 `repository.triggerSchedule(jobId)`
- 触发过程中按钮 loading
- 成功后 snackbar「已触发，跳转到关联会话查看」+ 提供「查看」按钮跳转 Chat
- 失败显示错误

注意：当前 PlayArrow 图标被用作 toggle，需要拆成两个按钮：
- toggle 按钮：`Icons.Filled.Pause` / `Icons.Filled.PlayCircle`（暂停/恢复）
- trigger 按钮：`Icons.Filled.Bolt` 或 `Icons.Filled.PlayArrow`（一次性触发）

### 2. 创建任务（P1）

后端：`POST /api/schedule`（Track 1 已加 Repository 方法）

需求：
- 顶部加 FAB（`Icons.Filled.Add`）
- 弹出 BottomSheet 表单：
  - name：任务名称
  - prompt：触发时要发送的提示词（多行）
  - trigger type：FilterChip 切换 cron / interval
  - cron：cron 表达式输入（cron 模式）
  - interval_minutes：分钟数输入（interval 模式）
  - session_id：可选，关联会话（提供「选择会话」入口）
  - end_date：可选，结束日期（DatePicker）
  - category：可选，分类
  - scene：可选，场景
- 保存调 `repository.createSchedule(...)`

参考：[desktop/src/components/ScheduleView.tsx](file:///Users/jsongo/code/life/ethan-ai/desktop/src/components/ScheduleView.tsx) 中的创建表单

### 3. Timeline 时间线（P1）

后端：`GET /api/schedule/timeline-status`、`POST /api/schedule/sync-timelines`、`POST /api/schedule/timeline/{id}/{action}`（Track 1 已加）

需求：
- 顶部 Tab 切换：Jobs / Timelines
- Timelines Tab：
  - 列出所有 timeline，按 scene 分组
  - 每个 timeline 显示：name、当前 phase、next_phase_at、status
  - 操作按钮：
    - skip_phase：跳过当前阶段
    - advance_phase：进入下一阶段
    - pause / resume
    - cleanup：清理
  - 顶部加「同步」按钮调 `syncTimelines`
  - 顶部加「导出」/「导入」入口（P2，可选）

参考：[desktop/src/components/ScheduleView.tsx](file:///Users/jsongo/code/life/ethan-ai/desktop/src/components/ScheduleView.tsx) Timeline 部分

### 4. 编辑任务（P2）

后端：`PATCH /api/schedule/{id}`（已有，扩展支持重命名 + 改 prompt）

需求：
- 长按 job 卡片弹「编辑」菜单
- 可改 name、prompt、active/paused
- 保存调 `patchSchedule`

### 5. 飞书日历同步（P2，可选）

后端：`POST /api/schedule/timeline/{id}/sync-lark`、`POST /api/schedule/timeline/{id}/cleanup-lark`

需求：
- Timeline 卡片右上角菜单加「同步到飞书日历」/「清理飞书日历事件」
- 调对应 API

## Tab 设计建议

```kotlin
enum class ScheduleTab(val title: String) {
    Jobs("任务"),
    Timelines("时间线"),
}
```

## ViewModel 状态建议

```kotlin
data class ScheduleUiState(
    val tab: ScheduleTab = ScheduleTab.Jobs,
    val jobs: List<ScheduleJob> = emptyList(),
    val timelines: List<TimelineStatus> = emptyList(),
    val triggeringIds: Set<String> = emptySet(),  // 正在触发的 job
    val showCreateDialog: Boolean = false,
    val createForm: CreateScheduleForm = CreateScheduleForm(),
    val isLoading: Boolean = false,
    val error: String? = null,
)
```

## 参考代码

- 后端：[ethan/interface/routers/schedule.py](file:///Users/jsongo/code/life/ethan-ai/ethan/interface/routers/schedule.py)
- Web 客户端：[desktop/src/lib/api-misc.ts](file:///Users/jsongo/code/life/ethan-ai/desktop/src/lib/api-misc.ts) 中的 `triggerSchedule`、`fetchTimelineStatus`、`timelineLifecycle`
- Web 视图：[desktop/src/components/ScheduleView.tsx](file:///Users/jsongo/code/life/ethan-ai/desktop/src/components/ScheduleView.tsx)

## 验收标准

- [ ] Jobs Tab 中每个 job 卡片有「立即触发」按钮，能成功触发
- [ ] 顶部 FAB 能弹创建表单，能成功创建 cron 和 interval 两种任务
- [ ] Timelines Tab 能加载所有 timeline，按 scene 分组
- [ ] Timeline 操作按钮能调对应 lifecycle API
- [ ] 编译通过、lint 无 error

## 不要做的事

- ❌ 不要改 `EthanRepository`（Track 1 管）
- ❌ 不要实现 Timeline 的导入/导出（P2 留作后续）
- ❌ 不要创建新的 ViewModel 文件（保持单文件）
