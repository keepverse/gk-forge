"""seedsmith.adapters.trees.census — the passive-tree distribution census (task P0.1,
`tasks/passive-tree-repair-plan.md` §1).

**Why this module exists.** The 2026-09-11 baseline measured the passive-tree corpus with a single
aggregate (`266/1680` bound) and missed the defect that actually makes the tree unplayable: mechanism
nodes bind at **2.1%** while magnitude nodes bind at **29.5%**, and tiers 8-10 — which the plan
authors as **100% mechanism** — therefore produce nothing. An aggregate hides a per-class collapse.
This module reports the distribution the aggregate hid: bind rate **by node class**, **by tier**,
**by category**, and **by tree**, plus the refusal buckets, the inert-bound count, the unspent budget,
and the vocabulary a run chose from.

**What it reads, and from where.** Three committed artifact families, each the output of a different
stage, never re-derived here:

  - the PLAN (`gk-data/packs/fusion/data/seed/passive-tree/plan/<treeId>.v1.json`, `tree-plan`'s output) — the
    AUTHORITATIVE expected population (`nodes[]` carries `nodeClass`/`tier`/`branch` per node);
  - the SEED (`gk-data/packs/fusion/data/seed/passive-tree/nodes/<treeId>.json`, `tree-language`'s output) — the chosen
    `affixIds` and the accepted node set, used only to detect a generated node with no seed document;
  - the BOUND report (`gk-data/packs/fusion/data/generated/passive-tree/<treeId>.json`, `tree-binder`'s output) — what
    actually bound, refused, and priced.

**Two different "missing node" states, never conflated.** A node in `bound`/`refused` that is absent
from the PLAN is a real defect (`orphan_generated_node_ids` — the binder emitted an id nobody planned).
A node in the PLAN that has no seed record is the opposite: normal class E, a not-yet-generated node
in a partly-run corpus (`never_generated_node_ids`), which the binder correctly refuses. The 2026-09-11
baseline reported the second as if it were the first; the 2026-09-12 pass measured the whole corpus
and found **zero** true orphans and exactly **one** never-generated node (`wither`'s
`skill.wither-def-t9-n1`, 39 of 40).

**Expected comes from the PLAN, never the seed.** A seed document is partial by construction (it holds
only accepted nodes), so using it as the denominator would make a partly-generated tree look fully
bound. The plan is the skeleton; `bound + refused` should reconcile to it, and where it does not, that
is itself a finding this census reports (`unaccounted`).

**This module measures. It never gates, never repairs, and never writes a corpus file.** Its CLI
surfaces (`trees census [--json]`) print; a later phase's gate compares two runs of it. Every number
here is a READING of the committed corpus at one revision, never a constant.
"""
from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

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


DEFAULT_SEED_ROOT = _owned("data/seed")
DEFAULT_OUT_ROOT = _owned("data/generated/passive-tree")

#: Coarse buckets for `tree-binder`'s refusal reasons. A reason that matches none lands in `other`
#: and is still reported verbatim by `by_reason`, so a new refusal shape shows up in the census on
#: the run it first appears rather than being silently folded into a known bucket.
_REFUSAL_PATTERNS: "tuple[tuple[str, str], ...]" = (
    ("does not exist in the shipped seed content", "affixNotGenerated"),
    ("op 'more'", "opMore"),
    ("names no atom id", "slotNamesNoAtom"),
    ("unregistered kind", "unregisteredKind"),
    ("unregistered attachPoint", "unregisteredAttachPoint"),
)

_MECHANISM = "mechanism"
_MAGNITUDE = "magnitude"

#: The one kind `PassiveTree.Resolve.TreeAtomSource.BoundAtomsFor` reads. That function skips every
#: atom whose `KindId` is not this one (`if (atom.KindId != "stat.derived") continue;`), so a bound
#: `stat.modify` atom is PRICED and never READ — it contributes exactly zero to a live actor.
#:
#: <para>**Readable is not the same as priced, and the census exists because they differ.** The
#: 2026-09-13 measurement found 407 bound nodes whose atoms were 100% `stat.modify` — every one
#: priced, every one dropped. Counting `node.atoms` non-empty as "contributing" reported 243 healthy
#: nodes where the truth was 0. This constant is the census's copy of the resolver's own predicate; it
#: is asserted against the resolver source in the test suite so the two cannot drift.</para>
READABLE_KIND_ID = "stat.derived"

