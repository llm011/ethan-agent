"""Notion 知识库后端 — child page 模型 + markdown ⇄ blocks 转换。"""
from ._helpers import _safe_subpath
from .contracts import KnowledgeBase, KnowledgeItem

_NOTION_VERSION = "2022-06-28"
_NOTION_TEXT_LIMIT = 1900  # Notion rich_text 单块上限 2000，留余量
_NOTION_MAX_CHILDREN = 100  # Notion 单次创建/追加 children 的上限


class NotionKnowledgeBase(KnowledgeBase):
    """Notion 作为知识库后端。

    模型：一个 root page 作为知识库根，每个条目是 root 下的一个 **child page**。
    层级标签（tags[0] 如 "work/coze/prd"）会在 root 下按段创建/复用中间 page，
    条目落在最深一级，与 filesystem/Obsidian 的多层级目录打平。

    - title  → child page 标题
    - content→ 页面正文（markdown 按段落/标题转 Notion blocks，超长自动分块）
    - tags   → 正文顶部一行 `Tags: a, b` 记录（Notion 普通 page 无自定义属性）
    - source → Notion page id（32 位 hex，可带连字符）

    scene 隔离：scene 非空时在 root 下先建一层 `{scene}` page 作为该场景子根。
    """

    def __init__(self, token: str, root_page_id: str, scene: str = ""):
        self._token = token
        self._root_page_id = (root_page_id or "").replace("-", "")
        self._scene = scene
        self._api = "https://api.notion.com/v1"

    # ── HTTP ─────────────────────────────────────────────────────────────
    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self._token}",
            "Notion-Version": _NOTION_VERSION,
            "Content-Type": "application/json",
        }

    def _client(self):
        import httpx
        return httpx.Client(base_url=self._api, headers=self._headers(), timeout=30, trust_env=False)

    # ── markdown ⇄ blocks ────────────────────────────────────────────────
    @staticmethod
    def _text_chunks(s: str) -> list[str]:
        return [s[i:i + _NOTION_TEXT_LIMIT] for i in range(0, len(s), _NOTION_TEXT_LIMIT)] or [""]

    @classmethod
    def _md_to_blocks(cls, content: str) -> list[dict]:
        """极简 markdown → Notion blocks：# 标题 → heading，其余按行 → paragraph。

        不追求完整还原，只保证内容可读、可往返（get 再拼回纯文本）。
        不做数量截断——超过单次 API 上限的部分由调用方分批写入（见 _write_children_batched）。
        """
        blocks: list[dict] = []
        for line in content.splitlines():
            stripped = line.rstrip()
            if not stripped:
                blocks.append({"object": "block", "type": "paragraph",
                               "paragraph": {"rich_text": []}})
                continue
            btype = "paragraph"
            text = stripped
            for lvl, mark in ((3, "### "), (2, "## "), (1, "# ")):
                if stripped.startswith(mark):
                    btype = f"heading_{lvl}"
                    text = stripped[len(mark):]
                    break
            rich = [{"type": "text", "text": {"content": c}} for c in cls._text_chunks(text)]
            blocks.append({"object": "block", "type": btype, btype: {"rich_text": rich}})
        return blocks

    @staticmethod
    def _write_children_batched(client, parent_id: str, blocks: list[dict]) -> None:
        """把 blocks 分批 append 到 parent，绕过 Notion 单次 100 children 上限。

        长笔记不再静默丢内容：超过 100 块的部分按批次续写。
        """
        for i in range(0, len(blocks), _NOTION_MAX_CHILDREN):
            batch = blocks[i:i + _NOTION_MAX_CHILDREN]
            client.patch(f"/blocks/{parent_id}/children",
                         json={"children": batch}).raise_for_status()

    @staticmethod
    def _all_child_blocks(client, parent_id: str) -> list[dict]:
        """翻页取回 parent 下**全部** child block（不止前 100），供读取/删除用。"""
        out: list[dict] = []
        cursor = None
        while True:
            params = {"page_size": 100}
            if cursor:
                params["start_cursor"] = cursor
            resp = client.get(f"/blocks/{parent_id}/children", params=params)
            resp.raise_for_status()
            data = resp.json()
            out.extend(data.get("results", []))
            if not data.get("has_more"):
                break
            cursor = data.get("next_cursor")
        return out

    @staticmethod
    def _blocks_to_text(blocks: list[dict]) -> str:
        lines: list[str] = []
        for b in blocks:
            t = b.get("type", "")
            payload = b.get(t, {})
            rich = payload.get("rich_text", []) if isinstance(payload, dict) else []
            text = "".join(r.get("plain_text") or r.get("text", {}).get("content", "") for r in rich)
            if t == "heading_1":
                lines.append(f"# {text}")
            elif t == "heading_2":
                lines.append(f"## {text}")
            elif t == "heading_3":
                lines.append(f"### {text}")
            else:
                lines.append(text)
        return "\n".join(lines).strip()

    # ── 层级容器 page 解析/创建 ───────────────────────────────────────────
    def _child_pages(self, parent_id: str) -> list[dict]:
        """返回 parent 下所有 child_page 块 [{id, title}]。"""
        out: list[dict] = []
        cursor = None
        with self._client() as c:
            while True:
                params = {"page_size": 100}
                if cursor:
                    params["start_cursor"] = cursor
                resp = c.get(f"/blocks/{parent_id}/children", params=params)
                resp.raise_for_status()
                data = resp.json()
                for blk in data.get("results", []):
                    if blk.get("type") == "child_page":
                        out.append({"id": blk["id"].replace("-", ""),
                                    "title": blk["child_page"].get("title", "")})
                if not data.get("has_more"):
                    break
                cursor = data.get("next_cursor")
        return out

    def _find_or_create_container(self, parent_id: str, title: str) -> str:
        for p in self._child_pages(parent_id):
            if p["title"] == title:
                return p["id"]
        with self._client() as c:
            resp = c.post("/pages", json={
                "parent": {"page_id": parent_id},
                "properties": {"title": {"title": [{"text": {"content": title}}]}},
            })
            resp.raise_for_status()
            return resp.json()["id"].replace("-", "")

    def _resolve_parent(self, tags: list[str] | None) -> str:
        """根据 scene + tags[0] 层级解析出条目应挂载的父 page id（沿途创建容器）。"""
        parent = self._root_page_id
        if self._scene:
            parent = self._find_or_create_container(parent, self._scene)
        if tags:
            subpath = _safe_subpath(tags[0])
            if subpath:
                for seg in subpath.parts:
                    parent = self._find_or_create_container(parent, seg)
        return parent

    # ── Write ────────────────────────────────────────────────────────────
    def add(self, title: str, content: str, tags: list[str] | None = None,
            frontmatter: dict | None = None) -> str:
        parent = self._resolve_parent(tags)
        body = content
        if tags:
            body = f"Tags: {', '.join(tags)}\n\n{content}"
        blocks = self._md_to_blocks(body)
        with self._client() as c:
            # 建页时最多带 100 个 children，其余分批 append，避免长笔记尾部丢失
            resp = c.post("/pages", json={
                "parent": {"page_id": parent},
                "properties": {"title": {"title": [{"text": {"content": title}}]}},
                "children": blocks[:_NOTION_MAX_CHILDREN],
            })
            resp.raise_for_status()
            pid = resp.json()["id"].replace("-", "")
            if len(blocks) > _NOTION_MAX_CHILDREN:
                self._write_children_batched(c, pid, blocks[_NOTION_MAX_CHILDREN:])
            return pid

    def update(self, source: str, title: str, content: str, tags: list[str] | None = None,
               frontmatter: dict | None = None) -> None:
        pid = source.replace("-", "")
        body = content
        if tags:
            body = f"Tags: {', '.join(tags)}\n\n{content}"
        with self._client() as c:
            # 更新标题
            c.patch(f"/pages/{pid}", json={
                "properties": {"title": {"title": [{"text": {"content": title}}]}},
            }).raise_for_status()
            # 清空旧 block 再写新（Notion 无整页替换，逐块删）。
            # 必须翻页取全部旧 block，否则超过 100 块的页面残留尾部会和新内容混在一起。
            for blk in self._all_child_blocks(c, pid):
                try:
                    c.delete(f"/blocks/{blk['id']}").raise_for_status()
                except Exception:
                    pass
            # 新内容分批写入，绕过单次 100 children 上限
            self._write_children_batched(c, pid, self._md_to_blocks(body))

    def delete(self, source: str) -> None:
        pid = source.replace("-", "")
        with self._client() as c:
            # Notion 无硬删除，归档即移出知识库
            c.patch(f"/pages/{pid}", json={"archived": True}).raise_for_status()

    def append(self, source: str, content: str) -> str:
        pid = source.replace("-", "")
        with self._client() as c:
            self._write_children_batched(c, pid, self._md_to_blocks(content))
        return pid  # 遵守基类契约：返回条目 source

    # ── Search / Read ────────────────────────────────────────────────────
    def _parent_page_id(self, pg: dict) -> str | None:
        """取 page 的直接父 page id（仅当 parent 是 page 时），否则 None。"""
        parent = pg.get("parent") or {}
        if parent.get("type") == "page_id":
            return (parent.get("page_id") or "").replace("-", "")
        return None

    def _is_within_root(self, pg: dict, client, root_id: str, cache: dict) -> bool:
        """沿 parent 链上溯，判断 page 是否落在 root_id 子树内。

        Notion /search 是 workspace 级的，会返回 integration 可见的所有页面；
        必须按 root 过滤，否则 people-kb 去重/召回会误匹配知识库外的页面。
        """
        seen: set[str] = set()
        parent_id = self._parent_page_id(pg)
        depth = 0
        while parent_id and depth < 25:
            if parent_id == root_id:
                return True
            if parent_id in seen:  # 环保护
                return False
            seen.add(parent_id)
            # 缓存父链，避免同一批结果重复请求
            if parent_id in cache:
                parent_id = cache[parent_id]
            else:
                pr = client.get(f"/pages/{parent_id}")
                if pr.status_code != 200:
                    return False
                nxt = self._parent_page_id(pr.json())
                cache[parent_id] = nxt
                parent_id = nxt
            depth += 1
        return False

    def _resolve_scene_root(self, client) -> str | None:
        """scene 非空时返回 root 下的 `{scene}` 容器 id（find-only，不创建）；
        找不到返回 None（该 scene 尚无内容）。scene 为空时返回真实 root。"""
        if not self._scene:
            return self._root_page_id
        for p in self._child_pages(self._root_page_id):
            if p["title"] == self._scene:
                return p["id"]
        return None

    def search(self, query: str, limit: int = 5) -> list[KnowledgeItem]:
        with self._client() as c:
            effective_root = self._resolve_scene_root(c)
            if effective_root is None:
                return []  # scene 容器还没建，说明该场景无任何条目
            # Notion /search 无 parent 过滤能力，先多取一些候选再按 root 收敛
            resp = c.post("/search", json={
                "query": query,
                "filter": {"property": "object", "value": "page"},
                "page_size": max(limit * 4, 20),
            })
            resp.raise_for_status()
            items: list[KnowledgeItem] = []
            ancestry_cache: dict[str, str | None] = {}
            for pg in resp.json().get("results", []):
                if len(items) >= limit:
                    break
                if not self._is_within_root(pg, c, effective_root, ancestry_cache):
                    continue  # 跳过知识库 root 之外的页面
                it = self._page_to_item(pg, with_content=False)
                if it:
                    items.append(it)
            return items

    async def semantic_search(self, query: str, limit: int = 5) -> list[KnowledgeItem]:
        # Notion 无向量检索，退回关键词 search
        return self.search(query, limit)

    def list_all(self) -> list[KnowledgeItem]:
        # 递归遍历 root（或 scene 子根）下所有 child page
        root = self._root_page_id
        if self._scene:
            for p in self._child_pages(self._root_page_id):
                if p["title"] == self._scene:
                    root = p["id"]
                    break
        items: list[KnowledgeItem] = []
        self._walk(root, items)
        return items

    def _walk(self, parent_id: str, out: list[KnowledgeItem]) -> None:
        self._walk_pages(self._child_pages(parent_id), out)

    def _walk_pages(self, pages: list[dict], out: list[KnowledgeItem]) -> None:
        """区分层级容器页与知识条目页：
        - 有子 page → 视作层级容器（work/、work/coze/ 这种），只递归、不收录，
          否则空正文的容器页会以空标题条目混进 list_all，且每页 get() 一次形成 N+1。
        - 无子 page → 叶子，才是真正的知识条目。
        条目在本 KB 中始终是叶子（add 总把新页挂在容器下），故该启发式成立。
        """
        for p in pages:
            children = self._child_pages(p["id"])
            if children:
                self._walk_pages(children, out)
            else:
                it = self.get(p["id"])
                if it:
                    out.append(it)

    def get(self, source: str) -> KnowledgeItem | None:
        pid = source.replace("-", "")
        with self._client() as c:
            pr = c.get(f"/pages/{pid}")
            if pr.status_code == 404:
                return None
            pr.raise_for_status()
            pg = pr.json()
            # 归档页 = 已删除（delete 用 archived=true 实现）。Notion 对归档页
            # /pages 仍返回 200，但其 children 已不可读（404）——视作不存在。
            if pg.get("archived") or pg.get("in_trash"):
                return None
            return self._page_to_item(pg, with_content=True)

    def _page_to_item(self, pg: dict, with_content: bool) -> KnowledgeItem | None:
        pid = pg.get("id", "").replace("-", "")
        if not pid:
            return None
        title = ""
        props = pg.get("properties", {})
        for prop in props.values():
            if prop.get("type") == "title":
                title = "".join(t.get("plain_text", "") for t in prop.get("title", []))
                break
        content, tags = "", []
        if with_content:
            with self._client() as c:
                # 翻页取全部 block，避免长笔记只读到前 100 块——
                # 基于截断内容再 update 会永久丢失尾部
                blocks = self._all_child_blocks(c, pid)
            content = self._blocks_to_text(blocks)
            if content.startswith("Tags:"):
                first, _, rest = content.partition("\n")
                tags = [t.strip() for t in first[len("Tags:"):].split(",") if t.strip()]
                content = rest.strip()
        return KnowledgeItem(title=title, content=content, source=pid, tags=tags)

    def health_check(self) -> tuple[bool, str]:
        if not self._token:
            return False, "Notion token 未配置"
        if not self._root_page_id:
            return False, "Notion root_page_id 未配置"
        try:
            with self._client() as c:
                resp = c.get(f"/pages/{self._root_page_id}")
                if resp.status_code == 200:
                    return True, f"Notion 后端 OK：root={self._root_page_id[:8]}…"
                if resp.status_code in (401, 403):
                    return False, "Notion token 无效或未授权访问该 root page（需在 Notion 里把页面分享给 integration）"
                if resp.status_code == 404:
                    return False, "找不到 root page（检查 root_page_id，并确认已分享给 integration）"
                return False, f"Notion API 返回 {resp.status_code}"
        except Exception as e:
            return False, f"Notion 连接失败：{e}"
