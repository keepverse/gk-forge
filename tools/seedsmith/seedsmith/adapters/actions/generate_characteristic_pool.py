"""seedsmith.adapters.actions.generate_characteristic_pool — A-S0's entrypoint
(spec-characteristic-pool.md). Reads the committed, offline inputs spec §2 names and writes both
of this module's two outputs through A-C1's envelope:

    gk-data/packs/fusion/data/seed/actions/_generated/role-lean.json          kind: "action-role-lean"
    gk-data/packs/fusion/data/seed/actions/_generated/characteristic-pool.json kind: "action-characteristic-pool"

Lives one level above `characteristic_pool/` (rather than inside it) for the same reason
`generate_motifs.py` sits beside `motifs.py` rather than inside a `motifs/` package: the
sub-package holds pure derivation (no filesystem writes, easy to unit-test in isolation); this
module is the one place that touches disk, mirroring every other `generate_*.py` entrypoint in
this adapter family.

Zero model calls (spec §1, acceptance #8) — every value here is read from a shipped table or
derived from one; the `--dry-run` flag exists only to preview the summary without writing.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from .characteristic_pool.anchors import load_anchor_tree, SPECIES_ROOT
from .characteristic_pool.catalog import (
    CATALOG_PATH, derive_live_family_assignments, load_catalog,
)
from .characteristic_pool.derive import build_species_anchor, derive_all, load_weights, TUNING_PATH
from .characteristic_pool.pool import build_pool_entries

__all__ = ["run", "regenerate", "ACTIONS_ROOT", "CREATURES_ROOT"]

REPO_ROOT = Path(__file__).resolve().parents[5]

# `REPO_ROOT`-relative joins below ask which repository actually carries the path. A prefix-keyed
# rewrite is wrong: `data`, `data/seed` and `data/seed/creatures` all resolve back to gk-forge,
# because nearest-match-wins and gk-forge owns its own generator inputs. `or REPO_ROOT` is
# load-bearing - `owning_base` returns None for a path no repository carries, where
# `content_root()` would RAISE.

from ...workspace_roots import owning_base, seed_root  # noqa: E402


def _owned(relative: str) -> "Path":
    """The repository carrying `relative`, joined to it; this one when none carries it."""
    return (owning_base(relative, REPO_ROOT) or REPO_ROOT) / relative

ACTIONS_ROOT = _owned("data/seed/actions")
CREATURES_ROOT = seed_root() / "creatures"
MOTIF_ASSIGNMENTS_PATH = CREATURES_ROOT / "_generated" / "motif-assignments.json"


def _canonical_dump(doc: dict) -> str:
    """Spec §3 step 6: sorted keys, fixed indent, `\\n` line ending, explicit nulls, CJK
    unescaped — the exact convention every other envelope writer in this program uses."""
    return json.dumps(doc, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def _corpus_hash(catalog, motif_assignments: dict, family_assignments: dict,
                 anchor_by_lower: dict) -> str:
    """A stable digest over every input this module reads, so `_meta.corpusHash` genuinely
    changes iff the derivation's OWN inputs changed — never a wall-clock stamp, and never a
    dependency on dict iteration order (the payload is built with `sort_keys=True`)."""
    payload = {
        "catalog": [
            {"id": s.species_id, "elementPrimary": s.element_primary,
             "elementSecondary": s.element_secondary, "rarity": s.rarity,
             "traits": list(s.traits)}
            for s in catalog
        ],
        "motifAssignments": motif_assignments,
        "familyAssignments": family_assignments,
        "anchors": {
            k: {"posture": v.posture, "reach": v.reach,
               "targetPreference": v.target_preference}
            for k, v in anchor_by_lower.items()
        },
    }
    blob = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def _role_lean_entries(entries, family_assignments: dict, corpus_hash: str,
                       tuning_version: int) -> dict:
    rows = []
    for e in entries:
        sp = e.species_anchor
        rows.append({
            "id": f"lean.{sp.species.species_id}",
            "speciesKey": sp.species.species_id,
            "family": sp.family,
            "families": list(family_assignments.get(sp.species.species_id) or ()),
            "themeKey": sp.theme_key,
            "element": {"primary": sp.species.element_primary,
                       "secondary": sp.species.element_secondary or "none"},
            "rarity": sp.species.rarity,
            "motifs": list(sp.motifs),
            "antiMotifs": list(sp.anti_motifs),
            "leanOrder": list(e.lean_order),
            "leanSource": e.lean_source,
            "separation": e.separation,
            "signals": list(e.signals),
        })
    rows.sort(key=lambda r: r["id"])
    return {
        "schemaVersion": 1,
        "kind": "action-role-lean",
        "_meta": {"partition": "role-lean", "corpusHash": corpus_hash,
                 "tuningVersion": tuning_version},
        "entries": rows,
    }


def _characteristic_pool_entries(corpus_hash: str, tuning_version: int) -> dict:
    rows = build_pool_entries()
    rows.sort(key=lambda r: r["id"])
    return {
        "schemaVersion": 1,
        "kind": "action-characteristic-pool",
        "_meta": {"partition": "characteristic-pool", "corpusHash": corpus_hash,
                 "tuningVersion": tuning_version},
        "entries": rows,
    }


def regenerate(*, actions_root: Path = ACTIONS_ROOT, creatures_root: Path = CREATURES_ROOT,
              catalog_path: Path = CATALOG_PATH, species_root: Path = SPECIES_ROOT,
              family_assignments_path: "Path | None" = None,
              tuning_path: Path = TUNING_PATH, write: bool = True) -> dict:
    """Pure computation + (optionally) two file writes. Returns a summary dict for the caller to
    report — never prints itself, so a test can call this without capturing stdout."""
    catalog = load_catalog(catalog_path)
    anchor_tree = load_anchor_tree(species_root)
    weights = load_weights(tuning_path)

    motif_assignments = json.loads(
        (creatures_root / "_generated" / "motif-assignments.json").read_text(encoding="utf-8"))
    using_live_families = family_assignments_path is None
    if using_live_families:
        family_assignments = derive_live_family_assignments(species_root)
    else:
        family_assignments = json.loads(family_assignments_path.read_text(encoding="utf-8"))

    live_ids = {species.species_id for species in catalog}
    if using_live_families and set(family_assignments) != live_ids:
        raise ValueError("live family assignments do not cover exactly the live species roster")
    motif_ids = {str(species_id).lower() for species_id in motif_assignments}
    if motif_ids != live_ids:
        raise ValueError(
            "motif-assignments.json is stale relative to the live species seed folder: "
            f"missing={sorted(live_ids - motif_ids)[:5]!r}, "
            f"extra={sorted(motif_ids - live_ids)[:5]!r}"
        )

    anchors = [
        build_species_anchor(
            sp, family_assignments=family_assignments, motif_assignments=motif_assignments,
            anchor_by_lower=anchor_tree.by_lower_id,
        )
        for sp in catalog
    ]
    entries, residue = derive_all(anchors, weights)

    corpus_hash = _corpus_hash(catalog, motif_assignments, family_assignments,
                               anchor_tree.by_lower_id)
    role_lean_doc = _role_lean_entries(entries, family_assignments, corpus_hash, weights.version)
    pool_doc = _characteristic_pool_entries(corpus_hash, weights.version)

    if write:
        gen = actions_root / "_generated"
        gen.mkdir(parents=True, exist_ok=True)
        (gen / "role-lean.json").write_text(_canonical_dump(role_lean_doc), encoding="utf-8")
        (gen / "characteristic-pool.json").write_text(_canonical_dump(pool_doc), encoding="utf-8")
        (gen / "family-map.json").write_text(_canonical_dump(family_assignments), encoding="utf-8")

    by_source: "dict[str, int]" = {}
    for e in entries:
        by_source[e.lean_source] = by_source.get(e.lean_source, 0) + 1

    return {
        "species": len(entries),
        "unjoinedAnchors": sorted(
            k for k in anchor_tree.by_lower_id if k not in {c.species_id for c in catalog}),
        "brokenAnchorIndexEntries": list(anchor_tree.broken_index_entries),
        "byLeanSource": by_source,
        "residue": {
            "familyAssigned": residue.family_assigned_count,
            "familyLess": residue.family_less_count,
            "residueCount": residue.residue_count,
            "residueSpecies": list(residue.residue_species),
        },
        "corpusHash": corpus_hash,
        "tuningVersion": weights.version,
        "written": bool(write),
    }


def run(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Derive the closed characteristic pool and species role lean (A-S0).")
    ap.add_argument("--dry-run", action="store_true", help="compute and print, write nothing")
    args = ap.parse_args(argv)

    summary = regenerate(write=not args.dry_run)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


def main(argv=None) -> int:
    return run(argv)


if __name__ == "__main__":  # pragma: no cover - dev entrypoint
    raise SystemExit(main())
