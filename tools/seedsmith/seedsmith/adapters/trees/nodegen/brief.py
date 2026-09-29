"""seedsmith.adapters.trees.nodegen.brief — the per-node §6.2 brief; permutation seeded from
`nodeId|field|sampleIndex` (task H1, spec-tree-language.md §6.2).

Follows `setgen/brief.py:48-85`'s anatomy (the spec's own citation) with its two deliberate
omissions: **any number**, and **any option outside the permitted subset**. Two things this text
deliberately does NOT contain, mirroring `items/setgen/brief.py`'s own opening paragraph almost
word for word:

- **any number** — no tier, no potency, no budget share. `tier_to_depth` renders the ONLY size/depth
  signal this stage ever sees as a label (`shallow | mid | deep`), never `tier: 5` — the same "a
  number that must be conveyed is rendered as a label" rule `family_propose/prompts.py:193-197`
  states for its own bands.
- **any option outside the permitted subset** — `render_brief` takes the ALREADY-narrowed
  `permitted_affixes`/`permitted_properties` as arguments; it does not itself decide what is legal,
  because that decision is `quota.py`/H3's, read once and rendered here, never re-derived.

**Permutation is verified, not trusted.** `order_for` (`creatures.anchor.permute`) is reused directly
rather than reimplemented — `verify_permutation` (`actions.validate_heal.derive`) is the gate that
later re-derives the same order and raises if a rendered brief does not reproduce it; this module's
job is only to call `order_for` with the right seed, `nodeId|field|sampleIndex` exactly as the
module docstring names it.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from ..plan.archetypes import TIER_COUNT
from ...creatures.anchor.permute import order_for
from ....briefkit.avoid_list import render_avoid_line
from .vocab import AffixOption

__all__ = [
    "PROMPT_VERSION",
    "SYSTEM_PROMPT",
    "DepthBand",
    "SiblingSummary",
    "tier_to_depth",
    "permuted_affix_ids",
    "permuted_property_keys",
    "render_brief",
]

# tree-language/2 (2026-09-07): item 3's "Prefer reroute" opening clause became the measured
# defect — 1638/1677 committed nodes at `reroute` with the identical propertyKeys. Reworded so
# "MOST NODES HAVE NONE" governs; provenance-split for the committed corpus (see render_brief's
# own comment).
# tree-language/3 (2026-09-11, A2): item 3 is now per-cell — the schema's `exclusion.form` enum
# is narrowed to the node's own quota-cell allocation (§4.2 step 6), the gate enforces the same
# set per response, and the brief states the allocation ("Your quota cell ..."). A `none` cell
# offers only `none`; a designated cell offers its rung plus the honest `none` default.
# 2026-09-11 (A2): item 3 became per-cell — the brief now names the node's own quota-cell
# exclusionForm allocation (three-way: legacy-no-cell / none-cell / designated), matching the
# schema enum's per-call narrowing (`schema_for_call(exclusion_forms=...)`) and the gate's own
# per-response check (`build_response_gate(permitted_exclusion_forms=...)`). All three now say what
# §4.2 step 6 says: the cell IS the enum. The `tree-language/2` corpus (1638/1677 at `reroute`) is
# distinguishable from this vintage by this stamp alone.
# tree-language/4 (2026-09-24, ip-censor T16/IC-4.1): the brief now carries the rendered IP
# avoid-list as its OWN line (a separate line from the motif "Avoid entirely:" line), so the model is
# told the third-party spellings to never use. The list is the shared `briefkit.avoid_list` helper's
# reading of the committed registry; it is passed in by the caller (`avoid_terms`), so this module
# still decides nothing about what is forbidden.
PROMPT_VERSION = "tree-language/4"

#: §6.2's SYSTEM block, verbatim — every negative clause here also lives in the schema (§7 gate 2 /
#: `schema.py`'s own field descriptions), per `family_propose/prompts.py:40-44`'s rule that a
#: description living only in prose beside a schema is a description the audit cannot read.
SYSTEM_PROMPT = (
    "You author ONE passive skill node for a build tree. You never write a number: not a "
    "strength, not a duration, not a chance, not a tier — tables you never see decide every "
    "magnitude. You never invent an effect id, an element, a status or a channel; you pick from "
    "the lists given, or you set `blocked`. You never name another node — an exclusion keys on "
    "a PROPERTY, never on a name."
)

#: `shallow | mid | deep` — §2.1's own reasoning restated for this exact label: the model never
#: sees a tier number, and this is the ONLY size/depth signal it ever receives.
DepthBand = str


def tier_to_depth(tier: int, tier_count: int = TIER_COUNT) -> DepthBand:
    """Splits `1..tier_count` into three roughly-equal thirds. Deterministic and total — every
    tier maps to exactly one band, and the boundaries never depend on which tree is asking."""
    if not (1 <= tier <= tier_count):
        raise ValueError(f"tier {tier} is outside 1..{tier_count}")
    third = tier_count / 3.0
    if tier <= third:
        return "shallow"
    if tier <= 2 * third:
        return "mid"
    return "deep"


@dataclass(frozen=True)
class SiblingSummary:
    """One already-accepted tier sibling, named and summarised — never cited, never quoted in
    full — per `distribution_planner/derive.py:516-522,576`'s `accepted_neighbours` precedent this
    module's own spec section names by file:line."""

    node_id: str
    name: str
    affix_ids: "tuple[str, ...]"


