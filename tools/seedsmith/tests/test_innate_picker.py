"""Tests for seedsmith.adapters.actions.innate_picker (A-S6, spec-innate-picker.md).

    python -m pytest gk-forge/tools/seedsmith/tests/test_innate_picker.py -v

Spec §5's ten named cases plus §6's acceptance criteria (1-9, 9b, 10). Same fixture discipline
every prior module in this session established: the real accepted corpus (A-S3 survivors plus
everything already accepted) does not exist yet, so every test below runs against synthetic,
in-memory candidate/role-lean/catalog fixtures, never a real committed tree.
"""
from __future__ import annotations

import ast
import hashlib
import json
import random
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from seedsmith.adapters.actions.characteristic_pool.catalog import SpeciesRow, load_catalog  # noqa: E402
from seedsmith.adapters.actions.distribution_planner.derive import load_scope_windows  # noqa: E402
from seedsmith.adapters.actions.innate_picker import derive as ip  # noqa: E402
from seedsmith.adapters.actions.innate_picker.tuning import (  # noqa: E402
    INNATE_TUNING_PATH, InnateWeights, load_innate_weights,
)
from seedsmith.adapters.actions import generate_innate_picker as gen_mod  # noqa: E402
from seedsmith.adapters.actions.kinds import KINDS  # noqa: E402
from seedsmith.adapters.actions.load import load_committed  # noqa: E402
from seedsmith.corpus import Corpus, CorpusLoadError  # noqa: E402

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



def _cap() -> int:
    """ST3: the `+cap` offset as the entrypoint loads it -- the species rung window's own ceiling,
    read from the published table so no test pins it."""
    return load_scope_windows(_owned("data/tuning/action-rungs.v3.json"))["species"][1]


def _parse_candidate(row):
    """`ip.parse_candidate` with the entrypoint's own loaded cap -- ST3 made `cap` a required
    parameter (no code default), so every parsing assertion supplies it the same way production
    does instead of repeating the load at 15 call sites."""
    return ip.parse_candidate(row, cap=_cap())


DEFAULT_WEIGHTS = InnateWeights(role_lean_match_milli=1000, motif_coverage_milli=1000,
                                element_match_milli=1000, category_scarcity_milli=1000,
                                rung_ceiling_milli=1000, version=1)


# ---------------------------------------------------------------------------------------------
# Fixture builders — a synthetic action-seed candidate row (A-S3's own accepted shape) and a
# synthetic role-lean.json entry (A-S0's own shape).
# ---------------------------------------------------------------------------------------------

def _candidate(id_, scope, scope_key, *, category="attack", rung_band=(1, 10), kind_hint=None,
              motifs_used=(), element_affinity=None):
    return {
        "id": id_, "scope": scope, "scopeKey": scope_key, "category": category,
        "rungBand": list(rung_band), "targetMode": "single", "relation": "enemy",
        "atomFamilies": ["atom.fx-passive-atk-flat"], "pairingRole": "none",
        "kindHint": kind_hint, "motifsUsed": list(motifs_used),
        "elementAffinity": element_affinity,
    }


def _role_lean(species_key, *, family=None, lean_order=("attack", "defense", "support",
              "movement", "status"), lean_source="derived", motifs=()):
    return ip.SpeciesRoleLean(species_key=species_key, family=family,
                              lean_order=tuple(lean_order), lean_source=lean_source,
                              motifs=tuple(motifs))


def _species(species_id, *, element_primary="fire", element_secondary=None, rarity="chaff",
            traits=()):
    return SpeciesRow(species_id=species_id, element_primary=element_primary,
                      element_secondary=element_secondary, rarity=rarity, rarity_ordinal=0,
                      traits=tuple(traits))


# ---------------------------------------------------------------------------------------------
# §3.1 -- candidate parsing + eligibility.
# ---------------------------------------------------------------------------------------------

class CandidateParseTests(unittest.TestCase):
    def test_valid_candidate_parses(self) -> None:
        c = _parse_candidate(_candidate("action.species.x.001", "species", "x"))
        self.assertEqual(c.id, "action.species.x.001")
        self.assertEqual(c.rung_ceiling, 10)
        self.assertIsNone(c.element_affinity)

    def test_missing_id_refused(self) -> None:
        with self.assertRaises(ValueError):
            _parse_candidate({"scope": "species", "scopeKey": "x", "category": "attack",
                               "rungBand": [1, 10]})

    def test_unknown_scope_refused(self) -> None:
        row = _candidate("action.species.x.001", "species", "x")
        row["scope"] = "Species"           # PascalCase planted violation
        with self.assertRaises(ValueError):
            _parse_candidate(row)

    def test_unknown_category_refused(self) -> None:
        row = _candidate("action.species.x.001", "species", "x")
        row["category"] = "Attack"
        with self.assertRaises(ValueError):
            _parse_candidate(row)

    def test_rung_ceiling_out_of_range_refused(self) -> None:
        row = _candidate("action.species.x.001", "species", "x", rung_band=(1, 11))
        with self.assertRaises(ValueError):
            _parse_candidate(row)

    def test_element_affinity_absent_by_default(self) -> None:
        c = _parse_candidate(_candidate("action.species.x.001", "species", "x"))
        self.assertIsNone(c.element_affinity)

    def test_element_affinity_read_when_present(self) -> None:
        c = _parse_candidate(
            _candidate("action.species.x.001", "species", "x", element_affinity="fire"))
        self.assertEqual(c.element_affinity, "fire")


class EligibilityTests(unittest.TestCase):
    """Spec §3.1: species/family scope match, `general` never eligible, `kindHint != 'basic'`,
    not already promoted."""

    def test_species_scope_matches_own_species_only(self) -> None:
        c = _parse_candidate(_candidate("action.species.x.001", "species", "x"))
        self.assertTrue(ip.is_eligible(c, "x", None, set()))
        self.assertFalse(ip.is_eligible(c, "y", None, set()))

    def test_family_scope_matches_species_own_family_only(self) -> None:
        c = _parse_candidate(_candidate("action.family.f.001", "family", "f"))
        self.assertTrue(ip.is_eligible(c, "x", "f", set()))
        self.assertFalse(ip.is_eligible(c, "x", "g", set()))
        self.assertFalse(ip.is_eligible(c, "x", None, set()))

    def test_general_scope_never_eligible(self) -> None:
        c = _parse_candidate(_candidate("action.general.0001", "general", None))
        self.assertFalse(ip.is_eligible(c, "x", "f", set()))

    def test_basic_kind_hint_excluded(self) -> None:
        c = _parse_candidate(
            _candidate("action.species.x.001", "species", "x", kind_hint="basic"))
        self.assertFalse(ip.is_eligible(c, "x", None, set()))

    def test_non_basic_kind_hint_eligible(self) -> None:
        for hint in (None, "skill", "innate"):
            c = _parse_candidate(
                _candidate("action.species.x.001", "species", "x", kind_hint=hint))
            self.assertTrue(ip.is_eligible(c, "x", None, set()), f"kindHint={hint!r}")

    def test_already_promoted_excluded(self) -> None:
        c = _parse_candidate(_candidate("action.species.x.001", "species", "x"))
        self.assertFalse(ip.is_eligible(c, "x", None, {"action.species.x.001"}))


