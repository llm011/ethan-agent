package com.ethan.agent.ui

import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.animation.AnimatedContentTransitionScope
import androidx.compose.animation.core.tween
import androidx.compose.material3.DrawerValue
import androidx.compose.material3.ModalNavigationDrawer
import androidx.compose.material3.Scaffold
import androidx.compose.material3.rememberDrawerState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.foundation.layout.padding
import androidx.compose.ui.Modifier
import org.koin.androidx.compose.koinViewModel
import org.koin.core.parameter.parametersOf
import androidx.navigation.NavBackStackEntry
import androidx.navigation.NavType
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.rememberNavController
import androidx.navigation.navArgument
import com.ethan.agent.core.model.AgendaEvent
import com.ethan.agent.shared.ChatLauncherBus
import com.ethan.agent.shared.viewmodel.AgendaViewModel
import com.ethan.agent.shared.viewmodel.AuthUiState
import com.ethan.agent.shared.viewmodel.AuthViewModel
import com.ethan.agent.ui.agenda.AgendaScreen
import com.ethan.agent.ui.auth.LoginScreen
import com.ethan.agent.ui.chat.ChatScreen
import com.ethan.agent.shared.viewmodel.ChatViewModel
import com.ethan.agent.ui.docs.DocsScreen
import com.ethan.agent.shared.viewmodel.DocsViewModel
import com.ethan.agent.ui.knowledge.KnowledgeScreen
import com.ethan.agent.shared.viewmodel.KnowledgeViewModel
import com.ethan.agent.ui.logs.LogsScreen
import com.ethan.agent.shared.viewmodel.LogsViewModel
import com.ethan.agent.ui.memory.MemoryScreen
import com.ethan.agent.shared.viewmodel.MemoryViewModel
import com.ethan.agent.ui.navigation.Screen
import com.ethan.agent.ui.schedule.ScheduleScreen
import com.ethan.agent.shared.viewmodel.ScheduleViewModel
import com.ethan.agent.ui.sessions.SessionsScreen
import com.ethan.agent.shared.viewmodel.SessionsViewModel
import com.ethan.agent.ui.settings.SettingsScreen
import com.ethan.agent.shared.viewmodel.SettingsViewModel
import com.ethan.agent.ui.skills.SkillsScreen
import com.ethan.agent.shared.viewmodel.SkillsViewModel
import com.ethan.agent.shared.viewmodel.UpdateViewModel
import com.ethan.agent.shared.viewmodel.BackgroundTasksViewModel
import com.ethan.agent.shared.viewmodel.PptPreviewViewModel
import com.ethan.agent.shared.viewmodel.AnnotationsViewModel
import com.ethan.agent.ui.components.AppDrawerContent
import com.ethan.agent.ui.components.LoadingBox
import com.ethan.agent.ui.components.UpdateDialog
import kotlinx.coroutines.launch

private val slideIn: AnimatedContentTransitionScope<NavBackStackEntry>.() -> androidx.compose.animation.EnterTransition = {
    slideIntoContainer(
        towards = AnimatedContentTransitionScope.SlideDirection.Left,
        animationSpec = tween(300),
    )
}
private val slideOut: AnimatedContentTransitionScope<NavBackStackEntry>.() -> androidx.compose.animation.ExitTransition = {
    slideOutOfContainer(
        towards = AnimatedContentTransitionScope.SlideDirection.Left,
        animationSpec = tween(300),
    )
}
private val popSlideIn: AnimatedContentTransitionScope<NavBackStackEntry>.() -> androidx.compose.animation.EnterTransition = {
    slideIntoContainer(
        towards = AnimatedContentTransitionScope.SlideDirection.Right,
        animationSpec = tween(300),
    )
}
private val popSlideOut: AnimatedContentTransitionScope<NavBackStackEntry>.() -> androidx.compose.animation.ExitTransition = {
    slideOutOfContainer(
        towards = AnimatedContentTransitionScope.SlideDirection.Right,
        animationSpec = tween(300),
    )
}

@Composable
fun EthanApp(authViewModel: AuthViewModel) {
    val authState by authViewModel.state.collectAsState()

    when {
        authState.isLoading -> LoadingBox()
        !authState.isAuthenticated -> LoginContent(authState, authViewModel)
        else -> MainContent(authViewModel)
    }
}

@Composable
private fun LoginContent(state: AuthUiState, viewModel: AuthViewModel) {
    LoginScreen(
        state = state,
        onLogin = viewModel::login,
    )
}

