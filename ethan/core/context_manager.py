"""
Context Manager - 动态上下文管理

功能：
1. 根据场景自动选择技能包
2. 运行时动态加载技能
3. Context 压缩优化
4. 向后兼容旧系统
"""

from typing import Dict, List, Optional, Any
import logging
from pathlib import Path
import asyncio

from ethan.core.skill_bundle import get_bundle_manager, SkillBundleManager

logger = logging.getLogger(__name__)


class ContextManager:
    """上下文管理器 - 智能构建和优化 Prompt"""
    
    def __init__(self):
        self.bundle_manager = get_bundle_manager()
        self._scene_cache: Dict[str, str] = {}  # 场景缓存
        
    async def build_context(self, query: str, user_id: str = "") -> str:
        """构建优化的上下文"""
        # 1. 检测场景
        scene = self._detect_scene(query)
        
        # 2. 获取对应的技能包
        bundle_config = self._get_bundle_config_for_scene(scene)
        
        # 3. 构建上下文
        context_parts = []
        
        # 始终注入 Core
        context_parts.append(await self._inject_bundle("core"))
        
        # 根据场景注入其他包
        for bundle_name in bundle_config.get("bundles", []):
            if await self._should_load_bundle(bundle_name, query):
                context_parts.append(await self._inject_bundle(bundle_name))
        
        # 合并并压缩
        full_context = "\n\n".join(context_parts)
        compressed = self._compress_context(full_context)
        
        logger.info(f"Built context for scene '{scene}' with {len(context_parts)} bundles")
        return compressed
    
    def _detect_scene(self, query: str) -> str:
        """检测用户意图场景"""
        query_lower = query.lower()
        
        # 场景匹配规则（优先级从高到低）
        scenes = {
            "development": ["代码", "debug", "git", "test", "deploy", "python", "java", "javascript"],
            "creative": ["PPT", "视频", "画图", "设计", "创作", "写歌", "剪辑"],
            "research": ["论文", "分析", "调研", "对比", "研究", "arxiv", "文献"],
            "productivity": ["飞书", "文档", "邮件", "日程", "会议", "报告"],
            "daily_chat": ["你好", "在吗", "聊聊", "今天", "天气", "新闻"],
            "general": [],  # 默认场景
        }
        
        for scene, keywords in scenes.items():
            if scene == "general":
                continue
            if any(kw in query_lower for kw in keywords):
                return scene
        
        return "general"
    
    def _get_bundle_config_for_scene(self, scene: str) -> Dict[str, Any]:
        """获取场景对应的技能包配置"""
        configs = {
            "development": {
                "bundles": ["core", "development"],
                "max_tokens": 600,
            },
            "creative": {
                "bundles": ["core", "creative"],
                "max_tokens": 800,
            },
            "research": {
                "bundles": ["core", "research"],
                "max_tokens": 700,
            },
            "productivity": {
                "bundles": ["core", "flow"],
                "max_tokens": 750,
            },
            "daily_chat": {
                "bundles": ["core"],
                "max_tokens": 200,
            },
            "general": {
                "bundles": ["core"],
                "max_tokens": 300,
            },
        }
        
        return configs.get(scene, configs["general"])
    
    async def _should_load_bundle(self, bundle_name: str, query: str) -> bool:
        """判断是否应该加载该技能包"""
        if bundle_name == "core":
            return True
        
        # 检查是否在已启用列表中
        enabled = self.bundle_manager.get_enabled_bundles()
        if bundle_name in enabled:
            return True
        
        # 检查触发关键词
        bundle = self.bundle_manager._get_bundle(bundle_name)
        if bundle and bundle.triggers:
            query_lower = query.lower()
            return any(trigger.lower() in query_lower for trigger in bundle.triggers)
        
        return False
    
    async def _inject_bundle(self, bundle_name: str) -> str:
        """注入单个技能包的内容"""
        bundle = self.bundle_manager._get_bundle(bundle_name)
        if not bundle:
            return ""
        
        lines = [f"# [{bundle.name.upper()} BUNDLE]"]
        lines.append(f"{bundle.description}")
        lines.append("")
        
        for skill_name in bundle.skills:
            if skill_name in self.bundle_manager._skill_registry:
                content = self.bundle_manager._skill_registry[skill_name]
                compressed = self._compress_skill(content)
                lines.append(f"## {skill_name}")
                lines.append(compressed[:500])
                lines.append("")
        
        return "\n".join(lines)
    
    def _compress_skill(self, content: str) -> str:
        """压缩技能内容"""
        lines = content.split('\n')
        compressed = []
        
        for line in lines:
            stripped = line.strip()
            
            # 保留关键信息
            if stripped.startswith('trigger:') or stripped.startswith('description:'):
                compressed.append(stripped)
            elif len(compressed) < 8:  # 最多保留前 8 行
                compressed.append(line)
        
        return '\n'.join(compressed)
    
    def _compress_context(self, context: str) -> str:
        """压缩整个上下文"""
        lines = context.split('\n')
        result = []
        token_count = 0
        max_tokens = 2000
        
        for line in lines:
            if token_count >= max_tokens:
                break
            
            result.append(line)
            token_count += len(line) // 4  # 粗略估算
        
        return '\n'.join(result)
    
    def suggest_bundles(self, query: str) -> List[str]:
        """推荐应该启用的技能包"""
        scene = self._detect_scene(query)
        config = self._get_bundle_config_for_scene(scene)
        
        suggested = []
        for bundle_name in config.get("bundles", []):
            if bundle_name != "core" and bundle_name not in self.bundle_manager.get_enabled_bundles():
                suggested.append(bundle_name)
        
        return suggested


# 全局实例
_context_manager: Optional[ContextManager] = None


def get_context_manager() -> ContextManager:
    """获取全局上下文管理器"""
    global _context_manager
    if _context_manager is None:
        _context_manager = ContextManager()
    return _context_manager
