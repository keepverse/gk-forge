"""`option-permutation`'s vote resolution (creature-seed module 6, spec-option-permutation.md §4-5).
Three samples in, one resolved value out — or `unresolved`, never the first value by default.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Sequence

#: Q25 — three-way voted, load-bearing fields. Adding or removing one is an "ask first" boundary
#: (moves the call budget) — pinned here as a frozenset so a change needs deliberate code, not a
#: silent list edit. `attackTempo` joined 2026-09-04 (creature-corpus-self-heal C1, owner-approved as
#: part of the full self-heal plan): the real 833-species audit found it collapsed to a single
#: value (entropy 0.00) — the one pipeline (`kit-shape`) that had never been wired into voting or
#: permutation at all, unlike every other classified field.
VOTED_FIELDS = frozenset({"elementPrimary", "aptitudePrimary", "rarity", "threatBand", "deployMode", "attackTempo"})


@dataclass(frozen=True)
class VoteResult:
    value: "str | None"        # None only when confidence == "unresolved"
    confidence: str            # "high" (3-0) | "split" (2-1) | "unresolved" (1-1-1, or too few answers)
    minority: "str | None"     # the minority value, recorded — only set when confidence == "split"


#: The empty string is a NON-ANSWER, not a value. The orchestrator reads each sample with
#: `draft.get(field_name) or ""`, so a model reply that omits the field — or returns it empty —
#: reaches this module as `""`.
BLANK_SAMPLE = ""


def resolve_vote(values: Sequence[str]) -> VoteResult:
    """Exactly three samples in. A 1-1-1 split is a genuine ambiguity signal, not a default —
    it never silently takes `values[0]` (spec §4's explicit warning: "the obvious way to build
    this wrong").

    **A blank sample is not a vote** (measured 2026-10-04 against the real corpus: 157 entries
    across three voted fields carried `""`). Three non-answers used to resolve to
    `VoteResult("", "high")` — a unanimous, HIGH-CONFIDENCE vote for the empty string — because
    `Counter` cannot tell "three people said nothing" from "three people agreed". The empty string
    was then written to the anchor as though it were a real judgement, and its provenance read
    `confidence: high` / `attempts: 1`, so nothing anywhere recorded that the model had not
    answered. No consumer can load the result: `SpeciesExpander` looks the value up in a closed
    vocabulary and refuses it, so the C# tool exits 1 on the first such entry and abandons the
    whole load.

    The rule: **blank samples are excluded from the tally and are never recorded as a value or as a
    minority**, and with fewer than two real answers left the field is `unresolved`. Never `"high"`
    on the strength of fewer than three answers, never `values[0]`, never `""`. This is the same
    discipline `resolve_set_vote` applies to a heal-exhausted `None` sample, for the same reason:
    a sample that did not answer must not be able to manufacture agreement.
    """
    if len(values) != 3:
        raise ValueError(f"resolve_vote needs exactly 3 samples, got {len(values)}")

    answers = [v for v in values if isinstance(v, str) and v.strip() != BLANK_SAMPLE]
    if len(answers) < 2:
        # Zero or one real answer out of three. A single answer is NOT a vote, and reporting it
        # would be the "never silently take values[0]" failure in a new costume.
        return VoteResult(value=None, confidence="unresolved", minority=None)

    counts = Counter(answers)
    top_value, top_count = counts.most_common()[0]

    if top_count == len(values):
        return VoteResult(value=top_value, confidence="high", minority=None)
    if top_count >= 2:
        # `next(...)` alone would raise StopIteration here: when blanks were excluded, the
        # remaining answers can all BE the top value (["fire", "fire", ""]), so there is no
        # minority to name. That is `split` with no recorded minority — the agreed answer, reached
        # on fewer than three answers, which is exactly what "split" means here.
        minority = next((v for v in answers if v != top_value), None)
        return VoteResult(value=top_value, confidence="split", minority=minority)
    # Every real answer distinct: the same genuine 1-1-1 ambiguity signal as before.
    return VoteResult(value=None, confidence="unresolved", minority=None)


@dataclass(frozen=True)
class SetVoteResult:
    """One resolved vote over a SET-valued field. Deliberately shaped so `.value` / `.minority_key`
    read like `VoteResult`'s own scalar fields — a caller that persists a row keeps its shape."""

    values: "tuple[str, ...]"      # resolved members, sorted; empty only when confidence == "unresolved"
    confidence: str                # "high" (every sample identical) | "split" | "unresolved"
    minority: "tuple[str, ...]"    # proposed but below threshold, sorted — recorded, never discarded
    tally: "dict[str, int]"        # member -> how many samples chose it (the diagnosis this lacked)

    @property
    def value(self) -> "str | None":
        """The canonical `|`-joined key, or `None` when unresolved — the exact shape
        `VoteResult.value` carries, so existing row writers need no reshape."""
        return "|".join(self.values) if self.values else None

    @property
    def minority_key(self) -> "str | None":
        return "|".join(self.minority) if self.minority else None


def resolve_set_vote(samples: "Sequence[Sequence[str] | None]", *,
                     sample_count: int = 3) -> SetVoteResult:
    """Per-MEMBER majority over a set-valued field — the aggregation `resolve_vote` cannot express.

    **Why this exists (measured, 2026-09-05).** `resolve_vote` is scalar: it compares whole values
    with `Counter` equality. A set-valued field reaching it has to be flattened to one string first
    (the action pipelines' own `canonical_family_key`), so `{a,b}` / `{a,c}` / `{a,d}` scores as a
    1-1-1 split — *unresolved* — even though `a` was chosen unanimously by all three samples. Every
    member-level agreement is discarded by the flattening. Over a ~98-option pool with multi-member
    picks, exact whole-set agreement across three independent samples is combinatorially unlikely,
    which is why the real action-corpus batches measured a 40-55% unresolved rate that five rounds
    of prompt work could not move: the ceiling was in the aggregation, not the model.

    **The rule.** A member joins the resolved set when at least a majority of `sample_count`
    samples chose it (2 of 3). The denominator is always `sample_count`, never "samples that
    answered" — a heal-exhausted sample (`None`) still counts against the threshold, the identical
    discipline the callers' own unresolved-sample sentinel already enforced, and for the same
    reason: dropping it would let two samples out-vote a total of two instead of three.

    **It can never fall back to one sample.** A member needs two independent samples to enter the
    set, which is strictly stronger per-member evidence than whole-set equality ever gave. An empty
    result is `unresolved` — the genuine ambiguity signal, never sample 0's raw pick.
    """
    if len(samples) != sample_count:
        raise ValueError(f"resolve_set_vote needs exactly {sample_count} samples, got {len(samples)}")

    threshold = sample_count // 2 + 1
    tally: "Counter[str]" = Counter()
    usable = 0
    for sample in samples:
        if sample is None:
            continue
        usable += 1
        tally.update(set(sample))

    resolved = tuple(sorted(m for m, c in tally.items() if c >= threshold))
    minority = tuple(sorted(m for m, c in tally.items() if c < threshold))

    if not resolved:
        return SetVoteResult(values=(), confidence="unresolved", minority=minority, tally=dict(tally))

    # "high" keeps its existing meaning exactly: every sample answered, and answered identically.
    unanimous = usable == sample_count and not minority and all(
        c == sample_count for c in tally.values())
    return SetVoteResult(values=resolved, confidence="high" if unanimous else "split",
                         minority=minority, tally=dict(tally))


@dataclass(frozen=True)
class VoteRecord:
    """One resolved vote, kept for disagreement reporting (spec §5)."""
    species_id: str
    side: str
    field: str
    result: VoteResult


def disagreement_rate(records: Sequence[VoteRecord]) -> dict:
    """Per field, per side: the share of votes that were NOT 3-0 (i.e. `split` or `unresolved`).
    Reported separately per side because a description can be clear for zombies and vague for
    plants (spec §5) — a single pooled rate would hide that."""
    totals: "dict[tuple[str, str], int]" = {}
    disagreed: "dict[tuple[str, str], int]" = {}
    for r in records:
        key = (r.field, r.side)
        totals[key] = totals.get(key, 0) + 1
        if r.result.confidence != "high":
            disagreed[key] = disagreed.get(key, 0) + 1

    report: "dict[str, dict]" = {}
    for (field, side), total in totals.items():
        report.setdefault(field, {})[side] = disagreed.get((field, side), 0) / total
    return report
