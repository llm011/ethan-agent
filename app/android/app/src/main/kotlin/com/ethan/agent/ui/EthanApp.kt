package com.ethan.agent.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.navigation.NavGraph.Companion.findStartDestination
import androidx.navigation.NavType
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.currentBackStackEntryAsState
import androidx.navigation.compose.rememberNavController
import androidx.navigation.navArgument
import com.ethan.agent.ui.auth.AuthUiState
import com.ethan.agent.ui.auth.AuthViewModel
import com.ethan.agent.ui.auth.LoginScreen
import com.ethan.agent.ui.chat.ChatScreen
import com.ethan.agent.ui.chat.ChatViewModel
import com.ethan.agent.ui.docs.DocsScreen
import com.ethan.agent.ui.docs.DocsViewModel
import com.ethan.agent.ui.knowledge.KnowledgeScreen
import com.ethan.agent.ui.knowledge.KnowledgeViewModel
import com.ethan.agent.ui.logs.LogsScreen
import com.ethan.agent.ui.logs.LogsViewModel
import com.ethan.agent.ui.memory.MemoryScreen
import com.ethan.agent.ui.memory.MemoryViewModel
import com.ethan.agent.ui.navigation.Screen
import com.ethan.agent.ui.navigation.bottomNavItems
import com.ethan.agent.ui.schedule.ScheduleScreen
import com.ethan.agent.ui.schedule.ScheduleViewModel
import com.ethan.agent.ui.sessions.SessionsScreen
import com.ethan.agent.ui.sessions.SessionsViewModel
import com.ethan.agent.ui.settings.SettingsScreen
import com.ethan.agent.ui.settings.SettingsViewModel
import com.ethan.agent.ui.skills.SkillsScreen
import com.ethan.agent.ui.skills.SkillsViewModel
import com.ethan.agent.ui.components.LoadingBox
import com.ethan.agent.ui.components.UpdateDialog

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
private fun CuteBottomBar(
    items: List<Screen>,
    currentRoute: String?,
    onItemClick: (Screen) -> Unit,
    isOnChatPage: Boolean = false,
) {
    // On chat page: no rounding/shadow so it merges with input bar above (unified dock)
    Surface(
        modifier = Modifier.fillMaxWidth(),
        shadowElevation = if (isOnChatPage) 0.dp else 8.dp,
        shape = if (isOnChatPage) RoundedCornerShape(0.dp)
            else RoundedCornerShape(topStart = 24.dp, topEnd = 24.dp),
        color = MaterialTheme.colorScheme.surface,
    ) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .height(64.dp)
                .padding(horizontal = 8.dp),
            horizontalArrangement = Arrangement.SpaceEvenly,
            verticalAlignment = Alignment.CenterVertically,
        ) {
            items.forEach { screen ->
                val baseRoute = screen.route.substringBefore("?")
                val selected = currentRoute?.startsWith(baseRoute) == true
                val color = if (selected) MaterialTheme.colorScheme.primary
                    else MaterialTheme.colorScheme.onSurfaceVariant

                Column(
                    modifier = Modifier
                        .weight(1f)
                        .clip(RoundedCornerShape(16.dp))
                        .clickable(
                            interactionSource = remember { MutableInteractionSource() },
                            indication = null,
                        ) { onItemClick(screen) }
                        .padding(vertical = 6.dp),
                    horizontalAlignment = Alignment.CenterHorizontally,
                    verticalArrangement = Arrangement.Center,
                ) {
                    Box(
                        modifier = Modifier
                            .background(
                                color = if (selected) MaterialTheme.colorScheme.primary.copy(alpha = 0.12f)
                                    else androidx.compose.ui.graphics.Color.Transparent,
                                shape = RoundedCornerShape(50),
                            )
                            .padding(horizontal = 16.dp, vertical = 4.dp),
                        contentAlignment = Alignment.Center,
                    ) {
                        screen.icon?.let {
                            Icon(
                                imageVector = it,
                                contentDescription = screen.title,
                                modifier = Modifier.size(22.dp),
                                tint = color,
                            )
                        }
                    }
                    Spacer(modifier = Modifier.height(2.dp))
                    Text(
                        text = screen.title,
                        style = MaterialTheme.typography.labelSmall,
                        color = color,
                    )
                }
            }
        }
    }
}

@Composable
private fun MainContent(authViewModel: AuthViewModel) {
    val navController = rememberNavController()
    val updateViewModel: com.ethan.agent.ui.components.UpdateViewModel = hiltViewModel()
    val backStack by navController.currentBackStackEntryAsState()
    val currentRoute = backStack?.destination?.route

    val showBottomBar = bottomNavItems.any { item ->
        currentRoute?.startsWith(item.route.substringBefore("?")) == true ||
            currentRoute == Screen.More.route
    }

    Scaffold(
        bottomBar = {
            if (showBottomBar) {
                CuteBottomBar(
                    items = bottomNavItems,
                    currentRoute = currentRoute,
                    onItemClick = { screen ->
                        navController.navigate(screen.route.substringBefore("?")) {
                            popUpTo(navController.graph.findStartDestination().id) {
                                saveState = true
                            }
                            launchSingleTop = true
                            restoreState = true
                        }
                    },
                    isOnChatPage = currentRoute?.startsWith("chat") == true,
                )
            }
        },
    ) { padding ->
        NavHost(
            navController = navController,
            startDestination = "chat",
            modifier = Modifier.padding(padding),
        ) {
            composable(
                route = "chat?sessionId={sessionId}",
                arguments = listOf(navArgument("sessionId") { type = NavType.StringType; nullable = true; defaultValue = null }),
            ) {
                val vm: ChatViewModel = hiltViewModel()
                val state by vm.state.collectAsState()
                ChatScreen(
                    state = state,
                    onInputChange = vm::onInputChange,
                    onSend = vm::sendMessage,
                    onModelSelected = vm::onModelSelected,
                    onModeSelected = vm::onModeSelected,
                    onQuote = vm::setQuote,
                    onUpload = vm::uploadAttachment,
                    onConsent = vm::respondConsent,
                    onDismissConsent = vm::dismissConsent,
                    onStop = vm::stopStreaming,
                    onOnboardingChange = vm::onOnboardingChange,
                    onCompleteOnboarding = vm::completeOnboarding,
                    onDismissOnboarding = vm::dismissOnboarding,
                    onClearError = vm::clearError,
                )
            }

            composable(Screen.Sessions.route) {
                val vm: SessionsViewModel = hiltViewModel()
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
                val vm: SettingsViewModel = hiltViewModel()
                val state by vm.state.collectAsState()
                SettingsScreen(
                    state = state,
                    onTabChange = vm::setTab,
                    onServerUrlChange = vm::onServerUrlChange,
                    onSaveServerUrl = vm::saveServerUrl,
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
                    onClearError = vm::clearError,
                )
            }

            composable(Screen.Memory.route) {
                val vm: MemoryViewModel = hiltViewModel()
                val state by vm.state.collectAsState()
                MemoryScreen(
                    state = state,
                    onTabChange = vm::setTab,
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
                val vm: KnowledgeViewModel = hiltViewModel()
                val state by vm.state.collectAsState()
                KnowledgeScreen(
                    state = state,
                    onQueryChange = vm::onQueryChange,
                    onToggleSemantic = vm::toggleSemantic,
                    onSelect = vm::selectItem,
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
                val vm: SkillsViewModel = hiltViewModel()
                val state by vm.state.collectAsState()
                SkillsScreen(
                    state = state,
                    onQueryChange = vm::onQueryChange,
                    onSelect = vm::selectSkill,
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

            composable(Screen.Schedule.route) {
                val vm: ScheduleViewModel = hiltViewModel()
                val state by vm.state.collectAsState()
                ScheduleScreen(
                    state = state,
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
                val vm: DocsViewModel = hiltViewModel()
                val state by vm.state.collectAsState()
                DocsScreen(state = state, onSelectDoc = { slug ->
                    navController.navigate("docs/$slug")
                }, onClearError = vm::clearError, showListOnly = true)
            }

            composable(
                route = Screen.DocDetail.route,
                arguments = listOf(navArgument("slug") { type = NavType.StringType }),
            ) {
                val vm: DocsViewModel = hiltViewModel()
                val state by vm.state.collectAsState()
                DocsScreen(state = state, onSelectDoc = vm::selectDoc, onClearError = vm::clearError)
            }

            composable(Screen.Logs.route) {
                val vm: LogsViewModel = hiltViewModel()
                val state by vm.state.collectAsState()
                LogsScreen(
                    state = state,
                    onTypeChange = vm::setType,
                    onQueryChange = vm::onQueryChange,
                    onRefresh = vm::load,
                    onClearError = vm::clearError,
                )
            }

            // Track 8 routes
            composable(Screen.BackgroundTasks.route) {
                val vm: com.ethan.agent.ui.background.BackgroundTasksViewModel = hiltViewModel()
                val state by vm.state.collectAsState()
                com.ethan.agent.ui.background.BackgroundTasksScreen(
                    state = state,
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
                val vm: com.ethan.agent.ui.ppt.PptPreviewViewModel = hiltViewModel()
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
                val vm: com.ethan.agent.ui.annotations.AnnotationsViewModel = hiltViewModel()
                val state by vm.state.collectAsState()
                com.ethan.agent.ui.annotations.AnnotationsScreen(
                    state = state,
                    onDelete = vm::deleteAnnotation,
                    onClearError = vm::clearError,
                )
            }
        }

        // 全局更新提示（自动检查 + 手动触发）
        UpdateDialog(updateViewModel)
    }
}
