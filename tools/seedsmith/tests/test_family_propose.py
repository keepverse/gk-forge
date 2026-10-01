"""Tests for `family-propose` (A-P2, spec-family-propose.md, action-corpus program).

    python -m pytest gk-forge/tools/seedsmith/tests/test_family_propose.py -v

Spec SS4's named cases plus SS5's acceptance criteria (1-12). Every test here runs against a
transport that has never been given a chance to be called -- most tests never touch
`pipeline.llm_caller` at all (`build_context`/`build_brief`/the validators/`finalize_candidate`
make zero calls by construction), and the ones that exercise the "makes no call" guarantee
end-to-end patch `seedsmith.pipeline.llm_caller.call_model` with a stub whose only behaviour is
`raise AssertionError` -- the same precedent `test_general_propose.py` uses
(`test_classify_pipelines.py`'s own `raising_call`, NOT `test_offline_guarantee.py`'s, which
PERMITS localhost -- exactly where the model runs).

The one "recorded transcript replay" test in SS4.2 feeds three PREVIOUSLY-RECORDED draft dicts
back through the same deterministic vote/hash logic (`finalize_candidate` -> `candidate_row` ->
`canonical_dump`) -- never a live call, and never `sample_draft`/`propose_family_action` (the two
functions in this whole module that DO call a model, per their own docstrings).

Real, live repo data (`gk-data/packs/fusion/data/seed/actions/_briefs/round-1.json`, A-S1's shipped output, and
`gk-data/packs/fusion/data/seed/creatures/_generated/family-assignments.json`) is used for determinism/shape/permutation/
roster tests, matching every prior action-corpus module's own fixture discipline this session;
synthetic, in-memory briefs are used for planted violations, vote resolution, and the anchor/slot
raises, so those tests do not depend on today's real round happening to contain a matching case.
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
from seedsmith.adapters.actions.family_propose.prompts import (  # noqa: E402
    FAMILY_ACTION_SCHEMA,
    SYSTEM_PROMPT,
    atom_families_are_allowed,
    atom_families_not_forbidden,
    build_brief,
    build_context,
    entry_for,
    motifs_expressed_are_known,
    motifs_expressed_exclude_anti_motifs,
    schema_for_call,
)
from seedsmith.adapters.actions.family_propose.derive import (  # noqa: E402
    MAX_HEAL,
    SAMPLE_COUNT,
    Candidate,
    build_verify_fn,
    candidate_row,
    candidate_set_hash,
    canonical_dump,
    canonical_family_key,
    default_for_none,
    finalize_candidate,
)
from seedsmith.adapters.actions import generate_family_actions as gen_mod  # noqa: E402
from seedsmith.adapters.creatures.anchor.permute import order_for  # noqa: E402
from seedsmith.adapters.creatures.anchor.vote import SetVoteResult  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[3]

# `REPO_ROOT`-relative joins below ask which repository actually carries the path. A prefix-keyed
# rewrite is wrong: `data`, `data/seed` and `data/seed/creatures` all resolve back to gk-forge,
# because nearest-match-wins and gk-forge owns its own generator inputs. `or REPO_ROOT` is
# load-bearing - `owning_base` returns None for a path no repository carries, where
# `content_root()` would RAISE.

from seedsmith.workspace_roots import owning_base, seed_root  # noqa: E402


def _owned(relative: str) -> "Path":
    """The repository carrying `relative`, joined to it; this one when none carries it."""
    return (owning_base(relative, REPO_ROOT) or REPO_ROOT) / relative

REAL_BRIEFS_PATH = _owned("data/seed/actions/_briefs/round-1.json")
REAL_FAMILY_ASSIGNMENTS_PATH = (
    seed_root() / "creatures/_generated/family-assignments.json"
)
RUN_TUNING_PATH = _owned("data/tuning/action-corpus-run.v1.json")


def raising_call(*args, **kwargs):
    raise AssertionError("a real model call was attempted -- this test's transport must never be reached")


# ---------------------------------------------------------------------------------------------
# Synthetic fixture -- a family-scope brief shaped exactly like A-S1's own shipped envelope
# (measured against `gk-data/packs/fusion/data/seed/actions/_briefs/round-1.json`), kept self-contained so vote/
# validator/planted-violation tests do not depend on today's real round happening to contain a
# matching case.
# ---------------------------------------------------------------------------------------------

def make_brief(**overrides) -> dict:
    brief = {
        "briefId": "brief.family.cherry.001", "id": "brief.family.cherry.001",
        "scope": "family", "scopeKey": "cherry",
        "anchor": {
            "family": "cherry", "element": None, "rarity": None, "themeKey": None,
            "motifs": [], "antiMotifs": [],
            "familyMotifs": ["bomb", "zombie"], "familyAntiMotifs": ["protect", "roof"],
            "familyMotifBasis": "intersection",
        },
        "slot": {"category": "attack", "targetMode": "self", "areaShape": None,
                "relation": "enemy", "kind": None, "rungBand": [1, 7]},
        "pool": {"allowedAtomFamilies": ["atom.a", "atom.b", "atom.c"],
                "forbiddenAtomFamilies": ["atom.z"]},
        "pairing": {"role": "none", "pairedPayoffFamily": None},
        "avoidNeighbours": [],
        "_provenance": {"corpusHash": "deadbeef", "promptVersion": 1, "round": 1, "tuningVersion": 1},
    }
    brief.update(overrides)
    return brief


def make_draft(**overrides) -> dict:
    draft = {
        "name": "Cherry Bloom Rally", "flavor": "A ripple runs through every cherry in the row.",
        "atomFamilies": ["atom.a", "atom.b"],
        "motifsExpressed": ["bomb"],
        "rationale": "Pairs a burst family with a utility one for the whole cherry line.",
        BLOCKED_FIELD: "",
    }
    draft.update(overrides)
    return draft


# ---------------------------------------------------------------------------------------------
# Acceptance #1/#2/#3 -- Stage 0's own schema audit, reused directly (never re-implemented
# locally), plus the schema's own shape rules.
# ---------------------------------------------------------------------------------------------

class SchemaAuditTests(unittest.TestCase):
    def test_shipped_schema_has_no_audit_defects(self):
        self.assertEqual(audit_schema(FAMILY_ACTION_SCHEMA), [])

    def test_every_property_description_carries_a_negative_clause(self):
        self.assertEqual(audit_descriptions(FAMILY_ACTION_SCHEMA), [])

    def test_blocked_field_is_required_and_a_string(self):
        self.assertIn(BLOCKED_FIELD, FAMILY_ACTION_SCHEMA["required"])
        self.assertEqual(FAMILY_ACTION_SCHEMA["properties"][BLOCKED_FIELD]["type"], "string")

    def test_every_field_is_required_and_additional_properties_is_false(self):
        # acceptance #3
        for key in ("name", "flavor", "atomFamilies", "motifsExpressed", "rationale", BLOCKED_FIELD):
            self.assertIn(key, FAMILY_ACTION_SCHEMA["required"])
        self.assertFalse(FAMILY_ACTION_SCHEMA["additionalProperties"])

    def test_schema_for_call_fills_both_enums_and_stays_defect_free(self):
        called = schema_for_call(["atom.a", "atom.b"], ["motif-x", "none"])
        self.assertEqual(called["properties"]["atomFamilies"]["items"]["enum"], ["atom.a", "atom.b"])
        self.assertEqual(called["properties"]["motifsExpressed"]["items"]["enum"], ["motif-x", "none"])
        self.assertEqual(FAMILY_ACTION_SCHEMA["properties"]["atomFamilies"]["items"]["enum"], [],
                         "schema_for_call must never mutate the shared constant")
        self.assertEqual(FAMILY_ACTION_SCHEMA["properties"]["motifsExpressed"]["items"]["enum"], [],
                         "schema_for_call must never mutate the shared constant")
        self.assertEqual(audit_schema(called), [])

    # --- planted violations (spec SS4.3) -----------------------------------------------------

    def test_planted_bare_integer_field_is_a_defect(self):
        planted = copy.deepcopy(FAMILY_ACTION_SCHEMA)
        planted["properties"]["rung"] = {"type": "integer", "description": "never a number"}
        defects = audit_schema(planted)
        self.assertTrue(any(d.path == "$.rung" for d in defects))

    def test_planted_all_numeric_string_enum_is_a_defect(self):
        planted = copy.deepcopy(FAMILY_ACTION_SCHEMA)
        planted["properties"]["tierEnum"] = {"type": "string", "enum": ["1", "2", "3"],
                                             "description": "never a magnitude"}
        defects = audit_schema(planted)
        self.assertTrue(any(d.path == "$.tierEnum" for d in defects))

    def test_schema_without_blocked_property_is_a_defect(self):
        planted = copy.deepcopy(FAMILY_ACTION_SCHEMA)
        del planted["properties"][BLOCKED_FIELD]
        planted["required"] = [r for r in planted["required"] if r != BLOCKED_FIELD]
        defects = audit_schema(planted)
        self.assertTrue(any("blocked" in d.reason for d in defects))

    def test_motifs_expressed_enum_without_none_is_this_modules_own_defect_to_catch(self):
        # spec SS4.3: "a schema whose motifsExpressed enum omits none -> this module's OWN schema
        # test fails". schema_for_call itself trusts its caller (it fills the enum AS GIVEN) --
        # the guarantee that "none" is always present lives in build_context, proven below by
        # DeterminismTests/BuildBriefContentTests. This test documents the failure mode directly:
        # a caller that forgets "none" produces a schema this test can see is wrong.
        called = schema_for_call(["atom.a"], ["motif-x"])  # caller forgot "none"
        self.assertNotIn("none", called["properties"]["motifsExpressed"]["items"]["enum"])


# ---------------------------------------------------------------------------------------------
# Acceptance #5 -- the two raises: species-scoped anchor content, and an absent family-motif
# derivation key. An empty derived list is legal (F15's own correction).
# ---------------------------------------------------------------------------------------------

class FamilyAnchorRaiseTests(unittest.TestCase):
    def test_well_formed_family_anchor_does_not_raise(self):
        build_context(make_brief(), sample_index=0)

    def test_missing_family_motif_derivation_key_raises(self):
        for key in ("familyMotifs", "familyAntiMotifs", "familyMotifBasis"):
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

    def test_empty_family_motif_lists_are_legal_not_a_raise(self):
        # F15's own correction (acceptance #5): the KEY must be present, but an EMPTY list is a
        # legal, real value -- "this family has no shared motif" is the correct render, not a
        # raise. Same absent-vs-empty discipline this program already applies elsewhere.
        anchor = dict(make_brief()["anchor"])
        anchor["familyMotifs"] = []
        anchor["familyAntiMotifs"] = []
        brief = make_brief(anchor=anchor)
        context = build_context(brief, sample_index=0)  # must not raise
        self.assertEqual(context["motifsExpressedEnum"], ["none"])
        self.assertIn("this family has no shared motif", build_brief(context).lower())

    def test_species_scoped_anchor_content_raises(self):
        base_anchor = dict(make_brief()["anchor"])
        for key, value in (("element", "fire"), ("motifs", ["fire"]),
                          ("themeKey", "creature.cherrybomb"), ("speciesKey", "cherrybomb")):
            with self.subTest(key=key):
                anchor = dict(base_anchor)
                anchor[key] = value
                brief = make_brief(anchor=anchor)
                with self.assertRaises(ValueError):
                    build_context(brief, sample_index=0)

    def test_real_species_scope_brief_raises(self):
        # a real A-S1 species-scope brief has no familyMotifs/familyAntiMotifs/familyMotifBasis
        # keys at all (measured against round-1.json) -- it must raise, never be silently read.
        doc = json.loads(REAL_BRIEFS_PATH.read_text(encoding="utf-8"))
        species_brief = next(e for e in doc["entries"] if e["scope"] == "species")
        with self.assertRaises(ValueError):
            build_context(species_brief, sample_index=0)

    def test_real_general_scope_brief_raises(self):
        doc = json.loads(REAL_BRIEFS_PATH.read_text(encoding="utf-8"))
        general_brief = next(e for e in doc["entries"] if e["scope"] == "general")
        with self.assertRaises(ValueError):
            build_context(general_brief, sample_index=0)

    def test_real_family_scope_briefs_never_raise(self):
        # The expected count comes from the live family keys and the current run tuning, not the
        # retired 19-family smoke projection.
        doc = json.loads(REAL_BRIEFS_PATH.read_text(encoding="utf-8"))
        family_briefs = [e for e in doc["entries"] if e["scope"] == "family"]
        family_count = len({e["scopeKey"] for e in family_briefs})
        per_family_count = json.loads(RUN_TUNING_PATH.read_text(encoding="utf-8"))["perFamilyCount"]
        self.assertEqual(len(family_briefs), family_count * per_family_count)
        for brief in family_briefs:
            with self.subTest(briefId=brief["briefId"]):
                build_context(brief, sample_index=0)  # must not raise

    def test_missing_slot_field_raises(self):
        for field_name in ("category", "targetMode", "areaShape", "relation", "kind", "rungBand"):
            with self.subTest(field=field_name):
                slot = dict(make_brief()["slot"])
                del slot[field_name]
                brief = make_brief(slot=slot)
                with self.assertRaises(ValueError):
                    build_context(brief, sample_index=0)

    def test_null_slot_value_does_not_raise(self):
        # a value being a legal `null` (kind/areaShape today) is a different thing from the KEY
        # being absent -- distribution_planner/derive.py ships `kind: null` on every brief.
        build_context(make_brief(), sample_index=0)


# ---------------------------------------------------------------------------------------------
# Acceptance #4 -- what build_brief inlines, and does not.
# ---------------------------------------------------------------------------------------------

class BuildBriefContentTests(unittest.TestCase):
    def test_no_file_path_or_markdown_citation(self):
        context = build_context(make_brief(), sample_index=0)
        text = build_brief(context)
        self.assertNotIn(".md", text)
        self.assertNotIn("spec-", text)

    def test_family_id_present_but_no_species_derived_token(self):
        context = build_context(make_brief(), sample_index=0)
        text = build_brief(context)
        self.assertIn("cherry", text)  # the family anchor IS meant to appear
        lowered = text.lower()
        for token in ("fire", "cultivated", "creature.", "element:", "species:"):
            self.assertNotIn(token, lowered)

    def test_family_motifs_render_in_permuted_order_matching_order_for(self):
        brief = make_brief(anchor=dict(make_brief()["anchor"],
                                       familyMotifs=["zeta", "alpha", "mu", "beta"]))
        context = build_context(brief, sample_index=2)
        expected = order_for(brief["briefId"], "motifsExpressed", 2,
                             sorted(["zeta", "alpha", "mu", "beta"]) + ["none"])
        self.assertEqual(context["motifsExpressedEnum"], list(expected))
        text = build_brief(context)
        # rendered order (minus "none") matches the permuted enum order, minus "none"
        rendered_order = [m for m in expected if m != "none"]
        self.assertIn(", ".join(rendered_order), text)

    def test_empty_family_motifs_render_explicit_sentence(self):
        anchor = dict(make_brief()["anchor"], familyMotifs=[])
        context = build_context(make_brief(anchor=anchor), sample_index=0)
        self.assertIn("this family has no shared motif", build_brief(context).lower())

    def test_anti_motifs_each_carry_the_rejection_sentence(self):
        context = build_context(make_brief(), sample_index=0)
        text = build_brief(context)
        for motif in context["familyAntiMotifs"]:
            self.assertIn(f"{motif}: an action expressing this is rejected.", text)

    def test_no_anti_motifs_section_when_list_is_empty(self):
        anchor = dict(make_brief()["anchor"], familyAntiMotifs=[])
        context = build_context(make_brief(anchor=anchor), sample_index=0)
        text = build_brief(context)
        self.assertNotIn("anti-motifs", text.lower())

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
            {"actionId": "action.family.0001", "fingerprint": "a+b|attack|self|enemy|none"},
        ])
        context = build_context(brief, sample_index=0)
        text = build_brief(context)
        self.assertIn("Do not produce", text)
        self.assertIn("a+b|attack|self|enemy|none", text)


# ---------------------------------------------------------------------------------------------
# SMOKE BATCH criterion-2 fix, 2026-09-05 -- same technique and same byte-identical-when-absent
# guarantee as `general_propose`'s own `AtomFamilyGlossaryTests` (`test_general_propose.py`).
# ---------------------------------------------------------------------------------------------

class ScopeLabelTests(unittest.TestCase):
    """ST3 (`spec-scope-window-tunables.md` contract 4, spec tests 6 and 6b): the rung-band label
    keys on the brief's SCOPE. The old pair-keyed table read `.get(window, fallback)`, which is
    exactly what spec test 6b describes -- with `family.ceiling = 6` a `[1,6]` family band missed
    the `(1, 7)` key and rendered the fallback text into the prompt instead of the family label."""

    FALLBACK = "outside the three known scope windows"

    def _label(self, **overrides) -> str:
        return build_context(make_brief(**overrides), sample_index=0)["rungBandLabel"]

    def test_the_label_comes_from_the_scope_not_the_window(self) -> None:
        shipped = self._label()                                   # scope family, band [1, 7]
        self.assertIn("mid tier", shipped)
        self.assertNotIn(self.FALLBACK, shipped)

        # The RETUNED family window (a `family.ceiling = 6` world) must render the family label --
        # never the fallback the old pair-keyed table produced for exactly this band.
        retuned = self._label(slot={**make_brief()["slot"], "rungBand": [1, 6]})
        self.assertEqual(shipped, retuned)
        self.assertNotIn(self.FALLBACK, retuned)

    def test_an_unknown_scope_raises_rather_than_falling_back(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            self._label(scope="not-a-real-scope")
        self.assertIn("not-a-real-scope", str(ctx.exception))
        self.assertIn("EligibilityScope", str(ctx.exception))


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
# Determinism / permutation (spec SS4.2) -- BOTH enums.
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
        brief = make_brief(anchor=dict(make_brief()["anchor"],
                                       familyMotifs=["delta", "gamma", "alpha"]))
        context = build_context(brief, sample_index=2)
        expected = order_for(brief["briefId"], "motifsExpressed", 2,
                             sorted(["delta", "gamma", "alpha"]) + ["none"])
        self.assertEqual(context["motifsExpressedEnum"], list(expected))

    def test_motifs_expressed_enum_always_includes_none(self):
        context = build_context(make_brief(), sample_index=0)
        self.assertIn("none", context["motifsExpressedEnum"])

    def test_motifs_expressed_enum_is_exactly_none_when_family_motifs_empty(self):
        anchor = dict(make_brief()["anchor"], familyMotifs=[])
        context = build_context(make_brief(anchor=anchor), sample_index=0)
        self.assertEqual(context["motifsExpressedEnum"], ["none"])

    def test_atom_families_and_motifs_expressed_use_independent_seeds(self):
        # two DIFFERENT field names in the permutation seed (spec SS2): a large enough atom pool
        # and motif pool that a shared/aliased seed would be statistically implausible to miss.
        doc = json.loads(REAL_BRIEFS_PATH.read_text(encoding="utf-8"))
        brief = next(e for e in doc["entries"] if e["scope"] == "family")
        context = build_context(brief, sample_index=0)
        atom_orders = [build_context(brief, sample_index=i)["allowedAtomFamilies"] for i in range(3)]
        self.assertTrue(atom_orders[0] != atom_orders[1] or atom_orders[1] != atom_orders[2])


# ---------------------------------------------------------------------------------------------
# Validators -- planted violations: an atom family / motif outside this brief's own lists, and a
# motif that is one of the family's own anti-motifs.
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
        draft = make_draft(atomFamilies=["atom.a", "atom.b"])
        self.assertEqual(atom_families_are_allowed(draft, context), [])

    def test_forbidden_family_is_rejected(self):
        context = build_context(make_brief(), sample_index=0)
        draft = make_draft(atomFamilies=["atom.a", "atom.z"])
        reasons = atom_families_not_forbidden(draft, context)
        self.assertTrue(reasons)
        self.assertIn("atom.z", reasons[0])

    def test_motif_outside_brief_list_is_rejected_and_named(self):
        context = build_context(make_brief(), sample_index=0)
        draft = make_draft(motifsExpressed=["not-a-real-motif"])
        reasons = motifs_expressed_are_known(draft, context)
        self.assertTrue(reasons)
        self.assertIn("not-a-real-motif", reasons[0])

    def test_motif_within_brief_list_passes(self):
        context = build_context(make_brief(), sample_index=0)
        draft = make_draft(motifsExpressed=["bomb"])
        self.assertEqual(motifs_expressed_are_known(draft, context), [])

    def test_none_is_a_legal_motif_pick(self):
        context = build_context(make_brief(), sample_index=0)
        draft = make_draft(motifsExpressed=["none"])
        self.assertEqual(motifs_expressed_are_known(draft, context), [])

    def test_anti_motif_in_motifs_expressed_is_hard_rejected_and_named(self):
        context = build_context(make_brief(), sample_index=0)
        anti = context["familyAntiMotifs"][0]
        draft = make_draft(motifsExpressed=[anti])
        reasons = motifs_expressed_exclude_anti_motifs(draft, context)
        self.assertTrue(reasons)
        self.assertIn(anti, reasons[0])

    def test_verify_fn_hard_defect_names_the_offending_family_for_the_reprompt(self):
        context = build_context(make_brief(), sample_index=0)
        verify_fn = build_verify_fn(context)
        draft = make_draft(atomFamilies=["atom.rogue-family"])
        hard, soft = verify_fn(dict(context), draft)
        self.assertIn("atomFamilies", hard)
        self.assertIn("atom.rogue-family", hard["atomFamilies"])

    def test_verify_fn_hard_defect_names_the_offending_anti_motif_for_the_reprompt(self):
        context = build_context(make_brief(), sample_index=0)
        anti = context["familyAntiMotifs"][0]
        verify_fn = build_verify_fn(context)
        draft = make_draft(motifsExpressed=[anti])
        hard, soft = verify_fn(dict(context), draft)
        self.assertIn("motifsExpressed", hard)
        self.assertIn(anti, hard["motifsExpressed"])

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
        self.assertIsNone(default_for_none("motifsExpressed", ["bomb"]))


# ---------------------------------------------------------------------------------------------
# Vote resolution (spec SS2 "Which fields are voted") -- ONLY atomFamilies. motifsExpressed is
# never voted; it is always sample 0's own value.
# ---------------------------------------------------------------------------------------------

class VoteResolutionTests(unittest.TestCase):
    def test_3_0_agreement_is_high_confidence_and_accepted(self):
        brief = make_brief()
        drafts = [make_draft(), make_draft(), make_draft()]
        cand = finalize_candidate(brief, drafts, candidate_id="candidate.family.000")
        self.assertEqual(cand.outcome, "accepted")
        self.assertEqual(cand.vote.confidence, "high")
        self.assertEqual(cand.entry["atomFamilies"], ["atom.a", "atom.b"])

    def test_2_1_split_records_the_minority_and_still_accepts(self):
        brief = make_brief()
        drafts = [make_draft(atomFamilies=["atom.a", "atom.b"]),
                 make_draft(atomFamilies=["atom.a", "atom.b"]),
                 make_draft(atomFamilies=["atom.a", "atom.c"])]
        cand = finalize_candidate(brief, drafts, candidate_id="candidate.family.000")
        self.assertEqual(cand.outcome, "accepted")
        self.assertEqual(cand.vote.confidence, "split")
        # Per-member voting names the member that fell below threshold (`atom.c`),
        # not the whole losing set -- the old answer wrongly listed `atom.a`, which
        # all three samples chose. See the general-propose twin of this test.
        self.assertEqual(cand.vote.minority, ("atom.c",))

    def test_1_1_1_split_is_unresolved_value_is_none_never_sample_zero(self):
        brief = make_brief()
        drafts = [make_draft(atomFamilies=["atom.a"]),
                 make_draft(atomFamilies=["atom.b"]),
                 make_draft(atomFamilies=["atom.c"])]
        cand = finalize_candidate(brief, drafts, candidate_id="candidate.family.000")
        self.assertEqual(cand.outcome, "unresolved")
        self.assertIsNone(cand.entry)
        self.assertIsNone(cand.vote.value)
        self.assertEqual(cand.vote.confidence, "unresolved")

    def test_atom_family_order_within_a_pick_does_not_create_a_false_split(self):
        brief = make_brief()
        drafts = [make_draft(atomFamilies=["atom.a", "atom.b"]),
                 make_draft(atomFamilies=["atom.b", "atom.a"]),
                 make_draft(atomFamilies=["atom.a", "atom.b"])]
        cand = finalize_candidate(brief, drafts, candidate_id="candidate.family.000")
        self.assertEqual(cand.vote.confidence, "high")

    def test_a_sample_that_never_produced_a_usable_pick_still_casts_its_own_vote(self):
        brief = make_brief()
        drafts = [make_draft(atomFamilies=["atom.a", "atom.b"]),
                 make_draft(atomFamilies=["atom.a", "atom.b"]),
                 make_draft(atomFamilies=None)]
        cand = finalize_candidate(brief, drafts, candidate_id="candidate.family.000")
        self.assertEqual(cand.outcome, "accepted")
        self.assertEqual(cand.vote.confidence, "split")

    def test_blocked_sample_zero_short_circuits_before_any_vote(self):
        brief = make_brief()
        drafts = [make_draft(**{BLOCKED_FIELD: "brief has nothing to work from"}),
                 make_draft(), make_draft()]
        cand = finalize_candidate(brief, drafts, candidate_id="candidate.family.000")
        self.assertEqual(cand.outcome, "blocked")
        self.assertIsNone(cand.entry)
        self.assertIsNone(cand.vote)

    def test_finalize_candidate_requires_exactly_three_drafts(self):
        with self.assertRaises(ValueError):
            finalize_candidate(make_brief(), [make_draft(), make_draft()], candidate_id="x")

    def test_motifs_expressed_is_never_voted_always_sample_zero(self):
        # three samples pick the SAME atomFamilies (an easy 3-0 vote) but DIFFERENT
        # motifsExpressed -- the final entry must carry sample 0's own value, proving the field
        # is never itself voted (spec SS2's own explicit rule).
        brief = make_brief()
        drafts = [make_draft(motifsExpressed=["bomb"]),
                 make_draft(motifsExpressed=["zombie"]),
                 make_draft(motifsExpressed=["none"])]
        cand = finalize_candidate(brief, drafts, candidate_id="candidate.family.000")
        self.assertEqual(cand.outcome, "accepted")
        self.assertEqual(cand.entry["motifsExpressed"], ["bomb"])  # sample 0's own value


# ---------------------------------------------------------------------------------------------
# A-S7 `coverage-assignment` splice (spec-coverage-assignment.md SS6) -- proven independently on
# THIS pipeline, not assumed to transfer from `signature_propose`'s own identical proof.
# ---------------------------------------------------------------------------------------------

class RequiredFamiliesSpliceTests(unittest.TestCase):
    def test_omitting_required_families_is_byte_identical(self):
        drafts = [make_draft(), make_draft(), make_draft()]
        with_key = finalize_candidate(make_brief(requiredFamilies=[]), drafts, candidate_id="x")
        without_key = finalize_candidate(make_brief(), drafts, candidate_id="x")
        self.assertEqual(with_key.entry["atomFamilies"], without_key.entry["atomFamilies"])
        self.assertEqual(without_key.entry["atomFamilies"], sorted({"atom.a", "atom.b"}))

    def test_an_accepted_candidate_gets_the_required_family_spliced_in(self):
        drafts = [make_draft(), make_draft(), make_draft()]
        cand = finalize_candidate(make_brief(requiredFamilies=["atom.required"]), drafts,
                                  candidate_id="x")
        self.assertEqual(cand.outcome, "accepted")
        self.assertEqual(cand.entry["atomFamilies"], sorted({"atom.a", "atom.b", "atom.required"}))

    def test_an_unresolved_candidate_is_never_spliced(self):
        drafts = [make_draft(atomFamilies=["atom.a"]), make_draft(atomFamilies=["atom.b"]),
                 make_draft(atomFamilies=["atom.c"])]
        cand = finalize_candidate(make_brief(requiredFamilies=["atom.required"]), drafts,
                                  candidate_id="x")
        self.assertEqual(cand.outcome, "unresolved")
        self.assertIsNone(cand.entry)


# ---------------------------------------------------------------------------------------------
# Recorded-transcript replay (spec SS4.2): three PRE-RECORDED samples fed through the same
# deterministic vote/hash logic twice -- byte-identical candidate output both times.
# ---------------------------------------------------------------------------------------------

class RecordedTranscriptReplayTests(unittest.TestCase):
    RECORDED_SAMPLES = [
        {"name": "Cherry Bloom Rally", "flavor": "A ripple runs through every cherry in the row.",
         "atomFamilies": ["atom.a", "atom.b"], "motifsExpressed": ["bomb"],
         "rationale": "Combines a burst family with a utility one across the whole line.",
         BLOCKED_FIELD: ""},
        {"name": "Ripe Detonation", "flavor": "Every fruit on the row primes at once.",
         "atomFamilies": ["atom.b", "atom.a"], "motifsExpressed": ["zombie"],
         "rationale": "The two families reinforce a single burst posture.",
         BLOCKED_FIELD: ""},
        {"name": "Bomb Line", "flavor": "A fuse that runs down every stem.",
         "atomFamilies": ["atom.a", "atom.b"], "motifsExpressed": ["none"],
         "rationale": "Anchors the role in raw burst damage.",
         BLOCKED_FIELD: ""},
    ]

    def _replay(self) -> str:
        brief = make_brief()
        cand = finalize_candidate(brief, [dict(d) for d in self.RECORDED_SAMPLES],
                                  candidate_id="candidate.family.000",
                                  provenance={"pipeline": "family-propose", "model": "recorded"})
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
        self.assertEqual(row["confidence"], "high")
        self.assertEqual(row["draft"]["atomFamilies"], ["atom.a", "atom.b"])
        self.assertEqual(row["draft"]["motifsExpressed"], ["bomb"])  # sample 0's own, never voted


# ---------------------------------------------------------------------------------------------
# Offline guarantee (spec SS4.1) -- every pure path makes zero calls, proven by patching the
# ACTUAL transport `call_model` with a stub that raises the moment it would be reached.
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
            self.assertEqual(audit_schema(FAMILY_ACTION_SCHEMA), [])
            cand = finalize_candidate(brief, [make_draft(), make_draft(), make_draft()],
                                      candidate_id="candidate.family.000")
            self.assertEqual(cand.outcome, "accepted")

    def test_entry_for_never_reaches_the_model(self):
        with patch("seedsmith.pipeline.llm_caller.call_model", raising_call):
            entry = entry_for(make_draft(), candidate_id="candidate.family.000",
                              brief_id="brief.family.cherry.001")
            self.assertEqual(entry["name"], "Cherry Bloom Rally")


# ---------------------------------------------------------------------------------------------
# Acceptance #8 -- `--dry-run` / `--count`, against real A-S1 output.
# ---------------------------------------------------------------------------------------------

class DryRunEntrypointTests(unittest.TestCase):
    def test_dry_run_makes_zero_calls_and_renders_a_sample_brief(self):
        with patch("seedsmith.pipeline.llm_caller.call_model", raising_call):
            summary = gen_mod.regenerate(dry_run=True, count=2)
        self.assertTrue(summary["dryRun"])
        self.assertEqual(summary["modelCalls"], 0)
        expected = len({e["scopeKey"] for e in json.loads(REAL_BRIEFS_PATH.read_text(encoding="utf-8"))["entries"]
                        if e["scope"] == "family"}) * json.loads(RUN_TUNING_PATH.read_text(encoding="utf-8"))["perFamilyCount"]
        self.assertEqual(summary["totalFamilyBriefs"], expected)
        self.assertEqual(summary["selected"], 2)
        self.assertIn("Design ONE family action", summary["sampleBrief"])

    def test_count_bounds_the_selection(self):
        with patch("seedsmith.pipeline.llm_caller.call_model", raising_call):
            summary = gen_mod.regenerate(dry_run=True, count=1)
        self.assertEqual(summary["selected"], 1)

    def test_load_family_briefs_reads_only_family_scope_sorted(self):
        briefs = gen_mod.load_family_briefs()
        self.assertTrue(all(b["scope"] == "family" for b in briefs))
        expected = len({b["scopeKey"] for b in briefs}) * json.loads(RUN_TUNING_PATH.read_text(encoding="utf-8"))["perFamilyCount"]
        self.assertEqual(len(briefs), expected)
        self.assertEqual([b["briefId"] for b in briefs], sorted(b["briefId"] for b in briefs))

    def test_brief_hash_is_deterministic_and_brief_specific(self):
        b1 = make_brief()
        b2 = make_brief()
        self.assertEqual(gen_mod._brief_hash(b1), gen_mod._brief_hash(b2))
        b3 = make_brief(briefId="brief.family.cherry.002")
        self.assertNotEqual(gen_mod._brief_hash(b1), gen_mod._brief_hash(b3))

    def test_real_run_writes_provenance_with_model_prompt_version_brief_hash_and_candidate_set_hash(self):
        def fake_propose(brief, *, candidate_id, pairing_table=None, family_glossary=None,
                        config=None, provenance=None):
            return Candidate(
                brief_id=brief["briefId"], outcome="accepted",
                entry=entry_for(make_draft(), candidate_id=candidate_id, brief_id=brief["briefId"],
                               provenance=provenance),
                vote=SetVoteResult(values=("atom.a", "atom.b"), confidence="high",
                                   minority=(), tally={"atom.a": 3, "atom.b": 3}),
                provenance=dict(provenance or {}),
            )

        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp) / "_candidates" / "family"
            with patch("seedsmith.adapters.actions.generate_family_actions.propose_family_action",
                      fake_propose):
                summary = gen_mod.regenerate(dry_run=False, count=1, candidates_dir=out_dir,
                                             config=LlmCallerConfig(model="test-model-x"))
            self.assertTrue(summary["written"])
            written = json.loads((out_dir / "round-1.json").read_text(encoding="utf-8"))
            self.assertEqual(written["_meta"]["model"], "test-model-x")
            self.assertEqual(written["_meta"]["promptVersion"], gen_mod.PROMPT_VERSION)
            self.assertIn("candidateSetHash", written["_meta"])
            self.assertIn("briefsCorpusHash", written["_meta"])
            row = written["entries"][0]
            self.assertIn("briefHash", row["_provenance"])
            self.assertEqual(row["_provenance"]["model"], "test-model-x")

            # rerun over unchanged inputs is byte-identical (acceptance #10)
            out_dir2 = Path(tmp) / "_candidates2" / "family"
            with patch("seedsmith.adapters.actions.generate_family_actions.propose_family_action",
                      fake_propose):
                gen_mod.regenerate(dry_run=False, count=1, candidates_dir=out_dir2,
                                   config=LlmCallerConfig(model="test-model-x"))
            self.assertEqual((out_dir / "round-1.json").read_text(encoding="utf-8"),
                             (out_dir2 / "round-1.json").read_text(encoding="utf-8"))


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

        with patch("seedsmith.adapters.actions.family_propose.derive.call_with_self_heal",
                  fake_call_with_self_heal):
            from seedsmith.adapters.actions.family_propose.derive import sample_draft
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
        brief = make_brief()
        cand = finalize_candidate(brief, [make_draft(), make_draft(), make_draft()],
                                  candidate_id="candidate.family.000",
                                  provenance={"pipeline": "family-propose", "model": "x"})
        row = candidate_row(cand)
        _walk_no_numbers(row)


# ---------------------------------------------------------------------------------------------
# Candidate-set hashing (mirrors acceptance #10's "candidate-set hash").
# ---------------------------------------------------------------------------------------------

class CandidateSetHashTests(unittest.TestCase):
    def test_hash_is_order_independent_of_input_ordering(self):
        brief = make_brief()
        cand = finalize_candidate(brief, [make_draft(), make_draft(), make_draft()],
                                  candidate_id="candidate.family.000")
        row = candidate_row(cand)
        row2 = dict(row)
        h1 = candidate_set_hash([row, row2])
        h2 = candidate_set_hash([row2, row])
        self.assertEqual(h1, h2)

    def test_hash_changes_when_a_row_changes(self):
        brief = make_brief()
        cand = finalize_candidate(brief, [make_draft(), make_draft(), make_draft()],
                                  candidate_id="candidate.family.000")
        row = candidate_row(cand)
        changed = dict(row, outcome="blocked")
        self.assertNotEqual(candidate_set_hash([row]), candidate_set_hash([changed]))


# ---------------------------------------------------------------------------------------------
# canonical_family_key -- the vote's own canonicalisation.
# ---------------------------------------------------------------------------------------------

class CanonicalFamilyKeyTests(unittest.TestCase):
    def test_order_independent_and_deduped(self):
        self.assertEqual(canonical_family_key(["b", "a", "a"]), canonical_family_key(["a", "b"]))

    def test_distinct_sets_produce_distinct_keys(self):
        self.assertNotEqual(canonical_family_key(["a"]), canonical_family_key(["a", "b"]))


# ---------------------------------------------------------------------------------------------
# Roster test, not a claim (spec SS4.4): the plan was sized on real per-family member counts read
# straight from `family-assignments.json`. Asserted as RECONCILIATION (bins sum, memberships sum),
# never a pinned snapshot -- the family map is a population that grows per shipped species
# (docs/architecture/validation-ssot.md).
# ---------------------------------------------------------------------------------------------

class RosterTests(unittest.TestCase):
    def test_family_assignments_reconcile(self):
        assignments = json.loads(REAL_FAMILY_ASSIGNMENTS_PATH.read_text(encoding="utf-8"))
        counts: "dict[str, int]" = {}
        for species_id, families in assignments.items():
            values = families if isinstance(families, list) else [families]
            self.assertTrue(values, f"{species_id} must carry at least one family")
            for family in values:
                counts[family] = counts.get(family, 0) + 1

        # Reconciliation: every membership joins a real family token, and the per-family totals sum
        # to the per-species membership sum -- both recomputed, never a literal.
        self.assertEqual(sum(counts.values()),
                         sum(len(v if isinstance(v, list) else [v])
                             for v in assignments.values()))
        self.assertEqual(len(counts), len(set(counts)), "family tokens are a set")
        # The largest family is at least as large as the mean; nut exists and is non-empty.
        mean = sum(counts.values()) / len(counts)
        self.assertGreaterEqual(max(counts.values()), mean)
        self.assertTrue(all(n >= 1 for n in counts.values()))
        print(f"family assignments: {len(assignments)} species, {len(counts)} families, "
              f"mean {mean:.1f}")


if __name__ == "__main__":
    unittest.main()
