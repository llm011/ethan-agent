package com.ethan.agent.shared.di

import com.ethan.agent.core.datastore.AppConfigStore
import com.ethan.agent.core.network.ChatSseClient
import com.ethan.agent.core.network.EthanApiService
import com.ethan.agent.core.network.NetworkFactory
import com.ethan.agent.shared.AuthTokenCache
import com.ethan.agent.shared.EthanRepository
import com.ethan.agent.shared.LocalCache
import com.ethan.agent.shared.ServerUrlCache
import com.ethan.agent.shared.viewmodel.*
import org.koin.core.module.Module
import org.koin.core.module.dsl.viewModel
import org.koin.core.module.dsl.viewModelOf
import org.koin.dsl.module

/**
 * Koin DI 模块：Repository + 缓存 + 全部 ViewModel。
 * 平台侧（Android/iOS）额外提供 AppConfigStore 和 AppUpdater 的 actual 实现。
 */
fun sharedModule(): Module = module {
    single { AuthTokenCache(get()) }
    single { ServerUrlCache(get()) }
    single { LocalCache() }
    // 图解析（非参数化）：Koin 自动从容器取 AuthTokenCache，避免 get() 无参时抛异常
    single<() -> String> { get<AuthTokenCache>()::get }
    single { NetworkFactory.createApiService(get<ServerUrlCache>()::get, get()) }
    single { NetworkFactory.createSseClient(get<ServerUrlCache>()::get, get()) }
    single { EthanRepository(get(), get(), get(), get(), get()) }

    // ViewModels
    viewModelOf(::AuthViewModel)
    viewModel { params -> ChatViewModel(get(), params.getOrNull<String>()) }
    viewModelOf(::SettingsViewModel)
    viewModelOf(::SkillsViewModel)
    viewModelOf(::ScheduleViewModel)
    viewModelOf(::AgendaViewModel)
    viewModelOf(::SessionsViewModel)
    viewModel { params -> PptPreviewViewModel(get(), params.getOrNull<String>() ?: "") }
    viewModelOf(::MemoryViewModel)
    viewModelOf(::LogsViewModel)
    viewModel { params -> DocsViewModel(get(), params.getOrNull<String>()) }
    viewModelOf(::KnowledgeViewModel)
    viewModelOf(::BackgroundTasksViewModel)
    viewModelOf(::AnnotationsViewModel)
    viewModelOf(::UpdateViewModel)
}