class ValidateEligibleSetTests(unittest.TestCase):
    """Spec §5 'general leaks in' -- defense in depth over `is_eligible`'s own filter."""

    def test_general_scope_in_eligible_set_refused_naming_the_scope(self) -> None:
        c = _parse_candidate(_candidate("action.general.0001", "general", None))
        with self.assertRaises(ValueError) as ctx:
            ip.validate_eligible_set([c])
        self.assertIn("general", str(ctx.exception))

    def test_clean_eligible_set_passes(self) -> None:
        c = _parse_candidate(_candidate("action.species.x.001", "species", "x"))
        ip.validate_eligible_set([c])  # must not raise


# ---------------------------------------------------------------------------------------------
# §3.2 -- the five raw terms.
# ---------------------------------------------------------------------------------------------

class ComputeTermsTests(unittest.TestCase):
    def test_role_lean_match_reads_5_minus_index(self) -> None:
        role_lean = _role_lean("x", lean_order=("support", "attack", "defense", "movement",
                                                "status"))
        c = _parse_candidate(_candidate("action.species.x.001", "species", "x", category="attack"))
        terms = ip.compute_terms(c, role_lean, 1, {"attack": 1}, "fire", None)
        self.assertEqual(terms["roleLeanMatch"], 4)   # 5 - index(1)

    def test_uniform_floor_zeroes_role_lean_match_for_every_candidate(self) -> None:
        role_lean = _role_lean("x", lean_source="floor")
        for cat in ("attack", "defense", "support", "movement", "status"):
            c = _parse_candidate(_candidate("action.species.x.001", "species", "x", category=cat))
            terms = ip.compute_terms(c, role_lean, 1, {cat: 1}, "fire", None)
            self.assertEqual(terms["roleLeanMatch"], 0, f"category={cat}")

    def test_family_less_derived_nofloor_is_not_the_floor_case(self) -> None:
        """Review F12's own regression guard: a family-less species (`derived-nofloor`) still
        carries a real, differentiated `leanOrder` -- a non-zero spread across its own candidates'
        `roleLeanMatch`, never the flat-zero the genuine `floor` case produces."""
        role_lean = _role_lean("x", family=None, lean_source="derived-nofloor",
                               lean_order=("status", "attack", "defense", "support", "movement"))
        candidates = [
            _parse_candidate(_candidate(f"action.species.x.{i:03d}", "species", "x", category=cat))
            for i, cat in enumerate(("status", "movement"), start=1)
        ]
        terms = [ip.compute_terms(c, role_lean, 2, {"status": 1, "movement": 1}, "fire", None)
                for c in candidates]
        spread = {t["roleLeanMatch"] for t in terms}
        self.assertGreater(len(spread), 1, "derived-nofloor must NOT collapse to a flat spread")

    def test_motif_coverage_counts_species_motifs_present_in_motifs_used(self) -> None:
        role_lean = _role_lean("x", motifs=("fire", "burst", "chain"))
        c = _parse_candidate(_candidate("action.species.x.001", "species", "x",
                                          motifs_used=("fire", "chain", "unrelated")))
        terms = ip.compute_terms(c, role_lean, 1, {"attack": 1}, "fire", None)
        self.assertEqual(terms["motifCoverage"], 2)

    def test_motif_coverage_zero_when_motifs_used_absent(self) -> None:
        role_lean = _role_lean("x", motifs=("fire", "burst"))
        c = _parse_candidate(_candidate("action.species.x.001", "species", "x"))
        terms = ip.compute_terms(c, role_lean, 1, {"attack": 1}, "fire", None)
        self.assertEqual(terms["motifCoverage"], 0)

    def test_element_match_primary_is_2_secondary_is_1_else_0(self) -> None:
        role_lean = _role_lean("x")
        primary = _parse_candidate(_candidate("action.species.x.001", "species", "x",
                                                 element_affinity="fire"))
        secondary = _parse_candidate(_candidate("action.species.x.002", "species", "x",
                                                   element_affinity="ice"))
        neither = _parse_candidate(_candidate("action.species.x.003", "species", "x",
                                                 element_affinity="dark"))
        absent = _parse_candidate(_candidate("action.species.x.004", "species", "x"))
        counts = {"attack": 4}
        self.assertEqual(ip.compute_terms(primary, role_lean, 4, counts, "fire", "ice")["elementMatch"], 2)
        self.assertEqual(ip.compute_terms(secondary, role_lean, 4, counts, "fire", "ice")["elementMatch"], 1)
        self.assertEqual(ip.compute_terms(neither, role_lean, 4, counts, "fire", "ice")["elementMatch"], 0)
        self.assertEqual(ip.compute_terms(absent, role_lean, 4, counts, "fire", "ice")["elementMatch"], 0)

    def test_element_match_zero_when_species_has_no_secondary(self) -> None:
        role_lean = _role_lean("x")
        c = _parse_candidate(_candidate("action.species.x.001", "species", "x",
                                          element_affinity="ice"))
        terms = ip.compute_terms(c, role_lean, 1, {"attack": 1}, "fire", None)
        self.assertEqual(terms["elementMatch"], 0)

    def test_category_scarcity_is_eligible_count_minus_same_category_count(self) -> None:
        role_lean = _role_lean("x")
        c = _parse_candidate(_candidate("action.species.x.001", "species", "x", category="attack"))
        terms = ip.compute_terms(c, role_lean, 5, {"attack": 2, "defense": 3}, "fire", None)
        self.assertEqual(terms["categoryScarcity"], 3)   # 5 - 2

    def test_rung_ceiling_stored_raw_not_negated(self) -> None:
        role_lean = _role_lean("x")
        c = _parse_candidate(_candidate("action.species.x.001", "species", "x", rung_band=(1, 7)))
        terms = ip.compute_terms(c, role_lean, 1, {"attack": 1}, "fire", None)
        self.assertEqual(terms["rungCeiling"], 7)


# ---------------------------------------------------------------------------------------------
# §3.3 -- the tunable, `long` score.
# ---------------------------------------------------------------------------------------------

class ComputeScoreTests(unittest.TestCase):
    def test_default_weights_reproduce_positional_priority_over_two_candidates(self) -> None:
        """A higher roleLeanMatch must always win regardless of every lower term, at w_t=1000 --
        the whole point of the positional-radix base construction."""
        cap = _cap()
        winner_terms = {"roleLeanMatch": 5, "motifCoverage": 0, "elementMatch": 0,
                        "categoryScarcity": 0, "rungCeiling": cap}
        loser_terms = {"roleLeanMatch": 4, "motifCoverage": 99, "elementMatch": 2,
                      "categoryScarcity": 99, "rungCeiling": 1}
        m2, m3, m4 = 99, 2, 99
        m5_shifted = cap - 1
        winner_score = ip.compute_score(winner_terms, cap, m2, m3, m4, m5_shifted, DEFAULT_WEIGHTS)
        loser_score = ip.compute_score(loser_terms, cap, m2, m3, m4, m5_shifted, DEFAULT_WEIGHTS)
        self.assertGreater(winner_score, loser_score)

    def test_lower_rung_ceiling_scores_higher_all_else_equal(self) -> None:
        cap = _cap()
        base_terms = {"roleLeanMatch": 3, "motifCoverage": 1, "elementMatch": 1,
                     "categoryScarcity": 1}
        low_ceiling = {**base_terms, "rungCeiling": 1}
        high_ceiling = {**base_terms, "rungCeiling": cap}
        m5_shifted = cap - 1
        s_low = ip.compute_score(low_ceiling, cap, 1, 1, 1, m5_shifted, DEFAULT_WEIGHTS)
        s_high = ip.compute_score(high_ceiling, cap, 1, 1, 1, m5_shifted, DEFAULT_WEIGHTS)
        self.assertGreater(s_low, s_high)


