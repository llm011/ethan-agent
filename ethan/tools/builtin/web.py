"""Web Fetch Tool — 获取网页内容并提取文本。"""
import re

import httpx

from ethan.tools.base import BaseTool


class WebFetchTool(BaseTool):
    fast_path = False
    no_compress = True  # 文章/文档原文必须逐字给模型，压成摘要会丢关键信息
    name = "web_fetch"
    description = (
        "Fetch a URL and return its content. Supports GET (default) and POST methods. "
        "Use for reading web pages, calling REST APIs, or fetching structured data (JSON/XML). "
        "For APIs that require POST body (e.g., Overpass API), set method='POST' and provide body. "
        "This runs server-side, bypassing browser CSP restrictions."
    )
    parameters = {
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "description": "The URL to fetch.",
            },
            "method": {
                "type": "string",
                "enum": ["GET", "POST"],
                "description": "HTTP method. Default GET.",
            },
            "body": {
                "type": "string",
                "description": "Request body for POST requests (form data or JSON string).",
            },
            "content_type": {
                "type": "string",
                "description": "Content-Type header for POST (e.g., 'application/json', 'application/x-www-form-urlencoded'). Default: auto-detect.",
            },
        },
        "required": ["url"],
    }

    async def run(self, url: str, method: str = "GET", body: str = "", content_type: str = "") -> str:
        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                              "AppleWebKit/537.36 (KHTML, like Gecko) "
                              "Chrome/120.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            }
            if content_type:
                headers["Content-Type"] = content_type
            # 从 ethan config 读取网络代理（支持需要翻墙的站点）
            proxy_url = None
            try:
                from ethan.core.config import load_config
                proxy_url = load_config().network.proxy or None
            except Exception:
                pass
            async with httpx.AsyncClient(follow_redirects=True, timeout=30.0, proxy=proxy_url) as client:
                if method.upper() == "POST":
                    resp = await client.post(url, headers=headers, content=body.encode() if body else None)
                else:
                    resp = await client.get(url, headers=headers)
                resp.raise_for_status()  # status_code 有问题直接抛异常，不浪费 token

            resp_ct = resp.headers.get("content-type", "")
            if "text/html" in resp_ct:
                text = self._extract_text(resp.text)
            else:
                text = resp.text

            # 不截断，让 registry 的 compressor（4000字阈值）决定是否压缩

            return text or "(empty page)"
        except httpx.HTTPStatusError as e:
            # status_code 错误，不返回页面内容（浪费 token）
            return f"Fetch failed: HTTP {e.response.status_code} for {url}"
        except Exception as e:
            return f"Fetch failed: {e}"

    def _extract_text(self, html: str) -> str:
        """从 HTML 中提取可读文本 + 图片 URL 列表。

        图片 URL 优先取 data-src（微信等懒加载站点真实地址在 data-src），
        回退 src。提取后去重保序，附在正文末尾，供上层决定是否下载/上传。
        """
        # 移除 script 和 style
        html = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL | re.IGNORECASE)
        html = re.sub(r"<style[^>]*>.*?</style>", "", html, flags=re.DOTALL | re.IGNORECASE)

        # 提取所有图片 URL（data-src 优先，src 回退）
        img_urls: list[str] = []
        for m in re.finditer(r"<img[^>]*/?>", html, re.IGNORECASE):
            tag = m.group(0)
            url_m = (
                re.search(r'data-src="([^"]+)"', tag, re.IGNORECASE)
                or re.search(r'src="([^"]+)"', tag, re.IGNORECASE)
            )
            if url_m:
                url = url_m.group(1).replace("&amp;", "&")
                if url.startswith("http"):
                    img_urls.append(url)

        # 移除 HTML 标签
        text = re.sub(r"<[^>]+>", " ", html)
        # 合并空白
        text = re.sub(r"\s+", " ", text).strip()
        # 按句子分行，便于阅读
        text = re.sub(r"\. ", ".\n", text)

        # 附加去重后的图片列表
        if img_urls:
            unique = list(dict.fromkeys(img_urls))  # 去重保序
            text += "\n\n---图片列表---\n" + "\n".join(
                f"{i + 1}. {u}" for i, u in enumerate(unique)
            )

        return text
