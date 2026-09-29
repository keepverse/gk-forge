"""Tests for seedsmith.adapters.trees.nodegen.vocab (task H1) — the affix pick vocabulary, counted
fresh from the real corpus, never transcribed (spec-tree-language.md §3 rows 11-12, §5.1).
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from seedsmith.adapters.items import registries
from seedsmith.adapters.trees.nodegen import vocab


class RealCorpusCountsTests(unittest.TestCase):
    """Reads the REAL committed affix-family corpus — the same one `items/setgen/vocab.py`
    reads — so a drift in the corpus is caught here too, never silently re-derived."""

    def test_counts_125_families_and_their_tag_values(self) -> None:
        # The committed affix corpus grew after the 112-family snapshot (owner commits
        # 27e908d3/3f9afb44 added thirteen offensive, seven defensive and two utility families, plus new
        # non-branch tags: metal/sturdy/arcane/mechanical, which never match a branch cut).
        vocabulary = vocab.build()
        # The committed affix corpus is a growing content population, never pinned (population-pin
        # SE3.5, 2026-09-20; the exact AGENTS.md worked example).
        self.assertTrue(vocabulary.count > 0)
        # ⛔ Three per-tag COUNT pins stood here (offensive 58 / defensive 47 / utility 19). A per-tag
        # count is a population count, and it went stale the moment the corpus legitimately moved: the
        # tag-axis exclusivity repair (`e1d9103ee`, 2026-09-20) stripped `utility` from two
        # `g-evade.json` entries that also carried a same-axis tag, taking it 19 -> 17 with the
        # GENERATOR's own rule as the cause. What this vocabulary owes its one consumer
        # (`permitted_for_branch`, keyed on offensive/defensive/utility) is the CONTRACT, so the
        # contract is what is asserted: the closed tag vocabulary, at least one tag per family, the
        # generators' own exclusivity rule (`affixfamgen/emit.py:120` calls the same helper with the
        # same `applies_to`), and a non-empty candidate set on BOTH branches.
        registry_tags = registries.load_vocabularies()["tags"]
        tag_axes = registries.load_tag_axes(applies_to="affix-family")
        for option in vocabulary.options:
            self.assertTrue(option.tags, f"{option.affix_id} carries no tag")
            for tag in option.tags:
                self.assertIn(tag, registry_tags, f"{option.affix_id} carries unknown tag {tag!r}")
            self.assertIsNone(
                registries.tag_axis_violation(option.tags, tag_axes),
                f"{option.affix_id} breaks the tag-axis exclusivity rule")
        for branch in ("offensive", "defensive"):
            self.assertTrue(vocabulary.permitted_for_branch(branch),
                            f"no affix family is offered on the {branch} branch")

    def test_ids_are_unique_and_get_resolves_a_real_one(self) -> None:
        vocabulary = vocab.build()
        ids = vocabulary.ids()
        self.assertEqual(len(ids), len(set(ids)))
        option = vocabulary.get(ids[0])
        self.assertEqual(option.affix_id, ids[0])

    def test_get_raises_on_an_unknown_id(self) -> None:
        vocabulary = vocab.build()
        with self.assertRaises(vocab.AffixVocabularyError):
            vocabulary.get("atom.does-not-exist")

    def test_one_line_never_carries_the_display_template_magnitude_placeholder(self) -> None:
        """§5's own reasoning applies here too: a brief must never carry a number. `one_line` uses
        the affix's `name`, never its `displayTemplate` (which embeds a `{value}%`-shaped
        placeholder) — this proves it structurally rather than by eyeballing one entry."""
        vocabulary = vocab.build()
        for option in vocabulary.options:
            self.assertNotIn("{value}", option.one_line)


class EmptyCorpusRefusalTests(unittest.TestCase):
    def test_an_empty_directory_is_refused_never_widened_to_an_empty_vocabulary(self) -> None:
        empty_dir = Path(tempfile.mkdtemp())
        with self.assertRaises(vocab.AffixVocabularyError):
            vocab.build(empty_dir)


class PermittedForBranchTests(unittest.TestCase):
    """task H3: the one real, unblocked cut this vocabulary supports today — branch tag plus
    'utility' — pending the atom-tag registry the module's own docstring names by name."""

    def setUp(self) -> None:
        self.vocabulary = vocab.build()

    def test_offensive_branch_gets_offensive_and_utility_tagged_affixes(self) -> None:
        options = self.vocabulary.permitted_for_branch("offensive")
        self.assertTrue(options)
        for option in options:
            self.assertTrue("offensive" in option.tags or "utility" in option.tags)
        # EX-1 + P5.1: minus structural ops (ladder principle) and minus unresolvable
        # families (no bindable emitted row) — the count identity holds on the offerable
        # subset, not the raw tag set.
        self.assertEqual(len(options), len([o for o in self.vocabulary.options
                                            if ("offensive" in o.tags or "utility" in o.tags)
                                            and o.op not in ("Replace", "Flag")
                                            and o.resolvable]))

    def test_defensive_branch_gets_defensive_and_utility_tagged_affixes(self) -> None:
        options = self.vocabulary.permitted_for_branch("defensive")
        self.assertTrue(options)
        for option in options:
            self.assertTrue("defensive" in option.tags or "utility" in option.tags)

    def test_an_illegal_branch_refuses(self) -> None:
        with self.assertRaises(ValueError):
            self.vocabulary.permitted_for_branch("sideways")

    def test_offensive_and_defensive_never_share_a_non_utility_only_affix(self) -> None:
        """An affix tagged ONLY 'offensive' must never show up in the defensive branch's own
        permitted subset, and vice versa -- utility is the only legal overlap."""
        offensive = {o.affix_id for o in self.vocabulary.permitted_for_branch("offensive")
                    if "utility" not in o.tags}
        defensive = {o.affix_id for o in self.vocabulary.permitted_for_branch("defensive")
                    if "utility" not in o.tags}
        self.assertEqual(offensive & defensive, set())

    def test_structural_ops_are_never_permitted_on_either_branch(self) -> None:
        """EX-1 (ladder principle): Replace/Flag substitute a constant where the power ladder
        requires f(Theta), so no branch offers them. Against the real corpus: every permitted
        option carries a composable op or none at all."""
        for branch in ("offensive", "defensive"):
            for option in self.vocabulary.permitted_for_branch(branch):
                self.assertNotIn(option.op, ("Replace", "Flag"),
                                 f"{option.affix_id} offers structural op {option.op!r}")

    def test_every_permitted_option_is_binder_resolvable(self) -> None:
        """P5.1: the permitted enum is binder-resolvable families only — every offered option
        has at least one emitted row the binder carries (concrete channel or status.apply
        with a status), proven against the real generated rows, never the family entry."""
        for branch in ("offensive", "defensive"):
            permitted = self.vocabulary.permitted_for_branch(branch)
            self.assertTrue(permitted, f"branch {branch!r} offers nothing — held, investigate")
            for option in permitted:
                self.assertTrue(option.resolvable, f"{option.affix_id} offered but unresolvable")

    def test_residue_classification_covers_every_unoffered_family(self) -> None:
        """P5.2: the residue is data — every family the enum does not offer carries exactly
        one closed reason (structural-op / no-emitted-rows / pool-channels-only /
        bare-stem-only). An unclassified family fails naming it."""
        residue = vocab.classify_residue(
            vocab.load_affix_families(), vocab.load_generated_rows())
        closed = {"structural-op", "no-emitted-rows", "pool-channels-only",
                  "bare-stem-only", "unbased-channel"}
        offered = {o.affix_id for o in self.vocabulary.options if o.resolvable}
        for fid, reason in residue.items():
            self.assertIn(reason, closed, f"{fid} carries unknown reason {reason!r}")
        for option in self.vocabulary.options:
            if not option.resolvable and option.op not in ("Replace", "Flag"):
                self.assertIn(option.affix_id, residue,
                              f"{option.affix_id} unresolvable but unclassified")
            if option.resolvable:
                self.assertNotIn(option.affix_id, residue,
                                 f"{option.affix_id} resolvable but listed as residue")


if __name__ == "__main__":
    unittest.main()
