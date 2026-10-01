"""Tests for item module 21's `combination-write-unblock` unblock work
(docs/architecture/item-seedgen/spec-combination-write-unblock.md).

    python -m pytest gk-forge/tools/seedsmith/tests/test_combogen.py -v

⚠ **A pre-existing sibling file already covers the grid/tuning/schema/supply/migration/emit/brief/
run/CLI surface exhaustively**: `test_strain_splice_gen.py` (52 tests, all green except one
corpus-count assertion that drifted for reasons unrelated to this module — the live gem corpus grew
from 40 to 60 gems between when that test was written and now). Missing that file on the first
search (its name does not match `*combo*`) was this session's own investigation gap; it is corrected
here rather than duplicated. This file therefore covers ONLY what did not exist before this module's
work: the two-field regression in `schema.combination_schema` (nameKey removed from the model-facing
schema), `emit.assemble_entry` (new), `combogen.deps` (new — acceptance 3a's dependency_validator
wiring), and `combogen.authored` + `workflow/graphs/item_combination.py` (new — the generation graph
and the RunLedger-based resume/reconcile/overwrite harness this module was built to wire in).

- **Regression tests** (`SchemaTests`, `EmitTests`) — the two files this module edited beyond what
  `test_strain_splice_gen.py` already exercises.
- **Real-corpus tests** (`DepsTests`) — run `combogen.deps.preflight`/`validate_entries` against
  the actual shipped gems/base-types/atom corpora, proving acceptance 3a for real.
- **Harness-mechanics tests** (`AuthoredBatchTests`) — resume/reconcile/overwrite through
  `pipeline.run_ledger.RunLedger`, run against an isolated `tmp_path` ledger/out-dir over a REAL
  (sliced-to-two) plan, with the authored-answer transport standing in for a model — the same proof
  `test_sockets_gen.py`'s own `RunPlanTests` gives for `gemgen`.
"""
from __future__ import annotations

import argparse
import contextlib
import dataclasses
import io
import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from seedsmith.adapters.items.combogen import authored as authored_mod  # noqa: E402
from seedsmith.adapters.items.combogen import deps as deps_mod  # noqa: E402
from seedsmith.adapters.items.combogen import emit  # noqa: E402
from seedsmith.adapters.items.combogen import migrate as migrate_mod  # noqa: E402
from seedsmith.adapters.items.combogen import run as run_mod  # noqa: E402
from seedsmith.adapters.items.combogen import schema as schema_mod  # noqa: E402
from seedsmith.adapters.items.combogen import supply as supply_mod  # noqa: E402
from seedsmith.adapters.items.combogen import tuning as tuning_mod  # noqa: E402
from seedsmith.adapters.items.setgen import name_repair as name_repair_mod  # noqa: E402
from seedsmith.adapters.items.setgen.answers import AnswerFile  # noqa: E402
from seedsmith.pipeline.model import audit_schema  # noqa: E402
from seedsmith.report import cli as cli_mod  # noqa: E402
from seedsmith.pipeline.run_ledger import RunLedger  # noqa: E402
from seedsmith.report import cli as cli_mod  # noqa: E402

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



def _real_tuning():
    return tuning_mod.load()


def _real_supply():
    return supply_mod.build()


# ------------------------------------------------------------------------------------------------
# schema.py — the net-new regression: `nameKey` is NOT a model-writable field (this module's own
# P1 fix — nameKey is PLANNED from the grid cell, never AUTHORED by the model). Everything else
# about this schema (audit_schema-clean, ingredient count, empty-universe refusal) is already
# covered by `test_strain_splice_gen.py::SchemaTests`.
# ------------------------------------------------------------------------------------------------
class SchemaTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tuning = _real_tuning()
        self.supply = _real_supply()
        self.host_roles = self.tuning.host_roles()

    def _schema(self):
        granted = run_mod.granted_family_vocabulary()
        return schema_mod.combination_schema(
            self.tuning, supplied_families=self.supply.families,
            host_roles=self.host_roles, granted_families=granted)

    def test_nameKey_is_not_offered_to_the_model(self) -> None:
        names = schema_mod.schema_field_names(self._schema())
        self.assertNotIn("nameKey", names)
        self.assertIn("name", names)
        self.assertIn("flavor", names)

    def test_the_schema_is_still_audit_schema_clean_after_the_nameKey_removal(self) -> None:
        defects = audit_schema(self._schema())
        self.assertEqual(defects, [], [str(d) for d in defects])


# ------------------------------------------------------------------------------------------------
# emit.py — the net-new `assemble_entry` (`ingredient_rows`/id-minting are already covered by
# `test_strain_splice_gen.py::EmitTests`/`GridTests`).
# ------------------------------------------------------------------------------------------------
class EmitTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tuning = _real_tuning()

    def test_assemble_entry_shape_and_no_tier_number_is_ever_emitted(self) -> None:
        entry = emit.assemble_entry(
            entry_id="combo.strain-might-offense", name_key="combination.strain-might-offense",
            name="Test Name", flavor="A flavour string that is long enough.", shape="strain",
            aptitudes=("Might",), archetype="offense",
            ingredient_families=["atom.might", "atom.might", "atom.cruelty", "atom.ferocity"],
            grants=["atom.savagery"], tuning=self.tuning, host_role="armament-primary")
        self.assertEqual(entry["id"], "combo.strain-might-offense")
        self.assertEqual(entry["nameKey"], "combination.strain-might-offense")
        self.assertEqual(entry["minSockets"], self.tuning.ingredient_count)
        self.assertNotIn("grantedTier", entry)          # SSH7.3: the rung decides it at runtime
        for row in entry["ingredients"]:
            self.assertNotIn("minTier", row)
        self.assertNotIn("hostFrame", entry)  # omitted, never null
        self.assertEqual(sum(r["quantity"] for r in entry["ingredients"]),
                         self.tuning.ingredient_count)

    def test_assemble_entry_refuses_zero_grants(self) -> None:
        with self.assertRaises(emit.IdRefused):
            emit.assemble_entry(
                entry_id="combo.strain-might-offense", name_key="combination.strain-might-offense",
                name="X", flavor="A flavour string that is long enough.", shape="strain",
                aptitudes=("Might",), archetype="offense",
                ingredient_families=["atom.might"] * self.tuning.ingredient_count,
                grants=[], tuning=self.tuning)


