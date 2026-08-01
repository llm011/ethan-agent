# Ethan KMP 化路线图（Android → 共享 → iOS）

> 目标：把现有 Android app 里用 Kotlin 写的业务逻辑，通过 Kotlin Multiplatform (KMP) 抽成
> 跨平台共享代码，供未来的 iOS app 复用，最终两端共享数据/网络/仓库/（可选）ViewModel 层。
>
> **执行原则：一期一期做，每期独立可合并、Android 零回归。**

## 现状分析（2026-08，已核对）

分层（已天然适合 KMP）：
- `:app` — Compose UI · 15 Screen · 14 ViewModel · Hilt DI（Android 专有）
- `:core:network` — Retrofit + OkHttp + 手写 SSE（3 文件，99 端点）
- `:core:model` — 11 个纯 `@Serializable` 数据类 + 工具（954 行）
- `:core:datastore` — androidx.datastore（1 文件）
- `EthanRepository`（825 行，在 :app/data 下）— 业务编排核心

版本栈全部 KMP 兼容：Kotlin 2.1.10 / AGP 8.8.2 / coroutines 1.10.1 / serialization 1.8.0。
`androidx.lifecycle.ViewModel` 已是 multiplatform。14 个 ViewModel **零 Android API**（已 grep 确认），但都靠 Hilt。

五个必须直面的改造点：
1. Retrofit → Ktor Client（Retrofit 无 iOS target）
2. 手写 SSE（`ChatSseClient` 用 `BufferedReader/InputStreamReader`）→ Ktor SSE
3. Hilt → Koin（仅 Phase 2 共享 ViewModel 时）
4. `ServerUrlUtils` 的 `java.net.URI` → 多平台 URL 解析（唯一一处 JVM 依赖）
5. iOS 工程从零搭（现无任何 Xcode 工程）

**环境限制**：本机无 Xcode / iOS SDK。KMP 化 + 编译 iOS klib 可做（Kotlin/Native 编译器 Gradle 自动下载）；产出/验证 XCFramework、跑 iOS app 需用户装 Xcode。

---

## 三期路线

### Phase 1 · 共享 数据 + 网络 + 仓库层（进行中）
把 `core:model` / `core:network`(换 Ktor) / `core:datastore`(换 KMP DataStore) / `EthanRepository`
迁进 `commonMain`，产出可供 iOS 用的共享库。Android 侧行为不变。
**投入产出比最高：约 2500+ 行业务逻辑一次跨端复用。**

详细步骤见下「Phase 1 执行清单」。

### Phase 2 · 共享 ViewModel
Hilt → Koin，14 个 ViewModel 迁 `commonMain`。iOS 的 SwiftUI 直接观察同一套 StateFlow。

### Phase 3（可选）· Compose Multiplatform 共享 UI
连界面共用。收益最大风险最大，前两期跑顺再评估。

---

## Phase 1 执行清单

分支：从干净 `origin/main` 新开 `feature/kmp-phase1-shared-core`（不与 Track 10 混）。

1. **根 build / settings**：加 `kotlin-multiplatform`、`ktor`、KMP `datastore` 到 libs.versions.toml。
2. **`core:model` KMP 化**：改 `com.android.library`+kotlin.android → `kotlin("multiplatform")`+android target；
   源码 `src/main/kotlin` → `src/commonMain/kotlin`；`ServerUrlUtils` 的 `java.net.URI` 换成纯 Kotlin 解析
   （或 expect/actual）。iosX64/iosArm64/iosSimulatorArm64 三 target。
3. **`core:network` 换 Ktor**：`EthanApiService`（99 端点）用 Ktor Client 重写为 `commonMain` 实现；
   `NetworkFactory` 的 OkHttp → Ktor（Android engine + Darwin engine）；`ChatSseClient` 用 Ktor SSE 重写；
   `BuildConfig.DEBUG` 日志开关换 KMP 方式。
4. **`core:datastore` KMP 化**：androidx.datastore-core（KMP 版）+ okio，`AppConfigStore` 迁 commonMain，
   路径用 expect/actual 提供。
5. **`EthanRepository` 迁共享**：⏸ **推迟到 Phase 2**。Repository 仍带 Hilt(`@Inject`/`@Singleton`)、
   `java.io.File`、`LocalCache(Context)`，把它迁 commonMain 势必先拆 Hilt——而 Hilt→Koin 正是 Phase 2 的核心。
   为保持每期边界清晰，Phase 1 只把它**适配**到共享 Ktor 层（去 refreshApi/Retrofit 耦合），留在 `:app`。
   上传参数已平台无关化（ByteArray+filename+mime），`HttpException` 已换成领域 `ApiException`。
6. **`:app` 适配**：✅ `AppModule`(Hilt) 注入共享层 factory（`NetworkFactory.createApiService(baseUrlProvider, tokenProvider)`）；
   新增 `ServerUrlCache` 供 Ktor 同步取 origin；ViewModel 不动（仍 Hilt）。
7. **验证**：
   - ✅ Android：`:app:assembleDebug` 通过（core:model/network/datastore 全 KMP 化后）。装模拟器冒烟待做。
   - ✅ iOS：`:core:model` / `:core:network` / `:core:datastore` 三个 `compileKotlinIosSimulatorArm64` 均编到 klib 通过（无 Xcode）。
   - ⏳ XCFramework 产出 + iOS app 接入：需用户装 Xcode，Phase 2 做。

## 进度

- [x] Phase 1（共享 core：model + network(Ktor) + datastore）— **基本完成**
      - 三层已在 commonMain 且两端(android + iosSimulatorArm64 klib)编译通过；Android assembleDebug 零回归
      - 剩余：模拟器冒烟；EthanRepository/LocalCache 迁共享随 Phase 2 一起做
- [ ] Phase 2（共享 ViewModel：Hilt→Koin + Repository/LocalCache 迁 commonMain）
- [ ] Phase 3（可选，共享 UI）