#: Per-record provenance vintages that are legitimate states of a corpus, never "current". Matched by
#: value, not enumerated as constants, so a new brief vintage never needs an edit here — only the
#: CURRENT one is special-cased, and it is read live from `brief.PROMPT_VERSION`.
_VINTAGE_MIXED = "mixed"
_VINTAGE_PRE_PROVENANCE = "pre-provenance"


def current_prompt_version() -> str:
    """The vintage a fresh generation stamps today, read from the brief that owns it. Imported
    lazily so this module stays importable (and testable) without the brief's model-facing surface,
    and so a caller can never accidentally duplicate the literal."""
    from .nodegen import brief

    return brief.PROMPT_VERSION


def classify_vintage(stamped: str, current: str) -> str:
    """One seed document's provenance state, as a closed classification (task P1.3):

    - ``current`` — every record carries the live vintage.
    - ``mixed`` — records disagree (a resumed run replaying pre-provenance records beside new ones);
      the document stamp is the literal ``mixed`` sentinel and hides exactly which nodes are stale.
    - ``pre-provenance`` — no record carries any vintage (the legacy shape: content generated before
      the per-record field existed). A document stamp that equals the CURRENT vintage while its
      records are pre-provenance is precisely the lie `build_seed_document`'s own note documents; it
      is reported as ``pre-provenance`` here, never as current.
    - ``stale`` — every record agrees, but on a vintage older than the live one.

    An empty `stamped` with an empty `current` is `current`, not stale: both say "no provenance
    expected", which is the pre-vintage program state.
    """
    if stamped == current:
        return "current"
    if stamped == _VINTAGE_MIXED:
        return _VINTAGE_MIXED
    if not stamped:
        return _VINTAGE_PRE_PROVENANCE
    return "stale"


def classify_refusal(reason: str) -> str:
    """The coarse bucket for one `tree-binder` refusal reason. `other` is a real answer, not a
    failure — `DistributionCensus.by_reason` always carries the exact string beside it."""
    for needle, bucket in _REFUSAL_PATTERNS:
        if needle in reason:
            return bucket
    return "other"


@dataclass(frozen=True)
class TreeCensus:
    """One tree's own distribution — the row an aggregate cannot show.

    `expected_*` come from the PLAN; `bound_*` from the bound report; `bound_without_priced_atoms`
    is the inert count (a node the binder called "bound" while pricing nothing the resolver reads),
    the single most misleading state this report exists to surface.
    """

    tree_id: str
    category: str
    gate_quantity: str
    verdict: str
    archetype: str

    expected_nodes: int
    seed_nodes: int
    bound_nodes: int
    refused_nodes: int
    unaccounted_nodes: int

    bound_with_priced_atoms: int
    bound_without_priced_atoms: int
    priced_atom_count: int
    bound_with_status_atoms: int
    status_atom_count: int
    bound_with_readable_atoms: int
    readable_atom_count: int
    bound_atoms_by_kind: "Mapping[str, int]"

    expected_mechanism: int
    bound_mechanism: int
    expected_magnitude: int
    bound_magnitude: int
    expected_mechanism_by_tier: "tuple[int, ...]"
    bound_mechanism_by_tier: "tuple[int, ...]"

    unspent_budget_share_milli: int
    orphan_generated_node_ids: "tuple[str, ...]"
    never_generated_node_ids: "tuple[str, ...]"
    bound_node_ids: "tuple[str, ...]"
    chosen_affix_ids: "tuple[str, ...]"
    document_vintage: str
    vintage_state: str
    stale_vintage_node_ids: "tuple[str, ...]"

    @property
    def mechanism_bind_permille(self) -> int:
        return _permille(self.bound_mechanism, self.expected_mechanism)

    @property
    def magnitude_bind_permille(self) -> int:
        return _permille(self.bound_magnitude, self.expected_magnitude)

    @property
    def bind_permille(self) -> int:
        return _permille(self.bound_nodes, self.expected_nodes)

    @property
    def inert_share_permille(self) -> int:
        return _permille(self.bound_without_priced_atoms, self.bound_nodes)

    @property
    def unreadable_share_permille(self) -> int:
        """The share of BOUND nodes the resolver actually drops — the repair skill's own §0.1
        definition of the expensive failure: *"a bound node whose `kindId` is not the one
        `TreeAtomSource` reads contributes exactly zero — the most expensive failure in this seam,
        because it is silent."* Distinct from `inert_share_permille`, which counts zero-priced
        atoms: a node can be fully priced and still 100% unreadable (the 2026-09-13 finding)."""
        return _permille(self.bound_nodes - self.bound_with_readable_atoms, self.bound_nodes)

    @property
    def never_generated_count(self) -> int:
        return len(self.never_generated_node_ids)

    @property
    def is_current_vintage(self) -> bool:
        return self.vintage_state == "current"


