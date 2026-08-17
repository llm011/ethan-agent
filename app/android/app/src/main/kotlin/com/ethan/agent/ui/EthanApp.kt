package com.ethan.agent.ui

import androidx.compose.animation.AnimatedContentTransitionScope
import androidx.compose.animation.core.tween
import androidx.compose.material3.DrawerValue
import androidx.compose.material3.ModalNavigationDrawer
import androidx.compose.material3.Scaffold
import androidx.compose.material3.rememberDrawerState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
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
                    navController.navigate("chat") {
                        launchSingleTop = true
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
        Scaffold { innerPadding ->
            NavHost(
                navController = navController,
                startDestination = "chat",
                enterTransition = slideIn,
                exitTransition = slideOut,
                popEnterTransition = popSlideIn,
                popExitTransition = popSlideOut,
                modifier = Modifier.padding(innerPadding),
            ) {
            composable(
                route = "chat?sessionId={sessionId}",
                arguments = listOf(navArgument("sessionId") { type = NavType.StringType; nullable = true; defaultValue = null }),
            ) {
                val vm: ChatViewModel = koinViewModel { parametersOf(it.arguments?.getString("sessionId")) }
                val state by vm.state.collectAsState()
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
                    onStop = vm::stopStreaming,
                    onOnboardingChange = vm::onOnboardingChange,
                    onCompleteOnboarding = vm::completeOnboarding,
                    onDismissOnboarding = vm::dismissOnboarding,
                    onClearError = vm::clearError,
                    onOpenDrawer = { scope.launch { drawerState.open() } },
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
                    onDismissFactEditor = vm::dismissFactEditor,
                    onEditChange = vm::onEditChange,
                    onSaveFact = vm::saveFact,
                    onDeleteFact = vm::deleteFact,
                    onDeleteProcedure = vm::deleteProcedure,
                    onClearError = vm::clearError,
                    onInsightsDateChange = vm::setInsightsDate,
                    onRefreshInsights = vm::loadInsights,
                    onRecordsFilterChange = vm::setRecordsFilter,
                    onRecordsSearchChange = vm::setRecordsSearch,
                    onSelectRecord = vm::selectRecord,
                    onDismissRecord = vm::dismissRecord,
                    onRecordEditContent = vm::onRecordEditContent,
                    onSaveRecord = vm::saveRecord,
                    onDeleteRecord = vm::deleteRecord,
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
                    onComplete = vm::completeEvent,
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
                DocsScreen(state = state, onBack = { navController.popBackStack() }, onSelectDoc = vm::selectDoc, onClearError = vm::clearError)
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
