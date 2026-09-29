"""`language_consistency` — added 2026-09-01 after the first real commander-effect run; extended
2026-09-08 (`seedsmith-content-standard` Task 4b) to catch the reverse direction.

⛔ **The defect this exists for.** 83/84 drafts passed every other tier-2 check, and **87% were
code-switched**: English prose with Chinese motif tokens spliced in —
*"When a 僵尸 enters the fray, the squad attempts to force a 变心..."*.

**We caused it.** `motif_coverage` requires the subject's motifs VERBATIM; the motifs are Chinese;
the model's default register for this prompt was English. So it satisfied the checker by splicing.
The 8 drafts that came back wholly in Chinese read markedly better.

That is the "a pass rate is not quality" thesis demonstrated at scale — and the right response is a
CHEAPER instrument, not a model-based one: this is mechanically checkable, so it belongs in tier 2.

⛔ **The second, opposite defect this now also exists for (found 2026-09-08, `seedsmith-content-
standard` audit).** A committed dungeon event
(`gk-data/packs/fusion/data/seed/dungeon/events/event.bargain-creature.allpeater-001.json`) has real, shipped English
motifs, yet its own `flavor` field contains stray Chinese fragments mid-English-sentence — the
ORIGINAL check's own guard clause (`if not motifs or not any(<the CJK range>.search(m) for m in
motifs): return []` — the range itself was removed by `script-check`, NS7) cannot see this, because it only ever fires when the subject's own INPUT motifs are
Chinese. A model can code-switch either direction regardless of which language the brief itself
used, so the check below now runs UNCONDITIONALLY on every draft — it no longer needs `context` to
decide whether to look at all, only (optionally) to phrase which language the value should have
been consistently written in.
"""
from __future__ import annotations

import re
from typing import Any, Mapping

from .scripts import is_cjk_side

__all__ = ["language_consistency"]

#: 3+ Latin letters — ignores incidental initialisms and punctuation.
_LATIN_WORD = re.compile(r"[A-Za-z]{3,}")


def _has_cjk(text: str) -> bool:
    """The CJK side of the mixing rule, per CHARACTER (spec-script-check.md §4). The old test was one
    regex range, U+4E00–9FFF, which cannot see Extension A/B, compatibility ideographs, ideographic
    punctuation, kana, Hangul or fullwidth letters — the exact gaps that let 53 of 54 committed Delve
    events ship with Han characters in `name`/`flavor`."""
    return any(is_cjk_side(ch) for ch in text)


def language_consistency(draft: "Mapping[str, Any]", context: "Mapping[str, Any]") -> "list[str]":
    """Reject any value mixing CJK and Latin prose, regardless of which language the subject's own
    motifs used.

    Two directions, one mechanical check (`_has_cjk(value) and _LATIN_WORD.findall(value)` is
    symmetric — it does not care which script arrived first): CJK motifs, English-contaminated
    output (the original 2026-09-01 incident, `commander_effect.py`) and English motifs, CJK-
    contaminated output (the 2026-09-08 dungeon defect, above). `context["motifs"]` is read only to
    phrase the message; an ALL-LATIN corpus with no contamination is still unaffected, so this
    stays a general validator, not a creatures- or CJK-specific one.

    The CJK side is detected by `scripts.is_cjk_side`'s per-character classifier, not the old single
    range (spec-script-check.md §4): behaviour is otherwise identical, so the existing tests stay
    green, but kana, Hangul, Extension A and ideographic punctuation now count."""
    motifs = [m for m in (context.get("motifs") or []) if m]
    motif_language = "Chinese" if any(_has_cjk(m) for m in motifs) else "the subject's language"

    defects: "list[str]" = []
    for name, value in draft.items():
        if not isinstance(value, str) or not value.strip():
            continue
        latin = _LATIN_WORD.findall(value)
        if _has_cjk(value) and latin:
            defects.append(
                f"field {name!r} mixes Chinese and English prose (e.g. {latin[0]!r}) — "
                f"write the whole value in {motif_language}, consistently")
    return defects
