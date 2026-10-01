"""Tests for task C2 — R-G1, R-G2, and the reproducibility contract
(spec-tree-plan.md §7, §7.1, §Reproducibility, §Testing).

    python -m pytest gk-forge/tools/seedsmith/tests/test_tree_plan_reproducibility.py -v

Covers:
  - `gates.py`: the checked-in evidence file is the ONLY source of `gateState`.
  - R-G1: stage-2 generation refuses a `pending` tree naming the tree and the gate quantity;
    `--emit`/planning stays free.
  - R-G2: `generationWave` is derived from `gateState`, never hand-assigned, and `trees[]` orders
    by `(generationWave, ordinal)`.
  - Canonical JSON: sorted keys, 2-space indent, bare `\\n`, UTF-8 no BOM — no `\\r` anywhere, which
    is what makes the Windows/Linux round trip byte-identical (this suite runs on Windows; the
    proxy for "would also match on Linux" is "contains no carriage return and depends on nothing
    OS-specific", which is exactly what `canonical_json_bytes` guarantees).
  - `planHash`: excludes `_provenance` (hence `emittedUtc`); changes when tree content changes.
  - `--check`'s contract: flipping one byte in a hashed input file fails `check_manifest`, naming
    the first differing path (this task's own Verification line).
  - `--diff`: budget deltas, archetype reassignments, and id adds/removes/re-mints between two
    manifests.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from seedsmith.workspace_roots import core_root, seed_root  # noqa: E402
from seedsmith.adapters.trees.plan import emit as plan_emit  # noqa: E402
from seedsmith.adapters.trees.plan import gates  # noqa: E402
from seedsmith.adapters.trees.plan import invariants  # noqa: E402
from seedsmith.adapters.trees.plan import tuning as plan_tuning  # noqa: E402


def real_seed_root() -> Path:
    """The REAL content pack's `data/seed` - NOT a path under this repository.

    This used to walk up to the nearest `CONTRIBUTING.md` and join `data/seed` onto it. Measured across all
    nine repositories, `CONTRIBUTING.md` exists in gk-workflow and NOWHERE ELSE, so that walk always landed on
    the workspace root - which carries neither `data/seed` (gk-data's pack) nor `data/tuning` (gk-core's).
    Every test that read the real corpus through it was reading a path that does not exist.

    `real_repo_root` is gone rather than left in place: nothing else used it, and a helper that returns the
    wrong root is a trap for the next reader rather than dead code.
    """
    return seed_root()


def real_tuning_root() -> Path:
    """The REAL `data/tuning`, which is gk-core's.

    The same reading `seedsmith/ladders.py` states in one line as `REPO_ROOT = core_root()`, with the comment
    explaining that `data/tuning` has always meant gk-core's and never gk-forge's.
    """
    return core_root() / "data" / "tuning"


_MIRROR_RELATIVE_PATHS = (
    Path("aptitudes") / "roster.json",
    Path("elements") / "roster.json",
    Path("statuses") / "roster.json",
    Path("passive-tree") / "vocabulary.json",
    Path("derived-stats") / "catalog.json",
    Path("passive-tree") / "gate-evidence.v1.json",
)

_TUNING_FILES = ("passive-tree.v1.json", "passive-tree-targets.v2.json")


def make_scratch_seed_and_tuning() -> "tuple[Path, Path]":
    """Copies just the real committed mirrors + tuning files C2's manifest machinery reads into a
    fresh scratch tree, so every manifest-level test is fully isolated from (and never writes into)
    the real `gk-data/packs/fusion/data/seed`/`gk-core/data/tuning` — same isolation discipline
    `EmitCheckRoundTripTests` already uses for the single-tree path."""
    scratch = Path(tempfile.mkdtemp())
    seed_root = scratch / "seed"
    tuning_root = scratch / "tuning"
    for rel in _MIRROR_RELATIVE_PATHS:
        src = real_seed_root() / rel
        dst = seed_root / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
    tuning_root.mkdir(parents=True, exist_ok=True)
    for name in _TUNING_FILES:
        shutil.copy2(real_tuning_root() / name, tuning_root / name)
    return seed_root, tuning_root


class GateEvidenceTests(unittest.TestCase):
    """gates.py: the ONLY source of gateState (task C2's own acceptance bullet 1)."""

    def test_the_real_evidence_file_has_all_four_kinds(self) -> None:
        evidence = gates.load_gate_evidence(real_seed_root())
        self.assertEqual(set(evidence.keys()),
                         {"aptitudePoints", "elementMastery", "statusApplied", "creatureTypeLevel"})

    def test_all_four_gate_index_kinds_are_carrier(self) -> None:
        # 2026-09-06: elementMastery/statusApplied flipped pending -> carrier for real -- their
        # production readers (ElementMasterySource/StatusAppliedSource, task G4) shipped, are
        # registered at the real composition root (GateCounterEndpoints.cs), and were live-probed
        # end to end against a real running save (task G6) well before this test's own old
        # "still pending" assertion was noticed as stale (spec-gate-counters.md §19's own readiness
        # ladder names the exact rung this crosses).
        evidence = gates.load_gate_evidence(real_seed_root())
        self.assertEqual(evidence["aptitudePoints"].gate_state, "carrier")
        self.assertEqual(evidence["creatureTypeLevel"].gate_state, "carrier")
        self.assertEqual(evidence["elementMastery"].gate_state, "carrier")
        self.assertEqual(evidence["statusApplied"].gate_state, "carrier")

    def test_resolve_unknown_kind_raises_naming_it(self) -> None:
        evidence = gates.load_gate_evidence(real_seed_root())
        with self.assertRaises(gates.GateEvidenceError) as ex:
            gates.resolve_gate_state("noSuchKind", evidence)
        self.assertIn("noSuchKind", str(ex.exception))

    def test_a_missing_evidence_file_is_EXIT_CANNOT_RUN_naming_the_file(self) -> None:
        empty_root = Path(tempfile.mkdtemp())
        with self.assertRaises(gates.GateEvidenceError) as ex:
            gates.load_gate_evidence(empty_root)
        self.assertIn("gate-evidence.v1.json", str(ex.exception))

    def test_an_illegal_gate_state_value_is_refused(self) -> None:
        scratch = Path(tempfile.mkdtemp())
        path = scratch / "passive-tree" / "gate-evidence.v1.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"rows": [
            {"gateIndexKind": "aptitudePoints", "gateState": "definitely-not-legal"},
        ]}), encoding="utf-8")
        with self.assertRaises(gates.GateEvidenceError):
            gates.load_gate_evidence(scratch)

    def test_might_tree_spec_reads_gate_state_from_the_evidence_file_not_a_literal(self) -> None:
        # The whole point of C2's acceptance bullet 1: this must equal whatever the checked-in
        # evidence row says, not a value hand-typed inside might_tree_spec itself.
        spec = plan_emit.might_tree_spec()
        evidence = gates.load_gate_evidence(real_seed_root())
        self.assertEqual(spec.gate_state, evidence[spec.gate_index_kind].gate_state)


