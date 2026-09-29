"""The two ladders' declaring reads must be the CURRENT published version (TB-H2's seedsmith half,
plus tier-propagation-contract T-2's "read the declaring file, never restate the ids").

TB-H2 found that every C# reader had stayed on `creature-threat.v1.json` while the classifier moved
to v2, and claimed the seedsmith side had followed — true of `power/bands.py` (which reads v2) and
false of `seedsmith/ladders.py`, which kept declaring the rung vocabulary from v1. This file is what
fails loudly if that ever happens again: it derives the expected version from the files ON DISK
rather than pinning a literal, so shipping a v3 without moving the read is a red test, not a silent
year-old ladder.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from seedsmith.ladders import (
    RARITY_LADDER,
    RARITY_LADDER_FILE,
    REPO_ROOT,
    THREAT_BAND,
    THREAT_TUNING_FILE,
)

_VERSIONED = re.compile(r"^creature-threat\.v(\d+)\.json$")


def _highest_shipped_threat_tuning() -> Path:
    files = [
        p for p in (REPO_ROOT / "data" / "tuning").iterdir() if _VERSIONED.match(p.name)
    ]
    assert files, "no creature-threat.v{n}.json shipped at all — the declaring file is gone"
    return max(files, key=lambda p: int(_VERSIONED.match(p.name).group(1)))


def test_the_threat_ladder_declaring_read_is_the_highest_shipped_version():
    highest = _highest_shipped_threat_tuning()

    assert THREAT_TUNING_FILE.name == highest.name, (
        f"seedsmith/ladders.py declares the threat vocabulary from {THREAT_TUNING_FILE.name} while "
        f"{highest.name} is the current published version (H7/T5: one version per domain; readers "
        f"move in the same commit as the publish)")


def test_the_threat_band_is_the_declaring_files_own_ids_in_rung_order():
    doc = json.loads(THREAT_TUNING_FILE.read_text(encoding="utf-8"))
    expected = tuple(r["id"] for r in sorted(doc["thresholds"], key=lambda r: r["rung"]))

    assert THREAT_BAND == expected
    assert len(set(THREAT_BAND)) == len(THREAT_BAND)  # a closed vocabulary, no repeats


def test_the_rarity_ladder_still_reads_its_own_declaring_file():
    doc = json.loads(RARITY_LADDER_FILE.read_text(encoding="utf-8"))
    expected = tuple(r["id"] for r in sorted(doc["entries"], key=lambda r: r["ordinal"]))

    assert RARITY_LADDER == expected


def test_the_two_shipped_threat_versions_agree_on_the_vocabulary_and_the_offsets():
    """Why the v1 -> v2 move was behaviour-preserving — and the reason it still had to be made:
    the only column the two files disagree on is `maxScore`, which only the Python classifier reads
    (`power/bands.py`); the rung ids and the `thetaOffset` column every other reader consumes are
    identical, so a reader left behind is invisible TODAY and silently wrong the day a v3 moves
    either of them. Read as a reconciliation over whatever versions are on disk, never a count."""
    versions = sorted(
        (REPO_ROOT / "data" / "tuning").glob("creature-threat.v*.json"),
        key=lambda p: int(_VERSIONED.match(p.name).group(1)),
    )
    assert len(versions) >= 2, "expected at least two shipped versions (v1 kept for revert)"

    docs = [json.loads(p.read_text(encoding="utf-8")) for p in versions]
    ids = [tuple(r["id"] for r in sorted(d["thresholds"], key=lambda r: r["rung"])) for d in docs]
    offsets = [
        tuple(r["thetaOffset"] for r in sorted(d["thresholds"], key=lambda r: r["rung"]))
        for d in docs
    ]

    assert all(i == ids[0] for i in ids), "the shipped versions disagree on the rung vocabulary"
    assert all(o == offsets[0] for o in offsets), "the shipped versions disagree on thetaOffset"
