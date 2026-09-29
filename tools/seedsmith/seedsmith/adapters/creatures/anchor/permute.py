"""`option-permutation` (creature-seed module 6, spec-option-permutation.md) — deterministic option
shuffling that neutralises label bias and position bias in LLM enum selection (ideal §4.7: up to a
75-point accuracy swing from reordering alone).

# sampleIndex is IN the seed. Three votes over three identical orders is one sample
# with extra steps - the obvious way to build this wrong. See spec section 3.
def order_for(species_id: str, field: str, sample_index: int) -> list[str]:
"""
from __future__ import annotations

import hashlib
import random
from typing import Sequence


def _seed_int(species_id: str, field: str, sample_index: int) -> int:
    """`blake2b(speciesId|field|sampleIndex, digest_size=8)` per spec §3, exactly — the byte
    concatenation is load-bearing: a rerun over an unchanged species must reproduce the identical
    permutation, or the disagreement rate (§5) measures prompt drift instead of model behaviour.
    """
    payload = species_id.encode("utf-8") + b"|" + field.encode("utf-8") + b"|" + str(sample_index).encode("utf-8")
    digest = hashlib.blake2b(payload, digest_size=8).digest()
    return int.from_bytes(digest, "big")


def order_for(species_id: str, field: str, sample_index: int, options: Sequence[str]) -> "list[str]":
    """A deterministic shuffle of `options`, seeded from `(species_id, field, sample_index)`.
    Never from a clock or a global counter — `random.Random` is seeded per call, so this function
    has no hidden state between calls."""
    rng = random.Random(_seed_int(species_id, field, sample_index))
    shuffled = list(options)
    rng.shuffle(shuffled)
    return shuffled
