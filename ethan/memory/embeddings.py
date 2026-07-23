"""Embedding utilities for semantic search.

优先用 BGE-small-zh INT8 ONNX（复用 router 的模型文件，轻量 tokenizers 加载），
零新增依赖——装 `ethan-agent[embedding]` 即可（onnxruntime + tokenizers + numpy）。
不可用时回退 char n-gram hash embedding（同 512 维，保证 schema 不变）。
"""
import asyncio
import hashlib
import logging
import math
import os
import re
from pathlib import Path

logger = logging.getLogger(__name__)

EMBEDDING_DIM = 512  # BGE-small-zh-v1.5；fallback hash 用同维度保证 schema 一致

# ── Fallback: char n-gram feature hashing ──────────────────────────────────

def _ngrams(text: str, n: int):
    for i in range(len(text) - n + 1):
        yield text[i : i + n]


def _hash_embed(text: str) -> list[float]:
    """Dense n-gram feature-hash embedding, L2-normalised to unit length."""
    cleaned = re.sub(r"\s+", " ", text.lower().strip())
    if not cleaned:
        return [0.0] * EMBEDDING_DIM

    vec = [0.0] * EMBEDDING_DIM

    for n in (2, 3, 4):
        for gram in _ngrams(cleaned, n):
            digest = hashlib.sha256(gram.encode()).digest()
            idx = int.from_bytes(digest[:4], "little") % EMBEDDING_DIM
            sign = 1.0 if digest[4] & 1 else -1.0
            vec[idx] += sign

    norm = math.sqrt(sum(x * x for x in vec))
    if norm > 0:
        vec = [x / norm for x in vec]

    return vec


# ── BGE-small-zh INT8 ONNX encoder ─────────────────────────────────────────

_encoder = None          # _BGEEncoder 实例 / None（未检查）/ False（已尝试且失败）
_encoder_checked = False


class _BGEEncoder:
    """BGE-small-zh INT8 ONNX 编码器，用轻量 tokenizers 加载（不依赖 transformers）。

    复用 router 的模型文件（model_quant.onnx + tokenizer.json），但独立加载。
    CLS pooling + L2 归一化，输出 512 维。
    """

    def __init__(self) -> None:
        self._ready = False
        self._sess = None
        self._tok = None
        self._input_names: set[str] = set()

    def _resolve_model_dir(self) -> Path | None:
        """定位 BGE ONNX 模型目录：env > 包内 router_models/ > ~/.ethan/models/bge-small-zh/。

        如果都不存在，尝试从 GitHub 下载（复用 router 的下载逻辑）。
        """
        # 1. 环境变量
        env_path = os.environ.get("ETHAN_BGE_ONNX")
        if env_path:
            p = Path(env_path)
            target = p.parent if p.is_file() else p
            if (target / "model_quant.onnx").exists():
                return target

        # 2. 包内 router_models/
        pkg = Path(__file__).resolve().parent.parent / "skills" / "router_models"
        if (pkg / "model_quant.onnx").exists():
            return pkg

        # 3. ~/.ethan/models/bge-small-zh/
        try:
            from ethan.core.config import CONFIG_DIR
            fb = CONFIG_DIR / "models" / "bge-small-zh"
            if (fb / "model_quant.onnx").exists():
                return fb
        except Exception:
            pass

        # 4. 尝试用 router 的下载逻辑
        try:
            from ethan.skills.router import ensure_model
            return ensure_model()
        except Exception:
            return None

    def _ensure(self) -> bool:
        if self._ready:
            return True
        if self._sess is False:  # 已尝试过且失败
            return False
        try:
            import onnxruntime as ort
            from tokenizers import Tokenizer

            model_dir = self._resolve_model_dir()
            if model_dir is None:
                self._sess = False
                return False

            tok_path = model_dir / "tokenizer.json"
            if not tok_path.exists():
                self._sess = False
                return False

            self._sess = ort.InferenceSession(
                str(model_dir / "model_quant.onnx"),
                providers=["CPUExecutionProvider"],
            )
            self._tok = Tokenizer.from_file(str(tok_path))
            self._tok.enable_truncation(max_length=512)
            self._input_names = {i.name for i in self._sess.get_inputs()}
            self._ready = True
            return True
        except Exception:
            self._sess = False
            return False

    def encode(self, text: str) -> list[float] | None:
        """单条文本 → 512 维 list[float]（已 L2 归一化）。不可用返回 None。"""
        if not self._ensure():
            return None
        import numpy as np

        # tokenizers 库的 encode 返回 Encoding 对象
        encoding = self._tok.encode(text)
        # 构造 ONNX 输入（BGE 用 input_ids + attention_mask + token_type_ids）
        input_ids = np.array([encoding.ids], dtype=np.int64)
        attention_mask = np.array([encoding.attention_mask], dtype=np.int64)
        feeds = {
            "input_ids": input_ids,
            "attention_mask": attention_mask,
        }
        # token_type_ids 可能不是必需的（取决于 ONNX 导出配置）
        if "token_type_ids" in self._input_names:
            feeds["token_type_ids"] = np.zeros_like(input_ids)

        feeds = {k: v for k, v in feeds.items() if k in self._input_names}
        try:
            out = self._sess.run(None, feeds)[0]
            emb = out[0, 0, :]  # CLS token
            emb = emb / (np.linalg.norm(emb) + 1e-8)
            return emb.tolist()
        except Exception:
            logger.warning("BGE ONNX 推理失败，回退 hash embedding", exc_info=True)
            return None


