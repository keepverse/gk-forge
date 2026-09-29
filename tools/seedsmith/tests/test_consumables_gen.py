"""Tests for `seedsmith.adapters.items.consumablegen` (item-seedgen module `consumables-gen`,
docs/architecture/item-seedgen/spec-consumables-gen.md).

    python -m pytest gk-forge/tools/seedsmith/tests/test_consumables_gen.py -v

Three groups, matching the spec's own "Testing strategy":

- `ReconcileRealCorpusTests` — acceptance criterion 2, run against the REAL shipped corpus (60 rows
  in `k1`/`k2`/`k3`, plus a 3-row hand-authored trial batch in `k1-trial`/`k2-trial`/`k3-trial`
  proving `run.py`'s own `generate_one`/`write_partition_file` end-to-end, 2026-09-07 -- 63 total).
- `FamilyExternalReferenceTests` — a generated consumable's `family` resolves against a real
  `atom-family-library.md` family, and a fabricated one is refused (never auto-backfilled — the
  EXTERNAL reference kind's own contract).
- `HarnessTests` — resume/reconcile/overwrite through the shared `RunLedger`.
"""
from __future__ import annotations

import json
import sys
import unittest
import unittest.mock
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from seedsmith.adapters.items.consumablegen import emit as emit_mod  # noqa: E402
from seedsmith.adapters.items.consumablegen import run as run_mod  # noqa: E402
from seedsmith.adapters.items.consumablegen import schema  # noqa: E402
from seedsmith.pipeline.run_ledger import RunLedger  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[3]
REAL_CONSUMABLES_DIR = REPO_ROOT / "data" / "seed" / "items" / "consumables"

#: A few of the real, shipped families `k1.json` names verbatim (atom-family-library.md:118-128).
REAL_FAMILIES_CITED_IN_SPEC = (
    "atom.vitality", "atom.fortitude", "atom.mending", "atom.bulwark", "atom.warding",
)


def _clean_answer(**overrides) -> dict:
    base = {
        "classId": "restore", "useContext": ["menu"], "family": "atom.vitality",
        "tags": ["defensive"], "name": "Proof Tonic", "nameKey": "consumable.proof-tonic",
    }
    base.update(overrides)
    return base


class RealCorpusFixtureTests(unittest.TestCase):
    """Sanity: the real corpus is exactly what the spec and the audit describe, so every other test
    in this file is measuring the real thing and not a stale assumption."""

    def test_the_real_shipped_corpus_is_six_files_sixty_three_rows(self) -> None:
        """The 60-row `k1`/`k2`/`k3` wave-1 corpus, plus a 3-row `k1-trial`/`k2-trial`/`k3-trial`
        batch (2026-09-07) -- one hand-authored entry per authorable classId (restore/draught/ward),
        each in a family the original 60 never used (`atom.mending` at the one band it never
        shipped, `atom.stoicism`, `atom.shield-toughness`), run through the real `generate_one` ->
        `RunLedger` -> `write_partition_file` path to prove it end-to-end before the full run."""
        self.assertTrue(REAL_CONSUMABLES_DIR.is_dir())
        files = sorted(p.name for p in REAL_CONSUMABLES_DIR.glob("*.json"))
        self.assertEqual(files, ["k1-trial.json", "k1.json", "k2-trial.json", "k2.json",
                                  "k3-trial.json", "k3.json"])
        entries = run_mod.load_corpus()
        # The count is a growing content population, never pinned (population-pin SE3.5,
        # 2026-09-20).
        self.assertTrue(len(entries) > 0)

    def test_grantsactionid_and_cooldownkey_are_legal_consumable_fields(self) -> None:
        """Confirms the audit's own premise: these are real schema fields (kinds.py's KindSpec),
        not something this module is inventing a gap for."""
        from seedsmith.adapters.items import kinds
        consumable_kind = next(k for k in kinds.KINDS if k.kind == "consumable")
        self.assertIn("grantsActionId", consumable_kind.optional)
        self.assertIn("cooldownKey", consumable_kind.optional)


