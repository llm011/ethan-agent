"""httpx transport backed by curl_cffi.

为什么需要这个
--------------
某些第三方中转网关会拦截 Python httpx 的 TLS 指纹（ClientHello 阶段
`SSL: UNEXPECTED_EOF_WHILE_READING`），但 curl / libcurl 的 TLS 栈能正常握手
（curl_cffi 实测 200）。anthropic SDK 底层走 httpx，所以整套 LLM 调用链都被卡住。

本模块给 httpx 提供一个用 curl_cffi 发请求的 `AsyncBaseTransport`，让 anthropic
SDK 的 `http_client=` 指过来就能绕过指纹拦截。impersonate='chrome' 模拟 Chrome
的 JA3 指纹，是 curl_cffi 能连上的关键——默认指纹仍可能被拦。

非流式与流式（SSE）都支持：
- 非流式：anthropic SDK 调 `response.aread()`，会迭代 stream 到结束（等价缓冲）
- 流式：anthropic SDK 调 `response.aiter_raw()`，逐块产出 SSE 事件

两种模式共用同一个 `AsyncByteStream` 实现——它把 curl_cffi 的 `aiter_content`
桥接成 httpx 要的 `__aiter__` / `aclose`。
"""
from __future__ import annotations

from typing import AsyncIterator

import httpx


class _CurlStream(httpx.AsyncByteStream):
    """把 curl_cffi 流式 response 桥接成 httpx AsyncByteStream。

    curl_cffi 的 `aiter_content` 产出 bytes，正好是 httpx AsyncByteStream 要的
    `__aiter__` 协议。`aclose` 关掉底层 curl 流，释放连接。

    必须显式继承 `httpx.AsyncByteStream`——httpx 在 `_send_single_request` 里用
    `isinstance(response.stream, AsyncByteStream)` 断言，鸭子类型过不了。

    注意**不在这里关 session**：session 由 `CurlCffiTransport` 持有并在请求间复用
    （见该类的泄漏教训），流关闭只释放本次响应。若把 session 塞进来关，第一个响应
    读完连接池就被关了，后续请求全部重建。
    """

    def __init__(self, curl_response):
        self._r = curl_response

    def __aiter__(self) -> AsyncIterator[bytes]:
        return self._r.aiter_content()

    async def aclose(self) -> None:
        try:
            await self._r.aclose()
        except Exception:
            pass


class CurlCffiTransport(httpx.AsyncBaseTransport):
    """用 curl_cffi 发请求的 httpx async transport。

    `impersonate` 默认 'chrome'——某些网关拦截的是 Python OpenSSL 的 TLS 指纹，
    模拟 Chrome 的 JA3 能过。如果将来别的网关拦别的指纹，可换 'safari' / 'firefox'。
    """

    def __init__(self, *, impersonate: str = "chrome", proxy: str | None = None,
                 verify: bool = True, timeout: float = 600.0):
        self._impersonate = impersonate
        self._proxy = proxy
        self._verify = verify
        self._timeout = timeout
        self._session = None  # 懒建，请求间复用；aclose() 统一关闭

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        # 复用 transport 级 session：连接池跨请求保活，省每次 TLS 握手（curl_cffi
        # impersonate 的握手开销比原生 httpx 大，判官路径每次召回 1-2 次调用，
        # 新建 session 的握手成本不可忽略）。
        if self._session is None:
            from curl_cffi.requests import AsyncSession
            session_kwargs: dict = {
                "impersonate": self._impersonate,
                "verify": self._verify,
            }
            if self._proxy:
                session_kwargs["proxy"] = self._proxy
            self._session = AsyncSession(**session_kwargs)

        session = self._session
        try:
            # curl_cffi 用 data 收 raw bytes（httpx 的 request.content 就是字节）；
            # 空请求体传 None。stream=True 让 curl_cffi 不预读 body，SSE 才能逐块产出。
            request_kwargs: dict = {
                "method": request.method,
                "url": str(request.url),
                "headers": dict(request.headers),
                "stream": True,
                "timeout": self._timeout,
            }
            if request.content:
                request_kwargs["data"] = request.content
            resp = await session.request(**request_kwargs)
        except Exception as exc:
            # 会话可能已损坏（连接被网关掐断等），丢弃让下次重建
            await self._close_session()
            # 转成 httpx 的连接错误，让 anthropic SDK 走它的重试/报错路径
            raise httpx.ConnectError(str(exc) or "curl_cffi connect failed",
                                      request=request) from exc

        # 构造 httpx Response。stream 用 _CurlStream 桥接；session 留在 transport
        # 上复用，_CurlStream.aclose 只释放本次响应。非流式调用方会 aread()
        # 迭代到结束。headers 原样透传。
        return httpx.Response(
            status_code=resp.status_code,
            headers=httpx.Headers(resp.headers),
            stream=_CurlStream(resp),
            request=request,
        )

    async def _close_session(self) -> None:
        if self._session is not None:
            try:
                await self._session.close()
            except Exception:
                pass
            self._session = None

    async def aclose(self) -> None:
        await self._close_session()