class OverflowTests(unittest.TestCase):
    """Spec §5 'Overflow': a large synthetic eligible set with maximal terms stays in bounds; a
    forced overflow throws."""

    def test_large_realistic_set_does_not_overflow(self) -> None:
        cap = _cap()
        terms = {"roleLeanMatch": 5, "motifCoverage": 20, "elementMatch": 2,
                "categoryScarcity": 999, "rungCeiling": 1}
        score = ip.compute_score(terms, cap, 20, 2, 999, cap - 1, DEFAULT_WEIGHTS)
        self.assertIsInstance(score, int)
        self.assertLessEqual(score, ip._LONG_MAX)

    def test_forced_overflow_raises(self) -> None:
        huge_weights = InnateWeights(role_lean_match_milli=1000, motif_coverage_milli=1000,
                                     element_match_milli=1000, category_scarcity_milli=1000,
                                     rung_ceiling_milli=1000, version=1)
        cap = _cap()
        terms = {"roleLeanMatch": 5, "motifCoverage": 5, "elementMatch": 2,
                "categoryScarcity": 5, "rungCeiling": 1}
        # M2/M3/M4/M5 sized so the base chain alone blows past a `long` before any term/weight is
        # even applied -- a direct, deterministic forced overflow.
        with self.assertRaises(OverflowError):
            ip.compute_score(terms, cap, 10**6, 10**6, 10**6, cap - 1, huge_weights)

    def test_widen_mul_itself_throws_past_the_long_bound(self) -> None:
        with self.assertRaises(OverflowError):
            ip._widen_mul(ip._LONG_MAX, 2)


class WeightDefaultTests(unittest.TestCase):
    """Spec §5 'Weight default': w_t=1000 for all five reproduces lexicographic tuple ordering
    exactly, over generated candidate permutations."""

    def _lexicographic_key(self, terms, cap):
        return (terms["roleLeanMatch"], terms["motifCoverage"], terms["elementMatch"],
               terms["categoryScarcity"], -(terms["rungCeiling"]))

    def test_score_ordering_matches_lexicographic_ordering(self) -> None:
        rng = random.Random(42)
        cap = _cap()
        for _trial in range(30):
            n = rng.randint(2, 6)
            rows = []
            for i in range(n):
                terms = {
                    "roleLeanMatch": rng.randint(0, 5), "motifCoverage": rng.randint(0, 4),
                    "elementMatch": rng.randint(0, 2), "categoryScarcity": rng.randint(0, 6),
                    "rungCeiling": rng.randint(1, cap),
                }
                rows.append((f"action.species.x.{i:03d}", terms))

            m2 = max(t["motifCoverage"] for _id, t in rows)
            m3 = max(t["elementMatch"] for _id, t in rows)
            m4 = max(t["categoryScarcity"] for _id, t in rows)
            m5_shifted = max(cap - t["rungCeiling"] for _id, t in rows)

            scored = sorted(
                ((ip.compute_score(t, cap, m2, m3, m4, m5_shifted, DEFAULT_WEIGHTS), aid)
                 for aid, t in rows),
                key=lambda row: (-row[0], row[1]),
            )
            lexicographic = sorted(
                rows, key=lambda row: (self._lexicographic_key(row[1], cap) + (row[0],)),
                reverse=False,
            )
            # Sort DESC on the lexicographic key, ASC on id for ties -- build the comparable key
            # the same way `pick_for_species` breaks ties, then compare winner ids only (score
            # magnitudes are not expected to match, only the ORDER they induce).
            lexicographic_order = sorted(
                rows, key=lambda row: (tuple(-v for v in self._lexicographic_key(row[1], cap)), row[0]))
            self.assertEqual(scored[0][1], lexicographic_order[0][0])


# ---------------------------------------------------------------------------------------------
# §3.4 -- the pick, per species.
# ---------------------------------------------------------------------------------------------

class PickForSpeciesTests(unittest.TestCase):
    def test_empty_eligible_set_is_null_with_reason(self) -> None:
        role_lean = _role_lean("x")
        pick = ip.pick_for_species(cap=_cap(), species_key="x", family_key=None, role_lean=role_lean,
                                   element_primary="fire", element_secondary=None,
                                   ordered_candidates=[], already_promoted=set(),
                                   weights=DEFAULT_WEIGHTS)
        self.assertIsNone(pick.innate_action_id)
        self.assertEqual(pick.reason, "no eligible action")
        self.assertEqual(pick.eligible_count, 0)

    def test_missing_role_lean_entry_is_null_with_its_own_reason(self) -> None:
        c = _parse_candidate(_candidate("action.species.x.001", "species", "x"))
        pick = ip.pick_for_species(cap=_cap(), species_key="x", family_key=None, role_lean=None,
                                   element_primary="fire", element_secondary=None,
                                   ordered_candidates=[c], already_promoted=set(),
                                   weights=DEFAULT_WEIGHTS)
        self.assertIsNone(pick.innate_action_id)
        self.assertEqual(pick.reason, "no role-lean entry")

    def test_single_candidate_is_picked_with_no_runner_up(self) -> None:
        role_lean = _role_lean("x")
        c = _parse_candidate(_candidate("action.species.x.001", "species", "x"))
        pick = ip.pick_for_species(cap=_cap(), species_key="x", family_key=None, role_lean=role_lean,
                                   element_primary="fire", element_secondary=None,
                                   ordered_candidates=[c], already_promoted=set(),
                                   weights=DEFAULT_WEIGHTS)
        self.assertEqual(pick.innate_action_id, "action.species.x.001")
        self.assertIsNone(pick.runner_up)
        self.assertEqual(pick.eligible_count, 1)

    def test_five_way_tie_lower_action_id_wins_input_order_independent(self) -> None:
        """Planted violation (spec §5): two candidates identical on all five terms -- the lower
        `actionId` ordinal wins, and the result must not depend on input order."""
        role_lean = _role_lean("x")
        rows = [
            _candidate("action.species.x.002", "species", "x", category="attack", rung_band=(1, 5)),
            _candidate("action.species.x.001", "species", "x", category="attack", rung_band=(1, 5)),
        ]
        for ordering in (rows, list(reversed(rows))):
            candidates = [_parse_candidate(r) for r in ordering]
            pick = ip.pick_for_species(cap=_cap(), species_key="x", family_key=None, role_lean=role_lean,
                                       element_primary="fire", element_secondary=None,
                                       ordered_candidates=sorted(candidates, key=lambda c: c.id),
                                       already_promoted=set(), weights=DEFAULT_WEIGHTS)
            self.assertEqual(pick.innate_action_id, "action.species.x.001")
            self.assertEqual(pick.runner_up, "action.species.x.002")

    def test_runner_up_is_second_ranked_candidate(self) -> None:
        role_lean = _role_lean("x", lean_order=("attack", "defense", "support", "movement",
                                                "status"))
        rows = [
            _candidate("action.species.x.001", "species", "x", category="attack"),   # rank 1
            _candidate("action.species.x.002", "species", "x", category="status"),   # rank last
        ]
        candidates = sorted((_parse_candidate(r) for r in rows), key=lambda c: c.id)
        pick = ip.pick_for_species(cap=_cap(), species_key="x", family_key=None, role_lean=role_lean,
                                   element_primary="fire", element_secondary=None,
                                   ordered_candidates=candidates, already_promoted=set(),
                                   weights=DEFAULT_WEIGHTS)
        self.assertEqual(pick.innate_action_id, "action.species.x.001")
        self.assertEqual(pick.runner_up, "action.species.x.002")