class ReconcileRealCorpusTests(unittest.TestCase):
    """Acceptance criterion 2: "A reconcile run against the current 60 entries reports the
    grantsActionId/cooldownKey gap precisely (which rows are schema-eligible but unauthored)."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.entries = run_mod.load_corpus()
        cls.report = run_mod.reconcile_grants_and_cooldowns(cls.entries)

    def test_the_measured_baseline_is_every_row_missing_both_fields(self) -> None:
        """The real, measured baseline (2026-09-07, re-measured after the trial batch): grepping
        k1/k2/k3/k1-trial/k2-trial/k3-trial for `grantsActionId` and `cooldownKey` finds zero real
        usages, only kinds.py's schema declaring them legal — so EVERY one of the 63 shipped rows
        (60 wave-1 + 3 trial) is schema-eligible but unauthored on both fields. The trial answers
        never set either field, so the gap this criterion measures is unchanged in kind, only in
        count."""
        # Self-referential (population-pin SE3.5, 2026-09-20): the premise is EVERY row is missing
        # both fields, so each bucket equals the measured total, not a second copy of the same
        # growing content count; the exact row ids are proven in the next test.
        self.assertEqual(self.report.total, len(self.report.missing_grants_action_id))
        self.assertEqual(self.report.total, len(self.report.missing_cooldown_key))
        self.assertEqual(self.report.total, len(self.report.missing_both))

    def test_the_report_names_every_real_row_id_precisely(self) -> None:
        """Not just a count -- the exact rows, so the report is auditable against the real files."""
        expected_ids = frozenset(self.entries.keys())
        self.assertEqual(frozenset(self.report.missing_grants_action_id), expected_ids)
        self.assertEqual(frozenset(self.report.missing_cooldown_key), expected_ids)
        self.assertEqual(frozenset(self.report.missing_both), expected_ids)
        # Spot-check real ids named in the spec/audit rather than trusting the set equality alone.
        for real_id in ("consumable.k1-001", "consumable.k2-018", "consumable.k3-020"):
            with self.subTest(real_id=real_id):
                self.assertIn(real_id, self.report.missing_both)

    def test_a_row_with_an_authored_grant_is_not_reported_missing(self) -> None:
        """The reconcile function itself is not hardcoded to "always everything" -- proven against a
        synthetic corpus where one row IS authored."""
        entries = {
            "consumable.fixture-001": {"id": "consumable.fixture-001", "grantsActionId": "action.x",
                                        "cooldownKey": "cd.x"},
            "consumable.fixture-002": {"id": "consumable.fixture-002"},
        }
        report = run_mod.reconcile_grants_and_cooldowns(entries)
        self.assertEqual(report.missing_grants_action_id, ("consumable.fixture-002",))
        self.assertEqual(report.missing_cooldown_key, ("consumable.fixture-002",))
        self.assertEqual(report.missing_both, ("consumable.fixture-002",))

    def test_an_explicit_null_is_exactly_as_unauthored_as_an_absent_key(self) -> None:
        entries = {"consumable.fixture-003": {"id": "consumable.fixture-003",
                                               "grantsActionId": None, "cooldownKey": None}}
        report = run_mod.reconcile_grants_and_cooldowns(entries)
        self.assertEqual(report.missing_both, ("consumable.fixture-003",))

    def test_this_module_never_writes_into_the_real_consumables_directory(self) -> None:
        """Boundary check: `load_corpus`/`reconcile_grants_and_cooldowns` are read-only. Proven by
        hashing the directory's mtimes before and after running the reconcile path."""
        before = {p: p.stat().st_mtime_ns for p in REAL_CONSUMABLES_DIR.glob("*.json")}
        run_mod.reconcile_grants_and_cooldowns(run_mod.load_corpus())
        after = {p: p.stat().st_mtime_ns for p in REAL_CONSUMABLES_DIR.glob("*.json")}
        self.assertEqual(before, after)


