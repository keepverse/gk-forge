"""Tests for seedsmith.adapters.actions.dedup_select (A-S3, spec-dedup-select.md).

    python -m pytest gk-forge/tools/seedsmith/tests/test_dedup_select.py -v

Spec §5's ten named cases plus §6's acceptance criteria (1, 1b, 2-9, 7b). Same fixture discipline
every prior module in this session established: A-S4's real candidate set does not exist yet (it
is a later, unbuilt module -- map's own build-order note lists A-S3 as buildable before A-S5
despite the data-flow dependency), so every test below runs against synthetic, in-memory
candidate-set fixtures, never a real round-1 tree. The one genuinely real thing this module
creates -- `gk-core/data/tuning/action-dedup.v1.json` -- is read directly against the live file where that
is the point of the test (`DedupTuningLoadTests`).
"""
from __future__ import annotations

import ast
import json
import random
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from seedsmith.adapters.actions.dedup_select import derive as ds  # noqa: E402
from seedsmith.adapters.actions.dedup_select import similarity as sim  # noqa: E402
from seedsmith.adapters.actions.dedup_select.tuning import (  # noqa: E402
    DEDUP_TUNING_PATH, IMPLEMENTED_T2_FIELD_DISTANCE, load_dedup_tuning,
)
from seedsmith.adapters.actions import generate_dedup_select as gen_mod  # noqa: E402
from seedsmith.adapters.actions.kinds import KINDS  # noqa: E402
from seedsmith.adapters.actions.load import load_committed  # noqa: E402
from seedsmith.adapters.actions.vocab import load_family_ids  # noqa: E402
from seedsmith.corpus import Corpus  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[3]
FAMILY_IDS = load_family_ids()                                   # the 98, read fresh (live tree)
FAM_A, FAM_B = sorted(FAMILY_IDS)[:2]
FIXTURE_ATOM_ID = "atom.fx-passive-atk-flat"                      # data/seed/atoms/fx-core.json (17)


# ---------------------------------------------------------------------------------------------
# Synthetic candidate fixture -- an action-seed row, the shape A-S4's (unbuilt) accepted output
# is spec'd to carry (spec §2's Reads row: "A-S4's accepted output, in the A-C1 action-seed
# envelope").
# ---------------------------------------------------------------------------------------------

def _candidate(id_, scope, scope_key, *, category="attack", target_mode="single", area_shape=None,
              relation="enemy", atom_families=(FAM_A,), structure_axes=(), pairing_role="none",
              name="Strike", rationale="deals damage", brief_id=None, area_key_present=True):
    row = {
        "id": id_, "scope": scope, "scopeKey": scope_key, "category": category,
        "rungBand": [1, 4], "targetMode": target_mode, "relation": relation,
        "atomFamilies": list(atom_families), "pairingRole": pairing_role,
        "structureAxes": list(structure_axes), "name": name, "rationale": rationale,
    }
    if area_key_present:
        row["areaShape"] = area_shape
    if brief_id is not None:
        row["briefId"] = brief_id
    return row


