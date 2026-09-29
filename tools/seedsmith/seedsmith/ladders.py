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

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]

#: The declaring files, named once each so a test can assert the version this leaf reads.
RARITY_LADDER_FILE = REPO_ROOT / "data" / "seed" / "rarity" / "ladder.v1.json"
THREAT_TUNING_FILE = REPO_ROOT / "data" / "tuning" / "creature-threat.v2.json"


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
