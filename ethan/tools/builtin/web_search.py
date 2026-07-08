"""Web Search Tool — 多 provider 搜索，支持通用和新闻模式。

Provider 优先级（可在 config.tools.web_search 中配置）：
  general: searxng → tavily → duckduckgo
  news:    searxng(categories=news) → google_news_rss → baidu_news_rss → duckduckgo
"""
from __future__ import annotations

import re
import urllib.parse

import httpx

from ethan.tools.base import BaseTool

_DDG_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"


class WebSearchTool(BaseTool):
    fast_path = False
    name = "web_search"
    description = (
        "Search the web for current information. "
        "Use when you need up-to-date data, facts, or real-time information. "
        "Set category='news' for recent news articles (supports Chinese news sources)."
    )
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
            "category": {
                "type": "string",
                "description": "Search category: 'general' (default) or 'news' for recent news articles.",
                "default": "general",
            },
            "time_range": {
                "type": "string",
                "description": "Time filter for news: 'day', 'week', 'month'. Only used when category='news'.",
                "default": "week",
            },
            "language": {
                "type": "string",
                "description": "Language/region for results, e.g. 'zh-CN', 'en-US', 'all'. Default: 'zh-CN'.",
                "default": "zh-CN",
            },
        },
        "required": ["query"],
    }

    async def run(
        self,
        query: str,
        max_results: int = 5,
        category: str = "general",
        time_range: str = "week",
        language: str = "zh-CN",
    ) -> str:
        try:
            from ethan.core.config import get_config
            cfg = get_config().tools.web_search

            is_news = category == "news"

            if is_news:
                results = await self._news_search(query, max_results, time_range, language, cfg)
            else:
                results = await self._general_search(query, max_results, cfg)

            if not results:
                return f"No results found for: {query}"
            return "\n\n".join(results)
        except Exception as e:
            return f"Search failed: {e}"

    # ── General search ──────────────────────────────────────────────────────

    async def _general_search(self, query: str, max_results: int, cfg) -> list[str]:
        if cfg.provider == "searxng" and cfg.base_url:
            results = await self._searxng_search(query, max_results, cfg.base_url)
            if results:
                return results
        if cfg.provider == "tavily" and cfg.api_key:
            return await self._tavily_search(query, max_results, cfg.api_key)
        return await self._ddg_search(query, max_results)

    # ── News search ─────────────────────────────────────────────────────────

    async def _news_search(self, query: str, max_results: int, time_range: str, language: str, cfg) -> list[str]:
        results: list[str] = []

        # 1. SearXNG news（配置了才用）
        if cfg.base_url:
            results = await self._searxng_news(query, max_results, cfg.base_url, time_range, language)
        if results:
            return results

        # 2. Google News RSS — 中英文均可，覆盖主流中文媒体
        results = await self._google_news_rss(query, max_results, language)
        if results:
            return results

        # 3. 百度新闻 RSS — 中文补充
        if language.startswith("zh"):
            results = await self._baidu_news_rss(query, max_results)
        if results:
            return results

        # 4. DDG fallback
        return await self._ddg_search(f"{query} site:news", max_results)

    async def _searxng_news(
        self, query: str, max_results: int, base_url: str, time_range: str, language: str
    ) -> list[str]:
        url = base_url.rstrip("/") + "/search"
        params: dict = {
            "q": query,
            "format": "json",
            "categories": "news",
            "language": language,
        }
        if time_range in ("day", "week", "month"):
            params["time_range"] = time_range

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(url, params=params)
                resp.raise_for_status()
            data = resp.json()
            results = []
            for item in data.get("results", [])[:max_results]:
                title = item.get("title", "")
                content = item.get("content", "")
                item_url = item.get("url", "")
                published = item.get("publishedDate", "")
                date_str = f"  [{published[:10]}]" if published else ""
                results.append(f"**{title}**{date_str}\n{content}\n{item_url}")
            return results
        except Exception:
            return []

    async def _google_news_rss(self, query: str, max_results: int, language: str = "zh-CN") -> list[str]:
        hl = "zh-CN" if language.startswith("zh") else "en-US"
        gl = "CN" if language.startswith("zh") else "US"
        ceid = f"{gl}:{hl.split('-')[0]}"
        encoded = urllib.parse.quote(query)
        url = f"https://news.google.com/rss/search?q={encoded}&hl={hl}&gl={gl}&ceid={ceid}"

        try:
            async with httpx.AsyncClient(
                timeout=12.0,
                follow_redirects=True,
                headers={"User-Agent": _DDG_UA, "Accept": "application/rss+xml,application/xml,*/*"},
            ) as client:
                resp = await client.get(url)
                resp.raise_for_status()
            return self._parse_rss(resp.text, max_results, source="Google News")
        except Exception:
            return []

    async def _baidu_news_rss(self, query: str, max_results: int) -> list[str]:
        encoded = urllib.parse.quote(query)
        url = f"https://news.baidu.com/ns?rss=1&tn=rss&cl=2&rn={max_results}&ct=1&ie=utf-8&word={encoded}"
        try:
            async with httpx.AsyncClient(
                timeout=10.0,
                follow_redirects=True,
                headers={"User-Agent": _DDG_UA, "Referer": "https://news.baidu.com"},
            ) as client:
                resp = await client.get(url)
                resp.raise_for_status()
            return self._parse_rss(resp.text, max_results, source="百度新闻")
        except Exception:
            return []

    def _parse_rss(self, xml: str, max_results: int, source: str = "") -> list[str]:
        items = re.findall(r"<item>(.*?)</item>", xml, re.DOTALL)
        results = []
        for item in items[:max_results]:
            title_m = re.search(r"<title[^>]*>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</title>", item, re.DOTALL)
            link_m = re.search(r"<link[^>]*>([^<]+)</link>|<link[^>]*/?>.*?href=['\"]([^'\"]+)['\"]", item, re.DOTALL)
            pub_m = re.search(r"<pubDate[^>]*>(.*?)</pubDate>", item, re.DOTALL)
            desc_m = re.search(r"<description[^>]*>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</description>", item, re.DOTALL)

            title = title_m.group(1).strip() if title_m else ""
            link = (link_m.group(1) or link_m.group(2)).strip() if link_m else ""
            pub = pub_m.group(1).strip()[:16] if pub_m else ""
            desc_raw = desc_m.group(1).strip() if desc_m else ""
            desc = re.sub(r"<[^>]+>", "", desc_raw)[:200].strip()

            if not title:
                continue
            src_tag = f"[{source}] " if source else ""
            date_tag = f"[{pub}] " if pub else ""
            snippet = f"\n{desc}" if desc else ""
            results.append(f"**{src_tag}{title}** {date_tag}{snippet}\n{link}")
        return results

    # ── SearXNG general ──────────────────────────────────────────────────────

    async def _searxng_search(self, query: str, max_results: int, base_url: str) -> list[str]:
        url = base_url.rstrip("/") + "/search"
        params = {"q": query, "format": "json"}
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(url, params=params)
                resp.raise_for_status()
            data = resp.json()
            results = []
            for item in data.get("results", [])[:max_results]:
                title = item.get("title", "")
                content = item.get("content", "")
                item_url = item.get("url", "")
                results.append(f"**{title}**\n{content}\n{item_url}")
            return results
        except Exception:
            return []

    # ── Tavily ───────────────────────────────────────────────────────────────

    async def _tavily_search(self, query: str, max_results: int, api_key: str) -> list[str]:
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(
                    "https://api.tavily.com/search",
                    json={
                        "api_key": api_key,
                        "query": query,
                        "search_depth": "basic",
                        "include_answer": False,
                        "include_images": False,
                        "include_raw_content": False,
                        "max_results": max_results,
                    },
                )
                resp.raise_for_status()
            results = []
            for item in resp.json().get("results", [])[:max_results]:
                results.append(f"**{item.get('title','')}**\n{item.get('content','')}\n{item.get('url','')}")
            return results
        except Exception:
            return []

    # ── DuckDuckGo ───────────────────────────────────────────────────────────

    async def _ddg_search(self, query: str, max_results: int) -> list[str]:
        # 优先尝试 duckduckgo-search 库（更稳定）
        try:
            from duckduckgo_search import DDGS  # type: ignore
            results = []
            with DDGS() as ddgs:
                for r in ddgs.text(query, max_results=max_results):
                    results.append(f"**{r.get('title','')}**\n{r.get('body','')}\n{r.get('href','')}")
            if results:
                return results
        except ImportError:
            pass
        except Exception:
            pass

        # Fallback: HTML 解析
        try:
            async with httpx.AsyncClient(
                follow_redirects=True, timeout=15.0, headers={"User-Agent": _DDG_UA}
            ) as client:
                resp = await client.post("https://html.duckduckgo.com/html/", data={"q": query})
                resp.raise_for_status()
            return self._parse_ddg_html(resp.text, max_results)
        except Exception:
            return []

    def _parse_ddg_html(self, html: str, max_results: int) -> list[str]:
        results = []
        snippets = re.findall(
            r'class="result__a"[^>]*href="([^"]*)"[^>]*>(.*?)</a>.*?'
            r'class="result__snippet"[^>]*>(.*?)</a>',
            html, re.DOTALL,
        )
        for url, title, snippet in snippets[:max_results]:
            t = re.sub(r"<[^>]+>", "", title).strip()
            s = re.sub(r"<[^>]+>", "", snippet).strip()
            if t:
                results.append(f"**{t}**\n{s}\n{url}")
        if not results:
            for t in re.findall(r'class="result__a"[^>]*>(.*?)</a>', html)[:max_results]:
                clean = re.sub(r"<[^>]+>", "", t).strip()
                if clean:
                    results.append(clean)
        return results
