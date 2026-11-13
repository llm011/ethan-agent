# Ethan Agent 内核架构设计

## 🎯 核心设计理念

Ethan Agent 采用**可插拔内核架构**，支持无缝切换不同的 AI 内核（DSH、Claude SDK、或其他），同时保持 API 一致性和向后兼容性。

---

## 🏗️ 架构层次

### 1. 内核抽象层 (Kernel Core)
```
┌─────────────────────────────────────┐
│   KernelManager (全局管理器)         │
├─────────────────────────────────────┤
│   BaseKernel (抽象接口)              │
│   - initialize()                     │
│   - execute_task()                   │
│   - resume_task()                    │
│   - cancel_task()                    │
│   - get_status()                     │
└─────────────────────────────────────┘
```

### 2. 内核实现层 (Kernel Implementations)
```
┌─────────────────────────────────────┐
│   DSHKernel                         │  ← DeepSeek Harness
├─────────────────────────────────────┤
│   ClaudeSDKKernel                   │  ← Anthropic Claude
├─────────────────────────────────────┤
│   CustomKernel                      │  ← 自定义内核
├─────────────────────────────────────┤
│   LegacyKernel                      │  ← 原 Ethan 内核
└─────────────────────────────────────┘
```

### 3. 状态管理层 (State Management)
```
┌─────────────────────────────────────┐
│   TaskStateManager                  │
├─────────────────────────────────────┤
│   - 任务状态机                       │
│   - 检查点持久化                     │
│   - 断点续传                         │
│   - 崩溃恢复                         │
└─────────────────────────────────────┘
```

### 4. 插件系统 (Plugin System)
```
┌─────────────────────────────────────┐
│   PluginRegistry                    │
├─────────────────────────────────────┤
│   - 插件注册/注销                    │
│   - 生命周期管理                     │
│   - 事件钩子                         │
│   - 热重载                           │
└─────────────────────────────────────┘
```

---

## 🔧 核心组件

### KernelManager - 内核管理器

```python
from ethan.kernel.core import get_kernel_manager, init_kernel

# 初始化内核
manager = await init_kernel(Path("config.yaml"))

# 执行任务
result = await manager.execute_task(
    task_id="task_001",
    prompt="分析这份代码",
    context={"file": "main.py"}
)

# 切换内核（运行时）
await manager.switch_kernel(KernelType.CLAUDE_SDK)

# 获取任务状态
status = manager.get_status("task_001")
```

### TaskStateManager - 任务状态管理

```python
from ethan.kernel.state import get_task_manager, TaskState

# 创建任务
task = await get_task_manager().create_task(
    task_id="long_task",
    prompt="生成年度报告",
    metadata={"priority": "high"}
)

# 保存检查点
await get_task_manager().save_checkpoint(
    task_id="long_task",
    step=5,
    data={"progress": "50%", "completed_sections": ["intro", "analysis"]},
    context_snapshot={...}  # 上下文快照
)

# 从检查点恢复
step, checkpoint = await get_task_manager().resume_from_checkpoint(
    task_id="long_task",
    checkpoint_step=-1  # 最近的检查点
)

# 完成任务
await get_task_manager().complete_task(
    task_id="long_task",
    result={"report_url": "..."}
)
```

### PluginSystem - 插件系统

```python
from ethan.kernel.plugin import Plugin, PluginConfig, get_plugin_registry

class MyToolPlugin(Plugin):
    @property
    def name(self) -> str:
        return "my_tool"
    
    @property
    def version(self) -> str:
        return "1.0.0"
    
    async def initialize(self, config: PluginConfig) -> None:
        pass
    
    async def execute(self, input_data: Dict[str, Any]) -> Any:
        # 插件逻辑
        return {"result": "success"}

# 注册插件
registry = get_plugin_registry()
registry.register(MyToolPlugin())

# 配置插件
config = PluginConfig(enabled=True, timeout=60)
registry.configure("my_tool", config)

# 执行插件
result = await registry.execute("my_tool", {"input": "data"})
```

---

## 📝 配置文件

### 默认配置 (`config.yaml`)

