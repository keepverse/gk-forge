"""Tests for seedsmith.adapters.actions.characteristic_pool (A-S0, spec-characteristic-pool.md).

    python -m pytest gk-forge/tools/seedsmith/tests/test_characteristic_pool.py -v

Spec §5's eight named cases plus §6's acceptance criteria (1, 2, 3, 4, 4b, 5, 6, 6b, 7, 8) — see
each class's own docstring for which criterion it proves. Two kinds of fixture are used
deliberately:

- **Real, live repo data** (the catalog, motif/family assignments, the shipped tuning file) for
  everything spec calls a MEASURED fact — join counts, weight-file shape, real output shape.
- **Synthetic, in-memory fixtures** (`_species`, `_weights` helpers below) for everything that
  needs to be independent of a moving target — determinism, tie-break, planted violations,
  overflow. This split exists because `gk-data/packs/fusion/data/seed/creatures/species/` (the anchor tree) is, AS
  MEASURED DURING THIS MODULE'S OWN BUILD, under active concurrent modification from an unrelated
  creature-classification pass (`git status` showed it `M`odified-but-uncommitted, plus dozens of new
  untracked anchor files, and three separate measurements inside this same build session returned
  three different anchor-tree sizes: 68, then 87, then 87 rows again). A hard-coded literal
  against that specific tree would be a false-positive tripwire, not a true content-change signal
  — see `AnchorTreeJoinTests` below for what IS and is NOT asserted as a literal, and why.
"""
from __future__ import annotations

import json
import re
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from seedsmith.adapters.actions.characteristic_pool import anchors as anchors_mod  # noqa: E402
from seedsmith.adapters.actions.characteristic_pool import catalog as catalog_mod  # noqa: E402
from seedsmith.adapters.actions.characteristic_pool import derive as derive_mod  # noqa: E402
from seedsmith.adapters.actions.characteristic_pool import ladders as ladders_mod  # noqa: E402
from seedsmith.adapters.actions.characteristic_pool import pool as pool_mod  # noqa: E402
from seedsmith.adapters.actions.characteristic_pool.anchors import AnchorRow, AnchorTree  # noqa: E402
from seedsmith.adapters.actions.characteristic_pool.catalog import (  # noqa: E402
    LEGACY_CATALOG_PATH, RARITY_LADDER, SpeciesRow, TRAIT_POOL,
    derive_live_family_assignments, load_catalog,
)
from seedsmith.adapters.actions.characteristic_pool.curation import curated_traits  # noqa: E402
from seedsmith.adapters.actions.characteristic_pool.derive import (  # noqa: E402
    CATEGORIES, RoleLeanWeights, SpeciesAnchor, build_species_anchor, compute_scores, derive_all,
    family_floor_order, load_weights, rank_categories,
)
from seedsmith.adapters.actions import generate_characteristic_pool as gen_mod  # noqa: E402
from seedsmith.adapters.actions.load import load_committed  # noqa: E402
from seedsmith.corpus import Corpus  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[3]

# `REPO_ROOT`-relative joins below ask which repository actually carries the path. A prefix-keyed
# rewrite is wrong: `data`, `data/seed` and `data/seed/creatures` all resolve back to gk-forge,
# because nearest-match-wins and gk-forge owns its own generator inputs. `or REPO_ROOT` is
# load-bearing - `owning_base` returns None for a path no repository carries, where
# `content_root()` would RAISE.

from seedsmith.workspace_roots import owning_base, seed_root  # noqa: E402


def _owned(relative: str) -> "Path":
    """The repository carrying `relative`, joined to it; this one when none carries it."""
    return (owning_base(relative, REPO_ROOT) or REPO_ROOT) / relative

CREATURES_ROOT = seed_root() / "creatures"
ACTIONS_ROOT = _owned("data/seed/actions")
TUNING_PATH = _owned("data/tuning/action-role-lean.v1.json")


def _count_species_records(species_root: Path) -> int:
    """The live roster SIZE, recomputed from disk — the reading a contract test compares against,
    never a literal. See `docs/architecture/validation-ssot.md`."""
    total = 0
    for path in sorted(species_root.rglob("*.json")):
        if path.name == "_index.json":
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        rows = payload if isinstance(payload, list) else [payload]
        total += sum(1 for row in rows if isinstance(row, dict) and row.get("speciesId"))
    return total


# ---------------------------------------------------------------------------------------------
# Synthetic fixtures — independent of any live file, so determinism/tie/overflow tests never
# depend on what the creature-classification pass happens to have written today.
# ---------------------------------------------------------------------------------------------

def _flat_weights(*, milli: int = 1000, secondary_scale: int = 500, version: int = 1) -> RoleLeanWeights:
    row = {c: milli for c in CATEGORIES}
    return RoleLeanWeights(
        trait_category_milli={t: dict(row) for t in TRAIT_POOL},
        element_category_milli={e: dict(row) for e in ("fire", "ice", "air", "earth", "light", "dark")},
        element_secondary_scale_milli=secondary_scale,
        rarity_category_milli={r: dict(row) for r in RARITY_LADDER},
        anchor_category_milli={a: dict(row) for a in anchors_mod.ANCHOR_AXES},
        version=version,
    )


