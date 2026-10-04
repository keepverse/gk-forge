"""T7.1/T7.2's own real authoring run, performed directly by Claude's own reasoning rather than a
local LM Studio model (which this environment cannot reach) — matching the same, already-established
substitution `run_checkpoint8a_claude_propose.py` used for the fusion-recipe gap-fill. Each draw below
is a genuinely reasoned named bundle over the REAL eligible atom pool (`generate_affixes.py`'s own
`load_eligible_atoms`, read fresh here, not copied), fed through the REAL, unmodified
`run_voted_draws` (schema validation, per-member vote via `resolve_set_vote`, class derivation,
persistence) exactly as three permuted samples from a real model would be — except every sample for a
given draw is the SAME considered choice, submitted honestly as a single judgment call, not a
fabricated multi-sample spread pretending to be independent stochastic noise it does not have (same
framing `run_checkpoint8a_claude_propose.py` already uses for the fusion-recipe run).

Small, deliberate batch — matching the owner's own explicitly-stated preference for small batches
reviewed before scaling (spec-affix-authoring.md's own precedent, `seed-to-concrete-phased-rollout-
decision`), not a bid to fill the whole eligible pool in one pass.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from seedsmith.adapters.effects.affix.generate_affixes import (
    ATOMS_ROOT,
    OUTPUT_DIR,
    load_eligible_atoms,
    load_existing,
    next_draw_start_index,
    run_voted_draws,
)

# Real eligible atom ids -> a real, considered name + bundle. Chosen for thematic coherence against
# each atom's own real effect (read from gk-data/packs/fusion/data/seed/atoms/*.json, not guessed) and, where relevant,
# using the naming register the existing 2 pilot affixes already set (elemental/nature-flavored,
# noun-phrase names). Never reuses an existing committed bundle's exact ref set.
REASONED_DRAWS: "list[tuple[str, list[str]]]" = [
    ("Glacial Bastion", ["atom.fx-freeze-on-hit.t1", "atom.fx-shield-grant.a.t1"]),
    ("Undertaker's Frost", ["atom.fx-spawn-zombie-ondeath.t1", "atom.fx-cold-on-hit.t1"]),
    ("Sovereign's Ember Mantle", ["atom.patron-aura-power.fire.t1", "atom.patron-aura-defense.fire.t1"]),
    ("Sovereign's Umbral Mantle", ["atom.patron-aura-power.dark.t1", "atom.patron-aura-defense.dark.t1"]),
    ("Golden Husbandry", ["atom.fx-economy-sun.t1", "atom.fx-spawn-butter.t1"]),
    ("Relentless Onslaught", ["atom.fx-overlay-damage.t1", "atom.fx-icd-butter.t1", "atom.fx-passive-atk-flat.t1"]),
    ("Cratered Earthworks", ["atom.fx-board-cherry.t1", "atom.fx-set-dirt-box.t1"]),
    ("Hunter's Precision", ["atom.critical-hunter.t1", "atom.fx-passive-atk-flat.t1"]),
]


def claude_propose_fn(eligible_ids: "set[str]"):
    """Yields `(name, refs)` per draw, refusing (and printing why) anything that has drifted out of
    the real eligible pool since this list was written — never silently substituting a different
    atom than the one actually reasoned about."""
    for name, refs in REASONED_DRAWS:
        missing = [r for r in refs if r not in eligible_ids]
        if missing:
            print(f"  ! skipping {name!r} — no longer eligible: {missing}", file=sys.stderr)
            continue
        yield name, refs


def main() -> int:
    atom_triggers = load_eligible_atoms(ATOMS_ROOT)
    eligible = sorted(atom_triggers)
    print(f"{len(eligible)} real eligible atoms loaded from {ATOMS_ROOT}")

    existing = load_existing()
    print(f"{len(existing)} existing committed affix(es)")

    all_fresh: "dict[str, dict]" = {}
    all_unresolved: "dict[str, dict]" = {}
    for name, refs in claude_propose_fn(set(eligible)):
        start = next_draw_start_index({**existing, **all_fresh})

        def call(system, user, *, config=None, schema=None, _name=name, _refs=refs):
            import json
            return json.dumps({"name": _name, "refs": list(_refs)})

        fresh, unresolved, _results = run_voted_draws(
            count=1, eligible=eligible, atom_triggers=atom_triggers,
            provenance_base={
                "pipeline": "affix-authoring",
                "model": "claude-sonnet-5",
                "note": "reasoned directly, no live LM Studio endpoint reachable in this "
                         "environment — see tools/seedsmith/run_t71_claude_propose.py",
            },
            start_index=start, call=call, workers=1)
        if unresolved:
            print(f"  ! {name!r} did not resolve: {unresolved}", file=sys.stderr)
            all_unresolved.update(unresolved)
            continue
        all_fresh.update(fresh)
        entry = next(iter(fresh.values()))
        print(f"  + {entry['id']}: {entry['name']!r} ({entry['class']}) refs="
              f"{[r['atom'] for r in entry['refs']]}")

    merged = {**existing, **all_fresh}
    entries = [merged[k] for k in sorted(merged)]

    import json
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUTPUT_DIR / "all.json").write_text(
        json.dumps({"schemaVersion": 1, "kind": "affix", "_meta": {"partition": "all"},
                    "entries": entries}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8", newline="\n")

    print(f"\nwrote {len(entries)} total entries ({len(all_fresh)} new) to {OUTPUT_DIR / 'all.json'}")
    if all_unresolved:
        print(f"{len(all_unresolved)} draw(s) unresolved — see stderr above", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
