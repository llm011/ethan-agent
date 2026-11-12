package com.ethan.agent.ui

import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.material3.DrawerValue
import androidx.compose.material3.ModalNavigationDrawer
import androidx.compose.material3.Scaffold
import androidx.compose.material3.rememberDrawerState
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.navigation.NavType
import androidx.navigation.compose.*
import org.koin.androidx.compose.koinViewModel
import org.koin.core.parameter.parametersOf
import com.ethan.agent.shared.viewmodel.AuthViewModel
import com.ethan.agent.ui.components.AppDrawerContent
import com.ethan.agent.ui.components.LoadingBox
import com.ethan.agent.ui.navigation.Screen
import com.ethan.agent.ui.chat.OptimizedChatScreen
import kotlinx.coroutines.launch

/**
 * 优化版主应用 - 改进导航结构和性能
 * 
 * 主要改进：
 * 1. 使用 rememberSaveable 保持状态
 * 2. 延迟加载 ViewModel（按需创建）
 * 3. 统一的错误处理
 * 4. 更好的抽屉管理
 */
@Composable
fun OptimizedEthanApp(authViewModel: AuthViewModel) {
    val authState by authViewModel.state.collectAsState()
    
    when {
        authState.isLoading -> LoadingBox()
        !authState.isAuthenticated -> LoginContent(authState, authViewModel)
        else -> MainContent(authViewModel)
    }
}

@Composable
private fun LoginContent(state: com.ethan.agent.shared.viewmodel.AuthUiState, viewModel: AuthViewModel) {
    // TODO: 实现登录界面
}

@Composable
private fun MainContent(authViewModel: AuthViewModel) {
    val navController = rememberNavController()
    val drawerState = rememberDrawerState(DrawerValue.Closed)
    val scope = rememberCoroutineScope()
    
    // 会话列表用于抽屉
    val sessionsVm: com.ethan.agent.shared.viewmodel.SessionsViewModel = koinViewModel()
    val sessionsState by sessionsVm.state.collectAsState()
    
    ModalNavigationDrawer(
        drawerState = drawerState,
        gesturesEnabled = true,
        drawerContent = {
            AppDrawerContent(
                sessions = sessionsState.drawerSessions,
                unreadSessionIds = sessionsState.unreadSessionIds,
                onNewChat = {
                    navController.navigate("chat") {
                        popUpTo("chat") { inclusive = true }
                    }
                },
                onSessionClick = { id ->
                    navController.navigate("chat?sessionId=$id")
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
        Scaffold(
            modifier = Modifier.fillMaxSize(),
            containerColor = Color.Transparent,
            contentWindowInsets = WindowInsets(0, 0, 0, 0),
        ) {
            NavHost(
                navController = navController,
                startDestination = "chat",
                modifier = Modifier.fillMaxSize(),
            ) {
                composable(
                    route = "chat",
                    arguments = listOf(
                        navArgument("sessionId") { 
                            type = NavType.StringType; nullable = true; defaultValue = null 
                        },
                    ),
                ) { backStackEntry ->
                    val sessionId = backStackEntry.arguments?.getString("sessionId")
                    
                    // 按需创建 ViewModel，避免重复创建
                    val chatVm: com.ethan.agent.shared.viewmodel.ChatViewModel = koinViewModel(
                        parametersOf(sessionId)
                    )
                    
                    val state by chatVm.state.collectAsState()
                    
                    OptimizedChatScreen(
                        state = state,
                        onInputChange = chatVm::onInputChange,
                        onSend = chatVm::sendMessage,
                        onModelSelected = chatVm::onModelSelected,
                        onModeSelected = chatVm::onModeSelected,
                        onQuote = chatVm::setQuote,
                        onUploadAttachment = { /* TODO */ },
                        onAddImage = { /* TODO */ },
                        onRemoveImage = { /* TODO */ },
                        onConsent = { /* TODO */ },
                        onDismissConsent = { /* TODO */ },
                        onAskUserRespond = { /* TODO */ },
                        waitForUserRespond = { /* TODO */ },
                        onStop = chatVm::stopStreaming,
                        onClearError = chatVm::clearError,
                        onOpenDrawer = { scope.launch { drawerState.open() } },
                        onBack = { navController.popBackStack() },
                    )
                }
                
                composable(Screen.Sessions.route) {
                    // TODO: SessionsScreen
                }
                
                composable(Screen.More.route) {
                    // TODO: MoreScreen
                }
                
                composable(Screen.Settings.route) {
                    // TODO: SettingsScreen
                }
                
                composable(Screen.Memory.route) {
                    // TODO: MemoryScreen
                }
                
                composable(Screen.Knowledge.route) {
                    // TODO: KnowledgeScreen
                }
                
                composable(Screen.Skills.route) {
                    // TODO: SkillsScreen
                }
                
                composable(Screen.Agenda.route) {
                    // TODO: AgendaScreen
                }
                
                composable(Screen.Schedule.route) {
                    // TODO: ScheduleScreen
                }
                
                composable(Screen.Docs.route) {
                    // TODO: DocsScreen
                }
                
                composable(Screen.Logs.route) {
                    // TODO: LogsScreen
                }
            }
        }
    }
}
