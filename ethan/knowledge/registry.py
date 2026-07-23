"""知识库后端工厂 — 根据配置返回对应的 KnowledgeBase 实例。"""
from pathlib import Path

from ethan.knowledge.base import (
    ExternalKnowledgeBase,
    FilesystemKnowledgeBase,
    KnowledgeBase,
    ObsidianKnowledgeBase,
)

# per-user 实例缓存
_instances: dict[str, KnowledgeBase] = {}


def get_knowledge_backend(user_id: str) -> KnowledgeBase:
    """根据配置获取当前用户对应的知识库后端实例（带缓存）。"""
    if user_id in _instances:
        return _instances[user_id]

    from ethan.core.config import get_config
    config = get_config()
    kb_cfg = config.tools.knowledge

    backend = kb_cfg.backend

    if backend == "obsidian":
        vault_path = kb_cfg.obsidian_vault_path
        if not vault_path:
            import os
            vault_path = os.environ.get("OBSIDIAN_VAULT_PATH", "")
        if not vault_path:
            # fallback to filesystem
            instance = _create_filesystem_backend()
        else:
            instance = ObsidianKnowledgeBase(
                vault_path=Path(vault_path),
                folder=kb_cfg.obsidian_folder or "Knowledge",
            )
    elif backend == "external":
        base_url = kb_cfg.external_base_url
        api_key = kb_cfg.external_api_key
        if not base_url:
            # fallback to filesystem
            instance = _create_filesystem_backend()
        else:
            instance = ExternalKnowledgeBase(base_url=base_url, api_key=api_key)
    else:
        # default: filesystem
        instance = _create_filesystem_backend()

    _instances[user_id] = instance
    return instance


def _create_filesystem_backend() -> FilesystemKnowledgeBase:
    from ethan.core.paths import user_knowledge_dir
    return FilesystemKnowledgeBase(user_knowledge_dir())
