"""seedsmith.adapters.trees.nodegen.emit — node id minting + grammar; `IdRefused`-shaped, never
sanitised (task H1, spec-tree-language.md §6.4, §2 table's `nameKey` row).

⛔ **This stage does not mint a node id — the plan already did (§2's own row: "Minted by the plan
... before the call. An id the stage picks is an id that collides and an id that churns between
runs").** What THIS module mints and refuses is the one identifier the language stage itself
produces: `nameKey`. Same discipline as `items/setgen/emit.py`'s `IdRefused` — a bad answer is
refused, never quietly repaired, because "silently repairing it teaches the next call nothing"
(`setgen/distribute.py:143-144`, cited by this program's own Boundaries section).

Owns writing `gk-data/packs/fusion/data/seed/passive-tree/nodes/<treeId>.json` (§6.4's middle arrow) — reusing
`tree-plan`'s own canonical-bytes writer (`plan.emit.canonical_json_bytes`) rather than a second
serializer, so the byte-identical-rerun property (§7 gate 24 / H2's own acceptance bullet) holds
for this file the same way it already holds for the plan.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from ..plan.emit import canonical_json_bytes, content_sha256, tree_content_hash
from .exclusion import compose_printed_text
from .schema import NAME_KEY_PATTERN

REPO_ROOT = Path(__file__).resolve().parents[6]

_NAME_KEY_RE = re.compile(NAME_KEY_PATTERN)


class NodeKeyRefused(ValueError):
    """A `nameKey` (or a within-tree collision of one) this module refuses to persist, with the
    rule it would have broken in the message — never sanitised into something that passes."""


def assert_name_key_grammar(name_key: str) -> None:
    """§6.3's own pattern, checked again on the write side rather than trusted from the model's
    structured-output mode alone (guardrail 1, `pipeline/model.py`'s own docstring: "a model's
    structured-output mode is an upgrade, never the only check")."""
    if not _NAME_KEY_RE.match(name_key):
        raise NodeKeyRefused(
            f"{name_key!r} fails the nameKey grammar {NAME_KEY_PATTERN!r} — refused, not "
            f"lower-cased or slugified into something that would pass")


def assert_no_duplicate_name_keys(name_keys: "Sequence[str]") -> None:
    """Within-tree collision only. Corpus-wide name collision is `NameCollision`'s job (H4's metric,
    §7 gate 21) — this is the narrower, cheaper check: two nodes of the SAME tree must never share a
    `nameKey`, which would make `tree-surface` unable to address one of them at all."""
    seen: "dict[str, int]" = {}
    for i, key in enumerate(name_keys):
        if key in seen:
            raise NodeKeyRefused(
                f"nameKey {key!r} is used by both node index {seen[key]} and node index {i} in "
                f"the same tree — refused, never renamed out from under the model's answer")
        seen[key] = i


#: The six axes `quota.QuotaCell` / `PassiveTree/QuotaDrift` read. Persisted under `quotaCell` as a
#: camelCase map so a later `check --family` can fill `quota_cells_by_tree` from the committed
#: corpus rather than a generation-time snapshot (metrics/passive_tree.py module docstring).
QUOTA_CELL_KEYS: "tuple[str, ...]" = (
    "nodeClass", "trigger", "element", "status", "channelFamily", "exclusionForm",
)


def quota_cell_to_dict(cell: "Mapping[str, str] | object") -> "dict[str, str]":
    """Normalise a `QuotaCell` (or an already-camelCase map) into the seed-file shape. Accepts
    either: a mapping already keyed by `QUOTA_CELL_KEYS`, or an object with `value_for(axis)` /
    the six `QuotaCell` attribute names — never invents a missing axis."""
    if hasattr(cell, "value_for"):
        return {axis: str(cell.value_for(axis)) for axis in QUOTA_CELL_KEYS}  # type: ignore[attr-defined]
    if isinstance(cell, Mapping):
        # Attribute-style QuotaCell spilled via dataclasses.asdict uses snake_case; the seed file
        # and QUOTA_CELL_KEYS are camelCase. Accept both so a caller never has to remember which.
        snake = {
            "nodeClass": "node_class", "trigger": "trigger", "element": "element",
            "status": "status", "channelFamily": "channel_family",
            "exclusionForm": "exclusion_form",
        }
        out: "dict[str, str]" = {}
        for key in QUOTA_CELL_KEYS:
            if key in cell:
                out[key] = str(cell[key])
            elif snake[key] in cell:
                out[key] = str(cell[snake[key]])
            else:
                raise KeyError(f"quota_cell_to_dict: missing axis {key!r} in {sorted(cell)}")
        return out
    raise TypeError(f"quota_cell_to_dict: unsupported cell type {type(cell)!r}")


def quota_cell_from_dict(raw: "Mapping[str, Any] | None") -> "dict[str, str] | None":
    """Load path for a persisted `quotaCell` — returns None when absent (every pre-persistence
    committed record), never invents defaults. Refuses a partial map rather than silently filling
    missing axes, so a truncated write is a loud load error instead of a silent wrong cell."""
    if raw is None:
        return None
    if not isinstance(raw, Mapping):
        raise TypeError(f"quotaCell must be a mapping, got {type(raw)!r}")
    missing = [k for k in QUOTA_CELL_KEYS if k not in raw]
    if missing:
        raise KeyError(f"quotaCell is missing axis/axes {missing!r}")
    return {k: str(raw[k]) for k in QUOTA_CELL_KEYS}


@dataclass(frozen=True)
class NodeSeedRecord:
    """One accepted node, in the shape §6.4's seed file persists. Mirrors §6.3's response fields
    plus the plan-side identity fields this stage never chooses (`nodeId`, `nodeKey`, `branch`,
    `tier`, `nodeClass` — all read from the plan via `plan_read`, never re-derived here).

    `printed_text` is H3's own addition (§2's `printedText` row): template-composed from
    `exclusion.compose_printed_text`, never asked of the model (it is not a §6.3 schema field) and
    never re-derivable from anything BUT the node's own `exclusion_form`/`exclusion_property_keys`
    — so a rerun over the same accepted response always recomputes the identical string.

    `quota_cell` is additive (2026-09-10 distribution-audit wiring): the six-axis cell H3 assigned
    at generation time. Absent (`None`) on every record committed before this field landed — the
    load path keeps those records legal; a new generation writes it so `PassiveTree/QuotaDrift`
    and `PassiveTree/CellOccupancy` can measure the committed corpus without a generation-time
    snapshot."""

    node_id: str
    node_key: str
    branch: str
    tier: int
    node_class: str
    affix_ids: "tuple[str, ...]"
    affinity: "tuple[str, ...]"
    exclusion_form: str
    exclusion_property_keys: "tuple[str, ...]"
    name: str
    name_key: str
    flavor: str
    rationale: str = ""
    printed_text: str = ""
    quota_cell: "Mapping[str, str] | None" = None
    #: Per-record generation provenance (2026-09-11): the prompt vintage this node's CONTENT was
    #: produced under. Additive, like `quota_cell`: empty on every pre-provenance record, which the
    #: document-stamp logic in `build_seed_document` reads as "one vintage, the current one".
    prompt_version: str = ""

    def to_dict(self) -> dict:
        out = {
            "id": self.node_id, "nodeKey": self.node_key, "branch": self.branch,
            "tier": self.tier, "nodeClass": self.node_class,
            "affixIds": list(self.affix_ids), "affinity": list(self.affinity),
            "exclusion": {"form": self.exclusion_form,
                          "propertyKeys": list(self.exclusion_property_keys),
                          "printedText": self.printed_text},
            "name": self.name, "nameKey": self.name_key, "flavor": self.flavor,
            "rationale": self.rationale,
        }
        if self.quota_cell is not None:
            out["quotaCell"] = quota_cell_to_dict(self.quota_cell)
        if self.prompt_version:
            out["promptVersion"] = self.prompt_version
        return out


def build_node_record(node_id: str, node_key: str, branch: str, tier: int, node_class: str,
                      response: "Mapping[str, Any]", *,
                      quota_cell: "Mapping[str, str] | object | None" = None,
                      prompt_version: str = "") -> NodeSeedRecord:
    """One accepted §6.3 response, turned into a `NodeSeedRecord` — refuses (via
    `assert_name_key_grammar`) rather than accepting a malformed `nameKey` the schema's own
    `pattern` should already have blocked; belt and braces, per guardrail 1.

    `printedText` is composed here (`role="loser"` — the only side this stage ever persists on a
    node, per `compose_printed_text`'s own docstring), from the response's OWN `exclusion` object
    alone — never from a value the response itself might supply for it, since `printedText` is not
    part of the §6.3 schema at all (§2's table: AUTHORED/FREE, "template-composed").

    `quota_cell` is optional and keyword-only: every pre-persistence call site (and every ledger
    replay of a record that never carried one) keeps working unmodified. When supplied — a real
    `QuotaCell` or an already-camelCase map — it is normalised and stored; when the response itself
    carries a persisted `quotaCell` (ledger replay) and the caller passed none, that stored value
    is preferred over inventing nothing.

    `prompt_version` (2026-09-11) rides the same additive contract: the caller's value is what a
    FRESH generation stamps; a persisted `promptVersion` in the response itself (ledger replay of
    a record accepted after this field landed) wins, so a replayed record keeps its own vintage —
    the exact per-record provenance the document-stamp logic in `build_seed_document` needs.
    """
    name_key = str(response["nameKey"])
    assert_name_key_grammar(name_key)
    exclusion = response.get("exclusion") or {"form": "none", "propertyKeys": []}
    form = str(exclusion.get("form", "none"))
    property_keys = tuple(exclusion.get("propertyKeys") or ())
    cell: "dict[str, str] | None"
    if quota_cell is not None:
        cell = quota_cell_to_dict(quota_cell)
    else:
        cell = quota_cell_from_dict(response.get("quotaCell"))
    #: Per-record provenance (2026-09-11): a FRESH generation stamps the caller's vintage; a
    #: ledger-replayed record that already carries its own `promptVersion` keeps it (the stored
    #: value wins), so re-reading a record never re-vintages its content.
    record_vintage = str(response.get("promptVersion") or prompt_version)
    return NodeSeedRecord(
        node_id=node_id, node_key=node_key, branch=branch, tier=tier, node_class=node_class,
        affix_ids=tuple(response["affixIds"]), affinity=tuple(response["affinity"]),
        exclusion_form=form, exclusion_property_keys=property_keys,
        name=str(response["name"]), name_key=name_key, flavor=str(response["flavor"]),
        rationale=str(response.get("rationale") or ""),
        printed_text=compose_printed_text(form, property_keys, role="loser"),
        quota_cell=cell,
        prompt_version=record_vintage,
    )


def nodes_path(tree_id: str, seed_root: "Path | None" = None) -> Path:
    root = seed_root or (REPO_ROOT / "data" / "seed")
    return root / "passive-tree" / "nodes" / f"{tree_id}.json"


def build_seed_document(tree_id: str, records: "Sequence[NodeSeedRecord]", *,
                        plan_hash: str, prompt_version: str, model: str,
                        confidence: "Mapping[str, float]" = (),
                        minority_values: "Mapping[str, Any]" = ()) -> dict:
    """§6.4's `gk-data/packs/fusion/data/seed/passive-tree/nodes/<treeId>.json` shape: the seed's nodes plus its
    `_provenance` block (`planHash, promptVersion, model, confidence, minorityValues` — named
    verbatim in the spec's own §6.4 diagram). Refuses a duplicate `nameKey` within this tree
    BEFORE writing, per `assert_no_duplicate_name_keys`.

    **The stamp is derived from the records, not blindly the current brief (2026-09-11).** A tree
    that mixed vintages (e.g. a resumed run replaying pre-provenance v1 records alongside newly
    generated v2 records) used to be stamped with the CURRENT `prompt_version` alone — a lie in
    the document that hid exactly which nodes were stale. With per-record vintages persisted, the
    document stamp reports the SINGLE vintage when every record agrees (today's normal case), and
    `mixed` when they do not, with the per-record split carried in `promptVersionByNode`. The
    caller's `prompt_version` argument remains the stamp for a tree whose records predate the
    per-record field entirely (all empty) — exactly the legacy shape.

    **An EMPTY per-record vintage is itself a vintage (2026-09-11, D2).** A failed re-roll under
    `--supersede` keeps its prior, pre-provenance record (so the tree stays complete rather than
    shrinking below its plan), which means a partially-superseded tree holds BOTH current-vintage
    records and empty-vintage ones. Filtering empties out of `vintages` before counting would then
    see a single value and stamp the whole document with the current vintage — the exact lie this
    docstring exists to prevent, now reachable through the real CLI. Empty is therefore kept as its
    own sentinel: `{v3}` stamps `v3`, `{"", v3}` stamps `mixed`, and only an all-empty set falls
    back to the caller's legacy stamp.
    """
    assert_no_duplicate_name_keys([r.name_key for r in records])
    vintages = {r.prompt_version for r in records}
    if any(vintages):
        doc_stamp = next(iter(vintages)) if len(vintages) == 1 else "mixed"
    else:
        doc_stamp = prompt_version
    provenance: "dict[str, Any]" = {
        "planHash": plan_hash,
        "promptVersion": doc_stamp,
        "model": model,
        "confidence": dict(confidence),
        "minorityValues": dict(minority_values),
    }
    if len(vintages) > 1:
        provenance["promptVersionByNode"] = {r.node_id: r.prompt_version for r in records}
    return {
        "schemaVersion": 1,
        "treeId": tree_id,
        "nodes": [r.to_dict() for r in records],
        "_provenance": provenance,
    }


def write_seed_document(doc: "Mapping[str, Any]", seed_root: "Path | None" = None) -> Path:
    """Writes via `plan.emit.canonical_json_bytes` + `Path.write_bytes` — never `write_text`, for
    the exact `\\r\\n`-on-Windows reason `plan.emit.canonical_json_bytes`'s own docstring records."""
    path = nodes_path(str(doc["treeId"]), seed_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_json_bytes(dict(doc)))
    return path


def read_seed_document(tree_id: str, seed_root: "Path | None" = None) -> "dict[str, Any] | None":
    path = nodes_path(tree_id, seed_root)
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


__all__ = [
    "NodeKeyRefused", "assert_name_key_grammar", "assert_no_duplicate_name_keys",
    "QUOTA_CELL_KEYS", "quota_cell_to_dict", "quota_cell_from_dict",
    "NodeSeedRecord", "build_node_record", "nodes_path", "build_seed_document",
    "write_seed_document", "read_seed_document", "content_sha256",
]
