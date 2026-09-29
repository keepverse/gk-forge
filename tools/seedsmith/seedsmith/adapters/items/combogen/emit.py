"""seedsmith.adapters.items.combogen.emit — ids, min tiers, min sockets.

**D27 gives combinations the `combo` container kind** — "the 25 generated resonances AND the 102
Strains/Splices" — so the lane's `gem.combo-*` / `gem.word-*` spelling is retired here as well as in
module 16's `ResonanceGenerator`. `definitions.md` §1 forces the prefix to match the kind.

```text
combo.strain-{aptitude}-{archetype}     combo.strain-might-offense      36
combo.splice-{aptitudeA}-{aptitudeB}    combo.splice-might-agility      66  -- pair sorted by
                                                                            -- Aptitude ordinal
```

⭐ **Sorting the pair by ordinal at MINT time is what makes a Splice unordered by construction.** A
uniqueness check would only discover `(Might, Agility)` and `(Agility, Might)` after both had been
generated — 66 rows late, and one of them a wasted call.

⚠ There is no `{seq:03}` here, and that is deliberate: a Strain's identity is its grid cell, not its
position in a wave. Two runs over the same grid mint the same 102 ids, which is what makes
`re_running_over_an_unchanged_grid_is_byte_identical` true rather than aspirational.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .grid import Cell, scan_for_banned_word
from .tuning import ComboTuning

#: `definitions.md` §1: one dot, then a kebab body. Anchored and strict on purpose — a permissive
#: pattern does not reject a bad id, it makes it invisible.
CONTAINER_ID_RE = re.compile(r"^[a-z][a-z0-9]*\.[a-z0-9]+(-[a-z0-9]+)*$")

CONTAINER_PREFIX = "combo"


class IdRefused(ValueError):
    """An id this module refuses to mint, with the rule it would have broken in the message."""


def _kebab_legal(token: str) -> bool:
    return bool(re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", token))


def _assert_container_grammar(minted: str) -> None:
    if minted.count(".") != 1:
        raise IdRefused(f"{minted!r} has {minted.count('.')} dots; the grammar allows exactly one")
    if not CONTAINER_ID_RE.match(minted):
        raise IdRefused(
            f"{minted!r} fails definitions.md §1's container_id grammar (one dot, then [a-z0-9-]+)")
    banned = scan_for_banned_word(minted)
    if banned:
        raise IdRefused(f"{minted!r} contains {banned} — ⛔ D20 bans that word outright")


def strain_id(aptitude_token: str, archetype: str) -> str:
    for token, label in ((aptitude_token, "aptitude"), (archetype, "archetype")):
        if not _kebab_legal(token):
            raise IdRefused(f"{label} token {token!r} is not kebab-legal; it cannot enter an id")
    minted = f"{CONTAINER_PREFIX}.strain-{aptitude_token}-{archetype}"
    _assert_container_grammar(minted)
    return minted


def splice_id(lo_token: str, lo_ordinal: int, hi_token: str, hi_ordinal: int) -> str:
    """The pair, sorted by shipped ordinal. Passing them the wrong way round mints the same id."""
    if lo_ordinal == hi_ordinal:
        raise IdRefused(
            f"a Splice joins two DIFFERENT aptitudes; both sides carry ordinal {lo_ordinal}")
    a, b = ((lo_token, hi_token) if lo_ordinal < hi_ordinal else (hi_token, lo_token))
    for token in (a, b):
        if not _kebab_legal(token):
            raise IdRefused(f"aptitude token {token!r} is not kebab-legal; it cannot enter an id")
    minted = f"{CONTAINER_PREFIX}.splice-{a}-{b}"
    _assert_container_grammar(minted)
    return minted


def combo_id(cell: Cell) -> str:
    if cell.combination_kind == "strain":
        return strain_id(cell.aptitudes[0].token, cell.archetype or "")
    lo, hi = cell.aptitudes
    return splice_id(lo.token, lo.ordinal, hi.token, hi.ordinal)


def name_key(cell: Cell) -> str:
    """The localisation key. `combo.strain-might-offense` is a container id, not a name key, so the
    key gets its own `combination.` namespace and the same grid-derived body."""
    return f"combination.{cell.combination_kind}-{cell.key}"


@dataclass(frozen=True)
class IngredientRow:
    """One `socket_combo_ingredient` row — D41's multiset entry. ⛔ No `position` field: module 16's
    `ComboIngredient` has none either, deliberately, and a matcher that read one would be a bug.
    ⛔ No `minTier` either since SSH7.3: the tier an ingredient needs is the LADDER's reading at match
    time, so a seed that carried one would pin a rung against a ladder a balance pass may republish."""

    family: str
    quantity: int

    def to_dict(self) -> dict:
        return {"family": self.family, "quantity": self.quantity}


def ingredient_rows(families: "list[str] | tuple[str, ...]",
                    tuning: ComboTuning) -> "tuple[IngredientRow, ...]":
    """Fold the model's four family picks into `(family, quantity)` rows.

    ⛔ **No tier is emitted** (strain-splice-host SSH7.3, spec-tier-ladder §3): which insert tier an
    ingredient needs is the LADDER's reading at match time, never a number a seed authors. It is the
    same split that already kept `grantedTier` out of the model's hands — a corpus row that carried a
    tier would pin a rung against a ladder that can be retuned without regenerating anything.

    Deterministic in one function of the answer: the picks are sorted by family id and identical
    families FOLD into one row, so the same four families in any arrangement produce byte-identical
    rows — D41 at the emit layer rather than only at the matcher.
    """
    picks = list(families)
    if len(picks) != tuning.ingredient_count:
        raise IdRefused(
            f"a combination takes exactly {tuning.ingredient_count} ingredients (D20 as amended, "
            f"§2f.2); got {len(picks)}")
    counts: "dict[str, int]" = {}
    for family in sorted(picks):
        counts[family] = counts.get(family, 0) + 1
    return tuple(IngredientRow(family=f, quantity=q) for f, q in sorted(counts.items()))


def min_sockets(tuning: ComboTuning) -> int:
    """`min_sockets` is DERIVED from the ingredient count, never authored (the P1 table's fourth
    row). A four-ingredient recipe needs four sockets and there is nothing to choose."""
    return tuning.ingredient_count


def assemble_entry(*, entry_id: str, name_key: str, name: str, flavor: str, shape: str,
                   aptitudes: "tuple[str, ...]", archetype: "str | None",
                   ingredient_families: "list[str]", grants: "list[str]",
                   tuning: ComboTuning, host_role: "str | None" = None,
                   host_frame: "str | None" = None) -> dict:
    """Plan + model draft -> the final `combination` entry, matching the field ORDER
    `sockwords.json`'s own legacy rows used (`id`, `nameKey`, `name`, `flavor`, then the shape's own
    fields) so a diff against the retired corpus reads as content, not a generator reordering keys.

    ⛔ **No tier number is emitted at all** (SSH7.3). The granted tier is
    `baseTier[shape] + ladder[rung].grantDelta + attunement`, and the RUNG is a runtime property of a
    concrete fill — the evaluator (module 16, C#) is the one place that fact exists. A seed that
    authored a tier would pin one against a ladder a balance pass may re-publish without regenerating
    the corpus, which is exactly what `tier-ladder` exists to allow.
    """
    if not entry_id.startswith(f"{CONTAINER_PREFIX}."):
        raise IdRefused(f"entry id {entry_id!r} does not carry the {CONTAINER_PREFIX!r} prefix")
    if not name:
        raise IdRefused("name must be non-empty")
    rows = ingredient_rows(ingredient_families, tuning)
    if not grants:
        raise IdRefused("a combination must grant at least one atom family")

    entry: dict = {
        "id": entry_id,
        "nameKey": name_key,
        "name": name,
        "flavor": flavor,
        "shape": shape,
        "aptitudes": list(aptitudes),
    }
    if archetype is not None:
        entry["archetype"] = archetype
    if host_role is not None:
        entry["hostRole"] = host_role
    if host_frame is not None:
        entry["hostFrame"] = host_frame
    entry["minSockets"] = min_sockets(tuning)
    entry["ingredients"] = [r.to_dict() for r in rows]
    entry["grants"] = list(grants)
    return entry
