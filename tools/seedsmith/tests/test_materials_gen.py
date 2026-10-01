"""Tests for `seedsmith.adapters.items.materialgen` (item module 3, `materials-gen`,
docs/architecture/item-seedgen/spec-materials-gen.md).

    python -m pytest gk-forge/tools/seedsmith/tests/test_materials_gen.py -v

⭐ **`VocabTests` is the spec's own #1 boundary.** Acceptance #2 requires confirming a target id is a
real member of the closed vocabulary BEFORE generating — refusing rather than authoring for an id
that doesn't exist mechanically. `test_a_fabricated_id_is_refused_loudly` and
`test_a_legacy_shard_id_is_known_but_refused_as_a_generation_target` are that requirement, proven
directly against `vocab.require_issuable` — the one gate every other module in this package calls
before it does anything with an id.
"""
from __future__ import annotations

import json
import re
import sys
import tempfile
import unittest
import unittest.mock
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from seedsmith.adapters.items.materialgen import brief as brief_mod  # noqa: E402
from seedsmith.adapters.items.materialgen import emit  # noqa: E402
from seedsmith.adapters.items.materialgen import run as run_mod  # noqa: E402
from seedsmith.adapters.items.materialgen import schema as schema_mod  # noqa: E402
from seedsmith.adapters.items.materialgen import vocab  # noqa: E402
from seedsmith.pipeline.run_ledger import RunLedger  # noqa: E402

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

REAL_MATERIALS_PATH = _owned("data/seed/items/materials/materials.json")


def _clean_answer(**overrides) -> dict:
    draft = {"name": "Proof Shard", "flavor": "A fixture, and it says so, in one full sentence.",
             "tags": ["mineral"]}
    draft.update(overrides)
    return draft


class VocabTests(unittest.TestCase):
    """The issuable vocabulary: a closed, 27-id core (five classes, mirrored from
    `MaterialCatalog.cs`) plus the open trophy population (species-gear-chain T34)."""

    def test_the_closed_core_is_exactly_27_ids_in_class_order(self) -> None:
        """The five closed classes are the FIRST 27 entries of `ISSUABLE`, in `MaterialCatalog.Build()`
        order — a real closed-vocabulary count, correctly pinned. `ISSUABLE` as a WHOLE is not pinned
        (see `test_trophy_ids_extend_issuable_and_stay_a_reading` below): its total is a population
        that grows with the committed trophy registry, never a literal here."""
        # The count (27) is fully implied by the element-wise equality below -- never pinned
        # separately (population-pin, mega-merge conflict resolution 2026-09-20).
        closed_core = vocab.ISSUABLE[:vocab._EXPECTED_CLOSED_CLASS_COUNT]
        classes = [m.material_class for m in closed_core]
        self.assertEqual(classes, ["shard"] * 10 + ["substrate"] * 8 + ["essence"] * 6 + ["catalyst"] * 3)

    def test_trophy_ids_extend_issuable_and_stay_a_reading(self) -> None:
        """Reconciliation, never a population count (`validation-ssot.md`): `ISSUABLE`'s total is
        exactly the closed core plus however many rows the committed trophy registry holds today,
        plus the seventh class's own closed three (species-gear-chain T40) -- the trophy count is
        never a literal pinned here; the assurance count IS (it is a real closed vocabulary, not a
        population)."""
        trophy_ids = [m for m in vocab.ISSUABLE if m.material_class == "trophy"]
        assurance_ids = [m for m in vocab.ISSUABLE if m.material_class == "assurance"]
        self.assertEqual(len(assurance_ids), 3)
        self.assertEqual(
            len(vocab.ISSUABLE),
            vocab._EXPECTED_CLOSED_CLASS_COUNT + len(trophy_ids) + len(assurance_ids))
        self.assertGreater(len(trophy_ids), 0, "the trophy registry should be non-empty in this checkout")
        self.assertTrue(all(m.scope in ("species", "family") for m in trophy_ids))
        self.assertEqual(len(trophy_ids), len({m.runtime_id for m in trophy_ids}), "duplicate trophy id")

    def test_shard_ids_follow_the_rarity_ladder_in_rank_order(self) -> None:
        shard_ids = [m.runtime_id for m in vocab.ISSUABLE if m.material_class == "shard"]
        self.assertEqual(shard_ids, [f"shard.{r}" for r in vocab.RARITY_RUNGS])
        self.assertEqual(shard_ids[0], "shard.chaff")   # weakest rung, ordinal 0
        self.assertEqual(shard_ids[-1], "shard.almanac")  # strongest rung, ordinal 9

    def test_substrate_ids_are_frame_outer_grade_inner(self) -> None:
        substrate_ids = [m.runtime_id for m in vocab.ISSUABLE if m.material_class == "substrate"]
        self.assertEqual(substrate_ids, [
            "substrate.humanoid.crude", "substrate.humanoid.sound",
            "substrate.humanoid.fine", "substrate.humanoid.prime",
            "substrate.plant.crude", "substrate.plant.sound",
            "substrate.plant.fine", "substrate.plant.prime",
        ])

    def test_essence_ids_exclude_omni(self) -> None:
        essence_ids = [m.runtime_id for m in vocab.ISSUABLE if m.material_class == "essence"]
        self.assertEqual(essence_ids, [f"essence.{e}" for e in vocab.ELEMENTS])
        self.assertNotIn("essence.omni", essence_ids)

    def test_a_fabricated_id_is_refused_loudly(self) -> None:
        """THE refusal test. A material id outside the 27-id closed vocabulary must never reach
        content authoring — it fails loudly, never silently inventing a new material kind."""
        for bad_id in ("shard.mythic", "essence.omni", "substrate.humanoid.masterwork",
                      "catalyst.dissolve", "material.made-up", "essence.fire.pvz", ""):
            with self.subTest(bad_id=bad_id):
                self.assertFalse(vocab.is_issuable(bad_id))
                with self.assertRaises(vocab.MaterialVocabularyRejection):
                    vocab.require_issuable(bad_id)

    def test_a_legacy_shard_id_is_known_but_refused_as_a_generation_target(self) -> None:
        """The four retired bands resolve (a saved reference does not hard-fail) but are NOT
        issuable, and `require_issuable` — the generator's own gate — refuses all four with a
        message distinct from "not a real id at all"."""
        for legacy_id in ("shard.common", "shard.rare", "shard.epic", "shard.legendary"):
            with self.subTest(legacy_id=legacy_id):
                self.assertTrue(vocab.is_known(legacy_id))
                self.assertFalse(vocab.is_issuable(legacy_id))
                with self.assertRaises(vocab.MaterialVocabularyRejection) as caught:
                    vocab.require_issuable(legacy_id)
                self.assertIn("legacy", str(caught.exception))

    def test_the_real_shipped_corpus_now_carries_every_rarity_ladder_shard_rung(self) -> None:
        """Read-only sanity check against the REAL, committed corpus (never written to by this
        test): the gap this generator exists to close is now CLOSED for the closed 27-id core —
        `materials-gen` authored the ten missing `shard.{rung}` rows (material.022-031,
        `_meta.amendments[0]`, 2026-09-07) — so `missing_from`, restricted to that core, reports
        nothing left. The four legacy shard-band ids (material.007-010) are untouched and still do
        not carry any of the ten rung ids, which is what keeps this a re-author rather than a
        rewrite of the legacy rows.

        **The trophy population is a separate, DELIBERATELY open gap here** (species-gear-chain
        T34): the planner mints ids, but authoring their name/flavor/tags is materialgen's own
        ONGOING generation work (a live-model run, out of scope for this offline test) — so this
        test never asserts the trophy portion of `missing_from` is empty; that would require this
        test suite to have spent a real model call, which it never does.

        **The assurance class is the identical, separate gap** (species-gear-chain T40): its three
        ids are real and closed the moment `vocab.py`/`CostClassMatrix.cs` ship, but authoring their
        own name/flavor/tags is the SAME live-model content pass as the trophy rows above, not
        something this offline test (or T40's own code change) does for them. T40's implementer
        scope is the mechanism (vocabulary, brief sentence, schema) that lets that run succeed once
        made; the real `materials.json` rows are the batch's own deliverable, not this commit's."""
        doc = json.loads(REAL_MATERIALS_PATH.read_text(encoding="utf-8"))
        existing_runtime_ids = {e["runtimeId"] for e in doc["entries"] if "runtimeId" in e}
        missing_closed_core = {
            m.runtime_id for m in vocab.missing_from(frozenset(existing_runtime_ids))
            if m.material_class not in ("trophy", "assurance")}
        self.assertEqual(missing_closed_core, set())
        for rung in vocab.RARITY_RUNGS:
            self.assertIn(f"shard.{rung}", existing_runtime_ids)


