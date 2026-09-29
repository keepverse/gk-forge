"""Task 4b (seedsmith-content-standard) — the bidirectional `language_consistency` fix.

No dedicated regression test existed for this validator before this task (confirmed: grep found
zero test files importing it) — both directions below are new coverage, not merely an extension of
an existing suite. The reverse-direction fixture is the REAL, already-shipped dungeon defect's own
text, not a synthetic stand-in.

    python -m pytest gk-forge/tools/seedsmith/tests/workflow/validators/test_language.py -q
"""
from __future__ import annotations

from seedsmith.workflow.validators.language import language_consistency

# The real, committed text from gk-data/packs/fusion/data/seed/dungeon/events/event.bargain-creature.allpeater-001.json —
# English motifs, Chinese fragments ("火力", "分配") spliced in mid-sentence.
REAL_DUNGEON_DEFECT_FLAVOR = (
    "A towering silhouette of smoke and embers coalesces in the center of the chamber. It offers "
    "to bolster your party's offensive火力, turning your strikes into torrents of hellfire, but it "
    "demands a portion of your vitality as a permanent 分配 of your life force to its own furnace."
)

# The shape of the ORIGINAL 2026-09-01 incident (commander_effect.py's own historical description):
# Chinese motifs, English words spliced into otherwise-Chinese prose.
ORIGINAL_INCIDENT_SHAPE_DRAFT_TEXT = "当一个僵尸 enters 战场时, the squad attempts to force a 变心."


def test_catches_the_real_reverse_direction_dungeon_defect_english_motifs_cjk_output():
    """The case the ORIGINAL (pre-fix) validator could not catch: motifs are English, but the
    model's own output contains CJK fragments anyway. This is a real fixture, not synthetic —
    the exact committed text of the real, already-found dungeon defect."""
    draft = {"flavor": REAL_DUNGEON_DEFECT_FLAVOR}
    context = {"motifs": ["ember", "hellfire", "sacrifice"]}  # English motifs — the real event's own

    defects = language_consistency(draft, context)

    assert defects, "the fixed validator must flag the real dungeon defect's own text"
    assert "flavor" in defects[0]


def test_still_catches_the_original_2026_09_01_incident_direction_cjk_motifs_latin_output():
    """The existing, already-proven direction must survive this fix unchanged: Chinese motifs,
    English words spliced into the output — the historical 87%-code-switched incident's own shape."""
    draft = {"effect": ORIGINAL_INCIDENT_SHAPE_DRAFT_TEXT}
    context = {"motifs": ["僵尸", "变心"]}  # Chinese motifs — the original incident's own

    defects = language_consistency(draft, context)

    assert defects, "the original CJK-motif direction must still be caught after the fix"
    assert "effect" in defects[0]


def test_an_all_latin_corpus_with_no_contamination_is_unaffected():
    draft = {"flavor": "The bone grows dense and heavy under the weight of the struggle."}
    context = {"motifs": ["bone", "struggle"]}

    assert language_consistency(draft, context) == []


def test_an_all_cjk_value_with_no_latin_words_is_not_flagged():
    # 8 of the original incident's 84 drafts came back wholly in Chinese and read better —
    # that outcome must stay a pass, not a new false positive from removing the motif-language gate.
    draft = {"effect": "整支队伍的士气因这场胜利而高涨。"}
    context = {"motifs": ["士气", "胜利"]}

    assert language_consistency(draft, context) == []


def test_fires_even_with_no_motifs_supplied_at_all():
    # The fix removes the `if not motifs: return []` short-circuit — a caller that forgot to pass
    # motifs must not silently disable the check.
    draft = {"flavor": REAL_DUNGEON_DEFECT_FLAVOR}

    defects = language_consistency(draft, {})

    assert defects
