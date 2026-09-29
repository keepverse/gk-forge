"""seedsmith.adapters.items.namekey_repair — mechanical `nameKey` kind-prefix repair.

`nameKey`'s first segment must be one of `naming.v1.json`'s closed
`namingGrammar.nameKey.kindPrefixes` (`NamingCheck.cs`'s `NameKeyPrefix` check). A handful of legacy
partitions wrote the seed file's own JSON `"kind"` string verbatim instead of the registered short
form: `base-type.*` (kind `base-type`, correct prefix `base`), `drop-table.*` (kind `drop-table`,
correct prefix `droptable`), `affix-family.*` (kind `affix-family`, correct prefix `affix`).
Confirmed via a real ItemSeedValidator run: exactly 353 `NameKeyPrefix` errors (319 base-type, 33
drop-table, 1 affix-family), nothing else.

`nameKey` is a purely mechanical field here — derived from `name` + kind, carrying no creative
content of its own (`basetypegen.emit.name_key_for` already emits the correct `base.{slug}` form for
every NEW entry; these are legacy rows predating that convention). This repair is therefore a
deterministic string substitution on the FIRST segment only, never a model call, and it never touches
`name`, `iconKey`, `flavorKey`, or any gameplay field — the same "change only what a validator names,
never more" discipline `setgen.name_repair.repair_name_keys` already established for the placeholder
`set.item`/`charm.item` key defect.

⛔ The map below names only the three prefixes a real validator run found wrong, never a general
`kind -> nameKey prefix` deriver — a future kind whose own short-prefix convention differs
legitimately (e.g. one that is NOT its `kind` string with a hyphen dropped) is not silently rewritten
by guesswork.
"""
from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .setgen.seedfile import ITEM_SEED_ROOT

WRONG_PREFIX_TO_CORRECT: "dict[str, str]" = {
    "base-type": "base",
    "drop-table": "droptable",
    "affix-family": "affix",
}


@dataclass(frozen=True)
class NameKeyPrefixRepair:
    entry_id: str
    path: Path
    old_key: str
    new_key: str


def plan(items_root: "Path | None" = None) -> "tuple[NameKeyPrefixRepair, ...]":
    """Read-only: every entry whose `nameKey` starts with one of the known-wrong prefixes."""
    root = Path(items_root or ITEM_SEED_ROOT)
    repairs: "list[NameKeyPrefixRepair]" = []
    for path in sorted(root.glob("**/*.json")):
        if path.name.startswith("_") or "_exemplars" in path.parts or "_runs" in path.parts:
            continue
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        entries = document.get("entries")
        if not isinstance(entries, list):
            continue
        for row in entries:
            if not isinstance(row, dict):
                continue
            key = row.get("nameKey")
            if not isinstance(key, str) or "." not in key:
                continue
            prefix, _, rest = key.partition(".")
            correct = WRONG_PREFIX_TO_CORRECT.get(prefix)
            if correct is None or not rest:
                continue
            repairs.append(NameKeyPrefixRepair(
                entry_id=str(row.get("id") or "(no id)"), path=path,
                old_key=key, new_key=f"{correct}.{rest}"))
    return tuple(sorted(repairs, key=lambda r: (str(r.path), r.entry_id)))


def apply(repairs: "tuple[NameKeyPrefixRepair, ...]", *, write: bool) -> "tuple[Path, ...]":
    """Apply every planned repair. `write=False` reports what WOULD change without touching disk."""
    by_path: "dict[Path, dict[str, str]]" = {}
    for r in repairs:
        by_path.setdefault(r.path, {})[r.old_key] = r.new_key

    changed: "list[Path]" = []
    for path, mapping in by_path.items():
        document = json.loads(path.read_text(encoding="utf-8"))
        touched = False
        for row in document.get("entries") or ():
            if not isinstance(row, dict):
                continue
            key = row.get("nameKey")
            if isinstance(key, str) and key in mapping:
                row["nameKey"] = mapping[key]
                touched = True
        if touched:
            changed.append(path)
            if write:
                _atomic_json(path, document)
    return tuple(sorted(changed))


def report(repairs: "tuple[NameKeyPrefixRepair, ...]", *, write: bool) -> "dict[str, object]":
    return {
        "write": write,
        "changedEntries": len(repairs),
        "changedFiles": len({r.path for r in repairs}),
        "repairs": [{"id": r.entry_id, "path": str(r.path), "oldKey": r.old_key, "newKey": r.new_key}
                    for r in repairs],
    }


def _atomic_json(path: Path, document: dict) -> None:
    handle, temporary = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        # newline="\n" pins the literal byte this repo's committed JSON already uses on every
        # platform. Without it, Python's text-mode universal-newline translation writes the OS
        # default (CRLF on Windows) regardless of what was on disk before — found by running
        # test_production_write_path_round_trips_the_real_d1_byte_identical, which caught this
        # repair silently turning a committed LF file into CRLF.
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as output:
            output.write(json.dumps(document, ensure_ascii=False, indent=2) + "\n")
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise
