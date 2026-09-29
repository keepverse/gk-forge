"""Locate base-type partitions by their authored entries, never by their filename.

The shipping corpus predates the generator and uses root files, display-name aliases, and nested
role/frame/band directories.  A filename is therefore not an authority for a partition key.  The
entry's own ``(role, frame, band)`` fields are.  This module makes planning, briefing, and writing
use that same authority so a resume cannot split one real partition into two files.
"""
from __future__ import annotations

import json
from pathlib import Path


class PartitionAmbiguityError(ValueError):
    """More than one file claims a partition, so an additive write would be unsafe."""


def _entries(path: Path) -> list[dict]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    entries = document.get("entries") if isinstance(document, dict) else None
    return [entry for entry in entries or () if isinstance(entry, dict)]


def _key(entry: dict) -> tuple[str, str, str] | None:
    role, frame, band = entry.get("role"), entry.get("frame"), entry.get("band")
    if not all(isinstance(value, str) and value for value in (role, frame, band)):
        return None
    return role, frame, band


def discover(base_types_dir: Path, *, legal_roles: frozenset[str]) -> list[tuple[str, str, str]]:
    """Return every real partition represented by a valid entry, in stable key order."""
    if not base_types_dir.is_dir():
        return []
    found: set[tuple[str, str, str]] = set()
    for path in sorted(base_types_dir.rglob("*.json")):
        for entry in _entries(path):
            key = _key(entry)
            if key is not None and key[0] in legal_roles:
                found.add(key)
    return sorted(found)


def file_for(role: str, frame: str, band: str, *, base_types_dir: Path) -> Path:
    """Return the one file already owning this partition, or its canonical new-file path.

    Refusing an ambiguous partition is deliberate: choosing a file then appending could hide or
    overwrite another live part of the same logical partition.
    """
    canonical = base_types_dir / f"{frame}-{role}-{band}.json"
    if not base_types_dir.is_dir():
        return canonical

    wanted = (role, frame, band)
    matches: list[Path] = []
    for path in sorted(base_types_dir.rglob("*.json")):
        keys = {_key(entry) for entry in _entries(path)}
        keys.discard(None)
        if wanted not in keys:
            continue
        if keys != {wanted}:
            raise PartitionAmbiguityError(
                f"{path} mixes base-type partitions {sorted(keys)}; refusing to append {wanted}")
        matches.append(path)

    if len(matches) > 1:
        joined = ", ".join(str(path) for path in matches)
        raise PartitionAmbiguityError(
            f"base-type partition {wanted} is claimed by multiple files: {joined}")
    if matches:
        if canonical.exists() and matches[0] != canonical:
            raise PartitionAmbiguityError(
                f"base-type partition {wanted} has canonical file {canonical} and live file "
                f"{matches[0]}; consolidate deliberately before generation")
        return matches[0]
    return canonical