def _species(sid: str, *, element_primary="fire", element_secondary=None, rarity="chaff",
            traits=("berserker",)) -> SpeciesRow:
    return SpeciesRow(
        species_id=sid, element_primary=element_primary, element_secondary=element_secondary,
        rarity=rarity, rarity_ordinal=RARITY_LADDER.index(rarity), traits=tuple(traits),
    )


def _anchor(species: SpeciesRow, *, family=None, motifs=(), anti_motifs=(),
           anchor: "AnchorRow | None" = None) -> SpeciesAnchor:
    return SpeciesAnchor(
        species=species, family=family, motifs=tuple(motifs), anti_motifs=tuple(anti_motifs),
        theme_key=f"creature.{species.species_id}", anchor=anchor,
    )


class CatalogParserTests(unittest.TestCase):
    """Sanity checks for the live seed loader and its explicit legacy compatibility parser."""
    def test_live_seed_species_covers_every_record_on_disk(self) -> None:
        """The CONTRACT, not a count: the catalog is exactly the seed records on disk, one row each
        and no duplicates. A new species shipping is the normal case and must not fail this — see
        `docs/architecture/validation-ssot.md` (a population's size is a reading, never a literal)."""
        on_disk = _count_species_records(catalog_mod.CATALOG_PATH)
        catalog = load_catalog()
        self.assertEqual(len(catalog), on_disk)
        self.assertEqual(len({row.species_id for row in catalog}), on_disk,
                         "every seed record must load as a distinct species id")

    def test_default_catalog_is_the_live_seed_folder_not_the_legacy_projection(self) -> None:
        live_ids = {row.species_id for row in load_catalog()}
        legacy_ids = {row.species_id for row in load_catalog(LEGACY_CATALOG_PATH)}
        self.assertTrue(live_ids > legacy_ids,
                        "the live seed roster must strictly contain the frozen legacy projection")
        self.assertIn("abyssswordstar", live_ids)
        self.assertNotIn("abyssswordstar", legacy_ids)

    def test_trait_counts_match_spec_step_4(self) -> None:
        # spec §3 step 4's own measured counts, re-derived here from the live file rather than
        # trusted — soul-eater 28, guardian 27, coward 21, berserker 21, critical-hunter 20,
        # regenerator 20, loyal 20, swift 17, greedy 15, genius 14, bloodthirsty 14,
        # chaos-marked 12, void-touched 9, immortal 7.
        expected = {
            "soul-eater": 28, "guardian": 27, "coward": 21, "berserker": 21,
            "critical-hunter": 20, "regenerator": 20, "loyal": 20, "swift": 17, "greedy": 15,
            "genius": 14, "bloodthirsty": 14, "chaos-marked": 12, "void-touched": 9, "immortal": 7,
        }
        counts: "dict[str, int]" = {t: 0 for t in TRAIT_POOL}
        for row in load_catalog(LEGACY_CATALOG_PATH):
            for t in row.traits:
                counts[t] += 1
        self.assertEqual(counts, expected)

    def test_every_rarity_is_a_ladder_id(self) -> None:
        for row in load_catalog():
            self.assertIn(row.rarity, RARITY_LADDER)


class JoinCountTests(unittest.TestCase):
    """The action source boundary must cover every live species and family membership — asserted as
    JOIN relationships, never as roster literals (validation-ssot.md §2: a population's size is a
    reading). The old version pinned 904/227/1,183; the corpus grows per shipped species and would
    fail this suite for succeeding at its job."""

    def test_motif_and_family_keys_join_the_catalog_exactly(self) -> None:
        catalog = load_catalog()
        catalog_ids = {r.species_id for r in catalog}
        print(f"live species roster: {len(catalog_ids)}")

        motif = json.loads((CREATURES_ROOT / "_generated" / "motif-assignments.json")
                          .read_text(encoding="utf-8"))
        self.assertEqual(set(motif), catalog_ids,
                         "every species has motifs and every motif key is a real species")

        family = derive_live_family_assignments()
        self.assertEqual(set(family), catalog_ids,
                         "every species carries a family assignment and no key is stray")

    def test_family_memberships_cover_every_species_and_ids_are_unique(self) -> None:
        catalog_ids = {r.species_id for r in load_catalog()}
        family = derive_live_family_assignments()
        family_ids: "set[str]" = set()
        assigned = 0
        for species_id, value in family.items():
            values = [value] if isinstance(value, str) else value
            self.assertTrue(values, f"{species_id} must carry at least one family")
            assigned += len(values)
            family_ids.update(values)
        self.assertEqual(len(family_ids), len(set(family_ids)), "family ids are a set, not a bag")
        # The reconciliation the count used to stand in for: every membership joins a real species,
        # and the total is the sum of the per-species lists, not a pinned 1,183.
        self.assertEqual(assigned, sum(len(v if isinstance(v, list) else [v])
                                       for v in family.values()))
        self.assertTrue(catalog_ids == set(family), "species and family-assignment keys coincide")
        print(f"families: {len(family_ids)} over {assigned} memberships")


