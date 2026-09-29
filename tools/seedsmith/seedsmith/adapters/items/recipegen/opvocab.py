"""seedsmith.adapters.items.recipegen.opvocab — the ONE place that knows the real, closed
`operation` vocabulary a recipe row may ever name (spec-recipes-gen.md acceptance #2 and "Code
style": *"`opvocab.py` reads the real, current operation vocabulary from its C# source of truth ...
rather than hand-typing a Python copy of it"*).

⛔ **This is the exact gap that let the 2026-09-05 drift happen unnoticed.** A human rewrote
`"operation": "reroll"` into `"reroll-one"`/`"reroll-all"` directly in the committed JSON because no
tool checked the corpus against the real vocabulary. This module is that check.

**Transcribed with citation, not hand-guessed — the same discipline `affixfamgen.opvocab` and
`materialgen.vocab` both state for their own closed vocabularies.** There is no JSON export of
`CraftOperation`/`CraftOperations` to read programmatically from Python, so the ten ids below are
copied verbatim from the real enum and its `Id()` switch, with exact line citations, and
`test_reconcile_operations_finds_zero_drift_in_the_real_30_entry_corpus_today` (in
`tests/test_recipes_gen.py`) is what catches a future drift between this transcription and the
real enum: it asserts the shipped corpus's own `operation` values are a subset of `ALL_OPERATIONS`,
so a real rename that this file is not updated for shows up as a red test, not a silent gap.

Real evidence, read directly from `gk-core/src/FusionRpg.Core/Items/Materials/CostClassMatrix.cs`:

    CostClassMatrix.cs:11-44   `enum CraftOperation` — ten members, Forge=0 first, RerollAll=9 last.
                               Ordinal IS `CraftOperations.All`'s own order (`OrderBy(o => (int)o)`).
    CostClassMatrix.cs:49-62   `CraftOperations.Id(CraftOperation)` — the literal kebab-case content
                               id for each member (`RerollOne -> "reroll-one"`, `RerollAll ->
                               "reroll-all"` — the exact two strings the 2026-09-05 patch introduced).
    CostClassMatrix.cs:101-120 `CostClassMatrix.CatalystFor(CraftOperation)` — which catalyst id (if
                               any) an operation rides. `Upcycle`/`Socket` ride none (their own
                               doc comment: "neither brings anything into existence").
    CostClassMatrix.cs:123-138 `CostClassMatrix.Allows(CraftOperation, MaterialClass)` — which spend
                               classes an operation may name at all, enforced at import
                               (`MaterialRecipeCatalog.Load` calls `CostClassMatrix.Check` per cost
                               line). `Souls` (the flat fee) is legal for every operation.

**`outputKind` per operation is NOT itself part of `CraftOperation`/`CostClassMatrix` — it is a
fact about what each operation DOES, read off the real 30-entry corpus and each operation's own doc
comment on the enum** (`Forge`: "Mint a base from nothing"; `Upcycle`: "Convert ... grade g into ...
grade g+1"; everything else in the shipped corpus mutates an owned instance). `ForgeGem` mints too
(a gem) and species-gear-chain T9 specified its reference target (`gemgen`, spec-gem-tier.md §4):
`OPERATION_OUTPUT_KIND` maps it to `"gem"` and `forgegem.py` emits its rows deterministically, so
the brief path still never offers it (nothing to author — same family, next tier) while the
vocabulary, output-kind map and cost-class checks all recognize it. `Imbue`'s own doc comment ("its `op_kind` is module 15's to
add, not this module's") — legal to parse, but not offered by this generator's brief since the real
corpus never uses it and this module has no basis to invent one.
"""
from __future__ import annotations

#: `CraftOperation` enum order, `CraftOperations.Id()` verbatim (CostClassMatrix.cs:11-71).
#: species-gear-chain T23 appended `repair` (the eleventh member).
ALL_OPERATIONS: "tuple[str, ...]" = (
    "forge", "upcycle", "forge-gem", "bore", "imbue", "socket", "elevate", "temper",
    "reroll-one", "reroll-all", "repair",
)

