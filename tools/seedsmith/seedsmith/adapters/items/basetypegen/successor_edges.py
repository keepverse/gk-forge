"""seedsmith.adapters.items.basetypegen.successor_edges — the upgrade tree's authored edges.

The owner ruled 2026-09-21 (species-gear-chain T37/T38, `d12dcb90`): a successor is an **explicit
per-base-type edge**, never a derivation from a class ladder. The class ladders are style / weight /
commitment axes, so `blade → blunt → launcher` (melee → ranged) or "whatever the next armour rung
wears" would silently turn an upgrade into a different *kind* of item.

**This table is the single authoring surface for those edges** — a `_registry` file, hand-authored
per the repo's own rule that registries (unlike generated corpora) are authored. The field is
**additive**: an entry with no authored edge carries no `successorOf` key at all, so introducing this
mechanism changes nothing in the corpus until an edge is authored.

**Authoring and regeneration (T37, 2026-09-21).** The armour ladders' values were authored in
`gk-data/packs/fusion/data/seed/items/_registry/successor-edges.v1.json` (see its own `note` for the pairing rule and the
one named gap), and the EMITTED corpus is brought onto them by this module's mechanical re-stamp —
`python -m seedsmith.adapters.items.basetypegen.successor_edges --dry-run` → `--write` — the same
shape `resocket.py` uses for `socketMax`: no model call, no formula, one `_meta.amendments` record
per touched partition. The re-stamp reads ONLY the registry; nothing recomputes a successor from a
class ladder, so a hand correction in the registry is the authority the corpus follows.

⛔ The edge is never model-authored. `basetypegen`'s brief asks a model for identity (name, flavour,
implicit family, tags) and for nothing structural; which chassis upgrades into which is content, read
here from the registry, exactly like `socketMax`/`powerBand`/`enhanceTrack`.
"""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path

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

SUCCESSOR_EDGES_REGISTRY = _owned("data/seed/items/_registry/successor-edges.v1.json")

#: The shipped emitted corpus the authored edges are ABOUT. Deliberately its own path rather than
#: `tuning.BASE_TYPES_DIR`: that attribute is monkeypatched by callers that redirect a generator run's
#: output (and by the generator's own tests), while the table's references are to the shipped tree — a
#: run into a private directory must not be refused because the table names ids it cannot see. The two
#: are the same directory in production.
SHIPPED_BASE_TYPES_DIR = _owned("data/seed/items/base-types")

#: The `_meta.amendments` batch id and the cite a reviewer reads for WHY the key moved.
AMENDMENT_BATCH = "successor-edges"
SOURCE_REF = "docs/architecture/species-gear-chain/spec-item-upgrade-tree.md#1-one-successor-source--the-authored-per-base-type-edge-owner-ruling-2026-09-21"


class SuccessorEdgeError(ValueError):
    """The edges table is structurally unusable — raised at load, before any entry is emitted, the
    same discipline `tuning.TuningError` uses so a defect lands before the first model call."""


