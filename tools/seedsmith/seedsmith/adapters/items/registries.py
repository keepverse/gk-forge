"""seedsmith.adapters.items.registries — reads `gk-data/packs/fusion/data/seed/items/_registry/*.json` fresh on every
call. Registry facts are read, never transcribed (tasks/seedsmith-plan.md verification
discipline) — the one exception is the allocated-partitions ledger, which is a DERIVED fact
sourced from `gk-forge/tools/ItemSeedValidator --list-partitions` (see `_registry_snapshot/`'s own
docstring for why that one is snapshotted rather than re-read live).
"""
from __future__ import annotations

import json
from pathlib import Path

from ...workspace_roots import owning_base  # noqa: E402

# `data/seed/**` is the CONTENT PACK's tree - gk-data/packs/fusion/data/seed - and gk-forge owns the
# GENERATOR, not the corpus. The split left generator inputs beside their generator, so a path walked
# up from this file lands on gk-forge and every registry read asked gk-forge/data/seed/items/_registry,
# a directory that does not exist. Measured, not assumed: owning_base() answers for this relative path
# and returns the pack; root_carrying() does NOT, because an ancestor walk reaches the workspace root,
# which does not carry data/seed; and content_root() RAISES for a temp directory, which these modules
# are imported by way of. `or REPO_ROOT` keeps that case working, which is what a non-raising lookup
# buys.
REPO_ROOT = Path(__file__).resolve().parents[5]


def _seed_root(relative: str) -> "Path":
    """The repository carrying `relative`, falling back to this one when none does."""
    return (owning_base(relative, REPO_ROOT) or REPO_ROOT) / relative
REGISTRY_DIR = _seed_root("data/seed/items/_registry")
SNAPSHOT_PATH = Path(__file__).resolve().parent / "_registry_snapshot" / "allocated_partitions.json"

_REGISTRY_FILES = ("bands.v1.json", "core.v1.json", "naming.v1.json", "tags.v1.json",
                   "classes.v1.json", "themes.v1.json", "words.v1.json")


def _load(name: str) -> dict:
    path = REGISTRY_DIR / name
    return json.loads(path.read_text(encoding="utf-8"))


def load_versions() -> dict[str, int]:
    """`registryVersion` per file, read fresh — not hardcoded. Measured 2026-08-23: naming and
    tags are at v4, classes at v3, the rest at v1 — a single assumed constant would already be
    wrong for half of them."""
    return {name.removesuffix(".v1.json"): _load(name)["registryVersion"]
           for name in _REGISTRY_FILES}


def load_theme_keys() -> frozenset[str]:
    """`themeKey`'s legal vocabulary — a UNION of two append-only populations that cannot collide
    by construction (spec-creature-themes.md §2.2a, resolving audit S5): legacy `theme.*` ids, human-
    authored and frozen in `themes.v1.json` (13 registered, 5 currently referenced by 38 real
    entries — measured 2026-08-31), and `creature.*` ids the creatures feature publishes at runtime.

    This is the ONE file outside `adapters/creatures/` the creatures feature is allowed to touch
    (spec-adapter-creatures.md's own single exception) — it adds a VOCABULARY, not a concept: this
    module still knows nothing about what a creature is, only that `creature.`-prefixed strings are now
    legal `themeKey` values. Creature themes are not loaded from a committed file here (none is
    committed yet — see the creatures feature's own build notes); a caller with a live creature theme
    registry unions its keys in via `creature_theme_keys`.

    ⭐ **A THIRD population landed 2026-09-04 (item module 13, `set-charm-gen`): `build.*`.** A
    `set` REQUIRES a `themeKey` (`kinds.py`'s own spec, mirroring `KindCatalog.cs`), and the 36
    build set families are keyed on `(aptitude, archetype)` and belong to no species — so without
    it a build set is unauthorable. Ruled as a third append-only namespace rather than a loosened
    `themeKey`, because `spec-creature-themes.md` §7 names making it *required* on `unique` as the
    intended direction and loosening it here would reverse that. Collision-free against `theme.*`
    and `creature.*` by construction, exactly the namespace split §2.2a already established.
    """
    legacy = frozenset(f"theme.{t['id']}" for t in _load("themes.v1.json")["themes"])
    build = frozenset(row["themeKey"] for row in _load("build-themes.v1.json")["themes"])
    return legacy | build


