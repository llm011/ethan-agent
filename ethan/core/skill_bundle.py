"""
Ethan Skill Bundles - 智能技能包系统

设计理念：
1. Core Bundle (必选) - 日常对话必备能力 (~150 tokens)
2. Flow Bundle (可选) - 工作效率场景 (~600 tokens)
3. Power Bundle (按需) - 深度任务场景 (~2000 tokens)

策略：
- 默认只注入 Core Bundle
- 根据场景自动推荐其他 Bundle
- 运行时动态加载，无需重启
"""

from dataclasses import dataclass, field
from typing import Dict, List, Set, Optional
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class SkillBundle:
    """技能包定义"""
    name: str
    description: str
    max_tokens: int  # 最大 Context 占用
    auto_enable: bool = False  # 是否自动启用
    triggers: List[str] = field(default_factory=list)  # 触发关键词
    skills: List[str] = field(default_factory=list)  # 包含的技能名
    priority: int = 0  # 优先级
    
    @property
    def is_core(self) -> bool:
        return self.name == "core"


# ========== Core Bundle - 核心能力（默认启用） ==========
CORE_BUNDLE = SkillBundle(
    name="core",
    description="基础对话能力：文件操作、命令执行、搜索、记忆管理",
    max_tokens=180,
    auto_enable=True,
    priority=100,
    skills=[
        "file_read",           # 读取文件
        "file_write",          # 写入文件
        "file_list",           # 列出文件
        "shell",               # 执行命令
        "web_search",          # 网络搜索
        "web_fetch",           # 网页抓取
        "recall_memory",       # 回忆记忆
        "memory_write",        # 写入记忆
        "schedule_create",     # 创建定时任务
        "schedule_list",       # 列出任务
        "knowledge_search",    # 知识库搜索
        "ui_card",             # 结构化卡片
    ]
)


# ========== Flow Bundle - 效率场景（可选） ==========
FLOW_BUNDLE = SkillBundle(
    name="flow",
    description="工作效率工具：浏览器自动化、飞书集成、文档处理",
    max_tokens=550,
    auto_enable=False,
    triggers=["飞书", "browser", "网页", "文档", "PPT", "报告"],
    skills=[
        "use-browser",         # 本机浏览器操作
        "agent-browser",       # 隔离浏览器
        "lark_chat_messages",  # 飞书消息
        "lark_calendar_events", # 飞书日历
        "lark_message_send",   # 飞书发送
        "doc_save",            # 文档保存
        "doc_list",            # 文档列表
        "ppt_generate",        # PPT生成
        "rg_search",           # 内容搜索
        "fd_find",             # 文件搜索
    ]
)


# ========== Power Bundle - 深度场景（按需） ==========
POWER_BUNDLES = {
    "development": SkillBundle(
        name="development",
        description="开发工具：代码审查、调试、Git 集成",
        max_tokens=400,
        auto_enable=False,
        triggers=["代码", "debug", "git", "test", "deploy"],
        skills=[
            "code_review",       # 代码审查
            "install_skill",     # 安装技能
            "skill_create",      # 创建技能
        ]
    ),
    "creative": SkillBundle(
        name="creative",
        description="创意工具：PPT、视频、图片、可视化",
        max_tokens=600,
        auto_enable=False,
        triggers=["PPT", "视频", "画图", "设计", "创作"],
        skills=[
            "ppt_generate",      # PPT生成
            "article_to_video",  # 文章转视频
            "visualization",     # 图表可视化
            "deliver_file",      # 文件交付
        ]
    ),
    "research": SkillBundle(
        name="research",
        description="研究工具：深度调研、论文分析、数据对比",
        max_tokens=450,
        auto_enable=False,
        triggers=["论文", "分析", "调研", "对比", "研究"],
        skills=[
            "deep_research",     # 深度调研
            "paper_analysis",    # 论文分析
            "arxiv",             # arXiv查询
        ]
    ),
}


