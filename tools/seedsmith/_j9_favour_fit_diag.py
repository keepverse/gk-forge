"""Diagnostic: capture the RAW favour-fit model responses for one real species, bypassing vote
resolution, to see whether a 100% 'none fits' outcome is genuine model judgment or a prompt/schema
defect."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from seedsmith.adapters.trees.species.roster import load_roster
from seedsmith.adapters.trees.species.plan import assign_favour_cells
from seedsmith.adapters.trees.targets import load as load_species_targets
from seedsmith.adapters.trees.species.prompts import (
    FAVOUR_FIT_SYSTEM_PROMPT, build_favour_fit_brief, build_favour_fit_context,
)
from seedsmith.adapters.trees.species.schemas import favour_fit_schema
from seedsmith.pipeline import llm_caller

roster = load_roster()
species_targets = load_species_targets()
assignments = assign_favour_cells(roster.species_ids, species_targets)

for species_id in ["AbyssSwordStar", "AcientSunNut", "AllPeater"]:
    anchor = roster.anchors[species_id]
    assignment = assignments[species_id]
    print(f"\n===== {species_id} =====")
    print("anchor:", anchor)
    print("offered:", assignment.cell)
    print("alternates:", assignment.alternates)

    alt_keys = [a.key() for a in assignment.alternates]
    schema = favour_fit_schema(alt_keys)
    context = build_favour_fit_context(anchor, assignment.cell, list(assignment.alternates))
    user = build_favour_fit_brief(context)
    print("\n--- USER BRIEF ---\n", user)
    print("\n--- SCHEMA enum ---\n", schema.get("properties", {}).get("choice", {}).get("enum"))

    for i in range(3):
        raw = llm_caller.call_model(
            FAVOUR_FIT_SYSTEM_PROMPT, user, config=llm_caller.DEFAULT_CONFIG, temperature=0.2,
            schema=schema)
        print(f"--- SAMPLE {i} RAW ---  {raw}")
