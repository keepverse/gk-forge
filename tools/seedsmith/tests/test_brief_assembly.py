"""Tests for seedsmith.adapters.actions.brief_assembly (A-S2, spec-brief-assembly.md).

    python -m pytest gk-forge/tools/seedsmith/tests/test_brief_assembly.py -v

Spec §5's eight named cases plus §6's seven acceptance criteria. Same fixture discipline every
prior module in this session established for an absent real upstream: A-P2 (`family-propose`) has
never run for real, so every test below proves the assembly logic against synthetic, in-memory
"accepted round" fixtures. The one thing that IS real here -- unlike A-P2's own output -- is A-S1's
own plan: `gk-data/packs/fusion/data/seed/actions/_briefs/round-1.json` was generated for real earlier this session, and
`ByteIdenticalToRealRound1Tests` reads it directly to prove non-`familyActions` fields are carried
through untouched, rather than trusting a synthetic plan fixture to catch a re-derivation bug.
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from seedsmith.adapters.actions.brief_assembly import derive as ba  # noqa: E402
from seedsmith.adapters.actions.characteristic_pool.catalog import (  # noqa: E402
    CATALOG_PATH, derive_live_family_assignments, load_catalog,
)
from seedsmith.adapters.actions import generate_brief_assembly as gen_mod  # noqa: E402
from seedsmith.adapters.actions.vocab import load_family_ids  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[3]
FAMILY_IDS = load_family_ids()                                   # the 98, read fresh (live tree)
FAM_A, FAM_B = sorted(FAMILY_IDS)[:2]
ROUND_1_PLAN_PATH = REPO_ROOT / "data" / "seed" / "actions" / "_briefs" / "round-1.json"


# ---------------------------------------------------------------------------------------------
# Fixture builders.
# ---------------------------------------------------------------------------------------------

def _plan_brief(species_key: str, *, family: "str | None" = None,
               motifs=("motif-a",), anti_motifs=()) -> dict:
    """A synthetic species-scope (signature) brief, shaped exactly like one of
    `distribution_planner.derive.plan_subject`'s own real entries -- every key this module must
    carry through byte-identical."""
    brief_id = f"brief.species.{species_key}.001"
    return {
        "id": brief_id, "briefId": brief_id, "scope": "species", "scopeKey": species_key,
        "anchor": {
            "family": family, "element": "fire", "rarity": "chaff", "themeKey": f"creature.{species_key}",
            "motifs": list(motifs), "antiMotifs": list(anti_motifs),
        },
        "slot": {
            "category": "attack", "targetMode": "single", "areaShape": None, "relation": "enemy",
            "kind": None, "rungBand": [1, 10], "structureAxes": ["restriction"],
            "structureEnforced": True,
        },
        "pool": {"allowedAtomFamilies": [FAM_A, FAM_B], "forbiddenAtomFamilies": []},
        "pairing": {"role": "none", "pairedPayoffFamily": None},
        "avoidNeighbours": [],
        "_provenance": {"corpusHash": "deadbeef", "promptVersion": 1, "round": 1, "tuningVersion": 1},
    }


def _plan_envelope(entries: "list[dict]") -> dict:
    return {"schemaVersion": 1, "kind": "action-brief",
           "_meta": {"partition": "round-1"}, "entries": entries}


def _accepted_action(id_, scope, scope_key, *, category="attack", target_mode="single",
                     area_shape=None, relation="enemy", atom_families=None, pairing_role="none",
                     name="Strike", rationale="deals damage", structure_axes=()) -> dict:
    """An accepted-round `action-seed` row -- the exact shape A-S3's own `survivors.json` writes
    (`dedup_select.derive.build_envelope("action-seed", ...)`), unsorted `atomFamilies` on
    purpose (`(FAM_B, FAM_A)` by default) so a passing test proves THIS module sorts them, never
    that the fixture happened to already be sorted."""
    if atom_families is None:
        atom_families = (FAM_B, FAM_A)
    return {
        "id": id_, "scope": scope, "scopeKey": scope_key, "category": category,
        "rungBand": [1, 7], "targetMode": target_mode, "areaShape": area_shape, "relation": relation,
        "atomFamilies": list(atom_families), "pairingRole": pairing_role,
        "structureAxes": list(structure_axes), "name": name, "rationale": rationale,
    }


def _accepted_envelope(entries: "list[dict]") -> dict:
    return {"schemaVersion": 1, "kind": "action-seed",
           "_meta": {"partition": "rounds", "round": 1}, "entries": entries}


# ---------------------------------------------------------------------------------------------
# §5 test 1 -- every emitted brief carries the `familyActions` key.
# ---------------------------------------------------------------------------------------------

class FamilyActionsKeyAlwaysPresentTests(unittest.TestCase):

    def test_every_brief_carries_the_key(self) -> None:
        plan = [_plan_brief("a", family="fam-x"), _plan_brief("b", family=None)]
        accepted = [_accepted_action("action.family.fam-x.001", "family", "fam-x")]
        briefs = ba.assemble_briefs(plan, accepted, FAMILY_IDS)
        self.assertEqual(len(briefs), 2)
        for b in briefs:
            self.assertIn("familyActions", b)


# ---------------------------------------------------------------------------------------------
# §5 test 2 -- a family-less species gets `[]`, present and empty, and is not skipped.
# ---------------------------------------------------------------------------------------------

class FamilyLessSpeciesTests(unittest.TestCase):

    def test_family_less_species_gets_empty_list_and_is_not_skipped(self) -> None:
        plan = [_plan_brief("lonely", family=None)]
        briefs = ba.assemble_briefs(plan, accepted_rows=[], family_ids=FAMILY_IDS)
        self.assertEqual(len(briefs), 1)                     # not skipped
        self.assertIn("familyActions", briefs[0])             # present
        self.assertEqual(briefs[0]["familyActions"], [])      # empty

    def test_family_less_species_ignores_unrelated_accepted_actions(self) -> None:
        """A family-less species must never pick up ANOTHER family's actions -- `anchor.family`
        being `None` means "no family to look up", not "look up nothing named"."""
        plan = [_plan_brief("lonely", family=None)]
        accepted = [_accepted_action("action.family.fam-x.001", "family", "fam-x")]
        briefs = ba.assemble_briefs(plan, accepted, FAMILY_IDS)
        self.assertEqual(briefs[0]["familyActions"], [])

    def test_live_family_assignments_cover_the_live_roster(self) -> None:
        """Family membership is derived from the live species seed folder, not stale generated
        creature artifacts."""
        catalog = load_catalog(CATALOG_PATH)
        assignments = derive_live_family_assignments(CATALOG_PATH)
        self.assertEqual(set(assignments), {row.species_id for row in catalog})


# ---------------------------------------------------------------------------------------------
# §5 test 3 -- sorted ordinally by actionId, stable across two runs.
# ---------------------------------------------------------------------------------------------

class SortedOrdinalTests(unittest.TestCase):

    def test_family_actions_sorted_ordinally_by_action_id(self) -> None:
        plan = [_plan_brief("a", family="fam-x")]
        accepted = [
            _accepted_action("action.family.fam-x.003", "family", "fam-x", name="Third"),
            _accepted_action("action.family.fam-x.001", "family", "fam-x", name="First"),
            _accepted_action("action.family.fam-x.002", "family", "fam-x", name="Second"),
        ]
        briefs = ba.assemble_briefs(plan, accepted, FAMILY_IDS)
        ids = [a["actionId"] for a in briefs[0]["familyActions"]]
        self.assertEqual(ids, ["action.family.fam-x.001", "action.family.fam-x.002",
                              "action.family.fam-x.003"])

    def test_stable_across_two_independent_runs(self) -> None:
        plan = [_plan_brief("a", family="fam-x")]
        accepted = [
            _accepted_action("action.family.fam-x.003", "family", "fam-x"),
            _accepted_action("action.family.fam-x.001", "family", "fam-x"),
            _accepted_action("action.family.fam-x.002", "family", "fam-x"),
        ]
        run1 = ba.assemble_briefs(plan, accepted, FAMILY_IDS)
        run2 = ba.assemble_briefs(plan, accepted, FAMILY_IDS)
        self.assertEqual(run1, run2)

    def test_atom_families_within_one_entry_are_also_sorted(self) -> None:
        """`spec-signature-propose.md` §2's own inlining rule: "name + SORTED atomFamilies +
        fingerprint" -- not just the outer list."""
        plan = [_plan_brief("a", family="fam-x")]
        accepted = [_accepted_action("action.family.fam-x.001", "family", "fam-x",
                                    atom_families=(FAM_B, FAM_A))]
        briefs = ba.assemble_briefs(plan, accepted, FAMILY_IDS)
        self.assertEqual(briefs[0]["familyActions"][0]["atomFamilies"], sorted([FAM_B, FAM_A]))


