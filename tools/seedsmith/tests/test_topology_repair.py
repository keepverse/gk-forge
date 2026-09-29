"""species-gear-chain T27 (`set-species-binding` a, `setClass` half) — the deterministic backward
re-plan over the shipped corpus.

    python -m pytest gk-forge/tools/seedsmith/tests/test_topology_repair.py -q

⛔ **Nothing here pins a population.** How many entries land on `general` and how many on `family` is
a READING that moves whenever content ships; `test_the_real_corpus_plan_reconciles_and_prints_its_
tally` prints it and asserts only the closure property (every entry resolves, every resolved entry
satisfies its own class). The write-path assertions run against a PRIVATE COPY of the real corpus, so
a test can never rewrite the committed tree — the rule this repo spent a 65.5 GB temp-dir leak
learning (`docs/contributing/testing-standard.md`).
"""
from __future__ import annotations

import glob
import json
import shutil
import tempfile
from pathlib import Path

import pytest

from seedsmith.adapters.items.setgen import species_repair as species_repair_mod
from seedsmith.adapters.items.setgen import topology as topology_mod
from seedsmith.adapters.items.setgen import topology_repair as repair_mod
from seedsmith.report.cli import EXIT_CLEAN, EXIT_REFUSED, main

REPO_ROOT = Path(__file__).resolve().parents[3]
SETS_DIR = REPO_ROOT / "data" / "seed" / "items" / "sets"

UNCLASSIFIABLE = {
    "schemaVersion": 1,
    "kind": "set",
    "entries": [
        {
            "id": "set.unclassifiable-001",
            "nameKey": "set.unclassifiable",
            "name": "Unclassifiable",
            "themeKey": "creature.unclassifiable",
            "members": [{"role": "core-guard", "frame": "plant", "baseType": "item.plant-stem-1"}],
            "thresholds": [{"pieces": pieces} for pieces in (2, 3, 4, 5, 6)],
        }
    ],
}


def _stamped(entry: dict) -> dict:
    """The entry without its class field — what the repair must leave byte-identical."""
    return {key: value for key, value in entry.items() if key != "setClass"}


def _unstamped_count(directory: Path) -> int:
    """How many entries the next write is expected to change. Computed from the partition rather than
    hard-coded: on a fresh corpus every entry changes, on an already-repaired one none does — and the
    committed corpus IS already repaired, so a test that assumed the former would only pass on the
    day it was written."""
    tuning = topology_mod.load()
    return sum(1 for entry in _entries(directory)
               if entry.get("setClass") != topology_mod.resolve_class(entry, tuning).class_id)


def _copied_corpus(root: Path) -> Path:
    target = root / "sets"
    shutil.copytree(SETS_DIR, target)
    return target


def _entries(directory: Path) -> "list[dict]":
    out: "list[dict]" = []
    for name in sorted(glob.glob(str(directory / "*.json"))):
        document = json.loads(Path(name).read_text(encoding="utf-8"))
        out.extend(document.get("entries") or ())
    return out


# --------------------------------------------------------------------------------------------
# the real corpus — a plan, a printed reading, and closure
# --------------------------------------------------------------------------------------------


def test_the_real_corpus_plan_resolves_every_entry_and_reconciles():
    result = repair_mod.repair_set_classes(sets_dir=SETS_DIR, write=False)
    tuning = topology_mod.load()
    assert result.entries > 0
    # Closure/reconciliation, never a population count: every entry landed in exactly one declared
    # class, and the per-class tally accounts for all of them.
    assert set(result.tally) <= set(tuning.class_ids)
    assert sum(result.tally.values()) == result.entries


def test_the_real_corpus_plan_is_deterministic():
    first = repair_mod.repair_set_classes(sets_dir=SETS_DIR, write=False)
    second = repair_mod.repair_set_classes(sets_dir=SETS_DIR, write=False)
    assert first.tally == second.tally
    assert first.changed_entries == second.changed_entries
    assert [f.path for f in first.files] == [f.path for f in second.files]


def test_the_plan_writes_nothing_without_write(capsys):
    before = {p: p.read_bytes() for p in sorted(SETS_DIR.glob("*.json"))}
    repair_mod.repair_set_classes(sets_dir=SETS_DIR, write=False)
    assert {p: p.read_bytes() for p in sorted(SETS_DIR.glob("*.json"))} == before


def test_report_prints_the_real_corpus_tally_as_a_reading():
    """⭐ A READING, printed and never asserted — the shipped corpus grows whenever content ships, so a
    test pinning `general 906` would fail on the normal case and its "fix" would be to bump a number."""
    result = repair_mod.repair_set_classes(sets_dir=SETS_DIR, write=False)
    report = repair_mod.repair_report(result, write=False)
    print("\nsetClass re-plan reading (printed, not asserted):")
    print(f"  entries {report['entries']}  files {report['changedFiles']}")
    for class_id, count in report["resolvedByClass"].items():
        print(f"  {class_id:<15} {count}")