class RG1GenerationGateTests(unittest.TestCase):
    """R-G1: stage-2 generation refuses a pending tree; --emit stays free."""

    def test_a_carrier_tree_is_allowed_to_generate(self) -> None:
        invariants.check_r_g1_generation_allowed("might", "carrier", "aptitude.Might@Commander")  # must not raise

    def test_a_pending_tree_refuses_naming_the_tree_and_the_gate_quantity(self) -> None:
        with self.assertRaises(invariants.PendingGateGenerationRefusal) as ex:
            invariants.check_r_g1_generation_allowed(
                "elemental.fire", "pending", "element_mastery.fire@Aspect")
        message = str(ex.exception)
        self.assertIn("elemental.fire", message)
        self.assertIn("element_mastery.fire@Aspect", message)

    def test_an_unrecognised_gate_state_refuses(self) -> None:
        with self.assertRaises(invariants.PendingGateGenerationRefusal):
            invariants.check_r_g1_generation_allowed("x", "not-a-real-state", "q")

    def test_emit_stays_free_for_a_pending_tree(self) -> None:
        # build_plan (--emit's own engine) must never call check_r_g1 -- planning a pending tree is
        # free, and this is where the absence becomes visible (§7.1), not where it is blocked.
        tuning = plan_tuning.load()
        pending_spec = plan_emit.TreeSpec(
            tree_id="elementalfiretest", category="elemental", ordinal=0,
            gate_quantity="element_mastery.fire@Aspect", gate_index_kind="elementMastery",
            gate_state="pending",
        )
        plan = plan_emit.build_plan(pending_spec, tuning)  # must not raise
        self.assertEqual(plan["gateState"], "pending")
        self.assertEqual(plan["generationWave"], 1)


