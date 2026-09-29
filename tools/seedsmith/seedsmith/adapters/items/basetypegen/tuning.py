"""seedsmith.adapters.items.basetypegen.tuning — every closed vocabulary and every numeric
resolution table a base-type generation run needs, read fresh from real registries and this
module's own tuning file. Nothing here is transcribed by hand from memory: every function reads
the live JSON on disk, the same "registry facts are read, never copied" discipline
`affixfamgen.brief` states for its own registries.

⛔ P1, restated for this corpus's own shape: `socketMax`, `implicit.powerBand` and
`enhanceTrack[].atLevel` are never authored by a model — `resolve_socket_max`,
`resolve_power_band` and `enhance_track_levels` are the only three places those numbers come from,
and all three read `gk-core/data/tuning/base-types-gen.v1.json`, never a private formula.

**The 30 role-frame taxonomy, found and cited, not re-invented** (spec-base-types-gen.md
acceptance #4): `gk-data/packs/fusion/data/seed/items/_registry/core.v1.json` → `roles.list` carries 15 `roleId` rows,
each with a `humanoidName`/`plantName`; crossed with the two body frames (`humanoid`, `plant`)
that is the 15 × 2 = 30 role-frames `authoring-fleet-plan.md` describes as *"750 identities across
30 role-frames"* and `naming.v1.json`'s own `idNamespaces.baseTypes.totalCombinations` states
verbatim: *"15 roles × 2 frames × 2 bands = 60"* (60 partitions covering the 30 role-frames, two
bands each). `commanderOnly.standard` is excluded from the 30 by the same file's own
`standardRoleNote` — it is a 31st, out-of-wave-1 role, not a hidden 16th body role.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from ..combogen.tuning import SOCKETS_PATH as SOCKETS_TUNING

REPO_ROOT = Path(__file__).resolve().parents[6]
CORE_REGISTRY = REPO_ROOT / "data" / "seed" / "items" / "_registry" / "core.v1.json"
CLASSES_REGISTRY = REPO_ROOT / "data" / "seed" / "items" / "_registry" / "classes.v3.json"
TAGS_REGISTRY = REPO_ROOT / "data" / "seed" / "items" / "_registry" / "tags.v1.json"
NAMING_REGISTRY = REPO_ROOT / "data" / "seed" / "items" / "_registry" / "naming.v1.json"
#: The sockets tuning revision is ONE constant, owned by the combogen reader and imported here
#: (strain-splice-host SSH5.6, circuit-topology §4): a second path literal here is how one generator
#: stays on an old revision. `basetypegen` never re-derives a ceiling, only reads it.
GEN_TUNING = REPO_ROOT / "data" / "tuning" / "base-types-gen.v1.json"
MILESTONES_CORPUS = REPO_ROOT / "data" / "seed" / "items" / "enhancement-milestones" / \
    "milestones.json"
BASE_TYPES_DIR = REPO_ROOT / "data" / "seed" / "items" / "base-types"

FRAMES: "tuple[str, ...]" = ("humanoid", "plant")


class UnknownRoleError(ValueError):
    """`role` is not one of `core.v1.json`'s 15 body roles (the commander-only `standard` role is
    deliberately not one of them — see this module's own docstring)."""


class TuningError(ValueError):
    """This module's own `base-types-gen.v1.json` is structurally unusable — raised at load, the
    same discipline `setgen.tuning.SetCharmTuningError` uses, so a defect lands before the first
    model call rather than on the Nth generated entry."""


@dataclass(frozen=True)
class RoleInfo:
    role_id: str
    humanoid_name: str
    plant_name: str

    def frame_role_name(self, frame: str) -> str:
        if frame == "humanoid":
            return self.humanoid_name
        if frame == "plant":
            return self.plant_name
        raise ValueError(f"frame must be 'humanoid' or 'plant', got {frame!r}")


def load_role_registry(path: "Path | None" = None) -> "dict[str, RoleInfo]":
    """`roleId -> RoleInfo` for the 15 real body roles (`core.v1.json` → `roles.list`), read fresh
    — never the 16th, commander-only `standard` row (`roles.commanderOnly`), which this generator
    does not author against (spec-base-types-gen.md's own 30-role-frame scope)."""
    doc = json.loads((path or CORE_REGISTRY).read_text(encoding="utf-8"))
    return {
        r["roleId"]: RoleInfo(role_id=r["roleId"], humanoid_name=r["humanoidName"],
                              plant_name=r["plantName"])
        for r in doc["roles"]["list"]
    }


