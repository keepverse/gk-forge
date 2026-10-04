"""seedsmith.adapters.creatures.family.fallback — the deterministic family repair, the sibling
`creatures/anchor/derive.py`'s `resolve_unresolved_*` family already is for threat/rarity/aptitude.

**Owner direction, 2026-09-07, verbatim: "if the LLM cannot solve it, just define a deterministic
engine to solve it."** That repaired 110 rarity values with zero model calls. This module is the same
answer for `family`, and it exists because the *other* repair shape — dropping the artefact labels —
strands species: `characteristic_pool/catalog.py` raises `species {id!r} has no family` on a species
with no live label, so removing a label that was a species' ONLY family turns a cosmetic artefact
into a hard load failure.

Returns `(value, was_deterministic)` — the same contract as every `resolve_unresolved_*` sibling, so
a caller stamps honest provenance (`deterministic-fallback`, never faked as a model judgment).

WHY THE GAME'S OWN NAME IS THE SOURCE. A family label here is a GROUPING, and the audit's own
structural test for that is "does this key ever bucket more than one thing?" — so the repair needs a
signal that is already a grouping rather than a property. Two of them exist in committed data, and
neither is authored here:

  1. The committed CamelCase `speciesId`. `PeaMine` is two words; `NutBlover` is two words. The
     capitals are the game's own record of where one creature word ends and the next begins, so this
     reads the game's taxonomy instead of inventing one. `aloe` as a species is one word carrying no
     signal, which is precisely the case that must be refused rather than guessed.
  2. The curated `families.v1.json` registry (22 ids) — this repo's own human-owned family
     vocabulary, read by the caller and passed in. It is what makes `nut` the answer for `NutTorch`
     and `NutBlover` rather than `torch`/`blover`, both of which are also real words that appear in
     other species' names and would otherwise win on a naive rule.

THE SELECTION RULE, and why each half of it is load-bearing:

  * A curated registry id among the name's tokens wins, head-most first. `IceCorn` offers both `ice`
    and `corn` and BOTH are curated — but `corn` is the head of the compound and `ice` is the
    modifier, so the head-most tiebreak is the whole difference between right and wrong. Left-most
    would give `ice`, and a bare `ice` family is this game's Ice-element bucket, which is a
    different thing from what an IceCorn is. `NutTorch` and `NutBlover` both land on `nut` here,
    not on `torch`/`blover`, and `PeaMine` on `pea`, not on the attested-but-wrong `mine`.
  * Failing that, the head-most token the corpus ALREADY groups by. Same head-most reasoning —
    `PeaMine` is a MINE that is a PEA — and iterating to the first corroborated match rather than
    taking the head unconditionally is what rescues `MiniSnowMonster`: its head `monster` groups
    nothing, and the next word `snow` groups 6.
  * Failing that: NO DERIVATION. Returns `(families, False)` and leaves the species exactly as it
    was. **A wrong family is worse than a missing one**, and the derivation must be able to say "I
    don't know" rather than damage a real entry by trying.

⛔ **A NAME-WORD FREQUENCY RULE WAS BUILT, MEASURED, AND CUT** (2026-10-04), because the measurement
is the reason it is not here. "Take the species' own name word that the most species are NAMED for"
resolves all 11 and is pure committed data — and produces `ultimate` for `UltimateCannon`,
`UltimateSwordZombie`, `UltimateBigSniper` and four more, `super` for `SuperSnowMonsterZombie`,
`doom` for `DoomTorch`, and `b` for `Submarine_B`. Those are not families; `ultimate` is precisely
the name-echo artefact class this module exists to stop, and a rule that manufactures nine of them
while fixing eleven is a net loss. Distinguishing `penguin` (a taxon, two species named for it) from
`super` (an intensifier, also two species named for it) needs to know what a word MEANS, and nothing
committed here knows that. So the frequency rule is cut and the honest "no derivation" branch below
is what those species get.
"""
from __future__ import annotations

from typing import Collection, Iterable, Mapping, Sequence

