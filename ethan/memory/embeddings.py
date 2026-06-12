"""Embedding utilities for semantic search.

Tries sentence-transformers (384-dim) if available; falls back to a
character n-gram hash embedding that produces the same 384-dim vectors
so the sqlite-vec schema never needs to change.
"""
import asyncio
import hashlib
import math
import re
from typing import Callable

EMBEDDING_DIM = 384  # matches all-MiniLM-L6-v2; fallback uses same dim

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
            # Two independent hashes for sign and bucket to reduce collisions
            digest = hashlib.sha256(gram.encode()).digest()
            idx = int.from_bytes(digest[:4], "little") % EMBEDDING_DIM
            sign = 1.0 if digest[4] & 1 else -1.0
            vec[idx] += sign

    # L2 normalise
    norm = math.sqrt(sum(x * x for x in vec))
    if norm > 0:
        vec = [x / norm for x in vec]

    return vec


# ── Optional sentence-transformers encoder ──────────────────────────────────

_encoder = None          # SentenceTransformer instance or False
_encoder_checked = False


def _try_get_encoder():
    global _encoder, _encoder_checked
    if _encoder_checked:
        return _encoder
    _encoder_checked = True
    try:
        from sentence_transformers import SentenceTransformer  # type: ignore

        _encoder = SentenceTransformer("all-MiniLM-L6-v2")
    except Exception:
        _encoder = None
    return _encoder


# ── Public API ──────────────────────────────────────────────────────────────

async def embed(text: str) -> list[float]:
    """Return a 384-dim embedding for *text*.

    Uses sentence-transformers when available, otherwise falls back to
    n-gram feature hashing.
    """
    encoder = _try_get_encoder()
    if encoder is not None:
        loop = asyncio.get_event_loop()
        result: list[float] = await loop.run_in_executor(
            None, lambda: encoder.encode(text).tolist()
        )
        return result
    return _hash_embed(text)


def embed_sync(text: str) -> list[float]:
    """Synchronous variant — use only when no event loop is running."""
    encoder = _try_get_encoder()
    if encoder is not None:
        return encoder.encode(text).tolist()
    return _hash_embed(text)
