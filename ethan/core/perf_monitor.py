"""性能监控工具 — 用于 profiling agent 启动和运行时的性能瓶颈。"""
import time
import logging
from functools import wraps
from typing import Callable, Any
from contextlib import contextmanager
import json
from pathlib import Path

logger = logging.getLogger(__name__)


class PerfMonitor:
    """性能监控器 — 记录关键操作的耗时。"""
    
    def __init__(self):
        self._timings: dict[str, list[float]] = {}
        self._enabled = False
    
    def enable(self):
        """启用性能监控。"""
        self._enabled = True
        self._timings.clear()
        logger.info("性能监控已启用")
    
    def disable(self):
        """禁用性能监控。"""
        self._enabled = False
        logger.info("性能监控已禁用")
    
    @contextmanager
    def section(self, name: str):
        """上下文管理器：记录某段代码的耗时。"""
        if not self._enabled:
            yield
            return
        
        start = time.perf_counter()
        try:
            yield
        finally:
            elapsed = time.perf_counter() - start
            if name not in self._timings:
                self._timings[name] = []
            self._timings[name].append(elapsed)
            
            # 超过 100ms 就警告
            if elapsed > 0.1:
                logger.warning("[perf] %s 耗时 %.3fs", name, elapsed)
    
    def report(self) -> str:
        """生成性能报告。"""
        if not self._timings:
            return "无性能数据"
        
        lines = ["=== 性能报告 ==="]
        for name, times in sorted(self._timings.items(), key=lambda x: sum(x[1]), reverse=True):
            avg = sum(times) / len(times)
            total = sum(times)
            max_t = max(times)
            lines.append(f"{name}:")
            lines.append(f"  总耗时：{total:.3f}s")
            lines.append(f"  平均：{avg:.3f}s")
            lines.append(f"  最大：{max_t:.3f}s")
            lines.append(f"  调用次数：{len(times)}")
        
        return "\n".join(lines)
    
    def save_report(self, path: Path | str):
        """保存性能报告到文件。"""
        report = {
            name: {
                "avg": sum(times) / len(times),
                "total": sum(times),
                "max": max(times),
                "count": len(times),
                "samples": times[-10:]  # 最后 10 次采样
            }
            for name, times in self._timings.items()
        }
        
        path = Path(path)
        path.write_text(json.dumps(report, indent=2, ensure_ascii=False))
        logger.info("性能报告已保存到 %s", path)


# 全局实例
_perf_monitor = PerfMonitor()


def get_perf_monitor() -> PerfMonitor:
    """获取全局性能监控器。"""
    return _perf_monitor


def timed(name: str | None = None):
    """装饰器：标记函数为性能监控点。"""
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            monitor = get_perf_monitor()
            func_name = name or func.__name__
            
            with monitor.section(func_name):
                return func(*args, **kwargs)
        
        return wrapper
    return decorator


@contextmanager
def profile_section(name: str):
    """上下文管理器：快速性能分析。"""
    monitor = get_perf_monitor()
    with monitor.section(name):
        yield


def check_startup_performance():
    """检查启动性能，输出关键路径的耗时。"""
    monitor = get_perf_monitor()
    
    # 检查 SkillRegistry 加载时间
    if "SkillRegistry.load" in monitor._timings:
        times = monitor._timings["SkillRegistry.load"]
        avg = sum(times) / len(times)
        if avg > 0.5:
            logger.warning("技能加载过慢：平均 %.3fs", avg)
    
    # 检查 ToolRegistry 构建时间
    if "ToolRegistry.build" in monitor._timings:
        times = monitor._timings["ToolRegistry.build"]
        avg = sum(times) / len(times)
        if avg > 0.3:
            logger.warning("工具注册过慢：平均 %.3fs", avg)


def enable_fast_mode():
    """启用快速模式：跳过非必要的性能开销。"""
    logger.info("启用快速模式")
    # 这里可以添加更多快速模式的逻辑
    # 例如：跳过某些可选工具的注册、减少 skill 注入等
