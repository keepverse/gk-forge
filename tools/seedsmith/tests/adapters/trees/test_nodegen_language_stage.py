"""Tests for seedsmith.adapters.trees.nodegen.run.run_language_stage (task H2) — the whole-tree
orchestration: idempotence (§7 gate 14) and, the sharpest acceptance bullet of this task, a forced
rerun of the language stage over UNCHANGED inputs leaving `nodes/<treeId>.json` BYTE-IDENTICAL,
hash-compared, with ZERO further model calls (proven by patching the transport with a stub that
raises the moment it would be reached).

This is the exact defect class named in tasks/passive-tree-todo.md's own H2 section: "the
commander-effect generator rewrote all 84 entries every run" — caught here at the LANGUAGE
pipeline stage specifically (distinct from H9's later catalog-from-plan byte-identical check).

    python -m pytest gk-forge/tools/seedsmith/tests/adapters/trees/test_nodegen_language_stage.py -v
"""
from __future__ import annotations

import hashlib
import itertools
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _nodegen_fixtures import raising_call, write_plan  # noqa: E402

from seedsmith.adapters.trees.nodegen import plan_read, run  # noqa: E402
from seedsmith.adapters.trees.nodegen.verdict import UNRESOLVED_COUNT_METRIC  # noqa: E402
from seedsmith.adapters.trees.nodegen.vocab import AffixOption, AffixVocabulary  # noqa: E402
from seedsmith.pipeline.llm_caller import LlmCallerConfig  # noqa: E402

AFFIX_A = AffixOption(affix_id="atom.a", name="Alpha Strike", tags=("offensive",), kind_id="k1")
VOCAB = AffixVocabulary(options=(AFFIX_A,))
TEST_CONFIG = LlmCallerConfig(max_heal=0, model="test-model")


def _accepted_response(node_key: str = "test-node") -> dict:
    return {
        "affixIds": ["atom.a"], "affinity": ["core"],
        "exclusion": {"form": "none", "propertyKeys": []},
        "name": f"Test Node {node_key}", "nameKey": f"tree.node.{node_key}",
        "flavor": "A steady line.", "rationale": "", "blocked": "",
    }


def _named_response(name: str) -> dict:
    """Like `_accepted_response`, but with an EXACT `name` the caller controls — needed to test
    `_derive_unique_name_key`'s own real behavior (it derives the persisted key from `name`, never
    the response's own claimed `nameKey`), where `_accepted_response`'s templated
    `f"Test Node {node_key}"` would not reproduce two different trees' models independently choosing
    the literal SAME name."""
    return {
        "affixIds": ["atom.a"], "affinity": ["core"],
        "exclusion": {"form": "none", "propertyKeys": []},
        "name": name, "nameKey": "tree.node.irrelevant-the-model-doesnt-control-this",
        "flavor": "A steady line.", "rationale": "", "blocked": "",
    }


def _inputs_for(_subject: run.Subject) -> run.NodeGenerationInputs:
    return run.NodeGenerationInputs(
        tree_display_name="Might", tree_reading="the way of raw force",
        motifs=("strength",), anti_motifs=(), anti_motif_tags=(),
        permitted_affixes=(AFFIX_A,), permitted_properties=("posture",),
        property_vocabulary={"posture": ("vanguard", "warden")}, affix_vocab=VOCAB)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class RunLanguageStageIdempotenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.seed_root = Path(tempfile.mkdtemp())
        write_plan(self.seed_root, "t1", node_count=1)
        self.plan = plan_read.load("t1", self.seed_root)
        self.ledger_path = self.seed_root / "_runs" / "ledger.json"

    def test_first_run_generates_and_writes_the_seed_document(self) -> None:
        payload = json.dumps(_accepted_response())
        with patch("seedsmith.pipeline.llm_caller.call_model", return_value=payload):
            result = run.run_language_stage(self.plan, _inputs_for, ledger_path=self.ledger_path,
                                            seed_root=self.seed_root, config=TEST_CONFIG,
                                            unresolved_max_share_permille=500)
        self.assertEqual(len(result.outcomes), 1)
        self.assertEqual(result.outcomes[0].outcome, "accepted")
        self.assertIsNotNone(result.seed_path)
        self.assertTrue(result.seed_path.exists())
        doc = json.loads(result.seed_path.read_text(encoding="utf-8"))
        self.assertEqual(len(doc["nodes"]), 1)
        self.assertEqual(doc["nodes"][0]["affixIds"], ["atom.a"])
        self.assertEqual(result.report.verdict.value, "pass")

    def test_seed_document_plan_hash_is_the_plans_own_content_hash(self) -> None:
        """The seed's `_provenance.planHash` names the plan it was generated from — the SAME value
        the manifest indexes as `trees[].sha256` (`plan.emit.tree_content_hash`), never the empty
        string a `raw.get("sha256", "")` read off a plan document that has no such key used to
        stamp (2026-09-11 fix). Proven against the plan the run actually read, not a fixture string.
        """
        from seedsmith.adapters.trees.plan.emit import tree_content_hash

        payload = json.dumps(_accepted_response())
        with patch("seedsmith.pipeline.llm_caller.call_model", return_value=payload):
            result = run.run_language_stage(self.plan, _inputs_for, ledger_path=self.ledger_path,
                                            seed_root=self.seed_root, config=TEST_CONFIG,
                                            unresolved_max_share_permille=500)
        doc = json.loads(result.seed_path.read_text(encoding="utf-8"))
        expected = tree_content_hash(self.plan.raw)
        self.assertNotEqual("", doc["_provenance"]["planHash"])
        self.assertEqual(expected, doc["_provenance"]["planHash"])

    def test_a_forced_rerun_over_unchanged_inputs_makes_zero_calls_and_is_byte_identical(self) -> None:
        payload = json.dumps(_accepted_response())
        with patch("seedsmith.pipeline.llm_caller.call_model", return_value=payload):
            first = run.run_language_stage(self.plan, _inputs_for, ledger_path=self.ledger_path,
                                           seed_root=self.seed_root, config=TEST_CONFIG,
                                           unresolved_max_share_permille=500)
        first_hash = _sha256(first.seed_path)
        first_bytes = first.seed_path.read_bytes()

        # The forced rerun: same plan, same (now-populated) ledger. The offline transport stub
        # RAISES on any call — if idempotence has a hole and the stage tries to regenerate even one
        # already-done subject, this test fails immediately rather than silently re-writing content.
        with patch("seedsmith.pipeline.llm_caller.call_model", raising_call):
            second = run.run_language_stage(self.plan, _inputs_for, ledger_path=self.ledger_path,
                                            seed_root=self.seed_root, config=TEST_CONFIG,
                                            unresolved_max_share_permille=500)

        self.assertEqual(len(second.outcomes), 0, "a forced rerun must generate nothing new")
        self.assertEqual(second.seed_path.read_bytes(), first_bytes)
        self.assertEqual(_sha256(second.seed_path), first_hash)

    def test_running_twice_never_double_records_the_same_subject_in_the_ledger(self) -> None:
        payload = json.dumps(_accepted_response())
        with patch("seedsmith.pipeline.llm_caller.call_model", return_value=payload):
            run.run_language_stage(self.plan, _inputs_for, ledger_path=self.ledger_path,
                                   seed_root=self.seed_root, config=TEST_CONFIG)
        with patch("seedsmith.pipeline.llm_caller.call_model", raising_call):
            run.run_language_stage(self.plan, _inputs_for, ledger_path=self.ledger_path,
                                   seed_root=self.seed_root, config=TEST_CONFIG)
        ledger = run.read_ledger(self.ledger_path)
        self.assertEqual(len(ledger), 1)


def _write_magnitude_first_plan(seed_root: Path, tree_id: str = "t1") -> None:
    """The exact shape the 2026-09-06 `might` smoke test surfaced: a tier's magnitude node listed in
    the plan BEFORE that tier's own mechanism node — `write_plan`'s shared fixture always puts a
    mechanism node first (`i == 0`), so it can never reproduce this ordering bug. Both nodes tier 1."""
    plan = {
        "schemaVersion": 1, "treeId": tree_id, "archetype": "broad-and-flat",
        "propertyVocabulary": {"posture": ["vanguard", "warden"]},
        "mechNodesByTier": [1, 0, 0, 0, 0, 0, 0, 0, 0, 0],
        "nodes": [
            {"id": f"skill.{tree_id}-off-t1-n0", "nodeKey": "n0", "branch": "offensive", "tier": 1,
             "indexInTier": 0, "nodeClass": "magnitude", "budgetShareMilli": 500, "budgetPoints": 25},
            {"id": f"skill.{tree_id}-off-t1-n1", "nodeKey": "n1", "branch": "offensive", "tier": 1,
             "indexInTier": 1, "nodeClass": "mechanism", "budgetShareMilli": 500, "budgetPoints": 25},
        ],
    }
    path = seed_root / "passive-tree" / "plan" / f"{tree_id}.v1.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(plan, indent=2) + "\n", encoding="utf-8")


class MechanismBeforeMagnitudeSiblingTests(unittest.TestCase):
    """2026-09-06: the smoke test's own root cause, closed. `plan_run` now orders a tier's mechanism
    node(s) before its magnitude node(s) regardless of file order, and `run_language_stage` tracks
    already-accepted tier siblings itself (never trusting `inputs_for` to do it) — so a magnitude node
    that would otherwise render with brief.py's own literal "(none yet)" now sees the real mechanism
    sibling that came before it, the moment one exists."""

    def setUp(self) -> None:
        self.seed_root = Path(tempfile.mkdtemp())
        _write_magnitude_first_plan(self.seed_root, "t1")
        self.plan = plan_read.load("t1", self.seed_root)
        self.ledger_path = self.seed_root / "_runs" / "ledger.json"
        self.rendered_users: "list[str]" = []

    def _capturing_call(self, _system, user, *, config=None, temperature=0.2, schema=None):
        # The brief TEXT carries no explicit node id, so which node a call is for is read off the
        # call's own position instead: subject order is fixed by `plan_run`'s reorder (mechanism n1
        # first, 3 calls -- base + 2 votes -- then magnitude n0, 3 more calls).
        index = len(self.rendered_users)
        self.rendered_users.append(user)
        node_key = "n1" if index < 3 else "n0"
        return json.dumps(_accepted_response(node_key))

    def test_the_mechanism_node_generates_first_despite_listing_second_in_the_plan(self) -> None:
        with patch("seedsmith.pipeline.llm_caller.call_model", side_effect=self._capturing_call):
            result = run.run_language_stage(self.plan, _inputs_for, ledger_path=self.ledger_path,
                                            seed_root=self.seed_root, config=TEST_CONFIG)
        self.assertEqual(len(result.outcomes), 2)
        # plan.subjects visits the mechanism node (n1) before the magnitude node (n0), even though
        # n0 is listed FIRST in the plan's own `nodes` array.
        self.assertEqual(result.outcomes[0].subject_id, "t1:skill.t1-off-t1-n1")
        self.assertEqual(result.outcomes[1].subject_id, "t1:skill.t1-off-t1-n0")
        self.assertEqual(result.outcomes[0].outcome, "accepted")
        self.assertEqual(result.outcomes[1].outcome, "accepted")

    def test_the_magnitude_nodes_own_brief_names_the_mechanism_sibling_that_preceded_it(self) -> None:
        with patch("seedsmith.pipeline.llm_caller.call_model", side_effect=self._capturing_call):
            run.run_language_stage(self.plan, _inputs_for, ledger_path=self.ledger_path,
                                   seed_root=self.seed_root, config=TEST_CONFIG)
        # n1 (mechanism, generated first): no siblings yet -- brief.py's own literal placeholder.
        n1_base_call_user = self.rendered_users[0]
        self.assertIn("(none yet)", n1_base_call_user)
        # n0 (magnitude, generated second, same tier): n1's own accepted name + affix now appear as
        # a real sibling line, never the empty placeholder -- this is the exact fix for the smoke
        # test's "magnitude node requires an existing thing to make larger; current tree is empty."
        n0_base_call_user = self.rendered_users[3]
        self.assertIn("Test Node n1", n0_base_call_user)
        self.assertIn("atom.a", n0_base_call_user)
        self.assertNotIn("(none yet)", n0_base_call_user)

    def test_a_resumed_run_seeds_siblings_from_the_ledger_not_only_this_runs_own_acceptances(self) -> None:
        # First run: only the mechanism node (n1) generates and is accepted; the magnitude node's
        # own call is never reached (simulates a process killed between the two subjects).
        def _only_n1(_system, user, *, config=None, temperature=0.2, schema=None):
            if "skill.t1-off-t1-n0" in user:
                raise AssertionError("n0 must not be called in the first, partial run")
            return json.dumps(_accepted_response("n1"))

        with patch("seedsmith.pipeline.llm_caller.call_model", side_effect=_only_n1):
            # Only run the mechanism subject by hand-truncating the plan -- reuses plan_run directly
            # since run_language_stage itself has no partial-run knob.
            partial_plan = run.plan_run(self.plan, ledger={})
            mechanism_subject = next(s for s in partial_plan.subjects if s.node_class == "mechanism")
            outcome = run.generate_node(mechanism_subject, _inputs_for(mechanism_subject), config=TEST_CONFIG)
            self.assertEqual(outcome.outcome, "accepted")
            done = run.record_accepted({}, mechanism_subject.subject_id, outcome.record)
            run.write_ledger(done, self.ledger_path)

        # Second run, fresh process (a new `rendered_users` capture): the magnitude node's own brief
        # must see n1 as a sibling even though THIS run never generated it itself.
        rendered: "list[str]" = []

        def _capture_second_run(_system, user, *, config=None, temperature=0.2, schema=None):
            rendered.append(user)
            return json.dumps(_accepted_response("n0"))

        with patch("seedsmith.pipeline.llm_caller.call_model", side_effect=_capture_second_run):
            result = run.run_language_stage(self.plan, _inputs_for, ledger_path=self.ledger_path,
                                            seed_root=self.seed_root, config=TEST_CONFIG)
        self.assertEqual(len(result.outcomes), 1)
        self.assertEqual(result.outcomes[0].subject_id, "t1:skill.t1-off-t1-n0")
        self.assertIn("Test Node n1", rendered[0])
        self.assertNotIn("(none yet)", rendered[0])


class TreeWideSiblingScopeTests(unittest.TestCase):
    """2026-09-06 real-call finding, closed the SAME day as the original tier-scoped sibling fix: a
    real `might` run independently generated "Deep Rooting" for THREE different defensive-branch
    nodes across TWO different tiers (t2-n0, t2-n1, t3-n1) — tier-scoped siblings cannot see across
    tiers, so none of them ever knew the name was already taken. Widened `run_language_stage`'s own
    tracking from per-tier to tree-wide (capped, most-recent-N) to close this for real."""

    def setUp(self) -> None:
        self.seed_root = Path(tempfile.mkdtemp())
        write_plan(self.seed_root, "t1", node_count=4)  # n0/n1 tier 1, n2/n3 tier 2 (fixture's own math)
        self.plan = plan_read.load("t1", self.seed_root)
        self.ledger_path = self.seed_root / "_runs" / "ledger.json"

    def test_a_node_in_a_later_tier_sees_an_earlier_tiers_own_accepted_sibling(self) -> None:
        rendered: "list[str]" = []

        def fake_call(_system, user, *, config=None, temperature=0.2, schema=None):
            n = len(rendered)
            rendered.append(user)
            return json.dumps(_accepted_response(f"n{n // 3}"))

        with patch("seedsmith.pipeline.llm_caller.call_model", side_effect=fake_call):
            result = run.run_language_stage(self.plan, _inputs_for, ledger_path=self.ledger_path,
                                            seed_root=self.seed_root, config=TEST_CONFIG)

        self.assertTrue(all(o.outcome == "accepted" for o in result.outcomes),
                        [(o.subject_id, o.outcome, o.detail) for o in result.outcomes])
        # Subject order: t1/n0 (mechanism, tier 1), t1/n1 (magnitude, tier 1), then tier 2's two
        # magnitude nodes (n2, n3) -- fixture's own `tier = 1 + (i // 2)` math. n2's own base call
        # (index 6 -- two tier-1 subjects x 3 calls each) is the first call that could show a
        # DIFFERENT-tier sibling; under the OLD tier-scoped design it would still read "(none yet)"
        # since nothing has been accepted in tier 2 yet -- under tree-wide scope it sees BOTH tier-1
        # nodes by name.
        n2_base_call_user = rendered[6]
        self.assertNotIn("(none yet)", n2_base_call_user)
        self.assertIn("Test Node n0", n2_base_call_user)
        self.assertIn("Test Node n1", n2_base_call_user)

    def test_the_sibling_list_is_capped_at_the_most_recent_N_not_unbounded(self) -> None:
        # write_plan's own fixture pairs two magnitude nodes per tier from tier 2 onward (tier =
        # 1 + i//2), so the count of already-accepted nodes BEFORE each new tier's batch starts runs
        # 0, 1, 2, 4, 6, 8, 10, 12, 14, ... -- the tier-8 batch (i=14/15) is the first whose OWN
        # pre-batch snapshot (14 already accepted) exceeds the cap (12), so it must have dropped the
        # two OLDEST (n0, n1) while keeping the dozen most recent.
        write_plan(self.seed_root, "t2", node_count=16)
        plan16 = plan_read.load("t2", self.seed_root)
        ledger_path = self.seed_root / "_runs" / "ledger16.json"
        rendered: "list[str]" = []

        def fake_call(_system, user, *, config=None, temperature=0.2, schema=None):
            n = len(rendered)
            rendered.append(user)
            return json.dumps(_accepted_response(f"n{n // 3}"))

        with patch("seedsmith.pipeline.llm_caller.call_model", side_effect=fake_call):
            result = run.run_language_stage(plan16, _inputs_for, ledger_path=ledger_path,
                                            seed_root=self.seed_root, config=TEST_CONFIG)

        self.assertTrue(all(o.outcome == "accepted" for o in result.outcomes))
        # Subject index 14 (0-indexed) is the first of the tier-8 batch -- its own base call is the
        # 15th subject's first call, i.e. rendered[14 * 3].
        tier8_base_call = rendered[14 * 3]
        self.assertNotIn("Test Node n0 (", tier8_base_call)
        self.assertNotIn("Test Node n1 (", tier8_base_call)
        self.assertIn("Test Node n2", tier8_base_call)
        self.assertIn("Test Node n13", tier8_base_call)


class DeriveUniqueNameKeyTests(unittest.TestCase):
    """2026-09-06 real-call finding, the deeper of two: even after `schema.py`'s own `nameKey`
    description was fixed to say "derive this from your own name" explicitly, the real local model
    reproduced the IDENTICAL generic templated key on a fresh run -- proving wording alone is not a
    durable fix for a demonstrated real-model failure to follow this instruction twice. `nameKey` is
    no longer trusted from the model's own response at all; `_derive_unique_name_key` computes it,
    deterministically, from the model's own accepted `name`."""

    def test_a_fresh_name_slugifies_with_no_suffix(self) -> None:
        self.assertEqual(run._derive_unique_name_key("Primal Surge", known_name_keys=set()),
                         "tree.node.primal-surge")

    def test_punctuation_and_mixed_case_fold_to_one_hyphen_run(self) -> None:
        self.assertEqual(run._derive_unique_name_key("  Weight of Intent!! ", known_name_keys=set()),
                         "tree.node.weight-of-intent")

    def test_a_name_that_collapses_to_nothing_falls_back_to_a_real_slug_not_an_empty_one(self) -> None:
        # NAME_KEY_PATTERN requires at least one character after "tree.node." -- a name that is pure
        # punctuation must never produce an invalid, schema-refused key.
        self.assertEqual(run._derive_unique_name_key("***", known_name_keys=set()), "tree.node.node")

    def test_a_colliding_slug_gets_the_next_free_numeric_suffix(self) -> None:
        known = {"tree.node.deep-rooting"}
        self.assertEqual(run._derive_unique_name_key("Deep Rooting", known_name_keys=known),
                         "tree.node.deep-rooting-2")

    def test_suffix_search_skips_every_already_taken_number_not_just_the_first(self) -> None:
        known = {"tree.node.deep-rooting", "tree.node.deep-rooting-2", "tree.node.deep-rooting-3"}
        self.assertEqual(run._derive_unique_name_key("Deep Rooting", known_name_keys=known),
                         "tree.node.deep-rooting-4")

    def test_forty_identically_named_nodes_all_get_forty_distinct_keys(self) -> None:
        # The exact real shape (`might`'s own smoke test): the model returns the SAME name forty
        # times over. Every derived key must still be unique -- proven by actually deriving all 40,
        # not asserting a formula.
        known: "set[str]" = set()
        derived = []
        for _ in range(40):
            key = run._derive_unique_name_key("Deep Rooting", known_name_keys=known)
            known.add(key)
            derived.append(key)
        self.assertEqual(len(derived), len(set(derived)))
        self.assertEqual(derived[0], "tree.node.deep-rooting")
        self.assertEqual(derived[1], "tree.node.deep-rooting-2")
        self.assertEqual(derived[39], "tree.node.deep-rooting-40")


class NullishBlockedTokenTests(unittest.TestCase):
    """2026-09-06 real-call finding (`might`, tier-4 mechanism node, LM Studio local model): asked to
    leave `blocked` as the empty string, the model wrote a full valid draft with `"blocked": "none"`
    instead — the exact same real-call finding `general_propose.derive._NULLISH_BLOCKED_TOKENS`'s own
    docstring already measured for a different local model (2026-09-04, "false"/"none"), this module
    simply never adopted. Proven here with fakes (zero real cost): a response that is otherwise fully
    valid, but carries a nullish token in `blocked`, must be ACCEPTED, not read as a genuine decline."""

    def setUp(self) -> None:
        self.seed_root = Path(tempfile.mkdtemp())
        write_plan(self.seed_root, "t1", node_count=1)
        self.plan = plan_read.load("t1", self.seed_root)
        self.ledger_path = self.seed_root / "_runs" / "ledger.json"

    def _response_with_blocked(self, token: str) -> str:
        payload = _accepted_response()
        payload["blocked"] = token
        return json.dumps(payload)

    def test_a_full_valid_draft_with_blocked_none_is_accepted_not_declined(self) -> None:
        with patch("seedsmith.pipeline.llm_caller.call_model",
                  return_value=self._response_with_blocked("none")):
            result = run.run_language_stage(self.plan, _inputs_for, ledger_path=self.ledger_path,
                                            seed_root=self.seed_root, config=TEST_CONFIG)
        self.assertEqual(result.outcomes[0].outcome, "accepted",
                         f"a real, valid draft must not be misread as a decline just because "
                         f"`blocked` held a nullish word instead of the empty string; detail="
                         f"{result.outcomes[0].detail!r}")

    def test_every_measured_nullish_token_is_folded_case_and_whitespace_insensitively(self) -> None:
        for token in ("none", "None", "  NONE  ", "false", "False", "null", "n/a", "na", "N/A"):
            with self.subTest(token=token):
                out = run._normalize_blocked({"blocked": token, "x": 1})
                self.assertEqual(out["blocked"], "", f"{token!r} must fold to the empty string")
                self.assertEqual(out["x"], 1, "every OTHER field must pass through untouched")

    def test_a_genuine_decline_reason_is_never_normalized_away(self) -> None:
        real_reason = "magnitude node requires an existing effect to scale; none of the permitted list fits"
        out = run._normalize_blocked({"blocked": real_reason})
        self.assertEqual(out["blocked"], real_reason)

    def test_true_is_deliberately_left_alone_no_real_call_evidence_for_that_direction(self) -> None:
        out = run._normalize_blocked({"blocked": "true"})
        self.assertEqual(out["blocked"], "true")


def _write_two_mechanism_one_magnitude_plan(seed_root: Path, tree_id: str = "t1") -> None:
    """One tier: two mechanism nodes (n0, n1 -- meant to run in the SAME parallel batch) and one
    magnitude node (n2 -- the next batch, meant to see BOTH n0 and n1 as tier-siblings)."""
    plan = {
        "schemaVersion": 1, "treeId": tree_id, "archetype": "broad-and-flat",
        "propertyVocabulary": {"posture": ["vanguard", "warden"]},
        "mechNodesByTier": [2, 0, 0, 0, 0, 0, 0, 0, 0, 0],
        "nodes": [
            {"id": f"skill.{tree_id}-off-t1-n0", "nodeKey": "n0", "branch": "offensive", "tier": 1,
             "indexInTier": 0, "nodeClass": "mechanism", "budgetShareMilli": 333, "budgetPoints": 25},
            {"id": f"skill.{tree_id}-off-t1-n1", "nodeKey": "n1", "branch": "offensive", "tier": 1,
             "indexInTier": 1, "nodeClass": "mechanism", "budgetShareMilli": 333, "budgetPoints": 25},
            {"id": f"skill.{tree_id}-off-t1-n2", "nodeKey": "n2", "branch": "offensive", "tier": 1,
             "indexInTier": 2, "nodeClass": "magnitude", "budgetShareMilli": 334, "budgetPoints": 25},
        ],
    }
    path = seed_root / "passive-tree" / "plan" / f"{tree_id}.v1.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(plan, indent=2) + "\n", encoding="utf-8")


