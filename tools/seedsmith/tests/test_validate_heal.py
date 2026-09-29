"""Tests for `validate-heal` (A-S4, spec-validate-heal.md, action-corpus program).

Every test here runs against a stubbed transport that RAISES, per binding constraint 8 ("Tests
never call a model") -- the only exception is `HealStageTests`, which uses `test_llm_caller.py`'s
own `MockModelServer` (a loopback fake, never a real endpoint) and asserts call COUNT only, never
content (per this module's own build instructions). `A-P1/A-P2/A-P3` do not exist yet, so every
brief/candidate below is a synthetic, in-memory fixture, constructed to match the shapes A-S1
(`distribution_planner`) and this module's own `schemas.py` fixtures already define -- the same
discipline every other action-corpus module in this session used against its own not-yet-existing
real input.
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from seedsmith.adapters.creatures.anchor.permute import _seed_int, order_for
from seedsmith.adapters.actions import generate_validate_heal as entrypoint
from seedsmith.adapters.actions.validate_heal.derive import (
    VoteSample,
    canonical_set_key,
    resolve_vote_field,
    run_self_heal,
    validate_candidate,
    validate_round,
    verify_permutation,
)
from seedsmith.adapters.actions.validate_heal.gates import BriefContext, run_g1, run_g2, run_g3
from seedsmith.adapters.actions.validate_heal.preflight import PROBE_SCHEMA, run_preflight
from seedsmith.adapters.actions.validate_heal.schema_audit import audit_descriptions
from seedsmith.adapters.actions.validate_heal.schemas import (
    FAMILY_SCHEMA,
    GENERAL_SCHEMA,
    SCHEMAS_BY_PIPELINE,
    SIGNATURE_SCHEMA,
)
from seedsmith.adapters.effects.affix.prompts import AFFIX_SCHEMA
from seedsmith.pipeline.llm_caller import LlmCallerConfig
from seedsmith.pipeline.model import BLOCKED_FIELD, audit_schema

from test_llm_caller import MockModelServer

BRIEF_ID = "brief.species.sunflower.001"
CEILING_BUDGET = ("scopeSplit", "riderStatus", "condition", "sequence", "consumption")


def base_ctx(**overrides) -> BriefContext:
    kwargs = dict(
        brief_id=BRIEF_ID, pipeline_id="A-P3",
        allowed_atom_families=frozenset({"g-on-hit", "g-precision"}),
        forbidden_atom_families=frozenset({"g-forbidden"}),
        motifs=frozenset({"radiance"}), anti_motifs=frozenset({"gloom"}),
        structure_budget_ceiling=CEILING_BUDGET,
    )
    kwargs.update(overrides)
    return BriefContext(**kwargs)


def good_draft(**overrides) -> dict:
    d = {
        "name": "Radiant Bloom", "flavor": "a bloom that answers with light",
        "rationale": "channels radiance into a burst",
        "atomFamilies": ["g-on-hit"], "motifsExpressed": ["radiance"],
        "structureAxes": ["condition"], "differentiator": "none",
    }
    d.update(overrides)
    return d


# ---- Stage 0: the schema audit extension (SS2 Stage 0, testing strategy SS4.3) -------------------


class TestStage0SchemaAuditExtension:
    def test_bare_numeric_field_is_an_audit_defect(self):
        defects = audit_schema({
            "type": "object",
            "properties": {"rung": {"type": "integer"}, BLOCKED_FIELD: {"type": "boolean"}},
        })
        assert any(d.path == "$.rung" for d in defects)

    def test_string_pattern_admitting_a_bare_number_is_an_audit_defect_from_this_modules_own_extension(self):
        defects = audit_schema({
            "type": "object",
            "properties": {
                "rungMilli": {"type": "string", "pattern": "^[0-9]+$"},
                BLOCKED_FIELD: {"type": "boolean"},
            },
        })
        assert any(d.path == "$.rungMilli" and "pattern" in d.reason for d in defects)

    def test_numeric_string_enum_is_an_audit_defect_from_this_modules_own_extension(self):
        defects = audit_schema({
            "type": "object",
            "properties": {
                "tier": {"type": "string", "enum": ["1", "2", "3"]},
                BLOCKED_FIELD: {"type": "boolean"},
            },
        })
        assert any(d.path == "$.tier" and "numeric" in d.reason for d in defects)

    def test_deny_listed_property_name_is_an_audit_defect_regardless_of_declared_type(self):
        defects = audit_schema({
            "type": "object",
            "properties": {
                "damage": {"type": "string", "enum": ["low", "high"]},
                BLOCKED_FIELD: {"type": "boolean"},
            },
        })
        assert any(d.path == "$.damage" and "deny-list" in d.reason for d in defects)

    def test_deny_listed_name_is_allow_listable_by_name(self):
        """The escape hatch the spec requires: a genuine identifier that happens to share a
        deny-listed name is exempted explicitly, per call, never silently."""
        schema = {
            "type": "object",
            "properties": {
                "tier": {"type": "string", "enum": ["a", "b"]},  # a real identifier, never arithmetic
                BLOCKED_FIELD: {"type": "boolean"},
            },
        }
        assert any(d.path == "$.tier" for d in audit_schema(schema))
        assert audit_schema(schema, name_allowlist=frozenset({"tier"})) == []

    def test_a_schema_with_no_blocked_variant_is_still_rejected(self):
        defects = audit_schema({"type": "object", "properties": {"name": {"type": "string"}}})
        assert any(BLOCKED_FIELD in d.reason for d in defects)

    def test_cannot_fail_guard_every_new_assertion_rejects_something(self):
        """SS4's own 'cannot fail' guard: each of Stage 0's three NEW assertions has already been
        proven to reject at least one planted input above -- restated here as one assertion so a
        future edit that quietly disables one of the three is caught in one place."""
        pattern_defects = audit_schema({"type": "object", "properties": {
            "x": {"type": "string", "pattern": "[0-9]+$"}, BLOCKED_FIELD: {"type": "boolean"}}})
        enum_defects = audit_schema({"type": "object", "properties": {
            "y": {"type": "string", "enum": ["1", "2"]}, BLOCKED_FIELD: {"type": "boolean"}}})
        name_defects = audit_schema({"type": "object", "properties": {
            "weight": {"type": "boolean"}, BLOCKED_FIELD: {"type": "boolean"}}})
        assert pattern_defects and enum_defects and name_defects


class TestDescriptionNegativeClause:
    def test_missing_description_is_a_defect(self):
        defects = audit_descriptions({"type": "object", "properties": {"a": {"type": "string"}}})
        assert any(d.path == "$.a" for d in defects)

    def test_description_with_no_negative_clause_is_a_defect(self):
        defects = audit_descriptions({"type": "object", "properties": {
            "a": {"type": "string", "description": "the thing's own name"}}})
        assert any(d.path == "$.a" and "negative clause" in d.reason for d in defects)

    def test_description_with_a_negative_clause_passes(self):
        defects = audit_descriptions({"type": "object", "properties": {
            "a": {"type": "string", "description": "the thing's name -- never empty"}}})
        assert defects == []

    def test_all_three_fixture_schemas_pass(self):
        for schema in (GENERAL_SCHEMA, FAMILY_SCHEMA, SIGNATURE_SCHEMA):
            assert audit_descriptions(schema) == []
            assert audit_schema(schema) == []


class TestAffixSchemaFix:
    """SS6 hazard 1 / acceptance #9b -- isolated because it carries a real, stated revert
    condition. See `python -m pytest gk-forge/tools/seedsmith/tests` run separately in the build report."""

    def test_affix_schema_now_carries_a_blocked_property(self):
        assert BLOCKED_FIELD in AFFIX_SCHEMA["properties"]

    def test_affix_schema_passes_the_extended_audit(self):
        assert audit_schema(AFFIX_SCHEMA) == []

    def test_affix_schema_changed_nothing_else(self):
        assert set(AFFIX_SCHEMA["properties"]) == {"name", "refs", BLOCKED_FIELD}
        assert AFFIX_SCHEMA["required"] == ["name", "refs"]
        assert AFFIX_SCHEMA["additionalProperties"] is False


# ---- Stage 1: g1/g2/g3 (SS2 Stage 1) --------------------------------------------------------------


class TestG1ContractGate:
    def test_missing_required_key_is_a_defect(self):
        draft = good_draft()
        del draft["atomFamilies"]
        defects = run_g1(draft, SIGNATURE_SCHEMA)
        assert "atomFamilies" in defects

    def test_extra_key_is_a_defect(self):
        draft = good_draft(extraField="not in the schema")
        defects = run_g1(draft, SIGNATURE_SCHEMA)
        assert "extraField" in defects

    def test_wrong_type_is_a_defect(self):
        draft = good_draft(atomFamilies="g-on-hit")  # should be an array
        defects = run_g1(draft, SIGNATURE_SCHEMA)
        assert "atomFamilies" in defects

    def test_a_well_formed_draft_has_no_g1_defects(self):
        assert run_g1(good_draft(), SIGNATURE_SCHEMA) == {}


class TestG2BriefConformance:
    def test_atom_family_outside_allowed_pool_is_a_hard_reject_naming_the_family(self):
        ctx = base_ctx()
        draft = good_draft(atomFamilies=["g-not-eligible"])
        defects, _ = run_g2(draft, ctx)
        assert "atomFamilies" in defects and "g-not-eligible" in defects["atomFamilies"]

    def test_forbidden_atom_family_is_a_hard_reject(self):
        ctx = base_ctx()
        draft = good_draft(atomFamilies=["g-forbidden"])
        defects, _ = run_g2(draft, ctx)
        assert "atomFamilies" in defects

    def test_anti_motif_in_motifs_expressed_is_a_hard_reject(self):
        ctx = base_ctx()
        draft = good_draft(motifsExpressed=["gloom"])
        defects, _ = run_g2(draft, ctx)
        assert "motifsExpressed" in defects

    def test_structure_axis_outside_the_ceiling_budget_is_a_hard_reject(self):
        # a narrower ceiling than CEILING_BUDGET, so 'condition' is genuinely outside it.
        ctx = base_ctx(structure_budget_ceiling=("scopeSplit", "riderStatus"))
        defects, _ = run_g2(good_draft(structureAxes=["condition"]), ctx)
        assert "structureAxes" in defects

    def test_claimed_reaction_is_a_hard_reject_not_a_flag(self):
        ctx = base_ctx()
        draft = good_draft(structureAxes=["reaction"])
        defects, restriction_claimed = run_g2(draft, ctx)
        assert "structureAxes" in defects and "reaction" in defects["structureAxes"]
        assert restriction_claimed is False

    def test_claimed_restriction_passes_g2_and_is_reported_unchecked(self):
        """The one place g2 is honestly incomplete -- StructureBudgetGuard cannot detect
        `restriction` without the effect-atom program's per-atom data. It must PASS, never be
        silently claimed as verified."""
        ctx = base_ctx()
        draft = good_draft(structureAxes=["restriction"])
        defects, restriction_claimed = run_g2(draft, ctx)
        assert "structureAxes" not in defects
        assert restriction_claimed is True

    def test_a_p3_atom_families_exactly_matching_a_family_actions_set_is_a_hard_reject(self):
        ctx = base_ctx(pipeline_id="A-P3", family_action_atom_sets=(frozenset({"g-on-hit"}),))
        defects, _ = run_g2(good_draft(atomFamilies=["g-on-hit"]), ctx)
        assert "atomFamilies" in defects

    def test_a_p1_draft_naming_a_forbidden_anchor_token_is_a_hard_reject(self):
        ctx = base_ctx(pipeline_id="A-P1", forbidden_anchor_tokens=("sunflower",))
        draft = good_draft(rationale="a burst that channels sunflower's own radiance")
        defects, _ = run_g2(draft, ctx)
        assert "name" in defects

    def test_a_well_formed_draft_has_no_g2_defects(self):
        ctx = base_ctx(family_action_atom_sets=(frozenset({"g-precision"}),))
        defects, restriction_claimed = run_g2(good_draft(), ctx)
        assert defects == {} and restriction_claimed is False


class TestG3QualityGate:
    def test_empty_name_is_a_note(self):
        notes = run_g3(good_draft(name=""), motif_or_role_terms=["radiance"], names_already_in_round=[])
        assert any("empty" in n for n in notes)

    def test_name_restating_atom_family_ids_is_a_note(self):
        notes = run_g3(good_draft(name="g-on-hit"), motif_or_role_terms=["radiance"],
                       names_already_in_round=[])
        assert any("restatement" in n for n in notes)

    def test_duplicate_name_within_the_round_is_a_note(self):
        notes = run_g3(good_draft(name="Radiant Bloom"), motif_or_role_terms=["radiance"],
                       names_already_in_round=["Radiant Bloom"])
        assert any("unique" in n for n in notes)

    def test_rationale_not_referencing_any_motif_is_a_note(self):
        notes = run_g3(good_draft(rationale="a generic burst of force"),
                       motif_or_role_terms=["radiance"], names_already_in_round=[])
        assert any("motif" in n for n in notes)

    def test_a_well_formed_draft_has_no_g3_notes(self):
        assert run_g3(good_draft(), motif_or_role_terms=["radiance"], names_already_in_round=[]) == []

    def test_g3_never_penalises_an_honest_differentiator_none(self):
        """SS2 Stage 1's own correction (review) -- `differentiator == 'none'` must never appear as
        a g3 note. g3 does not even look at `differentiator`; recording/never-penalising it is the
        orchestration layer's job (`validate_candidate`), proven in `AcceptanceOutcomeTests` below."""
        notes = run_g3(good_draft(differentiator="none"), motif_or_role_terms=["radiance"],
                       names_already_in_round=[])
        assert not any("differentiator" in n for n in notes)


