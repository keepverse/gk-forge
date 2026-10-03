"""seedsmith.adapters.actions.generate_type_weights — A-T1's entrypoint
(spec-type-weights.md). Reads:

    gk-data/packs/fusion/data/seed/actions/_generated/role-lean.json     (A-S0's own output; leanOrder, leanSource,
                                                       separation, family, element, signals)
    gk-core/data/tuning/action-type-weights.v1.json          (every coefficient the algorithm uses)

and writes, through A-C1's envelope:

    gk-data/packs/fusion/data/seed/actions/type-weights.json              kind: "action-type-weights"

Never touches A-S0's own raw inputs (the catalog, the anchor tree, motif/family-assignments) —
spec §2's Reads table lists `role-lean.json` only, and this module holds to that boundary.

**A live citation this module checked against `kinds.py` and did not follow, flagged rather than
silently resolved either way.** `adapters/actions/kinds.py`'s own `KindSpec` for
`"action-type-weights"` declares `directory="_generated"`. Followed literally, that would put this
file at `data/seed/actions/_generated/type-weights.json`. It is **not load-bearing**:
`KindSpec.directory` has zero call sites anywhere in this package (`grep -rn "\\.directory\\b"`
over `gk-forge/tools/seedsmith` returns nothing) — `seedsmith.corpus.model.Corpus.load` walks every
`*.json` under its root via `root.rglob("*.json")` regardless of subdirectory, so nothing downstream
actually depends on this file's location for loading. `spec-type-weights.md` §2's own "Writes" row
and §1's "Real gap" table both independently state the path with no `_generated/` segment
(`gk-data/packs/fusion/data/seed/actions/type-weights.json`), matching `spec-action-seeding.md:173`'s own naming — that
is what this module follows, since two independently-stated, load-bearing spec citations outrank
one unused metadata field on a KindSpec built for a different module (A-C1).
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from .type_weights.derive import RoleLeanRow, derive_all
from .type_weights.tuning import TUNING_PATH, load_type_weights

__all__ = ["run", "regenerate", "ACTIONS_ROOT", "ROLE_LEAN_PATH"]

REPO_ROOT = Path(__file__).resolve().parents[5]

# `REPO_ROOT`-relative joins below ask which repository actually carries the path. A prefix-keyed
# rewrite is wrong: `data`, `data/seed` and `data/seed/creatures` all resolve back to gk-forge,
# because nearest-match-wins and gk-forge owns its own generator inputs. `or REPO_ROOT` is
# load-bearing - `owning_base` returns None for a path no repository carries, where
# `content_root()` would RAISE.

from ...workspace_roots import owning_base  # noqa: E402


def _owned(relative: str) -> "Path":
    """The repository carrying `relative`, joined to it; this one when none carries it."""
    return (owning_base(relative, REPO_ROOT) or REPO_ROOT) / relative

ACTIONS_ROOT = _owned("data/seed/actions")
ROLE_LEAN_PATH = ACTIONS_ROOT / "_generated" / "role-lean.json"


def _canonical_dump(doc: dict) -> str:
    """Spec §3 step 7: sorted keys, fixed indent, `\\n` line ending, explicit nulls — the exact
    convention `generate_characteristic_pool.py`'s own writer already uses."""
    return json.dumps(doc, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def _parse_role_lean_rows(doc: dict) -> "list[RoleLeanRow]":
    """Narrows each `role-lean.json` entry to exactly the fields this module reads (spec §2).
    `reach` has no dedicated field on the entry — it is parsed out of the entry's own `signals`
    list (A-S0's `_signals_for`), the same list `characteristic_pool`'s own residue reporting
    reads, never re-derived from the anchor tree directly."""
    rows: "list[RoleLeanRow]" = []
    for e in doc["entries"]:
        reach: "str | None" = None
        for signal in e.get("signals", []):
            if signal.startswith("reach:"):
                reach = signal.split(":", 1)[1]
                break
        element = e["element"]
        secondary = element.get("secondary")
        rows.append(RoleLeanRow(
            species_key=e["speciesKey"], family=e.get("family"),
            families=tuple(e.get("families") or ((e["family"],) if e.get("family") else ())),
            lean_order=tuple(e["leanOrder"]), lean_source=e["leanSource"],
            separation=e.get("separation"),
            element_primary=element["primary"],
            element_secondary=(None if secondary in (None, "none") else secondary),
            reach=reach,
        ))
    rows.sort(key=lambda r: r.species_key)   # role-lean.json is already id-sorted; re-sorting here
                                              # makes this module's own input order independent of
                                              # the reader's iteration order too (determinism)
    return rows


def _entry_doc(entry) -> dict:
    return {
        "id": entry.id,
        "scope": entry.scope,
        "scopeKey": entry.scope_key,
        "categoryMilli": entry.category_milli,
        "targetModeMilli": entry.target_mode_milli,
        "areaShapeMilli": entry.area_shape_milli,
        "elementBiasMilli": entry.element_bias_milli,
        "basis": entry.basis,
    }


def regenerate(*, actions_root: Path = ACTIONS_ROOT, role_lean_path: Path = ROLE_LEAN_PATH,
              tuning_path: Path = TUNING_PATH, write: bool = True) -> dict:
    """Pure computation + (optionally) one file write. Returns a summary dict for the caller to
    report — never prints itself, so a test can call this without capturing stdout."""
    lean_text = role_lean_path.read_text(encoding="utf-8")
    lean_doc = json.loads(lean_text)
    rows = _parse_role_lean_rows(lean_doc)
    weights = load_type_weights(tuning_path)

    entries = derive_all(rows, weights)
    entries.sort(key=lambda e: e.id)

    # The hash names this file `leanHash` (spec §2's envelope example) rather than `corpusHash` —
    # it is a digest over this module's OWN single input file, not over the wider corpus A-S0's
    # own `corpusHash` covers.
    lean_hash = hashlib.sha256(lean_text.encode("utf-8")).hexdigest()

    out_doc = {
        "schemaVersion": 1,
        "kind": "action-type-weights",
        "_meta": {
            "partition": "type-weights", "tuningVersion": weights.version, "leanHash": lean_hash,
        },
        "entries": [_entry_doc(e) for e in entries],
    }

    if write:
        actions_root.mkdir(parents=True, exist_ok=True)
        # `newline="\n"` is the house convention for a byte-reproducible artifact, and this writer was
        # one of the 65 that never got it. Measured 2026-10-04: regenerating on Windows wrote 889,342
        # bytes with 39,596 CRLFs against a committed blob of 849,746 bytes - the same content, the
        # other line endings - so `test_a_fresh_publish_reproduces_the_committed_registry` compared
        # bytes and failed on a difference that carries no meaning. Matches emit.py and
        # adapters/items/setgen/seedfile.py, which already pass it.
        (actions_root / "type-weights.json").write_text(
            _canonical_dump(out_doc), encoding="utf-8", newline="\n")

    species_count = sum(1 for e in entries if e.scope == "species")
    family_count = sum(1 for e in entries if e.scope == "family")
    return {
        "species": species_count,
        "families": family_count,
        "total": len(entries),
        "leanHash": lean_hash,
        "tuningVersion": weights.version,
        "written": bool(write),
    }


def run(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Derive per-mille action-type weight vectors from A-S0's role lean (A-T1).")
    ap.add_argument("--dry-run", action="store_true", help="compute and print, write nothing")
    args = ap.parse_args(argv)

    summary = regenerate(write=not args.dry_run)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


def main(argv=None) -> int:
    return run(argv)


if __name__ == "__main__":  # pragma: no cover - dev entrypoint
    raise SystemExit(main())