class BatchedParallelExecutionTests(unittest.TestCase):
    """2026-09-06, owner request: `max_workers>1` fans out WITHIN a `(tier, node_class)` batch (no
    subject in a batch can be another's sibling), never ACROSS batches (a later batch must see an
    earlier one's real accepted siblings) — proven here, not just claimed."""

    def setUp(self) -> None:
        self.seed_root = Path(tempfile.mkdtemp())
        _write_two_mechanism_one_magnitude_plan(self.seed_root, "t1")
        self.plan = plan_read.load("t1", self.seed_root)
        self.ledger_path = self.seed_root / "_runs" / "ledger.json"

    def test_default_max_workers_one_is_byte_identical_to_the_pre_existing_sequential_path(self) -> None:
        # The exact same multi-call fixture RunLanguageStageMultiNodeTests already trusts, run once
        # with the new parameter explicit at its default and once omitted entirely -- both must
        # produce the identical seed document, proving the new parameter changes nothing by default.
        write_plan(self.seed_root, "t2", node_count=2)
        plan2 = plan_read.load("t2", self.seed_root)
        responses = ([json.dumps(_accepted_response("n0"))] * 3 + [json.dumps(_accepted_response("n1"))] * 3)
        with patch("seedsmith.pipeline.llm_caller.call_model", side_effect=list(responses)):
            explicit = run.run_language_stage(plan2, _inputs_for, ledger_path=self.seed_root / "l1.json",
                                              seed_root=self.seed_root, config=TEST_CONFIG, max_workers=1)
        with patch("seedsmith.pipeline.llm_caller.call_model", side_effect=list(responses)):
            omitted = run.run_language_stage(plan2, _inputs_for, ledger_path=self.seed_root / "l2.json",
                                             seed_root=self.seed_root, config=TEST_CONFIG)
        self.assertEqual(explicit.seed_path.read_bytes(), omitted.seed_path.read_bytes())

    def test_two_nodes_in_the_same_batch_never_see_each_other_as_siblings(self) -> None:
        # n0 and n1 (the SAME batch) each run entirely within ONE worker thread for their whole
        # generation (all 3 of a subject's own sample calls come from the thread that drew it from
        # the pool) -- a global call counter cannot tell them apart under real concurrency (their own
        # 3-call sequences interleave unpredictably), but THREAD IDENTITY can: whichever thread makes
        # a given call, ALL of that subject's calls share it. n2 (the next, size-1 batch) runs
        # in-process on the CURRENT thread, a third, distinct identity.
        import threading
        import time

        rendered_by_thread: "dict[int, list[str]]" = {}
        lock = threading.Lock()
        counter = itertools.count()

        def fake_call(_system, user, *, config=None, temperature=0.2, schema=None):
            # `ThreadPoolExecutor` only guarantees `max_workers` as an UPPER bound on concurrency,
            # never a lower one -- a near-instant fake call can complete before the pool ever spins up
            # a second thread, silently collapsing this "two real threads" test into one. A brief
            # sleep on every call forces both submitted tasks to genuinely overlap.
            time.sleep(0.02)
            tid = threading.get_ident()
            with lock:
                rendered_by_thread.setdefault(tid, []).append(user)
                n = next(counter)
            return json.dumps(_accepted_response(f"c{n}"))

        with patch("seedsmith.pipeline.llm_caller.call_model", side_effect=fake_call):
            result = run.run_language_stage(self.plan, _inputs_for, ledger_path=self.ledger_path,
                                            seed_root=self.seed_root, config=TEST_CONFIG, max_workers=2)

        self.assertEqual(len(result.outcomes), 3)
        self.assertTrue(all(o.outcome == "accepted" for o in result.outcomes),
                        [(o.subject_id, o.outcome, o.detail) for o in result.outcomes])

        main_thread_calls = rendered_by_thread.pop(threading.get_ident())
        # n2 (batch 2, size 1) always runs in-process on the calling thread -- its 3 calls are the
        # main thread's own entry.
        self.assertEqual(len(main_thread_calls), 3)
        # Exactly two OTHER threads did the batch-1 work (n0, n1), each making exactly 3 calls.
        self.assertEqual(sorted(len(v) for v in rendered_by_thread.values()), [3, 3])
        for calls in rendered_by_thread.values():
            self.assertIn("(none yet)", calls[0],
                         "a batch-1 subject must never see the OTHER batch-1 subject as a sibling")
        # n2's own brief names BOTH accepted batch-1 records as real tier-siblings, by NAME -- the
        # base call's own accepted `name` is `Test Node c<k>` for whichever unique call index k was
        # each subject's own sample_index=0 call; assert both real accepted names appear, never the
        # empty-sibling placeholder.
        accepted_names = {o.record.name for o in result.outcomes if o.record is not None
                          and o.subject_id != "t1:skill.t1-off-t1-n2"}
        self.assertEqual(len(accepted_names), 2)
        for name in accepted_names:
            self.assertIn(name, main_thread_calls[0])
        self.assertNotIn("(none yet)", main_thread_calls[0])

    def test_outcomes_are_returned_in_plan_order_regardless_of_which_worker_finishes_first(self) -> None:
        # n0 and n1 (the same batch) run in two DIFFERENT worker threads, submitted concurrently --
        # their own 3-call sequences (base + 2 votes) interleave unpredictably at the transport level,
        # so a global call counter cannot reliably tell them apart. Rather than guess which thread is
        # "n0", this makes the FIRST call from each newly-seen thread sleep once -- since the pool has
        # 2 workers for a 2-subject batch, this reliably makes whichever subject's thread happens to
        # start LAST finish first, forcing at least one real completion-order/plan-order mismatch
        # without needing to know which logical subject that thread belongs to. Every call gets a
        # globally unique name/nameKey (an itertools.count(), never tied to node identity) so no two
        # calls can collide regardless of interleaving.
        import time
        import threading

        seen_threads: "set[int]" = set()
        lock = threading.Lock()
        counter = itertools.count()

        def interleaving_call(_system, user, *, config=None, temperature=0.2, schema=None):
            tid = threading.get_ident()
            with lock:
                is_new = tid not in seen_threads
                seen_threads.add(tid)
            if is_new:
                time.sleep(0.05)
            n = next(counter)
            return json.dumps(_accepted_response(f"c{n}"))

        with patch("seedsmith.pipeline.llm_caller.call_model", side_effect=interleaving_call):
            result = run.run_language_stage(self.plan, _inputs_for, ledger_path=self.ledger_path,
                                            seed_root=self.seed_root, config=TEST_CONFIG, max_workers=2)

        self.assertTrue(all(o.outcome == "accepted" for o in result.outcomes),
                        [(o.subject_id, o.outcome, o.detail) for o in result.outcomes])
        subject_order = [o.subject_id for o in result.outcomes]
        self.assertEqual(subject_order, [
            "t1:skill.t1-off-t1-n0", "t1:skill.t1-off-t1-n1", "t1:skill.t1-off-t1-n2",
        ], "outcomes must follow plan order, never worker-completion order")

    def test_two_same_batch_subjects_picking_one_name_never_lose_the_tree(self) -> None:
        """2026-09-11 real-call finding, `might` with `--workers 4`. The generation-time gates run
        against a snapshot taken BEFORE a parallel batch starts, so two subjects in ONE batch can
        independently pick the identical name/nameKey. Before this fix the collision surfaced only at
        emit time, where `build_seed_document`'s `assert_no_duplicate_name_keys` refused the WHOLE
        tree (a real run lost all accepted nodes to one such pair). The sequential path already
        self-healed via `known_name_keys`; this pins the parallel path to the same guarantee.
        """
        import time
        import threading

        # Both subjects in the one batch answer with the IDENTICAL name and nameKey on every sample.
        twin = {"affixIds": ["atom.a"], "affinity": ["core"],
                "exclusion": {"form": "none", "propertyKeys": []},
                "name": "Twin Node", "nameKey": "tree.node.twin-node",
                "flavor": "A steady line.", "rationale": "", "blocked": ""}

        def colliding_call(_system, user, *, config=None, temperature=0.2, schema=None):
            time.sleep(0.02)  # force the two submitted tasks to genuinely overlap
            return json.dumps(twin)

        with patch("seedsmith.pipeline.llm_caller.call_model", side_effect=colliding_call):
            result = run.run_language_stage(self.plan, _inputs_for, ledger_path=self.ledger_path,
                                            seed_root=self.seed_root, config=TEST_CONFIG, max_workers=2)

        # No whole-tree refusal: a seed document exists and holds at least the first subject.
        self.assertIsNotNone(result.seed_path)
        doc = json.loads(result.seed_path.read_text(encoding="utf-8"))
        keys = [n["nameKey"] for n in doc["nodes"]]
        names = [n["name"] for n in doc["nodes"]]
        self.assertEqual(len(keys), len(set(keys)), "no duplicate nameKey may be persisted")
        self.assertEqual(len(names), len(set(names)), "no duplicate name may be persisted")
        # The colliding twin is an honest `unresolved` (gate 21: re-prompted, never persisted), not
        # a crash and not a silent rename.
        unresolved = [o for o in result.outcomes
                      if o.outcome == "unresolved" and "already taken" in o.detail]
        self.assertTrue(unresolved,
                        [(o.subject_id, o.outcome, o.detail) for o in result.outcomes])
        ledger = run.read_ledger(self.ledger_path)
        self.assertIn(unresolved[0].subject_id, ledger)
        self.assertIsNone(ledger[unresolved[0].subject_id]["record"])
        self.assertEqual("unresolved", ledger[unresolved[0].subject_id]["outcome"])
        self.assertEqual(1, ledger[unresolved[0].subject_id]["attempts"])


