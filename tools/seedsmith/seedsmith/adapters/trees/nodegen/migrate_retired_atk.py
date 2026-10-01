"""seedsmith.adapters.trees.nodegen.migrate_retired_atk — the fix for the 16 already-accepted
passive-tree nodes that named the now-retired `progression.bonus.atk` channel as their ONLY effect
(solid-enforcement `retire-atk` R5, spec-retire-atk.md, owner ruling 2026-09-18).

Mirrors `recipegen.migrate_legacy_shards`'s own shape exactly (detect / fix / apply-to-real-corpus /
CLI), the established pattern for "a mechanical id rewrite over an already-committed corpus, no
model call, no prompt involved" (that module's own `main()` docstring). The one real difference:
that corpus is ONE file; this one is 16 tree-scoped files under `gk-data/packs/fusion/data/seed/passive-tree/nodes/`, so
`apply_to_real_corpus` walks the whole directory rather than taking one path.

**Never a re-quota.** `quota.quota_for_plan` draws `channelFamily` from a weighted pool sized by
`len(plan.nodes)`; recomputing it after `progression.bonus.atk` left the vocabulary would reshuffle
EVERY tree's free-drawn cells, not just these 16 — the exact "no stage that calls a model is
re-run, and nothing else moves" acceptance line this module exists to satisfy. This module never
calls `quota_for_plan` at all: it walks the ALREADY-PERSISTED `quotaCell` on each accepted node and
resolves only `channelFamily`, through `quota.resolve_retired_quota_cell`.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from ..plan.emit import canonical_json_bytes
from . import quota as quota_mod

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

DEFAULT_NODES_DIR = _owned("data/seed/passive-tree/nodes")


@dataclass(frozen=True)
class RetiredQuotaCellHit:
    """One node whose persisted `quotaCell.channelFamily` named a retired family."""

    tree_id: str
    node_id: str
    node_index: int
    old_family: str
    new_family: str


def find_retired_quota_cells(doc: "Mapping[str, Any]") -> "list[RetiredQuotaCellHit]":
    """Detect. Walks every node's own `quotaCell` (absent on a legacy pre-quota record, per
    `nodegen.emit.NodeSeedRecord`'s own docstring — skipped, never invented); empty on an
    already-migrated (or never-affected) tree."""
    tree_id = str(doc.get("treeId", ""))
    findings: "list[RetiredQuotaCellHit]" = []
    for i, node in enumerate(doc.get("nodes", [])):
        cell = node.get("quotaCell")
        if not isinstance(cell, dict):
            continue
        family = cell.get("channelFamily")
        if not isinstance(family, str):
            continue
        successor = quota_mod.resolve_retired_channel_family(family)
        if successor != family:
            findings.append(RetiredQuotaCellHit(
                tree_id=tree_id, node_id=str(node.get("id")), node_index=i,
                old_family=family, new_family=successor))
    return findings


def migrate_retired_quota_cells(doc: "Mapping[str, Any]") -> "tuple[dict, list[RetiredQuotaCellHit]]":
    """Fix, pure. Returns a NEW doc (nodes with no retired cell are kept BY IDENTITY, never copied)
    with every retired `quotaCell.channelFamily` re-targeted via `quota.resolve_retired_quota_cell`
    — id, nodeKey, branch, tier, nodeClass, affixIds, affinity, exclusion, name, nameKey, flavor,
    rationale and every OTHER quota axis (element, status, trigger, exclusionForm) untouched — plus
    the list of changes made. An empty list means a no-op, safe to call on an already-clean tree.
    Never mutates `doc` itself."""
    findings = find_retired_quota_cells(doc)
    if not findings:
        return dict(doc), findings

    by_index = {f.node_index: f for f in findings}
    new_nodes = []
    for i, node in enumerate(doc.get("nodes", [])):
        f = by_index.get(i)
        if f is None:
            new_nodes.append(node)
            continue
        new_cell = quota_mod.resolve_retired_quota_cell(node["quotaCell"])
        new_nodes.append({**node, "quotaCell": new_cell})

    return {**dict(doc), "nodes": new_nodes}, findings


def apply_to_tree_file(path: Path) -> "list[RetiredQuotaCellHit]":
    """Read one `gk-data/packs/fusion/data/seed/passive-tree/nodes/<treeId>.json`, migrate, and — only if anything
    changed — write back via `canonical_json_bytes` (the SAME writer `nodegen.emit.write_seed_document`
    uses), so an untouched tree is byte-for-byte identical and a touched one keeps the shipped
    formatting exactly. `_provenance` (including `planHash`, a hash of the GENERATING plan, not of
    this file) is carried through unchanged — this is a mechanical id rewrite of already-accepted
    content, not a new generation."""
    doc: "dict[str, Any]" = json.loads(path.read_text(encoding="utf-8"))
    new_doc, findings = migrate_retired_quota_cells(doc)
    if not findings:
        return findings
    path.write_bytes(canonical_json_bytes(new_doc))
    return findings


def apply_to_real_corpus(nodes_dir: "Path | None" = None) -> "dict[str, list[RetiredQuotaCellHit]]":
    """Walks every `*.json` under `nodes_dir` (default: the real shipped
    `gk-data/packs/fusion/data/seed/passive-tree/nodes/`), fixing each in place. Returns `{treeId: [hit, ...]}` for
    every tree that had at least one retired cell — a tree with none is simply absent from the
    result (and left byte-for-byte untouched on disk), the same "clean corpus, no rewrite at all"
    guarantee `apply_to_tree_file` gives per file."""
    root = nodes_dir or DEFAULT_NODES_DIR
    results: "dict[str, list[RetiredQuotaCellHit]]" = {}
    for path in sorted(root.glob("*.json")):
        findings = apply_to_tree_file(path)
        if findings:
            results[path.stem] = findings
    return results


def main(argv=None) -> int:
    """`python -m seedsmith.adapters.trees.nodegen.migrate_retired_atk [--check]`.

    Default: apply the fix to the real shipped `gk-data/packs/fusion/data/seed/passive-tree/nodes/` corpus. `--check`:
    report only, exit 1 if any retired cell is found, 0 if the corpus is already clean — for
    CI/pre-flight use (mirrors `migrate_legacy_shards.main`'s own `--check` contract)."""
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true",
                        help="report findings only; do not write; exit 1 if any are found")
    args = parser.parse_args(argv)

    if args.check:
        total = 0
        for path in sorted(DEFAULT_NODES_DIR.glob("*.json")):
            doc = json.loads(path.read_text(encoding="utf-8"))
            for f in find_retired_quota_cells(doc):
                print(f"{f.tree_id}[{f.node_id}]: {f.old_family} -> {f.new_family}")
                total += 1
        if total == 0:
            print("clean — no retired quotaCell.channelFamily values found")
            return 0
        print(f"{total} retired quotaCell value(s) found")
        return 1

    results = apply_to_real_corpus()
    if not results:
        print("clean — no retired quotaCell.channelFamily values found, nothing written")
        return 0
    total = 0
    for tree_id, findings in results.items():
        for f in findings:
            print(f"fixed {tree_id}[{f.node_id}]: {f.old_family} -> {f.new_family}")
            total += 1
    print(f"wrote {len(results)} tree file(s), {total} node(s) fixed")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
