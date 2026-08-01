package com.ethan.agent.shared

import com.ethan.agent.shared.viewmodel.AnnotationsViewModel
import com.ethan.agent.shared.viewmodel.AuthViewModel
import com.ethan.agent.shared.viewmodel.BackgroundTasksViewModel
import com.ethan.agent.shared.viewmodel.ChatViewModel
import com.ethan.agent.shared.viewmodel.DocsViewModel
import com.ethan.agent.shared.viewmodel.KnowledgeViewModel
import com.ethan.agent.shared.viewmodel.LogsViewModel
import com.ethan.agent.shared.viewmodel.MemoryViewModel
import com.ethan.agent.shared.viewmodel.PptPreviewViewModel
import com.ethan.agent.shared.viewmodel.ScheduleViewModel
import com.ethan.agent.shared.viewmodel.SessionsViewModel
import com.ethan.agent.shared.viewmodel.SettingsViewModel
import com.ethan.agent.shared.viewmodel.SkillsViewModel
import com.ethan.agent.shared.viewmodel.UpdateViewModel
import org.koin.core.parameter.parametersOf
import org.koin.mp.KoinPlatform

/**
 * iOS 端 ViewModel 获取入口。
 *
 * Swift 调不了 Android 的 `koinViewModel()` Compose 扩展，这里用顶层函数封装
 * `KoinPlatform.getKoin().get()`，让 Swift 直接拿到 VM 实例，配合 SwiftUI 的
 * `@StateObject` 持有（Koin 的 viewModel DSL 在非 Android 平台按 factory 语义
 * 工作，每次 get 返回新实例，符合 SwiftUI 期望首次创建后持有的模型）。
 *
 * 用法（Swift）：
 * ```swift
 * @StateObject private var viewModel = IosViewModels.sharedChatViewModel(sessionId: "xxx")
 * let state = StateFlowWrapper(flow: viewModel.state)
 * ```
 *
 * 必须先调 [initKoin] 完成 Koin 启动后再取 VM。
 */
object IosViewModels {

    // ── 无参 ViewModel（11 个）──

    fun authViewModel(): AuthViewModel = KoinPlatform.getKoin().get()
    fun settingsViewModel(): SettingsViewModel = KoinPlatform.getKoin().get()
    fun skillsViewModel(): SkillsViewModel = KoinPlatform.getKoin().get()
    fun scheduleViewModel(): ScheduleViewModel = KoinPlatform.getKoin().get()
    fun sessionsViewModel(): SessionsViewModel = KoinPlatform.getKoin().get()
    fun memoryViewModel(): MemoryViewModel = KoinPlatform.getKoin().get()
    fun logsViewModel(): LogsViewModel = KoinPlatform.getKoin().get()
    fun knowledgeViewModel(): KnowledgeViewModel = KoinPlatform.getKoin().get()
    fun backgroundTasksViewModel(): BackgroundTasksViewModel = KoinPlatform.getKoin().get()
    fun annotationsViewModel(): AnnotationsViewModel = KoinPlatform.getKoin().get()
    fun updateViewModel(): UpdateViewModel = KoinPlatform.getKoin().get()

    // ── 带参 ViewModel（3 个）──

    /** @param sessionId 会话 ID，null 表示新建会话 */
    fun chatViewModel(sessionId: String?): ChatViewModel =
        KoinPlatform.getKoin().get { parametersOf(sessionId) }

    /** @param docId 文档 ID */
    fun pptPreviewViewModel(docId: String): PptPreviewViewModel =
        KoinPlatform.getKoin().get { parametersOf(docId) }

    /** @param param 文档参数 */
    fun docsViewModel(param: String?): DocsViewModel =
        KoinPlatform.getKoin().get { parametersOf(param) }
}