# ------------------------------------------------------------------------------------------------
# deps.py — acceptance 3a, run against the REAL corpus
# ------------------------------------------------------------------------------------------------
class DepsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tuning = _real_tuning()
        self.supply = _real_supply()

    def test_preflight_refuses_only_on_the_r11_base_reachability_in_this_window(self) -> None:
        # SSH5.10 window: v2 lifts more roles to the ingredient count than the un-restamped corpus
        # can host yet, so the R11 base-reachability arm names them. That refusal is cleared by
        # SSH5.13's owner-run re-stamp (after SSH5.12), not by anything here — and it is NOT an
        # ingredients/grants failure.
        report = deps_mod.preflight(self.tuning, supply=self.supply)
        self.assertGreater(report.ingredient_families_checked, 0)
        self.assertGreater(report.host_roles_checked, 0)
        self.assertEqual(report.refused, bool(report.roles_without_a_base))
        for reason in report.to_dict()["reasons"]:
            self.assertNotIn("no ingredient family", reason)
            self.assertNotIn("no host role's socket ceiling", reason)
        if report.refused:
            self.assertIn("no shipped base type's socketMax", report.to_dict()["reasons"][-1])

    def test_preflight_is_refused_when_no_family_is_supplied(self) -> None:
        empty = dataclasses.replace(self.supply, families=(), bands={})
        report = deps_mod.preflight(self.tuning, supply=empty)
        self.assertTrue(report.refused)
        self.assertIn("no ingredient family is supplied by any live gem", report.to_dict()["reasons"][0])

    def test_validate_entries_resolves_a_real_generated_entry(self) -> None:
        entry = emit.assemble_entry(
            entry_id="combo.strain-might-offense", name_key="combination.strain-might-offense",
            name="Test", flavor="A flavour string that is long enough.", shape="strain",
            aptitudes=("Might",), archetype="offense",
            ingredient_families=["atom.might", "atom.might", "atom.cruelty", "atom.ferocity"],
            grants=["atom.savagery"], tuning=self.tuning, host_role="armament-primary")
        report = deps_mod.validate_entries(
            {entry["id"]: entry}, supply=self.supply, host_roles=self.tuning.host_roles())
        self.assertEqual(report.unresolved, [], [r.value for r in report.unresolved])

    def test_validate_entries_reports_an_unresolved_external_grant_without_backfilling(self) -> None:
        entry = emit.assemble_entry(
            entry_id="combo.strain-might-offense", name_key="combination.strain-might-offense",
            name="Test", flavor="A flavour string that is long enough.", shape="strain",
            aptitudes=("Might",), archetype="offense",
            ingredient_families=["atom.might", "atom.might", "atom.cruelty", "atom.ferocity"],
            grants=["atom.this-family-does-not-exist"], tuning=self.tuning,
            host_role="armament-primary")
        report = deps_mod.validate_entries(
            {entry["id"]: entry}, supply=self.supply, host_roles=self.tuning.host_roles())
        unresolved = report.unresolved
        self.assertEqual(len(unresolved), 1)
        self.assertEqual(unresolved[0].manifest.kind, "external")
        self.assertEqual(unresolved[0].value, "atom.this-family-does-not-exist")
        # 3b: EXTERNAL is never backfillable by this program.
        from seedsmith.pipeline.dependency_validator import plan_backfill
        self.assertEqual(plan_backfill(report), [])

    def test_preflight_closes_every_offered_grant_against_the_atom_catalog(self) -> None:
        """strain-splice-host SSH2.1: `grants[]` is now an EXTERNAL manifest entry inside `preflight`
        too, not only in `validate_entries` (the post-generation check) — every family
        `run.granted_family_vocabulary()` could offer the model must itself resolve against the real
        production atom catalog, over the whole universe a run COULD request, before a single
        subject is planned. Before SSH2.1, `preflight`'s own `resolve_hard` was a stub ("never
        reached"), so this report said nothing about grants at all."""
        report = deps_mod.preflight(self.tuning, supply=self.supply)
        # The grant closure is independent of the R11 base-reachability arm (v2 window): this test
        # proves every offered grant resolves, whether or not the preflight is refused overall.
        self.assertGreater(report.grants_checked, 0)
        self.assertEqual(report.to_dict()["grantsChecked"], report.grants_checked)
        grant_results = [r for r in report.result.results
                         if r.manifest.target_module == deps_mod.TARGET_GRANTS]
        self.assertEqual(len(grant_results), report.grants_checked)
        self.assertTrue(all(r.resolved for r in grant_results),
                        [r.value for r in grant_results if not r.resolved])

    def test_the_offered_grant_vocabulary_is_the_production_atom_catalog(self) -> None:
        """The offer set is the families BOTH consumers accept.

        SSH2.5's defect: `granted_family_vocabulary()` returned `registries.load_atom_families()` —
        all of `gk-data/packs/fusion/data/seed/atoms/**`, which carries hand-authored atom sources (`atom.aura-*`,
        `atom.fx-*`, `patron-aura`, `trait-critical-hunter`, `extend-slot`) that no affix family
        carries, so the C# `ReferenceCheck` refuses them.

        SSH4.4's defect (this change): returning every AUTHORED affix family is still too broad —
        `FamilyExpansion.Expand` REFUSES 70 of them by name (bare `status.<family>` stem, no
        `BattleRuleset` curve, no E30 pool, op `Replace`/`Flag`, no `referenceBaseGameUnits`), and a
        grant on a refused family passes `ReferenceCheck` and then cannot build its container at
        boot (69 grants over 63 shipped entries). The offer set is therefore
        `authored ∩ materialised`, which every consumer resolves.

        Asserts the CONTRACT against the real catalogs, never a population count.
        """
        from seedsmith.adapters.items import registries

        granted = set(run_mod.granted_family_vocabulary())
        materialised = set(registries.load_materialised_affix_family_ids())
        authored = set(registries.load_authored_affix_family_ids())
        atom_catalog = set(registries.load_atom_families())

        self.assertEqual(granted, materialised)
        # The container build's own catalog resolves every offered grant (SSH4.4's contract).
        self.assertTrue(granted <= atom_catalog, sorted(granted - atom_catalog))
        # And every offered grant is AUTHORED, so `ReferenceCheck` resolves it (SSH2.5's contract).
        self.assertTrue(granted <= authored, sorted(granted - authored))

        # The refused authored families are the ones FamilyExpansion refuses: they are not offered,
        # and they are non-empty — a silent revert to the authored-only loader fails loudly here.
        refused = authored - materialised
        self.assertNotEqual(refused, set(),
                            "every authored affix family now materialises — this guard is no longer load-bearing")
        self.assertEqual(granted & refused, set(), sorted(granted & refused))

        # And the hand-authored atom-only families stay excluded (SSH2.5's own defect).
        atom_only = atom_catalog - authored
        self.assertNotEqual(atom_only, set(),
                            "the two catalogs have converged — this guard is no longer load-bearing")
        self.assertEqual(granted & atom_only, set(), sorted(granted & atom_only))

    def test_ingredients_still_close_against_the_gem_supply_not_the_whole_atom_catalog(self) -> None:
        """SSH2.1's own defect was `granted_family_vocabulary()` returning the SAME set ingredients
        draw from (`supply.families`, the narrow gem-suppliable set) — that narrowing was exactly why
        26 of 102 grid cells blocked, because a grant never needs to be gem-suppliable (it resolves
        to an atom at BIND time, module 4, not at socket time). After the fix the two vocabularies
        must be genuinely different closed sets — measured against the real corpus, not assumed:
        the shipped gem supply and the shipped atom-family catalog are not the same set (98 vs 94
        families here, and neither contains the other), so asserting `granted == supplied` would
        itself be the regression this test exists to catch. Ingredients still close against the gem
        supply exactly; grants close against the whole production atom catalog instead."""
        granted = set(run_mod.granted_family_vocabulary())
        supplied = set(self.supply.families)
        self.assertNotEqual(granted, supplied,
                            "grants must no longer be the same set ingredients draw from")
        report = deps_mod.preflight(self.tuning, supply=self.supply)
        self.assertEqual(report.ingredient_families_checked, self.supply.family_count)
        ingredient_results = [r for r in report.result.results
                              if r.manifest.target_module == deps_mod.TARGET_INGREDIENTS]
        self.assertEqual({r.value for r in ingredient_results}, supplied)


