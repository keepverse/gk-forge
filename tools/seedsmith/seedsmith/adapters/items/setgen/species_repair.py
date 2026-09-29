"""seedsmith.adapters.items.setgen.species_repair — species-gear-chain T28 (`set-species-binding` b).

Deterministic, model-free backward repair: every shipped `set` entry gets a `speciesId` (a real id
or explicit absence), read as a JOIN against the creature theme registry, never derived from
`themeKey` by string surgery alone and never guessed by a model.

⛔ **Case-normalising by necessity, not by convenience** (spec-set-species-binding.md Code style):
`themeKey` ships lower-case (``creature.abyssswordstar``); the registry's own `speciesId` field is
ALSO lower-case (``abyssswordstar``) — the same spelling `CreatureSpeciesCatalog` (the C# runtime
catalog) uses. The registry is the PRIMARY join (a missing key fails loudly); the suffix parsed off
`themeKey` is a CROSS-CHECK, not a fallback — a disagreement between the two is a refusal, never a
silent pick of either alone.

⛔ **"No species" and "species not found" must never collapse into the same value.** A `build.*` /
`theme.*` themeKey has no species — that is `None`, an explicit fact. A `creature.*` themeKey that
fails to resolve (missing registry row, or the row disagrees with the suffix) is an ERROR: the
caller refuses and reports it, never writes an absent value in its place.
"""
from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .seedfile import ITEM_SEED_ROOT
from .themes import CREATURE_THEME_REGISTRY


class SpeciesRepairError(ValueError):
    """A `creature.*` themeKey that could not be resolved to a speciesId — refused, never guessed."""


def load_theme_species_registry(path: "Path | None" = None) -> "dict[str, str]":
    """`themeKey -> speciesId` (lower-case), read fresh from the creature theme registry every call —
    never cached across a repair run, so a concurrent regeneration of the registry (a real ordering
    risk this spec names explicitly: `ladder-consistency-repair` rewrites this same file) is picked
    up rather than silently stale."""
    doc = json.loads((path or CREATURE_THEME_REGISTRY).read_text(encoding="utf-8"))
    out: "dict[str, str]" = {}
    for theme_key, row in doc["themes"].items():
        species_id = row.get("speciesId")
        if isinstance(species_id, str) and species_id:
            out[theme_key] = species_id
    return out


def species_for_theme(theme_key: str, registry: "dict[str, str]") -> "str | None":
    """`themeKey -> speciesId`, or `None` for a theme with no species.

    Returns `None` ONLY for a non-`creature.*` theme (`build.*`/`theme.*`), which is an explicit
    ABSENT value. A `creature.*` key that fails to resolve — no registry row, or the row's
    `speciesId` disagrees with the themeKey's own suffix — raises `SpeciesRepairError`; the caller
    must refuse and report it, never write absent in its place.
    """
    prefix, _, rest = theme_key.partition(".")
    if prefix != "creature":
        return None

    registered = registry.get(theme_key)
    if registered is None:
        raise SpeciesRepairError(
            f"'{theme_key}' has no row in the creature theme registry ({CREATURE_THEME_REGISTRY}) — "
            "a creature.* themeKey must resolve to a species; refusing rather than writing absent")

    suffix_guess = rest.lower()
    if registered.lower() != suffix_guess:
        raise SpeciesRepairError(
            f"'{theme_key}': registry speciesId {registered!r} disagrees with the themeKey's own "
            f"suffix {suffix_guess!r} — the join and the parse must agree; refusing rather than "
            "trusting either alone")
    return registered


@dataclass(frozen=True)
class SpeciesRepairFile:
    path: Path
    changed_entries: int
    total_entries: int


