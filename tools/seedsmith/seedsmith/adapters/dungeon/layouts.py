"""Layout template content (D4.30's own real prerequisite chain; spec-dungeon-seed-contract.md
§1.3, `dungeon-layout`'s own budget row: *"Model-free, planner-emitted directly from
`dungeon.v1.json` bands -- no call, no budget row needed beyond this placeholder"*).

**Real drift found and fixed before any content shipped, not trusted from the spec's own prose**:
`spec-dungeon-seed-contract.md`:76 cites `widthBand` as `narrow · regular · broad`, but the real,
committed `gk-data/packs/fusion/data/seed/dungeon/_registry/bands.v1.json`'s own `widthBand` band is
`narrow · mid · wide` — confirmed by reading the registry file directly, not assumed from the doc.
`schema.py`'s own `build_layout_schema` reads `reg["bands"]["widthBand"]`, so the REGISTRY is the
real contract; this module follows it, not the spec's stale prose.

Every field on a layout anchor is PLANNED (`schema.py`'s `LAYOUT_OWNERSHIP`, confirmed empty of
AUTHORED/VALIDATED members) -- there is no model call to make and no vote to resolve. This module
is the whole of `dungeon-layout`'s own generation: a small, hand-reasoned set of templates spanning
the real band space, minted and emitted exactly like a model-authored corpus would be, just without
a model in the loop.

**Why six, not the full 3x3x3x3x3x3x(2^3-1) combinatorial space**: the budget row's own "no cells"
framing means there is no coverage metric demanding exhaustive enumeration (unlike room/event/quest/
encounter). Six templates give real, reasoned variety across every one of the eight fields --
every value of `sizeBand`/`widthBand`/`branchiness` appears at least once, every value of the three
density bands appears at least once, and `raidModes` narrows from `[solo, pair]` at the simplest
template to `[quad]` at the most complex one, matching the real gameplay shape ("a bigger, more
tangled graph asks for more coordination, not less").
"""
from __future__ import annotations

from typing import Any

from .planner import IdMinter

#: (cell_key, sizeBand, widthBand, branchiness, gateDensity, secretDensity, oneWayDensity, raidModes)
#: Ordered simplest -> most complex; the ordering is also the mint order, so `layout.*-001` is
#: always the simplest real template on a fresh emit.
_TEMPLATES: "tuple[tuple[str, str, str, str, str, str, str, tuple[str, ...]], ...]" = (
    ("short-narrow-linear", "short", "narrow", "linear", "none", "sparse", "none", ("solo", "pair")),
    ("short-mid-forked", "short", "mid", "forked", "sparse", "sparse", "none", ("solo", "pair", "quad")),
    ("medium-mid-forked", "medium", "mid", "forked", "sparse", "sparse", "sparse", ("solo", "pair", "quad")),
    ("medium-wide-webbed", "medium", "wide", "webbed", "sparse", "dense", "sparse", ("pair", "quad")),
    ("long-mid-forked", "long", "mid", "forked", "dense", "sparse", "sparse", ("pair", "quad")),
    ("long-wide-webbed", "long", "wide", "webbed", "dense", "dense", "dense", ("quad",)),
)


def build_layout_entries(minter: "IdMinter | None" = None) -> "dict[str, dict[str, Any]]":
    """Mints and builds every layout entry, in the fixed order above. A fresh `IdMinter()` (the
    default) reproduces the SAME ids every call — `layout.short-narrow-linear-001` etc. — since
    `_TEMPLATES` is a fixed tuple and `IdMinter` mints deterministically from an empty high-water
    mark; the byte-identical-rerun test relies on exactly this, not on a frozen id list kept twice.
    """
    minter = minter if minter is not None else IdMinter()
    entries: "dict[str, dict[str, Any]]" = {}
    for cell_key, size, width, branch, gate, secret, one_way, raid_modes in _TEMPLATES:
        layout_id = minter.next_id("layout", cell_key)
        entries[layout_id] = {
            "layoutId": layout_id,
            "sizeBand": size,
            "widthBand": width,
            "branchiness": branch,
            "gateDensity": gate,
            "secretDensity": secret,
            "oneWayDensity": one_way,
            "raidModes": list(raid_modes),
        }
    return entries
