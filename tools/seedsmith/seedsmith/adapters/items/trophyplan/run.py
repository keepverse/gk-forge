"""seedsmith.adapters.items.trophyplan.run — the CLI entrypoint: `seedsmith items generate
--kind trophy --dry-run|--write`, plus a standalone `--check` mode wired for CI the same way every
sibling `*gen/run.py` module is directly invocable (`python -m seedsmith.adapters.items.trophyplan.run
--check`) without going through the shared multiplexer, matching `trees plan --check`'s own
module-local flag (`report/cli.py:3007`) rather than adding a shared flag no other kind needs.

No model call anywhere in this module (unlike every sibling `*gen/run.py`): the plan is a pure
function of three already-on-disk inputs (species tree, family map, `species-material-run.v1.json`)
plus whatever the committed registry already holds. `--write` therefore needs no `--endpoint`; there
is no answer schema, no brief, and no ledger — the registry itself is the append-only ledger.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

from . import plan as plan_mod
from . import species as species_mod
from . import tuning as tuning_mod

REPO_ROOT = Path(__file__).resolve().parents[6]
REGISTRY_PATH = REPO_ROOT / "data" / "seed" / "items" / "materials" / "trophy-registry.json"


def load_registry(path: "Path | None" = None) -> "tuple[plan_mod.TrophyRow, ...]":
    """Empty tuple if the registry does not exist yet (this module's own first `--write` births
    it) — never an error, distinct from every OTHER input this package reads, all of which refuse a
    missing file by name (§ Design 4's inputs are prerequisites; the registry is this module's own
    output, and "no output yet" is the ordinary first-run state, not a corpus defect)."""
    registry_path = path or REGISTRY_PATH
    if not registry_path.is_file():
        return ()
    doc = json.loads(registry_path.read_text(encoding="utf-8"))
    entries = doc.get("entries")
    if not isinstance(entries, list):
        raise plan_mod.TrophyRegistryError(f"{registry_path}: 'entries' must be a JSON array")
    return tuple(plan_mod.TrophyRow.from_dict(row) for row in entries)


def write_registry(rows: "tuple[plan_mod.TrophyRow, ...]", path: "Path | None" = None) -> Path:
    """Atomic replace (temp file + `os.replace`), the same discipline `materialgen.run._write_entries`
    already uses, so a killed process leaves either the old registry or the new one, never half."""
    registry_path = path or REGISTRY_PATH
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    doc = {"_meta": {"schemaVersion": 1, "kind": "trophy-registry"},
          "entries": [row.to_dict() for row in rows]}
    payload = json.dumps(doc, ensure_ascii=False, indent=2) + "\n"
    handle, tmp_name = tempfile.mkstemp(dir=str(registry_path.parent), suffix=".tmp")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as fh:
            fh.write(payload)
        os.replace(tmp_name, registry_path)
    except BaseException:
        Path(tmp_name).unlink(missing_ok=True)
        raise
    return registry_path


def build_plan(*, seed_root: "Path | None" = None, family_map_path: "Path | None" = None,
              tuning_path: "Path | None" = None, registry_path: "Path | None" = None,
              ) -> plan_mod.PlanResult:
    roster = species_mod.load_species_roster(seed_root)
    family_map = species_mod.load_family_map(family_map_path)
    family_membership = species_mod.resolve_family_membership(roster, family_map)
    run_tuning = tuning_mod.load_run_tuning(tuning_path or tuning_mod.RUN_TUNING_PATH)
    existing = load_registry(registry_path)
    return plan_mod.plan_trophy_registry(
        family_membership, per_species=run_tuning.per_species, per_family=run_tuning.per_family,
        existing_rows=existing)


def main(argv=None) -> int:
    import argparse

    ap = argparse.ArgumentParser(
        description="Mint the deterministic, append-only trophy id registry (no model call).")
    ap.add_argument("--dry-run", action="store_true", help="report the plan, write nothing")
    ap.add_argument("--write", action="store_true", help="write the merged registry back to disk")
    ap.add_argument("--check", action="store_true",
                    help="exit non-zero if the committed registry is missing rows the current "
                         "roster/tuning would mint (CI drift gate) -- makes no model call, writes "
                         "nothing regardless of --write")
    args = ap.parse_args(argv)

    try:
        result = build_plan()
    except (plan_mod.TrophyRegistryError, species_mod.TrophyPlanError,
           tuning_mod.TrophyTuningError) as exc:
        print(f"seedsmith: trophy plan refused -- {exc}", file=sys.stderr)
        return 1

    if args.check:
        if result.new_rows:
            print(f"seedsmith: trophy registry is stale -- {len(result.new_rows)} row(s) the "
                  f"current roster/tuning would mint are not yet committed; re-run with --write",
                  file=sys.stderr)
            return 1
        print(json.dumps({"totals": result.totals(), "drift": 0}, ensure_ascii=False, indent=2))
        return 0

    payload = {
        "totals": result.totals(),
        "newRowCount": len(result.new_rows),
        "speciesWithNoFamily": list(result.species_with_no_family),
    }
    if args.dry_run or not args.write:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        if not args.write:
            return 0

    if args.write:
        path = write_registry(result.all_rows)
        payload["writtenTo"] = str(path)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover - dev entrypoint
    raise SystemExit(main())
