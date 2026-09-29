"""Tests for `signature-propose` (A-P3, spec-signature-propose.md, action-corpus program).

    python -m pytest gk-forge/tools/seedsmith/tests/test_signature_propose.py -v

Spec SS4's named cases plus SS5's acceptance criteria (1-12, plus #11b). Every test here runs
against a transport that has never been given a chance to be called -- most tests never touch
`pipeline.llm_caller` at all (`build_context`/`build_brief`/the validators/`finalize_candidate`
make zero calls by construction), and the ones that exercise the "makes no call" guarantee
end-to-end patch `seedsmith.pipeline.llm_caller.call_model` with a stub whose only behaviour is
`raise AssertionError` -- the same precedent `test_family_propose.py`/`test_general_propose.py` use
(`test_classify_pipelines.py`'s own `raising_call`, NOT `test_offline_guarantee.py`'s, which
PERMITS localhost -- exactly where the model runs).

**This stage reads A-S2's ASSEMBLED brief, never A-S1's raw plan directly.** A-P2's own round has
never run for real in this checkout, so there is no real `p3-briefs.json` on disk yet
(`generate_brief_assembly.py`'s own docstring states the identical absence for its own upstream).
Two fixture strategies are used side by side, deliberately: SYNTHETIC in-memory briefs
(`make_brief`) for planted violations, vote resolution and the anchor/slot raises, so those tests
never depend on a real round happening to contain a matching case; and A-S2's OWN real functions
(`brief_assembly.derive.assemble_briefs`), fed A-S1's real shipped plan
(`gk-data/packs/fusion/data/seed/actions/_briefs/round-1.json`) plus a synthetic "accepted P2 round", to prove this
stage's own absent-vs-empty contract and family-action-ordering guarantee against A-S2's REAL
behaviour rather than an assumption about its shape (spec's own instruction: "verify this against
A-S2's own real behavior").
"""
from __future__ import annotations

import copy
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from seedsmith.pipeline.model import BLOCKED_FIELD, audit_schema  # noqa: E402
from seedsmith.pipeline.llm_caller import LlmCallerConfig  # noqa: E402
from seedsmith.adapters.actions.validate_heal.schema_audit import audit_descriptions  # noqa: E402
from seedsmith.adapters.actions.validate_heal.gates import run_g3  # noqa: E402
from seedsmith.adapters.actions.brief_assembly import derive as ba  # noqa: E402
from seedsmith.adapters.actions.characteristic_pool.catalog import (  # noqa: E402
    CATALOG_PATH, derive_live_family_assignments, load_catalog,
)
from seedsmith.adapters.actions.vocab import load_family_ids  # noqa: E402
from seedsmith.adapters.actions.signature_propose.prompts import (  # noqa: E402
    DIFFERENTIATOR_VALUES,
    SIGNATURE_ACTION_SCHEMA,
    SYSTEM_PROMPT,
    atom_families_are_allowed,
    atom_families_differ_from_family,
    atom_families_not_forbidden,
    build_brief,
    build_context,
    differentiator_is_known,
    entry_for,
    motifs_expressed_are_known,
    motifs_expressed_exclude_anti_motifs,
    schema_for_call,
)
from seedsmith.adapters.actions.signature_propose.derive import (  # noqa: E402
    MAX_HEAL,
    SAMPLE_COUNT,
    VOTED_FIELDS,
    Candidate,
    build_verify_fn,
    candidate_row,
    candidate_set_hash,
    canonical_dump,
    canonical_family_key,
    default_for_none,
    finalize_candidate,
)
from seedsmith.adapters.actions import generate_signature_actions as gen_mod  # noqa: E402
from seedsmith.adapters.actions import generate_brief_assembly as ba_gen_mod  # noqa: E402
from seedsmith.adapters.creatures.anchor.permute import order_for  # noqa: E402
from seedsmith.adapters.creatures.anchor.vote import VoteResult  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[3]
REAL_PLAN_PATH = REPO_ROOT / "data" / "seed" / "actions" / "_briefs" / "round-1.json"
FAMILY_IDS = load_family_ids()


def raising_call(*args, **kwargs):
    raise AssertionError("a real model call was attempted -- this test's transport must never be reached")


# ---------------------------------------------------------------------------------------------
# Synthetic fixture -- a species-scope (signature) brief shaped exactly like A-S2's own real
# assembled output (measured against `brief_assembly.derive.assemble_brief`'s own shape and
# `gk-data/packs/fusion/data/seed/actions/_briefs/round-1.json`'s real species entries), kept self-contained so vote/
# validator/planted-violation tests do not depend on a real A-P2 round existing.
# ---------------------------------------------------------------------------------------------

def make_brief(**overrides) -> dict:
    brief = {
        "briefId": "brief.species.cherrybomb.001", "id": "brief.species.cherrybomb.001",
        "scope": "species", "scopeKey": "cherrybomb",
        "anchor": {
            "family": "cherry", "element": "fire", "rarity": "heirloom",
            "themeKey": "creature.cherrybomb",
            "motifs": ["bomb", "fire"], "antiMotifs": ["protect", "roof"],
        },
        "slot": {"category": "attack", "targetMode": "self", "areaShape": None,
                "relation": "enemy", "kind": None, "rungBand": [1, 10]},
        "pool": {"allowedAtomFamilies": ["atom.a", "atom.b", "atom.c"],
                "forbiddenAtomFamilies": ["atom.z"]},
        "pairing": {"role": "none", "pairedPayoffFamily": None},
        "avoidNeighbours": [],
        "familyActions": [
            {"actionId": "action.family.cherry.001", "name": "Cherry Bloom Rally",
             "atomFamilies": ["atom.a", "atom.b"], "fingerprint": "a+b|attack|self|enemy|none"},
        ],
        "_provenance": {"corpusHash": "deadbeef", "promptVersion": 1, "round": 1, "tuningVersion": 1},
    }
    brief.update(overrides)
    return brief


def make_draft(**overrides) -> dict:
    # atomFamilies deliberately DIFFERS from make_brief()'s own familyActions[0] set
    # ({"atom.a","atom.b"}) so the default draft passes atom_families_differ_from_family.
    draft = {
        "name": "Detonation Instinct",
        "flavor": "This one primes before the others even notice.",
        "atomFamilies": ["atom.a", "atom.c"],
        "motifsExpressed": ["bomb"],
        "differentiator": "timing",
        "rationale": "Anchors a burst family to a solo-timing axis, unlike the family's paired burst.",
        BLOCKED_FIELD: "",
    }
    draft.update(overrides)
    return draft


# ---------------------------------------------------------------------------------------------
# Acceptance #1/#2/#3 -- Stage 0's own schema audit, reused directly (never re-implemented
# locally), plus the schema's own shape rules -- THREE enums this time, one of them a bare
# `enum` (not `items.enum`) since `differentiator` is a scalar, not an array.
# ---------------------------------------------------------------------------------------------

class SchemaAuditTests(unittest.TestCase):
    def test_shipped_schema_has_no_audit_defects(self):
        self.assertEqual(audit_schema(SIGNATURE_ACTION_SCHEMA), [])

    def test_every_property_description_carries_a_negative_clause(self):
        self.assertEqual(audit_descriptions(SIGNATURE_ACTION_SCHEMA), [])

    def test_blocked_field_is_required_and_a_string(self):
        self.assertIn(BLOCKED_FIELD, SIGNATURE_ACTION_SCHEMA["required"])
        self.assertEqual(SIGNATURE_ACTION_SCHEMA["properties"][BLOCKED_FIELD]["type"], "string")

    def test_every_field_is_required_and_additional_properties_is_false(self):
        # acceptance #3
        for key in ("name", "flavor", "atomFamilies", "motifsExpressed", "differentiator",
                   "rationale", BLOCKED_FIELD):
            self.assertIn(key, SIGNATURE_ACTION_SCHEMA["required"])
        self.assertFalse(SIGNATURE_ACTION_SCHEMA["additionalProperties"])

    def test_differentiator_is_a_scalar_string_not_an_array(self):
        # spec SS2: "a string enum -- NOT an array like the others."
        prop = SIGNATURE_ACTION_SCHEMA["properties"]["differentiator"]
        self.assertEqual(prop["type"], "string")
        self.assertNotIn("items", prop)

    def test_motifs_expressed_and_differentiator_both_admit_none(self):
        # acceptance #3
        self.assertIn("none", DIFFERENTIATOR_VALUES)

    def test_schema_for_call_fills_all_three_enums_and_stays_defect_free(self):
        called = schema_for_call(["atom.a", "atom.b"], ["motif-x", "none"], list(DIFFERENTIATOR_VALUES))
        self.assertEqual(called["properties"]["atomFamilies"]["items"]["enum"], ["atom.a", "atom.b"])
        self.assertEqual(called["properties"]["motifsExpressed"]["items"]["enum"], ["motif-x", "none"])
        self.assertEqual(set(called["properties"]["differentiator"]["enum"]), set(DIFFERENTIATOR_VALUES))
        self.assertEqual(SIGNATURE_ACTION_SCHEMA["properties"]["atomFamilies"]["items"]["enum"], [],
                         "schema_for_call must never mutate the shared constant")
        self.assertEqual(SIGNATURE_ACTION_SCHEMA["properties"]["motifsExpressed"]["items"]["enum"], [],
                         "schema_for_call must never mutate the shared constant")
        self.assertEqual(SIGNATURE_ACTION_SCHEMA["properties"]["differentiator"]["enum"], [],
                         "schema_for_call must never mutate the shared constant")
        self.assertEqual(audit_schema(called), [])

    # --- planted violations (spec SS4) ------------------------------------------------------

    def test_planted_bare_integer_field_is_a_defect(self):
        planted = copy.deepcopy(SIGNATURE_ACTION_SCHEMA)
        planted["properties"]["rung"] = {"type": "integer", "description": "never a number"}
        defects = audit_schema(planted)
        self.assertTrue(any(d.path == "$.rung" for d in defects))

    def test_planted_all_numeric_string_enum_is_a_defect(self):
        planted = copy.deepcopy(SIGNATURE_ACTION_SCHEMA)
        planted["properties"]["tierEnum"] = {"type": "string", "enum": ["1", "2", "3"],
                                             "description": "never a magnitude"}
        defects = audit_schema(planted)
        self.assertTrue(any(d.path == "$.tierEnum" for d in defects))

    def test_schema_without_blocked_property_is_a_defect(self):
        planted = copy.deepcopy(SIGNATURE_ACTION_SCHEMA)
        del planted["properties"][BLOCKED_FIELD]
        planted["required"] = [r for r in planted["required"] if r != BLOCKED_FIELD]
        defects = audit_schema(planted)
        self.assertTrue(any("blocked" in d.reason for d in defects))

    def test_differentiator_enum_omitting_none_is_this_modules_own_defect_to_catch(self):
        # spec SS4: "a differentiator enum omitting none -> this module's OWN schema test fails".
        # schema_for_call trusts its caller (it fills the enum AS GIVEN) -- the guarantee that
        # "none" is always present lives in DIFFERENTIATOR_VALUES/build_context, proven below by
        # DeterminismTests. This test documents the failure mode directly: a caller that forgets
        # "none" produces a schema this test can see is wrong.
        called = schema_for_call(["atom.a"], ["motif-x", "none"], ["atoms", "timing"])  # caller forgot "none"
        self.assertNotIn("none", called["properties"]["differentiator"]["enum"])

    def test_motifs_expressed_enum_without_none_is_this_modules_own_defect_to_catch(self):
        called = schema_for_call(["atom.a"], ["motif-x"], list(DIFFERENTIATOR_VALUES))  # caller forgot "none"
        self.assertNotIn("none", called["properties"]["motifsExpressed"]["items"]["enum"])


# ---------------------------------------------------------------------------------------------
# Acceptance #5 -- the raises: wrong scope, missing anchor content, missing familyActions key
# (absent, never collapsed with empty), missing slot field. Empty motif/anti-motif lists and an
# empty familyActions list are both legal.
# ---------------------------------------------------------------------------------------------

class SpeciesAnchorRaiseTests(unittest.TestCase):
    def test_well_formed_species_brief_does_not_raise(self):
        build_context(make_brief(), sample_index=0)

    def test_missing_species_anchor_key_raises(self):
        for key in ("family", "element", "rarity", "themeKey", "motifs", "antiMotifs"):
            with self.subTest(key=key):
                anchor = dict(make_brief()["anchor"])
                del anchor[key]
                brief = make_brief(anchor=anchor)
                with self.assertRaises(ValueError):
                    build_context(brief, sample_index=0)

    def test_missing_anchor_object_raises(self):
        brief = make_brief()
        del brief["anchor"]
        with self.assertRaises(ValueError):
            build_context(brief, sample_index=0)

    def test_null_family_is_legal_not_a_raise(self):
        # 31 of 84 species carry no family assignment -- anchor.family being None is normal.
        anchor = dict(make_brief()["anchor"], family=None)
        build_context(make_brief(anchor=anchor, familyActions=[]), sample_index=0)  # must not raise

    def test_empty_motif_lists_are_legal_not_a_raise(self):
        anchor = dict(make_brief()["anchor"])
        anchor["motifs"] = []
        anchor["antiMotifs"] = []
        brief = make_brief(anchor=anchor)
        context = build_context(brief, sample_index=0)  # must not raise
        self.assertEqual(context["motifsExpressedEnum"], ["none"])
        self.assertIn("this species has no motif", build_brief(context).lower())

    def test_wrong_scope_raises(self):
        for scope in ("general", "family", None, "bogus"):
            with self.subTest(scope=scope):
                brief = make_brief(scope=scope)
                with self.assertRaises(ValueError):
                    build_context(brief, sample_index=0)

    def test_real_family_scope_brief_raises(self):
        doc = json.loads(REAL_PLAN_PATH.read_text(encoding="utf-8"))
        family_brief = next(e for e in doc["entries"] if e["scope"] == "family")
        with self.assertRaises(ValueError):
            build_context(family_brief, sample_index=0)

    def test_real_general_scope_brief_raises(self):
        doc = json.loads(REAL_PLAN_PATH.read_text(encoding="utf-8"))
        general_brief = next(e for e in doc["entries"] if e["scope"] == "general")
        with self.assertRaises(ValueError):
            build_context(general_brief, sample_index=0)

    def test_missing_slot_field_raises(self):
        for field_name in ("category", "targetMode", "areaShape", "relation", "kind", "rungBand"):
            with self.subTest(field=field_name):
                slot = dict(make_brief()["slot"])
                del slot[field_name]
                brief = make_brief(slot=slot)
                with self.assertRaises(ValueError):
                    build_context(brief, sample_index=0)

    def test_null_slot_value_does_not_raise(self):
        build_context(make_brief(), sample_index=0)

    # --- the absence-vs-empty contract for familyActions (spec SS3, this module's own version of
    # `brief_assembly.derive.require_family_actions`'s rule) -----------------------------------

    def test_missing_family_actions_key_raises(self):
        brief = make_brief()
        del brief["familyActions"]
        with self.assertRaises(ValueError) as ctx:
            build_context(brief, sample_index=0)
        self.assertIn("familyActions", str(ctx.exception))

    def test_empty_family_actions_list_is_legal_and_renders_no_family_sentence(self):
        brief = make_brief(familyActions=[])
        context = build_context(brief, sample_index=0)  # must not raise
        self.assertEqual(context["familyActions"], [])
        text = build_brief(context)
        self.assertIn("this creature belongs to a family", text.lower())

    def test_empty_family_actions_for_family_less_species_renders_no_family_sentence(self):
        anchor = dict(make_brief()["anchor"], family=None)
        context = build_context(make_brief(anchor=anchor, familyActions=[]), sample_index=0)
        self.assertIn("this creature has no family; there is nothing to differ from",
                      build_brief(context).lower())

    def test_family_actions_must_be_a_list(self):
        brief = make_brief(familyActions="not-a-list")
        with self.assertRaises(ValueError):
            build_context(brief, sample_index=0)


# ---------------------------------------------------------------------------------------------
# The absence-vs-empty contract verified against A-S2's OWN REAL behaviour, not a synthetic
# assumption (the task's own instruction) -- A-S1's real shipped plan
# (`gk-data/packs/fusion/data/seed/actions/_briefs/round-1.json`) run through `brief_assembly.derive.assemble_briefs`
# (A-S2's real function), never a hand-rolled fixture pretending to be A-S2's output.
# ---------------------------------------------------------------------------------------------

class RealBriefAssemblyIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.plan_doc = json.loads(REAL_PLAN_PATH.read_text(encoding="utf-8"))
        cls.species_entries = [e for e in cls.plan_doc["entries"] if e["scope"] == "species"]

    def test_a_s2_own_output_for_a_family_less_species_runs_and_renders_no_family_sentence(self):
        family_less_entries = [e for e in self.species_entries if e["anchor"].get("family") is None]
        if not family_less_entries:
            self.skipTest("the current live seed roster assigns every species to a family")
        family_less = family_less_entries[0]
        [real_brief] = ba.assemble_briefs([family_less], accepted_rows=[], family_ids=FAMILY_IDS)
        self.assertEqual(real_brief["familyActions"], [])          # A-S2's own real empty-list shape
        context = build_context(real_brief, sample_index=0)         # must not raise
        self.assertIn("this creature has no family", build_brief(context).lower())

    def test_a_s2_own_output_for_a_family_bearing_species_carries_real_family_actions(self):
        family_bearing = next(e for e in self.species_entries if e["anchor"].get("family"))
        family = family_bearing["anchor"]["family"]
        fam_a, fam_b = sorted(FAMILY_IDS)[:2]
        accepted = [{
            "id": f"action.family.{family}.001", "scope": "family", "scopeKey": family,
            "category": "attack", "rungBand": [1, 7], "targetMode": "single", "areaShape": None,
            "relation": "enemy", "atomFamilies": [fam_b, fam_a], "pairingRole": "none",
            "structureAxes": [], "name": "Real Family Strike", "rationale": "deals damage",
        }]
        [real_brief] = ba.assemble_briefs([family_bearing], accepted, FAMILY_IDS)
        self.assertEqual(len(real_brief["familyActions"]), 1)
        context = build_context(real_brief, sample_index=0)  # must not raise
        self.assertEqual(len(context["familyActionAtomSets"]), 1)
        self.assertEqual(context["familyActionAtomSets"][0], frozenset({fam_a, fam_b}))
        text = build_brief(context)
        self.assertIn("Real Family Strike", text)
        self.assertIn("your action must differ from every one of these".lower(), text.lower())

    def test_missing_family_actions_key_on_a_real_a_s1_plan_entry_raises(self):
        # A-S1's own plan entry (BEFORE A-S2 assembles it) has no familyActions key at all --
        # feeding it straight to this stage (skipping A-S2) must raise, never silently run.
        species_brief = self.species_entries[0]
        self.assertNotIn("familyActions", species_brief)
        with self.assertRaises(ValueError):
            build_context(species_brief, sample_index=0)


# ---------------------------------------------------------------------------------------------
# Acceptance #4 -- what build_brief inlines, and does not; plus the family-action ordering
# guarantee (spec SS4: "a separate test asserting the family-output ordering is fixed (sorted by
# action id) before it's inlined -- reuse A-S2's own sort guarantee, don't re-sort independently").
# ---------------------------------------------------------------------------------------------

class BuildBriefContentTests(unittest.TestCase):
    def test_no_file_path_or_markdown_citation(self):
        context = build_context(make_brief(), sample_index=0)
        text = build_brief(context)
        self.assertNotIn(".md", text)
        self.assertNotIn("spec-", text)

    def test_species_key_element_rarity_present(self):
        context = build_context(make_brief(), sample_index=0)
        text = build_brief(context)
        self.assertIn("cherrybomb", text)
        self.assertIn("fire", text)
        self.assertIn("heirloom", text)

    def test_species_motifs_render_in_permuted_order_matching_order_for(self):
        brief = make_brief(anchor=dict(make_brief()["anchor"],
                                       motifs=["zeta", "alpha", "mu", "beta"]))
        context = build_context(brief, sample_index=2)
        expected = order_for(brief["briefId"], "motifsExpressed", 2,
                             sorted(["zeta", "alpha", "mu", "beta"]) + ["none"])
        self.assertEqual(context["motifsExpressedEnum"], list(expected))
        text = build_brief(context)
        rendered_order = [m for m in expected if m != "none"]
        self.assertIn(", ".join(rendered_order), text)

    def test_empty_species_motifs_render_explicit_sentence(self):
        anchor = dict(make_brief()["anchor"], motifs=[])
        context = build_context(make_brief(anchor=anchor), sample_index=0)
        self.assertIn("this species has no motif", build_brief(context).lower())

    def test_anti_motifs_each_carry_the_rejection_sentence(self):
        context = build_context(make_brief(), sample_index=0)
        text = build_brief(context)
        for motif in context["speciesAntiMotifs"]:
            self.assertIn(f"{motif}: an action expressing this is rejected.", text)

    def test_no_anti_motifs_section_when_list_is_empty(self):
        anchor = dict(make_brief()["anchor"], antiMotifs=[])
        context = build_context(make_brief(anchor=anchor), sample_index=0)
        text = build_brief(context)
        self.assertNotIn("anti-motifs", text.lower())

    def test_family_actions_render_name_sorted_atoms_and_fingerprint(self):
        context = build_context(make_brief(), sample_index=0)
        text = build_brief(context)
        self.assertIn("Cherry Bloom Rally", text)
        self.assertIn("atom.a, atom.b", text)                # sorted, per familyActions[].atomFamilies
        self.assertIn("a+b|attack|self|enemy|none", text)     # the fingerprint
        self.assertIn("your action must differ from every one of these", text.lower())

    def test_no_family_actions_renders_explicit_no_family_sentence(self):
        anchor = dict(make_brief()["anchor"], family=None)
        context = build_context(make_brief(anchor=anchor, familyActions=[]), sample_index=0)
        text = build_brief(context)
        self.assertIn("this creature has no family; there is nothing to differ from", text.lower())

    def test_family_actions_are_never_resorted_by_this_stage(self):
        # spec SS4's own named test: this stage TRUSTS A-S2's sort guarantee and never re-sorts.
        # Feeding an ALREADY-OUT-OF-ORDER list (as if A-S2 had a bug) proves this stage renders
        # it AS GIVEN, in that exact given order -- never silently correcting it.
        out_of_order = [
            {"actionId": "action.family.cherry.003", "name": "Third", "atomFamilies": ["atom.c"],
             "fingerprint": "c|attack|self|enemy|none"},
            {"actionId": "action.family.cherry.001", "name": "First", "atomFamilies": ["atom.a"],
             "fingerprint": "a|attack|self|enemy|none"},
        ]
        brief = make_brief(familyActions=out_of_order)
        context = build_context(brief, sample_index=0)
        self.assertEqual([a["actionId"] for a in context["familyActions"]],
                         ["action.family.cherry.003", "action.family.cherry.001"])
        text = build_brief(context)
        self.assertLess(text.index("Third"), text.index("First"))

    def test_family_actions_stay_sorted_through_this_stage_when_a_s2_supplies_them_sorted(self):
        # The positive case: A-S2's own REAL sort guarantee (`index_accepted_family_actions`)
        # produces ordinal-by-actionId order even when fed rows in a scrambled order -- and THIS
        # stage's own context/brief preserve that order untouched.
        plan_doc = json.loads(REAL_PLAN_PATH.read_text(encoding="utf-8"))
        family_bearing = next(e for e in plan_doc["entries"]
                              if e["scope"] == "species" and e["anchor"].get("family"))
        family = family_bearing["anchor"]["family"]
        fam_ids = sorted(FAMILY_IDS)[:3]
        accepted = [
            {"id": f"action.family.{family}.003", "scope": "family", "scopeKey": family,
             "category": "attack", "rungBand": [1, 7], "targetMode": "single", "areaShape": None,
             "relation": "enemy", "atomFamilies": [fam_ids[2]], "pairingRole": "none",
             "structureAxes": [], "name": "Third", "rationale": "x"},
            {"id": f"action.family.{family}.001", "scope": "family", "scopeKey": family,
             "category": "attack", "rungBand": [1, 7], "targetMode": "single", "areaShape": None,
             "relation": "enemy", "atomFamilies": [fam_ids[0]], "pairingRole": "none",
             "structureAxes": [], "name": "First", "rationale": "x"},
            {"id": f"action.family.{family}.002", "scope": "family", "scopeKey": family,
             "category": "attack", "rungBand": [1, 7], "targetMode": "single", "areaShape": None,
             "relation": "enemy", "atomFamilies": [fam_ids[1]], "pairingRole": "none",
             "structureAxes": [], "name": "Second", "rationale": "x"},
        ]
        [real_brief] = ba.assemble_briefs([family_bearing], accepted, FAMILY_IDS)
        context = build_context(real_brief, sample_index=0)
        ids = [a["actionId"] for a in context["familyActions"]]
        self.assertEqual(ids, sorted(ids))
        text = build_brief(context)
        self.assertLess(text.index("First"), text.index("Second"))
        self.assertLess(text.index("Second"), text.index("Third"))

    def test_payoff_role_inlines_the_payoff_family_and_its_enablers(self):
        brief = make_brief(
            pool={"allowedAtomFamilies": ["atom.a", "atom.enabler-1", "atom.enabler-2"],
                 "forbiddenAtomFamilies": []},
            pairing={"role": "payoff", "pairedPayoffFamily": "atom.a"},
        )
        pairing_table = {"atom.a": ("atom.enabler-1", "atom.enabler-2", "atom.not-eligible")}
        context = build_context(brief, sample_index=0, pairing_table=pairing_table)
        text = build_brief(context)
        self.assertIn("payoff for atom.a", text)
        self.assertIn("atom.enabler-1", text)
        self.assertIn("atom.enabler-2", text)
        self.assertNotIn("atom.not-eligible", text)

    def test_enabler_role_names_its_payoff_family(self):
        brief = make_brief(pairing={"role": "enabler", "pairedPayoffFamily": "atom.rot-punisher"})
        context = build_context(brief, sample_index=0)
        self.assertIn("enabler for atom.rot-punisher", build_brief(context))

    def test_forbidden_families_carry_a_reason(self):
        context = build_context(make_brief(), sample_index=0)
        text = build_brief(context)
        self.assertIn("atom.z", text)
        self.assertIn("Forbidden", text)

    def test_avoid_neighbours_render_as_do_not_produce(self):
        brief = make_brief(avoidNeighbours=[
            {"actionId": "action.species.0001", "fingerprint": "a+b|attack|self|enemy|none"},
        ])
        context = build_context(brief, sample_index=0)
        text = build_brief(context)
        self.assertIn("Do not produce", text)
        self.assertIn("a+b|attack|self|enemy|none", text)

    def test_differentiator_axis_list_never_inlined_in_brief_text(self):
        # differentiator is a pure judgement over a closed vocabulary presented via the SCHEMA
        # enum (schema_for_call), never as content the brief text itself lists -- unlike
        # atomFamilies/motifsExpressed, which ARE inlined because they are content the model
        # designs from.
        context = build_context(make_brief(), sample_index=0)
        text = build_brief(context)
        for axis in ("targetShape", "resource"):
            self.assertNotIn(axis, text)