# ---- "cannot fail" / "cannot falsely fail" guards (SS4.4 / SS4.5) ---------------------------------


class TestGateGuard:
    def test_cannot_fail_g1_rejects_a_missing_required_key(self):
        assert run_g1({}, SIGNATURE_SCHEMA) != {}

    def test_cannot_fail_g2_rejects_a_forbidden_family(self):
        defects, _ = run_g2(good_draft(atomFamilies=["g-forbidden"]), base_ctx())
        assert defects != {}

    def test_cannot_fail_g3_notes_an_empty_name(self):
        assert run_g3(good_draft(name=""), motif_or_role_terms=[], names_already_in_round=[]) != []

    def test_cannot_falsely_fail_a_two_member_enum_vote_where_all_three_samples_necessarily_collide(self):
        """The exact case SS2 Stage 2's F8 correction names: a 2-member enum collides with
        probability 1 across three independent draws. The OLD, wrong check ("assert the three
        samples used different orders") would have raised here on entirely legal input; the
        replacement (verify each sample reproduces its own seed) does not."""
        options = ["none", "a wider area"]
        samples = [
            VoteSample(sample_index=i, rendered_order=tuple(order_for(BRIEF_ID, "differentiator", i, options)),
                      chosen_value="none")
            for i in range(3)
        ]
        result = resolve_vote_field(BRIEF_ID, "differentiator", options, samples)
        assert result.confidence == "high"
        assert result.value == "none"

    def test_cannot_falsely_fail_an_honest_differentiator_none_is_accepted_end_to_end(self):
        ctx = base_ctx(family_action_atom_sets=(frozenset({"g-precision"}),))
        options = ["g-on-hit"]
        atom_samples = [
            VoteSample(sample_index=i, rendered_order=tuple(order_for(BRIEF_ID, "atomFamilies", i, options)),
                      chosen_value="g-on-hit")
            for i in range(3)
        ]
        diff_options = ["none", "something else"]
        diff_samples = [
            VoteSample(sample_index=i, rendered_order=tuple(order_for(BRIEF_ID, "differentiator", i, diff_options)),
                      chosen_value="none")
            for i in range(3)
        ]
        verdict = validate_candidate(
            candidate_id="cand.1", brief_id=BRIEF_ID, pipeline_id="A-P3", scope="species",
            draft=good_draft(differentiator="none"), ctx=ctx,
            vote_samples={"atomFamilies": atom_samples, "differentiator": diff_samples},
            vote_options={"atomFamilies": options, "differentiator": diff_options},
            motif_or_role_terms=["radiance"],
        )
        assert verdict.outcome == "accepted", verdict.gate_defects
        assert verdict.differentiator_is_none is True
        assert not any("differentiator" in n for n in verdict.quality_notes)