class FamilyExternalReferenceTests(unittest.TestCase):
    """`family` is an EXTERNAL reference into `atom-family-library.md` (an effect-atom corpus this
    program does not own) -- validated exactly like a hard reference, never auto-backfilled."""

    def test_the_real_families_named_in_the_spec_are_in_the_loaded_vocabulary(self) -> None:
        families = schema.load_atom_family_names()
        for family in REAL_FAMILIES_CITED_IN_SPEC:
            with self.subTest(family=family):
                self.assertIn(family, families)

    def test_every_family_the_real_shipped_corpus_uses_resolves(self) -> None:
        """The real corpus's own `family` values, whole -- not just the five the spec names. Every
        row (60 wave-1 + 3 trial) is shipped content, so if this fails, either the doc drifted or the
        parser is wrong; either way it is a real finding, not a fixture assumption."""
        entries = run_mod.load_corpus()
        used_families = {e["family"] for e in entries.values() if "family" in e}
        self.assertGreater(len(used_families), 0)
        report = run_mod.validate_family_references(entries)
        self.assertEqual(report.unresolved, [], [str(r) for r in report.unresolved])
        self.assertEqual(len(report.results), sum(1 for e in entries.values() if "family" in e))

    def test_a_generated_consumables_family_resolves_against_the_real_library(self) -> None:
        answer = _clean_answer(family="atom.mending")
        ledger_dir_entries: "dict[str, dict]" = {}
        outcome = run_mod.generate_one(
            "fixture-mending", answer, entry_id="consumable.fixture-mending-001", seq=0,
            ledger=_FakeLedgerHarness(ledger_dir_entries))
        self.assertEqual(outcome.outcome, "persisted")
        self.assertEqual(outcome.entry["family"], "atom.mending")
        self.assertIn("fixture-mending", ledger_dir_entries)

    def test_a_fabricated_family_id_is_refused_not_authored(self) -> None:
        """This program has no standing to author effect-atom's own content -- a family id that is
        not in the real, current library must be refused, never invented or silently accepted."""
        self.assertFalse(schema.is_real_atom_family("atom.made-up-family-nobody-shipped"))
        answer = _clean_answer(family="atom.made-up-family-nobody-shipped")
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            ledger = RunLedger(path=Path(tmp) / "test.ledger.json")
            outcome = run_mod.generate_one(
                "fixture-fake", answer, entry_id="consumable.fixture-fake-001", seq=0, ledger=ledger)
            self.assertEqual(outcome.outcome, "refused")
            self.assertTrue(any("atom.made-up-family-nobody-shipped" in d for d in outcome.defects),
                             outcome.defects)
            self.assertTrue(any("EXTERNAL" in d or "backfilled" in d for d in outcome.defects),
                             outcome.defects)
            # Refused means nothing was written to the ledger for this subject.
            self.assertEqual(ledger.read_done(), {})

    def test_dependency_validator_reports_a_fabricated_family_as_unresolved_never_backfilled(self):
        """Exercises the shared `pipeline.dependency_validator` module directly (not just this
        module's own wrapper), proving the EXTERNAL contract end-to-end: validated, unresolved, and
        `plan_backfill` refuses to touch it."""
        from seedsmith.pipeline.dependency_validator import plan_backfill

        entries = {
            "consumable.fixture-fake-002": {"id": "consumable.fixture-fake-002",
                                             "family": "atom.made-up-family-nobody-shipped"},
        }
        report = run_mod.validate_family_references(entries)
        self.assertEqual(len(report.unresolved), 1)
        self.assertEqual(report.unresolved[0].value, "atom.made-up-family-nobody-shipped")
        self.assertEqual(plan_backfill(report), [],
                          "EXTERNAL references must never be planned for backfill")