#: Operations this generator will offer a model, per this module's own docstring: every real,
#: parseable operation EXCEPT `imbue` (never used by the real corpus and this generator has no
#: basis to invent a first use of it). `forge-gem` JOINED this list in species-gear-chain T9 —
#: its reference target (`gemgen`) is now specified (spec-gem-tier.md §4) and its rows are emitted
#: deterministically by `forgegem.py` (no model call), so the brief path never offers it but the
#: vocabulary, output-kind map and cost-class checks all recognize it.
SUPPORTED_FOR_GENERATION: "tuple[str, ...]" = (
    "forge", "upcycle", "forge-gem", "bore", "socket", "elevate", "temper", "reroll-one",
    "reroll-all",
)

#: The `outputKind` each supported operation mints/mutates — read off the real 30-entry corpus
#: (every `forge` row is `container`, every `upcycle` row is `material`, everything else is
#: `mutation`) and each operation's own CostClassMatrix.cs doc comment. DERIVED, never a second
#: model choice — asking the model to also pick `outputKind` is exactly the "two authors of the
#: same fact eventually disagree" trap `materialgen.emit`'s own docstring names for `nameKey`.
OPERATION_OUTPUT_KIND: "dict[str, str]" = {
    "forge": "container",
    "upcycle": "material",
    "forge-gem": "gem",
    "bore": "mutation",
    "socket": "mutation",
    "elevate": "mutation",
    "temper": "mutation",
    "reroll-one": "mutation",
    "reroll-all": "mutation",
    "repair": "mutation",
}

#: `CostClassMatrix.CatalystFor` (CostClassMatrix.cs:101-120), transcribed. `None` for the two
#: operations that burn no catalyst at all.
CATALYST_FOR: "dict[str, str | None]" = {
    "forge": "catalyst.forge",
    "upcycle": None,
    "forge-gem": "catalyst.forge",
    "bore": "catalyst.forge",
    "imbue": "catalyst.forge",
    "socket": None,
    "elevate": "catalyst.temper",
    "temper": "catalyst.temper",
    "reroll-one": "catalyst.flux",
    "reroll-all": "catalyst.flux",
    "repair": "catalyst.temper",
}

#: `CostClassMatrix.Allows` (CostClassMatrix.cs:123-138), transcribed as the set of `MaterialClass`
#: NAMES (lowercase, matching `MaterialCatalog.ClassOf`'s own return-value spelling once lowercased)
#: each operation may spend a cost line of, EXCLUDING `souls` (legal for every operation, per
#: `Allows`'s own first case — checked separately, never per-operation).
ALLOWED_CLASSES: "dict[str, frozenset[str]]" = {
    "forge": frozenset({"substrate", "catalyst"}),
    "upcycle": frozenset({"substrate"}),
    "forge-gem": frozenset({"shard", "essence", "catalyst"}),
    "bore": frozenset({"substrate", "catalyst"}),
    "imbue": frozenset({"substrate", "essence", "catalyst"}),
    "socket": frozenset(),
    "elevate": frozenset({"shard", "substrate", "catalyst"}),
    "temper": frozenset({"substrate", "catalyst"}),
    "reroll-one": frozenset({"essence", "catalyst"}),
    "reroll-all": frozenset({"shard", "catalyst"}),
    "repair": frozenset({"shard", "substrate", "catalyst"}),
}


class UnsupportedOperationError(ValueError):
    """`operation` is not one of `SUPPORTED_FOR_GENERATION` — either not a real operation at all
    (the 2026-09-05 failure mode) or a real-but-out-of-scope one (`forge-gem`/`imbue`)."""

    def __init__(self, operation: str) -> None:
        super().__init__(
            f"operation {operation!r} is not one of this generator's supported operations "
            f"{SUPPORTED_FOR_GENERATION} — real vocabulary is {ALL_OPERATIONS} "
            f"(CraftOperations.AllIds); see opvocab.py's own docstring for why forge-gem/imbue "
            f"are parseable but not offered here")
        self.operation = operation


