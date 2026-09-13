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


def _mask_rule(rule: str) -> str:
    """把准则文本里出现的已知 secret 真值换成 <secret:name> 引用。

    准则会被 `build_context()` 拼进 system prompt，**每轮都发往 LLM provider** ——
    真值一旦落盘就等于反复外发。写入路径（`add` / `update`）必须都过这一道。

    只是 `str.replace` 已知的本地 secret 真值，不是给用户输入做通用脱敏：
    手写的普通文本不会被碰，所以不存在「误伤用户内容」的问题。

    函数内 import 沿用原写法，避免与 secrets_store 产生模块级循环依赖。
    """
    from ethan.core.services.secrets_store import mask_text
    return mask_text(rule)


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
        rule = _mask_rule(rule)
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

    def update(self, index: int, rule: str, context: str | None = None) -> bool:
        """按位置改写一条准则（前端「流程」tab 的编辑入口）。

        位置下标而不是 id，是因为 `Procedure` 本身没有稳定标识 —— 它只由
        `rule` 唯一，而 `rule` 正是这里要改的字段，拿它当 key 会在「改 rule」
        这个动作上自相矛盾。列表接口的 id 也一直是 enumerate 出来的下标，
        两边保持一致。

        新 rule 与**其他**条目重复时返回 False（不改）—— 去重逻辑和 `add`
        一致，否则会出现两条一模一样的准则。

        新 rule 和 `add` 一样过 `_mask_rule`：准则会被 `build_context()` 拼进
        system prompt 反复外发，含凭证的文本必须落盘前就换成 `<secret:name>` 引用。
        别把这里当成「给用户输入做通用脱敏」—— `mask_text` 只替换已知 secret
        真值，手写的普通文本原样保留。

        :param rule: 新内容；空白串视为非法，返回 False
        :param context: None = 保持原值
        """
        if index < 0 or index >= len(self._procedures):
            return False
        if not rule or not rule.strip():
            return False
        rule = _mask_rule(rule)
        normalized = rule.lower().strip()
        for i, p in enumerate(self._procedures):
            if i != index and p.rule.lower().strip() == normalized:
                return False
        target = self._procedures[index]
        target.rule = rule
        if context is not None:
            target.context = context
        self._save()
        return True

    def build_context(self) -> str:
        if not self._procedures:
            return ""
        lines = ["Behavioral guidelines (learned from past corrections):"]
        for p in sorted(self._procedures, key=lambda x: -x.hit_count):
            lines.append(f"- {p.rule}")
        return "\n".join(lines)

    def count(self) -> int:
        return len(self._procedures)
