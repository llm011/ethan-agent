"""
Event Bus - 事件驱动架构核心

设计理念：
1. 发布/订阅模式，解耦模块间通信
2. 异步非阻塞，高并发支持
3. 类型安全，泛型支持
4. 性能优化，减少锁竞争
5. 可观测性，完整事件追踪
"""

from typing import Any, Callable, Dict, List, Optional, TypeVar, Generic
from dataclasses import dataclass
from enum import Enum
import asyncio
import logging
import time
from functools import wraps
import uuid

logger = logging.getLogger(__name__)

T = TypeVar('T')


class EventType(Enum):
    """事件类型枚举"""
    TASK_STARTED = "task.started"
    TASK_PROGRESS = "task.progress"
    TASK_COMPLETED = "task.completed"
    TASK_FAILED = "task.failed"
    TASK_CANCELLED = "task.cancelled"
    
    CONTEXT_BUILT = "context.built"
    SKILL_LOADED = "skill.loaded"
    SKILL_UNLOADED = "skill.unloaded"
    
    PERFORMANCE_ALERT = "performance.alert"
    MEMORY_HIGH = "memory.high"
    CPU_HIGH = "cpu.high"
    
    USER_INTERACTION = "user.interaction"
    CONSENT_REQUESTED = "consent.requested"
    CONSENT_GRANTED = "consent.granted"
    CONSENT_DENIED = "consent.denied"


@dataclass
class Event(Generic[T]):
    """事件基类"""
    event_type: EventType
    event_id: str
    timestamp: float
    source: str
    data: T
    metadata: Dict[str, Any] = None
    
    def __post_init__(self):
        if self.event_id is None:
            self.event_id = str(uuid.uuid4())
        if self.metadata is None:
            self.metadata = {}


