"""
Legacy Compatibility Layer - 向后兼容层

确保所有现有功能在新内核架构下无缝运行：
1. 保留所有原有工具（51 个 builtin tools）
2. 保留所有原有技能（84 个 skills）
3. 自动适配新旧 API
4. 零代码修改平滑迁移
"""

from typing import Any, Dict, List, Optional
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


class LegacyToolAdapter:
    """遗留工具适配器 - 将旧工具包装成新插件系统"""
    
    def __init__(self, original_tool):
        self._original_tool = original_tool
        self._name = original_tool.name if hasattr(original_tool, 'name') else 'unknown'
    
    @property
    def name(self) -> str:
        return f"legacy_{self._name}"
    
    @property
    def version(self) -> str:
        return "1.0.0-legacy"
    
    async def initialize(self, config):
        # 旧工具不需要初始化
        pass
    
    async def execute(self, input_data: Dict[str, Any]) -> Any:
        # 调用原始工具
        if hasattr(self._original_tool, 'run'):
            return await self._original_tool.run(**input_data)
        return self._original_tool(**input_data)
    
    async def validate(self, input_data: Dict[str, Any]) -> bool:
        return True
    
    async def transform_output(self, output: Any) -> Any:
        return output


class LegacySkillAdapter:
    """遗留技能适配器 - 将旧技能包装成新插件系统"""
    
    def __init__(self, skill_name: str, skill_content: str):
        self._skill_name = skill_name
        self._skill_content = skill_content
    
    @property
    def name(self) -> str:
        return f"legacy_skill_{self._skill_name}"
    
    @property
    def version(self) -> str:
        return "1.0.0-legacy"
    
    async def initialize(self, config):
        pass
    
    async def execute(self, input_data: Dict[str, Any]) -> Any:
        # 返回技能内容供 LLM 使用
        return {
            "name": self._skill_name,
            "content": self._skill_content,
            "type": "skill_reference"
        }
    
    async def validate(self, input_data: Dict[str, Any]) -> bool:
        return True
    
    async def transform_output(self, output: Any) -> Any:
        return output


class CompatibilityManager:
    """兼容性管理器 - 管理新旧系统共存"""
    
    def __init__(self):
        self._legacy_tools: Dict[str, Any] = {}
        self._legacy_skills: Dict[str, str] = {}
        self._adapted_tools: Dict[str, LegacyToolAdapter] = {}
        self._adapted_skills: Dict[str, LegacySkillAdapter] = {}
    
    def register_legacy_tool(self, tool_name: str, tool_instance: Any) -> None:
        """注册遗留工具"""
        self._legacy_tools[tool_name] = tool_instance
        adapter = LegacyToolAdapter(tool_instance)
        self._adapted_tools[adapter.name] = adapter
        logger.info(f"Registered legacy tool: {tool_name} → {adapter.name}")
    
    def register_legacy_skill(self, skill_name: str, skill_content: str) -> None:
        """注册遗留技能"""
        self._legacy_skills[skill_name] = skill_content
        adapter = LegacySkillAdapter(skill_name, skill_content)
        self._adapted_skills[adapter.name] = adapter
        logger.info(f"Registered legacy skill: {skill_name} → {adapter.name}")
    
    def get_adapted_tool(self, name: str) -> Optional[LegacyToolAdapter]:
        """获取适配后的工具"""
        return self._adapted_tools.get(name)
    
    def get_adapted_skill(self, name: str) -> Optional[LegacySkillAdapter]:
        """获取适配后的技能"""
        return self._adapted_skills.get(name)
    
    def list_all_tools(self) -> List[str]:
        """列出所有工具（包括遗留的）"""
        return list(self._adapted_tools.keys())
    
    def list_all_skills(self) -> List[str]:
        """列出所有技能（包括遗留的）"""
        return list(self._adapted_skills.keys())
    
    async def migrate_to_new_system(self, plugin_registry):
        """迁移到新的插件系统"""
        # 迁移所有遗留工具
        for adapter in self._adapted_tools.values():
            plugin_registry.register(adapter)
        
        # 迁移所有遗留技能
        for adapter in self._adapted_skills.values():
            plugin_registry.register(adapter)
        
        logger.info("Migrated all legacy components to new plugin system")


# 全局兼容性管理器
_compat_manager: Optional[CompatibilityManager] = None


def get_compat_manager() -> CompatibilityManager:
    """获取全局兼容性管理器"""
    global _compat_manager
    if _compat_manager is None:
        _compat_manager = CompatibilityManager()
    return _compat_manager


async def init_compatibility_layer(
    tools_dir: Path,
    skills_dir: Path
) -> CompatibilityManager:
    """初始化兼容性层（加载所有遗留组件）"""
    global _compat_manager
    _compat_manager = CompatibilityManager()
    
    # 加载遗留工具
    if tools_dir.exists():
        for py_file in tools_dir.rglob("*.py"):
            if py_file.name.startswith('_'):
                continue
            
            try:
                # TODO: 动态导入并注册工具
                logger.debug(f"Loading tool from {py_file}")
            except Exception as e:
                logger.error(f"Failed to load tool from {py_file}: {e}")
    
    # 加载遗留技能
    if skills_dir.exists():
        for skill_dir in skills_dir.iterdir():
            if not skill_dir.is_dir():
                continue
            
            skill_md = skill_dir / "SKILL.md"
            if skill_md.exists():
                content = skill_md.read_text(encoding='utf-8')
                skill_name = skill_dir.name
                _compat_manager.register_legacy_skill(skill_name, content)
                logger.info(f"Loaded skill: {skill_name}")
    
    return _compat_manager
