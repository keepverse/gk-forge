"""seedsmith.adapters.actions.dedup_select.similarity — tier 3's shipped heuristic
(spec-dedup-select.md §1, "⛔ DECIDED 2026-09-03"): an in-repo token-overlap Jaccard similarity,
never an embedding index or a model call. This is the ONE default implementation of the
`similarity(a, b) -> int` seam `derive.run_tier3` accepts; a real embedding index, if ever
configured, would be a second implementation of the same seam, swapped in as a constructor
argument -- nothing in `derive.py` would need to change.

**Tokenisation, per spec §1 verbatim**: lowercase, split Latin (ASCII alphanumeric) runs on
non-alphanumerics, split CJK (or any other non-ASCII alphanumeric script) PER CHARACTER. The corpus
is bilingual and motifs are CJK (e.g. `铁头功`) -- a whitespace split would make a whole CJK phrase
one token and every pair of CJK phrases distance 1 apart regardless of actual overlap.

**Similarity, per spec §1 verbatim**: `similarityMilli = 1000 * |A ∩ B| / |A ∪ B|` -- Jaccard over
the token SET (not bag/multiset: a repeated token contributes no extra weight, matching the plain
set-membership reading of "token bag" the formula itself implies), one integer division, per-mille,
no float anywhere (docs/architecture/numeric-types.md's numeric rule).

**Provenance**: with no embedding model configured, spec §3 step 5 / acceptance #7 require the
similarity FUNCTION's own id and version instead of a model id -- `SIMILARITY_FUNCTION_ID`/
`_VERSION` below are that constant.
"""
from __future__ import annotations

__all__ = [
    "SIMILARITY_FUNCTION_ID", "SIMILARITY_FUNCTION_VERSION",
    "tokenize", "token_set", "jaccard_milli",
]

# A constant, never re-derived at runtime -- the same discipline `pipeline/provenance.py`'s
# `Provenance.model` field expects for whatever produced a row, applied to a pure function instead
# of a model.
SIMILARITY_FUNCTION_ID = "token-overlap-jaccard-milli"
SIMILARITY_FUNCTION_VERSION = 1

_MILLI_SCALE = 1000


def tokenize(text: str) -> "tuple[str, ...]":
    """Lowercase; group consecutive ASCII alphanumerics into one token each (a "Latin run"); treat
    every other alphanumeric character (CJK and any other non-ASCII script) as its own
    single-character token; every non-alphanumeric character is a separator, never a token."""
    text = text.lower()
    tokens: "list[str]" = []
    latin_run: "list[str]" = []
    for ch in text:
        if ch.isascii() and ch.isalnum():
            latin_run.append(ch)
            continue
        if latin_run:
            tokens.append("".join(latin_run))
            latin_run = []
        if ch.isalnum():                  # non-ASCII alphanumeric: CJK or similar, one token each
            tokens.append(ch)
        # else: whitespace/punctuation -- a separator only, never a token itself
    if latin_run:
        tokens.append("".join(latin_run))
    return tuple(tokens)


def token_set(name: str, rationale: str) -> "frozenset[str]":
    """The token bag spec §1 names, over `name` + `rationale` combined -- a space joins the two so
    the last character of `name` can never accidentally fuse with the first character of
    `rationale` into one Latin-run token."""
    return frozenset(tokenize(f"{name} {rationale}"))


def jaccard_milli(a: "frozenset[str]", b: "frozenset[str]") -> int:
    """`1000 * |A intersect B| / |A union B|`, one division, integer per-mille. Two empty token
    sets share no vocabulary to overlap on -- defined as 0, not a division by zero, and not treated
    as "identical" (an empty `name`+`rationale` pair is a data-quality problem elsewhere, never a
    reason to flag two rows as near-duplicate prose)."""
    union = a | b
    if not union:
        return 0
    inter = a & b
    return (_MILLI_SCALE * len(inter)) // len(union)
