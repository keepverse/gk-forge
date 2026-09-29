"""seedsmith.numerics.channel_weight_backfill — atom-family-expansion module `tier-bands-coverage`
(docs/architecture/atom-family-expansion/spec-tier-bands-coverage.md).

Closes the historical `gk-forge/tools/FamilyExpandGen -- --check` refusals shaped "no authored sharePermille
for family X (channel stem X not in tier-bands.v1.json)" by computing, from each family's own
`powerBand`, the `channelWeightPermille` entry it lacks today — then handing the result to the
already-built `seedsmith numerics rebalance --set-file ... --publish` CLI (`report/cli.py`) rather
than writing tier-bands.v{n}.json by any other path.

**The formula.** Reuses this project's own single, already-reviewed tier ratio
(`MAGNITUDE_RATIO_PERMILLE = 1750`, imported from `seedsmith.numerics` directly — never a private
copy) as the band-to-band step, anchored so `medium` maps to `1000`, matching `bands.v1.json`'s own
`powerBand.tierMap` ordinal (`trivial=1 .. extreme=5`) and the same `round_legible` both
`FamilyExpansion.cs` and this package's own `formulas.py` already implement identically.

**Known, accepted divergence (spec §6, owner decision 2026-09-08).** This formula reproduces 8 of the
14 already-published `channelWeightPermille` entries (the `medium`-band ones) exactly. The other 6
(`fortitude`/`ferocity`/`resilience`/`mending`, `low`; `bulwark`/`savagery`, `high`) are additively
left untouched even though the formula would compute a different value for them — composing this
band-derived weight with `opWeightPermille`'s own existing discount produces a real, demonstrated bias
(the everyday `Increased` lever gets cut hardest, the deliberately-rarest `More` lever is nearly
unaffected). The owner chose to ship as designed and revisit via telemetry later, matching
`tier-bands.v1.json`'s own stated "not a validated balance decision yet" posture — this module never
overwrites an already-published entry, so that decision is enforced structurally, not just by policy.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from . import tier_bands_io
from .model import MAGNITUDE_RATIO_PERMILLE, TierBands
from .formulas import round_legible, tier_ladder

REPO_ROOT = Path(__file__).resolve().parents[4]
FAMILIES_DIR = REPO_ROOT / "data" / "seed" / "items" / "affix-families"
BANDS_REGISTRY = REPO_ROOT / "data" / "seed" / "items" / "_registry" / "bands.v1.json"

#: bands.v1.json powerBand.tierMap, mirrored exactly, cited, never re-derived.
_BAND_ORDINAL = {"trivial": 1, "low": 2, "medium": 3, "high": 4, "extreme": 5}
_MEDIUM_ORDINAL = _BAND_ORDINAL["medium"]


def _weights_by_offset() -> "dict[int, int]":
    """Chained, per-step `round_legible` -- reusing `tier_ladder`'s own real iteration shape
    (`ladder[-1] * ratio / 1000`, rounded at EACH step) rather than a closed-form power
    calculation. This matters: chaining and a single-shot power computation can disagree once
    rounding is involved (verified directly: chained gives extreme=3062, a closed-form power
    calculation gives 3063 under round-half-up -- this module uses the former because it is the
    one real, already-shipped convention `FamilyExpansion.cs`'s own `TierLadder` and this
    package's own `tier_ladder` already establish for 'apply this ratio N steps in a row')."""
    # Upward from medium (offset 0): tier_ladder(1000, 3, ratio) = [offset0, offset+1, offset+2]
    up = tier_ladder(1000, 3, MAGNITUDE_RATIO_PERMILLE)
    # Downward from medium: the same per-step round_legible, dividing instead of multiplying.
    down = [1000]
    for _ in range(2):
        down.append(round_legible(down[-1] * 1000 / MAGNITUDE_RATIO_PERMILLE))
    return {0: up[0], 1: up[1], 2: up[2], -1: down[1], -2: down[2]}


_WEIGHT_BY_OFFSET = _weights_by_offset()

#: The 5-row table, computed once at import time from the real, shipped `tier_ladder`/
#: `round_legible` chain -- trivial=326, low=571, medium=1000, high=1750, extreme=3062. A drift
#: guard, not a hand-copied literal table: if bands.v1.json's own ordinal map or the shared
#: MAGNITUDE_RATIO_PERMILLE ever changes, this recomputes rather than going stale.
WEIGHT_BY_BAND: "dict[str, int]" = {
    band: _WEIGHT_BY_OFFSET[ordinal - _MEDIUM_ORDINAL] for band, ordinal in _BAND_ORDINAL.items()
}


@dataclass(frozen=True)
class FamilyEntry:
    id: str
    power_band: str


def load_families(families_dir: "Path | None" = None) -> "list[FamilyEntry]":
    """Every family across every non-underscore-prefixed `*.json` file in the affix-families
    directory, in file order. Mirrors `affixfamgen.brief.load_partition_context`'s own
    underscore-skip convention, but flat across all files (that function reads one partition;
    this one needs every family's own `powerBand`, which `PartitionContext` doesn't carry)."""
    d = families_dir or FAMILIES_DIR
    families: "list[FamilyEntry]" = []
    for path in sorted(d.glob("*.json")):
        if path.name.startswith("_"):
            continue
        doc = json.loads(path.read_text(encoding="utf-8"))
        for entry in doc.get("entries", []):
            if "id" not in entry or "powerBand" not in entry:
                continue
            families.append(FamilyEntry(id=entry["id"], power_band=entry["powerBand"]))
    return families


#: The 14 stems `tier-bands.v1.json` actually published, the ONLY set the owner's "ship the
#: formula, accept the known bias, leave the 14 untouched" decision (spec §6) was made against.
#: ⛔ **Real, found-mid-execution collision, not a hypothetical**: `TierBands.load("latest")`
#: resolved to the pre-backfill `v3.json`/`v4.json` snapshots (from an unrelated earlier effort,
#: `tasks/seedsmith-todo.md` S5) which carried the original 112 stems uniformly at `1000`,
#: `_meta` itself saying "not a validated balance decision yet," i.e. the exact placeholder state
#: this module exists to supersede for 98 of them. Checking "already covered" against `latest`
#: would treat that placeholder work as a second, unreviewed "protect this" decision and make this
#: whole module a no-op. The owner's actual decision named these 14 stems specifically (spec §6's
#: own six-family divergence list is a subset of exactly these) — so "already decided, don't touch"
#: means member-of-this-frozen-set, not member-of-whatever-latest-happens-to-contain-today.
PROTECTED_V1_STEMS: "frozenset[str]" = frozenset({
    "vitality", "fortitude", "bulwark", "might", "ferocity", "savagery", "warding", "resilience",
    "plating", "carapace", "mending", "quickening", "flourishing", "swiftness",
})


#: The uniform placeholder every non-`PROTECTED_V1_STEMS` entry in the pre-v5 snapshots happened to
#: carry (verified live for the original 98 entries, no exceptions) — `tier-bands.v1.json`'s (and
#: v2-v4's)
#: own `_meta.note` says these are "not a validated balance decision," and this exact value is the
#: tell. Used only as a defense-in-depth signal (see `missing_channel_weights` below), never as a
#: magic number a real computation depends on.
_UNREVIEWED_PLACEHOLDER_WEIGHT = 1000

# v5 is the first published tier-band snapshot produced by this backfill against the complete
# 125-family corpus. From that version onward, a 1000‰ value is an authored medium-band weight,
# not the old uniform placeholder. Older immutable snapshots retain the historical detection
# behaviour so the migration remains auditable.
_BACKFILL_COMPLETE_VERSION = 5


def missing_channel_weights(
    families: "list[FamilyEntry]", tuning: TierBands,
) -> "dict[str, int]":
    """Detect + compute, pure. For every family stem that is NOT one of the 14
    `PROTECTED_V1_STEMS`, the weight its `powerBand` maps to — recomputed and republished even if
    `tuning` (typically 'latest') already carries a value for it, since any such value beyond the
    protected 14 is, as far as this session could verify, exactly the uniform-`1000` placeholder
    this module exists to supersede, never a second reviewed decision.

    **Defense in depth**: if `tuning` carries a value for a non-protected stem that is NOT the
    known placeholder (`_UNREVIEWED_PLACEHOLDER_WEIGHT`), that is new information this function
    didn't have when this rule was written — some other, later effort deliberately set something
    real for it — and it is left alone, additive-only, matching the protected-14 posture exactly.
    """
    missing: "dict[str, int]" = {}
    for family in families:
        stem = family.id.removeprefix("atom.")
        if stem in PROTECTED_V1_STEMS:
            continue
        current = tuning.channel_weight_permille.get(stem)
        if current is not None:
            if tuning.version >= _BACKFILL_COMPLETE_VERSION or current != _UNREVIEWED_PLACEHOLDER_WEIGHT:
                continue
        missing[stem] = WEIGHT_BY_BAND[family.power_band]
    return missing


def write_set_file(missing: "dict[str, int]", path: Path) -> Path:
    """One `channelWeight.<id>=<value>` line per entry, sorted by id -- the exact format
    `seedsmith numerics rebalance --set-file` already parses (`report/cli.py`'s own
    `_parse_set_pairs`), no new CLI flag, no new parser.

    ⛔ **Real bug caught before shipping**: `_parse_set_pairs`/`TierBands.adjust` both document (and
    implement, `model.py:118-128`) that `--set`/`--set-file` values are **plain ratio multipliers**
    (`1.0` == `1000`‰, stored internally as `round(ratio * 1000)`) -- never a raw per-mille integer.
    Writing `channelWeight.foo=571` (this module's own internal representation) would have been
    silently misparsed as a ratio of 571 (-> 571000‰). Every value here is divided by 1000.0 before
    writing, so `WEIGHT_BY_BAND`'s per-mille integers round-trip back to themselves exactly through
    the real CLI, not through 1000x.
    """
    lines = [f"channelWeight.{stem}={value / 1000.0:g}" for stem, value in sorted(missing.items())]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def main(argv=None) -> int:
    """`python -m seedsmith.numerics.channel_weight_backfill [--out <path>]`.

    Reads the real corpus and the current published tuning, computes the missing entries, writes a
    `--set-file`-compatible file, and prints the exact `seedsmith numerics rebalance` command to run.
    Never calls `--publish` itself -- dry-by-default, matching `rebalance`'s own posture.
    """
    import argparse
    import tempfile

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=None,
                        help="where to write the --set-file (default: a temp file)")
    args = parser.parse_args(argv)

    families = load_families()
    tuning = TierBands.load("latest")
    missing = missing_channel_weights(families, tuning)

    if not missing:
        print("clean -- no missing channelWeightPermille entries found")
        return 0

    out_path = args.out
    if out_path is None:
        fd, name = tempfile.mkstemp(prefix="channel-weight-backfill-", suffix=".txt")
        import os
        os.close(fd)
        out_path = Path(name)
    write_set_file(missing, out_path)

    print(f"{len(missing)} missing channelWeightPermille entr{'y' if len(missing) == 1 else 'ies'} "
          f"written to {out_path}")
    print(f"seedsmith numerics rebalance --set-file {out_path} --publish")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
