"""seedsmith.adapters.items.materialgen.emit — ids, and the entry shape `kinds.py`'s `material`
KindSpec declares.

⛔ **`nameKey`/`iconKey` are derived, never authored.** Every one of the 21 shipped entries in
`gk-data/packs/fusion/data/seed/items/materials/materials.json` follows the exact same mechanical pattern:

    runtimeId "essence.fire"            -> nameKey "material.essence-fire"    -> iconKey "icon.material.essence-fire"
    runtimeId "substrate.humanoid.sound" -> nameKey "material.substrate-humanoid-sound" -> iconKey "icon.material.substrate-humanoid-sound"

(dots in the runtime id become dashes, prefixed with `material.`; the icon key is `icon.` + that).
Zero of the 21 shipped rows deviate. Asking the model to also choose these — as opposed to `name`/
`flavor`, which have no mechanical derivation — is exactly the trap `setgen.schema`'s `apCost`
precedent names: two authors of the same fact eventually disagree with each other. `schema.py`
accordingly never asks for them; this module derives both from the id alone.

The corpus-level `id` (`material.NNN`, sequential across the whole corpus, not per-class) is minted
here too, from the highest existing sequence number — never from a count, which double-books the
moment a hand edit removes a row from the middle of the file.
"""
from __future__ import annotations

import re

from .vocab import MaterialId

_SEQ_RE = re.compile(r"^material\.(\d+)$")


def derive_name_key(runtime_id: str) -> str:
    return "material." + runtime_id.replace(".", "-")


def derive_icon_key(runtime_id: str) -> str:
    return "icon." + derive_name_key(runtime_id)


def next_seq(existing_entries: "list[dict]") -> int:
    """One past the highest `material.NNN` id already in the corpus. `0` (-> seq `1`) if the corpus
    is empty, so a fresh/test corpus does not need a seed row to bootstrap from."""
    highest = 0
    for entry in existing_entries:
        match = _SEQ_RE.match(str(entry.get("id", "")))
        if match:
            highest = max(highest, int(match.group(1)))
    return highest + 1


def build_entry(material: MaterialId, answer: dict, *, seq: int) -> dict:
    """The full corpus row for `material`, in `kinds.py`'s own field order for readability. `answer`
    is a caller-validated draft (schema-checked by the caller, e.g. `run.run_batch`) — this function
    does not re-validate it, the same division of labor `setgen.emit` keeps from its own schema
    layer."""
    entry: "dict" = {
        "id": f"material.{seq:03d}",
        "nameKey": derive_name_key(material.runtime_id),
        "name": answer["name"],
        "runtimeId": material.runtime_id,
        "materialClass": material.material_class,
    }
    if material.element is not None:
        entry["element"] = material.element
    if material.frame is not None:
        entry["frame"] = material.frame
    if material.grade is not None:
        entry["grade"] = material.grade
    if material.scope is not None:
        entry["scope"] = material.scope
    if material.scope_key is not None:
        entry["scopeKey"] = material.scope_key
    if material.slot is not None:
        entry["slot"] = material.slot
    entry["iconKey"] = derive_icon_key(material.runtime_id)
    tags = answer.get("tags")
    if tags:
        entry["tags"] = list(tags)
    flavor = answer.get("flavor")
    if flavor:
        entry["flavor"] = flavor
    return entry
