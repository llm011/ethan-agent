"""过程记忆 — Agent 从用户纠正中学习行为准则（Phase 2e）。

当用户纠正 agent（"不对"、"不要这样"、"应该用..."），
自动提取并持久化为行为准则，注入未来的 system prompt。
"""
import json
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path

from ethan.core.config import CONFIG_DIR

PROCEDURES_FILE = CONFIG_DIR / "memory" / "procedures.json"


@dataclass
class Procedure:
    rule: str
    context: str = ""
    created_at: float = field(default_factory=time.time)
    hit_count: int = 0


class ProcedureStore:
    def __init__(self, path: Path = PROCEDURES_FILE):
        self._path = path
        self._procedures: list[Procedure] = []
        self._load()

    def _load(self) -> None:
        if self._path.exists():
            try:
                data = json.loads(self._path.read_text(encoding="utf-8"))
                self._procedures = [Procedure(**p) for p in data]
            except (json.JSONDecodeError, TypeError):
                self._procedures = []

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        data = [asdict(p) for p in self._procedures]
        self._path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def add(self, rule: str, context: str = "") -> None:
        for p in self._procedures:
            if p.rule.lower().strip() == rule.lower().strip():
                p.hit_count += 1
                self._save()
                return
        self._procedures.append(Procedure(rule=rule, context=context))
        self._save()

    def remove(self, rule: str) -> bool:
        before = len(self._procedures)
        self._procedures = [p for p in self._procedures if p.rule.lower().strip() != rule.lower().strip()]
        if len(self._procedures) < before:
            self._save()
            return True
        return False

    def all(self) -> list[Procedure]:
        return list(self._procedures)

    def build_context(self) -> str:
        if not self._procedures:
            return ""
        lines = ["Behavioral guidelines (learned from past corrections):"]
        for p in sorted(self._procedures, key=lambda x: -x.hit_count):
            lines.append(f"- {p.rule}")
        return "\n".join(lines)

    def count(self) -> int:
        return len(self._procedures)
