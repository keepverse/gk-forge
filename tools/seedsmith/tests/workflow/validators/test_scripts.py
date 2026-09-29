"""`script-check` (NS7, spec-script-check.md) — the per-character classifier and the declared policy.

    python -m pytest gk-forge/tools/seedsmith/tests/workflow/validators/test_scripts.py -q

`language_consistency`'s own suite (`tests/workflow/validators/test_language.py`) is the other half of
this task's acceptance and is deliberately untouched by it: the classifier replaces the single regex
range behind the same signature, and those tests must stay green.

One representative code point per class is pinned (spec §2's honesty note): this is a name-prefix
classifier over the Unicode character database Python ships, not the Unicode `Script` property, so a
Python upgrade that renames a character must fail here loudly rather than silently reclassify it.
"""
from __future__ import annotations

import pytest

from seedsmith.workflow.validators.registry import TIER, Tier
from seedsmith.workflow.validators.scripts import (
    Policy,
    ScriptClass,
    is_cjk_side,
    script_of,
    script_policy,
)

#: One pinned code point per class (spec §2's own examples).
REPRESENTATIVES = {
    ScriptClass.FULLWIDTH: "\uFF21",          # FULLWIDTH LATIN CAPITAL LETTER A
    ScriptClass.KANA: "\u3042",               # HIRAGANA LETTER A
    ScriptClass.HAN: "\u4E00",                # CJK UNIFIED IDEOGRAPH-4E00
    ScriptClass.HANGUL: "\uAC00",             # HANGUL SYLLABLE GA
    ScriptClass.CJK_PUNCTUATION: "\u3001",    # IDEOGRAPHIC COMMA
    ScriptClass.CYRILLIC: "\u0430",           # CYRILLIC SMALL LETTER A
    ScriptClass.LATIN: "\u00E9",              # LATIN SMALL LETTER E WITH ACUTE
    ScriptClass.DIGIT: "7",
    ScriptClass.COMMON: "\u2014",             # EM DASH
    ScriptClass.OTHER_LETTER: "\u03B1",       # GREEK SMALL LETTER ALPHA
    ScriptClass.OTHER: "\U0001F600",          # GRINNING FACE
}

#: Every class the `latin` policy refuses, with the fixture character that must trigger it.
FOREIGN_UNDER_LATIN = {
    ScriptClass.KANA: "\u3042",
    ScriptClass.HAN: "\u706B",
    ScriptClass.HANGUL: "\uAC00",
    ScriptClass.CJK_PUNCTUATION: "\u3001",
    ScriptClass.CYRILLIC: "\u0430",
    ScriptClass.FULLWIDTH: "\uFF21",
    ScriptClass.OTHER_LETTER: "\u03B1",
    ScriptClass.OTHER: "\U0001F600",
}

#: The REAL committed text of the 2026-09-08 dungeon defect, the same fixture
#: `test_language.py` carries (kept separate so either module's own fixture can move independently):
#: `gk-data/packs/fusion/data/seed/dungeon/events/event.bargain-creature.allpeater-001.json` before its regeneration.
REAL_DUNGEON_DEFECT_FLAVOR = (
    "A towering silhouette of smoke and embers coalesces in the center of the chamber. It offers "
    "to bolster your party's offensive火力, turning your strikes into torrents of hellfire, but it "
    "demands a portion of your vitality as a permanent 分配 of your life force to its own furnace."
)


def test_each_class_has_a_pinned_representative():
    for cls, ch in REPRESENTATIVES.items():
        assert script_of(ch) is cls, f"{ch!r} ({ch.encode('unicode_escape')!r}) classified as {cls}"


def test_extension_a_b_and_compatibility_ideographs_are_han():
    # The three Han ranges the old single range (U+4E00-9FFF) could not see.
    for ch in ("\u3400", "\U00020000", "\uF900"):
        assert script_of(ch) is ScriptClass.HAN


def test_kana_covers_halfwidth_and_the_prolonged_sound_mark():
    for ch in ("\u30A2", "\uFF71", "\u30FC"):
        assert script_of(ch) is ScriptClass.KANA


def test_fullwidth_digit_is_fullwidth_not_digit():
    assert script_of("\uFF11") is ScriptClass.FULLWIDTH