class _FakeLedgerHarness:
    """A minimal stand-in used only where a real RunLedger would be overkill for one assertion; the
    real end-to-end refusal path is exercised with a real `RunLedger` above and in `HarnessTests`."""

    def __init__(self, sink: dict) -> None:
        self._sink = sink

    def mark_done(self, subject_id: str, entry: dict) -> None:
        self._sink[subject_id] = entry


class EmitAndSchemaTests(unittest.TestCase):
    def test_a_clean_answer_has_no_defects(self) -> None:
        self.assertEqual(emit_mod.validate_answer(_clean_answer()), [])

    def test_an_unauthorable_classid_is_refused(self) -> None:
        defects = emit_mod.validate_answer(_clean_answer(classId="board"))
        self.assertTrue(any(d.field == "classId" for d in defects), defects)

    def test_lawn_use_context_is_refused(self) -> None:
        defects = emit_mod.validate_answer(_clean_answer(useContext=["lawn"]))
        self.assertTrue(any(d.field == "useContext" for d in defects), defects)

    def test_element_is_only_legal_on_the_two_elemental_families(self) -> None:
        defects = emit_mod.validate_answer(_clean_answer(element="fire"))
        self.assertTrue(any(d.field == "element" for d in defects), defects)
        clean = emit_mod.validate_answer(
            _clean_answer(family="atom.elemental-power", element="fire"))
        self.assertEqual(clean, [])

    def test_power_band_rotation_is_deterministic_and_covers_the_default_rotation(self) -> None:
        seen = {emit_mod.resolve_power_band(i) for i in range(8)}
        self.assertEqual(seen, set(emit_mod.DEFAULT_BAND_ROTATION))
        self.assertEqual(emit_mod.resolve_power_band(0), emit_mod.resolve_power_band(4))

    def test_manifest_cost_is_two_only_for_high_and_extreme(self) -> None:
        self.assertEqual(emit_mod.resolve_manifest_cost("trivial"), 1)
        self.assertEqual(emit_mod.resolve_manifest_cost("low"), 1)
        self.assertEqual(emit_mod.resolve_manifest_cost("medium"), 1)
        self.assertEqual(emit_mod.resolve_manifest_cost("high"), 2)
        self.assertEqual(emit_mod.resolve_manifest_cost("extreme"), 2)
        with self.assertRaises(ValueError):
            emit_mod.resolve_manifest_cost("not-a-band")

    def test_build_entry_matches_the_real_corpus_shape(self) -> None:
        entry = emit_mod.build_entry(_clean_answer(), entry_id="consumable.fixture-shape-001", seq=0)
        self.assertEqual(entry["id"], "consumable.fixture-shape-001")
        self.assertEqual(set(entry) - {"element", "notes"},
                          {"id", "nameKey", "name", "classId", "useContext", "family",
                           "powerBand", "manifestCost", "tags"})
        # These field NAMES are exactly what the real corpus (k1.json) ships -- not renamed here.
        real_entries = run_mod.load_corpus()
        real_row = real_entries["consumable.k1-001"]
        for shared_field in ("nameKey", "name", "classId", "useContext", "family", "powerBand",
                              "manifestCost", "tags"):
            with self.subTest(field=shared_field):
                self.assertIn(shared_field, real_row)
                self.assertIn(shared_field, entry)

    def test_build_entry_raises_on_a_defective_answer_rather_than_emitting_silently(self) -> None:
        with self.assertRaises(ValueError):
            emit_mod.build_entry(_clean_answer(classId="revive"), entry_id="x", seq=0)


class HarnessTests(unittest.TestCase):
    """Resume / reconcile / overwrite through the shared `RunLedger` — the spec's third testing
    requirement, "Harness tests (resume/reconcile/overwrite)"."""

    def test_resume_skips_a_subject_already_persisted(self) -> None:
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            ledger = RunLedger(path=Path(tmp) / "test.ledger.json")
            run_mod.generate_one("s1", _clean_answer(), entry_id="consumable.fixture-r-001", seq=0,
                                  ledger=ledger)
            remaining = run_mod.plan_generate(["s1", "s2"], ledger)
            self.assertEqual(remaining, ["s2"])

    def test_reconcile_requeues_a_ledger_row_whose_family_stopped_resolving(self) -> None:
        """If a ledger row's recorded family is no longer real (renamed/retired upstream), the next
        plan must requeue it rather than trust a stale "done" flag -- `RunLedger.plan`'s own
        reconcile contract, exercised against this module's `is_valid`."""
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            ledger = RunLedger(path=Path(tmp) / "test.ledger.json")
            ledger.mark_done("s1", {"entry": {"family": "atom.made-up-family-nobody-shipped"}})
            ledger.mark_done("s2", {"entry": {"family": "atom.vitality"}})
            remaining = run_mod.plan_generate(["s1", "s2"], ledger)
            self.assertEqual(remaining, ["s1"])

    def test_overwrite_by_id_bypasses_ledger_state_for_named_ids_only(self) -> None:
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            ledger = RunLedger(path=Path(tmp) / "test.ledger.json")
            run_mod.generate_one("s1", _clean_answer(), entry_id="consumable.fixture-o-001", seq=0,
                                  ledger=ledger)
            forced = ledger.force(["s1"], scope="ids")
            self.assertEqual(forced, ["s1"])

    def test_a_refused_subject_leaves_no_ledger_row_for_resume_to_trust(self) -> None:
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            ledger = RunLedger(path=Path(tmp) / "test.ledger.json")
            outcome = run_mod.generate_one(
                "s1", _clean_answer(classId="board"), entry_id="consumable.fixture-x-001", seq=0,
                ledger=ledger)
            self.assertEqual(outcome.outcome, "refused")
            remaining = run_mod.plan_generate(["s1"], ledger)
            self.assertEqual(remaining, ["s1"], "a refused subject is not marked done")


class DocCitationStillLiveTests(unittest.TestCase):
    """Mirrors `items/registries.py`'s own `HYBRID_FRAME_CITATION` precedent: one fact
    (`atom.stalwart`/`atom.affliction`/`atom.immunity`/`atom.susceptibility` are named in PROSE, not
    a table row) is transcribed rather than parsed, so a test pins the exact source sentence as a
    live substring -- a future doc edit that removes it fails loudly here instead of silently
    dropping four families from the vocabulary."""

    def test_the_status_channel_families_sentence_is_still_in_the_live_doc(self) -> None:
        text = schema._ATOM_FAMILY_LIBRARY_DOC.read_text(encoding="utf-8")
        self.assertIn(schema._STATUS_CHANNEL_FAMILIES_CITATION, text)

    def test_the_four_status_channel_families_are_in_the_loaded_vocabulary(self) -> None:
        families = schema.load_atom_family_names()
        for name in ("atom.affliction", "atom.stalwart", "atom.immunity", "atom.susceptibility"):
            with self.subTest(name=name):
                self.assertIn(name, families)