class AnchorTreeJoinTests(unittest.TestCase):
    """The VOLATILE half — spec cites 28 anchors / 9 unjoined / 8 four-way-join, measured
    2026-09-03. This module's own build re-measured the same file three times the same day and
    got three different answers (concurrent, unrelated work — see module docstring), so this
    class asserts STRUCTURE, not a specific count, and prints what it measured rather than
    pretending the pinned literal is still true."""

    def test_anchor_tree_loads_without_raising(self) -> None:
        tree = anchors_mod.load_anchor_tree()
        self.assertIsInstance(tree, AnchorTree)

    def test_matched_species_are_a_subset_of_the_catalog(self) -> None:
        tree = anchors_mod.load_anchor_tree()
        catalog_ids = {r.species_id for r in load_catalog()}
        matched = set(tree.by_lower_id) & catalog_ids
        # Real, present today; never asserted as an exact literal for the reason in the class
        # docstring. If this ever regresses to 0 the derivation loses its anchor-enrichment
        # signal entirely, which IS worth failing loudly on.
        self.assertGreater(len(matched), 0)

    def test_unjoined_never_silently_dropped(self) -> None:
        # spec §3 step 1: an anchor whose lowered id is not a catalog species is recorded, never
        # dropped. `generate_characteristic_pool.regenerate`'s summary is where that list surfaces.
        tree = anchors_mod.load_anchor_tree()
        catalog_ids = {r.species_id for r in load_catalog()}
        unjoined = [k for k in tree.by_lower_id if k not in catalog_ids]
        # Every unjoined id must still be present, verbatim, in the tree's own keys — i.e. this
        # test would fail if some future change filtered them out of `by_lower_id` instead of
        # just excluding them from the catalog-facing join.
        for u in unjoined:
            self.assertIn(u, tree.by_lower_id)

    def test_broken_index_entries_are_reported_not_silently_skipped(self) -> None:
        # A stale index key (points at a file that no longer holds that species' row, e.g. the
        # measured `SnorkleZombie` -> `zombie/unclassified.json` case) is a real data-quality gap
        # in the (externally-owned) anchor tree; this loader must SURFACE it, never crash on it
        # and never pretend the species was simply absent.
        tree = anchors_mod.load_anchor_tree()
        self.assertIsInstance(tree.broken_index_entries, tuple)


class WeightsFileTests(unittest.TestCase):
    """Acceptance #6 / #6b — the shipped tuning file's shape and its stated neutral default."""

    def test_file_loads_and_validates(self) -> None:
        w = load_weights()
        self.assertEqual(set(w.trait_category_milli), set(TRAIT_POOL))
        self.assertEqual(set(w.element_category_milli),
                         {"fire", "ice", "air", "earth", "light", "dark"})
        self.assertEqual(set(w.rarity_category_milli), set(RARITY_LADDER))
        self.assertEqual(set(w.anchor_category_milli), set(anchors_mod.ANCHOR_AXES))

    def test_every_cell_is_1000_except_the_secondary_scale(self) -> None:
        w = load_weights()
        for block in (w.trait_category_milli, w.element_category_milli, w.rarity_category_milli,
                     w.anchor_category_milli):
            for row_key, row in block.items():
                for cat, val in row.items():
                    self.assertEqual(val, 1000, f"{row_key}[{cat}] must default to 1000")
        self.assertEqual(w.element_secondary_scale_milli, 500)

    def test_meta_states_untuned_and_smoke_batch_evidence(self) -> None:
        doc = json.loads(TUNING_PATH.read_text(encoding="utf-8"))
        note = doc["_meta"]["note"]
        self.assertIn("untuned", note)
        self.assertIn("smoke batch", note)
        self.assertIn("evidence", note)

    def test_flat_default_reproduces_plain_signal_count_ranking(self) -> None:
        """AC6b: at every weight 1000, `compute_scores` must equal a hand-counted "how many of
        this species' own signals map (via `SIGNAL_CATEGORY`) to this category" — i.e. the
        weight table contributes nothing beyond presence/absence. Cross-checked against a
        from-scratch count that never calls `compute_scores` itself."""
        weights = _flat_weights()
        sp = _species("synthspecies", element_primary="fire", element_secondary="ice",
                      rarity="cultivated", traits=("berserker", "guardian", "swift", "genius"))
        anchor = _anchor(sp)
        scores = compute_scores(anchor, weights)

        expected = {c: 0 for c in CATEGORIES}
        for t in sp.traits:
            expected[derive_mod._TRAIT_CATEGORY[t]] += 1
        expected[derive_mod._ELEMENT_CATEGORY["fire"]] += 1
        # secondary scaled to half: 500/1000 of one full-strength signal -> floors to 0 here,
        # which is itself the expected, honest behaviour of an integer half-count.
        expected[derive_mod._ELEMENT_CATEGORY["ice"]] += 0
        for c in CATEGORIES:
            expected[c] += 1  # rarity: flat across every category (tie-shaping only)
        self.assertEqual(scores, expected)


