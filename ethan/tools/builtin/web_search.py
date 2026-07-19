"""Web Search Tool — 多 provider 搜索，支持通用/学术/IT/新闻模式。

Provider 优先级（可在 config.tools.web_search 中配置）：
  general: searxng → tavily → duckduckgo → bing
  science: searxng(categories=science) → searxng(categories=general) → tavily → duckduckgo → bing
  it:      searxng(categories=it) → searxng(categories=general) → tavily → duckduckgo → bing
  news:    searxng(categories=news) → google_news_rss → baidu_news_rss → duckduckgo

自动路由（category='auto' 时按 query 意图自动选择分类）：
  - 学术关键词（论文/算法/模型/研究/论文标题等）→ science 分类（arxiv/pubmed/google scholar 等）
  - 代码关键词（编程/语法/错误/库/框架等）→ it 分类（github/stackoverflow/mdn 等）
  - 新闻关键词（今日/最新/突破/发布/行情等）→ news 分类
  - 其他 → general 分类

兼容性：
  - 不配置 SearXNG（默认）：science/it 分类会降级到 general，走 DDG/bing 兜底链
  - 配置 SearXNG：science/it 分类使用专属引擎（arxiv/github 等）

容错机制（retry + fallback + circuit breaker）：
  - 每个 provider 调用失败时重试 1 次（共 2 次机会）
  - 重试仍失败则跳到下一个 provider
  - 连续 2 轮 fallback 后，标记该 provider 为熔断，冷却期内直接跳过
  - 主力分类返回空结果时自动降级到备用分类（engine 质量分级）

图片搜索请使用独立的 `image_search` 工具（需配置 SearXNG）。
"""
from __future__ import annotations

import asyncio
import html as _html
import logging
import re
import time
import urllib.parse

import httpx

from ethan.tools.base import BaseTool

logger = logging.getLogger(__name__)

_DDG_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"

# ── Circuit Breaker（进程级单例） ─────────────────────────────────────────────
_RETRY_COUNT = 1          # 每个 provider 重试次数（加上首次 = 共 2 次机会）
_FAILURE_THRESHOLD = 2    # 连续失败几轮后熔断
_COOLDOWN_SECONDS = 300   # 熔断冷却期（秒）

# ── 自动路由关键词表 ────────────────────────────────────────────────────────
# 用于 category='auto' 时按 query 意图自动选择 SearXNG 分类。
# 匹配优先级：science > it > news > general（最具体的关键词优先）。
_SCIENCE_KEYWORDS = (
    # 中文学术关键词
    "论文", "综述", "算法", "模型", "神经网络", "深度学习", "机器学习",
    "人工智能", "强化学习", "梯度", "反向传播", "注意力机制", "Transformer",
    "大语言模型", "幻觉", "微调", "对齐", "RLHF", "检索增强",
    "研究", "实验", "数据集", "benchmark", "SOTA", "state-of-the-art",
    # 医学/生物
    "疾病", "病因", "治疗", "药物", "临床试验", "预后", "诊断",
    # 英文学术关键词
    "paper", "arxiv", "research", "algorithm", "model", "neural network",
    "deep learning", "machine learning", "transformer", "attention",
    "llm", "gpt", "bert", "diffusion", "embedding", "fine-tuning",
    "benchmark", "dataset", "survey", "literature",
)

_IT_KEYWORDS = (
    # 编程语言/语法
    "python", "java", "javascript", "typescript", "go ", "golang", "rust",
    "c++", "c#", "swift", "kotlin", "ruby", "php",
    "asyncio", "await", "async", "thread", "lock", "mutex",
    "正则", "regex", "正则表达式",
    # 错误/调试
    "error", "exception", "报错", "错误", "异常", "debug", "调试",
    "traceback", "stacktrace", "崩溃", "crash",
    # 框架/库/工具
    "docker", "kubernetes", "k8s", "compose", "fastapi", "flask", "django",
    "react", "vue", "nextjs", "next.js", "node", "npm", "pnpm", "yarn",
    "git ", "github", "gitlab", "rebase", "merge", "commit", "branch",
    "sql", "mysql", "postgres", "redis", "mongodb",
    "linux", "shell", "bash", "zsh", "terminal",
    # 中文编程
    "代码", "函数", "用法", "示例", "教程", "安装", "配置",
    "部署", "编译", "运行", "报错", "调试",
)

