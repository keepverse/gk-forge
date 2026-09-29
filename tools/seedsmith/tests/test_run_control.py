"""Tests for `run-control` (spec-run-control.md, creature-seed module 9)."""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from seedsmith.adapters.creatures.run.machine import IllegalTransition, can, is_terminal, transition
from seedsmith.adapters.creatures.run.record import (
    RunRecord,
    can_overwrite_all,
    can_resume,
    can_start,
    is_process_alive,
    new_run_id,
    overwrite_all_token,
    read_record,
    write_record,
)
from seedsmith.adapters.creatures.run.selectors import UnknownSelectorKind, resolve_selector

DUMP_SPECIES = [
    {"speciesId": "peashooter", "side": "plant"},
    {"speciesId": "sunflower", "side": "plant"},
    {"speciesId": "normalzombie", "side": "zombie"},
]

ANCHORS = [
    {"speciesId": "peashooter", "side": "plant", "family": ["plant"], "basis": "observed",
     "elementPrimary": "earth", "_provenance": {"dumpHash": "hash-A", "promptVersions": {"element-primary": 1}}},
    {"speciesId": "sunflower", "side": "plant", "family": ["plant", "support"], "basis": "inferred",
     "elementPrimary": "unresolved", "_provenance": {"dumpHash": "hash-A", "promptVersions": {"element-primary": 1}}},
    {"speciesId": "normalzombie", "side": "zombie", "family": ["zombie"], "basis": "stated",
     "elementPrimary": "dark", "_provenance": {"dumpHash": "hash-OLD", "promptVersions": {"element-primary": 1}}},
]


# --- machine.py -----------------------------------------------------------------------------


def test_full_lifecycle_transitions():
    s = "idle"
    s = transition(s, "start"); assert s == "running"
    s = transition(s, "pause"); assert s == "paused"
    s = transition(s, "resume"); assert s == "running"
    s = transition(s, "complete"); assert s == "completed"
    assert is_terminal(s)


def test_cancel_from_running_and_paused():
    assert transition("running", "cancel") == "cancelled"
    assert transition("paused", "cancel") == "cancelled"


def test_failed_can_resume():
    assert transition("failed", "resume") == "running"


def test_illegal_transition_raises_not_silently_no_ops():
    with pytest.raises(IllegalTransition):
        transition("idle", "pause")
    with pytest.raises(IllegalTransition):
        transition("completed", "resume")
    assert not can("completed", "resume")


# --- record.py: refusals (spec §5) --------------------------------------------------------


def test_skip_model_preflight_cannot_start_a_run():
    preflight = {"dumpHash": "hash-A", "skipModel": True}
    ok, reason = can_start(preflight, dump_hash="hash-A", existing_record=None)
    assert ok is False
    assert "skip-model" in reason.lower()


def test_no_preflight_record_cannot_start():
    ok, reason = can_start(None, dump_hash="hash-A", existing_record=None)
    assert ok is False
    assert "preflight" in reason.lower()


def test_preflight_dump_mismatch_refuses_start():
    preflight = {"dumpHash": "hash-OLD", "skipModel": False}
    ok, reason = can_start(preflight, dump_hash="hash-A", existing_record=None)
    assert ok is False


def test_two_concurrent_starts_refuse_the_second():
    preflight = {"dumpHash": "hash-A", "skipModel": False}
    running = RunRecord(run_id="run-1", state="running", preflight=preflight, dump_hash="hash-A",
                        selector={"kind": "all"}, prompt_versions={}, pid=os.getpid())
    ok, reason = can_start(preflight, dump_hash="hash-A", existing_record=running)
    assert ok is False
    assert "run-1" in reason


def test_dead_process_record_offers_resume_not_a_hard_refuse_forever():
    preflight = {"dumpHash": "hash-A", "skipModel": False}
    dead_pid = 999_999_999  # astronomically unlikely to be a real live pid
    dead = RunRecord(run_id="run-dead", state="running", preflight=preflight, dump_hash="hash-A",
                     selector={"kind": "all"}, prompt_versions={}, pid=dead_pid)
    ok, reason = can_start(preflight, dump_hash="hash-A", existing_record=dead)
    assert ok is False
    assert "resume" in reason.lower()
    assert "run-dead" in reason


