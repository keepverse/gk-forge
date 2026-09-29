"""The declare/fulfil split (spec-planner.md §8, plan P5).

The problem this removes, in one sentence: a set's stage-5 can discover it needs a base type that
does not exist, which looks like a backward edge and breaks any hand-written order. That is why
"generate sets" and "generate base types" could never be sequenced by a human — the dependency is
only visible *after* the set is planned.

**Phase A — declare.** Every kind runs its deterministic stages and emits `NeedSpec`s. Nothing
creative runs; no file is written. A set says "I need a plant `core-guard` at band b"; a recipe says
"I need a `catalyst.forge` material".

**Phase B — fulfil.** The planner now holds the whole demand graph, so it can resolve against
existing content first and generate only the genuine shortfall — in dependency order by
construction, not by memory.

**Reuse is the default** (spec §8.3, owner decision superseding the audit's structural-cap
recommendation). Set overlap needs no cap precisely *because* Phase B sees every set at once:
concentration becomes a planner policy — spread demand across equally-good candidates — rather than
a rule bolted on afterwards that refuses at an arbitrary number and cannot weigh theme fit.

The measured baseline the policy has to beat, from the hand-written binder: of 154 base types used
as set members, **129 serve one set, 24 serve two, one serves three**.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Callable, Iterable, Mapping, Sequence

from .feasibility import Demand, FeasibilityResult, check_feasibility

__all__ = [
    "NeedSpec",
    "Candidate",
    "Fulfilment",
    "DemandGraph",
    "declare",
    "fulfil",
]


@dataclass(frozen=True)
class NeedSpec:
    """One declared need, from Phase A. Not a request to generate — a statement of requirement.

    `traits` is the match key: whatever the demanding kind cares about (role, frame, band, family).
    Left as an open mapping rather than a fixed schema because what makes a base type suitable is
    adapter knowledge, and freezing it here would put a second, staler copy of that in the planner.
    """

    demander: str                       # the entry declaring the need, e.g. "set.emberwake"
    demander_kind: str                  # "set"
    needs_kind: str                     # "base-type"
    traits: Mapping[str, str] = field(default_factory=dict)
    slot: str = ""                      # which member/ingredient slot, for a stable id

    @property
    def key(self) -> str:
        return f"{self.demander}#{self.slot}" if self.slot else self.demander

    def satisfied_by(self, candidate: "Candidate") -> bool:
        """Every declared trait must match. Absence of a trait means "don't care", not "must be
        absent" — an over-strict match silently generates duplicates of content that already fits.
        """
        if candidate.kind != self.needs_kind:
            return False
        return all(candidate.traits.get(k) == v for k, v in self.traits.items())


@dataclass(frozen=True)
class Candidate:
    """Something that already exists and could satisfy a need."""

    id: str
    kind: str
    traits: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class Fulfilment:
    """Phase B's answer: what was reused, what must be generated, and why.

    `shortfall` is the only thing that becomes a generation job. Everything else is already on disk,
    which is the whole point of declaring before fulfilling.
    """

    reused: Mapping[str, str]                      # need key -> existing candidate id
    shortfall: tuple[NeedSpec, ...]                # needs nothing existing can serve
    feasibility: FeasibilityResult | None = None
    concentration: Mapping[str, int] = field(default_factory=dict)   # candidate id -> reuse count

    @property
    def reuse_rate(self) -> float:
        total = len(self.reused) + len(self.shortfall)
        return len(self.reused) / total if total else 1.0

    @property
    def max_concentration(self) -> int:
        return max(self.concentration.values(), default=0)


@dataclass
class DemandGraph:
    """Every need declared in Phase A, indexed by the kind that must exist first.

    `needs_kind -> [NeedSpec]` is deliberately the primary index: it is the question Phase B asks,
    and it is also what makes the ordering fall out — a kind cannot be generated until every kind
    appearing as a `needs_kind` of its own demands has been.
    """

    needs: list[NeedSpec] = field(default_factory=list)

    def by_needed_kind(self) -> dict[str, list[NeedSpec]]:
        out: dict[str, list[NeedSpec]] = defaultdict(list)
        for need in self.needs:
            out[need.needs_kind].append(need)
        return dict(out)

    def kind_dependencies(self) -> dict[str, set[str]]:
        """`demander_kind -> {needs_kind}` — the same shape `ordering.derive_kind_order` consumes.

        This is what makes the recipe case structural: a recipe declaring a material need in Phase A
        *is* the edge that puts materials first. Nobody has to remember the order because nobody
        writes it down.
        """
        out: dict[str, set[str]] = defaultdict(set)
        for need in self.needs:
            out[need.demander_kind].add(need.needs_kind)
            out.setdefault(need.needs_kind, set())
        return dict(out)


def declare(
    entries: Iterable[object],
    stages: Mapping[str, Callable[[object], Sequence[NeedSpec]]],
) -> DemandGraph:
    """Phase A. Run each kind's deterministic stage over its entries and collect the needs.

    `stages` maps a kind to a pure function producing its needs. Pure is the contract: Phase A runs
    no model, writes no file, and must be safe to run repeatedly — which is what lets the whole
    graph be assembled before anything is decided.

    Entries whose kind has no stage contribute nothing. That is not an error: most kinds declare no
    cross-kind need at all, and requiring an empty stage for each of them would be ceremony that
    someone eventually skips.
    """
    graph = DemandGraph()
    for entry in entries:
        stage = stages.get(getattr(entry, "kind", ""))
        if stage is None:
            continue
        graph.needs.extend(stage(entry))
    return graph


def fulfil(
    graph: DemandGraph,
    existing: Sequence[Candidate],
    *,
    spread: bool = True,
) -> Fulfilment:
    """Phase B. Resolve every need against existing content first; only the shortfall is generated.

    **`spread` is the policy §8.3 describes, and it is why no cap is needed.** With full sight of
    every need at once, a candidate that has already served another need is chosen last among
    equally-good ones. A cap could only refuse at an arbitrary number; this weighs spread while
    still reusing, and it degrades gracefully — when the only candidate is one already used twice,
    it is used a third time rather than the plan failing.

    Determinism: needs are resolved in declaration order and candidates compared by
    `(times_used, id)`, so the same input always produces the same assignment. A plan that shuffles
    between runs cannot be diffed, which is how spec §7 judges this whole module.
    """
    used: dict[str, int] = defaultdict(int)
    reused: dict[str, str] = {}
    shortfall: list[NeedSpec] = []

    for need in graph.needs:
        candidates = [c for c in existing if need.satisfied_by(c)]
        if not candidates:
            shortfall.append(need)
            continue
        if spread:
            pick = min(candidates, key=lambda c: (used[c.id], c.id))
        else:
            pick = min(candidates, key=lambda c: c.id)
        reused[need.key] = pick.id
        used[pick.id] += 1

    # Feasibility over the needs that DID find candidates: totals fitting says nothing about a
    # subset, and this is exactly P1's job rather than a second implementation of it.
    feasibility = None
    matched = [n for n in graph.needs if n.key in reused]
    if matched:
        feasibility = check_feasibility(
            [
                Demand(
                    key=n.key,
                    allowed_slots=frozenset(c.id for c in existing if n.satisfied_by(c)),
                )
                for n in matched
            ],
            {c.id: len([n for n in matched if n.satisfied_by(c)]) or 1 for c in existing},
        )

    return Fulfilment(
        reused=reused,
        shortfall=tuple(shortfall),
        feasibility=feasibility,
        concentration=dict(used),
    )