_NEWS_KEYWORDS = (
    "今日", "今天", "最新", "最近", "本周", "本月", "近期",
    "新闻", "资讯", "热点", "事件", "进展", "动态",
    "发布", "上市", "推出", "突破", "首发",
    "行情", "股价", "涨跌", "财报", "业绩", "暴跌", "暴涨",
    "today", "latest", "news", "recent", "breaking", "announced", "released",
    "earnings", "stock", "market",
)


def _route_category(query: str) -> str:
    """根据 query 意图自动路由到 SearXNG 分类。

    匹配优先级：science > it > news > general（最具体的关键词优先）。
    """
    q_lower = query.lower()
    # 学术关键词最具体，优先匹配
    for kw in _SCIENCE_KEYWORDS:
        if kw.lower() in q_lower:
            return "science"
    # IT/编程关键词
    for kw in _IT_KEYWORDS:
        if kw.lower() in q_lower:
            return "it"
    # 新闻关键词
    for kw in _NEWS_KEYWORDS:
        if kw.lower() in q_lower:
            return "news"
    return "general"


class _CircuitBreaker:
    """简单的 provider 级熔断器。进程内存状态，重启即复位。"""

    def __init__(self):
        # {provider_name: consecutive_failure_count}
        self._failures: dict[str, int] = {}
        # {provider_name: timestamp_when_tripped}
        self._tripped_at: dict[str, float] = {}

    def is_available(self, provider: str) -> bool:
        """该 provider 当前是否可用（未熔断或已过冷却期）。"""
        tripped = self._tripped_at.get(provider)
        if tripped is None:
            return True
        if time.time() - tripped >= _COOLDOWN_SECONDS:
            # 冷却期结束，重置为半开状态（允许一次探测）
            self._failures.pop(provider, None)
            self._tripped_at.pop(provider, None)
            logger.info("[WebSearch] circuit half-open for %s, allowing probe", provider)
            return True
        return False

    def record_success(self, provider: str) -> None:
        """成功调用，重置计数器。"""
        self._failures.pop(provider, None)
        self._tripped_at.pop(provider, None)

    def record_failure(self, provider: str) -> None:
        """失败调用，累计计数；达到阈值则熔断。"""
        count = self._failures.get(provider, 0) + 1
        self._failures[provider] = count
        if count >= _FAILURE_THRESHOLD:
            self._tripped_at[provider] = time.time()
            logger.warning(
                "[WebSearch] circuit OPEN for %s (failed %d times), cooldown %ds",
                provider, count, _COOLDOWN_SECONDS,
            )


_breaker = _CircuitBreaker()