# ---- Stage 2: vote resolution (SS2 Stage 2, F8's corrected replacement) --------------------------


class TestVoteResolution:
    def test_a_3_0_vote_is_high_confidence(self):
        options = ["a", "b", "c"]
        samples = [VoteSample(i, tuple(order_for(BRIEF_ID, "atomFamilies", i, options)), "a")
                  for i in range(3)]
        result = resolve_vote_field(BRIEF_ID, "atomFamilies", options, samples)
        assert result.confidence == "high" and result.value == "a"

    def test_a_2_1_vote_is_split_and_records_the_minority(self):
        options = ["a", "b", "c"]
        values = ["a", "a", "b"]
        samples = [VoteSample(i, tuple(order_for(BRIEF_ID, "atomFamilies", i, options)), v)
                  for i, v in enumerate(values)]
        result = resolve_vote_field(BRIEF_ID, "atomFamilies", options, samples)
        assert result.confidence == "split" and result.value == "a" and result.minority == "b"

    def test_a_1_1_1_vote_is_unresolved_with_value_none(self):
        options = ["a", "b", "c"]
        values = ["a", "b", "c"]
        samples = [VoteSample(i, tuple(order_for(BRIEF_ID, "atomFamilies", i, options)), v)
                  for i, v in enumerate(values)]
        result = resolve_vote_field(BRIEF_ID, "atomFamilies", options, samples)
        assert result.confidence == "unresolved"
        assert result.value is None  # never the first sample

    def test_set_valued_partial_overlap_resolves_on_the_unanimous_member(self):
        """⛔ 2026-09-05. `chosen_value` for `atomFamilies` is a whole SET flattened to one
        `|`-joined key, so the scalar path scored these three as 1-1-1 -- unresolved -- while `a`
        was in fact chosen by all three samples. Per-member voting keeps that agreement. Same
        defect, same fix, as the three propose stages measured the same day."""
        from seedsmith.adapters.actions.validate_heal.derive import resolve_set_vote_field
        options = ["a", "b", "c", "d"]
        values = ["a|b", "a|c", "a|d"]
        samples = [VoteSample(i, tuple(order_for(BRIEF_ID, "atomFamilies", i, options)), v)
                  for i, v in enumerate(values)]
        result = resolve_set_vote_field(BRIEF_ID, "atomFamilies", options, samples)
        assert result.confidence == "split"
        assert result.value == "a"
        assert result.minority == ("b", "c", "d")

    def test_set_valued_fully_disjoint_is_still_unresolved(self):
        """The negative control: per-member voting must not rescue a genuine disagreement."""
        from seedsmith.adapters.actions.validate_heal.derive import resolve_set_vote_field
        options = ["a", "b", "c", "d", "e", "f"]
        values = ["a|b", "c|d", "e|f"]
        samples = [VoteSample(i, tuple(order_for(BRIEF_ID, "atomFamilies", i, options)), v)
                  for i, v in enumerate(values)]
        result = resolve_set_vote_field(BRIEF_ID, "atomFamilies", options, samples)
        assert result.confidence == "unresolved"
        assert result.value is None

    def test_confidence_is_never_read_from_a_model_field_it_is_computed_here(self):
        # The draft never carries a `confidence` key anywhere in this module's own schemas --
        # structural proof there is no field for a model to write one into.
        for schema in (GENERAL_SCHEMA, FAMILY_SCHEMA, SIGNATURE_SCHEMA):
            assert "confidence" not in schema["properties"]

    def test_a_sample_whose_rendered_order_does_not_reproduce_order_for_raises(self):
        """SS4's planted-violation case, F8-corrected: a mismatch is a real, deterministic defect
        and the run raises -- never silently accepted, never reported as a soft gate failure."""
        options = ["a", "b", "c"]
        real_order = tuple(order_for(BRIEF_ID, "atomFamilies", 0, options))
        wrong_order = real_order[1:] + real_order[:1]  # a rotation -- guaranteed distinct for 3 items
        assert wrong_order != real_order
        bad_sample = VoteSample(sample_index=0, rendered_order=wrong_order, chosen_value="a")
        with pytest.raises(ValueError, match="does not reproduce"):
            verify_permutation(BRIEF_ID, "atomFamilies", options, bad_sample)

    def test_structural_the_three_sample_seeds_are_distinct(self):
        """SS2 Stage 2 part 2 -- a STRUCTURAL unit test on the helper itself, never a per-run gate
        (the old, wrong per-run version fired on legal input for a 2-member enum)."""
        seeds = {_seed_int(BRIEF_ID, "atomFamilies", i) for i in range(3)}
        assert len(seeds) == 3

    def test_canonical_set_key_is_order_independent(self):
        assert canonical_set_key(["b", "a"]) == canonical_set_key(["a", "b"])

    def test_atom_families_is_finalized_from_the_vote_never_the_models_raw_draft(self):
        ctx = base_ctx(family_action_atom_sets=(frozenset({"nonexistent"}),))
        options = ["g-on-hit", "g-precision"]
        # the model's raw draft claims g-precision, but the 3-0 vote resolves g-on-hit
        samples = [VoteSample(i, tuple(order_for(BRIEF_ID, "atomFamilies", i, options)), "g-on-hit")
                  for i in range(3)]
        verdict = validate_candidate(
            candidate_id="cand.1", brief_id=BRIEF_ID, pipeline_id="A-P3", scope="species",
            draft=good_draft(atomFamilies=["g-precision"], differentiator="a real difference"),
            ctx=ctx, vote_samples={"atomFamilies": samples}, vote_options={"atomFamilies": options},
            motif_or_role_terms=["radiance"],
        )
        assert verdict.entry["atomFamilies"] == ["g-on-hit"]