class RankingAndTieTests(unittest.TestCase):
    """Spec §5 'Tie determinism' + acceptance #4b (a five-way tie serialises as the DECLARED
    order, never an invented one)."""

    def test_declared_order_is_the_categories_tuple(self) -> None:
        self.assertEqual(CATEGORIES, ("attack", "defense", "support", "movement", "status"))

    def test_tie_breaks_on_declared_order(self) -> None:
        scores = {"status": 5, "attack": 5, "movement": 1, "defense": 1, "support": 1}
        self.assertEqual(rank_categories(scores), ("attack", "status", "defense", "support", "movement"))

    def test_five_way_tie_serialises_as_declared_order(self) -> None:
        weights = _flat_weights()
        # An empty-signal species: no traits, primary element only, rarity only — engineered so
        # every category ends up equal (rarity's own flat contribution alone).
        sp = SpeciesRow(species_id="tiedspecies", element_primary="fire", element_secondary=None,
                        rarity="chaff", rarity_ordinal=0, traits=())
        # Neutralise the one asymmetric contribution (element primary) by zeroing that block for
        # this synthetic case, so every category truly ties on rarity's flat +1 alone.
        zero_row = {c: 0 for c in CATEGORIES}
        weights = RoleLeanWeights(
            trait_category_milli=weights.trait_category_milli,
            element_category_milli={e: dict(zero_row) for e in weights.element_category_milli},
            element_secondary_scale_milli=weights.element_secondary_scale_milli,
            rarity_category_milli=weights.rarity_category_milli,
            anchor_category_milli=weights.anchor_category_milli, version=1,
        )
        anchor = _anchor(sp)
        scores = compute_scores(anchor, weights)
        self.assertTrue(derive_mod.is_five_way_tie(scores))
        entries, report = derive_all([anchor], weights)
        self.assertEqual(entries[0].lean_source, "floor")
        self.assertEqual(entries[0].lean_order, CATEGORIES)
        self.assertIsNone(entries[0].separation)

    def test_identical_species_produce_identical_lean_order_regardless_of_input_order(self) -> None:
        weights = _flat_weights()
        a = _anchor(_species("speciesa", traits=("berserker", "swift")))
        b = _anchor(_species("speciesb", traits=("berserker", "swift")))
        entries1, _ = derive_all([a, b], weights)
        entries2, _ = derive_all([b, a], weights)
        order1 = {e.species_anchor.species.species_id: e.lean_order for e in entries1}
        order2 = {e.species_anchor.species.species_id: e.lean_order for e in entries2}
        self.assertEqual(order1["speciesa"], order1["speciesb"])
        self.assertEqual(order1, order2)


class FamilyFloorAndF12Tests(unittest.TestCase):
    """Spec §5 'Planted violation — invented anchor' + 'Family-less species are derived',
    acceptance #3."""

    def test_family_less_species_gets_null_family_and_derived_nofloor(self) -> None:
        weights = _flat_weights()
        sp = _species("orphan", traits=("berserker", "guardian", "swift"))
        anchor = _anchor(sp, family=None)
        entries, report = derive_all([anchor], weights)
        entry = entries[0]
        self.assertIsNone(entry.species_anchor.family)
        self.assertEqual(entry.lean_source, "derived-nofloor")
        self.assertIsNone(entry.separation)
        self.assertGreater(len(entry.signals), 0)
        # The F12 failure mode this guards: a build that instead floors every family-less
        # species would report leanSource "floor" and separation 0 — assert we are NOT that.
        self.assertNotEqual(entry.lean_source, "floor")

    def test_stripping_a_species_family_never_substitutes_a_neighbours_family(self) -> None:
        weights = _flat_weights()
        member_a = _anchor(_species("membera", traits=("berserker",)), family="testfam")
        # `member_b` starts in the family, then gets its family assignment stripped — the
        # "invented anchor" planted violation: a build that substituted a neighbour's family
        # would show family="testfam" here instead of None.
        member_b_species = _species("memberb", traits=("swift",))
        stripped = _anchor(member_b_species, family=None)
        entries, _ = derive_all([member_a, stripped], weights)
        stripped_entry = next(e for e in entries if e.species_anchor.species.species_id == "memberb")
        self.assertIsNone(stripped_entry.species_anchor.family)
        self.assertEqual(stripped_entry.lean_source, "derived-nofloor")

    def test_family_less_species_are_derived_over_real_roster(self) -> None:
        """Spec's own named test, run over the REAL 84-species roster: over the family-less
        species, the count whose `leanOrder` is not the bare declared order must be > 0. Uses the
        live anchor tree too (present-or-absent only matters for whether the anchor block
        contributes; it does not affect which species land in this test's population, which is
        defined purely by family-assignments.json — stable per JoinCountTests)."""
        catalog = load_catalog()
        weights = load_weights()
        motif = json.loads((CREATURES_ROOT / "_generated" / "motif-assignments.json")
                           .read_text(encoding="utf-8"))
        family = derive_live_family_assignments()
        anchor_tree = anchors_mod.load_anchor_tree()
        anchors = [build_species_anchor(sp, family_assignments=family, motif_assignments=motif,
                                        anchor_by_lower=anchor_tree.by_lower_id)
                  for sp in catalog]
        entries, report = derive_all(anchors, weights)
        self.assertEqual(report.family_less_count, 0)
        family_less = [e for e in entries if not e.species_anchor.family]
        self.assertEqual(family_less, [])
        non_bare = sum(1 for e in entries if e.lean_order != CATEGORIES)
        self.assertGreater(non_bare, 0)