# ------------------------------------------------------------------------------------------------
# authored.py — the generator-harness wiring: resume / reconcile / overwrite, zero live calls
# ------------------------------------------------------------------------------------------------
class AuthoredBatchTests(unittest.TestCase):
    def setUp(self) -> None:
        import tempfile

        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.out_dir = Path(self._tmp.name) / "out"
        self.out_dir.mkdir()
        self.ledger_path = self.out_dir / "combination-gen.ledger.json"

        self.tuning = _real_tuning()
        self.supply = _real_supply()
        full_plan = run_mod.plan_run(shape="strain", tuning=self.tuning, supply=self.supply)
        # Slice to the first two subjects — cheap, deterministic, and enough to exercise
        # resume/reconcile/overwrite without driving all 36.
        self.plan = dataclasses.replace(full_plan, subjects=full_plan.subjects[:2])
        self.family = sorted(self.supply.families)[0]
        self.grant_family = self._first_real_external_grant()

    def _first_real_external_grant(self) -> str:
        granted = set(run_mod.granted_family_vocabulary())
        supplied = set(self.supply.families)
        return sorted(supplied & granted)[0]

    def _answers_for_plan(self) -> AnswerFile:
        by_subject = {}
        for subject in self.plan.subjects:
            by_subject[subject.subject_id] = ({
                "name": f"Test {subject.entry_id}",
                "flavor": "A flavour string that is long enough to pass the schema minimum.",
                "ingredients": [self.family] * self.tuning.ingredient_count,
                "grants": [self.grant_family],
            },)
        return AnswerFile(kind="combination", population="n/a", prompt_version="test/1",
                          by_subject=by_subject)

    def test_a_name_the_shipped_corpus_already_uses_is_refused(self) -> None:
        from seedsmith.workflow.graphs import item_combination as graph_mod

        colliding = graph_mod.answer_reuses_a_shipped_idea(
            {"name": "Ferocity Bulwark"},
            {"keyOf": lambda names: {n: "bulwark ferocity" for n in names},
             "takenKeys": {"bulwark ferocity"}})
        self.assertEqual(len(colliding), 1)
        self.assertIn("same idea", colliding[0])
        distinct = graph_mod.answer_reuses_a_shipped_idea(
            {"name": "Ember Legion"},
            {"keyOf": lambda names: {n: "ember legion" for n in names},
             "takenKeys": {"bulwark ferocity"}})
        self.assertEqual(distinct, [])
        # A declared block carries no name and must not be judged on one.
        self.assertEqual(graph_mod.answer_reuses_a_shipped_idea(
            {"blocked": "no mechanism"},
            {"keyOf": lambda names: {n: "x" for n in names}, "takenKeys": {"x"}}), [])

    def test_the_shipped_key_guard_stops_a_run_persisting_a_colliding_name(self) -> None:
        """Every fixture answer keys to an already-shipped idea, so nothing may reach the seed file:
        the guard runs inside the graph, on the production path the CLI arms."""
        result = authored_mod.run_batch(
            plan=self.plan, answers=self._answers_for_plan(), tuning=self.tuning,
            out_dir=self.out_dir, authored_utc="1970-01-01T00:00:00Z", model="test/1",
            ledger_path=self.ledger_path,
            taken_keys={"taken"}, key_of=lambda names: {n: "taken" for n in names})
        self.assertEqual(result.persisted, [])
        self.assertEqual([o.outcome for o in result.outcomes], ["escalated", "escalated"])

    def test_a_name_the_naming_grammar_refuses_is_refused_by_the_graph(self) -> None:
        """SSH5.13-P1: the graph runs the C# validator's OWN grammar over the authored name, so a
        single-word fusion that does not decompose is heal feedback instead of a write the gate catches
        afterwards."""
        from seedsmith.workflow.graphs import item_combination as graph_mod

        refused = graph_mod.answer_uses_a_legal_name(
            {"name": "Ironstead"},
            {"nameDefects": lambda names: {n: ["name: a fusion that does not decompose"] for n in names}})
        self.assertEqual(1, len(refused))
        self.assertIn("fusion", refused[0])

        accepted = graph_mod.answer_uses_a_legal_name(
            {"name": "Ferocity Bulwark"},
            {"nameDefects": lambda names: {n: [] for n in names}})
        self.assertEqual([], accepted)

        # A declared block carries no name and is never judged on one.
        self.assertEqual([], graph_mod.answer_uses_a_legal_name(
            {"blocked": "no mechanism"},
            {"nameDefects": lambda names: {n: ["x"] for n in names}}))

        # Without an authority the check is OFF, never guessed (a unit fixture that supplies none).
        self.assertEqual([], graph_mod.answer_uses_a_legal_name({"name": "Ironstead"}, {}))

    def test_the_grammar_guard_stops_a_run_persisting_a_name_it_refuses(self) -> None:
        result = authored_mod.run_batch(
            plan=self.plan, answers=self._answers_for_plan(), tuning=self.tuning,
            out_dir=self.out_dir, authored_utc="1970-01-01T00:00:00Z", model="test/1",
            ledger_path=self.ledger_path,
            name_defects=lambda names: {n: ["name: a fusion that does not decompose"] for n in names})
        self.assertEqual(result.persisted, [])
        self.assertEqual([o.outcome for o in result.outcomes], ["escalated", "escalated"])

    def test_the_csharp_grammar_is_the_authority_for_a_candidate_name(self) -> None:
        defects = name_repair_mod.name_defects(["Ironstead", "Ferocity Bulwark", "Fang of Ash"])
        self.assertEqual(1, len(defects["Ironstead"]))
        self.assertIn("fusion", defects["Ironstead"][0])
        self.assertEqual([], defects["Ferocity Bulwark"])
        self.assertEqual([], defects["Fang of Ash"])

    def test_run_batch_persists_every_planned_subject(self) -> None:
        result = authored_mod.run_batch(
            plan=self.plan, answers=self._answers_for_plan(), tuning=self.tuning,
            out_dir=self.out_dir, authored_utc="1970-01-01T00:00:00Z", model="test/1",
            ledger_path=self.ledger_path)
        self.assertEqual(len(result.persisted), 2)
        self.assertEqual(len(result.outcomes), 2)
        self.assertTrue(result.file and result.file.exists())
        assert result.file is not None   # narrows the Optional for the type checker
        doc = json.loads(result.file.read_text(encoding="utf-8"))
        self.assertEqual(doc["kind"], "combination")
        self.assertEqual(len(doc["entries"]), 2)

    def test_resume_produces_no_new_work_the_second_time(self) -> None:
        authored_mod.run_batch(
            plan=self.plan, answers=self._answers_for_plan(), tuning=self.tuning,
            out_dir=self.out_dir, authored_utc="1970-01-01T00:00:00Z", model="test/1",
            ledger_path=self.ledger_path)
        ledger = RunLedger(self.ledger_path)
        needing = authored_mod.plan_needing_work(self.plan, ledger)
        self.assertEqual(needing, [])

        # A second `run_batch` with the SAME answers must not raise `AnswerExhausted` even though
        # nothing new is planned — its subject list is simply empty.
        result_again = authored_mod.run_batch(
            plan=self.plan, answers=self._answers_for_plan(), tuning=self.tuning,
            out_dir=self.out_dir, authored_utc="1970-01-01T00:00:00Z", model="test/1",
            ledger_path=self.ledger_path)
        self.assertEqual(result_again.outcomes, [])
        # The file still reflects both already-done entries — resume does not drop them.
        self.assertEqual(len(result_again.entries), 2)

    def test_limit_after_resume_skips_already_done_first_cell(self) -> None:
        """`--limit` must apply to needing work, not the raw grid head (smoke planned=0 bug)."""
        authored_mod.run_batch(
            plan=dataclasses.replace(self.plan, subjects=self.plan.subjects[:1]),
            answers=self._answers_for_plan(), tuning=self.tuning,
            out_dir=self.out_dir, authored_utc="1970-01-01T00:00:00Z", model="test/1",
            ledger_path=self.ledger_path)
        ledger = RunLedger(self.ledger_path)
        needing = authored_mod.plan_needing_work(self.plan, ledger)
        limited = needing[:1]
        self.assertEqual(len(limited), 1)
        self.assertEqual(limited[0].subject_id, self.plan.subjects[1].subject_id)
        # Wrong order (limit then resume) yields empty — the defect this guards against.
        wrong = authored_mod.plan_needing_work(
            dataclasses.replace(self.plan, subjects=self.plan.subjects[:1]), ledger)
        self.assertEqual(wrong, [])

    def test_reconcile_recovers_a_corrupted_ledger_row(self) -> None:
        authored_mod.run_batch(
            plan=self.plan, answers=self._answers_for_plan(), tuning=self.tuning,
            out_dir=self.out_dir, authored_utc="1970-01-01T00:00:00Z", model="test/1",
            ledger_path=self.ledger_path)
        doc = json.loads(self.ledger_path.read_text(encoding="utf-8"))
        first_key = self.plan.subjects[0].subject_id
        self.assertIn(first_key, doc["done"])
        doc["done"][first_key] = {"entryId": self.plan.subjects[0].entry_id}  # no "entry" -- corrupt
        self.ledger_path.write_text(json.dumps(doc), encoding="utf-8")

        ledger = RunLedger(self.ledger_path)
        needing = authored_mod.plan_needing_work(self.plan, ledger)
        self.assertEqual([s.subject_id for s in needing], [first_key])

    def test_overwrite_by_explicit_ids_only_touches_those_subjects(self) -> None:
        authored_mod.run_batch(
            plan=self.plan, answers=self._answers_for_plan(), tuning=self.tuning,
            out_dir=self.out_dir, authored_utc="1970-01-01T00:00:00Z", model="test/1",
            ledger_path=self.ledger_path)
        target_id = self.plan.subjects[0].subject_id
        result = authored_mod.run_batch(
            plan=self.plan, answers=self._answers_for_plan(), tuning=self.tuning,
            out_dir=self.out_dir, authored_utc="1970-01-01T00:00:00Z", model="test/1",
            ledger_path=self.ledger_path, overwrite=[target_id])
        self.assertEqual([o.subject_id for o in result.outcomes], [target_id])

    def test_a_typod_overwrite_scope_fails_loudly(self) -> None:
        with self.assertRaises(ValueError):
            authored_mod.run_batch(
                plan=self.plan, answers=self._answers_for_plan(), tuning=self.tuning,
                out_dir=self.out_dir, authored_utc="1970-01-01T00:00:00Z", model="test/1",
                ledger_path=self.ledger_path, overwrite="al")  # a typo of "all"

    def test_a_blocked_answer_writes_nothing_for_that_subject(self) -> None:
        answers = self._answers_for_plan()
        first_id = self.plan.subjects[0].subject_id
        answers.by_subject[first_id] = ({"blocked": "no fitting mechanism in this cell"},)
        result = authored_mod.run_batch(
            plan=self.plan, answers=answers, tuning=self.tuning, out_dir=self.out_dir,
            authored_utc="1970-01-01T00:00:00Z", model="test/1", ledger_path=self.ledger_path)
        blocked = [o for o in result.outcomes if o.subject_id == first_id]
        self.assertEqual(blocked[0].outcome, "blocked")
        self.assertEqual(len(result.persisted), 1)
        ledger = RunLedger(self.ledger_path)
        needing = authored_mod.plan_needing_work(self.plan, ledger)
        self.assertEqual([s.subject_id for s in needing], [])

    def test_an_escalated_answer_is_ledgered_so_resume_advances(self) -> None:
        answers = self._answers_for_plan()
        first_id = self.plan.subjects[0].subject_id
        # Exhaust attempts → escalate (ReplayTransport runs out of authored answers).
        answers.by_subject[first_id] = ()
        result = authored_mod.run_batch(
            plan=self.plan, answers=answers, tuning=self.tuning, out_dir=self.out_dir,
            authored_utc="1970-01-01T00:00:00Z", model="test/1", ledger_path=self.ledger_path)
        escalated = [o for o in result.outcomes if o.subject_id == first_id]
        self.assertEqual(escalated[0].outcome, "escalated")
        self.assertEqual(cli_mod._exit_for_graph_batch(result), cli_mod.EXIT_ESCALATED)
        ledger = RunLedger(self.ledger_path)
        needing = authored_mod.plan_needing_work(self.plan, ledger)
        self.assertNotIn(first_id, [s.subject_id for s in needing])
        row = ledger.read_done()[first_id]
        self.assertEqual(row["outcome"], "escalated")
        self.assertEqual(row.get("terminalSchemaVersion"), 1)
        self.assertEqual(row["terminalSchemaVersion"], 1)

    def test_blocked_only_batch_exits_clean_and_escalated_has_its_own_exit(self) -> None:
        blocked = SimpleNamespace(outcomes=[
            SimpleNamespace(outcome="blocked"),
            SimpleNamespace(outcome="persisted"),
        ])
        empty = SimpleNamespace(outcomes=[])
        escalated = SimpleNamespace(outcomes=[SimpleNamespace(outcome="escalated")])
        self.assertEqual(cli_mod.EXIT_CLEAN, cli_mod._exit_for_graph_batch(blocked))
        self.assertEqual(cli_mod.EXIT_CLEAN, cli_mod._exit_for_graph_batch(empty))
        self.assertEqual(cli_mod.EXIT_ESCALATED, cli_mod._exit_for_graph_batch(escalated))

    def test_authored_module_never_imports_the_live_model_caller(self) -> None:
        """Mirrors `setgen.answers`'s own "cannot reach the network" discipline: the replay
        transport this module defaults to imports nothing CALLABLE from `pipeline.llm_caller`, so
        a run driven by `run_batch` without an explicit `call=` cannot make a live request. Scoped
        to actual `import`/call syntax, not a bare substring match — the module's own docstring
        prose mentions `pipeline.llm_caller.call_model` by name when explaining what `call=`
        overrides, which a plain substring check would misread as a real import."""
        source = Path(authored_mod.__file__).read_text(encoding="utf-8")
        self.assertNotIn("import call_model", source)
        self.assertNotIn(" call_model(", source)
        self.assertNotIn("live_caller(", source)


class CombinationLiveTransportTests(unittest.TestCase):
    """The CLI must bind the existing injected graph seam to a live model caller."""

    def test_write_with_endpoint_uses_the_live_caller(self) -> None:
        import tempfile

        tuning = _real_tuning()
        supply = _real_supply()
        plan = run_mod.plan_run(shape="strain", tuning=tuning, supply=supply)
        plan = dataclasses.replace(plan, subjects=plan.subjects[:1])
        with tempfile.TemporaryDirectory() as temp:
            args = argparse.Namespace(
                kind="combination",
                out_dir=temp, answers="", endpoint="http://127.0.0.1:9876/v1/chat/completions",
                model="test-live-model", allow_production_tree=False, ledger="",
                authored_utc="1970-01-01T00:00:00Z")
            result = SimpleNamespace(persisted=[object()], outcomes=[], to_dict=dict)
            with patch("seedsmith.adapters.items.combogen.authored.run_batch", return_value=result) as batch:
                done = cli_mod._cmd_items_combination_write(args, plan=plan, tuning=tuning)

        self.assertEqual(0, done)
        kwargs = batch.call_args.kwargs
        self.assertEqual("test-live-model", kwargs["model"])
        self.assertIsNotNone(kwargs["call"])


# ------------------------------------------------------------------------------------------------
# migrate.py -- SSH2.3's own `--write` verb: deterministic, idempotent, ledgered retirement.
# Every test here uses an INJECTED temp `legacy_path`/`ledger_path` -- `retire_legacy_partition`
# performs a real filesystem delete, and the real `data/seed/items/socket-words/sockwords.json` is
# retired for real only by the owner-sequenced SSH2.6, never by a test.
# ------------------------------------------------------------------------------------------------
class MigrateWriteTests(unittest.TestCase):
    def setUp(self) -> None:
        import tempfile

        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.legacy_path = Path(self._tmp.name) / "sockwords.json"
        self.legacy_path.write_text(
            json.dumps({"kind": "socket-word", "entries": []}), encoding="utf-8")
        self.ledger_path = Path(self._tmp.name) / "combogen-migrate.ledger.json"

    def test_the_migrate_verb_writes_a_ledger_record_and_is_idempotent(self) -> None:
        record1, deleted1 = migrate_mod.retire_legacy_partition(
            legacy_path=self.legacy_path, ledger_path=self.ledger_path)
        self.assertTrue(deleted1)
        self.assertFalse(self.legacy_path.exists())
        self.assertEqual(record1.legacy_kind, migrate_mod.LEGACY_KIND)
        self.assertEqual(record1.target_kind, migrate_mod.TARGET_KIND)
        self.assertEqual(record1.ruling, migrate_mod.RETIREMENT_RULING)
        ledger_bytes_after_first = self.ledger_path.read_bytes()

        # Idempotent: a second call finds the file already gone (no-op delete, never an error) and
        # reproduces the IDENTICAL ledger record -- byte-identical, not merely "also succeeds".
        record2, deleted2 = migrate_mod.retire_legacy_partition(
            legacy_path=self.legacy_path, ledger_path=self.ledger_path)
        self.assertFalse(deleted2)
        self.assertEqual(record1, record2)
        self.assertEqual(ledger_bytes_after_first, self.ledger_path.read_bytes())

    def test_the_record_is_readable_through_run_ledgers_own_api_and_carries_no_clock_field(self) -> None:
        # "still a verb, never a hand deletion": the retirement is READABLE back through
        # RunLedger's real API, not a bespoke second reader; and it carries no wall-clock field --
        # that absence is exactly what keeps a second --write byte-identical.
        migrate_mod.retire_legacy_partition(
            legacy_path=self.legacy_path, ledger_path=self.ledger_path)
        ledger = RunLedger(self.ledger_path)
        row = ledger.read_done()[migrate_mod.RETIREMENT_LEDGER_KEY]
        self.assertEqual(row["ruling"], migrate_mod.RETIREMENT_RULING)
        self.assertNotIn("deletedAtUtc", row)
        self.assertNotIn("timestamp", row)

    def test_deleting_an_already_gone_file_is_a_no_op_not_an_error(self) -> None:
        self.legacy_path.unlink()  # simulate a prior retirement outside this ledger's own history
        record, deleted = migrate_mod.retire_legacy_partition(
            legacy_path=self.legacy_path, ledger_path=self.ledger_path)
        self.assertFalse(deleted)
        self.assertEqual(record.legacy_kind, migrate_mod.LEGACY_KIND)


class TuningRevisionLiteralTests(unittest.TestCase):
    """strain-splice-host SSH5.6/SSH7.1/SSH8.4: each revision is ONE path constant in its owning
    adapter. Only actual PATH joins are scanned — a message, docstring or comment naming the file is
    prose, not a reader."""

    @staticmethod
    def _is_canonical_assignment(tokens, literal_index: int, constant: str) -> bool:
        import tokenize

        for index in range(literal_index - 1, -1, -1):
            token = tokens[index]
            if token.type == tokenize.NAME and token.string == constant:
                return (index + 1 < len(tokens) and
                        tokens[index + 1].type == tokenize.OP and
                        tokens[index + 1].string == "=")
            if token.type == tokenize.OP and token.string == ";":
                break
        return False

    def _revision_path_offenders(
            self, domains: tuple[str, ...], canonical: dict[tuple[str, str], str]):
        import ast
        import io
        import re
        import tokenize

        package = _owned("tools/seedsmith/seedsmith")
        domain_pattern = re.compile(
            rf"(?:{'|'.join(re.escape(domain) for domain in domains)})"
            r"\.v\d+\.json\Z")
        ignored = {
            tokenize.COMMENT, tokenize.ENCODING, tokenize.INDENT, tokenize.DEDENT,
            tokenize.NL, tokenize.NEWLINE, tokenize.ENDMARKER,
        }
        offenders: list[str] = []
        canonical_hits = {key: 0 for key in canonical}

        for path in sorted(package.rglob("*.py")):
            rel = path.relative_to(REPO_ROOT).as_posix()
            source = path.read_text(encoding="utf-8")
            tokens = [
                token for token in tokenize.generate_tokens(io.StringIO(source).readline)
                if token.type not in ignored
            ]
            for index, token in enumerate(tokens):
                if token.type != tokenize.STRING:
                    continue
                try:
                    value = ast.literal_eval(token.string)
                except (SyntaxError, ValueError):
                    continue
                if not isinstance(value, str) or not domain_pattern.fullmatch(value):
                    continue

                previous = tokens[index - 1] if index else None
                is_path_join = (
                    previous is not None and previous.type == tokenize.OP and
                    previous.string == "/")
                if (previous is not None and previous.type == tokenize.OP and
                        previous.string == "(" and index >= 2):
                    is_path_join = (
                        tokens[index - 2].type == tokenize.NAME and
                        tokens[index - 2].string == "Path")
                if not is_path_join:
                    continue

                domain = value.split(".v", 1)[0]
                key = (rel, domain)
                expected_constant = canonical.get(key)
                if (expected_constant is not None and
                        self._is_canonical_assignment(tokens, index, expected_constant)):
                    canonical_hits[key] += 1
                    continue
                offenders.append(
                    f"{rel}:{token.start[0]}: {source.splitlines()[token.start[0] - 1].strip()}")

        return offenders, canonical_hits

    def test_no_other_python_module_names_a_sockets_revision_path_literal(self):
        canonical = {
            ("tools/seedsmith/seedsmith/adapters/items/combogen/tuning.py", "sockets"):
                "SOCKETS_PATH",
        }
        offenders, canonical_hits = self._revision_path_offenders(("sockets",), canonical)
        self.assertEqual([], offenders)
        self.assertEqual({key: 1 for key in canonical}, canonical_hits)

    def test_no_other_python_module_names_a_strain_splice_or_materials_revision_path_literal(self):
        canonical = {
            ("tools/seedsmith/seedsmith/adapters/items/combogen/tuning.py", "strain-splice"):
                "STRAIN_SPLICE_PATH",
            ("tools/seedsmith/seedsmith/adapters/items/recipegen/brief.py", "materials"):
                "MATERIALS_TUNING_PATH",
        }
        offenders, canonical_hits = self._revision_path_offenders(
            ("strain-splice", "materials"), canonical)
        self.assertEqual([], offenders)
        self.assertEqual({key: 1 for key in canonical}, canonical_hits)