from seedsmith.ladders import carries_no_identity, carries_placeholder

__all__ = ["resolve_unresolved_family", "family_label_is_artefact", "SIDE_WORDS"]

#: Words that name the SIDE of a species, never a family. Both are large consolidated family keys in
#: this corpus (measured 2026-10-04: `plant` 391 species, `zombie` 149), which is exactly why they
#: have to be excluded by name rather than by size — the size test would pick them.
SIDE_WORDS = frozenset({"plant", "zombie"})


def family_label_is_artefact(
    label: str, *, key_owners: "Mapping[str, Collection[str]]", species_id: str,
) -> bool:
    """True when `label` cannot be a grouping: it is a capture placeholder, or a word that asserts
    no identity was captured, or a consolidated key no OTHER species lands on.

    The last clause IS the audit's own structural test — "does this key ever bucket more than one
    thing?" — and it is stated per species rather than globally so a species is never the reason its
    own family looks corroborated. It deliberately does NOT ask whether the word "looks like" a
    category: that judgement cannot be made deterministic, and it is what produced the 79 labels in
    the first place. `botanical` is a category noun and `aloe` is a taxon, and this function
    cannot tell them apart — which is exactly why it asks the corpus instead.
    """
    text = str(label)
    if carries_placeholder(text) or carries_no_identity(text):
        return True
    return len(set(key_owners.get(text, ())) - {species_id}) < 1


def resolve_unresolved_family(
    families: Sequence[str],
    *,
    species_id: str,
    name_tokens: Sequence[str] = (),
    curated_terms: Iterable[str] = (),
    key_owners: "Mapping[str, Collection[str]]" = frozenset(),  # type: ignore[assignment]
) -> "tuple[list[str], bool]":
    """A real grouping for a species whose every family label is an artefact, and
    `(families, False)` unchanged when there is none to be had.

    Fires only when EVERY label is an artefact. A species holding one real grouping is left alone —
    including a real grouping of one species, because a taxon of one is still a taxon.

    `name_tokens` is the species' own committed CamelCase `speciesId` split into words (the caller
    reads it off `_rawSpeciesId`, because `load_live_records` lower-cases the id for the canonical
    key and `peamine` is one word where `PeaMine` is two). `key_owners` is which species land on
    each consolidated key. Both are corpus-wide readings, so both are the caller's — this function
    sees one species at a time.

    Returns `(value, was_deterministic)` — `was_deterministic` is what lets the caller record that no
    model ever decided this, which is the honesty the `resolve_unresolved_*` siblings exist to keep.
    """
    current = [str(f) for f in families]
    owners = key_owners if hasattr(key_owners, "get") else {}
    if not current or not all(
            family_label_is_artefact(f, key_owners=owners, species_id=species_id)
            for f in current):
        return current, False

    curated = frozenset(curated_terms)
    tokens = [t for t in name_tokens if t and t not in SIDE_WORDS]
    if not tokens:
        return current, False

    # Head-most first among curated matches: `IceCorn` offers both `ice` and `corn` and BOTH are
    # curated, but `corn` is the head of the compound and `ice` is the modifier. Left-most would
    # give `ice`, and a bare `ice` family is this game's Ice-ELEMENT bucket — a different thing from
    # what an IceCorn is. This is the whole difference between right and wrong on that species.
    for token in reversed(tokens):
        if token in curated:
            return [token], True

    # Failing that, the head-most token some OTHER species already groups by. Same head-most
    # reasoning — `PeaMine` is a MINE that is a PEA — and iterating to the first corroborated match
    # rather than taking the head unconditionally is what rescues `MiniSnowMonster`: its head
    # `monster` groups nothing, and the next word `snow` groups 7. This is what answers
    # `PenguinZombie`, whose `penguin` is a key only `SuperPenguinZombie` lands on — one other
    # species, which is a grouping of two and not a grouping of none.
    for token in reversed(tokens):
        if set(owners.get(token, ())) - {species_id}:
            return [token], True

    return current, False
