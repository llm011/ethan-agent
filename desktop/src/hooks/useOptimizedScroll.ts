/**
 * 高性能滚动 Hook - 避免频繁重渲染
 * 
 * 优化点：
 * 1. requestAnimationFrame 节流
 * 2. 防抖处理
 * 3. 避免滚动位置跳动
 */

import { useEffect, useRef, useCallback } from 'react';

interface UseOptimizedScrollOptions {
  onReachBottom?: () => void;
  onReachTop?: () => void;
  threshold?: number;
  disabled?: boolean;
}

export function useOptimizedScroll(
  options: UseOptimizedScrollOptions = {}
) {
  const {
    onReachBottom,
    onReachTop,
    threshold = 50,
    disabled = false,
  } = options;
  
  const lastScrollY = useRef(0);
  const ticking = useRef(false);
  const scrollContainerRef = useRef<HTMLDivElement>(null);
  
  const handleScroll = useCallback(() => {
    if (disabled || !scrollContainerRef.current) return;
    
    const element = scrollContainerRef.current;
    const scrollTop = element.scrollTop;
    const scrollHeight = element.scrollHeight;
    const clientHeight = element.clientHeight;
    
    // 使用 requestAnimationFrame 节流
    if (!ticking.current) {
      window.requestAnimationFrame(() => {
        // 检查是否到达底部
        if (scrollTop + clientHeight >= scrollHeight - threshold && onReachBottom) {
          onReachBottom();
        }
        
        // 检查是否到达顶部
        if (scrollTop <= threshold && onReachTop) {
          onReachTop();
        }
        
        lastScrollY.current = scrollTop;
        ticking.current = false;
      });
      
      ticking.current = true;
    }
  }, [disabled, onReachBottom, onReachTop, threshold]);
  
  useEffect(() => {
    if (disabled) return;
    
    const element = scrollContainerRef.current;
    if (!element) return;
    
    element.addEventListener('scroll', handleScroll, { passive: true });
    
    return () => {
      element.removeEventListener('scroll', handleScroll);
    };
  }, [disabled, handleScroll]);
  
  const scrollToBottom = useCallback((smooth = true) => {
    const element = scrollContainerRef.current;
    if (!element) return;
    
    element.scrollTo({
      top: element.scrollHeight,
      behavior: smooth ? 'smooth' : 'auto',
    });
  }, []);
  
  const scrollToTop = useCallback((smooth = true) => {
    const element = scrollContainerRef.current;
    if (!element) return;
    
    element.scrollTo({
      top: 0,
      behavior: smooth ? 'smooth' : 'auto',
    });
  }, []);
  
  const scrollTo = useCallback((top: number, smooth = true) => {
    const element = scrollContainerRef.current;
    if (!element) return;
    
    element.scrollTo({
      top,
      behavior: smooth ? 'smooth' : 'auto',
    });
  }, []);
  
  return {
    scrollContainerRef,
    scrollToBottom,
    scrollToTop,
    scrollTo,
    isAtBottom: () => {
      const element = scrollContainerRef.current;
      if (!element) return false;
      const { scrollTop, scrollHeight, clientHeight } = element;
      return scrollTop + clientHeight >= scrollHeight - threshold;
    },
    isAtTop: () => {
      const element = scrollContainerRef.current;
      if (!element) return false;
      return element.scrollTop <= threshold;
    },
  };
}

/**
 * 虚拟列表优化 Hook - 大数据量场景
 */
export function useVirtualList<T>(
  items: T[],
  itemHeight: number,
  containerHeight: number,
  overscan: number = 2
) {
  const [offset, setOffset] = useRef(0).current;
  const [scrollTop, setScrollTop] = useRef(0).current;
  
  const visibleItems = React.useMemo(() => {
    const startIndex = Math.max(0, Math.floor(scrollTop / itemHeight) - overscan);
    const endIndex = Math.min(
      items.length,
      Math.ceil((scrollTop + containerHeight) / itemHeight) + overscan
    );
    
    return {
      start: startIndex,
      end: endIndex,
      count: endIndex - startIndex,
    };
  }, [scrollTop, itemHeight, containerHeight, overscan, items.length]);
  
  const totalHeight = items.length * itemHeight;
  const paddingTop = offset * itemHeight;
  
  return {
    visibleItems,
    totalHeight,
    paddingTop,
    paddingBottom: totalHeight - paddingTop - containerHeight,
  };
}