def _permille(numerator: int, denominator: int) -> int:
    """Integer per-mille, truncating (integer division last). A zero denominator is
    `0`, which every caller reads as "no population" rather than "0% bound" — the two rows differ by
    their own denominators in the report."""
    if denominator <= 0:
        return 0
    return (numerator * 1000) // denominator


def _plan_node_class(node: Mapping[str, Any]) -> str:
    return _MECHANISM if str(node.get("nodeClass", "")).lower() == _MECHANISM else _MAGNITUDE


def _tier_of(node_id: str) -> int:
    """The tier segment `-t<N>-` of a node id, or `0` when the id does not carry one. The plan's own
    `tier` field is authoritative and preferred; this is the fallback for a generated id only."""
    marker = "-t"
    start = node_id.find(marker)
    if start < 0:
        return 0
    rest = node_id[start + len(marker):]
    digits = "".join(c for c in rest if c.isdigit())
    return int(digits) if digits else 0


def census_tree(
    tree_id: str,
    plan_raw: Mapping[str, Any],
    seed_doc: "Mapping[str, Any] | None",
    generated: "Mapping[str, Any] | None",
    *,
    current_vintage: str = "",
) -> TreeCensus:
    """One tree, from its three committed artifacts. Pure: no file I/O, no cross-tree reads.

    `current_vintage` is the live brief vintage (`brief.PROMPT_VERSION`); the default empty string is
    for a caller that only wants the shape, and makes every stamped document read `current` (no
    provenance expected). Pass the real value to classify staleness.
    """
    plan_nodes = list(plan_raw.get("nodes") or [])
    plan_class_by_id: "dict[str, str]" = {}
    plan_tier_by_id: "dict[str, int]" = {}
    expected_mechanism_by_tier = Counter()
    expected_mechanism = 0
    for node in plan_nodes:
        node_id = str(node.get("id", ""))
        node_class = _plan_node_class(node)
        expected_tier = int(node.get("tier") or _tier_of(node_id))
        plan_class_by_id[node_id] = node_class
        plan_tier_by_id[node_id] = expected_tier
        if node_class == _MECHANISM:
            expected_mechanism += 1
            expected_mechanism_by_tier[expected_tier] += 1

    seed_nodes = list((seed_doc or {}).get("nodes") or [])
    seed_ids = {str(n.get("id", "")) for n in seed_nodes}

    bound = list((generated or {}).get("bound") or [])
    refused = list((generated or {}).get("refused") or [])

    bound_with_priced_atoms = 0
    priced_atom_count = 0
    bound_with_status_atoms = 0
    status_atom_count = 0
    bound_with_readable_atoms = 0
    readable_atom_count = 0
    bound_by_kind: "Counter[str]" = Counter()
    bound_mechanism = 0
    bound_mechanism_by_tier = Counter()
    for node in bound:
        node_id = str(node.get("nodeId", ""))
        atoms = list(node.get("atoms") or [])
        if atoms:
            bound_with_priced_atoms += 1
            priced_atom_count += len(atoms)
        # MC-1: status atoms ride the sibling array in bound[] entries too — count them, so the
        # census stops reporting status-carrying nodes as unpriced.
        status_atoms = list(node.get("statusAtoms") or [])
        if status_atoms:
            bound_with_status_atoms += 1
            status_atom_count += len(status_atoms)
        readable = [a for a in atoms if str(a.get("kindId", "")) == READABLE_KIND_ID]
        if readable:
            bound_with_readable_atoms += 1
            readable_atom_count += len(readable)
        for atom in atoms:
            bound_by_kind[str(atom.get("kindId", ""))] += 1
        if plan_class_by_id.get(node_id) == _MECHANISM:
            bound_mechanism += 1
            bound_mechanism_by_tier[plan_tier_by_id.get(node_id, _tier_of(node_id))] += 1

    expected = len(plan_nodes)
    bound_count = len(bound)
    refused_count = len(refused)

    chosen_affix_ids: "set[str]" = set()
    for node in seed_nodes:
        chosen_affix_ids.update(str(a) for a in (node.get("affixIds") or []))

    provenance = (seed_doc or {}).get("_provenance") or {}
    document_vintage = str(provenance.get("promptVersion", ""))
    per_node_vintage = provenance.get("promptVersionByNode") or {}
    # The per-node vintages are authoritative, and the rule is exactly `nodegen.run.plan_run._stale`'s
    # own: a record is stale when its effective vintage differs from the live one, and an EMPTY
    # effective vintage is pre-provenance — stale, never current. That last point matters because
    # `build_seed_document` stamps the caller's CURRENT vintage as the document value when every
    # record predates the per-record field, so trusting the document stamp would report content that
    # was generated under an older brief as current. Effective vintage: the node's own recorded value
    # when present, else the document stamp.
    def _effective(node: Mapping[str, Any]) -> str:
        node_id = str(node.get("id", ""))
        if node_id in per_node_vintage:
            return str(per_node_vintage[node_id] or "")
        return document_vintage

    stale_vintage_node_ids = tuple(sorted(
        str(node.get("id", "")) for node in seed_nodes
        if current_vintage and _effective(node) != current_vintage
    ))
    vintage_state = classify_vintage(document_vintage, current_vintage)
    if vintage_state == "current" and stale_vintage_node_ids:
        vintage_state = _VINTAGE_MIXED

    orphans = tuple(sorted(
        node_id for node_id in
        {str(n.get("nodeId", "")) for n in bound} | {str(r.get("nodeId", "")) for r in refused}
        if node_id and node_id not in plan_class_by_id
    ))

    # A plan node with no seed record and no accepted ledger outcome is NOT an orphan and NOT a
    # defect: it is a node the language stage has not generated yet (class E, an incomplete run).
    # The seed document is partial by construction, so this is the normal state of a partly-run
    # corpus and the binder refuses it correctly (`affixIds must be 1..3, got 0`). It is reported
    # because it is the honest denominator for "how much of this tree is real" — never because it
    # is wrong. An empty plan makes the comparison meaningless, so it is skipped, not reported as
    # every-node-ungenerated.
    never_generated = tuple(sorted(
        node_id for node_id in plan_class_by_id if node_id not in seed_ids
    )) if plan_class_by_id else ()

    max_tier = max(
        list(expected_mechanism_by_tier) + list(bound_mechanism_by_tier) + [0],
    )
    return TreeCensus(
        tree_id=tree_id,
        category=str(plan_raw.get("category", "")),
        gate_quantity=str(plan_raw.get("gateQuantity", "")),
        verdict=str((generated or {}).get("verdict", "MISSING")),
        archetype=str((generated or {}).get("shapeArchetype") or plan_raw.get("archetype", "")),
        expected_nodes=expected,
        seed_nodes=len(seed_nodes),
        bound_nodes=bound_count,
        refused_nodes=refused_count,
        unaccounted_nodes=expected - bound_count - refused_count,
        bound_with_priced_atoms=bound_with_priced_atoms,
        bound_without_priced_atoms=bound_count - bound_with_priced_atoms,
        priced_atom_count=priced_atom_count,
        bound_with_status_atoms=bound_with_status_atoms,
        status_atom_count=status_atom_count,
        bound_with_readable_atoms=bound_with_readable_atoms,
        readable_atom_count=readable_atom_count,
        bound_atoms_by_kind=dict(sorted(bound_by_kind.items())),
        expected_mechanism=expected_mechanism,
        bound_mechanism=bound_mechanism,
        expected_magnitude=expected - expected_mechanism,
        bound_magnitude=bound_count - bound_mechanism,
        expected_mechanism_by_tier=tuple(expected_mechanism_by_tier.get(t, 0) for t in range(1, max_tier + 1)),
        bound_mechanism_by_tier=tuple(bound_mechanism_by_tier.get(t, 0) for t in range(1, max_tier + 1)),
        unspent_budget_share_milli=int((generated or {}).get("totalUnspentBudgetShareMilli", 0)),
        orphan_generated_node_ids=orphans,
        never_generated_node_ids=never_generated,
        bound_node_ids=tuple(sorted(str(n.get("nodeId", "")) for n in bound)),
        chosen_affix_ids=tuple(sorted(chosen_affix_ids)),
        document_vintage=document_vintage,
        vintage_state=vintage_state,
        stale_vintage_node_ids=stale_vintage_node_ids,
    )


