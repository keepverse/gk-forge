"""Regression tests for the BCU2.12 report's completeness join.

The report is allowed to use a real local run, but its own census is pure file/JSON logic. These
fixtures therefore stay in pytest's temp directory and never touch the committed passive-tree corpus.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

# `.claude/cmdc-agents/scripts/` is the WORKSPACE ROOT's lane tooling - gk-workflow's - and gk-forge has no
# `.claude/` directory at all. Built from `parents[3]`, which is gk-forge's own root, this raised at IMPORT
# time and took the whole seedsmith suite's collection down with it:
#
#     ERROR collecting tests/test_bcu212_report.py - FileNotFoundError: ... gk-forge\.claude\cmdc-agents\
#     scripts\bcu212-report.py
#
# Measured: the file exists at the workspace root and nowhere else. `workspace_root` rather than
# `root_carrying`, because this runs once at import of a file that lives in the real tree - unlike the 138
# seedsmith modules the rewriter touched, which must also survive being copied to a temp directory as a
# mutant, and where the strict accessor would raise. That distinction is the reason there are two
# non-raising helpers.
import sys as _sys

_sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from seedsmith.workspace_roots import workspace_root  # noqa: E402

SCRIPT = workspace_root() / ".claude" / "cmdc-agents" / "scripts" / "bcu212-report.py"
_spec = importlib.util.spec_from_file_location("bcu212_report", SCRIPT)
assert _spec is not None and _spec.loader is not None
report = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(report)


def _write_species(root: Path, species_id: str, *, codex_summary: str | None,
                   codex_reason: str | None = None) -> None:
    path = root / "species" / f"{species_id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "schemaVersion": 1,
        "speciesId": species_id,
        "codexSummary": codex_summary,
        "codexUnresolvedReason": codex_reason,
    }), encoding="utf-8")


def test_complete_requires_nodes_ledger_backing_and_a_real_codex_summary(tmp_path, monkeypatch,
                                                                        capsys) -> None:
    seed = tmp_path / "data" / "seed" / "passive-tree"
    expected_nodes = report.EXPECTED_NODES_PER_SPECIES
    roster = ["Alpha", "Bravo", "Charlie"]

    for species_id in roster:
        node_path = seed / "nodes" / f"{species_id}.json"
        node_path.parent.mkdir(parents=True, exist_ok=True)
        node_path.write_text(json.dumps({"nodes": [{} for _ in range(expected_nodes)]}),
                             encoding="utf-8")

    _write_species(seed, "Alpha", codex_summary="Rewards patient, steady offense.")
    _write_species(seed, "Bravo", codex_summary=None, codex_reason="vote_unresolved")
    _write_species(seed, "Charlie", codex_summary="Rewards bold, aggressive offense.")

    ledger_path = seed / "_runs" / "tree-language.ledger.json"
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    done = {}
    for species_id, accepted in (("Alpha", expected_nodes),
                                 ("Bravo", expected_nodes),
                                 ("Charlie", expected_nodes - 1)):
        for index in range(accepted):
            subject = f"{species_id}:skill.{species_id}-off-t1-n{index}"
            done[subject] = {"record": {"id": subject}}
    ledger_path.write_text(json.dumps({"schemaVersion": 1, "done": done}), encoding="utf-8")
    batch_path = tmp_path / "tools" / "seedsmith" / "_j9_batch_run_results.json"
    batch_path.parent.mkdir(parents=True, exist_ok=True)
    batch_path.write_text(json.dumps([{"speciesId": "Alpha", "hardGate": "FAIL"}]), encoding="utf-8")

    monkeypatch.setattr(report, "ROOT", tmp_path)
    monkeypatch.setattr(report, "OUT", tmp_path / "tasks" / "reports" / "BCU2.12-full-run.json")
    monkeypatch.setattr(report, "SEED", seed)

    roster_commands = []

    def fake_roster(python_command=None):
        roster_commands.append(python_command)
        return list(roster)

    monkeypatch.setattr(report, "roster_ids", fake_roster)

    def fake_sh(*args: str) -> str:
        if args[:2] == ("git", "rev-parse"):
            return "fixture"
        if args[0] == "selected-python" and args[1:4] == ("-m", "seedsmith", "check"):
            return "[NOTE] fixture"
        return ""

    monkeypatch.setattr(report, "sh", fake_sh)
    assert report.main(["--python", "selected-python"]) == 0
    capsys.readouterr()
    document = json.loads(report.OUT.read_text(encoding="utf-8"))
    census = document["census"]

    assert roster_commands == ["selected-python"]
    assert document["pythonCommand"] == "selected-python"

    assert census["complete"]["count"] == 1
    assert census["complete"]["sample"] == ["Alpha"]
    assert census["nodesWithoutCodexSupplement"]["count"] == 1
    assert census["nodesWithoutCodexSupplement"]["sample"] == ["Bravo"]
    assert census["startedIncomplete"]["count"] == 1
    assert "Charlie" in census["startedIncomplete"]["sample"]
    assert document["batchResultsLastPassOnly"]["hardGateFailures"] == [
        {"speciesId": "Alpha", "hardGate": "FAIL"}]


def _write_complete_ledger(seed: Path, species_ids: list[str], node_count: int) -> None:
    done = {}
    for species_id in species_ids:
        for index in range(node_count):
            subject = f"{species_id}:skill.{species_id}-off-t1-n{index}"
            done[subject] = {"record": {"id": subject}}
    path = seed / "_runs" / "tree-language.ledger.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"schemaVersion": 1, "done": done}), encoding="utf-8")


def _configure_report_fixture(monkeypatch, tmp_path: Path, seed: Path, roster: list[str]) -> None:
    monkeypatch.setattr(report, "ROOT", tmp_path)
    monkeypatch.setattr(report, "OUT", tmp_path / "tasks" / "reports" / "BCU2.12-full-run.json")
    monkeypatch.setattr(report, "SEED", seed)
    monkeypatch.setattr(report, "roster_ids", lambda _python_command=None: list(roster))

    def fake_sh(*args: str) -> str:
        if args[:2] == ("git", "rev-parse"):
            return "fixture"
        if args[0] == "selected-python" and args[1:4] == ("-m", "seedsmith", "check"):
            return "[NOTE] fixture"
        return ""

    monkeypatch.setattr(report, "sh", fake_sh)


def test_malformed_node_json_is_named_and_cannot_become_untouched(tmp_path, monkeypatch,
                                                                  capsys) -> None:
    seed = tmp_path / "data" / "seed" / "passive-tree"
    species_id = "BrokenNode"
    node_path = seed / "nodes" / f"{species_id}.json"
    node_path.parent.mkdir(parents=True)
    node_path.write_text("{ this is not JSON", encoding="utf-8")
    _write_species(seed, species_id, codex_summary="A valid supplement beside a broken tree.")
    _write_complete_ledger(seed, [species_id], report.EXPECTED_NODES_PER_SPECIES)
    _configure_report_fixture(monkeypatch, tmp_path, seed, [species_id])

    assert report.main(["--python", "selected-python"]) == 1
    capsys.readouterr()
    document = json.loads(report.OUT.read_text(encoding="utf-8"))
    errors = document["evidenceErrors"]["nodes"]

    assert any("BrokenNode.json" in path and "JSONDecodeError" in detail
               for path, detail in errors.items())
    assert document["census"]["malformedEvidence"]["count"] == 1
    assert document["census"]["untouched"] == 0
    assert document["census"]["complete"]["count"] == 0
    assert document["reportStatus"] == "error"


def test_malformed_species_json_is_named_and_cannot_become_complete(tmp_path, monkeypatch,
                                                                     capsys) -> None:
    seed = tmp_path / "data" / "seed" / "passive-tree"
    species_id = "BrokenSpecies"
    node_path = seed / "nodes" / f"{species_id}.json"
    node_path.parent.mkdir(parents=True)
    node_path.write_text(json.dumps({"nodes": [{} for _ in range(report.EXPECTED_NODES_PER_SPECIES)]}),
                         encoding="utf-8")
    species_path = seed / "species" / f"{species_id}.json"
    species_path.parent.mkdir(parents=True)
    species_path.write_text("{ this is not JSON", encoding="utf-8")
    _write_complete_ledger(seed, [species_id], report.EXPECTED_NODES_PER_SPECIES)
    _configure_report_fixture(monkeypatch, tmp_path, seed, [species_id])

    assert report.main(["--python", "selected-python"]) == 1
    capsys.readouterr()
    document = json.loads(report.OUT.read_text(encoding="utf-8"))
    errors = document["evidenceErrors"]["species"]

    assert any("BrokenSpecies.json" in path and "JSONDecodeError" in detail
               for path, detail in errors.items())
    assert document["census"]["malformedEvidence"]["count"] == 1
    assert document["census"]["untouched"] == 0
    assert document["census"]["complete"]["count"] == 0
    assert document["reportStatus"] == "error"


def test_roster_reader_uses_the_injected_python_command(monkeypatch) -> None:
    calls = []

    def fake_sh(*args: str) -> str:
        calls.append(args)
        return "Alpha\nBravo\n"

    monkeypatch.setattr(report, "sh", fake_sh)
    assert report.roster_ids("selected-python") == ["Alpha", "Bravo"]
    assert calls[0][0] == "selected-python"
