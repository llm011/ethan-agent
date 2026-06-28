"""基于 embedding 的 skill 路由器（multi-prototype max-sim 快筛）。

零训练快筛：每个 skill 的 trigger 短语 + description 各编码成一个锚点向量，
query 编码后与所有锚点算 max cosine，最高分 skill 的分数 >= FLOOR 才命中，
否则返回 None —— 交给 LLM 兜底（agent 始终注入 available_skills，漏触发可自补）。

设计依据（252 条手工评测集，BGE-small-zh ONNX，macro 口径）：
    关键词硬匹配       P=0.76 R=0.24  拒识 90.8%
    向量 FLOOR=0.50    P=0.89 R=0.64  拒识 67.8%
    向量 FLOOR=0.55    P=0.94 R=0.47  拒识 80.5%
误触发（污染 context，贵）比漏触发（LLM 能自补，便宜）代价高，故 FLOOR 取高位
0.55，宁可漏不可错。heavy 路径（Map-Reduce）执行始终经 LLM 闸门，注入 skill ≠ 执行。

依赖 onnxruntime + transformers + BGE ONNX 模型（pip install 'ethan-agent[router]'）。
缺任一 → encoder 不可用，route() 返回 None，调用方回退关键词匹配，不影响主流程。
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ethan.skills.loader import Skill

# BGE 中文：query 需加指令前缀，passage（锚点）不加
_QUERY_PREFIX = "为这个句子生成表示以用于检索相关文章："
_BASE_MODEL = "BAAI/bge-small-zh-v1.5"
_DEFAULT_FLOOR = 0.55

# 模型路径：环境变量优先，否则 ~/.ethan/models/bge-small-zh/model.onnx
_MODEL_ENV = "ETHAN_BGE_ONNX"


def _default_model_path() -> Path:
    from ethan.core.config import CONFIG_DIR
    return CONFIG_DIR / "models" / "bge-small-zh" / "model.onnx"


class _Encoder:
    """BGE-small-zh ONNX 编码器（CLS pooling，L2 归一化）。延迟加载，失败即不可用。"""

    def __init__(self) -> None:
        self._ready = False
        self._sess = None
        self._tok = None
        self._input_names: set[str] = set()

    def _ensure(self) -> bool:
        if self._ready:
            return True
        if self._sess is not None:  # 已尝试过且失败
            return False
        try:
            import numpy as np  # noqa: F401
            import onnxruntime as ort
            from transformers import AutoTokenizer

            model_path = os.environ.get(_MODEL_ENV) or str(_default_model_path())
            if not Path(model_path).exists():
                self._sess = False  # 标记尝试过
                return False
            self._sess = ort.InferenceSession(model_path, providers=["CPUExecutionProvider"])
            self._tok = AutoTokenizer.from_pretrained(_BASE_MODEL)
            self._input_names = {i.name for i in self._sess.get_inputs()}
            self._ready = True
            return True
        except Exception:
            self._sess = False
            return False

    def encode(self, texts):
        """texts: str | list[str] → np.ndarray [n, dim]（已归一化）。不可用时返回 None。"""
        if not self._ensure():
            return None
        import numpy as np

        if isinstance(texts, str):
            texts = [texts]
        batch = self._tok(texts, padding=True, truncation=True, max_length=512, return_tensors="np")
        feeds = {k: v for k, v in batch.items() if k in self._input_names}
        out = self._sess.run(None, feeds)[0]
        emb = out[:, 0, :]  # CLS token
        emb = emb / (np.linalg.norm(emb, axis=1, keepdims=True) + 1e-8)
        return emb


# 进程级单例：模型 ~94MB，只加载一次
_ENCODER = _Encoder()


class EmbeddingRouter:
    """multi-prototype max-sim 路由：锚点 = 各 skill 的 trigger 短语 + description。

    用法：
        router = EmbeddingRouter(floor=0.55)
        router.build(registry.all())      # 构建锚点索引（编码一次）
        name = router.route("这篇 pdf 讲了啥")   # → "paper-analysis" 或 None
    """

    def __init__(self, floor: float = _DEFAULT_FLOOR) -> None:
        self.floor = floor
        self._skill_anchors: dict[str, "object"] = {}  # name → np.ndarray [k, dim]
        self._built = False

    @property
    def available(self) -> bool:
        """encoder 是否就绪（依赖 + 模型都在）。"""
        return _ENCODER._ensure()

    def build(self, skills: list["Skill"]) -> bool:
        """为每个 skill 编码锚点（trigger 短语各一个 + description 一个）。

        encoder 不可用时返回 False（调用方应回退关键词匹配）。
        """
        self._skill_anchors = {}
        self._built = False
        for skill in skills:
            anchors = list(skill.trigger)
            if skill.description:
                anchors.append(skill.description)
            if not anchors:
                anchors = [skill.name]
            emb = _ENCODER.encode(anchors)
            if emb is None:
                return False  # encoder 不可用
            self._skill_anchors[skill.name] = emb
        self._built = bool(self._skill_anchors)
        return self._built

    def route(self, query: str) -> str | None:
        """返回最佳 skill 名；最高 max-sim < floor 则返回 None（交 LLM 兜底）。"""
        scored = self.route_scored(query)
        return scored[0] if scored else None

    def route_scored(self, query: str) -> tuple[str, float] | None:
        """返回 (skill_name, score)；低于 floor 或不可用时返回 None。"""
        if not self._built:
            return None
        import numpy as np

        q = _ENCODER.encode([_QUERY_PREFIX + query])
        if q is None:
            return None
        q = q[0]
        best_name, best_score = None, -1.0
        for name, anchors in self._skill_anchors.items():
            score = float(np.max(anchors @ q))
            if score > best_score:
                best_name, best_score = name, score
        if best_name is None or best_score < self.floor:
            return None
        return best_name, best_score
