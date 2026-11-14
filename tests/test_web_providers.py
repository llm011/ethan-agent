"""DeepSeek Search / Fetch 作为 web 工具 provider 的测试。

核心约束（来自官方 schema，写死在这里防回归）：
  · Search 的 `summary` 是「给模型读的长摘要」，`snippet` 是「给前端展示的短摘要」
  · count 上限 50
  · Fetch 返回的是现成 Markdown，不是 HTML
"""
from __future__ import annotations

from ethan.tools.builtin.web_search import WebSearchTool


class _FakeResp:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            import httpx

            raise httpx.HTTPStatusError("err", request=None, response=self)


def test_deepseek_uses_summary_not_snippet(monkeypatch):
    """summary 是官方定位的「给模型读」字段（600-800 字），snippet 只有 100-200 字。

    取错字段会让模型拿到信息量不足的短摘要。
    """
    payload = {
        "results": [
            {
                "title": "T",
                "url": "https://e.com",
                "snippet": "SHORT",
                "summary": "LONG_SUMMARY",
                "rerank_score": 2.5,
                "authority": 4,
                "site_name": "Example",
                "date": "2026-01-01T00:00:00+00:00",
            }
        ]
    }
    import httpx

    class _Client:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, *a, **kw):
            return _FakeResp(payload)

    monkeypatch.setattr(httpx, "AsyncClient", _Client)

    import asyncio

    out = asyncio.run(WebSearchTool()._deepseek_search("q", 5, "key"))
    assert out[0]["snippet"] == "LONG_SUMMARY"
    assert out[0]["engine"] == "deepseek"
    # 质量信号要带出来，供上层筛选
    assert out[0]["score"] == 2.5
    assert out[0]["authority"] == 4


def test_deepseek_falls_back_to_snippet_when_no_summary(monkeypatch):
    payload = {"results": [{"title": "T", "url": "u", "snippet": "ONLY_SNIPPET"}]}
    import httpx

    class _Client:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, *a, **kw):
            return _FakeResp(payload)

    monkeypatch.setattr(httpx, "AsyncClient", _Client)
    import asyncio

    out = asyncio.run(WebSearchTool()._deepseek_search("q", 5, "key"))
    assert out[0]["snippet"] == "ONLY_SNIPPET"


def test_deepseek_count_clamped_to_50(monkeypatch):
    """官方 count 上限 50，超了会 400。"""
    seen = {}
    import httpx

    class _Client:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, headers=None, json=None):
            seen["count"] = json["count"]
            return _FakeResp({"results": []})

    monkeypatch.setattr(httpx, "AsyncClient", _Client)
    import asyncio

    asyncio.run(WebSearchTool()._deepseek_search("q", 999, "key"))
    assert seen["count"] == 50


def test_deepseek_empty_results_not_an_error(monkeypatch):
    """无结果是正常返回（且不计费），不是失败——不该触发熔断。"""
    import httpx

    class _Client:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, *a, **kw):
            return _FakeResp({"results": []})

    monkeypatch.setattr(httpx, "AsyncClient", _Client)
    import asyncio

    assert asyncio.run(WebSearchTool()._deepseek_search("q", 5, "key")) == []


def test_deepseek_auth_header(monkeypatch):
    """鉴权走 Bearer，与 DeepSeek 其他 API 一致。"""
    seen = {}
    import httpx

    class _Client:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, headers=None, json=None):
            seen["auth"] = headers.get("Authorization")
            seen["url"] = url
            return _FakeResp({"results": []})

    monkeypatch.setattr(httpx, "AsyncClient", _Client)
    import asyncio

    asyncio.run(WebSearchTool()._deepseek_search("q", 5, "sk-test", "https://api.deepseek.com"))
    assert seen["auth"] == "Bearer sk-test"
    assert seen["url"] == "https://api.deepseek.com/v1/tools/search"
