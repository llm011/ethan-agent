"""
DSH 风格插件系统核心 - 学习 DeepSeek Harness 的插件架构

设计理念：
1. 所有功能都是插件，热插拔
2. 声明式配置驱动行为
3. 增量更新，避免全量重算
4. 异步优先，非阻塞 I/O
5. 状态持久化，可恢复
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Type
import yaml
import asyncio
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class PluginConfig:
    """插件配置数据类"""
    enabled: bool = True
    priority: int = 0  # 执行优先级
    timeout: int = 30  # 超时时间（秒）
    retry_count: int = 3  # 重试次数
    cache_ttl: int = 300  # 缓存过期时间（秒）
    metadata: Dict[str, Any] = field(default_factory=dict)


class Plugin(ABC):
    """插件基类 - 所有功能都实现为此基类的子类"""
    
    @property
    @abstractmethod
    def name(self) -> str:
        """插件唯一标识符"""
        pass
    
    @property
    @abstractmethod
    def version(self) -> str:
        """插件版本号"""
        pass
    
    @property
    @abstractmethod
    def description(self) -> str:
        """插件描述"""
        pass
    
    @abstractmethod
    async def initialize(self, config: PluginConfig) -> None:
        """初始化插件"""
        pass
    
    @abstractmethod
    async def shutdown(self) -> None:
        """关闭插件"""
        pass
    
    @abstractmethod
    async def execute(self, input_data: Dict[str, Any]) -> Any:
        """执行插件逻辑"""
        pass
    
    async def validate(self, input_data: Dict[str, Any]) -> bool:
        """验证输入数据"""
        return True
    
    async def transform_output(self, output: Any) -> Any:
        """转换输出格式"""
        return output


class PluginRegistry:
    """插件注册表 - 管理所有插件的生命周期"""
    
    def __init__(self):
        self._plugins: Dict[str, Plugin] = {}
        self._configs: Dict[str, PluginConfig] = {}
        self._hooks: Dict[str, List[Callable]] = {
            'before_init': [],
            'after_init': [],
            'before_execute': [],
            'after_execute': [],
            'on_error': [],
        }
    
    def register(self, plugin: Plugin) -> None:
        """注册插件"""
        if plugin.name in self._plugins:
            logger.warning(f"Plugin {plugin.name} already registered, overwriting")
        self._plugins[plugin.name] = plugin
        logger.info(f"Registered plugin: {plugin.name} v{plugin.version}")
    
    def unregister(self, name: str) -> Optional[Plugin]:
        """注销插件"""
        plugin = self._plugins.pop(name, None)
        if plugin:
            logger.info(f"Unregistered plugin: {name}")
        return plugin
    
    def get(self, name: str) -> Optional[Plugin]:
        """获取插件实例"""
        return self._plugins.get(name)
    
    def list_all(self) -> List[Plugin]:
        """列出所有插件"""
        return list(self._plugins.values())
    
    def configure(self, name: str, config: PluginConfig) -> None:
        """配置插件"""
        self._configs[name] = config
        logger.debug(f"Configured plugin: {name}")
    
    def get_config(self, name: str) -> Optional[PluginConfig]:
        """获取插件配置"""
        return self._configs.get(name)
    
    async def initialize_all(self) -> None:
        """初始化所有已配置的插件"""
        sorted_plugins = sorted(
            self._plugins.items(),
            key=lambda x: x[1].__class__.__dict__.get('priority', 0)
        )
        
        for name, plugin in sorted_plugins:
            if not plugin.enabled:
                continue
            
            try:
                config = self._configs.get(name, PluginConfig())
                
                # 调用钩子
                for hook in self._hooks['before_init']:
                    await hook(name, plugin)
                
                await plugin.initialize(config)
                
                # 调用钩子
                for hook in self._hooks['after_init']:
                    await hook(name, plugin)
                
                logger.info(f"Initialized plugin: {name}")
            except Exception as e:
                logger.error(f"Failed to initialize plugin {name}: {e}")
                for hook in self._hooks['on_error']:
                    await hook(name, plugin, e)
    
    async def execute(self, name: str, input_data: Dict[str, Any]) -> Any:
        """执行插件"""
        plugin = self._plugins.get(name)
        if not plugin:
            raise ValueError(f"Plugin {name} not found")
        
        config = self._configs.get(name, PluginConfig())
        
        try:
            # 调用 before 钩子
            for hook in self._hooks['before_execute']:
                await hook(name, input_data)
            
            # 验证输入
            if not await plugin.validate(input_data):
                raise ValueError(f"Invalid input for plugin {name}")
            
            # 执行插件
            result = await plugin.execute(input_data)
            
            # 转换输出
            result = await plugin.transform_output(result)
            
            # 调用 after 钩子
            for hook in self._hooks['after_execute']:
                await hook(name, result)
            
            return result
            
        except Exception as e:
            logger.error(f"Error executing plugin {name}: {e}")
            for hook in self._hooks['on_error']:
                await hook(name, input_data, e)
            raise
    
    def add_hook(self, event: str, callback: Callable) -> None:
        """添加事件钩子"""
        if event in self._hooks:
            self._hooks[event].append(callback)
            logger.debug(f"Added hook for event: {event}")
        else:
            logger.warning(f"Unknown event: {event}")


class PluginLoader:
    """插件加载器 - 从目录或配置文件加载插件"""
    
    def __init__(self, registry: PluginRegistry):
        self.registry = registry
    
    async def load_from_directory(self, directory: Path) -> int:
        """从目录加载插件"""
        count = 0
        for path in directory.rglob("*.py"):
            if path.name.startswith('_'):
                continue
            
            try:
                module = await self._import_module(path)
                plugins = self._extract_plugins(module)
                
                for plugin in plugins:
                    self.registry.register(plugin)
                    count += 1
                    
            except Exception as e:
                logger.error(f"Failed to load plugin from {path}: {e}")
        
        return count
    
    async def _import_module(self, path: Path) -> Any:
        """动态导入模块"""
        import importlib.util
        spec = importlib.util.spec_from_file_location(path.stem, path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    
    def _extract_plugins(self, module: Any) -> List[Plugin]:
        """从模块中提取插件实例"""
        plugins = []
        for attr_name in dir(module):
            attr = getattr(module, attr_name)
            if (isinstance(attr, type) and 
                issubclass(attr, Plugin) and 
                attr != Plugin and
                hasattr(attr, 'name') and
                hasattr(attr, 'version')):
                plugins.append(attr())
        return plugins
    
    async def load_from_config(self, config_path: Path) -> None:
        """从配置文件加载插件配置"""
        if not config_path.exists():
            return
        
        config = yaml.safe_load(config_path.read_text())
        for name, cfg in config.get('plugins', {}).items():
            plugin_config = PluginConfig(**cfg)
            self.registry.configure(name, plugin_config)


# 全局插件注册表
_global_registry: Optional[PluginRegistry] = None


def get_plugin_registry() -> PluginRegistry:
    """获取全局插件注册表"""
    global _global_registry
    if _global_registry is None:
        _global_registry = PluginRegistry()
    return _global_registry


def reset_plugin_registry() -> None:
    """重置全局插件注册表（用于测试）"""
    global _global_registry
    _global_registry = None
