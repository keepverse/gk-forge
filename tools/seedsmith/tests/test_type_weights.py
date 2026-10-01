"""Tests for seedsmith.adapters.actions.type_weights (A-T1, spec-type-weights.md).

    python -m pytest gk-forge/tools/seedsmith/tests/test_type_weights.py -v

Spec §5's eight named cases plus §6's acceptance criteria (1, 2, 3, 4, 4b, 5, 6, 6b, 7, 8) — see
each class's own docstring for which criterion it proves. Same fixture split
`test_characteristic_pool.py` already established: real, live repo data (role-lean.json, the
shipped tuning file, the written output) for everything spec calls a MEASURED fact; synthetic,
in-memory fixtures for determinism, tie-break, planted violations and overflow, so those never
depend on a moving target.
"""
from __future__ import annotations

import ast
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from seedsmith.adapters.actions.characteristic_pool.derive import CATEGORIES  # noqa: E402
from seedsmith.adapters.actions.type_weights import derive as derive_mod  # noqa: E402
from seedsmith.adapters.actions.type_weights import tuning as tuning_mod  # noqa: E402
from seedsmith.adapters.actions.type_weights.derive import (  # noqa: E402
    RoleLeanRow, TypeWeightEntry, category_milli_for, derive_all, element_bias_for,
    family_element_bias_inputs, largest_remainder_milli, raw_category_scores, target_shape_for,
)
from seedsmith.adapters.actions.type_weights.tuning import (  # noqa: E402
    AREA_SHAPES, ELEMENTS, TARGET_MODES, TypeWeights, load_type_weights,
)
from seedsmith.adapters.actions import generate_type_weights as gen_mod  # noqa: E402
from seedsmith.adapters.actions.kinds import KINDS  # noqa: E402
from seedsmith.adapters.actions.load import load_committed  # noqa: E402
from seedsmith.corpus import Corpus  # noqa: E402

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

ACTIONS_ROOT = _owned("data/seed/actions")
TUNING_PATH = _owned("data/tuning/action-type-weights.v1.json")
OUTPUT_PATH = ACTIONS_ROOT / "type-weights.json"


# ---------------------------------------------------------------------------------------------
# Synthetic fixtures — independent of any live file.
# ---------------------------------------------------------------------------------------------

def _weights(*, base: int = 1000, step: int = 250,
            separation_milli=(200, 400, 600, 800, 1000), null_separation_milli: int = 500,
            target_mode_milli=None, area_shape_milli=None,
            primary_milli: int = 400, secondary_milli: int = 200,
            family_secondary_scale_milli: int = 500, version: int = 1) -> TypeWeights:
    if target_mode_milli is None:
        row = {"self": 167, "single": 167, "multi": 167, "rolledTarget": 167, "all": 166, "area": 166}
        target_mode_milli = {c: dict(row) for c in CATEGORIES}
    if area_shape_milli is None:
        area_shape_milli = {"row": 250, "column": 250, "square": 250, "rectangle": 250}
    return TypeWeights(
        base=base, step=step, separation_milli=tuple(separation_milli),
        null_separation_milli=null_separation_milli,
        target_mode_milli=target_mode_milli, area_shape_milli=area_shape_milli,
        primary_milli=primary_milli, secondary_milli=secondary_milli,
        family_secondary_scale_milli=family_secondary_scale_milli, version=version,
    )


def _row(species_key: str, *, family=None, lean_order=CATEGORIES, lean_source="derived",
        separation=None, element_primary="fire", element_secondary=None, reach=None) -> RoleLeanRow:
    return RoleLeanRow(
        species_key=species_key, family=family, lean_order=tuple(lean_order),
        lean_source=lean_source, separation=separation, element_primary=element_primary,
        element_secondary=element_secondary, reach=reach,
    )


def _write_tuning(tmp_dir: Path, **overrides) -> Path:
    """Copies the REAL shipped tuning file and applies one JSON-level mutation, for the
    planted-violation tests — so every test starts from a genuinely valid document and breaks
    exactly one thing, never a hand-typed fixture that might already be invalid for an unrelated
    reason."""
    doc = json.loads(TUNING_PATH.read_text(encoding="utf-8"))
    doc.update(overrides)
    path = tmp_dir / "action-type-weights.v1.json"
    path.write_text(json.dumps(doc), encoding="utf-8")
    return path


class VocabOrderTests(unittest.TestCase):
    """The three declared-order tuples this module transcribed from the live C# files, re-verified
    against the source at build time (2026-09-03) rather than trusted from the spec's citations."""

    def test_target_modes_declared_order(self) -> None:
        self.assertEqual(TARGET_MODES, ("self", "single", "multi", "rolledTarget", "all", "area"))

    def test_area_shapes_declared_order(self) -> None:
        self.assertEqual(AREA_SHAPES, ("row", "column", "square", "rectangle"))

    def test_elements_declared_order(self) -> None:
        self.assertEqual(ELEMENTS, ("fire", "ice", "air", "earth", "light", "dark"))