class SchemaTests(unittest.TestCase):
    def test_a_clean_answer_has_no_schema_defects(self) -> None:
        from seedsmith.adapters.items.setgen.answers import schema_defects
        self.assertEqual(schema_defects(_clean_answer(), schema_mod.material_schema()), [])

    def test_each_closed_keyword_is_enforced(self) -> None:
        from seedsmith.adapters.items.setgen.answers import schema_defects
        schema = schema_mod.material_schema()
        cases = {
            "unknown field": ({**_clean_answer(), "runtimeId": "shard.chaff"}, "unknown field"),
            "tag outside the pool": ({**_clean_answer(), "tags": ["not-a-real-tag"]}, "is not one of"),
            "short name": ({**_clean_answer(), "name": "x"}, "below the minimum"),
            "too many tags": ({**_clean_answer(),
                              "tags": ["mineral", "metal", "organic", "arcane", "necrotic"]},
                             "above the maximum"),
        }
        for label, (draft, needle) in cases.items():
            with self.subTest(label):
                found = schema_defects(draft, schema)
                self.assertTrue(any(needle in d for d in found), f"{label}: {found}")

    def test_two_tags_on_one_exclusive_axis_is_a_violation(self) -> None:
        violations = schema_mod.tag_axis_violations(["light", "heavy"])  # both mass-class
        self.assertTrue(violations, "light/heavy are both mass-class, which tags.v1.json marks exclusive")

    def test_tags_from_different_axes_are_legal_together(self) -> None:
        # "metal" (material-nature) + "light" (mass-class) + "sturdy" (durability-class) — the real
        # combination shipped materials.json's own substrate-humanoid-crude entry uses two of.
        self.assertEqual(schema_mod.tag_axis_violations(["metal", "light", "sturdy"]), [])

    def test_material_is_a_legal_appliesto_for_every_axis_this_module_offers(self) -> None:
        axes = schema_mod.material_tag_axes()
        self.assertIn("mass-class", axes)
        self.assertIn("material-nature", axes)
        self.assertGreater(len(schema_mod.material_tags()), 0)

    def test_trophy_ids_share_the_same_schema_and_it_stays_audit_schema_clean(self) -> None:
        """T34 acceptance: `materialgen` names the new trophy ids with `audit_schema` clean — the
        schema is class-agnostic (name/flavor/tags/blocked, `schema.py`'s own module docstring), so
        adding trophy ids to `ISSUABLE` needed no schema change; this pins that fact so a future
        per-class schema split does not silently reintroduce a model-written number for trophy."""
        from seedsmith.pipeline.model import audit_schema
        trophy = next(m for m in vocab.ISSUABLE if m.material_class == "trophy")
        self.assertEqual(audit_schema(schema_mod.material_schema()), [])
        self.assertTrue(vocab.is_issuable(trophy.runtime_id))


