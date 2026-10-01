"""Tests for `general-propose` (A-P1, spec-general-propose.md, action-corpus program).

    python -m pytest gk-forge/tools/seedsmith/tests/test_general_propose.py -v

Spec SS4's named cases plus SS5's acceptance criteria (1-10). Every test here runs against a
transport that has never been given a chance to be called -- most tests never touch
`pipeline.llm_caller` at all (`build_context`/`build_brief`/the validators/`finalize_candidate`
make zero calls by construction), and the ones that exercise the "makes no call" guarantee
end-to-end patch `seedsmith.pipeline.llm_caller.call_model` with a stub whose only behaviour is
`raise AssertionError` -- the same precedent spec SS4.1 names (`test_classify_pipelines.py`'s own
`raising_call`), never `test_offline_guarantee.py`'s (that one PERMITS localhost, exactly where the
model runs).

The one "recorded transcript replay" test in SS4.2 feeds three PREVIOUSLY-RECORDED draft dicts
back through the same deterministic vote/hash logic (`finalize_candidate` -> `candidate_row` ->
`canonical_dump`) -- never a live call, and never `sample_draft`/`propose_general_action` (the two
functions in this whole module that DO call a model, per their own docstrings).

Real, live repo data (`gk-data/packs/fusion/data/seed/actions/_briefs/round-1.json`, A-S1's shipped output) is used for
determinism/shape/permutation tests, matching every prior action-corpus module's own fixture
discipline this session; synthetic, in-memory briefs are used for planted violations, vote
resolution, and the anchor/slot raises, so those tests do not depend on today's real round
happening to contain a case that exercises them.
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
from seedsmith.adapters.actions.general_propose.prompts import (  # noqa: E402
    GENERAL_ACTION_SCHEMA,
    SYSTEM_PROMPT,
    atom_families_are_allowed,
    atom_families_not_forbidden,
    build_brief,
    build_context,
    entry_for,
    render_worked_example,
    schema_for_call,
)
from seedsmith.adapters.actions.general_propose.derive import (  # noqa: E402
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
from seedsmith.adapters.actions import generate_general_actions as gen_mod  # noqa: E402
from seedsmith.adapters.creatures.anchor.permute import order_for  # noqa: E402
from seedsmith.adapters.creatures.anchor.vote import SetVoteResult  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[3]

# `REPO_ROOT`-relative joins below ask which repository actually carries the path. A prefix-keyed
# rewrite is wrong: `data`, `data/seed` and `data/seed/creatures` all resolve back to gk-forge,
# because nearest-match-wins and gk-forge owns its own generator inputs. `or REPO_ROOT` is
# load-bearing - `owning_base` returns None for a path no repository carries, where
# `content_root()` would RAISE.

from seedsmith.workspace_roots import owning_base  # noqa: E402


def _owned(relative: str) -> "Path":
    """The repository carrying `relative`, joined to it; this one when none carries it."""
    return (owning_base(relative, REPO_ROOT) or REPO_ROOT) / relative

REAL_BRIEFS_PATH = _owned("data/seed/actions/_briefs/round-1.json")
#: The TRACKED minimal fixture, not the pipeline's gitignored `_candidates/` scratch -- that scratch
#: is absent from every fresh checkout, so a test reading it could never pass there (SGC5-F1). The
#: fixture is a verbatim copy of the pinned accepted draft.
REAL_GENERAL_CANDIDATES_PATH = (
    _owned("data/seed/actions/_fixtures/general/round-1.json")
)


def raising_call(*args, **kwargs):
    raise AssertionError("a real model call was attempted -- this test's transport must never be reached")


# ---------------------------------------------------------------------------------------------
# Synthetic fixture -- a general-scope brief shaped exactly like A-S1's own shipped envelope, kept
# self-contained so vote/validator/planted-violation tests do not depend on today's real round
# happening to contain a matching case.
# ---------------------------------------------------------------------------------------------

def make_brief(**overrides) -> dict:
    brief = {
        "briefId": "brief.general.general.001", "id": "brief.general.general.001",
        "scope": "general", "scopeKey": None,
        "anchor": {"family": None, "element": None, "rarity": None, "themeKey": None,
                  "motifs": [], "antiMotifs": []},
        "slot": {"category": "attack", "targetMode": "self", "areaShape": None,
                "relation": "enemy", "kind": None, "rungBand": [1, 4]},
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
        "name": "Iron Resolve", "flavor": "A calm settles before the strike.",
        "atomFamilies": ["atom.a", "atom.b"],
        "rationale": "Pairs a defensive family with a utility one for a steady role.",
        BLOCKED_FIELD: "",
    }
    draft.update(overrides)
    return draft


# ---------------------------------------------------------------------------------------------
# Acceptance #1/#2 -- Stage 0's own schema audit, reused directly (never re-implemented locally).
# ---------------------------------------------------------------------------------------------

class SchemaAuditTests(unittest.TestCase):
    def test_shipped_schema_has_no_audit_defects(self):
        self.assertEqual(audit_schema(GENERAL_ACTION_SCHEMA), [])

    def test_every_property_description_carries_a_negative_clause(self):
        self.assertEqual(audit_descriptions(GENERAL_ACTION_SCHEMA), [])

    def test_blocked_field_is_required_and_a_string(self):
        self.assertIn(BLOCKED_FIELD, GENERAL_ACTION_SCHEMA["required"])
        self.assertEqual(GENERAL_ACTION_SCHEMA["properties"][BLOCKED_FIELD]["type"], "string")

    def test_schema_for_call_fills_the_enum_and_stays_defect_free(self):
        called = schema_for_call(["atom.a", "atom.b"])
        self.assertEqual(called["properties"]["atomFamilies"]["items"]["enum"], ["atom.a", "atom.b"])
        self.assertEqual(GENERAL_ACTION_SCHEMA["properties"]["atomFamilies"]["items"]["enum"], [],
                         "schema_for_call must never mutate the shared constant")
        self.assertEqual(audit_schema(called), [])

    # --- planted violations (spec SS4.3) -----------------------------------------------------

    def test_planted_bare_integer_field_is_a_defect(self):
        planted = copy.deepcopy(GENERAL_ACTION_SCHEMA)
        planted["properties"]["rung"] = {"type": "integer", "description": "never a number"}
        defects = audit_schema(planted)
        self.assertTrue(any(d.path == "$.rung" for d in defects))

    def test_planted_rungMilli_pattern_field_is_a_defect(self):
        planted = copy.deepcopy(GENERAL_ACTION_SCHEMA)
        planted["properties"]["rungMilli"] = {"type": "string", "pattern": "^[0-9]+$",
                                              "description": "never a bare number"}
        defects = audit_schema(planted)
        self.assertTrue(any(d.path == "$.rungMilli" and "pattern" in d.reason for d in defects))

    def test_planted_all_numeric_string_enum_is_a_defect(self):
        planted = copy.deepcopy(GENERAL_ACTION_SCHEMA)
        planted["properties"]["tierEnum"] = {"type": "string", "enum": ["1", "2", "3"],
                                             "description": "never a magnitude"}
        defects = audit_schema(planted)
        self.assertTrue(any(d.path == "$.tierEnum" for d in defects))

    def test_schema_without_blocked_property_is_a_defect(self):
        planted = copy.deepcopy(GENERAL_ACTION_SCHEMA)
        del planted["properties"][BLOCKED_FIELD]
        planted["required"] = [r for r in planted["required"] if r != BLOCKED_FIELD]
        defects = audit_schema(planted)
        self.assertTrue(any("blocked" in d.reason for d in defects))


# ---------------------------------------------------------------------------------------------
# Acceptance #4 -- the two raises. Anchor content and missing planner-owned slot fields.
# ---------------------------------------------------------------------------------------------

class NoAnchorRaiseTests(unittest.TestCase):
    def test_empty_anchor_key_does_not_raise(self):
        # A-S1's own shipped shape for every general-scope brief (measured against
        # gk-data/packs/fusion/data/seed/actions/_briefs/round-1.json): the `anchor` KEY is always present, every
        # sub-field null/empty. This must be legal, or every real brief would raise.
        build_context(make_brief(), sample_index=0)

    def test_missing_anchor_key_does_not_raise(self):
        brief = make_brief()
        del brief["anchor"]
        build_context(brief, sample_index=0)

    def test_real_anchor_content_raises(self):
        for key, value in (("family", "cherry"), ("element", "fire"), ("rarity", "cultivated"),
                          ("themeKey", "creature.cherrybomb"), ("motifs", ["fire"]),
                          ("antiMotifs", ["water"])):
            with self.subTest(key=key):
                anchor = {"family": None, "element": None, "rarity": None, "themeKey": None,
                         "motifs": [], "antiMotifs": []}
                anchor[key] = value
                brief = make_brief(anchor=anchor)
                with self.assertRaises(ValueError):
                    build_context(brief, sample_index=0)

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
        # being absent -- distribution_planner/derive.py:596 ships `kind: null` on every brief.
        build_context(make_brief(), sample_index=0)


# ---------------------------------------------------------------------------------------------
# Acceptance #3 -- what build_brief inlines, and does not.
# ---------------------------------------------------------------------------------------------

class BuildBriefContentTests(unittest.TestCase):
    def test_no_file_path_or_markdown_citation(self):
        context = build_context(make_brief(), sample_index=0)
        text = build_brief(context)
        self.assertNotIn(".md", text)
        self.assertNotIn("spec-", text)
        self.assertNotIn("/", text.replace("//", ""))  # no path-shaped tokens

    def test_no_anchor_derived_token(self):
        context = build_context(make_brief(), sample_index=0)
        text = build_brief(context).lower()
        for token in ("cherry", "fire", "cultivated", "creature.", "family:", "element:", "species:"):
            self.assertNotIn(token, text)

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
        self.assertNotIn("atom.not-eligible", text)  # not in this brief's own allowed pool

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
            {"actionId": "action.general.0001", "fingerprint": "a+b|attack|self|enemy|none"},
        ])
        context = build_context(brief, sample_index=0)
        text = build_brief(context)
        self.assertIn("Do not produce", text)
        self.assertIn("a+b|attack|self|enemy|none", text)


# ---------------------------------------------------------------------------------------------
# SMOKE BATCH criterion-2 fix, 2026-09-05: `family_glossary` renders a per-family gloss line
# instead of a bare id, closing the real ambiguity `vocab.load_family_glossary`'s own module-level
# comment names (a bare id like `atom.swiftness` gives the model nothing to judge fit by). Omitted
# or empty, output must stay byte-identical to every test above this block -- that is what every
# `BuildBriefContentTests`/`DeterminismTests` case already proves by never passing the parameter.
# ---------------------------------------------------------------------------------------------

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

    def test_family_missing_from_glossary_falls_back_to_bare_id(self):
        # Only "atom.a" is glossed; "atom.b" and "atom.c" (make_brief's other two pool members)
        # must still appear, bare, never dropped or replaced with a placeholder.
        glossary = {"atom.a": "Iron Wall [defensive] -- X more defense"}
        context = build_context(make_brief(), sample_index=0, family_glossary=glossary)
        text = build_brief(context)
        self.assertIn("atom.b", text)
        self.assertIn("atom.c", text)

    def test_glossed_rendering_still_names_the_model_id_only_instruction(self):
        context = build_context(make_brief(), sample_index=0, family_glossary={"atom.a": "Iron Wall"})
        text = build_brief(context)
        self.assertIn("answer with the id alone", text)

    def test_validators_are_unaffected_by_glossary_presence(self):
        # atom_families_are_allowed/not_forbidden read context["allowedAtomFamilies"] (ids), never
        # the glossary -- the schema enum this pipeline audits also stays ids-only (schema_for_call
        # is never given the glossary at all). This proves the glossary is prose-only.
        context = build_context(make_brief(), sample_index=0, family_glossary={"atom.a": "Iron Wall"})
        draft = make_draft(atomFamilies=["atom.a", "atom.not-eligible"])
        reasons = atom_families_are_allowed(draft, context)
        self.assertTrue(reasons)
        self.assertIn("atom.not-eligible", reasons[0])


class RealFamilyGlossaryTests(unittest.TestCase):
    """Against the real 98-family source (`gk-data/packs/fusion/data/seed/items/affix-families/*.json`), not a fixture --
    proves the real function this fix actually ships, not just the pure rendering above."""

    def test_real_glossary_covers_a_real_brief_own_allowed_pool(self):
        from seedsmith.adapters.actions.vocab import load_family_glossary

        glossary = load_family_glossary()
        doc = json.loads(REAL_BRIEFS_PATH.read_text(encoding="utf-8"))
        brief = next(e for e in doc["entries"] if e["scope"] == "general")
        allowed = brief["pool"]["allowedAtomFamilies"]
        missing = [f for f in allowed if f not in glossary]
        self.assertEqual(missing, [], "every real allowedAtomFamilies id must have a real gloss")

    def test_real_glossary_never_leaks_a_raw_template_placeholder(self):
        from seedsmith.adapters.actions.vocab import load_family_glossary

        glossary = load_family_glossary()
        leaky = {fid: g for fid, g in glossary.items() if "{" in g or "}" in g}
        self.assertEqual(leaky, {}, "no gloss may leak a raw {value}/{element}/{variant} token")

    def test_real_glossary_disambiguates_the_real_confusable_pair_from_the_smoke_batch(self):
        # The exact real-call evidence `vocab.py`'s own module comment cites: "Shift" (a general
        # repositioning action) split its vote between {swiftness, tempo-surge} (zombieSpeed --
        # lane advance) and {evasion, quickening} (dodge / attack-interval) -- three mechanically
        # unrelated things that all read as "speed" from the bare id alone. Proves the real
        # glossary actually carries the distinguishing signal, not just non-empty text.
        from seedsmith.adapters.actions.vocab import load_family_glossary

        glossary = load_family_glossary()
        self.assertIn("advance", glossary["atom.swiftness"].lower())     # zombie lane-advance speed
        self.assertIn("dodge", glossary["atom.evasion"].lower())         # combat.dodge channel
        self.assertIn("shots", glossary["atom.quickening"].lower())      # attackInterval channel


# ---------------------------------------------------------------------------------------------
# SMOKE BATCH criterion-2 PROBE, 2026-09-05: one real, previously-accepted brief->answer pair
# rendered as a worked example -- the family-glossary fix's own next-step suggestion, tried once.
# Omitted or empty, output must stay byte-identical to every test above this block -- same
# discipline `AtomFamilyGlossaryTests` above already established for `family_glossary`.
# ---------------------------------------------------------------------------------------------

class WorkedExampleTests(unittest.TestCase):
    def test_no_worked_example_is_byte_identical_to_without_it(self):
        context_without = build_context(make_brief(), sample_index=0)
        context_with_empty = build_context(make_brief(), sample_index=0, worked_example="")
        context_with_none = build_context(make_brief(), sample_index=0, worked_example=None)
        self.assertEqual(build_brief(context_without), build_brief(context_with_empty))
        self.assertEqual(build_brief(context_without), build_brief(context_with_none))

    def test_worked_example_text_is_inlined_verbatim(self):
        example_text = "EXAMPLE-MARKER: a fixed illustration string"
        context = build_context(make_brief(), sample_index=0, worked_example=example_text)
        text = build_brief(context)
        self.assertIn(example_text, text)

    def test_worked_example_is_not_permuted_by_sample_index(self):
        # the SAME already-rendered string must appear unchanged regardless of which sample this
        # call is for -- it is a fixed illustration, not a vote-scored, per-sample-permuted field
        # (unlike `allowedAtomFamilies`, which DOES change across sample_index -- see
        # DeterminismTests.test_different_sample_indices_permute_the_enum_differently below).
        example_text = "EXAMPLE-MARKER: a fixed illustration string"
        for sample_index in range(3):
            context = build_context(make_brief(), sample_index=sample_index, worked_example=example_text)
            self.assertIn(example_text, build_brief(context))

    def test_worked_example_composes_with_a_glossary_present_at_the_same_time(self):
        example_text = "EXAMPLE-MARKER"
        glossary = {"atom.a": "Iron Wall [defensive] -- X more defense"}
        context = build_context(make_brief(), sample_index=0, worked_example=example_text,
                                family_glossary=glossary)
        text = build_brief(context)
        self.assertIn(example_text, text)
        self.assertIn("atom.a: Iron Wall [defensive] -- X more defense", text)

    def test_validators_are_unaffected_by_worked_example_presence(self):
        # exactly the same proof AtomFamilyGlossaryTests gives for the glossary: the worked
        # example is prose-only and never touches what a real draft is validated against.
        context = build_context(make_brief(), sample_index=0, worked_example="EXAMPLE-MARKER")
        draft = make_draft(atomFamilies=["atom.a", "atom.not-eligible"])
        reasons = atom_families_are_allowed(draft, context)
        self.assertTrue(reasons)
        self.assertIn("atom.not-eligible", reasons[0])


class ScopeLabelTests(unittest.TestCase):
    """ST3 (`spec-scope-window-tunables.md` contract 4, spec tests 6 and 6b): the rung-band label
    keys on the brief's SCOPE. The old pair-keyed table read `.get(window, fallback)`, so retuning a
    window rendered "a tier outside the three known scope windows" into every model-calling prompt
    instead of failing -- the silent degradation this fixes."""

    FALLBACK = "outside the three known scope windows"

    def _label(self, **overrides) -> str:
        return build_context(make_brief(**overrides), sample_index=0)["rungBandLabel"]

    def test_the_label_comes_from_the_scope_not_the_window(self) -> None:
        shipped = self._label()                                   # scope general, band [1, 4]
        self.assertIn("early tier", shipped)
        self.assertNotIn(self.FALLBACK, shipped)

        # The same scope at a band a retuned window would produce must render the IDENTICAL text --
        # exactly the case the old pair-keyed table silently fell back on.
        retuned = self._label(slot={**make_brief()["slot"], "rungBand": [1, 6]})
        self.assertEqual(shipped, retuned)

    def test_an_unknown_scope_raises_rather_than_falling_back(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            self._label(scope="not-a-real-scope")
        self.assertIn("not-a-real-scope", str(ctx.exception))
        self.assertIn("EligibilityScope", str(ctx.exception))


class RealWorkedExampleTests(unittest.TestCase):
    """Against the real pinned brief/answer pair (`gk-data/packs/fusion/data/seed/actions/_briefs/round-1.json`
    briefId `brief.general.general.004`, `gk-data/packs/fusion/data/seed/actions/_fixtures/general/round-1.json`
    candidateId `candidate.general.003`), not a synthetic fixture -- proves the real function this
    probe actually ships, not just the pure rendering above. The answer is read from the tracked
    fixture because the pipeline's own `_candidates/` scratch is gitignored and absent from a fresh
    checkout (SGC5-F1); the fixture holds the pinned accepted draft verbatim."""

    def test_real_worked_example_is_genuine_non_empty_content(self):
        text = render_worked_example()
        self.assertTrue(text, "the real pinned brief/answer pair must be found in this checkout")
        self.assertIn("Worked example", text)

    def test_real_worked_example_carries_the_real_pinned_answer_fields(self):
        text = render_worked_example()
        # Re-read the current live pinned answer instead of freezing a historical model response.
        doc = json.loads(REAL_GENERAL_CANDIDATES_PATH.read_text(encoding="utf-8"))
        row = next(e for e in doc["entries"] if e["candidateId"] == "candidate.general.003")
        answer = row["draft"]
        for field in ("name", "flavor", "rationale"):
            self.assertIn(answer[field], text)
        for atom_family in answer["atomFamilies"]:
            self.assertIn(atom_family, text)

    def test_real_worked_example_never_leaks_a_numeric_magnitude(self):
        # the example is an ANSWER, and this pipeline's own binding constraint (acceptance #10:
        # "no numeric value anywhere in a candidate output") applies to the illustration too --
        # a worked example that itself broke that rule would teach the model the wrong lesson.
        import re

        text = render_worked_example()
        answer_section = text.split("Answer that was accepted for the example above:\n", 1)[1]
        answer_payload = json.loads(answer_section)
        self.assertFalse(any(isinstance(v, (int, float)) and not isinstance(v, bool)
                             for v in answer_payload.values()))
        self.assertIsNone(re.search(r"\d", answer_payload["rationale"]))

    def test_real_worked_example_is_deterministic_across_calls(self):
        self.assertEqual(render_worked_example(), render_worked_example())

    def test_real_worked_example_composes_with_the_real_family_glossary(self):
        from seedsmith.adapters.actions.vocab import load_family_glossary

        glossary = load_family_glossary()
        text = render_worked_example(glossary)
        # the example's own two real atom families must render glossed inside the example block,
        # exactly as they would on any other real call once the family-glossary fix is in effect.
        self.assertIn("atom.evd-brace:", text)
        self.assertIn("atom.sust-grit:", text)

    def test_real_pipeline_entrypoint_threads_the_worked_example_into_the_dry_run_brief(self):
        with patch("seedsmith.pipeline.llm_caller.call_model", raising_call):
            summary = gen_mod.regenerate(dry_run=True, count=1)
        self.assertIn("Worked example", summary["sampleBrief"])
        self.assertIn("Brace", summary["sampleBrief"])


# ---------------------------------------------------------------------------------------------
# Determinism / permutation (spec SS4.2).
# ---------------------------------------------------------------------------------------------

class DeterminismTests(unittest.TestCase):
    def test_same_brief_same_sample_index_is_byte_identical(self):
        brief = make_brief()
        c1 = build_context(brief, sample_index=1)
        c2 = build_context(brief, sample_index=1)
        b1 = build_brief(c1)
        b2 = build_brief(c2)
        self.assertEqual(hashlib.sha256(b1.encode()).hexdigest(), hashlib.sha256(b2.encode()).hexdigest())

    def test_enum_order_matches_order_for_exactly(self):
        brief = make_brief(pool={"allowedAtomFamilies": ["atom.c", "atom.a", "atom.b"],
                                "forbiddenAtomFamilies": []})
        context = build_context(brief, sample_index=2)
        expected = order_for(brief["briefId"], "atomFamilies", 2, sorted(["atom.a", "atom.b", "atom.c"]))
        self.assertEqual(context["allowedAtomFamilies"], list(expected))

    def test_different_sample_indices_permute_the_enum_differently(self):
        # a real 90+ family pool from A-S1's own shipped output -- practically certain to differ
        # across three independent seeds, and this is exactly what SS2 requires ("three votes over
        # three identical orders is one sample with extra steps").
        doc = json.loads(REAL_BRIEFS_PATH.read_text(encoding="utf-8"))
        brief = next(e for e in doc["entries"] if e["scope"] == "general")
        orders = [build_context(brief, sample_index=i)["allowedAtomFamilies"] for i in range(3)]
        self.assertTrue(orders[0] != orders[1] or orders[1] != orders[2])


# ---------------------------------------------------------------------------------------------
# Validators -- planted violation: an atom family outside allowedAtomFamilies.
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

    def test_verify_fn_hard_defect_names_the_offending_family_for_the_reprompt(self):
        context = build_context(make_brief(), sample_index=0)
        verify_fn = build_verify_fn(context)
        draft = make_draft(atomFamilies=["atom.rogue-family"])
        hard, soft = verify_fn(dict(context), draft)
        self.assertIn("atomFamilies", hard)
        self.assertIn("atom.rogue-family", hard["atomFamilies"])

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
        self.assertIsNone(default_for_none("name", "whatever"))


# ---------------------------------------------------------------------------------------------
# Vote resolution (spec SS2 "Which fields are voted", SS4.3's own named 1-1-1 case).
# ---------------------------------------------------------------------------------------------

class VoteResolutionTests(unittest.TestCase):
    def test_3_0_agreement_is_high_confidence_and_accepted(self):
        brief = make_brief()
        drafts = [make_draft(), make_draft(), make_draft()]
        cand = finalize_candidate(brief, drafts, candidate_id="candidate.general.000")
        self.assertEqual(cand.outcome, "accepted")
        self.assertEqual(cand.vote.confidence, "high")
        self.assertEqual(cand.entry["atomFamilies"], ["atom.a", "atom.b"])

    def test_2_1_split_records_the_minority_and_still_accepts(self):
        # Under per-member voting the minority is the MEMBER that fell below the threshold
        # (`atom.c`, chosen by one sample), not the whole losing SET. The old whole-set answer
        # here was `"atom.a|atom.c"` -- which named `atom.a` as minority even though all three
        # samples chose it, a genuinely misleading record this change fixes.
        brief = make_brief()
        drafts = [make_draft(atomFamilies=["atom.a", "atom.b"]),
                 make_draft(atomFamilies=["atom.a", "atom.b"]),
                 make_draft(atomFamilies=["atom.a", "atom.c"])]
        cand = finalize_candidate(brief, drafts, candidate_id="candidate.general.000")
        self.assertEqual(cand.outcome, "accepted")
        self.assertEqual(cand.vote.confidence, "split")
        self.assertEqual(cand.vote.minority, ("atom.c",))
        self.assertEqual(cand.entry["atomFamilies"], ["atom.a", "atom.b"])

    def test_1_1_1_split_is_unresolved_value_is_none_never_sample_zero(self):
        brief = make_brief()
        drafts = [make_draft(atomFamilies=["atom.a"]),
                 make_draft(atomFamilies=["atom.b"]),
                 make_draft(atomFamilies=["atom.c"])]
        cand = finalize_candidate(brief, drafts, candidate_id="candidate.general.000")
        self.assertEqual(cand.outcome, "unresolved")
        self.assertIsNone(cand.entry)
        self.assertIsNone(cand.vote.value)
        self.assertEqual(cand.vote.confidence, "unresolved")

    def test_THE_FIX_partial_overlap_resolves_on_the_unanimous_member_instead_of_unresolved(self):
        # The exact case the old whole-set aggregation got wrong, and the reason the real batches
        # sat at 40-55% unresolved: every sample chose `atom.a`, and they differed only on their
        # second pick. Flattened to `"a|b"` / `"a|c"` / `"a|d"` that scored 1-1-1 -> unresolved,
        # discarding a unanimous 3/3 signal. Per-member voting keeps it.
        brief = make_brief()
        drafts = [make_draft(atomFamilies=["atom.a", "atom.b"]),
                 make_draft(atomFamilies=["atom.a", "atom.c"]),
                 make_draft(atomFamilies=["atom.a", "atom.d"])]
        cand = finalize_candidate(brief, drafts, candidate_id="candidate.general.000")
        self.assertEqual(cand.outcome, "accepted")
        self.assertEqual(cand.entry["atomFamilies"], ["atom.a"])
        self.assertEqual(cand.vote.confidence, "split")
        self.assertEqual(cand.vote.minority, ("atom.b", "atom.c", "atom.d"))

    def test_a_member_chosen_by_only_one_sample_never_enters_the_resolved_set(self):
        # The binding "never sample 0's raw pick" rule, restated per-member: two independent
        # samples are required, so a lone pick can never ride along on another member's majority.
        brief = make_brief()
        drafts = [make_draft(atomFamilies=["atom.a", "atom.solo"]),
                 make_draft(atomFamilies=["atom.a", "atom.b"]),
                 make_draft(atomFamilies=["atom.a", "atom.b"])]
        cand = finalize_candidate(brief, drafts, candidate_id="candidate.general.000")
        self.assertEqual(cand.entry["atomFamilies"], ["atom.a", "atom.b"])
        self.assertNotIn("atom.solo", cand.entry["atomFamilies"])

    def test_fully_disjoint_picks_are_still_unresolved(self):
        # The negative control: per-member voting must NOT rescue a genuine three-way
        # disagreement. No member reaches two samples, so the resolved set is empty.
        brief = make_brief()
        drafts = [make_draft(atomFamilies=["atom.a", "atom.b"]),
                 make_draft(atomFamilies=["atom.c", "atom.d"]),
                 make_draft(atomFamilies=["atom.e", "atom.f"])]
        cand = finalize_candidate(brief, drafts, candidate_id="candidate.general.000")
        self.assertEqual(cand.outcome, "unresolved")
        self.assertIsNone(cand.entry)
        self.assertIsNone(cand.vote.value)

    def test_sample_picks_are_recorded_for_every_outcome_including_unresolved(self):
        # The observability gap this fix also closes: an unresolved row used to persist
        # `draft: null` and nothing else, so nobody could see how close the samples actually were.
        brief = make_brief()
        drafts = [make_draft(atomFamilies=["atom.a"]),
                 make_draft(atomFamilies=["atom.b"]),
                 make_draft(atomFamilies=["atom.c"])]
        cand = finalize_candidate(brief, drafts, candidate_id="candidate.general.000")
        self.assertEqual(cand.outcome, "unresolved")
        self.assertEqual(cand.provenance["samplePicks"],
                         [["atom.a"], ["atom.b"], ["atom.c"]])

    def test_atom_family_order_within_a_pick_does_not_create_a_false_split(self):
        brief = make_brief()
        drafts = [make_draft(atomFamilies=["atom.a", "atom.b"]),
                 make_draft(atomFamilies=["atom.b", "atom.a"]),
                 make_draft(atomFamilies=["atom.a", "atom.b"])]
        cand = finalize_candidate(brief, drafts, candidate_id="candidate.general.000")
        self.assertEqual(cand.vote.confidence, "high")

    def test_a_sample_that_never_produced_a_usable_pick_still_casts_its_own_vote(self):
        # a heal-exhausted sample's atomFamilies is None (F9's default_for_none) -- it must count
        # as its OWN distinct vote, never silently drop out of the three-way count.
        brief = make_brief()
        drafts = [make_draft(atomFamilies=["atom.a", "atom.b"]),
                 make_draft(atomFamilies=["atom.a", "atom.b"]),
                 make_draft(atomFamilies=None)]
        cand = finalize_candidate(brief, drafts, candidate_id="candidate.general.000")
        self.assertEqual(cand.outcome, "accepted")
        self.assertEqual(cand.vote.confidence, "split")

    def test_blocked_sample_zero_short_circuits_before_any_vote(self):
        brief = make_brief()
        drafts = [make_draft(**{BLOCKED_FIELD: "brief has nothing to work from"}),
                 make_draft(), make_draft()]
        cand = finalize_candidate(brief, drafts, candidate_id="candidate.general.000")
        self.assertEqual(cand.outcome, "blocked")
        self.assertIsNone(cand.entry)
        self.assertIsNone(cand.vote)

    def test_finalize_candidate_requires_exactly_three_drafts(self):
        with self.assertRaises(ValueError):
            finalize_candidate(make_brief(), [make_draft(), make_draft()], candidate_id="x")


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
# deterministic vote/hash logic twice -- byte-identical candidate output both times, canonical
# serialisation included. Never a live call.
# ---------------------------------------------------------------------------------------------

class RecordedTranscriptReplayTests(unittest.TestCase):
    RECORDED_SAMPLES = [
        {"name": "Bulwark Stance", "flavor": "Weight settles into the ground like a promise.",
         "atomFamilies": ["atom.a", "atom.b"],
         "rationale": "Combines a defensive family with a utility one for a steady role.",
         BLOCKED_FIELD: ""},
        {"name": "Steadfast Guard", "flavor": "Nothing moves it once it plants its feet.",
         "atomFamilies": ["atom.b", "atom.a"],
         "rationale": "The two families reinforce a single defensive posture.",
         BLOCKED_FIELD: ""},
        {"name": "Iron Wall", "flavor": "A line that does not break.",
         "atomFamilies": ["atom.a", "atom.b"],
         "rationale": "Anchors the role in raw endurance.",
         BLOCKED_FIELD: ""},
    ]

    def _replay(self) -> str:
        brief = make_brief()
        cand = finalize_candidate(brief, [dict(d) for d in self.RECORDED_SAMPLES],
                                  candidate_id="candidate.general.000",
                                  provenance={"pipeline": "general-propose", "model": "recorded"})
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

    def test_replay_resolves_to_the_voted_majority_pick(self):
        row = json.loads(self._replay())["entries"][0]
        self.assertEqual(row["outcome"], "accepted")
        self.assertEqual(row["confidence"], "high")
        self.assertEqual(row["draft"]["atomFamilies"], ["atom.a", "atom.b"])


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
            self.assertEqual(audit_schema(GENERAL_ACTION_SCHEMA), [])
            cand = finalize_candidate(brief, [make_draft(), make_draft(), make_draft()],
                                      candidate_id="candidate.general.000")
            self.assertEqual(cand.outcome, "accepted")

    def test_entry_for_never_reaches_the_model(self):
        with patch("seedsmith.pipeline.llm_caller.call_model", raising_call):
            entry = entry_for(make_draft(), candidate_id="candidate.general.000",
                              brief_id="brief.general.general.001")
            self.assertEqual(entry["name"], "Iron Resolve")


# ---------------------------------------------------------------------------------------------
# Acceptance #6 -- `--dry-run` / `--count`, against real A-S1 output.
# ---------------------------------------------------------------------------------------------

class DryRunEntrypointTests(unittest.TestCase):
    def test_dry_run_makes_zero_calls_and_renders_a_sample_brief(self):
        with patch("seedsmith.pipeline.llm_caller.call_model", raising_call):
            summary = gen_mod.regenerate(dry_run=True, count=2)
        self.assertTrue(summary["dryRun"])
        self.assertEqual(summary["modelCalls"], 0)
        self.assertGreater(summary["totalGeneralBriefs"], 0)
        self.assertEqual(summary["selected"], 2)
        self.assertIn("Design ONE general action", summary["sampleBrief"])

    def test_count_bounds_the_selection(self):
        with patch("seedsmith.pipeline.llm_caller.call_model", raising_call):
            summary = gen_mod.regenerate(dry_run=True, count=1)
        self.assertEqual(summary["selected"], 1)

    def test_load_general_briefs_reads_only_general_scope_sorted(self):
        briefs = gen_mod.load_general_briefs()
        self.assertTrue(all(b["scope"] == "general" for b in briefs))
        self.assertEqual([b["briefId"] for b in briefs], sorted(b["briefId"] for b in briefs))

    def test_brief_hash_is_deterministic_and_brief_specific(self):
        b1 = make_brief()
        b2 = make_brief()
        self.assertEqual(gen_mod._brief_hash(b1), gen_mod._brief_hash(b2))
        b3 = make_brief(briefId="brief.general.general.002")
        self.assertNotEqual(gen_mod._brief_hash(b1), gen_mod._brief_hash(b3))

    def test_real_run_writes_provenance_with_model_prompt_version_brief_hash_and_candidate_set_hash(self):
        def fake_propose(brief, *, candidate_id, pairing_table=None, family_glossary=None,
                        worked_example=None, config=None, provenance=None):
            return Candidate(
                brief_id=brief["briefId"], outcome="accepted",
                entry=entry_for(make_draft(), candidate_id=candidate_id, brief_id=brief["briefId"],
                               provenance=provenance),
                vote=SetVoteResult(values=("atom.a", "atom.b"), confidence="high",
                                   minority=(), tally={"atom.a": 3, "atom.b": 3}),
                provenance=dict(provenance or {}),
            )

        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp) / "_candidates" / "general"
            with patch("seedsmith.adapters.actions.generate_general_actions.propose_general_action",
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

            # rerun over unchanged inputs is byte-identical (acceptance #8)
            out_dir2 = Path(tmp) / "_candidates2" / "general"
            with patch("seedsmith.adapters.actions.generate_general_actions.propose_general_action",
                      fake_propose):
                gen_mod.regenerate(dry_run=False, count=1, candidates_dir=out_dir2,
                                   config=LlmCallerConfig(model="test-model-x"))
            self.assertEqual((out_dir / "round-1.json").read_text(encoding="utf-8"),
                             (out_dir2 / "round-1.json").read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------------------------
# Acceptance #9 -- repairs bounded at two, explicit, and default_for=None (F9).
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

        with patch("seedsmith.adapters.actions.general_propose.derive.call_with_self_heal",
                  fake_call_with_self_heal):
            from seedsmith.adapters.actions.general_propose.derive import sample_draft
            sample_draft(make_brief(), sample_index=0)

        self.assertEqual(captured["max_heal"], 2)
        self.assertIs(captured["default_for"], default_for_none)


# ---------------------------------------------------------------------------------------------
# Acceptance #10 -- no numeric value anywhere in a candidate row.
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
                                  candidate_id="candidate.general.000",
                                  provenance={"pipeline": "general-propose", "model": "x"})
        row = candidate_row(cand)
        _walk_no_numbers(row)


# ---------------------------------------------------------------------------------------------
# Candidate-set hashing (mirrors acceptance #8's "candidate-set hash").
# ---------------------------------------------------------------------------------------------

class CandidateSetHashTests(unittest.TestCase):
    def test_hash_is_order_independent_of_input_ordering(self):
        brief = make_brief()
        cand = finalize_candidate(brief, [make_draft(), make_draft(), make_draft()],
                                  candidate_id="candidate.general.000")
        row = candidate_row(cand)
        row2 = dict(row)
        h1 = candidate_set_hash([row, row2])
        h2 = candidate_set_hash([row2, row])
        self.assertEqual(h1, h2)

    def test_hash_changes_when_a_row_changes(self):
        brief = make_brief()
        cand = finalize_candidate(brief, [make_draft(), make_draft(), make_draft()],
                                  candidate_id="candidate.general.000")
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


if __name__ == "__main__":
    unittest.main()