class SkillBundleManager:
    """技能包管理器 - 智能管理和加载技能包"""
    
    def __init__(self):
        self._enabled_bundles: Set[str] = {"core"}
        self._bundle_cache: Dict[str, str] = {}  # 缓存已压缩的技能内容
        self._skill_registry: Dict[str, str] = {}  # 技能名称 → 内容映射
        
    def register_skill(self, skill_name: str, content: str) -> None:
        """注册技能内容"""
        self._skill_registry[skill_name] = content
    
    def enable_bundle(self, bundle_name: str) -> bool:
        """启用技能包"""
        if bundle_name not in self._get_all_bundles():
            logger.warning(f"Unknown bundle: {bundle_name}")
            return False
        
        self._enabled_bundles.add(bundle_name)
        logger.info(f"Enabled bundle: {bundle_name}")
        return True
    
    def disable_bundle(self, bundle_name: str) -> bool:
        """禁用技能包"""
        if bundle_name == "core":
            logger.warning("Cannot disable core bundle")
            return False
        
        self._enabled_bundles.discard(bundle_name)
        logger.info(f"Disabled bundle: {bundle_name}")
        return True
    
    def should_activate_bundle(self, query: str, bundle_name: str) -> bool:
        """判断是否应该激活该技能包"""
        if bundle_name in self._enabled_bundles:
            return True
        
        bundle = self._get_bundle(bundle_name)
        if not bundle or not bundle.triggers:
            return False
        
        query_lower = query.lower()
        return any(trigger.lower() in query_lower for trigger in bundle.triggers)
    
    def get_enabled_bundles(self) -> List[str]:
        """获取所有启用的技能包"""
        return list(self._enabled_bundles)
    
    def _get_all_bundles(self) -> Dict[str, SkillBundle]:
        """获取所有技能包"""
        return {
            CORE_BUNDLE.name: CORE_BUNDLE,
            FLOW_BUNDLE.name: FLOW_BUNDLE,
            **POWER_BUNDLES,
        }
    
    def _get_bundle(self, name: str) -> Optional[SkillBundle]:
        """获取指定技能包"""
        all_bundles = self._get_all_bundles()
        return all_bundles.get(name)
    
    def build_context(self, query: str, max_tokens: int = 2000) -> str:
        """构建优化的 Context，只注入必要的技能"""
        context_parts = []
        total_tokens = 0
        
        # 1. 始终注入 Core Bundle
        context_parts.append(self._inject_bundle(CORE_BUNDLE))
        total_tokens += len(CORE_BUNDLE.skills) * 15  # 估算 token
        
        # 2. 检测是否需要 Flow Bundle
        if self.should_activate_bundle(query, "flow"):
            context_parts.append(self._inject_bundle(FLOW_BUNDLE))
            total_tokens += len(FLOW_BUNDLE.skills) * 15
        
        # 3. 检测是否需要 Power Bundles
        for power_name, power_bundle in POWER_BUNDLES.items():
            if self.should_activate_bundle(query, power_name):
                context_parts.append(self._inject_bundle(power_bundle))
                total_tokens += len(power_bundle.skills) * 15
        
        # 4. 合并并截断
        full_context = "\n\n".join(context_parts)
        
        # 如果超过限制，优先保留高频技能
        if len(full_context) > max_tokens:
            full_context = self._compress_context(full_context, max_tokens)
        
        logger.debug(f"Built context with {len(context_parts)} bundles, ~{total_tokens} tokens")
        return full_context
    
    def _inject_bundle(self, bundle: SkillBundle) -> str:
        """注入单个技能包的内容"""
        lines = [f"# [{bundle.name.upper()} BUNDLE]"]
        lines.append(f"{bundle.description}")
        lines.append("")
        
        for skill_name in bundle.skills:
            if skill_name in self._skill_registry:
                # 只注入关键信息
                skill_content = self._skill_registry[skill_name]
                compressed = self._compress_skill(skill_content)
                lines.append(f"## {skill_name}")
                lines.append(compressed[:500])  # 每技能最多 500 字
                lines.append("")
        
        return "\n".join(lines)
    
    def _compress_skill(self, content: str) -> str:
        """压缩单个技能内容"""
        lines = content.split('\n')
        compressed = []
        
        for line in lines:
            # 保留关键行
            if line.startswith('trigger:') or line.startswith('description:'):
                compressed.append(line.strip())
            elif len(compressed) < 10:  # 最多保留前 10 行
                compressed.append(line)
        
        return '\n'.join(compressed)
    
    def _compress_context(self, context: str, max_tokens: int) -> str:
        """压缩整个 Context"""
        # 简单实现：按技能重要性排序，保留最重要的
        lines = context.split('\n')
        result = []
        current_tokens = 0
        
        for line in lines:
            if current_tokens >= max_tokens:
                break
            
            result.append(line)
            current_tokens += len(line) // 4  # 粗略估算
        
        return '\n'.join(result)


# 全局管理器
_bundle_manager: Optional[SkillBundleManager] = None


def get_bundle_manager() -> SkillBundleManager:
    """获取全局技能包管理器"""
    global _bundle_manager
    if _bundle_manager is None:
        _bundle_manager = SkillBundleManager()
    return _bundle_manager


async def init_skill_bundles(skills_dir: Path) -> SkillBundleManager:
    """初始化技能包系统"""
    global _bundle_manager
    _bundle_manager = SkillBundleManager()
    
    # 加载所有技能到注册表
    for skill_dir in skills_dir.iterdir():
        if not skill_dir.is_dir():
            continue
        
        skill_md = skill_dir / "SKILL.md"
        if skill_md.exists():
            content = skill_md.read_text(encoding='utf-8')
            skill_name = skill_dir.name
            _bundle_manager.register_skill(skill_name, content)
    
    logger.info(f"Initialized skill bundles with {len(_bundle_manager._skill_registry)} skills")
    return _bundle_manager