def _try_get_encoder():
    """延迟初始化 BGE encoder，失败返回 None（调用方回退 hash）。"""
    global _encoder, _encoder_checked
    if _encoder_checked:
        return _encoder if _encoder is not None else None
    _encoder_checked = True
    enc = _BGEEncoder()
    if enc._ensure():
        _encoder = enc
    else:
        _encoder = None
    return _encoder


# ── 轻量 token 计数（只加载 tokenizer.json，不跑 ONNX、不触发下载）────────────

_count_tok = None            # tokenizers.Tokenizer / None（未查）/ False（已查且不可用）


def _heuristic_token_count(text: str) -> int:
    """零依赖 token 估算：CJK 每字≈1 token，其余按空格分词计数。

    仅在 BGE tokenizer.json 不存在时兜底。粗略但跨语言稳定，够做寒闲聊门槛。
    """
    cjk = 0
    buf: list[str] = []
    for ch in text:
        if "一" <= ch <= "鿿" or "぀" <= ch <= "ヿ" or "가" <= ch <= "힣":
            cjk += 1
            buf.append(" ")
        else:
            buf.append(ch)
    words = len([w for w in "".join(buf).split() if any(c.isalnum() for c in w)])
    return cjk + words


def _resolve_tokenizer_path() -> Path | None:
    """定位 BGE tokenizer.json：env > 包内 router_models/ > ~/.ethan/models/。

    只查本地已存在的文件，绝不触发下载——token 计数不值得为此联网拉模型。
    """
    env_path = os.environ.get("ETHAN_BGE_ONNX")
    if env_path:
        p = Path(env_path)
        target = p.parent if p.is_file() else p
        tj = target / "tokenizer.json"
        if tj.exists():
            return tj
    pkg = Path(__file__).resolve().parent.parent / "skills" / "router_models" / "tokenizer.json"
    if pkg.exists():
        return pkg
    try:
        from ethan.core.config import CONFIG_DIR
        fb = CONFIG_DIR / "models" / "bge-small-zh" / "tokenizer.json"
        if fb.exists():
            return fb
    except Exception:
        pass
    return None


def count_tokens(text: str) -> int:
    """估算文本 token 数。优先用 BGE tokenizer.json（离线、不跑推理、不下载），
    加载失败退化到启发式。用于短会话/兜底扫描的寒暄过滤门槛。
    """
    global _count_tok
    if not text:
        return 0
    if _count_tok is None:
        tj = _resolve_tokenizer_path()
        if tj is None:
            _count_tok = False
        else:
            try:
                from tokenizers import Tokenizer
                _count_tok = Tokenizer.from_file(str(tj))
            except Exception:
                _count_tok = False
    if _count_tok is False:
        return _heuristic_token_count(text)
    try:
        ids = _count_tok.encode(text).ids
        return max(0, len(ids) - 2)  # 减 [CLS]/[SEP] 两个特殊 token
    except Exception:
        return _heuristic_token_count(text)


# ── Public API ──────────────────────────────────────────────────────────────

async def embed(text: str) -> list[float]:
    """Return a 512-dim embedding for *text*.

    Uses BGE-small-zh INT8 ONNX when available, otherwise falls back to
    n-gram feature hashing.
    """
    encoder = _try_get_encoder()
    if encoder is not None:
        loop = asyncio.get_event_loop()
        # ONNX 推理是同步阻塞，放线程池避免阻塞事件循环
        result = await loop.run_in_executor(None, encoder.encode, text)
        if result is not None:
            return result
    return _hash_embed(text)


def embed_sync(text: str) -> list[float]:
    """Synchronous variant — use only when no event loop is running."""
    encoder = _try_get_encoder()
    if encoder is not None:
        result = encoder.encode(text)
        if result is not None:
            return result
    return _hash_embed(text)
