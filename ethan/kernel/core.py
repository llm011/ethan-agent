"""
Ethan Kernel - 可插拔 Agent 内核系统

设计理念：
1. **内核抽象层** - 定义统一的 Agent 运行接口
2. **内核实现** - DSH、Claude SDK、或其他内核的具体实现
3. **配置驱动** - 通过 config.yaml 选择内核
4. **热切换** - 运行时动态切换内核，无需重启
5. **向后兼容** - 所有现有功能自动适配新内核

支持的内核类型：
- dsh: DeepSeek Harness 内核（默认）
- claude_sdk: Anthropic Claude Code SDK
- custom: 自定义内核
- legacy: 保留原 Ethan 内核（向后兼容）
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Protocol
import asyncio
import logging
import yaml
from pathlib import Path

logger = logging.getLogger(__name__)


# ========== 内核枚举 ==========

class KernelType(Enum):
    """支持的 kernel 类型"""
    DSH = "dsh"
    CLAUDE_SDK = "claude_sdk"
    CUSTOM = "custom"
    LEGACY = "legacy"


@dataclass
class KernelConfig:
    """内核配置"""
    type: KernelType = KernelType.DSH
    # DSH 特定配置
    dsh_config: Dict[str, Any] = field(default_factory=dict)
    # Claude SDK 特定配置
    claude_config: Dict[str, Any] = field(default_factory=dict)
    # 通用配置
    max_concurrent_tasks: int = 5
    timeout_seconds: int = 300
    enable_cache: bool = True
    cache_ttl: int = 3600
    # 日志级别
    log_level: str = "INFO"


# ========== 内核抽象层 ==========

class KernelContext(Protocol):
    """内核上下文协议"""
    
    async def initialize(self) -> None:
        """初始化内核"""
        pass
    
    async def shutdown(self) -> None:
        """关闭内核"""
        pass
    
    async def execute_task(self, task_id: str, prompt: str, context: Dict[str, Any]) -> Any:
        """执行任务"""
        pass
    
    async def resume_task(self, task_id: str, checkpoint: Dict[str, Any]) -> Any:
        """从检查点恢复任务"""
        pass
    
    async def cancel_task(self, task_id: str) -> bool:
        """取消任务"""
        pass
    
    def get_status(self, task_id: str) -> Dict[str, Any]:
        """获取任务状态"""
        pass


class BaseKernel(ABC):
    """内核基类 - 所有内核必须实现此接口"""
    
    @property
    @abstractmethod
    def name(self) -> str:
        """内核名称"""
        pass
    
    @property
    @abstractmethod
    def version(self) -> str:
        """内核版本"""
        pass
    
    @abstractmethod
    async def initialize(self, config: KernelConfig) -> None:
        """初始化内核"""
        pass
    
    @abstractmethod
    async def shutdown(self) -> None:
        """关闭内核"""
        pass
    
    @abstractmethod
    async def execute_task(self, task_id: str, prompt: str, context: Dict[str, Any]) -> Any:
        """执行任务"""
        pass
    
    @abstractmethod
    async def resume_task(self, task_id: str, checkpoint: Dict[str, Any]) -> Any:
        """从检查点恢复任务"""
        pass
    
    @abstractmethod
    async def cancel_task(self, task_id: str) -> bool:
        """取消任务"""
        pass
    
    @abstractmethod
    def get_status(self, task_id: str) -> Dict[str, Any]:
        """获取任务状态"""
        pass


# ========== 内核工厂 ==========

class KernelFactory:
    """内核工厂 - 创建和管理内核实例"""
    
    _kernels: Dict[KernelType, type[BaseKernel]] = {}
    
    @classmethod
    def register(cls, kernel_type: KernelType, kernel_class: type[BaseKernel]) -> None:
        """注册内核实现"""
        cls._kernels[kernel_type] = kernel_class
        logger.info(f"Registered kernel: {kernel_type.value} v{kernel_class().version}")
    
    @classmethod
    def create(cls, config: KernelConfig) -> BaseKernel:
        """创建内核实例"""
        if config.type not in cls._kernels:
            raise ValueError(f"Unknown kernel type: {config.type}")
        
        kernel_class = cls._kernels[config.type]
        return kernel_class()
    
    @classmethod
    def list_supported(cls) -> List[str]:
        """列出支持的内核类型"""
        return [kt.value for kt in cls._kernels.keys()]


# ========== 内核管理器 ==========

class KernelManager:
    """内核管理器 - 管理内核生命周期和热切换"""
    
    def __init__(self):
        self._current_kernel: Optional[BaseKernel] = None
        self._config: Optional[KernelConfig] = None
        self._switch_callbacks: List[Callable] = []
    
    async def initialize(self, config: KernelConfig) -> None:
        """初始化管理器"""
        self._config = config
        
        # 创建内核实例
        self._current_kernel = KernelFactory.create(config)
        await self._current_kernel.initialize(config)
        
        logger.info(f"Initialized kernel: {self._current_kernel.name} v{self._current_kernel.version}")
    
    async def switch_kernel(self, new_type: KernelType) -> None:
        """热切换内核"""
        if self._current_kernel is None:
            raise RuntimeError("Kernel manager not initialized")
        
        # 保存当前状态
        old_kernel = self._current_kernel
        old_config = self._config
        
        try:
            # 关闭旧内核
            await old_kernel.shutdown()
            
            # 创建新内核
            new_config = KernelConfig(type=new_type)
            self._current_kernel = KernelFactory.create(new_config)
            await self._current_kernel.initialize(new_config)
            
            self._config = new_config
            
            logger.info(f"Switched from {old_kernel.name} to {self._current_kernel.name}")
            
            # 通知回调
            for callback in self._switch_callbacks:
                await callback(old_kernel, self._current_kernel)
                
        except Exception as e:
            # 恢复旧内核
            await self._current_kernel.shutdown()
            self._current_kernel = old_kernel
            self._config = old_config
            await self._current_kernel.initialize(old_config)
            raise RuntimeError(f"Failed to switch kernel: {e}")
    
    def on_switch(self, callback: Callable) -> None:
        """添加内核切换回调"""
        self._switch_callbacks.append(callback)
    
    @property
    def current_kernel(self) -> Optional[BaseKernel]:
        """获取当前内核实例"""
        return self._current_kernel
    
    @property
    def config(self) -> Optional[KernelConfig]:
        """获取当前配置"""
        return self._config
    
    async def execute_task(self, task_id: str, prompt: str, context: Dict[str, Any]) -> Any:
        """委托给当前内核执行任务"""
        if self._current_kernel is None:
            raise RuntimeError("Kernel not initialized")
        
        return await self._current_kernel.execute_task(task_id, prompt, context)
    
    async def resume_task(self, task_id: str, checkpoint: Dict[str, Any]) -> Any:
        """委托给当前内核恢复任务"""
        if self._current_kernel is None:
            raise RuntimeError("Kernel not initialized")
        
        return await self._current_kernel.resume_task(task_id, checkpoint)
    
    async def cancel_task(self, task_id: str) -> bool:
        """委托给当前内核取消任务"""
        if self._current_kernel is None:
            raise RuntimeError("Kernel not initialized")
        
        return await self._current_kernel.cancel_task(task_id)
    
    def get_status(self, task_id: str) -> Dict[str, Any]:
        """获取任务状态"""
        if self._current_kernel is None:
            return {"error": "Kernel not initialized"}
        
        return self._current_kernel.get_status(task_id)


# ========== 全局管理器 ==========

_global_manager: Optional[KernelManager] = None


def get_kernel_manager() -> KernelManager:
    """获取全局内核管理器"""
    global _global_manager
    if _global_manager is None:
        _global_manager = KernelManager()
    return _global_manager


async def init_kernel(config_path: Optional[Path] = None) -> KernelManager:
    """初始化内核（从配置文件或默认配置）"""
    global _global_manager
    
    if _global_manager is None:
        _global_manager = KernelManager()
    
    if config_path and config_path.exists():
        config_data = yaml.safe_load(config_path.read_text())
        config = KernelConfig(**config_data.get('kernel', {}))
    else:
        config = KernelConfig()
    
    await _global_manager.initialize(config)
    return _global_manager


async def reset_kernel_manager() -> None:
    """重置全局内核管理器（用于测试）"""
    global _global_manager
    if _global_manager:
        await _global_manager.current_kernel.shutdown()
    _global_manager = None


# ========== 示例内核实现 ==========

class DSHKernel(BaseKernel):
    """DSH (DeepSeek Harness) 内核实现"""
    
    @property
    def name(self) -> str:
        return "DSH"
    
    @property
    def version(self) -> str:
        return "2.0.0"
    
    async def initialize(self, config: KernelConfig) -> None:
        logger.info("Initializing DSH kernel...")
        # TODO: 实现 DSH 内核初始化逻辑
    
    async def shutdown(self) -> None:
        logger.info("Shutting down DSH kernel...")
        # TODO: 实现 DSH 内核清理逻辑
    
    async def execute_task(self, task_id: str, prompt: str, context: Dict[str, Any]) -> Any:
        logger.info(f"Executing task {task_id} with DSH kernel")
        # TODO: 实现 DSH 任务执行逻辑
        return {"status": "success", "task_id": task_id}
    
    async def resume_task(self, task_id: str, checkpoint: Dict[str, Any]) -> Any:
        logger.info(f"Resuming task {task_id} with DSH kernel")
        # TODO: 实现 DSH 断点续传逻辑
        return {"status": "resumed", "task_id": task_id}
    
    async def cancel_task(self, task_id: str) -> bool:
        logger.info(f"Cancelling task {task_id}")
        # TODO: 实现 DSH 任务取消逻辑
        return True
    
    def get_status(self, task_id: str) -> Dict[str, Any]:
        return {"task_id": task_id, "status": "running"}


class ClaudeSDKKernel(BaseKernel):
    """Anthropic Claude Code SDK 内核实现"""
    
    @property
    def name(self) -> str:
        return "Claude SDK"
    
    @property
    def version(self) -> str:
        return "1.0.0"
    
    async def initialize(self, config: KernelConfig) -> None:
        logger.info("Initializing Claude SDK kernel...")
        # TODO: 实现 Claude SDK 初始化
    
    async def shutdown(self) -> None:
        logger.info("Shutting down Claude SDK kernel...")
        # TODO: 实现 Claude SDK 清理
    
    async def execute_task(self, task_id: str, prompt: str, context: Dict[str, Any]) -> Any:
        logger.info(f"Executing task {task_id} with Claude SDK")
        # TODO: 实现 Claude SDK 任务执行
        return {"status": "success", "task_id": task_id}
    
    async def resume_task(self, task_id: str, checkpoint: Dict[str, Any]) -> Any:
        logger.info(f"Resuming task {task_id} with Claude SDK")
        # TODO: 实现 Claude SDK 断点续传
        return {"status": "resumed", "task_id": task_id}
    
    async def cancel_task(self, task_id: str) -> bool:
        logger.info(f"Cancelling task {task_id}")
        # TODO: 实现 Claude SDK 任务取消
        return True
    
    def get_status(self, task_id: str) -> Dict[str, Any]:
        return {"task_id": task_id, "status": "running"}


# 注册内置内核
KernelFactory.register(KernelType.DSH, DSHKernel)
KernelFactory.register(KernelType.CLAUDE_SDK, ClaudeSDKKernel)


# ========== 配置示例 ==========

DEFAULT_KERNEL_CONFIG = """
kernel:
  type: dsh  # 可选：dsh, claude_sdk, custom, legacy
  
  # DSH 配置
  dsh_config:
    model: "deepseek-chat"
    temperature: 0.7
    max_tokens: 4096
  
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
"""