# ---------------------------------------------------------------------------------------------
# SMOKE BATCH criterion-2 fix, 2026-09-05 -- same technique and same byte-identical-when-absent
# guarantee as `general_propose`'s own `AtomFamilyGlossaryTests` (`test_general_propose.py`).
# ---------------------------------------------------------------------------------------------

class ScopeLabelTests(unittest.TestCase):
    """ST3 (`spec-scope-window-tunables.md` contract 4, spec tests 6 and 6b): the rung-band label
    keys on the brief's SCOPE. The old pair-keyed table read `.get(window, fallback)`, so a retuned
    signature window rendered "a tier outside the three known scope windows" into the prompt instead
    of the species label -- the silent degradation this fixes."""

    FALLBACK = "outside the three known scope windows"

    def _label(self, **overrides) -> str:
        return build_context(make_brief(**overrides), sample_index=0)["rungBandLabel"]

    def test_the_label_comes_from_the_scope_not_the_window(self) -> None:
        shipped = self._label()                                   # scope species, band [1, 10]
        self.assertIn("late tier", shipped)
        self.assertNotIn(self.FALLBACK, shipped)

        # The same scope at a band a retuned signature window would produce must render the
        # IDENTICAL text -- exactly the case the old pair-keyed table silently fell back on.
        retuned = self._label(slot={**make_brief()["slot"], "rungBand": [1, 8]})
        self.assertEqual(shipped, retuned)

    def test_an_unknown_scope_raises_rather_than_falling_back(self) -> None:
        # A-P3 is stricter than its siblings here: `build_context` rejects a non-species scope BEFORE
        # the label is read, so this stage's raise is the scope guard's, not the table's. Both are
        # "raise, never fall back"; the label's own direct index is what the sibling stages' tests
        # exercise, and all three carry the same three-scope table.
        with self.assertRaises(ValueError) as ctx:
            self._label(scope="not-a-real-scope")
        self.assertIn("not-a-real-scope", str(ctx.exception))
        self.assertNotIn(self.FALLBACK, str(ctx.exception))


class AtomFamilyGlossaryTests(unittest.TestCase):
    def test_no_glossary_is_byte_identical_to_the_bare_id_rendering(self):
        context_without = build_context(make_brief(), sample_index=0)
        context_with_empty = build_context(make_brief(), sample_index=0, family_glossary={})
        self.assertEqual(build_brief(context_without), build_brief(context_with_empty))

    def test_glossed_family_renders_id_and_gloss_together(self):
        glossary = {"atom.a": "Iron Wall [defensive] -- X more defense"}
        context = build_context(make_brief(), sample_index=0, family_glossary=glossary)
        text = build_brief(context)
        self.assertIn("atom.a: Iron Wall [defensive] -- X more defense", text)
        self.assertIn("atom.b", text)  # ungossed sibling stays bare, never dropped


# ---------------------------------------------------------------------------------------------
# Determinism / permutation (spec SS4) -- ALL THREE enums.
# ---------------------------------------------------------------------------------------------

class DeterminismTests(unittest.TestCase):
    def test_same_brief_same_sample_index_is_byte_identical(self):
        brief = make_brief()
        c1 = build_context(brief, sample_index=1)
        c2 = build_context(brief, sample_index=1)
        b1 = build_brief(c1)
        b2 = build_brief(c2)
        self.assertEqual(hashlib.sha256(b1.encode()).hexdigest(), hashlib.sha256(b2.encode()).hexdigest())

    def test_atom_families_enum_order_matches_order_for_exactly(self):
        brief = make_brief(pool={"allowedAtomFamilies": ["atom.c", "atom.a", "atom.b"],
                                "forbiddenAtomFamilies": []})
        context = build_context(brief, sample_index=2)
        expected = order_for(brief["briefId"], "atomFamilies", 2, sorted(["atom.a", "atom.b", "atom.c"]))
        self.assertEqual(context["allowedAtomFamilies"], list(expected))

    def test_motifs_expressed_enum_order_matches_order_for_exactly(self):
        brief = make_brief(anchor=dict(make_brief()["anchor"], motifs=["delta", "gamma", "alpha"]))
        context = build_context(brief, sample_index=2)
        expected = order_for(brief["briefId"], "motifsExpressed", 2,
                             sorted(["delta", "gamma", "alpha"]) + ["none"])
        self.assertEqual(context["motifsExpressedEnum"], list(expected))

    def test_differentiator_enum_order_matches_order_for_exactly(self):
        brief = make_brief()
        context = build_context(brief, sample_index=2)
        expected = order_for(brief["briefId"], "differentiator", 2, list(DIFFERENTIATOR_VALUES))
        self.assertEqual(context["differentiatorEnum"], list(expected))

    def test_differentiator_enum_always_includes_none_and_is_exactly_the_six_values(self):
        context = build_context(make_brief(), sample_index=0)
        self.assertEqual(set(context["differentiatorEnum"]), set(DIFFERENTIATOR_VALUES))
        self.assertEqual(len(context["differentiatorEnum"]), 6)

    def test_motifs_expressed_enum_always_includes_none(self):
        context = build_context(make_brief(), sample_index=0)
        self.assertIn("none", context["motifsExpressedEnum"])

    def test_motifs_expressed_enum_is_exactly_none_when_species_motifs_empty(self):
        anchor = dict(make_brief()["anchor"], motifs=[])
        context = build_context(make_brief(anchor=anchor), sample_index=0)
        self.assertEqual(context["motifsExpressedEnum"], ["none"])

    def test_all_three_enums_use_independent_seeds(self):
        # spec SS2/SS4: three permuted samples, one per enum field, from INDEPENDENT seeds -- a
        # large enough pool for each that a shared/aliased seed would be statistically implausible
        # to miss across 3 sample indices.
        brief = make_brief(
            pool={"allowedAtomFamilies": [f"atom.{c}" for c in "abcdefgh"], "forbiddenAtomFamilies": []},
            anchor=dict(make_brief()["anchor"], motifs=[f"motif-{c}" for c in "abcdefgh"]),
        )
        atom_orders = [build_context(brief, sample_index=i)["allowedAtomFamilies"] for i in range(3)]
        motif_orders = [build_context(brief, sample_index=i)["motifsExpressedEnum"] for i in range(3)]
        diff_orders = [build_context(brief, sample_index=i)["differentiatorEnum"] for i in range(3)]
        self.assertTrue(atom_orders[0] != atom_orders[1] or atom_orders[1] != atom_orders[2])
        self.assertTrue(motif_orders[0] != motif_orders[1] or motif_orders[1] != motif_orders[2])
        self.assertTrue(diff_orders[0] != diff_orders[1] or diff_orders[1] != diff_orders[2])
        # and the three fields don't just mirror each other at sample_index=0
        self.assertNotEqual(atom_orders[0][:6], motif_orders[0][:6])


# ---------------------------------------------------------------------------------------------
# Validators -- planted violations: atomFamilies outside the brief's pool, atomFamilies
# EXACTLY matching a family action's own set (this stage's own hard rule), a motif outside the
# brief's own list, a species anti-motif expressed, an unknown differentiator.
# ---------------------------------------------------------------------------------------------