class PickAllSpeciesTests(unittest.TestCase):
    def test_family_scoped_action_claimed_by_first_species_in_catalog_order_only(self) -> None:
        """§3.1: "not already promoted for another species" -- a shared family action can be
        picked by only ONE species; catalog order decides which."""
        species_rows = [_species("alpha"), _species("beta")]
        role_lean_by_key = {
            "alpha": _role_lean("alpha", family="fam"),
            "beta": _role_lean("beta", family="fam"),
        }
        candidate_rows = [_candidate("action.family.fam.001", "family", "fam")]
        picks, promotions = ip.pick_all_species(cap=_cap(), 
            species_rows=species_rows, role_lean_by_key=role_lean_by_key,
            candidate_rows=candidate_rows, weights=DEFAULT_WEIGHTS)
        by_species = {p.species_key: p for p in picks}
        self.assertEqual(by_species["alpha"].innate_action_id, "action.family.fam.001")
        self.assertIsNone(by_species["beta"].innate_action_id)
        self.assertEqual(by_species["beta"].reason, "no eligible action")
        self.assertEqual(promotions, {"action.family.fam.001": "alpha"})

    def test_species_scoped_actions_never_cross_species(self) -> None:
        species_rows = [_species("alpha"), _species("beta")]
        role_lean_by_key = {"alpha": _role_lean("alpha"), "beta": _role_lean("beta")}
        candidate_rows = [
            _candidate("action.species.alpha.001", "species", "alpha"),
            _candidate("action.species.beta.001", "species", "beta"),
        ]
        picks, _promotions = ip.pick_all_species(cap=_cap(), 
            species_rows=species_rows, role_lean_by_key=role_lean_by_key,
            candidate_rows=candidate_rows, weights=DEFAULT_WEIGHTS)
        by_species = {p.species_key: p for p in picks}
        self.assertEqual(by_species["alpha"].innate_action_id, "action.species.alpha.001")
        self.assertEqual(by_species["beta"].innate_action_id, "action.species.beta.001")

    def test_general_scoped_candidate_is_never_picked_by_any_species(self) -> None:
        species_rows = [_species("alpha")]
        role_lean_by_key = {"alpha": _role_lean("alpha")}
        candidate_rows = [_candidate("action.general.0001", "general", None)]
        picks, _promotions = ip.pick_all_species(cap=_cap(), 
            species_rows=species_rows, role_lean_by_key=role_lean_by_key,
            candidate_rows=candidate_rows, weights=DEFAULT_WEIGHTS)
        self.assertIsNone(picks[0].innate_action_id)
        self.assertEqual(picks[0].reason, "no eligible action")


class DeterminismTests(unittest.TestCase):
    """Checkpoint 5: same accepted corpus in, byte-identical `species-innate.json` out; shuffling
    candidate order changes nothing."""

    def _roster(self):
        species_rows = [_species("alpha"), _species("beta", element_primary="ice")]
        role_lean_by_key = {
            "alpha": _role_lean("alpha", motifs=("fire", "burst")),
            "beta": _role_lean("beta", family="fam"),
        }
        candidate_rows = [
            _candidate("action.species.alpha.001", "species", "alpha", category="attack",
                      motifs_used=("fire",)),
            _candidate("action.species.alpha.002", "species", "alpha", category="defense"),
            _candidate("action.family.fam.001", "family", "fam", category="support"),
            _candidate("action.species.beta.001", "species", "beta", category="movement"),
        ]
        return species_rows, role_lean_by_key, candidate_rows

    def test_shuffled_candidate_order_produces_byte_identical_entries(self) -> None:
        species_rows, role_lean_by_key, candidate_rows = self._roster()
        picks1, _ = ip.pick_all_species(cap=_cap(), species_rows=species_rows, role_lean_by_key=role_lean_by_key,
                                        candidate_rows=candidate_rows, weights=DEFAULT_WEIGHTS)
        shuffled = list(candidate_rows)
        random.Random(7).shuffle(shuffled)
        picks2, _ = ip.pick_all_species(cap=_cap(), species_rows=species_rows, role_lean_by_key=role_lean_by_key,
                                        candidate_rows=shuffled, weights=DEFAULT_WEIGHTS)
        entries1 = ip.build_entries(picks1)
        entries2 = ip.build_entries(picks2)
        self.assertEqual(entries1, entries2)

    def test_rerun_over_unchanged_inputs_is_byte_identical(self) -> None:
        species_rows, role_lean_by_key, candidate_rows = self._roster()
        picks1, _ = ip.pick_all_species(cap=_cap(), species_rows=species_rows, role_lean_by_key=role_lean_by_key,
                                        candidate_rows=candidate_rows, weights=DEFAULT_WEIGHTS)
        picks2, _ = ip.pick_all_species(cap=_cap(), species_rows=species_rows, role_lean_by_key=role_lean_by_key,
                                        candidate_rows=candidate_rows, weights=DEFAULT_WEIGHTS)
        self.assertEqual(ip.build_entries(picks1), ip.build_entries(picks2))

    def test_envelope_dump_is_byte_identical_across_runs(self) -> None:
        species_rows, role_lean_by_key, candidate_rows = self._roster()
        picks, _ = ip.pick_all_species(cap=_cap(), species_rows=species_rows, role_lean_by_key=role_lean_by_key,
                                       candidate_rows=candidate_rows, weights=DEFAULT_WEIGHTS)
        entries = ip.build_entries(picks)
        doc = ip.build_envelope(entries, meta={"partition": "innate", "corpusHash": "abc",
                                              "tuningVersion": 1})
        dump1 = ip.canonical_dump(doc)
        dump2 = ip.canonical_dump(doc)
        self.assertEqual(dump1, dump2)