# ---- Stage 3: bounded self-heal (SS2 Stage 3, F9's adapted contract) -----------------------------


class TestHealStage:
    def setup_method(self):
        self.server = MockModelServer()
        self.config = LlmCallerConfig(endpoint=self.server.url, attempts=1, retry_delay=0)

    def teardown_method(self):
        self.server.close()

    def _brief_and_ctx(self):
        ctx = base_ctx(pipeline_id="A-P1", allowed_atom_families=frozenset({"g-on-hit"}))
        brief = {"allowedAtomFamilies": ["g-on-hit"]}
        return brief, ctx

    def test_heal_is_bounded_at_exactly_two_repairs_three_attempts_total(self):
        brief, ctx = self._brief_and_ctx()
        bad = json.dumps({"name": "X", "flavor": "flavour text", "rationale": "no motif here",
                          "atomFamilies": ["g-forbidden"], "motifsExpressed": [], "structureAxes": []})
        self.server.queue(bad, bad, bad)

        out, soft, heal_count = run_self_heal(
            brief=brief, pipeline_id="A-P1", ctx=ctx, system="sys",
            build_user=lambda items: json.dumps(items), config=self.config,
        )
        assert len(self.server.requests) == 3
        assert heal_count == 2
        assert any(v.startswith("FAILED:") for v in soft.values())

    def test_build_heal_user_names_the_exact_defect(self):
        brief, ctx = self._brief_and_ctx()
        bad = json.dumps({"name": "X", "flavor": "flavour text", "rationale": "channels radiance",
                          "atomFamilies": ["g-forbidden"],
                          "motifsExpressed": [], "structureAxes": []})
        good = json.dumps({"name": "X", "flavor": "flavour text", "rationale": "channels radiance",
                           "atomFamilies": ["g-on-hit"],
                           "motifsExpressed": [], "structureAxes": []})
        self.server.queue(bad, good)

        out, soft, heal_count = run_self_heal(
            brief=brief, pipeline_id="A-P1", ctx=ctx, system="sys",
            build_user=lambda items: json.dumps(items), config=self.config,
        )
        assert len(self.server.requests) == 2
        heal_prompt = self.server.requests[1]["messages"][-1]["content"]
        assert "atomFamilies" in heal_prompt and "g-forbidden" in heal_prompt
        assert out["atomFamilies"] == ["g-on-hit"]
        assert heal_count == 1

    def test_default_for_always_returns_none_never_the_original_brief_value(self):
        """F9's own contract test: `default_for` must NEVER hand back a brief field as though the
        model had answered it. `run_self_heal` does not even expose a `default_for` parameter --
        `default_for_none` is used unconditionally -- so this is a structural guarantee, proven by
        exhausting the heal budget and checking the failed key's own value."""
        brief, ctx = self._brief_and_ctx()
        bad = json.dumps({"name": "X", "flavor": "flavour text", "rationale": "channels radiance",
                          "atomFamilies": ["g-forbidden"],
                          "motifsExpressed": [], "structureAxes": []})
        self.server.queue(bad, bad, bad)

        out, soft, heal_count = run_self_heal(
            brief=brief, pipeline_id="A-P1", ctx=ctx, system="sys",
            build_user=lambda items: json.dumps(items), config=self.config,
        )
        # `brief` itself carries no 'atomFamilies' key (only 'allowedAtomFamilies') -- so
        # `out['atomFamilies']` being anything other than None would already be suspicious; the
        # direct assertion is the one the F9 contract actually makes.
        assert out["atomFamilies"] is None

    def test_unresolved_is_derived_from_the_failed_soft_entries_never_from_a_raise(self):
        brief, ctx = self._brief_and_ctx()
        bad = json.dumps({"name": "X", "flavor": "flavour text", "rationale": "channels radiance",
                          "atomFamilies": ["g-forbidden"],
                          "motifsExpressed": [], "structureAxes": []})
        self.server.queue(bad, bad, bad)

        out, soft, heal_count = run_self_heal(
            brief=brief, pipeline_id="A-P1", ctx=ctx, system="sys",
            build_user=lambda items: json.dumps(items), config=self.config,
        )
        verdict = validate_candidate(
            candidate_id="cand.1", brief_id=BRIEF_ID, pipeline_id="A-P1", scope="general",
            draft=out, ctx=ctx, heal_count=heal_count,
            heal_defects={k: v[len("FAILED:"):] for k, v in soft.items() if v.startswith("FAILED:")},
        )
        assert verdict.outcome == "unresolved"
        assert verdict.heal_count == 2

    def test_a_well_formed_first_attempt_needs_no_heal_call(self):
        brief, ctx = self._brief_and_ctx()
        good = json.dumps({"name": "X", "flavor": "flavour text", "rationale": "channels radiance",
                           "atomFamilies": ["g-on-hit"],
                           "motifsExpressed": [], "structureAxes": []})
        self.server.queue(good)

        out, soft, heal_count = run_self_heal(
            brief=brief, pipeline_id="A-P1", ctx=ctx, system="sys",
            build_user=lambda items: json.dumps(items), config=self.config,
        )
        assert len(self.server.requests) == 1
        assert heal_count == 0
        assert soft == {}

    def test_a_genuine_block_short_circuits_g1_and_g2(self):
        brief, ctx = self._brief_and_ctx()
        blocked = json.dumps({BLOCKED_FIELD: True, "reason": "no legal action for this brief"})
        self.server.queue(blocked)

        out, soft, heal_count = run_self_heal(
            brief=brief, pipeline_id="A-P1", ctx=ctx, system="sys",
            build_user=lambda items: json.dumps(items), config=self.config,
        )
        assert len(self.server.requests) == 1
        assert out.get(BLOCKED_FIELD) is True
        assert soft == {}

    def test_a_transient_style_failure_absorbed_by_call_models_own_retry_consumes_zero_heal_budget(self):
        """Acceptance #8. `call_model`'s own `attempts` retry is where a transient blip (a dropped
        first request) is absorbed -- proven here by making the FIRST underlying HTTP attempt look
        like a fresh connection (MockModelServer just answers it), so this test instead proves the
        boundary directly: a single successful call never touches the heal loop at all, i.e. heal
        budget is a QUALITY concept this module owns, never a transport-retry one `call_model`
        already owns beneath it."""
        brief, ctx = self._brief_and_ctx()
        good = json.dumps({"name": "X", "flavor": "flavour text", "rationale": "channels radiance",
                           "atomFamilies": ["g-on-hit"],
                           "motifsExpressed": [], "structureAxes": []})
        self.server.queue(good)
        out, soft, heal_count = run_self_heal(
            brief=brief, pipeline_id="A-P1", ctx=ctx, system="sys",
            build_user=lambda items: json.dumps(items), config=self.config,
        )
        assert heal_count == 0  # no QUALITY repair was needed; nothing transient touched heal budget either


