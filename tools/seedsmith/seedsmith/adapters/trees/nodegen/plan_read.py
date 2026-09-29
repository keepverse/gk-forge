"""seedsmith.adapters.trees.nodegen.plan_read — reads `tree-plan`'s (task B1) committed plan for
one tree; refuses an unfilled hole rather than defaulting (task H1, spec-tree-language.md §2, §2.2,
§7 gate 3).

**This module reads. It never computes.** Every FROZEN field named in §2's ownership table —
`treeId`, `branch`, `tier`, `nodeClass`, `parents[]` (not yet emitted by B1; see `TreePlanNode`
below), `budgetShareMilli`, `potencyBand` (not yet emitted; same note) — is either read as-is or
reported absent, never synthesised. `quotaCell`/`permittedIds` are NOT emitted onto a B1 node
either (still true as of task H3): the real committed `might.v1.json` carries no such keys per
node. Rather than wait on a B1/emit change out of this stage's own scope, task H3's `quota.py`
computes them itself, downstream of this read — `quota.quota_for_plan(plan, targets, ...)` takes
the `TreePlan` this module returns and derives a `QuotaCell` per node from `plan.property_vocabulary`
(already read here) plus the corpus-wide targets, never from a `quotaCell` key that does not exist
on disk. §7 gate 3 ("plan reachability... unsatisfiable parents, an empty tier, an orphan") is
B1/C1's own `invariants.py` check at EMIT time; this module's own, narrower refusal is the read-side
half: a plan this stage cannot make sense of is a plan it refuses to read from, named by which key
is missing.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[6]


class TreePlanReadError(ValueError):
    """The committed plan has an unfilled hole this stage needs. Refused, never defaulted — the
    same "an unreviewed number here reaches every generated entry" reasoning `tuning.py`'s `A2`
    loader already applies to the targets file, applied here to the plan instead."""


@dataclass(frozen=True)
class TreePlanNode:
    """One `nodes[]` entry, narrowed to the fields this stage actually reads today.

    `quota_cell` and `permitted_ids` are `None` on every node B1 emits as of this task — H3's quota
    stage is what adds them (spec §2's own reconciliation: they are FROZEN fields the PLAN is
    supposed to carry, but the quota algorithm that fills them per §4.2 is out of B1's shipped
    scope and out of H1's). Reading one of these two fields off a plan that does not carry them
    yet must be an explicit `None` check at the call site, never a `KeyError` two modules away.
    """

    node_id: str
    node_key: str
    branch: str
    tier: int
    index_in_tier: int
    node_class: str
    budget_share_milli: int
    budget_points: "int | None"
    quota_cell: "Mapping[str, str] | None"
    permitted_ids: "Mapping[str, tuple[str, ...]] | None"


@dataclass(frozen=True)
class TreePlan:
    """The slice of `plan/<treeId>.v1.json` this stage reads (§2's FROZEN rows)."""

    tree_id: str
    archetype: str
    nodes: "tuple[TreePlanNode, ...]"
    property_vocabulary: "Mapping[str, tuple[str, ...]]"
    mech_nodes_by_tier: "tuple[int, ...]"
    raw: "Mapping[str, object]"

    def nodes_for(self, branch: str, tier: "int | None" = None) -> "tuple[TreePlanNode, ...]":
        return tuple(
            n for n in self.nodes
            if n.branch == branch and (tier is None or n.tier == tier)
        )


def plan_path(tree_id: str, seed_root: "Path | None" = None) -> Path:
    root = seed_root or (REPO_ROOT / "data" / "seed")
    return root / "passive-tree" / "plan" / f"{tree_id}.v1.json"


def _require(doc: dict, *path: str):
    node = doc
    for key in path:
        if not isinstance(node, dict) or key not in node:
            raise TreePlanReadError(
                f"tree-plan for {doc.get('treeId', '?')!r} is missing {'.'.join(path)!r} — "
                f"refusing to synthesise it; this stage reads the plan, it never fills a hole "
                f"in it")
        node = node[key]
    return node


def load(tree_id: str, seed_root: "Path | None" = None) -> TreePlan:
    """§7 gate 3's read-side refusal: a plan file that does not exist, or one whose `nodes[]` is
    empty (an unreachable/empty tier per B1's own invariants), is refused here rather than handed
    downstream as a zero-length subject list that LOOKS like a clean, finished run."""
    path = plan_path(tree_id, seed_root)
    if not path.exists():
        raise TreePlanReadError(
            f"no committed plan at {path} — tree-language reads tree-plan's output, it never "
            f"plans a tree itself (spec-tree-language.md is Stage 2, spec-tree-plan.md is Stage 1)")
    doc = json.loads(path.read_text(encoding="utf-8"))
    return _parse(doc, source_label=str(path))


def load_from_dict(doc: "dict", *, source_label: str = "<in-memory plan>") -> TreePlan:
    """The identical parse `load()` performs, for a caller that already HAS the plan document in
    memory rather than a committed file at the generic `plan/<treeId>.v1.json` path `plan_path()`
    assumes. Task J8: `species_tree_spec`'s own committed plan lives at a real but DIFFERENT path
    (`data/seed/passive-tree/plan/species/<speciesId>.json`, no `.v1` suffix, per spec-species-
    tree.md's own Project structure table) — this function lets the species orchestration feed
    `build_plan`'s own dict straight into the SAME `run_language_stage` every generic tree already
    uses, without teaching this generic, foundational module a second path shape. Whether that dict
    came from disk or was just built in memory is identical from here on: the exact same refusals
    (`nodes[]` empty, no `propertyVocabulary`) apply either way, and `raw` still round-trips the
    real document, never a narrowed copy.
    """
    return _parse(dict(doc), source_label=source_label)


def _parse(doc: "dict", *, source_label: str) -> TreePlan:
    raw_nodes = _require(doc, "nodes")
    if not raw_nodes:
        raise TreePlanReadError(f"{source_label}: nodes[] is empty — an empty tree is a plan-side "
                                f"defect, not something this stage may paper over")

    property_vocab = doc.get("propertyVocabulary")
    if not property_vocab:
        # §5.1 / §7 R8: the stage "refuses to run against a plan carrying no propertyVocabulary —
        # it never synthesises one" (H3's own acceptance wording, restated at the read site).
        raise TreePlanReadError(
            f"{source_label}: propertyVocabulary is missing or empty — tree-language never "
            f"synthesises a property vocabulary; it can only read one tree-plan already emitted")

    nodes = tuple(
        TreePlanNode(
            node_id=str(n["id"]),
            node_key=str(n["nodeKey"]),
            branch=str(n["branch"]),
            tier=int(n["tier"]),
            index_in_tier=int(n["indexInTier"]),
            node_class=str(n["nodeClass"]),
            budget_share_milli=int(n["budgetShareMilli"]),
            budget_points=(int(n["budgetPoints"]) if "budgetPoints" in n else None),
            quota_cell=(dict(n["quotaCell"]) if "quotaCell" in n else None),
            permitted_ids=(
                {k: tuple(v) for k, v in n["permittedIds"].items()} if "permittedIds" in n else None
            ),
        )
        for n in raw_nodes
    )

    return TreePlan(
        tree_id=str(_require(doc, "treeId")),
        archetype=str(_require(doc, "archetype")),
        nodes=nodes,
        property_vocabulary={k: tuple(v) for k, v in property_vocab.items()},
        mech_nodes_by_tier=tuple(int(x) for x in doc.get("mechNodesByTier", ())),
        raw=doc,
    )
