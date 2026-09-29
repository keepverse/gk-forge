"""seedsmith.adapters.items.setgen.brief — theme + aptitude + archetype → a brief.

**Motifs inline, no citation text.** `briefkit`'s own discipline: a brief carries the closed
vocabularies the model must choose from and the theme's own words, and nothing else — a citation
teaches the model to write about the document instead of the content.

Two things this brief deliberately does NOT contain, each because putting it there would break P1:

- **any number** — no tier, no magnitude, no per-mille, no AE budget. The model is not being asked
  to respect a budget; the distributor enforces it afterwards. Telling the model the budget invites
  it to reason numerically, which is the exact habit `audit_schema` exists to prevent.
- **any role outside the twelve** — the cap is applied here, in the brief, by construction. The
  model is never shown `head-guard`, so `SetRoleNotUniversal` is unproducible from a well-formed
  answer (ssot-sets §3.7 fires at LOAD; ~1,000 sets checked after the fact is a re-run).
"""
from __future__ import annotations

from .distribute import legal_set_stat_pool, threshold_ladder
from .roles import HYBRID_CORE_ROLES
from .themes import Theme
from .tuning import SetCharmGenTuning
from .vocab import FamilyPick, Vocabulary
from ..charmgen.rules import charm_pool
from ..naming_grammar import NAMING_GRAMMAR_RULES

# Bumped 1->2 (item-seed-regen cause 3, 2026-09-20): both briefs below now state
# naming.v1.json's naming grammar explicitly. Every prior answer under version 1 authored `name`
# with no grammar constraint at all.
PROMPT_VERSION = "set-charm-gen/2"


def _core_roles(pick: FamilyPick) -> "tuple[str, ...]":
    """A family's roles, narrowed to the twelve before they reach the brief.

    ⚠ Found by a test: the shipped families list their legality on `head-guard` / `sense` /
    `ward-array` too, and printing that verbatim would put a dropped role in front of the model in
    the same document that tells it those roles do not exist. A family's legality on a role a set
    may never claim is not information the model can act on.
    """
    return tuple(r for r in pick.roles if r in HYBRID_CORE_ROLES)


def _pick_lines(picks: "tuple[FamilyPick, ...]") -> str:
    """The whole pool, whole and unannotated-by-truncation.

    ⛔ Real incident, 2026-09-08: this used to take a `limit` and truncate — printing the first
    40 of 69 capability picks and the first 60 of 265 stat picks, with a bare "...and N more"
    tail. A live 53-subject run escalated EVERY subject on the same defect shape: the model
    named a family (`atom.sparking`, `atom.econ-bounty`, `atom.sporing`, `atom.deathblast.omni`,
    ...) that was a REAL, valid pick in the full pool, just never shown to it. This is the exact
    defect class `_charm_pick_lines` was already rebuilt to fix (its own docstring: "a truncated
    pool is what produced the collapse this brief was rebuilt to fix") — it had never been
    applied here. No truncation, matching that precedent.
    """
    lines = []
    for p in picks:
        core = _core_roles(p)
        lines.append(f"  - {p.pick_id}" + (f"  (roles: {', '.join(core)})" if core else ""))
    return "\n".join(lines)


def _capability_pick_lines(picks: "tuple[FamilyPick, ...]") -> str:
    """The capability pool, grouped BY FAMILY, with each family's elements listed on its own line.

    ⛔ Real incident, 2026-09-08 (the shape that survived every earlier brief fix): `capability` is the
    ONLY field in the whole set/charm surface that asks for a split `{family, variant}` object —
    every stat and charm family is named by copying ONE plain string. So the list is printed grouped by
    family, one line per family, with its elements spelled out after the family id. A model can then
    not produce `family: "atom.deathblast.fire"` even by accident, because no such token appears in the
    list to copy: `atom.deathblast` is what it sees, and `fire` is one of the elements it may name.

    This is a correctness fix, not a presentation one. The schema's closed `family` enum is built by
    `capability_family_ids`, which returns UNIQUE BASE family ids (51 of them, none carrying an element
    suffix), and `answers.schema_defects` enforces that enum on the way in. Printing `p.pick_id` — which
    for an elemental pick IS `f"{family}.{variant}"` — therefore printed 21 of 69 picks in a spelling
    the schema refuses outright, while `seedfile.resolve_capability` (whose own docstring records this
    exact echo as "legal") never got to run, because the draft was already turned away at the door. The
    tolerant lookup that was written to accept the echo shape was unreachable behind a stricter schema.

    Output is unchanged either way: `seedfile._atom_row` writes `family`/`params.element` from the
    RESOLVED pick, never from the raw draft string, so this only decides which spellings can reach the
    resolver. Grouping also collapses 69 lines to 51.
    """
    lines: "list[str]" = []
    done: "set[str]" = set()
    for p in picks:
        if p.family in done:
            continue
        done.add(p.family)
        core = _core_roles(p)
        line = f"  - {p.family}" + (f"  (roles: {', '.join(core)})" if core else "")
        elements = [q.variant for q in picks if q.family == p.family and q.variant]
        if elements:
            line += "   elements: " + ", ".join(elements)
        lines.append(line)
    return "\n".join(lines)