```yaml
kernel:
  type: dsh  # 可选：dsh, claude_sdk, custom, legacy
  
  # DSH 配置
  dsh_config:
    model: "deepseek-chat"
    temperature: 0.7
    max_tokens: 4096
    top_p: 0.9
  
  # Claude SDK 配置
  claude_config:
    model: "claude-3-opus-20240229"
    api_key_env: "ANTHROPIC_API_KEY"
  
  # 通用配置
  max_concurrent_tasks: 5
  timeout_seconds: 300
  enable_cache: true
  cache_ttl: 3600
  log_level: "INFO"

plugins:
  browser:
    enabled: true
    priority: 100
  
  lark:
    enabled: true
    priority: 90
  
  knowledge:
    enabled: true
    priority: 80

tasks:
  auto_save_interval: 60  # 自动保存检查点间隔（秒）
  max_checkpoints: 50     # 最大检查点数量
  cleanup_days: 30        # 清理旧任务天数
```

---

## 🔄 内核切换流程

### 热切换示例

```python
async def switch_to_claude():
    """切换到 Claude SDK 内核"""
    manager = get_kernel_manager()
    
    # 保存当前状态
    current_state = await save_session_state()
    
    # 切换内核
    await manager.switch_kernel(KernelType.CLAUDE_SDK)
    
    # 恢复状态
    await restore_session_state(current_state)
    
    logger.info("Switched to Claude SDK kernel")
```

### 切换注意事项

1. **状态保存**: 切换前必须保存当前任务状态
2. **资源释放**: 旧内核的资源需要正确释放
3. **钩子回调**: 切换会触发 `on_switch` 回调
4. **向后兼容**: 所有现有 API 保持不变

---

## 🚀 性能优化

### 1. 异步优先
- 所有 I/O 操作异步化
- 非阻塞执行
- 并发任务限制

### 2. 缓存策略
- 结果缓存（可配置 TTL）
- 智能失效
- 内存 + 磁盘双重缓存

### 3. 增量更新
- 只处理变化的部分
- 避免全量重算
- 差分同步

---

## 🛡️ 容错机制

### 1. 自动重试
```python
config = PluginConfig(
    retry_count=3,
    retry_delay=1.0,
    backoff_multiplier=2.0
)
```

### 2. 超时保护
```python
try:
    result = await asyncio.wait_for(
        task.execute(),
        timeout=300
    )
except asyncio.TimeoutError:
    # 超时处理
    await task.pause()
```

### 3. 崩溃恢复
- 自动保存检查点
- 重启后从最近检查点恢复
- 状态一致性保证

---

## 📊 监控指标

### 内核健康度
- 响应时间 P50/P95/P99
- 错误率
- 成功率
- 并发任务数

### 任务统计
- 平均执行时长
- 检查点频率
- 恢复成功率
- 取消率

---

## 🎯 使用场景

### 场景 1: 快速原型开发
```yaml
kernel:
  type: dsh
  dsh_config:
    model: "deepseek-fast"  # 快速模型
```

### 场景 2: 高质量输出
```yaml
kernel:
  type: claude_sdk
  claude_config:
    model: "claude-3-opus"  # 高质量模型
```

### 场景 3: 长程任务
```yaml
tasks:
  auto_save_interval: 30   # 频繁保存
  max_checkpoints: 100     # 更多检查点
```

---

## 📚 扩展指南

### 添加新内核

1. 继承 `BaseKernel`
2. 实现所有抽象方法
3. 注册到 `KernelFactory`

```python
class MyCustomKernel(BaseKernel):
    @property
    def name(self) -> str:
        return "MyCustom"
    
    @property
    def version(self) -> str:
        return "1.0.0"
    
    async def initialize(self, config):
        # 初始化逻辑
        pass
    
    # ... 其他方法
    
KernelFactory.register(KernelType.CUSTOM, MyCustomKernel)
```

### 添加新插件

1. 继承 `Plugin`
2. 实现核心方法
3. 注册到注册表

```python
class NewFeaturePlugin(Plugin):
    @property
    def name(self) -> str:
        return "new_feature"
    
    async def execute(self, input_data):
        # 实现新功能
        return {"result": "success"}

registry.register(NewFeaturePlugin())
```

---

## 🔄 迁移指南

### 从旧版本迁移

1. **备份数据**: 导出所有任务和检查点
2. **升级内核**: 运行 `ethan upgrade`
3. **验证功能**: 测试关键功能
4. **监控指标**: 观察性能变化

### 回滚方案

```bash
# 回滚到旧内核
ethan kernel rollback --to=legacy
```

---

**版本**: v2.0.0  
**最后更新**: 2026-11-14  
**作者**: Ethan Team