def permuted_affix_ids(node_id: str, sample_index: int,
                       permitted: "Sequence[AffixOption]") -> "list[AffixOption]":
    """§6.2's "permuted" clause for the legal-effects list, seeded `nodeId|"affixIds"|sampleIndex`.
    `verify_permutation` re-derives this exact order from the recorded sample and raises on a
    mismatch — this function's only job is to call `order_for` with the right three-part seed."""
    by_id = {o.affix_id: o for o in permitted}
    order = order_for(node_id, "affixIds", sample_index, list(by_id))
    return [by_id[i] for i in order]


def permuted_property_keys(node_id: str, sample_index: int,
                           permitted: "Sequence[str]") -> "list[str]":
    return order_for(node_id, "exclusionPropertyKeys", sample_index, list(permitted))


def render_brief(*, node_id: str, sample_index: int, tree_display_name: str, tree_reading: str,
                 branch: str, tier: int, node_class: str, motifs: "Sequence[str]",
                 anti_motifs: "Sequence[str]", permitted_affixes: "Sequence[AffixOption]",
                 permitted_properties: "Sequence[str]",
                 siblings: "Sequence[SiblingSummary]" = (), tier_count: int = TIER_COUNT,
                 exclusion_form: "str | None" = None,
                 avoid_terms: "Sequence[str]" = ()) -> str:
    """The full §6.2 USER block for one node. Every list argument is ALREADY the permitted subset
    (H3's job to narrow); this function only orders and renders it.

    `exclusion_form` (2026-09-11, A2) is the node's OWN quota-cell allocation for the exclusion
    axis — `None` when the caller did not resolve a cell (a legacy record, or a caller that does
    not resolve cells), `"none"` for a none-allocated cell, or the designated rung. It renders a
    per-node "Your quota cell" line rather than a generic exhortation, so the brief, the schema
    enum and the gate all say the same thing the cell says (§4.2 step 6).
    """
    if branch not in ("offensive", "defensive"):
        raise ValueError(f"branch must be 'offensive' or 'defensive', got {branch!r}")
    if node_class not in ("mechanism", "magnitude"):
        raise ValueError(f"node_class must be 'mechanism' or 'magnitude', got {node_class!r}")

    depth = tier_to_depth(tier, tier_count)
    affixes = permuted_affix_ids(node_id, sample_index, permitted_affixes)
    properties = permuted_property_keys(node_id, sample_index, permitted_properties)
    # 2026-09-07 real-corpus finding (`check --family PassiveTree --gate`, run for the first time
    # against the full 42-tree/1677-node committed corpus once the CLI finally wired real nodes into
    # this family's own metrics): `PassiveTree/ExclusionRate` measured 1638/1677 nodes (97.7%) at
    # form `reroute`, EVERY one with the identical propertyKeys=['posture'] and the identical
    # template-composed printedText -- against a committed target of <=30 per mille. The exclusion
    # object itself was legal every time (`validate_exclusion` never flagged one; a bare axis name is
    # spec-legal per `exclusion.py`'s own resolved D14/§5 ambiguity), so this was never a schema or
    # validation defect -- it was this brief's own wording. The old text opened item 3 with "Prefer
    # `reroute`. Most nodes have none." -- read by the model as an instruction to reach for `reroute`
    # by default, with "most nodes have none" landing as a mid-sentence aside rather than the actual
    # governing rule. Reworded so the FIRST clause states the rule ("MOST NODES HAVE NONE... only if
    # ... genuinely, concretely conflicts"), and "prefer reroute over nullification" is now clearly
    # scoped to the "if you do use one" branch, never the default. `PROMPT_VERSION` bumped to
    # `tree-language/2` so newly-generated content is distinguishable in provenance from the
    # already-committed corpus above, which this fix does NOT retroactively regenerate (a corpus-wide
    # re-roll is real machine time / model calls, the same "code fix now, run later" split this
    # program already holds to for J1/J9's own production passes) -- named in
    # `tasks/passive-tree-todo.md`, not silently left unrecorded.

    motif_line = ", ".join(motifs) if motifs else "(none named)"
    anti_line = f"\n  Avoid entirely: {', '.join(anti_motifs)}." if anti_motifs else ""
    # The IP avoid-list (ip-censor T16/IC-4.1) is a SEPARATE line from the motif `Avoid entirely:`
    # line above — different axis (third-party spellings vs this tree's anti-motifs), so a model never
    # reads one as the other. Empty terms render nothing, so a caller that passes no list is unchanged.
    ip_avoid_line = render_avoid_line(avoid_terms)
    ip_avoid_block = f"\n{ip_avoid_line}" if ip_avoid_line else ""
    affix_lines = "\n".join(f"    - {a.one_line}" for a in affixes)
    property_line = ", ".join(properties) if properties else "(no properties open on this tree)"
    sibling_lines = "\n".join(
        f"    - {s.name} ({', '.join(s.affix_ids)})" for s in siblings
    ) or "    (none yet)"
    # 2026-09-06 real-call finding (`might`, multiple tier-1 through tier-7 nodes, LM Studio local
    # model): the original one-line gloss ("makes an existing thing larger") was read by the model as
    # "there must already be a node in THIS TREE to reference" -- most real blocks quoted some variant
    # of "no existing effect/property in the current tier/context." Per spec-tree-plan.md's own formal
    # definition (§ "MAGNITUDE node ≔ every bound atom has AttachPoint.Stat AND kind ∈ {stat.modify,
    # stat.derived} AND conditionality == 1"), "an existing thing" means an existing GAME STAT/EFFECT
    # -- one of the entries in "Legal effects" below, which is ALREADY narrowed to stat-kind affixes
    # for a magnitude node by the plan's own quota cell -- never a sibling node this tree has or has
    # not generated yet. The clarification below states that explicitly rather than leaving the model
    # to infer it; it does not change what a magnitude node IS, only removes real, measured ambiguity
    # in how that definition was worded for a model to read.
    class_note = (
        "a MECHANISM node grants something the resolver does not otherwise have."
        if node_class == "mechanism" else
        "a MAGNITUDE node makes one of the effects below — an EXISTING game stat, always available, "
        "never a node this tree has or has not generated yet — scale with level. Picking an effect "
        "from the list IS naming the existing thing; nothing else needs to exist first."
    )

    # 2026-09-11 (A2): item 3's text is now per-cell (the three-way split below) instead of a
    # generic exhortation — the brief, the schema enum and the gate all say what the cell says.
    if exclusion_form is None:
        exclusion_line = (
            "  3. `exclusion` — MOST NODES HAVE NONE. Only set a form at all if this node's effect\n"
            "                   genuinely, concretely conflicts with one of the properties below — not\n"
            "                   because a property happens to be available to name. If (and only if) a\n"
            "                   real conflict exists, prefer `reroute` over `nullification`; the latter\n"
            "                   is the last resort, for when the pair can be neither rerouted nor\n"
            "                   ordered. If you use it, say plainly which side wins in `rationale` —\n"
            "                   never in `blocked`, which is reserved for declining to answer this brief\n"
            "                   at all.")
    elif exclusion_form == "none":
        exclusion_line = (
            "  3. `exclusion` — Your quota cell allocates `none` for this node: no exclusion. Fill\n"
            "                   `form` with `none` and `propertyKeys` with an empty list. This is the\n"
            "                   normal case — most nodes never leave it.")
    else:
        exclusion_line = (
            "  3. `exclusion` — Your quota cell designates THIS node for a real exclusion: the\n"
            f"                   only non-none form your enum offers is {exclusion_form!r}. If (and only\n"
            "                   if) a genuine, concrete conflict with one of the properties below actually\n"
            "                   exists, take that rung and name the properties in `propertyKeys`; if none\n"
            "                   does, stay at `none` — the cell narrows your choice, it never forces you\n"
            "                   to invent a conflict. Say plainly which side wins in `rationale` — never\n"
            "                   in `blocked`, which is reserved for declining to answer this brief at all.")

    return f"""Tree: {tree_display_name}{f" — {tree_reading}" if tree_reading != tree_display_name else ""}
Branch: {branch}.  Depth: {depth}.
This node must be a {node_class} node.
  - {class_note}

Motifs to express: {motif_line}.{anti_line}{ip_avoid_block}

Choose, and nothing else:
  1. `affixIds`  — 1 to 3 from the list below. They are this node's whole effect.
  2. `affinity`  — one entry PER chosen effect, in the same order as `affixIds` and the same
                   length: core | likely | occasional.
{exclusion_line}
  4. `name`, `nameKey`, `flavor`.

Never choose a number, a strength, a duration or a tier. Those are resolved after you answer.

Legal effects ({len(affixes)}):
{affix_lines}

Legal exclusion properties: {property_line}

Already written in this tier — do not repeat:
{sibling_lines}

If this brief cannot carry a node you would be happy to ship, set `blocked` and say why."""
