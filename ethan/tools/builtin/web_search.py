"""Web Search Tool — DuckDuckGo 免费搜索，无需 API Key。"""
import json
from urllib.parse import quote_plus

import httpx

from ethan.tools.base import BaseTool


class WebSearchTool(BaseTool):
    name = "web_search"
    description = "Search the web for current information. Use when you need up-to-date data, facts you're unsure about, or real-time information."
    parameters = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "The search query.",
            },
            "max_results": {
                "type": "integer",
                "description": "Maximum number of results to return (default 5).",
                "default": 5,
            },
        },
        "required": ["query"],
    }

    async def run(self, query: str, max_results: int = 5) -> str:
        try:
            results = await self._ddg_search(query, max_results)
            if not results:
                return f"No results found for: {query}"
            return "\n\n".join(results)
        except Exception as e:
            return f"Search failed: {e}"

    async def _ddg_search(self, query: str, max_results: int) -> list[str]:
        url = "https://html.duckduckgo.com/html/"
        headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"}

        async with httpx.AsyncClient(follow_redirects=True, timeout=15.0) as client:
            resp = await client.post(url, data={"q": query}, headers=headers)
            resp.raise_for_status()

        return self._parse_html(resp.text, max_results)

    def _parse_html(self, html: str, max_results: int) -> list[str]:
        """从 DuckDuckGo HTML 结果中提取标题和摘要。"""
        results = []
        # DuckDuckGo HTML 的结果结构
        # <a class="result__a" href="...">Title</a>
        # <a class="result__snippet">Snippet</a>
        import re

        # Extract result blocks
        snippets = re.findall(
            r'class="result__a"[^>]*href="([^"]*)"[^>]*>(.*?)</a>.*?'
            r'class="result__snippet"[^>]*>(.*?)</a>',
            html, re.DOTALL
        )

        for url, title, snippet in snippets[:max_results]:
            title_clean = re.sub(r"<[^>]+>", "", title).strip()
            snippet_clean = re.sub(r"<[^>]+>", "", snippet).strip()
            if title_clean:
                results.append(f"**{title_clean}**\n{snippet_clean}\n{url}")

        # Fallback: simpler pattern
        if not results:
            titles = re.findall(r'class="result__a"[^>]*>(.*?)</a>', html)
            for t in titles[:max_results]:
                clean = re.sub(r"<[^>]+>", "", t).strip()
                if clean:
                    results.append(clean)

        return results
