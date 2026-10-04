"""seedsmith.adapters.items.basetypegen.reslate — the D11 clause-1 corpus repair verb.

⛔ **Why a generator verb and not a data edit.** `gk-data/packs/fusion/data/seed/items/base-types/**` is seedsmith
OUTPUT (every file carries `_meta.model`). Hand-editing a row's `implicit.family` to satisfy D11
would fork the corpus from its generator — the next run reverts it and the run ledger stops
describing the file (AGENTS.md / CLAUDE.md hard rule; `gk-core/scripts/guard-generated-seed.py` blocks it).
The sanctioned path is: a generator operation that rewrites the row, then commit the re-emitted
output.

**What it does.** For every enabled base-type entry whose `implicit.family` is NOT in its own
`(role, frame)` slate (`classes.v3.json.legalFamiliesByFrame`, minted 2026-09-12), reassign it to a
family that IS in that slate. Because the two frame slates are disjoint by construction, a corpus
where every entry satisfies this cannot violate D11 clause 1 — the repair is correct by
construction, not by hoping the model picks disjointly.

**Identity is preserved** (`seed-contract.md` §7.2: "entry is wrong, same identity → edit in place,
same id"). Only `implicit.family` moves; id, name, class, band, socketMax, enhanceTrack and tags are
untouched. The flavour text is the one prose field that can go stale when the family moves, so the
verb reports those rows for a separate re-flavour pass rather than silently leaving prose over a
different family.

**Deterministic choice.** When more than one family is legal, pick by a stable hash of the entry id
so two runs produce the same assignment, and prefer a family already used by a sibling on the same
frame (keeps the corpus visually varied rather than piling every moved row on one family).
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from . import tuning


@dataclass(frozen=True)
class ReslateChange:
    entry_id: str
    role: str
    frame: str
    old_family: str
    new_family: str


@dataclass(frozen=True)
class ReslateReport:
    changed: "tuple[ReslateChange, ...]"
    already_legal: int
    total: int

    def summary(self) -> dict:
        return {"total": self.total, "alreadyLegal": self.already_legal,
                "reslated": len(self.changed),
                "rows": [{"id": c.entry_id, "role": c.role, "frame": c.frame,
                          "from": c.old_family, "to": c.new_family} for c in self.changed]}


def _slate_for(role: str, frame: str) -> "tuple[str, ...]":
    return tuning.load_legal_implicit_families(role, frame)


def _pick(family_options: "tuple[str, ...]", entry_id: str, already_used: "dict[str, int]") -> str:
    """Deterministic, variety-preserving pick. `already_used` counts a family's current usage on
    this (role, frame); a family with the lowest count wins, ties broken by a stable hash of the
    entry id — so a repair never collapses every moved row onto alphabetically-first family."""
    lowest = min(already_used.get(f, 0) for f in family_options)
    candidates = sorted(f for f in family_options if already_used.get(f, 0) == lowest)
    digest = hashlib.sha256(entry_id.encode("utf-8")).hexdigest()
    return candidates[int(digest, 16) % len(candidates)]


def plan_reslate(*, base_types_dir: "Path | None" = None,
                 classes_path: "Path | None" = None) -> ReslateReport:
    """Compute the re-slate without writing. `--apply` persists it."""
    directory = base_types_dir or tuning.BASE_TYPES_DIR
    changes: "list[ReslateChange]" = []
    already_legal = 0
    total = 0

    for path in sorted(directory.glob("**/*.json")):
        if path.name.startswith("_") or path.parent.name.startswith("_"):
            continue
        doc = json.loads(path.read_text(encoding="utf-8"))
        entries = doc.get("entries") or []
        # usage per (role, frame) across the whole corpus, so the pick spreads evenly
        usage: "dict[tuple[str, str], dict[str, int]]" = {}
        for e in entries:
            if e.get("enabled") is False:
                continue
            key = (e.get("role"), e.get("frame"))
            fam = (e.get("implicit") or {}).get("family")
            usage.setdefault(key, {})
            if fam:
                usage[key][fam] = usage[key].get(fam, 0) + 1

        for e in entries:
            if e.get("enabled") is False:
                continue
            role, frame = e.get("role"), e.get("frame")
            if not role or not frame:
                continue
            total += 1
            slate = tuning.load_legal_implicit_families(role, frame) if classes_path is None else \
                tuning.load_legal_implicit_families(role, frame, classes_path)
            family = (e.get("implicit") or {}).get("family")
            if family in slate:
                already_legal += 1
                continue
            new_family = _pick(slate, e["id"], usage[(role, frame)])
            usage[(role, frame)][new_family] = usage[(role, frame)].get(new_family, 0) + 1
            changes.append(ReslateChange(e["id"], role, frame, family or "", new_family))

    return ReslateReport(changed=tuple(changes), already_legal=already_legal, total=total)


def apply_reslate(report: ReslateReport, *, base_types_dir: "Path | None" = None,
                  dry_run: bool = False) -> int:
    """Write the planned reassignment. Returns the number of rows changed. `implicit.powerBand` is
    preserved; only `implicit.family` moves."""
    if dry_run:
        return len(report.changed)
    directory = base_types_dir or tuning.BASE_TYPES_DIR
    by_id = {c.entry_id: c for c in report.changed}
    written = 0
    for path in sorted(directory.glob("**/*.json")):
        if path.name.startswith("_") or path.parent.name.startswith("_"):
            continue
        doc = json.loads(path.read_text(encoding="utf-8"))
        touched = False
        for e in doc.get("entries") or []:
            change = by_id.get(e.get("id"))
            if change is None:
                continue
            e.setdefault("implicit", {})["family"] = change.new_family
            touched = True
            written += 1
        if touched:
            path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    return written


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(
        description="D11 clause-1 repair: reassign an entry's implicit family onto its own frame's "
                    "slate (classes.v3.json). Generator operation; never hand-edit the corpus.")
    ap.add_argument("--dry-run", action="store_true", help="report the plan, write nothing")
    ap.add_argument("--apply", action="store_true", help="write the reassignment")
    ap.add_argument("--json", default="", help="write the full plan to this path")
    args = ap.parse_args(argv)

    report = plan_reslate()
    payload = report.summary()
    if args.json:
        Path(args.json).write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                                   encoding="utf-8", newline="\n")
    print(json.dumps({k: v for k, v in payload.items() if k != "rows"}, ensure_ascii=False, indent=2))

    if args.apply:
        written = apply_reslate(report)
        print(json.dumps({"written": written}, ensure_ascii=False))
    elif not args.dry_run:
        raise SystemExit("seedsmith: pass --dry-run to inspect or --apply to write")
    return 0


if __name__ == "__main__":  # pragma: no cover - dev entrypoint
    raise SystemExit(main())