class CostClassForbiddenError(ValueError):
    """Mirrors `CostClassMatrix.CostClassForbiddenRule` — a cost line names a `MaterialClass` the
    operation may never spend, which `MaterialRecipeCatalog.Load` would refuse at import."""


class CatalystMismatchError(ValueError):
    """Mirrors `CostClassMatrix.CatalystMismatchRule` — a catalyst line names the wrong catalyst id
    for the operation (the spec's own named example: a `forge` recipe spending `catalyst.temper`)."""


def is_supported_operation(operation: str) -> bool:
    return operation in OPERATION_OUTPUT_KIND


def require_supported_operation(operation: str) -> str:
    """The generation-time gate: raises for anything outside `SUPPORTED_FOR_GENERATION`, returns
    `operation` unchanged on success. Called before a brief is ever built for it."""
    if not is_supported_operation(operation):
        raise UnsupportedOperationError(operation)
    return operation


def output_kind_for(operation: str) -> str:
    """The `outputKind` a legal-for-generation `operation` mints/mutates. Raises for an operation
    outside `SUPPORTED_FOR_GENERATION` rather than guessing."""
    if operation not in OPERATION_OUTPUT_KIND:
        raise UnsupportedOperationError(operation)
    return OPERATION_OUTPUT_KIND[operation]


def catalyst_for(operation: str) -> "str | None":
    if operation not in CATALYST_FOR:
        raise UnsupportedOperationError(operation)
    return CATALYST_FOR[operation]


def check_cost_class(operation: str, material_class: str, material_id: str) -> None:
    """Mirrors `CostClassMatrix.Check` (CostClassMatrix.cs:154-171) — raises the matching Python
    exception for exactly what the real C# loader would refuse at import, so a generated recipe can
    never reach the corpus with a cost line `MaterialRecipeCatalog.Load` would reject.
    `material_class` is one of `souls`/`shard`/`substrate`/`essence`/`catalyst` (lowercase)."""
    if material_class == "souls":
        return  # every operation may charge the flat fee (Allows's own first case)
    allowed = ALLOWED_CLASSES.get(operation)
    if allowed is None:
        raise UnsupportedOperationError(operation)
    if material_class not in allowed:
        raise CostClassForbiddenError(
            f"operation {operation!r} may not spend a {material_class} line ({material_id!r}) — "
            f"CostClassMatrix.Allows permits only {sorted(allowed) or '(none)'} for this operation")
    if material_class == "catalyst":
        expected = catalyst_for(operation)
        if expected != material_id:
            raise CatalystMismatchError(
                f"operation {operation!r} rides {expected!r}, not {material_id!r} "
                f"(CostClassMatrix.CatalystFor)")


def reconcile_operations(entries: "dict[str, dict]") -> "list[tuple[str, str]]":
    """The mechanical check acceptance #3 requires: every `(entryId, operation)` pair in `entries`
    whose `operation` is NOT one of `ALL_OPERATIONS` (the real, current, closed vocabulary) — the
    exact drift a `"reroll"` -> `"reroll-one"`/`"reroll-all"` rename would have produced, had this
    run against the corpus before 2026-09-05's hand patch. Checked against `ALL_OPERATIONS` (every
    real parseable operation), not `SUPPORTED_FOR_GENERATION` — reconcile asks "does the real C#
    loader still recognize this", not "would this generator have chosen it".

    Order-preserving over `entries`' own iteration order; pass a `dict` built from `sorted(ids)` for
    a byte-identical report across runs, the same discipline `dependency_validator.validate` states
    for itself.
    """
    drifted: "list[tuple[str, str]]" = []
    for entry_id, entry in entries.items():
        operation = entry.get("operation")
        if operation not in ALL_OPERATIONS:
            drifted.append((entry_id, operation))
    return drifted
