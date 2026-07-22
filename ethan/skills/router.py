"""基于 embedding 的 skill 路由器（INT8 BGE + LogisticRegression 头）。

query 用 BGE-small-zh INT8 ONNX 编码成 512 维向量，过一层训练好的
LogisticRegression 头（9 类：8 个 skill + others）得到分类概率，argmax 命中。
预测为 others、概率低于 FLOOR、或命中标签不在当前已加载 skills 中 → 返回 None，
交 LLM 兜底（agent 始终注入 available_skills，漏触发可自补）。

设计依据（Jason 独立手写评测集 router_train.jsonl，措辞风格与训练样本不同、规避近重复
泄漏，INT8、macro 口径）：
    旧·锚点 max-cosine        真实 macro F1 < 0.85
    INT8 + LR 头 FLOOR=0.00   macro F1=0.851 P=0.878 R=0.835   ← 工作点
开集拒识由 others 真实类承担（训练含 trap 样本），优于单一 cosine floor。FLOOR 默认从
LR 头元数据读（训练时 val 选定，当前 0.00），低置信预测可再上调拦截，但 others 类已兜住大头。

模型分发：
    INT8 ONNX model_quant.onnx（24MB）+ LR 头 lr_head.npz + tokenizer —— 首次从 GitHub
    （llm011/router-models）按 raw URL 下载到包内 router_models/；包目录不可写
    （只读 site-packages 安装）则回退 ~/.ethan/models/bge-small-zh/。也可用
    `ethan router pull` 预拉（Docker/离线）。包本身不携带任何模型文件。
缺依赖、下载失败或离线无缓存 → encoder 不可用，route() 返回 None，调用方回退关键词匹配，
不影响主流程。依赖 onnxruntime + tokenizers（pip install 'ethan-agent[embedding]'，
与 memory 共享同一套依赖）。
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ethan.skills.loader import Skill

logger = logging.getLogger(__name__)

# BGE 中文：query 需加指令前缀，passage 不加（分类只编码 query）
_QUERY_PREFIX = "为这个句子生成表示以用于检索相关文章："
_BASE_MODEL = "BAAI/bge-small-zh-v1.5"
_MAX_LENGTH = 144  # 必须与训练/评测一致（train_lr_router.py MAX_LENGTH）
# 长 query 头尾保留：用户粘贴长文档（整份 markdown）时，意图句（"把以上内容做成胶片"）
# 常在结尾，纯头部截断会把意图丢光。2026-07 实测：不做头尾保留时，"长 md+请求在后"
# 样本全靠"粘贴过 md 文档"的捷径蒙对，遇到"长 md+帮我总结/翻译"必串档。
_SPLICE_HEAD = 76  # 头部保留字符数
_SPLICE_TAIL = 40  # 尾部保留字符数（意图句一般 <20 字，留足余量）


def _splice_long(text: str) -> str:
    """超长 query 保留头尾、中间用省略号拼接。与 train_lr_router.py 的 splice 完全一致。"""
    if len(text) <= _SPLICE_HEAD + _SPLICE_TAIL + 3:
        return text
    return text[:_SPLICE_HEAD] + "\n…\n" + text[-_SPLICE_TAIL:]
_DEFAULT_FLOOR = 0.0  # 缺元数据时的兜底；实际从 lr_head.npz 读

# 模型路径：环境变量优先，否则包内 router_models/，再回退 ~/.ethan/models/bge-small-zh/
_MODEL_ENV = "ETHAN_BGE_ONNX"
# 运行时模型托管在 GitHub（按 raw URL 下载，无需 huggingface_hub）
_GH_RAW_BASE = "https://raw.githubusercontent.com/llm011/router-models/main"
_MODEL_FILENAME = "model_quant.onnx"  # INT8 量化版（24MB）
_LR_HEAD_FILENAME = "lr_head.npz"
# 运行时需下载的全部文件（ONNX + LR 头 + tokenizer 套件）
_REMOTE_FILES = [
    "model_quant.onnx",
    "lr_head.npz",
    "tokenizer.json",
    "tokenizer_config.json",
    "special_tokens_map.json",
    "vocab.txt",
    "config.json",
]


def _package_model_dir() -> Path:
    """包内模型目录：INT8 ONNX + LR 头 + tokenizer 优先下载到此。"""
    return Path(__file__).resolve().parent / "router_models"


def _fallback_model_dir() -> Path:
    """只读安装时的回退下载目录。"""
    from ethan.core.config import CONFIG_DIR
    return CONFIG_DIR / "models" / "bge-small-zh"


def _resolve_dir_with(filename: str) -> Path:
    """返回含 filename 的模型目录：env > 包内 > 回退；都没有则返回包内（首选下载目标）。"""
    env_path = os.environ.get(_MODEL_ENV)
    if env_path:
        p = Path(env_path)
        return p.parent if p.is_file() else p
    pkg = _package_model_dir()
    if (pkg / filename).exists():
        return pkg
    fb = _fallback_model_dir()
    if (fb / filename).exists():
        return fb
    return pkg


def lr_head_path() -> Path:
    """LR 头与 ONNX 同目录（运行时一起下载）。"""
    return _resolve_dir_with(_LR_HEAD_FILENAME) / _LR_HEAD_FILENAME


def _default_model_dir() -> Path:
    """返回 INT8 ONNX 所在/应在的目录（供 status 显示与 encoder 加载）。"""
    return _resolve_dir_with(_MODEL_FILENAME)


def _default_model_path() -> Path:
    return _default_model_dir() / _MODEL_FILENAME


def _writable_dir(d: Path) -> bool:
    """目录可创建/可写则 True（用于决定 ONNX 下载落点）。"""
    try:
        d.mkdir(parents=True, exist_ok=True)
        return os.access(d, os.W_OK)
    except Exception:
        return False


def ensure_model(force: bool = False) -> Path | None:
    """确保本地有 INT8 ONNX + tokenizer，返回模型目录；下载失败返回 None。

    顺序：环境变量指定 > 已下载（包内或回退）> 从 GitHub raw URL 下载（包内优先，
    不可写则回退）。供 `_Encoder` 和 `ethan router pull` 共用。ONNX + LR 头 + tokenizer 一起下载。
    """
    env_path = os.environ.get(_MODEL_ENV)
    if env_path:
        p = Path(env_path)
        return p.parent if p.is_file() else (p if p.exists() else None)

    if not force:
        for d in (_package_model_dir(), _fallback_model_dir()):
            if (d / _MODEL_FILENAME).exists():
                return d

    target = _package_model_dir()
    if not _writable_dir(target):
        target = _fallback_model_dir()
        if not _writable_dir(target):
            logger.warning("[router] 无可写模型目录，跳过下载")
            return None

    try:
        import urllib.request

        logger.info("[router] 正在下载语义路由模型 (~24MB，仅首次)...")
        for fn in _REMOTE_FILES:
            dst = target / fn
            if dst.exists() and not force:
                continue
            tmp = dst.with_suffix(dst.suffix + ".part")
            urllib.request.urlretrieve(f"{_GH_RAW_BASE}/{fn}", tmp)
            tmp.replace(dst)
    except Exception as e:
        logger.warning("[router] 模型下载失败（将回退关键词匹配）：%s", e)
        return None

    return target if (target / _MODEL_FILENAME).exists() else None


def model_present() -> bool:
    """本地是否已有 INT8 ONNX + LR 头（纯检查，不下载、不加载 session）。

    供 `available` 轻量判定用 —— agent 创建时只问"能不能用"，不触发模型加载。
    """
    if not lr_head_path().exists():
        return False
    env_path = os.environ.get(_MODEL_ENV)
    if env_path:
        p = Path(env_path)
        target = p if p.is_file() else p / _MODEL_FILENAME
        return target.exists()
    return any((d / _MODEL_FILENAME).exists()
               for d in (_package_model_dir(), _fallback_model_dir()))


class _Encoder:
    """BGE-small-zh INT8 ONNX 编码器（CLS pooling，L2 归一化）。延迟加载，失败即不可用。

    用轻量 tokenizers 库加载 tokenizer.json（与 memory embedding 共享依赖），
    不再依赖 transformers。
    """

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
            from tokenizers import Tokenizer

            model_dir = ensure_model()
            if model_dir is None:
                self._sess = False  # 标记尝试过
                return False
            model_path = str(model_dir / _MODEL_FILENAME)
            self._sess = ort.InferenceSession(model_path, providers=["CPUExecutionProvider"])
            # 直接用轻量 tokenizers 加载 tokenizer.json
            tok_path = model_dir / "tokenizer.json"
            if not tok_path.exists():
                self._sess = False
                return False
            self._tok = Tokenizer.from_file(str(tok_path))
            self._tok.enable_truncation(max_length=_MAX_LENGTH)
            self._tok.enable_padding(length=_MAX_LENGTH)
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
        texts = [_splice_long(t) for t in texts]
        # 轻量 tokenizers 批量编码
        encodings = self._tok.encode_batch(texts)
        input_ids = np.array([e.ids for e in encodings], dtype=np.int64)
        attention_mask = np.array([e.attention_mask for e in encodings], dtype=np.int64)
        feeds = {"input_ids": input_ids, "attention_mask": attention_mask}
        if "token_type_ids" in self._input_names:
            feeds["token_type_ids"] = np.zeros_like(input_ids)
        feeds = {k: v for k, v in feeds.items() if k in self._input_names}
        out = self._sess.run(None, feeds)[0]
        emb = out[:, 0, :]  # CLS token
        emb = emb / (np.linalg.norm(emb, axis=1, keepdims=True) + 1e-8)
        return emb


# 进程级单例：模型只加载一次
_ENCODER = _Encoder()


class _LRHead:
    """训练好的 LogisticRegression 头：softmax(emb·coefᵀ + intercept)。

    只依赖 numpy（无 sklearn 运行依赖）。从包内 lr_head.npz 加载，含 labels/floor/元数据。
    """

    def __init__(self) -> None:
        self._loaded = False
        self._fail = False
        self.coef = None        # [n_cls, dim]
        self.intercept = None    # [n_cls]
        self.labels: list[str] = []
        self.floor = _DEFAULT_FLOOR

    def load(self) -> bool:
        if self._loaded:
            return True
        if self._fail:
            return False
        try:
            import numpy as np
            p = lr_head_path()
            if not p.exists():
                self._fail = True
                return False
            d = np.load(p, allow_pickle=True)
            self.coef = d["coef"].astype(np.float32)
            self.intercept = d["intercept"].astype(np.float32)
            self.labels = [str(x) for x in d["labels"].tolist()]
            if "floor" in d.files:
                self.floor = float(d["floor"])
            self._loaded = True
            return True
        except Exception:
            self._fail = True
            return False

    def predict(self, emb):
        """emb: np.ndarray [dim] → (label, prob)。未加载时返回 None。"""
        if not self.load():
            return None
        import numpy as np
        logits = self.coef @ emb + self.intercept
        logits = logits - logits.max()
        exp = np.exp(logits)
        proba = exp / exp.sum()
        idx = int(proba.argmax())
        return self.labels[idx], float(proba[idx])


# 进程级单例：LR 头加载一次（与 ONNX 一起运行时下载）
_LR_HEAD = _LRHead()


class EmbeddingRouter:
    """INT8 BGE + LR 头路由：query → 9 类分类，命中已加载 skill 才返回。

    用法：
        router = EmbeddingRouter()
        router.build(registry.all())      # 加载 LR 头 + 记录可路由 skill 集
        name = router.route("这篇 pdf 讲了啥")   # → "paper-analysis" 或 None
    """

    def __init__(self, floor: float | None = None) -> None:
        self._floor_override = floor
        self._routable: set[str] = set()   # LR 标签 ∩ 已加载 skill 名
        self._built = False

    @property
    def floor(self) -> float:
        if self._floor_override is not None:
            return self._floor_override
        return _LR_HEAD.floor

    @property
    def available(self) -> bool:
        """模型文件 + LR 头是否就绪（不加载 session，零冷启动开销）。"""
        return model_present()

    def build(self, skills: list["Skill"]) -> bool:
        """加载 LR 头，记录可路由 skill 集（LR 标签 ∩ 已加载 skill 名，排除 others）。

        LR 头不可用时返回 False（调用方应回退关键词匹配）。
        不再编码锚点 —— LR 头与 skill 集合无关，仅用 skill 名做命中过滤。
        """
        self._routable = set()
        self._built = False
        if not _LR_HEAD.load():
            return False
        names = {s.name for s in skills}
        self._routable = {label for label in _LR_HEAD.labels if label != "others" and label in names}
        self._built = bool(self._routable)
        return self._built

    def route(self, query: str) -> str | None:
        """返回最佳 skill 名；预测 others / 低于 floor / 不在可路由集 → None（交 LLM 兜底）。"""
        scored = self.route_scored(query)
        return scored[0] if scored else None

    def route_scored(self, query: str) -> tuple[str, float] | None:
        """返回 (skill_name, prob)；预测 others、低于 floor、不在可路由集或不可用时返回 None。"""
        if not self._built:
            return None
        emb = _ENCODER.encode([_QUERY_PREFIX + query])
        if emb is None:
            return None
        result = _LR_HEAD.predict(emb[0])
        if result is None:
            return None
        label, prob = result
        if label == "others" or prob < self.floor or label not in self._routable:
            return None
        return label, prob
