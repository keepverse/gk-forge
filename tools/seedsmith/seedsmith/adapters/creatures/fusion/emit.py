"""`fusion-recipe-generator` §4 canonical serializer + the `--check` staleness discipline
(creature-seed module 17, spec-fusion-recipe-generator.md §4) — mirrors `anchor/emit.py`'s own
`json.dumps(..., indent=2, sort_keys=True, ensure_ascii=False)` convention and `CreatureSpeciesGen
--check`'s own shape (compare freshly-built content against what is on disk, byte-for-byte, write
nothing in check mode).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Mapping

#: `gk-data/packs/fusion/data/generated/creatures/_fusion-recipes.json` — underscore-prefixed, ONE committed file (spec §4:
#: recipes are far smaller than a full species stat block, so `species-generator`'s
#: one-file-per-species shape is the wrong precedent here — `redistribution-plan`'s single-file
#: shape is the right one).
DEFAULT_OUTPUT_RELATIVE = ("data", "generated", "creatures", "_fusion-recipes.json")


def build_seed(recipes: "Mapping[str, dict]") -> "dict[str, dict]":
    """Canonical, sorted by recipe id — the exact committed shape spec §4 shows."""
    return dict(sorted(recipes.items(), key=lambda kv: kv[0]))


def render(recipes: "Mapping[str, dict]") -> str:
    """The exact bytes written to disk. `sort_keys=True` also stabilizes each entry's own key
    order (`crossRungGapFill`/`inputSpeciesIdA`/...), matching `anchor/emit.py`'s convention —
    a trailing newline so the file is diffable the same way every other seed file in this repo is.
    """
    return json.dumps(build_seed(recipes), indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def write(recipes: "Mapping[str, dict]", path: Path) -> bool:
    """Writes only when the content actually changed. Returns True iff the file was (re)written —
    a clean re-run against an unchanged roster writes nothing, matching this module's own
    freeze-on-commit reproducibility claim (spec §3a): the bytes, not just the recipe count, must
    be identical run to run."""
    text = render(recipes)
    if path.exists() and path.read_text(encoding="utf-8") == text:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return True


def check(recipes: "Mapping[str, dict]", path: Path) -> "list[str]":
    """`--check` mode: NEVER writes. Returns the reasons the committed file is stale — empty means
    clean. Mirrors `CreatureSpeciesGen --check`'s own discipline (byte-for-byte comparison, not a
    count or a hash of counts)."""
    text = render(recipes)
    if not path.exists():
        return [f"{path} does not exist — run `reconcile` to generate it"]
    existing = path.read_text(encoding="utf-8")
    if existing != text:
        return [f"{path} is stale — its committed content does not match a fresh reconcile"]
    return []
