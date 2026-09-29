"""Tests for seedsmith.adapters.creatures.preflight (spec-dump-preflight.md, creature-seed module 5)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from seedsmith.adapters.creatures.preflight import (
    DEFAULT_DUMP_DIR,
    PreflightReport,
    check_1_dump_exists,
    check_2_dump_is_current,
    check_3_dump_is_complete,
    check_4_contract_audits_clean,
    check_5_and_6_model,
    check_7_venv_and_lock_current,
    check_8_tuning_present,
    check_9_disk_headroom,
    run_preflight,
    write_preflight_record,
)


def write_dump(tmp_path: Path, *, plant: list, zombie: list, baseline: list, recipes: list,
               corrupt_hash: bool = False) -> Path:
    dump_dir = tmp_path / "_dump"
    (dump_dir / "almanac").mkdir(parents=True)
    (dump_dir / "almanac" / "plant.json").write_text(json.dumps(plant), encoding="utf-8")
    (dump_dir / "almanac" / "zombie.json").write_text(json.dumps(zombie), encoding="utf-8")
    (dump_dir / "spawn-baseline.json").write_text(json.dumps(baseline), encoding="utf-8")
    (dump_dir / "recipes.json").write_text(json.dumps(recipes), encoding="utf-8")

    import hashlib
    sha = hashlib.sha256()
    for name in ("almanac/plant.json", "almanac/zombie.json", "spawn-baseline.json", "recipes.json"):
        sha.update((dump_dir / name).read_bytes())
    content_hash = sha.hexdigest()
    if corrupt_hash:
        content_hash = "0" * 64

    manifest = {
        "dumpFormatVersion": 1, "capturedUtc": "2026-01-01T00:00:00Z", "contentHash": content_hash,
        "plantCount": len(plant), "zombieCount": len(zombie),
        "baselineCount": len(baseline), "recipeCount": len(recipes),
    }
    (dump_dir / "_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return dump_dir


# --- checks 1-3: dump hygiene ---------------------------------------------------------------


def test_check1_dump_exists_true_and_false(tmp_path: Path):
    missing = check_1_dump_exists(tmp_path / "nope")
    assert missing.ok is False
    assert missing.fix_command is not None

    dump_dir = write_dump(tmp_path, plant=[{"a": 1}], zombie=[], baseline=[], recipes=[])
    present = check_1_dump_exists(dump_dir)
    assert present.ok is True


def test_stale_dump_is_detected_by_hash_not_mtime(tmp_path: Path):
    dump_dir = write_dump(tmp_path, plant=[{"a": 1}], zombie=[{"b": 2}], baseline=[], recipes=[])
    fresh = check_2_dump_is_current(dump_dir)
    assert fresh.ok is True

    # Touching mtime alone (no byte change) must still pass.
    import os, time as _time
    p = dump_dir / "almanac" / "plant.json"
    os.utime(p, (_time.time() + 1000, _time.time() + 1000))
    still_fresh = check_2_dump_is_current(dump_dir)
    assert still_fresh.ok is True

    # Changing one byte must fail, even though mtime says nothing new happened structurally.
    p.write_text(json.dumps([{"a": 1}, {"a": 2}]), encoding="utf-8")
    stale = check_2_dump_is_current(dump_dir)
    assert stale.ok is False
    assert stale.action == "ask"


def test_truncated_dump_refuses_never_asks(tmp_path: Path):
    dump_dir = write_dump(tmp_path, plant=[{"a": 1}, {"a": 2}], zombie=[], baseline=[], recipes=[])
    # Manifest says 2 plant rows; truncate the file to 1 after the manifest was written.
    (dump_dir / "almanac" / "plant.json").write_text(json.dumps([{"a": 1}]), encoding="utf-8")
    result = check_3_dump_is_complete(dump_dir)
    assert result.ok is False
    assert result.action == "refuse"


def test_hash_matches_the_real_committed_dump():
    # No fixture — this module's hash algorithm must agree byte-for-byte with the C#
    # DumpWriter.ComputeContentHash that actually wrote gk-data/packs/fusion/data/seed/creatures/_dump.
    result = check_2_dump_is_current(DEFAULT_DUMP_DIR)
    assert result.ok is True, result


# --- check 4: contract audit --------------------------------------------------------------


def test_contract_audits_clean_against_the_real_schema():
    result = check_4_contract_audits_clean()
    assert result.ok is True


# --- checks 5/6: model, stubbed -------------------------------------------------------------


def test_schema_ignoring_model_refuses():
    def fake_call(system, user, schema):
        return "Sure! Here's some prose, not JSON at all."

    c5, c6, model_id = check_5_and_6_model(call_model_fn=fake_call)
    assert c5.ok is True   # it DID answer
    assert c6.ok is False  # but it ignored the schema
    assert c6.action == "refuse"


def test_model_honouring_schema_passes_both_checks():
    def fake_call(system, user, schema):
        return json.dumps({"acknowledged": True, "note": "preflight-probe"})

    c5, c6, model_id = check_5_and_6_model(call_model_fn=fake_call)
    assert c5.ok is True
    assert c6.ok is True


def test_model_returning_extra_keys_fails_schema_check():
    def fake_call(system, user, schema):
        return json.dumps({"acknowledged": True, "note": "preflight-probe", "extra": "field"})

    c5, c6, _ = check_5_and_6_model(call_model_fn=fake_call)
    assert c5.ok is True
    assert c6.ok is False


def test_unreachable_model_asks_not_refuses():
    def fake_call(system, user, schema):
        raise RuntimeError("connection refused")

    c5, c6, _ = check_5_and_6_model(call_model_fn=fake_call)
    assert c5.ok is False
    assert c5.action == "ask"
    assert c6.ok is False  # cascades — nothing to check


# --- checks 7-9 ------------------------------------------------------------------------------


def test_venv_lock_missing_file_asks(tmp_path: Path):
    result = check_7_venv_and_lock_current(tmp_path / "nope.lock")
    assert result.ok is False
    assert result.action == "ask"


def test_venv_lock_mismatch_names_the_package(tmp_path: Path):
    lock = tmp_path / "requirements.lock"
    lock.write_text("this-package-does-not-exist-anywhere==99.99.99\n", encoding="utf-8")
    result = check_7_venv_and_lock_current(lock)
    assert result.ok is False
    assert "this-package-does-not-exist-anywhere" in result.observed


def test_tuning_present_against_the_real_file():
    result = check_8_tuning_present()
    assert result.ok is True


def test_disk_headroom_ask_when_threshold_impossibly_high(tmp_path: Path):
    result = check_9_disk_headroom(tmp_path, min_bytes=10**18)  # an exabyte — always fails
    assert result.ok is False
    assert result.action == "ask"


# --- structural rules --------------------------------------------------------------------


def test_every_failure_names_a_fix_command():
    # CheckResult's own __post_init__ enforces this for every individual result already
    # constructed above; this test additionally proves it over a real full report with real
    # failures (an intentionally empty/missing dump dir forces several checks to fail).
    report = run_preflight(dump_dir=Path("/nonexistent/dump/dir/for/preflight/test"),
                           lock_path=Path("/nonexistent/lock/for/preflight/test"),
                           skip_model=True)
    assert not report.full_pass
    for c in report.checks:
        if not c.ok:
            assert c.fix_command, f"check {c.id} ({c.name}) failed with no fix_command"


def test_preflight_record_is_written_only_on_full_pass(tmp_path: Path):
    dump_dir = write_dump(tmp_path, plant=[{"a": 1}], zombie=[], baseline=[], recipes=[], corrupt_hash=True)
    bad_report = PreflightReport(
        checks=(check_1_dump_exists(dump_dir), check_2_dump_is_current(dump_dir)),
        dump_hash=None, model_id=None)
    assert bad_report.full_pass is False
    path = write_preflight_record(bad_report, dump_dir=dump_dir, lock_path=tmp_path / "nope.lock", skip_model=True)
    assert path is None
    assert not (dump_dir / "_preflight.json").exists()

    good_report = PreflightReport(checks=(check_1_dump_exists(dump_dir),), dump_hash="deadbeef", model_id=None)
    assert good_report.full_pass is True
    path2 = write_preflight_record(good_report, dump_dir=dump_dir, lock_path=tmp_path / "nope.lock", skip_model=True)
    assert path2 is not None
    written = json.loads(path2.read_text(encoding="utf-8"))
    assert written["dumpHash"] == "deadbeef"
    assert written["skipModel"] is True


def test_skip_model_record_is_rejected_by_run_control():
    # run-control (T2.8/2.9) is not built yet — pinning the CONTRACT it must enforce: a
    # skip-model record must be visibly tagged so that module can refuse it before a real run
    # (spec's own escape-hatch rule — "--skip-model ... is refused by run-control").
    report = PreflightReport(checks=(), dump_hash="abc", model_id=None)
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        dump_dir = Path(d)
        path = write_preflight_record(report, dump_dir=dump_dir, lock_path=Path(d) / "nope.lock", skip_model=True)
        record = json.loads(path.read_text(encoding="utf-8"))
        assert record["skipModel"] is True, \
            "a skip-model preflight record must self-identify so run-control can refuse it"


def test_every_check_is_reachable_from_the_committed_module():
    # No check exists only in the gitignored skill — all nine are plain functions in this file.
    import seedsmith.adapters.creatures.preflight as mod
    for i in (1, 2, 3, 4, 5, 7, 8, 9):
        assert any(f"check_{i}" in name for name in dir(mod)), f"check {i} not found in preflight.py"
    assert "check_5_and_6_model" in dir(mod)  # check 6 is folded into the same function as 5


def test_skip_model_runs_only_seven_checks(tmp_path: Path):
    dump_dir = write_dump(tmp_path, plant=[{"a": 1}], zombie=[], baseline=[], recipes=[])
    report = run_preflight(dump_dir=dump_dir, lock_path=tmp_path / "nope.lock", skip_model=True)
    assert len(report.checks) == 7
    assert {c.id for c in report.checks} == {1, 2, 3, 4, 7, 8, 9}
