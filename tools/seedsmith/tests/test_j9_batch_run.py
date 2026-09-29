"""Tests for `gk-forge/tools/seedsmith/_j9_batch_run.py` — the J9 species-batch driver (BCU2.12).

The `--check` path is the one worth pinning: it is the model-free plan the full-run launcher calls
first, and it is what tells an operator which species are owed nodes before a 904-species run starts.
The run path itself is exercised for real by the bounded proof (`--count 2`), not here.

**The codex retry (task J9-B2, 2026-09-21)** is pinned here with a FAKE voter — no test in this file
reaches the real model. The retry is the driver's own bounded convergence policy, so this file is
where it is covered: `resolve_codex_with_retry` (only the species it is handed is re-drawn, it stops
as soon as one draw resolves, and the bound is a real TOTAL draw count), `finalize_codex` (the named
failure record a species still gets when the bound is reached, and nothing written for a species whose
tree never completed) and `run_batch` (the bound reaches every species' own call).
"""
from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

TOOL_PATH = Path(__file__).resolve().parents[1] / "_j9_batch_run.py"
_spec = importlib.util.spec_from_file_location("j9_batch_run", TOOL_PATH)
assert _spec is not None and _spec.loader is not None
j9 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(j9)

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from seedsmith.adapters.trees.species.plan import FavourCell
from seedsmith.adapters.trees.species.roster import SpeciesAnchor
from seedsmith.pipeline.llm_caller import LlmCallerConfig


class CheckPlanTests(unittest.TestCase):
    def test_check_with_zero_count_plans_nothing_but_still_reports_the_roster(self) -> None:
        summary = j9.check(count=0)
        self.assertGreater(summary["rosterSpecies"], 0)
        self.assertEqual([], summary["planned"])
        self.assertIsInstance(summary["ledgerDoneRows"], int)

    def test_check_plans_exactly_the_requested_prefix(self) -> None:
        summary = j9.check(count=2)
        self.assertEqual(2, len(summary["planned"]))
        # the roster's own stable order, never a re-sort
        self.assertNotEqual(summary["planned"][0]["speciesId"], summary["planned"][1]["speciesId"])

    def test_a_planned_row_reconciles_to_the_tree_size(self) -> None:
        row = j9.check(count=1)["planned"][0]
        self.assertEqual(
            {"speciesId", "owed", "alreadyDone", "superseded", "duplicateSuperseded"}, set(row))
        # owed subjects are the ones that are neither already done nor a re-roll
        self.assertGreaterEqual(row["alreadyDone"] + row["owed"], 0)
        self.assertLessEqual(row["duplicateSuperseded"], row["superseded"])

    def test_cli_check_exits_zero_and_prints_json(self) -> None:
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code = j9.main(["--check", "--count", "1"])
        self.assertEqual(0, code)
        doc = json.loads(buffer.getvalue())
        self.assertEqual(1, len(doc["planned"]))

    def test_a_negative_count_is_refused(self) -> None:
        with self.assertRaises(SystemExit):
            j9.main(["--check", "--count", "-1"])

    def test_a_positional_count_is_accepted_for_the_committed_full_run_launcher(self) -> None:
        # `.claude/cmdc-agents/scripts/bcu212-full-run.ps1` passes its count POSITIONALLY. Before the
        # alias existed argparse refused it outright (`unrecognized arguments: 2`, exit 2), so the
        # 840-species run would have died in seconds -- measured 2026-09-21, task J9-B2.
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code = j9.main(["2", "--check"])
        self.assertEqual(0, code)
        self.assertEqual(2, len(json.loads(buffer.getvalue())["planned"]))

    def test_a_positional_count_disagreeing_with_the_flag_is_refused(self) -> None:
        with self.assertRaises(SystemExit):
            j9.main(["2", "--count", "3", "--check"])

    def test_a_codex_attempt_bound_below_one_is_refused(self) -> None:
        with self.assertRaises(SystemExit):
            j9.main(["--check", "--count", "1", "--codex-attempts", "0"])