def test_resume_against_changed_dump_refuses():
    record = RunRecord(run_id="run-1", state="paused", preflight={}, dump_hash="hash-OLD",
                       selector={}, prompt_versions={}, pid=os.getpid())
    ok, reason = can_resume(record, current_dump_hash="hash-NEW")
    assert ok is False
    assert "rerun --stale" in reason


def test_overwrite_all_requires_the_token():
    ok, reason = can_overwrite_all("wrong-token", dump_hash="hash-A")
    assert ok is False
    real_token = overwrite_all_token("hash-A")
    ok2, _ = can_overwrite_all(real_token, dump_hash="hash-A")
    assert ok2 is True


def test_current_process_is_reported_alive():
    assert is_process_alive(os.getpid()) is True


def test_run_id_is_sortable():
    a = new_run_id()
    import time as _t
    _t.sleep(0.001)
    b = new_run_id()
    assert a < b  # string-sortable == time-sortable


# --- record persistence: lists, not counts (spec §3) ---------------------------------------


def test_record_lists_species_ids_not_counts(tmp_path: Path):
    record = RunRecord(
        run_id="run-1", state="completed", preflight={"dumpHash": "hash-A"}, dump_hash="hash-A",
        selector={"kind": "all"}, prompt_versions={"element-primary": 1}, pid=os.getpid(),
        completed=["peashooter", "sunflower"], failed=[], skipped=["normalzombie"], calls_made=16,
    )
    path = tmp_path / "run.json"
    write_record(record, path)
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert raw["completed"] == ["peashooter", "sunflower"]  # a LIST, answerable per-species
    assert "normalzombie" in raw["skipped"]

    read_back = read_record(path)
    assert read_back.completed == ["peashooter", "sunflower"]
    assert read_back.calls_made == 16


def test_missing_record_reads_as_none(tmp_path: Path):
    assert read_record(tmp_path / "nope.json") is None


# --- selectors.py: all eight, zero model calls ----------------------------------------------


def test_every_selector_resolves_without_a_model_call():
    # No `call`/transport parameter exists anywhere in resolve_selector's signature — the
    # strongest proof available that it cannot reach a model even by accident.
    import inspect
    sig = inspect.signature(resolve_selector)
    assert "call" not in sig.parameters

    assert resolve_selector({"kind": "all"}, dump_species=DUMP_SPECIES) == \
        ["normalzombie", "peashooter", "sunflower"]
    assert resolve_selector({"kind": "side", "side": "plant"}, dump_species=DUMP_SPECIES) == \
        ["peashooter", "sunflower"]
    assert resolve_selector({"kind": "family", "family": "support"}, dump_species=DUMP_SPECIES, anchors=ANCHORS) == \
        ["sunflower"]
    assert resolve_selector({"kind": "species", "species": ["peashooter", "not-real"]}, dump_species=DUMP_SPECIES) == \
        ["peashooter"]
    assert resolve_selector({"kind": "pipeline", "pipeline": "element-primary"}, dump_species=DUMP_SPECIES) == \
        ["normalzombie", "peashooter", "sunflower"]
    assert resolve_selector({"kind": "basis", "basis": "inferred"}, dump_species=DUMP_SPECIES, anchors=ANCHORS) == \
        ["sunflower"]
    assert resolve_selector({"kind": "unresolved"}, dump_species=DUMP_SPECIES, anchors=ANCHORS) == \
        ["sunflower"]
    stale = resolve_selector({"kind": "stale"}, dump_species=DUMP_SPECIES, anchors=ANCHORS,
                             current_dump_hash="hash-A", current_prompt_versions={"element-primary": 1})
    assert stale == ["normalzombie"]  # its provenance names hash-OLD


def test_unknown_selector_kind_raises():
    with pytest.raises(UnknownSelectorKind):
        resolve_selector({"kind": "nonsense"}, dump_species=DUMP_SPECIES)
