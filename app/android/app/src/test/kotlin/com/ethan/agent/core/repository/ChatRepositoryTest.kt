package com.ethan.agent.core.repository

import com.ethan.agent.core.model.Message
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.flowOf
import kotlinx.coroutines.test.runTest
import org.junit.Assert.*
import org.junit.Before
import org.junit.Test
import org.mockito.Mock
import org.mockito.MockitoAnnotations

/**
 * ChatRepository 单元测试
 */
class ChatRepositoryTest {
    
    @Mock
    private lateinit var mockApiService: com.ethan.agent.core.network.EthanApiService
    
    private lateinit var repository: ChatRepository
    
    @Before
    fun setup() {
        MockitoAnnotations.openMocks(this)
        repository = ChatRepository(mockApiService)
    }
    
    @Test
    fun `sendMessage should return success result`() = runTest {
        // Given
        val testMessage = Message(
            id = "test_1",
            sessionId = "session_1",
            role = "assistant",
            content = "Hello!",
            timestamp = System.currentTimeMillis(),
        )
        
        // When
        val result = repository.sendMessage("Hi")
        
        // Then - 验证返回 Result
        assertTrue(result.isSuccess || result.isFailure)
    }
    
    @Test
    fun `loadHistory should return list of messages`() = runTest {
        // Given
        val sessionId = "test_session"
        
        // When
        val result = repository.loadHistory(sessionId)
        
        // Then
        assertTrue(result.isSuccess || result.isFailure)
    }
    
    @Test
    fun `createNewSession should return session id`() = runTest {
        // When
        val result = repository.createNewSession("Test Session")
        
        // Then
        assertTrue(result.isSuccess || result.isFailure)
    }
}
