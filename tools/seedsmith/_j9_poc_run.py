"""One-off, real-model proof-of-concept for task J9's real prerequisite: does the FULL species-tree
orchestration (favour-fit -> plan/quota -> node generation -> marking -> codex) actually work
end-to-end for one REAL species, against the live local model? Never committed to the real
gk-data/packs/fusion/data/seed tree -- writes to an isolated temp seed_root, matching this whole session's own established
"prove it for real, without touching the working tree" discipline (J7's affix PoC, J8's favour-fit/
codex PoCs).
"""
import json
import sys
import time
from pathlib import Path

from seedsmith.adapters.trees.nodegen import tuning as nodegen_tuning
from seedsmith.adapters.trees.plan import tuning as plan_tuning
from seedsmith.adapters.trees.species.generate_tree import run_species_tree
from seedsmith.adapters.trees.species.plan import FavourCell
from seedsmith.adapters.trees.species.roster import SpeciesAnchor
from seedsmith.pipeline.llm_caller import load_config

seed_root = Path(sys.argv[1])
ledger_path = seed_root / "_runs" / "ledger.json"

anchor = SpeciesAnchor(
    species_id="AbyssSwordStar", element_primary="air", aptitude_primary="Onslaught",
    posture="Force",
    traits=("orbital-blade-rotation", "meteor-strike-summoning", "area-of-effect-cleave",
           "homing-projectile"),
    reason="The combination of rapid-fire multi-hit rotation and ten homing area-of-effect swords "
          "makes this a high-tier threat far exceeding a mere scourge.",
    source_path="plant/celestial-flora.json")

offered = FavourCell("Onslaught", "air", "spark")
alternates = [FavourCell("Ferocity", "air", "shatter"), FavourCell("Precision", "light", "expose")]

# Through the config chain. This used to be a literal `LlmCallerConfig(endpoint=..., model=...)`
# naming one machine's LM Studio port and one model id, in a committed file — so the PoC could only
# ever run on the machine that wrote it, it ignored `.env` entirely, and it could never honour a
# delegated run because `mode` rides on the same config. `load_config()` is the routed shape; the
# numbers it dropped (`attempts=2`, `timeout=420`) are already this package's own defaults.
config = load_config()

t0 = time.time()
result = run_species_tree(
    "AbyssSwordStar", anchor, 0, offered, alternates,
    targets=nodegen_tuning.load(), tuning=plan_tuning.load(),
    ledger_path=ledger_path, seed_root=seed_root, config=config, workers=4)
elapsed = time.time() - t0

print(json.dumps({
    "elapsedSeconds": round(elapsed, 1),
    "resolvedCell": None if result.resolved_cell is None else {
        "aptitude": result.resolved_cell.aptitude, "element": result.resolved_cell.element,
        "status": result.resolved_cell.status},
    "favourUnresolvedReason": result.favour_unresolved_reason,
    "outcomeCounts": result.outcome_counts,
    "markedNodeCount": len(result.marked_node_ids),
    "codexSummary": result.codex_summary,
    "codexUnresolvedReason": result.codex_unresolved_reason,
    "nodesSeedPath": str(result.nodes_seed_path) if result.nodes_seed_path else None,
    "metadataPath": str(result.metadata_path) if result.metadata_path else None,
}, indent=2))

if result.nodes_seed_path:
    doc = json.loads(result.nodes_seed_path.read_text(encoding="utf-8"))
    print(f"\n--- {len(doc['nodes'])} real nodes committed, 3 samples ---")
    for n in doc["nodes"][:3]:
        print(f"  [{n['branch']} t{n['tier']} {n['nodeClass']}] {n['name']!r} -- {n['flavor']!r} "
              f"affixIds={n['affixIds']}")
