"""Tests for seedsmith.adapters.creatures.anchor.review_queue (spec-classify-pipelines.md §3,
creature-seed module 7 pipeline 5 `threat-audit`, T2.5)."""
from __future__ import annotations

from pathlib import Path

from seedsmith.adapters.creatures.anchor.review_queue import (
    ThreatAuditReviewEntry,
    build_review_queue,
    read_review_queue,
    write_review_queue,
)


def test_agree_verdicts_never_enter_the_queue():
    entries = [
        ThreatAuditReviewEntry("peashooter", "plant", "nuisance", "agree", "matches"),
        ThreatAuditReviewEntry("wallnut", "plant", "warden", "too-high", "seems weaker than warden"),
    ]
    queue = build_review_queue(entries)
    assert len(queue) == 1
    assert queue[0].species_id == "wallnut"


def test_queue_write_read_roundtrip_is_sorted_and_stable(tmp_path: Path):
    entries = [
        ThreatAuditReviewEntry("zzz", "zombie", "tyrant", "too-low", "seems dangerous"),
        ThreatAuditReviewEntry("aaa", "plant", "pest", "too-high", "weaker than pest"),
    ]
    path = tmp_path / "queue.json"
    write_review_queue(entries, path)
    read_back = read_review_queue(path)
    assert [e.species_id for e in read_back] == ["aaa", "zzz"]  # (side, id) ordinal


def test_missing_queue_file_reads_as_empty(tmp_path: Path):
    assert read_review_queue(tmp_path / "nope.json") == []
