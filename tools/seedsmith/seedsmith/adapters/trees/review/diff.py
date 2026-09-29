"""seedsmith.adapters.trees.review.diff — the O(diff) incremental re-review pass (task J4,
spec-tree-review.md §8).

"Only the diff is re-reviewed, and node-id stability is what makes that sentence mean anything."
This module compares two snapshots of ONE tree and classifies what changed, per §8's own table.

**Real data checked before writing this, not assumed** — and a real design correction made from
what that check found, not from what seemed reasonable in the abstract. The first draft compared
only `gk-data/packs/fusion/data/seed/passive-tree/nodes/<treeId>.json` (language content — `name`/`flavor`/`affixIds`).
Read directly, `gk-data/packs/fusion/data/generated/passive-tree/<treeId>.json` (`tree-binder`'s own bound output)
carries only `nodeId` and `atoms[].kMicro/kindId/channelId/op/...` — NO content fields at all. This
matters for `"magnitude-retune"` specifically: a retune (`gk-core/data/tuning/` only) never touches the
language seed, so seed-only diffing can only ever report a retuned node as `"unchanged"` — true, but
not the distinct claim bullet 1 needs ("an EMPTY human queue" is a fact about the review OUTPUT,
provable either way, but "this was a retune" as its own category needs the bound catalog to see).
`content_fields` is therefore a real PARAMETER, not a hardcoded shape: the caller passes
`LANGUAGE_CONTENT_FIELDS` (the default) to diff the seed and get real `"content-changed"`
detection, or `()` to diff the bound catalog and get real `"magnitude-retune"` detection — an empty
field tuple makes `_content_equal` trivially true for any two dicts sharing an id, which is exactly
correct for the bound catalog: nothing else COULD differ there besides a coefficient.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

#: The language-stage seed's own content fields (`nodegen/emit.py`'s `NodeSeedRecord.to_dict`) —
#: what a human reviewer actually judges. The default `content_fields` for `diff_tree`.
LANGUAGE_CONTENT_FIELDS: "tuple[str, ...]" = ("name", "nameKey", "flavor", "rationale", "affixIds",
                                             "affinity", "exclusion")


@dataclass(frozen=True)
class NodeDiff:
    """One node's own before/after comparison. `kind` is one of:

    - `"unchanged"` — byte-identical old and new.
    - `"magnitude-retune"` — the SAME id, differing dicts, but every field named in the caller's own
      `content_fields` is identical (only fields OUTSIDE that set moved). Diffing the bound catalog
      with `content_fields=()` is what makes this category real (see module docstring) — diffing the
      language seed alone can never produce it, since a retune touches nothing there at all.
    - `"content-changed"` — the SAME id, and at least one field in `content_fields` differs. Needs
      human review, judged inside its own tree (bullet 3).
    - `"added"` / `"removed"` — the id exists in only one snapshot.
    """

    node_id: str
    kind: str
    old: "Mapping | None"
    new: "Mapping | None"


@dataclass(frozen=True)
class TreeDiff:
    """One tree's whole comparison. `full_review` is §8's own safety valve for bullet 2: id churn
    (any node id present in only one snapshot) means the diff cannot trust node-level identity for
    this tree at all, so EVERY node in EITHER snapshot is treated as needing review — never a
    partial diff built on a guess about which old id a new one "really" is. This is the id-stability
    dependency made into a real, checkable property rather than an assumed one: a rename LOOKS
    exactly like an unrelated remove+add (ids are the only identity there is), and the safe response
    to that ambiguity is "review the whole tree," not "guess they're the same node.\""""

    tree_id: str
    node_diffs: "tuple[NodeDiff, ...]"
    full_review: bool

    def human_review_queue(self) -> "tuple[NodeDiff, ...]":
        """Bullet 1 + 3: a magnitude retune (or an unchanged node) contributes NOTHING to the human
        queue — only a real content change, an add, or a remove does. When `full_review` is set
        (bullet 2), EVERY node diff is in the queue unconditionally, including removed ones — the
        whole point of the safety valve is that per-node kinds cannot be trusted once ids have
        churned, and a retirement is itself one of §8's own named review-worthy cases ("Node
        retired: Census the retirements"), never something to drop from the queue silently."""
        if self.full_review:
            return self.node_diffs
        return tuple(d for d in self.node_diffs
                    if d.kind in ("content-changed", "added", "removed"))


def _content_equal(old: "Mapping", new: "Mapping", content_fields: "tuple[str, ...]") -> bool:
    return all(old.get(field) == new.get(field) for field in content_fields)


def diff_tree(tree_id: str, old_nodes: "Mapping[str, Mapping]", new_nodes: "Mapping[str, Mapping]",
             *, content_fields: "tuple[str, ...]" = LANGUAGE_CONTENT_FIELDS) -> TreeDiff:
    """`old_nodes`/`new_nodes` are `{nodeId: nodeRecord}` — the same shape the committed
    `gk-data/packs/fusion/data/seed/passive-tree/nodes/<treeId>.json`'s own node list uses by default (each record keyed
    by its own `id`), or `gk-data/packs/fusion/data/generated/passive-tree/<treeId>.json`'s own bound output when called
    with `content_fields=()` (see module docstring for why that combination is what makes
    `"magnitude-retune"` real). Read twice (before/after) by the caller, never re-derived here. This
    function is pure: it takes two snapshots and returns a verdict, with no file I/O of its own —
    the caller (a future `trees review --diff <fromRev> <toRev>` CLI verb) owns loading the two
    committed revisions and picking which snapshot pair to feed it for which question.
    """
    old_ids = set(old_nodes.keys())
    new_ids = set(new_nodes.keys())
    full_review = old_ids != new_ids

    node_diffs: "list[NodeDiff]" = []
    for node_id in sorted(old_ids | new_ids):
        old = old_nodes.get(node_id)
        new = new_nodes.get(node_id)
        if old is None:
            node_diffs.append(NodeDiff(node_id=node_id, kind="added", old=None, new=new))
        elif new is None:
            node_diffs.append(NodeDiff(node_id=node_id, kind="removed", old=old, new=None))
        elif old == new:
            node_diffs.append(NodeDiff(node_id=node_id, kind="unchanged", old=old, new=new))
        elif _content_equal(old, new, content_fields):
            node_diffs.append(NodeDiff(node_id=node_id, kind="magnitude-retune", old=old, new=new))
        else:
            node_diffs.append(NodeDiff(node_id=node_id, kind="content-changed", old=old, new=new))

    return TreeDiff(tree_id=tree_id, node_diffs=tuple(node_diffs), full_review=full_review)