class CandidateParseTests(unittest.TestCase):
    """Spec §5 'areaShape absence' and 'Casing'."""

    def test_valid_candidate_parses(self) -> None:
        c = ds.parse_candidate(_candidate("action.species.x.001", "species", "x"), FAMILY_IDS)
        self.assertEqual(c.id, "action.species.x.001")
        self.assertEqual(c.fp.area_shape, None)

    def test_area_shape_absent_key_refused(self) -> None:
        row = _candidate("action.species.x.001", "species", "x", area_key_present=False)
        self.assertNotIn("areaShape", row)
        with self.assertRaises(ValueError) as ctx:
            ds.parse_candidate(row, FAMILY_IDS)
        self.assertIn("areaShape", str(ctx.exception))

    def test_area_mode_requires_a_real_shape(self) -> None:
        row = _candidate("action.species.x.001", "species", "x", target_mode="area", area_shape=None)
        with self.assertRaises(ValueError) as ctx:
            ds.parse_candidate(row, FAMILY_IDS)
        self.assertIn("area", str(ctx.exception))

    def test_non_area_mode_with_a_real_shape_refused(self) -> None:
        row = _candidate("action.species.x.001", "species", "x", target_mode="single", area_shape="row")
        with self.assertRaises(ValueError) as ctx:
            ds.parse_candidate(row, FAMILY_IDS)
        self.assertIn("null", str(ctx.exception))

    def test_area_mode_with_real_shape_renders_the_shape(self) -> None:
        row = _candidate("action.species.x.001", "species", "x", target_mode="area", area_shape="row")
        c = ds.parse_candidate(row, FAMILY_IDS)
        fp = ds.render_fingerprint(c.fp)
        self.assertEqual(fp[3], "row")

    def test_non_area_mode_renders_literal_none(self) -> None:
        c = ds.parse_candidate(_candidate("action.species.x.001", "species", "x"), FAMILY_IDS)
        fp = ds.render_fingerprint(c.fp)
        self.assertEqual(fp[3], "none")

    def test_planted_pascal_case_category_refused_before_hashing(self) -> None:
        row = _candidate("action.species.x.001", "species", "x", category="Attack")
        with self.assertRaises(ValueError) as ctx:
            ds.parse_candidate(row, FAMILY_IDS)
        self.assertIn("category", str(ctx.exception))

    def test_planted_pascal_case_target_mode_refused(self) -> None:
        row = _candidate("action.species.x.001", "species", "x", target_mode="Area", area_shape="Row")
        with self.assertRaises(ValueError) as ctx:
            ds.parse_candidate(row, FAMILY_IDS)
        self.assertIn("targetMode", str(ctx.exception))

    def test_planted_pascal_case_relation_refused(self) -> None:
        row = _candidate("action.species.x.001", "species", "x", relation="Enemy")
        with self.assertRaises(ValueError) as ctx:
            ds.parse_candidate(row, FAMILY_IDS)
        self.assertIn("relation", str(ctx.exception))

    def test_fixture_atom_family_outside_the_98_refused(self) -> None:
        row = _candidate("action.species.x.001", "species", "x", atom_families=(FIXTURE_ATOM_ID,))
        with self.assertRaises(ValueError) as ctx:
            ds.parse_candidate(row, FAMILY_IDS)
        self.assertIn(FIXTURE_ATOM_ID, str(ctx.exception))

    def test_ordering_key_falls_back_when_brief_id_absent(self) -> None:
        c = ds.parse_candidate(_candidate("action.species.x.001", "species", "x"), FAMILY_IDS)
        self.assertEqual(c.brief_id, "")


class TotalOrderingTests(unittest.TestCase):
    """Spec §3 step 1 -- scopeRank, then scopeKey, briefId, candidateId, byte-wise."""

    def test_scope_rank_orders_general_family_species(self) -> None:
        self.assertEqual(ds.SCOPE_RANK, {"general": 0, "family": 1, "species": 2})

    def test_order_is_total_and_shuffle_invariant(self) -> None:
        rows = [
            _candidate("action.species.b.001", "species", "b"),
            _candidate("action.general.0001", "general", None),
            _candidate("action.family.f.001", "family", "f"),
            _candidate("action.species.a.001", "species", "a"),
        ]
        candidates = [ds.parse_candidate(r, FAMILY_IDS) for r in rows]
        ordered = ds.order_candidates(candidates)
        self.assertEqual([c.id for c in ordered], [
            "action.general.0001", "action.family.f.001",
            "action.species.a.001", "action.species.b.001",
        ])
        shuffled = list(candidates)
        random.Random(11).shuffle(shuffled)
        self.assertEqual(ds.order_candidates(shuffled), ordered)


class Tier1Tests(unittest.TestCase):
    """Spec §5 'Planted violation -- t1': identical fingerprints, one survivor, fixed-order win."""

    def test_two_identical_fingerprints_one_survives_first_in_order_wins(self) -> None:
        c1 = _candidate("action.species.foo.001", "species", "foo")
        c2 = _candidate("action.species.foo.002", "species", "foo")   # identical fingerprint
        result = ds.select_round(candidate_rows=[c2, c1], accepted_rows=[], round_no=1,
                                 similarity_threshold_milli=700, family_ids=FAMILY_IDS)
        self.assertEqual([e["id"] for e in result.survivor_entries], ["action.species.foo.001"])
        self.assertEqual(len(result.reject_entries), 1)
        rej = result.reject_entries[0]
        self.assertEqual(rej["candidateId"], "action.species.foo.002")
        self.assertEqual(rej["tier"], 1)
        self.assertEqual(rej["reason"], "identical fingerprint")
        self.assertEqual(rej["collidedWith"], "action.species.foo.001")

    def test_exact_match_against_the_already_accepted_corpus_is_rejected(self) -> None:
        accepted = _candidate("action.species.foo.001", "species", "foo")
        candidate = _candidate("action.species.foo.002", "species", "foo")   # identical fp
        result = ds.select_round(candidate_rows=[candidate], accepted_rows=[accepted], round_no=1,
                                 similarity_threshold_milli=700, family_ids=FAMILY_IDS)
        self.assertEqual(result.survivor_entries, [])
        self.assertEqual(result.reject_entries[0]["collidedWith"], "action.species.foo.001")

    def test_ordering_change_never_changes_which_row_wins(self) -> None:
        # First-in-FIXED-ORDER wins, not first-in-input-order: swapping input order must not
        # change the survivor.
        c1 = _candidate("action.species.foo.001", "species", "foo")
        c2 = _candidate("action.species.foo.002", "species", "foo")
        for rows in ([c1, c2], [c2, c1]):
            result = ds.select_round(candidate_rows=rows, accepted_rows=[], round_no=1,
                                     similarity_threshold_milli=700, family_ids=FAMILY_IDS)
            self.assertEqual([e["id"] for e in result.survivor_entries], ["action.species.foo.001"])


