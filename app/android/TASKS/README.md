# Ethan Android 任务拆分总览

本目录是一组**可并行执行**的 Android 端补齐任务，每个 Track 由独立的 AI 助手认领。

## 协作铁律（务必遵守）

### 1. 文件独占原则

每个 Track 都有明确的「独占文件清单」。**只能修改清单内的文件**，严禁触碰其他 Track 的文件，否则会产生合并冲突。

如果某个改动必须跨 Track，请在 PR 描述里提出，由人类协调。

### 2. 依赖关系

```
Track 0 (已完成) ──┐
                   │
Track 1 (网络层) ──┼──→ Track 2~8 并行 ──→ Track 9 (整合) ──→ Track 10 (移动端独有)
                   │
```

- **Track 0**：编译阻塞修复 + CI（已完成，可被合并）
- **Track 1**：网络层补齐，是 Track 2~8 的前置依赖
- **Track 2~8**：UI 模块补齐，**可完全并行**
- **Track 9**：导航整合（依赖 2~8 完成后才合并）
- **Track 10**：移动端独有特性（FCM、Room、生物识别等，跨多目录，最后做）

### 3. PR 规范

- 每个 Track 一个 PR，PR 标题前缀 `[android:track-N]`
- PR 描述里贴本 Track 的 md 路径
- 不要把多个 Track 混在一个 PR

### 4. 代码规范

- Kotlin 2.1 + Jetpack Compose + Material 3 + Hilt
- ViewModel 风格参考 [DocsViewModel.kt](file:///Users/jsongo/code/life/ethan-ai/app/android/app/src/main/kotlin/com/ethan/agent/ui/docs/DocsViewModel.kt)：`MutableStateFlow` + `viewModelScope.launch` + `friendlyError`
- Screen 风格参考 [DocsScreen.kt](file:///Users/jsongo/code/life/ethan-ai/app/android/app/src/main/kotlin/com/ethan/agent/ui/docs/DocsScreen.kt)：`Scaffold` + `TopAppBar` + `ErrorSnackbar`
- API 调用全部走 [EthanRepository.kt](file:///Users/jsongo/code/life/ethan-ai/app/android/app/src/main/kotlin/com/ethan/agent/data/EthanRepository.kt)，不要直接 `Retrofit` 调用
- Model 类放在 `core/model`，序列化用 `@Serializable`

### 5. 后端 API 参考

- OpenAPI 文档：`http://<server>:8900/api/swagger`
- 路由源码：[ethan/interface/api.py](file:///Users/jsongo/code/life/ethan-ai/ethan/interface/api.py) + `ethan/interface/routers/`
- Web 客户端参考：[desktop/src/lib/](file:///Users/jsongo/code/life/ethan-ai/desktop/src/lib/) 下 7 个 `api-*.ts`

### 6. 验证

- 改完后 `./gradlew assembleDebug` 必须编译通过
- `./gradlew lintDebug` 不能新增 error（warning 可接受）
- 不要破坏现有功能

## Track 列表

| Track | 状态 | 优先级 | 独占目录 | 说明文档 |
|-------|------|--------|---------|---------|
| 0 基础设施 | ✅ 已完成 | P0 | `.github/workflows/android.yml`、`app/build.gradle.kts`、`app/proguard-rules.pro`、`ui/logs/` | [track-0-infra.md](./track-0-infra.md) |
| 1 网络层 | ⬜ 待认领 | P0 | `core/network/`、`core/model/`、`data/EthanRepository.kt`、`di/` | [track-1-network.md](./track-1-network.md) |
| 2 Chat UI | ⬜ 待认领 | P1 | `ui/chat/` | [track-2-chat-ui.md](./track-2-chat-ui.md) |
| 3 Memory UI | ⬜ 待认领 | P1 | `ui/memory/` | [track-3-memory-ui.md](./track-3-memory-ui.md) |
| 4 Schedule UI | ⬜ 待认领 | P1 | `ui/schedule/` | [track-4-schedule-ui.md](./track-4-schedule-ui.md) |
| 5 Settings UI | ⬜ 待认领 | P1 | `ui/settings/` | [track-5-settings-ui.md](./track-5-settings-ui.md) |
| 6 Sessions + Knowledge + Skills | ⬜ 待认领 | P2 | `ui/sessions/`、`ui/knowledge/`、`ui/skills/` | [track-6-sessions-knowledge-skills-ui.md](./track-6-sessions-knowledge-skills-ui.md) |
| 7 共享组件 + 主题 | ⬜ 待认领 | P1 | `ui/components/`、`ui/theme/`、`ui/navigation/Screen.kt` | [track-7-shared-components.md](./track-7-shared-components.md) |
| 8 新模块 | ⬜ 待认领 | P2 | `ui/background/`、`ui/ppt/`、`ui/annotations/` | [track-8-new-modules.md](./track-8-new-modules.md) |
| 9 导航整合 | ⬜ 待认领 | P2 | `ui/EthanApp.kt`、`ui/MoreScreen.kt`、`AndroidManifest.xml` | [track-9-integration.md](./track-9-integration.md) |
| 10 移动端独有 | ⬜ 待认领 | P3 | 跨多目录 | [track-10-mobile-native.md](./track-10-mobile-native.md) |

## 整体目标

让 Android app 从「能编译但功能严重滞后」升级到「与 Web/Desktop 端功能对齐」，并具备：

- Chat：Stop/Resume/Inject、annotations、A2UI 卡片、Mermaid
- Memory：Insights + Structured Records + Consolidate
- Schedule：Trigger now + Timeline
- 全新模块：Background Tasks、PPT 预览
- 主题系统：5 主题切换
- CI：path-filtered 自动打包
