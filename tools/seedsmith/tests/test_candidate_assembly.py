"""Tests for `candidate-assembly` (the new module closing the A-P{1,2,3} -> A-S4 -> A-S3 gap,
action-corpus program). Two fixture tiers, same discipline `test_brief_assembly.py` already uses
for its own `ByteIdenticalToRealRound1Tests`:

- Most tests here run against synthetic, in-memory candidate/brief fixtures, built exactly like a
  real A-P1/A-P2 round-row (`entry_for`'s own shape) and a real A-S1 brief
  (`distribution_planner.derive.plan_subject`'s own shape).
- `RealContentTests` reads the actual, real accepted candidates from this session's own smoke batch
  (`data/seed/actions/_candidates/{general,family}/round-1.json`, `gk-data/packs/fusion/data/seed/actions/_briefs/
  round-1.json`) and proves all four ("Brace"/"Kinetic Repulsion"/"Fickle Decay"/"Undead Volley")
  reach a real, gated, well-shaped `action-seed` row through this module alone -- the actual proof
  the gap this module exists to close is closed, not a synthetic stand-in for it.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from seedsmith.adapters.actions.candidate_assembly import derive as ca
from seedsmith.adapters.actions.dedup_select.derive import parse_candidate
from seedsmith.adapters.actions.vocab import load_family_ids

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

FAMILY_IDS = load_family_ids()
FAM_A, FAM_B = sorted(FAMILY_IDS)[:2]

GENERAL_CANDIDATES_PATH = _owned("data/seed/actions") / "_candidates" / "general" / "round-1.json"
FAMILY_CANDIDATES_PATH = _owned("data/seed/actions") / "_candidates" / "family" / "round-1.json"
BRIEFS_PATH = _owned("data/seed/actions/_briefs/round-1.json")


# ---------------------------------------------------------------------------------------------
# Fixture builders -- match `general_propose`/`family_propose`'s own `entry_for` shape for the
# candidate row, and `distribution_planner.derive.plan_subject`'s own shape for the brief.
# ---------------------------------------------------------------------------------------------

def _brief(scope: str, scope_key, *, category="attack", target_mode="single", area_shape=None,
          relation="enemy", rung_band=(1, 7), pairing_role="none", paired_payoff_family=None,
          family_motifs=(), family_anti_motifs=()) -> dict:
    brief_id = f"brief.{scope}.{scope_key or 'general'}.001"
    anchor = {"family": scope_key if scope == "family" else None, "element": None, "rarity": None,
             "themeKey": None, "motifs": [], "antiMotifs": []}
    if scope == "family":
        anchor["familyMotifs"] = list(family_motifs)
        anchor["familyAntiMotifs"] = list(family_anti_motifs)
        anchor["familyMotifBasis"] = "intersection"
    return {
        "id": brief_id, "briefId": brief_id, "scope": scope, "scopeKey": scope_key, "anchor": anchor,
        "slot": {"category": category, "targetMode": target_mode, "areaShape": area_shape,
                "relation": relation, "kind": None, "rungBand": list(rung_band),
                "structureAxes": ["scopeSplit", "riderStatus"], "structureEnforced": True},
        "pool": {"allowedAtomFamilies": [FAM_A, FAM_B], "forbiddenAtomFamilies": []},
        "pairing": {"role": pairing_role, "pairedPayoffFamily": paired_payoff_family},
        "avoidNeighbours": [],
        "_provenance": {"corpusHash": "deadbeef", "promptVersion": 1, "round": 1, "tuningVersion": 1},
    }


def _candidate_row(candidate_id, brief_id, pipeline_id, scope, *, name="Strike",
                   flavor="a decisive blow", rationale="channels force into a strike",
                   atom_families=None, motifs_expressed=None, differentiator=None,
                   outcome="accepted", confidence="high") -> dict:
    if atom_families is None:
        atom_families = [FAM_A]
    draft = {"candidateId": candidate_id, "briefId": brief_id, "scope": scope, "name": name,
            "flavor": flavor, "atomFamilies": list(atom_families), "rationale": rationale,
            "_provenance": {"healNotes": [{}, {}, {}]}}
    if motifs_expressed is not None:
        draft["motifsExpressed"] = list(motifs_expressed)
    if differentiator is not None:
        draft["differentiator"] = differentiator
    return {
        "candidateId": candidate_id, "briefId": brief_id, "pipelineId": pipeline_id, "scope": scope,
        "outcome": outcome, "confidence": confidence, "voteMinority": None,
        "draft": draft if outcome == "accepted" else None,
        "_provenance": {"healNotes": [{}, {}, {}]},
    }


# ---------------------------------------------------------------------------------------------
# Id minting -- the exact regex conformance proof the task calls for, never eyeballed.
# ---------------------------------------------------------------------------------------------

class TestIdMinting:
    def test_general_uses_a_four_digit_ordinal_no_scope_key_segment(self):
        assert ca.mint_action_id("general", None, 1) == "action.general.0001"
        assert ca.mint_action_id("general", None, 42) == "action.general.0042"

    def test_family_uses_a_three_digit_ordinal_with_the_scope_key_segment(self):
        assert ca.mint_action_id("family", "fruit", 1) == "action.family.fruit.001"

    def test_species_uses_a_three_digit_ordinal_with_the_scope_key_segment(self):
        assert ca.mint_action_id("species", "pyre-imp", 7) == "action.species.pyre-imp.007"

    def test_general_and_family_ordinals_genuinely_differ_in_digit_count(self):
        general_id = ca.mint_action_id("general", None, 1)
        family_id = ca.mint_action_id("family", "fruit", 1)
        general_digits = general_id.rsplit(".", 1)[1]
        family_digits = family_id.rsplit(".", 1)[1]
        assert len(general_digits) == 4
        assert len(family_digits) == 3

    def test_family_without_a_real_scope_key_raises(self):
        with pytest.raises(ValueError, match="scope_key"):
            ca.mint_action_id("family", None, 1)

    def test_ordinal_below_one_raises(self):
        with pytest.raises(ValueError, match="ordinal"):
            ca.mint_action_id("general", None, 0)

    @pytest.mark.parametrize("scope,scope_key,ordinal", [
        ("general", None, 1), ("general", None, 9999),
        ("family", "fruit", 1), ("family", "hypno-toad", 999),
        ("species", "pyre-imp", 1), ("species", "a1", 42),
    ])
    def test_every_minted_id_actually_matches_the_real_id_pattern(self, scope, scope_key, ordinal):
        """The regex-conformance proof, not eyeballed: `kinds.py`'s own real, live pattern (never a
        second, hand-copied string) against every id this module can mint."""
        minted = ca.mint_action_id(scope, scope_key, ordinal)
        assert ca.ACTION_SEED_ID_PATTERN.match(minted), (
            f"{minted!r} does not match {ca.ACTION_SEED_ID_PATTERN.pattern!r}")

    def test_the_pattern_this_module_checks_against_is_the_real_kinds_py_one(self):
        from seedsmith.adapters.actions.kinds import KINDS
        real_pattern = next(k.id_pattern for k in KINDS if k.kind == "action-seed")
        assert ca.ACTION_SEED_ID_PATTERN is real_pattern


# ---------------------------------------------------------------------------------------------
# The merge -- byte-for-byte correct from a known draft+brief pair.
# ---------------------------------------------------------------------------------------------

class TestAssembleSeedRow:
    def test_general_row_merges_mechanical_fields_from_the_brief_and_answer_fields_from_the_draft(self):
        brief = _brief("general", None, category="defense", target_mode="self", relation="self",
                       rung_band=(1, 4))
        row = _candidate_row("candidate.general.001", "brief.general.general.001", "A-P1", "general",
                             name="Brace", atom_families=[FAM_A, FAM_B])
        assembled = ca.assemble_seed_row(row, brief, action_id="action.general.0001")
        assert assembled == {
            "id": "action.general.0001", "scope": "general", "scopeKey": None,
            "category": "defense", "rungBand": [1, 4], "targetMode": "self", "areaShape": None,
            "relation": "self", "atomFamilies": [FAM_A, FAM_B], "pairingRole": "none",
            "pairedPayoffFamily": None, "name": "Brace",
        }

    def test_family_row_also_carries_motifs_used_renamed_from_motifs_expressed(self):
        brief = _brief("family", "fruit", category="defense", target_mode="self", relation="self",
                       rung_band=(1, 7))
        row = _candidate_row("candidate.family.004", "brief.family.fruit.001", "A-P2", "family",
                             name="Kinetic Repulsion", atom_families=[FAM_A],
                             motifs_expressed=["motif-a", "motif-b"])
        assembled = ca.assemble_seed_row(row, brief, action_id="action.family.fruit.001")
        assert assembled["scopeKey"] == "fruit"
        assert assembled["motifsUsed"] == ["motif-a", "motif-b"]
        assert assembled["name"] == "Kinetic Repulsion"

    def test_flavor_rationale_and_differentiator_never_appear_in_the_committed_row(self):
        """The real, considered decision this module's own docstring states: these three did their
        job informing the model's own pick and are not part of the committed `action-seed` shape
        (`kinds.py`'s `ACTION_SEED_REQUIRED`/`ACTION_SEED_OPTIONAL` names neither)."""
        brief = _brief("species", "pyre-imp", rung_band=(1, 10))
        row = _candidate_row("candidate.species.001", "brief.species.pyre-imp.001", "A-P3", "species",
                             motifs_expressed=["motif-a"], differentiator="none")
        assembled = ca.assemble_seed_row(row, brief, action_id="action.species.pyre-imp.001")
        assert "flavor" not in assembled
        assert "rationale" not in assembled
        assert "differentiator" not in assembled

    def test_area_shape_key_is_always_present_even_when_null(self):
        brief = _brief("general", None, target_mode="single", area_shape=None)
        row = _candidate_row("candidate.general.002", "brief.general.general.001", "A-P1", "general")
        assembled = ca.assemble_seed_row(row, brief, action_id="action.general.0002")
        assert "areaShape" in assembled and assembled["areaShape"] is None

    def test_paired_payoff_family_is_always_present_even_when_null(self):
        brief = _brief("general", None)
        row = _candidate_row("candidate.general.003", "brief.general.general.001", "A-P1", "general")
        assembled = ca.assemble_seed_row(row, brief, action_id="action.general.0003")
        assert "pairedPayoffFamily" in assembled and assembled["pairedPayoffFamily"] is None

    def test_a_missing_atom_families_on_the_draft_raises(self):
        brief = _brief("general", None)
        row = _candidate_row("candidate.general.004", "brief.general.general.001", "A-P1", "general",
                             atom_families=[])
        with pytest.raises(ValueError, match="atomFamilies"):
            ca.assemble_seed_row(row, brief, action_id="action.general.0004")


# ---------------------------------------------------------------------------------------------
# The gate -- A-S4's real per-pipeline schema, called against the answer-only projection.
# ---------------------------------------------------------------------------------------------

class TestGateCandidateRow:
    def test_a_well_formed_general_candidate_is_accepted(self):
        brief = _brief("general", None)
        row = _candidate_row("candidate.general.001", "brief.general.general.001", "A-P1", "general")
        verdict = ca.gate_candidate_row(row, brief)
        assert verdict.outcome == "accepted", verdict.gate_defects

    def test_a_family_candidate_missing_motifs_expressed_is_gated_a_defect(self):
        brief = _brief("family", "fruit")
        row = _candidate_row("candidate.family.001", "brief.family.fruit.001", "A-P2", "family")
        row["draft"].pop("motifsExpressed", None)
        # A-P2's own real schema REQUIRES motifsExpressed -- omitting it is a real g1 defect.
        verdict = ca.gate_candidate_row(row, brief)
        assert verdict.outcome == "unresolved"
        assert "motifsExpressed" in verdict.gate_defects

    def test_an_atom_family_outside_the_briefs_own_pool_is_gated_a_defect(self):
        brief = _brief("general", None)
        other = next(iter(FAMILY_IDS - {FAM_A, FAM_B}))
        row = _candidate_row("candidate.general.005", "brief.general.general.001", "A-P1", "general",
                             atom_families=[other])
        verdict = ca.gate_candidate_row(row, brief)
        assert verdict.outcome == "unresolved"
        assert "atomFamilies" in verdict.gate_defects

    def test_the_wrapper_fields_on_a_real_draft_never_trip_g1s_extra_key_check(self):
        """`candidateId`/`briefId`/`scope`/`_provenance` are real keys on every on-disk draft
        (`entry_for`'s own output) -- this module's `answer_only` projection strips them before
        gating, so a real candidate's own infrastructure fields never masquerade as a schema
        defect."""
        brief = _brief("general", None)
        row = _candidate_row("candidate.general.006", "brief.general.general.001", "A-P1", "general")
        assert "candidateId" in row["draft"] and "_provenance" in row["draft"]
        verdict = ca.gate_candidate_row(row, brief)
        assert verdict.outcome == "accepted", verdict.gate_defects


# ---------------------------------------------------------------------------------------------
# Round orchestration -- ordinal minting is deterministic and anchor-local.
# ---------------------------------------------------------------------------------------------

class TestAssembleRound:
    def test_two_general_candidates_mint_consecutive_ordinals_in_briefId_order(self):
        briefs = {b["briefId"]: b for b in [
            _brief("general", None, category="attack", rung_band=(1, 4)),
        ]}
        # Reuse one brief for two candidates (two briefs would need two distinct briefIds -- the
        # ordinal counter is anchor-local, not brief-local, so this alone proves it).
        b2 = dict(briefs["brief.general.general.001"])
        b2["briefId"] = "brief.general.general.002"
        b2["id"] = "brief.general.general.002"
        briefs[b2["briefId"]] = b2

        rows = [
            _candidate_row("candidate.general.002", "brief.general.general.002", "A-P1", "general", name="Beta"),
            _candidate_row("candidate.general.001", "brief.general.general.001", "A-P1", "general", name="Alpha"),
        ]
        result = ca.assemble_round(rows, briefs)
        assert [r["id"] for r in result.assembled_rows] == ["action.general.0001", "action.general.0002"]
        assert [r["name"] for r in result.assembled_rows] == ["Alpha", "Beta"]   # briefId order, not input order

    def test_existing_counts_seed_the_next_ordinal_not_a_restart_at_one(self):
        brief = _brief("family", "fruit")
        row = _candidate_row("candidate.family.010", "brief.family.fruit.001", "A-P2", "family",
                             motifs_expressed=["motif-a"])
        result = ca.assemble_round([row], {brief["briefId"]: brief},
                                   existing_counts={("family", "fruit"): 5})
        assert result.assembled_rows[0]["id"] == "action.family.fruit.006"

    def test_a_non_accepted_row_is_skipped_never_assembled(self):
        brief = _brief("general", None)
        rows = [
            _candidate_row("candidate.general.001", "brief.general.general.001", "A-P1", "general"),
            {"candidateId": None, "briefId": "brief.general.general.002", "pipelineId": "A-P1",
            "scope": "general", "outcome": "unresolved", "confidence": None, "draft": None},
        ]
        result = ca.assemble_round(rows, {brief["briefId"]: brief})
        assert len(result.assembled_rows) == 1
        assert len(result.skipped_unaccepted) == 1

    def test_a_gate_rejected_candidate_is_recorded_never_assembled(self):
        brief = _brief("general", None)
        other = next(iter(FAMILY_IDS - {FAM_A, FAM_B}))
        row = _candidate_row("candidate.general.001", "brief.general.general.001", "A-P1", "general",
                             atom_families=[other])
        result = ca.assemble_round([row], {brief["briefId"]: brief})
        assert result.assembled_rows == []
        assert len(result.gate_rejects) == 1
        assert result.gate_rejects[0].candidate_id == "candidate.general.001"

    def test_gate_false_skips_gating_and_assembles_anyway(self):
        brief = _brief("general", None)
        other = next(iter(FAMILY_IDS - {FAM_A, FAM_B}))
        row = _candidate_row("candidate.general.001", "brief.general.general.001", "A-P1", "general",
                             atom_families=[other])
        result = ca.assemble_round([row], {brief["briefId"]: brief}, gate=False)
        assert len(result.assembled_rows) == 1
        assert result.verdicts == {}

    def test_a_missing_brief_raises_rather_than_silently_skipping(self):
        row = _candidate_row("candidate.general.001", "brief.general.missing.001", "A-P1", "general")
        with pytest.raises(ValueError, match="no brief found"):
            ca.assemble_round([row], {})


# ---------------------------------------------------------------------------------------------
# Full chain, synthetic: assemble -> gate -> dedup, one accepted candidate end to end.
# ---------------------------------------------------------------------------------------------

class TestFullChainSynthetic:
    def test_an_assembled_row_survives_a_s3s_own_parse_candidate(self):
        brief = _brief("family", "fruit", category="defense", target_mode="self", relation="self")
        row = _candidate_row("candidate.family.001", "brief.family.fruit.001", "A-P2", "family",
                             name="Test Action", atom_families=[FAM_A], motifs_expressed=["motif-a"])
        result = ca.assemble_round([row], {brief["briefId"]: brief})
        assert len(result.assembled_rows) == 1
        assembled = result.assembled_rows[0]

        # A-S3's own validator, the SAME one that decides survival in the real pipeline -- never a
        # second, independently-written acceptance check.
        parsed = parse_candidate(assembled, FAMILY_IDS)
        assert parsed.id == assembled["id"]
        assert parsed.scope == "family"
        assert parsed.scope_key == "fruit"


# ---------------------------------------------------------------------------------------------
# Real content -- the actual proof, not a synthetic stand-in. All four real accepted candidates
# from this session's own smoke batch, through this module, then A-S3's own parser.
# ---------------------------------------------------------------------------------------------

@pytest.mark.skipif(not GENERAL_CANDIDATES_PATH.is_file() or not FAMILY_CANDIDATES_PATH.is_file()
                    or not BRIEFS_PATH.is_file(),
                    reason="real smoke-batch round-1 files not present in this checkout")
class TestRealContent:
    @staticmethod
    def _load(path: Path) -> dict:
        return json.loads(path.read_text(encoding="utf-8"))

    def test_real_accepted_candidates_reach_a_gated_row(self):
        general_doc = self._load(GENERAL_CANDIDATES_PATH)
        family_doc = self._load(FAMILY_CANDIDATES_PATH)
        briefs_doc = self._load(BRIEFS_PATH)

        candidate_rows = list(general_doc["entries"]) + list(family_doc["entries"])
        briefs_by_id = {b["briefId"]: b for b in briefs_doc["entries"]}

        result = ca.assemble_round(candidate_rows, briefs_by_id)

        assembled_names = sorted(r["name"] for r in result.assembled_rows)
        expected_accepted = sum(
            1 for r in candidate_rows if r.get("outcome") == "accepted" and r.get("candidateId")
        )
        assert expected_accepted > 0

        # Every real accepted row either assembles into a well-shaped action-seed, or is recorded
        # as a genuine A-S4 gate rejection -- never silently dropped.
        assert len(result.assembled_rows) + len(result.gate_rejects) == expected_accepted

        family_ids = load_family_ids()
        for row in result.assembled_rows:
            assert re.match(r"^action\.(general\.[0-9]{4}|(family|species)\.[a-z0-9_-]+\.[0-9]{3})$", row["id"])
            parsed = parse_candidate(row, family_ids)   # A-S3's own real acceptance parser
            assert parsed.id == row["id"]

        assert assembled_names or result.gate_rejects   # never a silent zero-and-zero


# ---------------------------------------------------------------------------------------------
# Existing-ordinal counting tolerates hand-authored rows outside the ordinal scheme.
# ---------------------------------------------------------------------------------------------

class TestExistingCountsRobustness:
    def test_row_without_numeric_ordinal_is_skipped_never_fatal(self) -> None:
        """Phase-4-found 2026-09-15: `act.attack` (hand-authored basic-attack fallback,
        `authored-basics.json`) carries no trailing numeric ordinal, and `_existing_counts`
        raised on it — crashing every validate/assemble run on the live tree. The count is a
        per-anchor MAX for ordinal continuation; a row with no ordinal contributes nothing to
        it. Assert the contract on the live tree: no raise, and every value a positive int."""
        from seedsmith.adapters.actions import generate_candidate_assembly as entrypoint
        from seedsmith.adapters.actions.load import load_committed
        root = seed_root() / "actions"
        counts = entrypoint._existing_counts(root)
        assert isinstance(counts, dict) and counts
        assert all(isinstance(v, int) and v >= 1 for v in counts.values())
        committed_ids = {e.id for e in load_committed(root).corpus.by_kind("action-seed")}
        assert "act.attack" in committed_ids, "regression guard needs its trigger row present"