class RunLanguageStageMultiNodeTests(unittest.TestCase):
    """A tree with more than one node: only the UNRESOLVED ones are ever regenerated on a rerun,
    and the seed document's own node ORDER is a pure function of `node_id` — never dict/insertion
    order — which is what makes the byte-identical property hold regardless of which subject
    happened to finish first."""

    def setUp(self) -> None:
        self.seed_root = Path(tempfile.mkdtemp())
        write_plan(self.seed_root, "t1", node_count=2)
        self.plan = plan_read.load("t1", self.seed_root)
        self.ledger_path = self.seed_root / "_runs" / "ledger.json"

    def test_two_nodes_both_accept_and_the_seed_document_is_sorted_by_node_id(self) -> None:
        # 3 calls (base + 2 vote samples) per node, in `plan.subjects` order (n0 then n1) --
        # each node's own `nameKey` must be distinct, or `build_seed_document`'s own
        # `assert_no_duplicate_name_keys` refuses the whole tree.
        responses = ([json.dumps(_accepted_response("n0"))] * 3
                    + [json.dumps(_accepted_response("n1"))] * 3)
        with patch("seedsmith.pipeline.llm_caller.call_model", side_effect=responses):
            result = run.run_language_stage(self.plan, _inputs_for, ledger_path=self.ledger_path,
                                            seed_root=self.seed_root, config=TEST_CONFIG)
        doc = json.loads(result.seed_path.read_text(encoding="utf-8"))
        ids = [n["id"] for n in doc["nodes"]]
        self.assertEqual(ids, sorted(ids))


class CrossTreeNameKeyDedupTests(unittest.TestCase):
    """2026-09-06 real-call finding: `nameKey` is spec-mandated "deduplicated corpus-wide"
    (spec-tree-language.md's own field table), not per-tree — but `known_name_keys` used to be seeded
    only from `plan.already_done`, ONE tree's own accepted subjects. Two different real trees run the
    same day independently minted the identical `tree.node.primal-surge` key from the same
    model-chosen name, unaware of each other (46 real collisions found across the 12 trees committed
    so far). Reproduced here with two synthetic trees sharing the SAME ledger file — the real
    production shape, where every tree's `--write` run reads and writes the one shared
    `tree-language.ledger.json`."""

    def setUp(self) -> None:
        self.seed_root = Path(tempfile.mkdtemp())
        write_plan(self.seed_root, "tree-a", node_count=1)
        write_plan(self.seed_root, "tree-b", node_count=1)
        self.plan_a = plan_read.load("tree-a", self.seed_root)
        self.plan_b = plan_read.load("tree-b", self.seed_root)
        self.ledger_path = self.seed_root / "_runs" / "ledger.json"

    def test_a_second_tree_naming_the_same_thing_is_refused_at_generation_time(self) -> None:
        same_name_payload = json.dumps(_named_response("Primal Surge"))
        with patch("seedsmith.pipeline.llm_caller.call_model", return_value=same_name_payload):
            first = run.run_language_stage(self.plan_a, _inputs_for, ledger_path=self.ledger_path,
                                           seed_root=self.seed_root, config=TEST_CONFIG)
        self.assertEqual(first.outcomes[0].record.name_key, "tree.node.primal-surge")

        with patch("seedsmith.pipeline.llm_caller.call_model", return_value=same_name_payload):
            second = run.run_language_stage(self.plan_b, _inputs_for, ledger_path=self.ledger_path,
                                            seed_root=self.seed_root, config=TEST_CONFIG)
        # 2026-09-11 contract change (gate 21's generation-time half): the second tree naming the
        # EXACT same thing is now REFUSED, not suffixed — the corpus metric counts a same-name draft
        # from a different tree as the collision defect, so no per-item check that saw only this
        # tree's own ledger could have distinguished "suffixed key, same name" from a real one.
        # Before this half was wired, tree-b persisted the SAME bare name under `-2`'s key and
        # `PassiveTree/NameCollision` flagged 46 real cross-tree collisions post-hoc.
        self.assertEqual(second.outcomes[0].outcome, "escalated")
        self.assertIn("already used by another", second.outcomes[0].detail)
        # The ledger now HONESTLY records the failed attempt (2026-09-11): tree-b's row exists, but
        # with `record: null`, so the node is still owed a generation on the next pass — never a
        # phantom "accepted" and never invisible. No accepted content leaked into the seed document.
        ledger = run.read_ledger(self.ledger_path)
        self.assertEqual(len(ledger), 2)
        attempt = ledger["tree-b:skill.tree-b-off-t1-n0"]
        self.assertIsNone(attempt["record"])
        self.assertEqual(attempt["outcome"], "escalated")
        self.assertEqual(1, attempt["attempts"])
        self.assertFalse(
            (self.seed_root / "passive-tree" / "nodes" / "tree-b.json").exists())

    def test_a_second_tree_with_a_distinct_name_gets_a_free_key_not_a_collision(self) -> None:
        # The ORIGINAL suffix contract survives under the new gate, narrowed to its only remaining
        # legitimate shape: the model picks a DISTINCT name that slugs identically (casing), so gate
        # 21 (exact-name) passes while `_derive_unique_name_key` still must suffix the KEY.
        first_payload = json.dumps(_named_response("Primal Surge"))
        second_payload = json.dumps(_named_response("PRIMAL SURGE"))
        with patch("seedsmith.pipeline.llm_caller.call_model", return_value=first_payload):
            first = run.run_language_stage(self.plan_a, _inputs_for, ledger_path=self.ledger_path,
                                           seed_root=self.seed_root, config=TEST_CONFIG)
        self.assertEqual(first.outcomes[0].record.name_key, "tree.node.primal-surge")
        with patch("seedsmith.pipeline.llm_caller.call_model", return_value=second_payload):
            second = run.run_language_stage(self.plan_b, _inputs_for, ledger_path=self.ledger_path,
                                            seed_root=self.seed_root, config=TEST_CONFIG)
        self.assertEqual(second.outcomes[0].outcome, "accepted")
        self.assertEqual(second.outcomes[0].record.name_key, "tree.node.primal-surge-2")

    def test_a_third_tree_still_finds_a_free_suffix_after_two_others_already_took_the_key(self) -> None:
        first_payload = json.dumps(_named_response("Primal Surge"))
        second_payload = json.dumps(_named_response("PRIMAL SURGE"))
        third_payload = json.dumps(_named_response("Primal surge"))
        write_plan(self.seed_root, "tree-c", node_count=1)
        plan_c = plan_read.load("tree-c", self.seed_root)

        for plan, payload in ((self.plan_a, first_payload), (self.plan_b, second_payload),
                              (plan_c, third_payload)):
            with patch("seedsmith.pipeline.llm_caller.call_model", return_value=payload):
                run.run_language_stage(plan, _inputs_for, ledger_path=self.ledger_path,
                                       seed_root=self.seed_root, config=TEST_CONFIG)

        ledger = run.read_ledger(self.ledger_path)
        keys = {entry["record"]["nameKey"] for entry in ledger.values()}
        self.assertEqual(keys, {"tree.node.primal-surge", "tree.node.primal-surge-2",
                                "tree.node.primal-surge-3"})