def load_vocabularies(
    *, creature_theme_keys: "frozenset[str] | None" = None,
) -> dict[str, frozenset[str]]:
    core = _load("core.v1.json")
    tags = _load("tags.v1.json")
    classes = _load("classes.v1.json")

    roles = frozenset(r["roleId"] for r in core["roles"]["list"])
    commander_roles = frozenset(r["roleId"] for r in core["roles"]["commanderOnly"])
    elements = frozenset(e["id"] for e in core["elements"]["concrete"]) | {core["elements"]["omni"]["id"]}
    rarities = frozenset(r["id"] for r in core["rarity"]["ladder"])
    tag_ids = frozenset(t["id"] for t in tags["tags"])
    # NOT `classLadders.keys()` (armour/weapon/offhand/jewel/standard) — those are LADDER names,
    # never a literal `class` field value. A base-type's real `class` value is a per-frame rung
    # id nested two levels down (classLadders[ladder][frame][i].id, e.g. "cloth", "leather") —
    # found only by loading a real entry and checking (base-types/footing/humanoid/a.json has
    # class="cloth"), after the ladder-name version produced a 100%-missing pairwise finding for
    # every (dimension, class) pair — a confidently wrong metric, not a real gap.
    class_values = frozenset(
        rung["id"]
        for ladder in classes["classLadders"].values()
        for frame_key in ("humanoid", "plant")
        for rung in ladder.get(frame_key, [])
    )

    snapshot = json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))
    partitions = frozenset(snapshot["partitionKind"].keys())
    power_band = frozenset(_load("bands.v1.json")["powerBand"]["enum"])

    return {
        "role": roles | commander_roles,
        "frame": frozenset({"humanoid", "plant", "hybrid"}),
        "band": frozenset({"a", "b"}),
        "powerBand": power_band,
        "element": elements,
        "rarity": rarities,
        "tags": tag_ids,
        "class": class_values,
        "partitions": partitions,
        "themeKey": load_theme_keys() | (creature_theme_keys or frozenset()),
    }


def partition_kind_map() -> dict[str, str]:
    snapshot = json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))
    return dict(snapshot["partitionKind"])


def load_omni_element_id() -> str:
    """`core.v1.json`'s own `elements.omni.id` — the additive baseline, never a concrete element.
    Legal as an `element` value (a family whose `variants.generate` is `"elements+omni"` produces
    one variant per concrete element PLUS this one), but never legal as a socket `affinityElement`
    (a socket affinity must be a concrete element a gem can match against). Callers that need to
    keep the two apart (gemgen) read this instead of hardcoding the literal `"omni"`."""
    return str(_load("core.v1.json")["elements"]["omni"]["id"])


def load_concrete_element_ids() -> "frozenset[str]":
    """`core.v1.json`'s `elements.concrete` ids only — excludes `omni`. The set a socket
    `affinityElement` must be drawn from."""
    return frozenset(e["id"] for e in _load("core.v1.json")["elements"]["concrete"])


def load_tag_axes(*, applies_to: "str | None" = None) -> "dict[str, tuple[str, ...]]":
    """`tags.v1.json`'s `axes`/`tags` arrays, grouped back to `axis id -> member tag ids` --
    `load_vocabularies()["tags"]` flattens every axis into one set, which loses exactly the
    grouping a caller needs to enforce an `exclusive: true` axis (e.g. `unique.tags` needing
    "exactly one mass-class", spec-unique-pipeline.md §1). `applies_to` filters to axes whose
    `appliesTo` list names that entry shape (e.g. `"unique"`); `None` returns every axis."""
    tags = _load("tags.v1.json")
    by_axis: "dict[str, list[str]]" = {}
    axis_applies: "dict[str, list[str]]" = {a["id"]: a.get("appliesTo", []) for a in tags["axes"]}
    for row in tags["tags"]:
        by_axis.setdefault(row["axis"], []).append(row["id"])
    return {
        axis: tuple(sorted(ids))
        for axis, ids in by_axis.items()
        if applies_to is None or applies_to in axis_applies.get(axis, ())
    }


