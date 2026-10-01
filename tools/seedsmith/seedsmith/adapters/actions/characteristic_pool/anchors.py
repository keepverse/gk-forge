"""seedsmith.adapters.actions.characteristic_pool.anchors — the classified species anchor tree
(spec §2's fifth "Reads" row: `gk-data/packs/fusion/data/seed/creatures/species/**/*.json`, the optional 19-species
enrichment of posture/reach/targetPreference/attackTempo).

**A live-data finding, not a defect in this module — read before trusting any specific count.**
Spec §1 cites `gk-data/packs/fusion/data/seed/creatures/species/_index.json` at "28 entries" and a four-way join of "8"
(measured 2026-09-03, the day the spec was written). As of this module's own build (same day,
later), that file is **modified but uncommitted** (`git status`: `M
gk-data/packs/fusion/data/seed/creatures/species/_index.json`, plus dozens of untracked `plant/*.json` anchor files) — a
concurrent, unrelated creature-species-classification pass is actively growing the tree WHILE this
module was being written: three separate measurements taken minutes apart during this module's
own build returned three different totals (28 -> 68 -> 87 unique anchor rows), and the
catalog-matching subset moved too (19 -> 23). This loader reads whatever is on disk at run time —
never a cached snapshot — which is the only way `unjoined` can honestly satisfy step 1's "never
dropped silently, never renamed to fit". See this module's build report and
`tests/test_characteristic_pool.py`'s `AnchorTreeJoinTests` for why no test in this program pins
an exact anchor-tree literal: at this file's current update cadence, a literal would be a stale
tripwire within the same working session, not a real content-change signal.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

__all__ = ["AnchorRow", "AnchorTree", "load_anchor_tree", "SPECIES_ROOT"]

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

SPECIES_ROOT = _owned("data/seed/creatures/species")
INDEX_NAME = "_index.json"

# The three closed anchor axes step 4 scores (`ATTACK_TEMPO` deliberately absent — spec §3 step 4:
# excluded by measurement, every observed value is "steady", so it carries no signal. A dedicated
# test proves re-adding it changes nothing rather than just omitting it silently).
ANCHOR_AXES: "tuple[str, ...]" = ("posture", "reach", "targetPreference")


@dataclass(frozen=True)
class AnchorRow:
    species_id_lower: str
    posture: "str | None"
    reach: "str | None"
    target_preference: "str | None"
    attack_tempo: "str | None"          # carried for the exclusion test only — never scored


@dataclass(frozen=True)
class AnchorTree:
    #: lowered speciesId -> its own row, ONE per species (a duplicate index key pointing at the
    #: same row is collapsed, never double-counted).
    by_lower_id: "dict[str, AnchorRow]"
    #: index entries whose target file could not be read, or whose target file exists but holds
    #: no row for that key — a real data-quality gap in the (unrelated, concurrently-generated)
    #: tree, surfaced rather than silently swallowed.
    broken_index_entries: "tuple[str, ...]"


def load_anchor_tree(root: Path = SPECIES_ROOT) -> AnchorTree:
    """Load every classified species row reachable from `_index.json`, keyed by the row's OWN
    `speciesId` (lower-cased) — never by the index's own key, which is a routing hint, not
    identity (a stale index key pointing at a file that no longer contains that species is exactly
    the `SnorkleZombie` / `zombie/unclassified.json` case measured 2026-09-03: the index still
    names the file, the file no longer holds that species' row)."""
    index_path = root / INDEX_NAME
    if not index_path.is_file():
        return AnchorTree(by_lower_id={}, broken_index_entries=())

    index = json.loads(index_path.read_text(encoding="utf-8"))
    by_lower: "dict[str, AnchorRow]" = {}
    broken: "list[str]" = []
    file_cache: "dict[Path, object]" = {}

    for index_key, rel_path in sorted(index.items()):
        target = root / rel_path
        if target not in file_cache:
            if not target.is_file():
                file_cache[target] = None
            else:
                try:
                    file_cache[target] = json.loads(target.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    file_cache[target] = None
        doc = file_cache[target]
        if not isinstance(doc, list):
            broken.append(index_key)
            continue

        # A file may hold several species' rows (e.g. `zombie/unclassified.json`'s ten). Find the
        # row whose OWN `speciesId` matches this index key case-insensitively — never "the first
        # row in the file", which would silently misattribute one species' anchor to another's.
        row = next((r for r in doc if isinstance(r, dict)
                   and str(r.get("speciesId", "")).lower() == index_key.lower()), None)
        if row is None:
            broken.append(index_key)
            continue

        lower_id = index_key.lower()
        if lower_id not in by_lower:
            by_lower[lower_id] = AnchorRow(
                species_id_lower=lower_id,
                posture=row.get("posture"),
                reach=row.get("reach"),
                target_preference=row.get("targetPreference"),
                attack_tempo=row.get("attackTempo"),
            )

    return AnchorTree(by_lower_id=by_lower, broken_index_entries=tuple(broken))
