"""seedsmith.adapters.trees.nodegen.exclusion — the D14 form ladder; `propertyKeys` checked
against the plan's own `propertyVocabulary` (task H1, spec-tree-language.md §5); `printedText`
template-composition is **H3's own addition** (§2's `printedText` row, §5.2 rule 1, D40).

**The honest finding this module is built around (§5.1): the property space is `tree-plan`'s
`propertyVocabulary`, never the atom corpus's tags.** `AffixOption.tags` (`vocab.py`) carries only
three values — not enough to key a single interesting exclusion on — so `validate_exclusion` below
checks every `propertyKeys` entry against the CALLER-SUPPLIED vocabulary (read by `plan_read` from
the committed plan), never against `vocab.py`'s affix tags.

**What this module checks today, and what it does not.** Per-response legality — is `form` one of
the four, is every key a real property, does no key look like a node id — is real here. The
CROSS-NODE requirement D40 adds for `nullification` (§5.2: both sides print the rule and name the
SAME winner) needs the paired node's own response and its `printedText`, which do not exist until
two calls have both completed and `printedText` has been template-composed — that pairing check is
`tree-review`'s corpus-level census (spec-tree-review.md §6.4 rule 2: "this module may now enforce
it"), not a single response's own validation, and not this stage's job either: `printedText` is
AUTHORED/FREE per §2's own table, never a schema field a model answers.

⚠ **A second spec ambiguity resolved here, stated plainly.** "Both sides print the rule, and both
name the same winner" (§5.2 rule 1) reads as if it needs a SECOND node's own response to compare
against. In practice there is usually no second AUTHORED node to compare against at all: the
properties this corpus can key on today (`posture`, `conversionState`, …) are game states no tree
node currently grants (D16 zero-budgets the one kind that would — §6 of the plan spec), so "the
winning side" is the PROPERTY itself, never another node (D14/§5.2 item 3's own rule: an exclusion
predicate keys on a property, never a node id — this extends the same discipline to what the
printed text may reference). Resolved default: `compose_printed_text` is a PURE function of
`(form, property_keys, role)` — never of which node is asking — so "the same winner" becomes a
property of the TEMPLATE rather than a runtime cross-node check this module has no data to run:
any two nodes (or a node and a future property-registry description) that key on the same property
and form are GUARANTEED to name the same winner, by construction, because they call the same
function with the same arguments. `exclusion_winner` is the one place "the winner" is computed, so
both the `role="loser"` text this stage actually emits on a node and the `role="winner"` text a
downstream property description could show are provably consistent. If a later task adds real
paired-node data, this is the one function whose contract changes.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Sequence

__all__ = [
    "EXCLUSION_FORMS",
    "REROUTE",
    "PRECEDENCE",
    "NULLIFICATION",
    "NONE_FORM",
    "ExclusionDefect",
    "ExclusionClaim",
    "validate_exclusion",
    "exclusion_winner",
    "compose_printed_text",
]

#: D14's ladder, in the order the brief asks a model to try it (§6.2: "Prefer `reroute`... Most
#: nodes have none. `nullification` is the last resort").
NONE_FORM = "none"
REROUTE = "reroute"
PRECEDENCE = "precedence"
NULLIFICATION = "nullification"
EXCLUSION_FORMS: "tuple[str, ...]" = (NONE_FORM, REROUTE, PRECEDENCE, NULLIFICATION)

#: A property key must never look like a node id — `exclusion.propertyKeys[]` "keys on a PROPERTY,
#: never on a node id" (§2's row, D14, restated non-negotiable at §5.2 item 3). Node ids are minted
#: `skill.<treeId>-<branch>-t<tier>-<nodeKey>` (§2's `nodeId` row); this pattern catches that shape
#: without having to import the id grammar from `plan.ids` and couple this module to it.
_NODE_ID_SHAPE_RE = re.compile(r"^skill\.[a-z0-9-]+-t\d+-[a-z0-9-]+$")


@dataclass(frozen=True)
class ExclusionDefect:
    reason: str

    def __str__(self) -> str:
        return self.reason


@dataclass(frozen=True)
class ExclusionClaim:
    """One response's `exclusion` object (§6.3), lifted out of the raw JSON so validation has a
    typed shape to check rather than re-indexing a dict at every call site."""

    form: str
    property_keys: "tuple[str, ...]"

    @classmethod
    def from_response(cls, exclusion: "dict") -> "ExclusionClaim":
        return cls(form=str(exclusion.get("form", NONE_FORM)),
                  property_keys=tuple(exclusion.get("propertyKeys") or ()))


def _legal_property_keys(property_vocabulary: "dict[str, tuple[str, ...]] | Sequence[str]",
                         ) -> "set[str]":
    """⚠ **A second spec ambiguity resolved here, stated plainly.** §5's own predicate mechanism
    (`EligibilityRule`, `:20-24`) carries TWO shapes: `RequireTags` (a bare axis key, e.g.
    `"posture"`) and `AnyOfTags` (a `key:value` pair, e.g. `"posture:vanguard"`) — the spec never
    states which shape a node's `exclusion.propertyKeys[]` entries take. Resolved default: BOTH are
    legal. A bare axis name (a dict key of `propertyVocabulary`) and any `axis:value` pair built
    from that axis's own members are accepted; nothing else is. If a later task narrows this to one
    shape only, this is the one function that needs to change.
    """
    if not isinstance(property_vocabulary, dict):
        return set(property_vocabulary)
    keys: "set[str]" = set(property_vocabulary.keys())
    for axis, members in property_vocabulary.items():
        keys.update(f"{axis}:{member}" for member in members)
    return keys


def validate_exclusion(claim: ExclusionClaim,
                       property_vocabulary: "dict[str, tuple[str, ...]] | Sequence[str]",
                       ) -> "list[ExclusionDefect]":
    """§7 gate 19's per-response half: `form` is one of the four, `none` carries no keys, any other
    form carries at least one, and every key is a real property (never a node id).

    `property_vocabulary` may be the plan's whole `{axis: (members...)}` map (a bare axis name OR
    an `axis:value` pair is then legal — `_legal_property_keys`'s own resolved ambiguity) or a
    flattened sequence of already-legal keys — both call shapes are real in this program
    (`plan_read.TreePlan.property_vocabulary` is the former; a pre-flattened permitted subset from
    `quota.py`/H3 is the latter), so this function accepts either rather than forcing every caller
    to flatten first.
    """
    defects: "list[ExclusionDefect]" = []

    if claim.form not in EXCLUSION_FORMS:
        defects.append(ExclusionDefect(
            f"form {claim.form!r} is not one of {EXCLUSION_FORMS} — this is a schema-enum "
            f"violation, so seeing it here means the schema's own enum was bypassed"))
        return defects

    if claim.form == NONE_FORM:
        if claim.property_keys:
            defects.append(ExclusionDefect(
                f"form is 'none' but propertyKeys is non-empty ({claim.property_keys!r}) — "
                f"'none' means no conflict, so it carries no keys"))
        return defects

    if not claim.property_keys:
        defects.append(ExclusionDefect(
            f"form {claim.form!r} carries no propertyKeys — every non-'none' form must name at "
            f"least one property it conflicts with"))

    legal_keys = _legal_property_keys(property_vocabulary)
    for key in claim.property_keys:
        if _NODE_ID_SHAPE_RE.match(key):
            defects.append(ExclusionDefect(
                f"propertyKeys entry {key!r} matches the node-id shape — D14/§5.2 item 3: an "
                f"exclusion predicate must key on a PROPERTY, never on a node id"))
        elif key not in legal_keys:
            defects.append(ExclusionDefect(
                f"propertyKeys entry {key!r} is not in the plan's propertyVocabulary — this "
                f"stage never widens the vocabulary it was given"))

    return defects


def exclusion_winner(property_keys: "Sequence[str]") -> str:
    """§5.2 rule 1's "the same winner", named: the property or properties this exclusion keys on
    — never a node id (D14/§5.2 item 3), and never anything a node's own response supplies beyond
    `propertyKeys` itself. A PURE function of `property_keys` alone is what makes "the SAME winner"
    checkable without a second node's response to compare against (this module's own resolved
    ambiguity, stated in its docstring): any two calls with the same `property_keys` return the
    identical string, by construction.
    """
    if not property_keys:
        raise ValueError("exclusion_winner: no propertyKeys to name a winner from")
    return " and ".join(property_keys)


def compose_printed_text(form: str, property_keys: "Sequence[str]", *, role: str = "loser") -> str:
    """§2's `printedText` row: "the exclusion's player-facing sentence, composed from a template so
    both sides print the same rule and name the same winner." `form == "none"` composes to the
    empty string — 'none' means no conflict, so there is nothing to print, mirroring
    `validate_exclusion`'s own "'none' means no conflict, so it carries no keys" rule.

    `role="loser"` is what THIS node's own record carries (the only side tree-language ever
    persists — a node's own `exclusion` object describes what conflicts with IT, never what some
    other node does); `role="winner"` is provided for a future consumer that renders the property's
    OWN side (a property-registry description, or `tree-review`'s census) — both roles are built
    from the SAME `exclusion_winner`, so whichever side is rendered, wherever, names the identical
    winner (§5.2 rule 1's "both name the same winner", satisfied by construction rather than by a
    runtime comparison — see this module's own docstring for why no second node's data exists to
    compare against today).
    """
    if role not in ("loser", "winner"):
        raise ValueError(f"compose_printed_text: role must be 'loser' or 'winner', got {role!r}")
    if form == NONE_FORM:
        return ""
    if form not in EXCLUSION_FORMS:
        raise ValueError(f"compose_printed_text: unknown exclusion form {form!r}")
    winner = exclusion_winner(property_keys)

    if form == REROUTE:
        return (f"While {winner} holds, this effect reroutes instead of applying normally."
                if role == "loser" else
                f"{winner} reroutes any effect that would otherwise conflict with it.")
    if form == PRECEDENCE:
        return (f"This applies before {winner} takes effect."
                if role == "loser" else
                f"{winner} takes effect only after this has already applied.")
    # NULLIFICATION
    return (f"Inert while {winner} is active — {winner} wins."
            if role == "loser" else
            f"{winner} nullifies anything that conflicts with it.")