class Tier2Tests(unittest.TestCase):
    """Spec §5 'Planted violation -- t2 within an anchor' / 't2 across anchors'."""

    def test_one_field_apart_within_the_same_anchor_rejects_the_later_one(self) -> None:
        c1 = _candidate("action.species.bar.001", "species", "bar", category="attack")
        c2 = _candidate("action.species.bar.002", "species", "bar", category="defense")
        result = ds.select_round(candidate_rows=[c1, c2], accepted_rows=[], round_no=1,
                                 similarity_threshold_milli=700, family_ids=FAMILY_IDS)
        self.assertEqual([e["id"] for e in result.survivor_entries], ["action.species.bar.001"])
        rej = result.reject_entries[0]
        self.assertEqual(rej["candidateId"], "action.species.bar.002")
        self.assertEqual(rej["tier"], 2)
        self.assertEqual(rej["collidedWith"], "action.species.bar.001")

    def test_one_field_apart_across_DIFFERENT_anchors_both_survive(self) -> None:
        c1 = _candidate("action.species.baz.001", "species", "baz", category="attack")
        c2 = _candidate("action.species.qux.001", "species", "qux", category="defense")
        result = ds.select_round(candidate_rows=[c1, c2], accepted_rows=[], round_no=1,
                                 similarity_threshold_milli=700, family_ids=FAMILY_IDS)
        self.assertEqual({e["id"] for e in result.survivor_entries},
                         {"action.species.baz.001", "action.species.qux.001"})
        self.assertEqual(result.reject_entries, [])

    def test_two_fields_apart_within_anchor_does_not_reject(self) -> None:
        c1 = _candidate("action.species.bar.001", "species", "bar", category="attack", relation="enemy")
        c2 = _candidate("action.species.bar.002", "species", "bar", category="defense", relation="self")
        result = ds.select_round(candidate_rows=[c1, c2], accepted_rows=[], round_no=1,
                                 similarity_threshold_milli=700, family_ids=FAMILY_IDS)
        self.assertEqual({e["id"] for e in result.survivor_entries},
                         {"action.species.bar.001", "action.species.bar.002"})

    def test_near_duplicate_against_the_already_accepted_corpus_within_anchor_rejected(self) -> None:
        accepted = _candidate("action.species.bar.001", "species", "bar", category="attack")
        candidate = _candidate("action.species.bar.002", "species", "bar", category="defense")
        result = ds.select_round(candidate_rows=[candidate], accepted_rows=[accepted], round_no=1,
                                 similarity_threshold_milli=700, family_ids=FAMILY_IDS)
        self.assertEqual(result.survivor_entries, [])
        self.assertEqual(result.reject_entries[0]["tier"], 2)

    def test_masked_hash_set_scales_linearly_not_quadratically_over_a_larger_anchor(self) -> None:
        # Correctness check at a larger n, not a timing assertion -- proves the masked-bucket
        # implementation still finds every true one-field-apart pair rather than only adjacent
        # ones, which an accidentally-O(n) but WRONG implementation could get away with at n=2.
        rows = [_candidate(f"action.species.big.{i:03d}", "species", "big",
                          category=("attack" if i % 2 == 0 else "defense"))
               for i in range(1, 21)]
        result = ds.select_round(candidate_rows=rows, accepted_rows=[], round_no=1,
                                 similarity_threshold_milli=700, family_ids=FAMILY_IDS)
        # Every candidate after the first shares a fingerprint with SOME earlier one modulo only
        # `category`, which alternates between exactly two values -- so exactly one survivor.
        # Self-referential (population-pin SE3.5, 2026-09-20): rows is this test's own fixture.
        self.assertEqual(len(result.survivor_entries), 1)
        self.assertEqual(len(rows) - 1, len(result.reject_entries))


