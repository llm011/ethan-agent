# Track 9: 导航整合

> 状态：⬜ 待认领 · 优先级：P2 · 前置依赖：Track 2~8 全部合并

## 目标

在 `EthanApp.kt` 注册 Track 7/8 新增的路由，在 `MoreScreen.kt` 加入口，更新 `AndroidManifest.xml` 加权限。

## 独占文件清单（只能改这些）

- `app/android/app/src/main/kotlin/com/ethan/agent/ui/EthanApp.kt`
- `app/android/app/src/main/kotlin/com/ethan/agent/ui/MoreScreen.kt`
- `app/android/app/src/main/AndroidManifest.xml`

**严禁触碰**：
- 任何具体 UI 模块
- `ui/navigation/Screen.kt`（Track 7 已加路由声明，本 Track 只在 NavHost 注册）
- `data/EthanRepository.kt`、`core/`

## 任务清单

### 1. 注册新路由（P0）

在 [EthanApp.kt](file:///Users/jsongo/code/life/ethan-ai/app/android/app/src/main/kotlin/com/ethan/agent/ui/EthanApp.kt) 的 `NavHost` 中注册：

```kotlin
// Background Tasks
composable(Screen.BackgroundTasks.route) {
    val vm: BackgroundTasksViewModel = hiltViewModel()
    val state by vm.state.collectAsState()
    BackgroundTasksScreen(
        state = state,
        onRefresh = vm::load,
        onStop = vm::stopTask,
        onOpenChat = { sessionId -> /* navController.navigate */ },
        onClearError = vm::clearError,
    )
}

// PPT Preview
composable(
    route = Screen.PptPreview.route,
    arguments = listOf(navArgument("sessionId") { type = NavType.StringType }),
) {
    val vm: PptPreviewViewModel = hiltViewModel()
    val state by vm.state.collectAsState()
    PptPreviewScreen(state = state, onPageChange = vm::setPage, onClearError = vm::clearError)
}

// Annotations
composable(
    route = Screen.Annotations.route,
    arguments = listOf(navArgument("sessionId") { type = NavType.StringType }),
) {
    val vm: AnnotationsViewModel = hiltViewModel()
    val state by vm.state.collectAsState()
    AnnotationsScreen(state = state, onDelete = vm::delete, onClearError = vm::clearError)
}
```

需要补 import：
- `com.ethan.agent.ui.background.BackgroundTasksScreen`、`BackgroundTasksViewModel`
- `com.ethan.agent.ui.ppt.PptPreviewScreen`、`PptPreviewViewModel`
- `com.ethan.agent.ui.annotations.AnnotationsScreen`、`AnnotationsViewModel`

### 2. MoreScreen 加入口（P0）

在 [MoreScreen.kt](file:///Users/jsongo/code/life/ethan-ai/app/android/app/src/main/kotlin/com/ethan/agent/ui/MoreScreen.kt) 中扩展 `moreMenuItems`：

方案 A（推荐）：直接在 `Screen.kt` 的 `moreMenuItems` 列表里追加（但 `Screen.kt` 由 Track 7 管，需要协调）

方案 B：在 `MoreScreen` 本地维护一个列表，覆盖 `moreMenuItems`：

```kotlin
val extendedMoreItems = moreMenuItems + listOf(
    Screen.BackgroundTasks,
)
```

推荐方案 B，避免改 `Screen.kt`。

### 3. AndroidManifest.xml 权限补齐（P0）

需要补的权限：

```xml
<!-- 生物识别（Track 10 用，但先声明） -->
<uses-permission android:name="android.permission.USE_BIOMETRIC" />

<!-- 推送通知（Track 10 用） -->
<uses-permission android:name="android.permission.POST_NOTIFICATIONS" />

<!-- 前台服务（Track 10 用，SSE 长连接保活） -->
<uses-permission android:name="android.permission.FOREGROUND_SERVICE" />

<!-- 保存图片到相册（Lightbox 长按保存，Track 7 用） -->
<uses-permission android:name="android.permission.WRITE_EXTERNAL_STORAGE"
    android:maxSdkVersion="28" /> <!-- Android 10+ 用 MediaStore -->
```

### 4. AndroidManifest.xml 网络安全（P1）

当前 `network_security_config.xml` 全局允许明文流量，建议收紧为按域名白名单：

```xml
<network-security-config>
    <base-config cleartextTrafficPermitted="false" />
    <domain-config cleartextTrafficPermitted="true">
        <!-- 允许局域网 IP 明文（NAS 部署场景） -->
        <domain includeSubdomains="true">192.168.0.0/16</domain>
        <domain includeSubdomains="true">10.0.0.0/8</domain>
        <domain includeSubdomains="true">172.16.0.0/12</domain>
        <domain includeSubdomains="true">localhost</domain>
        <domain includeSubdomains="true">127.0.0.1</domain>
    </domain-config>
</network-security-config>
```

注意：Android 的 `domain-config` 不支持 CIDR，需要列出具体 IP 段或单独 IP。可以先保持全局允许，加 TODO 注释。

### 5. 应用图标优化（P2）

当前只有 `mipmap-anydpi-v26/` 下的自适应图标，没有 PNG 位图 fallback。

由于 `minSdk = 26`，技术上不需要 fallback。但建议补一套：
- `mipmap-mdpi/ic_launcher.png` (48×48)
- `mipmap-hdpi/ic_launcher.png` (72×72)
- `mipmap-xhdpi/ic_launcher.png` (96×96)
- `mipmap-xxhdpi/ic_launcher.png` (144×144)
- `mipmap-xxxhdpi/ic_launcher.png` (192×192)

可以用 Android Studio 的 Image Asset Studio 生成，或用在线工具。本任务可选。

### 6. applicationId 和版本号同步（P1）

如果 `auto-bump-version.yml` 已经扩展为同步 Android 版本号（需在 Track 0 之后单独 PR 改 auto-bump），本 Track 检查 `app/build.gradle.kts` 的 `versionName` 是否与 `pyproject.toml` 一致。

如果不一致，需要协调：要么手动改，要么让 `auto-bump-version.yml` 自动同步（推荐，需改 auto-bump workflow）。

## 验收标准

- [ ] 点击 MoreScreen 中的「后台任务」能跳转到 BackgroundTasksScreen
- [ ] 从 Schedule 或 BackgroundTasks 跳转 PptPreview 能正常加载
- [ ] 新权限已声明
- [ ] 编译通过、lint 无 error
- [ ] 现有路由（chat/sessions/memory/...）不破坏

## 不要做的事

- ❌ 不要实现具体的 Screen 内容（Track 8 已做）
- ❌ 不要改 `Screen.kt` 路由声明（Track 7 已做）
- ❌ 不要改 `auto-bump-version.yml`（如需改，单独开 PR）
- ❌ 不要破坏底部导航（4 个 Tab：Chat/Sessions/More/Settings）