def tag_axis_violation(tags: "list[str] | tuple[str, ...]",
                       tag_axes: "dict[str, tuple[str, ...]]", *,
                       non_exclusive: "frozenset[str]" = frozenset()) -> "str | None":
    """`tags.v1.json`'s own per-axis exclusivity rule: at most one tag from an axis grouping (as
    `load_tag_axes` returns it) may appear together on one entry. The JSON Schema's flat `enum`
    list can restrict which STRINGS are legal but not "at most one from this subset, for N
    different subsets, in one array field" -- a model can satisfy the schema while still violating
    this rule (the exact gap `ItemSeedValidator`'s `TagAxisExclusive` check catches after the fact;
    this is the same rule enforced BEFORE a bad answer is ever assembled into an entry).

    Extracted from `uniques.pipelines._tag_axis_violation` (item-seed-regen cause 8, 2026-09-20) so
    `basetypegen`/`affixfamgen` share this exact check rather than each re-deriving it -- `uniques`'s
    own copy keeps its kind-specific "exactly one mass-class" requirement layered on top of this.
    `non_exclusive` names an axis `tag_axes` groups but `tags.v1.json` itself marks
    `exclusive: false` for the calling kind (`load_tag_axes` drops that flag on purpose, so a caller
    that can legally carry more than one tag from such an axis must say so explicitly here, rather
    than this function guessing). Returns the violation reason, or `None` when clean.
    """
    tag_to_axis = {t: axis for axis, ids in tag_axes.items() for t in ids}
    seen_per_axis: "dict[str, str]" = {}
    for tag in tags:
        axis = tag_to_axis.get(tag)
        if axis is None or axis in non_exclusive:
            continue
        if axis in seen_per_axis and seen_per_axis[axis] != tag:
            return f"more than one {axis} tag: {seen_per_axis[axis]!r} and {tag!r}"
        seen_per_axis[axis] = tag
    return None


def tag_axis_brief_note(applies_to: str) -> str:
    """The prose form of `tag_axis_violation`'s rule, for embedding directly in a model-facing
    brief — a flat `enum` tag list cannot itself say "at most one from this subset, for N
    different subsets", so a brief that only prints the tag list (every sibling module's
    original shape) never tells the model this rule exists at all. Shared by every brief that
    asks a model to pick `tags` for a kind `load_tag_axes` covers (item-seed-regen cause 8,
    2026-09-20). Empty string when the kind has no exclusive axis to state."""
    axes = load_tag_axes(applies_to=applies_to)
    if not axes:
        return ""
    lines = "\n".join(f"  - {axis}: pick AT MOST ONE of {', '.join(members)}"
                      for axis, members in sorted(axes.items()))
    return ("Some tags belong to a closed, mutually-exclusive group — pick at most one member of "
            f"each group below (never two from the same group):\n{lines}")


ATOMS_DIR = _seed_root("data/seed/atoms")


def load_atom_families() -> frozenset[str]:
    """`unique.fixedAtoms[].family` / `unique.varianceSlot.family`'s real VALIDATED vocabulary
    (spec-unique-pipeline.md §1). The one function in this module that reads OUTSIDE
    `gk-data/packs/fusion/data/seed/items/_registry/` -- deliberately, mirroring `load_theme_keys`'s own precedent of
    a single named exception rather than pretending the boundary is absolute: no atom-specific
    seedsmith adapter exists to own this loader instead, and `unique` is the only items kind that
    references the atom catalog by family id at all (D4.24's own finding: 144 unique anchors name
    68 families against a catalog of far fewer real ones -- reading this fresh, never
    hand-transcribing it, is exactly the discipline that finding depends on to stay true as the
    catalog grows, e.g. D4.26's `atom.extend-slot` landing the same session D4.24 counted 28)."""
    families: "set[str]" = set()
    for path in sorted(ATOMS_DIR.rglob("*.json")):
        doc = json.loads(path.read_text(encoding="utf-8"))
        for entry in doc.get("entries") or ():
            family = entry.get("family")
            if isinstance(family, str):
                families.add(family)
    return frozenset(families)


AFFIX_FAMILIES_DIR = _seed_root("data/seed/items/affix-families")


def load_materialised_affix_family_ids() -> "frozenset[str]":
    """The authored affix families `FamilyExpansion.Expand` ACTUALLY materialises — authored ids
    intersected with the families present in `gk-data/packs/fusion/data/seed/atoms/generated/**` (`gk-forge/tools/FamilyExpandGen`'s
    committed output).

    ⛔ **Why this is not `load_authored_affix_family_ids()`.** That loader returns every authored
    family id, but the expansion REFUSES some of them by name (a bare `status.<family>` stem, no
    `BattleRuleset` curve for a channel, no E30 pool, an op `Replace`/`Flag` excluded by principle, no
    `referenceBaseGameUnits`). A refused family has no atom, so a combination that GRANTS it passes
    `ReferenceCheck` (which resolves against authored affix entries) and then cannot build its
    container at boot — a word that visibly fires and does nothing (strain-splice-host SSH4.4).
    Measured 2026-09-22: 144 authored families read, 70 refused, and 10 of the refused ones carried 69
    grants across 63 shipped corpus entries.

    An intersection, not `load_atom_families()`: that broader loader also carries hand-authored
    sources no affix family has (`atom.aura-*`, `atom.fx-*`, `patron-aura`, `trait-critical-hunter`,
    `extend-slot`), which `ReferenceCheck` refuses — SSH2.5's own live defect."""
    materialised: "set[str]" = set()
    for path in sorted((ATOMS_DIR / "generated").glob("*.json")):
        doc = json.loads(path.read_text(encoding="utf-8"))
        for entry in doc.get("entries") or ():
            family = entry.get("family")
            if isinstance(family, str):
                materialised.add(family)
    return frozenset(load_authored_affix_family_ids() & materialised)


