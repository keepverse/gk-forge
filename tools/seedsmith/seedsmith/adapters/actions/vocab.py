"""seedsmith.adapters.actions.vocab — closed vocabularies transcribed from the C# code of record's
own `Name` functions (spec-corpus-loader.md §3 step 5), never from the enum member names — the
wire strings are what a loaded entry actually carries, and citing the declaration instead of the
`Name` function is the exact F10 mistake this spec's own first envelope example made ("Area" /
"Row" / "Enemy" instead of "area" / "row" / "enemy").

Every citation below was checked against the live file while this module was built (2026-09-03),
not copied from the spec's own citations — several of which point at the wrong file or a stale
line range (see corpus-loader's build report for the full corrected list; the short version: this
module's spec was written against an older `ActionEnums.cs` that was 24 lines shorter before A-E1
inserted `EligibilityScope`/`PairingRole`, and it names `RelationKind.cs` under `Actions/` when the
type actually lives in `FusionRpg.Contracts`).

`atomFamilies`/`pairedPayoffFamily`/family-scoped `scopeKey` are NOT transcribed here — they are
read fresh from the files that own them (`load_family_ids`, `load_pairing_keys`,
`load_family_map_keys`), same discipline as `adapters/items/registries.py`'s own docstring: a
registry fact is read, never re-typed, except the one C#-only fact (there is no JSON export of an
enum's `Name` switch to read instead).
"""
from __future__ import annotations

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[5]

# `REPO_ROOT`-relative joins below ask which repository actually carries the path. A prefix-keyed
# rewrite is wrong: `data`, `data/seed` and `data/seed/creatures` all resolve back to gk-forge,
# because nearest-match-wins and gk-forge owns its own generator inputs. `or REPO_ROOT` is
# load-bearing - `owning_base` returns None for a path no repository carries, where
# `content_root()` would RAISE.

from ...workspace_roots import owning_base, seed_root  # noqa: E402


def _owned(relative: str) -> "Path":
    """The repository carrying `relative`, joined to it; this one when none carries it."""
    return (owning_base(relative, REPO_ROOT) or REPO_ROOT) / relative


# ActionKinds.Name — gk-core/src/FusionRpg.Core/Actions/ActionEnums.cs:96-102 (spec cites :72-78 — stale,
# see module docstring).
ACTION_KINDS = frozenset({"basic", "innate", "skill"})

# ActionCategories.Name — ActionEnums.cs:120-128 (spec cites :96-104 — stale).
CATEGORIES = frozenset({"attack", "defense", "support", "movement", "status"})

# ActionTags.Name — ActionEnums.cs:152-163 (spec cites :128-139 — stale).
# `construct` added 2026-09-13 to match ActionEnums.cs:47-57 (`ActionTag.Construct`, shipped with
# base-defense `siege-construction`); this mirror had nine members' worth of source and only eight.
TAGS = frozenset({
    "offensive", "defensive", "heal", "buff", "debuff", "movement", "summon", "utility",
    "construct",
})

# ActionTargetModes.Name — gk-core/src/FusionRpg.Core/Actions/ActionTargetSpec.cs:103-112 (matches the
# spec's own citation exactly).
TARGET_MODES = frozenset({"self", "single", "multi", "rolledTarget", "all", "area"})

# ActionAreaShapes.Name — ActionTargetSpec.cs:134-141 (matches).
AREA_SHAPES = frozenset({"row", "column", "square", "rectangle"})

# RelationKinds.Name — gk-core/src/FusionRpg.Contracts/RelationKind.cs:21-28. The spec cites
# `.../Actions/RelationKind.cs:23-26`; the type lives in `FusionRpg.Contracts`, aliased into
# `FusionRpg.Core.Actions` by a `global using` at the top of `ActionTargetSpec.cs` — which is
# exactly why the spec's own prose elsewhere hedges with "or wherever `RelationKinds.Name` lives".
RELATIONS = frozenset({"self", "ally", "enemy", "any"})

# StatusCatalogBootstrap.RegisterAll — gk-core/src/FusionRpg.Core/Status/StatusCatalogBootstrap.cs:16-58
# (matches the spec's citation exactly — 21 Register/RegisterWithOptions calls) plus the three
# `nerve.*` ids from gk-core/data/tuning/status-catalog.v1.json (24 entries total).
#
# solid-enforcement `vocabulary-mirror` (SE2.7, 2026-09-19): this mirror was stale by three members
# (21 vs 24) — read this module's own history (this comment carried no exclusion note for `nerve.*`
# before today, and no action/status doc anywhere in the tree names a deliberate delve-only scoping
# for it either), so the gap is drift, not a design choice. Resolved `equal`, not `subset`: added the
# three ids rather than inventing an excuse for them. Verified: `guard-vocabulary-mirror.py`'s
# `action-status` pair reports zero findings against the real `status-catalog.v1.json` after this.
STATUSES = frozenset({
    "butter", "freeze", "cold", "poison", "hypno", "ember", "jala", "kelp",
    "wither", "bond", "rally", "leech", "expose", "command", "shatter", "charm_pulse",
    "blight", "rot", "spark", "pact_mark", "spore",
    "nerve.afflicted", "nerve.shaken", "nerve.unsettled",
})