def load(path: "Path | None" = None) -> "dict[str, str]":
    """The authored edges, source base-type id → successor base-type id. An empty table is legal and
    is the shipped state; a malformed one is a load rejection, never a silently ignored row."""
    resolved = Path(path) if path is not None else SUCCESSOR_EDGES_REGISTRY
    try:
        doc = json.loads(resolved.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:  # an absent authoring surface is a rejection, not "no edges"
        raise SuccessorEdgeError(f"{resolved} is missing — the upgrade tree's edge table must exist") from exc
    except json.JSONDecodeError as exc:
        raise SuccessorEdgeError(f"{resolved.name} is not valid JSON: {exc}") from exc

    if not isinstance(doc, dict):
        raise SuccessorEdgeError(f"{resolved.name}: the document must be an object")
    edges = doc.get("edges")
    if not isinstance(edges, dict):
        raise SuccessorEdgeError(
            f"{resolved.name}: 'edges' must be an object (an empty one is the shipped state), "
            f"got {type(edges).__name__}")

    out: "dict[str, str]" = {}
    for source, target in edges.items():
        if not isinstance(source, str) or not source:
            raise SuccessorEdgeError(f"{resolved.name}: an edge key must be a base-type id, got {source!r}")
        if not isinstance(target, str) or not target:
            raise SuccessorEdgeError(
                f"{resolved.name}: edge '{source}' must name a base-type id, got {target!r}")
        if target == source:
            raise SuccessorEdgeError(
                f"{resolved.name}: edge '{source}' points at itself — a successor is a different chassis")
        out[source] = target
    return out


def apply(entry: "dict", edges: "dict[str, str]") -> "dict":
    """Adds the authored edge for `entry`, or nothing at all.

    The key is absent rather than null when unauthored: the executor's refusal path
    (`upgrade.no-successor`) reads the absence, and an explicit `null` would make "nobody authored
    this yet" indistinguishable from "authored as nothing"."""
    target = edges.get(entry.get("id", ""))
    if target:
        entry["successorOf"] = target
    return entry


def closure_violations(edges: "dict[str, str]", base_types: "list[dict]") -> "list[str]":
    """Corpus-wide closure of the authored edges: every edge must join two real base types in the
    SAME frame. Returns one human-readable line per violation, empty when clean.

    Shape validation lives in :func:`load` (a malformed table is a load rejection); this is the
    *relational* check that needs the corpus, and it is the gate that has to exist **before the first
    edge is authored** — a dangling target would otherwise surface as a runtime refusal on a player's
    item rather than as a corpus failure. Zero edges authored ⇒ zero violations, by construction."""
    by_id = {row["id"]: row for row in base_types if isinstance(row, dict) and row.get("id")}
    out: "list[str]" = []
    for source, target in edges.items():
        origin = by_id.get(source)
        if origin is None:
            out.append(f"{source}: the edge's own source is not a base type in the corpus")
            continue
        successor = by_id.get(target)
        if successor is None:
            out.append(f"{source}: successor {target!r} does not resolve to a base type in the corpus")
            continue
        if successor.get("frame") != origin.get("frame"):
            out.append(
                f"{source}: successor {target!r} is frame {successor.get('frame')!r} against "
                f"{origin.get('frame')!r} — an edge never changes frame")
    return out

def base_type_rows(base_types_dir: "Path | str") -> "list[dict]":
    """Every emitted base type as `{id, frame}` — the corpus side of the closure check. Reads the
    shipped tree the same way the C# readers do (each file's `entries` array, id + frame), and skips a
    malformed file rather than throwing: this is the gate a generator RUN uses, and a corpus it cannot
    read is a different failure from an edge it cannot resolve."""
    resolved = Path(base_types_dir)
    rows: "list[dict]" = []
    if not resolved.exists():
        return rows
    for path in sorted(resolved.rglob("*.json")):
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(doc, dict):
            continue
        entries = doc.get("entries")
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            base_id, frame = entry.get("id"), entry.get("frame")
            if isinstance(base_id, str) and base_id and isinstance(frame, str) and frame:
                rows.append({"id": base_id, "frame": frame})
    return rows


def violations_in_corpus(base_types_dir: "Path | str", edges: "dict[str, str]") -> "list[str]":
    """The closure check against the REAL corpus: `closure_violations` over every emitted base type.

    ⛔ This is the gate a generator run must pass before it emits anything, which is why it lives here
    and not behind `seedsmith check`: the items adapter has no structural-check seam (only `kinds()` and
    `dimensions()`; `basetypegen/run.py` has no `--check`), so a callable nothing invokes would be the
    honest state only until edges are authored — and by then it is too late for a dangling one."""
    return closure_violations(edges, base_type_rows(base_types_dir))


# ── the mechanical re-stamp: the authored registry → the emitted corpus (T37, 2026-09-21) ──────────


@dataclass(frozen=True)
class EdgeRestampChange:
    """One emitted row whose `successorOf` moves (or is removed, when the registry no longer has it)."""

    entry_id: str
    previous: "str | None"
    successor: "str | None"

    def to_dict(self) -> dict:
        return {"id": self.entry_id, "from": self.previous, "to": self.successor}


@dataclass(frozen=True)
class EdgeRestampReport:
    changed: "tuple[EdgeRestampChange, ...]"
    unchanged: int
    total: int

    def summary(self) -> dict:
        return {"total": self.total, "unchanged": self.unchanged,
                "restamped": len(self.changed), "rows": [c.to_dict() for c in self.changed]}


def _partition_files(base_types_dir: "Path | str"):
    """Every emitable partition document, in a stable order — `_`-prefixed trees are authoring
    surfaces (`_registry`, `_exemplars`, `_runs`), never emitted corpus."""
    directory = Path(base_types_dir)
    if not directory.exists():
        return
    for path in sorted(directory.glob("**/*.json")):
        if path.name.startswith("_") or path.parent.name.startswith("_"):
            continue
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(doc, dict) and doc.get("kind") == "base-type":
            yield path, doc


def plan_restamp(*, base_types_dir: "Path | str | None" = None,
                 edges: "dict[str, str] | None" = None) -> EdgeRestampReport:
    """The plan, without writing. Refuses (a `SuccessorEdgeError` naming every violation) when the
    authored table does not close against the corpus it is about to be written into — the same gate
    `run.py` uses, applied to the re-stamp, so this verb can never be the way a dangling edge lands.

    Idempotent by construction: a second call after a `--write` plans nothing, because every row then
    equals its own authored edge (or has no key, for the rows nobody authored)."""
    directory = Path(base_types_dir) if base_types_dir is not None else SHIPPED_BASE_TYPES_DIR
    authored = load() if edges is None else dict(edges)
    violations = violations_in_corpus(directory, authored)
    if violations:
        raise SuccessorEdgeError(
            f"{SUCCESSOR_EDGES_REGISTRY.name} does not close against {directory}: "
            + "; ".join(violations))

    changed: "list[EdgeRestampChange]" = []
    unchanged = 0
    total = 0
    for _path, doc in _partition_files(directory):
        for entry in doc.get("entries") or []:
            if not isinstance(entry, dict) or not entry.get("id"):
                continue
            total += 1
            current = entry.get("successorOf")
            wanted = authored.get(entry["id"])
            if current == wanted:
                unchanged += 1
                continue
            changed.append(EdgeRestampChange(entry["id"], current, wanted))
    return EdgeRestampReport(tuple(changed), unchanged, total)


def apply_restamp(report: EdgeRestampReport, *, base_types_dir: "Path | str | None" = None,
                  dry_run: bool = False, authored_utc: str = "") -> int:
    """Write the planned edges (and the `_meta.amendments` record naming them). Returns the number of
    rows changed. Only `successorOf` moves: id, nameKey, name, class, band, implicit, socketMax,
    enhanceTrack, tags and flavor are preserved, so a re-stamp cannot launder identity."""
    if dry_run:
        return len(report.changed)

    directory = Path(base_types_dir) if base_types_dir is not None else SHIPPED_BASE_TYPES_DIR
    by_id = {c.entry_id: c for c in report.changed}
    written = 0
    for path, doc in _partition_files(directory):
        touched = [entry["id"] for entry in doc.get("entries") or []
                   if isinstance(entry, dict) and entry.get("id") in by_id]
        if not touched:
            continue

        for entry in doc["entries"]:
            change = by_id.get(entry.get("id"))
            if change is None:
                continue
            if change.successor is None:
                entry.pop("successorOf", None)
            else:
                entry["successorOf"] = change.successor
            written += 1

        meta = doc.get("_meta") or {}
        amendment = {
            "batch": AMENDMENT_BATCH,
            "note": (
                "successorOf re-stamped from the authored per-base-type edge table "
                "(_registry/successor-edges.v1.json, owner ruling 2026-09-21): the upgrade tree's "
                "successor is AUTHORED, never derived from a class ladder. Only successorOf moved; id, "
                "nameKey, name, class, band, implicit, socketMax, enhanceTrack, tags and flavor are "
                "preserved. No live model call — a mechanical re-stamp, no prompt."
            ),
            "promptVersion": "n/a-mechanical-successor-edges",
            "model": AMENDMENT_BATCH,
            "authoredUtc": authored_utc,
            "sourceRef": SOURCE_REF,
            "entries": sorted(touched),
        }
        doc["_meta"] = {**meta, "amendments": [*meta.get("amendments", []), amendment]}
        path.write_text(json.dumps(doc, ensure_ascii=False, sort_keys=False, indent=2) + "\n",
                        encoding="utf-8", newline="\n")

    return written


def main(argv=None) -> int:
    import argparse

    ap = argparse.ArgumentParser(
        description="Re-stamp base-type successorOf from the authored edge registry "
                    "(data/seed/items/_registry/successor-edges.v1.json). Generator operation; never "
                    "hand-edit the corpus.")
    ap.add_argument("--dry-run", action="store_true", help="print the diff, write nothing")
    ap.add_argument("--write", action="store_true",
                    help="persist the re-stamp and its _meta.amendments record")
    ap.add_argument("--json", default="", help="write the full plan to this path")
    ap.add_argument("--authored-utc", dest="authored_utc", default="1970-01-01T00:00:00Z",
                    help="the _meta timestamp; injected, never read from the clock")
    args = ap.parse_args(argv)

    try:
        report = plan_restamp()
    except SuccessorEdgeError as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2
    payload = report.summary()
    if args.json:
        Path(args.json).write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                                   encoding="utf-8", newline="\n")
    print(json.dumps(payload, ensure_ascii=False, indent=2))

    if args.write:
        written = apply_restamp(report, authored_utc=args.authored_utc)
        print(json.dumps({"written": written}, ensure_ascii=False))
    elif not args.dry_run:
        raise SystemExit("seedsmith: pass --dry-run to inspect or --write to re-stamp")
    return 0


if __name__ == "__main__":  # pragma: no cover - module entrypoint
    raise SystemExit(main())