class Tier3Tests(unittest.TestCase):
    """Spec §5 'Planted violation -- t3 tries to gate' and '--no-semantic equivalence'."""

    def test_maximum_similarity_stub_changes_zero_survivors(self) -> None:
        c1 = _candidate("action.species.a.001", "species", "a", category="attack")
        c2 = _candidate("action.species.b.001", "species", "b", category="defense")
        result = ds.select_round(candidate_rows=[c1, c2], accepted_rows=[], round_no=1,
                                 similarity_threshold_milli=700, family_ids=FAMILY_IDS,
                                 similarity_fn=lambda a, b: 1000)
        self.assertEqual({e["id"] for e in result.survivor_entries},
                         {"action.species.a.001", "action.species.b.001"})
        self.assertEqual(len(result.review_entries), 1)
        row = result.review_entries[0]
        self.assertEqual(row["candidateA"], "action.species.a.001")
        self.assertEqual(row["candidateB"], "action.species.b.001")
        self.assertEqual(row["similarityMilli"], 1000)

    def test_minimum_similarity_stub_grows_no_review_queue(self) -> None:
        c1 = _candidate("action.species.a.001", "species", "a", category="attack")
        c2 = _candidate("action.species.b.001", "species", "b", category="defense")
        result = ds.select_round(candidate_rows=[c1, c2], accepted_rows=[], round_no=1,
                                 similarity_threshold_milli=700, family_ids=FAMILY_IDS,
                                 similarity_fn=lambda a, b: 0)
        self.assertEqual(result.review_entries, [])

    def test_no_semantic_produces_byte_identical_survivors_and_rejects(self) -> None:
        rows = [
            _candidate("action.species.a.001", "species", "a", category="attack"),
            _candidate("action.species.a.002", "species", "a", category="attack"),   # t1 dup
            _candidate("action.species.b.001", "species", "b", category="defense"),
        ]
        with_semantic = ds.select_round(candidate_rows=rows, accepted_rows=[], round_no=1,
                                        similarity_threshold_milli=700, family_ids=FAMILY_IDS,
                                        run_semantic=True, similarity_fn=lambda a, b: 1000)
        without_semantic = ds.select_round(candidate_rows=rows, accepted_rows=[], round_no=1,
                                           similarity_threshold_milli=700, family_ids=FAMILY_IDS,
                                           run_semantic=False, similarity_fn=lambda a, b: 1000)
        self.assertEqual(with_semantic.survivor_entries, without_semantic.survivor_entries)
        self.assertEqual(with_semantic.reject_entries, without_semantic.reject_entries)
        self.assertEqual(without_semantic.review_entries, [])
        self.assertNotEqual(with_semantic.review_entries, without_semantic.review_entries)

    def test_tier3_never_compares_a_candidate_against_itself(self) -> None:
        c1 = _candidate("action.species.a.001", "species", "a")
        result = ds.select_round(candidate_rows=[c1], accepted_rows=[], round_no=1,
                                 similarity_threshold_milli=700, family_ids=FAMILY_IDS,
                                 similarity_fn=lambda a, b: 1000)
        self.assertEqual(result.review_entries, [])


class SimilarityFunctionTests(unittest.TestCase):
    """Spec §1's own decided heuristic, acceptance #7b."""

    def test_tokenize_splits_latin_runs_and_cjk_per_character(self) -> None:
        tokens = sim.tokenize("Burn 铁头功 test-123")
        self.assertEqual(tokens, ("burn", "铁", "头", "功", "test", "123"))

    def test_tokenize_lowercases(self) -> None:
        self.assertEqual(sim.tokenize("FIRE Blast"), ("fire", "blast"))

    def test_jaccard_milli_identical_sets_is_1000(self) -> None:
        a = sim.token_set("Fire Blast", "burns the target")
        b = sim.token_set("Fire Blast", "burns the target")
        self.assertEqual(sim.jaccard_milli(a, b), 1000)

    def test_jaccard_milli_disjoint_sets_is_zero(self) -> None:
        a = sim.token_set("Fire Blast", "burns the target")
        b = sim.token_set("Ice Shard", "freezes a row")
        self.assertEqual(sim.jaccard_milli(a, b), 0)

    def test_jaccard_milli_both_empty_is_zero_not_a_crash(self) -> None:
        self.assertEqual(sim.jaccard_milli(frozenset(), frozenset()), 0)

    def test_jaccard_milli_partial_overlap(self) -> None:
        a = frozenset({"a", "b", "c", "d"})
        b = frozenset({"a", "b", "e", "f"})
        # intersection {a,b}=2, union {a,b,c,d,e,f}=6 -> 1000*2//6 = 333
        self.assertEqual(sim.jaccard_milli(a, b), 333)

    def test_bilingual_pair_never_treats_a_cjk_phrase_as_one_token(self) -> None:
        a = sim.token_set("连击", "combo strike")
        b = sim.token_set("连环", "chain strike")
        # per-character CJK split: {连,击} vs {连,环} share one character -- provably NOT distance
        # 1-of-1 (which a whitespace split over the whole phrase would produce).
        self.assertIn("连", a)
        self.assertIn("连", b)
        self.assertGreater(sim.jaccard_milli(a, b), 0)

    def test_similarity_function_constant_is_stable(self) -> None:
        self.assertEqual(sim.SIMILARITY_FUNCTION_ID, "token-overlap-jaccard-milli")
        self.assertEqual(sim.SIMILARITY_FUNCTION_VERSION, 1)