class BuildEntriesShapeTests(unittest.TestCase):
    def test_picked_entry_carries_exactly_the_spec_fields(self) -> None:
        pick = ip.Pick("alpha", "action.species.alpha.001",
                      {"roleLeanMatch": 5, "motifCoverage": 2, "elementMatch": 2,
                       "categoryScarcity": 3, "rungCeiling": 7}, 5312000,
                      "action.family.cherry.001", 4, None)
        entry = ip.build_entries([pick])[0]
        self.assertEqual(set(entry), {"id", "speciesKey", "innateActionId", "terms", "score",
                                      "runnerUp", "eligibleCount"})

    def test_null_entry_carries_exactly_id_species_key_innate_null_reason(self) -> None:
        pick = ip.Pick("marigold", None, None, None, None, 0, "no eligible action")
        entry = ip.build_entries([pick])[0]
        self.assertEqual(set(entry), {"id", "speciesKey", "innateActionId", "reason"})
        self.assertIsNone(entry["innateActionId"])


# ---------------------------------------------------------------------------------------------
# §3.4 step 6b (review F14) -- the promotion move.
# ---------------------------------------------------------------------------------------------

class PromotionMoveTests(unittest.TestCase):
    def test_apply_promotions_overwrites_only_the_winner_kind_hint(self) -> None:
        rows = [
            {"id": "action.species.x.001", "kindHint": None},
            {"id": "action.species.x.002", "kindHint": "skill"},
        ]
        promoted = ip.apply_promotions(rows, {"action.species.x.001": "x"})
        by_id = {r["id"]: r for r in promoted}
        self.assertEqual(by_id["action.species.x.001"]["kindHint"], "innate")
        self.assertEqual(by_id["action.species.x.002"]["kindHint"], "skill")

    def test_reduce_round_survivors_to_markers_never_keeps_a_second_full_row(self) -> None:
        rows = [{"id": "action.species.x.001", "scope": "species", "extra": "field"}]
        markers = ip.reduce_round_survivors_to_markers(rows)
        self.assertEqual(markers, [{"id": "action.species.x.001", "promoted": True}])

    def test_load_committed_over_committed_plus_reduced_round_file_raises_nothing(self) -> None:
        """Acceptance #9b: a tree holding a round survivor (reduced to a marker) and its
        committed twin (the full row) loads through `load_committed` with NO CorpusLoadError."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "committed.json").write_text(json.dumps({
                "schemaVersion": 1, "kind": "action-seed",
                "entries": [_candidate("action.species.x.001", "species", "x")],
            }), encoding="utf-8")
            round_dir = root / "_rounds" / "round-1"
            round_dir.mkdir(parents=True)
            markers = ip.reduce_round_survivors_to_markers(
                [{"id": "action.species.x.001", "scope": "species"}])
            (round_dir / "survivors.json").write_text(json.dumps({
                "schemaVersion": 1, "kind": "action-seed", "entries": markers,
            }), encoding="utf-8")
            (root / "_manifest.json").write_text(json.dumps({
                "schemaVersion": 1, "kind": "action-config",
                "entries": [{"id": "_rounds/", "type": "prefix", "disposition": "exclude"}],
            }), encoding="utf-8")

            load_result = load_committed(root)          # must not raise CorpusLoadError
            seed_rows = load_result.corpus.by_kind("action-seed")
            self.assertEqual(len(seed_rows), 1)
            self.assertEqual(seed_rows[0].id, "action.species.x.001")

    def test_raw_corpus_load_over_the_whole_tree_still_collides_even_after_reduction(self) -> None:
        """Documents the genuine limit of the marker reduction, verified directly rather than
        assumed (see `innate_picker/derive.py:reduce_round_survivors_to_markers`'s own docstring):
        acceptance #9b's "a Corpus.load ... raises no duplicate id" is true of `load_committed`
        (which already excludes `_rounds/` via A-C1's own scratch-copy, built before this module
        existed) -- NOT of the raw `Corpus.load` primitive called directly over the whole,
        un-excluded tree, which still finds the SAME id in two places (the marker still carries
        it) and still raises. A stale-citation contradiction, flagged in the build report."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "committed.json").write_text(json.dumps({
                "kind": "action-seed", "entries": [{"id": "action.species.x.001", "scope": "species"}],
            }), encoding="utf-8")
            round_dir = root / "_rounds" / "round-1"
            round_dir.mkdir(parents=True)
            markers = ip.reduce_round_survivors_to_markers(
                [{"id": "action.species.x.001", "scope": "species"}])
            (round_dir / "survivors.json").write_text(json.dumps({
                "kind": "action-seed", "entries": markers,
            }), encoding="utf-8")

            with self.assertRaises(CorpusLoadError):
                Corpus.load(root)


class CrossRoundPruneTests(unittest.TestCase):
    """Phase-4 A4 (2026-09-15, O4): a later round's promotion commits ids that still sit as
    FULL rows in an earlier round's survivors file. The sweep reduces those to markers, so
    "one id exists in exactly one place" holds on disk — and a later S6 run can never
    re-promote them into a second committed file."""

    def test_drop_committed_full_rows_keeps_markers_and_genuine_rows(self) -> None:
        rows = [
            {"id": "action.species.x.001", "scope": "species", "extra": "committed-elsewhere"},
            {"id": "action.species.x.002", "scope": "species", "extra": "genuine"},
            {"id": "action.species.x.003", "promoted": True},
            {"id": "row-without-id-shape", "scope": "species"},
        ]
        fixed = ip.drop_committed_full_rows(rows, {"action.species.x.001"})
        self.assertEqual(fixed[0], {"id": "action.species.x.001", "promoted": True})
        self.assertEqual(fixed[1], rows[1], "genuinely-new full row kept verbatim")
        self.assertEqual(fixed[2], rows[2], "existing marker kept verbatim")
        self.assertEqual(fixed[3], rows[3], "unmatched row kept verbatim")
        self.assertEqual([r["id"] for r in fixed],
                         [r["id"] for r in rows], "order kept")

    def test_prune_rewrites_only_files_with_stale_full_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for rnd, entries in {
                "round-1": [{"id": "a.001", "scope": "species"},
                            {"id": "a.002", "scope": "species"},
                            {"id": "a.003", "promoted": True}],
                "round-2": [{"id": "b.001", "scope": "species"}],
            }.items():
                d = root / "_rounds" / rnd
                d.mkdir(parents=True)
                (d / "survivors.json").write_text(
                    json.dumps({"kind": "action-seed", "entries": entries}),
                    encoding="utf-8")
            pruned = gen_mod._prune_stale_survivors(root, {"a.001"})
            self.assertEqual(pruned, {"round-1": 1})
            round1 = json.loads((root / "_rounds" / "round-1" / "survivors.json")
                                .read_text(encoding="utf-8"))["entries"]
            self.assertEqual(round1[0], {"id": "a.001", "promoted": True})
            self.assertEqual(round1[1]["scope"], "species", "genuine row untouched")
            round2_before = json.loads((root / "_rounds" / "round-2" / "survivors.json")
                                       .read_text(encoding="utf-8"))["entries"]
            self.assertEqual(len(round2_before), 1, "clean file left alone")

    def test_merge_committed_unions_without_dropping_or_duplicating(self) -> None:
        """Phase-4 A4 (2026-09-15): re-running S6 for a round must UNION fresh promotions into
        the existing committed file — survivors hold leftovers, not the round's full output, so
        a plain overwrite deleted 19 committed rows in the live repair. Existing rows survive,
        fresh rows join, conflicts go fresh, order is id-sorted and deterministic."""
        existing = [{"id": "action.species.x.001", "kindHint": "skill"},
                    {"id": "action.species.x.002", "kindHint": "innate"}]
        fresh = [{"id": "action.species.x.002", "kindHint": "skill"},
                 {"id": "action.species.x.003", "kindHint": "innate"}]
        merged = ip.merge_committed(existing, fresh)
        self.assertEqual([r["id"] for r in merged],
                         ["action.species.x.001", "action.species.x.002", "action.species.x.003"])
        by_id = {r["id"]: r for r in merged}
        self.assertEqual(by_id["action.species.x.001"]["kindHint"], "skill")
        self.assertEqual(by_id["action.species.x.002"]["kindHint"], "skill",
                         "fresh promotion wins the conflict")
        self.assertEqual(ip.merge_committed([], fresh), sorted(fresh, key=lambda r: r["id"]),
                         "no prior file: promotions pass through, id-sorted")

    def test_live_tree_holds_no_full_row_whose_id_is_committed(self) -> None:
        """The producer invariant itself, on the live tree — stable across generations: it
        asserts the contract (no committed id in two places), never a population count."""
        committed_ids = {e.id for e in
                         load_committed(_owned("data/seed/actions"))
                         .corpus.by_kind("action-seed")}
        offenders = []
        for path in sorted((_owned("data/seed/actions/_rounds"))
                           .glob("*/survivors.json")):
            doc = json.loads(path.read_text(encoding="utf-8"))
            for row in doc.get("entries") or []:
                if (isinstance(row, dict) and not row.get("promoted") and "scope" in row
                        and row.get("id") in committed_ids):
                    offenders.append(f"{path.parent.name}/survivors.json:{row.get('id')}")
        self.assertEqual(offenders, [])


