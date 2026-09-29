"""seedsmith.adapters.base — the interface a feature implements to be understood by the core
(spec-foundation §2, field definitions per §7.2).

`LegalityFn` returning `True` unconditionally is a trap: an adapter that forgets to encode real
illegal combinations turns every genuinely-illegal pair into a permanent false Coverage finding
(spec-analytics §2.2). It is a required method, not an optional one with a safe-looking default,
and `adapters._stub` exercises a real `False` case so the trap cannot go unnoticed.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Protocol, runtime_checkable


class Unit(Enum):
    GAME_UNITS = "game_units"
    PER_MILLE = "per_mille"
    MILLISECONDS = "milliseconds"


@dataclass(frozen=True)
class KindSpec:
    kind: str                          # "base-type"
    directory: str                     # "base-types"
    namespace: str                     # allocation key, e.g. "base-type"
    required: frozenset[str] = frozenset()
    optional: frozenset[str] = frozenset()
    id_pattern: "re.Pattern[str] | None" = None
    runtime_id_fields: frozenset[str] = frozenset()   # fields holding a MINTED id

    # Fields on THIS kind that hold a cross-kind reference (P2). Ordering is derived from these
    # rather than from a hand-written stage label, because a label is a fact stated in two places
    # and the copy nobody edits is the one that goes stale -- which is precisely the 274-error
    # incident: a generation stage kept its old label after the graph beneath it changed.
    reference_fields: frozenset[str] = frozenset()

    # How a SHARED motif is expressed for this kind (spec-adapter-creatures.md §2.7, audit A1):
    # the same word means "a material" to an item theme, "a doctrine" to a commander effect,
    # "a tempo" to an action. Without this, five generators handed the same motifs produce a
    # thesaurus, not coherence -- and every check still passes, because nothing else can see it.
    #
    # DELIBERATE core change, additive with a default so `items` and `_stub` are untouched --
    # recorded per spec-adapter-creatures.md's own instruction ("if the core needs an edit, that is
    # the finding -- record it rather than patch around it"). This is why `spec-adapter-creatures.md`
    # §1/§4's "not one line of core code changed" / "no file outside adapters/creatures/" claims are
    # corrected to "true for D1's OWN kind additions, false for the feature as a whole" -- see
    # seedsmith-plan.md Part 4 §D-F1 for the full account of the three options weighed and why
    # this one (over a creatures-local dict, or abusing `registries()`) was chosen.
    motif_expression: "str | None" = None

    # Free-text field(s) on this kind that should ALSO run through SemanticDedup's near-duplicate
    # pipeline (spec-analytics.md §6.2), beyond the `name` field it always checks. `name` on most
    # kinds is short (a few words); `dedup_fields` names a kind's own longer prose field, when it
    # has one, where the same convergence risk applies at sentence scale -- confirmed for real on
    # the live corpus 2026-09-06: `commander-effect`'s 84-entry `doctrine` field already contains
    # two near-duplicate pairs (Jaccard 0.56, 0.41) with zero mechanism to notice as the roster
    # grows toward ~900. Additive, defaulted empty, so every kind without a prose field is
    # untouched -- same shape as `motif_expression` above.
    dedup_fields: frozenset[str] = frozenset()


@dataclass(frozen=True)
class Dimension:
    id: str                            # "role"
    values: tuple[str, ...]
    field: str                         # entry field carrying it
    applies_to: frozenset[str]         # kinds it is meaningful for


@dataclass(frozen=True)
class Channel:
    id: str                            # "maxHp"
    unit: Unit
    reference_base: Callable[[object], int]
    group: str                         # primary | flatDerived | sigmoidDerived | statusMagnitude
    ops: frozenset[str] = frozenset()  # Flat | Increased | More


# (dimA_id, valueA, dimB_id, valueB) -> is this pair possible at all
LegalityFn = Callable[[str, str, str, str], bool]


@dataclass(frozen=True)
class RegistrySet:
    vocabularies: "dict[str, frozenset[str]]" = field(default_factory=dict)
    versions: "dict[str, int]" = field(default_factory=dict)

    def is_legal(self, vocabulary: str, value: str) -> bool:
        return value in self.vocabularies.get(vocabulary, frozenset())


@runtime_checkable
class SeedAdapter(Protocol):
    def kinds(self) -> list[KindSpec]: ...
    def dimensions(self) -> list[Dimension]: ...
    def legal_combinations(self) -> LegalityFn: ...
    def registries(self) -> RegistrySet: ...
    def channels(self) -> list[Channel]: ...