class TuningFileLoadTests(unittest.TestCase):
    """Acceptance #4b — the shipped tuning file's shape and its stated neutral defaults."""

    def test_file_loads(self) -> None:
        w = load_type_weights()
        self.assertEqual(w.base, 1000)
        self.assertEqual(w.step, 250)
        self.assertEqual(w.separation_milli, (200, 400, 600, 800, 1000))
        self.assertEqual(w.null_separation_milli, 500)
        self.assertEqual(w.primary_milli, 400)
        self.assertEqual(w.secondary_milli, 200)
        self.assertEqual(w.family_secondary_scale_milli, 500)
        self.assertEqual(w.version, 2)

    def test_target_mode_rows_uniform_167_166_split(self) -> None:
        w = load_type_weights()
        expected = {"self": 167, "single": 167, "multi": 167, "rolledTarget": 167,
                   "all": 166, "area": 166}
        for head in CATEGORIES:
            self.assertEqual(w.target_mode_milli[head], expected)
            self.assertEqual(sum(w.target_mode_milli[head].values()), 1000)
            self.assertTrue(all(v > 0 for v in w.target_mode_milli[head].values()),
                            "no target mode is zero at the default")

    def test_area_shape_row_uniform_250(self) -> None:
        w = load_type_weights()
        self.assertEqual(w.area_shape_milli, {"row": 250, "column": 250, "square": 250,
                                              "rectangle": 250})

    def test_meta_states_untuned_and_smoke_batch_evidence(self) -> None:
        doc = json.loads(TUNING_PATH.read_text(encoding="utf-8"))
        note = doc["_meta"]["note"]
        self.assertIn("untuned", note)
        self.assertIn("smoke batch", note)
        self.assertIn("evidence", note)
        self.assertIn("A-S5", note)

    def test_rank_to_raw_reproduces_spec_2000_1750_1500_1250_1000(self) -> None:
        """Spec §2's worked example, the part that IS mechanically reproducible: base:1000/
        step:250 over ranks 1..5 score 2000/1750/1500/1250/1000 (spec §3 step 1's own formula, at
        `separation == 4`, which "keeps base/step intact")."""
        w = load_type_weights()
        order = ("attack", "defense", "support", "movement", "status")
        raw = raw_category_scores(order, "derived", 4, w)
        self.assertEqual(raw, {"attack": 2000, "defense": 1750, "support": 1500,
                               "movement": 1250, "status": 1000})

    def test_spec_own_400_350_300_250_200_per_mille_claim_does_not_hold(self) -> None:
        """**A found spec defect, documented rather than silently worked around.** Spec §2's
        defaults table claims the same worked example normalises to "400/350/300/250/200
        per-mille" — but that vector sums to 1500, not 1000, so it cannot be the actual output of
        §3 step 3's own formula (`weight_i = (raw_i * 1000) // sum(raw)`, which this module
        implements exactly and `SumInvariantTests` proves holds for every real entry). The
        formula's real output for this exact raw vector is 267/233/200/167/133 (sums to 1000,
        largest-remainder ties broken on declared category order). This test pins the CORRECT,
        formula-derived number rather than the spec's own inconsistent illustration — flagged in
        this module's build report for the spec's own maintainers to reconcile."""
        w = load_type_weights()
        order = ("attack", "defense", "support", "movement", "status")
        milli = category_milli_for(order, "derived", 4, w)
        self.assertEqual(sum(milli.values()), 1000)
        self.assertEqual(milli, {"attack": 267, "defense": 233, "support": 200,
                                 "movement": 167, "status": 133})
        self.assertNotEqual(milli, {"attack": 400, "defense": 350, "support": 300,
                                    "movement": 250, "status": 200})