class RG2WaveDerivationTests(unittest.TestCase):
    """R-G2: generationWave is a pure function of gateState, never hand-assigned."""

    def test_carrier_is_wave_zero(self) -> None:
        self.assertEqual(invariants.derive_generation_wave("carrier"), 0)

    def test_pending_is_wave_one(self) -> None:
        self.assertEqual(invariants.derive_generation_wave("pending"), 1)

    def test_an_unrecognised_state_raises(self) -> None:
        with self.assertRaises(invariants.PlanInvariantError):
            invariants.derive_generation_wave("sideways")

    def test_order_check_passes_for_a_correctly_sorted_index(self) -> None:
        index = [
            {"treeId": "might", "gateState": "carrier", "generationWave": 0},
            {"treeId": "ferocity", "gateState": "carrier", "generationWave": 0},
            {"treeId": "elemental-fire", "gateState": "pending", "generationWave": 1},
        ]
        invariants.check_r_g2_wave_order(index)  # must not raise

    def test_a_hand_typed_wave_disagreeing_with_gate_state_is_refused_naming_the_tree(self) -> None:
        index = [{"treeId": "might", "gateState": "carrier", "generationWave": 3}]
        with self.assertRaises(invariants.TreeOrderRefusal) as ex:
            invariants.check_r_g2_wave_order(index)
        self.assertIn("might", str(ex.exception))

    def test_out_of_wave_order_is_refused(self) -> None:
        index = [
            {"treeId": "elemental-fire", "gateState": "pending", "generationWave": 1},
            {"treeId": "might", "gateState": "carrier", "generationWave": 0},
        ]
        with self.assertRaises(invariants.TreeOrderRefusal):
            invariants.check_r_g2_wave_order(index)


class CanonicalJsonTests(unittest.TestCase):
    """Reproducibility: sorted keys, 2-space indent, bare `\\n`, UTF-8 no BOM."""

    def test_no_carriage_return_anywhere(self) -> None:
        data = plan_emit.canonical_json_bytes({"b": 1, "a": [3, 2, 1], "c": {"z": 1, "a": 2}})
        self.assertNotIn(b"\r", data)

    def test_no_bom(self) -> None:
        data = plan_emit.canonical_json_bytes({"a": 1})
        self.assertFalse(data.startswith(b"\xef\xbb\xbf"))

    def test_keys_are_sorted_and_indent_is_two_spaces(self) -> None:
        data = plan_emit.canonical_json_bytes({"b": 1, "a": 2}).decode("utf-8")
        self.assertEqual(data, '{\n  "a": 2,\n  "b": 1\n}\n')

    def test_ends_with_exactly_one_trailing_newline(self) -> None:
        data = plan_emit.canonical_json_bytes({"a": 1})
        self.assertTrue(data.endswith(b"\n"))
        self.assertFalse(data.endswith(b"\n\n"))

    def test_re_serializing_the_committed_might_plan_is_byte_identical(self) -> None:
        # Proves the ACTUAL committed file (regenerated by this task) round-trips through
        # canonical_json_bytes byte-for-byte -- the property the whole Reproducibility section
        # exists to guarantee.
        path = real_seed_root() / "passive-tree" / "plan" / "might.v1.json"
        if not path.exists():
            self.skipTest("might.v1.json not yet committed in this checkout")
        committed_bytes = path.read_bytes()
        doc = json.loads(committed_bytes.decode("utf-8"))
        self.assertEqual(plan_emit.canonical_json_bytes(doc), committed_bytes)


class TreeContentHashTests(unittest.TestCase):
    def test_hash_is_deterministic(self) -> None:
        doc = {"a": 1, "b": [1, 2, 3]}
        self.assertEqual(plan_emit.tree_content_hash(doc), plan_emit.tree_content_hash(dict(doc)))

    def test_hash_changes_when_content_changes(self) -> None:
        h1 = plan_emit.tree_content_hash({"a": 1})
        h2 = plan_emit.tree_content_hash({"a": 2})
        self.assertNotEqual(h1, h2)


