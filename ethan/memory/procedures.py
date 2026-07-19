"""过程记忆 — Agent 从用户纠正中学习行为准则（Phase 2e）。

当用户纠正 agent（"不对"、"不要这样"、"应该用..."），
自动提取并持久化为行为准则，注入未来的 system prompt。

注：success_patterns（成功路径，B1 扩展）已于 2026-07 退役。
原因：从 tool_steps 共现统计抽取的"模式"99.4% 是只出现一次的噪声，
且 scenario 字段被 LLM 自身的 meta 污染，注入 system prompt 信息增益为 0。
真正有价值的"行为准则"由 procedure_write 工具 / Consolidator 显式写入。
"""
import json
import logging
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from ethan.core.config import CONFIG_DIR

PROCEDURES_FILE = CONFIG_DIR / "memory" / "playbook.json"

logger = logging.getLogger(__name__)


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
        path = self._path
        if not path.exists():
            # 向后兼容：playbook.json 不存在时回退读旧的 procedures.json
            legacy = path.parent / "procedures.json"
            if legacy.exists() and legacy != path:
                path = legacy
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                # 兼容旧格式：
                # - 纯 list[dict] → procedures
                # - dict 含 procedures + success_patterns → 只取 procedures（success_patterns 已退役）
                if isinstance(data, list):
                    self._procedures = [Procedure(**p) for p in data]
                elif isinstance(data, dict):
                    self._procedures = [Procedure(**p) for p in data.get("procedures", [])]
            except (json.JSONDecodeError, TypeError):
                self._procedures = []

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        # 保留 success_patterns 字段为空列表，避免旧版本读取报错；
        # 旧数据由 _load 主动丢弃。
        data = {
            "procedures": [asdict(p) for p in self._procedures],
            "success_patterns": [],
        }
        self._path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def add(self, rule: str, context: str = "") -> None:
        from ethan.core.secrets_store import mask_text
        rule = mask_text(rule)
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
