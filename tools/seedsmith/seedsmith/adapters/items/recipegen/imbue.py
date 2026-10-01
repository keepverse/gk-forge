"""seedsmith.adapters.items.recipegen.imbue — the DETERMINISTIC imbue row emitter (strain-splice-host
SSH8.1, spec-socket-pricing §1).

Why deterministic, not briefed: an imbue row carries no authored choice — frame and element fully
determine it — the same argument `forgegem.py` makes for forge-gem. `opvocab.SUPPORTED_FOR_GENERATION`
is **not** widened: the model is still never offered `imbue`, and this module is the derivation path,
exactly as forge-gem's is.

Deterministic rules, all stated here (a future author changes the RULE, never a row):

- **steps**: one row per `(frame, element)`. Frames are the BORE rows' own frames; elements are the
  concrete roster `core.v1.json.elements.concrete`, in the registry's own order — `omni` is a separate
  registry key (`elements.omni`) precisely because it is never an affinity (ssot-sockets §4.2).
- **cost lines**: the bore row's substrate + catalyst lines for that frame, verbatim, plus
  `essence.<element>` — the operation's four priced legs (substrate, catalyst, essence, souls).
- **bands**: the bore row's bands, verbatim — imbue prices on bore's curve (D24). A bore row whose lines
  do NOT agree on one band is refused by name rather than having the emitter pick one.
- **name / nameKey**: `"Imbue: <Frame> <Element>"`, derived; the id is minted in the same `recipe.NNN`
  sequence every other row uses.
- **idempotence**: a `(frame, element)` already covered by a shipped imbue row is skipped, so re-running
  converges instead of duplicating.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..materialgen import vocab as material_vocab
from . import emit as emit_mod
from . import opvocab

REPO_ROOT = Path(__file__).resolve().parents[6]

# `REPO_ROOT`-relative joins below ask which repository actually carries the path. A prefix-keyed
# rewrite is wrong: `data`, `data/seed` and `data/seed/creatures` all resolve back to gk-forge,
# because nearest-match-wins and gk-forge owns its own generator inputs. `or REPO_ROOT` is
# load-bearing - `owning_base` returns None for a path no repository carries, where
# `content_root()` would RAISE.

from ....workspace_roots import owning_base  # noqa: E402


def _owned(relative: str) -> "Path":
    """The repository carrying `relative`, joined to it; this one when none carries it."""
    return (owning_base(relative, REPO_ROOT) or REPO_ROOT) / relative

CORE_REGISTRY = _owned("data/seed/items/_registry/core.v1.json")

#: The one essence namespace a row may name. Never `omni` — see `concrete_elements`.
ESSENCE_PREFIX = "essence."

#: `imbue` mutates an owned instance exactly as `bore` does — it declares which element a crafted
#: socket's affinity becomes. Stated HERE, and deliberately NOT added to
#: `opvocab.OPERATION_OUTPUT_KIND`: that map IS the generation gate (`opvocab.is_supported_operation`
#: reads it), so a key there would quietly offer the model a verb this module exists to DERIVE instead.
#: `test_imbue_is_never_offered_to_the_model` pins that refusal.
OUTPUT_KIND = "mutation"


def concrete_elements() -> "tuple[str, ...]":
    """The concrete element roster, in `core.v1.json`'s own ordinal order. ⛔ `omni` lives under a
    separate key and is NOT in it: omni is the absence of an affinity, so an `essence.omni` line would
    name a material no rule mints (ssot-sockets §4.2)."""
    document = json.loads(CORE_REGISTRY.read_text(encoding="utf-8"))
    rows = document["elements"]["concrete"]
    return tuple(str(row["id"]) for row in sorted(rows, key=lambda r: r["ordinal"]))


def bore_rows(existing: "dict[str, dict]") -> "list[dict[str, Any]]":
    """The shipped bore rows, in id order — the templates every imbue row is derived from."""
    return [entry for _, entry in sorted(existing.items())
            if entry.get("operation") == "bore"]


def imbued_element(entry: "dict[str, Any]") -> "str | None":
    """The element an existing imbue row declares, read off its own `essence.<element>` line — the
    idempotence key. A row carrying no essence line returns `None` (it covers no step)."""
    for line in entry.get("costLines") or []:
        material = str(line.get("material", ""))
        if material.startswith(ESSENCE_PREFIX):
            return material[len(ESSENCE_PREFIX):]
    return None


def _bore_band(bore: "dict[str, Any]") -> str:
    """The bore row's band, verbatim, refused by name when its lines disagree."""
    bands = {str(line.get("costBand", "")) for line in bore.get("costLines") or []}
    build = str(bore.get("soulsCostBand", ""))
    if build:
        bands.add(build)
    bands.discard("")
    if len(bands) != 1:
        raise ValueError(
            f"bore row '{bore.get('id')}' authors {sorted(bands)} bands; the imbue rule is 'the bore "
            "row's bands, verbatim', which needs one band per template row")
    return bands.pop()


def build_entry(frame: str, element: str, bore: "dict[str, Any]", *, seq: int) -> "dict[str, Any]":
    """One imbue recipe entry, shaped exactly like a real `recipes.json` entry."""
    if element not in concrete_elements():
        raise ValueError(
            f"'{element}' is not a concrete element of {CORE_REGISTRY.name} "
            f"({', '.join(concrete_elements())}) — omni is never an affinity")
    band = _bore_band(bore)
    cost_lines = [dict(line) for line in bore.get("costLines") or []]
    cost_lines.append({"material": f"{ESSENCE_PREFIX}{element}", "costBand": band})
    for line in cost_lines:
        material = material_vocab.require_issuable(line["material"])
        opvocab.check_cost_class("imbue", material.material_class, line["material"])

    minted_id = emit_mod.recipe_id(seq)
    return {
        "id": minted_id,
        "nameKey": emit_mod.name_key_for(minted_id),
        "name": f"Imbue: {frame.title()} {element.title()}",
        "operation": "imbue",
        "outputKind": OUTPUT_KIND,
        "outputQty": 1,
        "frame": frame,
        "costLines": cost_lines,
        "soulsCostBand": band,
        "tags": emit_mod.tags_for("imbue"),
    }


def plan_rows(*, existing: "dict[str, dict]", start_seq: int) -> "list[dict[str, Any]]":
    """One row per `(bore frame, concrete element)` not already covered by a shipped imbue row —
    idempotent: re-running after a write plans nothing."""
    covered = {(str(entry.get("frame") or "any"), imbued_element(entry))
               for entry in existing.values() if entry.get("operation") == "imbue"}
    rows: "list[dict[str, Any]]" = []
    seq = start_seq
    for bore in bore_rows(existing):
        frame = str(bore.get("frame") or "any")
        for element in concrete_elements():
            if (frame, element) in covered:
                continue
            rows.append(build_entry(frame, element, bore, seq=seq))
            seq += 1
    return rows