@dataclass(frozen=True)
class DistributionCensus:
    """Every tree plus the corpus-wide buckets. Aggregates are derived here, once, so two callers
    (text and JSON) can never disagree about one number."""

    trees: "tuple[TreeCensus, ...]"
    by_reason: "Mapping[str, int]"
    by_reason_class: "Mapping[str, int]"

    def tree(self, tree_id: str) -> "TreeCensus | None":
        for row in self.trees:
            if row.tree_id == tree_id:
                return row
        return None

    def totals(self) -> "dict[str, int]":
        return {
            "trees": len(self.trees),
            "expectedNodes": sum(t.expected_nodes for t in self.trees),
            "boundNodes": sum(t.bound_nodes for t in self.trees),
            "refusedNodes": sum(t.refused_nodes for t in self.trees),
            "unaccountedNodes": sum(t.unaccounted_nodes for t in self.trees),
            "boundWithPricedAtoms": sum(t.bound_with_priced_atoms for t in self.trees),
            "boundWithoutPricedAtoms": sum(t.bound_without_priced_atoms for t in self.trees),
            "pricedAtoms": sum(t.priced_atom_count for t in self.trees),
            "boundWithStatusAtoms": sum(t.bound_with_status_atoms for t in self.trees),
            "statusAtoms": sum(t.status_atom_count for t in self.trees),
            "boundWithReadableAtoms": sum(t.bound_with_readable_atoms for t in self.trees),
            "unreadableBoundNodes": sum(t.bound_nodes - t.bound_with_readable_atoms for t in self.trees),
            "readableAtoms": sum(t.readable_atom_count for t in self.trees),
            "unspentBudgetShareMilli": sum(t.unspent_budget_share_milli for t in self.trees),
        }

    def bound_atoms_by_kind(self) -> "dict[str, int]":
        """Every priced atom in the corpus, by kind — the one reading that states whether the binder
        and the resolver even agree on a kind. `{'stat.modify': N}` with no `stat.derived` means every
        bound node is silently dropped, no matter how healthy the bind rate looks."""
        totals: "Counter[str]" = Counter()
        for tree in self.trees:
            for kind, count in tree.bound_atoms_by_kind.items():
                totals[kind] += count
        return dict(sorted(totals.items(), key=lambda kv: (-kv[1], kv[0])))

    def by_class(self) -> "dict[str, dict[str, int]]":
        mech_expected = sum(t.expected_mechanism for t in self.trees)
        mech_bound = sum(t.bound_mechanism for t in self.trees)
        mag_expected = sum(t.expected_magnitude for t in self.trees)
        mag_bound = sum(t.bound_magnitude for t in self.trees)
        return {
            _MECHANISM: {"expected": mech_expected, "bound": mech_bound,
                         "bindPermille": _permille(mech_bound, mech_expected)},
            _MAGNITUDE: {"expected": mag_expected, "bound": mag_bound,
                         "bindPermille": _permille(mag_bound, mag_expected)},
        }

    def by_category(self) -> "dict[str, dict[str, int]]":
        out: "dict[str, dict[str, int]]" = {}
        for category in sorted({t.category for t in self.trees}):
            expected = sum(t.expected_nodes for t in self.trees if t.category == category)
            bound = sum(t.bound_nodes for t in self.trees if t.category == category)
            out[category] = {"trees": sum(1 for t in self.trees if t.category == category),
                             "expected": expected, "bound": bound,
                             "bindPermille": _permille(bound, expected)}
        return out

    def by_vintage(self) -> "dict[str, int]":
        counts: "Counter[str]" = Counter(t.vintage_state for t in self.trees)
        return dict(sorted(counts.items()))

    def stale_vintage_trees(self) -> "tuple[TreeCensus, ...]":
        """Every tree whose content is not the current brief vintage — the input a completion gate
        needs (task P1.3). A stale tree is not a defect in the corpus's *content*; it is content
        generated under an older brief, which only a re-roll can refresh, so this is the scope a
        regeneration pass must cover. Reported separately from `orphanGeneratedNodeIds`, which IS a
        defect: conflating "needs a re-roll" with "wrong" is how a real defect gets batched into a
        routine regeneration and disappears.
        """
        return tuple(t for t in self.trees if t.vintage_state != "current")

    def by_tier_mechanism(self) -> "dict[int, dict[str, int]]":
        tiers = range(1, 1 + max(
            (len(t.expected_mechanism_by_tier) for t in self.trees), default=0))
        out: "dict[int, dict[str, int]]" = {}
        for tier in tiers:
            index = tier - 1
            expected = sum(
                t.expected_mechanism_by_tier[index]
                for t in self.trees if index < len(t.expected_mechanism_by_tier))
            bound = sum(
                t.bound_mechanism_by_tier[index]
                for t in self.trees if index < len(t.bound_mechanism_by_tier))
            out[tier] = {"expected": expected, "bound": bound,
                         "bindPermille": _permille(bound, expected)}
        return out

    def worst_trees(self, limit: int = 12) -> "tuple[TreeCensus, ...]":
        return tuple(sorted(self.trees, key=lambda t: (t.bind_permille, -t.expected_nodes,
                                                       t.tree_id))[:limit])

    def best_trees(self, limit: int = 12) -> "tuple[TreeCensus, ...]":
        return tuple(sorted(self.trees, key=lambda t: (-t.bind_permille, -t.expected_nodes,
                                                       t.tree_id))[:limit])

    def to_dict(self) -> "dict[str, Any]":
        return {
            "totals": self.totals(),
            "byClass": self.by_class(),
            "byCategory": self.by_category(),
            "byTierMechanism": {str(k): v for k, v in self.by_tier_mechanism().items()},
            "byReason": dict(sorted(self.by_reason.items())),
            "byReasonClass": dict(sorted(self.by_reason_class.items())),
            "byVintage": self.by_vintage(),
            "trees": [
                {
                    "treeId": t.tree_id, "category": t.category, "archetype": t.archetype,
                    "verdict": t.verdict, "expectedNodes": t.expected_nodes,
                    "seedNodes": t.seed_nodes,
                    "boundNodes": t.bound_nodes, "refusedNodes": t.refused_nodes,
                    "unaccountedNodes": t.unaccounted_nodes,
            "boundWithPricedAtoms": t.bound_with_priced_atoms,
            "boundWithoutPricedAtoms": t.bound_without_priced_atoms,
            "pricedAtoms": t.priced_atom_count,
            "boundWithStatusAtoms": t.bound_with_status_atoms,
            "statusAtoms": t.status_atom_count,
            "boundWithReadableAtoms": t.bound_with_readable_atoms,
            "readableAtoms": t.readable_atom_count,
            "unreadableSharePermille": t.unreadable_share_permille,
            "boundAtomsByKind": dict(t.bound_atoms_by_kind),
                    "bindPermille": t.bind_permille,
                    "mechanismExpected": t.expected_mechanism,
                    "mechanismBound": t.bound_mechanism,
                    "mechanismBindPermille": t.mechanism_bind_permille,
                    "magnitudeExpected": t.expected_magnitude,
                    "magnitudeBound": t.bound_magnitude,
                    "magnitudeBindPermille": t.magnitude_bind_permille,
                    "expectedMechanismByTier": list(t.expected_mechanism_by_tier),
                    "boundMechanismByTier": list(t.bound_mechanism_by_tier),
                    "unspentBudgetShareMilli": t.unspent_budget_share_milli,
                    "orphanGeneratedNodeIds": list(t.orphan_generated_node_ids),
                    "neverGeneratedNodeIds": list(t.never_generated_node_ids),
                    "chosenAffixIds": list(t.chosen_affix_ids),
                    "documentVintage": t.document_vintage,
                    "vintageState": t.vintage_state,
                    "staleVintageNodeIds": list(t.stale_vintage_node_ids),
                }
                for t in self.trees
            ],
        }

    def format_text(self) -> str:
        def pct(permille: int) -> str:
            return f"{permille / 10:.1f}%"

        lines: "list[str]" = []
        totals = self.totals()
        lines.append("passive-tree distribution census")
        lines.append("=" * 78)
        lines.append(f"trees={totals['trees']}  expected={totals['expectedNodes']}  "
                     f"bound={totals['boundNodes']}  refused={totals['refusedNodes']}  "
                     f"unaccounted={totals['unaccountedNodes']}  "
                     f"overall={pct(_permille(totals['boundNodes'], totals['expectedNodes']))}")
        lines.append(f"boundWithPricedAtoms={totals['boundWithPricedAtoms']}  "
                     f"boundWithoutPricedAtoms={totals['boundWithoutPricedAtoms']}  "
                     f"pricedAtoms={totals['pricedAtoms']}  "
                     f"unspentBudgetShareMilli={totals['unspentBudgetShareMilli']}")
        lines.append(f"boundWithReadableAtoms={totals['boundWithReadableAtoms']}  "
                     f"unreadableBoundNodes={totals['unreadableBoundNodes']}  "
                     f"readableAtoms={totals['readableAtoms']}  "
                     f"readable={pct(_permille(totals['boundNodes'] - totals['unreadableBoundNodes'], totals['boundNodes']))} of bound")

        by_kind = self.bound_atoms_by_kind()
        lines.append("")
        lines.append("bound atoms by kind (the binder's priced set)")
        if not by_kind:
            lines.append("  (none)")
        for kind, count in by_kind.items():
            mark = "" if kind == READABLE_KIND_ID else "   <- NOT read by the resolver (dropped silently)"
            lines.append(f"  {kind or '(empty)'}: {count}{mark}")
        if by_kind and READABLE_KIND_ID not in by_kind:
            lines.append(f"  DEFECT: no '{READABLE_KIND_ID}' atom bound — every bound node contributes zero "
                         f"even though the bind rate looks healthy (task R4/P4.3)")

        lines.append("")
        lines.append("bind rate by node class")
        for name, row in self.by_class().items():
            lines.append(f"  {name:<10} {row['bound']:>5}/{row['expected']:<5} "
                         f"{pct(row['bindPermille']):>7}")
        lines.append("  (mechanism is the deep-tier payoff; a collapse here empties tiers 8-10)")

        lines.append("")
        lines.append("bind rate by category")
        for name, row in self.by_category().items():
            lines.append(f"  {name:<10} {row['bound']:>5}/{row['expected']:<5} "
                         f"{pct(row['bindPermille']):>7}  ({row['trees']} trees)")

        lines.append("")
        lines.append("mechanism by tier (expected -> bound)")
        for tier, row in self.by_tier_mechanism().items():
            lines.append(f"  tier {tier:>2}  {row['expected']:>4} -> {row['bound']:<4} "
                         f"{pct(row['bindPermille']):>7}")

        lines.append("")
        lines.append("refusal buckets")
        for bucket, count in sorted(self.by_reason_class.items(), key=lambda kv: -kv[1]):
            lines.append(f"  {bucket:<24} {count}")
        for reason, count in sorted(self.by_reason.items(), key=lambda kv: -kv[1]):
            lines.append(f"    · {count:>4}  {reason}")

        lines.append("")
        lines.append("worst trees")
        for t in self.worst_trees():
            lines.append(f"  {t.tree_id:<18} {t.bound_nodes:>3}/{t.expected_nodes:<3} "
                         f"{pct(t.bind_permille):>7}  mech {t.bound_mechanism}/{t.expected_mechanism}"
                         f"  inert {t.bound_without_priced_atoms}")

        lines.append("")
        lines.append("best trees")
        for t in self.best_trees():
            lines.append(f"  {t.tree_id:<18} {t.bound_nodes:>3}/{t.expected_nodes:<3} "
                         f"{pct(t.bind_permille):>7}  mech {t.bound_mechanism}/{t.expected_mechanism}"
                         f"  inert {t.bound_without_priced_atoms}")

        orphans = [(t.tree_id, t.orphan_generated_node_ids)
                   for t in self.trees if t.orphan_generated_node_ids]
        if orphans:
            lines.append("")
            lines.append("DEFECT — generated nodes with no plan node (the binder emitted an unknown id)")
            for tree_id, ids in orphans:
                lines.append(f"  {tree_id}: {', '.join(ids)}")

        never = [(t.tree_id, t.never_generated_node_ids)
                 for t in self.trees if t.never_generated_node_ids]
        if never:
            lines.append("")
            lines.append("plan nodes the language stage has not generated yet (class E; not a defect)")
            for tree_id, ids in never:
                lines.append(f"  {tree_id}: {len(ids)} node(s) — {', '.join(ids)}")

        lines.append("")
        lines.append("provenance vintage (the brief vintage a fresh generation would stamp today)")
        for state, count in self.by_vintage().items():
            lines.append(f"  {state:<16} {count} tree(s)")
        stale = [t for t in self.stale_vintage_trees()]
        if stale:
            total_stale = sum(len(t.stale_vintage_node_ids) for t in stale)
            lines.append(f"  {total_stale} record(s) across {len(stale)} tree(s) are not the current "
                         f"vintage — a fresh `trees generate` re-rolls them, and the document stamp "
                         f"cannot see it (per-node provenance is authoritative)")

        mismatched = [t for t in self.trees if t.unaccounted_nodes != 0]
        if mismatched:
            lines.append("")
            lines.append("trees where bound+refused does not reconcile to the plan")
            for t in mismatched:
                lines.append(f"  {t.tree_id}: plan={t.expected_nodes} bound={t.bound_nodes} "
                             f"refused={t.refused_nodes} unaccounted={t.unaccounted_nodes}")
        return "\n".join(lines)