def load_authored_affix_family_ids() -> "frozenset[str]":
    """Every family id actually AUTHORED in `gk-data/packs/fusion/data/seed/items/affix-families/*.json` — the set a
    unique's `fixedAtoms[]`/`varianceSlot` family can reference and have it actually RESOLVE
    (`ReferenceCheck.ResolveReference` looks it up in `ctx.ById`, populated from authored entries),
    unlike `load_atom_families()`'s broader runtime atom catalog under `gk-data/packs/fusion/data/seed/atoms/**` (which
    names many families no items-side content has authored yet — this repo's own prior finding,
    "144 unique anchors name 68 atom families, the real catalog has only 28"). A repair that offers
    a runtime-catalog-only family as a replacement mints a NEW `ReferenceUnresolved` finding instead
    of fixing one (item-seed-regen cause 8, 2026-09-20: found live when two of four
    UniqueFrameImpossible repairs picked exactly such a family)."""
    ids: "set[str]" = set()
    for path in sorted(AFFIX_FAMILIES_DIR.glob("*.json")):
        doc = json.loads(path.read_text(encoding="utf-8"))
        for row in doc.get("entries") or ():
            fam_id = row.get("id")
            if isinstance(fam_id, str):
                ids.add(fam_id)
    return frozenset(ids)


def load_atom_family_frames() -> "dict[str, frozenset[str]]":
    """familyId -> the frames that family may sit on, read from
    `gk-data/packs/fusion/data/seed/items/affix-families/*.json`'s own `frames` array -- the EXACT source
    `UniqueFrameCheck.cs` checks a unique's `fixedAtoms[].family`/`varianceSlot.family` against
    (ssot-uniques.md §3.5's physics carve-out: "a channel that only exists on the other side" is a
    dead line, not a daring one). Deliberately NOT `gk-data/packs/fusion/data/seed/atoms/**`
    (`load_atom_families()`'s own source) -- that answers a different question, "does this family
    exist in the real atom catalog", not "which frames can it sit on". A family absent from this
    map has no frame restriction, matching the C# check's own "a family with no frames list ... is
    skipped" rule (item-seed-regen cause 8, 2026-09-20)."""
    frames: "dict[str, set[str]]" = {}
    for path in sorted(AFFIX_FAMILIES_DIR.glob("*.json")):
        doc = json.loads(path.read_text(encoding="utf-8"))
        for row in doc.get("entries") or ():
            fam_id, fam_frames = row.get("id"), row.get("frames")
            if isinstance(fam_id, str) and isinstance(fam_frames, list) and fam_frames:
                frames.setdefault(fam_id, set()).update(f for f in fam_frames if isinstance(f, str))
    return {k: frozenset(v) for k, v in frames.items()}


# The one fact in this module transcribed rather than parsed: "hybrid drops these roles, and
# the commander never wears this frame" lives only inside core.v1.json's frame vocabulary as
# free-text prose (its `meaning` string for the "hybrid" entry), not a structured field —
# unlike everything else here, there is no key to read it from. `HYBRID_FRAME_CITATION` is the
# exact source sentence; `test_items_adapter.py` asserts it is still substring-present in the
# live registry, so a future registry edit that changes this rule cannot silently drift away
# from what this module assumes without a test noticing.
HYBRID_FRAME_CITATION = (
    "a chimera body combining both natures. Carries 12 of the 15 roles "
    "(drops ward-array, head-guard and sense); each remaining role accepts a base type from either "
    "pure frame's ladder. The commander never wears this frame — it takes humanoid or plant only."
)

# D30 (2026-09-04, core.v1.json registryVersion 2): D3 wins over the prior 13-role/895‰ shape this
# constant used to name. jewel-minor-b is now hybrid-eligible; head-guard and sense are not.
HYBRID_FRAME_EXCLUDED_ROLES = frozenset({"ward-array", "head-guard", "sense"})
COMMANDER_ROLE = "standard"
