"""seedsmith.adapters.effects.affix.derive — `affix_class` derivation from a bundle's own refs
(spec-affix-authoring.md, seed-contract.md §2.1). Mirrors `AffixValidator.AffixClassOfAtom` and its
own bundle-aggregation rule in `gk-core/src/FusionRpg.Core/Effects/Atoms/AffixValidator.cs` exactly: an atom
with no `when.trigger` is a permanent modifier and derives "prefix"; one that declares a trigger
derives "suffix"; a bundle spanning both derives "mixed" (A1 — it consumes one of each roll budget).

`affix_class` is DERIVED, never authored — P1's own boundary, restated for this content type: a
model that names its own class can contradict the bundle it just picked.
"""
from __future__ import annotations

from typing import Callable, Sequence

__all__ = ["derive_affix_class", "canonical_bundle_key"]


def derive_affix_class(atom_ids: "Sequence[str]", *, has_trigger: "Callable[[str], bool]") -> str:
    """`has_trigger` reads one atom's own `when.trigger` (never `AtomKindRegistry` — a kind that
    PERMITS a trigger is not the same as an atom that USES one, the exact distinction the C# side's
    own doc comment calls out). Raises on an empty bundle rather than guessing a default — the
    schema itself requires at least one ref, so an empty list here is a caller defect, not real
    authored content reaching this function."""
    if not atom_ids:
        raise ValueError("a bundle needs at least one atom ref to derive a class from")
    kinds = {"suffix" if has_trigger(atom_id) else "prefix" for atom_id in atom_ids}
    if len(kinds) > 1:
        return "mixed"
    return kinds.pop()


def canonical_bundle_key(atom_ids: "Sequence[str]") -> str:
    """A bundle's composition, canonicalised for `vote.resolve_vote` (which compares plain string
    equality across three samples). Sorted so the SAME set of picks in a different sampled order
    still counts as agreement — the vote is over WHICH atoms got bundled, not the order the model
    happened to list them in."""
    return ",".join(sorted(atom_ids))
