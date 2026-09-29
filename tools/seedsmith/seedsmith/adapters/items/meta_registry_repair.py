"""seedsmith.adapters.items.meta_registry_repair — mechanical `_meta.registryVersions` stamp bump.

A file's `_meta.registryVersions.<registry>` records which registry version its CONTENT was
authored against (seed-contract.md §9). `ItemSeedValidator`'s `MetaRegistryVersionMismatch` fires
when that stamp is below the registry's own `minCompatibleVersion` floor — a REAL "this content may
be stale" signal for a genuinely breaking bump, never something to paper over blindly.

⛔ **This module never decides that a bump is safe — the caller must have already proven it, per
(registry, old version, new version) triple, before calling `plan`.** It only performs the
mechanical write once that evidence exists. Reasoning recorded for item-seed-regen cause 5
(2026-09-20), core v1->v2 (D30, hybrid-role correction — see `core.v1.json`'s own `frozenNote`):
every one of the 121 files this run touched declared `_meta.registryVersions.core: 1`, but the ONLY
live downstream consequence of that bump is `RoleFamilyCheck.cs`'s `role-relocation.v1.json`
coverage check (a family legal on a role D30 dropped needs a relocation row) — a SEPARATE check on a
SEPARATE, already-generated artifact, not gated by this stamp at all, and it reports zero findings on
the current corpus. The other place hybrid-role eligibility could matter — a set's own member role
list — is enforced only at GENERATION-BRIEF time (`setgen.roles.HYBRID_CORE_ROLES` /
`SetRoleNotUniversal`, a load-time sanity check on the role-list CONFIG, never re-validated against
existing corpus entries by the C# validator); the 5 legacy hand-authored sets that use head-guard/
sense predate that mechanism entirely. So bumping the stamp changes no validated behavior on this
corpus today — it only makes the provenance record honest about which registry version the file has
actually been checked against, and it does NOT retroactively legalize content some other, more
specific check might still catch.

⛔ **Applies the bump as a surgical text edit, never a JSON load/dump round-trip.** The corpus mixes
encoding conventions across files (some `\\uXXXX`-escape every non-ASCII character, some write literal
UTF-8 — found live: `uniques/verdant-graft-90.json` had 7 escaped em-dashes in its flavor text; a
`json.dumps(..., ensure_ascii=False)` round-trip silently un-escaped every one of them, turning a
121-file, one-field-each metadata bump into an 839-line reformatting diff). Rewriting only the exact
`"registry": old_version` token inside the `_meta.registryVersions` object leaves every other byte —
including whichever escaping convention the file already uses — untouched.
"""
from __future__ import annotations

import json
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .setgen.seedfile import ITEM_SEED_ROOT

_REGISTRY_VERSIONS_OPEN = re.compile(r'"registryVersions"\s*:\s*\{')


@dataclass(frozen=True)
class MetaVersionBump:
    path: Path
    registry: str
    old_version: int
    new_version: int


def plan(registry: str, old_version: int, new_version: int,
        items_root: "Path | None" = None) -> "tuple[MetaVersionBump, ...]":
    """Every file whose `_meta.registryVersions[registry] == old_version`, for a single
    (registry, old, new) triple the CALLER has already decided is safe — never inferred here."""
    root = Path(items_root or ITEM_SEED_ROOT)
    bumps: "list[MetaVersionBump]" = []
    for path in sorted(root.glob("**/*.json")):
        if path.name.startswith("_") or "_runs" in path.parts:
            continue
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        meta = document.get("_meta")
        if not isinstance(meta, dict):
            continue
        versions = meta.get("registryVersions")
        if not isinstance(versions, dict):
            continue
        if versions.get(registry) == old_version:
            bumps.append(MetaVersionBump(path=path, registry=registry,
                                         old_version=old_version, new_version=new_version))
    return tuple(bumps)


def apply(bumps: "tuple[MetaVersionBump, ...]", *, write: bool) -> "tuple[Path, ...]":
    """Writes only the one `_meta.registryVersions[registry]` token, byte-preserving everything
    else. `write=False` reports what would change without touching disk. Raises `ValueError` rather
    than guessing if the exact token cannot be found (a file `plan()` already confirmed has it)."""
    changed: "list[Path]" = []
    for bump in bumps:
        text = bump.path.read_text(encoding="utf-8")
        new_text = _bump_in_text(text, bump.registry, bump.old_version, bump.new_version)
        if new_text is None:
            raise ValueError(
                f"{bump.path}: could not surgically locate registryVersions.{bump.registry} "
                f"== {bump.old_version} to replace")
        # Never write a text edit this module cannot itself re-parse back to the intended value —
        # cheap insurance against a regex mismatch corrupting the file.
        reparsed = json.loads(new_text)
        if reparsed.get("_meta", {}).get("registryVersions", {}).get(bump.registry) != bump.new_version:
            raise ValueError(f"{bump.path}: post-edit re-parse did not show the expected new "
                             f"value; refusing to write")
        changed.append(bump.path)
        if write:
            _atomic_write(bump.path, new_text)
    return tuple(changed)


def _bump_in_text(text: str, registry: str, old_version: int, new_version: int) -> "str | None":
    """Replace `"registry": old_version` inside the FIRST `"registryVersions": { ... }` object,
    leaving every other byte in the file untouched. `registryVersions` values are always bare
    integers (no nested strings/objects), so a simple brace-depth scan safely finds the matching
    close brace."""
    open_match = _REGISTRY_VERSIONS_OPEN.search(text)
    if open_match is None:
        return None
    open_index = open_match.end() - 1  # the '{' itself
    close_index = _matching_brace(text, open_index)
    if close_index is None:
        return None

    block = text[open_index:close_index + 1]
    key_pattern = re.compile(rf'("{re.escape(registry)}"\s*:\s*){old_version}\b')
    new_block, count = key_pattern.subn(rf"\g<1>{new_version}", block, count=1)
    if count != 1:
        return None
    return text[:open_index] + new_block + text[close_index + 1:]


def _matching_brace(text: str, open_index: int) -> "int | None":
    depth = 0
    for i in range(open_index, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return i
    return None


def _atomic_write(path: Path, text: str) -> None:
    handle, temporary = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        # newline="\n": preserve the file's own line endings exactly — `text` already carries them
        # verbatim from the original read, so this must not translate anything.
        with os.fdopen(handle, "w", encoding="utf-8", newline="") as output:
            output.write(text)
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise
