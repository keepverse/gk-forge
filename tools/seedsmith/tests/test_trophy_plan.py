"""species-gear-chain T34 (`species-materials` b) — the deterministic trophy id planner.

    $env:PYTHONPATH = "gk-forge/tools/seedsmith"; python -m pytest gk-forge/tools/seedsmith/tests/test_trophy_plan.py -q

⭐ **Reconciliation, not a count** (spec-species-materials.md § Design 4 acceptance #1): every
non-excluded species has exactly `perSpecies` ids, every family exactly `perFamily`; scope keys join
back; ids are unique; no scope outside `{species, family}`; totals are PRINTED by `run.py`, never
asserted here as a literal — `RealCorpusReconciliationTests` proves this against the real, committed
`gk-data/packs/fusion/data/seed/items/materials/trophy-registry.json` by re-deriving the expected counts from the same
inputs the planner reads, never from a hard-coded number.
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
import unittest.mock
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from seedsmith.adapters.items.trophyplan import plan as plan_mod  # noqa: E402
from seedsmith.adapters.items.trophyplan import run as run_mod  # noqa: E402
from seedsmith.adapters.items.trophyplan import species as species_mod  # noqa: E402
from seedsmith.adapters.items.trophyplan import tuning as tuning_mod  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[3]


def _write_json(path: Path, doc) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc), encoding="utf-8")


def _write_species_file(path: Path, records: "list[dict]") -> None:
    _write_json(path, records)


class TuningTests(unittest.TestCase):
    """The strict loader — same shape as `distribution_planner.tuning`, plus the unknown-key
    refusal R9 needs (a stale `perGeneral` must be refused BY NAME, never ignored)."""

    def test_a_well_formed_file_loads(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "species-material-run.v1.json"
            _write_json(path, {"schemaVersion": 1, "version": 1, "perSpecies": 2, "perFamily": 8})
            tuning = tuning_mod.load_run_tuning(path)
            self.assertEqual(tuning.per_species, 2)
            self.assertEqual(tuning.per_family, 8)
            self.assertEqual(tuning.version, 1)

    def test_missing_file_refuses_by_name(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "missing.json"
            with self.assertRaises(tuning_mod.TrophyTuningError) as caught:
                tuning_mod.load_run_tuning(path)
            self.assertIn(str(path), str(caught.exception))

    def test_a_stale_pergeneral_key_is_refused_by_name(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "t.json"
            _write_json(path, {"version": 1, "perSpecies": 2, "perFamily": 8, "perGeneral": 0})
            with self.assertRaises(tuning_mod.TrophyTuningError) as caught:
                tuning_mod.load_run_tuning(path)
            self.assertIn("perGeneral", str(caught.exception))

    def test_missing_perspecies_or_perfamily_refuses(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "t.json"
            _write_json(path, {"version": 1, "perFamily": 8})
            with self.assertRaises(tuning_mod.TrophyTuningError):
                tuning_mod.load_run_tuning(path)

    def test_float_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "t.json"
            _write_json(path, {"version": 1, "perSpecies": 2.0, "perFamily": 8})
            with self.assertRaises(tuning_mod.TrophyTuningError):
                tuning_mod.load_run_tuning(path)

    def test_bool_as_int_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "t.json"
            _write_json(path, {"version": 1, "perSpecies": True, "perFamily": 8})
            with self.assertRaises(tuning_mod.TrophyTuningError):
                tuning_mod.load_run_tuning(path)

    def test_numeric_string_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "t.json"
            _write_json(path, {"version": 1, "perSpecies": "2", "perFamily": 8})
            with self.assertRaises(tuning_mod.TrophyTuningError):
                tuning_mod.load_run_tuning(path)

    def test_negative_count_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "t.json"
            _write_json(path, {"version": 1, "perSpecies": -1, "perFamily": 8})
            with self.assertRaises(tuning_mod.TrophyTuningError):
                tuning_mod.load_run_tuning(path)

    def test_the_real_committed_file_loads_at_2_and_8(self) -> None:
        tuning = tuning_mod.load_run_tuning()
        self.assertEqual(tuning.per_species, 2)
        self.assertEqual(tuning.per_family, 8)


class SpeciesLoaderTests(unittest.TestCase):
    """The roster + family-map loaders — the planner's own inputs, never
    `adapters.actions.vocab.load_family_map_keys` (see `species.py`'s own docstring for why)."""

    def test_excluded_species_are_skipped(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "species"
            _write_species_file(root / "a.json", [
                {"speciesId": "KeptOne", "speciesKind": "creature"},
                {"speciesId": "DroppedOne", "speciesKind": "excluded"},
            ])
            roster = species_mod.load_species_roster(root)
            ids = {row.species_id for row in roster}
            self.assertEqual(ids, {"keptone"})

    def test_missing_species_root_refuses_by_name(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "does-not-exist"
            with self.assertRaises(species_mod.TrophyPlanError) as caught:
                species_mod.load_species_roster(root)
            self.assertIn(str(root), str(caught.exception))

    def test_underscore_prefixed_files_are_skipped_as_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "species"
            _write_species_file(root / "a.json", [{"speciesId": "Real", "speciesKind": "creature"}])
            _write_json(root / "_index.json", {"Real": "a.json"})
            roster = species_mod.load_species_roster(root)
            self.assertEqual({row.species_id for row in roster}, {"real"})

    def test_a_record_missing_speciesid_refuses(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "species"
            _write_species_file(root / "a.json", [{"speciesKind": "creature"}])
            with self.assertRaises(species_mod.TrophyPlanError):
                species_mod.load_species_roster(root)

    def test_missing_family_map_refuses_by_name(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "missing.json"
            with self.assertRaises(species_mod.TrophyPlanError) as caught:
                species_mod.load_family_map(path)
            self.assertIn(str(path), str(caught.exception))

    def test_family_map_must_map_to_a_string_array(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "fm.json"
            _write_json(path, {"abc": "flora"})  # scalar, not an array — refused
            with self.assertRaises(species_mod.TrophyPlanError):
                species_mod.load_family_map(path)

    def test_a_non_excluded_species_missing_from_the_family_map_refuses_by_name(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "species"
            _write_species_file(root / "a.json", [
                {"speciesId": "ShippedLate", "speciesKind": "creature"},
            ])
            roster = species_mod.load_species_roster(root)
            with self.assertRaises(species_mod.TrophyPlanError) as caught:
                species_mod.resolve_family_membership(roster, family_map={})
            self.assertIn("ShippedLate", str(caught.exception))

    def test_a_species_present_with_an_empty_family_list_is_legal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "species"
            _write_species_file(root / "a.json", [
                {"speciesId": "Loner", "speciesKind": "creature"},
            ])
            roster = species_mod.load_species_roster(root)
            membership = species_mod.resolve_family_membership(roster, family_map={"loner": []})
            self.assertEqual(membership, {"loner": ()})

    def test_the_real_family_map_loads_and_every_live_species_resolves(self) -> None:
        roster = species_mod.load_species_roster()
        family_map = species_mod.load_family_map()
        membership = species_mod.resolve_family_membership(roster, family_map)
        self.assertEqual(len(membership), len(roster))


class PlanTests(unittest.TestCase):
    """Pure arithmetic over a synthetic fixture — reconciliation, append-only, determinism."""

    def test_mint_counts_match_persspecies_and_perfamily(self) -> None:
        membership = {"sp1": ("fam1",), "sp2": ("fam1", "fam2")}
        result = plan_mod.plan_trophy_registry(membership, per_species=2, per_family=8)
        by_scope = result.totals()
        self.assertEqual(by_scope["species"], 2 * len(membership))
        self.assertEqual(by_scope["family"], 8 * 2)  # fam1, fam2
        # every scope key joins back
        species_keys = {r.scope_key for r in result.all_rows if r.scope == "species"}
        family_keys = {r.scope_key for r in result.all_rows if r.scope == "family"}
        self.assertEqual(species_keys, set(membership))
        self.assertEqual(family_keys, {"fam1", "fam2"})
        ids = [r.material_id for r in result.all_rows]
        self.assertEqual(len(ids), len(set(ids)), "minted a duplicate id")
        self.assertTrue(all(r.scope in plan_mod.SCOPES for r in result.all_rows))

    def test_a_no_family_species_mints_species_ids_only_and_is_reported(self) -> None:
        membership = {"lonely": (), "social": ("fam1",)}
        result = plan_mod.plan_trophy_registry(membership, per_species=2, per_family=8)
        self.assertEqual(result.species_with_no_family, ("lonely",))
        lonely_rows = [r for r in result.all_rows if r.scope_key == "lonely"]
        self.assertEqual({r.scope for r in lonely_rows}, {"species"})
        self.assertEqual(len(lonely_rows), 2)

    def test_excluded_species_never_reach_the_planner(self) -> None:
        # The planner itself trusts its caller's `family_membership` completely — exclusion is
        # `species.load_species_roster`'s own job (proven above). This test documents that division:
        # an id absent from `family_membership` mints nothing, whatever the reason for its absence.
        membership = {"kept": ("fam1",)}
        result = plan_mod.plan_trophy_registry(membership, per_species=2, per_family=8)
        self.assertEqual({r.scope_key for r in result.all_rows if r.scope == "species"}, {"kept"})

    def test_lowering_keeps_issued_ids_raising_appends_without_renumbering(self) -> None:
        membership = {"sp1": ()}
        first = plan_mod.plan_trophy_registry(membership, per_species=3, per_family=8)
        self.assertEqual(sorted(r.slot for r in first.all_rows), [1, 2, 3])

        lowered = plan_mod.plan_trophy_registry(
            membership, per_species=1, per_family=8, existing_rows=first.all_rows)
        self.assertEqual(lowered.new_rows, ())
        self.assertEqual(sorted(r.slot for r in lowered.all_rows), [1, 2, 3],
                         "lowering perSpecies must never delete an already-issued id")

        raised = plan_mod.plan_trophy_registry(
            membership, per_species=5, per_family=8, existing_rows=lowered.all_rows)
        self.assertEqual(sorted(r.slot for r in raised.new_rows), [4, 5],
                         "raising must append from the next free slot, never renumber")
        self.assertEqual(sorted(r.slot for r in raised.all_rows), [1, 2, 3, 4, 5])

    def test_a_second_run_over_the_same_inputs_is_byte_identical(self) -> None:
        membership = {f"sp{i}": (f"fam{i % 3}",) for i in range(12)}
        first = plan_mod.plan_trophy_registry(membership, per_species=2, per_family=8)
        second = plan_mod.plan_trophy_registry(
            membership, per_species=2, per_family=8, existing_rows=first.all_rows)
        self.assertEqual(second.new_rows, ())
        self.assertEqual(first.all_rows, second.all_rows)

    def test_id_grammar_matches_the_spec(self) -> None:
        self.assertEqual(plan_mod.compose_id("species", "abyssswordstar", 1),
                         "trophy.species.abyssswordstar.1")
        self.assertEqual(plan_mod.compose_id("family", "flora", 8), "trophy.family.flora.8")
        with self.assertRaises(plan_mod.TrophyRegistryError):
            plan_mod.compose_id("general", "x", 1)  # R9: no third scope word


class TrophyRowSerializationTests(unittest.TestCase):
    def test_round_trip(self) -> None:
        row = plan_mod.TrophyRow(material_id="trophy.species.foo.1", scope="species",
                                 scope_key="foo", slot=1)
        self.assertEqual(plan_mod.TrophyRow.from_dict(row.to_dict()), row)

    def test_a_materialid_disagreeing_with_its_own_scope_slot_is_refused(self) -> None:
        bad = {"materialId": "trophy.species.foo.2", "scope": "species", "scopeKey": "foo", "slot": 1}
        with self.assertRaises(plan_mod.TrophyRegistryError):
            plan_mod.TrophyRow.from_dict(bad)

    def test_scope_outside_the_closed_vocabulary_is_refused(self) -> None:
        bad = {"materialId": "trophy.general.foo.1", "scope": "general", "scopeKey": "foo", "slot": 1}
        with self.assertRaises(plan_mod.TrophyRegistryError):
            plan_mod.TrophyRow.from_dict(bad)


class RealCorpusReconciliationTests(unittest.TestCase):
    """Read-only against the REAL, committed registry — reconciliation, never a population count."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.roster = species_mod.load_species_roster()
        cls.family_map = species_mod.load_family_map()
        cls.membership = species_mod.resolve_family_membership(cls.roster, cls.family_map)
        cls.tuning = tuning_mod.load_run_tuning()
        cls.registry_rows = run_mod.load_registry()

    def test_every_species_has_exactly_persspecies_ids(self) -> None:
        by_species = {}
        for row in self.registry_rows:
            if row.scope == "species":
                by_species.setdefault(row.scope_key, set()).add(row.slot)
        self.assertEqual(set(by_species), set(self.membership))
        for species_id, slots in by_species.items():
            self.assertEqual(slots, set(range(1, self.tuning.per_species + 1)),
                             f"{species_id} has slots {sorted(slots)}")

    def test_every_family_has_exactly_perfamily_ids(self) -> None:
        all_families = {f for families in self.membership.values() for f in families}
        by_family = {}
        for row in self.registry_rows:
            if row.scope == "family":
                by_family.setdefault(row.scope_key, set()).add(row.slot)
        # OWNER RULING 2026-10-04: the registry is APPEND-ONLY, so this is a SUPERSET check, not
        # set equality. Exact equality asserted a property the generator cannot hold:
        # `plan_trophy_registry` only ever appends (`plan.py`'s `_mint_for_scope` says "never
        # renumbers, never removes", and `all_rows = existing_rows + new_rows` keeps every
        # existing row verbatim), so a family retired from the vocabulary leaves its rows behind
        # FOREVER, by construction rather than by accident.
        #
        # THE COST, restated here so it travels with the code: this assertion can no longer catch
        # a row belonging to a RETIRED family. A row minted for a family that no longer exists is
        # invisible to it from now on. What it still proves is the half that ships — every LIVE
        # family has rows — which is what the first assertion below checks.
        missing = all_families - set(by_family)
        self.assertEqual(
            missing, set(),
            f"{len(missing)} live family/families have no trophy row at all: {sorted(missing)[:10]}")
        for family_id, slots in by_family.items():
            self.assertEqual(slots, set(range(1, self.tuning.per_family + 1)),
                             f"{family_id} has slots {sorted(slots)}")

    def test_ids_are_unique_and_scope_is_closed(self) -> None:
        ids = [row.material_id for row in self.registry_rows]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertTrue(all(row.scope in plan_mod.SCOPES for row in self.registry_rows))

    def test_replanning_the_real_corpus_is_a_noop(self) -> None:
        result = plan_mod.plan_trophy_registry(
            self.membership, per_species=self.tuning.per_species, per_family=self.tuning.per_family,
            existing_rows=self.registry_rows)
        self.assertEqual(result.new_rows, (), "the committed registry should already be current")


class CliTests(unittest.TestCase):
    """`main()`'s flag handling — `build_plan`/`write_registry` are exercised directly above; this
    only proves `--check`/`--dry-run`/`--write` route a `PlanResult` to the right exit code/output."""

    def test_check_fails_when_new_rows_are_pending(self) -> None:
        fake = plan_mod.PlanResult(all_rows=(), new_rows=(
            plan_mod.TrophyRow("trophy.species.x.1", "species", "x", 1),), species_with_no_family=())
        with unittest.mock.patch.object(run_mod, "build_plan", return_value=fake):
            self.assertEqual(run_mod.main(["--check"]), 1)

    def test_check_passes_when_up_to_date(self) -> None:
        fake = plan_mod.PlanResult(all_rows=(), new_rows=(), species_with_no_family=())
        with unittest.mock.patch.object(run_mod, "build_plan", return_value=fake):
            self.assertEqual(run_mod.main(["--check"]), 0)

    def test_write_persists_the_full_plan(self) -> None:
        rows = (plan_mod.TrophyRow("trophy.species.x.1", "species", "x", 1),)
        fake = plan_mod.PlanResult(all_rows=rows, new_rows=rows, species_with_no_family=())
        with tempfile.TemporaryDirectory() as tmp:
            out_path = Path(tmp) / "registry.json"
            with unittest.mock.patch.object(run_mod, "build_plan", return_value=fake), \
                unittest.mock.patch.object(run_mod, "REGISTRY_PATH", out_path):
                self.assertEqual(run_mod.main(["--write"]), 0)
            written = run_mod.load_registry(out_path)
            self.assertEqual(written, rows)

    def test_a_refused_input_is_reported_and_exits_nonzero(self) -> None:
        with unittest.mock.patch.object(
                run_mod, "build_plan", side_effect=species_mod.TrophyPlanError("boom")):
            self.assertEqual(run_mod.main(["--dry-run"]), 1)


if __name__ == "__main__":  # pragma: no cover - dev entrypoint
    unittest.main()
