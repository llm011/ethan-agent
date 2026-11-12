/**
 * 专业级性能监控工具
 * 
 * 功能：
 * - React 组件渲染时间追踪
 * - 内存使用监控
 * - 网络请求性能分析
 * - 错误边界捕获
 */

interface PerformanceMetrics {
  renderTime: number;
  commitTime: number;
  memoryUsage?: {
    heapUsed: number;
    heapTotal: number;
  };
  networkLatency?: number;
}

class PerformanceMonitor {
  private static instance: PerformanceMonitor;
  private metrics: Map<string, PerformanceMetrics[]> = new Map();
  private thresholdMs = 100; // 超过 100ms 记录警告
  
  private constructor() {}
  
  static getInstance(): PerformanceMonitor {
    if (!PerformanceMonitor.instance) {
      PerformanceMonitor.instance = new PerformanceMonitor();
    }
    return PerformanceMonitor.instance;
  }
  
  /**
   * 测量组件渲染时间
   */
  measureRender(componentName: string, renderTime: number) {
    const metrics = this.metrics.get(componentName) || [];
    metrics.push({
      renderTime,
      commitTime: performance.now(),
    });
    
    // 保留最近 100 次测量
    if (metrics.length > 100) {
      metrics.shift();
    }
    
    this.metrics.set(componentName, metrics);
    
    if (renderTime > this.thresholdMs) {
      console.warn(`⚠️ ${componentName} 渲染耗时：${renderTime.toFixed(2)}ms`);
    }
  }
  
  /**
   * 获取组件性能统计
   */
  getComponentStats(componentName: string): {
    avg: number;
    max: number;
    min: number;
    count: number;
  } | null {
    const metrics = this.metrics.get(componentName);
    if (!metrics || metrics.length === 0) return null;
    
    const times = metrics.map(m => m.renderTime);
    const sum = times.reduce((a, b) => a + b, 0);
    
    return {
      avg: sum / times.length,
      max: Math.max(...times),
      min: Math.min(...times),
      count: times.length,
    };
  }
  
  /**
   * 监控内存使用
   */
  async monitorMemory(): Promise<{
    usedMB: number;
    totalMB: number;
    usagePercent: number;
  }> {
    if ('memory' in performance) {
      const mem = performance.memory as any;
      const usedMB = mem.usedJSHeapSize / 1024 / 1024;
      const totalMB = mem.totalJSHeapSize / 1024 / 1024;
      
      return {
        usedMB,
        totalMB,
        usagePercent: (usedMB / totalMB) * 100,
      };
    }
    
    return { usedMB: 0, totalMB: 0, usagePercent: 0 };
  }
  
  /**
   * 监控网络请求性能
   */
  async measureNetworkRequest(url: string): Promise<{
    latency: number;
    size: number;
    duration: number;
  }> {
    const start = performance.now();
    
    const response = await fetch(url, {
      headers: { 'X-Performance-Monitor': 'true' },
    });
    
    const end = performance.now();
    const duration = end - start;
    
    return {
      latency: 0, // 可以进一步细分
      size: response.size || 0,
      duration,
    };
  }
  
  /**
   * 导出性能报告
   */
  exportReport(): string {
    const report: Record<string, any> = {};
    
    for (const [componentName, metrics] of this.metrics.entries()) {
      const stats = this.getComponentStats(componentName);
      if (stats) {
        report[componentName] = stats;
      }
    }
    
    return JSON.stringify(report, null, 2);
  }
  
  /**
   * 清除所有指标
   */
  clear() {
    this.metrics.clear();
  }
}

// React Hook: 自动追踪组件渲染
export function usePerformanceTrace(componentName: string) {
  const startTime = useRef(performance.now()).current;
  
  useEffect(() => {
    const endTime = performance.now();
    const renderTime = endTime - startTime;
    
    PerformanceMonitor.getInstance().measureRender(componentName, renderTime);
  }, [componentName, startTime]);
}

// React Hook: 内存使用监控
export function useMemoryMonitor() {
  const [memory, setMemory] = useState({ usedMB: 0, totalMB: 0, usagePercent: 0 });
  
  useEffect(() => {
    const monitor = PerformanceMonitor.getInstance();
    
    const interval = setInterval(async () => {
      const mem = await monitor.monitorMemory();
      setMemory(mem);
    }, 5000); // 每 5 秒检查
    
    return () => clearInterval(interval);
  }, []);
  
  return memory;
}

export default PerformanceMonitor.getInstance();
