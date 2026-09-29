"""seedsmith.adapters.dungeon.registries — reads `gk-data/packs/fusion/data/seed/dungeon/_registry/*.json` fresh on
every call (D1.5, spec-dungeon-registries.md "The seedsmith side"): "the `dungeon` adapter reads
... fresh on every call, the `adapters/items/registries.py:1-6` discipline ('read, never
transcribed'), and never the `adapters/creatures/registries.py:3-9` shape (a mirror of C# enums,
pinned by count)."

This is the ONE place the nine registry files are read on the Python side. The C# counterpart is
`gk-core/src/FusionRpg.Core/Dungeon/Registry/DungeonRegistries.cs` — the two must never be allowed to
drift, which is exactly what `test_dungeon_registries.py` proves on every run: both sides load the
SAME committed JSON, so a drift is impossible by construction, not by discipline alone.
"""
from __future__ import annotations
import json

from pathlib import Path

from seedsmith.ladders import THREAT_BAND as _THREAT_BAND

REPO_ROOT = Path(__file__).resolve().parents[5]
REGISTRY_DIR = REPO_ROOT / "data" / "seed" / "dungeon" / "_registry"

#: `theme`'s own vocabulary has no dungeon-registries home (spec-dungeon-seed-contract.md:44:
#: `` `themes.v1.json` (84 rows) `` — stale count from the old 84-species catalog, 904 rows today and
#: unrelated to the 84 retired rarity ids T16 migrated (spec-ladder-consistency-repair.md Defect 1);
#: `party-dungeon-ideal.md:838`: "the frozen theme registry
#: under `gk-data/packs/fusion/data/seed/creatures/_registry/`") — a frozen CROSS-PROGRAM input the dungeon adapter reads,
#: never authors (`spec-dungeon-seed-contract.md:143`'s own "frozen inputs" list names
#: `themes/motifs/families` alongside `registries.v1`), the same shape `dropBand` already crosses
#: from the item registry into `dungeon-loot` on the C# side. Second-reader propagation of
#: `spec-creature-themes.md`'s own one-way publish — see this adapter's own D1.10 todo entry for the
#: full citation trail; `adapters/items/registries.py:33-55`'s `load_theme_keys()` is the direct
#: precedent for this exact cross-program read.
CREATURES_REGISTRY_DIR = REPO_ROOT / "data" / "seed" / "creatures" / "_registry"

_REGISTRY_FILES = (
    "room-kinds.v1.json", "door-kinds.v1.json", "override-tags.v1.json",
    "objective-templates.v1.json", "difficulty-rungs.v1.json", "disposition.v1.json",
    "interaction-verbs.v1.json", "raid-modes.v1.json", "bands.v1.json",
)


def _load(name: str) -> dict:
    path = REGISTRY_DIR / name
    return json.loads(path.read_text(encoding="utf-8"))


def _load_creatures(name: str) -> dict:
    path = CREATURES_REGISTRY_DIR / name
    return json.loads(path.read_text(encoding="utf-8"))


def load_versions() -> dict[str, int]:
    """`registryVersion` per file, read fresh — never hardcoded (items/registries.py precedent).
    Includes the two cross-program creature registries `theme`/`motif` read as frozen inputs, prefixed
    `creatures.` so a version bump on either side is independently named in provenance/`stale_ids()`
    rather than colliding with a same-named dungeon-native file."""
    versions = {name.removesuffix(".v1.json"): _load(name)["registryVersion"] for name in _REGISTRY_FILES}
    versions["creatures.themes"] = _load_creatures("themes.v1.json")["registryVersion"]
    versions["creatures.motifs"] = _load_creatures("motifs.v1.json")["registryVersion"]
    return versions


def load_room_kinds() -> dict[str, dict]:
    """The eleven room kinds with their flags — `climateNeutral`, `secretEligible`,
    `bossRowAllowed`, `neverAdjacentTo`, `unknownResolvesTo` — exactly the row shape
    `RoomKindCatalog.Parse` reads on the C# side."""
    return dict(_load("room-kinds.v1.json")["roomKinds"])


def load_door_kinds() -> dict[str, dict]:
    return dict(_load("door-kinds.v1.json")["doorKinds"])


def load_override_tags() -> "frozenset[str]":
    return frozenset(_load("override-tags.v1.json")["overrideTags"])


def load_objective_templates() -> dict[str, dict]:
    """The nine objective templates with `targetKind` and `sinkAvoidance`."""
    return dict(_load("objective-templates.v1.json")["objectiveTemplates"])


