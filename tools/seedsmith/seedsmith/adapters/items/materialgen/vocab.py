"""seedsmith.adapters.items.materialgen.vocab — the issuable material vocabulary: a CLOSED 27-id
core (five classes, mirrored from `MaterialCatalog.cs` and its two upstream enums), a sixth, OPEN
population minted by the trophy planner (species-gear-chain T34), and a seventh, CLOSED three-id
class (species-gear-chain T40, `assurance.assure`/`.protect`/`.repair`).

⛔ **This is the module's most important file.** `materials-gen`'s own spec (acceptance #2) requires
confirming a target id is a real member of the issuable vocabulary BEFORE generating content for it —
refusing rather than authoring for an id that doesn't exist. Every other file in this package calls
`require_issuable` (or checks `is_issuable`) before it does anything else with an id.

⛔ **The closed core is mirrored, never hand-copied from memory.** Its 27 ids are reconstructed here
by walking the same enum members and building the same class-order concatenation
`MaterialCatalog.Build()` does in C# — not a transcribed literal list — so a rung/element/grade/verb
added to an upstream enum shows up as a wrong COUNT here (pinned by `test_materials_gen.py`) rather
than silently drifting apart. There is no committed JSON mirror of this vocabulary anywhere in the
repo today (checked: no `AtomVocabCheck`-named file, no `material`-named registry file exists) — the
sole precedent for "mirror a closed C# enum into Python with a citation, no re-derivation" is
`adapters/creatures/registries.py`, and this file follows that same discipline.

⛔ **The trophy population is READ, never mirrored.** Unlike the five closed classes, Trophy ids do
not come from a C# enum at all (`MaterialCatalog.ClassOf` resolves them from a host-injected
registry at runtime, T34b) — so there is nothing to mirror. This file instead reads the same
committed registry file the planner writes (`gk-forge/tools/seedsmith/seedsmith/adapters/items/trophyplan/`)
and folds its rows into `ISSUABLE`. Its count is a reading of that file, never pinned
(`validation-ssot.md`).

Citations, read 2026-09-07 directly from source (never from memory or an earlier session's notes):

    gk-core/src/FusionRpg.Core/Creatures/CreatureRarity.cs:16-28        CreatureRarity enum — Chaff=0 .. Almanac=9,
                                                            ordinal IS rank (the enum's own doc comment)
    gk-core/src/FusionRpg.Core/Creatures/CreatureRarity.cs:52-65        CreatureRarityIds.ToId() — the literal id
                                                            string for each rung, e.g. Chaff -> "chaff"
    gk-core/src/FusionRpg.Core/Creatures/CreatureRarityLadder.cs:51-52  CreatureRarityLadder.All — every rung, ordered
                                                            by (int)r ascending (this is what
                                                            MaterialCatalog.Build() iterates for shard)
    gk-core/src/FusionRpg.Core/Creatures/CreatureRarity.cs:92-101       LegacyCreatureRarityIds.ForwardMap — the four
                                                            legacy band ids (common/rare/epic/legendary),
                                                            resolvable but never issuable
    gk-core/src/FusionRpg.Core/Stats/Derived/ActorElementTypes.cs:21-29
                                                            ElementRoster.Concrete — the 6 elements,
                                                            in iteration order (omni excluded: essence
                                                            ids are never omni, MaterialCatalog.cs:83)
    gk-core/src/FusionRpg.Core/Stats/Derived/ActorElementTypes.cs:93-102
                                                            ElementTypeIdExtensions.ToElementId() — the
                                                            literal id string for each element
    gk-core/src/FusionRpg.Core/Items/Materials/MaterialCatalog.cs:50   SubstrateFrames = humanoid, plant
    gk-core/src/FusionRpg.Core/Items/Materials/MaterialCatalog.cs:54   SubstrateGrades = crude, sound, fine, prime
    gk-core/src/FusionRpg.Core/Items/Materials/MaterialCatalog.cs:57   CatalystVerbs = forge, temper, flux
    gk-core/src/FusionRpg.Core/Items/Materials/MaterialCatalog.cs:70-90 Build() — the exact class order this
                                                            module's own `_build_issuable` mirrors:
                                                            shard x10, substrate x8, essence x6,
                                                            catalyst x3 = 27
"""
from __future__ import annotations

