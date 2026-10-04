"""T5.3's own real authoring run, performed directly by Claude's own reasoning rather than a local
LM Studio model (which this environment cannot reach) — same substitution pattern already used for
`run_checkpoint8a_claude_propose.py` (fusion recipes) and `run_t71_claude_propose.py` (affixes).

A small, deliberate batch (3 species) over REAL committed anchors and the REAL 10-affix catalog,
picked for thematic coherence against each species' own real aptitude/posture/element/traits (read
from `gk-data/packs/fusion/data/seed/creatures/species/**/*.json`, not guessed) and each affix's own real effect. Submitted
as 3 unanimous "samples" per species through the REAL, unmodified `entry_for`/`fixed_core_within_band`
— an honest single judgment call, not a fabricated stochastic spread (same framing the two precedents
above already use).

**Deliberately conservative, not exhaustive**: every pick respects `creature-species-effects.v1.json`'s
own `fixedCoreBandByRarity` for that species' real rarity (`conezombie` is `chaff` — band {0,0} — so
it gets ZERO core picks, pool only) and avoids the two still-unbuilt validator paths this run cannot
exercise correctly (posture/resource conflict-repair) by simply not authoring a pick that would
trigger one — a real, working small batch, not a stress test of gaps this task's own evidence already
named and left open.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from seedsmith.adapters.creatures.effects.prompts import (
    build_context,
    entry_for,
    fixed_core_within_band,
)
from seedsmith.workflow.graphs.species_effects import load_shape_tuning

REPO_ROOT = Path(__file__).resolve().parents[2]

# `REPO_ROOT`-relative joins below ask which repository actually carries the path. A prefix-keyed
# rewrite is wrong: `data`, `data/seed` and `data/seed/creatures` all resolve back to gk-forge,
# because nearest-match-wins and gk-forge owns its own generator inputs. `or REPO_ROOT` is
# load-bearing - `owning_base` returns None for a path no repository carries, where
# `content_root()` would RAISE.

from workspace_roots import owning_base  # noqa: E402


def _owned(relative: str) -> "Path":
    """The repository carrying `relative`, joined to it; this one when none carries it."""
    return (owning_base(relative, REPO_ROOT) or REPO_ROOT) / relative

SPECIES_ROOT = _owned("data/seed/creatures/species")
AFFIX_FILE = _owned("data/seed/effects/affixes/all.json")
OUTPUT_DIR = _owned("data/seed/creatures/species-effects")


def load_real_affixes() -> "tuple[dict, dict]":
    entries = json.loads(AFFIX_FILE.read_text(encoding="utf-8"))["entries"]
    refs_by_affix = {e["id"]: [r["atom"] for r in e["refs"]] for e in entries}
    class_by_affix = {e["id"]: e["class"].capitalize() for e in entries}
    return refs_by_affix, class_by_affix


def find_anchor(species_id_lower: str) -> dict:
    for path in SPECIES_ROOT.rglob("*.json"):
        doc = json.loads(path.read_text(encoding="utf-8"))
        entries = doc if isinstance(doc, list) else [doc]
        for e in entries:
            if (e.get("speciesId") or "").strip().lower() == species_id_lower:
                return e
    raise KeyError(f"no anchor found for {species_id_lower!r} under {SPECIES_ROOT}")


# (real speciesId, {affixId: affinity}) — every pick reasoned against the real anchor context above
# and each affix's own real effect, read together before writing this table.
REASONED_PICKS: "dict[str, dict[str, str]]" = {
    # Onslaught / Force / earth, "projectile-launching, defensive-line, rhythmic-attack" — an
    # offense-defined plant. Hunter's Precision (crit + flat atk) is its defining trait: core.
    # Cratered Earthworks (earth-flavored) fits the element as a rarer, thematic pick. Relentless
    # Onslaught was considered too (fits Onslaught aptitude thematically) but shares
    # atom.fx-passive-atk-flat.t1 with Hunter's Precision's own core pick — found live, running this
    # exact draft through the real importer ("is in both the fixed core and the pool"), so dropped
    # rather than authoring a pick this program's own validator would correctly refuse.
    "peashooter": {
        "affix.authored.affix-draw-009": "core",       # Hunter's Precision
        "affix.authored.affix-draw-008": "occasional",  # Cratered Earthworks
    },
    # Focus / Finesse / light, "sun-production, delayed-yield" — an economy-defined plant.
    # Golden Husbandry (sun economy + spawn-butter) IS what this species is: core.
    "sunflower": {
        "affix.authored.affix-draw-006": "core",       # Golden Husbandry
        "affix.authored.affix-draw-002": "occasional",  # Glacial Bastion (weaker thematic fit, rarer)
    },
    # Bulwark / Bastion / earth, "improvised-armor, oblivious, food-mimicry" — chaff rarity, band
    # {min:0, max:0}: NO core pick is legal here. A basic, mostly-inert chaff zombie gets one
    # occasional pick reflecting its improvised-armor trait, nothing guaranteed.
    "conezombie": {
        "affix.authored.affix-draw-002": "occasional",  # Glacial Bastion (shield fits improvised-armor)
    },
}


def main() -> int:
    refs_by_affix, class_by_affix = load_real_affixes()
    shape = load_shape_tuning()
    entries = []

    for species_id, picks in REASONED_PICKS.items():
        anchor = find_anchor(species_id)
        anchor = {**anchor, "speciesId": species_id}  # the real, canonical (lowercased) form
        context = build_context(anchor)
        band = shape["fixedCoreBandByRarity"].get(context["rarity"])

        draft = {
            "eligibleAffixes": [{"affixId": aid, "affinity": aff} for aid, aff in picks.items()],
            "eligibilityTags": {"requireTags": [], "anyOfTags": []},
        }

        defects = fixed_core_within_band(draft, {"fixedCoreBand": band})
        if defects:
            print(f"  ! {species_id}: {defects}", file=sys.stderr)
            continue

        entry = entry_for(
            anchor, draft,
            affix_class_of=class_by_affix.__getitem__,
            affix_refs_of=refs_by_affix.__getitem__,
            pool_affinity_weight_milli=shape["poolAffinityWeightMilli"],
            provenance={
                "pipeline": "species-effects",
                "model": "claude-sonnet-5",
                "note": "reasoned directly, no live LM Studio endpoint reachable in this "
                         "environment — see tools/seedsmith/run_t53_claude_propose.py",
            },
        )
        entries.append((anchor.get("side", "plant"), entry))
        print(f"  + {entry['id']}: {len(entry['atoms'])} fixed atom(s), {len(entry['pool'])} pool "
              f"row(s), prefixRolls={entry['prefixRolls']} suffixRolls={entry['suffixRolls']}")

    plant_dir = OUTPUT_DIR / "plant"
    zombie_dir = OUTPUT_DIR / "zombie"
    plant_dir.mkdir(parents=True, exist_ok=True)
    zombie_dir.mkdir(parents=True, exist_ok=True)

    # One file per side, matching spec §6's own "grouped like the anchors" layout — this small a
    # batch doesn't need per-family splitting yet.
    by_side: "dict[str, list]" = {"plant": [], "zombie": []}
    for side, entry in entries:
        by_side.setdefault(side, []).append(entry)

    for side, dir_ in (("plant", plant_dir), ("zombie", zombie_dir)):
        if not by_side.get(side):
            continue
        path = dir_ / "pilot-batch.json"
        path.write_text(
            json.dumps({"schemaVersion": 1, "kind": "container",
                        "_meta": {"pipeline": "species-effects", "partition": "pilot-batch"},
                        "entries": by_side[side]}, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8", newline="\n")
        print(f"wrote {len(by_side[side])} entries to {path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
