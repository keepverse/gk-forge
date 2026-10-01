"""seedsmith.adapters.trees.plan.vocabulary — the §6 thirteen-axis property vocabulary and the
`roster` block (spec-tree-plan.md §6, task B1).

Two refusals, both load-bearing (spec-tree-plan.md §6):
  - No axis lists its own members in code or in a tuning file. Every count is read and counted at
    load, from a roster mirror or the shipped registries — never typed as a literal.
  - A missing mirror is EXIT_CANNOT_RUN naming the file, never an empty axis (T5's rule applied to
    rosters: a default is a value nobody chose that behaves like one somebody did).
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[6]

# `data/seed/**` is gk-data's content pack, not gk-forge's, and the DIRECTORY cannot be resolved.
# `owning_base` answers by testing `(base / rel).exists()`, so a directory answers unreliably: gk-forge
# tracks ZERO files under data/ but holds an untracked `data/seed/creatures/` of three files, and that
# alone is enough for it to claim `data/seed`. So every site below resolves the FILE it wants through
# `owned_path` - a closed value it already had - and no directory is left to misattribute. Measured:
#
#     owning_base("data/seed")                                  -> gk-forge   wrong
#     owning_base("data/seed/passive-tree/plan/might.v1.json")    -> gk-data     right
#
# An explicit `seed_root` still short-circuits: a caller that supplies one is stating where the data
# is - a fixture, a disposable pack - and must not be overridden.

from ....workspace_roots import owned_path  # noqa: E402



def _seed_root(seed_root: "Path | None" = None) -> "Path":
    """`data/seed`, located through a FILE the pack really carries rather than asked about directly.

    `owned_path("data/seed/aptitudes/roster.json", REPO_ROOT)` resolves the exact file, and `data/seed` is
    its grandparent. Anchoring on a file is what makes this correct: `owning_base` tests existence, so
    `data/seed` alone answers "gk-forge" - gk-forge tracks nothing under data/ but holds an untracked
    `data/seed/creatures/` of three files, and that is enough for the resolver to claim it.

    A caller-supplied `seed_root` wins, because a fixture or a disposable pack is stating where the data is.
    """
    if seed_root is not None:
        return seed_root
    return owned_path("data/seed/aptitudes/roster.json", REPO_ROOT).parent.parent

class VocabularyError(ValueError):
    """EXIT_CANNOT_RUN — a roster mirror is missing or unreadable. Never an empty axis."""


def _read_json(path: Path) -> dict:
    if not path.exists():
        raise VocabularyError(f"missing roster mirror: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as ex:
        raise VocabularyError(f"{path} did not parse: {ex}") from ex


@dataclass(frozen=True)
class Roster:
    """The `roster.*` block of the plan schema (spec-tree-plan.md's frozen-fields table):
    `roster.aptitudes[]` / `.elements[]` / `.statuses[]` and `roster.counts`, read from mirrors."""
    aptitudes: "tuple[str, ...]"
    elements: "tuple[str, ...]"
    statuses: "tuple[str, ...]"

    @property
    def counts(self) -> dict:
        return {
            "aptitudes": len(self.aptitudes),
            "elements": len(self.elements),
            "statuses": len(self.statuses),
        }


def load_family_roster_or_pending(seed_root: "Path | None" = None) -> "tuple[tuple[str, ...], bool]":
    """`roster.creatureFamilies[]` (spec-tree-plan.md's frozen schema table) — UNLIKE `aptitudes`/
    `elements`/`statuses`, an absent family mirror is not `EXIT_CANNOT_RUN`: task C1's own acceptance
    bullet 9 requires a manifest missing the family roster to emit `_pending: ["creatureFamilies"]`
    instead, so `F = 0` is visible rather than silent. Returns `(families, pending)` — `pending`
    is `True` only when the mirror file itself is missing (a malformed one still raises, same as
    every other roster read, since that is a real data defect and not a declared absence).

    Reads `gk-data/packs/fusion/data/seed/creatures/_registry/families.v1.json`'s `families` map, keyed by canonical key —
    the same registry the creature program already ships (19 entries as of 2026-09)."""
    root = _seed_root(seed_root)
    path = root / "creatures" / "_registry" / "families.v1.json"
    if not path.exists():
        return (), True
    doc = _read_json(path)
    families = tuple(sorted(doc["families"].keys()))
    return families, False


def load_roster(seed_root: "Path | None" = None) -> Roster:
    root = _seed_root(seed_root)
    aptitude_doc = _read_json(root / "aptitudes" / "roster.json")
    element_doc = _read_json(root / "elements" / "roster.json")
    status_doc = _read_json(root / "statuses" / "roster.json")

    aptitudes = tuple(sorted((e["id"] for e in aptitude_doc["entries"]), key=lambda x: x))
    aptitude_ordered = tuple(e["id"] for e in sorted(aptitude_doc["entries"], key=lambda e: e["ordinal"]))
    elements = tuple(e["id"] for e in sorted(element_doc["entries"], key=lambda e: e["ordinal"]))
    statuses = tuple(sorted(e["id"] for e in status_doc["entries"]))
    return Roster(aptitudes=aptitude_ordered, elements=elements, statuses=statuses)


@dataclass(frozen=True)
class PropertyVocabulary:
    """The §6 thirteen axes. `members` holds each axis's legal values where they are enumerable as
    strings; `count` is always present and always READ, never typed (the acceptance bar this class
    exists to satisfy)."""
    axes: "dict[str, tuple[str, ...]]"  # axis id -> ordered member ids (or synthetic ids for numeric axes)
    counts: "dict[str, int]"

    def member_count(self, axis: str) -> int:
        if axis not in self.counts:
            raise VocabularyError(f"unknown property vocabulary axis '{axis}'")
        return self.counts[axis]


# The four fixed, closed enums that are NOT registry-driven (spec-tree-plan.md §6) — these are
# design-law closed sets stated directly in the spec, not read from a mirror, so they are the one
# place a literal member list is legitimate. `posture` IS registry-driven (aptitudes/roster.json's
# own `posture` field) and is therefore excluded from this constant.
NODE_CLASS = ("mechanism", "magnitude")
BRANCH = ("offensive", "defensive")
CONVERSION_STATE = ("converted", "unconverted")
EXCLUSION_FORM = ("reroute", "precedence", "nullification")


def load_property_vocabulary(tier_count: int, seed_root: "Path | None" = None) -> PropertyVocabulary:
    root = _seed_root(seed_root)
    roster = load_roster(root)

    aptitude_doc = _read_json(root / "aptitudes" / "roster.json")
    postures = tuple(sorted({e["posture"] for e in aptitude_doc["entries"]}))

    atom_vocab = _read_json(root / "passive-tree" / "vocabulary.json")
    attach_points = tuple(sorted(atom_vocab["attachPoints"]))
    kinds = tuple(sorted(k["id"] for k in atom_vocab["kinds"]))
    triggers = tuple(sorted(t["id"] for t in atom_vocab["triggers"]))
    authorable_triggers = tuple(sorted(t["id"] for t in atom_vocab["triggers"] if t["authorable"]))

    catalog = _read_json(root / "derived-stats" / "catalog.json")
    channel_families = tuple(sorted(e["family"] for e in catalog["entries"]))

    axes = {
        "nodeClass": NODE_CLASS,
        "branch": BRANCH,
        "tier": tuple(str(t) for t in range(1, tier_count + 1)),
        "posture": postures,
        "aptitude": roster.aptitudes,
        "element": roster.elements + ("omni",),
        "status": roster.statuses,
        "atomAttachPoint": attach_points,
        "atomKind": kinds,
        "atomTrigger": triggers,
        "channelFamily": channel_families,
        "conversionState": CONVERSION_STATE,
        "exclusionForm": EXCLUSION_FORM,
    }
    counts = {axis: len(members) for axis, members in axes.items()}
    # authorable trigger count is reported separately — spec-tree-plan.md §6's own row reads
    # "13 (11 authorable)", both numbers meaningful and neither typed here.
    counts["atomTriggerAuthorable"] = len(authorable_triggers)
    return PropertyVocabulary(axes=axes, counts=counts)
