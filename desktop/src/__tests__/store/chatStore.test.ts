/**
 * chatStore 单元测试
 */

import { describe, it, expect, beforeEach } from 'vitest';
import { useChatStore } from '@/store/chatStore';
import type { Message } from '@ethan/shared/chat/types';

describe('chatStore', () => {
  beforeEach(() => {
    // 重置 store 状态
    useChatStore.setState({
      messages: [],
      streaming: false,
      isLoading: false,
      error: null,
      activeSessionId: null,
      sessionTitle: '',
      sessionUsage: { input: 0, output: 0, cache: 0 },
      quote: null,
      models: [],
      selectedModel: '',
      modes: [],
      selectedMode: '',
      attachments: [],
      bgTasks: [],
      hasOlder: false,
      loadingOlder: false,
    });
  });

  it('should initialize with default state', () => {
    const state = useChatStore.getState();
    expect(state.messages).toEqual([]);
    expect(state.streaming).toBe(false);
    expect(state.isLoading).toBe(false);
    expect(state.error).toBeNull();
  });

  it('should set messages correctly', () => {
    const testMessages: Message[] = [
      { id: '1', sessionId: 's1', role: 'user', content: 'Hi', timestamp: Date.now() },
    ];
    
    useChatStore.setMessages(testMessages);
    
    const state = useChatStore.getState();
    expect(state.messages).toEqual(testMessages);
  });

  it('should add message to existing list', () => {
    const initialMessage: Message = {
      id: '1',
      sessionId: 's1',
      role: 'user',
      content: 'Hello',
      timestamp: Date.now(),
    };
    
    useChatStore.setMessages([initialMessage]);
    
    const newMessage: Message = {
      id: '2',
      sessionId: 's1',
      role: 'assistant',
      content: 'Hi there!',
      timestamp: Date.now(),
    };
    
    useChatStore.addMessage(newMessage);
    
    const state = useChatStore.getState();
    expect(state.messages).toHaveLength(2);
    expect(state.messages[1]).toEqual(newMessage);
  });

  it('should update message by id', () => {
    const message: Message = {
      id: '1',
      sessionId: 's1',
      role: 'assistant',
      content: 'Original',
      timestamp: Date.now(),
    };
    
    useChatStore.setMessages([message]);
    
    useChatStore.updateMessage('1', { content: 'Updated' });
    
    const state = useChatStore.getState();
    expect(state.messages[0].content).toBe('Updated');
  });

  it('should remove message by id', () => {
    const messages: Message[] = [
      { id: '1', sessionId: 's1', role: 'user', content: 'Hi', timestamp: Date.now() },
      { id: '2', sessionId: 's1', role: 'assistant', content: 'Hello', timestamp: Date.now() },
    ];
    
    useChatStore.setMessages(messages);
    
    useChatStore.removeMessage('1');
    
    const state = useChatStore.getState();
    expect(state.messages).toHaveLength(1);
    expect(state.messages[0].id).toBe('2');
  });

  it('should toggle streaming state', () => {
    useChatStore.setStreaming(true);
    expect(useChatStore.getState().streaming).toBe(true);
    
    useChatStore.setStreaming(false);
    expect(useChatStore.getState().streaming).toBe(false);
  });

  it('should handle error state', () => {
    useChatStore.setError('Test error');
    expect(useChatStore.getState().error).toBe('Test error');
    
    useChatStore.setError(null);
    expect(useChatStore.getState().error).toBeNull();
  });

  it('should add and remove attachments', () => {
    const file = new File(['test'], 'test.txt');
    
    useChatStore.addAttachment(file);
    expect(useChatStore.getState().attachments).toHaveLength(1);
    
    useChatStore.removeAttachment(0);
    expect(useChatStore.getState().attachments).toHaveLength(0);
  });

  it('should clear all attachments', () => {
    const file1 = new File(['test1'], 'test1.txt');
    const file2 = new File(['test2'], 'test2.txt');
    
    useChatStore.addAttachment(file1);
    useChatStore.addAttachment(file2);
    expect(useChatStore.getState().attachments).toHaveLength(2);
    
    useChatStore.clearAttachments();
    expect(useChatStore.getState().attachments).toHaveLength(0);
  });

  it('should manage background tasks', () => {
    const task = { id: 'task1', name: 'Test Task', status: 'running' as const };
    
    useChatStore.addBgTask(task);
    expect(useChatStore.getState().bgTasks).toHaveLength(1);
    
    useChatStore.removeBgTask('task1');
    expect(useChatStore.getState().bgTasks).toHaveLength(0);
  });
});
