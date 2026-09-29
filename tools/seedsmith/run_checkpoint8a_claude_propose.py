"""Checkpoint 8a's own propose pass, performed directly by Claude's own reasoning rather than a
local LM Studio model (which this environment cannot reach) — see
tasks/seed-to-concrete-todo.md's Checkpoint 8a entry for the full rationale. Each of the 14 real
Almanac deficits gets a genuinely reasoned candidate pair (element-match first, matching
CreatureRecipeCatalog's own established A/B preference; ring-related element as fallback for the
elements — "air" — with zero same-element candidates in the pool; loose thematic fit as the final
tie-break), fed through the REAL, unmodified reconcile()/per-member-vote/validation pipeline exactly
as a real model's samples would be. Not presented as identical to a live model vote — recorded
plainly as Claude-authored proposals, run through the same deterministic reconciliation every other
source uses.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from seedsmith.adapters.creatures.fusion import reconcile as reconcile_mod
from seedsmith.adapters.creatures.fusion.emit import write as emit_write, DEFAULT_OUTPUT_RELATIVE

# Reasoned pair per deficit output — see the session's own reasoning: element-match first
# (matching CreatureRecipeCatalog's own A-candidate preference), ring-related fallback for "air"
# (no same-element candidate exists anywhere in the real pool), thematic fit as the tie-break.
REASONED_PAIRS: "dict[str, tuple[str, str]]" = {
    "jacksonzombie": ("legionzombie", "legionsniperzombie"),
    "ultimatehypnodoom": ("qingzombie", "ultimatelegionzombie"),
    "ultimateimpking": ("summonedhorse", "superblackhorse"),
    "ultimateportalnut": ("endoflamezombie", "blacktrainzombie"),
    "zombieboss": ("ultimatehorse", "ultimatehorse2"),
    "jalasquashzombie": ("solarsunflower", "ultimateendoflamezombie"),
    "ultimatecabbagecannon": ("superjackboxzombie", "ultimatejackboxzombie"),
    "peashooterzombie": ("bedrocktallnut", "golddoom"),
    "ultimatesnipergatling": ("ultimatemachinenut", "supergargantuar"),
    "zombie9527": ("ultimategargantuar", "ultimategoldgargantuar"),
    "luckyblover": ("blackflagfootball", "elephantzombie_b"),
    "quickjacksonzombie": ("superhorse", "elephantzombie_c"),
    "swordstar": ("ultiwatergargantuar", "blackelephantzombie"),
    "ultimateportalsniper": ("submarine_c", "ultimatedolphin"),
}


def claude_propose_fn(output, candidates, claimed):
    pair = REASONED_PAIRS.get(output.species_id)
    if pair is None:
        print(f"  ! no reasoned pair authored for {output.species_id!r} — reporting unresolved", file=sys.stderr)
        return [None, None, None]
    # Submitted as 3 unanimous samples: a single considered judgment, not a fabricated multi-sample
    # spread pretending to be independent noise it does not have.
    return [pair, pair, pair]


def main() -> int:
    seam = reconcile_mod.run_seam_cli()
    print(f"seam: {len(seam['eligibleOutputs'])} eligible, {len(seam['deterministicRecipes'])} deterministic, {len(seam['deficits'])} deficits")

    existing = reconcile_mod.load_existing_seed(reconcile_mod.REPO_ROOT.joinpath(*DEFAULT_OUTPUT_RELATIVE))
    outcome = reconcile_mod.reconcile(seam, claude_propose_fn, existing_seed=existing)

    gap_fills = [rid for rid, r in outcome.recipes.items() if r["crossRungGapFill"]]
    print(f"resolved gap-fills: {len(gap_fills)} / {len(REASONED_PAIRS)} attempted")
    for rid in sorted(gap_fills):
        r = outcome.recipes[rid]
        print(f"  {rid}: {r['inputSpeciesIdA']} + {r['inputSpeciesIdB']}")
    if outcome.unresolved:
        print(f"still unresolved ({len(outcome.unresolved)}): {', '.join(sorted(outcome.unresolved))}")

    out_path = reconcile_mod.REPO_ROOT.joinpath(*DEFAULT_OUTPUT_RELATIVE)
    wrote = emit_write(outcome.recipes, out_path)
    print(f"{len(outcome.recipes)} total recipe(s) -> {out_path} ({'written' if wrote else 'unchanged'})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
