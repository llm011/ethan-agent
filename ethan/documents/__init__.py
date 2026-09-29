"""文档库模块导出。"""
from ethan.documents.library import (
    DOC_EXTS,
    DocMeta,
    DocNode,
    Library,
    build_file_tree,
    count_documents,
    documents_root,
    ensure_root,
    list_flat,
    relative_to_root,
    resolve_in_root,
    sanitize_segment,
)

__all__ = [
    "DOC_EXTS",
    "DocMeta",
    "DocNode",
    "Library",
    "build_file_tree",
    "count_documents",
    "documents_root",
    "ensure_root",
    "list_flat",
    "relative_to_root",
    "resolve_in_root",
    "sanitize_segment",
]