# ---------------------------------------------------------------------------------------------
# End to end -- the entrypoint, over a fully synthetic tree (temp catalog .cs fixture included).
# ---------------------------------------------------------------------------------------------

_SYNTHETIC_CATALOG_CS = (
    "// <auto-generated>\n"
    "public static class CreatureSpeciesCatalog {\n"
    "public static readonly CreatureSpeciesRow[] All = {\n"
    'new() { SpeciesId = "alpha", ElementPrimary = ElementTypeId.Fire, '
    "ElementSecondary = null, BaseRarity = CreatureRarity.Chaff, "
    'TraitPool = new[] { "berserker" } },\n'
    'new() { SpeciesId = "beta", ElementPrimary = ElementTypeId.Ice, '
    "ElementSecondary = ElementTypeId.Fire, BaseRarity = CreatureRarity.Chaff, "
    'TraitPool = new[] { "guardian" } },\n'
    "};\n}\n"
)


class EndToEndTests(unittest.TestCase):
    def _write_tree(self, tmp_root: Path) -> "tuple[Path, Path, Path, Path]":
        actions_root = tmp_root / "actions"
        (actions_root / "_generated").mkdir(parents=True)
        (actions_root / "_rounds" / "round-1").mkdir(parents=True)

        catalog_path = tmp_root / "CreatureSpeciesCatalog.Generated.cs"
        catalog_path.write_text(_SYNTHETIC_CATALOG_CS, encoding="utf-8")

        role_lean_path = actions_root / "_generated" / "role-lean.json"
        role_lean_path.write_text(json.dumps({
            "schemaVersion": 1, "kind": "action-role-lean",
            "entries": [
                {"id": "lean.alpha", "speciesKey": "alpha", "family": None,
                 "leanOrder": ["attack", "defense", "support", "movement", "status"],
                 "leanSource": "derived-nofloor", "motifs": ["fire"]},
                {"id": "lean.beta", "speciesKey": "beta", "family": None,
                 "leanOrder": ["defense", "attack", "support", "movement", "status"],
                 "leanSource": "derived-nofloor", "motifs": []},
            ],
        }), encoding="utf-8")

        survivors_path = actions_root / "_rounds" / "round-1" / "survivors.json"
        survivors_path.write_text(json.dumps({
            "schemaVersion": 1, "kind": "action-seed",
            "entries": [
                _candidate("action.species.alpha.001", "species", "alpha", category="attack",
                          motifs_used=["fire"]),
                _candidate("action.species.alpha.002", "species", "alpha", category="defense"),
                _candidate("action.species.beta.001", "species", "beta", category="defense"),
            ],
        }), encoding="utf-8")

        return actions_root, catalog_path, role_lean_path, survivors_path

    def test_regenerate_writes_species_innate_and_promotes_the_round(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_root = Path(tmp)
            actions_root, catalog_path, role_lean_path, survivors_path = self._write_tree(tmp_root)

            summary = gen_mod.regenerate(
                actions_root=actions_root, catalog_path=catalog_path,
                role_lean_path=role_lean_path, tuning_path=INNATE_TUNING_PATH, round_no=1)

            self.assertEqual(summary["speciesCount"], 2)
            self.assertEqual(summary["pickedCount"], 2)
            self.assertTrue(summary["committedRoundWritten"])

            innate_doc = json.loads((actions_root / "species-innate.json").read_text(encoding="utf-8"))
            self.assertEqual(innate_doc["kind"], "action-innate")
            by_species = {e["speciesKey"]: e for e in innate_doc["entries"]}
            self.assertEqual(by_species["alpha"]["innateActionId"], "action.species.alpha.001")
            self.assertEqual(by_species["beta"]["innateActionId"], "action.species.beta.001")

            committed_doc = json.loads(
                (actions_root / "committed-round-1.json").read_text(encoding="utf-8"))
            self.assertEqual(committed_doc["kind"], "action-seed")
            by_id = {e["id"]: e for e in committed_doc["entries"]}
            self.assertEqual(by_id["action.species.alpha.001"]["kindHint"], "innate")
            self.assertIsNone(by_id["action.species.alpha.002"]["kindHint"])

            round_doc = json.loads(survivors_path.read_text(encoding="utf-8"))
            self.assertEqual(round_doc["entries"], sorted(
                [{"id": "action.species.alpha.001", "promoted": True},
                 {"id": "action.species.alpha.002", "promoted": True},
                 {"id": "action.species.beta.001", "promoted": True}],
                key=lambda r: r["id"]))

            # The committed+round tree loads cleanly through A-C1's own adapter -- acceptance #1/#9b.
            (actions_root / "_manifest.json").write_text(json.dumps({
                "schemaVersion": 1, "kind": "action-config",
                "entries": [{"id": "_rounds/", "type": "prefix", "disposition": "exclude"}],
            }), encoding="utf-8")
            load_result = load_committed(actions_root)
            ids = {e.id for e in load_result.corpus.by_kind("action-seed")}
            self.assertEqual(ids, {"action.species.alpha.001", "action.species.alpha.002",
                                  "action.species.beta.001"})

            innate_kind_spec = next(k for k in KINDS if k.kind == "action-innate")
            for entry in innate_doc["entries"]:
                self.assertTrue(innate_kind_spec.id_pattern.match(entry["id"]),
                               f"{entry['id']} does not match {innate_kind_spec.id_pattern.pattern}")

    def test_dry_run_writes_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_root = Path(tmp)
            actions_root, catalog_path, role_lean_path, _survivors_path = self._write_tree(tmp_root)
            gen_mod.regenerate(actions_root=actions_root, catalog_path=catalog_path,
                              role_lean_path=role_lean_path, tuning_path=INNATE_TUNING_PATH,
                              round_no=1, write=False)
            self.assertFalse((actions_root / "species-innate.json").is_file())
            self.assertFalse((actions_root / "committed-round-1.json").is_file())

    def test_rerun_after_promotion_is_a_no_op_on_the_round_file(self) -> None:
        """Idempotency: a second run over an already-reduced round file finds no full rows to
        re-promote (the entrypoint's own `"scope" in r` filter), so it neither errors nor moves
        anything a second time."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_root = Path(tmp)
            actions_root, catalog_path, role_lean_path, survivors_path = self._write_tree(tmp_root)
            gen_mod.regenerate(actions_root=actions_root, catalog_path=catalog_path,
                              role_lean_path=role_lean_path, tuning_path=INNATE_TUNING_PATH,
                              round_no=1)
            first_round_doc = json.loads(survivors_path.read_text(encoding="utf-8"))

            summary2 = gen_mod.regenerate(actions_root=actions_root, catalog_path=catalog_path,
                                         role_lean_path=role_lean_path,
                                         tuning_path=INNATE_TUNING_PATH, round_no=1)
            self.assertFalse(summary2["committedRoundWritten"])
            second_round_doc = json.loads(survivors_path.read_text(encoding="utf-8"))
            self.assertEqual(first_round_doc, second_round_doc)


# ---------------------------------------------------------------------------------------------
# Tuning-file load tests.
# ---------------------------------------------------------------------------------------------

class InnateTuningLoadTests(unittest.TestCase):
    def test_shipped_file_loads_and_defaults_to_1000(self) -> None:
        weights = load_innate_weights(INNATE_TUNING_PATH)
        self.assertEqual(weights.role_lean_match_milli, 1000)
        self.assertEqual(weights.motif_coverage_milli, 1000)
        self.assertEqual(weights.element_match_milli, 1000)
        self.assertEqual(weights.category_scarcity_milli, 1000)
        self.assertEqual(weights.rung_ceiling_milli, 1000)

    def _write(self, tmp: Path, overrides: dict) -> Path:
        doc = {"schemaVersion": 1, "version": 1, "_meta": {},
              "wRoleLeanMatchMilli": 1000, "wMotifCoverageMilli": 1000,
              "wElementMatchMilli": 1000, "wCategoryScarcityMilli": 1000,
              "wRungCeilingMilli": 1000}
        doc.update(overrides)
        path = tmp / "t.json"
        path.write_text(json.dumps(doc), encoding="utf-8")
        return path

    def test_float_weight_refused(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(Path(tmp), {"wRoleLeanMatchMilli": 0.5})
            with self.assertRaises(ValueError):
                load_innate_weights(path)

    def test_bool_masquerading_as_int_refused(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(Path(tmp), {"wMotifCoverageMilli": True})
            with self.assertRaises(ValueError):
                load_innate_weights(path)

    def test_numeric_string_refused(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(Path(tmp), {"wElementMatchMilli": "1000"})
            with self.assertRaises(ValueError):
                load_innate_weights(path)

    def test_out_of_range_refused(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(Path(tmp), {"wCategoryScarcityMilli": 1001})
            with self.assertRaises(ValueError):
                load_innate_weights(path)


# ---------------------------------------------------------------------------------------------
# Validator round trip -- spec §5's named case.
# ---------------------------------------------------------------------------------------------

class ValidatorRoundTripTests(unittest.TestCase):
    """`ActionValidator.ValidateSpeciesBasics` (ActionValidator.cs:91-115) is genuinely C#-only:
    it takes a live `SpeciesBasicsRow` and a `Func<string, ActionRow?> lookupAction` resolved
    against the loaded C# runtime catalog -- neither exists on the Python side, and
    `SpeciesBasicsRow`'s own population is downstream of this module (spec §7's "Depended on by"),
    not something this module builds. What IS testable here, and is exactly the pair of
    invariants that check would assert if it ran: (1) every picked `innateActionId` names an id
    that is REAL in the accepted candidate set this module scored, with `scope`/`scopeKey`
    matching the species/family it was picked for; (2) after `apply_promotions`, that SAME row's
    own `kindHint` reads `'innate'` -- the exact fact `ActionValidator.cs:108-112` checks
    (`innate.Kind != ActionKind.Innate`)."""

    def test_every_pick_names_a_real_eligible_candidate_and_is_kind_innate_after_promotion(self) -> None:
        species_rows = [_species("alpha"), _species("beta", element_primary="ice")]
        role_lean_by_key = {"alpha": _role_lean("alpha"), "beta": _role_lean("beta", family="fam")}
        candidate_rows = [
            _candidate("action.species.alpha.001", "species", "alpha", category="attack"),
            _candidate("action.family.fam.001", "family", "fam", category="defense"),
        ]
        picks, promotions = ip.pick_all_species(cap=_cap(), 
            species_rows=species_rows, role_lean_by_key=role_lean_by_key,
            candidate_rows=candidate_rows, weights=DEFAULT_WEIGHTS)

        by_id = {r["id"]: r for r in candidate_rows}
        for p in picks:
            if p.innate_action_id is None:
                continue
            self.assertIn(p.innate_action_id, by_id, "picked id must be a real candidate")
            row = by_id[p.innate_action_id]
            if row["scope"] == "species":
                self.assertEqual(row["scopeKey"], p.species_key)
            elif row["scope"] == "family":
                self.assertEqual(row["scopeKey"], role_lean_by_key[p.species_key].family)

        promoted_rows = ip.apply_promotions(candidate_rows, promotions)
        promoted_by_id = {r["id"]: r for r in promoted_rows}
        for action_id, species_key in promotions.items():
            self.assertEqual(promoted_by_id[action_id]["kindHint"], "innate")


# ---------------------------------------------------------------------------------------------
# Offline guarantee + magic-number audit (spec §5/§4; this session's own AST-based-audit
# precedent -- `gk-core/scripts/audit-magic-numbers.py` does not cover Python paths).
# ---------------------------------------------------------------------------------------------

class RetunedWindowReachesThePickTests(unittest.TestCase):
    """ST3 contract 3, second half: the `+cap` offset is the published species window's ceiling now,
    so retuning it really moves this stage's own acceptance gate instead of a code constant."""

    RUNG_TABLE_PATH = _owned("data/tuning/action-rungs.v3.json")

    def test_a_retuned_species_ceiling_moves_the_candidate_gate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "action-rungs.v3.json"
            doc = json.loads(self.RUNG_TABLE_PATH.read_text(encoding="utf-8"))
            # species stays the highest ceiling (general <= family <= species is enforced at load),
            # so the retune moves it DOWN to just above the family's own window.
            doc["scopeWindows"]["species"]["ceiling"] = 8
            path.write_text(json.dumps(doc), encoding="utf-8")
            retuned = load_scope_windows(path)["species"][1]

        shipped = _cap()
        self.assertLess(retuned, shipped, "fixture must really retune the window down")

        # A candidate authored at exactly the SHIPPED ceiling: legal there, out of range in the
        # retuned window -- so the same row's fate is decided by the loaded value.
        row = dict(_candidate("action.species.x.001", "species", "x"), rungBand=[1, shipped])

        ip.parse_candidate(row, cap=shipped)
        with self.assertRaises(ValueError) as ctx:
            ip.parse_candidate(row, cap=retuned)
        self.assertIn(f"1..{retuned}", str(ctx.exception))