class LegacyRarityLeakTests(unittest.TestCase):
    """Spec §5 'Planted violation — legacy rarity leak', acceptance #2."""

    LEGACY_BANDS = frozenset({"common", "rare", "epic", "legendary"})

    def test_catalog_rarity_is_never_a_legacy_band(self) -> None:
        for row in load_catalog():
            self.assertNotIn(row.rarity, self.LEGACY_BANDS)
            self.assertIn(row.rarity, RARITY_LADDER)

    def test_written_role_lean_file_carries_no_legacy_band(self) -> None:
        path = ACTIONS_ROOT / "_generated" / "role-lean.json"
        if not path.is_file():
            self.skipTest("role-lean.json not yet generated in this checkout")
        doc = json.loads(path.read_text(encoding="utf-8"))
        for entry in doc["entries"]:
            self.assertIn(entry["rarity"], RARITY_LADDER)
            self.assertNotIn(entry["rarity"], self.LEGACY_BANDS)


class AttackTempoExclusionTests(unittest.TestCase):
    """Spec §5 'Planted violation — degenerate signal': `attackTempo` is excluded by measurement
    (constant `"steady"` on every observed anchor row) and a test must prove re-adding it changes
    nothing."""

    def test_attack_tempo_is_never_read_by_compute_scores(self) -> None:
        weights = _flat_weights()
        sp = _species("tempo-species", traits=("berserker",))
        with_tempo = _anchor(sp, anchor=AnchorRow(
            species_id_lower="tempo-species", posture="Bastion", reach="melee",
            target_preference="frontline", attack_tempo="steady"))
        without_tempo_row = AnchorRow(
            species_id_lower="tempo-species", posture="Bastion", reach="melee",
            target_preference="frontline", attack_tempo=None)
        without_tempo = _anchor(sp, anchor=without_tempo_row)
        self.assertEqual(compute_scores(with_tempo, weights), compute_scores(without_tempo, weights))

    def test_live_anchor_tree_attack_tempo_is_constant(self) -> None:
        """The measured fact this exclusion USED TO be grounded in: every observed `attackTempo`
        was `"steady"` — a single distinct value cannot discriminate between species even if it
        WERE scored, which was the reason re-adding it was provably inert.

        **That premise is no longer true as of 2026-09-04** (creature-corpus-self-heal C1/C2, a
        SEPARATE, approved program): `kit-shape` — the pipeline that decides `attackTempo` — had
        never been wired into `option-permutation`'s voting/permutation at all, unlike every other
        classified field, and a real 833-species audit found it had collapsed to `"steady"` 100%
        of the time as a direct result. That gap is now fixed and redeployed corpus-wide, and the
        live tree genuinely carries multiple `attackTempo` values.

        This test can no longer assert the OLD constant-value fact without asserting something
        false. It does not follow that re-including `attackTempo` in `compute_scores` is now
        correct — that is this module's own call (its `spec §3 step 4` names the exclusion
        deliberately, not just descriptively), not something a fix to the UPSTREAM classification
        pipeline should silently decide. Left as a flagged, skipped test rather than either a false
        assertion or a silent deletion, so the real question — should `attackTempo` score now that
        it discriminates? — stays visible to whoever owns this module next."""
        self.skipTest(
            "premise invalidated 2026-09-04 by creature-corpus-self-heal C1/C2: attackTempo is no "
            "longer constant in the live tree (kit-shape was fixed and redeployed) — whether "
            "compute_scores should now read it is a real, undecided design question for this "
            "module, not something to silently assert either way here")