class SingleRequestEndpointTests(unittest.TestCase):
    def test_four_workers_overlap_but_the_bcu212_driver_is_serialized(self) -> None:
        """A fake one-request endpoint proves the old worker count really overlaps requests.

        The production endpoint serves one model request at a time. Three codex samples submitted
        with ``workers=4`` must rendezvous at the fake transport; if the driver still selects four,
        the observed HTTP 400/500 burst has a concrete concurrency shape rather than being blamed on
        the model by assumption.
        """
        from seedsmith.adapters.trees.species.generate_codex import resolve_codex_summaries

        rendezvous = threading.Barrier(3)
        lock = threading.Lock()
        active = 0
        max_active = 0

        def one_request_transport(system, user, *, config=None, schema=None):
            nonlocal active, max_active
            with lock:
                active += 1
                max_active = max(max_active, active)
            rendezvous.wait(timeout=2)
            with lock:
                active -= 1
            return json.dumps({"codexSummary": "Rewards patient, steady offense.", "blocked": ""})

        anchor = SpeciesAnchor(
            species_id="fixture", element_primary="fire", aptitude_primary="Onslaught",
            posture="Force", traits=("relentless",), reason="a concurrency fixture",
            source_path="test.json")
        fresh, unresolved, _ = resolve_codex_summaries(
            [("fixture", anchor, FavourCell("Onslaught", "air", "spark"))],
            provenance_base={"pipeline": "single-request-test"}, call=one_request_transport,
            workers=4)

        self.assertEqual({}, unresolved)
        self.assertEqual({"fixture"}, set(fresh))
        self.assertEqual(3, max_active, "workers=4 must put all three samples in flight together")
        self.assertEqual(1, j9.WORKERS, "BCU2.12 targets one request at a time, so its driver is serial")


