"""`script_of` / `script_policy` — the per-character script classifier and the declared target-script
policy (spec-script-check.md, map row 2).

⛔ **The defect this exists for.** 53 of the 54 committed Delve events carry Han characters in `name`
or `flavor`, and the shipped check could not have caught all of them even if it had run: it was one
regex range, U+4E00–9FFF (`language.py:33`). That range misses CJK Extension A (U+3400), Extension B
and beyond (U+20000), compatibility ideographs (U+F900), ideographic punctuation (U+3001), fullwidth
Latin and digits (U+FF21, U+FF11), kana (U+3042, U+30A2, U+FF71, U+30FC), Hangul (U+AC00) and
Cyrillic (U+0430). Language identification cannot see the defect either — fastText calls "English with
two Chinese words" English.

**The mechanism, honestly.** This is a name-prefix classifier over the Unicode character database
Python ships (`unicodedata`), not the Unicode `Script` property itself: `re` has no script property and
seedsmith pins every dependency exactly, so the third-party `regex` package is not available. For the
classes below the two agree; `test_scripts.py` pins one representative code point per class so a Python
upgrade that renames a character fails loudly instead of silently reclassifying it.

Nothing here calls a model, LangGraph or an adapter, like every module in this package.
"""
from __future__ import annotations

import unicodedata
from enum import Enum
from typing import Any, Iterator, Mapping

__all__ = ["ScriptClass", "script_of", "is_cjk_side", "Policy", "script_policy"]


class ScriptClass(Enum):
    """One class per script family this check polices. Values are the strings a defect message carries
    (they are what a repair prompt reads), so they are lower-hyphen, not the member names."""

    FULLWIDTH = "fullwidth"
    KANA = "kana"
    HAN = "han"
    HANGUL = "hangul"
    CJK_PUNCTUATION = "cjk-punctuation"
    CYRILLIC = "cyrillic"
    LATIN = "latin"
    DIGIT = "digit"
    COMMON = "common"
    OTHER_LETTER = "other-letter"
    OTHER = "other"


class Policy(Enum):
    """The declared target script for one field path. `latin` is not a language check (English and
    French both pass, and so does any other Latin-script language); `han` exists so a Chinese-target
    corpus can adopt the same mechanism instead of writing its own; `none` is for fields that carry no
    prose at all (ids, enum values, keys)."""

    LATIN = "latin"
    HAN = "han"
    NONE = "none"


#: Which classes each policy accepts. Digits are deliberately accepted by both prose policies — the
#: no-digit rule for narrative prose belongs to `narrative-validators` (map row 12), so one defect
#: gets one message.
_POLICY_ACCEPTS: "dict[Policy, frozenset[ScriptClass]]" = {
    Policy.LATIN: frozenset({ScriptClass.LATIN, ScriptClass.DIGIT, ScriptClass.COMMON}),
    Policy.HAN: frozenset({ScriptClass.HAN, ScriptClass.CJK_PUNCTUATION, ScriptClass.FULLWIDTH,
                           ScriptClass.DIGIT, ScriptClass.COMMON}),
}

#: The "other side" of the mixing rule `language_consistency` applies (spec §4).
_CJK_SIDE = frozenset({ScriptClass.HAN, ScriptClass.KANA, ScriptClass.HANGUL,
                       ScriptClass.CJK_PUNCTUATION})

#: How many offending characters a defect quotes. A presentation constant, NOT a tunable: it exists so
#: one long foreign run cannot turn a defect string into kilobytes of repair prompt, and nothing about
#: correctness depends on its value (spec §4).
_QUOTE_CHARS = 8


def _name(ch: str) -> str:
    """`unicodedata.name`, or `""` for an unassigned code point / surrogate (which is `other`)."""
    try:
        return unicodedata.name(ch)
    except ValueError:
        return ""