def _charm_pick_lines(picks: "tuple[FamilyPick, ...]") -> str:
    """The charm pool, whole and unannotated.

    **No truncation.** A truncated pool is what produced the collapse this brief was rebuilt to
    fix: the old charm brief printed the first 60 of 242 stat picks, and the distributor accepted
    56 picks that were mostly outside that window. An offered list the author cannot see is the
    same defect as an offered list the distributor refuses.

    **No roles either.** A charm occupies no role and is frame-blind (ssot-charms §3.7), so a
    family's role legality is not something a charm author can act on — printing it invites the
    model to reason about a slot the container does not have.
    """
    return "\n".join(f"  - {p.pick_id}" for p in picks)


def _and_list(values: "tuple[int, ...]") -> str:
    if len(values) == 1:
        return str(values[0])
    return f"{', '.join(str(v) for v in values[:-1])} and {values[-1]}"


def _higher_sentence(higher: "tuple[int, ...]") -> str:
    """What the thresholds above the lowest carry — or that there are none.

    A one-threshold ladder is real (a two-member set), and a brief that assumed at least two is
    half of why a five-member set could not be authored at all.
    """
    if not higher:
        return "This set has no threshold above the lowest."
    return (f"Each of the others ({_and_list(higher)}) takes one to three stat families from the "
            f"second list.")


def build_set_brief(theme: Theme, tuning: SetCharmGenTuning, vocabulary: Vocabulary, *,
                    member_count: "int | None" = None) -> str:
    """One set, one theme. `member_count` defaults to the typical size; a grand set is the exception,
    not the pattern (ssot-sets §3.4), so it is always an explicit ask."""
    members = member_count or tuning.typical_members
    ladder = threshold_ladder(tuning, members)
    higher = ladder[1:]
    capability_pool = vocabulary.capability
    stat_pool = legal_set_stat_pool(vocabulary, tuning)
    identity = (f"the creature species '{theme.display_name}'" if theme.population == "species"
                else f"the build '{theme.display_name}' ({theme.aptitude} / {theme.archetype})")
    anti = (f"\nAvoid entirely: {', '.join(theme.anti_motifs)}." if theme.anti_motifs else "")
    lore = f"\nAdditional authored lore context: {theme.lore}" if theme.lore else ""
    return f"""Author ONE equipment set for {identity}.

Motifs to express: {', '.join(theme.motifs)}.{anti}{lore}
How this theme expresses itself in an item: {theme.expression_item}

Choose, and nothing else:
1. `capability` — exactly ONE family from the list below. **This is not optional.** A set with no
   capability is REFUSED, because a set that grants nothing is stat filler. There are exactly TWO
   valid answers to this question: one family from the list, or `blocked` with your reason. An empty
   `capability` on its own is not one of them - if you cannot pick a family, set `blocked` and say
   why, which is a real answer; leaving `capability` empty with no `blocked` is not. `family` takes a
   family id EXACTLY as the list prints it, and nothing else - no element suffix, ever, because
   `family` is closed over the family ids alone. Where a line offers `elements:`, name the one you
   want in `variant` (or leave `variant` empty if you want no element). **Read that `roles:` before you
   commit to a family, because it constrains the rest of your answer**: a family is only legal on a set
   that claims at least one of the roles it lists, and a family whose `roles:` your members do not
   cover is REFUSED (`SetCapabilityOffRole`) however good the set is otherwise. So pick a family whose
   `roles:` line contains a role you are willing to give a member. The three jewel roles -
   `jewel-major`, `jewel-minor-a`, `jewel-minor-b` - are legal on EVERY family in the list, so a set
   that claims any jewel role can never trip this. The family you
   pick is the set's identity and it sits at the set's LOWEST threshold, so a two-piece splash already
   gives the player the thing an ordinary item cannot roll.
2. `members` — {members} entries, each a (role, frame) pair. The role list below is closed and
   complete; at most one of armament-primary / armament-secondary, and no role twice.
3. `thresholds` — exactly {len(ladder)} entries, at {_and_list(ladder)} pieces. The piece counts are
   FIXED by the {members}-member size and are not yours to choose; give one entry for each, in that
   order. The lowest ({ladder[0]}) takes no families — it carries the capability. {_higher_sentence(higher)}
4. `name` — a short display name (1-4 words), and `flavor` — one sentence.

{NAMING_GRAMMAR_RULES}

Never choose a number, a strength, a duration or a tier. Those are resolved after you answer.
(There is no `nameKey` field to fill in — it is derived automatically from `name`.)

Legal member roles ({len(HYBRID_CORE_ROLES)}):
{chr(10).join('  - ' + r for r in HYBRID_CORE_ROLES)}

Capability families ({len(capability_pool)} picks):
{_capability_pick_lines(capability_pool)}

Stat families ({len(stat_pool)} picks):
{_pick_lines(stat_pool)}

If this theme cannot carry a set you would be happy to ship, set `blocked` and say why."""


