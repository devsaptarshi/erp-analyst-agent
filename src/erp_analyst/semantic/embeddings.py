"""Embedding function boundary. No embedding-provider API key (Voyage,
OpenAI, etc.) was available while building this — see KNOWN_LIMITS.md —
so `real_sql_generator`'s sibling here is `hashing_trick_embedder`: a
genuine (if crude) embedding technique, not a stand-in that only LOOKS
like one. It hashes character trigrams into a fixed-size vector and
L2-normalizes it, which is the classic "hashing trick" / random-projection
approach to a bag-of-n-grams embedding (see Weinberger et al., "Feature
Hashing for Large Scale Multitask Learning"). Two strings sharing more
trigrams end up with higher cosine similarity — it's a real, testable
retrieval signal, just a much weaker one than a trained embedding model.
Swap `EMBEDDING_DIM` + the function passed to the store for a real
provider's client without changing anything else in this module.
"""
from __future__ import annotations

import hashlib
import math
from typing import Protocol

EMBEDDING_DIM = 256


class EmbedFn(Protocol):
    def __call__(self, text: str) -> list[float]: ...


def _trigrams(text: str) -> list[str]:
    normalized = f"  {text.lower().strip()}  "
    return [normalized[i : i + 3] for i in range(len(normalized) - 2)]


def hashing_trick_embedder(text: str, dim: int = EMBEDDING_DIM) -> list[float]:
    vec = [0.0] * dim
    for gram in _trigrams(text):
        digest = hashlib.sha256(gram.encode("utf-8")).digest()
        index = int.from_bytes(digest[:4], "big") % dim
        sign = 1.0 if digest[4] % 2 == 0 else -1.0
        vec[index] += sign
    norm = math.sqrt(sum(v * v for v in vec))
    if norm == 0:
        return vec
    return [v / norm for v in vec]