# --------------------------------------------------------------------------------------------
# the write path — private copy, idempotence, and refusal
# --------------------------------------------------------------------------------------------


def test_applying_the_plan_stamps_every_entry_and_keeps_every_other_key():
    with tempfile.TemporaryDirectory() as temp:
        sets = _copied_corpus(Path(temp))
        before = {entry["id"]: _stamped(entry) for entry in _entries(sets)}
        expected_changes = _unstamped_count(sets)
        original_order = {path.name: list(json.loads(path.read_text(encoding="utf-8")))
                          for path in sorted(sets.glob("*.json"))}

        result = repair_mod.repair_set_classes(sets_dir=sets, write=True)
        assert result.changed_entries == expected_changes

        tuning = topology_mod.load()
        after = _entries(sets)
        assert len(after) == len(before)
        for entry in after:
            assert "setClass" in entry, entry["id"]
            assert entry["setClass"] in tuning.class_ids
            # The class restates the entry's own shape: re-resolving what was written must agree.
            assert entry["setClass"] == topology_mod.resolve_class(entry, tuning).class_id
            # Beside themeKey, so a corpus diff is one added line per entry.
            keys = list(entry)
            assert keys[keys.index("themeKey") + 1] == "setClass"
            # Every OTHER key is identical to what the entry carried before.
            assert _stamped(entry) == before[entry["id"]]
        # The partition envelope and its key order are untouched.
        for path in sorted(sets.glob("*.json")):
            assert list(json.loads(path.read_text(encoding="utf-8"))) == original_order[path.name]


def test_a_second_apply_changes_nothing_and_is_byte_identical():
    with tempfile.TemporaryDirectory() as temp:
        sets = _copied_corpus(Path(temp))
        repair_mod.repair_set_classes(sets_dir=sets, write=True)
        first = {p.name: p.read_bytes() for p in sorted(sets.glob("*.json"))}

        second = repair_mod.repair_set_classes(sets_dir=sets, write=True)
        assert second.changed_entries == 0
        assert second.changed_files == 0
        assert {p.name: p.read_bytes() for p in sorted(sets.glob("*.json"))} == first


def test_written_partitions_are_lf_only():
    """The sibling creature-theme writers shipped CRLF on Windows and dirtied 17,491 lines of a file
    they meant to touch once; this repair must not repeat it."""
    with tempfile.TemporaryDirectory() as temp:
        sets = _copied_corpus(Path(temp))
        repair_mod.repair_set_classes(sets_dir=sets, write=True)
        for path in sorted(sets.glob("*.json")):
            assert b"\r\n" not in path.read_bytes(), path.name


def test_every_written_class_satisfies_its_own_template():
    """The written class must satisfy the class template it names — a repair that stamped `general`
    unconditionally would pass the idempotence tests and fail this one. The `family` count is printed
    as a reading rather than asserted: it is a population that moves when content ships."""
    with tempfile.TemporaryDirectory() as temp:
        sets = _copied_corpus(Path(temp))
        repair_mod.repair_set_classes(sets_dir=sets, write=True)
        tuning = topology_mod.load()
        family = 0
        for entry in _entries(sets):
            shape = topology_mod.declared_topology(entry)
            rule = tuning.klass(entry["setClass"])
            if rule.parameterized:
                assert shape.distinct_roles in rule.member_role_set
            assert shape.distinct_roles >= rule.member_role_min
            assert len(shape.thresholds) <= rule.bonus_tier_ceiling
            assert shape.thresholds[0] == tuning.mandatory_first_pieces
            if entry["setClass"] == "family":
                family += 1
                assert shape.distinct_roles >= 5 and len(shape.thresholds) <= 3
        print(f"\nfamily entries after the re-plan (printed, not asserted): {family}")


def test_an_unclassifiable_entry_refuses_the_whole_run_and_writes_nothing():
    with tempfile.TemporaryDirectory() as temp:
        sets = Path(temp) / "sets"
        sets.mkdir(parents=True)
        good = {"kind": "set", "entries": [
            {"id": "set.fine-001", "nameKey": "set.fine", "name": "Fine",
             "themeKey": "creature.fine",
             "members": [{"role": r, "frame": "plant"}
                         for r in ("core-guard", "jewel-major", "manipulator", "footing")],
             "thresholds": [{"pieces": 2}, {"pieces": 4}]}]}
        (sets / "aaa-fine.json").write_text(json.dumps(good), encoding="utf-8")
        (sets / "zzz-bad.json").write_text(json.dumps(UNCLASSIFIABLE), encoding="utf-8")
        before = {p.name: p.read_bytes() for p in sorted(sets.glob("*.json"))}

        with pytest.raises(topology_mod.SetTopologyError) as caught:
            repair_mod.repair_set_classes(sets_dir=sets, write=True)
        message = str(caught.value)
        assert "zzz-bad.json" in message and "set.unclassifiable-001" in message
        # Refused means NOTHING was written, including the partition that resolves cleanly.
        assert {p.name: p.read_bytes() for p in sorted(sets.glob("*.json"))} == before


