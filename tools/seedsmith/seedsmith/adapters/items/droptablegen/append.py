"""seedsmith.adapters.items.droptablegen.append — the targeted append operation
(spec-relic-item-kind.md §Design 4a, empire-development Task 1.3b).

The genuinely new capability in this module: every existing `droptablegen` entry point mints a
brand-NEW `droptable.*` row, but the seven real `SourceKind`s (`web-wave`, `expedition-tier`,
`world-sector`, `dungeon-room`, `dungeon-clear`, `dungeon-quest`, `siege-assault`) already resolve
to ALREADY-SHIPPED table ids via their `loot_source` rows. This operation adds ONE new group
(`<slug>-relic`) carrying `Relic`-kind entries into ONE existing, on-disk `droptable.*` row,
addressed by its own id.

Same discipline as every other write path in this adapter:

- validate-then-write: id grammar, legal `dropBand`, and a ref resolved against the real relic
  corpus are all checked BEFORE anything touches disk (`emit`'s own `MintRefused` /
  `IllegalChoiceError`, the same errors `assemble_entry` raises for a brand-new table);
- the production write goes through `run._write_document` (atomic tempfile + `os.replace`,
  `indent=2`, `_meta` preserved verbatim) -- the same function `write_corpus` uses, so every
  untouched row/group in the file stays byte-identical;
- never silently duplicates: a table that already carries a `<slug>-relic` group refuses with
  `IdCollisionError` instead of appending a second one;
- refuses without `--write` on the CLI, mirroring `run.main`'s own `--write` gate.

Wiring into `items generate` / `items fill` (`--append <table-id> --entry-kind relic --ref ...
--drop-band ... --write`) is Task 1.3c's own content-task call -- the flag name is deliberately
not locked here. This module is the operation those flags will call.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

from . import emit as emit_mod
from . import run as run_mod
from . import tuning

#: `droptable.d{slot}-{seq:03}` -- the slot selects the `d{slot}.json` partition file to rewrite.
_TABLE_SLOT_RE = re.compile(r"^droptable\.d([1-4])-\d{3}$")


def _partition_file_for(table_id: str, drop_tables_dir: "Path | None" = None) -> "tuple[Path, int]":
    m = _TABLE_SLOT_RE.match(table_id)
    if m is None:
        raise emit_mod.MintRefused(
            f"{table_id!r} fails the droptable.d<slot>-<seq:03> id grammar -- "
            f"an append targets one existing table, never mints an id outside the grammar")
    slot = int(m.group(1))
    directory = drop_tables_dir or tuning.DROP_TABLES_DIR
    return directory / f"d{slot}.json", slot


def _relic_group_key(entry: "dict[str, Any]") -> str:
    """`<slug>-relic`, derived from the entry's own `nameKey` (`droptable.<slug>`) -- the same
    `<slug>-<kind>` group split every shipped table already uses (`-gear`/`-mat`/`-con`/`-ins`/
    `-cur`). Falls back to slugging the display `name` only for entries that predate `nameKey`."""
    name_key = entry.get("nameKey")
    if isinstance(name_key, str) and name_key.startswith("droptable."):
        slug = name_key[len("droptable."):]
        if slug and re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", slug):
            return f"{slug}-relic"
    name = entry.get("name")
    if not isinstance(name, str) or not name:
        raise emit_mod.MintRefused(
            f"table {entry.get('id')!r} carries neither a usable nameKey nor a name -- "
            f"no slug to derive a relic group key from")
    return f"{emit_mod.slug_from_name(name)}-relic"


def append_relic_group(*, table_id: str, relic_ref: str, drop_band: str,
                       drop_tables_dir: "Path | None" = None,
                       relics_dir: "Path | None" = None,
                       dry_run: bool = False) -> "dict[str, Any]":
    """Append exactly one `Relic`-kind group to the existing on-disk table `table_id`.

    Returns the appended group dict (`{"groupKey": ..., "entries": [...]}`). With
    `dry_run=True` nothing is written and the returned group is what WOULD be appended.
    Otherwise the table's partition file is rewritten through `run._write_document` with every
    other entry untouched.
    """
    # Validate-then-write, in the same order `assemble_entry` validates a brand-new table:
    # id grammar first, then the band vocabulary, then the corpus-backed ref.
    path, _slot = _partition_file_for(table_id, drop_tables_dir)
    legal_bands = tuning.load_drop_band_enum()
    if drop_band not in legal_bands:
        raise emit_mod.IllegalChoiceError(
            f"dropBand {drop_band!r} is not one of {legal_bands}")
    legal_relics = tuning.load_relic_ids(relics_dir)
    row = emit_mod._relic_row(relic_ref, drop_band, legal_relics)

    if not path.exists():
        raise emit_mod.MintRefused(
            f"{path} does not exist -- an append targets a shipped partition file, "
            f"never creates one (mint a new table through run.plan_run instead)")
    doc = json.loads(path.read_text(encoding="utf-8"))
    entries = doc.get("entries", [])
    target: "dict[str, Any] | None" = next(
        (e for e in entries if e.get("id") == table_id), None)
    if target is None:
        raise emit_mod.MintRefused(
            f"{table_id!r} is not in {path} -- an append targets one existing table id")

    group_key = _relic_group_key(target)
    if any(g.get("groupKey") == group_key for g in target.get("groups", [])):
        raise emit_mod.IdCollisionError(
            f"{table_id!r} already carries group {group_key!r} -- refusing a second "
            f"relic append rather than duplicating it")
    group = {"groupKey": group_key, "entries": [row]}

    if dry_run:
        return group

    new_target = {**target, "groups": [*target.get("groups", []), group]}
    doc["entries"] = [new_target if e.get("id") == table_id else e for e in entries]
    run_mod._write_document(path, doc)
    return group


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Append ONE Relic-kind group to an existing drop-table row.")
    ap.add_argument("--table", required=True,
                    help="the existing table id, e.g. droptable.d1-001")
    ap.add_argument("--ref", required=True,
                    help="the relic anchor id, e.g. relic.ember-001")
    ap.add_argument("--drop-band", required=True, help="one of the bands.v1.json dropBand enum")
    ap.add_argument("--write", action="store_true",
                    help="rewrite the partition file back to disk")
    ap.add_argument("--drop-tables-dir", default="",
                    help="override the drop-tables directory (tests/dev only)")
    ap.add_argument("--relics-dir", default="",
                    help="override the relics corpus directory (tests/dev only)")
    args = ap.parse_args(argv)

    if not args.write:
        raise SystemExit(
            "seedsmith: refused -- no --write. Re-run with --write to actually rewrite the "
            "partition file through the validate-then-write path.")

    group = append_relic_group(
        table_id=args.table, relic_ref=args.ref, drop_band=args.drop_band,
        drop_tables_dir=Path(args.drop_tables_dir) if args.drop_tables_dir else None,
        relics_dir=Path(args.relics_dir) if args.relics_dir else None)
    print(json.dumps({"appended": group["groupKey"], "table": args.table,
                      "entries": group["entries"]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover - dev entrypoint
    raise SystemExit(main())
