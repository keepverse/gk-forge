"""seedsmith.adapters.items.basetypegen.resocket — the deterministic `socketMax` re-stamp verb
(spec-circuit-topology.md §5, strain-splice-host SSH5.11).

⛔ **Why a generator verb and not a data edit.** `gk-data/packs/fusion/data/seed/items/base-types/**` is seedsmith OUTPUT
(every file carries `_meta.model`). Hand-editing a row's `socketMax` after `sockets.v2.json` widened
the per-role ceilings would fork the corpus from its generator — the next `base-types-gen` run
reverts it and the run ledger stops describing the file (AGENTS.md / CLAUDE.md hard rule). The
sanctioned path is a generator operation that rewrites the row, then commits the re-emitted output;
`--write` is the owner-run SSH5.12, never a hand edit.

**What it does.** For every enabled base-type entry it recomputes `socketMax` through the ONE
resolver, `tuning.resolve_socket_max(role, band, seq_index)`, under the CURRENT sockets revision
(`gk-core/data/tuning/sockets.v2.json`, named once by `SocketTuningFiles.Current` on the C# side and by
`combogen/tuning.SOCKETS_PATH` here). No model call, no formula, nothing random.

**The `seq` is the row's own position.** The corpus does not store `seq`; the generator assigns
`socketMax` from `seq_index = seq - 1` where `seq` is the emission order, which IS the row's 0-based
position in its partition file's `entries` array. Recovering it from the file order (not from the id
suffix, which survives across batches and does not restart per partition) is what makes the re-stamp
deterministic and reproducible.

**Identity is preserved.** Only `socketMax` moves; id, nameKey, name, class, band, `implicit`,
`enhanceTrack`, `tags` and `flavor` are kept. On `--write`, one `_meta.amendments` record documents
the batch (this corpus's own established convention, e.g. `recipegen`'s legacy-shard migration).
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from . import tuning

#: The `_meta.amendments` batch id and the cite a reviewer reads for WHY the value moved.
AMENDMENT_BATCH = "resocket"
SOURCE_REF = "docs/architecture/strain-splice-host/spec-circuit-topology.md#5"


@dataclass(frozen=True)
class ResocketChange:
    entry_id: str
    role: str
    band: str
    old_socket_max: int
    new_socket_max: int
    seq_index: int

    def to_dict(self) -> dict:
        return {"id": self.entry_id, "role": self.role, "band": self.band,
                "from": self.old_socket_max, "to": self.new_socket_max, "seqIndex": self.seq_index}


@dataclass(frozen=True)
class ResocketReport:
    changed: tuple[ResocketChange, ...]
    unchanged: int
    total: int

    def summary(self) -> dict:
        return {"total": self.total, "unchanged": self.unchanged,
                "resocketed": len(self.changed),
                "rows": [c.to_dict() for c in self.changed]}


def plan_resocket(*, base_types_dir: Path | None = None,
                  sockets_path: Path | None = None,
                  gen_tuning: tuning.GenTuning | None = None) -> ResocketReport:
    """Compute the re-stamp without writing. `--dry-run` prints this; `--write` persists it."""
    directory = base_types_dir or tuning.BASE_TYPES_DIR
    gt = gen_tuning or tuning.load_gen_tuning()
    changes: list[ResocketChange] = []
    unchanged = 0
    total = 0

    for path in sorted(directory.glob("**/*.json")):
        if path.name.startswith("_") or path.parent.name.startswith("_"):
            continue
        doc = json.loads(path.read_text(encoding="utf-8"))
        if doc.get("kind") != "base-type":
            continue
        for seq_index, entry in enumerate(doc.get("entries") or []):
            if entry.get("enabled") is False:
                continue
            role, band = entry.get("role"), entry.get("band")
            if not role or not band or "socketMax" not in entry:
                continue
            total += 1
            new_max = tuning.resolve_socket_max(role, band, seq_index, gen_tuning=gt,
                                                sockets_path=sockets_path)
            if new_max == entry["socketMax"]:
                unchanged += 1
                continue
            changes.append(ResocketChange(entry["id"], role, band, int(entry["socketMax"]),
                                          new_max, seq_index))

    return ResocketReport(changed=tuple(changes), unchanged=unchanged, total=total)


def apply_resocket(report: ResocketReport, *, base_types_dir: Path | None = None,
                   dry_run: bool = False, authored_utc: str = "") -> int:
    """Write the planned `socketMax` values. Returns the number of rows changed. Idempotent: a
    second call after a write plans nothing, because every row then equals its own resolution."""
    if dry_run:
        return len(report.changed)

    directory = base_types_dir or tuning.BASE_TYPES_DIR
    by_id = {c.entry_id: c for c in report.changed}
    written = 0
    for path in sorted(directory.glob("**/*.json")):
        if path.name.startswith("_") or path.parent.name.startswith("_"):
            continue
        doc = json.loads(path.read_text(encoding="utf-8"))
        if doc.get("kind") != "base-type":
            continue
        touched = [entry["id"] for entry in doc.get("entries") or []
                   if entry.get("id") in by_id]
        if not touched:
            continue

        for entry in doc["entries"]:
            change = by_id.get(entry.get("id"))
            if change is None:
                continue
            entry["socketMax"] = change.new_socket_max
            written += 1

        meta = doc.get("_meta") or {}
        amendment = {
            "batch": AMENDMENT_BATCH,
            "note": (
                "socketMax re-stamped through base-types-gen's ONE resolver "
                "(resolve_socket_max(role, band, seq)) under the current sockets revision. Only "
                "socketMax moved; id, nameKey, name, class, band, implicit, enhanceTrack, tags and "
                "flavor are preserved. No live model call — a mechanical re-stamp, no prompt."
            ),
            "promptVersion": "n/a-mechanical-resocket",
            "model": AMENDMENT_BATCH,
            "authoredUtc": authored_utc,
            "sourceRef": SOURCE_REF,
            "entries": sorted(touched),
        }
        doc["_meta"] = {**meta, "amendments": [*meta.get("amendments", []), amendment]}
        path.write_text(json.dumps(doc, ensure_ascii=False, sort_keys=False, indent=2) + "\n",
                        encoding="utf-8")

    return written


def main(argv=None) -> int:
    import argparse

    ap = argparse.ArgumentParser(
        description="Re-stamp base-type socketMax through resolve_socket_max under the current "
                    "sockets revision. Generator operation; never hand-edit the corpus.")
    ap.add_argument("--dry-run", action="store_true", help="print the diff, write nothing")
    ap.add_argument("--write", action="store_true",
                    help="persist the re-stamp and its _meta.amendments record (owner-run)")
    ap.add_argument("--json", default="", help="write the full plan to this path")
    ap.add_argument("--authored-utc", dest="authored_utc", default="1970-01-01T00:00:00Z",
                    help="the _meta timestamp; injected, never read from the clock")
    args = ap.parse_args(argv)

    report = plan_resocket()
    payload = report.summary()
    if args.json:
        Path(args.json).write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                                   encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))

    if args.write:
        written = apply_resocket(report, authored_utc=args.authored_utc)
        print(json.dumps({"written": written}, ensure_ascii=False))
    elif not args.dry_run:
        raise SystemExit("seedsmith: pass --dry-run to inspect or --write to re-stamp")
    return 0


if __name__ == "__main__":  # pragma: no cover - module entrypoint
    raise SystemExit(main())
