"""Tests for seedsmith.adapters.trees.species.generate_codex (task J8, spec-species-tree.md §6,
§7.1). The codex-summary stage: 3-way voted via exact-match `resolve_vote`, the same machinery
`generate_affixes.py`'s own `name` field already uses.
"""
from __future__ import annotations

import json
import unittest

from seedsmith.adapters.trees.species.generate_codex import resolve_codex_summaries
from seedsmith.adapters.trees.species.plan import FavourCell
from seedsmith.adapters.trees.species.roster import SpeciesAnchor


def _anchor(species_id: str) -> SpeciesAnchor:
    return SpeciesAnchor(
        species_id=species_id, element_primary="fire", aptitude_primary="Might", posture="Force",
        traits=("flurry",), reason="a test fixture creature", source_path="test.json")


def _favour(aptitude="Might", element="fire", status="poison") -> FavourCell:
    return FavourCell(aptitude=aptitude, element=element, status=status)


def _stub_call(responses_by_call_order: "list[dict]"):
    """The SAME `call()` double `test_affix_authoring.py`'s own `_stub_call` uses, reused here
    rather than forked — one JSON response per call, in call order."""
    log: "list[str]" = []

    def call(system, user, *, config=None, schema=None):
        log.append(user)
        return json.dumps(responses_by_call_order[len(log) - 1])

    return call, log


class ResolveCodexSummariesTests(unittest.TestCase):
    def _species(self, ids):
        return [(sid, _anchor(sid), _favour()) for sid in ids]

    def test_a_unanimous_vote_resolves_high_confidence(self) -> None:
        responses = [{"codexSummary": "Rewards steady, patient offense."}] * 3
        call, log = _stub_call(responses)
        fresh, unresolved, results = resolve_codex_summaries(
            self._species(["Alpha"]), provenance_base={"pipeline": "species-codex"},
            call=call, workers=1)
        self.assertEqual(3, len(log))
        self.assertEqual({}, unresolved)
        self.assertEqual(1, len(fresh))
        self.assertEqual("Rewards steady, patient offense.", fresh["Alpha"]["codexSummary"])
        self.assertEqual("high", fresh["Alpha"]["_provenance"]["voteConfidence"])

    def test_a_split_vote_resolves_with_the_majority_and_records_the_minority(self) -> None:
        responses = [
            {"codexSummary": "Rewards a bold, aggressive line."},
            {"codexSummary": "Rewards a bold, aggressive line."},
            {"codexSummary": "Rewards patient defense instead."},
        ]
        call, _ = _stub_call(responses)
        fresh, unresolved, _ = resolve_codex_summaries(
            self._species(["Beta"]), provenance_base={"pipeline": "species-codex"},
            call=call, workers=1)
        self.assertEqual({}, unresolved)
        self.assertEqual("Rewards a bold, aggressive line.", fresh["Beta"]["codexSummary"])
        self.assertEqual("split", fresh["Beta"]["_provenance"]["voteConfidence"])
        self.assertEqual("Rewards patient defense instead.", fresh["Beta"]["_provenance"]["voteMinority"])

    def test_a_three_way_split_is_vote_unresolved_never_the_first_sample(self) -> None:
        responses = [
            {"codexSummary": "First answer entirely."},
            {"codexSummary": "Second, different answer."},
            {"codexSummary": "Third, also different."},
        ]
        call, _ = _stub_call(responses)
        fresh, unresolved, _ = resolve_codex_summaries(
            self._species(["Gamma"]), provenance_base={"pipeline": "species-codex"},
            call=call, workers=1)
        self.assertEqual({}, fresh)
        self.assertEqual("vote_unresolved", unresolved["Gamma"]["reason"])

    def test_a_persistently_numeric_answer_never_reaches_fresh(self) -> None:
        # `codex_summary_content_is_clean` (the validate node) rejects every sample outright, so
        # none ever reach `persisted` -- proven here as `insufficient_valid_samples`, never a
        # "resolved but dirty" entry (a resolved value can only ever be one of the samples the
        # vote was given verbatim, and every one of THOSE already passed the same content check --
        # see this module's own docstring for why a post-vote re-check would be unreachable dead
        # code, found and removed while writing this exact test).
        responses = [{"codexSummary": "Grants a 15 percent reward for patience."}] * 3
        call, _ = _stub_call(responses)
        fresh, unresolved, _ = resolve_codex_summaries(
            self._species(["Delta"]), provenance_base={"pipeline": "species-codex"},
            call=call, workers=1)
        self.assertEqual({}, fresh)
        self.assertEqual("insufficient_valid_samples", unresolved["Delta"]["reason"])
        self.assertEqual(0, unresolved["Delta"]["validSamples"])

    def test_multiple_species_are_resolved_independently_in_one_call(self) -> None:
        # 6 calls total (3 per species), and each species' own outcome depends only on ITS OWN
        # three samples, never cross-contaminated with the other species' answers.
        call, log = _stub_call([
            {"codexSummary": "Rewards fire-forward aggression."},
            {"codexSummary": "Rewards fire-forward aggression."},
            {"codexSummary": "Rewards fire-forward aggression."},
            {"codexSummary": "First."},
            {"codexSummary": "Second."},
            {"codexSummary": "Third."},
        ])
        fresh, unresolved, _ = resolve_codex_summaries(
            self._species(["Epsilon", "Zeta"]), provenance_base={"pipeline": "species-codex"},
            call=call, workers=1)
        self.assertEqual(6, len(log))
        self.assertEqual({"Epsilon"}, set(fresh))
        self.assertEqual({"Zeta"}, set(unresolved))


if __name__ == "__main__":
    unittest.main()
