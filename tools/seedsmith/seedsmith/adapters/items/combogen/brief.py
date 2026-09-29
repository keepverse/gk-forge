"""seedsmith.adapters.items.combogen.brief — aptitude semantics from the roster; ⛔ never "runeword".

**Motifs and readings inline, no citation text.** `briefkit`'s discipline: a brief carries the closed
vocabularies the model must choose from and the theme's own words, and nothing else — a citation
teaches the model to write about the document instead of the content.

Three things this brief deliberately does NOT contain, each because putting it there would break a
rule this module is built on:

- **any number** — no tier, no magnitude, no socket count, no ingredient count spelled as a digit
  the model could echo back. The schema fixes the ingredient array at exactly four items; the brief
  says "the ingredients listed below", and the count is the array's own length.
- **any element** — the twelve aptitudes do not map to the six elements and nothing here invents
  one. D22-as-amended keys the bonus on each ingredient gem's own element, which the model never
  chooses.
- **the banned word** — asserted, not intended: `build_brief` scans its own output before returning.
"""
from __future__ import annotations

import re

from .grid import Cell, scan_for_banned_word
from .supply import SupplyReport
from .tuning import ComboTuning
from ..naming_grammar import NAMING_GRAMMAR_RULES

#: Bumped 2->3 (item-seed-regen cause 3, 2026-09-20): now states naming.v1.json's naming grammar.
PROMPT_VERSION = "strain-splice-gen/3"


class BriefRefused(ValueError):
    """The assembled brief broke one of the rules above. Raised rather than logged: a brief is the
    one artefact that reaches the model, so a defect in it is a defect in every entry it produces."""


def _supply_lines(supply: SupplyReport, limit: int) -> str:
    shown = supply.families[:limit]
    lines = [f"  - {f}  (gems at: {', '.join(supply.bands[f])})" for f in shown]
    if len(supply.families) > limit:
        lines.append(f"  - ...and {len(supply.families) - limit} more")
    return "\n".join(lines)


def _strain_reading_lines(cell: Cell) -> str:
    """Aptitude meaning always; offense-shaped `reading` only on the offense archetype.

    Defense/balance themes still carry the roster's global reading (e.g. Might → "Hit harder.") and
    often `antiMotifs: ["offense"]`. Pasting both into one brief invites a coherent `blocked`. Frame
    non-offense cells as posture over the aptitude, and omit the offense-shaped play reading so it
    cannot contradict `Avoid entirely: offense`.
    """
    apt = cell.aptitudes[0]
    lines = [f"What '{apt.id}' means: {apt.meaning}"]
    if cell.archetype == "offense":
        lines.append(f"What it reads as in play: {apt.reading}")
    else:
        lines.append(
            f"This cell's archetype is '{cell.archetype}' — express '{apt.id}' through that "
            f"posture (mitigation, sustain, or balanced commitment), not as a demand to grant "
            f"offense.")
    return "\n".join(lines)


def _identity_block(cell: Cell) -> str:
    if cell.combination_kind == "strain":
        apt = cell.aptitudes[0]
        return (
            f"a STRAIN — a single cultivated line of the '{apt.id}' aptitude, expressed through "
            f"the '{cell.archetype}' archetype.\n"
            f"{_strain_reading_lines(cell)}")
    lo, hi = cell.aptitudes
    return (
        f"a SPLICE — two cultivated lines fused, '{lo.id}' with '{hi.id}'. Splicing is the base "
        f"game's own verb; the result belongs to neither parent.\n"
        f"What '{lo.id}' means: {lo.meaning}  ({lo.reading})\n"
        f"What '{hi.id}' means: {hi.meaning}  ({hi.reading})\n"
        f"Opposing or tensioned readings across the two parents are the fusion's material — "
        f"author a mechanism that bridges them; do not refuse the cell merely because the "
        f"readings pull apart.")