def write_document(path: Path, document: dict) -> None:
    """Atomically replace `path` with `document`, LF-terminated and in the file's OWN escaping style.

    Shared with `topology_repair`: the two repairs write the SAME corpus, so they must agree byte for
    byte about how a partition file is serialised — otherwise running repair-species and then
    repair-set-class would produce a two-line diff where one line was intended.

    `newline="\n"` is load-bearing: text-mode `os.fdopen` otherwise writes the OS default line ending
    (CRLF on Windows) even when the source document was LF, silently rewriting all 17,491 lines of a
    file the change meant to touch once (see `name_repair._atomic_json`'s note and the todo row filed
    for the sibling creature-theme writers, which hit exactly this).

    `ensure_ascii` is **derived from the file being rewritten**, not fixed: a partition that ships
    `\u00a7` escapes keeps them, one that ships raw UTF-8 keeps that. Fixing it either way rewrites
    unrelated `flavor`/`notes` lines — measured on the real corpus, `ensure_ascii=False` alone turned
    six `\u2014`/`\u00a7` sequences into literal em dashes and section signs across the six legacy
    partitions, so a repair whose entire point is a ONE-LINE-PER-ENTRY diff would have shipped six
    lines nobody asked for.
    """
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    ensure_ascii = "\\u" in existing and not any(ord(char) > 127 for char in existing)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp",
                                     dir=str(path.parent), text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(document, ensure_ascii=ensure_ascii, indent=2) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def plan_set_partitions(target: Path) -> "list[tuple[Path, dict]]":
    """Every `set` partition under `target`, parsed, in sorted filename order.

    Sorted order is not incidental: both repairs report and write in this order, which is what makes
    a run reproducible and a refusal identify the FIRST offending file rather than an arbitrary one.
    """
    partitions: "list[tuple[Path, dict]]" = []
    for path in sorted(target.glob("*.json")):
        document = json.loads(path.read_text(encoding="utf-8"))
        if document.get("kind") != "set":
            continue
        partitions.append((path, document))
    return partitions


def repair_species_ids(*, sets_dir: "Path | None" = None,
                       registry_path: "Path | None" = None,
                       write: bool = False) -> "tuple[SpeciesRepairFile, ...]":
    """Plan or apply `speciesId` for every production `set` partition.

    `write=False` is a read-only plan (the same contract `repair_set_corpus` in `repair.py`
    already established). Idempotent and deterministic: no RNG, no model call, and re-running over
    an already-repaired tree changes nothing (the field, once correct, never disagrees with itself).
    An entry that already carries the correct `speciesId` is left untouched, byte for byte.
    """
    target = Path(sets_dir or (ITEM_SEED_ROOT / "sets")).resolve()
    registry = load_theme_species_registry(registry_path)
    result: "list[SpeciesRepairFile]" = []

    for path, document in plan_set_partitions(target):
        changed = 0
        entries = document.get("entries") or []
        for entry in entries:
            entry_id = entry.get("id")
            theme_key = entry.get("themeKey")
            if not isinstance(entry_id, str) or not entry_id:
                raise ValueError(f"{path}: set entry has no string id")
            if not isinstance(theme_key, str) or not theme_key:
                raise ValueError(f"{path}: set entry {entry_id!r} has no string themeKey")

            resolved = species_for_theme(theme_key, registry)
            existing = entry.get("speciesId")
            if resolved is None:
                if "speciesId" in entry:
                    del entry["speciesId"]
                    changed += 1
                continue
            if existing != resolved:
                entry["speciesId"] = resolved
                changed += 1

        if changed and write:
            write_document(path, document)
        if changed:
            result.append(SpeciesRepairFile(path=path, changed_entries=changed,
                                            total_entries=len(entries)))
    return tuple(result)


def repair_report(files: "tuple[SpeciesRepairFile, ...]", *, write: bool) -> "dict[str, Any]":
    return {
        "write": write,
        "files": [{"path": str(f.path), "changedEntries": f.changed_entries,
                   "totalEntries": f.total_entries} for f in files],
        "changedFiles": len(files),
        "changedEntries": sum(f.changed_entries for f in files),
    }