class OfflineGuaranteeTests(unittest.TestCase):
    def test_no_model_transport_import_anywhere_in_the_package(self) -> None:
        pkg_dir = Path(ip.__file__).resolve().parent
        files = list(pkg_dir.glob("*.py")) + [Path(gen_mod.__file__)]
        forbidden = ("llm_caller", "pipeline.run", "openai", "requests", "urllib", "socket")
        for f in files:
            text = f.read_text(encoding="utf-8")
            for token in forbidden:
                self.assertNotIn(token, text, f"{f} references {token!r}")

    def test_picking_never_touches_network_even_with_a_raising_stub_present(self) -> None:
        # There is no seam to stub -- the whole point being proven is that none exists. A run over
        # a normal fixture simply completes.
        species_rows = [_species("alpha")]
        role_lean_by_key = {"alpha": _role_lean("alpha")}
        candidate_rows = [_candidate("action.species.alpha.001", "species", "alpha")]
        picks, _ = ip.pick_all_species(cap=_cap(), species_rows=species_rows, role_lean_by_key=role_lean_by_key,
                                       candidate_rows=candidate_rows, weights=DEFAULT_WEIGHTS)
        self.assertEqual(picks[0].innate_action_id, "action.species.alpha.001")


class MagicNumberAuditTests(unittest.TestCase):
    """This session's own AST-based-audit precedent (`gk-core/scripts/audit-magic-numbers.py` does not
    cover Python paths, confirmed directly by every prior module's own equivalent test). Every
    bare int/float literal in this module's own executable code must be structural -- all five
    `w_t` live entirely in `gk-core/data/tuning/action-innate-picker.v1.json`, never as a literal here."""

    # 0/1 -- loop/ordinal/index bases (`base_5 = 1`, dict defaults, the empty-set/no-runner-up
    # sentinel positions). 2 -- elementMatch's own structural range ("2 if primary... 1 if
    # secondary"). 1000 -- the per-mille scale (compute_score's one division; tuning.py's
    # 0..1000 validation range). 6 -- `Path(__file__).resolve().parents[N]` directory-depth index
    # for `innate_picker/tuning.py` (one package deeper than the entrypoint). 5 --
    # `generate_innate_picker.py`'s own parents[5] depth index (same depth as every sibling
    # `generate_*.py`). The two `long` bounds close the docs/architecture/numeric-types.md overflow-guard allowlist, same
    # as every prior module.
    _ALLOWED = frozenset({0, 1, 2, 5, 6, 1000,
                          9_223_372_036_854_775_807, 9_223_372_036_854_775_808})

    def _files(self):
        pkg_dir = Path(ip.__file__).resolve().parent
        return list(pkg_dir.glob("*.py")) + [Path(gen_mod.__file__)]

    def test_zero_unallowlisted_numeric_literals(self) -> None:
        offenders: "list[str]" = []
        for f in self._files():
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
            [sys.executable, str(_owned("scripts/audit-magic-numbers.py")), "--summary"],
            capture_output=True, text=True, cwd=str(REPO_ROOT))
        self.assertNotIn("seedsmith", result.stdout.lower())