def load_difficulty_rungs() -> dict[str, int]:
    """Rung id -> its 1-based ordinal. Ten rows, ordinals contiguous 1..10 (enforced on the C#
    side by `DifficultyRungCatalog.Validate`; this reader trusts the same committed file)."""
    rungs = _load("difficulty-rungs.v1.json")["rungs"]
    return {rung_id: row["ordinal"] for rung_id, row in rungs.items()}


def load_disposition() -> "frozenset[str]":
    return frozenset(_load("disposition.v1.json")["disposition"])


def load_interaction_verbs() -> dict[str, "int | None"]:
    """Verb id -> its base-defense decision number, or `None` where the verb resolves through a
    key-supply override or an event-deck draw rather than a base-defense structure decision
    (`open`, `disarm`, `pray`, `loot`) — `destroy` is 12, `garrison` is 15."""
    verbs = _load("interaction-verbs.v1.json")["interactionVerbs"]
    return {verb_id: row["decision"] for verb_id, row in verbs.items()}


def load_raid_modes() -> "frozenset[str]":
    return frozenset(_load("raid-modes.v1.json")["raidModes"])


def load_themes() -> "dict[str, dict]":
    """The creature-seed program's own published theme registry (`spec-creature-themes.md`), read as a
    frozen cross-program vocabulary — this adapter is a SECOND reader alongside
    `adapters/items/registries.py:33-55`'s own `load_theme_keys()`, never a second publisher: no
    row here is ever written back, matching the source registry's own "publish one-way" boundary.
    A retired theme's own row still resolves (a creature that leaves the roster keeps its published
    theme, per `spec-creature-themes.md`'s own row) — legal to reference, never filtered out here."""
    return dict(_load_creatures("themes.v1.json")["themes"])


def load_theme_ids() -> "frozenset[str]":
    """The legal `theme` vocabulary for a dungeon domain anchor — every id in the registry,
    `creature.*`-prefixed, retired or not (see `load_themes`'s own doc comment on retirement)."""
    return frozenset(load_themes())


def load_motifs() -> "frozenset[str]":
    """The flat union of every theme's own motifs (`gk-data/packs/fusion/data/seed/creatures/_registry/motifs.v1.json`) —
    the vocabulary `dungeon-seed-contract.md`'s own planner motif briefs (D1.9) partition per cell,
    never re-derived from `load_themes()`'s own per-theme lists here (the committed file is
    already the union, kept in sync by the creature program's own `generate_motifs.py`)."""
    return frozenset(_load_creatures("motifs.v1.json")["motifs"])


#: `gk-data/packs/fusion/data/seed/atoms/` — outside both `REGISTRY_DIR` and `CREATURES_REGISTRY_DIR`, the SAME frozen
#: cross-program vocabulary `spec-dungeon-seed-contract.md:143`'s own "frozen inputs" list already
#: names alongside `themes/motifs` ("registries.v1 (7) · species (threatBand) · themes/motifs/
#: families · consumables"). `adapters/items/registries.py:128-143`'s `load_atom_families()` is the
#: direct precedent — dungeon's event `outcomes[].effects[].family` field needs the SAME real,
#: closed vocabulary D4.24 already measured (28 real families, far fewer than any corpus's own
#: invented list would guess), so this is a second reader of an already-precedented read, not a new
#: boundary crossing (`families` was in the frozen-inputs list from wave 1, before either items or
#: dungeon actually built a reader for it).
ATOMS_DIR = REPO_ROOT / "data" / "seed" / "atoms"


def load_atom_families() -> "frozenset[str]":
    """Every real `family` value across every shipped atom entry — read fresh, never hand-
    transcribed, for the same reason `items/registries.py`'s own copy exists: a corpus that invents
    family names against a remembered list silently drifts the moment the atom catalog grows.
    Unfiltered — includes subsystem-bound families (see `load_grantable_atom_families` below);
    kept for parity with `items/registries.py`'s own function of the same name and signature."""
    families: "set[str]" = set()
    for path in sorted(ATOMS_DIR.rglob("*.json")):
        doc = json.loads(path.read_text(encoding="utf-8"))
        for entry in doc.get("entries") or ():
            family = entry.get("family")
            if isinstance(family, str):
                families.add(family)
    return frozenset(families)


