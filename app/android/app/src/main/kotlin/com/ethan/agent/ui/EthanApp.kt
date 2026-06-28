package com.ethan.agent.ui

import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Icon
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
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
    val backStack by navController.currentBackStackEntryAsState()
    val currentRoute = backStack?.destination?.route

    val showBottomBar = bottomNavItems.any { item ->
        currentRoute?.startsWith(item.route.substringBefore("?")) == true ||
            currentRoute == Screen.More.route
    }

    Scaffold(
        bottomBar = {
            if (showBottomBar) {
                NavigationBar {
                    bottomNavItems.forEach { screen ->
                        val baseRoute = screen.route.substringBefore("?")
                        NavigationBarItem(
                            selected = currentRoute?.startsWith(baseRoute) == true,
                            onClick = {
                                navController.navigate(screen.route.substringBefore("?")) {
                                    popUpTo(navController.graph.findStartDestination().id) {
                                        saveState = true
                                    }
                                    launchSingleTop = true
                                    restoreState = true
                                }
                            },
                            icon = { screen.icon?.let { Icon(it, contentDescription = screen.title) } },
                            label = { Text(screen.title) },
                        )
                    }
                }
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
                )
            }

            composable(Screen.More.route) {
                MoreScreen(onNavigate = { route ->
                    navController.navigate(route)
                })
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
                    onDeleteEpisode = vm::deleteEpisode,
                    onDeleteProcedure = vm::deleteProcedure,
                    onClearError = vm::clearError,
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
                    onTagsChange = vm::onTagsChange,
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
                    onOpenSession = { id -> navController.navigate(Screen.Chat.createRoute(id)) },
                    onClearError = vm::clearError,
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
        }
    }
}
