"""情节记忆 — 每个 Session 结束时生成 summary，独立存储。

相比 rolling summary（温区），episodic memory 保留每个 session 的独立摘要，
可按时间范围或关键词检索特定过去对话的上下文。
"""
import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from ethan.core.config import CONFIG_DIR

EPISODES_FILE = CONFIG_DIR / "memory" / "episodes.json"


@dataclass
class Episode:
    session_id: str
    summary: str
    timestamp: float = field(default_factory=time.time)
    model: str = ""
    turn_count: int = 0
    keywords: list[str] = field(default_factory=list)


class EpisodeStore:
    def __init__(self, path: Path = EPISODES_FILE):
        self._path = path
        self._episodes: list[Episode] = []
        self._load()

    def _load(self) -> None:
        if self._path.exists():
            try:
                data = json.loads(self._path.read_text(encoding="utf-8"))
                self._episodes = [Episode(**e) for e in data]
            except (json.JSONDecodeError, TypeError):
                self._episodes = []

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        data = [asdict(e) for e in self._episodes]
        self._path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def add(self, session_id: str, summary: str, model: str = "", turn_count: int = 0, keywords: list[str] | None = None) -> None:
        for e in self._episodes:
            if e.session_id == session_id:
                e.summary = summary
                e.keywords = keywords or []
                e.turn_count = turn_count
                self._save()
                return
        self._episodes.append(Episode(
            session_id=session_id,
            summary=summary,
            model=model,
            turn_count=turn_count,
            keywords=keywords or [],
        ))
        self._save()

    def search(self, query: str, limit: int = 5) -> list[Episode]:
        """Simple keyword search over episode summaries."""
        query_lower = query.lower()
        query_words = set(query_lower.split())

        scored = []
        for ep in self._episodes:
            text = ep.summary.lower() + " " + " ".join(ep.keywords)
            score = sum(1 for w in query_words if w in text)
            if score > 0:
                scored.append((score, ep))

        scored.sort(key=lambda x: (-x[0], -x[1].timestamp))
        return [ep for _, ep in scored[:limit]]

    def recent(self, limit: int = 10) -> list[Episode]:
        return sorted(self._episodes, key=lambda e: -e.timestamp)[:limit]

    def build_context(self, query: str = "", max_episodes: int = 3) -> str:
        """Build context from relevant past episodes."""
        if query:
            episodes = self.search(query, limit=max_episodes)
        else:
            episodes = self.recent(limit=max_episodes)

        if not episodes:
            return ""

        lines = []
        for ep in episodes:
            lines.append(f"- [{ep.session_id[-8:]}] {ep.summary}")
        return "\n".join(lines)

    def count(self) -> int:
        return len(self._episodes)
