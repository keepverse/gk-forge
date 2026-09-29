"""Real-run entrypoint for commander-effect generation (G4.3).

Committed so the run is reproducible — the earlier creatures run used scratch scripts that lived
nowhere, which is why nothing could regenerate the artifacts it produced.

⛔ **Requires G1 (`motif-prose-filter`) to have landed.** Generating from the pre-filter motifs
(`一类` = "armour-class one", `伤害` from a stat row) would bake stat vocabulary into committed,
append-only content — a **Never** in spec-commander-effect.md §7. `--check-motifs` refuses to run
if stat vocabulary is still present.

Usage:
    python -m seedsmith.adapters.creatures.generate_commander_effects --dry-run   # briefs only
    python -m seedsmith.adapters.creatures.generate_commander_effects             # real model calls
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import time
from datetime import datetime, timezone
from pathlib import Path

from ...pipeline.llm_caller import resolve_live_transport
from ...workflow.runner import MAX_WORKERS
from ...workflow.state import new_state
from .commander_effect import (
    build_brief,
    build_context,
    entry_for,
    load_subjects,
    stale_ids,
)

CREATURES_ROOT = Path(__file__).resolve().parents[5] / "data" / "seed" / "creatures"
OUTPUT_DIR = CREATURES_ROOT / "commander-effect"

#: Stat vocabulary that must not survive G1. Its presence means G1 did not land.
_STAT_VOCABULARY = frozenset({"一类", "二类", "优先", "韧性"})

PROMPT_VERSION = "commander-effect/1"


def load_existing() -> "dict[str, dict]":
    """Committed entries keyed by creatureId, or empty when nothing has been generated yet."""
    path = OUTPUT_DIR / "all.json"
    if not path.exists():
        return {}
    doc = json.loads(path.read_text(encoding="utf-8"))
    return {e["creatureId"]: e for e in doc.get("entries", [])}


def refuse_if_motifs_are_stale(subjects) -> None:
    offenders = {s["speciesId"]: sorted(_STAT_VOCABULARY & set(s["motifs"]))
                 for s in subjects if _STAT_VOCABULARY & set(s["motifs"])}
    if offenders:
        raise SystemExit(
            "REFUSING TO RUN: motifs still carry stat vocabulary, so G1 (motif-prose-filter) has "
            f"not landed. Generating now would bake it into append-only content.\n{offenders}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Generate one commander effect per creature.")
    ap.add_argument("--dry-run", action="store_true", help="assemble briefs, make no model calls")
    ap.add_argument("--limit", type=int, default=0, help="only the first N creatures")
    ap.add_argument("--only", default="", help="comma-separated creature ids to (re)generate")
    ap.add_argument("--stale", action="store_true",
                    help="(re)generate only entries whose recorded motifs no longer match")
    ap.add_argument("--force", action="store_true",
                    help="regenerate every subject, discarding existing entries")
    ap.add_argument("--endpoint", default="")
    ap.add_argument("--model", default="")
    ap.add_argument("--workers", type=int, default=MAX_WORKERS)
    args = ap.parse_args(argv)

    subjects = load_subjects(CREATURES_ROOT)
    refuse_if_motifs_are_stale(subjects)
    if args.limit:
        subjects = subjects[: args.limit]

    if args.dry_run:
        print(f"{len(subjects)} subjects; no model calls made.")
        print("--- sample brief ---")
        print(build_brief(build_context(subjects[0])))
        return 0

    # Idempotency (plan CP-G4: "re-run produces zero new writes"). Generation is stochastic, so
    # regenerating an entry that is already correct DESTROYS good content and costs model time for
    # nothing. Default is therefore skip-existing; a re-run with no flags writes nothing.
    existing = load_existing()
    if args.force:
        keep, targets = {}, subjects
    elif args.only:
        wanted = {x.strip() for x in args.only.split(",") if x.strip()}
        unknown = wanted - {s["speciesId"] for s in subjects}
        if unknown:
            raise SystemExit(f"--only names creatures that are not subjects: {sorted(unknown)}")
        keep = {k: v for k, v in existing.items() if k not in wanted}
        targets = [s for s in subjects if s["speciesId"] in wanted]
    elif args.stale:
        wanted = set(stale_ids(list(existing.values()), subjects))
        keep = {k: v for k, v in existing.items() if k not in wanted}
        targets = [s for s in subjects if s["speciesId"] in wanted]
    else:
        keep = dict(existing)
        targets = [s for s in subjects if s["speciesId"] not in existing]

    print(json.dumps({"subjects": len(subjects), "existing": len(existing),
                      "toGenerate": len(targets),
                      "stale": len(stale_ids(list(existing.values()), subjects))},
                     ensure_ascii=False))
    if not targets:
        print("nothing to generate — every subject already has a current entry.")
        return 0
    subjects = targets

    from ...workflow.graphs.commander_effect import build_commander_effect_graph
    from ...workflow.runner import run_many

    persisted: "dict[str, dict]" = {}
    # The model/endpoint come from `.env`/`seedsmith.toml` (or an explicit CLI flag); the
    # attempts/retry/timeout overrides are this generator's own tuning (NS4).
    config = dataclasses.replace(resolve_live_transport(args.endpoint, args.model),
                                 attempts=2, retry_delay=1.0, timeout=420)
    app = build_commander_effect_graph(
        on_persist=lambda k, v: persisted.__setitem__(k, v), config=config)

    # Names already committed by OTHER subjects. `name_collision` needs this: siblings share
    # motifs, so the model converges on one name for both and no per-draft check can see it.
    all_names = {sid: e.get("name") for sid, e in existing.items()}

    states = []
    contexts = {}
    for s in subjects:
        ctx = dict(build_context(s))
        ctx["takenNames"] = sorted(
            n for sid, n in all_names.items() if n and sid != s["speciesId"])
        contexts[s["speciesId"]] = ctx
        states.append(new_state(s["speciesId"], brief=build_brief(ctx), context=ctx))

    t0 = time.time()
    results = run_many(app, states, max_workers=args.workers)
    elapsed = time.time() - t0

    by_outcome: "dict[str, int]" = {}
    for r in results.values():
        by_outcome[r.get("outcome", "?")] = by_outcome.get(r.get("outcome", "?"), 0) + 1

    basis_by_id = {s["speciesId"]: s["basis"] for s in subjects}
    motifs_by_id = {s["speciesId"]: s["motifs"] for s in subjects}
    provenance = {
        "pipeline": "commander-effect",
        "model": config.model,
        "promptVersion": PROMPT_VERSION,
        "generatedUtc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "closes": "Coverage/CreatureUncovered",
    }
    fresh = {sid: entry_for(sid, draft, basis=basis_by_id.get(sid, "text"),
                            provenance=provenance, motifs=motifs_by_id.get(sid))
             for sid, draft in persisted.items()}
    merged = {**keep, **fresh}
    entries = [merged[k] for k in sorted(merged)]

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUTPUT_DIR / "all.json").write_text(
        json.dumps({"kind": "commander-effect", "_meta": {"partition": "all"},
                    "entries": entries}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")

    print(json.dumps({
        "generated": len(fresh), "kept": len(keep), "totalEntries": len(entries),
        "byOutcome": by_outcome, "elapsedSec": round(elapsed, 1),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover - dev entrypoint
    raise SystemExit(main())
