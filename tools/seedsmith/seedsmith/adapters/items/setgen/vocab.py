"""seedsmith.adapters.items.setgen.vocab — the capability and stat pick vocabularies, COUNTED.

⛔ The standing rule this program produced at plan time applies here harder than anywhere else:
**never derive a design proportion from a snapshot of a generated corpus — count it, or don't quote
it.** The capability vocabulary is the ceiling on how many genuinely different sets can exist
(ssot-sets §3.2 puts exactly one capability atom on every set, at its lowest threshold), so a
transcribed "60" that has drifted is a design conclusion drawn from a stale number.

Counted fresh from `gk-data/packs/fusion/data/seed/items/affix-families/*.json` on every call. Measured 2026-09-04:

    98 families = 42 capability + 56 stat
    capability picks : 39 element-free  +  3 x 7 variant                        =  60
    stat picks       :  2 element-free  + 31 x 7 variant  + 23 stat.modify      = 242

A family whose `variants` block says `{"generate": "elements+omni"}` expands into one pick per
element plus omni — the params are otherwise FIXED per family (`atom.venomous` is always `poison`),
so a family without that block is exactly one pick.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .tuning import SetCharmGenTuning

REPO_ROOT = Path(__file__).resolve().parents[6]

# `REPO_ROOT`-relative joins below ask which repository actually carries the path. A prefix-keyed
# rewrite is wrong: `data`, `data/seed` and `data/seed/creatures` all resolve back to gk-forge,
# because nearest-match-wins and gk-forge owns its own generator inputs. `or REPO_ROOT` is
# load-bearing - `owning_base` returns None for a path no repository carries, where
# `content_root()` would RAISE.

from ....workspace_roots import owning_base  # noqa: E402


def _owned(relative: str) -> "Path":
    """The repository carrying `relative`, joined to it; this one when none carries it."""
    return (owning_base(relative, REPO_ROOT) or REPO_ROOT) / relative

AFFIX_FAMILY_DIR = _owned("data/seed/items/affix-families")


@dataclass(frozen=True)
class FamilyPick:
    """One pick a model may make: a family, plus the variant that narrows it, if it has any."""

    family: str
    kind_id: str
    variant: "str | None"
    roles: "tuple[str, ...]"
    frames: "tuple[str, ...]"
    power_band: str

    @property
    def pick_id(self) -> str:
        return f"{self.family}.{self.variant}" if self.variant else self.family


def _elements_and_omni() -> "tuple[str, ...]":
    core = json.loads(
        (_owned("data/seed/items/_registry/core.v1.json"))
        .read_text(encoding="utf-8"))
    concrete = tuple(e["id"] for e in core["elements"]["concrete"])
    return concrete + (core["elements"]["omni"]["id"],)


def load_families(directory: "Path | None" = None) -> "list[dict]":
    """Every shipped affix-family row, read fresh. Exemplars are excluded by directory — they live
    under `_exemplars/`, which this glob never reaches (the same `IsExemplar` precedent modules 6
    and 8 established for their own checks)."""
    families: "list[dict]" = []
    for path in sorted((directory or AFFIX_FAMILY_DIR).glob("*.json")):
        doc = json.loads(path.read_text(encoding="utf-8"))
        if doc.get("kind") != "affix-family":
            continue
        families.extend(doc.get("entries", []))
    return families


def expand(entry: dict, tuning: SetCharmGenTuning,
           elements: "tuple[str, ...] | None" = None) -> "list[FamilyPick]":
    variants = entry.get("variants")
    generated = isinstance(variants, dict) and variants.get("generate") == tuning.variant_generator
    values = list(elements if elements is not None else _elements_and_omni()) if generated else [None]
    return [
        FamilyPick(
            family=entry["id"], kind_id=entry["kindId"], variant=v,
            roles=tuple(entry.get("roles") or ()),
            frames=tuple(entry.get("frames") or ()),
            power_band=entry.get("powerBand", ""),
        )
        for v in values
    ]


@dataclass(frozen=True)
class Vocabulary:
    capability: "tuple[FamilyPick, ...]"
    stat: "tuple[FamilyPick, ...]"

    @property
    def capability_count(self) -> int:
        return len(self.capability)

    @property
    def stat_count(self) -> int:
        return len(self.stat)

    @property
    def all_picks(self) -> "tuple[FamilyPick, ...]":
        """Both buckets, in load order.

        ⚠ The capability/stat split is **ssot-sets §3.2's** cut — one capability atom at a set's
        lowest threshold, stats above. A charm has no such structure, so a charm resolves a family
        id against this, never against `stat` alone; `charmgen.rules.charm_pool` then narrows it to
        what §3.6 and §3.4 leave legal.
        """
        return self.capability + self.stat

    def capability_for_roles(self, roles: "list[str] | tuple[str, ...]") -> "tuple[FamilyPick, ...]":
        """The capability picks legal on at least one of `roles`.

        This is the constraint the spec names as mitigation #2 and it is load-bearing in the other
        direction too: it is what stops the picker collapsing onto the three or four most flattering
        capabilities. A family with no `roles` list is legal everywhere — that is how the corpus
        expresses "unrestricted", not a missing field.
        """
        wanted = set(roles)
        return tuple(p for p in self.capability if not p.roles or wanted & set(p.roles))

    def stat_for_roles(self, roles: "list[str] | tuple[str, ...]") -> "tuple[FamilyPick, ...]":
        wanted = set(roles)
        return tuple(p for p in self.stat if not p.roles or wanted & set(p.roles))


def build(tuning: SetCharmGenTuning, directory: "Path | None" = None) -> Vocabulary:
    elements = _elements_and_omni()
    capability: "list[FamilyPick]" = []
    stat: "list[FamilyPick]" = []
    for entry in load_families(directory):
        kind = entry["kindId"]
        bucket = (capability if kind in tuning.capability_kinds
                  else stat if kind in tuning.stat_kinds else None)
        if bucket is None:
            # Not silently dropped: an unclassified kind means the design cut in the tuning file
            # has fallen behind the corpus, and a generator that quietly ignores a whole kind is
            # the exact "confidently wrong" shape spec-analytics §2.2 warns about.
            raise ValueError(
                f"affix family {entry['id']!r} has kindId {kind!r}, which is neither a capability "
                f"kind nor a stat kind in set-charm-gen.v1.json — classify it before generating")
        bucket.extend(expand(entry, tuning, elements))
    return Vocabulary(capability=tuple(capability), stat=tuple(stat))
