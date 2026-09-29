"""Tests for seedsmith.adapters.trees.nodegen.run's task-H2 additions: the real gate runner over
one node — `build_response_gate`/`brief_conformance_defects` (§7 gate 9), `call_one_node_sample`/
`generate_node` (§7 gates 6, 7, 11, 12, 13), `offline_transport_stub`/`UnexpectedTransportCall`
(§7 gate 24), `audit_node_schema_descriptions` (§7 gate 2).

    python -m pytest gk-forge/tools/seedsmith/tests/adapters/trees/test_nodegen_generate.py -v

Every test that must make zero model calls patches `seedsmith.pipeline.llm_caller.call_model`
with `_nodegen_fixtures.raising_call` — the same offline-transport pattern already used four times
over in this repo (`test_classify_pipelines.py`, `test_family_propose.py`,
`test_general_propose.py`, `test_signature_propose.py`). Every test that DOES exercise a call
patches it with a small scripted stub instead, so no test ever reaches a real network endpoint.
"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _nodegen_fixtures import raising_call  # noqa: E402

from seedsmith.adapters.trees.nodegen import run  # noqa: E402
from seedsmith.adapters.trees.nodegen.vocab import AffixOption, AffixVocabulary  # noqa: E402
from seedsmith.pipeline.llm_caller import LlmCallerConfig  # noqa: E402


AFFIX_A = AffixOption(affix_id="atom.a", name="Alpha Strike", tags=("offensive",), kind_id="k1")
AFFIX_B = AffixOption(affix_id="atom.b", name="Bulwark", tags=("defensive",), kind_id="k2")
AFFIX_C = AffixOption(affix_id="atom.c", name="Cursed Bloom", tags=("utility", "anti"), kind_id="k3")
AFFIX_D = AffixOption(affix_id="atom.d", name="Driftguard", tags=("defensive",), kind_id="k4")
VOCAB = AffixVocabulary(options=(AFFIX_A, AFFIX_B, AFFIX_C, AFFIX_D))

TEST_CONFIG = LlmCallerConfig(max_heal=1)  # 2 attempts total per call — keeps scripts short


def _inputs(**overrides) -> run.NodeGenerationInputs:
    base = dict(
        tree_display_name="Might", tree_reading="the way of raw force",
        motifs=("strength",), anti_motifs=("weakness",), anti_motif_tags=("anti",),
        permitted_affixes=(AFFIX_A, AFFIX_B, AFFIX_C, AFFIX_D), permitted_properties=("posture",),
        property_vocabulary={"posture": ("vanguard", "warden")}, affix_vocab=VOCAB,
    )
    base.update(overrides)
    return run.NodeGenerationInputs(**base)


def _response(affix_ids=("atom.a",), name="Test Node", exclusion=None) -> dict:
    return {
        "affixIds": list(affix_ids), "affinity": ["core"] * len(affix_ids),
        "exclusion": exclusion or {"form": "none", "propertyKeys": []},
        "name": name, "nameKey": "tree.node.test-node", "flavor": "A steady line.",
        "rationale": "", "blocked": "",
    }


def _subject(node_id: str = "skill.might-off-t1-n0") -> run.Subject:
    return run.Subject(subject_id=f"t1:{node_id}", tree_id="t1", node_id=node_id, node_key="n0",
                      branch="offensive", tier=1, node_class="mechanism")


class OfflineTransportStubTests(unittest.TestCase):
    def test_the_stub_raises_on_any_call(self) -> None:
        with self.assertRaises(run.UnexpectedTransportCall):
            run.offline_transport_stub("system", "user", {})

    def test_the_stub_raises_even_with_no_schema(self) -> None:
        with self.assertRaises(run.UnexpectedTransportCall):
            run.offline_transport_stub("system", "user")


class RunPreflightDelegationTests(unittest.TestCase):
    """§7 gate 6 delegates VERBATIM to `actions.validate_heal.preflight.run_preflight` — no
    tree-specific probe schema of its own (constrained decoding is a property of the SERVER, not
    of this module's response shape)."""

    def test_skip_true_never_touches_the_transport(self) -> None:
        result = run.run_preflight(skip=True, transport=run.offline_transport_stub)
        self.assertEqual(result.status, "skipped")
        self.assertFalse(result.blocks_run)

    def test_a_raising_transport_with_skip_false_is_reported_failed_not_propagated(self) -> None:
        """`actions.validate_heal.preflight.run_preflight`'s own contract: any exception from the
        transport becomes a `status="failed"` result, never an uncaught raise — this module reuses
        that behaviour rather than reimplementing its own."""
        result = run.run_preflight(skip=False, transport=run.offline_transport_stub)
        self.assertEqual(result.status, "failed")
        self.assertTrue(result.blocks_run)


class AuditNodeSchemaDescriptionsTests(unittest.TestCase):
    def test_the_real_shipped_schema_passes_with_no_call(self) -> None:
        with patch("seedsmith.pipeline.llm_caller.call_model", raising_call):
            defects = run.audit_node_schema_descriptions()
        self.assertEqual(defects, [])


class BriefConformanceDefectsTests(unittest.TestCase):
    def test_an_affix_tagged_with_an_anti_motif_is_a_defect(self) -> None:
        defects = run.brief_conformance_defects(
            _response(affix_ids=["atom.c"]), permitted_affix_ids=["atom.a", "atom.b", "atom.c"],
            anti_motif_tags=["anti"], affix_vocab=VOCAB)
        self.assertIn("affixIds", defects)

    def test_a_clean_affix_pick_has_no_defect(self) -> None:
        defects = run.brief_conformance_defects(
            _response(affix_ids=["atom.a"]), permitted_affix_ids=["atom.a", "atom.b", "atom.c"],
            anti_motif_tags=["anti"], affix_vocab=VOCAB)
        self.assertEqual(defects, {})

    def test_an_affix_outside_the_permitted_set_is_never_double_reported_here(self) -> None:
        """Already a gate-7 (`run_g1`) enum violation — this function's own job is narrower."""
        defects = run.brief_conformance_defects(
            _response(affix_ids=["atom.zzz"]), permitted_affix_ids=["atom.a", "atom.b"],
            anti_motif_tags=["anti"], affix_vocab=VOCAB)
        self.assertEqual(defects, {})


class BuildResponseGateTests(unittest.TestCase):
    def setUp(self) -> None:
        from seedsmith.adapters.trees.nodegen.schema import schema_for_call
        self.schema = schema_for_call(["atom.a", "atom.b", "atom.c"], ["posture"])
        self.gate = run.build_response_gate(
            schema=self.schema, permitted_affix_ids=["atom.a", "atom.b", "atom.c"],
            permitted_property_keys=["posture"], anti_motif_tags=["anti"], affix_vocab=VOCAB,
            property_vocabulary={"posture": ("vanguard", "warden")},
            tree_display_name="Might", motifs=["strength"])

    def test_a_clean_response_passes(self) -> None:
        self.assertEqual(self.gate(_response(affix_ids=["atom.a"])), [])

    def test_a_contract_violation_is_reported(self) -> None:
        bad = _response(affix_ids=["atom.a"])
        del bad["nameKey"]
        self.assertTrue(self.gate(bad))

    def test_an_anti_motif_pick_is_reported(self) -> None:
        self.assertTrue(self.gate(_response(affix_ids=["atom.c"])))

    def test_a_name_that_echoes_the_tree_display_name_is_reported(self) -> None:
        self.assertTrue(self.gate(_response(name="Might")))

    def test_an_illegal_exclusion_property_key_is_reported(self) -> None:
        bad = _response(exclusion={"form": "reroute", "propertyKeys": ["not-a-real-property"]})
        self.assertTrue(self.gate(bad))


class CallOneNodeSampleOfflineGuaranteeTests(unittest.TestCase):
    def test_never_reaches_the_model_when_nothing_calls_it(self) -> None:
        """Assembling a brief/schema/gate makes zero calls by construction — proven by patching
        the real transport with a stub that raises the moment it would be reached."""
        from seedsmith.adapters.trees.nodegen.brief import render_brief
        from seedsmith.adapters.trees.nodegen.schema import schema_for_call

        with patch("seedsmith.pipeline.llm_caller.call_model", raising_call):
            schema = schema_for_call(["atom.a"], ["posture"])
            gate = run.build_response_gate(
                schema=schema, permitted_affix_ids=["atom.a"], permitted_property_keys=["posture"],
                anti_motif_tags=[], affix_vocab=VOCAB, property_vocabulary={"posture": ("vanguard",)},
                tree_display_name="Might", motifs=["strength"])
            self.assertEqual(gate(_response(affix_ids=["atom.a"])), [])
            text = render_brief(
                node_id="skill.might-off-t1-n0", sample_index=0, tree_display_name="Might",
                tree_reading="reading", branch="offensive", tier=1, node_class="mechanism",
                motifs=["strength"], anti_motifs=[], permitted_affixes=[AFFIX_A],
                permitted_properties=["posture"])
            self.assertIn("Might", text)


class GenerateNodeEmptyPermittedTests(unittest.TestCase):
    def test_empty_permitted_affixes_raise_unsatisfiable_naming_branch(self) -> None:
        """P5.1: no resolvable affix for this branch — the blocker is named (branch), never
        papered over with the whole vocabulary. Raises before any model call."""
        from seedsmith.adapters.trees.nodegen.quota import UnsatisfiableCell
        with self.assertRaises(UnsatisfiableCell) as ctx:
            run.generate_node(_subject(), _inputs(permitted_affixes=()), config=TEST_CONFIG)
        self.assertIn("offensive", str(ctx.exception))


class GenerateNodeAcceptedTests(unittest.TestCase):
    def test_a_unanimous_vote_is_accepted(self) -> None:
        payload = json.dumps(_response(affix_ids=["atom.a"]))
        with patch("seedsmith.pipeline.llm_caller.call_model", return_value=payload):
            outcome = run.generate_node(_subject(), _inputs(), config=TEST_CONFIG)
        self.assertEqual(outcome.outcome, "accepted")
        self.assertIsNotNone(outcome.record)
        self.assertEqual(outcome.record.affix_ids, ("atom.a",))

    def test_a_declared_block_on_the_base_call_is_reported_not_escalated(self) -> None:
        blocked = {**_response(), "blocked": "no legal effect fits this brief"}
        with patch("seedsmith.pipeline.llm_caller.call_model", return_value=json.dumps(blocked)):
            outcome = run.generate_node(_subject(), _inputs(), config=TEST_CONFIG)
        self.assertEqual(outcome.outcome, "blocked")

    def test_a_response_that_never_satisfies_the_gate_escalates(self) -> None:
        always_bad = json.dumps({"affixIds": ["atom.zzz"]})  # outside the permitted set, forever
        with patch("seedsmith.pipeline.llm_caller.call_model", return_value=always_bad):
            outcome = run.generate_node(_subject(), _inputs(), config=TEST_CONFIG)
        self.assertEqual(outcome.outcome, "escalated")

    def test_a_nullish_blocked_value_no_longer_bypasses_content_validation(self) -> None:
        """2026-09-06 real-call finding (`fortitude`, 4/40 nodes): a real local model sometimes fills
        `blocked: "false"` ALONGSIDE a fully-drafted, but internally INCONSISTENT, content payload
        (here: `affixIds` has 2 members, `affinity` has 1 — exactly the shape §6.3 forbids). Before
        the fix, `_node_verify_fn` read the raw, un-normalized `"false"` as a genuine decline and
        returned `({}, {})` WITHOUT ever calling `gate()` at all — so `call_with_self_heal` accepted
        the malformed draft on its FIRST attempt and never re-prompted the model to fix it. Real data
        proved this was not merely "eventually caught downstream" (this module's own
        `_resolve_affinity_for_members` safety net DOES still escalate rather than corrupt data
        either way — proven by `test_a_response_that_never_satisfies_the_gate_escalates` and friends)
        — the actual cost was throwing away a fixable draft: a model asked to correct a NAMED defect
        (`build_response_gate`'s own heal-retry message) often can, but never got the chance, because
        `verify_fn` never called `gate()` in the first place. Proven here by scripting a HEAL ROUND
        for every one of the 3 samples (malformed-with-blocked-false, then a clean corrected draft)
        and asserting the corrected content is what actually gets used — this is only possible if the
        fix makes `gate()` run against the malformed draft and trigger the retry `call_model` was
        scripted to expect."""
        def _malformed(suffix: str) -> str:
            return json.dumps({
                "affixIds": ["atom.a", "atom.b"], "affinity": ["core"],  # length mismatch, on purpose
                "exclusion": {"form": "none", "propertyKeys": []},
                "name": f"Bad Draft {suffix}", "nameKey": "tree.node.bad", "flavor": "x",
                "rationale": "", "blocked": "false",
            })

        def _clean(suffix: str) -> str:
            return json.dumps(_response(affix_ids=["atom.a"], name=f"Corrected Draft {suffix}"))

        # One heal round per sample: [malformed, clean] x 3 (base call, vote 1, vote 2).
        responses = [
            _malformed("s0"), _clean("s0"),
            _malformed("s1"), _clean("s1"),
            _malformed("s2"), _clean("s2"),
        ]
        with patch("seedsmith.pipeline.llm_caller.call_model", side_effect=responses):
            outcome = run.generate_node(_subject(), _inputs(), config=TEST_CONFIG)
        self.assertEqual(outcome.outcome, "accepted",
                         f"the model was scripted to self-correct when asked; a bypassed gate() "
                         f"never asks, so this proves the fix actually asks. detail={outcome.detail!r}")
        self.assertEqual(outcome.record.name, "Corrected Draft s0",
                         "the ACCEPTED content must be the corrected draft, never the malformed one "
                         "gate() should have rejected on the first attempt")

    def test_a_1_1_1_vote_is_unresolved(self) -> None:
        """Three distinct single-member picks (none anti-motif-tagged, so every individual call
        passes its own per-call gate) -- no member reaches the 2-of-3 majority threshold."""
        responses = [
            json.dumps(_response(affix_ids=["atom.a"])),
            json.dumps(_response(affix_ids=["atom.b"])),
            json.dumps(_response(affix_ids=["atom.d"])),
        ]
        with patch("seedsmith.pipeline.llm_caller.call_model", side_effect=responses):
            outcome = run.generate_node(_subject(), _inputs(), config=TEST_CONFIG)
        self.assertEqual(outcome.outcome, "unresolved")

    def test_a_voted_composite_wider_than_the_base_call_gets_its_own_resolved_affinity(self) -> None:
        """2026-09-06 real-call finding (`fortitude`, 19/40 nodes, 47.5%): `resolve_set_vote` is a
        per-MEMBER majority (§7 gate 11) — `atom.a` is unanimous (3/3), `atom.b` reaches the 2-of-3
        threshold from samples 1-2 alone, so the vote resolves to the TWO-member set `{a, b}` even
        though the base call (sample 0, whose OTHER fields the final record otherwise uses) only
        ever answered with the ONE-member set `{a}`. Before the fix, the persisted composite blindly
        reused sample 0's own one-entry `affinity` array against the two-member voted `affixIds`,
        which failed gate 13's length check on EVERY tree but `might` (whose own archetype happened
        to rarely produce this shape) — proven not a rare edge case once a second tree's real corpus
        was generated. `_resolve_affinity_for_members` fixes this by deriving `atom.b`'s own affinity
        from the two vote samples that actually proposed it (both `["core"]` here), so the composite
        is internally consistent and the node is correctly `accepted`, never escalated for a defect
        the pipeline itself introduced."""
        responses = [
            json.dumps(_response(affix_ids=["atom.a"])),               # base call, sample 0
            json.dumps(_response(affix_ids=["atom.a", "atom.b"])),      # vote sample 1
            json.dumps(_response(affix_ids=["atom.a", "atom.b"])),      # vote sample 2
        ]
        with patch("seedsmith.pipeline.llm_caller.call_model", side_effect=responses):
            outcome = run.generate_node(_subject(), _inputs(), config=TEST_CONFIG)
        self.assertEqual(outcome.outcome, "accepted")
        self.assertEqual(outcome.record.affix_ids, ("atom.a", "atom.b"))
        self.assertEqual(outcome.record.affinity, ("core", "core"))


class ResolveAffinityForMembersTests(unittest.TestCase):
    """Direct unit coverage of `_resolve_affinity_for_members`'s own per-member vote — the
    generate_node-level test above only exercises the unanimous-agreement path."""

    def test_a_member_only_one_sample_recorded_still_resolves_from_that_one_sample(self) -> None:
        picks = {0: ("a",), 1: ("a", "b"), 2: ("a", "b")}
        affinity = {0: ("core",), 1: ("core", "likely"), 2: ("core", "occasional")}
        result = run._resolve_affinity_for_members(("a", "b"), picks, affinity)
        self.assertEqual(result[0], "core")  # unanimous across all three samples
        # "b" is 1-1 between samples 1 (likely) and 2 (occasional) -- ties break to the lowest
        # sample_index, matching sample 0 already being this module's own tie-break convention.
        self.assertEqual(result[1], "likely")

    def test_a_2_of_3_affinity_majority_wins_over_the_lone_dissenter(self) -> None:
        picks = {0: ("a",), 1: ("a",), 2: ("a",)}
        affinity = {0: ("core",), 1: ("likely",), 2: ("likely",)}
        result = run._resolve_affinity_for_members(("a",), picks, affinity)
        self.assertEqual(result, ["likely"])

    def test_a_member_no_sample_ever_recorded_an_affinity_for_returns_none(self) -> None:
        # Defensive case: "c" is in the requested members but no sample's own (affixIds, affinity)
        # pair ever names it -- should not happen once resolve_set_vote's 2-of-3 threshold holds,
        # but the caller must escalate rather than crash if it ever does.
        picks = {0: ("a",), 1: ("a",), 2: ("a",)}
        affinity = {0: ("core",), 1: ("core",), 2: ("core",)}
        result = run._resolve_affinity_for_members(("a", "c"), picks, affinity)
        self.assertIsNone(result)


class RecordAcceptedIdempotenceTests(unittest.TestCase):
    def test_a_second_record_for_the_same_subject_raises(self) -> None:
        record = run.build_node_record("skill.t1-off-t1-n0", "n0", "offensive", 1, "mechanism",
                                       _response())
        done = run.record_accepted({}, "t1:skill.t1-off-t1-n0", record)
        with self.assertRaises(ValueError):
            run.record_accepted(done, "t1:skill.t1-off-t1-n0", record)

    def test_recording_never_mutates_the_callers_dict(self) -> None:
        record = run.build_node_record("skill.t1-off-t1-n0", "n0", "offensive", 1, "mechanism",
                                       _response())
        original: "dict" = {}
        run.record_accepted(original, "t1:skill.t1-off-t1-n0", record)
        self.assertEqual(original, {})


class RecordSupersededTests(unittest.TestCase):
    """Task J4 (spec-tree-review.md §8) — the deliberate, explicit counterpart to
    `record_accepted`'s "raise on duplicate" default, for an intentional incremental re-review pass.
    """

    def test_superseding_a_fresh_subject_with_no_prior_entry_carries_no_supersededRecord(self) -> None:
        record = run.build_node_record("skill.t1-off-t1-n0", "n0", "offensive", 1, "mechanism",
                                       _response())
        done = run.record_superseded({}, "t1:skill.t1-off-t1-n0", record)
        entry = done["t1:skill.t1-off-t1-n0"]
        self.assertNotIn("supersededRecord", entry)
        self.assertEqual(entry["record"]["id"], "skill.t1-off-t1-n0")

    def test_superseding_an_existing_subject_never_raises_unlike_record_accepted(self) -> None:
        first = run.build_node_record("skill.t1-off-t1-n0", "n0", "offensive", 1, "mechanism",
                                      _response(name="Old Name"))
        done = run.record_accepted({}, "t1:skill.t1-off-t1-n0", first)

        second = run.build_node_record("skill.t1-off-t1-n0", "n0", "offensive", 1, "mechanism",
                                       _response(name="New Name"))
        # record_accepted would raise here (proven above) -- record_superseded must not.
        done = run.record_superseded(done, "t1:skill.t1-off-t1-n0", second)
        self.assertEqual(done["t1:skill.t1-off-t1-n0"]["record"]["name"], "New Name")

    def test_the_prior_record_is_preserved_under_supersededRecord_never_discarded(self) -> None:
        first = run.build_node_record("skill.t1-off-t1-n0", "n0", "offensive", 1, "mechanism",
                                      _response(name="Old Name"))
        done = run.record_accepted({}, "t1:skill.t1-off-t1-n0", first)

        second = run.build_node_record("skill.t1-off-t1-n0", "n0", "offensive", 1, "mechanism",
                                       _response(name="New Name"))
        done = run.record_superseded(done, "t1:skill.t1-off-t1-n0", second)

        entry = done["t1:skill.t1-off-t1-n0"]
        self.assertEqual(entry["record"]["name"], "New Name")
        self.assertEqual(entry["supersededRecord"]["name"], "Old Name")

    def test_superseding_never_mutates_the_callers_dict(self) -> None:
        record = run.build_node_record("skill.t1-off-t1-n0", "n0", "offensive", 1, "mechanism",
                                       _response())
        original: "dict" = {}
        run.record_superseded(original, "t1:skill.t1-off-t1-n0", record)
        self.assertEqual(original, {})

    def test_a_second_supersede_chains_only_the_immediately_prior_record_not_the_whole_history(self) -> None:
        # A design choice stated as a test: supersededRecord holds the ONE prior version, not a
        # growing chain -- a full history is the diff card's own job (reading committed catalog
        # revisions over time), never this ledger's.
        v1 = run.build_node_record("skill.t1-off-t1-n0", "n0", "offensive", 1, "mechanism",
                                   _response(name="V1"))
        done = run.record_accepted({}, "t1:skill.t1-off-t1-n0", v1)
        v2 = run.build_node_record("skill.t1-off-t1-n0", "n0", "offensive", 1, "mechanism",
                                   _response(name="V2"))
        done = run.record_superseded(done, "t1:skill.t1-off-t1-n0", v2)
        v3 = run.build_node_record("skill.t1-off-t1-n0", "n0", "offensive", 1, "mechanism",
                                   _response(name="V3"))
        done = run.record_superseded(done, "t1:skill.t1-off-t1-n0", v3)

        entry = done["t1:skill.t1-off-t1-n0"]
        self.assertEqual(entry["record"]["name"], "V3")
        self.assertEqual(entry["supersededRecord"]["name"], "V2")


if __name__ == "__main__":
    unittest.main()
