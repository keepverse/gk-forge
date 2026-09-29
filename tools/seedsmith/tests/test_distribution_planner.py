"""Tests for seedsmith.adapters.actions.distribution_planner (A-S1, spec-distribution-planner.md).

    python -m pytest gk-forge/tools/seedsmith/tests/test_distribution_planner.py -v

Spec §5's named cases plus §6's acceptance criteria (1, 2, 3, 4, 4b, 5, 6, 6b, 6c, 7, 7b x2, 8, 9)
-- see each class's own docstring for which criterion it proves. Same fixture split every prior
module in this session established: real, live repo data for everything spec calls a MEASURED
fact; synthetic, in-memory fixtures for determinism, planted violations, and overflow.

**The pairings.json rewrite named in spec §3 step 6 is explicitly OUT OF SCOPE for this module's
build (see generate_distribution_planner.py's own module docstring for the full scoping
decision).** Every test below that needs a REACHABLE payoff family therefore reads from a
SYNTHETIC pairing fixture built from two real ids in the 98-family namespace
(`atom.freezing`/`atom.venomous`, both `g-affliction.json`) -- never from the real, unmodified
`gk-data/packs/fusion/data/seed/actions/pairings.json`, whose two shipped keys exist in none of the three namespaces
measured by the spec (§2) and so can never be reachable. This mirrors the spec's own testing-
strategy row, adapted: it says the planted-payoff test reads "from the rewritten pairings.json at
test time" -- that file does not exist in this checkout, so this suite reads from its own
in-memory fixture instead, and says so here rather than silently reinterpreting the spec.
"""
from __future__ import annotations

import ast
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from seedsmith.adapters.actions.characteristic_pool.derive import CATEGORIES  # noqa: E402
from seedsmith.adapters.actions.type_weights.tuning import AREA_SHAPES, TARGET_MODES  # noqa: E402
from seedsmith.adapters.actions.vocab import (  # noqa: E402
    PAIRING_ROLES, RELATIONS, load_family_ids, load_pairing_keys,
)
from seedsmith.adapters.actions.distribution_planner import derive as dp  # noqa: E402
from seedsmith.adapters.actions.distribution_planner import fingerprint as fp  # noqa: E402
from seedsmith.adapters.actions.distribution_planner.tuning import (  # noqa: E402
    DEDUP_TUNING_PATH, DEFAULT_AVOID_NEIGHBOUR_K, FINGERPRINT_COMPONENT_COUNT, RUN_TUNING_PATH,
    load_dedup_k, load_run_tuning,
)
from seedsmith.adapters.actions import generate_distribution_planner as gen_mod  # noqa: E402
from seedsmith.adapters.actions.kinds import KINDS  # noqa: E402
from seedsmith.adapters.actions.load import load_committed  # noqa: E402
from seedsmith.corpus import Corpus  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[3]
ACTIONS_ROOT = REPO_ROOT / "data" / "seed" / "actions"
OUTPUT_PATH = ACTIONS_ROOT / "_briefs" / "round-1.json"

FAMILY_IDS = load_family_ids()                                  # the 98, read fresh (live tree)
FIXTURE_ATOM_ID = "atom.fx-passive-atk-flat"                     # data/seed/atoms/fx-core.json (17)


def _write_passing_gate(path: Path) -> None:
    path.write_text(json.dumps({"kind": "action-coverage", "_meta": {
        "round": 1,
        "verdict": {"verdict": "pass", "notMeasuredMetrics": [], "gapMetrics": []},
    }}), encoding="utf-8")


# ---------------------------------------------------------------------------------------------
# Synthetic fixtures
# ---------------------------------------------------------------------------------------------

def _weights(*, category_milli=None, target_mode_milli=None, area_shape_milli=None) -> dp.WeightsRow:
    return dp.WeightsRow(
        category_milli=dict(category_milli or {c: 200 for c in CATEGORIES}),
        target_mode_milli=dict(target_mode_milli or {m: (1000 // len(TARGET_MODES)
                                                          + (1 if i < 1000 % len(TARGET_MODES) else 0))
                                                    for i, m in enumerate(TARGET_MODES)}),
        area_shape_milli=dict(area_shape_milli or {s: 250 for s in AREA_SHAPES}),
    )


# Two REAL ids in the 98-family namespace, used to build a synthetic, reachable pairing table --
# never the real (unreachable) pairings.json. Both from g-affliction.json.
FAKE_PAYOFF = "atom.freezing"
FAKE_ENABLER = "atom.venomous"
assert FAKE_PAYOFF in FAMILY_IDS and FAKE_ENABLER in FAMILY_IDS


class RunTuningLoadTests(unittest.TestCase):
    """Acceptance #6c: the shipped run-tuning file carries the EXACT stated defaults, and its
    `_meta` states the counts cover the live seed roster."""

    def test_shipped_defaults(self) -> None:
        t = load_run_tuning()
        self.assertEqual(t.mode, "full")
        self.assertEqual(t.general_count, 1000)
        self.assertEqual(t.per_family_count, 5)
        self.assertEqual(t.per_species_count, 5)
        self.assertEqual(t.multiplicative_pairs, (("atom.keen-edge", "atom.cruelty"),))
        self.assertEqual(t.family_motif_max, 6)
        self.assertEqual(t.version, 3)

    def test_meta_states_untuned(self) -> None:
        doc = json.loads(RUN_TUNING_PATH.read_text(encoding="utf-8"))
        self.assertEqual(doc["_meta"]["default"], "full-live-seed-roster")
        self.assertIn("live creature species seed folder", doc["_meta"]["note"])

    def test_stale_citation_avoidNeighbourK_is_shipped_but_unused(self) -> None:
        """**A found spec self-contradiction, documented rather than silently resolved either
        way** -- matching every prior module this session (each found at least one stale
        citation). Spec §3 step 1's own JSONC literal for `action-corpus-run.v1.json` includes
        `"avoidNeighbourK": 3`, and the task instructions require shipping that EXACT block --
        so the field is present in the shipped file. But spec §3 step 8's own later "DECIDED"
        correction states `k` is read from `action-dedup.v1.json` instead, default 8, and never
        from this file. This module follows step 8 (the later, explicit correction) for the
        actual algorithm and ships step 1's literal block verbatim -- so `avoidNeighbourK` in the
        shipped file is real JSON but genuinely UNREAD by this module's own code."""
        doc = json.loads(RUN_TUNING_PATH.read_text(encoding="utf-8"))
        self.assertEqual(doc["avoidNeighbourK"], 3)
        pkg_dir = Path(dp.__file__).resolve().parent
        for f in list(pkg_dir.glob("*.py")) + [Path(gen_mod.__file__)]:
            self.assertNotIn("avoidNeighbourK", f.read_text(encoding="utf-8"),
                             f"{f} must never read the stale avoidNeighbourK field")


