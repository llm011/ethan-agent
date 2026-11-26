"""Bounded synthetic HTTP peer; not an official service or live model."""
import json
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx

REASONS = ["  第一轮\n推理 α\t", "第二轮\n理由 β  "]
FINAL_REASON = "  无工具最终推理 γ\n"


class LocalOnlyTransport(httpx.AsyncHTTPTransport):
    def __init__(self, port, mutation=None):
        super().__init__(retries=0)
        self.port = port
        self.mutation = mutation

    async def handle_async_request(self, request):
        # Guard the real transport, including redirects/accidental production URLs.
        assert request.url.host == "127.0.0.1" and request.url.port == self.port
        if self.mutation:
            body = json.loads(await request.aread())
            assistants = [m for m in body["messages"] if m["role"] == "assistant"]
            if self.mutation == "drop":
                assistants[0].pop("reasoning_content", None)
            elif self.mutation == "swap":
                assistants[0]["reasoning_content"], assistants[1]["reasoning_content"] = (
                    assistants[1].get("reasoning_content"), assistants[0].get("reasoning_content"))
            elif self.mutation == "truncate":
                assistants[0]["reasoning_content"] = assistants[0].get("reasoning_content", "")[:-1]
            headers = dict(request.headers)
            headers.pop("content-length", None)
            request = httpx.Request(request.method, request.url, headers=headers,
                                    content=json.dumps(body).encode(), extensions=request.extensions)
        return await super().handle_async_request(request)


class StrictPeer:
    def __init__(self, final_reason):
        self.final_reason = final_reason
        self.expected = []
        self.accepted = 0
        self.rejected = 0
        self.requests = 0
        self.streaming = []

    def respond(self, body):
        self.requests += 1
        assert self.requests <= 8
        self.streaming.append(bool(body.get("stream")))
        actual = [m for m in body["messages"] if m["role"] == "assistant"]
        tools = [m for m in body["messages"] if m["role"] == "tool"]
        valid = len(actual) == len(self.expected)
        for message, expected in zip(actual, self.expected):
            valid &= message.get("reasoning_content") == expected["reasoning_content"] if expected["reasoning_content"] else not message.get("reasoning_content")
            valid &= message.get("content") == expected["content"]
            valid &= message.get("tool_calls", []) == expected.get("tool_calls", [])
        valid &= [m["tool_call_id"] for m in tools] == ["call-1", "call-2"][:min(len(self.expected), 2)]
        if not valid:
            self.rejected += 1
            return 400, {"error": {"message": "fixture strict reasoning mismatch", "type": "invalid_request_error"}}
        self.accepted += 1
        index = len(self.expected)
        message = {"role": "assistant", "content": "fixture done" if index >= 2 else None,
                   "reasoning_content": REASONS[index] if index < 2 else self.final_reason}
        if index < 2:
            message["tool_calls"] = [{"id": f"call-{index + 1}", "type": "function",
                                      "function": {"name": "fixture_read", "arguments": "{}"}}]
        self.expected.append(message)
        return 200, message


@contextmanager
def strict_peer(final_reason=FINAL_REASON):
    peer = StrictPeer(final_reason)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass  # No request bodies, headers, or credentials in logs.

        def do_POST(self):
            if self.path != "/v1/chat/completions" or peer.requests >= 8:
                self.send_error(400)
                return
            length = int(self.headers.get("content-length", "0"))
            if not 0 < length <= 200000:
                self.send_error(400)
                return
            body = json.loads(self.rfile.read(length))
            status, message = peer.respond(body)
            base = {"id": "fixture", "created": 1, "model": "deepseek-flash"}
            if status != 200:
                data = json.dumps(message).encode()
                content_type = "application/json"
            elif body.get("stream"):
                chunks = []
                reason = message["reasoning_content"]
                # Split Unicode/whitespace reasoning across actual SSE frames.
                for part in (reason[:3], reason[3:]):
                    chunks.append({**base, "object": "chat.completion.chunk", "choices": [
                        {"index": 0, "delta": {"reasoning_content": part}, "finish_reason": None}]})
                delta = {k: v for k, v in message.items() if k != "reasoning_content"}
                if "tool_calls" in delta:
                    delta["tool_calls"] = [{"index": 0, **delta["tool_calls"][0]}]
                chunks.append({**base, "object": "chat.completion.chunk", "choices": [
                    {"index": 0, "delta": delta, "finish_reason": "tool_calls" if "tool_calls" in message else "stop"}]})
                chunks.append({**base, "object": "chat.completion.chunk", "choices": [],
                               "usage": {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12}})
                data = ("".join(f"data: {json.dumps(chunk)}\n\n" for chunk in chunks) + "data: [DONE]\n\n").encode()
                content_type = "text/event-stream"
            else:
                data = json.dumps({**base, "object": "chat.completion", "choices": [
                    {"index": 0, "message": message, "finish_reason": "tool_calls" if "tool_calls" in message else "stop"}]}).encode()
                content_type = "application/json"
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    peer.port = server.server_port
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield peer
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
        assert not thread.is_alive()


async def local_provider(peer, base_url="https://api.deepseek.com", model="deepseek-flash", mutation=None):
    from ethan.core.config import ProviderConfig
    from ethan.providers._usage_observation import ObservedAsyncOpenAI
    from ethan.providers.openai_compat import OpenAICompatProvider

    provider = OpenAICompatProvider(ProviderConfig(api_key="fixture-not-a-secret", base_url=base_url), model)
    await provider._client.close()
    # Provider's endpoint identity remains official; only the test SDK client is local.
    provider._client = ObservedAsyncOpenAI(
        api_key="fixture-not-a-secret", base_url=f"http://127.0.0.1:{peer.port}/v1", max_retries=0,
        timeout=3, http_client=httpx.AsyncClient(trust_env=False, timeout=3,
                                               transport=LocalOnlyTransport(peer.port, mutation)))
    return provider