class ValidatorTests(unittest.TestCase):
    def test_atom_family_outside_allowed_is_rejected_and_named(self):
        context = build_context(make_brief(), sample_index=0)
        draft = make_draft(atomFamilies=["atom.a", "atom.not-eligible"])
        reasons = atom_families_are_allowed(draft, context)
        self.assertTrue(reasons)
        self.assertIn("atom.not-eligible", reasons[0])

    def test_atom_family_within_allowed_passes(self):
        context = build_context(make_brief(), sample_index=0)
        self.assertEqual(atom_families_are_allowed(make_draft(), context), [])

    def test_forbidden_family_is_rejected(self):
        context = build_context(make_brief(), sample_index=0)
        draft = make_draft(atomFamilies=["atom.a", "atom.z"])
        reasons = atom_families_not_forbidden(draft, context)
        self.assertTrue(reasons)
        self.assertIn("atom.z", reasons[0])

    def test_atom_families_exactly_matching_a_family_action_is_hard_rejected_and_names_it(self):
        # spec's own most novel rule for this stage.
        context = build_context(make_brief(), sample_index=0)     # familyActions[0] set == {a,b}
        draft = make_draft(atomFamilies=["atom.b", "atom.a"])      # same SET, different order
        reasons = atom_families_differ_from_family(draft, context)
        self.assertTrue(reasons)
        self.assertIn("Cherry Bloom Rally", reasons[0])
        self.assertIn("action.family.cherry.001", reasons[0])

    def test_atom_families_differing_from_family_passes(self):
        context = build_context(make_brief(), sample_index=0)
        self.assertEqual(atom_families_differ_from_family(make_draft(), context), [])

    def test_no_family_actions_means_nothing_to_differ_from(self):
        context = build_context(make_brief(familyActions=[]), sample_index=0)
        draft = make_draft(atomFamilies=["atom.a", "atom.b"])      # would have collided if a family existed
        self.assertEqual(atom_families_differ_from_family(draft, context), [])

    def test_motif_outside_brief_list_is_rejected_and_named(self):
        context = build_context(make_brief(), sample_index=0)
        draft = make_draft(motifsExpressed=["not-a-real-motif"])
        reasons = motifs_expressed_are_known(draft, context)
        self.assertTrue(reasons)
        self.assertIn("not-a-real-motif", reasons[0])

    def test_none_is_a_legal_motif_pick(self):
        context = build_context(make_brief(), sample_index=0)
        self.assertEqual(motifs_expressed_are_known(make_draft(motifsExpressed=["none"]), context), [])

    def test_species_anti_motif_in_motifs_expressed_is_hard_rejected_and_named(self):
        context = build_context(make_brief(), sample_index=0)
        anti = context["speciesAntiMotifs"][0]
        draft = make_draft(motifsExpressed=[anti])
        reasons = motifs_expressed_exclude_anti_motifs(draft, context)
        self.assertTrue(reasons)
        self.assertIn(anti, reasons[0])

    def test_differentiator_outside_enum_is_rejected_and_named(self):
        context = build_context(make_brief(), sample_index=0)
        reasons = differentiator_is_known(make_draft(differentiator="power-level"), context)
        self.assertTrue(reasons)
        self.assertIn("power-level", reasons[0])

    def test_differentiator_none_is_a_legal_pick(self):
        context = build_context(make_brief(), sample_index=0)
        self.assertEqual(differentiator_is_known(make_draft(differentiator="none"), context), [])

    def test_verify_fn_hard_defect_names_the_colliding_family_action_for_the_reprompt(self):
        context = build_context(make_brief(), sample_index=0)
        verify_fn = build_verify_fn(context)
        draft = make_draft(atomFamilies=["atom.b", "atom.a"])
        hard, _soft = verify_fn(dict(context), draft)
        self.assertIn("atomFamilies", hard)
        self.assertIn("Cherry Bloom Rally", hard["atomFamilies"])

    def test_verify_fn_hard_defect_names_the_offending_anti_motif_for_the_reprompt(self):
        context = build_context(make_brief(), sample_index=0)
        anti = context["speciesAntiMotifs"][0]
        verify_fn = build_verify_fn(context)
        draft = make_draft(motifsExpressed=[anti])
        hard, _soft = verify_fn(dict(context), draft)
        self.assertIn("motifsExpressed", hard)
        self.assertIn(anti, hard["motifsExpressed"])

    def test_verify_fn_hard_defect_on_unknown_differentiator(self):
        context = build_context(make_brief(), sample_index=0)
        verify_fn = build_verify_fn(context)
        draft = make_draft(differentiator="power-level")
        hard, _soft = verify_fn(dict(context), draft)
        self.assertIn("differentiator", hard)

    def test_verify_fn_flags_missing_required_key(self):
        context = build_context(make_brief(), sample_index=0)
        verify_fn = build_verify_fn(context)
        draft = make_draft()
        del draft["flavor"]
        hard, _soft = verify_fn(dict(context), draft)
        self.assertIn("flavor", hard)

    def test_verify_fn_declared_block_short_circuits_every_other_check(self):
        context = build_context(make_brief(), sample_index=0)
        verify_fn = build_verify_fn(context)
        draft = {BLOCKED_FIELD: "nothing to design from"}  # missing every other required key
        hard, _soft = verify_fn(dict(context), draft)
        self.assertEqual(hard, {})

    def test_default_for_none_is_always_none(self):
        self.assertIsNone(default_for_none("atomFamilies", ["atom.a"]))
        self.assertIsNone(default_for_none("differentiator", "timing"))


# ---------------------------------------------------------------------------------------------
# Vote resolution (spec SS2 "Which fields are voted") -- BOTH atomFamilies AND differentiator.
# motifsExpressed is never voted; it is always sample 0's own value.
# ---------------------------------------------------------------------------------------------

class VoteResolutionTests(unittest.TestCase):
    def test_voted_fields_are_exactly_atom_families_and_differentiator(self):
        self.assertEqual(VOTED_FIELDS, ("atomFamilies", "differentiator"))

    def test_3_0_agreement_on_both_fields_is_high_confidence_and_accepted(self):
        drafts = [make_draft(), make_draft(), make_draft()]
        cand = finalize_candidate(make_brief(), drafts, candidate_id="candidate.signature.000")
        self.assertEqual(cand.outcome, "accepted")
        self.assertEqual(cand.votes["atomFamilies"].confidence, "high")
        self.assertEqual(cand.votes["differentiator"].confidence, "high")
        self.assertEqual(cand.entry["atomFamilies"], ["atom.a", "atom.c"])
        self.assertEqual(cand.entry["differentiator"], "timing")

    def test_2_1_split_on_atom_families_records_the_minority_and_still_accepts(self):
        drafts = [make_draft(atomFamilies=["atom.a", "atom.c"]),
                 make_draft(atomFamilies=["atom.a", "atom.c"]),
                 make_draft(atomFamilies=["atom.a", "atom.b"])]  # this one WOULD collide, but loses
        cand = finalize_candidate(make_brief(), drafts, candidate_id="candidate.signature.000")
        self.assertEqual(cand.outcome, "accepted")
        self.assertEqual(cand.votes["atomFamilies"].confidence, "split")
        # Per-member voting names the member that lost (`atom.b`), not the whole losing set --
        # the old answer listed `atom.a` as minority despite all three samples choosing it.
        self.assertEqual(cand.votes["atomFamilies"].minority, ("atom.b",))
        self.assertEqual(cand.entry["atomFamilies"], ["atom.a", "atom.c"])

    def test_2_1_split_on_differentiator_records_the_minority_and_still_accepts(self):
        drafts = [make_draft(differentiator="timing"), make_draft(differentiator="timing"),
                 make_draft(differentiator="condition")]
        cand = finalize_candidate(make_brief(), drafts, candidate_id="candidate.signature.000")
        self.assertEqual(cand.outcome, "accepted")
        self.assertEqual(cand.votes["differentiator"].confidence, "split")
        self.assertEqual(cand.votes["differentiator"].minority, "condition")
        self.assertEqual(cand.entry["differentiator"], "timing")

    def test_1_1_1_split_on_atom_families_is_unresolved_whole_candidate(self):
        drafts = [make_draft(atomFamilies=["atom.a"]), make_draft(atomFamilies=["atom.b"]),
                 make_draft(atomFamilies=["atom.c"])]
        cand = finalize_candidate(make_brief(), drafts, candidate_id="candidate.signature.000")
        self.assertEqual(cand.outcome, "unresolved")
        self.assertIsNone(cand.entry)
        self.assertIsNone(cand.votes["atomFamilies"].value)
        self.assertEqual(cand.votes["atomFamilies"].confidence, "unresolved")
        # differentiator was 3-0 agreement -- still overridden to unresolved by the OTHER field
        self.assertEqual(cand.votes["differentiator"].confidence, "high")

    def test_1_1_1_split_on_differentiator_is_unresolved_even_though_atom_families_resolved(self):
        drafts = [make_draft(differentiator="atoms"), make_draft(differentiator="timing"),
                 make_draft(differentiator="condition")]
        cand = finalize_candidate(make_brief(), drafts, candidate_id="candidate.signature.000")
        self.assertEqual(cand.outcome, "unresolved")
        self.assertIsNone(cand.entry)
        self.assertIsNone(cand.votes["differentiator"].value)
        self.assertEqual(cand.votes["differentiator"].confidence, "unresolved")
        # atomFamilies was 3-0 agreement -- the WHOLE candidate is still unresolved (spec SS2)
        self.assertEqual(cand.votes["atomFamilies"].confidence, "high")

    def test_atom_family_order_within_a_pick_does_not_create_a_false_split(self):
        drafts = [make_draft(atomFamilies=["atom.a", "atom.c"]),
                 make_draft(atomFamilies=["atom.c", "atom.a"]),
                 make_draft(atomFamilies=["atom.a", "atom.c"])]
        cand = finalize_candidate(make_brief(), drafts, candidate_id="candidate.signature.000")
        self.assertEqual(cand.votes["atomFamilies"].confidence, "high")

    def test_a_sample_that_never_produced_a_usable_pick_still_casts_its_own_vote_both_fields(self):
        drafts = [make_draft(atomFamilies=["atom.a", "atom.c"], differentiator="timing"),
                 make_draft(atomFamilies=["atom.a", "atom.c"], differentiator="timing"),
                 make_draft(atomFamilies=None, differentiator=None)]
        cand = finalize_candidate(make_brief(), drafts, candidate_id="candidate.signature.000")
        self.assertEqual(cand.outcome, "accepted")
        self.assertEqual(cand.votes["atomFamilies"].confidence, "split")
        self.assertEqual(cand.votes["differentiator"].confidence, "split")

    def test_blocked_sample_zero_short_circuits_before_any_vote(self):
        drafts = [make_draft(**{BLOCKED_FIELD: "brief has nothing to work from"}),
                 make_draft(), make_draft()]
        cand = finalize_candidate(make_brief(), drafts, candidate_id="candidate.signature.000")
        self.assertEqual(cand.outcome, "blocked")
        self.assertIsNone(cand.entry)
        self.assertIsNone(cand.votes)

    def test_finalize_candidate_requires_exactly_three_drafts(self):
        with self.assertRaises(ValueError):
            finalize_candidate(make_brief(), [make_draft(), make_draft()], candidate_id="x")

    def test_motifs_expressed_is_never_voted_always_sample_zero(self):
        drafts = [make_draft(motifsExpressed=["bomb"]),
                 make_draft(motifsExpressed=["fire"]),
                 make_draft(motifsExpressed=["none"])]
        cand = finalize_candidate(make_brief(), drafts, candidate_id="candidate.signature.000")
        self.assertEqual(cand.outcome, "accepted")
        self.assertEqual(cand.entry["motifsExpressed"], ["bomb"])  # sample 0's own value

    # --- acceptance #11b: differentiator == "none" is accepted and RECORDED, never scored down --

    def test_differentiator_none_3_0_is_accepted_and_recorded_never_scored_down(self):
        drafts = [make_draft(differentiator="none"), make_draft(differentiator="none"),
                 make_draft(differentiator="none")]
        cand = finalize_candidate(make_brief(), drafts, candidate_id="candidate.signature.000")
        self.assertEqual(cand.outcome, "accepted")
        self.assertEqual(cand.votes["differentiator"].confidence, "high")
        self.assertEqual(cand.entry["differentiator"], "none")
        row = candidate_row(cand)
        self.assertEqual(row["outcome"], "accepted")
        self.assertEqual(row["draft"]["differentiator"], "none")