# ---------------------------------------------------------------------------------------------
# §5 test 4 -- only accepted, deduped, id-assigned actions appear; a rejected/unaccepted proposal
# planted alongside the accepted round never appears.
# ---------------------------------------------------------------------------------------------

class OnlyAcceptedActionsAppearTests(unittest.TestCase):

    def test_unaccepted_proposal_planted_alongside_the_accepted_round_never_appears(self) -> None:
        """A "raw A-P2 output" round is, in general, indistinguishable BY SHAPE from an accepted
        one -- ids are assigned at proposal time (`dedup_select.derive.Candidate.id`), not at
        acceptance time, so a rejected row parses exactly like a survivor. The only thing that
        keeps a rejected proposal out of `familyActions` is that this module NEVER reads anything
        but the `accepted_rows` its caller explicitly hands it -- proven here by constructing a
        combined "raw" set and showing that only the rows actually passed as `accepted_rows`
        (A-S3's own survivors) ever reach the output."""
        survived = _accepted_action("action.family.fam-x.001", "family", "fam-x", name="Survivor")
        rejected = _accepted_action("action.family.fam-x.002", "family", "fam-x", name="Ghost")
        raw_round = [survived, rejected]                     # what a round looks like pre-dedup
        accepted_only = [survived]                           # what A-S3's survivors.json actually holds

        plan = [_plan_brief("a", family="fam-x")]
        briefs = ba.assemble_briefs(plan, accepted_only, FAMILY_IDS)
        ids = {a["actionId"] for a in briefs[0]["familyActions"]}
        self.assertEqual(ids, {"action.family.fam-x.001"})
        self.assertNotIn(rejected["id"], ids)
        self.assertIn(rejected, raw_round)                   # the plant really was there to catch

    def test_general_and_species_scoped_accepted_rows_never_leak_into_family_actions(self) -> None:
        """Only `scope == "family"` accepted rows ever feed a brief's `familyActions`
        (`spec-signature-propose.md` §2: "its FAMILY's accepted actions")."""
        plan = [_plan_brief("a", family="fam-x")]
        accepted = [
            _accepted_action("action.general.0001", "general", None),
            _accepted_action("action.species.other.001", "species", "other"),
            _accepted_action("action.family.fam-x.001", "family", "fam-x"),
        ]
        briefs = ba.assemble_briefs(plan, accepted, FAMILY_IDS)
        ids = {a["actionId"] for a in briefs[0]["familyActions"]}
        self.assertEqual(ids, {"action.family.fam-x.001"})


