# Track 10: 移动端独有特性

> 状态：⬜ 待认领 · 优先级：P3 · 前置依赖：Track 9 已合并

## 目标

补齐 PRD §5 中标记为「未实现」的移动端独有特性。

## ⚠️ 跨多目录任务

本 Track 涉及多个目录，**必须在 Track 2~9 全部合并后才能开始**，否则会产生大量冲突。

涉及文件（不能严格独占，需要协调）：
- `app/android/app/src/main/AndroidManifest.xml`（与 Track 9 协调，Track 9 已加权限）
- `app/android/app/build.gradle.kts`（加新依赖）
- `app/android/gradle/libs.versions.toml`（加新库版本）
- `app/android/app/src/main/kotlin/com/ethan/agent/EthanApplication.kt`
- `app/android/app/src/main/kotlin/com/ethan/agent/MainActivity.kt`
- 各 UI 模块（按需小改）

## 任务清单

### 1. 推送通知（FCM）P2

需求：
- 接入 Firebase Cloud Messaging
- 后端在定时任务完成、心跳结果、长任务结束时通过 FCM 推送
- App 接收推送后：
  - 显示系统通知（带标题、内容、目标 sessionId）
  - 点击通知跳转对应 Chat 会话
- 需要后端配合：在 `ethan/interface/routers/notifications.py` 加注册 token 端点（如未实现）

涉及改动：
- `app/build.gradle.kts`：加 `firebase-messaging` 依赖
- `libs.versions.toml`：加版本
- `EthanApplication.kt`：初始化 Firebase
- 新建 `com.ethan.agent.push.PushService` 继承 `FirebaseMessagingService`
- `AndroidManifest.xml`：注册 service + POST_NOTIFICATIONS 权限
- 后端：需要新增 `/api/push/register` 端点存储 token（**需要单独和后端 owner 协调**）

### 2. 离线缓存（Room）P2

需求：
- 用 Room 数据库缓存：
  - 会话列表（最近 50 条）
  - 当前会话的消息（最近 3 天）
  - 知识库条目（最近访问的 20 条）
- 网络可用时拉取最新，网络断开时显示缓存
- 在 Settings 加「清空缓存」按钮

涉及改动：
- `app/build.gradle.kts`：加 Room 依赖
- `libs.versions.toml`：加版本
- 新建 `com.ethan.agent.data.local.AppDatabase`
- 新建 `com.ethan.agent.data.local.SessionDao`、`MessageDao`、`KnowledgeDao`
- 修改 `EthanRepository`：在每次 API 调用后写缓存，失败时回退缓存（**与 Track 1 协调**）
- 新建 `com.ethan.agent.data.NetworkMonitor`：监听网络状态

### 3. 生物识别锁 P2

需求：
- App 启动时若开启了锁，弹 BiometricPrompt 验证
- 验证通过后才进入主界面
- 在 Settings → General 加「应用锁」开关
- 开启时调用 `BiometricPrompt` 注册

涉及改动：
- `app/build.gradle.kts`：加 `androidx.biometric:biometric` 依赖
- `libs.versions.toml`：加版本
- 新建 `com.ethan.agent.auth.BiometricLockManager`
- `MainActivity.kt`：在 `onCreate` 中检查锁状态
- `SettingsScreen.kt`：加开关（与 Track 5 协调，或本 Track 直接在 Settings 加）
- `AndroidManifest.xml`：`USE_BIOMETRIC` 权限（Track 9 已加）

### 4. 平板双栏布局 P2

需求：
- 用 `WindowSizeClass` 检测屏幕宽度
- 折叠屏 / 平板（宽度 ≥ 600dp）：
  - Chat 页面：左侧会话列表 + 右侧对话
  - Memory 页面：左侧条目列表 + 右侧详情
  - Knowledge 页面：已有双栏，优化即可
  - Schedule 页面：左侧任务列表 + 右侧详情
- 手机（宽度 < 600dp）：保持当前单栏

涉及改动：
- `app/build.gradle.kts`：加 `androidx.compose.material3:material3-window-size-class` 依赖
- 各 UI 模块：按需改成 `ListDetailPaneScaffold` 或手动两栏布局
  - 与 Track 2~6 协调，或本 Track 在他们完成后做增量改进

### 5. 前台服务（SSE 保活）P2

需求：
- 当有活跃的 SSE 流时，启动前台服务保活
- 显示通知「Ethan 正在生成回复...」
- 流结束后停止前台服务

涉及改动：
- 新建 `com.ethan.agent.service.ChatStreamService`
- `AndroidManifest.xml`：注册 service + FOREGROUND_SERVICE 权限（Track 9 已加）
- `ChatViewModel`：在 stream 开始时 startForegroundService，结束时 stopService（与 Track 2 协调）

### 6. 应用内更新 P3

需求：
- 启动时检查 GitHub Release 最新版本
- 如果有新版本，弹 dialog 提示更新
- 提供「下载 APK」按钮，下载完成后调起安装 Intent

涉及改动：
- 新建 `com.ethan.agent.update.UpdateChecker`
- 调 GitHub API：`https://api.github.com/repos/llm011/ethan-agent/releases/latest`
- `MainActivity.kt`：在 `onCreate` 中检查
- 需要 `INTERNET` 和 `REQUEST_INSTALL_PACKAGES` 权限

### 7. 分享到 Ethan P3

需求：
- 在系统分享菜单中注册 Ethan
- 用户在其他 App 中选「分享到 Ethan」时：
  - 如果是文字：直接发送到当前会话或新建会话
  - 如果是图片：上传后发送
  - 如果是文件：上传后发送

涉及改动：
- `AndroidManifest.xml`：MainActivity 加 `<intent-filter>` 处理 `ACTION_SEND`
- `MainActivity.kt`：处理 intent，提取 shared 内容
- 新建 `com.ethan.agent.share.ShareReceiver`

## 后端协作需求

本 Track 中以下任务需要后端配合：

| 任务 | 后端改动 |
|------|---------|
| 推送通知 | 新增 `/api/push/register` 端点存储 FCM token；在 schedule / heartbeat / background_task 完成时触发推送 |
| 离线缓存 | 无（纯前端） |
| 生物识别 | 无（纯前端） |
| 平板双栏 | 无（纯前端） |
| 前台服务 | 无（纯前端） |
| 应用更新 | 无（用 GitHub API） |
| 分享到 Ethan | 无（纯前端） |

建议先做不需要后端配合的任务（2/3/4/5/6/7），推送通知（1）等后端 ready 再做。

## 验收标准

每完成一个子任务都应：
- [ ] 单独 PR，PR 标题 `[android:track-10.X]`
- [ ] 编译通过、lint 无 error
- [ ] 不破坏现有功能

## 不要做的事

- ❌ 不要一次性做完所有子任务（每个子任务独立 PR）
- ❌ 不要在没有后端配合的情况下硬上 FCM 推送
- ❌ 不要改 `core/network/`（如需新 API，由 Track 1 增量加）