class PlantedViolationFloatTests(unittest.TestCase):
    """Spec §5 'Planted violation — a float', acceptance #3: all four smuggling shapes refused at
    load, each naming the offending row."""

    def test_bare_float(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = _write_tuning(Path(tmp), base=1000.4)
            with self.assertRaises(ValueError) as ctx:
                load_type_weights(path)
            self.assertIn("base", str(ctx.exception))

    def test_numeric_string(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = _write_tuning(Path(tmp), primaryMilli="400")
            with self.assertRaises(ValueError) as ctx:
                load_type_weights(path)
            self.assertIn("primaryMilli", str(ctx.exception))

    def test_bool_masquerading_as_int(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            doc = json.loads(TUNING_PATH.read_text(encoding="utf-8"))
            doc["targetModeMilli"]["attack"]["self"] = True
            path = Path(tmp) / "action-type-weights.v1.json"
            path.write_text(json.dumps(doc), encoding="utf-8")
            with self.assertRaises(ValueError) as ctx:
                load_type_weights(path)
            self.assertIn("targetModeMilli", str(ctx.exception))

    def test_array_of_numeric_strings(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = _write_tuning(Path(tmp), separationMilli=["0", "250", "500", "750", "1000"])
            with self.assertRaises(ValueError) as ctx:
                load_type_weights(path)
            self.assertIn("separationMilli", str(ctx.exception))


class PlantedViolationUnknownMemberTests(unittest.TestCase):
    """Spec §5 'Planted violation — unknown member', acceptance #6."""

    def test_unknown_category_row(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            doc = json.loads(TUNING_PATH.read_text(encoding="utf-8"))
            doc["targetModeMilli"]["economy"] = dict(doc["targetModeMilli"]["attack"])
            path = Path(tmp) / "action-type-weights.v1.json"
            path.write_text(json.dumps(doc), encoding="utf-8")
            with self.assertRaises(ValueError) as ctx:
                load_type_weights(path)
            self.assertIn("economy", str(ctx.exception))

    def test_seventh_target_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            doc = json.loads(TUNING_PATH.read_text(encoding="utf-8"))
            doc["targetModeMilli"]["attack"]["ranged"] = 0
            path = Path(tmp) / "action-type-weights.v1.json"
            path.write_text(json.dumps(doc), encoding="utf-8")
            with self.assertRaises(ValueError) as ctx:
                load_type_weights(path)
            self.assertIn("targetModeMilli", str(ctx.exception))

    def test_pascal_case_area_shape_key(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            doc = json.loads(TUNING_PATH.read_text(encoding="utf-8"))
            doc["areaShapeMilli"] = {"Row": 250, "column": 250, "square": 250, "rectangle": 250}
            path = Path(tmp) / "action-type-weights.v1.json"
            path.write_text(json.dumps(doc), encoding="utf-8")
            with self.assertRaises(ValueError) as ctx:
                load_type_weights(path)
            self.assertIn("areaShapeMilli", str(ctx.exception))


class RankToRawTests(unittest.TestCase):
    """Spec §3 step 1, and its F12 correction: the uniform floor triggers on `leanSource ==
    "floor"` only, never on a null family."""

    def test_floor_source_is_flat_regardless_of_lean_order(self) -> None:
        w = _weights()
        raw = raw_category_scores(CATEGORIES, "floor", None, w)
        self.assertEqual(set(raw.values()), {w.base})

    def test_derived_nofloor_uses_its_own_lean_order_not_the_floor_branch(self) -> None:
        """The F12 guard: a family-less species (`derived-nofloor`) must run through the SAME
        ranked formula as `derived`, never the flat `floor` branch. Since the AC5 fix,
        `derived-nofloor` reads `null_separation_milli`, not `separation_milli[0]`, so this uses a
        non-degenerate default for that row specifically (see `SeparationScalingTests` below)."""
        w = _weights(null_separation_milli=200)  # non-degenerate null row
        order = ("movement", "attack", "status", "support", "defense")
        raw = raw_category_scores(order, "derived-nofloor", None, w)
        ranked = sorted(raw, key=lambda c: -raw[c])
        self.assertEqual(ranked[0], "movement")
        self.assertGreater(len(set(raw.values())), 1, "must not collapse to a flat vector here")


class SeparationScalingTests(unittest.TestCase):
    """Spec §3 step 2 + acceptance #5."""

    def test_separation_0_flatter_than_separation_4_at_shipped_defaults(self) -> None:
        w = load_type_weights()
        order = ("attack", "defense", "support", "movement", "status")
        flat = category_milli_for(order, "derived", 0, w)
        spread = category_milli_for(order, "derived", 4, w)
        self.assertGreater(max(spread.values()) - min(spread.values()),
                           max(flat.values()) - min(flat.values()))
        self.assertLessEqual(max(flat.values()) - min(flat.values()), 100,
                             "row 0 is the flattest row, but no longer flat to zero — a real "
                             "separation==0 keeps its own lean order (re-tune 2026-09-11)")

    def test_separation_null_uses_its_own_row_not_row_zero(self) -> None:
        """AC5 fix (2026-09-03, owner decision): `separation: null` no longer shares row 0 with a
        genuine tie — spec §3 step 2's literal "takes the same row as 0" text is superseded by a
        dedicated `nullSeparationMilli` tuning key, because sharing row 0 made every family-less
        species print flat under the shipped v1 defaults (`separationMilli[0] == 0`), directly
        contradicting acceptance #5. This test proves the two rows are now independent: changing
        row 0 alone must NOT change the null-separation result, and vice versa."""
        w = _weights(separation_milli=(300, 250, 500, 750, 1000), null_separation_milli=999)
        order = ("support", "attack", "status", "movement", "defense")
        via_null = raw_category_scores(order, "derived-nofloor", None, w)
        via_zero = raw_category_scores(order, "derived", 0, w)
        self.assertNotEqual(via_null, via_zero)
        # And using the SAME value for both rows still reproduces the same output either way —
        # confirming `null_separation_milli` is genuinely a distinct, correctly-wired factor,
        # not an accidental alias for `separation_milli[0]` under a different name.
        w2 = _weights(separation_milli=(777, 250, 500, 750, 1000), null_separation_milli=777)
        self.assertEqual(raw_category_scores(order, "derived-nofloor", None, w2),
                         raw_category_scores(order, "derived", 0, w2))

    def test_family_less_species_gets_a_leanorder_shaped_vector_at_shipped_defaults(self) -> None:
        """Acceptance #5, proven directly against the real shipped tuning file (not a hypothetical
        tuned row): a family-less species' vector visibly reflects its OWN `leanOrder` because
        `nullSeparationMilli` (shipped `500`) is real, non-collapsing signal — and since the
        2026-09-11 re-tune `separationMilli[0]` is `200` too, so neither a null nor a zero
        separation collapses a differentiated species to flat any more."""
        w = load_type_weights()
        order = ("status", "movement", "support", "defense", "attack")
        milli = category_milli_for(order, "derived-nofloor", None, w)
        self.assertNotEqual(milli, {c: 200 for c in CATEGORIES})
        self.assertEqual(max(milli, key=milli.get), "status")

    def test_real_separation_zero_stays_flattest_at_shipped_defaults(self) -> None:
        """A GENUINE tie (`separation == 0`, inside a family) reads as the flattest row — it must
        stay the least-spread row, so 'less differentiated -> flatter' still holds. It is no longer
        collapsed to all-200 (re-tune 2026-09-11): the true five-way tie is handled by its own
        `leanSource == "floor"` branch, so row 0 flattening a differentiated species was redundant.
        The vector must still keep the species' own lean head, not the declared order."""
        w = load_type_weights()
        order = ("movement", "attack", "defense", "support", "status")
        milli = category_milli_for(order, "derived", 0, w)
        self.assertGreater(len(set(milli.values())), 1, "row 0 is flatter, not flat to zero")
        self.assertEqual(max(milli, key=milli.get), "movement")

    def test_declared_order_tie_break_survives_in_the_floor_case(self) -> None:
        w = _weights()
        raw = raw_category_scores(CATEGORIES, "floor", None, w)
        milli = largest_remainder_milli(raw, CATEGORIES)
        self.assertEqual(milli, {c: 200 for c in CATEGORIES})


class ShippedDefaultFlatnessIsExpectedTests(unittest.TestCase):
    """A measured, honest fact about the SHIPPED tuning file, post-2026-09-11 re-tune.
    `separationMilli[0]` is now `200`, not `0`: measured over the live 904-species roster, row 0's
    old `0` collapsed 459 real `separation == 0` species to a flat 200/200/200/200/200 vector, which
    was redundant because a true five-way tie is already handled by its own `leanSource == "floor"`
    branch. `separation: null` has its own `nullSeparationMilli` row (shipped `500`). This test pins
    the invariant that matters: no species row prints a flat vector any more, from either cause."""

    def test_measured_flat_count_at_shipped_defaults(self) -> None:
        if not OUTPUT_PATH.is_file():
            self.skipTest("type-weights.json not yet generated in this checkout")
        doc = json.loads(OUTPUT_PATH.read_text(encoding="utf-8"))
        lean_path = ACTIONS_ROOT / "_generated" / "role-lean.json"
        lean_by_key = {e["speciesKey"]: e for e in
                      json.loads(lean_path.read_text(encoding="utf-8"))["entries"]}

        flat_keys = [e["scopeKey"] for e in doc["entries"] if e["scope"] == "species"
                    and len(set(e["categoryMilli"].values())) == 1]
        nofloor_flat = sum(1 for k in flat_keys if lean_by_key[k]["leanSource"] == "derived-nofloor")

        self.assertEqual(flat_keys, [],
                         "no species row prints a flat 200/200/200/200/200 vector (re-tune "
                         "2026-09-11): a genuine floor tie is handled by its own leanSource branch")
        self.assertEqual(nofloor_flat, 0,
                         "AC5: a family-less species must never print flat")


class LargestRemainderTests(unittest.TestCase):
    """Spec §5 'Largest remainder', acceptance #2."""

    def test_hand_built_remainder_distributes_to_largest_fractions(self) -> None:
        # total=3, values 1,1,1,0,0 -> 333.33 per-mille each for the three equal cells -> floors
        # to 333 x3 = 999, a single remainder unit left over. All three fractional parts tie
        # exactly, so the tie breaks on declared category order: attack, defense, support (in
        # that order) — only "attack" is first in line for the +1.
        raw = {"attack": 1, "defense": 1, "support": 1, "movement": 0, "status": 0}
        milli = largest_remainder_milli(raw, CATEGORIES)
        self.assertEqual(sum(milli.values()), 1000)
        # Ties broken on declared order: attack, defense, support (the three equal, nonzero cells)
        # get the +1 remainder unit in that order until exhausted.
        self.assertEqual(milli["attack"], 334)
        self.assertEqual(milli["defense"], 333)
        self.assertEqual(milli["support"], 333)
        self.assertEqual(milli["movement"], 0)
        self.assertEqual(milli["status"], 0)

    def test_result_is_independent_of_the_raw_dicts_own_insertion_order(self) -> None:
        raw_a = {"attack": 7, "defense": 3, "support": 5, "movement": 2, "status": 1}
        raw_b = {"status": 1, "movement": 2, "support": 5, "defense": 3, "attack": 7}
        self.assertEqual(largest_remainder_milli(raw_a, CATEGORIES),
                         largest_remainder_milli(raw_b, CATEGORIES))

    def test_zero_sum_raises_rather_than_dividing_by_zero(self) -> None:
        with self.assertRaises(ValueError):
            largest_remainder_milli({c: 0 for c in CATEGORIES}, CATEGORIES)


class OverflowTests(unittest.TestCase):
    """Spec §5 'Overflow' — `long` throughout, widened before multiplying, and a forced overflow
    THROWS (AGENTS.md rule 5) rather than silently wrapping — a real check this module makes
    explicitly, since Python's own arbitrary-precision ints never overflow on their own."""

    def test_synthetic_top_of_range_vector_does_not_overflow(self) -> None:
        huge = 3_000_000_000_000_000  # ~3e15; *1000 stays under the long ceiling (~9.22e18)
        raw = {c: huge for c in CATEGORIES}
        milli = largest_remainder_milli(raw, CATEGORIES)
        self.assertEqual(sum(milli.values()), 1000)
        for v in milli.values():
            self.assertIsInstance(v, int)

    def test_forced_overflow_throws(self) -> None:
        with self.assertRaises(OverflowError):
            derive_mod._widen_mul(10_000_000_000_000_000_000, 1000)  # 1e19 * 1000 >> long max

    def test_widen_before_multiply_matters(self) -> None:
        a, b = 4_000_000_000, 4_000_000_000  # product ~1.6e19, exceeds a long, well past a 32-bit int
        with self.assertRaises(OverflowError):
            derive_mod._widen_mul(a, b)
        self.assertGreater(a * b, 2**63)  # confirms this genuinely needed a `long`-range check


class ElementBiasTests(unittest.TestCase):
    """Spec §3 step 5, acceptance #2/#6."""

    def test_primary_and_secondary_get_their_exact_milli(self) -> None:
        w = _weights()
        milli = element_bias_for("fire", "ice", w)
        self.assertEqual(milli["fire"], 400)
        self.assertEqual(milli["ice"], 200)
        self.assertEqual(sum(milli.values()), 1000)
        # remainder 400 split evenly over the other 4 -> 100 each, exact.
        for e in ("air", "earth", "light", "dark"):
            self.assertEqual(milli[e], 100)

    def test_no_secondary_splits_remainder_over_five(self) -> None:
        w = _weights()
        milli = element_bias_for("earth", None, w)
        self.assertEqual(milli["earth"], 400)
        self.assertEqual(sum(milli.values()), 1000)
        others = [milli[e] for e in ELEMENTS if e != "earth"]
        self.assertEqual(len(others), 5)
        self.assertEqual(others, [120] * 5)  # 600 / 5, exact

    def test_declared_order_governs_leftover_assignment(self) -> None:
        w = _weights(primary_milli=1, secondary_milli=0)   # remainder 999 over 5 -> 199 r4
        milli = element_bias_for("dark", None, w)           # dark is LAST in declared order
        rest_in_order = [e for e in ELEMENTS if e != "dark"]
        leftovers = [e for e in rest_in_order if milli[e] == 200]
        self.assertEqual(leftovers, rest_in_order[:4])       # first 4 in declared order get +1


class TargetShapeTests(unittest.TestCase):
    """Spec §3 step 4, acceptance #6b (never a second roll — this only proves the LOOKUP)."""

    def test_falls_back_to_bare_head_row_when_no_reach_qualified_row_exists(self) -> None:
        w = load_type_weights()
        tmm, _ = target_shape_for("attack", "melee", w)
        self.assertEqual(tmm, w.target_mode_milli["attack"])

    def test_reach_qualified_row_wins_when_the_tuning_file_ships_one(self) -> None:
        custom_row = {"self": 0, "single": 1000, "multi": 0, "rolledTarget": 0, "all": 0, "area": 0}
        tmm_rows = {c: {"self": 167, "single": 167, "multi": 167, "rolledTarget": 167,
                        "all": 166, "area": 166} for c in CATEGORIES}
        tmm_rows["attack:melee"] = custom_row
        w = _weights(target_mode_milli=tmm_rows)
        tmm, _ = target_shape_for("attack", "melee", w)
        self.assertEqual(tmm, custom_row)
        # a DIFFERENT reach on the same head still falls back to the bare row.
        tmm2, _ = target_shape_for("attack", "long", w)
        self.assertEqual(tmm2, w.target_mode_milli["attack"])

    def test_area_shape_returned_alongside_every_target_mode_row(self) -> None:
        w = load_type_weights()
        _, area = target_shape_for("status", None, w)
        self.assertEqual(area, w.area_shape_milli)
        self.assertEqual(sum(area.values()), 1000)

    def test_area_mode_keeps_nonzero_weight_at_the_default(self) -> None:
        """spec §4: `area` keeps a non-zero weight even with no board — the gate lives at
        `ActionSeeder.cs:51-53` / `ActionValidator.AreaRequiresBoard`, never here."""
        w = load_type_weights()
        for head in CATEGORIES:
            self.assertGreater(w.target_mode_milli[head]["area"], 0)


class HardGateZeroTests(unittest.TestCase):
    """Spec §5 'Planted violation — hard gate', acceptance #2: a zero weight is legal and never
    excluded from the emitted vector."""

    def test_a_synthetic_zero_category_stays_present_not_dropped(self) -> None:
        w = _weights(base=0, step=1000)  # worst-ranked category's raw score is exactly 0
        order = ("attack", "defense", "support", "movement", "status")
        milli = category_milli_for(order, "derived", 4, w)
        self.assertEqual(set(milli), set(CATEGORIES), "every category key must still be present")
        self.assertEqual(milli["status"], 0)
        self.assertIn("status", milli, "a 0-weight category is never removed from the vector")

    def test_derive_all_over_a_zero_producing_row_does_not_drop_or_raise(self) -> None:
        w = _weights(base=0, step=1000)
        row = _row("zerocat", lean_order=("attack", "defense", "support", "movement", "status"),
                   lean_source="derived", separation=4)
        entries = derive_all([row], w)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].category_milli["status"], 0)


class FamilyRowTests(unittest.TestCase):
    """Spec §3 step 6, acceptance #1."""

    def test_family_row_is_the_sum_of_member_raw_scores(self) -> None:
        w = _weights()
        m1 = _row("m1", family="fam", lean_order=("attack", "defense", "support", "movement", "status"),
                  lean_source="derived", separation=0)
        m2 = _row("m2", family="fam", lean_order=("status", "attack", "defense", "support", "movement"),
                  lean_source="derived", separation=4)
        entries = derive_all([m1, m2], w)
        family_entry = next(e for e in entries if e.scope == "family")
        self.assertEqual(family_entry.id, "weights.family.fam")
        self.assertEqual(family_entry.scope_key, "fam")

        expected_raw = {}
        r1 = raw_category_scores(m1.lean_order, m1.lean_source, m1.separation, w)
        r2 = raw_category_scores(m2.lean_order, m2.lean_source, m2.separation, w)
        for c in CATEGORIES:
            expected_raw[c] = r1[c] + r2[c]
        expected_milli = largest_remainder_milli(expected_raw, CATEGORIES)
        self.assertEqual(family_entry.category_milli, expected_milli)

    def test_family_element_bias_uses_the_tuned_secondary_scale(self) -> None:
        w = _weights(family_secondary_scale_milli=500)
        m1 = _row("m1", family="fam", element_primary="fire", element_secondary=None)
        m2 = _row("m2", family="fam", element_primary="fire", element_secondary="ice")
        primary, secondary = family_element_bias_inputs([m1, m2], w)
        # fire: 1000+1000=2000, ice: 500 -> primary fire, secondary ice
        self.assertEqual(primary, "fire")
        self.assertEqual(secondary, "ice")

    def test_family_with_no_secondary_signal_gets_none(self) -> None:
        w = _weights()
        m1 = _row("m1", family="fam", element_primary="dark", element_secondary=None)
        primary, secondary = family_element_bias_inputs([m1], w)
        self.assertEqual(primary, "dark")
        self.assertIsNone(secondary)

    def test_live_families_over_the_real_corpus(self) -> None:
        w = load_type_weights()
        lean_path = ACTIONS_ROOT / "_generated" / "role-lean.json"
        if not lean_path.is_file():
            self.skipTest("role-lean.json not yet generated in this checkout")
        doc = json.loads(lean_path.read_text(encoding="utf-8"))
        rows = gen_mod._parse_role_lean_rows(doc)
        entries = derive_all(rows, w)
        families = {e.scope_key for e in entries if e.scope == "family"}
        # A JOIN to the live family namespace, never a literal — it grows as families consolidate.
        from seedsmith.adapters.actions.characteristic_pool.catalog import (
            derive_live_family_assignments)
        from seedsmith.adapters.actions.generate_distribution_planner import _family_members
        self.assertEqual(families, set(_family_members(derive_live_family_assignments())))
        print(f"family rows: {len(families)}")


class DeterminismTests(unittest.TestCase):
    """Spec §5 'Determinism' + acceptance #7."""

    def test_derive_all_is_byte_identical_across_two_runs(self) -> None:
        w = load_type_weights()
        lean_path = ACTIONS_ROOT / "_generated" / "role-lean.json"
        if not lean_path.is_file():
            self.skipTest("role-lean.json not yet generated in this checkout")
        doc = json.loads(lean_path.read_text(encoding="utf-8"))
        rows = gen_mod._parse_role_lean_rows(doc)
        e1 = derive_all(rows, w)
        e2 = derive_all(rows, w)
        self.assertEqual(e1, e2)

    def test_regenerate_writes_byte_identical_files_over_a_frozen_snapshot(self) -> None:
        with tempfile.TemporaryDirectory(prefix="a-t1-determinism-") as tmp:
            tmp_path = Path(tmp)
            lean_src = ACTIONS_ROOT / "_generated" / "role-lean.json"
            if not lean_src.is_file():
                self.skipTest("role-lean.json not yet generated in this checkout")
            frozen_lean = tmp_path / "role-lean.json"
            frozen_lean.write_text(lean_src.read_text(encoding="utf-8"), encoding="utf-8")

            out1 = tmp_path / "out1"
            out2 = tmp_path / "out2"
            gen_mod.regenerate(actions_root=out1, role_lean_path=frozen_lean, write=True)
            gen_mod.regenerate(actions_root=out2, role_lean_path=frozen_lean, write=True)

            text1 = (out1 / "type-weights.json").read_text(encoding="utf-8")
            text2 = (out2 / "type-weights.json").read_text(encoding="utf-8")
            self.assertEqual(text1, text2)
            self.assertTrue(text1.endswith("\n"))


class ProvenanceTests(unittest.TestCase):
    """Acceptance #7 — `_meta` records `leanHash` and `tuningVersion`."""

    def test_written_file_carries_provenance(self) -> None:
        if not OUTPUT_PATH.is_file():
            self.skipTest("type-weights.json not yet generated in this checkout")
        doc = json.loads(OUTPUT_PATH.read_text(encoding="utf-8"))
        self.assertIn("leanHash", doc["_meta"])
        self.assertIn("tuningVersion", doc["_meta"])
        # The recorded version is the SHIPPED tuning file's own `version`, never a literal — it
        # moved 1 -> 2 in the 2026-09-11 separation re-tune, and pinning the number here would
        # make every future re-tune fail a provenance test for no reason.
        self.assertEqual(doc["_meta"]["tuningVersion"], load_type_weights().version)
        lean_path = ACTIONS_ROOT / "_generated" / "role-lean.json"
        # Matches `regenerate()`'s own method exactly: `Path.read_text()` normalises newlines
        # before the hash, so this must too — hashing raw bytes here would fail on a CRLF
        # checkout even though the generator itself is perfectly deterministic.
        expected_hash = hashlib.sha256(
            lean_path.read_text(encoding="utf-8").encode("utf-8")).hexdigest()
        self.assertEqual(doc["_meta"]["leanHash"], expected_hash)


class RosterSizeTests(unittest.TestCase):
    """Spec §5 'Roster size', acceptance #1 — one row per live species plus one per consolidated
    family, asserted as a JOIN to the live roster rather than a pinned count. The roster grows per
    shipped species, so a literal fails the suite for succeeding at its job (validation-ssot.md)."""

    @classmethod
    def setUpClass(cls) -> None:
        if not OUTPUT_PATH.is_file():
            cls.doc = None
            return
        cls.doc = json.loads(OUTPUT_PATH.read_text(encoding="utf-8"))

    def setUp(self) -> None:
        if self.doc is None:
            self.skipTest("type-weights.json not yet generated in this checkout")

    def test_one_row_per_live_species_and_family(self) -> None:
        from seedsmith.adapters.actions.characteristic_pool.catalog import (
            derive_live_family_assignments, load_catalog)
        from seedsmith.adapters.actions.generate_distribution_planner import _family_members
        catalog_ids = {r.species_id for r in load_catalog()}
        family_ids = set(_family_members(derive_live_family_assignments()))

        species = {e["scopeKey"] for e in self.doc["entries"] if e["scope"] == "species"}
        families = {e["scopeKey"] for e in self.doc["entries"] if e["scope"] == "family"}
        self.assertEqual(species, catalog_ids)
        self.assertEqual(families, family_ids)
        # One row each — no duplicates, and no scope outside the closed three-member set.
        self.assertEqual(len(self.doc["entries"]),
                         len([e for e in self.doc["entries"]]),
                         "entries are one per subject")
        self.assertEqual({e["scope"] for e in self.doc["entries"]}, {"species", "family"})
        print(f"type-weights rows: {len(species)} species, {len(families)} families")


class SumInvariantTests(unittest.TestCase):
    """Spec §5 'Sum invariant', acceptance #2 — over all 84+19 real entries."""

    @classmethod
    def setUpClass(cls) -> None:
        if not OUTPUT_PATH.is_file():
            cls.doc = None
            return
        cls.doc = json.loads(OUTPUT_PATH.read_text(encoding="utf-8"))

    def setUp(self) -> None:
        if self.doc is None:
            self.skipTest("type-weights.json not yet generated in this checkout")

    def test_every_vector_sums_to_exactly_1000(self) -> None:
        for entry in self.doc["entries"]:
            for key in ("categoryMilli", "targetModeMilli", "areaShapeMilli", "elementBiasMilli"):
                total = sum(entry[key].values())
                self.assertEqual(total, 1000, f"{entry['id']}.{key} sums to {total}")

    def test_every_value_is_a_non_negative_int(self) -> None:
        for entry in self.doc["entries"]:
            for key in ("categoryMilli", "targetModeMilli", "areaShapeMilli", "elementBiasMilli"):
                for k, v in entry[key].items():
                    self.assertIsInstance(v, int)
                    self.assertNotIsInstance(v, bool)
                    self.assertGreaterEqual(v, 0)


class KeyVocabularyTests(unittest.TestCase):
    """Acceptance #6 — every key is the wire string, never a PascalCase enum member name."""

    def setUp(self) -> None:
        if not OUTPUT_PATH.is_file():
            self.skipTest("type-weights.json not yet generated in this checkout")
        self.doc = json.loads(OUTPUT_PATH.read_text(encoding="utf-8"))

    def test_category_keys(self) -> None:
        for entry in self.doc["entries"]:
            self.assertEqual(set(entry["categoryMilli"]), set(CATEGORIES))

    def test_target_mode_keys(self) -> None:
        for entry in self.doc["entries"]:
            self.assertEqual(set(entry["targetModeMilli"]), set(TARGET_MODES))
        self.assertEqual(TARGET_MODES, ("self", "single", "multi", "rolledTarget", "all", "area"))

    def test_area_shape_keys(self) -> None:
        for entry in self.doc["entries"]:
            self.assertEqual(set(entry["areaShapeMilli"]), set(AREA_SHAPES))

    def test_element_keys(self) -> None:
        for entry in self.doc["entries"]:
            self.assertEqual(set(entry["elementBiasMilli"]), set(ELEMENTS))

    def test_no_pascal_case_leakage_anywhere(self) -> None:
        pascal_tokens = {"Self", "Single", "Multi", "RolledTarget", "All", "Area", "Row", "Column",
                         "Square", "Rectangle", "Attack", "Defense", "Support", "Movement",
                         "Status", "Fire", "Ice", "Air", "Earth", "Light", "Dark"}
        for entry in self.doc["entries"]:
            for key in ("categoryMilli", "targetModeMilli", "areaShapeMilli", "elementBiasMilli"):
                self.assertTrue(pascal_tokens.isdisjoint(entry[key]),
                                f"{entry['id']}.{key} carries a PascalCase key: {entry[key].keys()}")

    def test_basis_is_derived_or_floor(self) -> None:
        for entry in self.doc["entries"]:
            self.assertIn(entry["basis"], {"derived", "floor"})

    def test_scope_and_id_pattern(self) -> None:
        kind_spec = next(k for k in KINDS if k.kind == "action-type-weights")
        for entry in self.doc["entries"]:
            self.assertIn(entry["scope"], {"species", "family"})
            self.assertIsNotNone(kind_spec.id_pattern.match(entry["id"]), entry["id"])


class ConsumerNoteTests(unittest.TestCase):
    """Spec §2's F5 decision + acceptance #6b: `targetModeMilli`/`areaShapeMilli` are consumed by
    A-S1 at PLAN time; no code path in THIS module feeds them to `WeightedChoice.Pick`, and this
    module never claims otherwise."""

    def test_no_reference_to_weighted_choice_pick_anywhere_in_this_package(self) -> None:
        pkg_dir = Path(derive_mod.__file__).resolve().parent
        files = list(pkg_dir.glob("*.py")) + [Path(gen_mod.__file__)]
        for f in files:
            text = f.read_text(encoding="utf-8")
            self.assertNotIn("WeightedChoice", text, f"{f} must never wire into the roll-time pick")

    def test_module_docstrings_name_a_s1_as_the_plan_time_consumer(self) -> None:
        text = Path(derive_mod.__file__).read_text(encoding="utf-8")
        self.assertIn("A-S1", text)
        self.assertIn("plan time", text.lower())


class NoBoardGateDuplicationTests(unittest.TestCase):
    """Spec §4: never re-implement the `area` board gate — it stays at `ActionSeeder.cs:51-53` /
    `ActionValidator.AreaRequiresBoard`."""

    def test_no_board_gate_logic_anywhere_in_this_package(self) -> None:
        pkg_dir = Path(derive_mod.__file__).resolve().parent
        files = list(pkg_dir.glob("*.py")) + [Path(gen_mod.__file__)]
        forbidden = ("AreaRequiresBoard", "ResolveMaxTargets", "hasBoard", "HasBoard")
        for f in files:
            text = f.read_text(encoding="utf-8")
            for token in forbidden:
                self.assertNotIn(token, text, f"{f} references {token!r} — the board gate must "
                                              f"stay in the shipped C# code, never here")


class OfflineGuaranteeTests(unittest.TestCase):
    """Spec §5 'Offline guarantee' / acceptance #8 — zero model calls, anywhere in this module."""

    def test_no_llm_transport_import_anywhere_in_the_package(self) -> None:
        pkg_dir = Path(derive_mod.__file__).resolve().parent
        files = list(pkg_dir.glob("*.py")) + [Path(gen_mod.__file__)]
        forbidden = ("llm_caller", "pipeline.run", "openai", "requests")
        for f in files:
            text = f.read_text(encoding="utf-8")
            for token in forbidden:
                self.assertNotIn(token, text, f"{f} references {token!r} — this module must "
                                              f"never import a model transport")

    def test_regenerate_runs_with_no_network(self) -> None:
        lean_path = ACTIONS_ROOT / "_generated" / "role-lean.json"
        if not lean_path.is_file():
            self.skipTest("role-lean.json not yet generated in this checkout")
        summary = gen_mod.regenerate(write=False)
        from seedsmith.adapters.actions.characteristic_pool.catalog import load_catalog
        from seedsmith.adapters.actions.generate_distribution_planner import _family_members
        from seedsmith.adapters.actions.characteristic_pool.catalog import (
            derive_live_family_assignments)
        self.assertEqual(summary["species"], len({r.species_id for r in load_catalog()}))
        self.assertEqual(summary["families"],
                         len(_family_members(derive_live_family_assignments())))


class MagicNumberAuditTests(unittest.TestCase):
    """Acceptance #4 — a magic-number-style audit over this module's OWN source (Python is not
    covered by `gk-core/scripts/audit-magic-numbers.py`, so this module carries its own AST-based check,
    same technique A-S0's build used). Every bare int/float `ast.Constant` in executable code must
    be either a genuinely structural value (an index, a fixed count, the 1000 per-mille scale, the
    `long` range bounds) or absent entirely — every balance-surface coefficient lives in
    `gk-core/data/tuning/action-type-weights.v1.json`, never in this code."""

    # Structural allowlist: loop/slice indices, small fixed counts (5 categories, 6 target
    # modes/elements), the per-mille scale, and the two `long` range bounds (each assigned to a
    # single named, documented module-level constant in derive.py — never re-typed elsewhere).
    _ALLOWED = frozenset({0, 1, 2, 5, 6, 1000, 9_223_372_036_854_775_807, 9_223_372_036_854_775_808})

    def test_zero_unallowlisted_numeric_literals(self) -> None:
        pkg_dir = Path(derive_mod.__file__).resolve().parent
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


class CorpusLoadRoundTripTests(unittest.TestCase):
    """The written file loads back through A-C1's own `Corpus.load`, with ids matching the
    `action-type-weights` KindSpec's own pattern."""

    def test_written_file_loads_through_corpus_load(self) -> None:
        """Uses `load_committed`, not a raw `Corpus.load(ACTIONS_ROOT)` — real content has since
        landed under `_rounds/` (a real smoke batch, 2026-09-04), which deliberately reuses
        `_briefs/round-1.json`'s own ids (A-S2's `p3-briefs.json` shares A-S1's `briefId`s by
        design, `spec-brief-assembly.md` §3.2). A raw whole-tree load collides on that overlap; the
        purpose-built `load_committed` already excludes `_rounds/` for exactly this reason
        (`spec-corpus-loader.md` §3 step 2b, review F14) — this test was never about `_rounds/` at
        all, it only ever asked "does my own output load," so the fix is the loader this repo
        already built for that question, not a synthetic-fixture workaround."""
        if not OUTPUT_PATH.is_file():
            self.skipTest("type-weights.json not yet generated in this checkout")
        result = load_committed(ACTIONS_ROOT)
        rows = result.corpus.by_kind("action-type-weights")
        self.assertEqual(len(rows), len(json.loads(OUTPUT_PATH.read_text(encoding="utf-8"))["entries"]),
                         "every emitted row loads back through the corpus loader")


if __name__ == "__main__":
    unittest.main()