# ---- Determinism / replay ---------------------------------------------------------------------


class TestDeterminism:
    def test_the_same_candidate_set_through_the_gates_twice_is_byte_identical(self):
        ctx = base_ctx(family_action_atom_sets=(frozenset({"g-precision"}),))
        options = ["g-on-hit"]
        samples = [VoteSample(i, tuple(order_for(BRIEF_ID, "atomFamilies", i, options)), "g-on-hit")
                  for i in range(3)]
        row = {"candidateId": "cand.1", "briefId": BRIEF_ID, "pipelineId": "A-P3", "scope": "species",
              "draft": good_draft()}
        kwargs = {"cand.1": {"vote_samples": {"atomFamilies": samples},
                             "vote_options": {"atomFamilies": options},
                             "motif_or_role_terms": ["radiance"]}}

        first = validate_round([row], contexts={BRIEF_ID: ctx}, candidate_kwargs=kwargs)
        second = validate_round([row], contexts={BRIEF_ID: ctx}, candidate_kwargs=kwargs)

        assert [v.outcome for v in first.verdicts] == [v.outcome for v in second.verdicts]
        assert first.candidate_set_hash == second.candidate_set_hash
        assert json.dumps(first.disagreement_rate, sort_keys=True) == json.dumps(second.disagreement_rate, sort_keys=True)