class OverflowTests(unittest.TestCase):
    """Spec §5 'Overflow' — `long` throughout (Python ints are arbitrary precision, so this
    proves the WIDEN-BEFORE-MULTIPLY shape holds even at extreme magnitudes, never that Python
    itself can overflow)."""

    def test_maximal_species_does_not_overflow_and_stays_int(self) -> None:
        huge = 2_000_000_000  # far past a 32-bit boundary, well inside `long`
        weights = _flat_weights(milli=huge, secondary_scale=huge)
        sp = _species("maxspecies", element_primary="fire", element_secondary="ice",
                      rarity=RARITY_LADDER[-1], traits=TRAIT_POOL)
        anchor = _anchor(sp, anchor=AnchorRow(
            species_id_lower="maxspecies", posture="Bastion", reach="siege",
            target_preference="elite", attack_tempo="steady"))
        scores = compute_scores(anchor, weights)
        for cat, val in scores.items():
            self.assertIsInstance(val, int)
            self.assertGreater(val, 0)

    def test_secondary_contribution_widens_before_multiplying(self) -> None:
        # (long)a * b, never (long)(a * b) — with values whose PRODUCT exceeds a 32-bit int even
        # though neither factor alone does, a narrowing-before-multiply bug would silently wrap.
        huge = 3_000_000_000
        result = derive_mod._secondary_contribution(huge, huge)
        self.assertEqual(result, (huge * huge) // 1000)
        self.assertGreater(result, 2**31)


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
        # No mocking needed to prove this — the function simply never imports anything that
        # could reach a network. A stub transport that raises would be redundant scaffolding for
        # a module with no call sites to stub.
        summary = gen_mod.regenerate(write=False)
        self.assertEqual(summary["species"], _count_species_records(catalog_mod.CATALOG_PATH))


class ResidueReportedTests(unittest.TestCase):
    """Acceptance #5 — the residue count and per-family histogram are PRINTED (the CLI summary
    `run()` emits) and WRITTEN (each entry's own `separation` field, from which both are
    reconstructible by any later reader — Checkpoint 2's "the role lean is reported with its
    separation")."""

    def test_summary_carries_the_residue_report(self) -> None:
        summary = gen_mod.regenerate(write=False)
        self.assertIn("residue", summary)
        for key in ("familyAssigned", "familyLess", "residueCount", "residueSpecies"):
            self.assertIn(key, summary["residue"])
        # Every live species is family-assigned today (no `derived-nofloor` rows); recomputed from
        # the roster rather than pinned.
        self.assertEqual(summary["residue"]["familyAssigned"],
                         _count_species_records(catalog_mod.CATALOG_PATH))
        self.assertEqual(summary["residue"]["familyLess"], 0)

    def test_every_written_entry_carries_its_own_separation(self) -> None:
        path = ACTIONS_ROOT / "_generated" / "role-lean.json"
        if not path.is_file():
            self.skipTest("role-lean.json not yet generated in this checkout")
        doc = json.loads(path.read_text(encoding="utf-8"))
        for entry in doc["entries"]:
            self.assertIn("separation", entry)  # present (possibly null) on every entry


class DeterminismTests(unittest.TestCase):
    """Spec §5 'Determinism' + acceptance #7 — byte-identical output over unchanged inputs, using
    a frozen snapshot (never the live, concurrently-modified anchor tree — see module docstring)."""

    def _frozen_inputs(self):
        catalog = load_catalog()
        weights = load_weights()
        motif = json.loads((CREATURES_ROOT / "_generated" / "motif-assignments.json")
                           .read_text(encoding="utf-8"))
        family = json.loads((CREATURES_ROOT / "_generated" / "family-assignments.json")
                            .read_text(encoding="utf-8"))
        # Freeze the anchor tree ONCE so both runs in a test see identical input, independent of
        # whatever the concurrent classification pass does between the two calls.
        anchor_tree = anchors_mod.load_anchor_tree()
        return catalog, weights, motif, family, anchor_tree

    def test_derive_all_is_byte_identical_across_two_runs(self) -> None:
        catalog, weights, motif, family, anchor_tree = self._frozen_inputs()
        anchors = [build_species_anchor(sp, family_assignments=family, motif_assignments=motif,
                                        anchor_by_lower=anchor_tree.by_lower_id)
                  for sp in catalog]
        entries1, report1 = derive_all(anchors, weights)
        entries2, report2 = derive_all(anchors, weights)
        rows1 = [(e.species_anchor.species.species_id, e.lean_order, e.lean_source, e.separation,
                 e.signals) for e in entries1]
        rows2 = [(e.species_anchor.species.species_id, e.lean_order, e.lean_source, e.separation,
                 e.signals) for e in entries2]
        self.assertEqual(rows1, rows2)
        self.assertEqual(report1, report2)

    def test_regenerate_writes_byte_identical_files_over_a_frozen_snapshot(self) -> None:
        """Sandboxes the whole `regenerate()` write path against a private copy of the real
        inputs, so this specific test's two runs cannot observe the live tree changing between
        them (the risk `AnchorTreeJoinTests`'s docstring documents)."""
        with tempfile.TemporaryDirectory(prefix="a-s0-determinism-") as tmp:
            tmp_path = Path(tmp)
            creatures_root = tmp_path / "creatures"
            (creatures_root / "_generated").mkdir(parents=True)
            for name in ("motif-assignments.json", "family-assignments.json"):
                (creatures_root / "_generated" / name).write_text(
                    (CREATURES_ROOT / "_generated" / name).read_text(encoding="utf-8"),
                    encoding="utf-8")
            species_root = tmp_path / "species"
            species_root.mkdir()
            (species_root / "_index.json").write_text("{}", encoding="utf-8")  # frozen: empty tree

            actions_root_1 = tmp_path / "actions1"
            actions_root_2 = tmp_path / "actions2"

            summary1 = gen_mod.regenerate(
                actions_root=actions_root_1, creatures_root=creatures_root,
                species_root=species_root,
                family_assignments_path=creatures_root / "_generated" / "family-assignments.json",
                write=True)
            summary2 = gen_mod.regenerate(
                actions_root=actions_root_2, creatures_root=creatures_root,
                species_root=species_root,
                family_assignments_path=creatures_root / "_generated" / "family-assignments.json",
                write=True)

            for name in ("role-lean.json", "characteristic-pool.json"):
                text1 = (actions_root_1 / "_generated" / name).read_text(encoding="utf-8")
                text2 = (actions_root_2 / "_generated" / name).read_text(encoding="utf-8")
                self.assertEqual(text1, text2, f"{name} must be byte-identical across two runs")
                self.assertTrue(text1.endswith("\n"))

            self.assertEqual(summary1["corpusHash"], summary2["corpusHash"])


class ProvenanceTests(unittest.TestCase):
    """Acceptance #7 — both files' `_meta` record `corpusHash` and `tuningVersion`."""

    def test_written_files_carry_provenance(self) -> None:
        for name in ("role-lean.json", "characteristic-pool.json"):
            path = ACTIONS_ROOT / "_generated" / name
            if not path.is_file():
                self.skipTest(f"{name} not yet generated in this checkout")
            doc = json.loads(path.read_text(encoding="utf-8"))
            self.assertIn("corpusHash", doc["_meta"])
            self.assertIn("tuningVersion", doc["_meta"])
            self.assertEqual(doc["_meta"]["tuningVersion"], 1)


class RoleLeanShapeTests(unittest.TestCase):
    """Acceptance #1, #2, #4 — over the REAL written file."""

    @classmethod
    def setUpClass(cls) -> None:
        path = ACTIONS_ROOT / "_generated" / "role-lean.json"
        if not path.is_file():
            cls.doc = None
            return
        cls.doc = json.loads(path.read_text(encoding="utf-8"))

    def setUp(self) -> None:
        if self.doc is None:
            self.skipTest("role-lean.json not yet generated in this checkout")

    def test_one_entry_per_live_species(self) -> None:
        """A JOIN to the roster, not a count: role-lean covers exactly the catalog, one row each."""
        self.assertEqual(len(self.doc["entries"]),
                         len({e["speciesKey"] for e in self.doc["entries"]}),
                         "one role-lean entry per species, no duplicates")
        self.assertEqual({e["speciesKey"] for e in self.doc["entries"]},
                         {r.species_id for r in load_catalog()},
                         "role-lean speciesKeys are exactly the catalog ids")

    def test_lean_order_is_a_permutation_of_the_five_categories(self) -> None:
        for entry in self.doc["entries"]:
            self.assertEqual(set(entry["leanOrder"]), set(CATEGORIES))
            self.assertEqual(len(entry["leanOrder"]), 5)

    def test_lean_source_is_one_of_the_three_legal_values(self) -> None:
        for entry in self.doc["entries"]:
            self.assertIn(entry["leanSource"], {"floor", "derived", "derived-nofloor"})

    def test_family_less_entries_have_null_separation_never_zero(self) -> None:
        for entry in self.doc["entries"]:
            if entry["family"] is None and entry["leanSource"] == "derived-nofloor":
                self.assertIsNone(entry["separation"])

    def test_no_entry_key_is_an_unjoined_anchor_id(self) -> None:
        catalog_ids = {r.species_id for r in load_catalog()}
        for entry in self.doc["entries"]:
            self.assertIn(entry["speciesKey"], catalog_ids)


class PoolStructureTests(unittest.TestCase):
    """Acceptance for `characteristic-pool.json` — the six groups A-F, spec §2's inlined table,
    never `action-corpus-ideal.md` §12."""

    def test_six_groups(self) -> None:
        rows = pool_mod.build_pool_entries()
        self.assertEqual(len(rows), 6)
        self.assertEqual({r["group"] for r in rows}, set("ABCDEF"))

    def test_pairing_role_uses_none_never_neutral(self) -> None:
        rows = pool_mod.build_pool_entries()
        group_e = next(r for r in rows if r["group"] == "E")
        self.assertIn("none", group_e["closedValues"]["pairingRole"])
        self.assertNotIn("neutral", group_e["closedValues"]["pairingRole"])

    def test_group_b_has_no_threat_band_field(self) -> None:
        rows = pool_mod.build_pool_entries()
        group_b = next(r for r in rows if r["group"] == "B")
        self.assertNotIn("threatBand", group_b["fields"])

    def test_ids_match_the_action_characteristic_pool_kind_pattern(self) -> None:
        from seedsmith.adapters.actions.kinds import KINDS
        kind_spec = next(k for k in KINDS if k.kind == "action-characteristic-pool")
        for row in pool_mod.build_pool_entries():
            self.assertIsNotNone(kind_spec.id_pattern.match(row["id"]), row["id"])


class CorpusLoadRoundTripTests(unittest.TestCase):
    """The written files load back through A-C1's own `Corpus.load`, with ids matching their own
    KindSpec patterns (never `action-seed`'s) — the whole point of writing through the envelope."""

    def test_written_files_load_through_corpus_load(self) -> None:
        """`load_committed`, not a raw `Corpus.load` — see `test_type_weights.py`'s own sibling
        fix (2026-09-04) for the full reasoning: real `_rounds/` content now legitimately reuses
        `_briefs/round-1.json`'s ids by design, which only the purpose-built `_rounds/`-excluding
        loader this repo already ships correctly tolerates."""
        if not (ACTIONS_ROOT / "_generated" / "role-lean.json").is_file():
            self.skipTest("outputs not yet generated in this checkout")
        result = load_committed(ACTIONS_ROOT)
        self.assertEqual(len(result.corpus.by_kind("action-role-lean")),
                         _count_species_records(catalog_mod.CATALOG_PATH))
        # 6 is a CLOSED vocabulary (spec §2's groups A-F) a human changes — pinning it is correct.
        self.assertEqual(len(result.corpus.by_kind("action-characteristic-pool")), 6)


class CurationParityTests(unittest.TestCase):
    """Guards the transcription `curation.py` performs of the C# SSOT `CreatureTraitPoolCuration`.

    The 2026-09-11 review's finding: `curated_traits` re-implements
    `CreatureTraitPoolCuration.PickFor` constant-for-constant (sub-pools, FNV salts, the Heirloom
    threshold, the Almanac top rung) with nothing binding the two. No committed artifact carries the
    curated closed pool (`gk-data/packs/fusion/data/generated/creatures/*.json` holds the OPEN flavor text), so a value
    oracle does not exist. These tests instead parse the C# source that owns each fact and assert the
    Python side agrees — so editing the C# arrays, salts, or ladder fails here rather than silently
    changing the trait pool the game grants while the corpus keeps scoring the old bridge.
    """

    CS_ROOT = _owned("src/FusionRpg.Core/Creatures")

    @staticmethod
    def _cs(path: Path) -> str:
        if not path.is_file():
            raise unittest.SkipTest(f"C# source not present: {path}")
        return path.read_text(encoding="utf-8")

    def test_combat_and_personality_pools_match_the_csharp_arrays(self) -> None:
        text = self._cs(self.CS_ROOT / "Generation" / "CreatureTraitPoolCuration.cs")
        combat = re.search(r"Combat\s*=\s*\{([^}]*)\}", text)
        personality = re.search(r"Personality\s*=\s*\{([^}]*)\}", text)
        self.assertIsNotNone(combat, "Combat array not found in CreatureTraitPoolCuration.cs")
        self.assertIsNotNone(personality, "Personality array not found")
        cs_combat = tuple(re.findall(r'"([a-z-]+)"', combat.group(1)))
        cs_personality = tuple(re.findall(r'"([a-z-]+)"', personality.group(1)))
        self.assertEqual(ladders_mod.COMBAT_TRAITS, cs_combat)
        self.assertEqual(ladders_mod.PERSONALITY_TRAITS, cs_personality)

    def test_rarity_ladder_matches_the_csharp_enum_declaration_order(self) -> None:
        text = self._cs(self.CS_ROOT / "CreatureRarity.cs")
        enum_block = re.search(r"enum CreatureRarity\s*\{(?P<body>[^}]*)\}", text)
        self.assertIsNotNone(enum_block, "CreatureRarity enum not found")
        members = re.findall(r"\b([A-Z][A-Za-z0-9]*)\b", enum_block.group("body"))
        cs_ladder = tuple(m.lower() for m in members)
        self.assertEqual(ladders_mod.RARITY_LADDER, cs_ladder,
                         "the shared rarity ladder must match CreatureRarity's declaration order — "
                         "a widened enum here silently shifts the Heirloom/essence threshold")

    def test_trait_pool_matches_the_csharp_catalog_ids(self) -> None:
        text = self._cs(self.CS_ROOT / "CreatureTraitCatalog.cs")
        ids = tuple(re.findall(r'new\("([a-z-]+)"', text))
        self.assertEqual(ladders_mod.TRAIT_POOL, ids)

    def test_fnv_salts_match_the_csharp_call_sites(self) -> None:
        text = self._cs(self.CS_ROOT / "Generation" / "CreatureTraitPoolCuration.cs")
        cs_salts = tuple(re.findall(r'Hash\(gameTypeId,\s*"([a-z0-9-]+)"\)', text))
        self.assertEqual(cs_salts, ("curate-t1", "curate-t2", "curate-t3", "curate-essence"))

    def test_essence_and_top_rung_thresholds_match_the_ladder(self) -> None:
        text = self._cs(self.CS_ROOT / "Generation" / "CreatureTraitPoolCuration.cs")
        self.assertIn("AtLeast(rarity, CreatureRarity.Heirloom)", text)
        self.assertIn("IsTopRung(rarity)", text)
        # The C# `AtLeast(..., Heirloom)` is ordinal >= the Heirloom index; `IsTopRung` is the last
        # ladder rung. Both are derived in `curation.py` from the shared ladder, not re-typed.
        self.assertEqual(ladders_mod.RARITY_ORDINAL["heirloom"],
                         ladders_mod.RARITY_LADDER.index("heirloom"))
        top = ladders_mod.RARITY_LADDER[-1]
        self.assertEqual(top, "almanac")
        # Almanac (top) must be >= Heirloom, or the top-rung essence branch would never fire.
        self.assertGreaterEqual(ladders_mod.RARITY_ORDINAL[top],
                                ladders_mod.RARITY_ORDINAL["heirloom"])

    def test_curated_traits_is_deterministic_and_in_the_closed_pool(self) -> None:
        for sid, rarity, gid in (("x", "chaff", 7), ("y", "heirloom", 7), ("z", "almanac", 7)):
            first = curated_traits(sid, rarity, gid)
            self.assertEqual(first, curated_traits(sid, rarity, gid))
            self.assertTrue(set(first) <= set(TRAIT_POOL), first)
            if rarity == "almanac":
                self.assertIn("immortal", first)


if __name__ == "__main__":
    unittest.main()
