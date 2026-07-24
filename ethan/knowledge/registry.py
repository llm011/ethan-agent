"""知识库后端工厂 — 根据配置返回对应的 KnowledgeBase 实例。

缓存策略：按配置指纹（backend + 关键参数）缓存，配置变更后自动失效。
tools.knowledge 是全局配置（非 per-user），故实例也全局共享。
"""
from pathlib import Path

from ethan.knowledge.base import (
    ExternalKnowledgeBase,
    FilesystemKnowledgeBase,
    KnowledgeBase,
    ObsidianKnowledgeBase,
)

# 配置指纹 → 实例。指纹变化（用户切换后端/vault/URL）时自动建新实例。
_instances: dict[tuple, KnowledgeBase] = {}


def _config_fingerprint(kb_cfg) -> tuple:
    """生成配置指纹。配置变更 → 指纹变化 → 缓存自动失效。"""
    return (
        kb_cfg.backend,
        kb_cfg.obsidian_vault_path,
        kb_cfg.obsidian_folder,
        kb_cfg.external_base_url,
        kb_cfg.external_api_key,
    )


def get_knowledge_backend(user_id: str = "") -> KnowledgeBase:
    """根据配置获取知识库后端实例（带配置指纹缓存）。

    user_id 参数保留以兼容现有调用方，但配置是全局的，实例也全局共享。
    """
    from ethan.core.config import get_config
    config = get_config()
    kb_cfg = config.tools.knowledge

    fp = _config_fingerprint(kb_cfg)
    if fp in _instances:
        return _instances[fp]

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
                folder=kb_cfg.obsidian_folder or ".",
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

    _instances[fp] = instance
    return instance


def clear_registry_cache() -> None:
    """显式清空缓存。配置保存流程可调用以确保立即生效。"""
    _instances.clear()


def _create_filesystem_backend() -> FilesystemKnowledgeBase:
    from ethan.core.paths import user_knowledge_dir
    return FilesystemKnowledgeBase(user_knowledge_dir())