def load_grantable_atom_families() -> "frozenset[str]":
    """The real subset of `load_atom_families()` legal for a dungeon-event `outcomes[].effects[]`
    grant — found by direct reading, not assumed: an atom carrying `icdKey` is bound to a SPECIFIC
    subsystem's own trigger wiring (`fx-board/-core/-status.json`'s lawn `when.trigger` hooks;
    `patron-aura.json`'s own aura mechanism; `trait-critical-hunter.json`; `extend-slot.json`'s own
    unique-rung mechanic) and is never handed out generically by another corpus — confirmed the
    property is per-FAMILY, not per-entry (every tier of a given family agrees). What is LEFT after
    excluding those (`generated/family-expand.g-*.json`'s own plain `stat.modify` atoms, no
    `icdKey`, no `when`) is exactly the same ownerless, freely-instantiable pool `unique-pipeline`
    already draws its 7-family overlap from (D4.24), plus two more of the same shape
    (`resilience`, `warding`) this reader surfaces for the first time."""
    grantable: "set[str]" = set()
    bound: "set[str]" = set()
    for path in sorted(ATOMS_DIR.rglob("*.json")):
        doc = json.loads(path.read_text(encoding="utf-8"))
        for entry in doc.get("entries") or ():
            family = entry.get("family")
            if not isinstance(family, str):
                continue
            (bound if "icdKey" in entry else grantable).add(family)
    return frozenset(grantable - bound)


#: `gk-data/packs/fusion/data/seed/items/_registry/bands.v1.json`'s own top-level `powerBand` key — a THIRD frozen
#: cross-program input (alongside themes/motifs and atom families), confirmed by direct read: the
#: dungeon-native `bands.v1.json` (`REGISTRY_DIR`) has no `powerBand` member at all (checked
#: directly — its twenty owned bands are `branchiness/countBand/dangerBand/deltaBand/density/
#: depthBand/elementSpread/entry/eventKind/formation/hazardBand/hpBand/nerveStage/outcomeOrdinal/
#: phasing/questScope/repeatScope/rewardBand/sightBand/widthBand`, no `powerBand` among them) — the
#: SAME five-value vocabulary `unique-pipeline`'s own `fixedAtoms[].powerBand` already reads
#: (`UniqueBudget.TierOfPowerBand`), one row per tier the atom layer has (definitions.md §1).
ITEMS_REGISTRY_DIR = REPO_ROOT / "data" / "seed" / "items" / "_registry"


def load_power_bands() -> "frozenset[str]":
    """The legal `outcomes[].effects[].powerBand` vocabulary for a dungeon event — read fresh from
    the items registry's own frozen `powerBand` entry, never hand-transcribed as a local literal
    tuple: a five-value enum is small enough to tempt hardcoding, which is exactly the drift risk
    `load_atom_families`'s own doc comment already names for the sibling cross-program read."""
    doc = json.loads((ITEMS_REGISTRY_DIR / "bands.v1.json").read_text(encoding="utf-8"))
    return frozenset(doc["powerBand"]["enum"])


#: `gk-data/packs/fusion/data/seed/zomboss/patterns.json` — a FOURTH frozen cross-program input (alongside themes/
#: motifs/atom-families/powerBand). `ZombossPatterns.cs`'s own doc comment states this file's exact
#: purpose: "a checked-in MIRROR for tooling that cannot reference this assembly, not the source of
#: truth" — seedsmith is precisely that tooling (Python, no access to the C# `ZombossPatterns.All`
#: registry it mirrors). Nine real ids: three pure-posture builds plus six non-self-cancelling
#: (defence, breaks) pairs, two variants each (class-system-todo.md P7.5).
ZOMBOSS_PATTERNS_PATH = REPO_ROOT / "data" / "seed" / "zomboss" / "patterns.json"


def load_zomboss_pattern_ids() -> "frozenset[str]":
    """The legal `boss.build` vocabulary for a dungeon encounter — read fresh from the checked-in
    mirror, never hand-transcribed: `ZombossPatterns.cs`'s own set could grow past nine without this
    reader noticing unless it stays a live read of the same committed file."""
    doc = json.loads(ZOMBOSS_PATTERNS_PATH.read_text(encoding="utf-8"))
    return frozenset(e["id"] for e in doc["entries"])


#: `gk-data/packs/fusion/data/seed/creatures/_registry/families.v1.json` — a FIFTH frozen cross-program input (alongside
#: themes/motifs/atom-families/powerBand). A species-lineage grouping (`canonicalKey`+
#: `nativeLabels`, e.g. `bucket`/`cactus`/`cherry`), unrelated to a species anchor's own free-text
#: `family` array (`BloverUmbrella.family == ["aerial flora"]`, confirmed by direct read of a real
#: species file) — `retinueFamily` references THIS registry's `canonicalKey`, never a species's own
#: prose field. 19 real families, measured directly, not assumed.
CREATURE_FAMILIES_PATH = CREATURES_REGISTRY_DIR / "families.v1.json"

#: The real species corpus — `gk-data/packs/fusion/data/seed/creatures/species/**/*.json`, the SAME tree
#: `check_boss_species.py`-style direct scans already read this session. Not under
#: `CREATURES_REGISTRY_DIR` (that is frozen vocabulary files, not per-species anchors).
CREATURE_SPECIES_DIR = REPO_ROOT / "data" / "seed" / "creatures" / "species"

