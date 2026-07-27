# Track 3: Memory UI 增强

> 状态：⬜ 待认领 · 优先级：P1 · 前置依赖：Track 1 已合并

## 目标

让 MemoryScreen 支持 Insights（永久记忆）和 Structured Records（结构化记忆）两套新系统，并提供手动 Consolidate 入口。

## 独占文件清单（只能改这些）

- `app/android/app/src/main/kotlin/com/ethan/agent/ui/memory/MemoryModels.kt`
- `app/android/app/src/main/kotlin/com/ethan/agent/ui/memory/MemoryScreen.kt`
- `app/android/app/src/main/kotlin/com/ethan/agent/ui/memory/MemoryViewModel.kt`

**严禁触碰**：
- `data/EthanRepository.kt`、`core/model/`（Track 1 管）
- `ui/components/`（Track 7 管）
- 其他 UI 模块

## 当前实现

MemoryScreen 已有 3 Tab：
- Facts（列表 + 编辑 + 删除）
- Episodes（仅列表 + 删除，后端已退役返回空）
- Procedures（列表 + 删除）

## 缺失功能（本 Track 任务）

### 1. 新增 Tab：Insights（P0）

后端：
- `GET /api/memory/insights?limit=50&offset=0`（Track 1 已加 Repository 方法）
- `GET /api/memory/insights/date/{date_str}`

需求：
- Tab 改为 4 个：Facts / Insights / Procedures / Records（Episodes 移除或隐藏）
- Insights Tab 显示永久记忆卡片列表（每条显示 content、date、importance）
- 顶部加日期筛选器（默认今天，可切换历史日期）
- 支持下拉刷新

### 2. 新增 Tab：Structured Records（P0）

后端：
- `GET /api/memory/records?type=&status=&domain=&limit=&offset=`
- `GET /api/memory/records/search?q=&limit=`
- `GET /api/memory/records/{id}`（详情含 evidence）
- `PATCH /api/memory/records/{id}`
- `DELETE /api/memory/records/{id}`（forget）
- `POST /api/memory/records/{id}/confirm`（候选转正）
- `GET /api/memory/records/summaries?domain=&limit=`

需求：
- Records Tab 显示结构化记忆卡片：
  - 顶部状态 FilterChip：All / Pending（候选）/ Confirmed / Superseded
  - 顶部类型 FilterChip：general / signal / observation / reflection / ...
  - 顶部 domain 切换：general / signal / observation / reflection
  - 卡片显示 content、structured_data（JSON 美化）、confidence、importance、valid_from/until
  - 点击进入详情页（新 Composable）：显示完整 evidence 列表
- Pending 状态的卡片加「确认」按钮调 `confirmStructuredCandidate`
- 任何卡片可编辑（content、importance、confidence）
- 任何卡片可删除（forget，二次确认）
- 顶部加搜索框（300ms debounce），调 `searchStructuredMemories`

### 3. 手动 Consolidate（P1）

后端：
- `POST /api/memory/consolidate`（夜间统一沉淀）
- `POST /api/memory/records/consolidate?target_date=`（结构化日沉淀）

需求：
- Facts Tab 顶部加「立即沉淀」按钮（图标 `Icons.Filled.AutoAwesome`），调 `triggerConsolidation`
- Records Tab 顶部加「结构化沉淀」按钮，调 `triggerStructuredConsolidation`，可选 target_date
- 沉淀过程中显示 loading dialog「正在沉淀，可能需要 1-2 分钟…」
- 完成后刷新列表

### 4. 日摘要列表（P2）

后端：`GET /api/memory/records/summaries?domain=&limit=`

需求：
- Records Tab 顶部加「查看日摘要」入口（图标 `Icons.Filled.CalendarToday`）
- 进入日摘要列表页，按日期倒序展示
- 点击某天的摘要，显示完整 summary 内容

### 5. Episodes 清理（P0）

后端 episodes 已退役，返回空列表。

需求：
- 直接移除 Episodes Tab
- 不再调用 `repository.getEpisodes()` / `deleteEpisode()`
- 如果 Track 1 把 `Episode` 标记了 `@Deprecated`，本 Track 不再 import 它

## Tab 设计建议

```kotlin
enum class MemoryTab(val title: String) {
    Facts("事实"),
    Insights("永久记忆"),
    Procedures("流程"),
    Records("结构化记忆"),
}
```

使用 `TabRow` + `HorizontalPager` 实现左右滑动切换。

## ViewModel 状态建议

```kotlin
data class MemoryUiState(
    val tab: MemoryTab = MemoryTab.Facts,
    val facts: List<Fact> = emptyList(),
    val insights: List<Insight> = emptyList(),
    val procedures: List<Procedure> = emptyList(),
    val records: List<StructuredRecord> = emptyList(),
    val recordsFilter: RecordsFilter = RecordsFilter(),
    val recordsSearch: String = "",
    val selectedRecord: StructuredRecord? = null,
    val summaries: List<DailySummary> = emptyList(),
    val isConsolidating: Boolean = false,
    val isLoading: Boolean = false,
    val error: String? = null,
)

data class RecordsFilter(
    val status: String? = null,    // pending / confirmed / superseded
    val type: String? = null,
    val domain: String = "general",
)
```

## 参考代码

- 后端：[ethan/interface/routers/memory.py](file:///Users/jsongo/code/life/ethan-ai/ethan/interface/routers/memory.py)
- Web 客户端：[desktop/src/lib/api-memory.ts](file:///Users/jsongo/code/life/ethan-ai/desktop/src/lib/api-memory.ts)
- Web 视图：[desktop/src/components/MemoryView.tsx](file:///Users/jsongo/code/life/ethan-ai/desktop/src/components/MemoryView.tsx)

## 验收标准

- [ ] 4 Tab 切换流畅
- [ ] Insights 列表能加载，日期筛选生效
- [ ] Records 列表能加载，status/type/domain 过滤生效
- [ ] Pending 记录能 confirm，列表刷新
- [ ] 任何记录能编辑、删除
- [ ] 「立即沉淀」按钮可触发，完成后刷新
- [ ] 编译通过、lint 无 error

## 不要做的事

- ❌ 不要改 `EthanRepository`（Track 1 管）
- ❌ 不要改 `core/model/` 下的 Model 类（Track 1 管）
- ❌ 不要实现笔记编辑器（Markdown 编辑用 `SimpleMarkdown`，渲染交给 Track 7 升级）
- ❌ 不要改 Tab 数量超过 4 个（移动端空间有限）