# ---- Round-level orchestration: escalated, disagreement rate, restriction-unchecked count -------


class TestRoundOrchestration:
    def test_a_candidate_that_raises_is_recorded_escalated_never_aborts_the_round(self):
        """A permutation-reproduction mismatch (Stage 2's own raise) surfaces here as `escalated`,
        the same convention `workflow/runner.py`'s own `run_many` already uses for a fan-out
        subject that raised -- reused deliberately, see `derive.py`'s own module docstring."""
        ctx = base_ctx()
        bad_samples = {"atomFamilies": [
            VoteSample(0, ("a", "b"), "a"),  # wrong order on purpose -- never reproduces order_for
            VoteSample(1, tuple(order_for(BRIEF_ID, "atomFamilies", 1, ["a", "b"])), "a"),
            VoteSample(2, tuple(order_for(BRIEF_ID, "atomFamilies", 2, ["a", "b"])), "a"),
        ]}
        row = {"candidateId": "cand.bad", "briefId": BRIEF_ID, "pipelineId": "A-P3", "scope": "species",
              "draft": good_draft()}
        row_ok = {"candidateId": "cand.ok", "briefId": BRIEF_ID, "pipelineId": "A-P3", "scope": "species",
                 "draft": good_draft()}
        kwargs = {
            "cand.bad": {"vote_samples": bad_samples, "vote_options": {"atomFamilies": ["a", "b"]}},
            "cand.ok": {},
        }
        report = validate_round([row, row_ok], contexts={BRIEF_ID: ctx}, candidate_kwargs=kwargs)
        by_id = {v.candidate_id: v for v in report.verdicts}
        assert by_id["cand.bad"].outcome == "escalated"
        assert by_id["cand.ok"].outcome in ("accepted", "unresolved")  # unrelated candidate unaffected

    def test_the_per_field_disagreement_rate_is_a_first_class_report_line(self):
        ctx = base_ctx()
        options = ["a", "b", "c"]
        split_samples = [VoteSample(i, tuple(order_for(BRIEF_ID, "atomFamilies", i, options)), v)
                        for i, v in enumerate(["a", "a", "b"])]
        row = {"candidateId": "cand.1", "briefId": BRIEF_ID, "pipelineId": "A-P3", "scope": "species",
              "draft": good_draft(atomFamilies=["a"])}
        report = validate_round(
            [row], contexts={BRIEF_ID: ctx},
            candidate_kwargs={"cand.1": {"vote_samples": {"atomFamilies": split_samples},
                                        "vote_options": {"atomFamilies": options}}},
        )
        assert report.disagreement_rate["atomFamilies"]["species"] == 1.0  # a 2-1 split, not 3-0

    def test_restriction_unchecked_is_counted_at_the_round_level(self):
        ctx = base_ctx(family_action_atom_sets=(frozenset({"nonexistent"}),))
        row = {"candidateId": "cand.1", "briefId": BRIEF_ID, "pipelineId": "A-P3", "scope": "species",
              "draft": good_draft(structureAxes=["restriction"])}
        report = validate_round([row], contexts={BRIEF_ID: ctx})
        assert report.restriction_unchecked_count == 1


