"""Tests for the `run-control` execution driver (spec-run-control.md, creature-seed module 9).

Uses `test_run_orchestrator.py`'s own `always_valid_call` stub — the REAL LangGraph pipeline
graphs run end to end, only the network call is replaced, so these tests exercise the actual
`run_one_species`/anchor-emit/record wiring, never a re-implementation of it.
"""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import pytest

pytest.importorskip("langgraph.graph")

from seedsmith.adapters.creatures.anchor.prompts import PIPELINES  # noqa: E402
from seedsmith.adapters.creatures.power.bands import classify as classify_threat  # noqa: E402
from seedsmith.adapters.creatures.power.parse import parse_power_seed  # noqa: E402
from seedsmith.adapters.creatures.preflight import PREFLIGHT_RECORD_NAME, _compute_content_hash  # noqa: E402
from seedsmith.adapters.creatures.run import runner  # noqa: E402
from seedsmith.adapters.creatures.run.record import RunRecord, write_record  # noqa: E402
from test_run_orchestrator import always_valid_call  # noqa: E402

# Every SPECIES row below has statsObserved=True -> basis="observed" -> threat-audit is NOT one of
# the voted pipelines (Q26: only inferred/blocked genuinely choose a rung — observed/stated AUDIT
# a deterministic computed one). So 5 of the 8 pipelines vote (3 samples each) and 3 don't (1 each):
# 5*3 + 3*1 = 18, never a flat `len(PIPELINES)` (spec-option-permutation.md §6's own budget).
# `attackTempo` (kit-shape) joined the voted 5 on 2026-09-04 (creature-corpus-self-heal C1) — was 16
# (4*3 + 4*1) before kit-shape was wired into voting/permutation at all.
CALLS_PER_OBSERVED_SPECIES = 18


def make_dump(tmp_path: Path, species: "list[dict]") -> Path:
    """A minimal, real-shaped corpus-dump tree — same row schema `dump_ctx.py`/`preflight.py`
    actually read (side/typeId/typeName/displayName/flavorInfo/hp/attack/statsObserved)."""
    dump_dir = tmp_path / "_dump"
    almanac = dump_dir / "almanac"
    almanac.mkdir(parents=True)
    plants = [s for s in species if s["side"] == "plant"]
    zombies = [s for s in species if s["side"] == "zombie"]
    (almanac / "plant.json").write_text(json.dumps(plants), encoding="utf-8")
    (almanac / "zombie.json").write_text(json.dumps(zombies), encoding="utf-8")
    # `_compute_content_hash` (preflight.py) hashes all FOUR payload files together — these two
    # are otherwise-unused-by-this-test but must exist or the hash is None on every dump,
    # silently defeating any test that checks the hash actually changed.
    (dump_dir / "spawn-baseline.json").write_text("[]", encoding="utf-8")
    (dump_dir / "recipes.json").write_text("[]", encoding="utf-8")
    (dump_dir / "_manifest.json").write_text(
        json.dumps({"plantCount": len(plants), "zombieCount": len(zombies)}), encoding="utf-8")
    return dump_dir


def species_row(species_id: str, side: str, type_id: int) -> dict:
    return {
        "side": side, "typeId": type_id, "typeName": species_id, "displayName": species_id,
        "flavorInfo": f"{species_id} flavor text, no numbers spoken here.",
        "flavorIntroduce": None, "hp": 300, "attack": 20, "statsObserved": True,
        "enrichment": None,
    }


SPECIES = [species_row("alpha", "plant", 1), species_row("beta", "plant", 2)]