def build_brief(cell: Cell, tuning: ComboTuning, supply: SupplyReport, *,
                granted_families: "tuple[str, ...]",
                host_roles: "tuple[str, ...]",
                supply_limit: int = 40, granted_limit: int = 60) -> str:
    """One combination, one grid cell."""
    anti = (f"\nAvoid entirely: {', '.join(cell.anti_motifs)}." if cell.anti_motifs else "")
    text = f"""Author ONE socket combination: {_identity_block(cell)}

Motifs to express: {', '.join(cell.motifs)}.{anti}

A combination is what a player gets for filling an item's sockets with the right set of inserts. It
is a PLAN, not a lottery: a cheap base of the right role, its sockets opened by crafting, and the
inserts collected on purpose. So it must grant a MECHANISM — a proc, a rider, a spawn, a new
behaviour — never simply more of the stat its own ingredients already carry. That is the difference
between a combination and a volume discount with a name.

Choose, and nothing else:
1. `ingredients` — the gem families whose inserts assemble this combination, from the closed list
   below. The array's length is fixed; repeats are allowed and mean "more than one of that family".
   Order does not matter and is not recorded: the recipe is matched as an unordered collection.
2. `grants` — one or two atom families this combination grants, from the second list.
3. `hostRole` / `hostFrame` — omit either to leave it open. Naming a role pins the combination to
   that chassis; only the roles listed can hold this many inserts at all.
4. `name`, `flavor`. (`nameKey` is not yours to pick — it is minted from this cell, the same way
   the corpus's own id is.)

{NAMING_GRAMMAR_RULES}

Never choose a number, a strength, a duration or a tier. Those are resolved after you answer.

Ingredient families a live gem can actually supply ({supply.family_count} of them, from \
{supply.gem_count} shipped gems):
{_supply_lines(supply, supply_limit)}

Grantable atom families ({len(granted_families)}):
{chr(10).join('  - ' + f for f in granted_families[:granted_limit])}\
{chr(10) + '  - ...and ' + str(len(granted_families) - granted_limit) + ' more'
 if len(granted_families) > granted_limit else ''}

Legal host roles: {', '.join(host_roles)}.

If this cell cannot carry a combination you would be happy to ship, set `blocked` and say why."""

    banned = scan_for_banned_word(text)
    if banned:
        raise BriefRefused(
            f"the assembled brief contains {banned} — ⛔ D20 bans that word in prompts as well as "
            f"in ids, because a model shown the word once will use it in every name it returns")
    spelled = spells_the_count(text, tuning.ingredient_count)
    if spelled:
        # Not cosmetic: a brief that spells the ingredient count invites the model to reason about
        # "four" as a number it may adjust. The schema already fixes the array length, which is the
        # enforcement; keeping the count out of the prose is what stops the two disagreeing.
        raise BriefRefused(
            f"the assembled brief spells the ingredient count as {spelled}; the schema's fixed "
            f"array length is the enforcement and the prose must not restate it")
    return text


#: English for the counts a `structuralCeiling` of 4 can reach, plus headroom. A brief that writes
#: "four ingredients" is exactly as much of a second source of truth as one that writes "4".
_NUMBER_WORDS: "dict[int, str]" = {
    1: "one", 2: "two", 3: "three", 4: "four", 5: "five",
    6: "six", 7: "seven", 8: "eight", 9: "nine", 10: "ten",
}

#: A markdown-style enumeration marker at the start of a line (`1.`, `2.`, …). Stripped before the
#: scan below: the brief's own numbered instruction list is not a claim about the ingredient count,
#: and a check that cannot tell the two apart refuses every brief it is given (found by running it).
_ENUMERATION_RE = re.compile(r"^\s*\d+\.\s", flags=re.MULTILINE)


def spells_the_count(text: str, count: int) -> "list[str]":
    """Every place `text` states `count` in prose, as digits or as an English word. Empty = clean."""
    prose = _ENUMERATION_RE.sub("", text)
    hits = [m.group(0) for m in re.finditer(rf"\b{count}\b", prose)]
    word = _NUMBER_WORDS.get(count)
    if word:
        hits += [m.group(0) for m in re.finditer(rf"\b{word}\b", prose, flags=re.IGNORECASE)]
    return hits
