"""seedsmith.adapters.items.setgen.emit — ids, and the one that would have shipped broken.

⛔ **A creature `themeKey` cannot go into a set id.** `naming.v1.json` (registryVersion 4, frozen) gives
sets `idTemplate: "set.{themeId}-{seq:03}"`. A creature theme key is `creature.allpeater`; substituting it
yields `set.creature.allpeater-001` — **two dots**, which fails `definitions.md` §1's grammar (the body
after the first dot is `[a-z0-9-]+`, no dot; `ContainerValidator.cs` mirrors it). Composed with
ssot-sets §4.3's tier suffix it is worse.

> **The id uses the theme's `speciesId`, never its `themeKey`.** `set.allpeater-001`, tier
> `set.allpeater-001-04`.

⚠ The zero pad on the tier suffix is load-bearing, not cosmetic — module 12 proved it at the DAL:
the actor effect list orders by `container_id ASC`, so `-02`, `-04`, `-10` sort correctly only
because they are padded. Its `ThresholdContainerIds` refuses a `set_id` ending in `-NN` for the same
reason, and this module refuses to MINT one.
"""
from __future__ import annotations

import re

#: `definitions.md` §1: one dot, then a kebab body. Deliberately anchored and deliberately strict —
#: a permissive pattern here does not reject a bad id, it makes it invisible (the exact lesson
#: `ReferenceCheck.cs`'s own underscore comment records).
CONTAINER_ID_RE = re.compile(r"^[a-z][a-z0-9]*\.[a-z0-9]+(-[a-z0-9]+)*$")

#: `naming.v1.json` `idPolicy.sequenceRange`: 001-899 is wave generation, 900-999 is reserved in
#: EVERY partition for later hand-authored corrections. A generator that mints 900+ silently eats
#: the correction range.
SEQ_MIN = 1
SEQ_MAX = 899


class IdRefused(ValueError):
    """An id this module refuses to mint, with the rule it would have broken in the message."""


def _kebab_legal(token: str) -> bool:
    return bool(re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", token))


def container_species_id(species_id: str) -> str:
    """Return the stable kebab spelling used in item container ids.

    The creature dump still contains a small legacy variant slice whose ``typeName`` uses
    underscores (for example ``BlackFootball_a``).  Those names remain the authoritative
    ``speciesId`` in the theme registry, but ``definitions.md`` permits only kebab-case in a
    container id.  Normalise that representation at the item boundary instead of rewriting
    creature identifiers or silently minting an invalid id.
    """
    token = species_id.strip().lower().replace("_", "-")
    if not _kebab_legal(token):
        raise IdRefused(
            f"speciesId {species_id!r} cannot be normalised to a kebab-case container token")
    return token


def set_id(species_id: str, seq: int, *, legacy_partitions: "frozenset[str]" = frozenset()) -> str:
    """`set.{speciesId}-{seq:03}` — never the `themeKey`."""
    if species_id.startswith(("creature.", "theme.", "build.")):
        raise IdRefused(
            f"{species_id!r} is a themeKey, not a speciesId — substituting it yields "
            f"'set.{species_id}-{seq:03}', two dots, which fails definitions.md §1's container_id "
            f"grammar. Use the theme's speciesId.")
    token = container_species_id(species_id)
    legacy_tokens = {container_species_id(partition) for partition in legacy_partitions}
    if token in legacy_tokens:
        raise IdRefused(
            f"speciesId {species_id!r} collides with a pinned legacy set partition — "
            f"naming.v1.json's five `themeIds` already own that prefix and ids are never reused")
    if not (SEQ_MIN <= seq <= SEQ_MAX):
        raise IdRefused(
            f"seq {seq} is outside 001-899; 900-999 is reserved in every partition for later "
            f"hand-authored corrections (naming.v1.json idPolicy.sequenceRange)")
    minted = f"set.{token}-{seq:03d}"
    if re.search(r"-\d{2}$", minted):
        # A three-digit seq cannot produce this today, but a two-digit one would, and the id would
        # then be indistinguishable from one of its OWN tier containers.
        raise IdRefused(
            f"{minted!r} ends in -NN and would collide with its own tier container id")
    _assert_container_grammar(minted)
    return minted


def build_set_id(aptitude: str, archetype: str, seq: int) -> str:
    """A build set's id. It has no species, so its partition is `(aptitude, archetype)` — the same
    pair its `build.` themeKey is keyed on, spelled without the prefix so the id keeps one dot."""
    partition = f"{aptitude.lower()}-{archetype.lower()}"
    if not _kebab_legal(partition):
        raise IdRefused(f"build partition {partition!r} is not kebab-legal")
    if not (SEQ_MIN <= seq <= SEQ_MAX):
        raise IdRefused(f"seq {seq} is outside 001-899")
    minted = f"set.{partition}-{seq:03d}"
    _assert_container_grammar(minted)
    return minted


def tier_container_id(set_id_value: str, pieces: int) -> str:
    """ssot-sets §4.3 — `set.{set_id}-{pieces:D2}`, and the pad is load-bearing at the DAL."""
    if not (0 < pieces < 100):
        raise IdRefused(f"pieces {pieces} does not fit a two-digit zero-padded suffix")
    minted = f"{set_id_value}-{pieces:02d}"
    _assert_container_grammar(minted)
    return minted


def charm_id(axis_group_id: str, seq: int) -> str:
    """`charm.{axisGroupId}-{seq:03}` (naming.v1.json `idNamespaces.charms`)."""
    if not _kebab_legal(axis_group_id):
        raise IdRefused(f"axisGroupId {axis_group_id!r} is not kebab-legal")
    if not (SEQ_MIN <= seq <= SEQ_MAX):
        raise IdRefused(f"seq {seq} is outside 001-899")
    minted = f"charm.{axis_group_id}-{seq:03d}"
    _assert_container_grammar(minted)
    return minted


def _assert_container_grammar(minted: str) -> None:
    if not CONTAINER_ID_RE.match(minted):
        raise IdRefused(
            f"{minted!r} fails definitions.md §1's container_id grammar "
            f"(one dot, then [a-z0-9-]+)")
    if minted.count(".") != 1:
        raise IdRefused(f"{minted!r} has {minted.count('.')} dots; the grammar allows exactly one")