def role_info(role: str, path: "Path | None" = None) -> RoleInfo:
    roles = load_role_registry(path)
    if role not in roles:
        raise UnknownRoleError(
            f"role {role!r} is not one of core.v1.json's 15 body roles: {sorted(roles)}")
    return roles[role]


def load_class_choices(role: str, frame: str, path: "Path | None" = None) -> "tuple[str, ...]":
    """Every class-ladder rung legal for `(role, frame)`, drawn from
    `classes.v2.json.classLadders` — a role may draw from more than one ladder (`armament-secondary`
    draws from both `weapon` and `offhand`), so this returns the UNION, in stable sorted order, of
    every ladder whose rung's `roles` list names `role`. Never hand-maintained: a role's ladder
    membership is read straight from the registry's own `roles` arrays, so a future ladder edit
    cannot drift silently out of sync with this generator's offered vocabulary.
    """
    doc = json.loads((path or CLASSES_REGISTRY).read_text(encoding="utf-8"))
    ids: "set[str]" = set()
    for ladder in doc["classLadders"].values():
        rungs = ladder.get(frame)
        if not rungs:
            continue
        for rung in rungs:
            if role in (rung.get("roles") or ()):
                ids.add(rung["id"])
    return tuple(sorted(ids))


def load_legal_implicit_families(role: str, frame: str, path: "Path | None" = None) -> "tuple[str, ...]":
    """The closed `implicit.family` vocabulary for `(role, frame)`, read from
    `classes.v3.json.implicitSlates[role].legalFamiliesByFrame[frame]` — the SAME registry
    acceptance #5 asks this generator's output to resolve against.

    ⛔ **2026-09-12 (D11 clause 1).** This used to return `classes.v2.json`'s role-wide
    `legalFamilies` for every frame. Because both frames were offered the identical set and told only
    to "pick the family that best fits", they drifted into the same picks, and D11 clause 1
    (humanoid and plant implicit sets must be DISJOINT) failed in 7 roles. The v3 registry carries a
    per-frame `legalFamiliesByFrame`, split by the rule recorded on each slate's own `splitRule`
    (humanoid = burst/offence, plant = sustain/defence — CORRELATED across every role per
    item-ideal 2f.2). The role-wide `legalFamilies` stays the union for readers that only need
    membership.

    `standard` is D14 out of scope and its two frame sets are declared IDENTICAL on purpose; the
    corpus never ships standard base types, and D11 clause 1 skips the role.
    """
    doc = json.loads((path or CLASSES_REGISTRY).read_text(encoding="utf-8"))
    slate = doc["implicitSlates"].get(role)
    if slate is None:
        raise UnknownRoleError(
            f"role {role!r} has no implicitSlates entry in classes.v3.json — known roles: "
            f"{sorted(doc['implicitSlates'])}")
    by_frame = slate.get("legalFamiliesByFrame")
    if by_frame is None:
        # Backward-compatible with a v2-shaped document (tests pass a fixture path): fall back to
        # the role-wide union rather than crash, since membership legality is unchanged.
        return tuple(slate["legalFamilies"])
    if frame not in by_frame:
        raise UnknownRoleError(
            f"frame {frame!r} has no slate for role {role!r}; frames present: {sorted(by_frame)}")
    return tuple(by_frame[frame])


def load_tag_vocab(path: "Path | None" = None) -> "tuple[str, ...]":
    doc = json.loads((path or TAGS_REGISTRY).read_text(encoding="utf-8"))
    return tuple(t["id"] for t in doc["tags"])


def load_socket_ceiling(role: str, path: "Path | None" = None) -> int:
    """Module 16's `socketCeiling(role)` (`data/tuning/sockets.v{n}.json`, the current revision) —
    this generator NEVER
    re-derives a ceiling, only reads it, per spec-base-types-gen.md's boundary that a generated
    base type must never skip `item_role_family`'s (module 8's) legality checks, of which the
    socket ceiling is one."""
    doc = json.loads((path or SOCKETS_TUNING).read_text(encoding="utf-8"))
    ceiling = doc["socketCeiling"].get(role)
    if ceiling is None:
        raise UnknownRoleError(
            f"role {role!r} has no socketCeiling row in {SOCKETS_TUNING.name} (the commander-only "
            f"`standard` role is deliberately absent there too — see that file's own "
            f"socketCeilingNote)")
    return int(ceiling)


def frame_role_name_rule(role: str, frame: str, path: "Path | None" = None) -> str:
    """`naming.v1.json`'s own `frameRoleNameRule`: the id segment is `humanoidName` on the humanoid
    frame, `plantName` on plant, VERBATIM including internal hyphens (e.g. `main-hand`, `ring-1`) —
    never the frame-neutral `roleId` itself."""
    return role_info(role, None).frame_role_name(frame)


@dataclass(frozen=True)
class GenTuning:
    """Parsed, validated view of `base-types-gen.v1.json`. One class, no silent defaults — a
    missing key raises at load rather than substituting a plausible number, mirroring
    `setgen.tuning.SetCharmGenTuning`'s own discipline."""

    socket_split: "dict[str, tuple[int, int]]"          # band -> (floorPermille, ceilingPermille)
    socket_split_default: "tuple[int, int]"
    power_band_ladder: "dict[str, tuple[str, ...]]"      # band -> cycled ladder
    power_band_ladder_default: "tuple[str, ...]"
    enhance_levels: "tuple[int, ...]"
    enhance_family_count: int

    def socket_range(self, role: str, band: str, *, ceiling: int) -> "tuple[int, int]":
        """`[lo, hi]` (inclusive) socketMax may take for `(role, band)`, given the role's own
        `ceiling` — `resolve_socket_max` is the only caller that turns this into one integer."""
        floor_pm, ceil_pm = self.socket_split.get(band, self.socket_split_default)
        import math
        lo = math.floor(ceiling * floor_pm / 1000)
        hi = math.ceil(ceiling * ceil_pm / 1000)
        hi = max(hi, lo)
        hi = min(hi, ceiling)
        return lo, hi

    def power_band_for(self, band: str, seq_index: int) -> str:
        ladder = self.power_band_ladder.get(band, self.power_band_ladder_default)
        if not ladder:
            raise TuningError(f"band {band!r} resolves to an empty powerBand ladder")
        return ladder[seq_index % len(ladder)]


def _require(doc: dict, *path: str):
    node = doc
    for key in path:
        if not isinstance(node, dict) or key not in node:
            raise TuningError(
                f"base-types-gen tuning is missing {'.'.join(path)!r} — refusing to substitute a "
                f"default; an unreviewed number here reaches every generated entry")
        node = node[key]
    return node


def load_gen_tuning(path: "Path | None" = None) -> GenTuning:
    doc = json.loads((path or GEN_TUNING).read_text(encoding="utf-8"))
    try:
        split_doc = _require(doc, "socketMaxSplit")
        default_split = _require(doc, "socketMaxSplit", "bandNotListedDefault")
        splits = {
            band: (int(row["floorPermilleOfCeiling"]), int(row["ceilingPermilleOfCeiling"]))
            for band, row in split_doc.items()
            if band not in ("description", "bandNotListedDefault") and isinstance(row, dict)
        }
        band_doc = _require(doc, "implicitPowerBandLadder")
        default_ladder = tuple(_require(doc, "implicitPowerBandLadder", "bandNotListedDefault"))
        ladders = {
            band: tuple(row) for band, row in band_doc.items()
            if band not in ("description", "bandNotListedDefault", "bandNotListedNote")
        }
        enhance_doc = _require(doc, "enhanceTrack")
        tuning = GenTuning(
            socket_split=splits,
            socket_split_default=(int(default_split["floorPermilleOfCeiling"]),
                                  int(default_split["ceilingPermilleOfCeiling"])),
            power_band_ladder=ladders,
            power_band_ladder_default=default_ladder,
            enhance_levels=tuple(int(x) for x in _require(enhance_doc, "levels")),
            enhance_family_count=int(_require(enhance_doc, "familyCount")),
        )
    except (KeyError, TypeError, ValueError) as exc:
        if isinstance(exc, TuningError):
            raise
        raise TuningError(f"base-types-gen tuning is structurally malformed: {exc}") from exc
    _validate(tuning)
    return tuning


def _validate(t: GenTuning) -> None:
    if not t.enhance_levels:
        raise TuningError("enhanceTrack.levels is empty — every base type needs at least one "
                          "enhancement milestone rung")
    if sorted(t.enhance_levels) != list(t.enhance_levels):
        raise TuningError(f"enhanceTrack.levels {list(t.enhance_levels)} is not ascending")
    if t.enhance_family_count != len(t.enhance_levels):
        raise TuningError(
            f"enhanceTrack.familyCount {t.enhance_family_count} does not match "
            f"len(levels) {len(t.enhance_levels)} — one family per rung")
    for band, (lo, hi) in t.socket_split.items():
        if not (0 <= lo <= hi <= 1000):
            raise TuningError(f"socketMaxSplit[{band!r}] = ({lo}, {hi}) is out of [0, 1000]")


def resolve_socket_max(role: str, band: str, seq_index: int, *,
                       gen_tuning: "GenTuning | None" = None,
                       sockets_path: "Path | None" = None) -> int:
    """The ONE place `socketMax` is decided — a table lookup plus a deterministic cycle over the
    resulting range, never a formula the model could have reasoned about and never random."""
    tuning = gen_tuning or load_gen_tuning()
    ceiling = load_socket_ceiling(role, sockets_path)
    lo, hi = tuning.socket_range(role, band, ceiling=ceiling)
    span = hi - lo + 1
    return lo + (seq_index % span)


def resolve_power_band(band: str, seq_index: int, *, gen_tuning: "GenTuning | None" = None) -> str:
    tuning = gen_tuning or load_gen_tuning()
    return tuning.power_band_for(band, seq_index)


def load_milestone_families(path: "Path | None" = None) -> "tuple[str, ...]":
    """Every `runtimeFamily` enhancement-milestones-gen's real corpus currently ships, sorted — the
    universe `resolve_enhance_track` draws its per-partition triple from. Reads the corpus fresh
    every call rather than caching, so a module-11 run that mints a new family is visible to the
    next base-types-gen run without a code change (acceptance #5: `enhanceTrack[].family` must
    resolve against that corpus's REAL, current content)."""
    p = path or MILESTONES_CORPUS
    if not p.exists():
        return ()
    doc = json.loads(p.read_text(encoding="utf-8"))
    return tuple(sorted({e["runtimeFamily"] for e in doc.get("entries", []) if e.get("runtimeFamily")}))


def resolve_enhance_track(role: str, frame: str, band: str, *,
                          gen_tuning: "GenTuning | None" = None,
                          milestones_path: "Path | None" = None) -> "tuple[tuple[int, str], ...]":
    """`((atLevel, family), ...)` for one partition — fixed for the whole `(role, frame, band)`
    partition (measured: every one of the 740 shipped entries in a given partition file shares one
    identical `enhanceTrack`, never varying per entry — see this package's own module docstring).
    Families are drawn from `load_milestone_families()`, deterministically, by hashing the
    partition key into the sorted family list — stable across re-runs, and it can never name a
    family the real corpus does not currently ship, which is what acceptance #5 requires.
    """
    tuning = gen_tuning or load_gen_tuning()
    families = load_milestone_families(milestones_path)
    if len(families) < tuning.enhance_family_count:
        raise TuningError(
            f"enhancement-milestones-gen's corpus ships only {len(families)} family/families; "
            f"this partition needs {tuning.enhance_family_count} distinct ones — run "
            f"enhancement-milestones-gen first (this is a HARD backfill dependency, "
            f"spec-base-types-gen.md's reference manifest)")
    import hashlib
    key = f"{role}:{frame}:{band}".encode("utf-8")
    start = int(hashlib.sha256(key).hexdigest(), 16) % len(families)
    chosen: "list[str]" = []
    i = start
    while len(chosen) < tuning.enhance_family_count:
        fam = families[i % len(families)]
        if fam not in chosen:
            chosen.append(fam)
        i += 1
    return tuple(zip(tuning.enhance_levels, chosen))