class WebSearchTool(BaseTool):
    fast_path = False
    cacheable = False  # 搜索结果不缓存——空结果不应被复用
    name = "web_search"
    description = (
        "Search the web for current information. "
        "Use when you need up-to-date data, facts, or real-time information. "
        "Categories: 'general' (default), 'science' (academic papers from arxiv/pubmed/google scholar), "
        "'it' (code/tech from github/stackoverflow/mdn), 'news' (recent news), "
        "or 'auto' (smart routing by query intent). "
        "For image search, use the 'image_search' tool instead."
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
                "description": (
                    "Search category: "
                    "'auto' (default, smart routing by query intent), "
                    "'general' (web search), "
                    "'science' (academic papers: arxiv/pubmed/google scholar), "
                    "'it' (code/tech: github/stackoverflow/mdn), "
                    "'news' (recent news articles)."
                ),
                "default": "auto",
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
        category: str = "auto",
        time_range: str = "week",
        language: str = "zh-CN",
    ) -> str:
        try:
            from ethan.core.config import get_config
            cfg = get_config().tools.web_search

            # 自动路由：按 query 意图选择分类
            if category == "auto":
                category = _route_category(query)
                logger.info("[WebSearch] auto-routed query=%r → category=%s", query[:50], category)

            if category == "news":
                results = await self._news_search(query, max_results, time_range, language, cfg)
            elif category in ("science", "it"):
                # 学术/IT 分类：主力分类 → 降级到 general（引擎质量分级）
                results = await self._categorized_search(query, max_results, category, cfg)
            else:
                # general 或未知 category 都走通用搜索
                results = await self._general_search(query, max_results, cfg)

            if not results:
                return f"No results found for: {query}"
            return "\n\n".join(results)
        except Exception as e:
            return f"Search failed: {e}"

    # ── Categorized search（science/it 分类，带降级）─────────────────────────

    async def _categorized_search(self, query: str, max_results: int, category: str, cfg) -> list[str]:
        """按指定分类（science/it）搜索，主力分类返回空时降级到 general。

        引擎质量分级策略：
          1. 主力：SearXNG 指定分类（science→arxiv/pubmed/google scholar；it→github/stackoverflow/mdn）
          2. 备用：SearXNG general 分类（bing/google cse/startpage）
          3. 兜底：tavily / duckduckgo / bing（通用 provider 链）

        兼容性：未配置 SearXNG（base_url 为空）时，直接走 general 兜底链（DDG/bing）。
        """
        # 主力：SearXNG 指定分类
        if cfg.base_url:
            try:
                results = await self._searxng_search_category(query, max_results, cfg.base_url, category)
                if results:
                    return results
                logger.info("[WebSearch] %s category empty, falling back to general", category)
            except Exception as e:
                logger.info("[WebSearch] %s category error: %s, falling back to general", category, e)
        else:
            # 未配置 SearXNG：science/it 无专属引擎可用，直接降级到 general
            logger.debug("[WebSearch] no SearXNG configured, %s category falls back to general", category)

        # 降级到 general（包含 SearXNG general → tavily → ddg → bing 完整链）
        return await self._general_search(query, max_results, cfg)

    async def _searxng_search_category(
        self, query: str, max_results: int, base_url: str, category: str
    ) -> list[str]:
        """SearXNG 指定分类搜索。异常向上传播。"""
        url = base_url.rstrip("/") + "/search"
        params = {"q": query, "format": "json", "categories": category}
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
        data = resp.json()
        unresponsive = data.get("unresponsive_engines", [])
        actual_results = data.get("results", [])
        if not actual_results and unresponsive:
            engines = [e[0] for e in unresponsive[:3]]
            raise RuntimeError(f"SearXNG {category} engines unavailable: {engines}")
        results = []
        for item in actual_results[:max_results]:
            title = item.get("title", "")
            content = item.get("content", "")
            item_url = item.get("url", "")
            results.append(f"**{title}**\n{content}\n{item_url}")
        return results

    # ── General search（retry + fallback + circuit breaker）────────────────

    async def _general_search(self, query: str, max_results: int, cfg) -> list[str]:
        """按优先级尝试各 provider，每个带 retry，失败则 fallback，累计熔断。"""
        # 构建候选 provider 链
        candidates: list[tuple[str, object]] = []  # (name, callable_coroutine_factory)
        if cfg.base_url:
            candidates.append(("searxng", lambda: self._searxng_search(query, max_results, cfg.base_url)))
        if cfg.api_key:
            candidates.append(("tavily", lambda: self._tavily_search(query, max_results, cfg.api_key)))
        candidates.append(("duckduckgo", lambda: self._ddg_search(query, max_results)))
        candidates.append(("bing", lambda: self._bing_general_search(query, max_results)))

        for name, factory in candidates:
            if not _breaker.is_available(name):
                logger.debug("[WebSearch] skipping %s (circuit open)", name)
                continue
            results, had_error = await self._call_with_retry(name, factory)
            if results:
                _breaker.record_success(name)
                return results
            if had_error:
                # 只有实际的网络/provider 错误才计入熔断
                _breaker.record_failure(name)
                logger.info("[WebSearch] %s error for query=%r, trying next provider", name, query[:50])
            else:
                # 空结果但 provider 正常响应 → 不熔断，继续尝试下一个
                logger.debug("[WebSearch] %s returned empty for query=%r, trying next", name, query[:50])

        return []

    async def _call_with_retry(self, provider_name: str, factory) -> tuple[list[str], bool]:
        """对单个 provider 调用，失败重试 _RETRY_COUNT 次。
        返回 (results, had_error)：had_error=True 表示遇到异常（provider 可能不可用）。
        """
        had_error = False
        for attempt in range(_RETRY_COUNT + 1):
            try:
                results = await factory()
                if results:
                    return results, False
                # provider 正常响应但无结果 → 不算 error
            except Exception as e:
                had_error = True
                logger.debug("[WebSearch] %s attempt %d error: %s", provider_name, attempt + 1, e)
            if attempt < _RETRY_COUNT:
                await asyncio.sleep(0.5)  # 重试前短暂等待
        return [], had_error

    # ── News search（同样带 retry + fallback + circuit breaker）──────────────

    async def _news_search(self, query: str, max_results: int, time_range: str, language: str, cfg) -> list[str]:
        candidates: list[tuple[str, object]] = []
        if cfg.base_url:
            candidates.append(("searxng_news", lambda: self._searxng_news(query, max_results, cfg.base_url, time_range, language)))
        candidates.append(("google_news", lambda: self._google_news_rss(query, max_results, language)))
        if language.startswith("zh"):
            candidates.append(("baidu_news", lambda: self._baidu_news_rss(query, max_results)))
        candidates.append(("duckduckgo_news", lambda: self._ddg_search(f"{query} site:news", max_results)))

        for name, factory in candidates:
            if not _breaker.is_available(name):
                logger.debug("[WebSearch] skipping %s (circuit open)", name)
                continue
            results, had_error = await self._call_with_retry(name, factory)
            if results:
                _breaker.record_success(name)
                return results
            if had_error:
                _breaker.record_failure(name)
                logger.info("[WebSearch] %s error for query=%r, trying next", name, query[:50])

        return []

    async def _searxng_news(
        self, query: str, max_results: int, base_url: str, time_range: str, language: str
    ) -> list[str]:
        """SearXNG 新闻搜索。异常向上传播给 _call_with_retry 处理。"""
        url = base_url.rstrip("/") + "/search"
        params: dict = {
            "q": query,
            "format": "json",
            "categories": "news",
            "language": language,
        }
        if time_range in ("day", "week", "month"):
            params["time_range"] = time_range

        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
        data = resp.json()
        # 检测所有引擎不可用
        unresponsive = data.get("unresponsive_engines", [])
        actual_results = data.get("results", [])
        if not actual_results and unresponsive:
            engines = [e[0] for e in unresponsive[:3]]
            raise RuntimeError(f"SearXNG news engines unavailable: {engines}")
        results = []
        for item in actual_results[:max_results]:
            title = item.get("title", "")
            content = item.get("content", "")
            item_url = item.get("url", "")
            published = item.get("publishedDate", "")
            date_str = f"  [{published[:10]}]" if published else ""
            results.append(f"**{title}**{date_str}\n{content}\n{item_url}")
        return results

    async def _google_news_rss(self, query: str, max_results: int, language: str = "zh-CN") -> list[str]:
        """Google News RSS。异常向上传播给 _call_with_retry 处理。"""
        hl = "zh-CN" if language.startswith("zh") else "en-US"
        gl = "CN" if language.startswith("zh") else "US"
        ceid = f"{gl}:{hl.split('-')[0]}"
        encoded = urllib.parse.quote(query)
        url = f"https://news.google.com/rss/search?q={encoded}&hl={hl}&gl={gl}&ceid={ceid}"

        async with httpx.AsyncClient(
            timeout=12.0,
            follow_redirects=True,
            headers={"User-Agent": _DDG_UA, "Accept": "application/rss+xml,application/xml,*/*"},
        ) as client:
            resp = await client.get(url)
            resp.raise_for_status()
        return self._parse_rss(resp.text, max_results, source="Google News")

    async def _baidu_news_rss(self, query: str, max_results: int) -> list[str]:
        """百度新闻 RSS。异常向上传播给 _call_with_retry 处理。"""
        encoded = urllib.parse.quote(query)
        url = f"https://news.baidu.com/ns?rss=1&tn=rss&cl=2&rn={max_results}&ct=1&ie=utf-8&word={encoded}"
        async with httpx.AsyncClient(
            timeout=10.0,
            follow_redirects=True,
            headers={"User-Agent": _DDG_UA, "Referer": "https://news.baidu.com"},
        ) as client:
            resp = await client.get(url)
            resp.raise_for_status()
        return self._parse_rss(resp.text, max_results, source="百度新闻")

    def _parse_rss(self, xml: str, max_results: int, source: str = "") -> list[str]:
        items = re.findall(r"<item>(.*?)</item>", xml, re.DOTALL)
        results = []
        for item in items[:max_results]:
            title_m = re.search(r"<title[^>]*>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</title>", item, re.DOTALL)
            link_m = re.search(r"<link[^>]*>([^<]+)</link>|<link[^>]*/?>.*?href=['\"]([^'\"]+)['\"]", item, re.DOTALL)
            pub_m = re.search(r"<pubDate[^>]*>(.*?)</pubDate>", item, re.DOTALL)
            desc_m = re.search(r"<description[^>]*>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</description>", item, re.DOTALL)

            title_raw = title_m.group(1).strip() if title_m else ""
            title = re.sub(r"<[^>]+>", "", title_raw).strip()
            link_raw = link_m.group(1) or link_m.group(2) or ""
            link = link_raw.strip() if link_raw else ""
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
        """SearXNG 通用搜索。异常向上传播给 _call_with_retry 处理。"""
        url = base_url.rstrip("/") + "/search"
        params = {"q": query, "format": "json"}
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
        data = resp.json()
        # 检测 SearXNG 所有引擎都不可用的情况（返回 200 但无结果）
        unresponsive = data.get("unresponsive_engines", [])
        actual_results = data.get("results", [])
        if not actual_results and unresponsive:
            engines = [e[0] for e in unresponsive[:3]]
            raise RuntimeError(f"SearXNG engines unavailable: {engines}")
        results = []
        for item in actual_results[:max_results]:
            title = item.get("title", "")
            content = item.get("content", "")
            item_url = item.get("url", "")
            results.append(f"**{title}**\n{content}\n{item_url}")
        return results

    # ── Tavily ───────────────────────────────────────────────────────────────

    async def _tavily_search(self, query: str, max_results: int, api_key: str) -> list[str]:
        """Tavily 搜索。异常向上传播给 _call_with_retry 处理。"""
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

    # ── DuckDuckGo ───────────────────────────────────────────────────────────

    async def _ddg_search(self, query: str, max_results: int) -> list[str]:
        """DuckDuckGo 搜索：先尝试 ddg 库，再 HTML fallback。最终失败则抛异常。"""
        # 优先尝试 duckduckgo-search 库（更稳定）
        last_err: Exception | None = None
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
        except Exception as e:
            last_err = e

        # Fallback: HTML 解析
        try:
            async with httpx.AsyncClient(
                follow_redirects=True, timeout=15.0, headers={"User-Agent": _DDG_UA}
            ) as client:
                resp = await client.post("https://html.duckduckgo.com/html/", data={"q": query})
                resp.raise_for_status()
            return self._parse_ddg_html(resp.text, max_results)
        except Exception as e:
            raise RuntimeError(f"DuckDuckGo all methods failed: {e}") from (last_err or e)

    def _parse_ddg_html(self, html: str, max_results: int) -> list[str]:
        results = []
        snippets = re.findall(
            r'class="result__a"[^>]*href="([^"]*)"[^>]*>(.*?)</a>.*?'
            r'class="result__snippet"[^>]*>(.*?)</a>',
            html, re.DOTALL,
        )
        for url, title, snippet in snippets[:max_results]:
            t = _html.unescape(re.sub(r"<[^>]+>", "", title).strip())
            s = _html.unescape(re.sub(r"<[^>]+>", "", snippet).strip())
            if t:
                results.append(f"**{t}**\n{s}\n{url}")
        if not results:
            for t in re.findall(r'class="result__a"[^>]*>(.*?)</a>', html)[:max_results]:
                clean = _html.unescape(re.sub(r"<[^>]+>", "", t).strip())
                if clean:
                    results.append(clean)
        return results

    # ── Bing General Search ──────────────────────────────────────────────────

    async def _bing_general_search(self, query: str, max_results: int) -> list[str]:
        """Bing 中国版通用搜索（HTML 解析）。作为 DuckDuckGo 不可用时的兜底。"""
        encoded = urllib.parse.quote(query)
        url = f"https://cn.bing.com/search?q={encoded}&count={max_results}"
        async with httpx.AsyncClient(
            timeout=12.0,
            follow_redirects=True,
            headers={
                "User-Agent": _DDG_UA,
                "Accept": "text/html,application/xhtml+xml",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            },
        ) as client:
            resp = await client.get(url)
            resp.raise_for_status()
        return self._parse_bing_html(resp.text, max_results)

    def _parse_bing_html(self, html: str, max_results: int) -> list[str]:
        """从 Bing 搜索结果 HTML 提取标题、摘要、URL。"""
        results = []
        # Bing 结果块：<li class="b_algo">
        algo_positions = [m.start() for m in re.finditer(r'class="b_algo"', html)]
        for pos in algo_positions[:max_results]:
            li_start = html.rfind("<li", max(0, pos - 100), pos)
            li_end = html.find("</li>", pos)
            if li_start < 0 or li_end < 0:
                continue
            block = html[li_start:li_end]
            # Title: <h2><a href="...">title</a></h2>
            title_m = re.search(r'<h2[^>]*><a[^>]*href="([^"]+)"[^>]*>(.*?)</a>', block, re.DOTALL)
            if not title_m:
                continue
            href = title_m.group(1)
            title = _html.unescape(re.sub(r"<[^>]+>", "", title_m.group(2)).strip())
            # Description: first <p> in block
            desc_m = re.search(r"<p[^>]*>(.*?)</p>", block, re.DOTALL)
            desc = ""
            if desc_m:
                desc = _html.unescape(re.sub(r"<[^>]+>", "", desc_m.group(1)).strip())[:200]
            if title:
                snippet = f"\n{desc}" if desc else ""
                results.append(f"**{title}**{snippet}\n{href}")
        return results