def test_latin_policy_rejects_each_foreign_class():
    for cls, ch in FOREIGN_UNDER_LATIN.items():
        defects = script_policy({"flavor": f"an english sentence with a {ch} inside it"},
                                {"scriptPolicy": {"flavor": Policy.LATIN}})
        assert defects, f"{cls.value} must be refused under latin"
        assert "'flavor'" in defects[0], defects[0]
        assert cls.value in defects[0], f"the defect must name the class: {defects[0]}"


def test_latin_policy_accepts_plain_english_with_curly_quotes_and_dashes():
    text = "The squad's advance \u2014 unbroken \u2014 keeps 'em coming\u2026 7 strong."
    assert script_policy({"flavor": text}, {"scriptPolicy": {"flavor": Policy.LATIN}}) == []


def test_decomposed_accent_is_normalised():
    # NFC: "cafe" + U+0301 (category Mn) is `other` without normalisation, and would refuse English.
    assert script_policy({"flavor": "cafe\u0301 au lait"}, {"scriptPolicy": {"flavor": Policy.LATIN}}) == []


def test_real_dungeon_defect_is_caught_under_latin_policy():
    defects = script_policy({"flavor": REAL_DUNGEON_DEFECT_FLAVOR},
                            {"scriptPolicy": {"flavor": Policy.LATIN}})
    assert defects, "the real committed dungeon defect must be refused under the latin policy"
    assert "'flavor'" in defects[0]
    assert ScriptClass.HAN.value in defects[0]


def test_han_policy_accepts_all_chinese_and_rejects_hangul():
    assert script_policy({"effect": "整支队伍的士气因这场胜利而高涨。"},
                         {"scriptPolicy": {"effect": Policy.HAN}}) == []
    defects = script_policy({"effect": "整支队伍\uAC00的士气"},
                            {"scriptPolicy": {"effect": Policy.HAN}})
    assert defects and ScriptClass.HANGUL.value in defects[0]


def test_undeclared_string_leaf_is_a_defect():
    defects = script_policy({"name": "Ember", "flavor": "It burns."}, {})
    assert len(defects) == 2
    assert any("'name'" in d for d in defects)
    assert any("'flavor'" in d for d in defects)


def test_array_paths_match():
    draft = {"choices": [{"label": "One"}, {"label": "\u3042"}]}
    defects = script_policy(draft, {"scriptPolicy": {"choices[].label": Policy.LATIN}})
    assert len(defects) == 1, defects
    assert "choices[].label" in defects[0]


def test_none_policy_skips_the_field():
    assert script_policy({"id": "affix-draw-001"}, {"scriptPolicy": {"id": Policy.NONE}}) == []


def test_a_string_policy_value_is_accepted():
    # A JSON-authored policy map arrives as strings, so both spellings are legal.
    assert script_policy({"flavor": "plain english"}, {"scriptPolicy": {"flavor": "latin"}}) == []


def test_unknown_policy_value_fails_loudly():
    with pytest.raises(ValueError, match="unknown script policy"):
        script_policy({"flavor": "x"}, {"scriptPolicy": {"flavor": "english"}})


def test_language_consistency_now_sees_kana_and_ext_a():
    from seedsmith.workflow.validators.language import language_consistency

    for fragment in ("\u3042", "\u3400", "\uFF21"):
        defects = language_consistency({"flavor": f"When the {fragment} enters the fray"}, {})
        assert defects, f"{fragment!r} plus Latin words must be a mixing defect"


def test_is_cjk_side_counts_fullwidth_letters_not_fullwidth_digits():
    assert is_cjk_side("\uFF21") is True      # FULLWIDTH LATIN CAPITAL LETTER A
    assert is_cjk_side("\uFF11") is False     # FULLWIDTH DIGIT ONE


def test_script_policy_is_tier_two():
    assert TIER["script_policy"] is Tier.DETERMINISTIC


def test_ScriptClass_and_Policy_are_closed():
    assert [c.value for c in ScriptClass] == [
        "fullwidth", "kana", "han", "hangul", "cjk-punctuation", "cyrillic", "latin", "digit",
        "common", "other-letter", "other",
    ]
    assert [p.value for p in Policy] == ["latin", "han", "none"]
