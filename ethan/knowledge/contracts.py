"""知识库核心契约 — 数据模型 KnowledgeItem 与抽象基类 KnowledgeBase。

各后端（filesystem / obsidian / external / notion）继承 KnowledgeBase 实现。
"""
import logging
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class KnowledgeItem:
    title: str
    content: str
    source: str  # file path or URL
    tags: list[str]

    def snippet(self, max_len: int = 800) -> str:
        text = re.sub(r"\s+", " ", self.content).strip()
        return text[:max_len] + "…" if len(text) > max_len else text


class KnowledgeBase(ABC):
    @abstractmethod
    def add(self, title: str, content: str, tags: list[str] | None = None,
            frontmatter: dict | None = None) -> str:
        """Add an item. Returns its ID/path.

        frontmatter: 仅 Obsidian 后端生效，用于补充 source/url/author 等自定义 front matter 字段；
                     固定字段（title/type/tags/created/updated）仍由后端自动管理，不要在此重复传入。
        """

    @abstractmethod
    def search(self, query: str, limit: int = 5) -> list[KnowledgeItem]:
        """Search by keyword."""

    @abstractmethod
    async def semantic_search(self, query: str, limit: int = 5) -> list[KnowledgeItem]:
        """Search by semantic similarity."""

    @abstractmethod
    def list_all(self) -> list[KnowledgeItem]:
        """List all items."""

    @abstractmethod
    def get(self, source: str) -> KnowledgeItem | None:
        """Get item by source identifier."""

    @abstractmethod
    def update(self, source: str, title: str, content: str, tags: list[str] | None = None,
               frontmatter: dict | None = None) -> None:
        """Update an existing item in place.

        frontmatter: 仅 Obsidian 后端生效，用于补充 source/url/author 等自定义 front matter 字段；
                     固定字段（title/type/tags/created/updated）仍由后端自动管理，不要在此重复传入。
        """

    @abstractmethod
    def delete(self, source: str) -> None:
        """Delete an item by source identifier."""

    @abstractmethod
    def health_check(self) -> tuple[bool, str]:
        """Validate connectivity / accessibility. Returns (ok, message)."""

    def append(self, source: str, content: str) -> str:
        """把内容追加到已有条目正文末尾。默认基于 get+update 实现，子类可 override 优化。"""
        item = self.get(source)
        if item is None:
            raise FileNotFoundError(f"Knowledge item not found: {source}")
        new_content = (item.content.rstrip() + "\n\n" + content.strip()).strip()
        self.update(item.source, item.title, new_content, tags=item.tags)
        return item.source

    def list_tags(self) -> dict[str, int]:
        """列出所有 tag 及出现次数。可选能力，后端按需实现。"""
        raise NotImplementedError(f"{type(self).__name__} does not support list_tags")

    @staticmethod
    def _tokenize_query(query: str) -> set[str]:
        """将查询切分为 token 集合，用于关键词搜索打分。

        - 英文/数字：按空格切分（长度 >= 2 才作为 token）
        - 中文：按 2-gram 切分（"内置浏览器" → {"内置", "置浏", "浏览", "览器"}），
          让查询和文档字面表述不完全一致时也能匹配（如"内置的浏览器"）
        - 完整 query 也作为一个 token（精确匹配加分）
        """
        import re

        query_lower = query.lower().strip()
        if not query_lower:
            return set()

        tokens: set[str] = set()
        for m in re.findall(r"[a-z0-9]+", query_lower):
            if len(m) >= 2:
                tokens.add(m)
        for seg in re.findall(r"[\u4e00-\u9fff]+", query_lower):
            if len(seg) >= 2:
                for i in range(len(seg) - 1):
                    tokens.add(seg[i : i + 2])
            elif len(seg) == 1:
                tokens.add(seg)
        if len(query_lower) >= 2:
            tokens.add(query_lower)
        return tokens

    def _keyword_search(self, query: str, limit: int = 5) -> list["KnowledgeItem"]:
        """通用关键词搜索（2-gram 分词），FilesystemKB 和 ObsidianKB 共用。

        排序策略：标题/文件名命中完整 query 加分远高于正文命中，
        让"内置浏览器"能把标题就是"内置浏览器"的 PRD 文件排到第一，
        而不是被内容里只是提到这个词的其他文件挤掉。
        """
        tokens = self._tokenize_query(query)
        if not tokens:
            return []
        query_lower = query.lower().strip()
        results: list[tuple[int, KnowledgeItem]] = []
        for item in self.list_all():
            filename = Path(item.source).stem.lower()
            title_lower = item.title.lower()
            # 标题/文件名命中完整 query：+20（强偏好）
            # 正文命中完整 query：+5
            # 2-gram 命中：每个 +1
            title_text = title_lower + " " + filename
            content_text = (item.content + " " + " ".join(item.tags)).lower()
            score = sum(1 for t in tokens if t in title_text or t in content_text)
            if query_lower in title_text:
                score += 20
            elif query_lower in content_text:
                score += 5
            if score > 0:
                results.append((score, item))
        results.sort(key=lambda x: -x[0])
        return [item for _, item in results[:limit]]

    def _resolve_in_dir(self, source: str) -> Path:
        """解析 source 为 self._dir 子树内的绝对路径，越界直接拒绝（防路径穿越）。"""
        path = Path(source)
        if not path.is_absolute():
            path = self._dir / source
        resolved = path.resolve()
        try:
            resolved.relative_to(self._dir.resolve())
        except ValueError:
            raise ValueError(f"Path outside knowledge base: {source}")
        return resolved