#: The four `threatBand` values a domain's `bossSpeciesRef` may point at (rungs 7-10,
#: `spec-domain-catalog.md` §2 row 2's own "`threatBand ≥ bossFloorRung`" — measured directly
#: against the real 10-band `creature-threat.v1.json` ladder rather than assumed as "the top few").
BOSS_FLOOR_THREAT_BAND = frozenset(_THREAT_BAND[6:])  # declaring read slice (T-2), never retyped


def load_creature_families() -> "frozenset[str]":
    """The legal `retinueFamily` vocabulary for a dungeon domain — read fresh from the creature
    program's own published family registry, never hand-transcribed (the same "second reader, never
    a second publisher" boundary `load_themes`'s own doc comment already states for its sibling)."""
    doc = json.loads(CREATURE_FAMILIES_PATH.read_text(encoding="utf-8"))
    return frozenset(doc["families"])


def load_boss_species_by_climate() -> "dict[str, frozenset[str]]":
    """Real, boss-eligible (`threatBand` in `BOSS_FLOOR_THREAT_BAND`) species ids, grouped by their
    own `elementPrimary` — the legal `bossSpeciesRef` vocabulary for a dungeon domain, PARTITIONED
    per climate cell the same way `load_grantable_atom_families` partitions atoms into
    grantable/bound. Read fresh from the real species corpus on every call — never a remembered
    count — because a re-band or a roster change moves candidates between climates, exactly the
    drift `stale_ids()` exists to catch downstream. A climate absent from the corpus (none measured
    this session, all six present) returns an empty frozenset rather than a KeyError, so a caller
    sees "zero candidates" as data, not a crash."""
    by_climate: "dict[str, set[str]]" = {}
    for path in sorted(CREATURE_SPECIES_DIR.rglob("*.json")):
        if path.name.startswith("_"):
            continue
        doc = json.loads(path.read_text(encoding="utf-8"))
        entries = doc if isinstance(doc, list) else doc.get("entries", doc.get("anchors", []))
        for entry in entries:
            if entry.get("threatBand") not in BOSS_FLOOR_THREAT_BAND:
                continue
            climate = entry.get("elementPrimary")
            species_id = entry.get("speciesId")
            if not isinstance(climate, str) or not isinstance(species_id, str):
                continue
            by_climate.setdefault(climate, set()).add(species_id)
    return {climate: frozenset(ids) for climate, ids in by_climate.items()}


# The twenty band vocabularies this registry owns (spec-dungeon-registries.md "bands.v1.json" row)
# — kept as an explicit list so a missing or an extra band in the committed file is a loud
# assertion failure in the test, never a silent `KeyError` three modules downstream.
BAND_NAMES = (
    "dangerBand", "depthBand", "widthBand", "branchiness", "density", "hazardBand", "sightBand",
    "countBand", "elementSpread", "formation", "eventKind", "outcomeOrdinal", "repeatScope",
    "entry", "phasing", "questScope", "rewardBand", "deltaBand", "hpBand", "nerveStage",
)


def load_bands() -> "dict[str, frozenset[str]]":
    """One `frozenset` of legal members per band name — the vocabulary every anchor field's enum
    is checked against. Display names are a stage-facing (delve-stage, wave 5) concern, not read
    here: this adapter cares about legal ids, never player-facing copy."""
    bands = _load("bands.v1.json")["bands"]
    return {band_name: frozenset(row["members"]) for band_name, row in bands.items()}


def load_band_display_names() -> "dict[str, dict[str, str]]":
    bands = _load("bands.v1.json")["bands"]
    return {band_name: dict(row["displayNames"]) for band_name, row in bands.items()}


def load_vocabularies() -> dict[str, "frozenset[str]"]:
    """The `RegistrySet.vocabularies` shape every other adapter exposes (`items`/`creatures`
    precedent) — one legal-id set per registry, flattened. Structured registries (room kinds,
    objective templates, interaction verbs, difficulty rungs) contribute their id set here; their
    per-row detail (flags, decision numbers, ordinals) is available from the dedicated loaders
    above for callers that need more than membership."""
    vocab: dict[str, "frozenset[str]"] = {
        "roomKind": frozenset(load_room_kinds()),
        "doorKind": frozenset(load_door_kinds()),
        "overrideTag": load_override_tags(),
        "objectiveTemplate": frozenset(load_objective_templates()),
        "difficultyRung": frozenset(load_difficulty_rungs()),
        "disposition": load_disposition(),
        "interactionVerb": frozenset(load_interaction_verbs()),
        "raidMode": load_raid_modes(),
        "theme": load_theme_ids(),
        "motif": load_motifs(),
    }
    vocab.update(load_bands())
    return vocab
