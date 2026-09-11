"""外部 REST API 知识库后端。"""
from urllib.parse import quote

from .contracts import KnowledgeBase, KnowledgeItem


class ExternalKnowledgeBase(KnowledgeBase):
    """通过 REST API 连接外部知识库服务。

    scene 参数用于按场景隔离（如 'work'/'life'）。客户端会把 scene 作为
    query 参数 / payload 字段传给外部服务；外部服务应按 scene 隔离存储与搜索，
    以履行 knowledge 工具宣称的 "Different scenes are isolated for storage
    and search" 契约。scene 为空时不传该字段，向后兼容。
    """

    def __init__(self, base_url: str, api_key: str = "", headers: dict[str, str] | None = None,
                 scene: str = ""):
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._scene = scene
        self._headers = headers or {}
        if api_key:
            self._headers.setdefault("Authorization", f"Bearer {api_key}")

    def _client(self):
        import httpx
        return httpx.Client(base_url=self._base_url, headers=self._headers, timeout=30)

    def _async_client(self):
        import httpx
        return httpx.AsyncClient(base_url=self._base_url, headers=self._headers, timeout=30)

    @staticmethod
    def _encode_source(source: str) -> str:
        """URL-encode source，避免 / # ? 等字符破坏路径。"""
        return quote(str(source), safe="")

    def _scene_params(self, extra: dict | None = None) -> dict:
        """构造 query 参数，scene 非空时附加。"""
        params = dict(extra or {})
        if self._scene:
            params.setdefault("scene", self._scene)
        return params

    def _with_scene(self, payload: dict) -> dict:
        """给 POST/PUT payload 注入 scene 字段（非空时）。"""
        if self._scene:
            return {**payload, "scene": self._scene}
        return payload

    # ── Write ──────────────────────────────────────────────────────────────

    def add(self, title: str, content: str, tags: list[str] | None = None,
            frontmatter: dict | None = None) -> str:
        payload = self._with_scene({"title": title, "content": content, "tags": tags or []})
        if frontmatter:
            payload["frontmatter"] = frontmatter
        with self._client() as client:
            resp = client.post("/items", json=payload)
            resp.raise_for_status()
            data = resp.json()
            return data.get("source") or data.get("id") or ""

    def update(self, source: str, title: str, content: str, tags: list[str] | None = None,
               frontmatter: dict | None = None) -> None:
        payload = self._with_scene({"title": title, "content": content, "tags": tags or []})
        if frontmatter:
            payload["frontmatter"] = frontmatter
        with self._client() as client:
            resp = client.put(f"/items/{self._encode_source(source)}", json=payload)
            resp.raise_for_status()

    def delete(self, source: str) -> None:
        with self._client() as client:
            resp = client.delete(
                f"/items/{self._encode_source(source)}", params=self._scene_params()
            )
            resp.raise_for_status()

    # ── Search ─────────────────────────────────────────────────────────────

    def search(self, query: str, limit: int = 5) -> list[KnowledgeItem]:
        with self._client() as client:
            resp = client.get(
                "/search", params=self._scene_params({"q": query, "limit": limit})
            )
            resp.raise_for_status()
            return self._parse_items(resp.json())

    async def semantic_search(self, query: str, limit: int = 5) -> list[KnowledgeItem]:
        async with self._async_client() as client:
            resp = await client.get(
                "/search",
                params=self._scene_params({"q": query, "limit": limit, "semantic": "true"}),
            )
            resp.raise_for_status()
            return self._parse_items(resp.json())

    # ── Read ───────────────────────────────────────────────────────────────

    def list_all(self) -> list[KnowledgeItem]:
        with self._client() as client:
            resp = client.get("/items", params=self._scene_params())
            resp.raise_for_status()
            return self._parse_items(resp.json())

    def get(self, source: str) -> KnowledgeItem | None:
        with self._client() as client:
            resp = client.get(
                f"/items/{self._encode_source(source)}", params=self._scene_params()
            )
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            data = resp.json()
            return KnowledgeItem(
                title=data.get("title", ""),
                content=data.get("content", ""),
                source=data.get("source") or data.get("id") or source,
                tags=data.get("tags") or [],
            )

    def health_check(self) -> tuple[bool, str]:
        import httpx
        try:
            with self._client() as client:
                # 尝试 /health 端点，退而求其次 /
                for endpoint in ("/health", "/"):
                    try:
                        resp = client.get(endpoint)
                        if resp.status_code < 500:
                            return True, f"External KB API reachable (status={resp.status_code}): {self._base_url}"
                    except httpx.HTTPError:
                        continue
                return False, f"External KB API not healthy: {self._base_url}"
        except Exception as e:
            return False, f"External KB API connection failed: {e}"

    # ── Internal ───────────────────────────────────────────────────────────

    def _parse_items(self, data) -> list[KnowledgeItem]:
        """从 API 响应解析条目列表，兼容 {"items": [...]} 或直接 [...] 格式。"""
        if data is None:
            return []
        items_raw = data if isinstance(data, list) else data.get("items") or data.get("results") or []
        items = []
        for d in items_raw:
            items.append(KnowledgeItem(
                title=d.get("title", ""),
                content=d.get("content", ""),
                source=d.get("source") or d.get("id") or "",
                tags=d.get("tags") or [],
            ))
        return items
