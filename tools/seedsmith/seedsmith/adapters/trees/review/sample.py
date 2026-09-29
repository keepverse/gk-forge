"""seedsmith.adapters.trees.review.sample — the three review tiers (task J2, spec-tree-review.md
§3.2).

Tier 1 (CENSUS): read whole, never sampled — small, high-risk populations.
Tier 2 (CLUSTER SAMPLE): 60 trees, stratified, for the generator's health.
Tier 3 (THIN NODE SAMPLE): ~200 nodes over rare quota cells, catching what a tree-level sample
under-covers by construction.

Tiers 2 and 3 both go through the ALREADY-SHIPPED `seedsmith.sampling.stratified_sample` — **no
second sampler is written** (§3.2's own explicit rule, restated here because it is this module's
central constraint, not a detail). Every draw is seeded from `metric_id + revision`
(`sampling.corpus_revision` or a caller-supplied string), so the same draw is reproducible byte for
byte across two calls — the property a reviewer's own re-read depends on.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from .... import sampling
from ..nodegen.quota import QuotaCell

# ---- Tier 1: CENSUS ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ExclusionCensusEntry:
    """One node carrying a real exclusion — population #1 (§3.2's own table): "D14's whole
    mechanism, and all three forms including nullification (D40)"."""

    node_id: str
    tree_id: str
    exclusion_form: str


def census_exclusion_nodes(nodes_by_tree: "dict[str, list[dict]]") -> "tuple[ExclusionCensusEntry, ...]":
    """Every node whose committed `nodes/<treeId>.json` record carries a real exclusion —
    `nodes_by_tree` is `{treeId: [nodeRecord, ...]}`, the same shape `plan_read`/the language
    stage's own seed documents already use. A node with no `exclusion` key, or `exclusion.form ==
    "None"` (the schema's own literal string for "not excluded" — `schema.py`'s own sentinel, never
    a JSON `null`), is not a member. Census, not sample — every match is returned, never truncated.
    """
    entries: "list[ExclusionCensusEntry]" = []
    for tree_id, nodes in nodes_by_tree.items():
        for node in nodes:
            exclusion = node.get("exclusion")
            if not isinstance(exclusion, dict):
                continue
            form = exclusion.get("form")
            if not form or form == "None":
                continue
            entries.append(ExclusionCensusEntry(
                node_id=str(node["id"]), tree_id=tree_id, exclusion_form=str(form)))
    return tuple(entries)


def census_escalated_nodes(outcomes: "Sequence") -> "tuple[str, ...]":
    """Population #2: every subject a real generation run's own `NodeOutcome` sequence reports
    `"escalated"`. Takes the run's own outcomes directly, by design — escalation history has no
    durable store of its own yet (J3's own "verdict queue" is the future home for this; a
    `run_language_stage` call's outcomes are the only real source that exists today, and they are
    never persisted past that one call except for `"accepted"` records in the ledger). A census
    against a corpus with no recent run to hand this function is correctly empty, not fabricated.
    """
    return tuple(o.subject_id for o in outcomes if o.outcome == "escalated")


def census_unresolved_nodes(outcomes: "Sequence") -> "tuple[str, ...]":
    """Population #3: the 1-1-1 vote splits (§3.2's own table: "the creature run's 695 two-to-one
    splits were resolved by majority and no human adjudicated one — do not repeat that"). Same
    input shape and same "no durable store yet" caveat as `census_escalated_nodes` above."""
    return tuple(o.subject_id for o in outcomes if o.outcome == "unresolved")


def census_review_queue(review_dir: "Path", lot: str) -> "tuple":
    """Population #4: "should be zero" (§3.2) — a queue nobody counts is a hiding place. Delegates
    to `verdict_queue.read_verdict_queue` — this task's own EARLIER build (before J3's own
    `VerdictQueueEntry` schema existed) read raw, unvalidated dicts directly; updated the same day
    J3 shipped the real schema so there is exactly one reader of this file format, never two
    independently-shaped ones. A missing file is still an honest `()`
    (`verdict_queue.read_verdict_queue`'s own "declared absence, not fabricated" reading, itself
    matching `census_gate.py`'s established convention for the identical situation one layer up —
    `SheetNotRendered`), unchanged from this function's own original behavior.
    """
    from . import verdict_queue
    return verdict_queue.read_verdict_queue(review_dir, lot)


# ---- Tier 2: CLUSTER SAMPLE over trees ----------------------------------------------------------


@dataclass(frozen=True)
class TreeStratumInput:
    """One tree's own stratification identity (§3.2's own four-axis table: favour triple x side x
    rarity rung x category). The first three axes are properties of a SPECIES anchor (D17's own
    favour triple, the plant/zombie side, the item-rarity rung) — they do not exist for any tree
    category shipped today (primary/elemental/status, J1; family/species are still unbuilt,
    J5-J9). For those, the three species-only axes correctly collapse to `None` rather than a
    fabricated value; the moment species trees exist, their real values flow through
    `stratum_key_for_tree` unchanged — a wiring gap this dataclass's own optional fields already
    accommodate, never an architectural wall (AGENTS.md's rule)."""

    tree_id: str
    category: str
    favour_triple: "tuple[str, str, str] | None" = None
    side: "str | None" = None
    rarity_rung: "int | None" = None


def stratum_key_for_tree(t: TreeStratumInput) -> str:
    """§3.2's own four-axis key, flattened to the single string `stratified_sample` keys on. A
    species-only axis absent on `t` renders as the literal `"n/a"` segment — visible in the key
    itself, so a corpus report can honestly show "most of today's corpus shares one stratum on
    three of four axes" rather than hiding it behind a default that looks like real data."""
    triple = "/".join(t.favour_triple) if t.favour_triple else "n/a"
    side = t.side or "n/a"
    rung = str(t.rarity_rung) if t.rarity_rung is not None else "n/a"
    return f"{t.category}|{triple}|{side}|{rung}"


def cluster_sample_trees(trees: "Sequence[TreeStratumInput]", n: int, *,
                         metric_id: str, revision: str) -> "dict[str, list[TreeStratumInput]]":
    """§3.2 tier 2: draw `n` trees (60 in production), stratified by `stratum_key_for_tree`, through
    the shipped `stratified_sample` — this function never draws itself, only groups and delegates."""
    items_by_stratum: "dict[str, list[TreeStratumInput]]" = defaultdict(list)
    for t in trees:
        items_by_stratum[stratum_key_for_tree(t)].append(t)
    return sampling.stratified_sample(dict(items_by_stratum), n, metric_id=metric_id, revision=revision)


# ---- Tier 3: THIN NODE SAMPLE over rare quota cells ---------------------------------------------


def quota_cell_key(cell: QuotaCell) -> str:
    """The full six-axis quota cell (§2's own `quotaCell` row), flattened to one string — tier 3's
    own stratum, "over rare quota cells" meaning the FULL cell identity, not one axis of it (a
    single rare AXIS value can still land in a common cell overall; §3.2's own worked example,
    "every frostbite node is the same sentence," is about a specific status's own cell, not the
    status axis alone)."""
    return "|".join((cell.node_class, cell.trigger, cell.element, cell.status,
                     cell.channel_family, cell.exclusion_form))


def thin_node_sample(nodes_with_cells: "Sequence[tuple[str, QuotaCell]]", n: int, *,
                     metric_id: str, revision: str) -> "dict[str, list[str]]":
    """§3.2 tier 3: draw `n` nodes (~200 in production), stratified by their own full quota cell,
    through the shipped `stratified_sample` — `stratified_sample`'s own "every non-empty stratum
    gets at least one sample" guarantee is exactly what makes a rare cell (one real status holding
    ~4‰ of the quota, appearing in ~140 nodes corpus-wide) surface in this draw even though a
    60-tree cluster sample would rarely land inside it by chance."""
    items_by_stratum: "dict[str, list[str]]" = defaultdict(list)
    for node_id, cell in nodes_with_cells:
        items_by_stratum[quota_cell_key(cell)].append(node_id)
    return sampling.stratified_sample(dict(items_by_stratum), n, metric_id=metric_id, revision=revision)
