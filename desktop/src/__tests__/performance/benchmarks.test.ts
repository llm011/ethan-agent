/**
 * 性能基准测试
 */

import { describe, it, expect, beforeAll } from 'vitest';

describe('Performance Benchmarks', () => {
  let metrics: Record<string, number> = {};
  
  beforeAll(async () => {
    // 收集基础性能指标
    if ('memory' in performance) {
      const mem = performance.memory as any;
      metrics = {
        heapUsedMB: mem.usedJSHeapSize / 1024 / 1024,
        heapTotalMB: mem.totalJSHeapSize / 1024 / 1024,
        jsHeapLimitMB: mem.jsHeapSizeLimit / 1024 / 1024,
      };
    }
  });
  
  it('should have acceptable initial memory usage', () => {
    // 初始内存使用应该在合理范围内 (< 50MB)
    if (metrics.heapUsedMB > 0) {
      expect(metrics.heapUsedMB).toBeLessThan(50);
    }
  });
  
  it('should have reasonable heap total', () => {
    // 总堆内存应该合理 (< 500MB)
    if (metrics.heapTotalMB > 0) {
      expect(metrics.heapTotalMB).toBeLessThan(500);
    }
  });
  
  it('should measure render performance', async () => {
    // 模拟渲染性能测试
    const iterations = 100;
    const start = performance.now();
    
    for (let i = 0; i < iterations; i++) {
      // 模拟简单的 DOM 操作
      const div = document.createElement('div');
      div.textContent = `Item ${i}`;
      document.body.appendChild(div);
      document.body.removeChild(div);
    }
    
    const end = performance.now();
    const avgTime = (end - start) / iterations;
    
    // 平均渲染时间应该 < 10ms
    expect(avgTime).toBeLessThan(10);
  });
  
  it('should measure list rendering performance', async () => {
    const itemCount = 1000;
    const start = performance.now();
    
    // 创建虚拟列表（优化后的方式）
    const fragment = document.createDocumentFragment();
    for (let i = 0; i < itemCount; i++) {
      const div = document.createElement('div');
      div.textContent = `List Item ${i}`;
      div.style.height = '40px';
      fragment.appendChild(div);
    }
    
    document.body.appendChild(fragment);
    
    const end = performance.now();
    const totalTime = end - start;
    
    // 渲染 1000 项应该 < 100ms
    expect(totalTime).toBeLessThan(100);
  });
  
  it('should measure scroll performance', async () => {
    const container = document.createElement('div');
    container.style.height = '100px';
    container.style.overflowY = 'auto';
    
    // 创建大量内容
    const content = document.createElement('div');
    content.style.height = '2000px';
    container.appendChild(content);
    document.body.appendChild(container);
    
    const scrollIterations = 50;
    const start = performance.now();
    
    for (let i = 0; i < scrollIterations; i++) {
      container.scrollTop = i * 40;
    }
    
    const end = performance.now();
    const avgScrollTime = (end - start) / scrollIterations;
    
    // 每次滚动操作应该 < 5ms
    expect(avgScrollTime).toBeLessThan(5);
    
    document.body.removeChild(container);
  });
  
  it('should track memory growth over time', async () => {
    const samples: number[] = [];
    const sampleCount = 5;
    
    if ('memory' in performance) {
      for (let i = 0; i < sampleCount; i++) {
        const mem = performance.memory as any;
        samples.push(mem.usedJSHeapSize / 1024 / 1024);
        
        // 等待一点时间
        await new Promise(resolve => setTimeout(resolve, 100));
      }
      
      // 检查内存增长是否在可接受范围
      const growth = samples[samples.length - 1] - samples[0];
      expect(growth).toBeLessThan(10); // 5 次采样内增长不超过 10MB
    }
  });
});
