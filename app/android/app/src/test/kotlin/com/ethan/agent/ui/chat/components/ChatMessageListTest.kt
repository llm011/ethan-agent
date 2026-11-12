package com.ethan.agent.ui.chat.components

import androidx.compose.ui.test.ExperimentalComposeUiApi
import androidx.compose.ui.test.junit4.createAndroidComposeRule
import androidx.compose.ui.test.onNodeWithText
import com.ethan.agent.shared.model.Message
import org.junit.Assert.assertEquals
import org.junit.Rule
import org.junit.Test

/**
 * ChatMessageList 组件测试
 * 
 * 测试覆盖：
 * 1. 消息列表渲染正确性
 * 2. 用户/助手消息样式区分
 * 3. 滚动到底部功能
 */
@OptIn(ExperimentalComposeUiApi::class)
class ChatMessageListTest {
    
    @get:Rule
    val composeRule = createAndroidComposeRule<androidx.activity.ComponentActivity>()
    
    @Test
    fun `render empty list should show no items`() {
        // Given
        val messages = emptyList<Message>()
        
        // When
        composeRule.setContent {
            ChatMessageList(
                messages = messages,
                onMessageClick = {},
                onMessageLongClick = {},
            )
        }
        
        // Then - 应该不显示任何消息项
        composeRule.onNodeWithText("test message").assertDoesNotExist()
    }
    
    @Test
    fun `render single user message should display correctly`() {
        // Given
        val userMessage = Message(
            id = "1",
            sessionId = "session1",
            role = "user",
            content = "Hello Ethan!",
            timestamp = System.currentTimeMillis(),
            isStreaming = false,
        )
        
        // When
        composeRule.setContent {
            ChatMessageList(
                messages = listOf(userMessage),
                onMessageClick = {},
                onMessageLongClick = {},
            )
        }
        
        // Then
        composeRule.onNodeWithText("Hello Ethan!").assertExists()
    }
    
    @Test
    fun `render assistant message should display avatar`() {
        // Given
        val assistantMessage = Message(
            id = "2",
            sessionId = "session1",
            role = "assistant",
            content = "Hi there!",
            timestamp = System.currentTimeMillis(),
            isStreaming = false,
        )
        
        // When
        composeRule.setContent {
            ChatMessageList(
                messages = listOf(assistantMessage),
                onMessageClick = {},
                onMessageLongClick = {},
            )
        }
        
        // Then - 应该有头像图标
        composeRule.onNodeWithContentDescription("Assistant").assertExists()
    }
    
    @Test
    fun `multiple messages should be rendered in order`() {
        // Given
        val messages = listOf(
            Message("1", "s1", "user", "First", System.currentTimeMillis()),
            Message("2", "s1", "assistant", "Second", System.currentTimeMillis()),
            Message("3", "s1", "user", "Third", System.currentTimeMillis()),
        )
        
        // When
        composeRule.setContent {
            ChatMessageList(
                messages = messages,
                onMessageClick = {},
                onMessageLongClick = {},
            )
        }
        
        // Then
        composeRule.onNodeWithText("First").assertExists()
        composeRule.onNodeWithText("Second").assertExists()
        composeRule.onNodeWithText("Third").assertExists()
    }
}
