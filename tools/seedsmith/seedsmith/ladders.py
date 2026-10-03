"""The two tier ladders' declaring reads (tier-propagation-contract T-2).

T-2 bans restating a ladder's ids in code. The rarity ladder's declaring file is
`gk-data/packs/fusion/data/seed/rarity/ladder.v1.json` (entries carry `id` + `ordinal`; its own `_meta.sourceRef`
cites ssot-rarity.md §3.3) and the threat ladder's is the CURRENT published
`data/tuning/creature-threat.v{n}.json` (`thresholds` carry `rung` + `id`). Every seedsmith module
reads the ladders from here — never a transcribed tuple — so a widening touches the declaring
files and nothing else.

**The threat ladder's version moved v1 -> v2 on 2026-09-23 (TB-H2's seedsmith half).** The row
that found the C# readers lagging claimed "the seedsmith side followed" — true of the
*classifier* (`adapters/creatures/power/bands.py` reads v2) and NOT true of this leaf, which kept
declaring the vocabulary from v1. Both files carry the SAME ten rung ids, the same `thetaOffset`
column and the same `inferredDefaultRung` (measured); only `maxScore` differs, and only the
classifier reads that column — so this is a version-alignment fix, behaviour-preserving, and the
whole point of H7/T5's one-version-per-domain rule: the day a v3 renames a rung or moves an
offset, a reader left on v2 would silently keep the old ladder. `test_ladders_declaring_reads.py`
now fails loudly if this leaf ever lags the highest shipped version again.

Deliberately import-time reads of two tiny JSON files: these are closed vocabularies the
tooling owns (validation-ssot.md §1), and every consumer previously hardcoded them at import
anyway. No seedsmith-internal imports here, so this leaf can never join an import cycle.
"""
from __future__ import annotations

import re

import json
from pathlib import Path

from .workspace_roots import content_root, core_root

#: The declaring files, named once each so a test can assert the version this leaf reads.
#:
#: THESE TWO LIVES IN TWO DIFFERENT REPOSITORIES, which is what the single `REPO_ROOT` above could not
#: express. `data/seed/**` is gk-data's pack and `data/tuning/**` is gk-core's; before the split both
#: sat under one root. The module read `REPO_ROOT = parents[3]` - gk-forge - which has neither, so
#: `rarity_ladder()` raised FileNotFoundError at IMPORT time, and because `RARITY_LADDER` is a
#: module-level constant every entry point that imports this one died with it.
#:
#: That is the failure this fixes, and it was invisible for the same reason fourteen check wrappers
#: were: the wrappers were reporting green without running, so nothing had asked this module for a
#: rarity rung since the split. The docstring one line below already named the post-split path
#: (`gk-data/packs/fusion/data/seed/rarity/ladder.v1.json`) while the code above it still walked up
#: from gk-forge - the same docstring-right/code-stale shape as prove_actor_hud_live.py's WEB_DIR.
#:
#: `REPO_ROOT` SURVIVES, and it now means gk-core rather than gk-forge.
#:
#: I removed it first, on a measurement that was wrong. The grep I used looked for `ladders.REPO_ROOT`
#: and for `ladders import`, and the one real consumer writes it as a multi-line
#: `from seedsmith.ladders import (...)` - which neither pattern matched, and my result was truncated
#: to ten lines, so the miss looked like a clean answer. Removing it broke
#: tests/test_ladders_declaring_reads.py at IMPORT time, which is how I found out.
#:
#: Its one consumer uses it as `REPO_ROOT / "data" / "tuning"`, and `data/tuning` is gk-core's - so
#: `core_root()` is what it has always meant in practice, and saying so is the honest reading. It is
#: kept under the old name rather than renamed because renaming it would churn a test for no gain,
#: and the comment is what stops the next reader assuming it points at the package's own repository.
REPO_ROOT = core_root()
RARITY_LADDER_FILE = content_root() / "data" / "seed" / "rarity" / "ladder.v1.json"
THREAT_TUNING_FILE = core_root() / "data" / "tuning" / "creature-threat.v2.json"


def _read_ids(path: Path, rows_key: str, order_key: str, id_key: str) -> "tuple[str, ...]":
    with open(path, encoding="utf-8") as f:
        doc = json.load(f)
    rows = doc[rows_key]
    return tuple(r[id_key] for r in sorted(rows, key=lambda r: r[order_key]))


def rarity_ladder() -> "tuple[str, ...]":
    """The ten rarity rung ids, weakest first — `gk-data/packs/fusion/data/seed/rarity/ladder.v1.json` order."""
    return _read_ids(RARITY_LADDER_FILE, "entries", "ordinal", "id")


def threat_band() -> "tuple[str, ...]":
    """The ten threat rung ids, lowest first — the current `creature-threat.v{n}.json` order
    (`THREAT_TUNING_FILE`; v2 as of 2026-09-23)."""
    return _read_ids(THREAT_TUNING_FILE, "thresholds", "rung", "id")


#: The declaring reads, loaded once. Import these names — never re-transcribe the ids.
RARITY_LADDER: "tuple[str, ...]" = rarity_ladder()
THREAT_BAND: "tuple[str, ...]" = threat_band()


def normalize_family_key(label: str) -> str:
    """Turn a descriptive family label into a stable action namespace key.

    Lives in this shared leaf rather than in the actions characteristic_pool because the
    creatures runner must judge family labels exactly as that pool does. Restating the regex
    in the runner would be a second implementation free to drift from the consumer it exists to
    satisfy - the same shape as a parser validated only against itself. Moved here so both
    sides read one definition, measured 2026-10-04 when 36 Chinese-language labels across 13
    entries were written and every one would have been refused at load.
    """
    key = re.sub(r"[^a-z0-9]+", "-", label.strip().lower()).strip("-")
    if not key:
        raise ValueError(f"family label {label!r} normalizes to an empty key")
    return key