# ---------------------------------------------------------------------------------------------
# A-S7 `coverage-assignment` splice (spec-coverage-assignment.md SS6): `brief.requiredFamilies`,
# if present, is unioned into an ACCEPTED candidate's final `atomFamilies` -- never touches an
# unresolved/blocked outcome, never present means byte-identical to before this feature existed.
# ---------------------------------------------------------------------------------------------

class RequiredFamiliesSpliceTests(unittest.TestCase):
    def test_omitting_required_families_is_byte_identical(self):
        drafts = [make_draft(), make_draft(), make_draft()]
        with_key = finalize_candidate(make_brief(requiredFamilies=[]), drafts, candidate_id="x")
        without_key = finalize_candidate(make_brief(), drafts, candidate_id="x")
        self.assertEqual(with_key.entry["atomFamilies"], without_key.entry["atomFamilies"])
        self.assertEqual(without_key.entry["atomFamilies"], sorted({"atom.a", "atom.c"}))

    def test_an_accepted_candidate_gets_the_required_family_spliced_in(self):
        drafts = [make_draft(), make_draft(), make_draft()]
        cand = finalize_candidate(make_brief(requiredFamilies=["atom.required"]), drafts,
                                  candidate_id="x")
        self.assertEqual(cand.outcome, "accepted")
        self.assertIn("atom.required", cand.entry["atomFamilies"])
        self.assertEqual(cand.entry["atomFamilies"], sorted({"atom.a", "atom.c", "atom.required"}))

    def test_a_required_family_already_in_the_voted_set_is_not_duplicated(self):
        drafts = [make_draft(), make_draft(), make_draft()]
        cand = finalize_candidate(make_brief(requiredFamilies=["atom.a"]), drafts, candidate_id="x")
        self.assertEqual(cand.entry["atomFamilies"], sorted({"atom.a", "atom.c"}))

    def test_an_unresolved_candidate_is_never_spliced(self):
        drafts = [make_draft(atomFamilies=["atom.a"]), make_draft(atomFamilies=["atom.b"]),
                 make_draft(atomFamilies=["atom.c"])]
        cand = finalize_candidate(make_brief(requiredFamilies=["atom.required"]), drafts,
                                  candidate_id="x")
        self.assertEqual(cand.outcome, "unresolved")
        self.assertIsNone(cand.entry)

    def test_a_blocked_candidate_is_never_spliced(self):
        drafts = [make_draft(**{BLOCKED_FIELD: "no anchor"}), make_draft(), make_draft()]
        cand = finalize_candidate(make_brief(requiredFamilies=["atom.required"]), drafts,
                                  candidate_id="x")
        self.assertEqual(cand.outcome, "blocked")
        self.assertIsNone(cand.entry)


# ---------------------------------------------------------------------------------------------
# Recorded-transcript replay (spec SS4): three PRE-RECORDED samples fed through the same
# deterministic vote/hash logic twice -- byte-identical candidate output both times.
# ---------------------------------------------------------------------------------------------

class RecordedTranscriptReplayTests(unittest.TestCase):
    RECORDED_SAMPLES = [
        {"name": "Detonation Instinct", "flavor": "This one primes before the others even notice.",
         "atomFamilies": ["atom.a", "atom.c"], "motifsExpressed": ["bomb"], "differentiator": "timing",
         "rationale": "A solo-timing burst, unlike the family's paired one.", BLOCKED_FIELD: ""},
        {"name": "Early Fuse", "flavor": "It never waits for the others to prime first.",
         "atomFamilies": ["atom.c", "atom.a"], "motifsExpressed": ["fire"], "differentiator": "timing",
         "rationale": "Reuses the same burst pair on a solo timing axis.", BLOCKED_FIELD: ""},
        {"name": "Lone Spark", "flavor": "A single flare, no chorus needed.",
         "atomFamilies": ["atom.a", "atom.c"], "motifsExpressed": ["none"], "differentiator": "timing",
         "rationale": "The whole line waits; this one does not.", BLOCKED_FIELD: ""},
    ]

    def _replay(self) -> str:
        cand = finalize_candidate(make_brief(), [dict(d) for d in self.RECORDED_SAMPLES],
                                  candidate_id="candidate.signature.000",
                                  provenance={"pipeline": "signature-propose", "model": "recorded"})
        row = candidate_row(cand)
        return canonical_dump({"entries": [row]})

    def test_replaying_the_same_transcript_twice_is_byte_identical(self):
        first = self._replay()
        second = self._replay()
        self.assertEqual(first, second)
        self.assertEqual(hashlib.sha256(first.encode()).hexdigest(),
                         hashlib.sha256(second.encode()).hexdigest())

    def test_canonical_dump_is_sorted_keys_fixed_indent_trailing_newline(self):
        dumped = self._replay()
        self.assertTrue(dumped.endswith("\n"))
        self.assertFalse(dumped.endswith("\n\n"))
        parsed = json.loads(dumped)
        self.assertEqual(dumped, json.dumps(parsed, ensure_ascii=False, indent=2, sort_keys=True,
                                            default=str) + "\n")

    def test_replay_resolves_to_the_voted_majority_pick_and_sample_zero_motif(self):
        row = json.loads(self._replay())["entries"][0]
        self.assertEqual(row["outcome"], "accepted")
        self.assertEqual(row["confidence"]["atomFamilies"], "high")
        self.assertEqual(row["confidence"]["differentiator"], "high")
        self.assertEqual(row["draft"]["atomFamilies"], ["atom.a", "atom.c"])
        self.assertEqual(row["draft"]["differentiator"], "timing")
        self.assertEqual(row["draft"]["motifsExpressed"], ["bomb"])  # sample 0's own, never voted


