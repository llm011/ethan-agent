# Track 1: 网络层 + Repository 补齐

> 状态：⬜ 待认领 · 优先级：P0 · 前置依赖：Track 0 已合并

## 目标

把后端有但 Android 缺的 API 端点全部加到 [EthanApiService.kt](file:///Users/jsongo/code/life/ethan-ai/app/android/core/network/src/main/kotlin/com/ethan/agent/core/network/EthanApiService.kt) 和 [EthanRepository.kt](file:///Users/jsongo/code/life/ethan-ai/app/android/app/src/main/kotlin/com/ethan/agent/data/EthanRepository.kt)，并补对应 Model 类。

本 Track 是 Track 2~8 的前置：UI Track 都依赖这里加好的 Repository 方法。

## 独占文件清单（只能改这些）

- `app/android/core/network/src/main/kotlin/com/ethan/agent/core/network/**`
- `app/android/core/model/src/main/kotlin/com/ethan/agent/core/model/**`
- `app/android/app/src/main/kotlin/com/ethan/agent/data/EthanRepository.kt`
- `app/android/app/src/main/kotlin/com/ethan/agent/di/AppModule.kt`
- `app/android/app/src/main/kotlin/com/ethan/agent/di/AuthTokenCache.kt`

**严禁触碰**：任何 `ui/` 下的文件、`Screen.kt`、`EthanApp.kt`、`MoreScreen.kt`、`build.gradle.kts`、`AndroidManifest.xml`。

## 参考代码

- 后端路由：[ethan/interface/routers/](file:///Users/jsongo/code/life/ethan-ai/ethan/interface/routers/) 下各 .py 文件
- Web 客户端：[desktop/src/lib/api-memory.ts](file:///Users/jsongo/code/life/ethan-ai/desktop/src/lib/api-memory.ts)、[api-misc.ts](file:///Users/jsongo/code/life/ethan-ai/desktop/src/lib/api-misc.ts)、[api-sessions.ts](file:///Users/jsongo/code/life/ethan-ai/desktop/src/lib/api-sessions.ts)、[api-chat.ts](file:///Users/jsongo/code/life/ethan-ai/desktop/src/lib/api-chat.ts)、[api-settings.ts](file:///Users/jsongo/code/life/ethan-ai/desktop/src/lib/api-settings.ts)、[api-annotations.ts](file:///Users/jsongo/code/life/ethan-ai/desktop/src/lib/api-annotations.ts)
- Android 现有风格：[EthanApiService.kt](file:///Users/jsongo/code/life/ethan-ai/app/android/core/network/src/main/kotlin/com/ethan/agent/core/network/EthanApiService.kt) 中已有的 51 个方法

## 任务清单

### 1. Sessions 补齐

| 方法 | 路径 | 请求/响应 |
|------|------|----------|
| POST | `sessions/{id}/regen-title` | 无 body，返回 `{ok, title}` |
| POST | `sessions/{id}/summary` | 无 body，返回 `{summary, sections}` |
| DELETE | `sessions/{id}/messages/{msg_id}` | 无 body，返回 `{ok}` |

参考：[ethan/interface/routers/sessions.py](file:///Users/jsongo/code/life/ethan-ai/ethan/interface/routers/sessions.py)

### 2. Chat 补齐（非 SSE）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `chat/{id}/stream` | 重连进行中的生成（SSE，204 表示无活跃 run）。**用 OkHttp 直接发 GET，不走 Retrofit** |
| POST | `chat/{id}/stop` | 停止生成，已生成部分标记 `[已停止]` 保存 |
| POST | `chat/{id}/inject` | 运行中向 agent 上下文补充信息（409 = 无活跃 run） |

参考：[ethan/interface/routers/chat.py](file:///Users/jsongo/code/life/ethan-ai/ethan/interface/routers/chat.py)、[ChatSseClient.kt](file:///Users/jsongo/code/life/ethan-ai/app/android/core/network/src/main/kotlin/com/ethan/agent/core/network/ChatSseClient.kt)

**实现要点**：`streamResume` 要复用 `ChatSseClient` 的解析逻辑。建议在 `ChatSseClient` 加一个 `resumeStream(sessionId): Flow<ChatStreamEvent>` 方法，发 GET 请求并解析同样的 SSE 事件流。

### 3. Memory 补齐（重点）

后端有 3 套并行的记忆系统，Android 当前只支持 legacy 的 facts/procedures/episodes。

**Insights 永久记忆**（[ethan/interface/routers/memory.py](file:///Users/jsongo/code/life/ethan-ai/ethan/interface/routers/memory.py)）：

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `memory/insights?limit&offset` | 分页获取永久记忆 |
| GET | `memory/insights/date/{date_str}` | 按日期筛选，`date_str` 格式 `YYYY-MM-DD` |
| POST | `memory/consolidate` | 手动触发夜间统一沉淀 |

**Structured Records 结构化记忆**：

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `memory/records?type&status&domain&limit&offset` | 列表 |
| GET | `memory/records/search?q&limit` | FTS 搜索 |
| GET | `memory/records/{id}` | 详情（含 evidence） |
| GET | `memory/records/{id}/evidence` | 单独取证据 |
| PATCH | `memory/records/{id}` | 编辑 |
| DELETE | `memory/records/{id}` | forget |
| POST | `memory/records/{id}/confirm` | 候选记忆转正 |
| POST | `memory/records/consolidate?target_date` | 手动触发结构化日沉淀 |
| GET | `memory/records/summaries?domain&limit` | 日摘要列表 |
| GET | `memory/records/summaries/{date_str}` | 按日期取摘要 |

**清理过时**：`episodes` 端点后端已退役（返回空），把 `Episode` 数据类标记 `@Deprecated`，但保留方法签名不破坏现有 UI 调用。

### 4. Schedule 补齐

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `schedule` | 创建（cron 或 interval_minutes） |
| POST | `schedule/{id}/trigger` | 手动触发一次 |

参考：[ethan/interface/routers/schedule.py](file:///Users/jsongo/code/life/ethan-ai/ethan/interface/routers/schedule.py)

**Timeline 时间线**（可选，Track 4 用得到）：

| 方法 | 路径 |
|------|------|
| GET | `schedule/timeline-status` |
| POST | `schedule/sync-timelines` |
| POST | `schedule/timeline/{id}/{action}` |
| POST | `schedule/timeline-export` |
| POST | `schedule/timeline-import` |
| POST | `schedule/timeline-validate` |
| POST | `schedule/timeline/{id}/sync-lark` |
| POST | `schedule/timeline/{id}/cleanup-lark` |

### 5. Settings 补齐

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `tool-tiers` | 实时计算 fast/full 两档路由工具集 |
| GET | `fast-rules` | 快捷路由规则 |
| GET | `fast-rules/options` | 可挂载工具 + 已安装技能 |
| PATCH | `fast-rules` | 更新 |
| POST | `settings/knowledge/validate` | 验证知识库后端连通性 |
| GET | `channels/lark/deps-status` | 飞书依赖安装状态 |
| POST | `channels/lark/install-deps` | 手动触发飞书依赖安装 |

参考：[ethan/interface/routers/settings.py](file:///Users/jsongo/code/life/ethan-ai/ethan/interface/routers/settings.py)

### 6. Background Tasks（全新）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `background-tasks` | 列出后台任务 |
| POST | `background-tasks/{id}/stop` | 终止 |

参考：[ethan/interface/routers/background_tasks.py](file:///Users/jsongo/code/life/ethan-ai/ethan/interface/routers/background_tasks.py)（实际位置可能不同，grep 确认）

### 7. Annotations 标注（全新）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `annotations/{message_id}` | 单条消息标注 |
| GET | `annotations/batch?ids=` | 批量取 |
| POST | `annotations` | 创建（type: highlight/underline/strike/comment，4 色） |
| DELETE | `annotations/{anno_id}` | 删除 |

参考：[ethan/interface/routers/annotations.py](file:///Users/jsongo/code/life/ethan-ai/ethan/interface/routers/annotations.py)

### 8. Files / 资产（全新）

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `files/sign` | 批量签发短期签名 URL（10 分钟） |
| GET | `files/download?session_id=&path=` | 下载 deliver_file 交付的文件 |
| GET | `files/deck?session_id=` | 取 PPT 项目 deck.json + pages/*.json |
| GET | `files/asset?session_id=&path=` | 取项目 assets/ 下图片 |
| GET | `images/{filename}` | image_search 下载到 /tmp 的图片 |
| GET | `assets/images/{session_id}/{filename}` | 用户上传的图片 |
| GET | `browser/shot/{name}` | browser 工具截图 |

参考：[ethan/interface/routers/files.py](file:///Users/jsongo/code/life/ethan-ai/ethan/interface/routers/files.py)

### 9. Models 补齐

| 方法 | 路径 | 说明 |
|------|------|------|
| PUT | `models/{provider}/{model_id}` | 更新模型 |

参考：[ethan/interface/routers/models.py](file:///Users/jsongo/code/life/ethan-ai/ethan/interface/routers/models.py)

### 10. 端点路径修复（小坑）

现有 `api-keys` 三个方法用了绝对路径 `/api-keys`，应改为相对 `api-keys`，与 baseUrl 的 `/api` 后缀对齐（参考其他端点写法）。

## Model 类设计建议

把新增 Model 按业务模块分文件存放，避免一个巨型 Models.kt：

```
core/model/src/main/kotlin/com/ethan/agent/core/model/
├── Auth.kt          # 已有
├── Chat.kt          # 已有
├── Sessions.kt      # 已有，补 RegenTitleResponse、SummaryResponse
├── Memory.kt        # 重写：Insights + StructuredRecord + Evidence + Summary
├── Schedule.kt      # 已有，补 CreateScheduleRequest、TimelineStatus、TimelineAction
├── Settings.kt      # 已有，补 ToolTiers、FastRules、FastRuleOptions、KnowledgeValidateRequest
├── BackgroundTask.kt # 新建
├── Annotation.kt    # 新建
├── Files.kt         # 新建：SignRequest、SignResponse、DeckResponse
└── ...
```

如果现有 Model 都在一个文件里，可以保持原结构，但至少新建文件用清晰的命名。

## 验收标准

- [ ] `./gradlew assembleDebug` 编译通过
- [ ] `./gradlew lintDebug` 无新增 error
- [ ] 所有新方法在 `EthanRepository` 上都能被 ViewModel 调用
- [ ] 现有 UI 不破坏（编译通过即可，UI 改动由 Track 2~8 负责）

## 不要做的事

- ❌ 不要改 UI 文件
- ❌ 不要改 build.gradle.kts（依赖版本由 Track 0 控制）
- ❌ 不要删除现有的 episodes 方法（仅标记 deprecated）
- ❌ 不要写单元测试（Track 1 不要求，UI 集成测试由各 UI Track 负责）
