"""Tests for seedsmith.briefkit.avoid_list (ip-censor T14) — the one shared IP avoid-list
helper the tree brief (T16) and the uniques brief (T15) adopt.

    python -m pytest gk-forge/tools/seedsmith/tests/test_briefkit_avoid_list.py -q

Every mark here is invented (`Examplemark`, `Zorblax`, `Zqx`, `CodeonlyInternal`):
`gk-forge/tools/seedsmith/**` is an enforced `generator-prompt` surface, so no real registry spelling
may appear in a seedsmith test file. No count over the REAL registry is pinned (a registry row
is a closed vocabulary a person edits; these tests use the fixture only).
"""
from __future__ import annotations

import ast
import json
import re
import tempfile
import unittest
from pathlib import Path

from seedsmith.adapters.trees.nodegen import brief as tree_brief
from seedsmith.adapters.trees.nodegen.vocab import AffixOption
from seedsmith.briefkit.avoid_list import (
    DEFAULT_REGISTRY_FILE,
    load_avoid_terms,
    render_avoid_line,
)

FIXTURE_REGISTRY = Path(__file__).resolve().parent / "fixtures" / "avoid_list" / "registry.json"

#: The shipped `seedsmith` package — every string literal in it is a candidate a prompt could be
#: hiding inside, so the prompt-hygiene rules below are stated over the whole package (a superset of
#: its prompts) rather than over a list of prompt constants that a future edit could rename.
PACKAGE_ROOT = Path(__file__).resolve().parent.parent / "seedsmith"

#: The GRAMMAR of a franchise style citation, not a word list: a capitalised proper noun bound
#: directly to a lowercase style descriptor by a hyphen. It names no franchise, so it holds for a
#: brand the registry carries no row for — which is the case the deny-source-driven rule below
#: structurally cannot see. Measured over the shipped package at authoring time: exactly one match,
#: the citation this rule exists to catch. A false positive is a hyphenated capitalised phrase
#: ending in one of these descriptors; the failure message says so.
FRANCHISE_CITATION = re.compile(
    r"\b[A-Z][a-z]{2,}-(?:style|like|esque|inspired|flavou?red|tone)\b")


def _affixes() -> "list[AffixOption]":
    return [
        AffixOption(affix_id="atom.freezing", name="Killing Frost", tags=("offensive",),
                    kind_id="status.apply"),
    ]