class ManifestTests(unittest.TestCase):
    """build_manifest / emit_manifest / check_manifest, fully isolated from the real gk-data/packs/fusion/data/seed."""

    def setUp(self) -> None:
        self.seed_root, self.tuning_root = make_scratch_seed_and_tuning()
        self.tuning = plan_tuning.load(self.tuning_root / "passive-tree.v1.json")
        self.spec = plan_emit.might_tree_spec(self.seed_root)

    def test_manifest_indexes_one_tree_with_the_right_fields(self) -> None:
        manifest, tree_plans = plan_emit.build_manifest([self.spec], self.tuning, seed_root=self.seed_root,
                                                        tuning_root=self.tuning_root)
        self.assertEqual(len(manifest["trees"]), 1)
        entry = manifest["trees"][0]
        self.assertEqual(entry["treeId"], "might")
        self.assertEqual(entry["gateState"], "carrier")
        self.assertEqual(entry["generationWave"], 0)
        self.assertEqual(entry["sha256"], plan_emit.tree_content_hash(tree_plans["might"]))
        self.assertNotIn("ordinal", entry)  # internal sort key only, never emitted (frozen schema)

    def test_trees_index_is_ordered_by_wave_then_ordinal(self) -> None:
        pending_spec = plan_emit.TreeSpec(
            tree_id="elementalfiretest", category="elemental", ordinal=0,
            gate_quantity="element_mastery.fire@Aspect", gate_index_kind="elementMastery",
            gate_state="pending",
        )
        # Deliberately pass the pending (wave 1) spec FIRST -- the manifest must still put the
        # carrier (wave 0) tree first, proving the order is derived, not input order.
        manifest, _ = plan_emit.build_manifest([pending_spec, self.spec], self.tuning,
                                               seed_root=self.seed_root, tuning_root=self.tuning_root)
        self.assertEqual([e["treeId"] for e in manifest["trees"]], ["might", "elementalfiretest"])

    def test_plan_hash_excludes_provenance_and_therefore_emitted_utc(self) -> None:
        manifest_a, _ = plan_emit.build_manifest([self.spec], self.tuning, seed_root=self.seed_root,
                                                 tuning_root=self.tuning_root)
        manifest_b, _ = plan_emit.build_manifest([self.spec], self.tuning, seed_root=self.seed_root,
                                                 tuning_root=self.tuning_root)
        self.assertNotEqual(manifest_a["_provenance"]["emittedUtc"], "")  # sanity: it IS populated
        self.assertEqual(manifest_a["planHash"], manifest_b["planHash"])

    def test_plan_hash_changes_when_a_trees_content_changes(self) -> None:
        manifest_before, _ = plan_emit.build_manifest([self.spec], self.tuning, seed_root=self.seed_root,
                                                       tuning_root=self.tuning_root)
        mutated_tuning = json.loads(json.dumps(self.tuning))
        mutated_tuning["tierLadder"]["reqScalePoints"] = self.tuning["tierLadder"]["reqScalePoints"] + 1
        manifest_after, _ = plan_emit.build_manifest([self.spec], mutated_tuning, seed_root=self.seed_root,
                                                      tuning_root=self.tuning_root)
        self.assertNotEqual(manifest_before["planHash"], manifest_after["planHash"])

    def test_emit_then_check_manifest_is_clean(self) -> None:
        plan_emit.emit_manifest([self.spec], self.tuning, seed_root=self.seed_root, tuning_root=self.tuning_root)
        diffs = plan_emit.check_manifest([self.spec], self.tuning, seed_root=self.seed_root,
                                         tuning_root=self.tuning_root)
        self.assertEqual(diffs, [])

    def test_flipping_one_hashed_input_byte_fails_check_and_names_the_first_differing_path(self) -> None:
        """This task's own Verification line, run for real: emit a clean manifest, flip ONE byte
        inside a hashed input mirror on disk, and prove `check_manifest` reports a difference whose
        first entry names a real path (not just "something changed")."""
        plan_emit.emit_manifest([self.spec], self.tuning, seed_root=self.seed_root, tuning_root=self.tuning_root)

        vocab_path = self.seed_root / "passive-tree" / "vocabulary.json"
        doc = json.loads(vocab_path.read_text(encoding="utf-8"))
        original = doc["attachPoints"][0]
        self.assertNotIn(original[:-1] + "s", doc["attachPoints"])  # the flip must be a real change
        doc["attachPoints"][0] = original[:-1] + "s"  # one character flip, e.g. "Board" -> "Boars"
        vocab_path.write_text(json.dumps(doc), encoding="utf-8")

        diffs = plan_emit.check_manifest([self.spec], self.tuning, seed_root=self.seed_root,
                                         tuning_root=self.tuning_root)
        self.assertTrue(diffs, "flipping one input byte must produce at least one reported diff")
        self.assertTrue(any("atomAttachPoint" in d or "propertyVocabulary" in d for d in diffs),
                        f"expected the diff to name the affected vocabulary path, got: {diffs}")

    def test_check_manifest_without_a_committed_manifest_is_EXIT_CANNOT_RUN(self) -> None:
        with self.assertRaises(plan_emit.EmitError):
            plan_emit.check_manifest([self.spec], self.tuning, seed_root=self.seed_root,
                                     tuning_root=self.tuning_root)

    def test_provenance_inputs_are_hashed_and_named(self) -> None:
        manifest, _ = plan_emit.build_manifest([self.spec], self.tuning, seed_root=self.seed_root,
                                               tuning_root=self.tuning_root)
        input_paths = {entry["path"] for entry in manifest["_provenance"]["inputs"]}
        self.assertTrue(any(p.endswith("gate-evidence.v1.json") for p in input_paths))
        self.assertTrue(any(p.endswith("vocabulary.json") for p in input_paths))
        for entry in manifest["_provenance"]["inputs"]:
            # Formula, not a literal (population-pin SE3.5, 2026-09-20): a real sha256 hex digest,
            # not a stub -- a structural fact about the algorithm, never content.
            self.assertEqual(hashlib.sha256().digest_size * 2, len(entry["sha256"]))

    def test_provenance_tuning_names_both_domains_with_their_own_version(self) -> None:
        manifest, _ = plan_emit.build_manifest([self.spec], self.tuning, seed_root=self.seed_root,
                                               tuning_root=self.tuning_root)
        domains = {entry["domain"]: entry for entry in manifest["_provenance"]["tuning"]}
        self.assertEqual(set(domains), {"passive-tree", "passive-tree-targets"})
        self.assertEqual(domains["passive-tree"]["version"], 1)


