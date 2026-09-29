"""seedsmith.adapters.creatures — the creatures feature (seedsmith-map.md §3b, feature 2), wired to
`gk-data/packs/fusion/data/seed/creatures/`. spec-adapter-creatures.md.

**Done means:** `StubAdapter`-shaped, `ItemsAdapter`-sized. `channels()` is empty — creatures carry no
magnitude (rarity is a band, Theta comes from the power ladder), so `numerics` stays inert for this
feature by construction, not by convention (audit A4).
"""
from __future__ import annotations

from .kinds import KINDS, NO_GENERATOR_YET
from .registries import load_vocabularies, load_versions
from ..base import Dimension, KindSpec, RegistrySet


def _applies_to(field_name: str) -> "frozenset[str]":
    return frozenset(k.kind for k in KINDS if field_name in k.required or field_name in k.optional)


class CreaturesAdapter:
    def kinds(self) -> "list[KindSpec]":
        return list(KINDS)

    def dimensions(self) -> "list[Dimension]":
        vocab = load_vocabularies()
        return [
            Dimension(id="side", values=tuple(sorted(vocab["side"])), field="side",
                     applies_to=_applies_to("side")),
            # `rarity` and `element` are DECLARED (real, non-empty vocabularies — they are legal
            # dimensions for whatever later reads them) but `applies_to` is computed the same
            # honest way as `items` computes it: from actual KindSpec field membership, not
            # hand-asserted. Neither is a field on ANY creatures-adapter kind today — rarity lives
            # only on the catalog (§2.1: never restated on the corpus entry), and `aspect` (the
            # kind that will eventually carry element) generates nothing until aspect-scope is
            # built (audit S2). A hand-declared `applies_to` here produced a real, confirmed
            # `Coverage/PairwiseHole` false positive (side×rarity, "8 of 8 pairs never co-occur")
            # on the very first `check` run against the live corpus — the exact "confidently
            # wrong" trap `adapters/items/__init__.py` already documents avoiding for `class`.
            # `PairwiseHole`'s own docstring is explicit that an empty `applies_to` intersection is
            # SKIPPED, not reported as 100% missing — that is the correct behavior here, and this
            # comment is the citation for why `_applies_to()` is used unconditionally below.
            Dimension(id="rarity", values=tuple(sorted(vocab["rarity"])), field="rarity",
                     applies_to=_applies_to("rarity")),
            Dimension(id="element", values=tuple(sorted(vocab["element"])), field="element",
                     applies_to=_applies_to("element")),
            # `family` DECLARED with EMPTY values in D1 (spec §2.4) — no candidate has been
            # extracted yet (D2). Partitioning falls back to side/rarity honestly rather than the
            # adapter claiming a grouping it cannot supply. NOT omitted: an omitted dimension and
            # an empty one report differently to a reader checking "does this feature have a
            # family axis at all", and the answer here is "yes, not yet populated" — a fact worth
            # keeping visible. Safe from the same PairwiseHole trap regardless of `applies_to`:
            # `values=()` makes `required` empty in the metric, so it self-skips either way.
            Dimension(id="family", values=tuple(sorted(vocab["family"])), field="family",
                     applies_to=_applies_to("family")),
        ]

    def legal_combinations(self):
        def _legal(dim_a: str, val_a: str, dim_b: str, val_b: str) -> bool:
            paired = {dim_a: val_a, dim_b: val_b}
            if set(paired) == {"element", "rarity"} and paired.get("element") == "omni":
                # Real, verifiable fact, not an invented example (unlike the mechanism-only pair
                # `_stub` uses): CreatureSpeciesGenerator.cs draws ElementPrimary only from
                # `ElementRoster.Concrete` (fire/ice/air/earth/light/dark), which excludes omni —
                # no creature of ANY rarity can ever have ElementPrimary=omni. `omni` still belongs
                # in the `element` registry vocabulary (it is a legal value for OTHER systems),
                # which is exactly why this needs a real legality rule rather than just dropping
                # the value from the vocabulary.
                return False
            return True
        return _legal

    def registries(self) -> RegistrySet:
        return RegistrySet(vocabularies=load_vocabularies(), versions=load_versions())

    def channels(self):
        # Deliberately empty (§2.6, audit A4): rarity is a band, Theta comes from the power
        # ladder, and generated creature content carries no numbers at all. `numerics` is consumed
        # only via `adapter.channels()` — an empty list makes "never a number" structural for this
        # feature rather than a rule someone has to remember to follow.
        return []