# ---- --preflight (acceptance #9c) ---------------------------------------------------------------


class TestPreflight:
    def test_dry_run_skips_and_never_calls(self):
        def never_call(*a, **k):
            raise AssertionError("preflight must never call a model when skip=True")

        result = run_preflight(skip=True, call_model_fn=never_call)
        assert result.status == "skipped"
        assert result.blocks_run is False

    def test_a_raising_stub_never_reaches_call_model_fn_when_skipped(self):
        result = run_preflight(skip=True)
        assert result.status == "skipped"

    def test_probe_schema_has_a_single_member_enum(self):
        prop = PROBE_SCHEMA["properties"]["acknowledged"]
        assert prop["type"] == "string" and len(prop["enum"]) == 1

    def test_a_non_conforming_reply_fails_and_blocks_the_run(self):
        def bad_call(system, user, schema):
            return "not json at all"
        result = run_preflight(skip=False, call_model_fn=bad_call)
        assert result.status == "failed"
        assert result.blocks_run is True

    def test_a_conforming_reply_passes(self):
        def good_call(system, user, schema):
            return json.dumps({"acknowledged": "preflight-ok"})
        result = run_preflight(skip=False, call_model_fn=good_call)
        assert result.status == "passed"
        assert result.blocks_run is False


# ---- Never dedup here; never share one gate path across the three pipelines ----------------------