class SpeciesCategoryTreeResumabilityTests(unittest.TestCase):
    """Task J8's own remaining acceptance bullet: "the run is resumable... proven by a mid-run kill
    test." `run_language_stage` (this file's whole subject) is ALREADY proven resumable for generic
    trees above -- this class proves the SAME property holds for a REAL species-category plan, built
    through the actual `species_tree_spec`/`build_plan` pipeline (task J8's own `TreeSpec.
    mechanical_favour` + `build_slot` fixes), not a hand-typed fixture standing in for one. No new
    resumability machinery was built for species trees because none was needed: `run_language_stage`
    never branches on `category` at all, so a correctly-shaped species plan already gets the
    identical ledger-backed idempotence every generic tree already has -- proven here, not assumed."""

    def setUp(self) -> None:
        from seedsmith.adapters.trees.nodegen import quota as quota_mod
        from seedsmith.adapters.trees.nodegen import vocab as vocab_mod
        from seedsmith.adapters.trees.plan import emit as plan_emit
        from seedsmith.adapters.trees.plan import tuning as plan_tuning

        self.seed_root = Path(tempfile.mkdtemp())
        self.ledger_path = self.seed_root / "_runs" / "ledger.json"

        spec = plan_emit.species_tree_spec("AbyssSwordStar", 0, ("Onslaught", "air", "spark"))
        plan_dict = plan_emit.build_plan(spec, plan_tuning.load())
        self.plan = plan_read.load_from_dict(plan_dict, source_label="species:AbyssSwordStar")
        # The fixed tree-shape size is never pinned as a literal (population-pin SE3.5, 2026-09-20).
        self.assertTrue(len(self.plan.nodes) > 0)  # a real, full-size species tree, not a stub shape

        real_targets = __import__(
            "seedsmith.adapters.trees.nodegen.tuning", fromlist=["load"]).load()
        self.cells = quota_mod.quota_for_plan(
            self.plan, real_targets, category="species", forced_element="air", forced_status="spark")
        self.affix_vocab = vocab_mod.build()

    def _inputs_for(self, subject: "run.Subject") -> "run.NodeGenerationInputs":
        from seedsmith.adapters.trees.nodegen import quota as quota_mod
        cell = self.cells[subject.node_id]
        permitted_ids = quota_mod.permitted_ids_for_cell(cell, self.plan.property_vocabulary)
        permitted_affixes = self.affix_vocab.permitted_for_branch(subject.branch)
        return run.NodeGenerationInputs(
            tree_display_name="AbyssSwordStar", tree_reading="AbyssSwordStar",
            motifs=(), anti_motifs=(), anti_motif_tags=(),
            permitted_affixes=permitted_affixes, permitted_properties=sorted(self.plan.property_vocabulary),
            property_vocabulary=self.plan.property_vocabulary, affix_vocab=self.affix_vocab)

    def test_every_forced_axis_reaches_the_real_quota_cells_species_needed_this_for(self) -> None:
        # The real end-to-end proof `build_slot`'s own fix exists for: every one of the real 40
        # nodes forced to the SAME element+status, reached via the exact quota_for_plan call
        # run_language_stage's own real callers (e.g. _cmd_trees_generate) already make.
        # Same fixed tree-shape size as setUp's plan -- never a second literal (population-pin
        # SE3.5, 2026-09-20).
        self.assertEqual(len(self.plan.nodes), len(self.cells))
        for cell in self.cells.values():
            self.assertEqual("air", cell.value_for("element"))
            self.assertEqual("spark", cell.value_for("status"))

    @staticmethod
    def _response_for_schema(node_key: str, schema: "dict | None") -> str:
        """The real `affix_vocab` (112 shipped families, not the sibling tests' own tiny synthetic
        `VOCAB`) means `_accepted_response`'s own hardcoded `"atom.a"` is never a permitted id here
        -- found for real the first time this test ran (`'accepted' != 'escalated'`, the content
        gate correctly refusing a name it does not recognise). `schema_for_call`'s own gate-8
        per-call `enum` (`nodegen/schema.py`) always carries the REAL permitted affix ids for this
        exact node, so reading the first one back off the schema the generate node call itself
        received is what makes this response actually valid, for any node, without hand-maintaining
        a fixture of real ids that could drift from the shipped library.
        """
        response = _accepted_response(node_key)
        enum = (schema or {}).get("properties", {}).get("affixIds", {}).get("items", {}).get("enum") or []
        if enum:
            response["affixIds"] = [enum[0]]
        return json.dumps(response)

    def test_a_mid_run_kill_then_resume_produces_no_duplicate_provenance_and_completes_the_tree(self) -> None:
        # Simulates "the process died after N nodes" the SAME way this file's own generic-tree
        # test does (`test_a_resumed_run_seeds_siblings_from_the_ledger_not_only_this_runs_own_
        # acceptances`, above): run a handful of subjects directly via `generate_node` +
        # `record_accepted` + `write_ledger`, never through `run_language_stage` at all for the
        # "first, partial run" -- a real, previous finding (this file's own comment on that test)
        # is that `LlmCallerConfig.attempts=2` retries a raised transport error internally rather
        # than propagating it out of `run_language_stage`, so an exception-based "kill" would not
        # actually reproduce a mid-run crash here; this is the proven-correct way to do it instead.
        partial_plan = run.plan_run(self.plan, ledger={})
        first_five = partial_plan.subjects[:5]
        done: "dict[str, dict]" = {}
        killed_node_keys: "list[str]" = []

        def _kill_stub(system, user, *, config=None, temperature=0.2, schema=None):
            return self._response_for_schema(f"killed-{len(killed_node_keys)}", schema)

        with patch("seedsmith.pipeline.llm_caller.call_model", side_effect=_kill_stub):
            for subject in first_five:
                outcome = run.generate_node(subject, self._inputs_for(subject), config=TEST_CONFIG)
                self.assertEqual("accepted", outcome.outcome)
                killed_node_keys.append(outcome.record.name_key)
                done = run.record_accepted(done, subject.subject_id, outcome.record)
        run.write_ledger(done, self.ledger_path)
        self.assertEqual(5, len(run.read_ledger(self.ledger_path)))
        self.assertEqual(5, len(set(killed_node_keys)), "even the killed partial run mints distinct keys")

        # Resume: a fresh process, a fresh call stub. Real finding while writing this test
        # (`generate_node` makes THREE calls per node, not one -- §7.1's own "vote exactly one
        # field" cost table, confirmed live here by inspecting the raw call log): a naive per-CALL
        # counter would hand three DIFFERENT names to the same node's own three votes, which could
        # never resolve. Checked and rejected: keying on the prompt text (permuted per sample,
        # `creatures.anchor.permute.order_for`'s own precedent, so NOT identical within a node) or on
        # the schema (byte-identical within a node, but multiple DIFFERENT nodes sharing a branch
        # can carry the identical permitted-affix schema too, since every node in this tree is
        # forced to the SAME element+status -- schema-keying would wrongly collapse them). The
        # reliable signal is call ORDER: `max_workers=1` (this call's own default) makes
        # `generate_node`'s three votes strictly consecutive, so `(call_index // 3)` is the node
        # index regardless of content -- proven correct by `resume_calls["n"] == 35 * 3` below (not
        # 35): if the first five subjects were regenerated instead of read back from the ledger,
        # this would be 40 * 3, AND at least one of its answers would collide with a killed-run key
        # already in the ledger -- `build_seed_document`'s own duplicate-name-key guard would refuse
        # the whole resumed run outright, which is the concrete, structural meaning of "no duplicate
        # provenance row" this test proves rather than assumes from a call count alone.
        resume_calls = {"n": 0}

        def _resume(system, user, *, config=None, temperature=0.2, schema=None):
            node_index = resume_calls["n"] // 3
            resume_calls["n"] += 1
            return self._response_for_schema(f"resumed-{node_index}", schema)

        with patch("seedsmith.pipeline.llm_caller.call_model", side_effect=_resume):
            result = run.run_language_stage(self.plan, self._inputs_for, ledger_path=self.ledger_path,
                                            seed_root=self.seed_root, config=TEST_CONFIG)

        self.assertEqual(105, resume_calls["n"], "3 votes per node (§7.1's own cost shape) x 35 nodes")
        self.assertEqual(35, len(result.outcomes), "the resumed run's own outcomes are the REMAINDER")
        final_ledger = run.read_ledger(self.ledger_path)
        self.assertEqual(40, len(final_ledger), "the full tree, no more no less, once resumed")
        # No duplicate provenance row: every one of the 40 final subject ids is distinct (a dict
        # already guarantees this structurally, but the count check above is what proves nothing
        # was silently dropped OR double-counted across the kill/resume boundary), and the seed
        # document itself was actually written (build_seed_document did not refuse).
        # Self-referential (population-pin SE3.5, 2026-09-20): both sides read back the same fixed
        # tree-shape size the ledger and the written seed document must agree on, never a literal.
        self.assertEqual(len(self.plan.nodes), len(set(final_ledger.keys())))
        self.assertIsNotNone(result.seed_path)
        doc = json.loads(result.seed_path.read_text(encoding="utf-8"))
        self.assertEqual(len(self.plan.nodes), len(doc["nodes"]))

    def test_a_species_tree_never_forces_neither_axis_the_bug_this_whole_feature_would_have_shipped_with(self) -> None:
        # Historical-regression guard: before `build_slot`'s own fix (task J8, 2026-09-07), a
        # species-category quota_for_plan call would have silently returned a FREELY-DRAWN element/
        # status distribution instead of refusing OR forcing -- this is the one test in this whole
        # suite that would have gone red (by finding more than one distinct value) had that fix been
        # reverted, without needing to re-read build_slot's own source to notice.
        distinct_elements = {cell.value_for("element") for cell in self.cells.values()}
        distinct_statuses = {cell.value_for("status") for cell in self.cells.values()}
        self.assertEqual({"air"}, distinct_elements)
        self.assertEqual({"spark"}, distinct_statuses)