# ---------------------------------------------------------------------------------------------
# §5 test 5 -- every non-`familyActions` field is byte-identical to what A-S1 actually produced.
# ---------------------------------------------------------------------------------------------

class ByteIdenticalToRealRound1Tests(unittest.TestCase):
    """Reads the REAL `gk-data/packs/fusion/data/seed/actions/_briefs/round-1.json` A-S1 wrote earlier this session --
    never a synthetic plan fixture -- so a re-derivation bug in this module (recomputing a slot,
    an anchor field, a pairing role...) cannot hide behind a fixture that happens to match."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.round1_doc = json.loads(ROUND_1_PLAN_PATH.read_text(encoding="utf-8"))
        cls.species_entries = [e for e in cls.round1_doc["entries"] if e["scope"] == "species"]

    def test_round1_matches_the_live_roster_and_plan_quota(self) -> None:
        live_species = load_catalog(CATALOG_PATH)
        self.assertEqual(len(self.species_entries), len(live_species) * 5)
        family_less = [e for e in self.species_entries if e["anchor"].get("family") is None]
        self.assertEqual(len(family_less), 0)

    def test_every_non_family_actions_field_is_byte_identical(self) -> None:
        briefs = ba.assemble_briefs(self.species_entries, accepted_rows=[], family_ids=FAMILY_IDS)
        self.assertEqual(len(briefs), len(self.species_entries))
        for original, produced in zip(self.species_entries, briefs):
            without_new_key = {k: v for k, v in produced.items() if k != "familyActions"}
            self.assertEqual(without_new_key, original)

    def test_a_family_bearing_species_still_gets_the_key(self) -> None:
        family_bearing = next(e for e in self.species_entries if e["anchor"].get("family"))
        family = family_bearing["anchor"]["family"]
        accepted = [_accepted_action(f"action.family.{family}.001", "family", family)]
        briefs = ba.assemble_briefs([family_bearing], accepted, FAMILY_IDS)
        self.assertEqual(len(briefs[0]["familyActions"]), 1)
        self.assertEqual(briefs[0]["familyActions"][0]["actionId"], f"action.family.{family}.001")


# ---------------------------------------------------------------------------------------------
# §5 test 6 -- planted violation: a brief missing the key fails when consumed, exercising the
# absence-vs-empty contract this module and A-P3 share (A-P3 itself is unbuilt).
# ---------------------------------------------------------------------------------------------

class AbsenceContractTests(unittest.TestCase):

    def test_missing_key_raises_on_consumption(self) -> None:
        malformed = {"id": "brief.species.x.001", "scope": "species"}   # no familyActions at all
        with self.assertRaises(ValueError) as ctx:
            ba.require_family_actions(malformed)
        self.assertIn("familyActions", str(ctx.exception))

    def test_empty_list_is_legal_on_consumption(self) -> None:
        legal = {"id": "brief.species.x.001", "scope": "species", "familyActions": []}
        self.assertEqual(ba.require_family_actions(legal), [])

    def test_this_modules_own_output_never_has_the_defect(self) -> None:
        plan = [_plan_brief("a", family=None), _plan_brief("b", family="fam-x")]
        accepted = [_accepted_action("action.family.fam-x.001", "family", "fam-x")]
        for b in ba.assemble_briefs(plan, accepted, FAMILY_IDS):
            ba.require_family_actions(b)                      # must not raise


# ---------------------------------------------------------------------------------------------
# §5 test 7 -- planted violation: assembling from an unaccepted-output fixture (rejected/pending,
# not accepted) fails.
# ---------------------------------------------------------------------------------------------

class UnacceptedInputRefusedTests(unittest.TestCase):
    """`generate_brief_assembly.regenerate` gates on the round envelope's own `kind` tag --
    exactly what `generate_dedup_select.py` and `generate_innate_picker.py` already gate their own
    accepted-corpus reads on. A `kind: "action-review"` file (A-S4's blocked/unresolved/escalated
    buckets) or `kind: "action-reject"` (A-S3's own rejects.json) is refused rather than silently
    read as though it were the accepted round."""

    def _run(self, accepted_doc: dict) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_root = Path(tmp)
            plan_path = tmp_root / "plan.json"
            plan_path.write_text(json.dumps(_plan_envelope([_plan_brief("a", family="fam-x")])),
                                 encoding="utf-8")
            accepted_path = tmp_root / "round.json"
            accepted_path.write_text(json.dumps(accepted_doc), encoding="utf-8")
            gen_mod.regenerate(plan_path=plan_path, accepted_round_path=accepted_path,
                              actions_root=tmp_root / "actions", round_no=1, write=False)

    def test_action_review_round_file_refused(self) -> None:
        doc = {"schemaVersion": 1, "kind": "action-review", "_meta": {}, "entries": []}
        with self.assertRaises(ValueError) as ctx:
            self._run(doc)
        self.assertIn("action-seed", str(ctx.exception))

    def test_action_reject_round_file_refused(self) -> None:
        doc = {"schemaVersion": 1, "kind": "action-reject", "_meta": {}, "entries": []}
        with self.assertRaises(ValueError) as ctx:
            self._run(doc)
        self.assertIn("action-seed", str(ctx.exception))

    def test_malformed_accepted_row_refused_inside_parse_candidate(self) -> None:
        """Even under the correct `kind: "action-seed"` tag, a row shaped like A-S3's own reject
        entries (`{id, candidateId, tier, reason, collidedWith}` -- no `category`/`targetMode`)
        fails inside `parse_candidate`, never silently included."""
        reject_shaped_row = {"id": "reject.round-1.0001", "candidateId": "action.family.fam-x.099",
                             "tier": 1, "reason": "identical fingerprint", "collidedWith": "x"}
        accepted = [_accepted_action("action.family.fam-x.001", "family", "fam-x"), reject_shaped_row]
        with self.assertRaises(ValueError):
            ba.assemble_briefs([_plan_brief("a", family="fam-x")], accepted, FAMILY_IDS)


# ---------------------------------------------------------------------------------------------
# §5 test 8 -- offline guarantee: no model transport imported anywhere in this module.
# ---------------------------------------------------------------------------------------------

class OfflineGuaranteeTests(unittest.TestCase):
    """This module makes no model call at all (spec §4's first line) -- the "stubbed transport
    that raises" pattern collapses to "no transport is imported anywhere in this module's source",
    matching every prior model-free module's own offline test (`test_dedup_select.py`'s own
    `OfflineGuaranteeTests`, `test_innate_picker.py`'s)."""

    def test_no_model_transport_import_anywhere_in_the_package(self) -> None:
        pkg_dir = Path(ba.__file__).resolve().parent
        files = list(pkg_dir.glob("*.py")) + [Path(gen_mod.__file__)]
        forbidden = ("llm_caller", "pipeline.run", "openai", "requests", "urllib", "socket")
        self.assertGreaterEqual(len(files), 2)
        for f in files:
            text = f.read_text(encoding="utf-8")
            for token in forbidden:
                self.assertNotIn(token, text, f"{f} references {token!r}")


# ---------------------------------------------------------------------------------------------
# Entrypoint integration -- real write path, always a tempfile-scoped tree, never the real
# `gk-data/packs/fusion/data/seed/actions/` tree (A-P2 has not run for real; this module's spec explicitly forbids
# fabricating an "accepted round" file into the real corpus).
# ---------------------------------------------------------------------------------------------

class EntrypointIntegrationTests(unittest.TestCase):

    def test_regenerate_writes_p3_briefs_and_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_root = Path(tmp)
            plan_path = tmp_root / "plan.json"
            plan_path.write_text(json.dumps(_plan_envelope([
                _plan_brief("a", family="fam-x"), _plan_brief("b", family=None),
            ])), encoding="utf-8")
            accepted_path = tmp_root / "accepted.json"
            accepted_path.write_text(json.dumps(_accepted_envelope([
                _accepted_action("action.family.fam-x.001", "family", "fam-x"),
            ])), encoding="utf-8")

            actions_root = tmp_root / "actions"
            summary = gen_mod.regenerate(plan_path=plan_path, accepted_round_path=accepted_path,
                                         actions_root=actions_root, round_no=1, write=True)
            self.assertEqual(summary["briefCount"], 2)
            self.assertEqual(summary["familyLessBriefCount"], 1)
            self.assertTrue(summary["written"])

            out_path = actions_root / "_rounds" / "round-1" / "p3-briefs.json"
            self.assertTrue(out_path.is_file())
            doc = json.loads(out_path.read_text(encoding="utf-8"))
            self.assertEqual(doc["kind"], "action-brief")
            self.assertEqual(len(doc["entries"]), 2)
            for entry in doc["entries"]:
                self.assertIn("familyActions", entry)

    def test_dry_run_writes_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_root = Path(tmp)
            plan_path = tmp_root / "plan.json"
            plan_path.write_text(json.dumps(_plan_envelope([_plan_brief("a", family=None)])),
                                 encoding="utf-8")
            accepted_path = tmp_root / "accepted.json"
            accepted_path.write_text(json.dumps(_accepted_envelope([])), encoding="utf-8")

            actions_root = tmp_root / "actions"
            summary = gen_mod.regenerate(plan_path=plan_path, accepted_round_path=accepted_path,
                                         actions_root=actions_root, round_no=1, write=False)
            self.assertFalse(summary["written"])
            self.assertFalse((actions_root / "_rounds").exists())


if __name__ == "__main__":
    unittest.main()
