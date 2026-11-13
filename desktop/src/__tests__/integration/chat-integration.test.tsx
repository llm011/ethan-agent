/**
 * 聊天功能集成测试
 */

import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { ProfessionalThemeProvider } from '@/theme/ProfessionalTheme';
import { useChatStore } from '@/store/chatStore';
import { OptimizedChatView } from '@/components/chat/OptimizedChatView';

// Mock API calls
vi.mock('@/lib/api', () => ({
  streamChat: vi.fn(),
}));

describe('OptimizedChatView Integration', () => {
  const mockMessages = [
    { id: '1', sessionId: 's1', role: 'user', content: 'Hello', timestamp: Date.now() },
  ];
  
  const renderComponent = (initialMessages = mockMessages) => {
    useChatStore.setState({ messages: initialMessages });
    
    return render(
      <MemoryRouter>
        <ProfessionalThemeProvider>
          <OptimizedChatView
            messages={initialMessages}
            inputText=""
            isStreaming={false}
            error={null}
            onInputChange={vi.fn()}
            onSend={vi.fn()}
            onMessageClick={vi.fn()}
            onMessageLongClick={vi.fn()}
          />
        </ProfessionalThemeProvider>
      </MemoryRouter>
    );
  };
  
  beforeEach(() => {
    vi.clearAllMocks();
  });
  
  it('should display messages correctly', () => {
    renderComponent();
    
    expect(screen.getByText('Hello')).toBeInTheDocument();
  });
  
  it('should show input field', () => {
    renderComponent();
    
    const input = screen.getByPlaceholderText(/输入消息/i);
    expect(input).toBeInTheDocument();
  });
  
  it('should allow typing in input', async () => {
    renderComponent();
    
    const input = screen.getByPlaceholderText(/输入消息/i);
    await userEvent.type(input, 'Test message');
    
    expect(input).toHaveValue('Test message');
  });
  
  it('should send message on Enter key', async () => {
    const onSendMock = vi.fn();
    
    render(
      <MemoryRouter>
        <ProfessionalThemeProvider>
          <OptimizedChatView
            messages={mockMessages}
            inputText="Test"
            isStreaming={false}
            error={null}
            onInputChange={vi.fn()}
            onSend={onSendMock}
            onMessageClick={vi.fn()}
            onMessageLongClick={vi.fn()}
          />
        </ProfessionalThemeProvider>
      </MemoryRouter>
    );
    
    const input = screen.getByPlaceholderText(/输入消息/i);
    fireEvent.change(input, { target: { value: 'Test' } });
    
    // Simulate Enter key
    fireEvent.keyDown(input, { key: 'Enter', code: 'Enter' });
    
    expect(onSendMock).toHaveBeenCalled();
  });
  
  it('should not send on Shift+Enter', async () => {
    const onSendMock = vi.fn();
    
    render(
      <MemoryRouter>
        <ProfessionalThemeProvider>
          <OptimizedChatView
            messages={mockMessages}
            inputText="Test"
            isStreaming={false}
            error={null}
            onInputChange={vi.fn()}
            onSend={onSendMock}
            onMessageClick={vi.fn()}
            onMessageLongClick={vi.fn()}
          />
        </ProfessionalThemeProvider>
      </MemoryRouter>
    );
    
    const input = screen.getByPlaceholderText(/输入消息/i);
    fireEvent.keyDown(input, { key: 'Enter', code: 'Enter', shiftKey: true });
    
    expect(onSendMock).not.toHaveBeenCalled();
  });
  
  it('should show streaming indicator', () => {
    render(
      <MemoryRouter>
        <ProfessionalThemeProvider>
          <OptimizedChatView
            messages={[...mockMessages, { 
              id: '2', 
              sessionId: 's1', 
              role: 'assistant', 
              content: '', 
              timestamp: Date.now(),
              isStreaming: true,
            }]}
            inputText=""
            isStreaming={true}
            error={null}
            onInputChange={vi.fn()}
            onSend={vi.fn()}
            onMessageClick={vi.fn()}
            onMessageLongClick={vi.fn()}
          />
        </ProfessionalThemeProvider>
      </MemoryRouter>
    );
    
    expect(screen.getByText(/正在思考/i)).toBeInTheDocument();
  });
  
  it('should show error banner when error exists', () => {
    render(
      <MemoryRouter>
        <ProfessionalThemeProvider>
          <OptimizedChatView
            messages={mockMessages}
            inputText=""
            isStreaming={false}
            error="Network error"
            onInputChange={vi.fn()}
            onSend={vi.fn()}
            onMessageClick={vi.fn()}
            onMessageLongClick={vi.fn()}
          />
        </ProfessionalThemeProvider>
      </MemoryRouter>
    );
    
    expect(screen.getByText('Network error')).toBeInTheDocument();
  });
});