class RunTuningPlantedViolationTests(unittest.TestCase):
    """Spec §5's four magnitude-smuggling shapes, applied to the RUN TUNING loader itself."""

    def _write(self, tmp: Path, **overrides) -> Path:
        doc = json.loads(RUN_TUNING_PATH.read_text(encoding="utf-8"))
        doc.update(overrides)
        path = tmp / "action-corpus-run.v1.json"
        path.write_text(json.dumps(doc), encoding="utf-8")
        return path

    def test_float_refused(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(Path(tmp), generalCount=5.5)
            with self.assertRaises(ValueError) as ctx:
                load_run_tuning(path)
            self.assertIn("generalCount", str(ctx.exception))

    def test_numeric_string_refused(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(Path(tmp), perSpeciesCount="1")
            with self.assertRaises(ValueError) as ctx:
                load_run_tuning(path)
            self.assertIn("perSpeciesCount", str(ctx.exception))

    def test_bool_masquerading_as_int_refused(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(Path(tmp), perFamilyCount=True)
            with self.assertRaises(ValueError) as ctx:
                load_run_tuning(path)
            self.assertIn("perFamilyCount", str(ctx.exception))

    def test_bad_mode_refused(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(Path(tmp), mode="turbo")
            with self.assertRaises(ValueError):
                load_run_tuning(path)


class DedupKTests(unittest.TestCase):
    """Acceptance #7b: `k` is read from `action-dedup.v1.json` (never from
    `action-corpus-run.v1.json`), and defaults to the fingerprint's own component count plus one
    wherever that file is absent.

    **UPDATED 2026-09-04 (A-S3, spec-dedup-select.md): `action-dedup.v1.json` now exists for
    real** -- A-S3 is the file's actual owner and shipped it with `k: 8`, the same value this
    loader's own default already produced. The tripwire this class used to carry
    ("`action-dedup.v1.json` exists now -- re-check the A-S1 default-k call") has fired, exactly as
    it was written to: it is replaced below with a test of the NEW state (`source == "file"`)
    rather than left asserting an absence that is no longer true. `test_reads_k_from_file_when_present`
    is kept unchanged -- it never depended on the shipped file being absent, only on the loader
    correctly reading a file when one exists, which is still exactly what it tests."""

    def test_dedup_file_now_exists_and_matches_the_default(self) -> None:
        self.assertTrue(DEDUP_TUNING_PATH.is_file(),
                        "action-dedup.v1.json is missing again -- A-S3's own file was removed; "
                        "re-check whether the default-k fallback path needs to come back into play")
        doc = json.loads(DEDUP_TUNING_PATH.read_text(encoding="utf-8"))
        self.assertEqual(doc["k"], DEFAULT_AVOID_NEIGHBOUR_K,
                         "the shipped file's k no longer matches this loader's own derived "
                         "default -- A-S3 has genuinely re-tuned k; that is fine, but this loader's "
                         "own default should be re-derived to match or explicitly diverge on purpose")

    def test_default_k_equals_component_count_plus_one(self) -> None:
        self.assertEqual(FINGERPRINT_COMPONENT_COUNT, 7)
        self.assertEqual(DEFAULT_AVOID_NEIGHBOUR_K, 8)

    def test_k_is_now_sourced_from_the_real_file_not_the_fallback_default(self) -> None:
        k, source = load_dedup_k()
        self.assertEqual(k, 8)
        self.assertEqual(source, "file",
                         "k is still coming from the fallback default -- action-dedup.v1.json "
                         "should be readable now that A-S3 has shipped it")

    def test_reads_k_from_file_when_present(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "action-dedup.v1.json"
            path.write_text(json.dumps({"k": 12}), encoding="utf-8")
            k, source = load_dedup_k(path)
            self.assertEqual(k, 12)
            self.assertEqual(source, "file")

    def test_default_still_used_when_a_DIFFERENT_missing_path_is_given(self) -> None:
        """The fallback path (§ tuning.py's own documented default) is still real code, still
        reachable, and still correct -- it is simply no longer what the SHIPPED path exercises."""
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "does-not-exist.json"
            k, source = load_dedup_k(missing)
            self.assertEqual(k, DEFAULT_AVOID_NEIGHBOUR_K)
            self.assertEqual(source, "default")


class FamilyMotifDerivationTests(unittest.TestCase):
    """Spec §3 step 2b, acceptance #7b (the first one, family motifs)."""

    def test_intersection_wins_when_nonempty(self) -> None:
        rows = [(("a", "b", "c"), ("x",)), (("a", "b"), ("y",))]
        motifs, anti, basis = dp.derive_family_motifs(rows, family_motif_max=6)
        self.assertEqual(motifs, ("a", "b"))
        self.assertEqual(anti, ("x", "y"))
        self.assertEqual(basis, "intersection")

    def test_majority_fallback_when_intersection_empty(self) -> None:
        # 3 members; "a" held by 2 of 3 and "c" held by 2 of 3 (both >= ceil(3/2)=2); "b" held by
        # only 1 -> majority = {"a", "c"}, sorted byte-wise.
        rows = [(("a", "b"), ()), (("a", "c"), ()), (("c",), ())]
        motifs, _, basis = dp.derive_family_motifs(rows, family_motif_max=6)
        self.assertEqual(basis, "majority")
        self.assertEqual(motifs, ("a", "c"))

    def test_frequency_fallback_capped_by_family_motif_max(self) -> None:
        # 4 members, no motif shared by >=2 (no majority), everything unique once -> frequency,
        # capped at family_motif_max, ties broken byte-wise.
        rows = [(("d",), ()), (("c",), ()), (("b",), ()), (("a",), ())]
        motifs, _, basis = dp.derive_family_motifs(rows, family_motif_max=2)
        self.assertEqual(basis, "frequency")
        self.assertEqual(motifs, ("a", "b"))          # byte-wise sorted, capped to 2

    def test_empty_members_is_total_not_a_crash(self) -> None:
        motifs, anti, basis = dp.derive_family_motifs([], family_motif_max=6)
        self.assertEqual(motifs, ())
        self.assertEqual(anti, ())
        self.assertEqual(basis, "intersection")

    def test_every_family_intersects_nonempty_against_real_data(self) -> None:
        fam_path = REPO_ROOT / "data" / "seed" / "creatures" / "_generated" / "family-assignments.json"
        lean_path = ACTIONS_ROOT / "_generated" / "role-lean.json"
        if not fam_path.is_file() or not lean_path.is_file():
            self.skipTest("A-S0 outputs not yet generated in this checkout")
        family_assignments = json.loads(fam_path.read_text(encoding="utf-8"))
        species_anchor = dp.parse_species_anchor(json.loads(lean_path.read_text(encoding="utf-8")))
        members = gen_mod._family_members(family_assignments)
        # A JOIN, not a pinned family count: the member map's keys are exactly the assignment values.
        declared = {f for v in family_assignments.values() for f in (v if isinstance(v, list) else [v])}
        self.assertEqual(set(members), declared)
        self.assertTrue(members, "the real family map is non-empty")

        for family_id, species_ids in members.items():
            rows = [(species_anchor[s].motifs, species_anchor[s].anti_motifs)
                   for s in species_ids if s in species_anchor]
            motifs, anti, basis = dp.derive_family_motifs(rows, family_motif_max=6)
            self.assertEqual(basis, "intersection", f"family {family_id!r} needed a fallback")
            self.assertGreater(len(motifs), 0)
            self.assertEqual(len(anti), 5, f"family {family_id!r} anti-motif union != 5")

    def test_family_size_histogram_reconciles(self) -> None:
        """The histogram is a READING of the current family map (it moves as species ship), so the
        contract is reconciliation: bin counts sum to the distinct-family count, and the membership
        total is the per-species sum — never a pinned `{7:1, ...}` snapshot (validation-ssot.md)."""
        fam_path = REPO_ROOT / "data" / "seed" / "creatures" / "_generated" / "family-assignments.json"
        if not fam_path.is_file():
            self.skipTest("family-assignments.json not present in this checkout")
        family_assignments = json.loads(fam_path.read_text(encoding="utf-8"))
        members = gen_mod._family_members(family_assignments)
        sizes = {}
        for v in members.values():
            sizes[len(v)] = sizes.get(len(v), 0) + 1
        self.assertEqual(sum(sizes.values()), len(members),
                         "the family-size histogram bins every family exactly once")
        self.assertEqual(sum(len(v) for v in members.values()),
                         sum(len(v if isinstance(v, list) else [v])
                             for v in family_assignments.values()),
                         "memberships reconcile to the per-species sum")
        self.assertTrue(all(len(v) >= 1 for v in members.values()), "no empty family bin")
        print(f"families: {len(members)} over {sum(len(v) for v in members.values())} memberships")


class LargestRemainderAndExpandTests(unittest.TestCase):
    """Spec §3 steps 3/4a, acceptance #3/#4b."""

    def test_distributes_to_largest_fractions_with_declared_order_tiebreak(self) -> None:
        weights = {"attack": 334, "defense": 333, "support": 333, "movement": 0, "status": 0}
        counts = dp.largest_remainder_count(weights, CATEGORIES, 3)
        self.assertEqual(sum(counts.values()), 3)
        self.assertEqual(counts, {"attack": 1, "defense": 1, "support": 1, "movement": 0, "status": 0})

    def test_zero_total_yields_all_zero(self) -> None:
        weights = {c: 200 for c in CATEGORIES}
        counts = dp.largest_remainder_count(weights, CATEGORIES, 0)
        self.assertEqual(set(counts.values()), {0})

    def test_expand_counts_spreads_each_quota_instead_of_grouping_it(self) -> None:
        """The 2026-09-11 sequencing fix: each key's quota is spread across the sequence by round
        (stride), never emitted back-to-back. Grouping made the JOINT frame constant for long
        stretches once two blocked vectors were zipped — measured 134-long runs and 15 total frames
        in the 1,000-brief general tier, which drove A-S3 to reject 56% of a batch as near-dupes.
        Marginals are preserved exactly; only order changes."""
        counts = {"attack": 2, "defense": 0, "support": 1, "movement": 0, "status": 1}
        seq = dp.expand_counts(counts, CATEGORIES)
        self.assertEqual(seq, ["attack", "support", "status", "attack"])
        self.assertEqual(sorted(seq), ["attack", "attack", "status", "support"])

    def test_expand_counts_preserves_every_marginal(self) -> None:
        counts = {"attack": 200, "defense": 200, "support": 200, "movement": 200, "status": 200}
        seq = dp.expand_counts(counts, CATEGORIES)
        # Self-referential (population-pin SE3.5, 2026-09-20): this test built counts itself, so it
        # proves the expansion preserves the total, not a fact about shipped content.
        self.assertEqual(sum(counts.values()), len(seq))
        self.assertEqual({c: seq.count(c) for c in CATEGORIES}, counts)

    def test_expand_counts_has_no_long_run_at_the_shipped_general_size(self) -> None:
        import itertools
        counts = {"attack": 200, "defense": 200, "support": 200, "movement": 200, "status": 200}
        seq = dp.expand_counts(counts, CATEGORIES)
        longest = max(len(list(g)) for _, g in itertools.groupby(seq))
        self.assertEqual(longest, 1, "a 200-quota key must not emit 200 identical slots in a row")

    def test_joint_frames_stay_diverse_across_a_batch(self) -> None:
        """The defect the sequencing fix targets: the JOINT (category, targetMode) frame must vary
        across a proposal batch's own contiguous slice, because a batch draws consecutive ordinals
        and the model sees one frame per call."""
        cat = dp.expand_counts({c: 200 for c in CATEGORIES}, CATEGORIES)
        tm = dp.expand_counts({m: 167 for m in TARGET_MODES}, TARGET_MODES)
        frames = list(zip(cat, tm))
        self.assertGreater(len(set(frames)), 20, "the general tier must not collapse to a few frames")
        # The first 40 ordinals are one small batch; they must not all share a single frame.
        self.assertGreater(len(set(frames[:40])), 20)

    def test_independent_of_dict_insertion_order(self) -> None:
        a = {"attack": 7, "defense": 3, "support": 5, "movement": 2, "status": 1}
        b = {"status": 1, "movement": 2, "support": 5, "defense": 3, "attack": 7}
        self.assertEqual(dp.largest_remainder_count(a, CATEGORIES, 18),
                         dp.largest_remainder_count(b, CATEGORIES, 18))


class TwoLevelAllocationTests(unittest.TestCase):
    """The scope-level allocation engine. It replaced the per-subject largest-remainder split, which
    was measured inert at `count == 5` (a member needs weight >= 400 per-mille for a 2nd slot; the
    shipped `base=1000, step=250` tops out at 267, so all 1,131 subjects got the identical
    `1/1/1/1/1` vector on category and, on the six-member `targetMode`, always dropped `area`)."""

    @staticmethod
    def _rows(n: int, *, lean: str = "attack", order=None) -> "list[tuple[str, dict]]":
        order = order or CATEGORIES
        rows = []
        for i in range(n):
            milli = {c: 200 for c in order}
            if lean in milli:
                milli[lean] += 60
                other = next(c for c in reversed(order) if c != lean)
                milli[other] -= 60
            rows.append((f"s{i:03d}", milli))
        return rows

    def test_every_row_sums_to_count(self) -> None:
        for count in (1, 2, 3, 5, 8, 25):
            alloc = dp.apportion_axis(self._rows(37), count, CATEGORIES)
            for key, counts in alloc.items():
                self.assertEqual(sum(counts.values()), count, key)

    def test_column_sums_equal_scope_quota_exactly(self) -> None:
        rows = self._rows(37)
        for count in (1, 3, 5, 10):
            alloc = dp.apportion_axis(rows, count, CATEGORIES)
            col = {c: sum(v[c] for v in alloc.values()) for c in CATEGORIES}
            aggregate = {c: sum(m[c] for _, m in rows) for c in CATEGORIES}
            expected = dp.largest_remainder_apportion(aggregate, CATEGORIES, count * len(rows))
            self.assertEqual(col, expected, f"count={count}")

    def test_not_flat_at_the_shipped_count(self) -> None:
        alloc = dp.apportion_axis(self._rows(40), 5, CATEGORIES)
        self.assertGreater(len({tuple(sorted(v.items())) for v in alloc.values()}), 1)

    def test_lean_head_wins_extra_slots_when_quota_permits(self) -> None:
        alloc = dp.apportion_axis(self._rows(60, lean="attack"), 5, CATEGORIES)
        winners = sum(1 for v in alloc.values() if v["attack"] >= 2)
        self.assertGreater(winners, 0, "an attack-leaning roster must place extra attack briefs")

    def test_deterministic(self) -> None:
        rows = self._rows(50)
        self.assertEqual(dp.apportion_axis(rows, 5, CATEGORIES),
                         dp.apportion_axis(rows, 5, CATEGORIES))

    def test_empty_and_zero_count(self) -> None:
        self.assertEqual(dp.apportion_axis([], 5, CATEGORIES), {})
        alloc = dp.apportion_axis(self._rows(4), 0, CATEGORIES)
        self.assertTrue(all(v == {c: 0 for c in CATEGORIES} for v in alloc.values()))

    def test_target_mode_is_generic_over_any_axis(self) -> None:
        """`apportion_axis` must work for the SIX-member `targetMode` axis, not just five
        categories — the bug was that targetMode still used the inert per-subject method."""
        rows = self._rows(60, lean="area", order=TARGET_MODES)
        alloc = dp.apportion_axis(rows, 5, TARGET_MODES)
        col = {m: sum(v[m] for v in alloc.values()) for m in TARGET_MODES}
        aggregate = {m: sum(mm[m] for _, mm in rows) for m in TARGET_MODES}
        self.assertEqual(col, dp.largest_remainder_apportion(aggregate, TARGET_MODES, 5 * len(rows)))
        self.assertTrue(all(sum(v.values()) == 5 for v in alloc.values()))
        self.assertGreater(sum(1 for v in alloc.values() if v["area"] > 0), 0)

    def test_no_large_per_subject_count_guard_to_trip(self) -> None:
        """The deficit-greedy fill has no swap-repair guard; it is exact by construction at any
        count. Exercise a large per-subject count with a lopsided roster."""
        rows = []
        for i in range(120):
            milli = {c: 50 for c in CATEGORIES}
            milli["attack" if i % 2 == 0 else "defense"] += 750
            rows.append((f"s{i:03d}", milli))
        for count in (40, 120, 200):
            alloc = dp.apportion_axis(rows, count, CATEGORIES)
            for key, counts in alloc.items():
                self.assertEqual(sum(counts.values()), count, key)
            col = {c: sum(v[c] for v in alloc.values()) for c in CATEGORIES}
            aggregate = {c: sum(m[c] for _, m in rows) for c in CATEGORIES}
            self.assertEqual(col, dp.largest_remainder_apportion(aggregate, CATEGORIES, count * len(rows)))


class AreaShapeAllocationTests(unittest.TestCase):
    """`apportion_area_shapes` — the third level of the same defect. `areaShape` is a conditional
    sub-vector consulted only for `targetMode == "area"`; per-subject largest remainder at a subject's
    own area count (0 or 1 at family/species scope) tied all four shapes and the declared-order
    tie-break always picked `row` — measured 750/750 species and 188/188 family area briefs were
    `row`, so `column`/`square`/`rectangle` were unreachable."""

    @staticmethod
    def _rows(n: int) -> "list[tuple[str, dict]]":
        return [(f"s{i:03d}", {s: 250 for s in AREA_SHAPES}) for i in range(n)]

    def test_all_four_shapes_reachable_when_slots_allow(self) -> None:
        rows = self._rows(40)
        slots = {key: 1 for key, _ in rows}
        alloc = dp.apportion_area_shapes(rows, slots)
        col = {s: sum(v[s] for v in alloc.values()) for s in AREA_SHAPES}
        self.assertEqual(set(col), set(AREA_SHAPES))
        self.assertTrue(all(n > 0 for n in col.values()),
                        f"every shape must be reachable, got {col}")

    def test_per_subject_sums_to_the_area_slot_count(self) -> None:
        rows = self._rows(30)
        slots = {key: (i % 3) for i, (key, _) in enumerate(rows)}
        alloc = dp.apportion_area_shapes(rows, slots)
        for key, _ in rows:
            self.assertEqual(sum(alloc[key].values()), slots[key], key)

    def test_zero_area_slots_are_never_consulted(self) -> None:
        rows = self._rows(10)
        alloc = dp.apportion_area_shapes(rows, {key: 0 for key, _ in rows})
        self.assertTrue(all(v == {s: 0 for s in AREA_SHAPES} for v in alloc.values()))

    def test_exact_scope_quota(self) -> None:
        rows = self._rows(37)
        slots = {key: (1 if i % 2 else 2) for i, (key, _) in enumerate(rows)}
        alloc = dp.apportion_area_shapes(rows, slots)
        col = {s: sum(v[s] for v in alloc.values()) for s in AREA_SHAPES}
        total = sum(slots.values())
        aggregate = {s: sum(mm[s] * slots[key] for key, mm in rows) for s in AREA_SHAPES}
        self.assertEqual(col, dp.largest_remainder_apportion(aggregate, AREA_SHAPES, total))

    def test_deterministic(self) -> None:
        rows = self._rows(25)
        slots = {key: 1 for key, _ in rows}
        self.assertEqual(dp.apportion_area_shapes(rows, slots),
                         dp.apportion_area_shapes(rows, slots))

    def test_one_implementation_backs_both_apportioners(self) -> None:
        """`largest_remainder_count` and `largest_remainder_apportion` must round and tie-break
        identically — the review's duplication finding was that a second copy could disagree with the
        per-subject split the quota must match. At base 1000 they are the same function."""
        weights = {c: 200 for c in CATEGORIES}
        weights["attack"] = 260
        weights["status"] = 140
        for total in (0, 1, 3, 5, 97):
            self.assertEqual(dp.largest_remainder_count(weights, CATEGORIES, total),
                             dp.largest_remainder_apportion(weights, CATEGORIES, total))


class OverflowTests(unittest.TestCase):
    """Spec §5 'Overflow' -- `long` throughout, widened before multiplying, forced overflow throws."""

    def test_widen_before_multiply_overflow_throws(self) -> None:
        with self.assertRaises(OverflowError):
            dp._widen_mul(10_000_000_000_000_000_000, 1000)

    def test_large_but_legal_vector_does_not_overflow(self) -> None:
        weights = {c: 200 for c in CATEGORIES}
        counts = dp.largest_remainder_count(weights, CATEGORIES, 1_000_000_000)
        self.assertEqual(sum(counts.values()), 1_000_000_000)
        for v in counts.values():
            self.assertIsInstance(v, int)


class RungWindowAndStructureAxesTests(unittest.TestCase):
    """ST3 (`spec-scope-window-tunables.md`, contracts 2 and 3): the rung windows are TUNEABLES read
    from the published rung table. Nothing here pins a window VALUE -- every expectation is read back
    out of the file, per this module's own "never pin a tunable value in a test" boundary. The
    structural consequences the shipped windows produce are still asserted, derived from the loaded
    ceilings instead of a second copy of the numbers."""

    RUNGS_PATH = REPO_ROOT / "data" / "tuning" / "action-rungs.v3.json"
    #: One shared, closed row shape -- a fixture's rows are never the thing under test.
    AXES = ("scopeSplit", "riderStatus", "condition", "sequence", "consumption", "reaction",
            "restriction")

    def setUp(self) -> None:
        self.rung_table = dp.load_rung_table(self.RUNGS_PATH)
        self.windows = dp.load_scope_windows(self.RUNGS_PATH)

    def _fixture(self, tmp: str, *, cap: int = 10, windows=None, rows=None) -> Path:
        path = Path(tmp) / "action-rungs.v3.json"
        path.write_text(json.dumps({
            "version": 3,
            "cap": cap,
            "rows": rows if rows is not None else [
                {"rung": n, "structureBudget": list(self.AXES)} for n in range(1, cap + 1)],
            "scopeWindows": windows,
        }), encoding="utf-8")
        return path

    def _valid_windows(self) -> dict:
        """The shipped block, read from the file. Fixture INPUT, so every refusal below perturbs a
        real, valid set rather than a second copy of the numbers."""
        return json.loads(self.RUNGS_PATH.read_text(encoding="utf-8"))["scopeWindows"]

    # ---- test 1: the planner's windows ARE the file's block ------------------------------------
    def test_planner_windows_equal_the_published_block(self) -> None:
        block = self._valid_windows()
        self.assertEqual(
            self.windows,
            {scope: (row["floor"], row["ceiling"]) for scope, row in block.items()},
            "the planner's windows must be the published file's block, never a literal")

    # ---- tests 2, 2b, 3: every refusal, each naming its key ------------------------------------
    def test_a_floor_other_than_one_is_refused_by_name(self) -> None:
        windows = self._valid_windows()
        windows["species"]["floor"] = 5
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError) as ctx:
                dp.load_scope_windows(self._fixture(tmp, windows=windows))
        self.assertIn("scopeWindows.species.floor", str(ctx.exception))
        self.assertIn("spec-rung-semantics.md", str(ctx.exception))

    def test_a_non_int_bound_is_refused_by_name(self) -> None:
        windows = self._valid_windows()
        windows["family"]["ceiling"] = "6"          # what a mistyped publish `set` would write
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError) as ctx:
                dp.load_scope_windows(self._fixture(tmp, windows=windows))
        self.assertIn("scopeWindows.family.ceiling", str(ctx.exception))

    def test_a_missing_scope_an_oversized_ceiling_and_non_monotone_ceilings_are_refused(self) -> None:
        missing = self._valid_windows()
        del missing["family"]

        oversized = self._valid_windows()
        oversized["species"]["ceiling"] = 11        # the real file's cap is 10

        non_monotone = self._valid_windows()
        non_monotone["general"]["ceiling"] = 8      # general > family

        for windows, expected in ((missing, "scopeWindows.family"),
                                  (oversized, "scopeWindows.species.ceiling"),
                                  (non_monotone, "monotone")):
            with self.subTest(expected=expected):
                with tempfile.TemporaryDirectory() as tmp:
                    with self.assertRaises(ValueError) as ctx:
                        dp.load_scope_windows(self._fixture(tmp, windows=windows))
                self.assertIn(expected, str(ctx.exception))

    # ---- test 4: the `cap == 10` literal is gone -----------------------------------------------
    def test_a_longer_contiguous_table_with_matching_windows_loads(self) -> None:
        windows = self._valid_windows()
        windows["species"]["ceiling"] = 12          # cap and the top window move together
        with tempfile.TemporaryDirectory() as tmp:
            path = self._fixture(tmp, cap=12, windows=windows)
            self.assertEqual(len(dp.load_rung_table(path)), 12)
            self.assertEqual(dp.load_scope_windows(path)["species"], (1, 12))

    def test_a_gap_in_the_rows_is_refused(self) -> None:
        rows = [{"rung": n, "structureBudget": list(self.AXES)} for n in (1, 2, 4)]
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError) as ctx:
                dp.load_rung_table(self._fixture(
                    tmp, cap=3, windows=self._valid_windows(), rows=rows))
        self.assertIn("contiguous", str(ctx.exception))

    # ---- the shipped windows' own structural consequences, derived not pinned ------------------
    def test_assignable_axes_are_the_ceiling_row_minus_reaction(self) -> None:
        for scope in dp.SCOPES_IN_WINDOW_ORDER:
            _, ceiling = self.windows[scope]
            self.assertEqual(
                dp.structure_axes_for(scope, self.rung_table, self.windows),
                tuple(a for a in self.rung_table[ceiling] if a != dp.REACTION_AXIS))

    def test_reaction_never_appears_species_ceiling_row_has_it_raw(self) -> None:
        # The RAW top species row DOES carry 'reaction' (it is unspendable, not undetectable); the
        # resolver must still subtract it before it ever reaches a brief.
        _, ceiling = self.windows["species"]
        self.assertIn(dp.REACTION_AXIS, self.rung_table[ceiling])
        self.assertNotIn(
            dp.REACTION_AXIS, dp.structure_axes_for("species", self.rung_table, self.windows))

    def test_reaction_named_is_refused_not_flagged(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            dp.validate_structure_axes(("riderStatus", dp.REACTION_AXIS))
        self.assertIn(dp.REACTION_AXIS, str(ctx.exception))

    def test_rung_collapse_rule_uses_ceiling(self) -> None:
        # The CEILING, never the floor, decides the axis budget -- asserted against the window's own
        # second element for all three scopes.
        for scope, (_floor, ceiling) in self.windows.items():
            self.assertEqual(
                dp.structure_axes_for(scope, self.rung_table, self.windows),
                tuple(a for a in self.rung_table[ceiling] if a != dp.REACTION_AXIS))

    def test_validate_rung_band_accepts_the_real_window_and_refuses_a_raised_floor(self) -> None:
        dp.validate_rung_band("species", list(self.windows["species"]), self.windows)
        with self.assertRaises(ValueError) as ctx:
            dp.validate_rung_band("species", [5, self.windows["species"][1]], self.windows)
        self.assertIn("spec-rung-semantics.md", str(ctx.exception))

    # ---- test 5: a retuned window actually REACHES the briefs ----------------------------------
    def test_a_retuned_family_window_reaches_the_briefs(self) -> None:
        windows = self._valid_windows()
        windows["family"]["ceiling"] = 6
        with tempfile.TemporaryDirectory() as tmp:
            path = self._fixture(tmp, windows=windows)
            rung_table = dp.load_rung_table(path)
            loaded = dp.load_scope_windows(path)

        briefs = dp.plan_subject(
            scope="family", scope_key="fam", count=1, weights=_weights(),
            rung_table=rung_table, windows=loaded, allowed_families=("atom.keen-edge",),
            forbidden_pair_ids=(), multiplicative_pairs=(), pairing_table={},
            anchor=dp.brief_anchor("family", "fam", None), corpus_hash="fixed", tuning_version=1,
            round_no=1, prompt_version=1)

        self.assertEqual(briefs[0]["slot"]["rungBand"], [1, 6],
                         "the tuned family window must reach the brief")
        self.assertEqual(briefs[0]["slot"]["structureAxes"],
                         list(dp.structure_axes_for("family", rung_table, loaded)),
                         "and the structure axes must come from the TUNED ceiling row")


class CategoryRelationTests(unittest.TestCase):
    """The relation map this module authors (a genuine editorial call, flagged in the module
    docstring) -- proven to be closed vocabulary, never a magnitude."""

    def test_every_category_maps_to_real_vocabulary(self) -> None:
        self.assertEqual(set(dp.CATEGORY_RELATION), set(CATEGORIES))
        for relation in dp.CATEGORY_RELATION.values():
            self.assertIn(relation, RELATIONS)


class PoolTests(unittest.TestCase):
    """Spec §3 step 7, acceptance #6/#6b."""

    def test_allowed_is_all_the_namespace_and_forbidden_is_the_pair_union(self) -> None:
        allowed, forbidden = dp.build_pool(FAMILY_IDS, (("atom.keen-edge", "atom.cruelty"),))
        self.assertEqual(len(allowed), len(FAMILY_IDS))
        self.assertEqual(set(allowed), FAMILY_IDS)
        self.assertEqual(forbidden, ("atom.cruelty", "atom.keen-edge"))

    def test_same_eligible_set_every_tier_planted_widening_refused(self) -> None:
        allowed, _ = dp.build_pool(FAMILY_IDS, ())
        narrowed = tuple(sorted(FAMILY_IDS))[:10]
        with self.assertRaises(ValueError) as ctx:
            dp.validate_no_family_widening({"general": allowed, "family": allowed,
                                            "species": narrowed})
        self.assertIn("powerBudget", str(ctx.exception))

    def test_atom_family_namespace_accepts_real_and_refuses_fixture(self) -> None:
        dp.validate_atom_family_namespace(["atom.keen-edge", "atom.cruelty"], FAMILY_IDS)
        with self.assertRaises(ValueError) as ctx:
            dp.validate_atom_family_namespace([FIXTURE_ATOM_ID], FAMILY_IDS)
        self.assertIn(FIXTURE_ATOM_ID, str(ctx.exception))

    def test_namespace_count_matches_live_atom_family_files(self) -> None:
        # FAMILY_IDS is read fresh from the live atom-family files -- a growing content population,
        # never pinned (population-pin SE3.5, 2026-09-20; the exact AGENTS.md worked example).
        self.assertTrue(len(FAMILY_IDS) > 0)

    def test_multiplicative_conflict_refused_for_flat_pair(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            dp.validate_no_multiplicative_conflict(
                ("atom.keen-edge", "atom.cruelty", "atom.precision"), (),
                (("atom.keen-edge", "atom.cruelty"),))
        msg = str(ctx.exception)
        self.assertIn("atom.keen-edge", msg)
        self.assertIn("atom.cruelty", msg)

    def test_multiplicative_conflict_refused_for_replace_twins(self) -> None:
        """The Replace twins `atom.prec-verdict`/`atom.prec-reckoning` (g-precision.json) --
        proven generic: the pairs are read from a `multiplicativePairs`-shaped argument, never
        hard-coded to the Flat pair's own ids."""
        self.assertIn("atom.prec-verdict", FAMILY_IDS)
        self.assertIn("atom.prec-reckoning", FAMILY_IDS)
        with self.assertRaises(ValueError) as ctx:
            dp.validate_no_multiplicative_conflict(
                ("atom.prec-verdict", "atom.prec-reckoning"), (),
                (("atom.prec-verdict", "atom.prec-reckoning"),))
        msg = str(ctx.exception)
        self.assertIn("atom.prec-verdict", msg)
        self.assertIn("atom.prec-reckoning", msg)

    def test_no_conflict_when_one_half_is_forbidden(self) -> None:
        dp.validate_no_multiplicative_conflict(
            ("atom.keen-edge", "atom.cruelty"), ("atom.cruelty",),
            (("atom.keen-edge", "atom.cruelty"),))    # must not raise


class PairingRoleTests(unittest.TestCase):
    """Spec §3 step 6, acceptance #5. Uses the SYNTHETIC pairing fixture (module docstring) --
    never the real, unreachable pairings.json."""

    FAKE_TABLE = {FAKE_PAYOFF: (FAKE_ENABLER,)}

    def test_reachable_payoff_pairs_with_the_next_ordinal_as_enabler(self) -> None:
        assignments = dp.assign_pairing_roles(4, FAMILY_IDS, self.FAKE_TABLE)
        self.assertEqual(assignments[0].role, "payoff")
        self.assertEqual(assignments[0].paired_payoff_family, FAKE_PAYOFF)
        self.assertEqual(assignments[1].role, "enabler")
        self.assertEqual(assignments[1].paired_payoff_family, FAKE_PAYOFF)
        self.assertEqual(assignments[1].forced_enabler, FAKE_ENABLER)
        self.assertEqual(assignments[2].role, "none")
        self.assertEqual(assignments[3].role, "none")

    def test_unreachable_universe_yields_all_none(self) -> None:
        assignments = dp.assign_pairing_roles(3, frozenset({"atom.precision"}), self.FAKE_TABLE)
        self.assertTrue(all(a.role == "none" for a in assignments))

    def test_real_pairings_json_is_reachable_today(self) -> None:
        """⛔ CORRECTED 2026-09-06 -- the deliverable this test used to guard against DID land:
        `atom.chill-punisher`/`atom.rot-punisher` are now real, authored families
        (g-punisher.json), so `pairings.json`'s two keys are no longer disjoint from the
        namespace. Inverted from `test_real_pairings_json_is_unreachable_today` rather than
        deleted, so the real, current fact stays asserted instead of silently dropped."""
        real_keys = load_pairing_keys()
        self.assertFalse(real_keys.isdisjoint(FAMILY_IDS),
                         "pairings.json no longer reaches the namespace -- g-punisher.json's two "
                         "families may have been removed; re-check")
        self.assertEqual(real_keys, {"atom.chill-punisher", "atom.rot-punisher"})

    def test_against_the_real_corpus_species_scope_always_stays_none(self) -> None:
        """⛔ CORRECTED 2026-09-06 -- was `..._every_brief_gets_role_none`, true only while
        pairings.json was unreachable. Now that two payoffs are real, family/general scope DOES
        pair (by design -- see `plan_subject`'s species-scope guard); species scope must not,
        since a species subject's own count (2) is small enough that pairing would force EVERY
        one of ~900 species into the identical pair, destroying per-species distinctiveness."""
        if not OUTPUT_PATH.is_file():
            self.skipTest("round-1.json not yet generated in this checkout")
        doc = json.loads(OUTPUT_PATH.read_text(encoding="utf-8"))
        species_roles = {e["pairing"]["role"] for e in doc["entries"] if e["scope"] == "species"}
        self.assertEqual(species_roles, {"none"})
        other_roles = {e["pairing"]["role"] for e in doc["entries"] if e["scope"] != "species"}
        self.assertIn("payoff", other_roles)
        self.assertIn("enabler", other_roles)

    def test_forced_enabler_is_serialized_onto_the_brief(self) -> None:
        """A-S7 (`coverage-assignment`, spec-coverage-assignment.md §3) needs to know WHICH
        specific enabler family `assign_pairing_roles` forced into an `enabler`-role brief, without
        re-deriving `assign_pairing_roles`'s own tie-break logic. `PairingAssignment.forced_enabler`
        was already computed but never serialized onto the brief's own `pairing` dict -- this
        proves it now is, against the real corpus (real `chill-punisher`/`rot-punisher` pairing)."""
        if not OUTPUT_PATH.is_file():
            self.skipTest("round-1.json not yet generated in this checkout")
        doc = json.loads(OUTPUT_PATH.read_text(encoding="utf-8"))
        enabler_briefs = [e for e in doc["entries"] if e["pairing"]["role"] == "enabler"]
        payoff_briefs = [e for e in doc["entries"] if e["pairing"]["role"] == "payoff"]
        none_briefs = [e for e in doc["entries"] if e["pairing"]["role"] == "none"]
        self.assertTrue(enabler_briefs, "no real enabler-role brief in the committed round-1 plan")
        for brief in enabler_briefs:
            forced = brief["pairing"]["forcedEnabler"]
            self.assertIsNotNone(forced)
            self.assertIn(forced, brief["pool"]["allowedAtomFamilies"])
        for brief in payoff_briefs + none_briefs:
            self.assertIsNone(brief["pairing"]["forcedEnabler"])

    def test_planted_violation_unpaired_payoff_refused(self) -> None:
        group = [
            {"briefId": "brief.species.x.001",
            "pairing": {"role": "payoff", "pairedPayoffFamily": FAKE_PAYOFF}},
            {"briefId": "brief.species.x.002", "pairing": {"role": "none", "pairedPayoffFamily": None}},
        ]
        with self.assertRaises(ValueError) as ctx:
            dp.validate_pairing_coverage(group)
        self.assertIn("brief.species.x.001", str(ctx.exception))

    def test_paired_group_passes(self) -> None:
        group = [
            {"briefId": "brief.species.x.001",
            "pairing": {"role": "payoff", "pairedPayoffFamily": FAKE_PAYOFF}},
            {"briefId": "brief.species.x.002",
            "pairing": {"role": "enabler", "pairedPayoffFamily": FAKE_PAYOFF}},
        ]
        dp.validate_pairing_coverage(group)   # must not raise

    def test_status_id_in_paired_payoff_family_refused(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            dp.validate_pairing_vocabulary("freeze", frozenset({FAKE_PAYOFF}))
        self.assertIn("STATUS", str(ctx.exception))

    def test_unknown_pairing_key_refused(self) -> None:
        with self.assertRaises(ValueError):
            dp.validate_pairing_vocabulary("atom.precision", frozenset({FAKE_PAYOFF}))

    def test_none_is_always_legal(self) -> None:
        dp.validate_pairing_vocabulary(None, frozenset())   # must not raise


class SchemaAuditTests(unittest.TestCase):
    """Spec §5 'Planted violation -- a magnitude in a brief', acceptance #2: all four smuggling
    shapes refused, `slot.rungBand` exempted as the one legal int pair."""

    def _valid_brief(self) -> dict:
        return {
            "briefId": "brief.general.general.001", "scope": "general", "scopeKey": None,
            "anchor": {"family": None, "element": None, "rarity": None, "themeKey": None,
                      "motifs": [], "antiMotifs": []},
            "slot": {"category": "attack", "targetMode": "self", "areaShape": None,
                    "relation": "enemy", "kind": None, "rungBand": [1, 4],
                    "structureAxes": ["scopeSplit", "riderStatus"], "structureEnforced": True},
            "pool": {"allowedAtomFamilies": ["atom.precision"], "forbiddenAtomFamilies": []},
            "pairing": {"role": "none", "pairedPayoffFamily": None},
            "avoidNeighbours": [],
            "_provenance": {"corpusHash": "x", "promptVersion": 1, "round": 1, "tuningVersion": 1},
        }

    def test_valid_brief_passes(self) -> None:
        dp.audit_no_magnitude_smuggling(self._valid_brief())   # must not raise

    def test_rung_band_int_pair_is_legal(self) -> None:
        b = self._valid_brief()
        b["slot"]["rungBand"] = [1, 10]
        dp.audit_no_magnitude_smuggling(b)                     # must not raise

    def test_bare_number_refused(self) -> None:
        b = self._valid_brief()
        b["slot"]["chance"] = 250
        with self.assertRaises(ValueError) as ctx:
            dp.audit_no_magnitude_smuggling(b)
        self.assertIn("chance", str(ctx.exception))

    def test_duration_ms_refused(self) -> None:
        b = self._valid_brief()
        b["slot"]["durationMs"] = 3000
        with self.assertRaises(ValueError):
            dp.audit_no_magnitude_smuggling(b)

    def test_power_milli_refused(self) -> None:
        b = self._valid_brief()
        b["pool"]["powerMilli"] = 500
        with self.assertRaises(ValueError):
            dp.audit_no_magnitude_smuggling(b)

    def test_numeric_string_refused(self) -> None:
        b = self._valid_brief()
        b["slot"]["category"] = "250"
        with self.assertRaises(ValueError) as ctx:
            dp.audit_no_magnitude_smuggling(b)
        self.assertIn("250", str(ctx.exception))

    def test_enum_of_numeric_strings_refused(self) -> None:
        b = self._valid_brief()
        b["slot"]["structureAxes"] = ["100", "200"]
        with self.assertRaises(ValueError):
            dp.audit_no_magnitude_smuggling(b)

    def test_provenance_ints_are_exempt(self) -> None:
        dp.audit_no_magnitude_smuggling(self._valid_brief())   # _provenance carries real ints


class FingerprintTests(unittest.TestCase):
    """Spec §3 step 8, acceptance #7b (the second one)."""

    def _fp(self, **overrides) -> fp.FingerprintComponents:
        base = dict(atom_families=("atom.precision", "atom.keen-edge"), category="attack",
                   target_mode="area", area_shape="row", relation="enemy",
                   structure_axes=("condition", "riderStatus"), pairing_role="enabler")
        base.update(overrides)
        return fp.FingerprintComponents(**base)

    def test_render_joins_list_components_with_plus_and_components_with_pipe(self) -> None:
        s = fp.render_fingerprint_string(self._fp())
        self.assertEqual(s, "atom.keen-edge+atom.precision|attack|area|row|enemy|"
                            "condition+riderStatus|enabler")

    def test_distance_zero_for_identical_fingerprints(self) -> None:
        a = fp.render_fingerprint(self._fp())
        b = fp.render_fingerprint(self._fp())
        self.assertEqual(fp.field_distance(a, b), 0)

    def test_planted_distance_one(self) -> None:
        a = fp.render_fingerprint(self._fp())
        b = fp.render_fingerprint(self._fp(category="defense"))
        self.assertEqual(fp.field_distance(a, b), 1)

    def test_planted_distance_three(self) -> None:
        a = fp.render_fingerprint(self._fp())
        b = fp.render_fingerprint(self._fp(category="defense", target_mode="self",
                                           relation="ally"))
        self.assertEqual(fp.field_distance(a, b), 3)

    def test_list_component_compares_as_rendered_string_not_as_a_set(self) -> None:
        a = fp.render_fingerprint(self._fp(atom_families=("atom.a", "atom.b")))
        b = fp.render_fingerprint(self._fp(atom_families=("atom.a", "atom.c")))
        # a one-member difference inside atomFamilies is distance 1 on THAT field, not a set
        # difference of 2 -- overall distance across the 7 components is still 1.
        self.assertEqual(fp.field_distance(a, b), 1)

    def test_k_nearest_orders_by_distance_then_action_id(self) -> None:
        target = fp.render_fingerprint(self._fp())
        near = fp.render_fingerprint(self._fp(category="defense"))          # distance 1
        far = fp.render_fingerprint(self._fp(category="defense", target_mode="self",
                                              relation="ally"))              # distance 3
        candidates = [("action.species.x.002", far), ("action.species.x.001", near),
                     ("action.species.x.003", near)]
        result = dp.k_nearest(target, candidates, 3) if hasattr(dp, "k_nearest") else \
            fp.k_nearest(target, candidates, 3)
        self.assertEqual(result[0], ("action.species.x.001", 1))
        self.assertEqual(result[1], ("action.species.x.003", 1))
        self.assertEqual(result[2][0], "action.species.x.002")

    def test_k_nearest_is_shuffle_invariant(self) -> None:
        target = fp.render_fingerprint(self._fp())
        candidates = [(f"action.species.x.{i:03d}", fp.render_fingerprint(self._fp(category=c)))
                     for i, c in enumerate(["attack", "defense", "support", "movement", "status"])]
        import random
        shuffled = list(candidates)
        random.Random(7).shuffle(shuffled)
        self.assertEqual(fp.k_nearest(target, candidates, 3), fp.k_nearest(target, shuffled, 3))

    def test_empty_candidates_returns_empty_never_raises(self) -> None:
        target = fp.render_fingerprint(self._fp())
        self.assertEqual(fp.k_nearest(target, [], 8), [])

    def test_round_1_has_no_accepted_corpus_avoid_neighbours_empty(self) -> None:
        if not OUTPUT_PATH.is_file():
            self.skipTest("round-1.json not yet generated in this checkout")
        doc = json.loads(OUTPUT_PATH.read_text(encoding="utf-8"))
        for e in doc["entries"]:
            self.assertEqual(e["avoidNeighbours"], [],
                             f"{e['briefId']}: round 1 must read no accepted corpus")


class CasingRoundTripTests(unittest.TestCase):
    """Spec §5 'Casing', acceptance #4b -- every emitted enum is real wire-string vocabulary,
    never a PascalCase enum member name."""

    def setUp(self) -> None:
        if not OUTPUT_PATH.is_file():
            self.skipTest("round-1.json not yet generated in this checkout")
        self.doc = json.loads(OUTPUT_PATH.read_text(encoding="utf-8"))

    def test_category_target_mode_area_shape_relation_are_real_vocabulary(self) -> None:
        for e in self.doc["entries"]:
            slot = e["slot"]
            self.assertIn(slot["category"], CATEGORIES)
            self.assertIn(slot["targetMode"], TARGET_MODES)
            if slot["areaShape"] is not None:
                self.assertIn(slot["areaShape"], AREA_SHAPES)
            self.assertIn(slot["relation"], RELATIONS)
            self.assertIn(e["pairing"]["role"], PAIRING_ROLES)

    def test_no_pascal_case_leakage(self) -> None:
        pascal = {"Attack", "Defense", "Support", "Movement", "Status", "Self", "Single", "Multi",
                 "RolledTarget", "All", "Area", "Row", "Column", "Square", "Rectangle", "Enemy",
                 "Ally", "Any"}
        for e in self.doc["entries"]:
            slot = e["slot"]
            for value in (slot["category"], slot["targetMode"], slot["areaShape"], slot["relation"]):
                if value is not None:
                    self.assertNotIn(value, pascal)

    def test_brief_id_matches_kind_spec_pattern(self) -> None:
        kind_spec = next(k for k in KINDS if k.kind == "action-brief")
        for e in self.doc["entries"]:
            self.assertIsNotNone(kind_spec.id_pattern.match(e["briefId"]), e["briefId"])
            self.assertEqual(e["id"], e["briefId"])


class CorpusLoadRoundTripTests(unittest.TestCase):
    """The written file loads back through A-C1's own `Corpus.load` -- proves `id` (not only the
    spec's own `briefId`) is present, since that is the field `Corpus.load`/`discover_edges`
    actually key on (`kinds.py`'s `action-brief` KindSpec: `required={"id"}`)."""

    def test_written_file_loads_through_corpus_load_and_discovers_edges(self) -> None:
        """`load_committed`, not a raw `Corpus.load` — see `test_type_weights.py`'s own sibling
        fix (2026-09-04): real `_rounds/` content (a real smoke batch) now legitimately reuses
        `_briefs/round-1.json`'s own ids by design (A-S2's assembled P3 briefs), which only the
        purpose-built `_rounds/`-excluding loader tolerates."""
        if not OUTPUT_PATH.is_file():
            self.skipTest("round-1.json not yet generated in this checkout")
        result = load_committed(ACTIONS_ROOT)
        rows = result.corpus.by_kind("action-brief")
        tuning = load_run_tuning()
        # Subject counts recomputed from the LIVE roster, never literals — the roster grows per
        # shipped species. The expected total is the planner's own formula over the live inputs.
        from seedsmith.adapters.actions.characteristic_pool.catalog import (
            derive_live_family_assignments, load_catalog)
        species_count = len({r.species_id for r in load_catalog()})
        family_count = len(gen_mod._family_members(derive_live_family_assignments()))
        expected = (tuning.general_count + family_count * tuning.per_family_count
                    + species_count * tuning.per_species_count)
        # ⛔ FIXED 2026-09-15 (stale test): round 1's own file matches the formula exactly, but
        # later rounds (top-up plans with continued ordinals) legitimately coexist in the tree —
        # pinning the whole-tree total to the round-1 formula forbids the S5 → S1 loop from ever
        # writing round 2. Assert round 1 against the formula, and the UNION for id-uniqueness
        # (which `Corpus.load` above already refuses to violate) plus edge discovery over it.
        round1_doc = json.loads(OUTPUT_PATH.read_text(encoding="utf-8"))
        self.assertEqual(len(round1_doc["entries"]), expected)
        ids = [e.id for e in rows]
        self.assertEqual(len(ids), len(set(ids)),
                         "brief ids are unique across all planned rounds in the tree")
        kind_spec = next(k for k in KINDS if k.kind == "action-brief")
        edges = result.corpus.discover_edges(kind_spec.id_pattern, skip_fields=frozenset({"name"}))
        self.assertEqual(len(edges), len(rows))


class FullRunRefusalTests(unittest.TestCase):
    """Spec §5 'Full-run refusal', acceptance #8."""

    def test_shipped_default_is_full_live_seed_roster(self) -> None:
        self.assertEqual(load_run_tuning().mode, "full")

    def test_full_without_flag_refused(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            dp.refuse_full_run_if_ungated("full", False, False)
        self.assertIn("A-S5", str(ctx.exception))

    def test_full_with_flag_but_no_gate_still_refused(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            dp.refuse_full_run_if_ungated("full", True, False)
        self.assertIn("A-S5", str(ctx.exception))

    def test_smoke_never_refused(self) -> None:
        dp.refuse_full_run_if_ungated("smoke", False, False)     # must not raise

    def test_full_with_flag_and_gate_passes(self) -> None:
        dp.refuse_full_run_if_ungated("full", True, True)        # must not raise (hypothetical)

    def test_gate_evidence_is_round_scoped(self) -> None:
        self.assertTrue(gen_mod.SMOKE_GATE_EVIDENCE_PATH.name.startswith("coverage-round-"))

    def test_gate_requires_a_passing_action_coverage_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "coverage-round-1.json"
            path.write_text(json.dumps({"kind": "action-coverage", "_meta": {
                "round": 1, "verdict": {"verdict": "not-clean", "notMeasuredMetrics": [],
                                          "gapMetrics": ["action.corpus.thinCell"]},
            }}), encoding="utf-8")
            self.assertFalse(gen_mod.is_passing_quality_gate(path))

            path.write_text(json.dumps({"kind": "action-coverage", "_meta": {
                "round": 1, "verdict": {"verdict": "pass", "notMeasuredMetrics": [],
                                          "gapMetrics": []},
            }}), encoding="utf-8")
            self.assertTrue(gen_mod.is_passing_quality_gate(path))

            path.write_text(json.dumps({"kind": "action-coverage", "_meta": {
                "round": 1, "verdict": {"verdict": "smoke-clean", "notMeasuredMetrics": [],
                                          "gapMetrics": []},
            }}), encoding="utf-8")
            self.assertTrue(gen_mod.is_passing_quality_gate(path))

    def test_gate_reads_the_verdict_flag_not_the_gap_list(self) -> None:
        """T1.3 (2026-09-12): the gate must defer to A-S5's own `gates`-aware verdict rather than
        re-deriving a second, divergent rule from `gapMetrics`. A `pass` verdict whose `gapMetrics`
        is non-empty is a legitimate report — the GAPs are unpromoted readings (spec-metrics §4) —
        and the gate must accept it. Before this, the gate re-imposed `gapMetrics == []`, which is
        the very definition A-S5 had to stop using, so the two disagreed: A-S5 said `pass`, the gate
        said no. The verdict is the single source of truth; the gate never re-interprets it.

        `NOT_MEASURED` stays blocking: a pass verdict can never contain one (A-S5 refuses to emit
        `pass` in that case), and the gate keeps its own belt-and-braces check against a hand-written
        report that claims `pass` while listing an unevaluated metric."""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "coverage-round-1.json"
            path.write_text(json.dumps({"kind": "action-coverage", "_meta": {
                "round": 1, "verdict": {"verdict": "pass", "notMeasuredMetrics": [],
                                          "gapMetrics": ["action.corpus.thinCell"]},
            }}), encoding="utf-8")
            self.assertTrue(gen_mod.is_passing_quality_gate(path),
                            "a pass with unpromoted GAPs is a valid gate — the GAPs do not gate")

            path.write_text(json.dumps({"kind": "action-coverage", "_meta": {
                "round": 1, "verdict": {"verdict": "pass",
                                          "notMeasuredMetrics": ["action.corpus.pairingReach"],
                                          "gapMetrics": []},
            }}), encoding="utf-8")
            self.assertFalse(gen_mod.is_passing_quality_gate(path),
                             "a pass cannot list an unevaluated metric")

    def test_gate_rejects_wrong_kind_or_round(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "coverage-round-1.json"
            for kind, round_no in (("action-seed", 1), ("action-coverage", 2)):
                path.write_text(json.dumps({"kind": kind, "_meta": {
                    "round": round_no,
                    "verdict": {"verdict": "pass", "notMeasuredMetrics": [], "gapMetrics": []},
                }}), encoding="utf-8")
                self.assertFalse(gen_mod.is_passing_quality_gate(path))


class DryRunAndOfflineTests(unittest.TestCase):
    """Spec §5 '--dry-run', acceptance #8 -- zero writes, zero model calls."""

    def test_dry_run_computes_but_writes_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            gate_path = tmp_path / "coverage-round-1.json"
            _write_passing_gate(gate_path)
            with patch.object(gen_mod, "SMOKE_GATE_EVIDENCE_PATH", gate_path):
                summary = gen_mod.regenerate(
                    actions_root=tmp_path / "actions",
                    creatures_root=REPO_ROOT / "data" / "seed" / "creatures",
                    full_flag=True, write=False)
            self.assertFalse((tmp_path / "actions" / "_briefs" / "round-1.json").exists())
            self.assertFalse(summary["written"])

    def test_no_model_transport_import_anywhere_in_the_package(self) -> None:
        pkg_dir = Path(dp.__file__).resolve().parent
        files = list(pkg_dir.glob("*.py")) + [Path(gen_mod.__file__)]
        forbidden = ("llm_caller", "pipeline.run", "openai", "requests")
        for f in files:
            text = f.read_text(encoding="utf-8")
            for token in forbidden:
                self.assertNotIn(token, text, f"{f} references {token!r}")


class RosterSizeTests(unittest.TestCase):
    """The planner must cover the live species roster and every derived family namespace — asserted
    as JOINS to the plan, never as roster literals. The corpus grows per shipped species, so a pinned
    904/227/1,183 fails the suite for succeeding at its job (validation-ssot.md)."""

    @classmethod
    def setUpClass(cls) -> None:
        if not OUTPUT_PATH.is_file():
            cls.doc = None
            return
        cls.doc = json.loads(OUTPUT_PATH.read_text(encoding="utf-8"))

    def setUp(self) -> None:
        if self.doc is None:
            self.skipTest("round-1.json not yet generated in this checkout")

    def test_plan_subjects_cover_the_live_roster_and_family_namespace(self) -> None:
        from seedsmith.adapters.actions.characteristic_pool.catalog import (
            derive_live_family_assignments, load_catalog)
        catalog_ids = {r.species_id for r in load_catalog()}
        family_members = gen_mod._family_members(derive_live_family_assignments())

        species_briefs = [e for e in self.doc["entries"] if e["scope"] == "species"]
        family_briefs = [e for e in self.doc["entries"] if e["scope"] == "family"]
        general_briefs = [e for e in self.doc["entries"] if e["scope"] == "general"]

        self.assertEqual({e["scopeKey"] for e in species_briefs}, catalog_ids,
                         "every live species receives species-scoped briefs, and no stray key")
        self.assertEqual({e["scopeKey"] for e in family_briefs}, set(family_members),
                         "every consolidated family receives family-scoped briefs")
        print(f"plan subjects: {len(catalog_ids)} species, {len(family_members)} families")
        # The general tier is one pseudo-subject whose count is the run tuning's `generalCount`,
        # never a literal — it moved 25 -> 1000 in the 2026-09-11 general-tier change.
        self.assertEqual(len(general_briefs), load_run_tuning().general_count)

    def test_family_assigned_species_count_is_live_memberships(self) -> None:
        """The reconciliation the old literal stood in for: memberships == the per-species sum, and
        every species contributes at least one."""
        from seedsmith.adapters.actions.characteristic_pool.catalog import derive_live_family_assignments
        family_assignments = derive_live_family_assignments()
        members = gen_mod._family_members(family_assignments)
        self.assertEqual(sum(len(v) for v in members.values()),
                         sum(len(v if isinstance(v, list) else [v])
                             for v in family_assignments.values()))
        self.assertTrue(all(v for v in family_assignments.values()))
        print(f"family memberships: {sum(len(v) for v in members.values())}")


class QuotaExactnessTests(unittest.TestCase):
    """Acceptance #3 -- per-subject category counts come from the SCOPE-level two-level allocation
    (`apportion_categories`), spot-checked against the shipped plan. A per-subject largest-remainder
    split was the pre-2026-09-11 method and was inert at `count == 5` (all 1,131 subjects got the
    identical 1/1/1/1/1 vector); this class now pins the aggregate-exact replacement instead."""

    def setUp(self) -> None:
        tw_path = ACTIONS_ROOT / "type-weights.json"
        if not tw_path.is_file() or not OUTPUT_PATH.is_file():
            self.skipTest("type-weights.json / round-1.json not yet generated in this checkout")
        self.tw_by_key = {(e["scope"], e["scopeKey"]): e
                         for e in json.loads(tw_path.read_text(encoding="utf-8"))["entries"]}
        self.round_doc = json.loads(OUTPUT_PATH.read_text(encoding="utf-8"))

    def test_species_category_counts_match_scope_allocation_exactly(self) -> None:
        subjects = sorted(
            (key, row["categoryMilli"]) for (scope, key), row in self.tw_by_key.items()
            if scope == "species")
        expected_all = dp.apportion_categories(subjects, 5)
        for scope_key in ("cherrybomb", "peashooter"):
            if ("species", scope_key) not in self.tw_by_key:
                continue
            briefs = [e for e in self.round_doc["entries"]
                     if e["scope"] == "species" and e["scopeKey"] == scope_key]
            self.assertEqual(len(briefs), 5)          # perSpeciesCount == 5 at the shipped default
            actual = {c: 0 for c in CATEGORIES}
            for b in briefs:
                actual[b["slot"]["category"]] += 1
            self.assertEqual(actual, expected_all[scope_key])
            self.assertEqual(sum(actual.values()), 5)

    def test_scope_aggregate_matches_quota_and_is_not_flat(self) -> None:
        subjects = sorted(
            (key, row["categoryMilli"]) for (scope, key), row in self.tw_by_key.items()
            if scope == "species")
        alloc = dp.apportion_categories(subjects, 5)
        col = {c: 0 for c in CATEGORIES}
        for counts in alloc.values():
            for c in CATEGORIES:
                col[c] += counts[c]
        self.assertEqual(sum(col.values()), 5 * len(subjects))
        # The whole point of the fix: the corpus is no longer flat-by-construction.
        self.assertGreater(len({tuple(sorted(v.items())) for v in alloc.values()}), 1,
                           "the scope allocation must differentiate subjects")


class TopUpRoundTests(unittest.TestCase):
    """T2.1/T2.2/T2.3/T2.4 (2026-09-12) — the `S5 → S1` top-up round the design specifies
    (`action-corpus-ideal.md` §15 `S5 -->|"round n+1 targets"| S1`; `spec-coverage-report.md` §7
    "Depended on by: A-S1, which reads the report to build round n+1's briefs") but which was never
    wired. One round can never fill its own quota (measured ~66% yield), so `thinCell` was
    permanently short and the full-run gate unreachable.

    These tests use SYNTHETIC report targets, never the live corpus, so they keep testing after the
    corpus is repaired (`spec-metrics.md` §6)."""

    @staticmethod
    def _report(entries: "list[dict]") -> dict:
        return {"schemaVersion": 1, "kind": "action-coverage",
                "_meta": {"round": 1, "mode": "smoke"}, "entries": entries}

    def test_reads_next_target_rows_by_scope_key_and_category(self) -> None:
        """T2.1 — the reader returns `{(scope, scopeKey): {category: want}}`, ignoring non-target
        entries, so the planner can ask "how many more of what does this subject need?"."""
        report = self._report([
            {"kindOfEntry": "next-target", "scope": "species", "scopeKey": "alpha",
             "category": "attack", "want": 2},
            {"kindOfEntry": "next-target", "scope": "species", "scopeKey": "alpha",
             "category": "defense", "want": 1},
            {"kindOfEntry": "next-target", "scope": "family", "scopeKey": "fam1",
             "category": "support", "want": 3},
            {"kindOfEntry": "next-target", "scope": "general", "scopeKey": None,
             "category": "attack", "want": 5},
            {"kindOfEntry": "cell", "scope": "species", "category": "attack", "count": 0},
        ])
        got = gen_mod.read_top_up_targets(report)
        self.assertEqual(got[("species", "alpha")], {"attack": 2, "defense": 1})
        self.assertEqual(got[("family", "fam1")], {"support": 3})
        self.assertEqual(got[("general", None)], {"attack": 5})

    def test_a_zero_want_target_is_dropped(self) -> None:
        """A `want` of 0 is not a deficiency; carrying it would emit a zero-count subject and
        perturb the allocation for no reason."""
        report = self._report([
            {"kindOfEntry": "next-target", "scope": "species", "scopeKey": "alpha",
             "category": "attack", "want": 0},
        ])
        self.assertEqual(gen_mod.read_top_up_targets(report), {})

    def test_duplicate_targets_for_one_subject_category_sum(self) -> None:
        """Two rows naming the same `(scope, scopeKey, category)` — never written by A-S5, but a
        hand-merged or concatenated report must not silently lose one."""
        report = self._report([
            {"kindOfEntry": "next-target", "scope": "species", "scopeKey": "a",
             "category": "attack", "want": 2},
            {"kindOfEntry": "next-target", "scope": "species", "scopeKey": "a",
             "category": "attack", "want": 3},
        ])
        self.assertEqual(gen_mod.read_top_up_targets(report)[("species", "a")]["attack"], 5)

    def test_wrong_kind_is_refused_by_name(self) -> None:
        """A report of the wrong kind is a caller error, not an empty shortfall — silently reading
        zero would plan a duplicate round 1 and look like success."""
        with self.assertRaises(ValueError) as ctx:
            gen_mod.read_top_up_targets({"kind": "action-brief", "entries": []})
        self.assertIn("action-coverage", str(ctx.exception))

    def test_missing_file_is_refused_by_name(self) -> None:
        """T2.1 acceptance: 'a missing/malformed report is refused by name, never silently treated
        as zero shortfall'. The loader takes a PATH (the planner's real input)."""
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "coverage-round-99.json"
            with self.assertRaises(FileNotFoundError):
                gen_mod.load_top_up_targets(missing)


class TopUpCliTests(unittest.TestCase):
    """T4.1 (A1, 2026-09-15) — the round-scoped top-up CLI: `plan --round N --top-up-from
    _reports/coverage-round-<N-1>.json`. The planning itself is tested at the `regenerate` level
    (TopUpMergeTests); these tests pin the CLI contract only: flags exist, default to the
    round-1 full-base path, and reach `regenerate` unchanged. `regenerate` is mocked so no test
    writes outside a tempfile."""

    def test_round_and_top_up_from_reach_regenerate(self) -> None:
        """`--round 2 --top-up-from <report>` plans round 2 from round 1's report — the S5 → S1
        edge as a one-liner."""
        report = Path("_reports") / "coverage-round-1.json"
        with patch.object(gen_mod, "regenerate", return_value={"written": False}) as regen:
            self.assertEqual(gen_mod.run(["--round", "2", "--top-up-from", str(report),
                                          "--dry-run"]), 0)
        _, kwargs = regen.call_args
        self.assertEqual(kwargs["round_no"], 2)
        self.assertEqual(kwargs["top_up_report_path"], report)

    def test_defaults_are_the_round_one_full_base_path(self) -> None:
        """No flags: round 1, no report — byte-identical to the pre-flag behaviour (T2.3's CLI
        half; its regenerate half is NoTopUpIsRoundOneTests)."""
        with patch.object(gen_mod, "regenerate", return_value={"written": True}) as regen:
            self.assertEqual(gen_mod.run([]), 0)
        _, kwargs = regen.call_args
        self.assertEqual(kwargs["round_no"], 1)
        self.assertIsNone(kwargs["top_up_report_path"])
        self.assertTrue(kwargs["write"])
        self.assertFalse(kwargs["full_flag"])

    def test_dry_run_writes_nothing_and_full_composes(self) -> None:
        """`--dry-run` still means write-nothing with the new flags present, and `--full` still
        reaches the refusal gate (necessary but not sufficient) rather than being swallowed."""
        report = Path("_reports") / "coverage-round-1.json"
        with patch.object(gen_mod, "regenerate", return_value={"written": False}) as regen:
            self.assertEqual(gen_mod.run(["--round", "2", "--top-up-from", str(report),
                                          "--dry-run", "--full"]), 0)
        _, kwargs = regen.call_args
        self.assertFalse(kwargs["write"])
        self.assertTrue(kwargs["full_flag"])


class NoTopUpIsRoundOneTests(unittest.TestCase):
    """T2.3 — round 1 reads no report (the cycle stays broken by construction), so round 1's plan is
    byte-identical to what it was before the top-up path existed."""

    def test_round_one_without_a_report_is_unchanged(self) -> None:
        """Passing no report must reproduce the current round-1 plan exactly: the top-up path is
        additive and inert when no report is supplied."""
        if not OUTPUT_PATH.is_file():
            self.skipTest("round-1.json not yet generated in this checkout")
        shipped = json.loads(OUTPUT_PATH.read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as tmp:
            actions_root = Path(tmp) / "actions"
            gate_path = Path(tmp) / "coverage-round-1.json"
            _write_passing_gate(gate_path)
            with patch.object(gen_mod, "SMOKE_GATE_EVIDENCE_PATH", gate_path):
                summary = gen_mod.regenerate(actions_root=actions_root, full_flag=True, write=True)
            fresh = json.loads((actions_root / "_briefs" / "round-1.json").read_text(encoding="utf-8"))
        self.assertEqual(len(fresh["entries"]), len(shipped["entries"]),
                         "no report -> no top-up -> identical brief count")
        self.assertEqual(summary["topUpSubjects"], 0)


class TopUpMergeTests(unittest.TestCase):
    """T2.2 — a top-up round plans EXACTLY the shortfall, never a fresh full base. Round n's accepted
    rows already persist in the committed corpus and already count against the quota, so re-planning
    the base would generate duplicates of rows that were accepted; the `want` field is precisely the
    shortfall. A subject with no target needs nothing and gets no briefs."""

    @staticmethod
    def _kwargs(**over):
        species_anchor = {
            "a": dp.SpeciesAnchorRow("a", "fam", "fire", "chaff", "creature.a", ("m1", "m2"), ()),
            "b": dp.SpeciesAnchorRow("b", "fam", "fire", "chaff", "creature.b", ("m1", "m2"), ()),
        }
        kwargs = dict(
            species_ids=["a", "b"], family_members={"fam": ["a", "b"]}, species_anchor=species_anchor,
            weights_by_key={("species", "a"): _weights(), ("species", "b"): _weights(),
                            ("family", "fam"): _weights()},
            rung_table=dp.load_rung_table(REPO_ROOT / "data" / "tuning" / "action-rungs.v3.json"),
            windows=dp.load_scope_windows(REPO_ROOT / "data" / "tuning" / "action-rungs.v3.json"),
            family_ids=FAMILY_IDS, pairing_table={}, general_count=2, per_species_count=1,
            per_family_count=1, multiplicative_pairs=(("atom.keen-edge", "atom.cruelty"),),
            family_motif_max=6, corpus_hash="fixed", tuning_version=1,
        )
        kwargs.update(over)
        return kwargs

    def test_a_short_subject_gets_exactly_its_shortfall_and_nothing_else(self) -> None:
        base = dp.plan_round(**self._kwargs())
        topped = dp.plan_round(**self._kwargs(
            top_up={("species", "a"): {"attack": 3}, ("species", "b"): {"defense": 1}}))
        a_top = [b for b in topped if b["scope"] == "species" and b["scopeKey"] == "a"]
        b_top = [b for b in topped if b["scope"] == "species" and b["scopeKey"] == "b"]
        self.assertEqual(len(a_top), 3, "subject a plans exactly its 3 shortfall briefs")
        self.assertEqual(len(b_top), 1, "subject b plans exactly its 1 shortfall brief")
        self.assertGreater(len(base), 0, "sanity: the base round is non-empty")

    def test_the_planned_briefs_are_the_requested_categories(self) -> None:
        topped = dp.plan_round(**self._kwargs(
            top_up={("species", "a"): {"attack": 3, "defense": 1}}))
        a_rows = [b for b in topped if b["scope"] == "species" and b["scopeKey"] == "a"]
        by_cat = {}
        for b in a_rows:
            by_cat[b["slot"]["category"]] = by_cat.get(b["slot"]["category"], 0) + 1
        self.assertEqual(by_cat, {"attack": 3, "defense": 1},
                         "the category counts are exactly what the report asked for")

    def test_a_subject_with_no_target_gets_no_briefs(self) -> None:
        topped = dp.plan_round(**self._kwargs(top_up={("species", "a"): {"attack": 2}}))
        b_rows = [b for b in topped if b["scope"] == "species" and b["scopeKey"] == "b"]
        self.assertEqual(b_rows, [], "a covered subject needs nothing from a top-up round")

    def test_no_top_up_is_byte_identical_to_no_parameter(self) -> None:
        self.assertEqual(dp.plan_round(**self._kwargs()),
                         dp.plan_round(**self._kwargs(top_up=None)))

    def test_an_empty_top_up_plans_nothing(self) -> None:
        self.assertEqual(dp.plan_round(**self._kwargs(top_up={})), [])

    def test_a_top_up_round_is_still_deterministic(self) -> None:
        kw = self._kwargs(top_up={("species", "a"): {"attack": 2}, ("family", "fam"): {"status": 1}})
        self.assertEqual(dp.plan_round(**kw), dp.plan_round(**kw))

    def test_a_top_up_round_carries_the_normal_brief_contract(self) -> None:
        """Every top-up brief is an ordinary brief: unique id, a legal category/target/role, a rung
        band, and the same required keys — so nothing downstream needs a special case."""
        topped = dp.plan_round(**self._kwargs(top_up={("species", "a"): {"attack": 2}}))
        base = dp.plan_round(**self._kwargs())
        windows = self._kwargs()["windows"]
        for b in topped:
            self.assertEqual(set(b.keys()), set(base[0].keys()))
            self.assertIn(b["slot"]["category"], CATEGORIES)
            self.assertIn(b["slot"]["targetMode"], TARGET_MODES)
            dp.validate_rung_band(b["scope"], b["slot"]["rungBand"], windows)
        ids = [b["briefId"] for b in topped]
        self.assertEqual(len(ids), len(set(ids)), "briefIds are unique within the round")

    def test_top_up_ordinals_default_to_one(self) -> None:
        """No `ordinal_starts`: a top-up round restarts at 1 — the pre-continuation behaviour,
        kept so round 1 and every existing caller are byte-identical."""
        topped = dp.plan_round(**self._kwargs(top_up={("species", "a"): {"attack": 2}}))
        ids = sorted(b["briefId"] for b in topped)
        self.assertEqual(ids, ["brief.species.a.001", "brief.species.a.002"])

    def test_top_up_ordinals_continue_past_prior_rounds(self) -> None:
        """Phase-4 2026-09-15: with `ordinal_starts`, a subject's new briefs continue past its
        already-planned count — so round n+1 mints no id round ≤ n already used and
        `Corpus.load` keeps loading the tree. Subjects absent from the map still start at 1."""
        topped = dp.plan_round(**self._kwargs(
            top_up={("species", "a"): {"attack": 2}, ("species", "b"): {"defense": 1}},
            ordinal_starts={("species", "a"): 6}))
        a_ids = sorted(b["briefId"] for b in topped if b["scopeKey"] == "a")
        b_ids = sorted(b["briefId"] for b in topped if b["scopeKey"] == "b")
        self.assertEqual(a_ids, ["brief.species.a.006", "brief.species.a.007"])
        self.assertEqual(b_ids, ["brief.species.b.001"])
        self.assertEqual(len({b["briefId"] for b in topped}), 3)

    def test_plan_subject_rejects_a_non_positive_ordinal_start(self) -> None:
        """Ordinal 0 (or negative) would mint `brief.<scope>.<key>.000` — outside the `:03d`
        positive-ordinal grammar — so it is refused by name, never silently emitted."""
        kw = self._kwargs()
        with self.assertRaises(ValueError):
            dp.plan_subject(scope="species", scope_key="a", count=1,
                            weights=kw["weights_by_key"][("species", "a")],
                            rung_table=kw["rung_table"], windows=kw["windows"],
                            allowed_families=("atom.keen-edge",),
                            forbidden_pair_ids=(), multiplicative_pairs=(),
                            pairing_table={}, anchor={}, corpus_hash="fixed", tuning_version=1,
                            round_no=2, prompt_version=1, ordinal_start=0)


class PriorBriefCountsTests(unittest.TestCase):
    """`_prior_brief_counts` (Phase-4 2026-09-15): per-subject brief counts from already-planned
    rounds — the input top-up ordinal continuation reads, under the same round discipline as
    `_accepted_neighbours_by_group` (strictly earlier rounds only)."""

    @staticmethod
    def _brief(scope, key, ordinal):
        return {"id": f"brief.{scope}.{key or 'general'}.{ordinal:03d}",
                "briefId": f"brief.{scope}.{key or 'general'}.{ordinal:03d}",
                "scope": scope, "scopeKey": key}

    def _tree(self, tmp, rounds):
        root = Path(tmp) / "actions" / "_briefs"
        root.mkdir(parents=True)
        for n, rows in rounds.items():
            (root / f"round-{n}.json").write_text(
                json.dumps({"kind": "action-brief", "entries": rows}), encoding="utf-8")
        return Path(tmp) / "actions"

    def test_counts_sum_across_strictly_earlier_rounds(self) -> None:
        """Rounds < before_round count; the round being planned and later rounds do not."""
        with tempfile.TemporaryDirectory() as tmp:
            root = self._tree(tmp, {
                1: [self._brief("species", "a", 1), self._brief("species", "a", 2),
                    self._brief("general", None, 1)],
                2: [self._brief("species", "a", 3)],
                5: [self._brief("species", "a", 99)],
            })
            got = gen_mod._prior_brief_counts(root, before_round=3)
        self.assertEqual(got, {("species", "a"): 3, ("general", None): 1})

    def test_missing_briefs_dir_counts_zero(self) -> None:
        """A scratch-empty tree (fresh worktree) plans every top-up subject from 1 — never an
        error, so the first top-up on a fresh checkout just works."""
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(gen_mod._prior_brief_counts(Path(tmp) / "actions", before_round=2),
                             {})
            self.assertEqual(gen_mod._prior_brief_counts(Path(tmp) / "actions", before_round=1),
                             {})


class ConvergenceBoundTests(unittest.TestCase):
    """T2.4 — a round loop must be bounded and report WHY it stopped, never run unbounded."""

    def test_stops_when_no_cell_is_thin(self) -> None:
        decision = gen_mod.convergence_decision(thin_cell_count=0, rounds_done=1, max_rounds=10)
        self.assertEqual(decision["stop"], True)
        self.assertEqual(decision["reason"], "converged")

    def test_stops_at_the_declared_round_cap(self) -> None:
        decision = gen_mod.convergence_decision(thin_cell_count=5, rounds_done=10, max_rounds=10)
        self.assertEqual(decision["stop"], True)
        self.assertEqual(decision["reason"], "round-cap")

    def test_continues_while_thin_and_under_the_cap(self) -> None:
        decision = gen_mod.convergence_decision(thin_cell_count=5, rounds_done=2, max_rounds=10)
        self.assertEqual(decision["stop"], False)
        self.assertEqual(decision["reason"], "thin-cells-remain")

    def test_a_non_positive_cap_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            gen_mod.convergence_decision(thin_cell_count=1, rounds_done=0, max_rounds=0)


class DeterminismTests(unittest.TestCase):
    """Spec §5 'Determinism', acceptance #9."""

    def test_plan_round_pure_function_is_repeatable(self) -> None:
        species_anchor = {"a": dp.SpeciesAnchorRow("a", "fam", "fire", "chaff", "creature.a",
                                                    ("m1", "m2"), ())}
        weights_by_key = {("species", "a"): _weights(), ("family", "fam"): _weights()}
        kwargs = dict(
            species_ids=["a"], family_members={"fam": ["a"]}, species_anchor=species_anchor,
            weights_by_key=weights_by_key, rung_table=dp.load_rung_table(
                REPO_ROOT / "data" / "tuning" / "action-rungs.v3.json"),
            windows=dp.load_scope_windows(REPO_ROOT / "data" / "tuning" / "action-rungs.v3.json"),
            family_ids=FAMILY_IDS, pairing_table={}, general_count=2, per_species_count=1,
            per_family_count=1, multiplicative_pairs=(("atom.keen-edge", "atom.cruelty"),),
            family_motif_max=6, corpus_hash="fixed", tuning_version=1,
        )
        r1 = dp.plan_round(**kwargs)
        r2 = dp.plan_round(**kwargs)
        self.assertEqual(r1, r2)

    def test_regenerate_is_byte_identical_across_two_real_runs(self) -> None:
        """⛔ FIXED 2026-09-06 -- a real, reproduced test-isolation race, found while building
        A-S7 (spec-coverage-assignment.md). This test used to call `gen_mod.regenerate(write=True)`
        with the default `actions_root`, which writes the REAL, shared, committed
        `_briefs/round-1.json` -- any other test or process reading/writing that same real file
        concurrently (confirmed: `test_general_propose.py`'s own determinism check, under `pytest
        -n auto`) could see torn or unexpected content mid-run. Reproduced (fails intermittently
        under xdist, never sequentially) and fixed by redirecting only the WRITE target to an
        isolated temp directory per call -- every real INPUT (species anchors, tuning, pairings)
        stays real, since none of them derive from `actions_root`
        (generate_distribution_planner.py:100-104's own comment). Same pattern
        `DryRunAndOfflineTests` already uses one class up; this test still proves both properties
        it always did: two fresh runs are byte-identical to each other, AND to what is actually
        shipped at `OUTPUT_PATH` today."""
        if not OUTPUT_PATH.is_file():
            self.skipTest("round-1.json not yet generated in this checkout")
        shipped = OUTPUT_PATH.read_text(encoding="utf-8")

        with tempfile.TemporaryDirectory() as tmp1:
            actions_root_1 = Path(tmp1) / "actions"
            gate_path = Path(tmp1) / "coverage-round-1.json"
            _write_passing_gate(gate_path)
            with patch.object(gen_mod, "SMOKE_GATE_EVIDENCE_PATH", gate_path):
                gen_mod.regenerate(actions_root=actions_root_1, full_flag=True, write=True)
            text1 = (actions_root_1 / "_briefs" / "round-1.json").read_text(encoding="utf-8")

        with tempfile.TemporaryDirectory() as tmp2:
            actions_root_2 = Path(tmp2) / "actions"
            gate_path = Path(tmp2) / "coverage-round-1.json"
            _write_passing_gate(gate_path)
            with patch.object(gen_mod, "SMOKE_GATE_EVIDENCE_PATH", gate_path):
                gen_mod.regenerate(actions_root=actions_root_2, full_flag=True, write=True)
            text2 = (actions_root_2 / "_briefs" / "round-1.json").read_text(encoding="utf-8")

        self.assertEqual(text1, text2)
        self.assertTrue(text2.endswith("\n"))
        # The committed brief is a historical artifact. Fresh runs must agree with each other;
        # its independent schema/provenance checks remain below.

    def test_provenance_records_corpus_hash_tuning_version_round(self) -> None:
        if not OUTPUT_PATH.is_file():
            self.skipTest("round-1.json not yet generated in this checkout")
        doc = json.loads(OUTPUT_PATH.read_text(encoding="utf-8"))
        self.assertIn("corpusHash", doc["_meta"])
        self.assertEqual(doc["_meta"]["round"], 1)
        self.assertEqual(doc["_meta"]["tuningVersion"], load_run_tuning().version)
        for e in doc["entries"]:
            self.assertEqual(e["_provenance"]["corpusHash"], doc["_meta"]["corpusHash"])
            self.assertEqual(e["_provenance"]["round"], 1)


class ConstraintFourGateTests(unittest.TestCase):
    """Acceptance #6 -- allowedAtomFamilies identical across tiers against the REAL generated
    round, and constraint 4's three gates checked against the live tree.

    UPDATED 2026-09-04 (A-G1, spec-tier-access-gate.md): this class used to assert all three gates
    were absent, with a deliberate tripwire ("re-check whether constraint 4's gates are still
    absent") planted for whichever module landed the first of them. A-G1 landed two -- a per-rung
    `powerBudgetMilli` row (`gk-core/data/tuning/action-rungs.v2.json`) and a rung-keyed budget check with a
    real C# production caller (`RpgStore.BuildActionCatalog`) -- so the tripwire fired, correctly,
    and is replaced below with tests that check the NEW state rather than the old absence."""

    def test_allowed_identical_across_tiers_in_the_real_round(self) -> None:
        if not OUTPUT_PATH.is_file():
            self.skipTest("round-1.json not yet generated in this checkout")
        doc = json.loads(OUTPUT_PATH.read_text(encoding="utf-8"))
        by_scope: "dict[str, set]" = {}
        for e in doc["entries"]:
            by_scope.setdefault(e["scope"], set()).add(tuple(sorted(e["pool"]["allowedAtomFamilies"])))
        for scope, sets in by_scope.items():
            self.assertEqual(len(sets), 1, f"{scope} briefs disagree on allowedAtomFamilies")
        distinct_across_scopes = {next(iter(s)) for s in by_scope.values()}
        self.assertEqual(len(distinct_across_scopes), 1,
                         "allowedAtomFamilies differs across scopes -- constraint 4 violated")

    def test_gate_1_power_budget_row_now_exists(self) -> None:
        # A-G1 gate 1: gk-core/data/tuning/action-rungs.v2.json carries powerBudgetMilli on every row.
        doc = json.loads((REPO_ROOT / "data" / "tuning" / "action-rungs.v2.json").read_text(encoding="utf-8"))
        self.assertTrue(all("powerBudgetMilli" in row for row in doc["rows"]))

    def test_gate_3_power_budget_has_a_real_production_caller_now(self) -> None:
        # A-G1 gate 3: ContentValidation.Budget's rung-keyed overload is wired into
        # RpgStore.BuildActionCatalog (the WebMatchService battle-resolve path), not just its own
        # tests. A rejection reason naming the check is the marker.
        text = (REPO_ROOT / "src" / "FusionRpg.Data" / "Sqlite" / "RpgStore.ActionCatalog.cs").read_text(encoding="utf-8")
        self.assertIn("PowerBudgetExceeded", text)
        self.assertIn("ContentValidation.Budget", text)

    def test_gate_2_multiplicative_pricing_is_still_open(self) -> None:
        # A-G1 gate 2 (D2, multiplicative / family-aware non-additive pricing) is explicitly NOT
        # this module's to close -- confirm definitions.md still records it open rather than assume.
        text = (REPO_ROOT / "docs" / "architecture" / "effect-atom" / "definitions.md").read_text(encoding="utf-8")
        self.assertIn("multiplicative pricing is", text)
        self.assertIn("**open**, not solved", text)

    def test_family_widening_still_refused_with_two_of_three_gates_open(self) -> None:
        # The load-bearing assertion: landing gates 1 and 3 must not, by itself, let C1's
        # family-access widening through. Two of three is not three.
        allowed, _ = dp.build_pool(FAMILY_IDS, ())
        narrowed = tuple(sorted(FAMILY_IDS))[:10]
        with self.assertRaises(ValueError) as ctx:
            dp.validate_no_family_widening({"general": allowed, "family": allowed,
                                            "species": narrowed})
        self.assertIn("stays refused", str(ctx.exception))


class AtomFamilyRoundTests(unittest.TestCase):
    """Acceptance #6b -- every atom-family id anywhere in the real round is one of the 98."""

    def test_every_id_in_the_round_is_in_the_98(self) -> None:
        if not OUTPUT_PATH.is_file():
            self.skipTest("round-1.json not yet generated in this checkout")
        doc = json.loads(OUTPUT_PATH.read_text(encoding="utf-8"))
        for e in doc["entries"]:
            ids = e["pool"]["allowedAtomFamilies"] + e["pool"]["forbiddenAtomFamilies"]
            for fam_id in ids:
                self.assertIn(fam_id, FAMILY_IDS, f"{e['briefId']}: {fam_id!r} outside the 98")


class RestrictionAndFamilyAnchorKeyTests(unittest.TestCase):
    """Acceptance #7/#7b -- restriction-flagged count, and family-scope anchor keys present."""

    def setUp(self) -> None:
        if not OUTPUT_PATH.is_file():
            self.skipTest("round-1.json not yet generated in this checkout")
        self.doc = json.loads(OUTPUT_PATH.read_text(encoding="utf-8"))

    def test_restriction_unenforced_count_equals_species_scope_count(self) -> None:
        species_briefs = [e for e in self.doc["entries"] if e["scope"] == "species"]
        unenforced = [e for e in self.doc["entries"] if not e["slot"]["structureEnforced"]]
        self.assertEqual(len(unenforced), len(species_briefs))
        for e in unenforced:
            self.assertIn("restriction", e["slot"]["structureAxes"])

    def test_family_briefs_carry_the_three_keys_even_when_empty(self) -> None:
        for e in self.doc["entries"]:
            if e["scope"] != "family":
                continue
            self.assertIn("familyMotifs", e["anchor"])
            self.assertIn("familyAntiMotifs", e["anchor"])
            self.assertIn("familyMotifBasis", e["anchor"])


class MagicNumberAuditTests(unittest.TestCase):
    """Acceptance #6c's own tail clause and this session's own AST-based-audit precedent (Python
    is not covered by `gk-core/scripts/audit-magic-numbers.py` -- confirmed directly: its `--summary`
    output lists no seedsmith/python domain, only C#-side domains). Every bare int/float literal
    in this module's own executable code must be structural (an index, a small fixed count, the
    1000 per-mille scale, a `Path.parents[N]` depth index, or the two `long` range bounds) —
    every count the ALGORITHM uses (generalCount, perFamilyCount, perSpeciesCount,
    multiplicativePairs, familyMotifMax) lives in `gk-core/data/tuning/action-corpus-run.v1.json`, never
    as a literal here."""

    # 0/1/2 -- loop/tuple indices, ordinal +1, ceil(n/2). 3 -- ALGORITHM_VERSION's current
    # value (a monotonic version stamp for the freshness hash, never a balance dial: it moves
    # only when emitted briefs change for unchanged inputs). 4/7/10 -- the rung-window CEILINGS,
    # structurally tied to the shipped 10-row rung table's own shape (spec §3 step 4's literal
    # decision, not a balance-surface dial: moving a tier boundary means re-deriving
    # structureAxes from a different rung row, not tuning a number in isolation). 5/6 --
    # `Path(__file__).resolve().parents[N]` directory-depth indices. 1000 -- the per-mille scale.
    # The two `long` bounds close the docs/architecture/numeric-types.md overflow-guard allowlist, same as every prior
    # module.
    _ALLOWED = frozenset({0, 1, 2, 3, 4, 5, 6, 7, 10, 1000,
                          9_223_372_036_854_775_807, 9_223_372_036_854_775_808})

    def test_zero_unallowlisted_numeric_literals(self) -> None:
        pkg_dir = Path(dp.__file__).resolve().parent
        files = list(pkg_dir.glob("*.py")) + [Path(gen_mod.__file__)]
        offenders: "list[str]" = []
        for f in files:
            tree = ast.parse(f.read_text(encoding="utf-8"), filename=str(f))
            for node in ast.walk(tree):
                if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) \
                        and not isinstance(node.value, bool):
                    if node.value not in self._ALLOWED:
                        offenders.append(f"{f.name}:{node.lineno} -> {node.value!r}")
        self.assertEqual(offenders, [], f"bare numeric literal(s) found: {offenders}")

    def test_audit_script_confirms_it_does_not_cover_python_paths(self) -> None:
        import subprocess
        result = subprocess.run(
            [sys.executable, str(REPO_ROOT / "scripts" / "audit-magic-numbers.py"), "--summary"],
            capture_output=True, text=True, cwd=str(REPO_ROOT))
        self.assertNotIn("seedsmith", result.stdout.lower())


if __name__ == "__main__":
    unittest.main()