class GeometricCeilingTests(unittest.TestCase):
    """SSH6.1 (combo-budget §2): the circuit-aware geometry reading, and the two ports' agreement."""

    def test_python_and_csharp_readings_agree_on_the_shipped_tuning(self):
        import re

        # The two ports agree because they share ONE constant and ONE formula: the C#
        # `SocketLimits.SocketCircuitSize` is read from its source and compared to CIRCUIT_SIZE, then
        # both readings are recomputed over the same shipped sockets file.
        csharp = (_owned("src/FusionRpg.Core/Items/Sockets/SocketTuning.cs"))\
            .read_text(encoding="utf-8")
        match = re.search(r"SocketCircuitSize = (\d+)", csharp)
        self.assertIsNotNone(match, "the C# SocketCircuitSize constant was not found")
        self.assertEqual(int(match.group(1)), tuning_mod.CIRCUIT_SIZE)

        tuning = tuning_mod.load()
        # Whole table: Σ floor(ceiling / CIRCUIT_SIZE).
        self.assertEqual(
            sum(c // tuning_mod.CIRCUIT_SIZE for c in tuning.socket_ceiling.values()),
            tuning.geometric_combo_ceiling(tuple(tuning.socket_ceiling)))
        # Default: the OFFERED host set, a subset of the table.
        self.assertEqual(
            sum(tuning.socket_ceiling[r] // tuning_mod.CIRCUIT_SIZE for r in tuning.host_roles()),
            tuning.geometric_combo_ceiling())
        # Reachability is the same sum over the admitted roles (an unpinned recipe admits every one).
        self.assertEqual(tuning.geometric_combo_ceiling(tuple(tuning.socket_ceiling)),
                         tuning.reachable_combo_ceiling(tuple(tuning.socket_ceiling)))


# ── SSH6.4: the readable combo-budget report, over the ONE C# computation ────────────────────────

class ComboBudgetReportTests(unittest.TestCase):
    """strain-splice-host SSH6.4 (spec-combo-budget §3). The report renders the JSON the C#
    `ComboPricing` computation writes; `power(c,k)` is never computed here, because a second
    implementation of the price of an atom is the defect the dump exists to prevent."""

    @staticmethod
    def _materials() -> dict:
        return json.loads(tuning_mod.latest_materials_path().read_text(encoding="utf-8"))

    @staticmethod
    def _recipes() -> list[dict]:
        document = json.loads((_owned("data/seed/items/recipes/recipes.json")).read_text(encoding="utf-8"))
        return list(document.get("entries") or ())

    def _souls_leg(self, operation: str, rung_index: int) -> int:
        """One operation's cheapest souls leg, resolved the way the C# resolver does: the recipe's own
        authored band scales `coefficient x (rungIndex + 1)`, ceilinged, never free. A recipe that
        authors no `soulsCostBand` spends no souls on that leg — which is how the upcycle chain's
        souls term is zero today."""
        materials = self._materials()
        leg = materials["operations"][operation]["souls"]
        bands = materials["costBandMultiplierPerMille"]
        candidates = [entry["soulsCostBand"] for entry in self._recipes()
                      if entry.get("operation") == operation and entry.get("soulsCostBand")]
        if not candidates:
            return 0
        return min(max(1, -(-leg["coefficient"] * (rung_index + 1) * bands[band] // 1000))
                   for band in candidates)

    def _gem_souls(self, tier: int) -> int:
        """`gem(t)` = the spec's own term: `forge-gem` at the output tier, or the upcycle chain from the
        tier below when that is cheaper (SSH6.2's `GemSouls`, re-derived here for parity)."""
        forge = self._souls_leg("forge-gem", tier - 1)
        if tier <= 1:
            return forge
        sockets = json.loads(tuning_mod.SOCKETS_PATH.read_text(encoding="utf-8"))
        chain = (sockets["insertTiers"]["upcycleInputPerOutput"] * self._gem_souls(tier - 1)
                 + self._souls_leg("upcycle", 0))
        return min(forge, chain)

    def test_price_floor_parity_python_and_csharp_agree_on_a_gem_only_cell(self) -> None:
        """The acceptance's parity test: the C# dump's floor for a gem-only cell equals an INDEPENDENT
        Python resolution of the same spec term, leg by leg and in total."""
        dump = tuning_mod.combo_budget_dump()
        cell = next(c for c in dump["cells"] if c["legs"] and
                    all(leg["name"] == "gem" for leg in c["legs"]))

        expected = [self._gem_souls(leg["rungIndex"] + 1) for leg in cell["legs"]]
        self.assertEqual(expected, [leg["souls"] for leg in cell["legs"]])
        self.assertEqual(sum(expected), cell["priceFloorSouls"])
        # A gem-only floor is the four gems and nothing else: no bore, no imbue.
        self.assertEqual(tuning_mod.load().ingredient_count, len(cell["legs"]))

    def test_the_report_names_the_failing_cells_and_the_lever_that_fixes_them(self) -> None:
        """A red run is a result: the cells cheap enough to be a cheaper route to power than a better
        base are named, with the derived coefficient, and the exit code is non-zero."""
        passing = {"comboId": "combo.ok", "tier": 1, "attuned": False, "power": 1,
                   "priceFloorSouls": 180, "legs": [], "floorRungIndex": 4,
                   "ratioMilli": 5, "referenceMilli": 9166, "passes": True}
        failing = {"comboId": "combo.dear", "tier": 1, "attuned": False, "power": 22800,
                   "priceFloorSouls": 180, "legs": [], "floorRungIndex": 4,
                   "ratioMilli": 126666, "referenceMilli": 9166, "passes": False}
        dump = {
            "maxRatioToRarityRouteMilli": 1000,
            "geometry": {"allRoles": 13, "reachable": 13,
                         "byRole": [{"role": "core-guard", "ceiling": 8, "circuits": 2}]},
            "reference": {"fromRung": "sprout", "toRung": "grafted", "deltaPower": 1100,
                          "elevateSouls": 120},
            "excludedSteps": [],
            "recipeRefusals": [],
            "cells": [passing, failing],
            "refused": [],
            "derivation": {
                "levers": [{"lever": "forge-gem", "currentCoefficient": 30, "derivedCoefficient": 415}],
                "cells": [{"comboId": "combo.dear", "levers": ["forge-gem"],
                           "smallestLever": "forge-gem", "requiredCoefficient": 415}],
                "unfixable": [],
            },
        }
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code = cli_mod._print_combo_budget_report(dump, _owned("data/seed/items"))
        text = buffer.getvalue()
        self.assertEqual(cli_mod.EXIT_GAP, code)
        self.assertIn("combo.dear", text)
        self.assertIn("FAIL", text)
        self.assertIn("forge-gem", text)
        self.assertIn("30 -> 415", text)

        # The same dump with every cell passing exits clean and says so.
        dump["cells"] = [passing]
        dump["derivation"]["cells"] = []
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code = cli_mod._print_combo_budget_report(dump, _owned("data/seed/items"))
        self.assertEqual(cli_mod.EXIT_CLEAN, code)
        self.assertIn("PASS", buffer.getvalue())
class TuningVersionFieldTests(unittest.TestCase):
    """SSH5.10-P2 (c): the internal `version` field is not a revision identity.

    `gk-core/data/tuning/sockets.v2.json` carries `"version": 2` while `sockets.v1.json` carries 3 —
    `publish.py` writes the filename-derived `v{n+1}`, which can move the field backwards. No reader
    may read it; this scan keeps a future one from inheriting the trap.
    """

    def test_no_tuning_loader_reads_the_internal_version_field(self):
        import re

        readers = [
            _owned("tools/seedsmith/seedsmith/adapters/items/combogen/tuning.py"),
            _owned("tools/seedsmith/seedsmith/adapters/items/basetypegen/tuning.py"),
        ]
        read_pattern = re.compile(r'\[\s*["\']version["\']\s*\]|get\(\s*["\']version["\']')
        offenders = []
        for path in readers:
            for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if read_pattern.search(line):
                    offenders.append(f"{path.relative_to(REPO_ROOT)}:{number}")
        self.assertEqual([], offenders)


if __name__ == "__main__":
    unittest.main()


# ── SSH7.3: the Python ladder rules mirror the C# ones ───────────────────────────────────────────

class TierLadderParityTests(unittest.TestCase):
    """The generator's ladder validation, rule for rule against the C#
    `StrainSpliceTuning.ValidateTierLadder` (SSH7.1/SSH7.2). A generator that accepted a ladder the
    runtime refuses would author rungs nothing can reach."""

    def _with_ladder(self, ladder):
        raw = json.loads(tuning_mod.STRAIN_SPLICE_PATH.read_text(encoding="utf-8"))
        raw["recipe"]["tierLadder"] = ladder
        return _tmp_tuning(self, raw)

    def test_the_shipped_file_loads_as_the_one_rung_its_floor_describes(self) -> None:
        tuning = tuning_mod.load()
        rung = tuning.tier_ladder[0]
        self.assertEqual(1, rung.rung)
        self.assertEqual(tuning.min_tier_plan, rung.floors)
        self.assertEqual(0, rung.grant_delta)

    def test_a_published_ladder_replaces_the_mapping_whole(self) -> None:
        ladder = [{"rung": 1, "floors": [1, 1, 2, 2], "grantDelta": 0},
                  {"rung": 2, "floors": [2, 2, 3, 3], "grantDelta": 1}]
        tuning = tuning_mod.load(sockets_path=tuning_mod.SOCKETS_PATH,
                                 strain_splice_path=self._with_ladder(ladder))
        self.assertEqual(2, len(tuning.tier_ladder))
        self.assertEqual((2, 2, 3, 3), tuning.tier_ladder[1].floors)
        self.assertEqual(1, tuning.tier_ladder[1].grant_delta)

    def test_every_rule_the_csharp_validator_enforces_is_enforced_here(self) -> None:
        cases = {
            "floors falling inside one rung": [
                {"rung": 1, "floors": [1, 1, 3, 2], "grantDelta": 0},
                {"rung": 2, "floors": [1, 1, 2, 3], "grantDelta": 1}],
            "a grant delta that does not rise": [
                {"rung": 1, "floors": [1, 1, 2, 2], "grantDelta": 0},
                {"rung": 2, "floors": [1, 1, 2, 3], "grantDelta": 0}],
            "a higher rung asking for less": [
                {"rung": 1, "floors": [1, 1, 3, 4], "grantDelta": 0},
                {"rung": 2, "floors": [1, 1, 2, 4], "grantDelta": 1}],
            "a floor outside the insert ladder": [
                {"rung": 1, "floors": [1, 1, 2, 2], "grantDelta": 0},
                {"rung": 2, "floors": [1, 1, 2, 9], "grantDelta": 1}],
            "a top rung past the atom ladder": [
                {"rung": 1, "floors": [1, 1, 2, 2], "grantDelta": 0},
                {"rung": 2, "floors": [1, 1, 2, 3], "grantDelta": 9}],
            "rung 1 carrying a grant delta": [
                {"rung": 1, "floors": [1, 1, 2, 2], "grantDelta": 1}],
            "a ladder with no rung": [],
        }
        for label, ladder in cases.items():
            with self.subTest(label):
                with self.assertRaises(tuning_mod.ComboTuningError):
                    tuning_mod.load(strain_splice_path=self._with_ladder(ladder))


def _tmp_tuning(testcase, doc: dict):
    import os
    import tempfile
    fd, name = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    path = Path(name)
    path.write_text(json.dumps(doc), encoding="utf-8")
    testcase.addCleanup(path.unlink, missing_ok=True)
    return path
