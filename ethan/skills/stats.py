import json
import time
from pathlib import Path

from ethan.core.config import CONFIG_DIR

STATS_FILE = CONFIG_DIR / "skills" / ".stats.json"


class SkillStats:
    def __init__(self, path: Path = STATS_FILE):
        self._path = path
        self._data: dict = {}
        self._load()

    def _load(self):
        if self._path.exists():
            try:
                self._data = json.loads(self._path.read_text(encoding="utf-8"))
            except Exception:
                self._data = {}

    def _save(self):
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(self._data, ensure_ascii=False, indent=2), encoding="utf-8")

    def record_hit(self, skill_name: str):
        e = self._data.setdefault(skill_name, {"hit_count": 0, "corrections": [], "last_hit": 0})
        e["hit_count"] += 1
        e["last_hit"] = time.time()
        self._save()

    def record_correction(self, skill_name: str, correction: str):
        e = self._data.setdefault(skill_name, {"hit_count": 0, "corrections": [], "last_hit": 0})
        if correction not in e["corrections"]:
            e["corrections"].append(correction)
        self._save()

    def get(self, skill_name: str) -> dict:
        return self._data.get(skill_name, {"hit_count": 0, "corrections": [], "last_hit": 0})

    def all(self) -> dict:
        return dict(self._data)

    def needs_update(self, skill_name: str, threshold: int = 2) -> bool:
        return len(self.get(skill_name)["corrections"]) >= threshold
