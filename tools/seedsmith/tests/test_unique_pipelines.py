"""Tests for seedsmith.adapters.items.uniques.pipelines (D4.29, spec-unique-pipeline.md §1).

    python -m pytest gk-forge/tools/seedsmith/tests/test_unique_pipelines.py -v

Transport is ALWAYS a fake or a raising stub here -- this repo's own rule ("tests never call a
model; stub the transport so it raises"), mirroring `test_general_propose.py`'s `raising_call`.
`raising_call` proves a path that must never reach the network really doesn't; the deterministic
`FakeCall` proves the vote/permutation/assembly logic without any network dependency either.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from seedsmith.adapters.items.uniques.briefs import build_unique_schema, role_for_cell  # noqa: E402
from seedsmith.adapters.items.uniques.pipelines import (  # noqa: E402
    SAMPLES_PER_DRAW,
    UniquesDrawRefused,
    _duplicate_fixed_atom_family,
    _permute_schema_enums,
    _tag_axis_violation,
    run_unique_draws,
)
from seedsmith.adapters.items.uniques.planner import Cell, IdMinter, plan_ids_for_cells  # noqa: E402
from seedsmith.briefkit.avoid_list import load_avoid_terms, render_avoid_line  # noqa: E402

CELL = Cell("plant", "offense", "firstseed", "plant-offense-firstseed")
_CELL_ROLE = role_for_cell(CELL)

FAKE_TAG_AXES = {
    "mass-class": ("light", "medium", "heavy"),
    "material-nature": ("organic", "metal"),
    "combat-posture": ("offensive", "defensive", "utility"),
    "origin": ("rooted", "undead"),
    "durability-class": ("sturdy", "fragile"),
}

FAKE_SCHEMA_KWARGS = dict(
    base_types_by_frame_and_role={("plant", _CELL_ROLE): frozenset({"item.plant-example-a-001"}),
                                  ("humanoid", _CELL_ROLE): frozenset({"item.humanoid-example-a-001"})},
    atom_families=frozenset({"atom.might", "atom.vitality"}),
    tag_axes=FAKE_TAG_AXES,
)


def _planned_ids_for(cell: Cell) -> "dict[str, dict[str, str]]":
    minter = IdMinter()
    ids = plan_ids_for_cells([cell], {cell.cell_key: 1}, minter)[cell.cell_key]
    uid = ids[0]
    return {cell.cell_key: {"id": uid, "nameKey": f"unique.{uid.split('.', 1)[1]}",
                            "iconKey": f"icon.{uid}", "flavorKey": f"flavor.{uid}"}}


def raising_call(*args, **kwargs) -> str:
    raise AssertionError("a real model call was attempted -- this test's transport must never be reached")


def _entry(name: str, base_type: str = "item.plant-example-a-001", family: str = "atom.might") -> dict:
    # The FAKE MODEL's own raw output shape: five single-value tag axis fields, matching
    # build_unique_schema's real properties -- run_unique_draws calls assemble_tags() on the
    # WINNING sample to turn these into the real tags[] array, exactly like a live call would.
    return {
        "id": "unique.plant-offense-firstseed-001", "nameKey": "unique.example",
        "iconKey": "icon.unique.example", "flavorKey": "flavor.unique.example",
        "frame": "plant", "powerAxis": "offense", "rarity": "firstseed", "acquisition": "drop",
        "name": name, "flavor": "A thing that does a thing.",
        "baseType": base_type,
        "fixedAtoms": [{"family": family, "powerBand": "medium"}],
        "counterPressure": {"kind": "narrow", "note": "It has a weakness."},
        "massClass": "light", "materialNature": "organic", "combatPosture": "offensive",
        "origin": "none", "durabilityClass": "none",
    }


class FakeCall:
    """A deterministic stand-in for `llm_caller.call_model` -- returns `json.dumps(entry)` for
    each of the three permuted calls in a draw, in the order this test controls, never touching a
    socket. `calls` records every (system, user) pair so a test can assert exactly how many times
    (and never more than expected) this was reached."""

    def __init__(self, responses: "list[dict]") -> None:
        import collections
        self._responses = collections.deque(responses)
        self.calls: "list[tuple[str, str]]" = []

    def __call__(self, system: str, user: str, *, config=None, schema=None) -> str:
        import json
        self.calls.append((system, user))
        if not self._responses:
            raise AssertionError("FakeCall exhausted -- more calls made than responses supplied")
        return json.dumps(self._responses.popleft())


#: A wide fixture for the permutation tests below -- `FAKE_SCHEMA_KWARGS`'s own 1-2-element enums
#: make a coincidental identity/duplicate shuffle likely (a real, self-caught blind spot: the
#: original version of these tests used the narrow fixture and passed even while
#: `_permute_schema_enums` had a real mutate-the-input bug, precisely because a 1-element enum has
#: only one possible "order" either way). 8 elements makes a coincidental repeat astronomically
#: unlikely without making any single assertion probabilistic in a way that could flake.
_WIDE_KWARGS = dict(FAKE_SCHEMA_KWARGS, atom_families=frozenset(f"atom.f{i}" for i in range(8)))


class AvoidListWiringTests(unittest.TestCase):
    """ip-censor T15/IC-3 on the uniques DRAW caller: the shared avoid line reaches the brief the
    model is actually handed, and an unreadable registry refuses the draw instead of silently
    sending briefs with no avoid line at all."""

    def _draw(self, call) -> "list":
        return run_unique_draws(
            [CELL], _planned_ids_for(CELL), call=call, schema_kwargs=FAKE_SCHEMA_KWARGS,
            tag_axes=FAKE_TAG_AXES)

    def test_every_drawn_brief_carries_the_shared_avoid_line(self) -> None:
        call = FakeCall([_entry("Heartbloom Crown") for _ in range(SAMPLES_PER_DRAW)])
        results = self._draw(call)
        self.assertEqual(1, len(results))
        self.assertIsNotNone(results[0].entry, results[0].reason)
        self.assertEqual(SAMPLES_PER_DRAW, len(call.calls))
        expected = render_avoid_line(load_avoid_terms())
        for system, user in call.calls:
            self.assertIn(expected, user)
            # The avoid line is a brief instruction, not a schema change: it must not leak into the
            # system turn, or it would start constraining the model's identity prose too.
            self.assertNotIn(expected, system)

    def test_an_unreadable_avoid_registry_refuses_the_draw_instead_of_rendering_nothing(self) -> None:
        """The fail-closed direction, proven at the caller. An empty list is the failure this
        program exists to prevent: the brief would carry no avoid line and read as "nothing to
        avoid" while every test stayed green. Refused BEFORE any cell is drawn, so there is nothing
        to clean up and no partial `DrawResult` to mistake for a content outcome."""
        call = FakeCall([_entry("Heartbloom Crown") for _ in range(SAMPLES_PER_DRAW)])
        with patch("seedsmith.briefkit.avoid_list.load_avoid_terms",
                   side_effect=ValueError("registry is missing 'groups' — refusing to guess")):
            with self.assertRaisesRegex(UniquesDrawRefused, "avoid"):
                self._draw(call)
        self.assertEqual([], call.calls, "a refused draw must not have called the model at all")


class PermuteSchemaEnumsTests(unittest.TestCase):
    def test_never_mutates_its_own_input_schema(self) -> None:
        # Self-caught 2026-09-06: the first version of this function walked `schema` (the
        # caller's own object) while returning a SEPARATE deepcopy taken before that walk ran --
        # every call silently corrupted the caller's schema as a side effect. Proven here by a
        # before/after snapshot rather than trusted from the function's own docstring claim.
        import copy as copy_mod
        schema = build_unique_schema(CELL, _planned_ids_for(CELL)[CELL.cell_key], **_WIDE_KWARGS)
        before = copy_mod.deepcopy(schema)
        _permute_schema_enums(schema, draw_id="unique-draw-x", sample_index=0)
        self.assertEqual(schema, before, "the input schema must be unchanged after the call")

    def test_permutation_is_deterministic_across_reruns_of_the_same_unmutated_schema(self) -> None:
        schema = build_unique_schema(CELL, _planned_ids_for(CELL)[CELL.cell_key], **_WIDE_KWARGS)
        p1 = _permute_schema_enums(schema, draw_id="unique-draw-x", sample_index=0)
        p2 = _permute_schema_enums(schema, draw_id="unique-draw-x", sample_index=0)
        self.assertEqual(p1["properties"]["fixedAtoms"]["items"]["properties"]["family"]["enum"],
                         p2["properties"]["fixedAtoms"]["items"]["properties"]["family"]["enum"])

    def test_different_sample_indices_produce_different_orders_from_the_same_base_schema(self) -> None:
        schema = build_unique_schema(CELL, _planned_ids_for(CELL)[CELL.cell_key], **_WIDE_KWARGS)
        orders = [
            tuple(_permute_schema_enums(schema, draw_id="unique-draw-x", sample_index=i)
                  ["properties"]["fixedAtoms"]["items"]["properties"]["family"]["enum"])
            for i in range(SAMPLES_PER_DRAW)
        ]
        self.assertEqual(len(set(orders)), SAMPLES_PER_DRAW, "all three sample indices should diverge")
        for order in orders:
            self.assertEqual(set(order), {f"atom.f{i}" for i in range(8)})

    def test_planned_const_fields_are_never_touched_by_permutation(self) -> None:
        schema = build_unique_schema(CELL, _planned_ids_for(CELL)[CELL.cell_key], **FAKE_SCHEMA_KWARGS)
        permuted = _permute_schema_enums(schema, draw_id="unique-draw-x", sample_index=0)
        self.assertEqual(permuted["properties"]["frame"]["const"], "plant")
        self.assertNotIn("enum", permuted["properties"]["frame"])


class RunUniqueDrawsVoteTests(unittest.TestCase):
    def test_three_zero_agreement_resolves_high_confidence(self) -> None:
        fake = FakeCall([_entry("Windborne Bellows")] * SAMPLES_PER_DRAW)
        planned = _planned_ids_for(CELL)
        results = run_unique_draws([CELL], planned, call=fake, schema_kwargs=FAKE_SCHEMA_KWARGS)
        self.assertEqual(len(results), 1)
        self.assertIsNotNone(results[0].entry)
        self.assertEqual(results[0].entry["name"], "Windborne Bellows")
        self.assertEqual(results[0].vote_confidence, "high")
        self.assertEqual(len(fake.calls), SAMPLES_PER_DRAW)

    def test_two_one_split_resolves_to_the_majority_name(self) -> None:
        fake = FakeCall([_entry("Windborne Bellows"), _entry("Windborne Bellows"), _entry("Driftpod")])
        planned = _planned_ids_for(CELL)
        results = run_unique_draws([CELL], planned, call=fake, schema_kwargs=FAKE_SCHEMA_KWARGS)
        self.assertEqual(results[0].entry["name"], "Windborne Bellows")
        self.assertEqual(results[0].vote_confidence, "split")

    def test_one_one_one_split_is_unresolved_never_a_guess(self) -> None:
        fake = FakeCall([_entry("Windborne Bellows"), _entry("Driftpod"), _entry("Loftgland")])
        planned = _planned_ids_for(CELL)
        results = run_unique_draws([CELL], planned, call=fake, schema_kwargs=FAKE_SCHEMA_KWARGS)
        self.assertIsNone(results[0].entry)
        self.assertEqual(results[0].reason, "vote_unresolved")

    def test_a_sample_that_never_parses_makes_the_draw_insufficient(self) -> None:
        class BadJsonThenRaisingCall:
            def __init__(self) -> None:
                self.n = 0

            def __call__(self, system, user, *, config=None, schema=None) -> str:
                self.n += 1
                return "not json at all, and never will be"  # exhausts MAX_PARSE_HEAL, then raises

        results = run_unique_draws([CELL], _planned_ids_for(CELL), call=BadJsonThenRaisingCall(),
                                   schema_kwargs=FAKE_SCHEMA_KWARGS)
        self.assertIsNone(results[0].entry)
        self.assertEqual(results[0].reason, "insufficient_valid_samples")

    def test_the_winning_samples_own_fields_stay_together_not_recombined(self) -> None:
        # Two samples agree on name but differ in baseType/family -- the assembled entry must
        # come entirely from ONE of the two agreeing samples, never a mix of both.
        a = _entry("Windborne Bellows", base_type="item.plant-example-a-001", family="atom.might")
        b = _entry("Windborne Bellows", base_type="item.plant-example-a-001", family="atom.might")
        c = _entry("Driftpod", base_type="item.plant-example-a-001", family="atom.vitality")
        fake = FakeCall([a, b, c])
        results = run_unique_draws([CELL], _planned_ids_for(CELL), call=fake, schema_kwargs=FAKE_SCHEMA_KWARGS)
        entry = results[0].entry
        self.assertEqual(entry["fixedAtoms"][0]["family"], "atom.might")


CELL2 = Cell("plant", "control", "almanac", "plant-control-almanac")


class NameCollisionTests(unittest.TestCase):
    def test_a_name_matching_an_existing_name_is_a_collision(self) -> None:
        # Real finding 2026-09-06: with nothing differentiating a firstseed vs. almanac brief
        # beyond the rarity const, the model wrote the IDENTICAL name for both bands four times
        # in the first real 20-cell batch -- ItemSeedValidator's own NameCollision check caught it.
        fake = FakeCall([_entry("Gilded Tread")] * SAMPLES_PER_DRAW)
        results = run_unique_draws([CELL], _planned_ids_for(CELL), call=fake,
                                   schema_kwargs=FAKE_SCHEMA_KWARGS, existing_names=["Gilded Tread"])
        self.assertIsNone(results[0].entry)
        self.assertTrue(results[0].reason.startswith("name_collision"))

    def test_two_cells_in_the_same_call_cannot_collide_with_each_other(self) -> None:
        planned = {**_planned_ids_for(CELL), **_planned_ids_for(CELL2)}
        schema_kwargs = dict(FAKE_SCHEMA_KWARGS,
                             base_types_by_frame_and_role={
                                 **FAKE_SCHEMA_KWARGS["base_types_by_frame_and_role"],
                                 ("plant", role_for_cell(CELL2)): frozenset({"item.plant-example-b-001"}),
                             })
        fake = FakeCall([_entry("Gilded Tread")] * (SAMPLES_PER_DRAW * 2))
        results = run_unique_draws([CELL, CELL2], planned, call=fake, schema_kwargs=schema_kwargs)
        resolved = [r for r in results if r.entry is not None]
        collided = [r for r in results if r.entry is None]
        self.assertEqual(len(resolved), 1, "exactly one of the two identically-named cells should ship")
        self.assertEqual(len(collided), 1)
        self.assertTrue(collided[0].reason.startswith("name_collision"))

    def test_a_name_normalizing_the_same_way_is_still_a_collision(self) -> None:
        # canonical_words is case/punctuation-insensitive -- "gilded tread!" and "Gilded Tread"
        # normalize to the identical {gilded, tread} set.
        fake = FakeCall([_entry("gilded tread!")] * SAMPLES_PER_DRAW)
        results = run_unique_draws([CELL], _planned_ids_for(CELL), call=fake,
                                   schema_kwargs=FAKE_SCHEMA_KWARGS, existing_names=["Gilded Tread"])
        self.assertIsNone(results[0].entry)

    def test_a_genuinely_different_name_is_not_a_collision(self) -> None:
        fake = FakeCall([_entry("Windborne Bellows")] * SAMPLES_PER_DRAW)
        results = run_unique_draws([CELL], _planned_ids_for(CELL), call=fake,
                                   schema_kwargs=FAKE_SCHEMA_KWARGS, existing_names=["Gilded Tread"])
        self.assertIsNotNone(results[0].entry)


#: A DIFFERENT axis shape than the module-level `FAKE_TAG_AXES` (line 31) -- this one carries the
#: notability/economy-source axes `TagAxisViolationTests`' own cases below actually exercise.
#: Deliberately its own name (not a second `FAKE_TAG_AXES=` reassignment, which would silently
#: shadow the earlier binding for every line below it -- a real, confusing footgun this file had
#: until 2026-09-06, fixed while already editing this file for the name-collision addition above).
TAG_AXIS_VIOLATION_FIXTURE = {
    "mass-class": ("light", "medium", "heavy"),
    "material-nature": ("organic", "metal"),
    "notability": ("signature",),
    "economy-source": ("crafted-only", "vendor-stocked"),
}


class DuplicateFixedAtomFamilyTests(unittest.TestCase):
    def test_two_distinct_families_has_no_violation(self) -> None:
        self.assertIsNone(_duplicate_fixed_atom_family(
            [{"family": "atom.might", "powerBand": "low"}, {"family": "atom.vitality", "powerBand": "high"}]))

    def test_the_same_family_at_the_same_power_band_is_a_violation(self) -> None:
        # Real live finding 2026-09-06: `uniqueItems: true` on the schema did NOT stop this exact
        # shape from coming back -- grammar-based constrained decoding enforces per-field shape,
        # not whole-object equality, so the post-hoc check is the only real backstop.
        reason = _duplicate_fixed_atom_family(
            [{"family": "atom.vitality", "powerBand": "high"}, {"family": "atom.vitality", "powerBand": "high"}])
        self.assertIsNotNone(reason)
        self.assertIn("atom.vitality", reason)

    def test_the_same_family_at_DIFFERENT_power_bands_is_still_a_violation(self) -> None:
        # A real generated entry did exactly this (vitality-low + vitality-high) -- schema-legal
        # (uniqueItems only forbids IDENTICAL objects) but content-wrong: no sampled real anchor
        # in the 144-corpus ever repeats a family, at any power band.
        reason = _duplicate_fixed_atom_family(
            [{"family": "atom.vitality", "powerBand": "low"}, {"family": "atom.vitality", "powerBand": "high"}])
        self.assertIsNotNone(reason)

    def test_a_single_fixed_atom_has_no_violation(self) -> None:
        self.assertIsNone(_duplicate_fixed_atom_family([{"family": "atom.might", "powerBand": "low"}]))

    def test_three_distinct_families_has_no_violation(self) -> None:
        self.assertIsNone(_duplicate_fixed_atom_family([
            {"family": "atom.might", "powerBand": "low"},
            {"family": "atom.vitality", "powerBand": "medium"},
            {"family": "atom.fortitude", "powerBand": "high"},
        ]))


class RunUniqueDrawsDuplicateFixedAtomTests(unittest.TestCase):
    def test_a_winning_entry_with_a_repeated_family_is_unresolved_not_shipped(self) -> None:
        bad = _entry("Windborne Bellows")
        bad["fixedAtoms"] = [{"family": "atom.might", "powerBand": "low"}, {"family": "atom.might", "powerBand": "high"}]
        fake = FakeCall([bad] * SAMPLES_PER_DRAW)
        results = run_unique_draws([CELL], _planned_ids_for(CELL), call=fake, schema_kwargs=FAKE_SCHEMA_KWARGS)
        self.assertIsNone(results[0].entry)
        self.assertTrue(results[0].reason.startswith("duplicate_fixed_atom"))


class TagAxisViolationTests(unittest.TestCase):
    def test_a_clean_tag_set_has_no_violation(self) -> None:
        self.assertIsNone(_tag_axis_violation(["light", "organic", "signature"], TAG_AXIS_VIOLATION_FIXTURE))

    def test_two_mass_class_tags_is_a_violation(self) -> None:
        reason = _tag_axis_violation(["light", "heavy", "organic"], TAG_AXIS_VIOLATION_FIXTURE)
        self.assertIsNotNone(reason)
        self.assertIn("mass-class", reason)

    def test_zero_mass_class_tags_is_a_violation(self) -> None:
        reason = _tag_axis_violation(["organic", "signature"], TAG_AXIS_VIOLATION_FIXTURE)
        self.assertIsNotNone(reason)
        self.assertIn("mass-class", reason)

    def test_two_tags_from_a_non_exclusive_axis_is_not_a_violation(self) -> None:
        self.assertIsNone(_tag_axis_violation(
            ["light", "organic", "crafted-only", "vendor-stocked"], TAG_AXIS_VIOLATION_FIXTURE))

    def test_two_different_exclusive_axes_each_with_one_tag_is_not_a_violation(self) -> None:
        self.assertIsNone(_tag_axis_violation(["light", "organic"], TAG_AXIS_VIOLATION_FIXTURE))


class RunUniqueDrawsTagAssemblyTests(unittest.TestCase):
    def test_a_well_formed_response_assembles_a_clean_tags_array_end_to_end(self) -> None:
        # The old version of this test forced a violation by hand-writing a bad flat tags[]
        # array -- structurally impossible now that the model answers five single-value fields
        # instead (build_unique_schema's own 2026-09-06 redesign, after a real batch measured a
        # 15% resolve rate against the old flat-array shape). This proves the replacement: a
        # normal five-field response survives vote + assemble_tags + the defensive check intact.
        fake = FakeCall([_entry("Windborne Bellows")] * SAMPLES_PER_DRAW)
        results = run_unique_draws([CELL], _planned_ids_for(CELL), call=fake, schema_kwargs=FAKE_SCHEMA_KWARGS)
        self.assertIsNotNone(results[0].entry)
        self.assertEqual(results[0].entry["tags"], ["light", "organic", "offensive", "signature"])
        for field in ("massClass", "materialNature", "combatPosture", "origin", "durabilityClass"):
            self.assertNotIn(field, results[0].entry)

    def test_the_defensive_check_still_fires_if_assembly_ever_produced_a_bad_array(self) -> None:
        # assemble_tags() itself cannot produce a violation from valid single-enum inputs (proven
        # in test_unique_briefs.py), so this exercises run_unique_draws's OWN defensive call to
        # _tag_axis_violation directly, standing in for "assembly had a bug" without needing one.
        entry = {"tags": ["light", "heavy", "organic"]}
        self.assertIsNotNone(_tag_axis_violation(entry["tags"], FAKE_TAG_AXES))


class RetryAttemptTests(unittest.TestCase):
    def test_a_different_attempt_number_permutes_a_different_enum_order(self) -> None:
        # A retried draw (batch-level policy, e.g. after an unresolved vote) must not silently
        # reproduce the identical three samples -- `attempt` has to actually reach the permutation
        # seed, proven here by capturing the real schema each call receives and confirming the
        # family enum's order differs between attempt=0's first sample and attempt=1's first sample.
        # The shared wide fixture (8 families, not FAKE_SCHEMA_KWARGS's 2-element one) keeps a
        # coincidental same-order shuffle astronomically unlikely rather than merely improbable.
        seen_schemas: "list[dict]" = []

        class RecordingCall:
            def __call__(self, system, user, *, config=None, schema=None) -> str:
                import json
                seen_schemas.append(schema)
                return json.dumps(_entry("Windborne Bellows", family="atom.f0"))

        run_unique_draws([CELL], _planned_ids_for(CELL), call=RecordingCall(),
                         schema_kwargs=_WIDE_KWARGS, attempt=0)
        attempt_0_first_order = seen_schemas[0]["properties"]["fixedAtoms"]["items"]["properties"]["family"]["enum"]
        seen_schemas.clear()
        run_unique_draws([CELL], _planned_ids_for(CELL), call=RecordingCall(),
                         schema_kwargs=_WIDE_KWARGS, attempt=1)
        attempt_1_first_order = seen_schemas[0]["properties"]["fixedAtoms"]["items"]["properties"]["family"]["enum"]
        self.assertNotEqual(attempt_0_first_order, attempt_1_first_order)


class NeverCallsTheRealTransportTests(unittest.TestCase):
    def test_an_empty_cell_list_makes_zero_calls(self) -> None:
        # `raising_call` proves this by construction: if `run_unique_draws` ever reached it, the
        # test would fail with the stub's own AssertionError instead of passing quietly.
        results = run_unique_draws([], {}, call=raising_call, schema_kwargs=FAKE_SCHEMA_KWARGS)
        self.assertEqual(results, [])

    def test_missing_planned_ids_for_a_cell_raises_before_any_call(self) -> None:
        with self.assertRaises(KeyError):
            run_unique_draws([CELL], {}, call=raising_call, schema_kwargs=FAKE_SCHEMA_KWARGS)


if __name__ == "__main__":
    unittest.main()
