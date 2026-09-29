"""seedsmith.adapters.items.consumablegen.brief — theme -> a brief-and-answer prompt.

Mirrors `setgen/brief.py`'s own discipline (closed vocabularies printed whole, never truncated —
module 13's own DEFECT 1/2 are what a truncated pool costs). Two things this brief deliberately
never contains, for the same P1 reason `setgen/brief.py` states:

- **`powerBand` and `manifestCost`.** Acceptance criterion 1 draws the line here: the model picks
  the qualitative content (`classId`, `useContext`, `family`, `element`, `tags`, name/flavor); code
  resolves the two numeric-shaped fields deterministically in `emit.py`. Telling the model a band or
  a cost invites it to reason numerically about a magnitude it is never asked to set.
- **`useContext = lawn`, or a `classId` outside the three authorable ones.** The cap is applied here,
  in the brief, by construction — the model is never shown `lawn`/`board`/`revive`/`utility`, so a
  well-formed answer cannot name one (ssot-consumables.md §3.1 / §9 item 5(b) fire at LOAD only as a
  backstop, the same relationship `setgen/brief.py` describes for `SetRoleNotUniversal`).
"""
from __future__ import annotations

from . import schema

PROMPT_VERSION = "consumables-gen/1"


def _pick_lines(picks: "tuple[str, ...]") -> str:
    return "\n".join(f"  - {p}" for p in sorted(picks))


def build_consumable_brief(theme: str, *, motifs: "tuple[str, ...]" = ()) -> str:
    """One consumable, one theme. `theme` is free text describing the item's flavor identity (a
    material, a creature, an aptitude) — this module has no theme registry of its own; the caller
    supplies one (a creature species name, a build archetype, a recipe line), same as `setgen` takes
    its `Theme` from a loaded registry the brief itself does not own."""
    families = schema.load_atom_family_names()
    motif_line = f"\nMotifs to express: {', '.join(motifs)}." if motifs else ""
    return f"""Author ONE consumable for '{theme}'.{motif_line}

Choose, and nothing else:
1. `classId` — exactly one of: {', '.join(sorted(schema.AUTHORABLE_CLASS_IDS))}.
   `restore` refills a pool now. `draught` is a run-scoped stat buff, bound at dispatch.
   `ward` is a depleting absorption layer bound at battle setup.
2. `useContext` — one or more of: {', '.join(sorted(schema.AUTHORABLE_USE_CONTEXTS))}.
3. `family` — exactly ONE id from the list below. It is the atom family this consumable's effect
   binds — never invent one outside this list.
4. `element` — only if `family` is `atom.elemental-power` or `atom.elemental-defense`; omit
   otherwise.
5. `tags`, `name`, `nameKey`, and optionally `notes`.

Never choose a number, a powerBand, or a manifestCost. Those are resolved after you answer.

Legal families ({len(families)} picks):
{_pick_lines(families)}

If this theme cannot carry a consumable you would be happy to ship, set `blocked` and say why."""
