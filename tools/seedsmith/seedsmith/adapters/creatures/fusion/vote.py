"""`fusion-recipe-propose`'s own per-member majority over a proposed PAIR (creature-seed module 17,
spec-fusion-recipe-generator.md §2) — reuses `anchor/vote.py`'s `resolve_set_vote` shape exactly,
NOT `resolve_vote`'s whole-value equality. Whole-pair equality is the wrong precedent for an open
pairing space drawn from dozens of candidates: this repo already measured the analogous failure
for whole-SET agreement over a ~98-option pool ("a 40-55% unresolved rate that five rounds of
prompt work could not move: the ceiling was in the aggregation, not the model" —
`resolve_set_vote`'s own docstring) before fixing it with per-member majority. This module reuses
that fix, not the one that already failed at smaller scale.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from ..anchor.vote import resolve_set_vote


@dataclass(frozen=True)
class FusionPairVoteResult:
    """Mirrors `SetVoteResult`'s own shape, narrowed to EXACTLY two resolved members — a fusion
    recipe takes exactly two inputs, so a resolved set of any other size is `unresolved` for this
    module's purposes even where `resolve_set_vote` itself would report `split` (one member
    unanimous, no second member ever reaching threshold) or a 3-member cyclic tie (A-B / B-C / C-A,
    each pair reaching the 2-of-3 threshold on a different member — a real case, not a hypothetical
    one, at three independent samples over an open pool)."""
    pair: "tuple[str, str] | None"   # sorted; None only when confidence == "unresolved"
    confidence: str                   # "high" | "split" | "unresolved"
    tally: "dict[str, int]"


def resolve_fusion_pair_vote(
    samples: "Sequence[tuple[str, str] | None]", *, sample_count: int = 3,
) -> FusionPairVoteResult:
    """Canonicalizes each sample's pair to a sorted tuple BEFORE tallying (spec §2 step 1 — a
    sample proposing (A, B) and another proposing (B, A) are the same vote, not a disagreement),
    then reuses `resolve_set_vote`'s per-member majority (spec §2 steps 2-3) over those
    canonicalized 2-member sets. A species enters the resolved pair at >= 2 of `sample_count`
    votes; anything other than EXACTLY two resolved members is `unresolved`, reported by name,
    never sample 0's raw pick — the same rule `resolve_set_vote` already enforces, narrowed to the
    fixed pair width a fusion recipe actually needs.
    """
    canonicalized: "list[tuple[str, ...] | None]" = []
    for s in samples:
        if s is None:
            canonicalized.append(None)
            continue
        if len(s) != 2:
            raise ValueError(f"each fusion proposal sample must be a pair of 2 species, got {s!r}")
        canonicalized.append(tuple(sorted(s)))

    set_result = resolve_set_vote(canonicalized, sample_count=sample_count)

    if len(set_result.values) != 2:
        return FusionPairVoteResult(pair=None, confidence="unresolved", tally=set_result.tally)

    pair = (set_result.values[0], set_result.values[1])  # already sorted by resolve_set_vote
    return FusionPairVoteResult(pair=pair, confidence=set_result.confidence, tally=set_result.tally)


def assign_input_a_b(
    pair: "tuple[str, str]", *, candidate_elements: "dict[str, str]", output_element_primary: str,
) -> "tuple[str, str]":
    """The exact assignment `CreatureRecipeCatalog.TryFindPair` already uses for every other recipe
    (spec §2 step 4) — no new rule invented for gap-fills. The candidate matching the output's own
    primary element becomes `inputA`; the other becomes `inputB`. A tie (both match, or neither
    matches) breaks on `SpeciesId` ordinal — `TryFindPair`'s own existing tie-break — the lower id
    wins `inputA`. A/B carries no gameplay asymmetry either way (`spec-creature-fusion.md` lock 5's
    guaranteed-trait pick is symmetric); this exists only so identity is stable across reruns.
    """
    def sort_key(species_id: str) -> "tuple[bool, str]":
        matches_output = candidate_elements[species_id] == output_element_primary
        return (not matches_output, species_id)  # a match (False) sorts before a non-match (True)

    ordered = sorted(pair, key=sort_key)
    return ordered[0], ordered[1]
