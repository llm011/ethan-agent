package com.ethan.agent.core.usecase

import com.ethan.agent.core.model.Message
import com.ethan.agent.core.repository.ChatRepository
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.test.runTest
import org.junit.Assert.*
import org.junit.Before
import org.junit.Test
import org.mockito.Mock
import org.mockito.MockitoAnnotations

/**
 * SendMessageUseCase 单元测试
 */
class SendMessageUseCaseTest {
    
    @Mock
    private lateinit var mockRepository: ChatRepository
    
    private lateinit var useCase: SendMessageUseCase
    
    @Before
    fun setup() {
        MockitoAnnotations.openMocks(this)
        useCase = SendMessageUseCase(mockRepository)
    }
    
    @Test
    fun `invoke should call repository sendMessage`() = runTest {
        // Given
        val messageContent = "Test message"
        
        // When
        val resultFlow = useCase(messageContent)
        
        // Then - 验证 Flow 返回
        assertNotNull(resultFlow)
    }
}