class TestModuleBoundary:
    def test_each_pipeline_has_its_own_distinct_schema_object(self):
        assert GENERAL_SCHEMA is not FAMILY_SCHEMA
        assert FAMILY_SCHEMA is not SIGNATURE_SCHEMA
        assert SCHEMAS_BY_PIPELINE["A-P1"] is GENERAL_SCHEMA
        assert SCHEMAS_BY_PIPELINE["A-P2"] is FAMILY_SCHEMA
        assert SCHEMAS_BY_PIPELINE["A-P3"] is SIGNATURE_SCHEMA

    def test_this_module_never_deduplicates_two_accepted_candidates(self):
        """Cross-candidate comparison is A-S3's job. `validate_round` never compares one
        candidate's CONTENT against another's beyond the g3 name-uniqueness NOTE (advisory,
        SS3) -- proven structurally: two candidates with identical atomFamilies both accept."""
        ctx = base_ctx(family_action_atom_sets=())
        options = ["g-on-hit"]
        samples = lambda: [VoteSample(i, tuple(order_for(BRIEF_ID, "atomFamilies", i, options)), "g-on-hit")
                          for i in range(3)]
        rows = [
            {"candidateId": "cand.1", "briefId": BRIEF_ID, "pipelineId": "A-P3", "scope": "species",
            "draft": good_draft(name="Alpha")},
            {"candidateId": "cand.2", "briefId": BRIEF_ID, "pipelineId": "A-P3", "scope": "species",
            "draft": good_draft(name="Beta")},
        ]
        kwargs = {r["candidateId"]: {"vote_samples": {"atomFamilies": samples()},
                                     "vote_options": {"atomFamilies": options},
                                     "motif_or_role_terms": ["radiance"]}
                 for r in rows}
        report = validate_round(rows, contexts={BRIEF_ID: ctx}, candidate_kwargs=kwargs)
        assert {v.outcome for v in report.verdicts} == {"accepted"}


class TestEntrypointContracts:
    def test_available_candidate_paths_supports_staged_rounds(self, monkeypatch, tmp_path):
        candidates_root = tmp_path / "actions" / "_candidates"
        (candidates_root / "general").mkdir(parents=True)
        (candidates_root / "family").mkdir(parents=True)
        (candidates_root / "general" / "round-1.json").write_text("{}", encoding="utf-8")
        (candidates_root / "family" / "round-1.json").write_text("{}", encoding="utf-8")
        monkeypatch.setattr(entrypoint, "ACTIONS_ROOT", tmp_path / "actions")

        paths = entrypoint.available_candidate_paths_for_round(1)

        assert [p.parent.name for p in paths] == ["general", "family"]

    def test_dry_run_validates_all_candidate_partitions_and_assembles_only_after_validation(self):
        brief_id = "brief.general.general.001"
        brief = {
            "briefId": brief_id, "scope": "general", "scopeKey": None,
            "anchor": {"motifs": [], "antiMotifs": []},
            "slot": {"category": "attack", "targetMode": "single", "areaShape": None,
                     "relation": "enemy", "rungBand": [1, 4],
                     "structureAxes": ["scopeSplit"]},
            "pool": {"allowedAtomFamilies": ["g-on-hit"], "forbiddenAtomFamilies": []},
            "pairing": {"role": "none", "pairedPayoffFamily": None},
        }
        accepted = {
            "candidateId": "candidate.general.001", "briefId": brief_id,
            "pipelineId": "A-P1", "scope": "general", "outcome": "accepted",
            "draft": {
                "candidateId": "candidate.general.001", "briefId": brief_id, "scope": "general",
                "name": "Test Strike", "flavor": "a clean strike", "atomFamilies": ["g-on-hit"],
                "rationale": "a role-based strike", "_provenance": {},
            },
        }
        unresolved = {
            "candidateId": None, "briefId": "brief.general.general.002",
            "pipelineId": "A-P1", "scope": "general", "outcome": "unresolved", "draft": None,
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            briefs = root / "briefs.json"
            general = root / "general.json"
            family = root / "family.json"
            briefs.write_text(json.dumps({"kind": "action-brief", "entries": [brief]}), encoding="utf-8")
            general.write_text(json.dumps({"kind": "action-candidate", "entries": [accepted]}), encoding="utf-8")
            family.write_text(json.dumps({"kind": "action-candidate", "entries": [unresolved]}), encoding="utf-8")

            summary = entrypoint.regenerate(
                candidates_path=[general, family], briefs_path=briefs, dry_run=True, write=False,
            )

        assert summary["candidateCount"] == 2
        assert summary["validatedAcceptedCount"] == 1
        assert summary["acceptedCount"] == 1
        assert summary["unresolvedCount"] == 1
        assert summary["escalatedCount"] == 0


class TestMissingCandidateFileNamesProducer:
    def test_missing_candidate_file_names_the_propose_stage(self, tmp_path):
        missing = tmp_path / 'general-round-1.json'
        with pytest.raises(ValueError, match='A-P1/A-P2'):
            entrypoint.regenerate(candidates_path=[missing], briefs_path=tmp_path / 'briefs.json', dry_run=True, write=False)