class LoadAvoidTermsTests(unittest.TestCase):
    def test_returns_every_player_facing_alias_and_nothing_else(self) -> None:
        self.assertEqual(
            load_avoid_terms(FIXTURE_REGISTRY),
            ("example mark", "Examplemark", "Zorblax", "Zqx"),
        )

    def test_a_code_identifier_only_group_is_absent(self) -> None:
        self.assertNotIn("CodeonlyInternal", load_avoid_terms(FIXTURE_REGISTRY))

    def test_a_short_alias_with_its_own_scope_is_included(self) -> None:
        self.assertIn("Zqx", load_avoid_terms(FIXTURE_REGISTRY))

    def test_two_loads_are_byte_identical(self) -> None:
        self.assertEqual(load_avoid_terms(FIXTURE_REGISTRY), load_avoid_terms(FIXTURE_REGISTRY))

    def test_order_does_not_depend_on_file_order(self) -> None:
        doc = json.loads(FIXTURE_REGISTRY.read_text(encoding="utf-8"))
        doc["groups"] = list(reversed(doc["groups"]))
        with tempfile.TemporaryDirectory() as tmp:
            reordered = Path(tmp) / "registry.json"
            reordered.write_text(json.dumps(doc), encoding="utf-8")
            self.assertEqual(load_avoid_terms(reordered), load_avoid_terms(FIXTURE_REGISTRY))

    def test_a_registry_missing_groups_throws_naming_the_key(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "registry.json"
            bad.write_text(json.dumps({"schemaVersion": 1}), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "groups"):
                load_avoid_terms(bad)

    def test_a_group_missing_scope_throws_naming_the_key(self) -> None:
        doc = json.loads(FIXTURE_REGISTRY.read_text(encoding="utf-8"))
        del doc["groups"][0]["scope"]
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "registry.json"
            bad.write_text(json.dumps(doc), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "scope"):
                load_avoid_terms(bad)


class RenderAvoidLineTests(unittest.TestCase):
    def test_empty_terms_render_an_empty_string(self) -> None:
        self.assertEqual(render_avoid_line(()), "")

    def test_two_renders_are_byte_identical(self) -> None:
        terms = load_avoid_terms(FIXTURE_REGISTRY)
        self.assertEqual(render_avoid_line(terms), render_avoid_line(terms))

    def test_the_line_names_every_term(self) -> None:
        line = render_avoid_line(load_avoid_terms(FIXTURE_REGISTRY))
        for term in load_avoid_terms(FIXTURE_REGISTRY):
            self.assertIn(term, line)

    def test_terms_are_casefold_unique_and_sorted_as_a_property_not_a_fixture_list(self) -> None:
        """The docstring's claim, asserted rather than trusted — over BOTH the fixture and the REAL
        committed registry, because the property is what every adopter depends on (two briefs that
        disagree about order disagree about the brief hash, and a duplicate casefold spelling would
        print twice and read as two separate warnings).

        `validation-ssot.md` forbids pinning a COUNT over the real registry, and this pins none: it
        asserts shape, which holds for every row a person will ever add.
        """
        for label, registry in (("fixture", FIXTURE_REGISTRY), ("real", DEFAULT_REGISTRY_FILE)):
            terms = load_avoid_terms(registry)
            with self.subTest(registry=label):
                self.assertTrue(terms, f"{label} registry yielded no terms at all")
                folded = [t.casefold() for t in terms]
                self.assertEqual(len(set(folded)), len(folded),
                                 f"{label}: two spellings share one casefold")
                self.assertEqual(sorted(folded), folded, f"{label}: terms are not sorted")
                self.assertEqual(terms, load_avoid_terms(registry), f"{label}: two loads differ")

    def test_the_rendered_line_is_byte_identical_not_merely_equal(self) -> None:
        """`assertEqual` on two strs is an equality claim; a brief's identity is its BYTES, because
        the brief hash is taken over the rendered text. Compared as encoded bytes so a platform
        newline or encoding difference cannot hide behind str equality."""
        terms = load_avoid_terms(FIXTURE_REGISTRY)
        first = render_avoid_line(terms).encode("utf-8")
        second = render_avoid_line(load_avoid_terms(FIXTURE_REGISTRY)).encode("utf-8")
        self.assertEqual(first, second)


class TreeBriefAdoptionTests(unittest.TestCase):
    """T16's adoption half at the brief seam: the rendered tree brief carries the avoid line as
    its own line, and no fixture `franchise-mark` spelling appears outside that line (the
    prompt-hygiene check, over the brief text, not the corpus)."""

    def test_the_tree_brief_contains_the_avoid_line(self) -> None:
        text = tree_brief.render_brief(
            node_id="skill.t-off-t1-n0", sample_index=0, tree_display_name="Might",
            tree_reading="raw physical force", branch="offensive", tier=1, node_class="mechanism",
            motifs=["ferocity"], anti_motifs=["cowardice"],
            permitted_affixes=_affixes(), permitted_properties=["posture"],
            avoid_terms=load_avoid_terms(FIXTURE_REGISTRY),
        )
        self.assertIn(render_avoid_line(load_avoid_terms(FIXTURE_REGISTRY)), text)

    def test_the_avoid_line_is_separate_from_the_motif_avoid_line(self) -> None:
        text = tree_brief.render_brief(
            node_id="skill.t-off-t1-n0", sample_index=0, tree_display_name="Might",
            tree_reading="raw physical force", branch="offensive", tier=1, node_class="mechanism",
            motifs=[], anti_motifs=["cowardice"],
            permitted_affixes=_affixes(), permitted_properties=[],
            avoid_terms=load_avoid_terms(FIXTURE_REGISTRY),
        )
        motif_lines = [ln for ln in text.splitlines() if "Avoid entirely:" in ln]
        ip_lines = [ln for ln in text.splitlines() if "IP avoid-list" in ln]
        self.assertEqual(1, len(motif_lines))
        self.assertEqual(1, len(ip_lines))
        self.assertNotEqual(motif_lines[0], ip_lines[0])

    def test_no_fixture_mark_spelling_appears_outside_the_avoid_line(self) -> None:
        text = tree_brief.render_brief(
            node_id="skill.t-off-t1-n0", sample_index=0, tree_display_name="Might",
            tree_reading="raw physical force", branch="offensive", tier=1, node_class="mechanism",
            motifs=[], anti_motifs=[],
            permitted_affixes=_affixes(), permitted_properties=[],
            avoid_terms=load_avoid_terms(FIXTURE_REGISTRY),
        )
        remainder = text.replace(render_avoid_line(load_avoid_terms(FIXTURE_REGISTRY)), "")
        for spelling in ("examplemark", "example mark", "zorblax", "zqx"):
            self.assertNotIn(spelling, remainder.lower())

    def test_without_terms_the_brief_is_unchanged(self) -> None:
        text = tree_brief.render_brief(
            node_id="skill.t-off-t1-n0", sample_index=0, tree_display_name="Might",
            tree_reading="raw physical force", branch="offensive", tier=1, node_class="mechanism",
            motifs=[], anti_motifs=[],
            permitted_affixes=_affixes(), permitted_properties=[],
        )
        self.assertNotIn("IP avoid-list", text)


def _shipped_string_literals() -> "list[tuple[str, int, str]]":
    """Every string literal in the shipped `seedsmith` package, as `(file, line, text)`.

    Read through `ast`, not a text search, so a citation cannot hide in a concatenation, an f-string
    segment or a docstring. Deliberately a superset of the package's prompts: the rule is about
    shipped prose, and narrowing the corpus would narrow the guarantee.
    """
    found: "list[tuple[str, int, str]]" = []
    for path in sorted(PACKAGE_ROOT.rglob("*.py")):
        rel = path.relative_to(PACKAGE_ROOT.parent.parent.parent)
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                found.append((rel.as_posix(), node.lineno, node.value))
    return found


def _marks_in_scope_for_prompts(registry_file: Path) -> "tuple[str, ...]":
    """The registry spellings whose OWN effective scope includes `generator-prompt` — the marks this
    surface is actually meant to police, read from the deny source at RUN time.

    The same surface-and-scope conjunction the release gate applies (`ipcensor.registry.Registry.
    enforces`, `scope-policy.v1.json`), applied here so the local test needs no second list and
    writes no real spelling into a seedsmith file.
    """
    document = json.loads(registry_file.read_text(encoding="utf-8"))
    spellings: "list[str]" = []
    for group in document["groups"]:
        group_scope = {str(s) for s in group["scope"]}
        for alias in group["aliases"]:
            own = alias.get("scope")
            effective = {str(s) for s in own} if isinstance(own, list) else group_scope
            if "generator-prompt" in effective:
                spellings.append(str(alias["text"]))
    return tuple(sorted(set(spellings), key=str.casefold))


class PromptHygieneTests(unittest.TestCase):
    """T15's prompt-hygiene half, stated over the SHIPPED package instead of over a corpus.

    Two rules, because one rule cannot see everything:

    1. The deny-source rule reads the program's own registry and asks whether a mark it carries is
       spelled inside a shipped prompt. This is the durable gate, and it is the strongest available
       check — but it is bounded by the registry's COVERAGE, and a brand with no row is invisible to
       it by construction (`Registry.scope_for` returns the empty set for an unknown mark,
       `ipcensor/registry.py:230-238`).
    2. The citation-grammar rule below therefore carries the case rule 1 cannot: it names no
       franchise, so it holds for a brand nobody has registered yet. This is a grammar, not a
       second IP list — it lives in a test and in no production path.
    """

    def test_the_selection_honours_group_scope_and_an_alias_own_narrower_scope(self) -> None:
        """The selection's own contract, proven on the FIXTURE so it can never rot.

        Deliberately not asserted against the real registry: a test that goes red when an owner
        retires a mark trains people to weaken tests, and retiring `overwatch` now that IC-4.1's live
        node is clean would be a *correct* act that must not redden a unit test. What must hold
        forever is that the selection reads SCOPE — from the group, and from an alias's own narrower
        scope when it declares one — and the fixture is where that is stated.
        """
        # The fixture's `Examplemark` group is player-scoped only, so nothing in it is selected for
        # this surface; its `Zqx` alias declares `player-name`/`player-prose` of its own, same answer.
        self.assertEqual((), _marks_in_scope_for_prompts(FIXTURE_REGISTRY))

        doc = json.loads(FIXTURE_REGISTRY.read_text(encoding="utf-8"))
        doc["groups"][0]["scope"] = ["generator-prompt", "player-name", "player-prose"]
        with tempfile.TemporaryDirectory() as tmp:
            promoted = Path(tmp) / "registry.json"
            promoted.write_text(json.dumps(doc), encoding="utf-8")
            selected = _marks_in_scope_for_prompts(promoted)
        self.assertTrue(selected, "promoting a group onto this surface must select its spellings")
        self.assertIn("Examplemark", selected)
        # The short alias carries its OWN scope, which still excludes this surface: a group's scope
        # must not leak onto an alias that narrowed itself.
        self.assertNotIn("Zqx", selected)

    def test_this_surface_is_an_enforced_one_and_the_deny_source_is_readable(self) -> None:
        """Anti-vacuity, split so that neither half can rot.

        The policy half is a fact about `scope-policy.v1.json` and does not go stale: if
        `generator-prompt` were ever dropped from `enforcedSurfaces`, this surface would no longer
        be meant to be policed and a test that says so is correct. The readability half is already
        thrown by `load_avoid_terms` (T14) and is repeated here so the failure names this contract.

        What is deliberately NOT asserted is that some particular mark is in scope here — see
        `test_the_selection_honours_group_scope_and_an_alias_own_narrower_scope` for why.
        """
        policy = json.loads(
            (DEFAULT_REGISTRY_FILE.parent / "scope-policy.v1.json").read_text(encoding="utf-8"))
        self.assertIn("generator-prompt", policy["enforcedSurfaces"],
                      "the surface this rule polices is no longer an enforced one")
        self.assertTrue(DEFAULT_REGISTRY_FILE.is_file(), DEFAULT_REGISTRY_FILE)
        document = json.loads(DEFAULT_REGISTRY_FILE.read_text(encoding="utf-8"))
        self.assertEqual(1, document.get("schemaVersion"))
        self.assertIsInstance(document.get("groups"), list)
        self.assertTrue(load_avoid_terms(), "the deny source yields no player-facing spelling at all")

    def test_no_mark_the_deny_source_carries_appears_in_a_shipped_prompt(self) -> None:
        hits: "list[str]" = []
        for spelling in _marks_in_scope_for_prompts(DEFAULT_REGISTRY_FILE):
            needle = spelling.casefold()
            for rel, line, text in _shipped_string_literals():
                if needle in text.casefold():
                    hits.append(f"{rel}:{line} spells a registry mark in scope on this surface")
        self.assertEqual([], hits)

    def test_no_shipped_string_cites_another_franchise_by_name(self) -> None:
        hits = [f"{rel}:{line} cites a brand as a style reference: {match!r}"
                for rel, line, text in _shipped_string_literals()
                for match in FRANCHISE_CITATION.findall(text)]
        self.assertEqual(
            [], hits,
            "a brief never names another game or franchise as a style reference "
            "(ip-censor-map.md:149, spec-avoid-list.md:34-35); style comes from this program's own "
            "exemplars. A match here is either such a citation or a hyphenated capitalised phrase "
            "ending in a style descriptor — check which before changing this pattern.")


if __name__ == "__main__":
    unittest.main()