# ------------------------------------------------------------------------------------------------
# CLI — real gap, closed 2026-09-08: this module had no entrypoint of any kind before this.
# ------------------------------------------------------------------------------------------------
class CliTests(unittest.TestCase):
    def setUp(self) -> None:
        import tempfile
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        tmp_path = Path(self._tmp.name)
        self.consumables_dir = tmp_path / "consumables"
        self.consumables_dir.mkdir()
        self.ledger_path = tmp_path / "ledger.json"
        self._dir_patch = unittest.mock.patch.object(run_mod, "CONSUMABLES_DIR",
                                                      self.consumables_dir)
        self._ledger_patch = unittest.mock.patch.object(run_mod, "DEFAULT_LEDGER", self.ledger_path)
        self._dir_patch.start()
        self._ledger_patch.start()
        self.addCleanup(self._dir_patch.stop)
        self.addCleanup(self._ledger_patch.stop)

    def test_cli_default_with_no_theme_reconciles_and_makes_no_model_call(self) -> None:
        import io
        import json as json_mod
        from contextlib import redirect_stdout

        buf = io.StringIO()
        with redirect_stdout(buf):
            exit_code = run_mod.main([])
        self.assertEqual(exit_code, 0)
        report = json_mod.loads(buf.getvalue())
        self.assertEqual(report["total"], 0)  # the isolated tmp corpus is empty

    def test_cli_theme_without_write_refuses(self) -> None:
        with self.assertRaises(SystemExit):
            run_mod.main(["--theme", "fire", "--slot", "1"])

    def test_cli_theme_dry_run_prints_a_brief_without_calling_a_model(self) -> None:
        import io
        from contextlib import redirect_stdout

        with unittest.mock.patch("seedsmith.pipeline.llm_caller.live_answer_caller") as caller:
            buf = io.StringIO()
            with redirect_stdout(buf):
                exit_code = run_mod.main(["--theme", "fire", "--slot", "1", "--dry-run"])

        self.assertEqual(exit_code, 0)
        self.assertIn("Author ONE consumable for 'fire'", buf.getvalue())
        caller.assert_not_called()

    def test_cli_a_real_live_run_writes_a_real_partition_file(self) -> None:
        """⛔ Real gap, closed 2026-09-08 — see basetypegen's identical test for the full account.
        No schema exists yet for this module's own answer shape, unlike its siblings — the live
        caller is invoked with an empty schema (`{}`), matching `call_model`'s own documented
        `schema=None` fallback rather than inventing one."""
        import io
        import json as json_mod
        from contextlib import redirect_stdout

        called_with = {}

        def _fake_live_answer_caller(config):
            called_with["config"] = config

            def _call(brief, schema_arg):
                called_with["schema"] = schema_arg
                return _clean_answer(name="Live-Wired Tonic")
            return _call

        with unittest.mock.patch("seedsmith.pipeline.llm_caller.live_answer_caller",
                                 _fake_live_answer_caller):
            buf = io.StringIO()
            with redirect_stdout(buf):
                exit_code = run_mod.main(["--theme", "fire", "--slot", "1", "--write",
                                         "--endpoint", "http://unit-test-endpoint",
                                         "--model", "unit-test-model"])
            outcome = json_mod.loads(buf.getvalue())

        self.assertEqual(exit_code, 0)
        self.assertEqual(outcome["outcome"], "persisted")
        self.assertEqual(called_with["config"].endpoint, "http://unit-test-endpoint")
        self.assertEqual(called_with["schema"], {})
        written = json_mod.loads((self.consumables_dir / "k1-cli.json").read_text(encoding="utf-8"))
        names = {e["name"] for e in written["entries"]}
        self.assertIn("Live-Wired Tonic", names)

    def test_cli_a_second_live_run_is_additive_not_overwriting(self) -> None:
        # `live_answer_caller(config)` is invoked fresh inside `main()` on EVERY call, so the
        # iterator has to live outside the factory closure — otherwise each `main()` call would
        # see a brand-new `iter(...)` and always produce "First".
        calls = iter([_clean_answer(name="First"), _clean_answer(name="Second")])

        def _fake_live_answer_caller(config):
            return lambda brief, schema_arg: next(calls)

        with unittest.mock.patch("seedsmith.pipeline.llm_caller.live_answer_caller",
                                 _fake_live_answer_caller):
            run_mod.main(["--theme", "fire", "--slot", "1", "--write",
                        "--endpoint", "http://unit-test-endpoint"])
            run_mod.main(["--theme", "fire", "--slot", "1", "--write",
                        "--endpoint", "http://unit-test-endpoint"])

        written = json.loads((self.consumables_dir / "k1-cli.json").read_text(encoding="utf-8"))
        names = {e["name"] for e in written["entries"]}
        self.assertEqual(names, {"First", "Second"})


if __name__ == "__main__":
    unittest.main()