@Composable
private fun MainContent(authViewModel: AuthViewModel) {
    val navController = rememberNavController()
    val updateViewModel: UpdateViewModel = koinViewModel()
    val drawerState = rememberDrawerState(DrawerValue.Closed)
    val scope = rememberCoroutineScope()

    // Sessions data for drawer
    val sessionsVm: SessionsViewModel = koinViewModel()
    val sessionsState by sessionsVm.state.collectAsState()

    ModalNavigationDrawer(
        drawerState = drawerState,
        gesturesEnabled = true,
        drawerContent = {
            AppDrawerContent(
                sessions = sessionsState.sessions,
                unreadSessionIds = sessionsState.unreadSessionIds,
                onNewChat = {
                    // 开新会话。两个坑：
                    //  1. `launchSingleTop = true` 在这里**不能**用 —— Chat 的路由是
                    //     `chat?sessionId={sessionId}`，去重是按 route 模板比的，所以
                    //     只要当前已经在 Chat 页（无论带不带 sessionId），这次导航会被
                    //     静默丢弃，用户看到的就是「点了新建对话没反应，还是当前会话」。
                    //  2. 直接 navigate 会不断往回退栈里压 chat 条目，来回点几次后
                    //     返回键要按很多下。所以先 popUpTo 掉已有的 chat，再压新的。
                    navController.navigate("chat") {
                        popUpTo("chat?sessionId={sessionId}") { inclusive = true }
                    }
                },
                onSessionClick = { id ->
                    sessionsVm.markRead(id)
                    navController.navigate(Screen.Chat.createRoute(id))
                },
                onSearchClick = {
                    scope.launch { drawerState.close() }
                    navController.navigate(Screen.Sessions.route) {
                        launchSingleTop = true
                    }
                },
                onNavigate = { route ->
                    navController.navigate(route) {
                        launchSingleTop = true
                    }
                },
                onClose = { scope.launch { drawerState.close() } },
            )
        },
    ) {
        // contentWindowInsets 必须归零：状态栏 inset 由各页面自己的 EthanTopBar
        // （statusBarsPadding）负责。这里再算一遍的话，同一个状态栏高度会被叠两次，
        // 实测顶栏文字落到 272px（多出约 74dp 的空白带）—— 就是用户说的
        // 「header 离顶部那么远」。既然各页自己管，这个外层 Scaffold 就一个 inset
        // 都不该加，innerPadding 也就不需要了。
        //
        // lint 的 UnusedMaterial3ScaffoldPaddingParameter 在这里是误报：它假设
        // contentPadding 里带着 app bar 的高度，但本 Scaffold 既没有 appBar 也把
        // contentWindowInsets 归了零，innerPadding 恒为 0，忽略它是刻意的。
        @Suppress("UnusedMaterial3ScaffoldPaddingParameter")
        Scaffold(contentWindowInsets = WindowInsets(0, 0, 0, 0)) { _ ->
            NavHost(
                navController = navController,
                startDestination = "chat",
                enterTransition = slideIn,
                exitTransition = slideOut,
                popEnterTransition = popSlideIn,
                popExitTransition = popSlideOut,
                modifier = Modifier.fillMaxSize(),
            ) {
            composable(
                route = "chat?sessionId={sessionId}",
                arguments = listOf(navArgument("sessionId") { type = NavType.StringType; nullable = true; defaultValue = null }),
            ) {
                val vm: ChatViewModel = koinViewModel { parametersOf(it.arguments?.getString("sessionId")) }
                val state by vm.state.collectAsState()
                // 从其他页（如 Agenda「拆解该安排」）带过来的自动发送 prompt：该 entry 首次组合时一次性消费
                val launchPrompt = remember { ChatLauncherBus.take() }
                LaunchedEffect(launchPrompt) {
                    if (launchPrompt != null) vm.autoSendPrompt(launchPrompt)
                }
                ChatScreen(
                    state = state,
                    onInputChange = vm::onInputChange,
                    onSend = vm::sendMessage,
                    onModelSelected = vm::onModelSelected,
                    onModeSelected = vm::onModeSelected,
                    onQuote = vm::setQuote,
                    onUpload = vm::uploadAttachment,
                    onAddImage = vm::addImage,
                    onRemoveImage = vm::removeImage,
                    onConsent = vm::respondConsent,
                    onDismissConsent = vm::dismissConsent,
                    onAskUserRespond = vm::respondAskUser,
                    onWaitForUserRespond = vm::respondWaitForUser,
                    onStop = vm::stopStreaming,
                    onOnboardingChange = vm::onOnboardingChange,
                    onCompleteOnboarding = vm::completeOnboarding,
                    onDismissOnboarding = vm::dismissOnboarding,
                    onClearError = vm::clearError,
                    onOpenDrawer = { scope.launch { drawerState.open() } },
                    onToggleAutoConsent = vm::toggleAutoConsent,
                    onSignFile = vm::signFile,
                )
            }

            composable(Screen.Sessions.route) {
                val vm: SessionsViewModel = koinViewModel()
                val state by vm.state.collectAsState()
                SessionsScreen(
                    state = state,
                    onQueryChange = vm::onQueryChange,
                    onSessionClick = { id -> navController.navigate(Screen.Chat.createRoute(id)) },
                    onRename = vm::startRename,
                    onRenameTextChange = vm::onRenameTextChange,
                    onConfirmRename = vm::confirmRename,
                    onCancelRename = vm::cancelRename,
                    onDelete = vm::deleteSession,
                    onClearError = vm::clearError,
                    onRegenTitle = vm::regenTitle,
                    onSummary = vm::summarySession,
                    onDismissSummary = vm::dismissSummary,
                    onSetSourceFilter = vm::setSourceFilter,
                    onToggleHideHeartbeat = vm::toggleHideHeartbeat,
                    onToggleHideScheduled = vm::toggleHideScheduled,
                    onToggleSource = vm::toggleSource,
                    onSelectAllSources = vm::selectAllSources,
                    onTogglePin = vm::togglePin,
                    onBack = { navController.popBackStack() },
                )
            }

            composable(Screen.More.route) {
                MoreScreen(
                    onNavigate = { route ->
                        navController.navigate(route)
                    },
                )
            }

            composable(Screen.Settings.route) {
                val vm: SettingsViewModel = koinViewModel()
                val state by vm.state.collectAsState()
                SettingsScreen(
                    state = state,
                    onBack = { navController.popBackStack() },
                    onTabChange = vm::setTab,
                    onServerUrlChange = vm::onServerUrlChange,
                    onAuthTokenChange = vm::onAuthTokenChange,
                    onSaveServerUrl = vm::saveServerUrl,
                    onClearConnectionToast = vm::clearConnectionToast,
                    onUpdateAgent = vm::updateAgent,
                    onSaveAgent = vm::saveAgent,
                    onUpdateProvider = vm::updateProvider,
                    onSaveProviders = vm::saveProviders,
                    onUpdateSystem = vm::updateSystem,
                    onSaveSystem = vm::saveSystem,
                    onProfileChange = vm::onProfileChange,
                    onSaveProfile = vm::saveProfile,
                    onChannelChange = vm::updateChannel,
                    onSaveChannel = vm::saveChannel,
                    onLoadPromptPreview = vm::loadPromptPreview,
                    onCreateApiKey = vm::createApiKey,
                    onDeleteApiKey = vm::deleteApiKey,
                    onDismissNewApiKey = vm::dismissNewApiKey,
                    onInstallLarkDeps = vm::installLarkDeps,
                    onValidateKnowledge = vm::validateKnowledge,
                    onClearKnowledgeResult = vm::clearKnowledgeValidateResult,
                    onSetTheme = vm::setTheme,
                    onCheckUpdate = updateViewModel::checkForUpdate,
                    onSetAppLock = vm::setAppLockEnabled,
                    onClearCache = vm::clearCache,
                    onClearCacheCleared = vm::clearCacheCleared,
                    onClearError = vm::clearError,
                )
            }

            composable(Screen.Memory.route) {
                val vm: MemoryViewModel = koinViewModel()
                val state by vm.state.collectAsState()
                MemoryScreen(
                    state = state,
                    onTabChange = vm::setTab,
                    onBack = { navController.popBackStack() },
                    onSelectFact = vm::selectFact,
                    onEditChange = vm::onEditChange,
                    onClearError = vm::clearError,
                    onDismissEditor = vm::dismissEditor,
                    onSaveEditing = vm::saveEditing,
                    onDeleteEditing = vm::deleteEditing,
                    onInsightsDateChange = vm::setInsightsDate,
                    onRefreshInsights = vm::loadInsights,
                    onRecordsFilterChange = vm::setRecordsFilter,
                    onRecordsSearchChange = vm::setRecordsSearch,
                    onSelectRecord = vm::selectRecord,
                    onSelectProcedure = vm::selectProcedure,
                    onDeleteRecord = vm::deleteRecord,
                    onDeleteProcedure = vm::deleteProcedure,
                    onConfirmRecord = vm::confirmRecord,
                    onConsolidate = vm::triggerConsolidate,
                    onConsolidateRecords = { vm.triggerRecordsConsolidate() },
                    onLoadSummaries = vm::loadSummaries,
                    onHideSummaries = vm::hideSummaries,
                )
            }

            composable(Screen.Knowledge.route) {
                val vm: KnowledgeViewModel = koinViewModel()
                val state by vm.state.collectAsState()
                KnowledgeScreen(
                    state = state,
                    onBack = { navController.popBackStack() },
                    onQueryChange = vm::onQueryChange,
                    onToggleSemantic = vm::toggleSemantic,
                    onSelect = vm::selectItem,
                    onDeselect = vm::deselectItem,
                    onStartCreate = vm::startCreate,
                    onTitleChange = vm::onTitleChange,
                    onContentChange = vm::onContentChange,
                    onTagInputChange = vm::onTagInputChange,
                    onAddTag = vm::addTagFromInput,
                    onRemoveTag = vm::removeTag,
                    onSave = vm::save,
                    onDelete = vm::delete,
                    onClearError = vm::clearError,
                )
            }

            composable(Screen.Skills.route) {
                val vm: SkillsViewModel = koinViewModel()
                val state by vm.state.collectAsState()
                SkillsScreen(
                    state = state,
                    onBack = { navController.popBackStack() },
                    onQueryChange = vm::onQueryChange,
                    onSelect = vm::selectSkill,
                    onDeselect = vm::deselectSkill,
                    onStartCreate = vm::startCreate,
                    onNameChange = vm::onNameChange,
                    onDescriptionChange = vm::onDescriptionChange,
                    onTriggersChange = vm::onTriggersChange,
                    onContentChange = vm::onContentChange,
                    onSave = vm::save,
                    onDelete = vm::delete,
                    onClearError = vm::clearError,
                )
            }

            composable(Screen.Agenda.route) {
                val vm: AgendaViewModel = koinViewModel()
                val state by vm.state.collectAsState()
                AgendaScreen(
                    state = state,
                    onBack = { navController.popBackStack() },
                    onRefresh = vm::load,
                    onToggleEnabled = vm::toggleEnabled,
                    onSelectDate = vm::selectDate,
                    onPrevMonth = vm::prevMonth,
                    onNextMonth = vm::nextMonth,
                    onToggleCalendar = vm::toggleCalendar,
                    onGoToday = vm::goToday,
                    onShowCreate = vm::showCreateSheet,
                    onEditEvent = vm::editEvent,
                    onDismissSheet = vm::dismissSheet,
                    onUpdateForm = vm::updateForm,
                    onSubmit = vm::submitEvent,
                    onSetCompletion = vm::setCompletion,
                    onCancelAbandon = vm::cancelAbandon,
                    onAbandonTextChange = vm::updateAbandonText,
                    onConfirmAbandon = vm::confirmAbandon,
                    onBreakdown = { ev ->
                        ChatLauncherBus.post(buildBreakdownPrompt(ev))
                        navController.navigate("chat") {
                            launchSingleTop = true
                        }
                    },
                    onRequestDelete = vm::requestDelete,
                    onCancelDelete = vm::cancelDelete,
                    onConfirmDelete = vm::confirmDelete,
                    onClearError = vm::clearError,
                )
            }

            composable(Screen.Schedule.route) {
                val vm: ScheduleViewModel = koinViewModel()
                val state by vm.state.collectAsState()
                ScheduleScreen(
                    state = state,
                    onBack = { navController.popBackStack() },
                    onToggle = vm::toggleJob,
                    onDelete = vm::deleteJob,
                    onTrigger = vm::triggerJob,
                    onOpenSession = { id -> navController.navigate(Screen.Chat.createRoute(id)) },
                    onTabChange = vm::setTab,
                    onSyncTimelines = vm::syncTimelines,
                    onTimelineAction = vm::timelineAction,
                    onShowCreateSheet = vm::showCreateSheet,
                    onDismissCreateSheet = vm::dismissCreateSheet,
                    onUpdateForm = vm::updateForm,
                    onSubmitCreate = vm::submitCreate,
                    onClearError = vm::clearError,
                    onClearTriggerSuccess = vm::clearTriggerSuccess,
                )
            }

            composable(Screen.Docs.route) {
                val vm: DocsViewModel = koinViewModel()
                val state by vm.state.collectAsState()
                DocsScreen(state = state, onBack = { navController.popBackStack() }, onSelectDoc = { slug ->
                    navController.navigate("docs/$slug")
                }, onClearError = vm::clearError, showListOnly = true)
            }

            composable(
                route = Screen.DocDetail.route,
                arguments = listOf(navArgument("slug") { type = NavType.StringType }),
            ) {
                val vm: DocsViewModel = koinViewModel { parametersOf(it.arguments?.getString("slug")) }
                val state by vm.state.collectAsState()
                val detailSlug = it.arguments?.getString("slug")
                DocsScreen(
                    state = state,
                    onBack = { navController.popBackStack() },
                    // 点正文里的相对链接 → 换一篇文档。用 navigate（而不是 vm.selectDoc
                    // 就地换内容）才能让系统返回键回到「上一篇」，符合阅读预期。
                    //
                    // **不要加 launchSingleTop**：它是按 route **模板**（`docs/{slug}`）
                    // 去重，不是按实际参数。在详情页里点另一个 slug 时，栈顶那条恰好也
                    // 匹配 `docs/{slug}`，于是整次导航被静默丢弃 —— 表现就是「链接点了
                    // 没反应」（已实测）。重复点同一篇文档也只是多压一层，返回键多按一次
                    // 即可，代价远小于链接失灵。
                    onSelectDoc = { slug -> navController.navigate("docs/$slug") },
                    onClearError = vm::clearError,
                )
            }

            composable(Screen.Logs.route) {
                val vm: LogsViewModel = koinViewModel()
                val state by vm.state.collectAsState()
                LogsScreen(
                    state = state,
                    onBack = { navController.popBackStack() },
                    onTypeChange = vm::setType,
                    onQueryChange = vm::onQueryChange,
                    onRefresh = vm::load,
                    onClearError = vm::clearError,
                )
            }

            // Track 8 routes
            composable(Screen.BackgroundTasks.route) {
                val vm: BackgroundTasksViewModel = koinViewModel()
                val state by vm.state.collectAsState()
                com.ethan.agent.ui.background.BackgroundTasksScreen(
                    state = state,
                    onBack = { navController.popBackStack() },
                    onRefresh = vm::load,
                    onStop = vm::stopTask,
                    onOpenSession = { id -> navController.navigate(Screen.Chat.createRoute(id)) },
                    onClearError = vm::clearError,
                )
            }

            composable(
                route = Screen.PptPreview.route,
                arguments = listOf(navArgument("sessionId") { type = NavType.StringType }),
            ) {
                val vm: PptPreviewViewModel = koinViewModel { parametersOf(it.arguments?.getString("sessionId")) }
                val state by vm.state.collectAsState()
                com.ethan.agent.ui.ppt.PptPreviewScreen(
                    state = state,
                    onClearError = vm::clearError,
                )
            }

            composable(
                route = Screen.Annotations.route,
                arguments = listOf(navArgument("sessionId") { type = NavType.StringType }),
            ) {
                val vm: AnnotationsViewModel = koinViewModel()
                val state by vm.state.collectAsState()
                com.ethan.agent.ui.annotations.AnnotationsScreen(
                    state = state,
                    onDelete = vm::deleteAnnotation,
                    onClearError = vm::clearError,
                )
            }
            }
        }

        // 全局更新提示（自动检查 + 手动触发）
        UpdateDialog(updateViewModel)
    }
}

/** 「拆解该安排」：生成发给新对话的 prompt（与 Web/Desktop 端 buildBreakdownPrompt 一致）。 */
private fun buildBreakdownPrompt(ev: AgendaEvent): String {
    val lines = mutableListOf("帮我拆解并准备这个日程安排：", "", "【安排】${ev.title}")
    if (ev.note.isNotBlank()) lines.add("【描述】${ev.note}")
    lines.addAll(
        listOf(
            "",
            "请总结并从我的知识库中收集整理与这个安排相关的资料：",
            "1. 汇总相关笔记和资料的要点；",
            "2. 相关资料如有链接，用 markdown 链接格式列出；",
            "3. 最后给出一份简短的行动指引（分步骤），帮我快速上手这件事。",
        ),
    )
    return lines.joinToString("\n")
}