from dataclasses import dataclass

from seedsmith.ladders import RARITY_LADDER as RARITY_RUNGS

from ..trophyplan.run import REGISTRY_PATH as TROPHY_REGISTRY_PATH
from ..trophyplan.run import load_registry as _load_trophy_registry

#: The declaring read — gk-data/packs/fusion/data/seed/rarity/ladder.v1.json via seedsmith.ladders
#: (tier-propagation-contract T-2). Chaff (weakest) first, Almanac (strongest) last.
#: Ordinal IS rank; never re-sort this alphabetically or by any other key
#: (CreatureRarity.cs's own hard warning).

#: MaterialCatalog.SubstrateFrames.
SUBSTRATE_FRAMES: "tuple[str, ...]" = ("humanoid", "plant")

#: MaterialCatalog.SubstrateGrades — ordinal 1..4, `SubstrateGrades[g-1]` for grade `g`.
SUBSTRATE_GRADES: "tuple[str, ...]" = ("crude", "sound", "fine", "prime")

#: ElementRoster.Concrete, in iteration order. Omni is deliberately excluded — MaterialCatalog.cs's
#: `Build()` iterates `ElementRoster.Concrete` only, never the omni id, so `essence.omni` is not,
#: and will never be, a member of this vocabulary.
ELEMENTS: "tuple[str, ...]" = ("fire", "ice", "air", "earth", "light", "dark")

#: MaterialCatalog.CatalystVerbs.
CATALYST_VERBS: "tuple[str, ...]" = ("forge", "temper", "flux")

#: MaterialCatalog.AssuranceVerbs (species-gear-chain T40) — the seventh class, CLOSED at three
#: like CATALYST_VERBS, never a population like the trophy registry below.
ASSURANCE_VERBS: "tuple[str, ...]" = ("assure", "protect", "repair")

#: LegacyCreatureRarityIds.ForwardMap's keys — the four retired shard bands. `IsKnown` (not
#: `IsIssuable`) resolves these; a generator must never author NEW content for one.
LEGACY_SHARD_IDS: "frozenset[str]" = frozenset({"common", "rare", "epic", "legendary"})


class MaterialVocabularyRejection(ValueError):
    """Mirrors `MaterialVocabularyRejection` (MaterialCatalog.cs) in name and in refusing loudly
    rather than silently inventing content — this module raises its own exception type (there is no
    cross-language exception to import) but keeps the same name on purpose: a refusal on the Python
    side and a refusal on the C# side should read as the same rule stated twice, not two different
    tools disagreeing about what is legal."""


@dataclass(frozen=True)
class MaterialId:
    """One issuable material id, with the structural fields `kinds.py`'s `material` KindSpec already
    declares as optional (`element`, `frame`, `grade`, and — species-gear-chain T34 — `scope`/
    `scopeKey`/`slot`) — populated only where the class carries them, exactly as
    `MaterialCatalog.ClassOf`/`FrameOf`/`GradeOf` would report for the same runtime id."""

    material_class: str            # "shard" | "substrate" | "essence" | "catalyst" | "trophy" | "assurance"
    runtime_id: str
    element: "str | None" = None
    frame: "str | None" = None
    grade: "int | None" = None
    scope: "str | None" = None      # trophy only: "species" | "family"
    scope_key: "str | None" = None  # trophy only: the speciesId/familyId this trophy came from
    slot: "int | None" = None       # trophy only: 1..perSpecies/perFamily


def _build_issuable() -> "tuple[MaterialId, ...]":
    """`MaterialCatalog.Build()`'s exact class order, walked the same way: shard, then substrate
    (frame outer, grade inner), then essence, then catalyst."""
    out: "list[MaterialId]" = []
    for rung in RARITY_RUNGS:
        out.append(MaterialId(material_class="shard", runtime_id=f"shard.{rung}"))
    for frame in SUBSTRATE_FRAMES:
        for ordinal, grade in enumerate(SUBSTRATE_GRADES, start=1):
            out.append(MaterialId(
                material_class="substrate", runtime_id=f"substrate.{frame}.{grade}",
                frame=frame, grade=ordinal))
    for element in ELEMENTS:
        out.append(MaterialId(
            material_class="essence", runtime_id=f"essence.{element}", element=element))
    for verb in CATALYST_VERBS:
        out.append(MaterialId(material_class="catalyst", runtime_id=f"catalyst.{verb}"))
    return tuple(out)


