from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from seedsmith.pipeline.llm_caller import LlmCallerConfig
from seedsmith.adapters.actions.generate_action_pipeline import (
    ACTIONS_ROOT,
    _foundation_inputs,
    _load_plan,
    _run_partition,
)
from seedsmith.adapters.actions.generation_batches import (
    load_resume_entries,
    merge_entries,
    select_brief_batch,
)


def _brief(brief_id: str) -> dict:
    return {"briefId": brief_id}


def _entry(brief_id: str, outcome: str, candidate_id: str) -> dict:
    return {"briefId": brief_id, "candidateId": candidate_id, "outcome": outcome}


class ActionGenerationBatchTests(unittest.TestCase):
    def test_plan_freshness_check_rejects_a_stale_upstream_hash(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "round-1.json"
            path.write_text(json.dumps({
                "kind": "action-brief",
                "_meta": {"corpusHash": "old-live-roster"},
                "entries": [],
            }), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "stale relative to the live inputs"):
                _load_plan(path, expected_corpus_hash="new-live-roster")

    def test_partition_continues_past_eight_successful_batches(self):
        calls = []

        def generate(**kwargs):
            calls.append(kwargs)
            remaining = max(0, 10 - len(calls))
            return {"selected": 1, "remaining": remaining,
                    "byOutcome": {"accepted": 1}}

        summary = _run_partition(
            name="family", generate=generate, briefs_path=Path("briefs.json"),
            candidates_dir=Path("candidates"), round_no=1, batch_size=1, max_passes=1,
            config=LlmCallerConfig(endpoint="endpoint", model="model"),
            dry_run=False, resume=False,
        )

        self.assertEqual(len(calls), 10)
        self.assertEqual([call["resume"] for call in calls], [False] + [True] * 9)
        self.assertEqual(summary["remaining"], 0)

    def test_partition_refuses_after_consecutive_stalled_batches(self):
        def generate(**kwargs):
            return {"selected": 1, "remaining": 1, "byOutcome": {"unresolved": 1}}

        with self.assertRaisesRegex(RuntimeError, "stalled passes"):
            _run_partition(
                name="signature", generate=generate, briefs_path=Path("briefs.json"),
                candidates_dir=Path("candidates"), round_no=1, batch_size=1, max_passes=2,
                config=LlmCallerConfig(endpoint="endpoint", model="model"),
                dry_run=False, resume=False,
            )

    def test_resume_skips_terminal_entries_but_retries_unresolved_in_plan_order(self):
        briefs = [_brief("b.001"), _brief("b.002"), _brief("b.003"), _brief("b.004")]
        existing = [
            _entry("b.001", "accepted", "candidate.x.000"),
            _entry("b.002", "unresolved", "candidate.x.001"),
            _entry("b.003", "blocked", "candidate.x.002"),
        ]

        selected = select_brief_batch(briefs, count=2, existing_entries=existing)

        self.assertEqual([b["briefId"] for b in selected], ["b.002", "b.004"])

    def test_merge_replaces_retried_entry_and_sorts_by_brief_id(self):
        existing = [_entry("b.002", "unresolved", "candidate.x.001"),
                   _entry("b.001", "accepted", "candidate.x.000")]
        replacement = [_entry("b.002", "accepted", "candidate.x.001")]

        merged = merge_entries(existing, replacement)

        self.assertEqual([e["briefId"] for e in merged], ["b.001", "b.002"])
        self.assertEqual(merged[1]["outcome"], "accepted")

    def test_resume_rejects_another_plan_hash(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "round-1.json"
            path.write_text(json.dumps({
                "kind": "action-candidate",
                "_meta": {"partition": "general", "round": 1,
                          "briefsCorpusHash": "old-plan"},
                "entries": [],
            }), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "briefsCorpusHash"):
                load_resume_entries(path, partition="general", round_no=1,
                                    briefs_corpus_hash="new-plan")


if __name__ == "__main__":
    unittest.main()


class FoundationInputsTests(unittest.TestCase):
    """ADG-F3 (`action-distribution-gaps`, 2026-09-21): the two model-free foundation stages must be
    computed into ONE root in dependency order, so the type-weights stage hashes the role-lean this
    call just derived rather than whatever was already on disk. Before the fix a `--dry-run` wrote
    nothing, so type-weights hashed the STALE committed role-lean while the characteristic-pool hash
    was fresh -- the expected plan hash became a third value that matched neither the committed plan
    nor a real run. `_foundation_inputs` is the seam that made that testable."""

    def test_type_weights_hashes_the_freshly_derived_role_lean_not_a_stale_one(self):
        stale_text = json.dumps({"entries": [], "marker": "stale"}, ensure_ascii=False)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "_generated").mkdir()
            (root / "_generated" / "role-lean.json").write_text(stale_text, encoding="utf-8")

            foundation = _foundation_inputs(root)

            # `type_weights` hashes the TEXT it reads (`read_text`, so universal newlines -- the
            # writer emits CRLF on Windows and the hash must not depend on that).
            fresh_text = (root / "_generated" / "role-lean.json").read_text(encoding="utf-8")
            self.assertNotEqual(fresh_text, stale_text, "the derivation must have rewritten it")
            self.assertEqual(foundation["typeWeights"]["leanHash"],
                             hashlib.sha256(fresh_text.encode("utf-8")).hexdigest())
            self.assertNotEqual(foundation["typeWeights"]["leanHash"],
                                hashlib.sha256(stale_text.encode("utf-8")).hexdigest())

    def test_both_stages_land_under_the_root_they_were_given(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            foundation = _foundation_inputs(root)
            self.assertTrue((root / "_generated" / "role-lean.json").is_file())
            self.assertTrue((root / "_generated" / "characteristic-pool.json").is_file())
            self.assertTrue((root / "type-weights.json").is_file())
            self.assertEqual(foundation["characteristicPool"]["written"], True)
            self.assertEqual(foundation["typeWeights"]["written"], True)

    def test_the_tracked_foundation_files_are_untouched_by_a_computation_into_a_temp_root(self):
        tracked = [ACTIONS_ROOT / "_generated" / "role-lean.json", ACTIONS_ROOT / "type-weights.json"]
        before = {p: p.read_bytes() for p in tracked}
        with tempfile.TemporaryDirectory() as tmp:
            _foundation_inputs(Path(tmp))
        self.assertEqual({p: p.read_bytes() for p in tracked}, before)