class BriefTests(unittest.TestCase):
    def test_the_brief_never_shows_a_number(self) -> None:
        material = vocab.require_issuable("shard.chaff")
        text = brief_mod.build_material_brief(material)
        self.assertIn("shard.chaff", text)
        self.assertIn("Never invent a tag", text)

    def test_a_substrate_brief_names_its_frame_and_grade(self) -> None:
        material = vocab.require_issuable("substrate.plant.fine")
        text = brief_mod.build_material_brief(material)
        self.assertIn("plant", text)
        self.assertIn("grade 3 of 4", text)

    def test_a_trophy_brief_names_its_scope_and_carries_no_magnitude(self) -> None:
        species_trophy = next(m for m in vocab.ISSUABLE
                              if m.material_class == "trophy" and m.scope == "species")
        family_trophy = next(m for m in vocab.ISSUABLE
                             if m.material_class == "trophy" and m.scope == "family")
        species_text = brief_mod.build_material_brief(species_trophy)
        family_text = brief_mod.build_material_brief(family_trophy)
        self.assertIn(species_trophy.scope_key, species_text)
        self.assertIn(family_trophy.scope_key, family_text)
        self.assertIn("TROPHY", species_text)
        self.assertIn("provenance", species_text)
        self.assertIn("Never invent a tag", species_text)

    def test_a_trophy_brief_tells_the_model_its_name_must_differ_from_its_siblings(self) -> None:
        """The trophy class is the one class whose brief never mentions its siblings, and it is the
        largest class by an order of magnitude: `trophyplan` mints one id per species slot, so 3,602
        trophies are drawn from a few hundred species.

        Measured on a full run's corpus: **747 `SemanticDedup/NearDuplicate` findings, every one of them
        a name used verbatim by 2 to 35 entries** ('Ancestral Echo' by 35). Nothing in the old trophy
        brief could have prevented that — the model was asked for an evocative name, handed a species key
        and a slot number, and told nothing about the 3,601 other names. The SUBSTRATE branch of
        `_identity_sentence` already carries the anti-repetition clause its own 8 members need
        (*"should read as a step up from the grade below it, not a repeat of it"*), so the wording to copy
        is in this same function, three branches up.
        """
        trophy = next(m for m in vocab.ISSUABLE if m.material_class == "trophy")
        text = brief_mod.build_material_brief(trophy)
        lowered = text.lower()
        # Asserted as the REQUIREMENT, not as a predicted phrasing: the brief must name its sibling class
        # AND forbid the repetition. Asserting an exact sentence here would only pin today's wording —
        # and an over-specific assertion is how a test ends up defending a phrasing instead of a rule.
        # Both fragments are absent from the pre-fix trophy brief, so this still reproduces the defect.
        self.assertIn(f"other {trophy.material_class}", lowered,
                      "the trophy brief must name the siblings the name has to differ from")
        self.assertIn("must not repeat", lowered,
                      "the trophy brief must forbid the repetition the substrate branch already forbids")

    def test_the_anti_repetition_clause_reaches_every_class_that_has_siblings(self) -> None:
        """Guards the fix against being narrowed back to trophies only. `shard` (10 rungs) and
        `substrate` (8) are the other two classes whose members are siblings of one another, and
        `substrate` already had the clause — so this asserts the property per class rather than
        asserting one string, which is what let the gap exist beside a correct sibling branch."""
        by_class: "dict[str, list]" = {}
        for material in vocab.ISSUABLE:
            by_class.setdefault(material.material_class, []).append(material)
        for cls in ("shard", "substrate", "trophy"):
            members = by_class[cls]
            self.assertGreater(len(members), 1, f"{cls} is expected to be a sibling class")
            with self.subTest(cls=cls):
                text = brief_mod.build_material_brief(members[0]).lower()
                self.assertTrue("not a repeat" in text or "must not repeat" in text,
                                f"the {cls} brief ({len(members)} siblings) carries no anti-repetition "
                                f"clause, so a full run can populate it with colliding names")


class EmitTests(unittest.TestCase):
    """`nameKey`/`iconKey` cross-checked against the REAL shipped corpus's own entries (read-only) —
    not merely against a rule this test invented independently of the data."""

    def test_derivation_matches_every_real_shipped_entry(self) -> None:
        """⛔ The population pin at the end of this test was itself a defect, fixed 2026-09-28.

        It asserted `checked == 31` with the message *"the real corpus has 31 entries today; a changed count
        means this cross-check is running against fewer rows than it should"*. On this repo's own rule
        (`docs/architecture/validation-ssot.md`) a guardrail validates the CONTRACT and closed enums, never
        a population count — a test that pins a count fails whenever content ships, and its only "fix" is to
        bump the number. It failed the moment a re-emit grew the corpus past 31, which is the normal case.

        Worse, the message was written for SHRINKAGE while the real cause was GROWTH, so the failure text
        actively pointed the reader at the wrong diagnosis.

        **But it cannot simply be deleted.** The loop `continue`s on any row without a `runtimeId`, so a
        corpus that was empty — or one where every row lost its `runtimeId` — would leave `checked == 0` and
        this test would pass having verified nothing. The replacement therefore asserts the CONTRACT three
        ways instead of a count:

          * **closure** — `checked == len(entries)`: every shipped row was actually cross-checked, so no row
            is silently skipped;
          * **non-vacuity** — the corpus is not empty and rows were really examined;
          * a **floor**, not an exact count, using the 21 hand-authored rows the original comment
            documented, so an accidental truncation is still caught while shipping more content is not a
            failure.
        """
        doc = json.loads(REAL_MATERIALS_PATH.read_text(encoding="utf-8"))
        entries = doc["entries"]
        checked = 0
        for entry in entries:
            runtime_id = entry.get("runtimeId")
            if not runtime_id:
                self.fail(f"{entry.get('id')!r} has no runtimeId, so this cross-check would skip it "
                          f"silently - every shipped row must be derivable from its runtimeId")
            self.assertEqual(emit.derive_name_key(runtime_id), entry["nameKey"],
                             f"nameKey drifted for {runtime_id}")
            self.assertEqual(emit.derive_icon_key(runtime_id), entry["iconKey"],
                             f"iconKey drifted for {runtime_id}")
            checked += 1
        self.assertEqual(checked, len(entries),
                         "every shipped row must be cross-checked, or this test is not checking the corpus")
        # 21 original rows + the 10 shard.{rung} rows materials-gen authored 2026-09-07 (material.022-031)
        # to close the rarity-ladder gap, and more since. A FLOOR, so growth is not a failure: 21 is the
        # hand-authored baseline the original comment recorded, and anything below it means rows vanished.
        self.assertGreaterEqual(checked, 21,
                                "fewer than the 21 hand-authored rows are present - rows have been lost, "
                                "which is the one direction this test should still fail on")

    def test_next_seq_resumes_from_the_highest_existing_id(self) -> None:
        self.assertEqual(emit.next_seq([]), 1)
        self.assertEqual(emit.next_seq([{"id": "material.001"}, {"id": "material.021"}]), 22)
        # A hole in the middle never gets backfilled with a duplicate — highest, not count.
        self.assertEqual(emit.next_seq([{"id": "material.001"}, {"id": "material.099"}]), 100)

    def test_build_entry_omits_class_fields_the_id_does_not_carry(self) -> None:
        shard = vocab.require_issuable("shard.chaff")
        entry = emit.build_entry(shard, _clean_answer(), seq=22)
        self.assertNotIn("element", entry)
        self.assertNotIn("frame", entry)
        self.assertNotIn("grade", entry)
        self.assertEqual(entry["runtimeId"], "shard.chaff")
        self.assertEqual(entry["materialClass"], "shard")
        self.assertEqual(entry["id"], "material.022")
        self.assertNotIn("scope", entry)
        self.assertNotIn("scopeKey", entry)
        self.assertNotIn("slot", entry)

    def test_build_entry_carries_scope_scopekey_slot_for_a_trophy_id(self) -> None:
        trophy = next(m for m in vocab.ISSUABLE if m.material_class == "trophy")
        entry = emit.build_entry(trophy, _clean_answer(), seq=32)
        self.assertEqual(entry["scope"], trophy.scope)
        self.assertEqual(entry["scopeKey"], trophy.scope_key)
        self.assertEqual(entry["slot"], trophy.slot)
        self.assertNotIn("element", entry)
        self.assertNotIn("frame", entry)
        self.assertNotIn("grade", entry)


