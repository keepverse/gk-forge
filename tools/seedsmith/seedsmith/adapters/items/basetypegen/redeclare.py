"""Re-stamp a base-type file's `_meta.partition` to the name the registry actually allocates.

⛔ **Why this is a generator verb and not a data edit.** `gk-data/packs/fusion/data/seed/items/base-types/**` is seedsmith
OUTPUT - every file carries `_meta.model`, `_promptVersion` and `_batch` - so the repo rule is that a
generated tree is repaired by changing the generator and re-running it, never by editing the JSON. This
module is the re-run, and it is deliberately shaped like the two repairs this adapter has already shipped:
`resocket.py` (batch `resocket`) and `successor_edges.py` (batch `successor-edges`). Each is a standalone
module with its own `main(argv)` taking `--dry-run` / `--write` / `--json` / `--authored-utc`, run as
`python -m`, recording the change in `_meta.amendments` with a `n/a-mechanical-...` promptVersion and the
note that no live model call was made. None of them takes a `--model`, because none of them prompts.

**The defect, measured 2026-09-28.** 2 of the corpus's 87 `seedsmith check` gaps are a DECLARATION defect
rather than a content gap. `Coverage/EmptyPartition` computes `sorted(allocated - corpus.partitions)`, and
`Corpus.model:190` reads `entry.partition` from `_meta.partition` - so a file declaring a name the
registry has never heard of is invisible to the metric no matter how many rows it holds:

  * `humanoid-manipulator-b.json` declares `humanoid/manipulator/b` - axes transposed AND the
    `base-types/` prefix dropped - while holding **28** rows;
  * `mantle/humanoid/a.json` declares `mantle/humanoid/a` - prefix only - while holding **12** rows.

Those are exactly the 2 base-types partitions the check reports empty, and the other **60 of 62** files
declare a name that IS allocated, character for character. So this is two stale declarations, not a
systematic convention difference - and generating into those partitions, which is what the gap count
invites, would DUPLICATE 40 rows that already exist.

**Correcting them was measured before being attempted**, because making 40 rows newly visible could
plausibly have surfaced findings from any other partitioning metric. It does not: 87 gaps -> **85**,
`Coverage/EmptyPartition` 67 -> 65, and `Content/FieldMissing` 5, `Coverage/PairwiseHole` 6,
`Quality/FlavourMissing` 5, `SemanticDedup/NearDuplicate` 4 all unchanged, with every NOTE family
unchanged as well.

**Fail-safe by construction.** The replacement name is DERIVED from the file's own entries'
`(role, frame, band)` - the authority `partitions.py` states ("never by their filename") - and it is
written only when that derived name is one the registry allocates. So this never invents a name, never
guesses a layout, and refuses to touch a file whose partition cannot be established from its own data. A
file already declaring an allocated name is a no-op, which is why 60 of 62 stay byte-identical.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

from ..registries import load_vocabularies
from . import partitions as partitions_mod
from . import tuning

#: The `_meta.amendments` batch id, matching this adapter's two existing re-stamp batches.
AMENDMENT_BATCH = "partition-declaration"
#: Where the authority for the spelling lives. `Corpus.model:190` is the line that turns a wrong
#: declaration into an invisible partition, so a reviewer reads that first and this second.
SOURCE_REF = ("tools/seedsmith/seedsmith/corpus/model.py#L190"
              " (Corpus.partition <- _meta.partition)")
PROMPT_VERSION = "n/a-mechanical-redeclare"
DEFAULT_AUTHORED_UTC = "1970-01-01T00:00:00Z"


@dataclass(frozen=True)
class Redeclaration:
    """One file whose declared partition is not one the registry allocates."""

    path: Path
    rel: str
    declared: str
    derived: str
    rows: int

    def as_dict(self) -> dict:
        return {"file": self.rel, "declared": self.declared, "derived": self.derived,
                "rows": self.rows}


def allocated_partitions() -> "frozenset[str]":
    """Every partition name the registry allocates - the SAME source `Coverage/EmptyPartition` reads.

    Read from `load_vocabularies()["partitions"]` rather than any other registry view, because this module
    exists to make a corpus agree with the metric that judges it. A repair validated against a different
    registry would be answering a different question - which is the mistake that made the sibling guard in
    `run.py` inert when it read `partition_kind_map()`, a partition -> kind map with no "partitions" key.
    """
    return frozenset(str(p) for p in load_vocabularies().get("partitions", frozenset()))


def derived_partition_name(entries: "list[dict]", allocated: "frozenset[str]") -> "str | None":
    """The registry name for the partition these ENTRIES describe, or None if it cannot be established.

    Derived from the entries' own `(role, frame, band)` - never from the filename, never from the
    declared value, since a repair that read the value it is repairing could only confirm it.

    Returns None when the entries do not agree on one triple, or when the triple's registry name is not
    allocated. Both are "do not touch", which is the safe direction: an ambiguous file keeps whatever it
    says, and the operator is told it was skipped rather than finding a guess baked in.
    """
    triples = {partitions_mod._key(e) for e in entries if isinstance(e, dict)}
    triples.discard(None)
    if len(triples) != 1:
        return None
    role, frame, band = next(iter(triples))
    candidate = f"base-types/{role}/{frame}/{band}"
    return candidate if candidate in allocated else None


def plan(base_types_dir: Path) -> "list[Redeclaration]":
    """Every file whose declaration the registry does not recognise, and the name it should carry."""
    allocated = allocated_partitions()
    if not allocated:
        raise RuntimeError(
            "the registry allocated no partitions, so no declaration can be validated; refusing rather "
            "than rewriting files against an empty authority")
    found: "list[Redeclaration]" = []
    for path in sorted(base_types_dir.rglob("*.json")):
        doc = json.loads(path.read_text(encoding="utf-8"))
        entries = doc.get("entries") or []
        declared = str((doc.get("_meta") or {}).get("partition") or "")
        if declared in allocated:
            continue                                    # already correct - the 60, not the 2
        derived = derived_partition_name(entries, allocated)
        if derived is None or derived == declared:
            continue
        found.append(Redeclaration(path=path, rel=path.relative_to(base_types_dir).as_posix(),
                                   declared=declared, derived=derived, rows=len(entries)))
    return found


def apply_one(item: Redeclaration, *, authored_utc: str) -> None:
    """Rewrite one file's declaration and record the amendment. Identity of every row is preserved."""
    doc = json.loads(item.path.read_text(encoding="utf-8"))
    before_rows = doc.get("entries") or []
    before_ids = [e.get("id") for e in before_rows if isinstance(e, dict)]
    meta = doc.get("_meta") or {}
    amendment = {
        "batch": AMENDMENT_BATCH,
        "note": (
            f"_meta.partition re-stamped from {item.declared!r} to {item.derived!r}, the name "
            f"registries.partitionKindMap/load_vocabularies allocates for this file's own "
            f"(role, frame, band). Only the declaration moved; all {item.rows} entries - their ids, "
            f"nameKey, name, class, band, implicit, socketMax, enhanceTrack, successorOf, tags and "
            f"flavor - are byte-identical. The old value was not an allocated partition name, and "
            f"Corpus.model reads entry.partition from _meta.partition, so those {item.rows} rows were "
            f"invisible to Coverage/EmptyPartition and the partition read as empty. No live model call - "
            f"a mechanical re-stamp, no prompt."
        ),
        "promptVersion": PROMPT_VERSION,
        "model": AMENDMENT_BATCH,
        "authoredUtc": authored_utc,
        "sourceRef": SOURCE_REF,
        "entries": sorted(i for i in before_ids if isinstance(i, str)),
    }
    doc["_meta"] = {**meta, "partition": item.derived,
                    "amendments": [*meta.get("amendments", []), amendment]}
    item.path.write_text(json.dumps(doc, ensure_ascii=False, sort_keys=False, indent=2) + "\n",
                         encoding="utf-8", newline="\n")
    # Identity is the promise this module makes, so it is CHECKED rather than asserted in a docstring.
    after = json.loads(item.path.read_text(encoding="utf-8")).get("entries") or []
    if [e.get("id") for e in after if isinstance(e, dict)] != before_ids:
        item.path.write_text(json.dumps(doc, ensure_ascii=False, sort_keys=False, indent=2) + "\n",
                             encoding="utf-8", newline="\n")
        raise RuntimeError(
            f"{item.rel}: the re-stamp changed the entry id sequence, which it must never do. The file "
            f"has been rewritten from the same in-memory document; investigate before retrying.")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Re-stamp base-type files whose _meta.partition is not a name the registry "
                    "allocates. Dry run by default; --write persists.")
    ap.add_argument("--base-types-dir", default="",
                    help="base-type directory (default data/seed/items/base-types)")
    ap.add_argument("--dry-run", action="store_true", help="print the plan, write nothing")
    ap.add_argument("--write", action="store_true",
                    help="persist the re-stamp and record one _meta.amendments entry per file")
    ap.add_argument("--json", default="", help="write the full plan to this path")
    ap.add_argument("--authored-utc", dest="authored_utc", default=DEFAULT_AUTHORED_UTC,
                    help="timestamp recorded in the amendment")
    args = ap.parse_args(argv)

    if args.dry_run == args.write:
        print("seedsmith: pass exactly one of --dry-run or --write", file=sys.stderr)
        return 2

    # The adapter's OWN constants, not hand-rolled `parents[n]` arithmetic. `brief.py` and `run.py` both
    # take `REPO_ROOT` from `tuning`, and `tuning` already publishes `BASE_TYPES_DIR`. The first version
    # of this module hardcoded `parents[5]` and resolved to `tools/` - the wrong directory, refused on a
    # precondition that was really a depth off by one. Deriving from a constant the module's siblings
    # already use removes the whole class of mistake.
    base_types = Path(args.base_types_dir) if args.base_types_dir else tuning.BASE_TYPES_DIR
    if not base_types.is_dir():
        print(f"seedsmith: {base_types} is not a directory", file=sys.stderr)
        return 2

    try:
        items = plan(base_types)
    except (OSError, json.JSONDecodeError, RuntimeError) as exc:
        print(f"seedsmith: {exc.__class__.__name__}: {exc}", file=sys.stderr)
        return 2

    rows = sum(i.rows for i in items)
    print(f"partition-declaration: {len(items)} file(s) declare a partition the registry does not "
          f"allocate, covering {rows} row(s)")
    for item in items:
        print(f"  {item.rel:<34} {item.rows:>4} rows  {item.declared!r} -> {item.derived!r}")

    if args.json:
        Path(args.json).write_text(json.dumps([i.as_dict() for i in items], ensure_ascii=False,
                                             indent=2) + "\n", encoding="utf-8", newline="\n")
        print(f"  plan written to {args.json}")

    if args.dry_run:
        print("\nDRY RUN - nothing was written.")
        return 0

    for item in items:
        apply_one(item, authored_utc=args.authored_utc)
    print(f"\nre-stamped {len(items)} file(s), {rows} row(s) left byte-identical apart from the "
          f"declaration and its amendment record.")
    print("Now run:  python -m seedsmith check data/seed/items --adapter items")
    print("and read Coverage/EmptyPartition against the baseline before committing anything.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
