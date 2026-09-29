"""seedsmith.adapters.trees.species.prompts — the codex-summary and favour-fit briefs (task J8,
spec-species-tree.md §3.1 step 3, §6).

**Why the codex brief hands the model the mechanical favour triple directly, in full, rather than a
softened paraphrase**: §6's own contract is *"what building into this bloodline rewards, in the
player's words"* — the model's whole job is the TRANSLATION from mechanism to player language, so
withholding the mechanism would leave it guessing at the very thing it is meant to translate. The
system prompt is what forbids the mechanical vocabulary from leaking into the OUTPUT; the input is
allowed, even expected, to be exact.

**The favour-fit brief is the one real judgement call D17 locks against an open enum**: the model
never picks a favour freely — it only ever answers "does the offered one fit, does one of these few
alternates fit instead, or does none of them" (§3.1 step 3's own wording, quoted verbatim in the
brief below), and `schemas.favour_fit_schema` makes every other answer structurally unsampleable.
"""
from __future__ import annotations

from typing import Any, Mapping, Sequence

from .plan import FavourCell
from .roster import SpeciesAnchor

CODEX_SYSTEM_PROMPT = (
    "You write ONE sentence for a creature's Codex entry, describing what building a character "
    "around this creature's own passive tree REWARDS. You do not describe what the creature IS — "
    "that is already written elsewhere and is not your job. Speak to the player, in plain words, "
    "about the payoff of investing in this specific bloodline. Never write a number. Never name a "
    "stat, a channel, an aptitude, an element, a status, or any other mechanics term by its game "
    "name — translate the mechanism into what it means for how the player plays."
)


def build_codex_context(anchor: SpeciesAnchor, favour: FavourCell) -> "dict[str, Any]":
    """Read-only inputs the brief needs — the anchor's own thematic fields (§4's own table: *"what
    this creature is"*) plus the PLANNER-assigned mechanical lock (§4: *"what building into this
    species rewards"*), kept as two separate groups in the context exactly as they are two separate
    fields on the record, never merged before the model sees them."""
    return {
        "speciesId": anchor.species_id,
        "elementPrimary": anchor.element_primary,
        "aptitudePrimary": anchor.aptitude_primary,
        "posture": anchor.posture,
        "traits": list(anchor.traits),
        "reason": anchor.reason,
        "favourAptitude": favour.aptitude,
        "favourElement": favour.element,
        "favourStatus": favour.status,
    }


def build_codex_brief(context: "Mapping[str, Any]") -> str:
    lines = [f"Creature: {context['speciesId']}"]
    if context.get("reason"):
        lines.append(f"What it is: {context['reason']}")
    if context.get("traits"):
        lines.append(f"Traits: {', '.join(context['traits'])}")
    lines.append(
        f"This species' mechanical favour (what building into it rewards) is locked to: "
        f"aptitude={context['favourAptitude']}, element={context['favourElement']}, "
        f"status={context['favourStatus']}.")
    lines += [
        "",
        "Write ONE sentence, at most 140 characters, describing what a player gets by building "
        "into this bloodline. No numbers. No mechanics terms by name.",
    ]
    return "\n".join(lines)


FAVOUR_FIT_SYSTEM_PROMPT = (
    "You judge whether a mechanical build-favour assignment (an aptitude + element + status "
    "triple) can be justified for a creature. This is creative game design, not a literal lore "
    "fact-check — a loose, reframed or metaphorical connection is enough. A shy, defensive "
    "creature can favour an aggressive aptitude if its true strength is overwhelming force once "
    "provoked; an earth-themed creature can favour fire if its passive channels volcanic or "
    "geothermal heat. You are given ONE offered favour and a short list of ALTERNATES — every "
    "option you may choose is already listed; you never invent a different favour. Answer "
    "\"offered\" whenever the offered favour can be reasonably justified, even with some "
    "narrative stretch — this should be your answer most of the time. Otherwise, answer the EXACT "
    "key of the one alternate that fits at least as well. Reserve \"none\" for the rare case where "
    "EVERY listed option is actively contradictory or absurd for this creature, not merely "
    "imperfect — most creatures should find a real fit among the options given."
)


def build_favour_fit_context(
    anchor: SpeciesAnchor, offered: FavourCell, alternates: "Sequence[FavourCell]",
) -> "dict[str, Any]":
    """§3.1 step 3's own three inputs: the offered cell, its alternates (already inside the
    quota — `species.plan.assign_favour_cells`'s own output), and the species' own lore. Every
    alternate is carried by its OWN key (`FavourCell.key()`), the exact string the schema's enum
    and the model's own answer must agree on — never re-derived from a description at judge time.
    """
    return {
        "speciesId": anchor.species_id,
        "elementPrimary": anchor.element_primary,
        "aptitudePrimary": anchor.aptitude_primary,
        "posture": anchor.posture,
        "traits": list(anchor.traits),
        "reason": anchor.reason,
        "offeredKey": offered.key(),
        "offered": {"aptitude": offered.aptitude, "element": offered.element, "status": offered.status},
        "alternateKeys": [a.key() for a in alternates],
        "alternates": [{"key": a.key(), "aptitude": a.aptitude, "element": a.element,
                       "status": a.status} for a in alternates],
    }


def build_favour_fit_brief(context: "Mapping[str, Any]") -> str:
    lines = [f"Creature: {context['speciesId']}"]
    if context.get("reason"):
        lines.append(f"What it is: {context['reason']}")
    if context.get("traits"):
        lines.append(f"Traits: {', '.join(context['traits'])}")
    offered = context["offered"]
    lines.append(
        f"OFFERED favour (answer \"offered\" if this can be justified, even loosely): "
        f"aptitude={offered['aptitude']}, element={offered['element']}, status={offered['status']}")
    for alt in context["alternates"]:
        lines.append(
            f"ALTERNATE {alt['key']}: aptitude={alt['aptitude']}, element={alt['element']}, "
            f"status={alt['status']}")
    lines += [
        "",
        "Can the OFFERED favour be reasonably justified for this creature, even with some "
        "narrative stretch? If so, answer \"offered\" — most creatures should. If not, does one "
        "of the ALTERNATES fit at least as well — name its exact key? Only if EVERY option is "
        "actively contradictory or absurd, answer \"none\".",
    ]
    return "\n".join(lines)
