"""A deterministic lexical embedder for CI and tests only: EMBED_MODEL=hash-bow-768.

Why it exists: the e2e-eval CI job must index a corpus and measure recall@k in a few
minutes, with no network and no model download. This embedder hashes word unigrams and
bigrams into a fixed-size vector (the "hashing trick"), then L2-normalises it, so cosine
similarity measures word overlap. It is NOT a semantic model and is never used in prod.

The API has a byte-identical copy at api/app/hashembed.py. tests/test_hashembed_copies.py
fails CI if the two files ever differ, because two different algorithms under one model
name would be exactly the silent mismatch section 4.4 is about.
"""

from __future__ import annotations

import hashlib
import math
import re

HASH_PREFIX = "hash-bow-"
_WORD = re.compile(r"[a-z0-9]+(?:[.,][0-9]+)*")
_STOP = frozenset(
    "a an the of to in on for and or is are be by with at as it this that what which who "
    "how do does can i my me you your from if".split()
)


def is_hash_model(name: str) -> bool:
    return name.startswith(HASH_PREFIX)


def hash_dimension(name: str) -> int:
    return int(name[len(HASH_PREFIX):])


def tokens(text: str) -> list[str]:
    return [w for w in _WORD.findall(text.lower()) if w not in _STOP]


def hash_embed(text: str, dim: int) -> list[float]:
    words = tokens(text)
    features = words + [f"{a}_{b}" for a, b in zip(words, words[1:])]
    vec = [0.0] * dim
    for feat in features:
        digest = hashlib.md5(feat.encode()).digest()
        index = int.from_bytes(digest[:4], "little") % dim
        sign = 1.0 if digest[4] & 1 else -1.0
        vec[index] += sign
    norm = math.sqrt(sum(v * v for v in vec))
    if norm == 0.0:
        vec[0] = 1.0
        return vec
    return [v / norm for v in vec]