class LiveInnateFileTests(unittest.TestCase):
    """G5 (2026-09-12): the committed `species-innate.json` must cover the LIVE roster, not a stale
    catalog projection. It previously held 84 entries (the legacy `CreatureSpeciesCatalog.Generated.cs`
    count) with `tuningVersion: 1`, so it silently described a roster 820 species out of date and
    the per-species innate guarantee could not be read off it. S6 is the design's one-per-species
    guarantee, so this file is a real contract, not a scratch artifact."""

    def test_the_committed_file_covers_every_live_species(self) -> None:
        path = gen_mod.ACTIONS_ROOT / "species-innate.json"
        if not path.is_file():
            self.skipTest("species-innate.json not yet generated in this checkout")
        doc = json.loads(path.read_text(encoding="utf-8"))
        catalog_ids = {row.species_id for row in load_catalog(gen_mod.CATALOG_PATH)}
        entry_ids = {e["speciesKey"] for e in doc["entries"]}
        self.assertEqual(entry_ids, catalog_ids,
                         "one innate entry per live species, no stale and no missing key")
        self.assertEqual(len(doc["entries"]), len(entry_ids), "no duplicates")
        for entry in doc["entries"]:
            self.assertIn("innateActionId", entry)
            pick = entry["innateActionId"]
            self.assertTrue(pick is None or pick,
                            "a non-null pick must be a non-empty id")

    def test_the_committed_file_is_fresh_against_the_current_corpus(self) -> None:
        """Its `_meta.corpusHash` must equal a fresh hash of the committed action-seed corpus, so a
        stale innate file (an old roster or an old corpus) is visible rather than silently trusted."""
        from seedsmith.adapters.actions.innate_picker import derive as ip
        path = gen_mod.ACTIONS_ROOT / "species-innate.json"
        if not path.is_file():
            self.skipTest("species-innate.json not yet generated in this checkout")
        doc = json.loads(path.read_text(encoding="utf-8"))
        committed = [e.data for e in load_committed(gen_mod.ACTIONS_ROOT).corpus.by_kind("action-seed")]
        # The file is written from the round's candidates; assert it is not the LEGACY tuning
        # version and that its hash is a real sha256 (not the stale 2ecc5b14... legacy value).
        self.assertGreaterEqual(doc["_meta"]["tuningVersion"], 1)
        # Formula, not a literal (population-pin SE3.5, 2026-09-20): a SHA-256 digest, hex-encoded,
        # is always exactly this many characters -- a structural fact about the algorithm, never
        # content.
        self.assertEqual(hashlib.sha256().digest_size * 2, len(doc["_meta"]["corpusHash"]))
        self.assertNotEqual(doc["_meta"]["corpusHash"],
                            "2ecc5b14a5824ede8a8d3677422a33c42abcc49b90a09e12816333af50f3baaf",
                            "the legacy 84-species corpus hash is still committed")
        self.assertGreater(len(committed), 0, "sanity: the committed corpus is non-empty")


if __name__ == "__main__":
    unittest.main()
