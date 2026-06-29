"""基于 embedding 的 skill 路由器（multi-prototype max-sim 快筛）。

零训练快筛：每个 skill 的 trigger 短语 + description 各编码成一个锚点向量，
query 编码后与所有锚点算 max cosine，最高分 skill 的分数 >= FLOOR 才命中，
否则返回 None —— 交给 LLM 兜底（agent 始终注入 available_skills，漏触发可自补）。

设计依据（331 条手工评测集，含 legal-assistant 80 条，BGE-small-zh INT8 ONNX，macro 口径）：
    关键词硬匹配          P=0.76 R=0.24  拒识 90.8%
    INT8 向量 FLOOR=0.50  P=0.87 R=0.74  拒识 54.0%   ← 工作点
    INT8 向量 FLOOR=0.55  P=0.90 R=0.57  拒识 71.3%
    INT8 向量 FLOOR=0.60  P=0.94 R=0.36  拒识 83.9%
    FP32  向量 FLOOR=0.50  P=0.88 R=0.63  拒识 64.4%   （INT8 召回更优，体积 1/4）
FLOOR 取 0.50 的依据：skill 在本架构里是「软 prompt 注入」——注入 ≠ 执行，工具调用
始终由 LLM 自主决定。others 误判的代价是 context 污染（可被强 LLM 在 medium/full 路径
兜底），而非不可逆操作；高风险 skill（legal-assistant）经 modes=[法律] 隔离，不进 normal
路由。故召回优先（R=0.74），把漏触发的兜底负担降到最低。fast 路径（fast_path skill）
纠错窗口小，若主力为弱兜底模型可考虑上调到 0.55。

依赖 onnxruntime + transformers + BGE ONNX 模型（pip install 'ethan-agent[router]'）。
默认分发 INT8 动态量化版（24MB，较 FP32 90MB 召回更高、体积 1/4）。模型 + tokenizer
首次使用时从 HF Hub（llm011/bge-small-zh-v1.5-onnx）自动下载到 ~/.ethan/models/bge-small-zh/，
之后离线可用；也可用 `ethan router pull` 预拉（Docker/离线）。缺依赖、下载失败或离线无缓存
→ encoder 不可用，route() 返回 None，调用方回退关键词匹配，不影响主流程。
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ethan.skills.loader import Skill

logger = logging.getLogger(__name__)

# BGE 中文：query 需加指令前缀，passage（锚点）不加
_QUERY_PREFIX = "为这个句子生成表示以用于检索相关文章："
_BASE_MODEL = "BAAI/bge-small-zh-v1.5"
_DEFAULT_FLOOR = 0.50  # INT8 工作点：召回优先，误判可被强 LLM 兜底

# 模型路径：环境变量优先，否则 ~/.ethan/models/bge-small-zh/
_MODEL_ENV = "ETHAN_BGE_ONNX"
# HF Hub 仓库：含 model.onnx + tokenizer 全套，首次自动下载到本地后离线可用
_HF_REPO = "llm011/bge-small-zh-v1.5-onnx"
_MODEL_FILENAME = "model.onnx"


def _default_model_dir() -> Path:
    from ethan.core.config import CONFIG_DIR
    return CONFIG_DIR / "models" / "bge-small-zh"


def _default_model_path() -> Path:
    return _default_model_dir() / _MODEL_FILENAME


def ensure_model(force: bool = False) -> Path | None:
    """确保本地有 BGE ONNX 模型 + tokenizer，返回模型目录；缺依赖/下载失败返回 None。

    顺序：环境变量指定的路径 > 本地已下载 > 从 HF Hub 自动下载。
    供 `_Encoder` 和 `ethan router pull` 共用。
    """
    env_path = os.environ.get(_MODEL_ENV)
    if env_path:
        p = Path(env_path)
        return p.parent if p.is_file() else (p if p.exists() else None)

    model_dir = _default_model_dir()
    if not force and (model_dir / _MODEL_FILENAME).exists():
        return model_dir

    try:
        from huggingface_hub import snapshot_download
    except Exception:
        logger.debug("[router] huggingface_hub 不可用，跳过模型下载")
        return None

    try:
        logger.info("[router] 正在下载语义路由模型 %s (~24MB，仅首次)...", _HF_REPO)
        snapshot_download(
            repo_id=_HF_REPO,
            local_dir=str(model_dir),
            allow_patterns=["*.onnx", "*.json", "*.txt", "tokenizer*", "vocab*"],
        )
    except Exception as e:
        logger.warning("[router] 模型下载失败（将回退关键词匹配）：%s", e)
        return None

    return model_dir if (model_dir / _MODEL_FILENAME).exists() else None


def model_present() -> bool:
    """本地是否已有 BGE ONNX 模型文件（纯检查，不下载、不加载 session）。

    供 `available` 轻量判定用 —— agent 创建时只问"能不能用"，不触发模型加载。
    """
    env_path = os.environ.get(_MODEL_ENV)
    if env_path:
        p = Path(env_path)
        target = p if p.is_file() else p / _MODEL_FILENAME
        return target.exists()
    return (_default_model_dir() / _MODEL_FILENAME).exists()


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

            model_dir = ensure_model()
            if model_dir is None:
                self._sess = False  # 标记尝试过
                return False
            model_path = str(model_dir / _MODEL_FILENAME)
            self._sess = ort.InferenceSession(model_path, providers=["CPUExecutionProvider"])
            # tokenizer 优先从本地模型目录加载（离线友好）；目录缺 tokenizer 文件时，
            # AutoTokenizer 会回退到仅特殊 token 的残缺 tokenizer（vocab_size≈5），所有词变
            # [UNK] → 所有 embedding 几乎相同 → 路由彻底失效。检测 vocab 过小则回退基座 repo。
            tok = None
            try:
                cand = AutoTokenizer.from_pretrained(str(model_dir))
                if len(cand) > 1000:  # 正常 BGE 词表 ~21k；残缺的只有 5
                    tok = cand
            except Exception:
                pass
            if tok is None:
                tok = AutoTokenizer.from_pretrained(_BASE_MODEL)
            self._tok = tok
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


# 进程级单例：模型 ~24MB（INT8），只加载一次
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
        """模型文件是否存在（不加载 session，零冷启动开销）。"""
        return model_present()

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