def _build_trophy_issuable(path=None) -> "tuple[MaterialId, ...]":
    """The trophy portion of `ISSUABLE` — **species-gear-chain T34, revising T33's own note that
    "Trophy contributes NOTHING here."** That note described `MaterialCatalog.ClassOf` (C# runtime
    side, still true and untouched: Trophy resolves from a HOST-INJECTED registry, never a compiled
    enum, T34b's own territory) — a different vocabulary from THIS one, which is "what may
    `materialgen` author display content for." The trophy id registry
    (`gk-forge/tools/seedsmith/seedsmith/adapters/items/trophyplan/`) is that same population's SOURCE here:
    every row it has minted is issuable content-wise, even though none of them are ever hard-coded
    into a Python enum the way shard/substrate/essence/catalyst are.

    Missing-registry-file tolerant (returns `()`), matching `_load_trophy_registry`'s own bootstrap
    contract (a fresh checkout before the planner's first `--write` is not a materialgen import-time
    crash) — the same posture `distribution_planner.tuning.load_dedup_k` already takes for its own
    not-yet-built sibling file.
    """
    rows = _load_trophy_registry(path)
    return tuple(
        MaterialId(material_class="trophy", runtime_id=row.material_id,
                  scope=row.scope, scope_key=row.scope_key, slot=row.slot)
        for row in rows)


def _build_assurance_issuable() -> "tuple[MaterialId, ...]":
    """species-gear-chain T40 — the seventh class's own three ids. CLOSED, like the original five
    (`_build_issuable`), never a population like trophy: `materialgen` authors display content for
    exactly `assurance.assure`/`.protect`/`.repair`, and a fourth verb is the next ask-first
    boundary (`MaterialCatalog.AssuranceVerbs`'s own doc comment)."""
    return tuple(
        MaterialId(material_class="assurance", runtime_id=f"assurance.{verb}")
        for verb in ASSURANCE_VERBS)


#: The issuable vocabulary materialgen may author display content for, in `MaterialCatalog.All`'s
#: own order for the five closed classes, followed by the trophy population, followed by the
#: assurance class. The closed-class count (27 today: shard x10 + substrate x8 + essence x6 +
#: catalyst x3) is a RECONCILIATION below, never a literal (species-gear-chain T33): an upstream
#: rung/frame/grade/element/verb addition is caught by the four counted building blocks disagreeing
#: with the built list, not by a number this file would otherwise need editing to match. The trophy
#: count is likewise a READING of the committed registry file, never pinned (`validation-ssot.md`: a
#: derived population's size is a reading, not a constant) — it grows exactly when the planner mints
#: new rows, never by an edit here. The assurance count (3, T40) IS pinned — it is a genuinely closed
#: vocabulary, the same species of constant as `len(CATALYST_VERBS)`, not a population.
ISSUABLE: "tuple[MaterialId, ...]" = (
    _build_issuable() + _build_trophy_issuable() + _build_assurance_issuable())

ISSUABLE_BY_ID: "dict[str, MaterialId]" = {m.runtime_id: m for m in ISSUABLE}

_EXPECTED_CLOSED_CLASS_COUNT = (
    len(RARITY_RUNGS)                                  # shard.{rung}
    + len(SUBSTRATE_FRAMES) * len(SUBSTRATE_GRADES)    # substrate.{frame}.{grade}
    + len(ELEMENTS)                                    # essence.{element}
    + len(CATALYST_VERBS)                              # catalyst.{verb}
)
_TROPHY_COUNT = len(_build_trophy_issuable())
_ASSURANCE_COUNT = len(ASSURANCE_VERBS)
_EXPECTED_ISSUABLE_COUNT = _EXPECTED_CLOSED_CLASS_COUNT + _TROPHY_COUNT + _ASSURANCE_COUNT
assert len(ISSUABLE) == _EXPECTED_ISSUABLE_COUNT, (
    f"ISSUABLE has {len(ISSUABLE)} ids but the closed classes (rungs={len(RARITY_RUNGS)}, "
    f"substrate={len(SUBSTRATE_FRAMES)}x{len(SUBSTRATE_GRADES)}, elements={len(ELEMENTS)}, "
    f"catalysts={len(CATALYST_VERBS)} = {_EXPECTED_CLOSED_CLASS_COUNT}) plus the trophy registry "
    f"({_TROPHY_COUNT} rows) plus assurance ({_ASSURANCE_COUNT} ids) expect "
    f"{_EXPECTED_ISSUABLE_COUNT} — either the C# enum mirror or the trophy registry has drifted "
    "from what this file reconstructs")
