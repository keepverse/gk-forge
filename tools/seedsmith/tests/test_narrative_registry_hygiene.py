"""Checkpoint 1's registry hygiene (map §11 checkpoint 1, first line) — no OWNED narrative registry
carries a weight, a probability or a price.

    python -m pytest gk-forge/tools/seedsmith/tests/test_narrative_registry_hygiene.py -q -s

The rule is that a narrative registry is a VOCABULARY: it declares members and their clauses, and every
magnitude lives in tuning or in a table the runtime owns. A number smuggled into a registry is the defect
this scan exists for — a model-facing file that quietly carries a balance knob.

**One file in `_registry/` is not this program's, and it is excluded BY NAME, never by a hole in a glob.**
`doctrines.v1.json` carries `speciesElementBiasMilli` / `orderWeightMilli` by design and its `_meta.owner`
is `docs/architecture/npc-story-events/spec-counter-doctrine.md#3` — `npc-story-events`' counter-doctrine
module, which places its registry here. `test_the_foreign_registry_is_named_and_owned_elsewhere` pins that,
so a new magnitude in a NEW file cannot hide behind the same exclusion.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from seedsmith.workspace_roots import content_root  # noqa: E402

REGISTRY_DIR_REL = "data/seed/narrative/_registry"

#: The one registry under `_registry/` this program does NOT own. Named on purpose: an exclusion by
#: pattern would let a new file inherit it silently.
FOREIGN_REGISTRY = "doctrines.v1.json"
#: A key that would make a vocabulary file a balance surface. Counts, orders and indices are NOT listed:
#: `outcomes`, `position`, `beats`, `teachingOrder` and `chunkSize` are structural, bounded by the player's
#: own cap or by a registry rule, and each has a negative clause saying so.
FORBIDDEN_KEY = re.compile(r"weight|probab|price|chance|share|ratio|multipl", re.IGNORECASE)


def _registry_dir() -> Path:
    return content_root() / REGISTRY_DIR_REL


def _owned_registries() -> "list[Path]":
    return sorted(path for path in _registry_dir().glob("*.json")
                  if path.name != FOREIGN_REGISTRY)


def _walk_keys(node, where: str = "") -> "list[tuple[str, str]]":
    """Every `(path, key)` in a JSON document, so a finding names where the number sits."""
    found: "list[tuple[str, str]]" = []
    if isinstance(node, dict):
        for key, value in node.items():
            found.append((where or ".", str(key)))
            found.extend(_walk_keys(value, f"{where}.{key}"))
    elif isinstance(node, list):
        for index, value in enumerate(node):
            found.extend(_walk_keys(value, f"{where}[{index}]"))
    return found


def test_no_owned_narrative_registry_carries_a_weight_probability_or_price(capsys) -> None:
    files = _owned_registries()
    assert files, f"{REGISTRY_DIR_REL}: no registry to inspect — the scan would prove nothing"
    hits: "list[str]" = []
    key_count = 0
    for path in files:
        document = json.loads(path.read_text(encoding="utf-8"))
        keys = _walk_keys(document)
        assert keys, f"{path.name}: carries no key at all"
        key_count += len(keys)
        hits.extend(f"{path.name}: {where}.{key}" for where, key in keys
                    if FORBIDDEN_KEY.search(key))
    print(f"reading: owned registries scanned={len(files)} keys={key_count} "
          f"forbidden-key hits={len(hits)}")
    assert hits == [], f"a vocabulary file carries a magnitude: {hits}"


def test_the_foreign_registry_is_named_and_owned_elsewhere(capsys) -> None:
    foreign = _registry_dir() / FOREIGN_REGISTRY
    assert foreign.exists(), f"{FOREIGN_REGISTRY} is gone — remove it from this exclusion"
    document = json.loads(foreign.read_text(encoding="utf-8"))
    owner = str((document.get("_meta") or {}).get("owner") or "")
    assert owner.startswith("docs/architecture/npc-story-events/"), owner
    assert FORBIDDEN_KEY.search("orderWeightMilli"), "the exclusion exists for a magnitude key"
    # Every OTHER registry under this directory is this program's, which is what makes the scan's scope
    # the same thing as its ownership: a foreign file must declare its owner.
    for path in _owned_registries():
        other = json.loads(path.read_text(encoding="utf-8"))
        declared = str((other.get("_meta") or {}).get("owner") or "")
        assert not declared, f"{path.name} declares owner {declared!r}; the exclusion list needs it"
    print(f"reading: foreign registry = {FOREIGN_REGISTRY} owner = {owner}")
