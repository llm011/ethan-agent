"""Web Fetch Tool — 获取网页内容并提取文本。"""
import re

import httpx

from ethan.tools.base import BaseTool


class WebFetchTool(BaseTool):
    fast_path = False
    name = "web_fetch"
    description = "Fetch a webpage URL and extract its text content. Use for reading articles, documentation, or any web page."
    parameters = {
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "description": "The URL to fetch.",
            },
        },
        "required": ["url"],
    }

    async def run(self, url: str) -> str:
        try:
            headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"}
            async with httpx.AsyncClient(follow_redirects=True, timeout=15.0) as client:
                resp = await client.get(url, headers=headers)
                resp.raise_for_status()

            content_type = resp.headers.get("content-type", "")
            if "text/html" in content_type:
                text = self._extract_text(resp.text)
            else:
                text = resp.text

            if len(text) > 8000:
                text = text[:8000] + "\n...(truncated)"

            return text or "(empty page)"
        except Exception as e:
            return f"Fetch failed: {e}"

    def _extract_text(self, html: str) -> str:
        """从 HTML 中提取可读文本。"""
        # 移除 script 和 style
        html = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL | re.IGNORECASE)
        html = re.sub(r"<style[^>]*>.*?</style>", "", html, flags=re.DOTALL | re.IGNORECASE)
        # 移除 HTML 标签
        text = re.sub(r"<[^>]+>", " ", html)
        # 合并空白
        text = re.sub(r"\s+", " ", text).strip()
        # 按句子分行，便于阅读
        text = re.sub(r"\. ", ".\n", text)
        return text
