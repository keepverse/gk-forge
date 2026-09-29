"""seedsmith.adapters.items.affixfamgen.opvocab — the ONE place that knows the real, closed
op-per-atom-kind vocabulary this generator may ever emit (spec-affix-families-gen.md, Acceptance
#3 and "Code style").

**Transcribed with citation, not hand-guessed, and not re-derived a second time anywhere else in
this package.** There is no JSON export of `AtomKindRegistry.cs`'s per-kind op enum to read
programmatically from Python — the same situation `adapters.items.channels` already documents for
`BattleRuleset`'s formulas ("there is no JSON export of that C# class to read instead"). This
module follows that exact precedent: copy the real values, cite the exact lines, and let a test
assert the shipped seed corpus (`gk-data/packs/fusion/data/seed/items/affix-families/*.json`) never uses an op outside
what is transcribed here — so a future registry change that silently drifts is caught by the
corpus itself disagreeing with this table, not by trusting the transcription forever.

Real evidence, read directly from `gk-core/src/FusionRpg.Core/Effects/Atoms/AtomKindRegistry.cs`:

- `stat.modify` (line ~494-521): `ParamDef("op", ...)` carries no `Vocabulary` declaration, but the
  kind's own doc string (line 517) states plainly "Ops are Flat|Increased|More — effects cannot
  emit Override", and `Validate()` (line 349-357) explicitly REJECTS `op == "Override"`
  (case-insensitive) with that exact reasoning ("it has no revert path; a permanent Override would
  leak"). Three legal ops: `Flat`, `Increased`, `More`.
- `stat.derived` (line ~523-583): same shape, no `Vocabulary` on `op`, but the kind's own doc
  string (line 582) states "Derived ops are Flat|Increased|Replace|Flag; there is no More on the
  derived side." Four legal ops: `Flat`, `Increased`, `Replace`, `Flag`.

Real, shipped seed content confirms the exact casing used on disk (PascalCase, not lowercase):
`gk-data/packs/fusion/data/seed/items/affix-families/g-attack.json` uses `"op": "Flat"` / `"Increased"` / `"More"` for
three `stat.modify` entries; `gk-data/packs/fusion/data/seed/items/affix-families/g-precision.json` uses `"Flat"` /
`"Replace"` / `"Flag"` for `stat.derived` entries. The spec's own Acceptance #3 prose spells the
vocabulary in lowercase (`flat`/`increased`/`replace`/`flag`, `flat`/`increased`/`more`) — this is
the spec's own shorthand for the SET, not the literal on-disk casing; this module treats the
comparison as case-insensitive (matching `AtomKindRegistry.Validate`'s own `OrdinalIgnoreCase`
check on `Override`) but always EMITS the shipped PascalCase spelling, never invents a third
casing convention.
"""
from __future__ import annotations

STAT_MODIFY = "stat.modify"
STAT_DERIVED = "stat.derived"

#: kindId -> the real, closed op vocabulary, PascalCase (the shipped on-disk casing).
LEGAL_OPS: "dict[str, tuple[str, ...]]" = {
    STAT_MODIFY: ("Flat", "Increased", "More"),
    STAT_DERIVED: ("Flat", "Increased", "Replace", "Flag"),
}

#: The two atom kinds this module is scoped to (spec's own Acceptance #3: "the generator must know
#: which kind the family targets"). Any other kindId is out of scope for `affix-families-gen` —
#: refused, never guessed at.
SUPPORTED_KINDS: "frozenset[str]" = frozenset(LEGAL_OPS)


class UnsupportedKindError(ValueError):
    """`kindId` is not one of the two atom kinds this generator authors against."""

    def __init__(self, kind_id: str) -> None:
        super().__init__(
            f"kindId {kind_id!r} is not one of {sorted(SUPPORTED_KINDS)} — affix-families-gen "
            f"only authors stat.modify / stat.derived families (spec-affix-families-gen.md "
            f"Acceptance #3)")
        self.kind_id = kind_id


class IllegalOpError(ValueError):
    """An op outside the real, closed vocabulary for the given kindId."""

    def __init__(self, kind_id: str, op: str) -> None:
        legal = LEGAL_OPS[kind_id]
        super().__init__(
            f"op {op!r} is not legal for kindId {kind_id!r} — the real vocabulary is "
            f"{legal} (AtomKindRegistry.cs). Never emit an op neither consumer can parse.")
        self.kind_id = kind_id
        self.op = op


def legal_ops(kind_id: str) -> "tuple[str, ...]":
    """The real, closed op vocabulary for `kind_id`. Raises `UnsupportedKindError` for anything
    outside `SUPPORTED_KINDS` rather than returning an empty tuple — an empty enum in a JSON Schema
    is a silent dead end, not a clear refusal."""
    if kind_id not in LEGAL_OPS:
        raise UnsupportedKindError(kind_id)
    return LEGAL_OPS[kind_id]


def is_legal_op(kind_id: str, op: str) -> bool:
    """Case-insensitive membership check, matching `AtomKindRegistry.Validate`'s own
    `OrdinalIgnoreCase` comparison on the one op it explicitly special-cases (`Override`)."""
    if kind_id not in LEGAL_OPS:
        return False
    return op.lower() in {o.lower() for o in LEGAL_OPS[kind_id]}


def is_supported_kind(kind_id: str) -> bool:
    """True for the two atom kinds this generator authors against. Distinct from `is_legal_op`
    (which also needs a real `op`): a caller scanning mixed-kind content (the real corpus has
    `spawn.entity`, `resource.delta`, `status.apply` entries with no `op` param at all) checks this
    FIRST, before it is safe to even look for an `op` field."""
    return kind_id in SUPPORTED_KINDS


def canonical_op(kind_id: str, op: str) -> str:
    """The shipped PascalCase spelling for a legal `op`, regardless of the caller's casing —
    `emit.py` uses this so a model answer spelled `"flat"` still lands in the corpus as `"Flat"`,
    matching the casing every real entry in `gk-data/packs/fusion/data/seed/items/affix-families/*.json` already uses.
    Raises `IllegalOpError` (not a silent pass-through) if `op` is not legal for `kind_id` — the
    canonicalization step is exactly where Acceptance #3's guarantee is enforced, not merely
    documented."""
    if kind_id not in LEGAL_OPS:
        raise UnsupportedKindError(kind_id)
    for legal in LEGAL_OPS[kind_id]:
        if legal.lower() == op.lower():
            return legal
    raise IllegalOpError(kind_id, op)


def assert_legal_op(kind_id: str, op: str) -> None:
    """Raises `UnsupportedKindError` / `IllegalOpError`; returns `None` on success. A thin,
    intention-revealing wrapper `emit.py`'s validation path calls before writing anything."""
    canonical_op(kind_id, op)
