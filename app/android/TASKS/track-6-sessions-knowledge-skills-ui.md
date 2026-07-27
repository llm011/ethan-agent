# Track 6: Sessions + Knowledge + Skills UI 补齐

> 状态：⬜ 待认领 · 优先级：P2 · 前置依赖：Track 1 已合并

## 目标

补齐 Sessions、Knowledge、Skills 三个 UI 模块的小功能缺口。这三个模块改动量小，合并到一个 Track 避免 PR 碎片化。

## 独占文件清单（只能改这些）

- `app/android/app/src/main/kotlin/com/ethan/agent/ui/sessions/SessionsScreen.kt`
- `app/android/app/src/main/kotlin/com/ethan/agent/ui/sessions/SessionsViewModel.kt`
- `app/android/app/src/main/kotlin/com/ethan/agent/ui/knowledge/KnowledgeScreen.kt`
- `app/android/app/src/main/kotlin/com/ethan/agent/ui/knowledge/KnowledgeViewModel.kt`
- `app/android/app/src/main/kotlin/com/ethan/agent/ui/skills/SkillsScreen.kt`
- `app/android/app/src/main/kotlin/com/ethan/agent/ui/skills/SkillsViewModel.kt`

**严禁触碰**：
- `data/EthanRepository.kt`、`core/model/`（Track 1 管）
- `ui/components/`（Track 7 管）
- 其他 UI 模块

## 任务 A：Sessions 增强

### A1. 重生成标题（P0）

后端：`POST /api/sessions/{id}/regen-title`（Track 1 已加）

需求：
- 会话卡片长按弹菜单：重命名 / 重生成标题 / 删除
- 「重生成标题」调 `repository.regenSessionTitle(id)`
- 完成后用返回的新 title 更新列表
- loading 期间卡片显示「生成中...」

### A2. 生成结构化总结（P1）

后端：`POST /api/sessions/{id}/summary`（Track 1 已加）

需求：
- 会话卡片长按菜单加「生成总结」
- 调 `repository.summarySession(id)`
- 返回结构化 summary 后，弹 BottomSheet 展示：
  - summary 总览
  - sections 列表（每段标题 + 内容）
- 提供「复制全文」按钮

### A3. 删除单条消息（P1）

后端：`DELETE /api/sessions/{id}/messages/{msg_id}`（Track 1 已加）

需求：
- 在 ChatScreen 中长按消息弹菜单加「删除」选项
  - **注意**：本任务属于 Track 2 的范畴，Track 6 只负责在 Repository 层暴露方法（Track 1 已做），ChatScreen 的菜单实现由 Track 2 完成
- Sessions 这边无需额外工作

### A4. 过滤器（P2）

后端：`GET /api/sessions?source=&mode=&hide_heartbeat=&hide_scheduled=&title_prefixes=`

需求：
- 顶部搜索框旁加 FilterChip：
  - 来源：All / web / lark / repl / heartbeat
  - 隐藏心跳：toggle
  - 隐藏定时：toggle

## 任务 B：Knowledge 增强

### B1. Markdown 编辑器升级（P1）

需求：
- 当前 KnowledgeScreen 的编辑器是简单 `OutlinedTextField`
- 升级为带预览的编辑器：左侧编辑 + 右侧预览（横屏）/ 顶部编辑 + 底部预览（竖屏）
- 用 `WindowSizeClass` 判断屏幕方向
- 预览用 `SimpleMarkdown`（来自 Track 7 的升级版）

### B2. 标签管理（P2）

需求：
- 当前 tags 是逗号分隔字符串输入，体验差
- 改为 Chip 输入：输入框 + 已添加的 tag 作为 InputChip，可点 × 删除
- 回车或逗号触发添加

### B3. 搜索结果高亮（P2）

需求：
- 搜索时在结果卡片中高亮匹配的关键字
- 用 `AnnotatedString` 实现

## 任务 C：Skills 增强

### C1. 技能分类（P1）

后端 `GET /api/skills` 返回的 skill 信息中可能包含 category（如果后端有）。

需求：
- 列表按 category 分组显示
- 无 category 的归到「未分类」
- 顶部加搜索框过滤

### C2. 技能内容预览（P2）

需求：
- 列表卡片显示 skill 的 description + 前 200 字 content 预览
- 点击进入完整编辑器（已有）

### C3. 校验（P2，可选）

后端：`POST /api/skills/evolve`（演化）

需求：
- 编辑器右上角加「演化」按钮，调 `repository.evolveSkill(name)`
- 返回结果展示在对话框

## 参考代码

- 后端：
  - [ethan/interface/routers/sessions.py](file:///Users/jsongo/code/life/ethan-ai/ethan/interface/routers/sessions.py)
  - [ethan/interface/routers/knowledge.py](file:///Users/jsongo/code/life/ethan-ai/ethan/interface/routers/knowledge.py)
  - [ethan/interface/routers/skills.py](file:///Users/jsongo/code/life/ethan-ai/ethan/interface/routers/skills.py)
- Web 客户端：
  - [desktop/src/lib/api-sessions.ts](file:///Users/jsongo/code/life/ethan-ai/desktop/src/lib/api-sessions.ts)
  - [desktop/src/lib/api-misc.ts](file:///Users/jsongo/code/life/ethan-ai/desktop/src/lib/api-misc.ts) 中 knowledge/skills 部分
- Web 视图：
  - [desktop/src/components/AllSessionsView.tsx](file:///Users/jsongo/code/life/ethan-ai/desktop/src/components/AllSessionsView.tsx)
  - [desktop/src/components/KnowledgeView.tsx](file:///Users/jsongo/code/life/ethan-ai/desktop/src/components/KnowledgeView.tsx)
  - [desktop/src/components/SkillsView.tsx](file:///Users/jsongo/code/life/ethan-ai/desktop/src/components/SkillsView.tsx)

## 验收标准

- [ ] Sessions 卡片长按能弹菜单，重生成标题功能正常
- [ ] Sessions 能生成总结并在 BottomSheet 展示
- [ ] Knowledge 编辑器有预览功能
- [ ] Knowledge 标签用 Chip 输入
- [ ] Skills 列表按 category 分组
- [ ] 编译通过、lint 无 error

## 不要做的事

- ❌ 不要改 `EthanRepository`（Track 1 管）
- ❌ 不要改 ChatScreen（Track 2 管，A3 任务的菜单由 Track 2 做）
- ❌ 不要改 `SimpleMarkdown` 组件本身（Track 7 管，本 Track 只调用）