class CodexRetryTests(unittest.TestCase):
    """The bounded codex re-vote, driven by fake voters. Every model call below is a Python stub;
    the real model is never reached by any test in this file."""

    CELL = FavourCell(aptitude="Onslaught", element="air", status="spark")
    ANCHOR = SpeciesAnchor(
        species_id="fixture", element_primary="fire", aptitude_primary="Onslaught",
        posture="Force", traits=("relentless",), reason="a test fixture creature",
        source_path="test.json")
    CONFIG = LlmCallerConfig(max_heal=0, model="test-model")

    #: Three individually CLEAN sentences that never agree -> a real 1-1-1 `vote_unresolved`.
    SPLIT = ["First answer entirely.", "Second, different answer.", "Third, also different."]
    #: A unanimous draw -> resolves at any rung.
    SETTLED = ["The settled answer."] * 3

    def _voter(self, draws):
        """`draws` is a list of 3-answer groups, one group per DRAW in call order (a later draw
        reuses the last group, so "never resolves" is `[self.SPLIT]`). Returns `(call, log)`; `log`
        holds every sample's user prompt, so a test can count the exact model calls made."""
        log: "list[str]" = []

        def call(system, user, *, config=None, schema=None):
            index = len(log)
            log.append(user)
            group = draws[min(index // 3, len(draws) - 1)]
            return json.dumps({"codexSummary": group[index % 3], "blocked": ""})

        return call, log

    def _result(self, species_id: str, *, codex_summary=None, codex_reason=None,
                marked=frozenset(), metadata_path=None):
        return SimpleNamespace(
            species_id=species_id, resolved_cell=self.CELL, marked_node_ids=marked,
            codex_summary=codex_summary, codex_unresolved_reason=codex_reason,
            metadata_path=metadata_path)

    def test_the_retry_redraws_the_unresolved_species_and_stops_as_soon_as_it_resolves(self) -> None:
        # `first_reason` is the draw the CALLER already made, so the voter below supplies only the
        # retry's own draws: it resolves on the retry's first draw and the bound's third is unused.
        call, log = self._voter([self.SETTLED])
        summary, reason, draws = j9.resolve_codex_with_retry(
            "Beta", self.ANCHOR, self.CELL, first_reason="vote_unresolved", total_attempts=3,
            call=call, config=self.CONFIG, workers=1)
        self.assertEqual("The settled answer.", summary)
        self.assertIsNone(reason)
        self.assertEqual(2, draws, "the caller's own first draw is counted; the bound is a total")
        self.assertEqual(3, len(log), "exactly one 3-sample re-draw, then it stops")

    def test_the_bound_is_reached_and_the_last_draws_own_reason_stands(self) -> None:
        # A species that never agrees: bounded at `total_attempts` draws (draw 1 + two re-draws),
        # reporting the last draw's reason rather than retrying forever.
        call, log = self._voter([self.SPLIT])
        summary, reason, draws = j9.resolve_codex_with_retry(
            "Delta", self.ANCHOR, self.CELL, first_reason="vote_unresolved", total_attempts=3,
            call=call, config=self.CONFIG, workers=1)
        self.assertIsNone(summary)
        self.assertEqual("vote_unresolved", reason)
        self.assertEqual(3, draws, "bounded: draw 1 plus two re-draws, never more")
        self.assertEqual(6, len(log), "two re-draws x three samples")

    def test_a_single_draw_bound_makes_no_model_call_at_all(self) -> None:
        def _never_called(*args, **kwargs):
            raise AssertionError("total_attempts=1 must not re-draw")

        summary, reason, draws = j9.resolve_codex_with_retry(
            "Epsilon", self.ANCHOR, self.CELL, first_reason="vote_unresolved", total_attempts=1,
            call=_never_called, config=self.CONFIG, workers=1)
        self.assertIsNone(summary)
        self.assertEqual("vote_unresolved", reason)
        self.assertEqual(1, draws)

    def test_a_retry_without_a_reason_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            j9.resolve_codex_with_retry(
                "Zeta", self.ANCHOR, self.CELL, first_reason="", total_attempts=3)

    def test_a_bound_below_one_draw_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            j9.resolve_codex_with_retry(
                "Zeta", self.ANCHOR, self.CELL, first_reason="vote_unresolved", total_attempts=0)

    def test_finalize_codex_retries_then_writes_the_named_failure_at_the_bound(self) -> None:
        # The whole point of the row: a species the vote never resolves within the bound still gets
        # its `species/<id>.json` -- carrying the vote's own reason and the bound it reached.
        seed_root = Path(tempfile.mkdtemp())
        call, log = self._voter([self.SPLIT])
        codex = j9.finalize_codex(
            self._result("Eta", codex_reason="vote_unresolved", marked=frozenset({"n1", "n2"})),
            self.ANCHOR, seed_root=seed_root, codex_attempts=3, call=call, config=self.CONFIG,
            workers=1)
        self.assertIsNone(codex["codexSummary"])
        self.assertEqual("vote_unresolved", codex["codexUnresolvedReason"])
        self.assertEqual(3, codex["codexAttempts"])
        self.assertFalse(codex["metadataWritten"])
        self.assertTrue(codex["failureRecordWritten"])
        self.assertEqual(6, len(log))

        document = json.loads(
            (seed_root / "passive-tree" / "species" / "Eta.json").read_text(encoding="utf-8"))
        self.assertIsNone(document["codexSummary"])
        self.assertEqual("vote_unresolved", document["codexUnresolvedReason"])
        self.assertEqual(3, document["codexAttempts"])
        self.assertEqual(["n1", "n2"], document["speciesUniqueNodeIds"])
        self.assertEqual("Onslaught", document["mechanicalFavour"]["aptitude"])

    def test_finalize_codex_writes_the_resolved_document_when_a_retry_succeeds(self) -> None:
        seed_root = Path(tempfile.mkdtemp())
        call, _ = self._voter([self.SETTLED])
        codex = j9.finalize_codex(
            self._result("Theta", codex_reason="vote_unresolved"), self.ANCHOR,
            seed_root=seed_root, codex_attempts=3, call=call, config=self.CONFIG, workers=1)
        self.assertEqual("The settled answer.", codex["codexSummary"])
        self.assertIsNone(codex["codexUnresolvedReason"])
        self.assertEqual(2, codex["codexAttempts"])
        self.assertTrue(codex["metadataWritten"])
        self.assertFalse(codex["failureRecordWritten"])
        document = json.loads(
            (seed_root / "passive-tree" / "species" / "Theta.json").read_text(encoding="utf-8"))
        self.assertEqual("The settled answer.", document["codexSummary"])
        self.assertNotIn("codexUnresolvedReason", document)

    def test_finalize_codex_leaves_an_already_resolved_species_alone(self) -> None:
        # Draw 1 resolving must not re-draw (no model call) and must not rewrite the file
        # `run_species_tree` already wrote.
        def _never_called(*args, **kwargs):
            raise AssertionError("a resolved codex must not be re-drawn")

        codex = j9.finalize_codex(
            self._result("Iota", codex_summary="Already good.",
                         metadata_path=Path("already-written.json")),
            self.ANCHOR, codex_attempts=6, call=_never_called, config=self.CONFIG, workers=1)
        self.assertEqual("Already good.", codex["codexSummary"])
        self.assertIsNone(codex["codexUnresolvedReason"])
        self.assertEqual(1, codex["codexAttempts"])
        self.assertTrue(codex["metadataWritten"])
        self.assertFalse(codex["failureRecordWritten"])

    def test_finalize_codex_writes_nothing_for_a_species_whose_tree_never_completed(self) -> None:
        # An unresolved favour (or a refused tree) never reaches the codex stage: no codexSummary,
        # no reason, no species file -- it names itself in the run's own results row instead.
        def _never_called(*args, **kwargs):
            raise AssertionError("an unreached codex stage must not call the model")

        codex = j9.finalize_codex(
            self._result("Kappa"), self.ANCHOR, codex_attempts=6, call=_never_called,
            config=self.CONFIG, workers=1)
        self.assertEqual(0, codex["codexAttempts"])
        self.assertIsNone(codex["codexSummary"])
        self.assertIsNone(codex["codexUnresolvedReason"])
        self.assertFalse(codex["metadataWritten"])
        self.assertFalse(codex["failureRecordWritten"])

    def test_completed_species_are_checkpointed_before_the_next_species_is_interrupted(self) -> None:
        """A killed process must leave the completed prefix, not an absent/stale result file."""
        def _fake_run_species_tree(species_id, anchor, ordinal, cell, alternates, **kwargs):
            if ordinal == 1:
                raise KeyboardInterrupt("simulated process interruption")
            return SimpleNamespace(
                species_id=species_id, resolved_cell=cell, favour_unresolved_reason=None,
                node_key_refused_reason=None, outcome_counts={"accepted": 1},
                marked_node_ids=frozenset(), codex_summary="Resolved.",
                codex_unresolved_reason=None, metadata_path=Path("written.json"))

        def _fake_finalize(result, anchor, **kwargs):
            return {"codexSummary": "Resolved.", "codexUnresolvedReason": None,
                    "codexAttempts": 1, "metadataWritten": True, "failureRecordWritten": False}

        with tempfile.TemporaryDirectory() as tmp:
            out_path = Path(tmp) / "results.json"
            with patch.object(j9, "run_species_tree", _fake_run_species_tree), \
                    patch.object(j9, "finalize_codex", _fake_finalize):
                with self.assertRaises(KeyboardInterrupt):
                    j9.run_batch(count=2, out_path=out_path, codex_attempts=3)

            self.assertTrue(out_path.exists(), "the first completed species must already be durable")
            rows = json.loads(out_path.read_text(encoding="utf-8"))
            self.assertEqual(1, len(rows))
            self.assertEqual(j9.load_roster().species_ids[0], rows[0]["speciesId"])
            self.assertEqual([], list(Path(tmp).glob("*.tmp")))

    def test_a_failed_language_gate_checkpoints_the_prefix_and_propagates(self) -> None:
        """A hard-gate failure must not be converted into a green batch result or a later species."""
        finalized = []

        def _fake_run_species_tree(species_id, anchor, ordinal, cell, alternates, **kwargs):
            if ordinal == 1:
                raise j9.SpeciesTreeGateFailure("fixture: PassiveTree/UnresolvedCount=fail")
            return SimpleNamespace(
                species_id=species_id, resolved_cell=cell, favour_unresolved_reason=None,
                node_key_refused_reason=None, outcome_counts={"accepted": 1},
                marked_node_ids=frozenset(), codex_summary="Resolved.",
                codex_unresolved_reason=None, metadata_path=Path("written.json"))

        def _fake_finalize(result, anchor, **kwargs):
            finalized.append(result.species_id)
            return {"codexSummary": "Resolved.", "codexUnresolvedReason": None,
                    "codexAttempts": 1, "metadataWritten": True, "failureRecordWritten": False}

        with tempfile.TemporaryDirectory() as tmp:
            out_path = Path(tmp) / "results.json"
            with patch.object(j9, "run_species_tree", _fake_run_species_tree), \
                    patch.object(j9, "finalize_codex", _fake_finalize):
                with self.assertRaises(j9.SpeciesTreeGateFailure):
                    j9.run_batch(count=2, out_path=out_path, codex_attempts=3)
            rows = json.loads(out_path.read_text(encoding="utf-8"))
            self.assertEqual(2, len(rows))
            self.assertEqual("FAIL", rows[1]["hardGate"])
            self.assertEqual([j9.load_roster().species_ids[0]], finalized)
            self.assertEqual(j9.load_roster().species_ids[1], rows[1]["speciesId"])

    def test_a_run_that_dies_before_its_first_species_clears_a_stale_results_file(self) -> None:
        def _fake_run_species_tree(species_id, anchor, ordinal, cell, alternates, **kwargs):
            raise KeyboardInterrupt("simulated first-species interruption")

        with tempfile.TemporaryDirectory() as tmp:
            out_path = Path(tmp) / "results.json"
            out_path.write_text('[{"speciesId":"stale-smoke-row"}]', encoding="utf-8")
            with patch.object(j9, "run_species_tree", _fake_run_species_tree):
                with self.assertRaises(KeyboardInterrupt):
                    j9.run_batch(count=1, out_path=out_path, codex_attempts=3)
            self.assertEqual([], json.loads(out_path.read_text(encoding="utf-8")))

    def test_the_bound_reaches_the_real_per_species_call(self) -> None:
        # `run_batch` is the only caller that decides the bound, so it must forward it to every
        # species. Both fakes make no model call and write no file.
        seen: "list[int]" = []

        def _fake_run_species_tree(species_id, anchor, ordinal, cell, alternates, **kwargs):
            return SimpleNamespace(
                species_id=species_id, resolved_cell=cell, favour_unresolved_reason=None,
                node_key_refused_reason=None, outcome_counts={"accepted": 1},
                marked_node_ids=frozenset(), codex_summary="Resolved.",
                codex_unresolved_reason=None, metadata_path=Path("written.json"))

        def _fake_finalize(result, anchor, **kwargs):
            seen.append(kwargs["codex_attempts"])
            return {"codexSummary": "Resolved.", "codexUnresolvedReason": None,
                    "codexAttempts": 1, "metadataWritten": True, "failureRecordWritten": False}

        with tempfile.TemporaryDirectory() as tmp:
            out_path = Path(tmp) / "results.json"
            with patch.object(j9, "run_species_tree", _fake_run_species_tree), \
                    patch.object(j9, "finalize_codex", _fake_finalize):
                rows = j9.run_batch(count=2, out_path=out_path, codex_attempts=5)
            self.assertEqual([5, 5], seen, "run_batch must forward --codex-attempts to every species")
            self.assertEqual(2, len(rows))
            for row in rows:
                self.assertEqual(1, row["codexAttempts"])
                self.assertTrue(row["metadataWritten"])
                self.assertFalse(row["failureRecordWritten"])
            self.assertEqual(rows, json.loads(out_path.read_text(encoding="utf-8")))


if __name__ == "__main__":
    unittest.main()
