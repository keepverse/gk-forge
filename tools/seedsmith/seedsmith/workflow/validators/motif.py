"""Motif validators — the two that forced a repair in the real 8-creature run.

⛔ **Matching is script-aware** (spec-dungeon-generator-repair.md §2). The original check was a
case-SENSITIVE SUBSTRING match: correct for Chinese motifs, wrong for the English glosses the Delve
event brief now carries — `Ash` would miss `ash`, and `ash` would falsely match `crash` (the word-list
failure AI Dungeon shipped). A motif whose every character classifies as `latin`/`digit` now matches
case-insensitively on word boundaries; any other motif keeps the substring match, so the Chinese-motif
consumers (commander effects, tree nodes) behave exactly as before.
"""
from __future__ import annotations

import re
from typing import Any, Mapping

from .scripts import ScriptClass, script_of

__all__ = ["motif_coverage", "anti_motif_violation", "_text_of", "is_latin_motif", "motif_matches"]


#: The classes a motif may consist of to be matched as a Latin WORD. `common` (spaces, ASCII
#: punctuation, dashes) is included on purpose: a hyphen carries no script, and "no character outside
#: latin/digit/common" is this program's own accepted set for English text (spec §2's brief test).
_LATIN_MOTIF_CLASSES = frozenset({ScriptClass.LATIN, ScriptClass.DIGIT, ScriptClass.COMMON})


def _text_of(draft: "Mapping[str, Any]") -> str:
    """All string values concatenated — a motif may legitimately land in any prose field."""
    return " ".join(str(v) for v in draft.values() if isinstance(v, str))


def is_latin_motif(motif: str) -> bool:
    """True when every non-space character of `motif` is `latin`, `digit` or `common`
    (per `script-check`'s classifier) — i.e. an English/ASCII motif rather than a Chinese one."""
    classes = {script_of(ch) for ch in motif if not ch.isspace()}
    return bool(classes) and classes <= _LATIN_MOTIF_CLASSES


def motif_matches(motif: str, blob: str) -> bool:
    """Word-bounded and case-insensitive for a Latin motif; the original substring match otherwise."""
    if not motif:
        return False
    if is_latin_motif(motif):
        return re.search(r"\b" + re.escape(motif) + r"\b", blob, re.IGNORECASE) is not None
    return motif in blob


def motif_coverage(draft: "Mapping[str, Any]", context: "Mapping[str, Any]") -> "list[str]":
    """Reject output using NONE of the subject's motifs.

    This is the check that produced `attempts: 2` in the probe: the first draft ignored the motifs,
    was rejected mechanically, and the retry complied. ⚠️ It proves USE, never GOOD use — see the
    package docstring."""
    motifs = [m for m in (context.get("motifs") or []) if m]
    if not motifs:
        return []
    blob = _text_of(draft)
    if any(motif_matches(m, blob) for m in motifs):
        return []
    return [f"uses none of the subject's motifs {list(motifs)} — at least one must appear"]


def anti_motif_violation(draft: "Mapping[str, Any]", context: "Mapping[str, Any]") -> "list[str]":
    """Reject output using a word the subject is defined AGAINST.

    The hardest constraint measured (a NEGATIVE instruction); it held 0/8 violations."""
    blob = _text_of(draft)
    return [f"uses anti-motif {a!r}, which this subject is defined against"
            for a in (context.get("antiMotifs") or []) if a and motif_matches(a, blob)]
