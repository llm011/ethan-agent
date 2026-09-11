"""知识库系统 — 可扩展的外部知识来源。

默认实现：本地 Markdown 文件目录（~/.ethan/knowledge/）。
通过 adapter 机制支持第三方笔记系统（Obsidian 等）及外部 REST API。

本模块已拆分为多个子模块，此处保留为兼容 façade（对外 import 路径不变）：
- contracts   → KnowledgeItem, KnowledgeBase
- filesystem  → FilesystemKnowledgeBase
- obsidian    → ObsidianKnowledgeBase
- external    → ExternalKnowledgeBase
- notion      → NotionKnowledgeBase
"""
from .contracts import KnowledgeBase, KnowledgeItem
from .external import ExternalKnowledgeBase
from .filesystem import FilesystemKnowledgeBase
from .notion import NotionKnowledgeBase
from .obsidian import ObsidianKnowledgeBase

__all__ = ["KnowledgeItem", "KnowledgeBase", "FilesystemKnowledgeBase",
           "ObsidianKnowledgeBase", "ExternalKnowledgeBase", "NotionKnowledgeBase"]