class RunPlanAndBatchTests(unittest.TestCase):
    """Harness integration: resume, reconcile, and the explicit overwrite path — the same discipline
    `run_ledger.py` itself was built to generalize from `setgen`."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        tmp = Path(self._tmp.name)
        self.materials_path = tmp / "materials.json"
        self.ledger = RunLedger(tmp / "materials-gen.ledger.json")

    def _seed_corpus(self, entries: "list[dict]") -> None:
        self.materials_path.write_text(
            json.dumps({"schemaVersion": 1, "kind": "material", "entries": entries}), encoding="utf-8")

    def test_a_generated_entry_for_a_real_id_persists_and_is_schema_clean(self) -> None:
        self._seed_corpus([])
        plan = run_mod.plan_run(materials_path=self.materials_path, ledger=self.ledger)
        subject_ids = {s.subject_id for s in plan.subjects}
        self.assertIn("shard.chaff", subject_ids, "shard.chaff is real and missing — it must be planned")

        result = run_mod.run_batch(
            plan, {"shard.chaff": _clean_answer(name="Chaff Fragment")},
            materials_path=self.materials_path, ledger=self.ledger)
        self.assertEqual(result.persisted, ("shard.chaff",))
        doc = json.loads(self.materials_path.read_text(encoding="utf-8"))
        entry = next(e for e in doc["entries"] if e["runtimeId"] == "shard.chaff")
        self.assertEqual(entry["name"], "Chaff Fragment")
        self.assertEqual(entry["nameKey"], "material.shard-chaff")
        self.assertEqual(entry["iconKey"], "icon.material.shard-chaff")
        self.assertEqual(entry["materialClass"], "shard")
        self.assertEqual(entry["tags"], ["mineral"])
        self.assertTrue(self.ledger.path.exists())
        self.assertIn("shard.chaff", self.ledger.read_done())

    def test_resume_does_not_replan_an_already_generated_id(self) -> None:
        self._seed_corpus([])
        plan = run_mod.plan_run(materials_path=self.materials_path, ledger=self.ledger)
        run_mod.run_batch(plan, {"shard.chaff": _clean_answer()},
                          materials_path=self.materials_path, ledger=self.ledger)

        resumed = run_mod.plan_run(materials_path=self.materials_path, ledger=self.ledger)
        self.assertNotIn("shard.chaff", {s.subject_id for s in resumed.subjects})

    def test_reconcile_replans_a_hand_deleted_row(self) -> None:
        self._seed_corpus([])
        plan = run_mod.plan_run(materials_path=self.materials_path, ledger=self.ledger)
        run_mod.run_batch(plan, {"shard.chaff": _clean_answer()},
                          materials_path=self.materials_path, ledger=self.ledger)

        # Simulate an out-of-band hand edit that removes the generated row, but the ledger still
        # claims the subject done.
        doc = json.loads(self.materials_path.read_text(encoding="utf-8"))
        doc["entries"] = [e for e in doc["entries"] if e["runtimeId"] != "shard.chaff"]
        self.materials_path.write_text(json.dumps(doc), encoding="utf-8")

        reconciled = run_mod.plan_run(materials_path=self.materials_path, ledger=self.ledger)
        self.assertIn("shard.chaff", {s.subject_id for s in reconciled.subjects},
                      "a ledger-managed row missing from the corpus must be replanned, not skipped")

    def test_hand_authored_content_with_no_ledger_row_is_never_touched(self) -> None:
        """The 17 issuable ids the real corpus already carries hand-authored content for (essence,
        substrate, catalyst) must never be silently regenerated just because this generator now
        exists."""
        self._seed_corpus([{"id": "material.001", "nameKey": "material.essence-fire",
                            "name": "Hand-Authored Ember", "runtimeId": "essence.fire",
                            "materialClass": "essence", "element": "fire",
                            "iconKey": "icon.material.essence-fire", "tags": ["arcane"]}])
        plan = run_mod.plan_run(materials_path=self.materials_path, ledger=self.ledger)
        self.assertNotIn("essence.fire", {s.subject_id for s in plan.subjects})

    def test_overwrite_forces_regeneration_of_an_existing_hand_authored_row(self) -> None:
        self._seed_corpus([{"id": "material.001", "nameKey": "material.essence-fire",
                            "name": "Hand-Authored Ember", "runtimeId": "essence.fire",
                            "materialClass": "essence", "element": "fire",
                            "iconKey": "icon.material.essence-fire", "tags": ["arcane"]}])
        # Never planned by the ordinary resume path...
        ordinary = run_mod.plan_run(materials_path=self.materials_path, ledger=self.ledger)
        self.assertNotIn("essence.fire", {s.subject_id for s in ordinary.subjects})

        # ...but an explicit --overwrite reaches it, and replaces the SAME row (same `id`) in place.
        forced = run_mod.plan_overwrite(["essence.fire"], ledger=self.ledger)
        self.assertEqual([s.subject_id for s in forced.subjects], ["essence.fire"])
        result = run_mod.run_batch(
            forced, {"essence.fire": _clean_answer(name="Reforged Ember", tags=["arcane"])},
            materials_path=self.materials_path, ledger=self.ledger)
        self.assertEqual(result.persisted, ("essence.fire",))
        doc = json.loads(self.materials_path.read_text(encoding="utf-8"))
        self.assertEqual(len(doc["entries"]), 1, "overwrite replaces the row, it does not duplicate it")
        self.assertEqual(doc["entries"][0]["id"], "material.001")
        self.assertEqual(doc["entries"][0]["name"], "Reforged Ember")

    def test_overwrite_refuses_a_fabricated_id(self) -> None:
        with self.assertRaises(vocab.MaterialVocabularyRejection):
            run_mod.plan_overwrite(["shard.mythic"], ledger=self.ledger)

    def test_overwrite_refuses_an_empty_scope_rather_than_defaulting_to_all(self) -> None:
        with self.assertRaises(ValueError):
            run_mod.plan_overwrite([], ledger=self.ledger)

    def test_a_blocked_answer_persists_nothing(self) -> None:
        self._seed_corpus([])
        plan = run_mod.plan_run(materials_path=self.materials_path, ledger=self.ledger)
        result = run_mod.run_batch(plan, {"shard.chaff": {"blocked": "no motif lands cleanly"}},
                                   materials_path=self.materials_path, ledger=self.ledger)
        outcome = next(o for o in result.outcomes if o.subject_id == "shard.chaff")
        self.assertEqual(outcome.outcome, "blocked")
        self.assertEqual(result.persisted, ())
        self.assertFalse(self.materials_path.exists() and
                         json.loads(self.materials_path.read_text(encoding="utf-8"))["entries"])

    def test_a_missing_answer_is_reported_not_silently_skipped(self) -> None:
        self._seed_corpus([])
        plan = run_mod.plan_run(materials_path=self.materials_path, ledger=self.ledger)
        result = run_mod.run_batch(plan, {}, materials_path=self.materials_path, ledger=self.ledger)
        outcomes = {o.subject_id: o.outcome for o in result.outcomes}
        self.assertEqual(outcomes.get("shard.chaff"), "missing_answer")

    def test_a_bad_answer_is_refused_with_named_defects(self) -> None:
        self._seed_corpus([])
        plan = run_mod.plan_run(materials_path=self.materials_path, ledger=self.ledger)
        result = run_mod.run_batch(
            plan, {"shard.chaff": {"name": "x", "flavor": "too short a name above"}},
            materials_path=self.materials_path, ledger=self.ledger)
        outcome = next(o for o in result.outcomes if o.subject_id == "shard.chaff")
        self.assertEqual(outcome.outcome, "refused")
        self.assertTrue(any("below the minimum" in d for d in outcome.defects), outcome.defects)
        self.assertEqual(result.persisted, ())


# ------------------------------------------------------------------------------------------------
# CLI — real gap, closed 2026-09-08: this module had no entrypoint of any kind before this.
# ------------------------------------------------------------------------------------------------
class NameCollisionGateTests(unittest.TestCase):
    """The write-path gate: a name already in use by a DIFFERENT material id is refused, and the
    refusal names the collision.

    This is the second half of the fix, and it is deterministic rather than statistical. The 747 findings
    a full run produced are all of the form *"'X' is used verbatim by N entries"* — a verbatim name
    reuse, not a fuzzy similarity judgement. So the gate needs no threshold, no minhash and no tuning
    value: an authored name that is already another material's name is a fact, and the fact is checkable
    in O(1) before anything is written.

    That matters because the alternative — setgen's population-level `rate_permille` against
    `tuning.near_duplicate_rate_max_permille` — can only be evaluated *after* the whole batch has
    already been persisted. `materialgen`'s `run_batch` writes atomically and unconditionally, so a
    population-level gate there would report the collision and keep the rows.
    """

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        tmp = Path(self._tmp.name)
        self.materials_path = tmp / "materials.json"
        self.ledger = RunLedger(tmp / "materials-gen.ledger.json")

    def _entry(self, runtime_id: str, name: str, seq: int) -> dict:
        # The id suffix must be an INTEGER: `run_batch` resumes a sequence with
        # `int(existing["id"].rsplit(".", 1)[-1])`, so a non-numeric fixture id raises ValueError and the
        # test would fail for a reason that has nothing to do with the gate under test.
        return {"id": f"material.{seq}", "nameKey": f"material.{runtime_id.replace('.', '-')}",
                "name": name, "runtimeId": runtime_id, "materialClass": "shard",
                "iconKey": f"icon.material.{runtime_id.replace('.', '-')}", "tags": ["mineral"]}

    def _seed(self, entries: "list[dict]") -> None:
        self.materials_path.write_text(
            json.dumps({"schemaVersion": 1, "kind": "material", "entries": entries}), encoding="utf-8")

    def _run(self, plan, answers):
        return run_mod.run_batch(plan, answers, materials_path=self.materials_path, ledger=self.ledger)

    def test_a_name_already_used_by_another_material_is_refused_and_named(self) -> None:
        self._seed([self._entry("shard.chaff", "Chaff Fragment", 9001)])
        plan = run_mod.plan_run(materials_path=self.materials_path, ledger=self.ledger)
        self.assertIn("shard.sprout", {s.subject_id for s in plan.subjects})

        result = self._run(plan, {"shard.sprout": _clean_answer(name="Chaff Fragment")})

        self.assertNotIn("shard.sprout", result.persisted,
                         "a name already in use by another material id must not be persisted")
        outcome = next(o for o in result.outcomes if o.subject_id == "shard.sprout")
        self.assertEqual(outcome.outcome, "refused")
        self.assertTrue(any("Chaff Fragment" in d for d in outcome.defects),
                        f"the refusal must NAME the colliding name, got {outcome.defects!r}")
        self.assertTrue(any("shard.chaff" in d for d in outcome.defects),
                        f"the refusal must NAME the id that already holds it, got {outcome.defects!r}")
        doc = json.loads(self.materials_path.read_text(encoding="utf-8"))
        self.assertNotIn("shard.sprout", [e["runtimeId"] for e in doc["entries"]],
                         "the corpus must not gain the colliding row")

    def test_two_subjects_in_one_batch_cannot_share_a_name(self) -> None:
        """The batch is one `answers` mapping, so a collision can be *within* a single call's output —
        the shape a 3,602-item run actually has. The second offender is refused; the first persists."""
        self._seed([])
        plan = run_mod.plan_run(materials_path=self.materials_path, ledger=self.ledger)
        shared = _clean_answer(name="Essence of the Undead Monarch")
        result = self._run(plan, {"shard.chaff": dict(shared), "shard.sprout": dict(shared)})

        self.assertEqual(len(result.persisted), 1,
                         f"exactly one of a colliding pair may persist, got {result.persisted!r}")
        refused = [o for o in result.outcomes if o.outcome == "refused"]
        self.assertEqual(len(refused), 1, f"expected exactly one refusal, got {result.outcomes!r}")
        self.assertTrue(any("Essence of the Undead Monarch" in d for d in refused[0].defects),
                        f"the refusal must name the colliding name, got {refused[0].defects!r}")

    def test_a_distinct_name_still_persists(self) -> None:
        """The positive control. A gate that refuses everything would pass both tests above."""
        self._seed([self._entry("shard.chaff", "Chaff Fragment", 9001)])
        plan = run_mod.plan_run(materials_path=self.materials_path, ledger=self.ledger)
        result = self._run(plan, {"shard.sprout": _clean_answer(name="Sprout of the First Light")})
        self.assertIn("shard.sprout", result.persisted)
        doc = json.loads(self.materials_path.read_text(encoding="utf-8"))
        names = [e["name"] for e in doc["entries"]]
        self.assertEqual(names.count("Sprout of the First Light"), 1)

    def test_a_name_reused_by_its_own_id_is_not_a_collision(self) -> None:
        """Re-emitting the SAME id with the same name is a legitimate overwrite, not a collision — an
        over-strict gate would make the adapter's own `plan_overwrite` path unrunnable, which is a
        regression introduced by the fix rather than caught by it."""
        self._seed([self._entry("shard.chaff", "Chaff Fragment", 9001)])
        plan = run_mod.plan_overwrite(["shard.chaff"], ledger=self.ledger)
        result = self._run(plan, {"shard.chaff": _clean_answer(name="Chaff Fragment")})
        self.assertIn("shard.chaff", result.persisted)
        doc = json.loads(self.materials_path.read_text(encoding="utf-8"))
        self.assertEqual([e["name"] for e in doc["entries"]].count("Chaff Fragment"), 1)


class CrossBatchCollisionTests(unittest.TestCase):
    """A name persisted by an EARLIER batch must block a LATER one.

    This is load-bearing for the re-emit plan rather than incidental. The 1,857 colliding trophy names
    cannot be re-authored in one invocation: the `--overwrite` id list is **48,805 characters** against
    Windows' **32,767**-character command-line limit, so it overflows by 16,109 and the run must be split
    into at least three batches of roughly 934 ids.

    If the gate only compared a batch against itself, a name published by batch 1 would be free for batch 2
    to reuse, and splitting the run would silently reintroduce the exact defect the gate exists to stop —
    1,857 calls spent, and the collisions back. The reason it is safe is that `run_batch` re-reads the
    corpus file at the start of every invocation, so batch 2 sees batch 1's output as "on disk". That is a
    property of the write path, not of the gate, so it is pinned here rather than assumed.
    """

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        tmp = Path(self._tmp.name)
        self.materials_path = tmp / "materials.json"
        self.ledger = RunLedger(tmp / "materials-gen.ledger.json")
        self.materials_path.write_text(
            json.dumps({"schemaVersion": 1, "kind": "material", "entries": []}), encoding="utf-8")

    def _overwrite(self, ids):
        return run_mod.plan_overwrite(ids, ledger=self.ledger)

    def test_a_name_persisted_by_an_earlier_batch_blocks_a_later_batch(self) -> None:
        first = self._overwrite(["shard.chaff"])
        run_mod.run_batch(first, {"shard.chaff": _clean_answer(name="Batch One Keeper")},
                          materials_path=self.materials_path, ledger=self.ledger)

        # Batch two, a fresh invocation, asks for a DIFFERENT id but reuses batch one's name.
        second = self._overwrite(["shard.sprout"])
        result = run_mod.run_batch(
            second, {"shard.sprout": _clean_answer(name="Batch One Keeper")},
            materials_path=self.materials_path, ledger=self.ledger)

        self.assertNotIn("shard.sprout", result.persisted,
                         "a name an earlier batch persisted must block a later batch, or splitting the "
                         "re-emit into batches reintroduces the collisions the gate exists to stop")
        outcome = next(o for o in result.outcomes if o.subject_id == "shard.sprout")
        self.assertEqual(outcome.outcome, "refused")
        self.assertTrue(any("Batch One Keeper" in d for d in outcome.defects),
                        f"the refusal must name the reused name, got {outcome.defects!r}")

        doc = json.loads(self.materials_path.read_text(encoding="utf-8"))
        names = [e["name"] for e in doc["entries"]]
        self.assertEqual(names.count("Batch One Keeper"), 1,
                         "exactly one entry may hold the name after both batches")

    def test_a_later_batch_may_still_use_its_own_name(self) -> None:
        """The guard-rail: cross-batch blocking must not stop a later batch from succeeding."""
        first = self._overwrite(["shard.chaff"])
        run_mod.run_batch(first, {"shard.chaff": _clean_answer(name="Batch One Keeper")},
                          materials_path=self.materials_path, ledger=self.ledger)
        second = self._overwrite(["shard.sprout"])
        result = run_mod.run_batch(
            second, {"shard.sprout": _clean_answer(name="Batch Two Distinct")},
            materials_path=self.materials_path, ledger=self.ledger)
        self.assertIn("shard.sprout", result.persisted)
        doc = json.loads(self.materials_path.read_text(encoding="utf-8"))
        self.assertEqual(len(doc["entries"]), 2)


class CliTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        tmp_path = Path(self._tmp.name)
        self.materials_path = tmp_path / "materials.json"
        self.ledger_path = tmp_path / "ledger.json"
        self._materials_patch = unittest.mock.patch.object(
            run_mod, "MATERIALS_PATH", self.materials_path)
        self._ledger_patch = unittest.mock.patch.object(
            run_mod, "DEFAULT_LEDGER_PATH", self.ledger_path)
        self._materials_patch.start()
        self._ledger_patch.start()
        self.addCleanup(self._materials_patch.stop)
        self.addCleanup(self._ledger_patch.stop)

    def test_cli_write_without_endpoint_refuses(self) -> None:
        """Refuse only when the *resolved* transport has no endpoint."""
        from seedsmith.pipeline.llm_caller import LlmCallerConfig
        with unittest.mock.patch(
                "seedsmith.pipeline.llm_caller.resolve_live_transport",
                return_value=LlmCallerConfig(endpoint="", model="x")):
            with self.assertRaises(SystemExit):
                run_mod.main(["--overwrite", "shard.chaff", "--write"])

    def test_cli_a_real_live_run_writes_a_real_corpus_file(self) -> None:
        """⛔ Real gap, closed 2026-09-08 — see basetypegen's identical test for the full account:
        `run_batch` here takes a pre-built `{subject_id: answer}` mapping, not a `call` callable —
        `main()` builds that mapping from `live_answer_caller` before calling it."""
        called_with = {}

        def _fake_live_answer_caller(config):
            called_with["config"] = config
            return lambda brief, schema: _clean_answer(name="Live-Wired Shard")

        with unittest.mock.patch("seedsmith.pipeline.llm_caller.live_answer_caller",
                                 _fake_live_answer_caller):
            exit_code = run_mod.main(["--overwrite", "shard.chaff", "--write",
                                     "--endpoint", "http://unit-test-endpoint",
                                     "--model", "unit-test-model"])

        self.assertEqual(exit_code, 0)
        self.assertEqual(called_with["config"].endpoint, "http://unit-test-endpoint")
        self.assertEqual(called_with["config"].model, "unit-test-model")
        written = json.loads(self.materials_path.read_text(encoding="utf-8"))
        names = {e["name"] for e in written["entries"]}
        self.assertIn("Live-Wired Shard", names)

    # ---- a raising subject must not discard the calls already paid for ----

    _BRIEF_ID = re.compile(r"`([a-z]+\.[a-z0-9.]+)`")

    def _caller_raising_for(self, doomed: str, counter: "dict | None" = None) -> object:
        """A live caller that refuses exactly one subject id, and counts the calls it received.

        The subject is recovered from the BRIEF, because the signature really is
        `call(brief, schema)` with no subject in sight - so the answer's name has to come from there too.
        Deriving it from the doomed id instead would hand every survivor the SAME name, and the name gate
        would refuse them, which reads as a gate failure rather than the fixture bug it is.
        """
        def _caller(config):
            def _call(brief, schema):
                if counter is not None:
                    counter["calls"] = counter.get("calls", 0) + 1
                match = self._BRIEF_ID.search(brief)
                subject = match.group(1) if match else "unknown"
                if subject == doomed:
                    raise RuntimeError(f"model call failed for {doomed}: simulated endpoint wedge")
                return _clean_answer(name=f"Wired {subject.split('.')[-1].title()} Shard")
            return _call
        return _caller

    def test_one_failing_subject_does_not_discard_the_rest(self) -> None:
        """⛔ The defect this pins, and it is a spend defect, not a correctness one.

        `main()` used to build the whole `{subject_id: answer}` mapping in ONE dict comprehension, so a
        single raising subject unwound the invocation and every answer already generated was lost. Measured
        on a live probe against a dead port: 2 attempts spent, 0 rows written. At the 1,081-id batch the
        re-emit plan uses, an abort at subject 900 discards 900 paid-for generations.

        On the old code this test ERRORS with the propagated `RuntimeError` and writes nothing. It passes
        only when the loop records the failure, keeps going, and hands `run_batch` a partial mapping — which
        `run_batch` has always supported through its `missing_answer` outcome.
        """
        counter: dict = {}
        with unittest.mock.patch("seedsmith.pipeline.llm_caller.live_answer_caller",
                                 self._caller_raising_for("shard.sprout", counter)):
            exit_code = run_mod.main(["--overwrite", "shard.chaff,shard.sprout,shard.almanac",
                                      "--write", "--endpoint", "http://unit-test-endpoint",
                                      "--model", "unit-test-model"])

        self.assertEqual(exit_code, 1, "a partial run must report non-zero, not read as success")
        self.assertEqual(counter["calls"], 3, "every subject must still be attempted")
        written = json.loads(self.materials_path.read_text(encoding="utf-8"))
        names = {e["name"] for e in written["entries"]}
        self.assertEqual(len(names), 2, "the two subjects that answered must be on disk")
        self.assertIn("Wired Chaff Shard", names)
        self.assertIn("Wired Almanac Shard", names)
        done = RunLedger(self.ledger_path).read_done()
        self.assertIn("shard.chaff", done, "a persisted subject is ledgered, so a re-run skips it")
        self.assertIn("shard.almanac", done)
        self.assertNotIn("shard.sprout", done, "the subject that failed is NOT ledgered done")

    def test_a_dead_endpoint_stops_after_consecutive_failures(self) -> None:
        """The opposite bound: a wholly dead endpoint must not be ground down one doomed call per subject.
        The whole 1,863-id plan at 8 requests per subject would otherwise burn thousands on a port that
        is not listening."""
        counter: dict = {}

        def _always_fails(config):
            def _call(brief, schema):
                counter["calls"] = counter.get("calls", 0) + 1
                raise RuntimeError("connection refused")
            return _call

        with unittest.mock.patch("seedsmith.pipeline.llm_caller.live_answer_caller", _always_fails):
            exit_code = run_mod.main(["--overwrite", "shard.chaff,shard.sprout,shard.almanac,shard.grafted",
                                      "--write", "--endpoint", "http://unit-test-endpoint",
                                      "--model", "unit-test-model",
                                      "--max-consecutive-call-failures", "2"])

        self.assertEqual(counter["calls"], 2, "it must stop at the cap, not attempt all four")
        self.assertEqual(exit_code, 1)

    def test_a_flaky_endpoint_is_ridden_through_rather_than_abandoned(self) -> None:
        """The counter is CONSECUTIVE, so one success resets it. A flaky endpoint — the common case, and
        the one `SEEDSMITH_LLM_ATTEMPTS=2` already exists for — must not trip a cap of 2."""
        counter: dict = {}
        state = {"n": 0}

        def _alternating(config):
            def _call(brief, schema):
                counter["calls"] = counter.get("calls", 0) + 1
                state["n"] += 1
                if state["n"] % 2 == 1:
                    raise RuntimeError("transient")
                return _clean_answer(name=f"Flaky {state['n']} Shard")
            return _call

        with unittest.mock.patch("seedsmith.pipeline.llm_caller.live_answer_caller", _alternating):
            exit_code = run_mod.main(["--overwrite", "shard.chaff,shard.sprout,shard.almanac,shard.grafted",
                                      "--write", "--endpoint", "http://unit-test-endpoint",
                                      "--model", "unit-test-model",
                                      "--max-consecutive-call-failures", "2"])

        self.assertEqual(counter["calls"], 4, "no two failures ever occur back to back, so none may stop it")
        self.assertEqual(exit_code, 1, "half still failed, so the run is still a partial one")
        written = json.loads(self.materials_path.read_text(encoding="utf-8"))
        self.assertEqual(len(written["entries"]), 2, "the two that succeeded are on disk")

    def test_a_clean_run_reports_no_call_failures(self) -> None:
        """The success payload carries the new keys as EMPTY, so a consumer can read one shape either way
        rather than branching on whether the keys happen to exist."""
        with unittest.mock.patch("seedsmith.pipeline.llm_caller.live_answer_caller",
                                 lambda config: (lambda brief, schema: _clean_answer(name="Clean Shard"))):
            exit_code = run_mod.main(["--overwrite", "shard.chaff", "--write",
                                      "--endpoint", "http://unit-test-endpoint",
                                      "--model", "unit-test-model"])
        self.assertEqual(exit_code, 0)


class NameRetryTests(unittest.TestCase):
    """A refused NAME must be re-askable. Measured 2026-09-28 by a live pilot against the rescue corpus.

    ⛔ The gap these pin, from a run rather than from reading: 16 subjects, **9 persisted, 7 refused -
    437 per mille** - and every refusal was `name_gate`, not a malformed answer. So the pipeline was
    healthy and the YIELD was the limit, and the 56% that survived was the FINAL figure, because the live
    loop asked each subject exactly once and `run_batch` recorded a collision and moved on. Spending the
    planned 2,176 subjects at that rate buys roughly 1,200 rows and 1,000 escalations, and a plain re-run
    re-asks the identical question and gets the identical name - as it did for 3 torch-themed species that
    each returned 'Torch of the Stump'.

    `setgen` already had this repair for the same defect, worded "Previous attempt was rejected because its
    name duplicated an existing item. Choose a completely new surface name" - but wired to
    `--retry-blocked`, which selects only `blocked` subjects, while a name collision ESCALATES terminally
    and so never reached it. The test therefore pins the reachability, not just the wording: the
    escalated outcome is what has to become retryable.
    """

    COLLISION = ("duplicate name 'Torch of the Stump': already the name of 'material.099'. Every "
                 "material id must hold a distinct name - author a new one rather than reusing "
                 "another's.")

    def test_the_retry_brief_names_the_specific_collision(self) -> None:
        """A re-ask that does not change the question gets the same answer, so the retry has to carry
        what the model did not already know: WHICH name is taken, and by whom."""
        brief = run_mod._name_retry_brief("Author a trophy material.", (self.COLLISION,))
        self.assertIn("Torch of the Stump", brief,
                      "FAIL-BEFORE: the retry must quote the refused name verbatim")
        self.assertIn("material.099", brief,
                      "and the id that holds it, so the model can aim somewhere else")
        self.assertIn("REJECTED ON THE NAME", brief,
                      "the rejection has to be stated, or the extra text reads as more instructions")
        self.assertIn("Change ONLY the name", brief,
                      "the retry must not invite the model to re-roll tags or stats, which would trade a "
                      "name collision for a schema defect")
        self.assertIn("Author a trophy material.", brief,
                      "the original brief must survive, or the retry answers a different question")

    def test_a_brief_with_no_name_defect_is_returned_unchanged(self) -> None:
        """A schema or tag-axis defect is not re-asked: the brief already states the shape, so a retry
        spends a call to re-roll something correct."""
        original = "Author a trophy material."
        self.assertEqual(run_mod._name_retry_brief(original, ("$.name: too short",)), original)
        self.assertEqual(run_mod._name_retry_brief(original, ()), original)

    def test_an_escalated_name_collision_is_retryable_which_blocked_is_not(self) -> None:
        """The reachability, which is the actual defect: an ESCALATED name collision must be selected
        for a re-ask, and a non-name refusal must not be.

        FAIL-BEFORE: there was no selection at all - the live loop asked once and stopped, so a name
        collision was terminal by construction rather than by decision.

        The shape case is the one that earned its keep: `$.name: expected at least 3 characters` is a
        SCHEMA defect that contains the word "name", and the first version of the production predicate
        matched on the substring. This is the assertion that caught it.
        """
        self.assertTrue(run_mod._is_name_defect(
            "duplicate name 'Torch of the Stump': already the name of 'material.099'."))
        self.assertTrue(run_mod._is_name_defect(
            "near-duplicate name 'Sunblover's Essence': Jaccard 0.79 against 'material.201'."))
        for not_a_name_defect in (
            "$.name: expected at least 3 characters, got 'ab'",
            "$.flavor: is not one of ['short']",
            "tags 'light' and 'heavy' are both on the 'mass-class' axis, which tags.v1.json marks "
            "exclusive - an entry may carry at most one",
            "",
        ):
            self.assertFalse(run_mod._is_name_defect(not_a_name_defect),
                             f"a non-name defect must not be re-asked: {not_a_name_defect[:60]!r}")

    def test_a_refused_name_is_asked_again_with_the_collision_named(self) -> None:
        """End to end through `main()`, with a stubbed transport: the first answer collides, the second
        does not, and the second ASK carries the collision.

        This is the whole point of the change, so it is worth driving the real entrypoint. The stub is a
        caller, not a corpus: no model is called and nothing is written outside a temp dir.
        """
        import contextlib
        import io
        import pathlib
        import shutil
        import tempfile as _tf

        import seedsmith.adapters.items.materialgen.run as run_module
        import seedsmith.pipeline.llm_caller as llm

        seen: "list[str]" = []

        def _fake_caller(_config):
            def call(brief, _schema):
                seen.append(brief)
                if len(seen) == 1:
                    return {"name": "Torch of the Stump", "flavor": "A charred torch, long spent.",
                            "tags": ["elemental"], "element": "fire"}
                return {"name": "Ember of the Kindling Stack", "flavor": "A torch that lights others.",
                        "tags": ["elemental"], "element": "fire"}
            return call

        # A real closed-class id, taken the way the rest of this suite takes one (`essence.fire` in
        # `plan_overwrite` tests): `plan_overwrite` refuses anything it cannot vouch for, so an invented
        # `material.NNN` is refused before the test reaches the behaviour it means to check.
        subject_id = "essence.fire"

        plan = run_module.plan_overwrite([subject_id], ledger=None)
        real_plan_overwrite = run_module.plan_overwrite
        real_caller = llm.live_answer_caller
        real_transport = llm.resolve_live_transport
        real_path = run_module.MATERIALS_PATH
        run_module.plan_overwrite = lambda ids, ledger=None: plan
        llm.live_answer_caller = _fake_caller
        llm.resolve_live_transport = lambda endpoint, model: type(
            "C", (), {"endpoint": "http://stub", "model": "stub", "timeout": 1.0, "attempts": 1,
                      "retry_delay": 0.0, "max_heal": 0})()
        tmp = pathlib.Path(_tf.mkdtemp(prefix="name-retry-"))
        try:
            # The corpus must ALREADY hold the name the first answer returns, or there is no collision to
            # recover from and the retry never runs. The first version of this test wrote an empty corpus
            # and asserted two calls, which is why it saw one.
            corpus = tmp / "materials.json"
            corpus.write_text(json.dumps({
                "schemaVersion": 1, "kind": "material",
                "entries": [{"id": "material.099", "runtimeId": "trophy.species.pew.1",
                             "name": "Torch of the Stump", "nameKey": "torch-of-the-stump",
                             "materialClass": "trophy", "tags": [], "element": "fire"}],
            }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            run_module.MATERIALS_PATH = corpus
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                try:
                    run_module.main(["--write", "--endpoint", "http://stub", "--model", "stub",
                                     "--overwrite", subject_id])
                except SystemExit:
                    pass
        finally:
            llm.live_answer_caller = real_caller
            llm.resolve_live_transport = real_transport
            run_module.plan_overwrite = real_plan_overwrite
            run_module.MATERIALS_PATH = real_path
            shutil.rmtree(tmp, ignore_errors=True)

        payload = out.getvalue()
        self.assertIn("nameRetries", payload,
                      "FAIL-BEFORE: the run reported no retry activity, so a refused name was terminal")
        self.assertGreaterEqual(len(seen), 2,
                                "the subject must be asked a SECOND time after a name collision")
        self.assertIn("REJECTED ON THE NAME", seen[-1],
                      "the second ask must carry the collision; asking the identical question again is "
                      "what produced 'Torch of the Stump' three times in the pilot")


if __name__ == "__main__":
    unittest.main()