def test_stamp_class_refuses_an_entry_with_no_themeKey():
    with pytest.raises(topology_mod.SetTopologyError):
        topology_mod.stamp_class({"id": "set.themeless-001", "members": [], "thresholds": []},
                                 topology_mod.load())


# --------------------------------------------------------------------------------------------
# the CLI verb
# --------------------------------------------------------------------------------------------


def test_the_cli_dry_run_plans_without_writing(capsys):
    assert main(["items", "repair-set-class"]) == EXIT_CLEAN
    report = json.loads(capsys.readouterr().out)
    assert report["write"] is False
    assert report["entries"] == sum(report["resolvedByClass"].values())


def test_the_cli_refuses_a_production_write_without_the_explicit_flag(capsys):
    assert main(["items", "repair-set-class", "--write"]) == EXIT_REFUSED
    assert "allow-production-tree" in capsys.readouterr().err


def test_the_cli_writes_a_private_tree_and_is_idempotent(capsys):
    with tempfile.TemporaryDirectory() as temp:
        sets = _copied_corpus(Path(temp))
        expected_changes = _unstamped_count(sets)
        assert main(["items", "repair-set-class", "--write", "--sets-dir", str(sets)]) == EXIT_CLEAN
        first = json.loads(capsys.readouterr().out)
        assert first["changedEntries"] == expected_changes
        assert all("setClass" in entry for entry in _entries(sets))
        assert main(["items", "repair-set-class", "--write", "--sets-dir", str(sets)]) == EXIT_CLEAN
        second = json.loads(capsys.readouterr().out)
        assert second["changedEntries"] == 0
        assert second["changedFiles"] == 0


def test_the_shared_writer_is_the_one_species_repair_uses():
    """Both repairs write the same corpus, so they must agree byte for byte about serialisation —
    otherwise running them in sequence produces a diff line nobody asked for."""
    assert species_repair_mod.write_document is repair_mod.write_document


def test_the_writer_preserves_the_partitions_own_ascii_escaping_style():
    """⭐ Measured on the real corpus: six of the legacy partitions ship `\\u00a7`/`\\u2014` escapes
    while the other 878 ship raw UTF-8. A writer that fixes `ensure_ascii` either way rewrites
    unrelated `notes`/`flavor` lines — so the ONE-LINE-PER-ENTRY diff this repair promises would
    carry six lines nobody asked for. The style is taken from the file being rewritten."""
    with tempfile.TemporaryDirectory() as temp:
        escaped = Path(temp) / "escaped.json"
        raw = Path(temp) / "raw.json"
        escaped.write_text(json.dumps({"value": "a \u00a7 b"}, indent=2) + "\n", encoding="utf-8")
        raw.write_text(json.dumps({"value": "a \u00a7 b"}, ensure_ascii=False, indent=2) + "\n",
                       encoding="utf-8")

        species_repair_mod.write_document(escaped, {"value": "a \u00a7 b"})
        species_repair_mod.write_document(raw, {"value": "a \u00a7 b"})

        assert escaped.read_bytes() == (json.dumps({"value": "a \u00a7 b"}, indent=2) + "\n"
                                        ).encode("utf-8")
        assert raw.read_bytes() == (json.dumps({"value": "a \u00a7 b"}, ensure_ascii=False,
                                                indent=2) + "\n").encode("utf-8")


def test_the_real_partitions_keep_their_escaping_style_through_a_write():
    """The same property over the corpus itself: a partition whose committed bytes carry `\\u` and no
    raw non-ASCII must still carry `\\u` after the repair (and vice versa)."""
    with tempfile.TemporaryDirectory() as temp:
        sets = _copied_corpus(Path(temp))
        escaped_before = {p.name for p in sorted(sets.glob("*.json"))
                          if "\\u" in p.read_text(encoding="utf-8")
                          and not any(ord(c) > 127 for c in p.read_text(encoding="utf-8"))}
        assert escaped_before, "the corpus no longer has an escaped partition — this test is dead"

        repair_mod.repair_set_classes(sets_dir=sets, write=True)

        for path in sorted(sets.glob("*.json")):
            text = path.read_text(encoding="utf-8")
            raw_non_ascii = any(ord(c) > 127 for c in text)
            if path.name in escaped_before:
                assert not raw_non_ascii, f"{path.name} gained literal non-ASCII it did not ship"
            else:
                assert raw_non_ascii or "\\u" not in text
