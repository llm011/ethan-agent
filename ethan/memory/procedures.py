"""过程记忆 — Agent 从用户纠正中学习行为准则（Phase 2e）。

当用户纠正 agent（"不对"、"不要这样"、"应该用..."），
自动提取并持久化为行为准则，注入未来的 system prompt。

B1 扩展：同时存储 success_patterns（成功路径），从心跳任务的决策模式抽取中沉淀。
"""
import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from ethan.core.config import CONFIG_DIR

PROCEDURES_FILE = CONFIG_DIR / "memory" / "playbook.json"


@dataclass
class Procedure:
    rule: str
    context: str = ""
    created_at: float = field(default_factory=time.time)
    hit_count: int = 0


@dataclass
class SuccessPattern:
    """B1: 从 tool_steps 中提取的成功路径，注入 behavioral_guidelines 作为正反馈。"""
    scenario: str           # 场景描述（如"查京东订单"）
    tool_sequence: list[str]  # 工具调用序列（如 ["shell:jd_query", "file_write:save"]）
    success_count: int = 1
    last_used: float = field(default_factory=time.time)


class ProcedureStore:
    def __init__(self, path: Path = PROCEDURES_FILE):
        self._path = path
        self._procedures: list[Procedure] = []
        self._success_patterns: list[SuccessPattern] = []
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
                # 兼容旧格式：纯 list[dict] → procedures；新格式：{"procedures": [...], "success_patterns": [...]}
                if isinstance(data, list):
                    self._procedures = [Procedure(**p) for p in data]
                elif isinstance(data, dict):
                    self._procedures = [Procedure(**p) for p in data.get("procedures", [])]
                    self._success_patterns = [SuccessPattern(**p) for p in data.get("success_patterns", [])]
            except (json.JSONDecodeError, TypeError):
                self._procedures = []

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "procedures": [asdict(p) for p in self._procedures],
            "success_patterns": [asdict(p) for p in self._success_patterns],
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

    def add_success_pattern(self, scenario: str, tool_sequence: list[str]) -> None:
        """B1: 添加或更新成功路径。相同 scenario 合并，success_count 累加。"""
        for p in self._success_patterns:
            if p.scenario.lower().strip() == scenario.lower().strip():
                p.success_count += 1
                p.last_used = time.time()
                # 合并 tool_sequence（去重保序）
                seen = set(p.tool_sequence)
                for t in tool_sequence:
                    if t not in seen:
                        p.tool_sequence.append(t)
                        seen.add(t)
                self._save()
                return
        self._success_patterns.append(SuccessPattern(
            scenario=scenario,
            tool_sequence=tool_sequence,
        ))
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

    def all_success_patterns(self) -> list[SuccessPattern]:
        return list(self._success_patterns)

    def build_context(self) -> str:
        if not self._procedures and not self._success_patterns:
            return ""
        lines = ["Behavioral guidelines (learned from past corrections):"]
        for p in sorted(self._procedures, key=lambda x: -x.hit_count):
            lines.append(f"- {p.rule}")
        # B1: 注入成功路径作为正反馈
        if self._success_patterns:
            lines.append("")
            lines.append("Success patterns (similar scenarios worked well before):")
            for p in sorted(self._success_patterns, key=lambda x: -x.success_count):
                seq = " → ".join(p.tool_sequence)
                lines.append(f"- {p.scenario}: {seq} ({p.success_count}次成功)")
        return "\n".join(lines)

    def count(self) -> int:
        return len(self._procedures)