class ProvenanceSupersedeTests(unittest.TestCase):
    """spec-tree-review.md §8's provenance-supersede pass, end to end at stage level (2026-09-11).

    `record_superseded` (the ledger primitive) was always unit-tested; what never existed was the
    PRODUCTION path: a caller that asks the runner to re-roll every ledger row whose per-record
    `promptVersion` is absent or differs from the current brief vintage, preserving the prior row
    under `supersededRecord`. `plan_run(supersede_stale=True)` finds stale rows and schedules them
    (they ride `plan.subjects`); `_record_outcome` routes their acceptance through
    `record_superseded`. Proven here at each seam, against a real synthetic plan.
    """

    def setUp(self) -> None:
        self.seed_root = Path(tempfile.mkdtemp())
        write_plan(self.seed_root, "t1", node_count=2)
        self.plan = plan_read.load("t1", self.seed_root)
        self.ledger_path = self.seed_root / "_runs" / "ledger.json"

    @staticmethod
    def _payload_stub(node_keys):
        """3 calls per node (base + 2 vote samples, §7.1's cost shape), strictly consecutive under
        max_workers=1, so `(call_index // 3)` keys which node a call belongs to — the same
        call-order trick `SpeciesCategoryTreeResumabilityTests` proven-uses above. Distinct names
        per node also keep gate 21 (the taken-names gate) from refusing the second subject."""
        calls = {"n": 0}
        payloads = [json.dumps(_accepted_response(k)) for k in node_keys]

        def _call(*args, **kwargs):
            payload = payloads[min(calls["n"] // 3, len(payloads) - 1)]
            calls["n"] += 1
            return payload

        return _call

    def _age_off_vintage(self) -> None:
        """Rewrite the ledger WITHOUT per-record promptVersion — the exact shape of every row
        committed before 2026-09-11 (the vintage `supersede_stale` exists to re-roll)."""
        ledger = run.read_ledger(self.ledger_path)
        for entry in ledger.values():
            entry["record"].pop("promptVersion", None)
        run.write_ledger(ledger, self.ledger_path)

    def _flagged(self, stub):
        with patch("seedsmith.pipeline.llm_caller.call_model", side_effect=stub):
            return run.run_language_stage(self.plan, _inputs_for, ledger_path=self.ledger_path,
                                          seed_root=self.seed_root, config=TEST_CONFIG,
                                          supersede_stale=True)

    def test_a_pre_provenance_row_is_re_rolled_and_the_prior_row_is_preserved(self) -> None:
        with patch("seedsmith.pipeline.llm_caller.call_model",
                   side_effect=self._payload_stub(["n0", "n1"])):
            first = run.run_language_stage(self.plan, _inputs_for, ledger_path=self.ledger_path,
                                           seed_root=self.seed_root, config=TEST_CONFIG)
        self.assertEqual(2, len(first.outcomes))
        self.assertTrue(all(o.outcome == "accepted" for o in first.outcomes))

        self._age_off_vintage()

        # Flagged pass: both rows are stale (no vintage), so both re-roll; the new rows carry the
        # current brief vintage while the prior rows survive under supersededRecord.
        second = self._flagged(self._payload_stub(["n0", "n1"]))
        self.assertEqual(2, len(second.outcomes))
        self.assertTrue(all(o.outcome == "accepted" for o in second.outcomes))
        ledger = run.read_ledger(self.ledger_path)
        self.assertEqual(2, len(ledger))
        for entry in ledger.values():
            self.assertEqual(run.brief_mod.PROMPT_VERSION, entry["record"]["promptVersion"])
            self.assertIn("supersededRecord", entry)
            self.assertNotIn("promptVersion", entry["supersededRecord"])

        # A third flagged pass is a no-op: every row now carries the current vintage.
        with patch("seedsmith.pipeline.llm_caller.call_model", side_effect=raising_call) as mocked:
            third = run.run_language_stage(self.plan, _inputs_for, ledger_path=self.ledger_path,
                                           seed_root=self.seed_root, config=TEST_CONFIG,
                                           supersede_stale=True)
        mocked.assert_not_called()
        self.assertEqual(0, len(third.outcomes), "nothing stale left — zero model calls")
        self.assertEqual(2, len(run.read_ledger(self.ledger_path)))

    def test_a_current_vintage_row_is_never_superseded(self) -> None:
        # First pass stamps the CURRENT vintage (generate_node's own per-record provenance); a
        # second flagged pass must replay from the ledger — zero model calls, no supersededRecord.
        with patch("seedsmith.pipeline.llm_caller.call_model",
                   side_effect=self._payload_stub(["n0", "n1"])):
            run.run_language_stage(self.plan, _inputs_for, ledger_path=self.ledger_path,
                                   seed_root=self.seed_root, config=TEST_CONFIG)
        with patch("seedsmith.pipeline.llm_caller.call_model",
                   side_effect=raising_call) as mocked:
            result = run.run_language_stage(self.plan, _inputs_for, ledger_path=self.ledger_path,
                                            seed_root=self.seed_root, config=TEST_CONFIG,
                                            supersede_stale=True)
        mocked.assert_not_called()
        ledger = run.read_ledger(self.ledger_path)
        self.assertEqual(2, len(ledger))
        self.assertTrue(all("supersededRecord" not in e for e in ledger.values()))
        self.assertEqual(0, len(result.outcomes), "a fully-replayed run returns no outcomes")

    def test_supersede_routes_through_record_superseded_not_record_accepted(self) -> None:
        # The routing contract at the seam that matters: a second accept of the same subject would
        # raise under record_accepted's duplicate guard, so a flagged run COMPLETING with the prior
        # row preserved under supersededRecord IS the routing proof.
        with patch("seedsmith.pipeline.llm_caller.call_model",
                   side_effect=self._payload_stub(["n0", "n1"])):
            run.run_language_stage(self.plan, _inputs_for, ledger_path=self.ledger_path,
                                   seed_root=self.seed_root, config=TEST_CONFIG)
        self._age_off_vintage()
        second = self._flagged(self._payload_stub(["n0", "n1"]))
        self.assertTrue(all(o.outcome == "accepted" for o in second.outcomes))
        ledger = run.read_ledger(self.ledger_path)
        self.assertTrue(all("supersededRecord" in e for e in ledger.values()))

    def test_a_stale_row_is_not_double_counted_in_the_run_report_denominator(self) -> None:
        # Gate 23's denominator counts `len(plan.subjects) + len(plan.already_done)`. A superseded
        # subject rides `subjects` and must stay OUT of `already_done`, so a 2-node tree reports
        # 0/2 unresolved — never the 2+2=4 double-count.
        with patch("seedsmith.pipeline.llm_caller.call_model",
                   side_effect=self._payload_stub(["n0", "n1"])):
            run.run_language_stage(self.plan, _inputs_for, ledger_path=self.ledger_path,
                                   seed_root=self.seed_root, config=TEST_CONFIG)
        self._age_off_vintage()
        second = self._flagged(self._payload_stub(["n0", "n1"]))
        # The plan-shape contract itself: a stale subject rides `subjects`, never `already_done`.
        plan = run.plan_run(self.plan, ledger=run.read_ledger(self.ledger_path),
                            supersede_stale=True, prompt_version="v-current")
        self.assertEqual(2, len(plan.subjects))
        self.assertEqual(0, len(plan.already_done))
        # And the gate-23 denominator follows the same shape: 0 unresolved over 2 total, no /4.
        with patch("seedsmith.pipeline.llm_caller.call_model", side_effect=raising_call):
            replay = run.run_language_stage(self.plan, _inputs_for, ledger_path=self.ledger_path,
                                            seed_root=self.seed_root, config=TEST_CONFIG,
                                            supersede_stale=True,
                                            unresolved_max_share_permille=500)
        detail = next(r.detail for r in replay.report.outcomes
                      if r.metric == UNRESOLVED_COUNT_METRIC and r.detail)
        self.assertIn("0/2 unresolved", detail)
        self.assertNotIn("/4", detail)


class FailedSupersedeKeepsPriorNodeTests(unittest.TestCase):
    """A superseded subject whose re-roll FAILS (gate 11's unresolved vote) must not delete the
    already-accepted node it was re-rolling — the seed document stays complete at the plan's own
    node count, with the prior record's content untouched. Before this fix a superseded subject rode
    `plan.subjects` and was only written on ACCEPT, so a failed re-roll left it absent from the seed
    document entirely: a real MechanismRamp shortfall (the tree shrank below its plan) rather than a
    metric artefact.
    """

    def setUp(self) -> None:
        self.seed_root = Path(tempfile.mkdtemp())
        write_plan(self.seed_root, "t1", node_count=2)
        self.plan = plan_read.load("t1", self.seed_root)
        self.ledger_path = self.seed_root / "_runs" / "ledger.json"

    @staticmethod
    def _payload_stub(node_keys):
        calls = {"n": 0}
        payloads = [json.dumps(_accepted_response(k)) for k in node_keys]

        def _call(*args, **kwargs):
            payload = payloads[min(calls["n"] // 3, len(payloads) - 1)]
            calls["n"] += 1
            return payload

        return _call

    def test_a_failed_re_roll_keeps_the_prior_record_in_the_seed_document(self) -> None:
        with patch("seedsmith.pipeline.llm_caller.call_model",
                   side_effect=self._payload_stub(["n0", "n1"])):
            run.run_language_stage(self.plan, _inputs_for, ledger_path=self.ledger_path,
                                   seed_root=self.seed_root, config=TEST_CONFIG)
        # Age the vintage off so both rows are scheduled for re-roll.
        ledger = run.read_ledger(self.ledger_path)
        for entry in ledger.values():
            entry["record"].pop("promptVersion", None)
        run.write_ledger(ledger, self.ledger_path)

        before = json.loads(
            (self.seed_root / "passive-tree" / "nodes" / "t1.json").read_text(encoding="utf-8"))
        before_by_id = {n["id"]: n for n in before["nodes"]}
        self.assertEqual(2, len(before_by_id))

        # The re-roll answers with a DIFFERENT affix on every call: the vote is 1-1-1 (no majority),
        # so both subjects come back `unresolved` and neither prior row is replaced.
        def _unresolved_call(*args, **kwargs):
            return json.dumps({
                "affixIds": ["atom.a"], "affinity": ["core"],
                "exclusion": {"form": "none", "propertyKeys": []},
                "name": "Changed Name", "nameKey": "tree.node.changed",
                "flavor": "A changed line.", "rationale": "", "blocked": "",
            })

        with patch("seedsmith.pipeline.llm_caller.call_model", side_effect=_unresolved_call):
            result = run.run_language_stage(self.plan, _inputs_for, ledger_path=self.ledger_path,
                                            seed_root=self.seed_root, config=TEST_CONFIG,
                                            supersede_stale=True)
        # Whether or not the vote resolves, the tree is never smaller than its plan.
        after = json.loads(
            (self.seed_root / "passive-tree" / "nodes" / "t1.json").read_text(encoding="utf-8"))
        after_ids = {n["id"] for n in after["nodes"]}
        self.assertEqual(2, len(after_ids), "a superseded node must never vanish from the seed doc")
        self.assertEqual(set(before_by_id), after_ids)
        # Every unresolved subject kept its prior content byte-for-byte.
        unresolved_ids = {o.subject_id.split(":", 1)[1] for o in result.outcomes
                          if o.outcome == "unresolved"}
        for node_id in unresolved_ids:
            prior = before_by_id[node_id]
            current = next(n for n in after["nodes"] if n["id"] == node_id)
            self.assertEqual(prior["name"], current["name"])
            self.assertEqual(prior["affixIds"], current["affixIds"])
            self.assertEqual(prior["nameKey"], current["nameKey"])

    def test_a_successful_re_roll_replaces_the_prior_record(self) -> None:
        with patch("seedsmith.pipeline.llm_caller.call_model",
                   side_effect=self._payload_stub(["n0", "n1"])):
            run.run_language_stage(self.plan, _inputs_for, ledger_path=self.ledger_path,
                                   seed_root=self.seed_root, config=TEST_CONFIG)
        ledger = run.read_ledger(self.ledger_path)
        for entry in ledger.values():
            entry["record"].pop("promptVersion", None)
        run.write_ledger(ledger, self.ledger_path)

        def _renamed_call(*args, **kwargs):
            # Same affix on all three samples -> a clean 3-0 accept; a fresh name proves replacement.
            # Distinct names per node (call index // 3) keep the within-tree nameKey rule from
            # refusing the second subject's identical slug.
            calls = _renamed_call.calls
            name = "Fresh Name" if calls // 3 == 0 else "Fresh Name Two"
            _renamed_call.calls += 1
            return json.dumps({
                "affixIds": ["atom.a"], "affinity": ["core"],
                "exclusion": {"form": "none", "propertyKeys": []},
                "name": name, "nameKey": "tree.node.fresh",
                "flavor": "A fresh line.", "rationale": "", "blocked": "",
            })
        _renamed_call.calls = 0

        with patch("seedsmith.pipeline.llm_caller.call_model", side_effect=_renamed_call):
            result = run.run_language_stage(self.plan, _inputs_for, ledger_path=self.ledger_path,
                                            seed_root=self.seed_root, config=TEST_CONFIG,
                                            supersede_stale=True)
        self.assertTrue(any(o.outcome == "accepted" for o in result.outcomes))
        after = json.loads(
            (self.seed_root / "passive-tree" / "nodes" / "t1.json").read_text(encoding="utf-8"))
        self.assertEqual(2, len(after["nodes"]))
        self.assertTrue(all(n["name"].startswith("Fresh Name") for n in after["nodes"]))
        # The prior rows survive under supersededRecord in the ledger.
        final_ledger = run.read_ledger(self.ledger_path)
        self.assertTrue(all("supersededRecord" in e for e in final_ledger.values()))


if __name__ == "__main__":
    unittest.main()