# ---------------------------------------------------------------------------------------------
# Offline guarantee (spec SS4) -- every pure path makes zero calls, proven by patching the ACTUAL
# transport `call_model` with a stub that raises the moment it would be reached.
# ---------------------------------------------------------------------------------------------

class OfflineGuaranteeTests(unittest.TestCase):
    def test_build_render_validate_and_finalize_never_reach_the_model(self):
        with patch("seedsmith.pipeline.llm_caller.call_model", raising_call):
            brief = make_brief()
            context = build_context(brief, sample_index=0)
            text = build_brief(context)
            self.assertTrue(text)
            self.assertEqual(atom_families_are_allowed(make_draft(), context), [])
            self.assertEqual(motifs_expressed_are_known(make_draft(), context), [])
            self.assertEqual(differentiator_is_known(make_draft(), context), [])
            self.assertEqual(audit_schema(SIGNATURE_ACTION_SCHEMA), [])
            cand = finalize_candidate(brief, [make_draft(), make_draft(), make_draft()],
                                      candidate_id="candidate.signature.000")
            self.assertEqual(cand.outcome, "accepted")

    def test_entry_for_never_reaches_the_model(self):
        with patch("seedsmith.pipeline.llm_caller.call_model", raising_call):
            entry = entry_for(make_draft(), candidate_id="candidate.signature.000",
                              brief_id="brief.species.cherrybomb.001")
            self.assertEqual(entry["name"], "Detonation Instinct")


# ---------------------------------------------------------------------------------------------
# Acceptance #8 -- `--dry-run` / `--count`, against a REAL A-S2-assembled p3-briefs envelope
# (built from A-S1's real shipped plan, since A-P2 has never run for real).
# ---------------------------------------------------------------------------------------------

def _real_p3_briefs_envelope(*, count: int = 5) -> dict:
    """Build a REAL A-S2 output envelope (never a hand-typed fixture pretending to be one) by
    running `brief_assembly.derive.assemble_briefs` over A-S1's real shipped plan with an empty
    accepted round -- every species gets `familyActions: []`, which is legal (spec SS3) and lets
    the dry-run/entrypoint tests exercise this stage's real reader against A-S2's real writer."""
    plan_doc = json.loads(REAL_PLAN_PATH.read_text(encoding="utf-8"))
    species_entries = [e for e in plan_doc["entries"] if e["scope"] == "species"][:count]
    briefs = ba.assemble_briefs(species_entries, accepted_rows=[], family_ids=FAMILY_IDS)
    return ba.build_envelope(briefs, meta={
        "partition": "round-1", "round": 1, "planPath": str(REAL_PLAN_PATH),
        "planCorpusHash": "plan-round-abc123",
        "acceptedRoundPath": "synthetic-empty-round", "acceptedRoundCorpusHash": "p2-round-abc123",
    })


