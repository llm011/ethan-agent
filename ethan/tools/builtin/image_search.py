"""Image Search Tool — 基于 SearXNG 的图片搜索工具。

仅在配置了 SearXNG（config.tools.web_search.base_url 非空）且
image_search_enabled=True 时启用（注册逻辑见 ethan/core/agent_factory.py）。

特点：
  - 调用 SearXNG images 分类，并行聚合 bing images / flickr / openverse / devicons 等引擎
  - 默认只返回图片元数据（URL + 标题 + 来源 + 尺寸）
  - 可选 download=True：下载图片到本地临时目录，返回本地路径
    下载时会用真实 User-Agent + Referer 绕过部分防盗链
  - 失败的 URL（403/404/超时）自动过滤，只返回可访问的图片

返回格式：
  - download=False（默认）：
      **标题**
      URL: https://example.com/image.jpg
      来源: bing images | 尺寸: 1920x1080
  - download=True：
      **标题**
      本地路径: /tmp/ethan_images/img_xxxxxx.jpg
      来源: bing images | 原始 URL: https://example.com/image.jpg
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
from pathlib import Path

import httpx

from ethan.tools.base import BaseTool, ToolResult

logger = logging.getLogger(__name__)

# 图片下载相关配置
_IMAGE_DOWNLOAD_DIR = Path("/tmp/ethan_images")
_IMAGE_DOWNLOAD_TIMEOUT = 10.0  # 单张图片下载超时
_IMAGE_MAX_SIZE = 10 * 1024 * 1024  # 10MB，超过则跳过
_USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

# 支持的图片扩展名（根据 content-type 或 URL 后缀判断）
_IMAGE_CONTENT_TYPES = {"image/jpeg", "image/png", "image/gif", "image/webp", "image/svg+xml", "image/bmp"}
_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".bmp"}


class ImageSearchTool(BaseTool):
    fast_path = False
    cacheable = False  # 搜索结果不缓存
    side_effect = True  # download=True 时会写文件
    name = "image_search"
    description = (
        "Search for images on the web. Returns image URLs and metadata (title, source, dimensions). "
        "Optionally downloads images to local /tmp directory when download=true. "
        "Requires SearXNG to be configured. "
        "Use cases: find product photos, illustrations, logos, diagrams, etc."
    )
    parameters = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "The image search query (e.g. 'cute cat', 'Python logo', '红烧肉').",
            },
            "max_results": {
                "type": "integer",
                "description": "Maximum number of images to return (default 5).",
                "default": 5,
            },
            "download": {
                "type": "boolean",
                "description": (
                    "If true, download images to /tmp/ethan_images/ and return local paths. "
                    "If false (default), only return image URLs. "
                    "Download mode verifies images are actually accessible and filters out broken links."
                ),
                "default": False,
            },
            "language": {
                "type": "string",
                "description": "Language/region for results, e.g. 'zh-CN', 'en-US'. Default: 'zh-CN'.",
                "default": "zh-CN",
            },
        },
        "required": ["query"],
    }

    async def run(
        self,
        query: str,
        max_results: int = 5,
        download: bool = False,
        language: str = "zh-CN",
    ) -> str | ToolResult:
        try:
            from ethan.core.config import get_config
            cfg = get_config().tools.web_search

            if not cfg.base_url:
                return (
                    "Image search requires SearXNG to be configured. "
                    "Please set SEARXNG_BASE_URL environment variable or "
                    "configure tools.web_search.base_url in config.yaml."
                )

            # 搜索图片（多取一些，过滤后取前 max_results）
            fetch_count = max_results * 3 if download else max_results
            raw_results = await self._searxng_images(query, fetch_count, cfg.base_url, language)

            if not raw_results:
                return f"No images found for: {query}"

            if download:
                # 下载模式：并发下载，过滤失败的
                downloaded = await self._download_images(raw_results, max_results)
                if not downloaded:
                    return f"Found {len(raw_results)} images but all downloads failed. Try download=false for URLs only."
                return self._build_result(query, downloaded, download=True)
            else:
                # URL 模式：只返回元数据
                return self._build_result(query, raw_results[:max_results], download=False)

        except Exception as e:
            return f"Image search failed: {e}"

    def _build_result(self, query: str, results: list[dict], download: bool) -> ToolResult:
        """把结构化图片结果转成 ToolResult。

        - content: 给 LLM 的纯文本摘要（兼容旧格式），让模型知道搜到了什么
        - cards: 结构化卡片数据，前端按 type=image 渲染横向滚动图片画廊

        download=True 时 cards 里含 local_path 字段，前端优先用本地路径展示；
        download=False 时只有 url 字段，前端直接用远程 URL（可能受防盗链限制）。
        """
        content_parts: list[str] = []
        for r in results:
            title = r.get("title", "") or "(无标题)"
            source = r.get("source", "")
            w = r.get("width")
            h = r.get("height")
            size_str = f" | 尺寸: {w}x{h}" if w and h else ""
            if download and r.get("local_path"):
                size_kb = r.get("size_kb", 0)
                content_parts.append(
                    f"**{title}**\n本地路径: {r['local_path']}\n来源: {source}{size_str} | 大小: {size_kb}KB | 原始 URL: {r.get('url', '')}"
                )
            else:
                content_parts.append(
                    f"**{title}**\nURL: {r.get('url', '')}\n来源: {source}{size_str}"
                )
        content = "\n\n".join(content_parts)

        cards = [
            {
                "type": "image",
                "title": r.get("title", "") or "(无标题)",
                "url": r.get("url", ""),
                "local_path": r.get("local_path", ""),
                "source": r.get("source", ""),
                "page_url": r.get("page_url", ""),
                "width": r.get("width"),
                "height": r.get("height"),
                "size_kb": r.get("size_kb"),
            }
            for r in results
        ]

        return ToolResult(
            tool_call_id="",  # 由 registry 回填
            content=content,
            cards=cards,
        )

    async def _searxng_images(
        self, query: str, max_results: int, base_url: str, language: str
    ) -> list[dict]:
        """调用 SearXNG images 分类搜索。返回原始结果列表。"""
        url = base_url.rstrip("/") + "/search"
        params = {"q": query, "format": "json", "categories": "images", "language": language}
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
        data = resp.json()
        results = []
        for item in data.get("results", [])[:max_results]:
            img_url = item.get("img_src", "") or item.get("url", "")
            if not img_url:
                continue
            results.append({
                "title": (item.get("title", "") or "")[:80],
                "url": img_url,  # 图片直接 URL
                "source": item.get("engine", ""),
                "page_url": item.get("url", ""),
                "width": item.get("img_format_src", {}).get("width") if isinstance(item.get("img_format_src"), dict) else None,
                "height": item.get("img_format_src", {}).get("height") if isinstance(item.get("img_format_src"), dict) else None,
            })
        return results

    async def _download_images(self, items: list[dict], max_results: int) -> list[dict]:
        """并发下载图片到 /tmp/ethan_images/，返回结构化结果列表。

        失败的图片自动过滤。只返回下载成功的前 max_results 张。
        每条 dict 在原 item 基础上补充 local_path / size_kb 字段。
        """
        _IMAGE_DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)

        async def download_one(client: httpx.AsyncClient, item: dict) -> dict | None:
            url = item["url"]
            try:
                # 用真实浏览器 UA + Referer 绕过部分防盗链
                headers = {
                    "User-Agent": _USER_AGENT,
                    "Accept": "image/webp,image/apng,image/*,*/*;q=0.8",
                }
                # Referer 用来源页面 URL（如果有），否则用来源引擎域名
                page_url = item.get("page_url", "")
                if page_url:
                    headers["Referer"] = page_url
                elif item.get("source"):
                    # 从图片 URL 提取 origin 作为 Referer
                    from urllib.parse import urlparse
                    parsed = urlparse(url)
                    headers["Referer"] = f"{parsed.scheme}://{parsed.netloc}/"

                resp = await client.get(url, headers=headers, follow_redirects=True, timeout=_IMAGE_DOWNLOAD_TIMEOUT)
                resp.raise_for_status()

                content_type = resp.headers.get("content-type", "").split(";")[0].strip().lower()
                content_length = len(resp.content)

                # 验证是图片
                if content_type and content_type not in _IMAGE_CONTENT_TYPES:
                    logger.debug("[ImageSearch] skip non-image content-type=%s url=%s", content_type, url[:80])
                    return None
                if content_length > _IMAGE_MAX_SIZE:
                    logger.debug("[ImageSearch] skip too large %dB url=%s", content_length, url[:80])
                    return None
                if content_length < 100:  # 太小，可能是占位图
                    logger.debug("[ImageSearch] skip too small %dB url=%s", content_length, url[:80])
                    return None

                # 根据content-type 确定扩展名
                ext = self._ext_from_content_type(content_type, url)
                # 用 url hash 生成文件名，避免冲突
                url_hash = hashlib.md5(url.encode()).hexdigest()[:12]
                filename = f"img_{url_hash}{ext}"
                filepath = _IMAGE_DOWNLOAD_DIR / filename

                # 避免重复下载
                if not filepath.exists():
                    filepath.write_bytes(resp.content)

                # 返回结构化 dict：保留原 item 字段，补充本地路径和大小
                return {
                    **item,
                    "url": url,  # 原始远程 URL
                    "local_path": str(filepath),
                    "size_kb": content_length // 1024,
                }
            except Exception as e:
                logger.debug("[ImageSearch] download failed url=%s err=%s", url[:80], e)
                return None

        # 并发下载，最多 5 个同时
        semaphore = asyncio.Semaphore(5)
        async def bounded_download(client, item):
            async with semaphore:
                return await download_one(client, item)

        async with httpx.AsyncClient() as client:
            tasks = [bounded_download(client, item) for item in items]
            results = await asyncio.gather(*tasks)

        # 过滤失败，取前 max_results
        successful = [r for r in results if r is not None][:max_results]
        return successful

    def _ext_from_content_type(self, content_type: str, url: str) -> str:
        """根据 content-type 或 URL 后缀确定文件扩展名。"""
        ct_to_ext = {
            "image/jpeg": ".jpg",
            "image/png": ".png",
            "image/gif": ".gif",
            "image/webp": ".webp",
            "image/svg+xml": ".svg",
            "image/bmp": ".bmp",
        }
        if content_type in ct_to_ext:
            return ct_to_ext[content_type]
        # 从 URL 后缀推断
        from urllib.parse import urlparse
        path = urlparse(url).path.lower()
        for ext in _IMAGE_EXTENSIONS:
            if path.endswith(ext):
                return ext
        return ".jpg"  # 默认