assert len(ISSUABLE_BY_ID) == _EXPECTED_ISSUABLE_COUNT, "duplicate runtime id produced by this mirror"


def is_issuable(runtime_id: str) -> bool:
    """True for one of the closed, issuable ids `MaterialCatalog.Build()` mints. Mirrors `IsIssuable`."""
    return runtime_id in ISSUABLE_BY_ID


def is_legacy_shard_id(runtime_id: str) -> bool:
    """True only for the four retired band ids (`shard.common`/`shard.rare`/`shard.epic`/
    `shard.legendary`) — resolvable, never minted. Mirrors `IsLegacyShardId`."""
    if not runtime_id.startswith("shard."):
        return False
    return runtime_id[len("shard."):] in LEGACY_SHARD_IDS


def is_known(runtime_id: str) -> bool:
    """Issuable OR a legacy shard id. Mirrors `IsKnown` — a saved reference to a legacy id still
    resolves, but `is_issuable` alone is what this generator gates new content on."""
    return is_issuable(runtime_id) or is_legacy_shard_id(runtime_id)


def require_issuable(runtime_id: str) -> MaterialId:
    """The generator's own gate. Call this BEFORE authoring content for any id — it refuses loudly,
    never silently inventing a new material kind, for anything outside the 27-id closed vocabulary,
    including an id that is merely *known* (a legacy shard band) rather than issuable."""
    material = ISSUABLE_BY_ID.get(runtime_id)
    if material is not None:
        return material
    if is_legacy_shard_id(runtime_id):
        raise MaterialVocabularyRejection(
            f"material id {runtime_id!r} is a legacy, retired shard band — resolvable for backward "
            f"compatibility (LegacyCreatureRarityIds.ForwardMap) but deliberately NOT issuable "
            f"(MaterialCatalog.IsIssuable is false for every legacy id, per its own doc comment); "
            f"materials-gen only authors content for an id the ladder will actually mint, never for "
            f"a retired one.")
    raise MaterialVocabularyRejection(
        f"material id {runtime_id!r} is not issuable: not one of the {_EXPECTED_CLOSED_CLASS_COUNT} "
        f"closed-class ids MaterialCatalog.All defines (shard.<rung>, substrate.<frame>.<grade>, "
        f"essence.<element>, catalyst.<verb>), not one of the {_TROPHY_COUNT} ids the trophy "
        f"registry ({TROPHY_REGISTRY_PATH.name}) has minted, and not one of the {_ASSURANCE_COUNT} "
        f"closed assurance.<verb> ids. materials-gen never invents a new material id — it only "
        f"authors display content for one an upstream source already lists. Extending the closed "
        f"classes (MaterialClass/CatalystVerbs/SubstrateFrames/SubstrateGrades/AssuranceVerbs) is "
        f"ask-first per MaterialCatalog.cs's own doc comment; a new trophy id is minted only by "
        f"the trophyplan planner, never fabricated here.")


def missing_from(existing_runtime_ids: "set[str] | frozenset[str]") -> "tuple[MaterialId, ...]":
    """The issuable ids NOT already present in a corpus snapshot, in `ISSUABLE`'s own order —
    the real content gap this generator exists to close (measured 2026-09-07: all ten rarity-ladder
    shard rungs are missing from `gk-data/packs/fusion/data/seed/items/materials/materials.json` today; only the four
    legacy shard ids it carries are shard entries at all)."""
    return tuple(m for m in ISSUABLE if m.runtime_id not in existing_runtime_ids)