def build_charm_brief(theme: Theme, tuning: SetCharmGenTuning, vocabulary: Vocabulary,
                      *, axis_hint: str | None = None, class_hint: str | None = None) -> str:
    """One charm, one theme. Charms are the always-on, side-wide layer.

    ⭐ **The pool is `charmgen.rules.charm_pool`, and that is the whole of defects 1 and 2.** This
    brief used to print `vocabulary.stat` — the SET's stat bucket, truncated to 60 of 242 picks —
    against a distributor that accepted 56 picks across 14 families, every one armour or shield.
    An `offense`, `control`, `utility` or `economy` charm was unauthorable from it, though those are
    four of the five shipped axes and 48 of the 70 shipped rows. The pool is now the same expression
    the distributor refuses against, drawn from both buckets, and printed whole.
    """
    anti = (f"\nAvoid entirely: {', '.join(theme.anti_motifs)}." if theme.anti_motifs else "")
    lore = f"\nAdditional authored lore context: {theme.lore}" if theme.lore else ""
    classes = ", ".join(c.id for c in tuning.charm_classes)
    pool = charm_pool(tuning, vocabulary.all_picks)
    axis_instruction = (f"\nDeterministic coverage assignment: use axis `{axis_hint}` for this subject."
                        if axis_hint else "")
    class_instruction = (f"\nDeterministic class assignment: use charmClass `{class_hint}` for this subject."
                         if class_hint else "")
    return f"""Author ONE charm for the creature species '{theme.display_name}'.

Motifs to express: {', '.join(theme.motifs)}.{anti}{lore}
How this theme expresses itself in an item: {theme.expression_item}

A charm is carried by the commander, not worn by one actor: it is always on, it applies to every
deployed actor, and it buys that breadth with depth. So it carries FLAT effects only — never a
percentage, never a multiplier.

Choose, and nothing else:
1. `charmClass` — one of: {classes}. Use the assigned class when one is provided. A signet is named,
   carries a drawback, and rolls nothing.{class_instruction}
2. `axis` — one of offense, survivability, control, utility, economy. Pick the assigned axis when
   one is provided; otherwise pick the one this species actually leans into.{axis_instruction}
3. `frameHint`, `families` (one or two always-on families from the list below), `name`, `flavor`.
   A signet also names its `drawback` family.
   `name` must be a new, specific surface name for this species; do not reuse a generic name
   such as a familiar weapon/material phrase or any name you have seen in another item.

{NAMING_GRAMMAR_RULES}

Never choose a number, a cost, a strength or a tier. Those are resolved after you answer.
(There is no `nameKey` field to fill in — it is derived automatically from `name`.)

The list below is the WHOLE legal pool — every id in it is accepted, and nothing outside it is.
Copy an id exactly as printed, including the element suffix where one is shown.
Do not prepend `atom.` to an id that already starts with `atom.` (for example, write
`atom.death-salvo`, never `atom.atom.death-salvo`).

Always-on families ({len(pool)} picks):
{_charm_pick_lines(pool)}

Decision rule for difficult motifs: do not block merely because the motif suggests a projectile,
trigger, multiplier, or narrative mechanic. Choose the closest legal always-on FLAT family and
let the deterministic planner enforce its magnitude and tier rules. Set `blocked` only when no
legal family/class/axis combination exists in the printed pool, or when the theme's anti-motifs
forbid every such combination. Explain that concrete incompatibility in `blocked`."""
