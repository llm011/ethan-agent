package com.ethan.agent.shared.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.ethan.agent.core.model.Message
import com.ethan.agent.core.repository.ChatRepository
import kotlinx.coroutines.flow.*
import kotlinx.coroutines.launch

/**
 * 优化版聊天 ViewModel - 使用 Repository 模式分离关注点
 * 
 * 主要改进：
 * 1. 职责单一：只处理 UI 状态和业务逻辑
 * 2. 使用 StateFlow 管理状态
 * 3. 异步操作在 viewModelScope 中执行
 * 4. 错误处理和用户反馈统一
 */
class OptimizedChatViewModel(
    private val chatRepository: ChatRepository,
    sessionId: String? = null,
) : ViewModel() {
    
    // UI 状态 - 使用 mutableStateOf + asStateAsFlow
    private val _uiState = MutableStateFlow(ChatUiState())
    val uiState: StateFlow<ChatUiState> = _uiState.asStateFlow()
    
    init {
        if (sessionId != null) {
            loadHistory(sessionId)
        } else {
            createNewSession()
        }
    }
    
    /**
     * 输入文本变化
     */
    fun onInputChange(text: String) {
        _uiState.update { it.copy(inputText = text) }
    }
    
    /**
     * 发送消息
     */
    fun sendMessage() {
        val text = _uiState.value.inputText.trim()
        if (text.isBlank()) return
        
        viewModelScope.launch {
            _uiState.update { it.copy(isLoading = true) }
            
            chatRepository.sendMessage(text).onSuccess { message ->
                _uiState.update { 
                    it.copy(
                        isLoading = false,
                        inputText = "",
                        messages = it.messages + message,
                    )
                }
            }.onFailure { error ->
                _uiState.update { 
                    it.copy(
                        isLoading = false,
                        error = "发送失败：${error.message}",
                    )
                }
            }
        }
    }
    
    /**
     * 停止流式响应
     */
    fun stopStreaming() {
        viewModelScope.launch {
            chatRepository.stopStreaming().onFailure { error ->
                _uiState.update { 
                    it.copy(
                        error = "停止失败：${error.message}",
                    )
                }
            }
        }
    }
    
    /**
     * 加载历史会话
     */
    private fun loadHistory(sessionId: String) {
        viewModelScope.launch {
            _uiState.update { it.copy(isLoading = true) }
            
            chatRepository.loadHistory(sessionId).onSuccess { messages ->
                _uiState.update { 
                    it.copy(
                        isLoading = false,
                        messages = messages,
                        sessionTitle = messages.firstOrNull()?.let { "对话 ${it.id.takeLast(8)}" },
                    )
                }
            }.onFailure { error ->
                _uiState.update { 
                    it.copy(
                        isLoading = false,
                        error = "加载失败：${error.message}",
                    )
                }
            }
        }
    }
    
    /**
     * 创建新会话
     */
    private fun createNewSession() {
        viewModelScope.launch {
            chatRepository.createNewSession().onSuccess { newSessionId ->
                chatRepository.currentSessionId = newSessionId
                _uiState.update { 
                    it.copy(
                        sessionTitle = "新对话",
                        messages = emptyList(),
                    )
                }
            }.onFailure { error ->
                _uiState.update { 
                    it.copy(
                        error = "创建会话失败：${error.message}",
                    )
                }
            }
        }
    }
    
    /**
     * 清除错误
     */
    fun clearError() {
        _uiState.update { it.copy(error = null) }
    }
    
    /**
     * 上传附件
     */
    fun uploadAttachment(uri: String) {
        // TODO: 实现附件上传逻辑
    }
    
    /**
     * 移除附件
     */
    fun removeImage(uri: String) {
        // TODO: 实现移除附件逻辑
    }
    
    override fun onCleared() {
        super.onCleared()
        // 清理资源
    }
}

// UI 状态数据类
data class ChatUiState(
    val inputText: String = "",
    val messages: List<Message> = emptyList(),
    val isLoading: Boolean = false,
    val error: String? = null,
    val sessionTitle: String? = null,
    val canGoBack: Boolean = false,
    val connectionState: String = "disconnected",
    val consentRequired: Boolean = false,
    val attachments: List<String> = emptyList(),
)
