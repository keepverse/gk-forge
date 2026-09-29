"""seedsmith.pipeline.dependency_validator — deterministic cross-corpus reference resolution and
backfill planning (item-seedgen's `generator-harness`, module 1). Full design rationale, the three
reference kinds, and the real evidence behind each:
docs/architecture/item-seedgen/spec-generator-harness.md and docs/architecture/item-seedgen-map.md §1.

**Three reference kinds, found by auditing real content, not assumed:**
- HARD — an entry names an EXACT id in another corpus (a recipe's `outputRef`). Resolution: does the
  id exist verbatim.
- CATEGORICAL — an entry names a SELECTOR another corpus's entries are matched against (a set's
  `members[].role`+`.frame`). Resolution: does at least one entry satisfy the selector — reported as
  a COUNT, not a boolean, so "resolves, but only barely (1 match)" stays visible.
- EXTERNAL — a HARD-shaped reference into a corpus THIS PROGRAM DOES NOT OWN (consumables' `family`
  into effect-atom's `atom-family-library.md`). Validated identically to HARD, but NEVER passed to
  `plan_backfill` — this program has no standing to author another program's content.

**Deterministic by construction.** No function in this module makes a model/LLM call. `validate`'s
report is built by iterating the caller-supplied `entries` dict in insertion order — pass an
already-sorted dict (e.g. built from `sorted(ids)`) for a byte-identical report across runs; this
module does not re-sort for you, so a caller iterating an unsorted dict is a caller bug, not this
module's non-determinism.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Callable, Iterable

HARD = "hard"
CATEGORICAL = "categorical"
EXTERNAL = "external"
_KINDS = (HARD, CATEGORICAL, EXTERNAL)


@dataclass(frozen=True)
class ReferenceManifestEntry:
    """One declared reference a module's own schema carries. `field_path` is a small dotted reader
    (see `_extract` below) — deliberately not a full JSONPath implementation; every real reference
    audited so far (outputRef, members[].role, family, ingredients) is reachable with dotted/bracketed
    segments, and a real need for more should extend `_extract`, not motivate a dependency."""

    field_path: str
    kind: str
    target_module: str

    def __post_init__(self) -> None:
        if self.kind not in _KINDS:
            raise ValueError(f"kind must be one of {_KINDS}, got {self.kind!r}")


@dataclass(frozen=True)
class ResolvedReference:
    entry_id: str
    manifest: ReferenceManifestEntry
    value: object
    resolved: bool
    match_count: int


@dataclass(frozen=True)
class ValidationReport:
    results: "tuple[ResolvedReference, ...]"

    @property
    def unresolved(self) -> "list[ResolvedReference]":
        return [r for r in self.results if not r.resolved]

    def to_dict(self) -> dict:
        """Canonical, sort_keys-serializable shape — the determinism test asserts on THIS, not on
        the dataclass repr, which Python does not guarantee canonical ordering for across versions."""
        return {
            "results": [
                {
                    "entryId": r.entry_id,
                    "fieldPath": r.manifest.field_path,
                    "kind": r.manifest.kind,
                    "targetModule": r.manifest.target_module,
                    "value": r.value,
                    "resolved": r.resolved,
                    "matchCount": r.match_count,
                }
                for r in self.results
            ]
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, ensure_ascii=False, indent=2)


def _extract(entry: dict, field_path: str):
    """`"a.b"` -> `entry["a"]["b"]`. `"a[].b"` -> a list of `x["b"]` for each `x` in `entry["a"]`
    (used for `members[].role`-shaped paths). Missing/wrong-shaped path -> `None`, never a raised
    error — a manifest describing a field an entry happens not to carry is a "no reference here" fact,
    not a validator bug."""
    parts = field_path.split(".")
    node = entry
    for i, part in enumerate(parts):
        if part.endswith("[]"):
            key = part[:-2]
            if not isinstance(node, dict) or key not in node or not isinstance(node[key], list):
                return None
            remainder = ".".join(parts[i + 1 :])
            if not remainder:
                return node[key]
            return [_extract(item, remainder) for item in node[key] if isinstance(item, dict)]
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node


def validate(
    entries: "dict[str, dict]",
    manifest: "list[ReferenceManifestEntry]",
    resolve_hard: Callable[[str, object], bool],
    resolve_categorical: Callable[[str, object], int],
) -> ValidationReport:
    """`resolve_hard(target_module, value) -> bool` and `resolve_categorical(target_module, value) ->
    int` are supplied by the caller — this module never reaches into another corpus itself, so it has
    no I/O of its own and no way to be non-deterministic through a side channel. HARD and EXTERNAL
    both resolve through `resolve_hard`; only `manifest.kind` (recorded on the result) distinguishes
    them for `plan_backfill` below."""
    results: "list[ResolvedReference]" = []
    for entry_id, entry in entries.items():
        for m in manifest:
            value = _extract(entry, m.field_path)
            if value is None:
                continue
            if isinstance(value, list):
                for item in value:
                    if item is None:
                        continue
                    results.append(_resolve_one(entry_id, m, item, resolve_hard, resolve_categorical))
            else:
                results.append(_resolve_one(entry_id, m, value, resolve_hard, resolve_categorical))
    return ValidationReport(tuple(results))


def _resolve_one(entry_id, m: ReferenceManifestEntry, value, resolve_hard, resolve_categorical) -> ResolvedReference:
    if m.kind == CATEGORICAL:
        count = resolve_categorical(m.target_module, value)
        return ResolvedReference(entry_id, m, value, count > 0, count)
    ok = resolve_hard(m.target_module, value)
    return ResolvedReference(entry_id, m, value, ok, 1 if ok else 0)


@dataclass(frozen=True)
class BackfillRequest:
    target_module: str
    kind: str
    id_or_selector: object


def plan_backfill(report: ValidationReport) -> "list[BackfillRequest]":
    """Deterministic: one deduped request per distinct (target_module, id_or_selector) among
    unresolved, non-EXTERNAL references — EXTERNAL is never backfilled (this program has no standing
    to author another program's content). Dedup key uses a canonical JSON dump of the value so two
    entries naming the identical missing id/selector produce exactly one request, not one per
    referencing entry — the "found on adversarial review" gap the first draft of this design had."""
    seen: "set[tuple[str, str]]" = set()
    requests: "list[BackfillRequest]" = []
    for r in report.unresolved:
        if r.manifest.kind == EXTERNAL:
            continue
        dedup_value = json.dumps(r.value, sort_keys=True, ensure_ascii=False)
        key = (r.manifest.target_module, dedup_value)
        if key in seen:
            continue
        seen.add(key)
        requests.append(BackfillRequest(r.manifest.target_module, r.manifest.kind, r.value))
    return requests


def run_backfill_loop(
    entries: "dict[str, dict]",
    manifest: "list[ReferenceManifestEntry]",
    resolve_hard: Callable[[str, object], bool],
    resolve_categorical: Callable[[str, object], int],
    generate: Callable[[BackfillRequest], "dict[str, dict]"],
    *,
    max_depth: int = 3,
) -> "tuple[dict[str, dict], list[BackfillRequest]]":
    """The cascade-guard orchestrator (found missing on adversarial review of the first draft): plans
    backfill, calls the caller-supplied `generate` for each request (which may itself hand generation
    off to a model — the ONE place in this whole flow that is not deterministic), merges the newly
    generated entries in, and RE-VALIDATES before declaring the gap closed — a freshly-backfilled
    entry can itself carry an unresolved reference (a minted base-type also naming an affix family
    that does not exist yet), and only re-validation catches that.

    Returns the (possibly-extended) entries dict and the list of requests still unresolved after
    `max_depth` rounds — the caller decides whether that remainder is `unresolvable: true` or a retry.
    """
    current = dict(entries)
    for _ in range(max_depth):
        report = validate(current, manifest, resolve_hard, resolve_categorical)
        requests = plan_backfill(report)
        if not requests:
            return current, []
        for req in requests:
            current.update(generate(req))
    # One final check so the caller can distinguish "still genuinely missing" from "generate() didn't
    # actually close the gap it was asked to."
    final_report = validate(current, manifest, resolve_hard, resolve_categorical)
    return current, plan_backfill(final_report)
