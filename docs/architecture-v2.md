# Ethan Agent v2 架构设计（优化版）

## 🎯 核心原则

1. **简单优先** - 能用简单的就不用复杂的
2. **渐进式复杂性** - 按需引入高级特性
3. **可观测性** - 所有关键路径都有日志和监控
4. **向后兼容** - 新旧系统共存，平滑迁移
5. **性能第一** - 每个组件都考虑性能影响

---

## 🏗️ 优化后的分层架构

```
┌─────────────────────────────────────────────────────────┐
│                    Presentation Layer                     │
│  • Android (Kotlin) / Desktop (React) / Web             │
│  • 统一的状态管理接口                                    │
│  • 实时反馈 UI 组件                                       │
└─────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────┐
│                   Service Layer                           │
│  • Task Service (任务编排)                               │
│  • Context Service (上下文管理)                          │
│  • Feedback Service (实时反馈)                           │
│  • Performance Service (性能监控)                        │
└─────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────┐
│                   Domain Layer                            │
│  • Skill Bundle Manager (技能包管理)                      │
│  • Scene Detector (场景检测)                             │
│  • Code Assistant (编程助手)                             │
│  • Memory Manager (记忆管理)                             │
└─────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────┐
│                 Infrastructure Layer                      │
│  • Kernel Adapter (内核适配层)                           │
│  • Tool Registry (工具注册表)                            │
│  • State Store (状态存储 - SQLite + Redis)               │
│  • Event Bus (轻量级事件总线)                            │
└─────────────────────────────────────────────────────────┘
```

---

## 🔑 关键设计决策

### 1. **混合事件模型**

```python
# 轻量级事件总线（仅用于跨模块通信）
class EventBus:
    def __init__(self):
        self._subscribers = {}
    
    # 同步发布（简单场景）
    def publish_sync(self, event: Event):
        for cb in self._subscribers.get(event.type, []):
            cb(event)
    
    # 异步发布（高性能场景）
    async def publish_async(self, event: Event):
        await asyncio.gather(*[
            cb(event) for cb in self._async_subscribers.get(event.type, [])
        ])

# 使用策略：
# - 简单操作：同步发布
# - 耗时操作：异步发布
# - 关键路径：双重发布（同步 + 异步）
```

### 2. **状态管理分层**

```python
class StateManager:
    """三层状态管理"""
    
    # Layer 1: 会话级状态（内存）
    session_state: Dict[str, Any]
    
    # Layer 2: 用户级状态（SQLite）
    user_state: UserStateStore
    
    # Layer 3: 全局配置（YAML + Redis 缓存）
    global_config: GlobalConfigStore
    
    def get_state(self, scope: str, key: str) -> Any:
        if scope == "session":
            return self.session_state.get(key)
        elif scope == "user":
            return self.user_state.get(key)
        else:
            return self.global_config.get(key)
```

### 3. **性能监控集成**

```python
class PerformanceMonitor:
    """全链路性能监控"""
    
    def track(self, operation: str):
        """装饰器：自动追踪操作耗时"""
        def decorator(func):
            @wraps(func)
            async def wrapper(*args, **kwargs):
                start = time.perf_counter()
                try:
                    result = await func(*args, **kwargs)
                    latency = (time.perf_counter() - start) * 1000
                    
                    # 记录指标
                    metrics.record(operation, latency)
                    
                    # 告警
                    if latency > THRESHOLD[operation]:
                        await alert(f"{operation} slow: {latency}ms")
                    
                    return result
                except Exception as e:
                    metrics.record_error(operation, str(e))
                    raise
            return wrapper
        return decorator
    
    @track("context.build")
    async def build_context(self, query: str):
        ...
```

### 4. **编程能力强化**

```python
class CodeAssistant:
    """专业编程助手"""
    
    # 核心工具链
    tools = {
        "code_read": FileReadTool(patterns=["*.py", "*.js", "*.ts"]),
        "code_write": FileWriteTool(auto_format=True),
        "code_run": ShellTool(allowed_commands=["python", "node", "npm", "pytest"]),
        "code_debug": DebuggerAdapter(),
        "code_test": TestRunner(),
        "code_review": CodeReviewTool(),
        "git_ops": GitTool(),
    }
    
    # 智能辅助
    features = {
        "auto_complete": True,      # 代码补全
        "error_explain": True,      # 错误解释
        "refactor_suggest": True,   # 重构建议
        "security_scan": True,      # 安全扫描
    }
    
    @track("code.task")
    async def execute_code_task(self, task: CodeTask) -> CodeResult:
        # 1. 分析需求
        requirements = await self.analyze_requirements(task.prompt)
        
        # 2. 生成代码
        code = await self.generate_code(requirements)
        
        # 3. 运行测试
        test_result = await self.run_tests(code)
        
        # 4. 代码审查
        review = await self.code_review(code)
        
        # 5. 返回结果
        return CodeResult(code=code, tests=test_result, review=review)
```

### 5. **实时反馈系统**

```python
class FeedbackEngine:
    """实时反馈引擎"""
    
    def __init__(self):
        self._stream = None
        self._phases = []
    
    async def start_feedback_stream(self, task_id: str):
        """开始反馈流"""
        self._stream = create_feedback_stream(task_id)
        
        # 阶段总结
        for phase in self._phases:
            await self.send_phase_summary(phase)
        
        # 进度更新
        for progress in self._stream:
            await self.send_progress(progress)
    
    async def send_phase_summary(self, phase: TaskPhase):
        """发送阶段总结"""
        feedback = {
            "type": "phase_summary",
            "phase": phase.name,
            "status": phase.status,
            "duration": phase.duration,
            "highlights": phase.highlights,
            "next_steps": phase.next_steps,
        }
        await self._stream.send(feedback)
    
    async def send_progress(self, progress: ProgressUpdate):
        """发送进度更新"""
        feedback = {
            "type": "progress",
            "step": progress.step,
            "total": progress.total,
            "message": progress.message,
            "estimated_time": progress.estimated_time,
        }
        await self._stream.send(feedback)
```

---

## 📊 性能基准

| 操作 | 目标耗时 | 当前耗时 | 优化空间 |
|------|---------|---------|---------|
| 启动应用 | < 1s | ~2s | 50% ⚡ |
| 构建 Context | < 100ms | ~300ms | 67% ⚡ |
| 首字延迟 | < 200ms | ~500ms | 60% ⚡ |
| 代码生成 | < 2s | ~5s | 60% ⚡ |
| 长程任务恢复 | < 5s | ~15s | 67% ⚡ |

---

## 🔄 迁移策略

### 从 v1 到 v2

1. **并行运行** - 新旧系统同时工作
2. **灰度发布** - 逐步切换用户
3. **数据迁移** - 自动转换旧格式
4. **回滚机制** - 一键回退到 v1

### 兼容性保证

- ✅ 所有旧 API 保持兼容
- ✅ 配置文件自动转换
- ✅ 历史数据无缝迁移
- ✅ 插件系统向后兼容

---

## 🎯 成功标准

### 技术指标
- [ ] 启动时间 < 1s
- [ ] Context 占用 < 300 tokens
- [ ] 首字延迟 < 200ms
- [ ] 99% 请求 P99 < 1s

### 用户体验
- [ ] 流畅无卡顿
- [ ] 实时反馈清晰
- [ ] 编程能力显著提升
- [ ] 场景识别准确率 > 90%

### 开发体验
- [ ] 插件热重载 < 1s
- [ ] 调试信息完整
- [ ] 文档覆盖全面
- [ ] 测试覆盖率 > 80%

---

**版本**: v2.0  
**最后更新**: 2026-11-14  
**状态**: 设计中 → 实施中 → 测试中