def write_real_preflight(dump_dir: Path) -> None:
    dump_hash = _compute_content_hash(dump_dir)
    record = {"dumpHash": dump_hash, "modelId": "stub", "lockHash": None, "skipModel": False,
              "writtenUtc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    (dump_dir / PREFLIGHT_RECORD_NAME).write_text(json.dumps(record), encoding="utf-8")


def make_paths(tmp_path: Path, species=SPECIES) -> runner.RunPaths:
    dump_dir = make_dump(tmp_path, species)
    write_real_preflight(dump_dir)
    return runner.RunPaths(
        dump_dir=dump_dir, anchors_dir=tmp_path / "species", runs_dir=tmp_path / "_runs",
        family_assignments=tmp_path / "families.json")  # absent on purpose: falls back to "unclassified"


def test_start_classifies_every_selected_species_and_writes_anchor_files(tmp_path):
    paths = make_paths(tmp_path)
    record = runner.start({"kind": "all"}, paths=paths, call=always_valid_call)

    assert record.state == "completed"
    assert sorted(record.completed) == ["alpha", "beta"]
    assert record.calls_made == 2 * CALLS_PER_OBSERVED_SPECIES

    index = json.loads((paths.anchors_dir / "_index.json").read_text(encoding="utf-8"))
    assert set(index) == {"alpha", "beta"}
    for species_id, rel in index.items():
        entries = json.loads((paths.anchors_dir / rel).read_text(encoding="utf-8"))
        assert any(e["speciesId"] == species_id for e in entries)
        entry = next(e for e in entries if e["speciesId"] == species_id)
        assert entry["_provenance"]["dumpHash"] == record.dump_hash
        assert "_derived" in entry


def test_skip_model_preflight_cannot_start_a_run(tmp_path):
    paths = make_paths(tmp_path)
    dump_hash = _compute_content_hash(paths.dump_dir)
    (paths.dump_dir / PREFLIGHT_RECORD_NAME).write_text(
        json.dumps({"dumpHash": dump_hash, "skipModel": True}), encoding="utf-8")

    with pytest.raises(runner.RunRefused, match="skip-model"):
        runner.start({"kind": "all"}, paths=paths, call=always_valid_call)


def test_no_preflight_record_cannot_start(tmp_path):
    paths = make_paths(tmp_path)
    (paths.dump_dir / PREFLIGHT_RECORD_NAME).unlink()

    with pytest.raises(runner.RunRefused, match="preflight"):
        runner.start({"kind": "all"}, paths=paths, call=always_valid_call)


def test_pause_never_splits_a_species_and_resume_makes_no_new_call_for_it(tmp_path):
    paths = make_paths(tmp_path)
    calls = {"n": 0}

    def counting_call(system, user, *, config=None, schema=None):
        calls["n"] += 1
        return always_valid_call(system, user, config=config, schema=schema)

    seen: "list[str]" = []

    def progress(species_id, done, total):
        seen.append(species_id)
        if len(seen) == 1:
            runner.request_pause(paths=paths)  # pause is polled BETWEEN species only

    record = runner.start({"kind": "all"}, paths=paths, call=counting_call, progress=progress)
    assert record.state == "paused"
    assert len(record.completed) == 1  # the first species finished ALL eight pipelines
    calls_after_pause = calls["n"]
    assert calls_after_pause == CALLS_PER_OBSERVED_SPECIES  # one full species, never a partial one

    resumed = runner.resume(paths=paths, call=counting_call, progress=progress)
    assert resumed.state == "completed"
    assert sorted(resumed.completed) == ["alpha", "beta"]
    # the resumed species made exactly one more species' worth of calls — the paused one was
    # NOT re-classified (TRANSIENT semantics, spec §1).
    assert calls["n"] == calls_after_pause + CALLS_PER_OBSERVED_SPECIES


def test_resume_against_changed_dump_refuses(tmp_path):
    paths = make_paths(tmp_path)

    def pause_after_first(system, user, *, config=None, schema=None):
        return always_valid_call(system, user, config=config, schema=schema)

    def progress(species_id, done, total):
        if done == 1:
            runner.request_pause(paths=paths)

    runner.start({"kind": "all"}, paths=paths, call=pause_after_first, progress=progress)

    # The dump changes underneath the paused run (a new corpus-dump was captured).
    (paths.dump_dir / "almanac" / "plant.json").write_text(
        json.dumps([species_row("alpha", "plant", 1), species_row("gamma", "plant", 3)]),
        encoding="utf-8")

    with pytest.raises(runner.RunRefused, match="changed"):
        runner.resume(paths=paths, call=always_valid_call)


def test_dead_process_record_offers_resume_not_a_permanent_refusal(tmp_path):
    paths = make_paths(tmp_path)
    dump_hash = _compute_content_hash(paths.dump_dir)
    dead_record = RunRecord(
        run_id="dead-run", state="running", preflight={"dumpHash": dump_hash}, dump_hash=dump_hash,
        selector={"kind": "all"}, prompt_versions={}, pid=999_999_999,  # never a real live pid
        completed=[], failed=[], started_utc="2020-01-01T00:00:00Z")
    write_record(dead_record, paths.current_record_path)

    resumed = runner.resume(paths=paths, call=always_valid_call)
    assert resumed.state == "completed"


def test_two_concurrent_starts_refuse_the_second(tmp_path):
    paths = make_paths(tmp_path)
    dump_hash = _compute_content_hash(paths.dump_dir)
    import os
    live_record = RunRecord(
        run_id="live-run", state="running", preflight={"dumpHash": dump_hash}, dump_hash=dump_hash,
        selector={"kind": "all"}, prompt_versions={}, pid=os.getpid(),  # THIS process — always alive
        completed=[], failed=[], started_utc="2020-01-01T00:00:00Z")
    write_record(live_record, paths.current_record_path)

    with pytest.raises(runner.RunRefused, match="live-run"):
        runner.start({"kind": "all"}, paths=paths, call=always_valid_call)


def test_cancel_marks_terminal_and_commits_the_record(tmp_path):
    paths = make_paths(tmp_path)

    def progress(species_id, done, total):
        if done == 1:
            runner.request_pause(paths=paths)

    runner.start({"kind": "all"}, paths=paths, call=always_valid_call, progress=progress)
    assert runner.status(paths=paths)["state"] == "paused"

    cancelled = runner.cancel(paths=paths)
    assert cancelled.state == "cancelled"
    assert not paths.current_record_path.exists()
    assert (paths.runs_dir / f"{cancelled.run_id}.json").exists()
    # the one species finished before the pause is a real, already-emitted seed — untouched.
    index = json.loads((paths.anchors_dir / "_index.json").read_text(encoding="utf-8"))
    assert "alpha" in index


def test_overwrite_all_requires_the_correct_token(tmp_path):
    paths = make_paths(tmp_path)
    with pytest.raises(runner.RunRefused, match="token"):
        runner.overwrite_all("wrong-token", paths=paths, call=always_valid_call)

    dump_hash = _compute_content_hash(paths.dump_dir)
    from seedsmith.adapters.creatures.run.record import overwrite_all_token
    token = overwrite_all_token(dump_hash)
    record = runner.overwrite_all(token, paths=paths, call=always_valid_call)
    assert record.state == "completed"


def test_rerun_reclassifies_even_an_already_emitted_species(tmp_path):
    paths = make_paths(tmp_path)
    runner.start({"kind": "all"}, paths=paths, call=always_valid_call)

    calls = {"n": 0}

    def counting_call(system, user, *, config=None, schema=None):
        calls["n"] += 1
        return always_valid_call(system, user, config=config, schema=schema)

    record = runner.rerun({"kind": "species", "species": ["alpha"]}, paths=paths, call=counting_call)
    assert record.state == "completed"
    assert record.completed == ["alpha"]
    assert calls["n"] == CALLS_PER_OBSERVED_SPECIES  # re-classified despite already being emitted


# ---- pipeline-scoped rerun (2026-09-04, creature-corpus-self-heal B1) -----------------------------
#
# Redeploying a fixed prompt used to mean either living with the stale field forever or paying for
# a full 8-pipeline reclassification of species that already have 7 perfectly good judgments.
# `{"kind": "pipeline", "pipeline": <id>}` re-executes ONLY that pipeline and merges its own
# output into the existing entry — everything else must stay byte-identical.

def test_a_pipeline_scoped_rerun_makes_one_call_per_species_not_eight(tmp_path):
    paths = make_paths(tmp_path)  # alpha, beta
    runner.start({"kind": "all"}, paths=paths, call=always_valid_call)

    calls = {"n": 0}

    def counting_call(system, user, *, config=None, schema=None):
        calls["n"] += 1
        return always_valid_call(system, user, config=config, schema=schema)

    record = runner.rerun({"kind": "pipeline", "pipeline": "kit-shape"}, paths=paths, call=counting_call)

    assert record.state == "completed"
    assert sorted(record.completed) == ["alpha", "beta"]
    # kit-shape's own attackTempo is voted (3 samples) since C1 (2026-09-04) -> 3 calls/species,
    # still far short of the full 8-pipeline reclassify's 18.
    assert calls["n"] == 6
    assert record.calls_made == 6


def test_a_pipeline_scoped_rerun_leaves_every_other_field_byte_identical(tmp_path):
    paths = make_paths(tmp_path, species=[species_row("alpha", "plant", 1)])
    runner.start({"kind": "all"}, paths=paths, call=always_valid_call)
    index = json.loads((paths.anchors_dir / "_index.json").read_text(encoding="utf-8"))
    rel = index["alpha"]
    before = json.loads((paths.anchors_dir / rel).read_text(encoding="utf-8"))[0]

    def different_kit_shape_call(system, user, *, config=None, schema=None):
        base = json.loads(always_valid_call(system, user, config=config, schema=schema))
        if "attackTempo" in base:
            base["attackTempo"] = "flurry"  # deliberately different from the stub's usual answer
        return json.dumps(base)

    runner.rerun({"kind": "pipeline", "pipeline": "kit-shape"}, paths=paths, call=different_kit_shape_call)

    index_after = json.loads((paths.anchors_dir / "_index.json").read_text(encoding="utf-8"))
    after = json.loads((paths.anchors_dir / index_after["alpha"]).read_text(encoding="utf-8"))[0]

    assert after["attackTempo"] == "flurry"  # the reran pipeline's own field DID change
    # every field NOT owned by kit-shape (attackTempo/reach/targetPreference/resourceProfile) is
    # untouched, proven field by field rather than trusting a partial spot check.
    kit_shape_fields = {"attackTempo", "reach", "targetPreference", "resourceProfile"}
    for key in before:
        if key in kit_shape_fields or key == "_provenance":
            continue
        assert after[key] == before[key], f"field {key!r} changed on a kit-shape-only rerun"


def test_a_rarity_only_scoped_rerun_recomputes_rank_and_never_leaves_it_stale(tmp_path):
    # rank is DERIVED from (threatBand, rarity), so a scoped rerun that moves ONLY rarity must move
    # rank with it. Without the merge path's recompute the species would keep its OLD rank beside
    # its new rarity — a stale derived field, which is the exact defect this test exists for.
    from seedsmith.adapters.creatures.anchor.derive import derive_rank

    paths = make_paths(tmp_path, species=[species_row("alpha", "plant", 1)])
    runner.start({"kind": "all"}, paths=paths, call=always_valid_call)

    # This fixture's observed-basis pass writes a threat-audit VERDICT, not a rung, so the species
    # reaches the entry with no threatBand and an explicitly unresolved rank — the real corpus's own
    # state for the 721/906 anchors that carried no threatBand (measured 2026-09-20).
    # `fix_unresolved` stamps the sanctioned rung AND recomputes rank from it: the fallback-stamped
    # input path (spec §1), which this sanity check also covers.
    runner.fix_unresolved(paths=paths)

    index = json.loads((paths.anchors_dir / "_index.json").read_text(encoding="utf-8"))
    before = json.loads((paths.anchors_dir / index["alpha"]).read_text(encoding="utf-8"))[0]
    assert before["threatBand"] not in (None, "unresolved")
    assert before["rank"] == derive_rank(before["threatBand"], before["rarity"])

    moved = "almanac" if before["rarity"] != "almanac" else "chaff"

    def different_rarity_call(system, user, *, config=None, schema=None):
        base = json.loads(always_valid_call(system, user, config=config, schema=schema))
        if "rarity" in base:
            base["rarity"] = moved  # deliberately different from the stub's usual answer
        return json.dumps(base)

    runner.rerun({"kind": "pipeline", "pipeline": "identity"}, paths=paths, call=different_rarity_call)

    index_after = json.loads((paths.anchors_dir / "_index.json").read_text(encoding="utf-8"))
    after = json.loads((paths.anchors_dir / index_after["alpha"]).read_text(encoding="utf-8"))[0]

    assert after["rarity"] == moved  # the reran pipeline's own field DID change
    assert after["threatBand"] == before["threatBand"]  # and nothing outside it did
    assert after["rank"] == derive_rank(after["threatBand"], after["rarity"])
    assert after["rank"] != before["rank"]


def test_a_pipeline_scoped_rerun_updates_only_the_reran_pipelines_own_provenance(tmp_path):
    paths = make_paths(tmp_path, species=[species_row("alpha", "plant", 1)])
    runner.start({"kind": "all"}, paths=paths, call=always_valid_call)
    index = json.loads((paths.anchors_dir / "_index.json").read_text(encoding="utf-8"))
    before = json.loads((paths.anchors_dir / index["alpha"]).read_text(encoding="utf-8"))[0]
    other_pipeline_attempts_before = {
        k: v for k, v in before["_provenance"]["attempts"].items() if k != "kit-shape"
    }
    assert "kit-shape" in before["_provenance"]["attempts"]  # sanity: the first run did record it

    runner.rerun({"kind": "pipeline", "pipeline": "kit-shape"}, paths=paths, call=always_valid_call)

    index_after = json.loads((paths.anchors_dir / "_index.json").read_text(encoding="utf-8"))
    after = json.loads((paths.anchors_dir / index_after["alpha"]).read_text(encoding="utf-8"))[0]
    other_pipeline_attempts_after = {
        k: v for k, v in after["_provenance"]["attempts"].items() if k != "kit-shape"
    }
    assert other_pipeline_attempts_after == other_pipeline_attempts_before  # untouched
    assert after["_provenance"]["attempts"]["kit-shape"] == 1  # the reran one still recorded


def test_a_pipeline_scoped_rerun_on_a_never_classified_species_refuses_that_species(tmp_path):
    paths = make_paths(tmp_path)  # alpha, beta — neither classified yet
    record = runner.rerun({"kind": "pipeline", "pipeline": "kit-shape"}, paths=paths, call=always_valid_call)

    # A scoped rerun cannot invent the 7 fields it never ran — the species lands in `failed` with
    # a named reason, never a silent first-classification-via-the-back-door.
    assert sorted(record.failed) == ["alpha", "beta"]
    assert record.completed == []


def test_status_reports_state_and_progress(tmp_path):
    paths = make_paths(tmp_path)
    assert runner.status(paths=paths)["state"] == "idle"

    def progress(species_id, done, total):
        if done == 1:
            runner.request_pause(paths=paths)

    runner.start({"kind": "all"}, paths=paths, call=always_valid_call, progress=progress)
    s = runner.status(paths=paths)
    assert s["state"] == "paused"
    assert s["completed"] == 1


# ---- family-file bucketing (2026-09-02) ------------------------------------------------------
#
# Real bug found on T2.11's own 20-species run: `_family_for` only ever consulted
# `family-assignments.json` (built for the unrelated fusion-product `creature` corpus) and ignored
# the anchor's own just-classified `family` field entirely — every base species not coincidentally
# sharing an id with that other corpus landed in the generic "unclassified" bucket despite the
# `identity` pipeline (spec-classify-pipelines.md pipeline 8) already having proposed a real family
# for it in the SAME run.


def test_family_for_prefers_the_anchors_own_classified_family():
    # No entry in the external lookup at all — the anchor's own LLM-proposed family still wins.
    assert runner._family_for("chomper", {}, classified_family=["Apex Predator Flora"]) == "apex-predator-flora"


def test_family_for_falls_back_to_the_external_lookup_when_unclassified():
    families = {"cherrybomb": ["cherry"]}
    assert runner._family_for("CherryBomb", families, classified_family=None) == "cherry"
    assert runner._family_for("CherryBomb", families, classified_family=[]) == "cherry"


def test_family_for_falls_back_to_unclassified_when_neither_source_has_anything():
    assert runner._family_for("nobody", {}, classified_family=None) == "unclassified"
    assert runner._family_for("nobody", {}, classified_family=[""]) == "unclassified"


def test_family_for_ignores_blank_entries_in_the_classified_list():
    # An open array can contain a blank string without being empty — skip to the next real value.
    assert runner._family_for("x", {}, classified_family=["", "  ", "Voidkin"]) == "voidkin"


def test_slugify_family_matches_the_repos_own_kebab_case_grammar():
    assert runner._slugify_family("Apex Predator Flora") == "apex-predator-flora"
    assert runner._slugify_family("Ice & Frost!!") == "ice-frost"
    assert runner._slugify_family("  already-kebab  ") == "already-kebab"


# ---- stale-duplicate write bug (2026-09-04, creature-corpus-self-heal A1) --------------------------
#
# Real bug found via CreatureQualityReport at corpus scale: a reclassification that changes a
# species' own `family` moves its entry to a NEW bucket file but never removed it from the OLD
# one — 217 of 833 real species had a stale copy left behind. `_write_species_entry` now scans
# every OTHER file already loaded into `existing_by_file` and removes this species from it too.

# ---- _load_existing_anchors scans disk, never trusts a possibly-stale index (2026-09-04) -------
#
# Real bug found live during C2 (the corpus-wide kit-shape redeploy), not theorized: the OLD
# `_load_existing_anchors` only read files `_index.json`'s OWN value set currently pointed at. A
# species whose real file the index had drifted away from (the exact class of staleness A1/A2
# exist to fix) became invisible to every future run — and since `_rewrite_index` rebuilds the
# index FROM whatever this function returned, the loss was permanent and self-reinforcing, not
# one-off: `CherryBomb`'s real, intact `plant/cherry.json` entry was silently dropped this way.

def test_load_existing_anchors_finds_a_species_even_when_the_index_does_not_point_at_it(tmp_path):
    paths = make_paths(tmp_path, species=[species_row("alpha", "plant", 1)])
    runner.start({"kind": "all"}, paths=paths, call=always_valid_call)

    # Corrupt the index exactly the way the real bug did: point it at a file that does not exist,
    # leaving alpha's REAL file on disk completely unreferenced by the index's own value set.
    (paths.anchors_dir / "_index.json").write_text(
        json.dumps({"alpha": "plant/nonexistent.json"}), encoding="utf-8")

    anchors = runner._load_existing_anchors(paths.anchors_dir)
    assert any(a.get("speciesId") == "alpha" for a in anchors), (
        "a species' real file must be found by scanning disk, even when the index no longer "
        "points at it — trusting the index here is exactly the bug that caused CherryBomb's "
        "real, intact entry to go silently unreachable")


def _call_with_family(attempt: "dict[str, int]", family_by_attempt: "dict[int, str]"):
    """Wraps `always_valid_call` so every field still validates normally — only `family` (the
    `identity` pipeline's own array field) is overridden, by whichever attempt number the test has
    currently set. `identity`'s `rarity` is voted (3 samples), but `family` is read from sample 0
    only, so returning the SAME family across all samples within one `run_one_species` call (and a
    DIFFERENT one only when the test bumps `attempt`) matches how a real model would behave."""
    def call(system, user, *, config=None, schema=None):
        base = json.loads(always_valid_call(system, user, config=config, schema=schema))
        if "family" in base:
            base["family"] = [family_by_attempt[attempt["n"]]]
        return json.dumps(base)
    return call


def test_a_reclassify_that_changes_family_removes_the_stale_entry_from_the_old_file(tmp_path):
    species = [species_row("alpha", "plant", 1)]
    paths = make_paths(tmp_path, species=species)
    attempt = {"n": 1}
    call = _call_with_family(attempt, {1: "First Family", 2: "Second Family"})

    started = runner.start({"kind": "all"}, paths=paths, call=call)
    assert started.state == "completed"
    index_after_first = json.loads((paths.anchors_dir / "_index.json").read_text(encoding="utf-8"))
    old_rel_path = index_after_first["alpha"]
    assert old_rel_path == "plant/first-family.json"
    assert (paths.anchors_dir / old_rel_path).exists()

    attempt["n"] = 2
    rerun = runner.rerun({"kind": "species", "species": ["alpha"]}, paths=paths, call=call)
    assert rerun.state == "completed"

    index_after_second = json.loads((paths.anchors_dir / "_index.json").read_text(encoding="utf-8"))
    new_rel_path = index_after_second["alpha"]
    assert new_rel_path == "plant/second-family.json"

    # The OLD file must be gone entirely (it held only this one species) — not merely absent from
    # the index while still sitting on disk with a stale copy inside it.
    assert not (paths.anchors_dir / old_rel_path).exists(), \
        f"stale file {old_rel_path} was left behind after alpha moved to {new_rel_path}"
    new_entries = json.loads((paths.anchors_dir / new_rel_path).read_text(encoding="utf-8"))
    assert [e["speciesId"] for e in new_entries] == ["alpha"]


def test_a_reclassify_that_changes_family_does_not_touch_a_sibling_species_in_the_old_file(tmp_path):
    # The old file holding MORE than one species must keep its other residents — only the one
    # species that actually moved gets removed from it.
    species = [species_row("alpha", "plant", 1), species_row("beta", "plant", 2)]
    paths = make_paths(tmp_path, species=species)
    attempt = {"n": 1}

    def call(system, user, *, config=None, schema=None):
        base = json.loads(always_valid_call(system, user, config=config, schema=schema))
        if "family" in base:
            base["family"] = ["Shared Family"]
        return json.dumps(base)

    runner.start({"kind": "all"}, paths=paths, call=call)
    index = json.loads((paths.anchors_dir / "_index.json").read_text(encoding="utf-8"))
    shared_path = index["alpha"]
    assert shared_path == index["beta"] == "plant/shared-family.json"

    moved_call = _call_with_family(attempt, {1: "Shared Family", 2: "Alpha Only Family"})
    attempt["n"] = 2
    runner.rerun({"kind": "species", "species": ["alpha"]}, paths=paths, call=moved_call)

    remaining = json.loads((paths.anchors_dir / shared_path).read_text(encoding="utf-8"))
    assert [e["speciesId"] for e in remaining] == ["beta"]  # beta stayed, alpha left cleanly
    index_after = json.loads((paths.anchors_dir / "_index.json").read_text(encoding="utf-8"))
    assert index_after["alpha"] == "plant/alpha-only-family.json"
    assert index_after["beta"] == shared_path


# ---- start/resume mutual exclusion (2026-09-02) ------------------------------------------------
#
# Real bug: two overlapping `resume`-driving loops (this session's own process management, not a
# hypothetical) both read the SAME record between one species' completion and the next `resume`
# call, both saw it as resumable (the pre-existing `state == "running" and is_process_alive(pid)`
# check is a read-then-check, not an atomic claim), and both proceeded — producing two divergent
# real anchor files for the same 2 species. These tests exercise the lock directly (deterministic)
# rather than racing two real `resume()` calls via threads (timing-sensitive, and the pre-existing
# `always_valid_call` stub is fast enough that a thread race would be flaky either way) — the lock
# IS the mechanism under test, so holding it and asserting the second caller is refused proves
# exactly the same thing a true race would, without the flake risk.


def test_a_held_lock_refuses_a_concurrent_start(tmp_path):
    paths = make_paths(tmp_path)
    runner._acquire_run_lock(paths.runs_dir)
    try:
        with pytest.raises(runner.RunRefused, match="already in progress"):
            runner.start({"kind": "all"}, paths=paths, call=always_valid_call)
    finally:
        runner._release_run_lock(paths.runs_dir)

    # Released, the SAME call now succeeds — the lock refuses while held, not permanently.
    record = runner.start({"kind": "all"}, paths=paths, call=always_valid_call)
    assert record.state == "completed"


def test_a_held_lock_refuses_a_concurrent_resume(tmp_path):
    paths = make_paths(tmp_path)
    seen: "list[str]" = []

    def progress(species_id, done, total):
        seen.append(species_id)
        if len(seen) == 1:
            runner.request_pause(paths=paths)

    paused = runner.start({"kind": "all"}, paths=paths, call=always_valid_call, progress=progress)
    assert paused.state == "paused"

    runner._acquire_run_lock(paths.runs_dir)
    try:
        with pytest.raises(runner.RunRefused, match="already in progress"):
            runner.resume(paths=paths, call=always_valid_call)
    finally:
        runner._release_run_lock(paths.runs_dir)

    resumed = runner.resume(paths=paths, call=always_valid_call)
    assert resumed.state == "completed"


def test_a_stale_lock_from_a_dead_process_is_reclaimed_not_a_permanent_refusal(tmp_path):
    paths = make_paths(tmp_path)
    paths.runs_dir.mkdir(parents=True, exist_ok=True)
    lock_path = paths.runs_dir / runner.RESUME_LOCK_NAME
    # A pid nothing on this machine will ever hold -- 2**31-1, matching this repo's own
    # `is_process_alive`-tests-a-dead-pid convention elsewhere.
    lock_path.write_text("2147483647", encoding="utf-8")

    record = runner.start({"kind": "all"}, paths=paths, call=always_valid_call)

    assert record.state == "completed"
    # The stale lock was reclaimed and released after the call, not left behind.
    assert not lock_path.exists()


def test_a_normal_call_leaves_no_lock_file_behind(tmp_path):
    paths = make_paths(tmp_path)
    runner.start({"kind": "all"}, paths=paths, call=always_valid_call)
    assert not (paths.runs_dir / runner.RESUME_LOCK_NAME).exists()


# ---- workers (2026-09-03): the model-call phase fanned out across N threads ------------------
#
# `_run_parallel` is tested directly first (fast, deterministic where the design allows it, and
# able to prove invariants — like "finalize never runs off the calling thread" — that an
# end-to-end run through `start()` could never demonstrate). The integration tests after it prove
# the real entrypoint (`start(..., workers=N)`) produces the SAME committed result the sequential
# path always has, through the real `run_one_species`/anchor-emit wiring, not a stub of it.

def _fake_classify(species_id, *, delay=0.0, thread_names=None):
    if thread_names is not None:
        thread_names.append(threading.current_thread().name)
    if delay:
        time.sleep(delay)
    return (species_id, {"row": True}, "observed", {"speciesId": species_id}, None)


def test_run_parallel_classifies_every_id_exactly_once_and_returns_not_paused(tmp_path):
    paths = runner.RunPaths(runs_dir=tmp_path)
    ids = [f"s{i}" for i in range(11)]  # deliberately not a multiple of `workers`
    finalized = []

    paused = runner._run_parallel(
        ids, 4, lambda sid: _fake_classify(sid), lambda *args: finalized.append(args[0]), paths)

    assert paused is False
    assert sorted(finalized) == sorted(ids)  # every id exactly once, order not guaranteed


def test_run_parallel_finalize_only_ever_runs_on_the_calling_thread(tmp_path):
    paths = runner.RunPaths(runs_dir=tmp_path)
    calling_thread = threading.current_thread()
    violations = []

    def finalize(species_id, row, basis, merged, err):
        if threading.current_thread() is not calling_thread:
            violations.append(species_id)

    runner._run_parallel(
        [f"s{i}" for i in range(10)], 4, lambda sid: _fake_classify(sid, delay=0.005),
        finalize, paths)

    assert violations == []


def test_run_parallel_actually_uses_more_than_one_thread(tmp_path):
    # Proves real parallelism happens, not a workers=4 flag that silently serializes anyway. A
    # short sleep forces genuine overlap between workers — standard, not flaky at this margin.
    paths = runner.RunPaths(runs_dir=tmp_path)
    thread_names: "list[str]" = []

    runner._run_parallel(
        [f"s{i}" for i in range(12)], 4,
        lambda sid: _fake_classify(sid, delay=0.02, thread_names=thread_names),
        lambda *args: None, paths)

    assert len(set(thread_names)) > 1, f"only one thread ever ran classify_one: {thread_names!r}"


def test_run_parallel_a_missing_row_is_finalized_not_silently_dropped(tmp_path):
    paths = runner.RunPaths(runs_dir=tmp_path)
    finalized = []

    def classify(species_id):
        if species_id == "ghost":
            return (species_id, None, None, None, None)  # matches _classify_one's "not found" shape
        return _fake_classify(species_id)

    runner._run_parallel(["a", "ghost", "b"], 2, classify, lambda *args: finalized.append(args), paths)

    ghost_call = next(c for c in finalized if c[0] == "ghost")
    assert ghost_call[1] is None  # row is None — _finalize's own "species not found" branch


def test_run_parallel_an_unexpected_exception_in_classify_one_does_not_hang_the_run(tmp_path):
    # The defensive backstop: classify_one is contractually never supposed to raise (the real one,
    # `_run_loop`'s own `_classify_one`, catches everything predictable) — but if a future bug
    # broke that contract, an uncaught exception in a worker thread would otherwise kill that
    # thread silently, its final `None` sentinel would never be sent, and the exit loop below would
    # wait forever for a sentinel that never comes. Proves that does NOT happen: the call returns.
    paths = runner.RunPaths(runs_dir=tmp_path)
    finalized = []

    def classify(species_id):
        if species_id == "buggy":
            raise RuntimeError("a bug, not a caught species-level failure")
        return _fake_classify(species_id)

    paused = runner._run_parallel(
        ["a", "buggy", "b"], 2, classify, lambda *args: finalized.append(args), paths)

    assert paused is False
    assert sorted(f[0] for f in finalized) == ["a", "b", "buggy"]
    buggy_call = next(c for c in finalized if c[0] == "buggy")
    assert isinstance(buggy_call[4], RuntimeError)  # the real exception, not swallowed


def test_run_parallel_pausing_leaves_some_ids_unfinalized_for_the_next_resume(tmp_path):
    paths = runner.RunPaths(runs_dir=tmp_path)
    paths.runs_dir.mkdir(parents=True, exist_ok=True)
    paths.pause_sentinel_path.write_text("now", encoding="utf-8")
    finalized = []
    ids = [f"s{i}" for i in range(30)]

    paused = runner._run_parallel(
        ids, 2, lambda sid: _fake_classify(sid, delay=0.02), lambda *args: finalized.append(args[0]),
        paths)

    assert paused is True
    assert not paths.pause_sentinel_path.exists()  # consumed, same as the sequential path
    assert 0 < len(finalized) < len(ids)  # some in-flight work finished; the rest deferred
    assert len(set(finalized)) == len(finalized)  # no id finalized twice


def test_start_with_workers_produces_the_same_result_as_sequential(tmp_path):
    species = [species_row(f"s{i}", "plant", i) for i in range(6)]
    paths = make_paths(tmp_path, species=species)

    record = runner.start({"kind": "all"}, paths=paths, call=always_valid_call, workers=4)

    assert record.state == "completed"
    assert sorted(record.completed) == sorted(s["typeName"] for s in species)
    assert record.calls_made == len(species) * CALLS_PER_OBSERVED_SPECIES
    assert record.failed == []

    index = json.loads((paths.anchors_dir / "_index.json").read_text(encoding="utf-8"))
    assert set(index) == {s["typeName"] for s in species}
    for species_id, rel in index.items():
        entries = json.loads((paths.anchors_dir / rel).read_text(encoding="utf-8"))
        entry = next(e for e in entries if e["speciesId"] == species_id)
        assert entry["_provenance"]["dumpHash"] == record.dump_hash


def test_resume_with_more_workers_than_the_original_start_only_finishes_what_remains(tmp_path):
    species = [species_row(f"s{i}", "plant", i) for i in range(4)]
    paths = make_paths(tmp_path, species=species)

    seen: "list[str]" = []

    def pause_after_first(species_id, done, total):
        seen.append(species_id)
        if len(seen) == 1:
            runner.request_pause(paths=paths)

    started = runner.start({"kind": "all"}, paths=paths, call=always_valid_call, workers=1,
                           progress=pause_after_first)
    assert started.state == "paused"
    assert len(started.completed) == 1  # one full species finished before the pause landed

    # A different `workers` than the original start — matches resume()'s own doc: workers is a
    # resource knob for THIS process, not a property recorded on the run.
    resumed = runner.resume(paths=paths, call=always_valid_call, workers=4)

    assert resumed.state == "completed"
    assert sorted(resumed.completed) == sorted(s["typeName"] for s in species)
    assert resumed.calls_made == len(species) * CALLS_PER_OBSERVED_SPECIES


# ---- fix_unresolved (2026-09-04, creature-corpus-self-heal F1; extended Phase H, 2026-09-07) ------
#
# The deliberate fix step, run ON DEMAND after reading CreatureQualityReport's own unresolved-rate
# finding, never automatically during classification. threatBand has a real, already-sanctioned
# deterministic default (creature-threat.v1.json's own inferredDefaultRung). rarity, added on
# explicit owner direction (Phase H), falls back to threatBand via a rank-preserving
# correspondence (creature-rarity-power-fallback.v1.json) — rarity is this game's own invented
# mechanism, not an almanac/PvZ property, so a vote that never converges gets a deterministic
# engine instead of staying unresolved forever.

def _mark_field_unresolved(paths, species_id: str, field: str) -> None:
    """Test-only corruption matching what a genuine 1-1-1 vote split looks like on disk."""
    index = json.loads((paths.anchors_dir / "_index.json").read_text(encoding="utf-8"))
    rel = index[species_id]
    path = paths.anchors_dir / rel
    entries = json.loads(path.read_text(encoding="utf-8"))
    for e in entries:
        if e["speciesId"] == species_id:
            e[field] = "unresolved"
    path.write_text(json.dumps(entries), encoding="utf-8")


def _mark_threat_band_unresolved(paths, species_id: str) -> None:
    _mark_field_unresolved(paths, species_id, "threatBand")


def test_fix_unresolved_scores_a_scoreable_species_before_defaulting(tmp_path):
    # threat-band-fill T3: the fixture IS scoreable (hp 300 / attack 20, observed), so the fix
    # must carry the scorer's rung with "scored" provenance — never the sanctioned default.
    paths = make_paths(tmp_path, species=[species_row("alpha", "plant", 1)])
    runner.start({"kind": "all"}, paths=paths, call=always_valid_call)
    _mark_threat_band_unresolved(paths, "alpha")

    fixed = runner.fix_unresolved(paths=paths)

    assert len(fixed) == 1
    assert fixed[0]["speciesId"] == "alpha"
    assert fixed[0]["before"] == "unresolved"
    tuning = runner.ThreatTuning.load()
    seed = parse_power_seed(
        side="plant", type_id=1, stats_observed=True, hp=300, attack=20,
        flavor_text="alpha flavor text, no numbers spoken here.")
    assert fixed[0]["after"] == classify_threat(seed, tuning).id

    index = json.loads((paths.anchors_dir / "_index.json").read_text(encoding="utf-8"))
    entries = json.loads((paths.anchors_dir / index["alpha"]).read_text(encoding="utf-8"))
    entry = next(e for e in entries if e["speciesId"] == "alpha")
    assert entry["threatBand"] == fixed[0]["after"]
    # Honest provenance: scored by the engine from the dump, never an LLM judgment, never
    # disguised as one — and visibly distinct from the sanctioned-default stamp below.
    assert entry["_provenance"]["confidence"]["threatBand"] == "scored"


def test_fix_unresolved_defaults_an_unscorable_species_with_default_provenance(tmp_path):
    # Same fix, no signal: an inferred-basis species has nothing to score, so it lands on the
    # real sanctioned default with "default" provenance — the trace the old code never left.
    row = species_row("gamma", "plant", 3)
    row.update(statsObserved=False, hp=None, attack=None)
    paths = make_paths(tmp_path, species=[row])
    runner.start({"kind": "all"}, paths=paths, call=always_valid_call)
    _mark_threat_band_unresolved(paths, "gamma")

    fixed = runner.fix_unresolved(paths=paths)

    assert len(fixed) == 1
    tuning = runner.ThreatTuning.load()
    assert fixed[0]["after"] == tuning.threshold_for_rung(tuning.inferred_default_rung).id

    index = json.loads((paths.anchors_dir / "_index.json").read_text(encoding="utf-8"))
    entries = json.loads((paths.anchors_dir / index["gamma"]).read_text(encoding="utf-8"))
    entry = next(e for e in entries if e["speciesId"] == "gamma")
    assert entry["_provenance"]["confidence"]["threatBand"] == "default"


def test_fix_unresolved_fills_a_missing_threat_band_field(tmp_path):
    # The shipped corpus shape: 719 species carry NO threatBand field at all (not even the
    # vote-split sentinel) and silently read as the default rung. The fill writes what the
    # runtime was assuming — scored here, since this fixture is scoreable.
    paths = make_paths(tmp_path, species=[species_row("alpha", "plant", 1)])
    runner.start({"kind": "all"}, paths=paths, call=always_valid_call)

    index = json.loads((paths.anchors_dir / "_index.json").read_text(encoding="utf-8"))
    path = paths.anchors_dir / index["alpha"]
    entries = json.loads(path.read_text(encoding="utf-8"))
    entry_before = next(e for e in entries if e["speciesId"] == "alpha")
    # The wiring gap itself: classification audits observed species but never WRITES the rung,
    # so the field is absent — not even the vote-split sentinel.
    assert "threatBand" not in entry_before

    fixed = runner.fix_unresolved(paths=paths)

    assert len(fixed) == 1
    assert fixed[0]["before"] is None
    tuning = runner.ThreatTuning.load()
    seed = parse_power_seed(
        side="plant", type_id=1, stats_observed=True, hp=300, attack=20,
        flavor_text="alpha flavor text, no numbers spoken here.")
    assert fixed[0]["after"] == classify_threat(seed, tuning).id

    after = json.loads(path.read_text(encoding="utf-8"))
    entry = next(e for e in after if e["speciesId"] == "alpha")
    assert entry["threatBand"] == fixed[0]["after"]
    assert entry["_provenance"]["confidence"]["threatBand"] == "scored"


def test_fix_unresolved_never_touches_aptitude_secondary_or_element(tmp_path):
    # The remaining, deliberate scope boundary: no fallback of either kind (derived or invented)
    # exists for these two, so touching them would be guessing, not deriving or deciding.
    paths = make_paths(tmp_path, species=[species_row("alpha", "plant", 1)])
    runner.start({"kind": "all"}, paths=paths, call=always_valid_call)
    _mark_threat_band_unresolved(paths, "alpha")

    index = json.loads((paths.anchors_dir / "_index.json").read_text(encoding="utf-8"))
    before = json.loads((paths.anchors_dir / index["alpha"]).read_text(encoding="utf-8"))[0]

    runner.fix_unresolved(paths=paths)

    after = json.loads((paths.anchors_dir / index["alpha"]).read_text(encoding="utf-8"))[0]
    for field in ("aptitudeSecondary", "elementPrimary"):
        assert after[field] == before[field], f"{field} changed — out of this fix's scope"


def test_fix_unresolved_never_touches_an_already_resolved_aptitude(tmp_path):
    paths = make_paths(tmp_path, species=[species_row("alpha", "plant", 1)])
    runner.start({"kind": "all"}, paths=paths, call=always_valid_call)
    _mark_threat_band_unresolved(paths, "alpha")  # aptitude itself is left alone, still resolved

    index = json.loads((paths.anchors_dir / "_index.json").read_text(encoding="utf-8"))
    before = json.loads((paths.anchors_dir / index["alpha"]).read_text(encoding="utf-8"))[0]

    runner.fix_unresolved(paths=paths)

    after = json.loads((paths.anchors_dir / index["alpha"]).read_text(encoding="utf-8"))[0]
    assert after["aptitudePrimary"] == before["aptitudePrimary"]
    assert after["posture"] == before["posture"]
    assert after["pure"] == before["pure"]


def test_fix_unresolved_resolves_aptitude_to_the_flat_invented_default(tmp_path):
    paths = make_paths(tmp_path, species=[species_row("alpha", "plant", 1)])
    runner.start({"kind": "all"}, paths=paths, call=always_valid_call)
    _mark_field_unresolved(paths, "alpha", "aptitudePrimary")

    fixed = runner.fix_unresolved(paths=paths)

    aptitude_fixes = [f for f in fixed if f["field"] == "aptitudePrimary"]
    assert len(aptitude_fixes) == 1
    assert aptitude_fixes[0]["speciesId"] == "alpha"
    assert aptitude_fixes[0]["before"] == "unresolved"
    default = runner.load_aptitude_fallback()
    assert aptitude_fixes[0]["after"] == default

    index = json.loads((paths.anchors_dir / "_index.json").read_text(encoding="utf-8"))
    entry_after = json.loads((paths.anchors_dir / index["alpha"]).read_text(encoding="utf-8"))[0]
    assert entry_after["aptitudePrimary"] == default
    # posture/pure are functions of aptitudePrimary — must not go stale after the fix.
    assert entry_after["posture"] == runner.derive_posture(default)
    assert entry_after["pure"] == runner.derive_pure(default, entry_after["aptitudeSecondary"])
    # Honest provenance: this must never look like a real LLM judgment.
    assert entry_after["_provenance"]["confidence"]["aptitudePrimary"] == "deterministic-fallback"


def test_fix_unresolved_is_idempotent_for_aptitude(tmp_path):
    paths = make_paths(tmp_path, species=[species_row("alpha", "plant", 1)])
    runner.start({"kind": "all"}, paths=paths, call=always_valid_call)
    _mark_field_unresolved(paths, "alpha", "aptitudePrimary")

    first = runner.fix_unresolved(paths=paths)
    second = runner.fix_unresolved(paths=paths)

    assert [f for f in first if f["field"] == "aptitudePrimary"] != []
    assert [f for f in second if f["field"] == "aptitudePrimary"] == []


def test_fix_unresolved_dry_run_never_writes_the_aptitude_fix(tmp_path):
    paths = make_paths(tmp_path, species=[species_row("alpha", "plant", 1)])
    runner.start({"kind": "all"}, paths=paths, call=always_valid_call)
    _mark_field_unresolved(paths, "alpha", "aptitudePrimary")

    fixed = runner.fix_unresolved(paths=paths, dry_run=True)

    assert [f for f in fixed if f["field"] == "aptitudePrimary"] != []
    index = json.loads((paths.anchors_dir / "_index.json").read_text(encoding="utf-8"))
    entry = json.loads((paths.anchors_dir / index["alpha"]).read_text(encoding="utf-8"))[0]
    assert entry["aptitudePrimary"] == "unresolved"  # untouched — dry run never writes


def test_fix_unresolved_never_touches_an_already_resolved_rarity(tmp_path):
    paths = make_paths(tmp_path, species=[species_row("alpha", "plant", 1)])
    runner.start({"kind": "all"}, paths=paths, call=always_valid_call)
    _mark_threat_band_unresolved(paths, "alpha")  # rarity itself is left alone, still resolved

    index = json.loads((paths.anchors_dir / "_index.json").read_text(encoding="utf-8"))
    before_rarity = json.loads((paths.anchors_dir / index["alpha"]).read_text(encoding="utf-8"))[0]["rarity"]

    runner.fix_unresolved(paths=paths)

    after_rarity = json.loads((paths.anchors_dir / index["alpha"]).read_text(encoding="utf-8"))[0]["rarity"]
    assert after_rarity == before_rarity


def _set_field(paths, species_id: str, field: str, value) -> None:
    index = json.loads((paths.anchors_dir / "_index.json").read_text(encoding="utf-8"))
    path = paths.anchors_dir / index[species_id]
    entries = json.loads(path.read_text(encoding="utf-8"))
    for e in entries:
        if e["speciesId"] == species_id:
            e[field] = value
    path.write_text(json.dumps(entries), encoding="utf-8")


def test_fix_unresolved_resolves_rarity_from_a_resolved_threat_band(tmp_path):
    paths = make_paths(tmp_path, species=[species_row("alpha", "plant", 1)])
    runner.start({"kind": "all"}, paths=paths, call=always_valid_call)
    # This fixture's basis never computes a real threatBand on its own (no parseable
    # toughness/damage) — set one explicitly so there is a genuine resolved signal to derive from.
    _set_field(paths, "alpha", "threatBand", "tyrant")
    _mark_field_unresolved(paths, "alpha", "rarity")

    index = json.loads((paths.anchors_dir / "_index.json").read_text(encoding="utf-8"))
    entry_before = json.loads((paths.anchors_dir / index["alpha"]).read_text(encoding="utf-8"))[0]
    threat_band = entry_before["threatBand"]

    fixed = runner.fix_unresolved(paths=paths)

    rarity_fixes = [f for f in fixed if f["field"] == "rarity"]
    assert len(rarity_fixes) == 1
    assert rarity_fixes[0]["speciesId"] == "alpha"
    assert rarity_fixes[0]["before"] == "unresolved"
    mapping = runner.load_rarity_power_fallback()
    assert rarity_fixes[0]["after"] == mapping[threat_band]

    entry_after = json.loads((paths.anchors_dir / index["alpha"]).read_text(encoding="utf-8"))[0]
    assert entry_after["rarity"] == rarity_fixes[0]["after"]
    # Honest provenance: this must never look like a real LLM judgment.
    assert entry_after["_provenance"]["confidence"]["rarity"] == "deterministic-fallback"


def test_fix_unresolved_chains_rarity_off_a_threat_band_fixed_in_the_same_pass(tmp_path):
    # Both fields unresolved: threatBand gets the sanctioned default FIRST, then rarity derives
    # from that freshly-fixed value in the same pass — not from the pre-fix "unresolved" string.
    paths = make_paths(tmp_path, species=[species_row("alpha", "plant", 1)])
    runner.start({"kind": "all"}, paths=paths, call=always_valid_call)
    _mark_threat_band_unresolved(paths, "alpha")
    _mark_field_unresolved(paths, "alpha", "rarity")

    fixed = runner.fix_unresolved(paths=paths)

    fields_fixed = {f["field"] for f in fixed}
    assert fields_fixed == {"threatBand", "rarity"}
    threat_fix = next(f for f in fixed if f["field"] == "threatBand")
    rarity_fix = next(f for f in fixed if f["field"] == "rarity")
    mapping = runner.load_rarity_power_fallback()
    assert rarity_fix["after"] == mapping[threat_fix["after"]]


def test_fix_unresolved_chains_rarity_from_a_filled_default(tmp_path):
    # threat-band-fill T3 retired the old "missing threatBand, rarity stays unresolved" case on
    # purpose: an absent field now fills (default here — inferred basis, nothing to score) and
    # rarity chains from that freshly-filled value in the same pass, exactly like the scored path.
    row = species_row("gamma", "plant", 3)
    row.update(statsObserved=False, hp=None, attack=None)
    paths = make_paths(tmp_path, species=[row])
    runner.start({"kind": "all"}, paths=paths, call=always_valid_call)
    # Inferred species vote their rung for real (Q26), so this fixture arrives resolved —
    # mark both fields to exercise the chain.
    _mark_threat_band_unresolved(paths, "gamma")
    _mark_field_unresolved(paths, "gamma", "rarity")

    fixed = runner.fix_unresolved(paths=paths)

    fields_fixed = {f["field"] for f in fixed}
    assert fields_fixed == {"threatBand", "rarity"}
    threat_fix = next(f for f in fixed if f["field"] == "threatBand")
    rarity_fix = next(f for f in fixed if f["field"] == "rarity")
    tuning = runner.ThreatTuning.load()
    assert threat_fix["after"] == tuning.threshold_for_rung(tuning.inferred_default_rung).id
    mapping = runner.load_rarity_power_fallback()
    assert rarity_fix["after"] == mapping[threat_fix["after"]]


def test_fix_unresolved_leaves_an_already_resolved_species_untouched(tmp_path):
    paths = make_paths(tmp_path, species=[species_row("alpha", "plant", 1)])
    runner.start({"kind": "all"}, paths=paths, call=always_valid_call)
    # Classification audits observed species but never writes the rung (see the test above),
    # so "already resolved" here means a real rung is present — the authored branch, no stamp.
    index = json.loads((paths.anchors_dir / "_index.json").read_text(encoding="utf-8"))
    path = paths.anchors_dir / index["alpha"]
    entries = json.loads(path.read_text(encoding="utf-8"))
    for e in entries:
        if e["speciesId"] == "alpha":
            e["threatBand"] = "tyrant"
    path.write_text(json.dumps(entries), encoding="utf-8")

    fixed = runner.fix_unresolved(paths=paths)

    assert fixed == []


def test_fix_unresolved_dry_run_reports_without_writing(tmp_path):
    paths = make_paths(tmp_path, species=[species_row("alpha", "plant", 1)])
    runner.start({"kind": "all"}, paths=paths, call=always_valid_call)
    _mark_threat_band_unresolved(paths, "alpha")

    fixed = runner.fix_unresolved(paths=paths, dry_run=True)

    assert len(fixed) == 1
    index = json.loads((paths.anchors_dir / "_index.json").read_text(encoding="utf-8"))
    entries = json.loads((paths.anchors_dir / index["alpha"]).read_text(encoding="utf-8"))
    entry = next(e for e in entries if e["speciesId"] == "alpha")
    assert entry["threatBand"] == "unresolved"  # untouched — dry run never writes


def test_fix_unresolved_is_idempotent(tmp_path):
    paths = make_paths(tmp_path, species=[species_row("alpha", "plant", 1)])
    runner.start({"kind": "all"}, paths=paths, call=always_valid_call)
    _mark_threat_band_unresolved(paths, "alpha")

    first = runner.fix_unresolved(paths=paths)
    second = runner.fix_unresolved(paths=paths)

    assert len(first) == 1
    assert second == []  # already fixed — nothing left to do, not re-applied


# ---- fix_secondary_from_fusion_lineage (2026-09-07, owner-directed combat-unification F2 follow-up) --
#
# A DIFFERENT signal source from fix_unresolved's three fields above: those only fire on a genuine
# vote-split ("unresolved"); this fires on an already-resolved "none" when a fusion recipe's own
# lineage supplies real cross-species signal the per-species lore classifier could never see.

def _set_field(paths, species_id: str, field: str, value) -> None:
    """Test-only field override — same disk-level shape `_mark_field_unresolved` already uses,
    generalized to set an arbitrary value rather than only "unresolved"."""
    index = json.loads((paths.anchors_dir / "_index.json").read_text(encoding="utf-8"))
    rel = index[species_id]
    path = paths.anchors_dir / rel
    entries = json.loads(path.read_text(encoding="utf-8"))
    for e in entries:
        if e["speciesId"] == species_id:
            e[field] = value
    path.write_text(json.dumps(entries), encoding="utf-8")


def _write_fusion_recipes(tmp_path: Path, *, output: str, input_a: str, input_b: str) -> Path:
    recipes_path = tmp_path / "_fusion-recipes.json"
    recipes_path.write_text(json.dumps({
        f"recipe.{output}": {
            "outputSpeciesId": output, "inputSpeciesIdA": input_a, "inputSpeciesIdB": input_b,
            "crossRungGapFill": False,
        }
    }), encoding="utf-8")
    return recipes_path


def test_fix_secondary_from_fusion_derives_from_the_one_parent_that_differs(tmp_path):
    paths = make_paths(tmp_path, species=[
        species_row("output", "plant", 1), species_row("parenta", "plant", 2),
        species_row("parentb", "plant", 3)])
    runner.start({"kind": "all"}, paths=paths, call=always_valid_call)
    _set_field(paths, "output", "elementPrimary", "air")
    _set_field(paths, "output", "elementSecondary", "none")
    _set_field(paths, "parenta", "elementPrimary", "air")   # matches output — no new signal
    _set_field(paths, "parentb", "elementPrimary", "earth")  # the real signal
    recipes = _write_fusion_recipes(tmp_path, output="output", input_a="parenta", input_b="parentb")

    fixed = runner.fix_secondary_from_fusion_lineage(paths=paths, recipes_path=recipes)

    assert len(fixed) == 1
    assert fixed[0] == {"speciesId": "output", "field": "elementSecondary",
                        "before": "none", "after": "earth"}
    index = json.loads((paths.anchors_dir / "_index.json").read_text(encoding="utf-8"))
    entries = json.loads((paths.anchors_dir / index["output"]).read_text(encoding="utf-8"))
    entry = next(e for e in entries if e["speciesId"] == "output")
    assert entry["elementSecondary"] == "earth"
    # Honest, distinct provenance — never confused with a real LLM judgment OR with a
    # no-real-signal-existed "deterministic-fallback".
    assert entry["_provenance"]["confidence"]["elementSecondary"] == "fusion-lineage-derived"


def test_fix_secondary_from_fusion_leaves_a_real_secondary_untouched(tmp_path):
    paths = make_paths(tmp_path, species=[
        species_row("output", "plant", 1), species_row("parenta", "plant", 2),
        species_row("parentb", "plant", 3)])
    runner.start({"kind": "all"}, paths=paths, call=always_valid_call)
    _set_field(paths, "output", "elementPrimary", "air")
    _set_field(paths, "output", "elementSecondary", "fire")  # already real
    _set_field(paths, "parentb", "elementPrimary", "earth")
    recipes = _write_fusion_recipes(tmp_path, output="output", input_a="parenta", input_b="parentb")

    fixed = runner.fix_secondary_from_fusion_lineage(paths=paths, recipes_path=recipes)

    assert fixed == []


def test_fix_secondary_from_fusion_leaves_it_none_when_both_parents_agree_with_the_output(tmp_path):
    paths = make_paths(tmp_path, species=[
        species_row("output", "plant", 1), species_row("parenta", "plant", 2),
        species_row("parentb", "plant", 3)])
    runner.start({"kind": "all"}, paths=paths, call=always_valid_call)
    _set_field(paths, "output", "elementPrimary", "light")
    _set_field(paths, "output", "elementSecondary", "none")
    _set_field(paths, "parenta", "elementPrimary", "light")
    _set_field(paths, "parentb", "elementPrimary", "light")
    recipes = _write_fusion_recipes(tmp_path, output="output", input_a="parenta", input_b="parentb")

    fixed = runner.fix_secondary_from_fusion_lineage(paths=paths, recipes_path=recipes)

    assert fixed == []  # both parents already agree with the output — real signal, not a gap


def test_fix_secondary_from_fusion_leaves_it_unresolved_when_both_parents_disagree(tmp_path):
    paths = make_paths(tmp_path, species=[
        species_row("output", "plant", 1), species_row("parenta", "plant", 2),
        species_row("parentb", "plant", 3)])
    runner.start({"kind": "all"}, paths=paths, call=always_valid_call)
    _set_field(paths, "output", "elementPrimary", "light")
    _set_field(paths, "output", "elementSecondary", "none")
    _set_field(paths, "parenta", "elementPrimary", "earth")   # neither matches output —
    _set_field(paths, "parentb", "elementPrimary", "dark")    # inputA's own "should match" failed
    recipes = _write_fusion_recipes(tmp_path, output="output", input_a="parenta", input_b="parentb")

    fixed = runner.fix_secondary_from_fusion_lineage(paths=paths, recipes_path=recipes)

    assert fixed == []  # neither parent trustworthy as "the other element" — left unresolved


def test_fix_secondary_from_fusion_is_a_noop_for_a_species_with_no_recipe(tmp_path):
    paths = make_paths(tmp_path, species=[species_row("standalone", "plant", 1)])
    runner.start({"kind": "all"}, paths=paths, call=always_valid_call)
    _set_field(paths, "standalone", "elementSecondary", "none")
    recipes = _write_fusion_recipes(tmp_path, output="output", input_a="parenta", input_b="parentb")

    fixed = runner.fix_secondary_from_fusion_lineage(paths=paths, recipes_path=recipes)

    assert fixed == []


def test_fix_secondary_from_fusion_dry_run_never_writes(tmp_path):
    paths = make_paths(tmp_path, species=[
        species_row("output", "plant", 1), species_row("parenta", "plant", 2),
        species_row("parentb", "plant", 3)])
    runner.start({"kind": "all"}, paths=paths, call=always_valid_call)
    _set_field(paths, "output", "elementPrimary", "air")
    _set_field(paths, "output", "elementSecondary", "none")
    _set_field(paths, "parenta", "elementPrimary", "air")
    _set_field(paths, "parentb", "elementPrimary", "earth")
    recipes = _write_fusion_recipes(tmp_path, output="output", input_a="parenta", input_b="parentb")

    fixed = runner.fix_secondary_from_fusion_lineage(paths=paths, recipes_path=recipes, dry_run=True)

    assert len(fixed) == 1
    index = json.loads((paths.anchors_dir / "_index.json").read_text(encoding="utf-8"))
    entries = json.loads((paths.anchors_dir / index["output"]).read_text(encoding="utf-8"))
    entry = next(e for e in entries if e["speciesId"] == "output")
    assert entry["elementSecondary"] == "none"  # unchanged on disk


def test_fix_secondary_from_fusion_is_idempotent(tmp_path):
    paths = make_paths(tmp_path, species=[
        species_row("output", "plant", 1), species_row("parenta", "plant", 2),
        species_row("parentb", "plant", 3)])
    runner.start({"kind": "all"}, paths=paths, call=always_valid_call)
    _set_field(paths, "output", "elementPrimary", "air")
    _set_field(paths, "output", "elementSecondary", "none")
    _set_field(paths, "parenta", "elementPrimary", "air")
    _set_field(paths, "parentb", "elementPrimary", "earth")
    recipes = _write_fusion_recipes(tmp_path, output="output", input_a="parenta", input_b="parentb")

    first = runner.fix_secondary_from_fusion_lineage(paths=paths, recipes_path=recipes)
    second = runner.fix_secondary_from_fusion_lineage(paths=paths, recipes_path=recipes)

    assert len(first) == 1
    assert second == []


def test_fix_secondary_from_fusion_missing_recipes_file_is_a_noop(tmp_path):
    paths = make_paths(tmp_path, species=[species_row("alpha", "plant", 1)])
    runner.start({"kind": "all"}, paths=paths, call=always_valid_call)

    fixed = runner.fix_secondary_from_fusion_lineage(
        paths=paths, recipes_path=tmp_path / "does-not-exist.json")

    assert fixed == []


# ---- rederive_from_measured_capture (creature-seed R-CS1/R-CS3/R-CS4, 2026-09-17) ---------------
#
# A deterministic, on-demand re-derivation of the two DERIVED fields the game's own static stat
# table answers: `basis` (the measured upgrade) and `speciesKind` (the mark). No model calls.


def _write_measured_capture(dump_dir: Path, rows: "list[dict]") -> None:
    """The committed `type-base-stats.json` shape, as `CreatureCorpusDump --base-stats` writes it.
    `contentHash` is the C# tool's business (`--verify` owns that check) — the Python loader reads
    `entries` and nothing else, so a fixture supplies exactly that."""
    (dump_dir / "type-base-stats.json").write_text(json.dumps({
        "capturedUtc": "2026-09-17T14:50:55Z",
        "dumpFormatVersion": 1,
        "entries": [
            {"side": r["side"], "typeId": r["typeId"], "typeName": r.get("typeName"),
             "capturedUtc": "2026-09-17T14:50:55Z",
             "statsJson": json.dumps({"hpBase": r["hpBase"], "attackBase": r["attackBase"]})}
            for r in rows
        ],
    }), encoding="utf-8")


def _entry(paths, species_id: str) -> dict:
    index = json.loads((paths.anchors_dir / "_index.json").read_text(encoding="utf-8"))
    entries = json.loads((paths.anchors_dir / index[species_id]).read_text(encoding="utf-8"))
    return next(e for e in entries if e["speciesId"] == species_id)


def test_rederive_marks_a_resolving_species_creature_and_a_phantom_excluded(tmp_path):
    # `alpha` resolves in the capture; `ghost` does not — the exact shape of the twelve phantom rows
    # (a corpus id generated from an enum value the game does not define).
    species = [species_row("alpha", "plant", 1), species_row("ghost", "plant", 261)]
    paths = make_paths(tmp_path, species=species)
    runner.start({"kind": "all"}, paths=paths, call=always_valid_call)
    _write_measured_capture(paths.dump_dir, [
        {"side": "plant", "typeId": 1, "typeName": "alpha", "hpBase": 300, "attackBase": 20}])

    changed = runner.rederive_from_measured_capture(paths=paths)

    kinds = {c["speciesId"]: c["after"] for c in changed if c["field"] == "speciesKind"}
    assert kinds == {"alpha": "creature", "ghost": "excluded"}
    assert _entry(paths, "alpha")["speciesKind"] == "creature"
    assert _entry(paths, "ghost")["speciesKind"] == "excluded"


def test_rederive_marks_a_phantom_without_removing_it_from_the_corpus(tmp_path):
    # R-CS3: "instead of delete and untrack, we mark to track." The row must still be present,
    # joinable, and carrying its original id — deleting it would break every downstream join that
    # already references it.
    species = [species_row("alpha", "plant", 1), species_row("ghost", "plant", 261)]
    paths = make_paths(tmp_path, species=species)
    runner.start({"kind": "all"}, paths=paths, call=always_valid_call)
    _write_measured_capture(paths.dump_dir, [
        {"side": "plant", "typeId": 1, "typeName": "alpha", "hpBase": 300, "attackBase": 20}])

    runner.rederive_from_measured_capture(paths=paths)

    entry = _entry(paths, "ghost")
    assert entry["speciesId"] == "ghost"
    assert entry["gameTypeId"] == 261
    assert entry["speciesKind"] == "excluded"
    assert "ghost" in json.loads((paths.anchors_dir / "_index.json").read_text(encoding="utf-8"))


def test_rederive_stamps_honest_provenance_and_preserves_the_original_dump_hash(tmp_path):
    paths = make_paths(tmp_path, species=[species_row("alpha", "plant", 1)])
    record = runner.start({"kind": "all"}, paths=paths, call=always_valid_call)
    _write_measured_capture(paths.dump_dir, [
        {"side": "plant", "typeId": 1, "typeName": "alpha", "hpBase": 300, "attackBase": 20}])

    runner.rederive_from_measured_capture(paths=paths)

    prov = _entry(paths, "alpha")["_provenance"]
    assert prov["confidence"]["speciesKind"] == "native-type-resolution"
    # The entry's other fields are still its own classification era's, so claiming a fresh dump hash
    # would overstate what this pass did — same rule `fix_unresolved` holds.
    assert prov["dumpHash"] == record.dump_hash


def test_rederive_is_idempotent(tmp_path):
    paths = make_paths(tmp_path, species=[species_row("alpha", "plant", 1)])
    runner.start({"kind": "all"}, paths=paths, call=always_valid_call)
    _write_measured_capture(paths.dump_dir, [
        {"side": "plant", "typeId": 1, "typeName": "alpha", "hpBase": 300, "attackBase": 20}])

    assert runner.rederive_from_measured_capture(paths=paths)          # first run does work
    assert runner.rederive_from_measured_capture(paths=paths) == []    # second run is a no-op


def test_rederive_dry_run_reports_without_writing(tmp_path):
    paths = make_paths(tmp_path, species=[species_row("alpha", "plant", 1)])
    runner.start({"kind": "all"}, paths=paths, call=always_valid_call)
    _write_measured_capture(paths.dump_dir, [
        {"side": "plant", "typeId": 1, "typeName": "alpha", "hpBase": 300, "attackBase": 20}])

    assert runner.rederive_from_measured_capture(paths=paths, dry_run=True)
    assert "speciesKind" not in _entry(paths, "alpha")


def test_rederive_with_no_capture_marks_nothing_rather_than_excluding_everything(tmp_path):
    # The failure this guards: an absent capture read as "nothing resolves" would mark an entire
    # corpus `excluded` in one pass.
    paths = make_paths(tmp_path, species=[species_row("alpha", "plant", 1)])
    runner.start({"kind": "all"}, paths=paths, call=always_valid_call)

    changed = runner.rederive_from_measured_capture(paths=paths)

    assert [c for c in changed if c["field"] == "speciesKind"] == []
    assert "speciesKind" not in _entry(paths, "alpha")


def test_rederive_with_an_empty_capture_also_marks_nothing(tmp_path):
    # A capture file that exists but swept zero rows is a BROKEN capture, not proof that nothing
    # resolves — same outcome as no file at all. The distinction matters because the two are one
    # `git checkout` apart and the wrong reading would exclude an entire corpus.
    paths = make_paths(tmp_path, species=[species_row("alpha", "plant", 1)])
    runner.start({"kind": "all"}, paths=paths, call=always_valid_call)
    _write_measured_capture(paths.dump_dir, [])

    changed = runner.rederive_from_measured_capture(paths=paths)

    assert [c for c in changed if c["field"] == "speciesKind"] == []
    assert "speciesKind" not in _entry(paths, "alpha")


def test_rederive_never_touches_threat_band(tmp_path):
    # Deliberate boundary, not an oversight — re-scoring the rung against thresholds fitted on the
    # OLD score distribution is a `creature-threat.v2.json` balance change, not a data upgrade. See
    # `rederive_from_measured_capture`'s own docstring for the measurement behind this line.
    paths = make_paths(tmp_path, species=[species_row("alpha", "plant", 1)])
    runner.start({"kind": "all"}, paths=paths, call=always_valid_call)
    before = _entry(paths, "alpha").get("threatBand")
    _write_measured_capture(paths.dump_dir, [
        {"side": "plant", "typeId": 1, "typeName": "alpha", "hpBase": 640000, "attackBase": 9000}])

    changed = runner.rederive_from_measured_capture(paths=paths)

    assert [c for c in changed if c["field"] == "threatBand"] == []
    assert _entry(paths, "alpha").get("threatBand") == before


# ---- refresh_rank (spec-species-rank.md §1/§4, creature-seed Task 4) -------------------------------
#
# The one deterministic pass that can put a DERIVED rank on a corpus whose classified fields are all
# already resolved: the other three skip every entry whose field they do not change, so none of them
# can backfill a field the whole corpus is missing.

def _del_field(paths, species_id: str, field: str) -> None:
    """Test-only removal, so a fixture can stand in for a corpus written before the field existed."""
    index = json.loads((paths.anchors_dir / "_index.json").read_text(encoding="utf-8"))
    path = paths.anchors_dir / index[species_id]
    entries = json.loads(path.read_text(encoding="utf-8"))
    for e in entries:
        if e["speciesId"] == species_id:
            e.pop(field, None)
    path.write_text(json.dumps(entries), encoding="utf-8")


def test_refresh_rank_backfills_a_corpus_that_predates_it(tmp_path):
    from seedsmith.adapters.creatures.anchor.derive import derive_rank

    paths = make_paths(tmp_path, species=[species_row("alpha", "plant", 1)])
    runner.start({"kind": "all"}, paths=paths, call=always_valid_call)
    # This fixture's observed-basis pass writes a threat-audit VERDICT, not a rung, so a resolved
    # pair is set explicitly — the same stand-in the fix_unresolved tests use.
    _set_field(paths, "alpha", "threatBand", "tyrant")
    expected = derive_rank(_entry(paths, "alpha")["threatBand"], _entry(paths, "alpha")["rarity"])
    _del_field(paths, "alpha", "rank")

    changed = runner.refresh_rank(paths=paths)

    assert changed == [{"speciesId": "alpha", "field": "rank", "before": None, "after": expected}]
    assert _entry(paths, "alpha")["rank"] == expected


def test_refresh_rank_is_a_byte_for_byte_no_op_on_a_second_run(tmp_path):
    paths = make_paths(tmp_path, species=[species_row("alpha", "plant", 1)])
    runner.start({"kind": "all"}, paths=paths, call=always_valid_call)
    _del_field(paths, "alpha", "rank")

    assert runner.refresh_rank(paths=paths) != []  # the first run has real work to do
    files = sorted(p for p in paths.anchors_dir.rglob("*.json"))
    before_bytes = {p: p.read_bytes() for p in files}

    assert runner.refresh_rank(paths=paths) == []  # nothing left to refresh
    assert {p: p.read_bytes() for p in files} == before_bytes


def test_refresh_rank_leaves_every_classified_field_untouched(tmp_path):
    paths = make_paths(tmp_path, species=[species_row("alpha", "plant", 1)])
    runner.start({"kind": "all"}, paths=paths, call=always_valid_call)
    _del_field(paths, "alpha", "rank")
    before = dict(_entry(paths, "alpha"))

    runner.refresh_rank(paths=paths)

    after = _entry(paths, "alpha")
    for key, value in before.items():
        if key in ("rank", "_provenance"):
            continue  # rank is this pass's own field; emittedUtc records that a pass ran
        assert after[key] == value, f"refresh_rank changed {key!r}"


def test_refresh_rank_never_defaults_an_unresolved_input(tmp_path):
    # Assumption 4: skip, don't fabricate. An unresolved pair derives "unresolved", never a rung.
    paths = make_paths(tmp_path, species=[species_row("alpha", "plant", 1)])
    runner.start({"kind": "all"}, paths=paths, call=always_valid_call)
    _set_field(paths, "alpha", "threatBand", "unresolved")
    _set_field(paths, "alpha", "rank", "chaff")  # a fabricated rung this pass must correct away

    runner.refresh_rank(paths=paths)

    assert _entry(paths, "alpha")["rank"] == "unresolved"


def test_refresh_rank_dry_run_reports_without_writing(tmp_path):
    paths = make_paths(tmp_path, species=[species_row("alpha", "plant", 1)])
    runner.start({"kind": "all"}, paths=paths, call=always_valid_call)
    _del_field(paths, "alpha", "rank")
    before_bytes = (paths.anchors_dir / json.loads(
        (paths.anchors_dir / "_index.json").read_text(encoding="utf-8"))["alpha"]).read_bytes()

    changed = runner.refresh_rank(paths=paths, dry_run=True)

    assert [c["speciesId"] for c in changed] == ["alpha"]
    assert (paths.anchors_dir / json.loads(
        (paths.anchors_dir / "_index.json").read_text(encoding="utf-8"))["alpha"]).read_bytes() == before_bytes


def test_a_deterministic_merge_never_drops_another_passs_relead_provenance(tmp_path):
    # `lead-relabel-pass` writes `_provenance.relead`; `_write_species_entry`'s merge branch builds a
    # fresh AnchorProvenance, so the block was silently erased from every entry a deterministic pass
    # rewrote (found live 2026-09-23: the refresh-rank regen lost it on 104 of 904 real entries).
    paths = make_paths(tmp_path, species=[species_row("alpha", "plant", 1)])
    runner.start({"kind": "all"}, paths=paths, call=always_valid_call)
    relead = {
        "fromPrimary": "Might", "promptVersion": 1, "dumpHash": "0123456789abcdef",
        "votes": ["Might", "Fortitude"], "confidence": "high", "measureHash": "fedcba9876543210",
        "outcome": "accepted",
    }
    entry = _entry(paths, "alpha")
    _set_field(paths, "alpha", "_provenance", {**entry["_provenance"], "relead": relead})
    _del_field(paths, "alpha", "rank")

    runner.refresh_rank(paths=paths)

    assert _entry(paths, "alpha")["_provenance"]["relead"] == relead