def _load_json(path: Path) -> "dict[str, Any] | None":
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def planned_tree_ids(seed_root: "Path | None" = None) -> "list[str]":
    """Every generic tree with a committed plan. Mirrors `report/cli._every_planned_tree_id` so the
    census never reads a different tree set than `trees generate --all` writes."""
    root = (seed_root or DEFAULT_SEED_ROOT) / "passive-tree" / "plan"
    if not root.is_dir():
        return []
    return sorted(p.name[: -len(".v1.json")] for p in root.glob("*.v1.json"))


def census(
    seed_root: "Path | None" = None,
    out_root: "Path | None" = None,
    tree_ids: "Sequence[str] | None" = None,
    *,
    current_vintage: "str | None" = None,
) -> DistributionCensus:
    """Read the three committed artifact families for every planned tree and compute the
    distribution. Missing artifacts are a legitimate reading (`MISSING` verdict, zero bound), not an
    error — a tree the binder has never run is a real, reportable state.

    `current_vintage` defaults to the live `brief.PROMPT_VERSION`; pass `""` to classify provenance
    without asserting a target vintage.
    """
    seed = seed_root or DEFAULT_SEED_ROOT
    out = out_root or DEFAULT_OUT_ROOT
    ids = list(tree_ids) if tree_ids is not None else planned_tree_ids(seed)
    vintage = current_prompt_version() if current_vintage is None else current_vintage

    rows: "list[TreeCensus]" = []
    by_reason: "Counter[str]" = Counter()
    by_reason_class: "Counter[str]" = Counter()

    for tree_id in ids:
        plan_raw = _load_json(seed / "passive-tree" / "plan" / f"{tree_id}.v1.json")
        if plan_raw is None:
            continue
        seed_doc = _load_json(seed / "passive-tree" / "nodes" / f"{tree_id}.json")
        generated = _load_json(out / f"{tree_id}.json")
        rows.append(census_tree(tree_id, plan_raw, seed_doc, generated,
                                current_vintage=vintage))
        for refused in (generated or {}).get("refused") or []:
            reason = str(refused.get("reason", ""))
            by_reason[reason] += 1
            by_reason_class[classify_refusal(reason)] += 1

    return DistributionCensus(trees=tuple(sorted(rows, key=lambda t: t.tree_id)),
                              by_reason=dict(by_reason), by_reason_class=dict(by_reason_class))


__all__ = [
    "REPO_ROOT", "DEFAULT_SEED_ROOT", "DEFAULT_OUT_ROOT",
    "classify_refusal", "current_prompt_version", "classify_vintage",
    "TreeCensus", "DistributionCensus",
    "census_tree", "planned_tree_ids", "census",
]