def script_of(ch: str) -> ScriptClass:
    """The script class of ONE character. Rules apply in order; the first match wins (spec §2)."""
    if len(ch) != 1:
        raise ValueError(f"script_of takes exactly one character, got {ch!r}")
    cp = ord(ch)
    name = _name(ch)
    category = unicodedata.category(ch)
    if name.startswith(("FULLWIDTH ", "HALFWIDTH ")) and not name.startswith("HALFWIDTH KATAKANA"):
        return ScriptClass.FULLWIDTH
    if name.startswith(("HIRAGANA", "KATAKANA", "HALFWIDTH KATAKANA")):
        return ScriptClass.KANA
    if name.startswith(("CJK UNIFIED IDEOGRAPH", "CJK COMPATIBILITY IDEOGRAPH")):
        return ScriptClass.HAN
    if name.startswith("HANGUL"):
        return ScriptClass.HANGUL
    if 0x3000 <= cp <= 0x303F or name.startswith("IDEOGRAPHIC"):
        return ScriptClass.CJK_PUNCTUATION
    if name.startswith("CYRILLIC"):
        return ScriptClass.CYRILLIC
    if category.startswith("L") and name.startswith("LATIN"):
        return ScriptClass.LATIN
    if "0" <= ch <= "9":
        return ScriptClass.DIGIT
    if ch.isspace() or 0x21 <= cp <= 0x2F or 0x3A <= cp <= 0x40 or 0x5B <= cp <= 0x60 \
            or 0x7B <= cp <= 0x7E or 0x2000 <= cp <= 0x206F:
        return ScriptClass.COMMON
    if category.startswith("L"):
        return ScriptClass.OTHER_LETTER
    return ScriptClass.OTHER


def is_cjk_side(ch: str) -> bool:
    """True when `ch` is the CJK side of `language_consistency`'s mixing rule. Fullwidth counts only
    when it is a LETTER — a fullwidth digit is not evidence of Chinese prose (spec §4)."""
    cls = script_of(ch)
    if cls in _CJK_SIDE:
        return True
    return cls is ScriptClass.FULLWIDTH and unicodedata.category(ch).startswith("L")


def _string_leaves(node: Any, path: str = "") -> "Iterator[tuple[str, str]]":
    """Every string leaf as `(dotted path, value)`. Array items get `[]`: `choices[].label` covers every
    choice's label, and a list of scalars is `tags[]` (spec §3, 'Field paths')."""
    if isinstance(node, Mapping):
        for key, value in node.items():
            child = f"{path}.{key}" if path else str(key)
            yield from _string_leaves(value, child)
    elif isinstance(node, list):
        for item in node:
            yield from _string_leaves(item, f"{path}[]")
    elif isinstance(node, str):
        yield (path, node)


def _coerce_policy(value: Any) -> "Policy | None":
    """`None` for an undeclared field; a `Policy` for a declared one. An unknown spelling raises —
    silently treating a wrong value as absent is the defect class this whole check exists to catch."""
    if value is None:
        return None
    if isinstance(value, Policy):
        return value
    try:
        return Policy(value)
    except ValueError:
        raise ValueError(
            f"unknown script policy {value!r} — declared policies are "
            f"{[p.value for p in Policy]}; adding one is a reviewed change (spec §3)") from None


def _quote(chars: "list[str]") -> str:
    head = chars[:_QUOTE_CHARS]
    return f"{''.join(head)!r} ({' '.join(f'U+{ord(c):04X}' for c in head)})"


def script_policy(draft: "Mapping[str, Any]", context: "Mapping[str, Any]") -> "list[str]":
    """Reject any string leaf whose characters fall outside its field's declared policy.

    `context["scriptPolicy"]` maps dotted field paths (`name`, `flavor`, `choices[].label`) to a
    `Policy` (or its string value). A string leaf with NO declared policy is itself a defect — an
    undeclared field is how a new prose field would slip past this check, so there is deliberately no
    default policy.

    Values are normalised to NFC before classification: without it a decomposed `é` (`e` + U+0301,
    category `Mn`) lands in `other` and English text with an accented loanword is refused.

    `Policy.HAN` deliberately does NOT implement `language_consistency`'s "a Latin word of three or
    more letters" clause — that is a language rule, and the two validators are run together by every
    `han` consumer (spec §3/§4).
    """
    declared = context.get("scriptPolicy") or {}
    defects: "list[str]" = []
    for path, raw in _string_leaves(draft):
        policy = _coerce_policy(declared.get(path))
        if policy is None:
            defects.append(
                f"field {path!r} has no declared script policy — add it to context['scriptPolicy'] "
                f"(one of {[p.value for p in Policy]}); an undeclared string field is how a new "
                f"prose field slips past this check")
            continue
        if policy is Policy.NONE:
            continue
        value = unicodedata.normalize("NFC", raw)
        if not value.strip():
            continue
        accepted = _POLICY_ACCEPTS[policy]
        offending = [ch for ch in value if script_of(ch) not in accepted]
        if not offending:
            continue
        defects.append(
            f"field {path!r} contains {script_of(offending[0]).value} characters "
            f"{_quote(offending)}; this field's policy is {policy.value} — write it entirely in the "
            f"target language")
    return defects
