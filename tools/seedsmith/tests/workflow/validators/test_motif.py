"""NS9 (spec-dungeon-generator-repair.md §2) — script-aware motif matching.

The event brief now carries English glosses as well as Chinese motifs, and the original case-sensitive
substring match is wrong for the English half: `Ash` would miss `ash`, and `ash` would falsely match
`crash`. These tests pin both directions, plus the unchanged Chinese behaviour so the shared validator's
existing consumers (commander effects, tree nodes) cannot drift.

    python -m pytest gk-forge/tools/seedsmith/tests/workflow/validators/test_motif.py -q
"""
from __future__ import annotations

from seedsmith.workflow.validators.motif import (
    anti_motif_violation,
    is_latin_motif,
    motif_coverage,
    motif_matches,
)


def test_latin_motifs_are_detected_as_latin_and_chinese_ones_are_not():
    assert is_latin_motif("ash") is True
    assert is_latin_motif("Ash") is True
    assert is_latin_motif("ember-fire") is True
    assert is_latin_motif("gpt4") is True
    assert is_latin_motif("\u706B\u529B") is False
    assert is_latin_motif("") is False


def test_motif_match_is_word_bounded_for_latin():
    assert motif_matches("ash", "The crash was loud") is False
    assert motif_matches("ash", "The ash grows") is True
    assert motif_matches("ash", "Ash and bone") is True          # case-insensitive
    assert motif_matches("ash", "ashen ground") is False         # no prefix match


def test_motif_match_unchanged_for_chinese():
    assert motif_matches("\u706B\u529B", "\u706B\u529B\u5168\u5F00") is True
    assert motif_matches("\u706B\u529B", "no motif here") is False


def test_motif_coverage_is_word_bounded_for_latin():
    assert motif_coverage({"flavor": "The crash was loud"}, {"motifs": ["ash"]}) != []
    assert motif_coverage({"flavor": "The ash grows"}, {"motifs": ["ash"]}) == []
    assert motif_coverage({"flavor": "Ash and bone"}, {"motifs": ["ash"]}) == []


def test_motif_coverage_is_unchanged_for_chinese():
    ctx = {"motifs": ["\u706B\u529B"]}
    assert motif_coverage({"flavor": "\u706B\u529B\u5168\u5F00"}, ctx) == []
    assert motif_coverage({"flavor": "nothing"}, ctx) != []


def test_anti_motif_violation_is_word_bounded_for_latin():
    assert anti_motif_violation({"flavor": "The crash was loud"}, {"antiMotifs": ["ash"]}) == []
    assert anti_motif_violation({"flavor": "Ash and bone"}, {"antiMotifs": ["ash"]}) != []


def test_anti_motif_violation_is_unchanged_for_chinese():
    ctx = {"antiMotifs": ["\u706B\u529B"]}
    assert anti_motif_violation({"flavor": "\u706B\u529B"}, ctx) != []
    assert anti_motif_violation({"flavor": "clean"}, ctx) == []


def test_no_motifs_declared_is_still_a_pass():
    assert motif_coverage({"flavor": "anything"}, {}) == []
    assert anti_motif_violation({"flavor": "anything"}, {}) == []
