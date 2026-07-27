# Track 0: 基础设施（已完成）

> 状态：✅ 已完成 · 优先级：P0

## 目标

修复 Android app 的编译阻塞，配置签名和 ProGuard 规则，新建 CI workflow。

## 独占文件清单

- [.github/workflows/android.yml](file:///Users/jsongo/code/life/ethan-ai/.github/workflows/android.yml) — Android CI workflow
- [app/android/app/build.gradle.kts](file:///Users/jsongo/code/life/ethan-ai/app/android/app/build.gradle.kts) — 签名配置
- [app/android/app/proguard-rules.pro](file:///Users/jsongo/code/life/ethan-ai/app/android/app/proguard-rules.pro) — ProGuard keep 规则
- [app/android/app/src/main/kotlin/com/ethan/agent/ui/logs/LogsViewModel.kt](file:///Users/jsongo/code/life/ethan-ai/app/android/app/src/main/kotlin/com/ethan/agent/ui/logs/LogsViewModel.kt) — 新建
- [app/android/app/src/main/kotlin/com/ethan/agent/ui/logs/LogsScreen.kt](file:///Users/jsongo/code/life/ethan-ai/app/android/app/src/main/kotlin/com/ethan/agent/ui/logs/LogsScreen.kt) — 新建

## 已完成的工作

### 1. 补齐 Logs 模块（修复编译失败）

[EthanApp.kt](file:///Users/jsongo/code/life/ethan-ai/app/android/app/src/main/kotlin/com/ethan/agent/ui/EthanApp.kt) 引用了 `ui/logs/LogsScreen` 和 `LogsViewModel`，但 `ui/logs/` 目录整个不存在。

补齐内容：
- `LogsViewModel`：支持 backend/frontend 类型切换、关键字过滤（300ms debounce）、刷新
- `LogsScreen`：TopAppBar + FilterChip 类型选择 + OutlinedTextField 关键字 + 等宽字体日志展示

### 2. 签名配置

在 `app/build.gradle.kts` 加 `signingConfigs.release`，从环境变量或 `~/.gradle/gradle.properties` 读取：
- `ANDROID_STORE_FILE`
- `ANDROID_STORE_PASSWORD`
- `ANDROID_KEY_ALIAS`
- `ANDROID_KEY_PASSWORD`

仅当签名信息可用时才挂到 release buildType，否则回退 debug key（CI 无签名环境时也能跑通）。

### 3. ProGuard 规则

补全 keep 规则：
- Hilt / Dagger 2（反射注入）
- Retrofit 2（动态代理 + 注解扫描）
- OkHttp / OkIO
- kotlinx.serialization（Serializer 反射）
- 项目自身 `com.ethan.agent.core.model.**` 模型类

### 4. Android CI workflow

[.github/workflows/android.yml](file:///Users/jsongo/code/life/ethan-ai/.github/workflows/android.yml) 设计：

**触发条件**（path-filtered）：
- `push` 到 main，仅 `app/android/**` 或本 workflow 文件改动时
- `push` tag `v*`：与 desktop/pypi/docker 发布并行
- `pull_request`：仅 `app/android/**` 改动时
- `workflow_dispatch`：手动触发

**Job 结构**：
- `check-changes`：通过 git diff 检测自上一个 tag 以来 `app/android/` 是否变化
- `build`：JDK 17 + Android SDK 35 + Gradle cache → lint + test + assembleDebug → 上传 APK artifact
  - tag 触发时额外：注入签名 keystore → assembleRelease → 上传到 GitHub Release

**签名密钥**（GitHub Secrets，仅 tag 触发需要）：
- `ANDROID_KEYSTORE_BASE64`：base64 编码的 keystore
- `ANDROID_STORE_PASSWORD`、`ANDROID_KEY_ALIAS`、`ANDROID_KEY_PASSWORD`

## 验证

```bash
cd app/android
export ANDROID_HOME=~/Library/Android/sdk
./gradlew assembleDebug
```

应能产出 `app/build/outputs/apk/debug/app-debug.apk`。

## 后续 CI 待办

- 在 GitHub 仓库 Settings → Secrets 中添加 4 个签名 secret（人类操作）
- 在 `auto-bump-version.yml` 中追加同步 `app/android/app/build.gradle.kts` 的 versionCode/versionName（待 Track 1 完成后做）
