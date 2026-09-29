#!/usr/bin/env python3
"""Regenerate `_registry_snapshot/allocated_partitions.json` from its own source of record.

Why this file exists at all: `adapters/items/registries.partition_kind_map` resolves a partition's
kind without a runtime `dotnet` dependency, by reading a committed snapshot. Its `_meta.regenerate`
has always named the source (`dotnet run --project gk-forge/tools/ItemSeedValidator -- --list-partitions
gk-data/packs/fusion/data/seed/items`), but that command prints a HUMAN table, so the JSON was assembled by hand and
drifted: the 2026-08-23 capture still mapped `socket-words -> socket-word`, a kind SSH2.6 retired for
real (found by lane `seed-corpus`, ISG7-F2, 2026-09-21).

`--list-partitions-json` (added the same day) makes the source machine-readable, so this script
regenerates the snapshot for real instead of hand-editing it.

    python gk-forge/tools/seedsmith/refresh_allocated_partitions.py --check   # exit 1 when stale
    python gk-forge/tools/seedsmith/refresh_allocated_partitions.py --write   # regenerate

`--check` compares only `partitionKind` (the load-bearing content); `capturedUtc` changes on every
`--write` by design and is not a drift signal.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

#: This script is standalone (stdlib only) EXCEPT for the one thing it must not re-implement: launching
#: a repo tool. `run_tool` names a missing executable and raises the caller's own refusal, where a bare
#: `subprocess.run(["dotnet", ...])` dies with an opaque `FileNotFoundError` before any of this script's
#: own error messages can fire.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from seedsmith.tooling import run_tool  # noqa: E402

TOOL_PROJECT = Path("tools") / "ItemSeedValidator"
SEED_ROOT = Path("data") / "seed" / "items"
SNAPSHOT = (Path(__file__).resolve().parent / "seedsmith" / "adapters" / "items"
            / "_registry_snapshot" / "allocated_partitions.json")
#: The tool's serialized document opens with this exact line (`WriteIndented`, two spaces). Build
#: output shares stdout, so the marker is what separates the JSON from it.
_JSON_MARKER = '{\n  "partitionKind"'


def _repo_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / "CONTRIBUTING.md").is_file():
            return parent
    raise SystemExit("could not locate the repo root (CONTRIBUTING.md not found upward)")


def live_partition_kind() -> dict[str, str]:
    """The tool's own allocation, read as JSON -- never re-derived here (the C# tool is the
    authority; a second Python implementation is exactly what the snapshot's own note forbids)."""
    root = _repo_root()
    proc = run_tool(
        ["dotnet", "run", "--project", str(root / TOOL_PROJECT), "--", "--list-partitions-json",
         str(root / SEED_ROOT)],
        cwd=str(root), refusal=SystemExit,
        what="the ItemSeedValidator partition list this snapshot is regenerated from",
    )
    if proc.returncode != 0:
        raise SystemExit(f"ItemSeedValidator exited {proc.returncode}:\n{proc.stderr[-2000:]}")
    start = proc.stdout.find(_JSON_MARKER)
    if start < 0:
        raise SystemExit(f"no `partitionKind` JSON in the tool output:\n{proc.stdout[-2000:]}")
    doc = json.loads(proc.stdout[start:])
    kinds = doc["partitionKind"]
    if not isinstance(kinds, dict) or not kinds:
        raise SystemExit("the tool returned an empty `partitionKind` -- refusing to write that")
    return dict(kinds)


def build_snapshot(prev_meta: dict) -> dict:
    meta = dict(prev_meta)
    meta["capturedUtc"] = date.today().isoformat()
    # The `_meta` path names the MACHINE-READABLE source and the one-command regeneration, so the
    # next reader does not hand-assemble this file again (the defect ISG7-F2 exists because the old
    # wording named only the human `--list-partitions` table).
    meta["source"] = ("dotnet run --project tools/ItemSeedValidator -- --list-partitions-json "
                      "data/seed/items")
    meta["regenerate"] = "python tools/seedsmith/refresh_allocated_partitions.py --write"
    return {"_meta": meta, "partitionKind": live_partition_kind()}


def dump(doc: dict) -> str:
    # Matches the committed file's own shape: one-space indent, sorted keys, LF, trailing newline.
    return json.dumps(doc, ensure_ascii=False, indent=1, sort_keys=True) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--write", action="store_true", help="write the snapshot (default: --check)")
    ap.add_argument("--check", action="store_true", help="report drift and exit 1 (the default)")
    args = ap.parse_args(argv)

    current = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    fresh = build_snapshot(current.get("_meta", {}))

    if args.write:
        # `newline="\n"`: a text-mode write otherwise emits the OS line ending (CRLF on Windows)
        # and rewrites every line of a committed LF file -- the same class the themes writers hit.
        SNAPSHOT.write_text(dump(fresh), encoding="utf-8", newline="\n")
        print(f"wrote {SNAPSHOT} ({len(fresh['partitionKind'])} partitions)")
        return 0

    committed = current.get("partitionKind") or {}
    if committed == fresh["partitionKind"]:
        print(f"current ({len(committed)} partitions)")
        return 0
    added = sorted(set(fresh["partitionKind"]) - set(committed))
    removed = sorted(set(committed) - set(fresh["partitionKind"]))
    changed = sorted(k for k in set(committed) & set(fresh["partitionKind"])
                     if committed[k] != fresh["partitionKind"][k])
    print(f"stale: committed {len(committed)}, live {len(fresh['partitionKind'])}; "
          f"added {len(added)}, removed {len(removed)}, changed {len(changed)}")
    for label, keys in (("removed", removed), ("changed", changed), ("added", added)):
        for key in keys[:10]:
            print(f"  {label}: {key}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
