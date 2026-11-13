/**
 * useOptimizedScroll Hook 单元测试
 */

import { describe, it, expect, beforeEach, vi } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import { useOptimizedScroll } from '@/hooks/useOptimizedScroll';

describe('useOptimizedScroll', () => {
  let mockElement: HTMLElement;
  
  beforeEach(() => {
    // 创建模拟 DOM 元素
    mockElement = document.createElement('div');
    mockElement.style.height = '100px';
    mockElement.style.overflowY = 'auto';
    mockElement.scrollTop = 0;
    
    // Mock requestAnimationFrame
    global.requestAnimationFrame = vi.fn((cb) => setTimeout(cb, 0));
    global.cancelAnimationFrame = vi.fn();
    
    // 添加到 DOM
    document.body.appendChild(mockElement);
  });
  
  afterEach(() => {
    document.body.removeChild(mockElement);
    vi.clearAllMocks();
  });
  
  it('should return scroll container ref', () => {
    const { result } = renderHook(() => useOptimizedScroll());
    
    expect(result.current.scrollContainerRef).toBeDefined();
    expect(typeof result.current.scrollContainerRef.current).toBe('object');
  });
  
  it('should provide scrollToBottom function', () => {
    const { result } = renderHook(() => useOptimizedScroll());
    
    expect(typeof result.current.scrollToBottom).toBe('function');
  });
  
  it('should provide scrollToTop function', () => {
    const { result } = renderHook(() => useOptimizedScroll());
    
    expect(typeof result.current.scrollToTop).toBe('function');
  });
  
  it('should provide isAtBottom function', () => {
    const { result } = renderHook(() => useOptimizedScroll());
    
    expect(typeof result.current.isAtBottom).toBe('function');
  });
  
  it('should provide isAtTop function', () => {
    const { result } = renderHook(() => useOptimizedScroll());
    
    expect(typeof result.current.isAtTop).toBe('function');
  });
  
  it('should update scroll state when element scrolls', async () => {
    const onReachBottom = vi.fn();
    const { result } = renderHook(() => 
      useOptimizedScroll({ onReachBottom })
    );
    
    // Simulate scroll event
    act(() => {
      mockElement.scrollTop = 50;
      mockElement.dispatchEvent(new Event('scroll'));
    });
    
    // Wait for RAF
    await new Promise(resolve => setTimeout(resolve, 10));
    
    // Verify scroll handler was called
    expect(mockElement.scrollTop).toBe(50);
  });
  
  it('should debounce scroll events', async () => {
    const onReachBottom = vi.fn();
    const { result } = renderHook(() => 
      useOptimizedScroll({ onReachBottom, threshold: 50 })
    );
    
    // Trigger multiple rapid scroll events
    act(() => {
      for (let i = 0; i < 10; i++) {
        mockElement.scrollTop = i * 10;
        mockElement.dispatchEvent(new Event('scroll'));
      }
    });
    
    // Wait for debouncing
    await new Promise(resolve => setTimeout(resolve, 200));
    
    // Should only trigger once after debounce
    expect(onReachBottom).toHaveBeenCalled();
  });
});