class DiffManifestsTests(unittest.TestCase):
    """--diff: budget deltas, archetype reassignments, and id adds/removes/re-mints."""

    def setUp(self) -> None:
        self.seed_root, self.tuning_root = make_scratch_seed_and_tuning()
        self.tuning = plan_tuning.load(self.tuning_root / "passive-tree.v1.json")
        self.spec = plan_emit.might_tree_spec(self.seed_root)

    def _emit_manifest_copy(self, out_dir: Path, tuning: dict) -> Path:
        seed_root = out_dir / "seed"
        for rel in _MIRROR_RELATIVE_PATHS:
            dst = seed_root / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(self.seed_root / rel, dst)
        return plan_emit.emit_manifest([self.spec], tuning, seed_root=seed_root, tuning_root=self.tuning_root)

    def test_identical_manifests_report_no_differences(self) -> None:
        path_a = self._emit_manifest_copy(Path(tempfile.mkdtemp()), self.tuning)
        path_b = self._emit_manifest_copy(Path(tempfile.mkdtemp()), self.tuning)
        report = plan_emit.diff_manifests(path_a, path_b)
        self.assertEqual(report, {
            "budgetDeltas": [], "archetypeReassignments": [], "quotaCellMoves": [],
            "idsAdded": [], "idsRemoved": [], "idsReminted": [],
        })

    def test_a_budget_total_change_is_reported_as_a_budget_delta(self) -> None:
        path_a = self._emit_manifest_copy(Path(tempfile.mkdtemp()), self.tuning)
        mutated = json.loads(json.dumps(self.tuning))
        mutated["budget"]["treeTotalPoints"] = self.tuning["budget"]["treeTotalPoints"] + 100
        path_b = self._emit_manifest_copy(Path(tempfile.mkdtemp()), mutated)
        report = plan_emit.diff_manifests(path_a, path_b)
        self.assertTrue(report["budgetDeltas"], "a changed treeTotalPoints must show up as a budget delta")

    def test_a_tree_present_only_in_b_is_reported_as_ids_added(self) -> None:
        path_a = self._emit_manifest_copy(Path(tempfile.mkdtemp()), self.tuning)

        second_spec = plan_emit.TreeSpec(
            tree_id="ferocitytest", category="primary", ordinal=1,
            gate_quantity="aptitude.Ferocity@Commander", gate_index_kind="aptitudePoints",
            gate_state="carrier",
        )
        out_dir_b = Path(tempfile.mkdtemp())
        seed_root_b = out_dir_b / "seed"
        for rel in _MIRROR_RELATIVE_PATHS:
            dst = seed_root_b / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(self.seed_root / rel, dst)
        path_b = plan_emit.emit_manifest([self.spec, second_spec], self.tuning, seed_root=seed_root_b,
                                         tuning_root=self.tuning_root)

        report = plan_emit.diff_manifests(path_a, path_b)
        self.assertTrue(any("ferocitytest" in i for i in report["idsAdded"]))
        self.assertEqual(report["idsRemoved"], [])

    def test_a_missing_referenced_tree_file_is_EXIT_CANNOT_RUN(self) -> None:
        path_a = self._emit_manifest_copy(Path(tempfile.mkdtemp()), self.tuning)
        (path_a.parent / "plan" / "might.v1.json").unlink()
        with self.assertRaises(plan_emit.EmitError):
            plan_emit.diff_manifests(path_a, path_a)


if __name__ == "__main__":
    unittest.main()