# EligibilityScopes.Name — ActionEnums.cs:228-234. Not part of acceptance #6's counted list (that
# one names exactly 7 groups), kept anyway because `scope` is a required action-seed field and a
# real closed vocabulary the loader must still refuse an unknown member against.
SCOPES = frozenset({"general", "family", "species"})

# PairingRoles.Name — ActionEnums.cs:250-256. Same status as SCOPES above — `pairingRole` is
# required (F7 correction: `none` is a value, never an omission).
PAIRING_ROLES = frozenset({"none", "enabler", "payoff"})


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def load_family_ids() -> "frozenset[str]":
    """The 98 authored atom-family ids `atomFamilies` / `pairedPayoffFamily` draw from
    (`gk-data/packs/fusion/data/seed/items/affix-families/*.json`, `entries[].id`) — read fresh every call, never
    transcribed (spec-corpus-loader.md §2's "DECIDED" section; measured 2026-09-03: 15 files, 98
    entries, zero overlap with the 17 demo families under `gk-data/packs/fusion/data/seed/atoms/`).

    <para>This is the GENERATOR POOL — the set a generated action-seed may SELECT from. It stays
    affix-only: the 17 `gk-data/packs/fusion/data/seed/atoms/` families are never eligible for generation. The loader's
    ACCEPTED namespace is a wider set (see <see cref="load_accepted_family_ids"/>) because a
    hand-authored row may legitimately name an fx family; keeping the two apart is what stops the
    generator from ever emitting one (AC-F1 amendment, 2026-09-24).</para>"""
    families_dir = _owned("data/seed/items/affix-families")
    ids: set[str] = set()
    for path in sorted(families_dir.glob("*.json")):
        doc = _load_json(path)
        for row in doc.get("entries", []):
            if isinstance(row, dict) and row.get("id"):
                ids.add(row["id"])
    return frozenset(ids)


def load_fx_family_ids() -> "frozenset[str]":
    """The fx effect families (`data/seed/atoms/fx-*.json`, `entries[].family`; 16 ids) — a LIVE
    atom-registry namespace, disjoint from the 98 affix families. Read fresh, never transcribed."""
    atoms_dir = _owned("data/seed/atoms")
    ids: set[str] = set()
    for path in sorted(atoms_dir.glob("fx-*.json")):
        doc = _load_json(path)
        for row in doc.get("entries", []):
            if isinstance(row, dict) and row.get("family"):
                ids.add(row["family"])
    return frozenset(ids)


def load_accepted_family_ids() -> "frozenset[str]":
    """The full namespace an `action-seed`'s `atomFamilies` may NAME and still be accepted by the
    corpus loader: the 98 authored affix families PLUS the fx effect families.

    <para><b>AMENDED 2026-09-24 (owner decision, AC-F1).</b> The 2026-09-03 rule predates the
    shipped fx mechanic: `act.attack` (hand-authored, lawn-combat-wire owned) legitimately names
    `atom.fx-overlay-damage`, resolved at runtime through a caller-supplied lookup with no namespace
    restriction — seed and runtime agreed while the corpus loader refused. The loader now accepts
    both; the generator pool (<see cref="load_family_ids"/>) stays affix-only, so a generated row
    still never names an fx family.</para>"""
    return frozenset(load_family_ids() | load_fx_family_ids())


def load_pairing_keys() -> "frozenset[str]":
    """The payoff-family keys of `gk-data/packs/fusion/data/seed/actions/pairings.json` — the only legal values for
    `pairedPayoffFamily` (`EnablerPayoffPairings.IsPayoff`,
    `gk-core/src/FusionRpg.Core/Actions/Seeding/EnablerPayoffPairings.cs:26`). Read fresh — this loader
    must never touch that file, only read it (§4's first bullet)."""
    path = _owned("data/seed/actions/pairings.json")
    doc = _load_json(path)
    return frozenset(doc.keys())


#: SMOKE BATCH criterion-2 investigation, 2026-09-05: the three propose pipelines' own briefs list
#: `allowedAtomFamilies` as bare ids only (e.g. `atom.swiftness`), with no other signal -- measured
#: directly against real affix-family data, `atom.swiftness` is tagged `offensive` and writes the
#: `zombieSpeed` channel ("faster zombie advance"), which a model reading only the id string cannot
#: tell apart from `atom.evasion` (a `combat.dodge` channel) or `atom.quickening` (`attackInterval`)
#: -- three genuinely different mechanics that all read as "something about speed" from the id
#: alone. A real 2026-09-04 candidate ("Shift", a general repositioning action) picked
#: `{atom.swiftness, atom.tempo-surge}` in one sample and `{atom.evasion, atom.quickening}` in
#: another -- the exact ambiguity this glossary exists to close, not a hypothetical. `{value}` is
#: replaced with the literal word "X" below, never a number -- this is prose grounding read by the
#: model, not a schema change (the schema's own `enum` still lists ids only, unchanged).
_GLOSSARY_PLACEHOLDER_SUBS: "tuple[tuple[str, str], ...]" = (
    ("{value}", "X"), ("{element}", "an element"), ("{variant}", "a kind"),
    # Several later family partitions use the same display-template convention with more
    # specific tokens.  A glossary is prompt grounding, not a formatter: expose a readable
    # placeholder while never leaking template syntax to the model.
    ("{word}", "an effect"), ("{op}", "an operation"),
    ("{name}", "a name"), ("{tempo}", "tempo"),
)


def _humanize_display_template(template: "str | None") -> str:
    if not template:
        return ""
    text = template
    for token, replacement in _GLOSSARY_PLACEHOLDER_SUBS:
        text = text.replace(token, replacement)
    return text


def load_family_glossary() -> "dict[str, str]":
    """One-line, magnitude-free gloss per atom family id -- `name` + `tags` + a humanized
    `displayTemplate` -- read fresh from the identical source `load_family_ids` reads
    (`gk-data/packs/fusion/data/seed/items/affix-families/*.json`), never cached or transcribed. Exists so a propose
    pipeline's own brief can show `atom.swiftness: Swiftness [offensive] -- X faster zombie
    advance` instead of the bare id `atom.swiftness` -- see the module-level comment above for the
    real-call evidence this closes. Every one of the 98 real entries carries `name`/`tags`/
    `displayTemplate` (measured 2026-09-05: zero missing across all 15 files), so this returns one
    entry per id with no fallback path needed for a real file; a synthetic/test fixture id simply
    has no key here, and callers must treat a miss as "no gloss available", never as a defect."""
    families_dir = _owned("data/seed/items/affix-families")
    glossary: "dict[str, str]" = {}
    for path in sorted(families_dir.glob("*.json")):
        doc = _load_json(path)
        for row in doc.get("entries", []):
            if not isinstance(row, dict) or not row.get("id"):
                continue
            name = row.get("name") or row["id"]
            tags = ", ".join(row.get("tags") or ()) or "unlabeled"
            effect = _humanize_display_template(row.get("displayTemplate"))
            gloss = f"{name} [{tags}]"
            if effect:
                gloss += f" -- {effect}"
            glossary[row["id"]] = gloss
    return glossary


def load_family_map_keys() -> "frozenset[str]":
    """The family ids a `family`-scoped entry's `scopeKey` may name — the VALUES of
    `gk-data/packs/fusion/data/seed/actions/_generated/family-map.json` (species -> family id list), A-S0's projection and
    §3 step 5's eleventh vocabulary. Returns an empty set if the file is absent so a caller in a
    checkout where A-S0 has not yet run degrades to "nothing known" rather than raising — but as of
    2026-09-11 the file is live: 904 species over 227 family ids. ⛔ **RE-MEASURED 2026-09-11:** this
    docstring previously said "53 species over 19 family ids, matching the spec's measured numbers",
    which was the legacy `CreatureSpeciesCatalog.Generated.cs` projection. A species may now map to more
    than one family (626 one, 277 two, 1 three), so the value is a LIST, never a scalar."""
    path = _owned("data/seed/actions/_generated/family-map.json")
    if not path.is_file():
        return frozenset()
    doc = _load_json(path)
    family_ids: "set[str]" = set()
    for value in doc.values():
        if isinstance(value, str):
            family_ids.add(value)
        elif isinstance(value, list):
            family_ids.update(str(family_id) for family_id in value)

    # Keep previously committed family-scoped action rows loadable while the live
    # seed roster evolves its family vocabulary. This compatibility registry is
    # seed data, never a runtime or SQLite projection.
    registry_path = seed_root() / "creatures/_registry/families.v1.json"
    if registry_path.is_file():
        registry = _load_json(registry_path)
        family_ids.update(str(family_id) for family_id in (registry.get("families") or {}).keys())
    return frozenset(family_ids)