class DedupTuningLoadTests(unittest.TestCase):
    """The tuning file A-S3 owns for real (spec §2's "new" Reads row)."""

    def test_shipped_file_matches_spec_defaults(self) -> None:
        t = load_dedup_tuning()
        self.assertEqual(t.k, 8)
        self.assertEqual(t.similarity_threshold_milli, 700)
        self.assertEqual(t.t2_field_distance, 1)
        self.assertEqual(t.version, 1)

    def test_k_matches_fingerprint_component_count_plus_one(self) -> None:
        from seedsmith.adapters.actions.distribution_planner.tuning import (
            DEFAULT_AVOID_NEIGHBOUR_K, FINGERPRINT_COMPONENT_COUNT,
        )
        self.assertEqual(FINGERPRINT_COMPONENT_COUNT, 7)
        self.assertEqual(DEFAULT_AVOID_NEIGHBOUR_K, 8)
        self.assertEqual(load_dedup_tuning().k, DEFAULT_AVOID_NEIGHBOUR_K)

    def _write(self, tmp: Path, **overrides) -> Path:
        doc = json.loads(DEDUP_TUNING_PATH.read_text(encoding="utf-8"))
        doc.update(overrides)
        path = tmp / "action-dedup.v1.json"
        path.write_text(json.dumps(doc), encoding="utf-8")
        return path

    def test_float_k_refused(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(Path(tmp), k=8.5)
            with self.assertRaises(ValueError) as ctx:
                load_dedup_tuning(path)
            self.assertIn("k", str(ctx.exception))

    def test_bool_masquerading_as_int_refused(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(Path(tmp), k=True)
            with self.assertRaises(ValueError):
                load_dedup_tuning(path)

    def test_numeric_string_threshold_refused(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(Path(tmp), similarityThresholdMilli="700")
            with self.assertRaises(ValueError) as ctx:
                load_dedup_tuning(path)
            self.assertIn("similarityThresholdMilli", str(ctx.exception))

    def test_threshold_out_of_range_refused(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(Path(tmp), similarityThresholdMilli=1001)
            with self.assertRaises(ValueError):
                load_dedup_tuning(path)

    def test_t2_field_distance_other_than_implemented_value_refused(self) -> None:
        self.assertEqual(IMPLEMENTED_T2_FIELD_DISTANCE, 1)
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(Path(tmp), t2FieldDistance=2)
            with self.assertRaises(ValueError) as ctx:
                load_dedup_tuning(path)
            self.assertIn("t2FieldDistance", str(ctx.exception))


class DeterminismAndPurityTests(unittest.TestCase):
    """Spec §5 'Determinism' and 'Purity', acceptance #3/#8."""

    def _fixture(self) -> "list[dict]":
        return [
            _candidate("action.species.a.001", "species", "a", category="attack",
                      name="Fire Blast", rationale="burns the target"),
            _candidate("action.species.a.002", "species", "a", category="support"),
            _candidate("action.family.f.001", "family", "f"),
            _candidate("action.general.0001", "general", None),
            _candidate("action.species.b.001", "species", "b", category="defense",
                      name="Fire Blast", rationale="burns the target"),
        ]

    def test_shuffled_input_order_produces_byte_identical_output(self) -> None:
        rows = self._fixture()
        r1 = ds.select_round(candidate_rows=rows, accepted_rows=[], round_no=1,
                             similarity_threshold_milli=700, family_ids=FAMILY_IDS)
        shuffled = list(rows)
        random.Random(3).shuffle(shuffled)
        r2 = ds.select_round(candidate_rows=shuffled, accepted_rows=[], round_no=1,
                             similarity_threshold_milli=700, family_ids=FAMILY_IDS)
        self.assertEqual(r1.survivor_entries, r2.survivor_entries)
        self.assertEqual(r1.reject_entries, r2.reject_entries)
        self.assertEqual(r1.review_entries, r2.review_entries)
        self.assertEqual(r1.corpus_hash, r2.corpus_hash)
        self.assertEqual(r1.candidate_set_hash, r2.candidate_set_hash)

    def test_rerun_over_unchanged_inputs_is_identical(self) -> None:
        rows = self._fixture()
        r1 = ds.select_round(candidate_rows=rows, accepted_rows=[], round_no=1,
                             similarity_threshold_milli=700, family_ids=FAMILY_IDS)
        r2 = ds.select_round(candidate_rows=rows, accepted_rows=[], round_no=1,
                             similarity_threshold_milli=700, family_ids=FAMILY_IDS)
        self.assertEqual(r1, r2)


class ProvenanceTests(unittest.TestCase):
    """Acceptance #7 -- corpus hash, candidate-set hash, tuning version, similarity function id."""

    def test_regenerate_records_provenance_and_semantic_fields_only_land_in_review_queue(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_root = Path(tmp)
            actions_root = tmp_root / "actions"
            (actions_root / "_generated").mkdir(parents=True)
            candidates_doc = {
                "schemaVersion": 1, "kind": "action-seed",
                "entries": [
                    _candidate("action.species.a.001", "species", "a", category="attack",
                              name="Fire Blast", rationale="burns the target"),
                    _candidate("action.species.b.001", "species", "b", category="defense",
                              name="Fire Blast", rationale="burns the target"),
                ],
            }
            candidates_path = tmp_root / "candidates.json"
            candidates_path.write_text(json.dumps(candidates_doc), encoding="utf-8")

            summary = gen_mod.regenerate(candidates_path=candidates_path, actions_root=actions_root,
                                         round_no=1, run_semantic=True, write=True)
            self.assertEqual(summary["survivorCount"], 2)

            round_dir = actions_root / "_rounds" / "round-1"
            survivors_doc = json.loads((round_dir / "survivors.json").read_text(encoding="utf-8"))
            rejects_doc = json.loads((round_dir / "rejects.json").read_text(encoding="utf-8"))
            review_doc = json.loads((round_dir / "review-queue.json").read_text(encoding="utf-8"))

            for doc, kind in ((survivors_doc, "action-seed"), (rejects_doc, "action-reject"),
                             (review_doc, "action-review")):
                self.assertEqual(doc["kind"], kind)
                self.assertIn("corpusHash", doc["_meta"])
                self.assertIn("candidateSetHash", doc["_meta"])
                self.assertEqual(doc["_meta"]["tuningVersion"], 1)
                self.assertEqual(doc["_meta"]["round"], 1)

            self.assertNotIn("semanticEnabled", survivors_doc["_meta"])
            self.assertNotIn("semanticEnabled", rejects_doc["_meta"])
            self.assertTrue(review_doc["_meta"]["semanticEnabled"])
            self.assertEqual(review_doc["_meta"]["similarityFunctionId"], "token-overlap-jaccard-milli")
            self.assertEqual(review_doc["_meta"]["similarityFunctionVersion"], 1)

    def test_no_semantic_review_queue_meta_carries_explicit_nulls(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_root = Path(tmp)
            actions_root = tmp_root / "actions"
            (actions_root / "_generated").mkdir(parents=True)
            candidates_doc = {
                "schemaVersion": 1, "kind": "action-seed",
                "entries": [_candidate("action.species.a.001", "species", "a")],
            }
            candidates_path = tmp_root / "candidates.json"
            candidates_path.write_text(json.dumps(candidates_doc), encoding="utf-8")

            gen_mod.regenerate(candidates_path=candidates_path, actions_root=actions_root,
                              round_no=1, run_semantic=False, write=True)
            review_doc = json.loads(
                (actions_root / "_rounds" / "round-1" / "review-queue.json").read_text(encoding="utf-8"))
            self.assertFalse(review_doc["_meta"]["semanticEnabled"])
            self.assertIsNone(review_doc["_meta"]["similarityFunctionId"])
            self.assertIsNone(review_doc["_meta"]["similarityFunctionVersion"])
            self.assertIn("similarityFunctionId", review_doc["_meta"])   # explicit null, never omitted


class PurityIntegrationTests(unittest.TestCase):
    """Spec §5 'Purity' over the real write path -- a tempfile-scoped scratch tree
    (`load._load_committed_corpus`'s own scratch-copy pattern), never the real
    `gk-data/packs/fusion/data/seed/actions/_rounds/` tree with fabricated content (task scoping note)."""

    def test_regenerate_twice_over_the_same_inputs_writes_byte_identical_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_root = Path(tmp)
            actions_root = tmp_root / "actions"
            (actions_root / "_generated").mkdir(parents=True)
            candidates_doc = {
                "schemaVersion": 1, "kind": "action-seed",
                "entries": [
                    _candidate("action.species.a.001", "species", "a", category="attack"),
                    _candidate("action.species.a.002", "species", "a", category="attack"),  # t1 dup
                    _candidate("action.species.b.001", "species", "b", category="defense",
                              name="Fire Blast", rationale="burns"),
                    _candidate("action.species.c.001", "species", "c", category="support",
                              name="Fire Blast", rationale="burns"),
                ],
            }
            candidates_path = tmp_root / "candidates.json"
            candidates_path.write_text(json.dumps(candidates_doc), encoding="utf-8")

            gen_mod.regenerate(candidates_path=candidates_path, actions_root=actions_root, round_no=1)
            round_dir = actions_root / "_rounds" / "round-1"
            self.assertEqual(sorted(p.name for p in round_dir.glob("*.json")),
                             ["rejects.json", "review-queue.json", "survivors.json"])
            # Nothing was written anywhere under actions_root OTHER than `_rounds/round-1/` --
            # spec §4's "never write outside data/seed/actions/_rounds/round-<n>/", asserted
            # rather than assumed.
            written_dirs = {p.relative_to(actions_root).parts[0] for p in actions_root.iterdir()}
            self.assertEqual(written_dirs, {"_generated", "_rounds"})
            text1 = {p.name: p.read_text(encoding="utf-8") for p in round_dir.glob("*.json")}

            gen_mod.regenerate(candidates_path=candidates_path, actions_root=actions_root, round_no=1)
            text2 = {p.name: p.read_text(encoding="utf-8") for p in round_dir.glob("*.json")}

            self.assertEqual(text1, text2)
            for text in text1.values():
                self.assertTrue(text.endswith("\n"))

    def test_dry_run_writes_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_root = Path(tmp)
            actions_root = tmp_root / "actions"
            (actions_root / "_generated").mkdir(parents=True)
            candidates_doc = {
                "schemaVersion": 1, "kind": "action-seed",
                "entries": [_candidate("action.species.a.001", "species", "a")],
            }
            candidates_path = tmp_root / "candidates.json"
            candidates_path.write_text(json.dumps(candidates_doc), encoding="utf-8")

            summary = gen_mod.regenerate(candidates_path=candidates_path, actions_root=actions_root,
                                         round_no=1, write=False)
            self.assertFalse(summary["written"])
            self.assertFalse((actions_root / "_rounds").exists())

    def test_wrong_kind_candidates_envelope_refused(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_root = Path(tmp)
            actions_root = tmp_root / "actions"
            (actions_root / "_generated").mkdir(parents=True)
            candidates_path = tmp_root / "candidates.json"
            candidates_path.write_text(json.dumps({"schemaVersion": 1, "kind": "action-brief",
                                                   "entries": []}), encoding="utf-8")
            with self.assertRaises(ValueError) as ctx:
                gen_mod.regenerate(candidates_path=candidates_path, actions_root=actions_root, round_no=1)
            self.assertIn("action-seed", str(ctx.exception))


class EnvelopeAndCorpusRoundTripTests(unittest.TestCase):
    """AC1 -- files load back through an explicit round load and match `kinds.py`'s own KindSpec
    id_patterns for `action-reject`/`action-review`."""

    def test_reject_and_review_ids_match_kind_spec_patterns(self) -> None:
        rows = [
            _candidate("action.species.a.001", "species", "a", category="attack",
                      name="Fire Blast", rationale="burns"),
            _candidate("action.species.a.002", "species", "a", category="attack",
                      name="Fire Blast", rationale="burns"),                 # t1 dup
            _candidate("action.species.b.001", "species", "b", category="defense",
                      name="Fire Blast", rationale="burns"),
        ]
        result = ds.select_round(candidate_rows=rows, accepted_rows=[], round_no=7,
                                 similarity_threshold_milli=0, family_ids=FAMILY_IDS,
                                 similarity_fn=lambda a, b: 1000)
        reject_pattern = next(k for k in KINDS if k.kind == "action-reject").id_pattern
        review_pattern = next(k for k in KINDS if k.kind == "action-review").id_pattern
        seed_pattern = next(k for k in KINDS if k.kind == "action-seed").id_pattern
        for r in result.reject_entries:
            self.assertIsNotNone(reject_pattern.match(r["id"]), r["id"])
        for r in result.review_entries:
            self.assertIsNotNone(review_pattern.match(r["id"]), r["id"])
        for e in result.survivor_entries:
            self.assertIsNotNone(seed_pattern.match(e["id"]), e["id"])

    def test_round_written_files_load_back_through_explicit_round_load(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_root = Path(tmp)
            actions_root = tmp_root / "actions"
            (actions_root / "_generated").mkdir(parents=True)
            candidates_doc = {
                "schemaVersion": 1, "kind": "action-seed",
                "entries": [_candidate("action.species.a.001", "species", "a")],
            }
            candidates_path = tmp_root / "candidates.json"
            candidates_path.write_text(json.dumps(candidates_doc), encoding="utf-8")
            gen_mod.regenerate(candidates_path=candidates_path, actions_root=actions_root, round_no=1)

            round_corpus = Corpus.load(actions_root / "_rounds" / "round-1")
            self.assertEqual(len(round_corpus.by_kind("action-seed")), 1)
            self.assertEqual(round_corpus.by_kind("action-seed")[0].id, "action.species.a.001")


class RoundIsolationTests(unittest.TestCase):
    """Spec §2's F14 correction and acceptance #1b -- a committed-corpus load over a tree holding
    both a round survivor and its promoted twin raises no duplicate-id error, because `_rounds/`
    is excluded by `_manifest.json` (A-C1, already declared) and this module is the first one to
    actually write real content there."""

    def test_survivor_and_promoted_twin_do_not_collide_through_committed_load(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "_manifest.json").write_text(json.dumps({
                "schemaVersion": 1, "kind": "action-config",
                "entries": [{"id": "_rounds/", "type": "prefix", "disposition": "exclude",
                            "reason": "test fixture, mirrors the real _manifest.json row"}],
            }), encoding="utf-8")

            promoted_row = _candidate("action.species.foo.001", "species", "foo")
            (root / "committed.json").write_text(json.dumps({
                "schemaVersion": 1, "kind": "action-seed", "entries": [promoted_row],
            }), encoding="utf-8")

            round_dir = root / "_rounds" / "round-1"
            round_dir.mkdir(parents=True)
            (round_dir / "survivors.json").write_text(json.dumps({
                "schemaVersion": 1, "kind": "action-seed",
                "entries": [promoted_row],           # same id -- the round file's own "promoted" marker
            }), encoding="utf-8")

            load_result = load_committed(root)        # must not raise CorpusLoadError
            seed_rows = load_result.corpus.by_kind("action-seed")
            self.assertEqual(len(seed_rows), 1)
            self.assertEqual(seed_rows[0].path, "committed.json")


class OfflineGuaranteeTests(unittest.TestCase):
    """Spec §5 'Offline guarantee', acceptance #9 -- zero model calls on the acceptance path."""

    def test_no_semantic_never_invokes_the_similarity_seam_even_if_it_would_raise(self) -> None:
        def _raising(a, b):
            raise RuntimeError("a real transport must never be reached here")
        c1 = _candidate("action.species.a.001", "species", "a", category="attack", relation="enemy")
        c2 = _candidate("action.species.b.001", "species", "b", category="movement", relation="self")
        result = ds.select_round(candidate_rows=[c1, c2], accepted_rows=[], round_no=1,
                                 similarity_threshold_milli=700, family_ids=FAMILY_IDS,
                                 run_semantic=False, similarity_fn=_raising)   # must not raise
        self.assertEqual(len(result.survivor_entries), 2)

    def test_no_model_transport_import_anywhere_in_the_package(self) -> None:
        pkg_dir = Path(ds.__file__).resolve().parent
        files = list(pkg_dir.glob("*.py")) + [Path(gen_mod.__file__)]
        forbidden = ("llm_caller", "pipeline.run", "openai", "requests", "urllib", "socket")
        for f in files:
            text = f.read_text(encoding="utf-8")
            for token in forbidden:
                self.assertNotIn(token, text, f"{f} references {token!r}")


class MagicNumberAuditTests(unittest.TestCase):
    """This session's own AST-based-audit precedent (`gk-core/scripts/audit-magic-numbers.py` does not
    cover Python paths, confirmed directly in `test_distribution_planner.py`). Every bare
    int/float literal in this module's own executable code must be structural -- the balance
    surface (k, similarityThresholdMilli, t2FieldDistance) lives entirely in
    `gk-core/data/tuning/action-dedup.v1.json`, never as a literal here."""

    # 0/1/2/3 -- loop/tuple/field indices, ordinal +1. 5/6 -- `Path(__file__).resolve().parents[N]`
    # directory-depth indices (generate_dedup_select.py is 5 deep from repo root; dedup_select/
    # tuning.py, one package deeper, is 6). 1000 -- the per-mille scale (similarity.py). The two
    # `long`-adjacent bounds are not needed here (this module does no `long` arithmetic of its own
    # -- it hashes and compares strings).
    _ALLOWED = frozenset({0, 1, 2, 3, 5, 6, 1000})

    def test_zero_unallowlisted_numeric_literals(self) -> None:
        pkg_dir = Path(ds.__file__).resolve().parent
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


if __name__ == "__main__":
    unittest.main()