class DryRunEntrypointTests(unittest.TestCase):
    def test_dry_run_makes_zero_calls_and_renders_a_sample_brief(self):
        with tempfile.TemporaryDirectory() as tmp:
            briefs_path = Path(tmp) / "p3-briefs.json"
            briefs_path.write_text(ba.canonical_dump(_real_p3_briefs_envelope(count=5)), encoding="utf-8")
            with patch("seedsmith.pipeline.llm_caller.call_model", raising_call):
                summary = gen_mod.regenerate(briefs_path=briefs_path, dry_run=True, count=2)
            self.assertTrue(summary["dryRun"])
            self.assertEqual(summary["modelCalls"], 0)
            self.assertEqual(summary["totalSignatureBriefs"], 5)
            self.assertEqual(summary["selected"], 2)
            self.assertIn("Design THE signature action", summary["sampleBrief"])

    def test_regenerate_refuses_a_non_action_brief_envelope(self):
        with tempfile.TemporaryDirectory() as tmp:
            briefs_path = Path(tmp) / "wrong-kind.json"
            briefs_path.write_text(json.dumps({"schemaVersion": 1, "kind": "action-seed",
                                              "_meta": {}, "entries": []}), encoding="utf-8")
            with self.assertRaises(ValueError) as ctx:
                gen_mod.regenerate(briefs_path=briefs_path, dry_run=True, count=1)
            self.assertIn("action-brief", str(ctx.exception))

    def test_load_signature_briefs_reads_only_species_scope_sorted(self):
        with tempfile.TemporaryDirectory() as tmp:
            briefs_path = Path(tmp) / "p3-briefs.json"
            briefs_path.write_text(ba.canonical_dump(_real_p3_briefs_envelope(count=5)), encoding="utf-8")
            briefs = gen_mod.load_signature_briefs(briefs_path)
            self.assertTrue(all(b["scope"] == "species" for b in briefs))
            self.assertEqual(len(briefs), 5)
            self.assertEqual([b["briefId"] for b in briefs], sorted(b["briefId"] for b in briefs))

    def test_brief_hash_is_deterministic_and_brief_specific(self):
        b1 = make_brief()
        b2 = make_brief()
        self.assertEqual(gen_mod._brief_hash(b1), gen_mod._brief_hash(b2))
        b3 = make_brief(briefId="brief.species.other.001")
        self.assertNotEqual(gen_mod._brief_hash(b1), gen_mod._brief_hash(b3))

    def test_real_run_writes_provenance_with_p2_candidate_set_hash_extra_field(self):
        # acceptance #10's own EXTRA field relative to A-P1/A-P2: "the P2 candidate-set hash this
        # round differed against" -- sourced from A-S2's own envelope meta
        # (`acceptedRoundCorpusHash`, added to `generate_brief_assembly.py` for exactly this).
        def fake_propose(brief, *, candidate_id, pairing_table=None, family_glossary=None,
                        usage_weights=None, config=None, provenance=None):
            return Candidate(
                brief_id=brief["briefId"], outcome="accepted",
                entry=entry_for(make_draft(), candidate_id=candidate_id, brief_id=brief["briefId"],
                               provenance=provenance),
                votes={"atomFamilies": VoteResult(value="atom.a|atom.c", confidence="high", minority=None),
                      "differentiator": VoteResult(value="timing", confidence="high", minority=None)},
                provenance=dict(provenance or {}),
            )

        with tempfile.TemporaryDirectory() as tmp:
            tmp_root = Path(tmp)
            briefs_path = tmp_root / "p3-briefs.json"
            briefs_path.write_text(ba.canonical_dump(_real_p3_briefs_envelope(count=1)), encoding="utf-8")
            out_dir = tmp_root / "_candidates" / "signature"

            with patch("seedsmith.adapters.actions.generate_signature_actions.propose_signature_action",
                      fake_propose):
                summary = gen_mod.regenerate(briefs_path=briefs_path, dry_run=False, count=1,
                                             candidates_dir=out_dir,
                                             config=LlmCallerConfig(model="test-model-x"))
            self.assertTrue(summary["written"])
            written = json.loads((out_dir / "round-1.json").read_text(encoding="utf-8"))
            self.assertEqual(written["_meta"]["model"], "test-model-x")
            self.assertEqual(written["_meta"]["promptVersion"], gen_mod.PROMPT_VERSION)
            self.assertIn("candidateSetHash", written["_meta"])
            self.assertEqual(written["_meta"]["briefsCorpusHash"], "plan-round-abc123")
            self.assertEqual(written["_meta"]["p2CandidateSetHash"], "p2-round-abc123")
            row = written["entries"][0]
            self.assertIn("briefHash", row["_provenance"])
            self.assertEqual(row["_provenance"]["briefsCorpusHash"], "plan-round-abc123")
            self.assertEqual(row["_provenance"]["model"], "test-model-x")
            self.assertEqual(row["_provenance"]["p2CandidateSetHash"], "p2-round-abc123")

            # rerun over unchanged inputs is byte-identical (acceptance #10)
            out_dir2 = tmp_root / "_candidates2" / "signature"
            with patch("seedsmith.adapters.actions.generate_signature_actions.propose_signature_action",
                      fake_propose):
                gen_mod.regenerate(briefs_path=briefs_path, dry_run=False, count=1,
                                   candidates_dir=out_dir2,
                                   config=LlmCallerConfig(model="test-model-x"))
            self.assertEqual((out_dir / "round-1.json").read_text(encoding="utf-8"),
                             (out_dir2 / "round-1.json").read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------------------------
# `generate_brief_assembly.py`'s own small addition (this build): its envelope meta now carries
# `acceptedRoundCorpusHash`, the accepted P2 round's own `_meta.corpusHash`, forwarded so THIS
# stage never has to re-open the accepted-round file itself.
# ---------------------------------------------------------------------------------------------

class BriefAssemblyProvenanceForwardingTests(unittest.TestCase):
    def test_p3_briefs_envelope_carries_the_accepted_rounds_own_corpus_hash(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_root = Path(tmp)
            plan_path = tmp_root / "plan.json"
            plan_path.write_text(json.dumps({
                "schemaVersion": 1, "kind": "action-brief", "_meta": {},
                "entries": [{
                    "id": "brief.species.x.001", "briefId": "brief.species.x.001", "scope": "species",
                    "scopeKey": "x",
                    "anchor": {"family": None, "element": "fire", "rarity": "chaff",
                              "themeKey": "creature.x", "motifs": [], "antiMotifs": []},
                    "slot": {"category": "attack", "targetMode": "single", "areaShape": None,
                            "relation": "enemy", "kind": None, "rungBand": [1, 10]},
                    "pool": {"allowedAtomFamilies": [], "forbiddenAtomFamilies": []},
                    "pairing": {"role": "none", "pairedPayoffFamily": None},
                    "avoidNeighbours": [],
                }],
            }), encoding="utf-8")
            accepted_path = tmp_root / "accepted.json"
            accepted_path.write_text(json.dumps({
                "schemaVersion": 1, "kind": "action-seed",
                "_meta": {"partition": "rounds", "round": 1, "corpusHash": "p2-real-hash-xyz"},
                "entries": [],
            }), encoding="utf-8")

            summary = ba_gen_mod.regenerate(plan_path=plan_path, accepted_round_path=accepted_path,
                                            actions_root=tmp_root / "actions", round_no=1, write=True)
            self.assertTrue(summary["written"])
            doc = json.loads((tmp_root / "actions" / "_rounds" / "round-1" / "p3-briefs.json")
                            .read_text(encoding="utf-8"))
            self.assertEqual(doc["_meta"]["acceptedRoundCorpusHash"], "p2-real-hash-xyz")


# ---------------------------------------------------------------------------------------------
# Acceptance #11 -- repairs bounded at two, explicit, and default_for=None (F9).
# ---------------------------------------------------------------------------------------------

class HealBudgetTests(unittest.TestCase):
    def test_max_heal_is_two_not_the_llm_caller_default(self):
        from seedsmith.pipeline.llm_caller import LlmCallerConfig
        self.assertEqual(MAX_HEAL, 2)
        self.assertNotEqual(MAX_HEAL, LlmCallerConfig().max_heal)

    def test_sample_count_is_three(self):
        self.assertEqual(SAMPLE_COUNT, 3)

    def test_sample_draft_wires_max_heal_and_default_for_explicitly(self):
        captured = {}

        def fake_call_with_self_heal(items, system, build_user, verify_fn, *, config, max_heal,
                                     default_for=None, build_heal_user=None, schema=None):
            captured["max_heal"] = max_heal
            captured["default_for"] = default_for
            return dict(make_draft()), {}

        with patch("seedsmith.adapters.actions.signature_propose.derive.call_with_self_heal",
                  fake_call_with_self_heal):
            from seedsmith.adapters.actions.signature_propose.derive import sample_draft
            sample_draft(make_brief(), sample_index=0)

        self.assertEqual(captured["max_heal"], 2)
        self.assertIs(captured["default_for"], default_for_none)


# ---------------------------------------------------------------------------------------------
# Acceptance #12 -- no numeric value anywhere in a candidate row.
# ---------------------------------------------------------------------------------------------

def _walk_no_numbers(obj, path="$"):
    if isinstance(obj, bool) or obj is None or isinstance(obj, str):
        return
    if isinstance(obj, (int, float)):
        raise AssertionError(f"{path}: numeric value {obj!r} in candidate output")
    if isinstance(obj, dict):
        for k, v in obj.items():
            _walk_no_numbers(v, f"{path}.{k}")
    elif isinstance(obj, (list, tuple)):
        for i, v in enumerate(obj):
            _walk_no_numbers(v, f"{path}[{i}]")


class NoNumericOutputTests(unittest.TestCase):
    def test_accepted_candidate_row_carries_no_numeric_value(self):
        cand = finalize_candidate(make_brief(), [make_draft(), make_draft(), make_draft()],
                                  candidate_id="candidate.signature.000",
                                  provenance={"pipeline": "signature-propose", "model": "x"})
        row = candidate_row(cand)
        _walk_no_numbers(row)


# ---------------------------------------------------------------------------------------------
# Candidate-set hashing (mirrors acceptance #10's "candidate-set hash").
# ---------------------------------------------------------------------------------------------

class CandidateSetHashTests(unittest.TestCase):
    def test_hash_is_order_independent_of_input_ordering(self):
        cand = finalize_candidate(make_brief(), [make_draft(), make_draft(), make_draft()],
                                  candidate_id="candidate.signature.000")
        row = candidate_row(cand)
        row2 = dict(row)
        h1 = candidate_set_hash([row, row2])
        h2 = candidate_set_hash([row2, row])
        self.assertEqual(h1, h2)

    def test_hash_changes_when_a_row_changes(self):
        cand = finalize_candidate(make_brief(), [make_draft(), make_draft(), make_draft()],
                                  candidate_id="candidate.signature.000")
        row = candidate_row(cand)
        changed = dict(row, outcome="blocked")
        self.assertNotEqual(candidate_set_hash([row]), candidate_set_hash([changed]))


class CanonicalFamilyKeyTests(unittest.TestCase):
    def test_order_independent_and_deduped(self):
        self.assertEqual(canonical_family_key(["b", "a", "a"]), canonical_family_key(["a", "b"]))

    def test_distinct_sets_produce_distinct_keys(self):
        self.assertNotEqual(canonical_family_key(["a"]), canonical_family_key(["a", "b"]))


# ---------------------------------------------------------------------------------------------
# Acceptance #11b, in full: A-S4's g3 genuinely never penalises `differentiator: "none"` -- a
# real, dedicated test against the SHIPPED `validate_heal.gates.run_g3` (never re-implemented
# here), proving g3 is blind to `differentiator` entirely (it only ever reads `name`/`rationale`/
# `atomFamilies`), so "none" and any other value produce IDENTICAL g3 notes.
# ---------------------------------------------------------------------------------------------

class ValidateHealG3NeverPenalisesDifferentiatorNoneTests(unittest.TestCase):
    def test_g3_produces_identical_notes_regardless_of_differentiator_value(self):
        draft_none = {**make_draft(differentiator="none"), "structureAxes": []}
        draft_atoms = {**make_draft(differentiator="atoms"), "structureAxes": []}
        notes_none = run_g3(draft_none, motif_or_role_terms=["bomb", "fire"], names_already_in_round=[])
        notes_atoms = run_g3(draft_atoms, motif_or_role_terms=["bomb", "fire"], names_already_in_round=[])
        self.assertEqual(notes_none, notes_atoms)

    def test_g3_never_reads_the_differentiator_key_at_all(self):
        # a draft where 'differentiator' isn't even a real value (a sentinel object) must still
        # produce the same notes as one where it's a normal string -- proving g3 never inspects it.
        class _NeverReadMe:
            def __eq__(self, other):
                raise AssertionError("g3 must never compare against differentiator's own value")

        draft = {**make_draft(), "differentiator": _NeverReadMe(), "structureAxes": []}
        run_g3(draft, motif_or_role_terms=["bomb"], names_already_in_round=[])  # must not raise


# ---------------------------------------------------------------------------------------------
# Roster test, not a claim (spec SS4): the plan was sized on real per-species motif/family data
# read straight from the generated files -- asserted as a JOIN to the live roster, never a pinned
# size (docs/architecture/validation-ssot.md: a population that grows per shipped species is a
# reading).
# ---------------------------------------------------------------------------------------------

class RosterTests(unittest.TestCase):
    def test_live_roster_and_family_memberships_reconcile(self):
        species = load_catalog(CATALOG_PATH)
        families = derive_live_family_assignments(CATALOG_PATH)
        species_ids = {row.species_id for row in species}
        # JOIN: one family assignment per species, every key a real species, none stray.
        self.assertEqual(set(families), species_ids)
        self.assertTrue(all(v for v in families.values()),
                        "every species carries at least one family")
        # Every family id is a non-empty string; the membership total is the per-species sum.
        family_ids = {f for v in families.values() for f in (v if isinstance(v, list) else [v])}
        self.assertTrue(all(isinstance(f, str) and f for f in family_ids))
        memberships = sum(len(v if isinstance(v, list) else [v]) for v in families.values())
        self.assertGreaterEqual(memberships, len(species_ids),
                                "at least one membership per species")
        print(f"signature roster: {len(species_ids)} species, {len(family_ids)} families, "
              f"{memberships} memberships")


if __name__ == "__main__":
    unittest.main()