class EventBus:
    """高性能事件总线"""
    
    def __init__(self, max_queue_size: int = 10000):
        self._subscribers: Dict[EventType, List[Callable]] = {}
        self._async_subscribers: Dict[EventType, List[Callable]] = {}
        self._event_history: List[Event] = []
        self._max_history = 1000
        self._queue: asyncio.Queue = asyncio.Queue(maxsize=max_queue_size)
        self._running = False
        self._processor_task: Optional[asyncio.Task] = None
        
        # 性能指标
        self._events_published = 0
        self._events_processed = 0
        self._avg_latency_ms = 0.0
        
    async def start(self) -> None:
        """启动事件处理器"""
        if self._running:
            return
        
        self._running = True
        self._processor_task = asyncio.create_task(self._process_queue())
        logger.info("Event bus started")
    
    async def stop(self) -> None:
        """停止事件处理器"""
        self._running = False
        if self._processor_task:
            await self._processor_task
        logger.info("Event bus stopped")
    
    def subscribe(self, event_type: EventType, callback: Callable[[Event], None]) -> None:
        """订阅同步事件"""
        if event_type not in self._subscribers:
            self._subscribers[event_type] = []
        self._subscribers[event_type].append(callback)
        logger.debug(f"Subscribed to {event_type.value}")
    
    def subscribe_async(self, event_type: EventType, callback: Callable[[Event], None]) -> None:
        """订阅异步事件"""
        if event_type not in self._async_subscribers:
            self._async_subscribers[event_type] = []
        self._async_subscribers[event_type].append(callback)
        logger.debug(f"Async subscribed to {event_type.value}")
    
    def unsubscribe(self, event_type: EventType, callback: Callable) -> None:
        """取消订阅"""
        if event_type in self._subscribers:
            self._subscribers[event_type] = [cb for cb in self._subscribers[event_type] if cb != callback]
        if event_type in self._async_subscribers:
            self._async_subscribers[event_type] = [cb for cb in self._async_subscribers[event_type] if cb != callback]
    
    async def publish(self, event: Event) -> None:
        """发布事件（异步）"""
        try:
            await self._queue.put(event)
            self._events_published += 1
            
            # 记录历史
            self._event_history.append(event)
            if len(self._event_history) > self._max_history:
                self._event_history.pop(0)
            
            logger.debug(f"Published event: {event.event_type.value} (id: {event.event_id[:8]})")
        except asyncio.QueueFull:
            logger.warning(f"Event queue full, dropping event: {event.event_type.value}")
    
    def publish_sync(self, event: Event) -> None:
        """发布事件（同步，用于测试或简单场景）"""
        callbacks = self._subscribers.get(event.event_type, [])
        for callback in callbacks:
            try:
                callback(event)
            except Exception as e:
                logger.error(f"Error in sync callback for {event.event_type.value}: {e}")
        
        async_callbacks = self._async_subscribers.get(event.event_type, [])
        for callback in async_callbacks:
            try:
                # 在后台执行
                asyncio.create_task(callback(event))
            except Exception as e:
                logger.error(f"Error in async callback for {event.event_type.value}: {e}")
    
    async def _process_queue(self) -> None:
        """处理事件队列"""
        while self._running:
            try:
                event = await asyncio.wait_for(self._queue.get(), timeout=1.0)
                start_time = time.perf_counter()
                
                # 调用同步回调
                callbacks = self._subscribers.get(event.event_type, [])
                for callback in callbacks:
                    try:
                        callback(event)
                    except Exception as e:
                        logger.error(f"Error in sync callback: {e}")
                
                # 调用异步回调
                async_callbacks = self._async_subscribers.get(event.event_type, [])
                for callback in async_callbacks:
                    try:
                        await callback(event)
                    except Exception as e:
                        logger.error(f"Error in async callback: {e}")
                
                # 更新性能指标
                latency = (time.perf_counter() - start_time) * 1000
                self._events_processed += 1
                self._avg_latency_ms = (
                    self._avg_latency_ms * 0.9 + latency * 0.1
                )
                
            except asyncio.TimeoutError:
                continue
            except Exception as e:
                logger.error(f"Error processing event queue: {e}")
    
    def get_stats(self) -> Dict[str, Any]:
        """获取事件总线统计信息"""
        return {
            "events_published": self._events_published,
            "events_processed": self._events_processed,
            "avg_latency_ms": self._avg_latency_ms,
            "queue_size": self._queue.qsize(),
            "history_size": len(self._event_history),
        }
    
    def get_recent_events(self, limit: int = 50) -> List[Event]:
        """获取最近的事件"""
        return self._event_history[-limit:]


# 全局事件总线实例
_global_bus: Optional[EventBus] = None


def get_event_bus() -> EventBus:
    """获取全局事件总线"""
    global _global_bus
    if _global_bus is None:
        _global_bus = EventBus()
    return _global_bus


async def init_event_bus() -> EventBus:
    """初始化事件总线"""
    global _global_bus
    _global_bus = EventBus()
    await _global_bus.start()
    return _global_bus


# 装饰器：自动发布事件
def on_event(event_type: EventType, source: str = ""):
    """装饰器：函数执行前后发布事件"""
    def decorator(func: Callable):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            bus = get_event_bus()
            
            # 发布开始事件
            start_event = Event(
                event_type=EventType.TASK_STARTED,
                event_id=None,
                timestamp=time.time(),
                source=source or func.__name__,
                data={"function": func.__name__},
            )
            await bus.publish(start_event)
            
            try:
                result = await func(*args, **kwargs)
                
                # 发布完成事件
                complete_event = Event(
                    event_type=EventType.TASK_COMPLETED,
                    event_id=None,
                    timestamp=time.time(),
                    source=source or func.__name__,
                    data={"function": func.__name__, "result": result},
                )
                await bus.publish(complete_event)
                
                return result
                
            except Exception as e:
                # 发布失败事件
                error_event = Event(
                    event_type=EventType.TASK_FAILED,
                    event_id=None,
                    timestamp=time.time(),
                    source=source or func.__name__,
                    data={"function": func.__name__, "error": str(e)},
                )
                await bus.publish(error_event)
                raise
        
        return wrapper
    return decorator
