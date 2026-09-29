"""seedsmith.metrics.passive_tree — `PassiveTree/TreeEqualValue` (spec-tree-plan.md §3.2, task C1)
plus the eight `PassiveTree/*` corpus metrics (spec-tree-language.md §7 gates 15-22, task H4), plus
task H5's own three `tree-review` metrics (spec-tree-review.md §4.1, §4.2, §7): the CONTENT-side
half of `TreeEqualValue` (over `tree-binder`'s own bound prices, folded into the SAME registration
C1 already made — never a second metric sharing one name), `PassiveTree/DeepMechanismValue`
(`gates=False`, reports rather than blocks), and `PassiveTree/HiddenFileCount` (walks every seed
root WITHOUT the `_`-prefix skip convention, reporting `visitedFileCount` explicitly).

`spec-tree-review.md:202` leans on this gate to justify not sampling budgets by hand, and
`:210` correctly notes it is plan-side arithmetic rather than one of `tree-language`'s 24
content gates. It was left unowned by both specs; this module is where it lives, registered
beside `Distribution/CellOccupancy` (`metrics/cell_occupancy.py`) and the `action.corpus.*`
family (`metrics/action_coverage.py`) through the SAME `Metric`/`MetricRegistry` machinery.

The real arithmetic is `adapters.trees.plan.invariants.check_tree_equal_value` — this module is a
thin `Metric` wrapper, the same shape `action_coverage.py`'s own docstring describes for itself:
"the real computation lives in the adapter; this is a thin wrapper." It never raises out of
`run()` (the `Metric` contract here is "return findings," not "throw") — a violation becomes a
GAP-severity `Finding` naming the tree/branch/tier/archetype the underlying refusal named, so a
caller that wants a hard stop still has `invariants.check_tree_equal_value` itself, which DOES
raise, and IS what `report/cli.py`'s `--emit`/`--check` paths call directly.

⛔ **H4's own honest finding, stated once here rather than repeated in every class below.** The
node record `tree-language` actually persists (`nodegen/emit.py:NodeSeedRecord.to_dict`) carries
`nodeClass`, `exclusion.{form,propertyKeys,printedText}`, `name`, `nameKey`, `flavor`, `affixIds`
and `affinity` — it does NOT carry `trigger`, `element`, `status` or `channelFamily` (§5.1's own
"blocked on other work" finding: the atom-tag registry that would let a node's own bound affixes
be traced back to those four axes does not exist yet). So a metric that needs one of those four
axes (`QuotaDrift`, `CellOccupancy`) reads it off `PassiveTreePlanCtx.quota_cells_by_tree` — the
per-node `QuotaCell` H3's own `quota.assign_quota_cells` computed AT GENERATION TIME, which is the
only place today those four axes are recorded at all. This is a wiring gap (AGENTS.md's own
rule, not an architectural wall): the day a generation run persists `quotaCell` onto the node
record itself, this ctx field is filled from the committed corpus directly rather than a
caller-supplied snapshot, and no metric below needs to change.
"""
from __future__ import annotations

import json
import statistics
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

from ..adapters.trees.nodegen import dedup as nodegen_dedup
from ..adapters.trees.nodegen import exclusion as nodegen_exclusion
from ..adapters.trees.nodegen import quota as nodegen_quota
from ..adapters.trees.plan import invariants as plan_invariants
from ..adapters.trees.plan.archetypes import SHIPPED_ARCHETYPES, TIER_COUNT, Archetype
from ..adapters.trees.species import plan as species_plan
from ..adapters.trees.targets import PassiveTreeTargets
from ..workflow.validators.field_echo import name_collision
from .model import Ctx, Finding, Loop, Metric, Severity


@dataclass(frozen=True)
class PassiveTreePlanCtx:
    """What `PassiveTree/TreeEqualValue` needs: the emitted plan(s) alone, plus the tuning values
    the underlying checks compare against — no corpus, no adapter, no model call.

    **H4 additions below** (`targets` through `atom_tag_registry`): the corpus-side half this same
    context grew into once the eight `PassiveTree/*` metrics needed real generation output to
    measure. Every one of them defaults to empty/`None`, so every existing `PassiveTreePlanCtx(...)`
    construction site (C1's own tests included) keeps working unmodified — this is additive, never a
    breaking reshape of a context two tasks already ship tests against.
    """
    plans: "list[dict]"
    archetypes: "tuple[Archetype, ...]"
    tier_count: int
    unlock_first_points: int
    unlock_step_points: int
    reward_spread_max_ratio_milli: int
    min_terminal_width: int

    #: H4 — the real `PassiveTreeTargets` (`adapters.trees.targets.load()`), for every threshold
    #: the eight metrics below compare against. `None` means "no thresholds available," which every
    #: metric that needs one reports as `NOT_MEASURED`, never a silently-passed default.
    targets: "PassiveTreeTargets | None" = None

    #: H4 — one `plan_read.TreePlan` per tree in this corpus (typed loosely as `object` to avoid a
    #: dependency on `nodegen.plan_read` from this dataclass's own declaration — every metric below
    #: reads it duck-typed, the same discipline `quota.py`'s own `quota_for_plan` already applies to
    #: its own `plan` parameter). Keyed implicitly by each plan's own `.tree_id`.
    tree_plans: "tuple[Any, ...]" = ()

    #: H4 — `{treeId: [nodeRecordDict, ...]}`, exactly the shape `nodegen.emit.read_seed_document`
    #: returns under `"nodes"` — the committed, ACCEPTED corpus (never a node that was blocked,
    #: escalated or left unresolved; those live in `outcomes_by_tree` instead).
    nodes_by_tree: "Mapping[str, Sequence[Mapping[str, Any]]]" = field(default_factory=dict)

    #: H4 — `{treeId: {nodeId: QuotaCell}}`, the per-node six-axis cell a real generation run
    #: assigned (`quota.assign_quota_cells`'s own output) — the stand-in for "what the corpus
    #: actually shows" on the four axes the seed file itself does not persist (module docstring).
    quota_cells_by_tree: "Mapping[str, Mapping[str, Any]]" = field(default_factory=dict)

    #: H4 — `{treeId: [{"nodeId": ..., "outcome": "accepted"|"blocked"|"unresolved"|"escalated"}]}`,
    #: one entry per `nodegen.run.Subject` a real run attempted — `UnresolvedCount` is the one
    #: metric that needs to see a node that never made it into `nodes_by_tree` at all.
    outcomes_by_tree: "Mapping[str, Sequence[Mapping[str, Any]]]" = field(default_factory=dict)

    #: H4 — the not-yet-built atom-tag registry (§5.1). `None` (its only real value today) makes
    #: `ExclusionResolvable` report `NOT_MEASURED` by name rather than fake a pass or crash.
    atom_tag_registry: "Mapping[str, Any] | None" = None

    # -- H5 additions below (spec-tree-review.md §4.1, §4.2, §7) -- same growth discipline as H4's
    # own note above: every field defaults to empty/`None`, so every H4-and-earlier construction
    # site (including C1's own tests) keeps working unmodified. `needs` stays `passive_tree_plan`
    # for both new H5 metrics too -- never a new `Ctx`/`VALID_NEEDS` entry for a need nothing else
    # in this family would ever read (the exact rule the H4 docstring above states for itself).

    #: H5 -- `tree-binder`'s own committed output, one entry per tree it bound
    #: (`gk-data/packs/fusion/data/generated/passive-tree/<treeId>.json`, `ReportWriter.Serialize`'s exact shape):
    #: `{treeId: {"treeId":.., "verdict":.., "bound": [{"nodeId":.., "atoms": [{"channelId":..,
    #: "kMicro":.., ...}]}], "refused": [...]}}`. Empty (its default) means "no bound reports were
    #: supplied" -- `TreeEqualValueMetric` reads that as "the content-side half was not asked to
    #: run this time," never as "checked and clean" (spec-tree-review.md §4.1's own ✅ resolution:
    #: two halves, two stages, neither substitutes for the other).
    bound_reports_by_tree: "Mapping[str, Any]" = field(default_factory=dict)

    #: H5 -- the two `tree-binder` tunables §3.3's formula reads
    #: (`gk-core/data/tuning/passive-tree.v1.json`'s own top-level `treeShareMilli`/`treeBudgetMilli` keys,
    #: R2's "the program's ONE tunable file"). `None` means "the content-side half cannot recompute
    #: an expected kMicro" -- reported as `NOT_MEASURED`, never guessed at a placeholder.
    tree_share_milli: "int | None" = None
    tree_budget_milli: "int | None" = None

    #: H5 -- D29's structural branch count (2, never tunable -- "the tree's own shape"). Kept as a
    #: field rather than a bare literal in the formula below so a caller building `PassiveTreePlanCtx`
    #: names every input the formula reads, matching every sibling H4 field's own discipline.
    branches: int = 2

    #: H5 -- `channelAnchorMilli` per anchor family (`"atk"`/`"defense"`, the only two
    #: `power-scale.v{n}.json` publishes a pin for today -- spec-tree-binder.md §3.3/§3.6),
    #: precomputed by the caller from that tuning file's own pins (`round_half_away(pinCh * 1000,
    #: pinHp)`) rather than re-parsed here: this module stays pure computation over caller-supplied
    #: data, the same discipline every other H4 field already holds to (no metric in this file reads
    #: a tuning file itself). A missing family reports as a distinct `noChannelAnchorSupplied`
    #: problem, never a silently-skipped node.
    channel_anchor_milli: "Mapping[str, int]" = field(default_factory=dict)

    #: H5 -- `PassiveTree/DeepMechanismValue`'s own input: `{treeId: [{"nodeId":..,
    #: "winShareDeltaMilli":..}, ...]}`, one entry per deep-tier mechanism node a real `CombatSim`
    #: sweep sampled. This module never runs `CombatSim` itself (a C# tool, outside this task's own
    #: scope) and never invents a sample -- empty (the default) reports `NOT_MEASURED` by name.
    deep_mechanism_samples: "Mapping[str, Sequence[Mapping[str, Any]]]" = field(default_factory=dict)

    #: H5 -- the reporting-only threshold `DeepMechanismValue` compares a sample's
    #: `winShareDeltaMilli` against. `None` (no threshold available) means every supplied sample is
    #: reported but none is flagged weak -- this metric `gates=False` regardless, so a missing
    #: threshold here can never silently pass a run the way a missing GATING_METRICS threshold would.
    deep_mechanism_value_min_win_share_delta_milli: "int | None" = None

    #: H5 -- every seed root `PassiveTree/HiddenFileCount` walks WITHOUT the `_`-prefix skip
    #: convention (§7's own named blind spot). Empty (its default) means zero roots were walked --
    #: the metric still reports a NOTE naming `visitedFileCount: 0` explicitly, so that green is
    #: never confused with "the real corpus was checked and is clean."
    tree_seed_roots: "Sequence[Path]" = ()

    # -- J5 addition below (spec-species-tree.md §3.1 step 4, §3.2/D32) -- same growth discipline:
    # both fields default empty/`None`, so every earlier construction site keeps working unmodified.

    #: J5 -- one entry per species a real `species.plan.assign_favour_cells` run placed, shaped
    #: `{"speciesId": ..., "aptitude": ..., "element": ..., "status": ...}` (duck-typed rather than
    #: importing `species.plan.FavourAssignment` here, the same "typed loosely, read off a real
    #: run's own output" discipline `tree_plans`/`outcomes_by_tree` already hold to above). Empty
    #: (its default) means no emitted favour distribution was supplied -- `FavourDriftMetric`
    #: reports `NOT_MEASURED` rather than compare against nothing.
    species_favour_assignments: "Sequence[Mapping[str, str]]" = ()

    #: J5 -- one entry per species the STAGE (spec-species-tree.md §3.1 step 3, not yet built --
    #: "the call receives ONE cell, its alternates... and answers: does this favour fit?") attempted,
    #: shaped `{"speciesId": ..., "outcome": "resolved" | "unresolved"}` -- the species-level sibling
    #: of `outcomes_by_tree`'s own per-node `"outcome"` field, read by `UnresolvedCountMetric` below
    #: as a SECOND, independent population under the SAME gate (§3.1/§4's own success criterion names
    #: the identical 50‰ figure `gates.unresolvedCount.maxSharePermille` already ships). Empty (its
    #: default) means no favour-resolution attempts were supplied -- every pre-J5 call site is
    #: unaffected, proven by test.
    species_favour_outcomes: "Sequence[Mapping[str, Any]]" = ()

    #: J5 -- the reporting-only tolerance `FavourDriftMetric` flags a GAP beyond, in per-mille share
    #: of the corpus (never a raw unit count -- the three favour axes have wildly different member
    #: counts, 12/6/24, so a share is the only comparable unit across all three). `None` (no real
    #: generation run exists yet to calibrate against, per §5.1's own shipped posture: "promote one
    #: gate at a time, only after a real run has been measured") means every axis-member's drift is
    #: still reported, just never flagged GAP -- the same "reporting threshold, not a required one"
    #: shape `deep_mechanism_value_min_win_share_delta_milli` already holds to above.
    favour_drift_tolerance_share_permille: "int | None" = None


# -- H5's own arithmetic (spec-tree-review.md §4.1) -- the CONTENT-side half of TreeEqualValue,
# re-deriving each bound atom's `kMicro` from its node's own `budgetShareMilli` via the EXACT
# formula `CoefficientBinder.Bind` computes in C# (spec-tree-binder.md §3.3), and comparing it
# against what `tree-binder` actually persisted. This lives here rather than in
# `adapters.trees.plan.invariants` deliberately: that module is `tree-plan`'s own (its docstring:
# "this module does not re-derive arithmetic archetypes.py and ladder.py already own"), and
# `adapters.trees.plan.tuning`'s own docstring draws the boundary explicitly -- "tree-binder's ...
# keys live in the same file but are that module's concern." There is no Python-side `tree-binder`
# package to own this yet (the real binder is `gk-forge/tools/TreeBinder`, C#, task D2); until one exists,
# the metric that NEEDS this re-derivation carries it, the same way `QuotaDrift` above carries its
# own re-derivation of a quota rather than importing a target from somewhere quota.py doesn't own.
#
# Every module in this file that widens before multiplying keeps its OWN private `_widen_mul` copy
# (docs/architecture/numeric-types.md's numeric-overflow rule 3) rather than importing a sibling module's private helper --
# `invariants.py`, `emit.py` and every `adapters.actions.*.derive` module already draw this same
# line, so this is not a new convention.

_LONG_MAX = 9_223_372_036_854_775_807
_LONG_MIN = -9_223_372_036_854_775_808


def _widen_mul(a: int, b: int) -> int:
    """The repo-wide `long` bound (docs/architecture/numeric-types.md's numeric-overflow table) as an EXPLICIT stand-in --
    Python ints never actually overflow, so this is the same guard every sibling adapter's own
    `_widen_mul` copy already carries."""
    product = int(a) * int(b)
    if product > _LONG_MAX or product < _LONG_MIN:
        raise OverflowError(f"_widen_mul({a}, {b}) = {product} does not fit a long ({_LONG_MIN}..{_LONG_MAX})")
    return product


def _trunc_div(n: int, d: int) -> int:
    """Truncating-toward-zero integer division -- C#'s `/` semantics for integers, which Python's
    `//` (floor) does not match for mixed-sign operands. Pure integer arithmetic, to mirror the C#
    integer result exactly."""
    q = abs(n) // abs(d)
    return -q if (n < 0) != (d < 0) else q


def _round_half_away_from_zero(numerator: int, denominator: int) -> int:
    """Mirrors `CoefficientBinder.RoundHalfAwayFromZero` / `ChannelAnchor`'s identical private copy
    (both C#, spec-tree-binder.md §3.3) exactly, bit for bit -- including the truncating quotient,
    never Python's floor-biased `divmod`."""
    if denominator == 0:
        raise ZeroDivisionError("denominator must not be zero")
    q = _trunc_div(numerator, denominator)
    r = numerator - q * denominator
    if r == 0:
        return q
    twice_r = abs(r) * 2
    if numerator >= 0:
        return q + 1 if twice_r >= abs(denominator) else q
    return q - 1 if twice_r >= abs(denominator) else q


def _anchor_family_for_channel(channel_id: "str | None") -> "str | None":
    """Mirrors `ChannelAnchor.AnchorFamilyOf` (spec-tree-binder.md §3.6, `ChannelAnchor.cs:30-37`)
    exactly -- the only two `GameUnits` families `power-scale.v{n}.json` publishes a pin for today.
    Anything else (a `PerMilleRatio`/`ThetaLinear` channel, or an atom `TreeBinderRun` composed but
    deliberately did not price -- its own stated scope) returns `None` rather than guessing a
    family: this check only prices the atoms the binder actually priced by this formula, never
    invents one for the atoms it left composed-not-priced."""
    if channel_id in ("atk", "defense"):
        return channel_id
    if isinstance(channel_id, str) and channel_id.startswith("combat.power."):
        return "atk"
    if isinstance(channel_id, str) and channel_id.startswith("combat.defense."):
        return "defense"
    return None


def _expected_kmicro(tree_share_milli: int, tree_budget_milli: int, budget_share_milli: int,
                     channel_anchor_milli: int, branches: int) -> int:
    """`kMicro = round_half_away(treeShareMilli * treeBudgetMilli * budgetShareMilli *
    channelAnchorMilli, branches * 1_000_000)` -- spec-tree-binder.md §3.3, the exact formula
    `CoefficientBinder.Bind` computes in C#. Re-derived here independently (never trusting the
    stored value) so a divergence between what `tree-binder` actually persisted and what the
    plan's own `budgetShareMilli` says it should have priced is a real, catchable defect -- the
    same "recompute rather than trust a stored value" discipline `QuotaDrift` already applies one
    layer up in this same file."""
    num = _widen_mul(_widen_mul(_widen_mul(tree_share_milli, tree_budget_milli), budget_share_milli),
                     channel_anchor_milli)
    denom = _widen_mul(branches, 1_000_000)
    return _round_half_away_from_zero(num, denom)


def check_bound_prices_honour_budget(
    plans: "list[dict]",
    bound_reports_by_tree: "Mapping[str, Any]",
    tree_share_milli: int,
    tree_budget_milli: int,
    branches: int,
    channel_anchor_milli: "Mapping[str, int]",
) -> "list[dict]":
    """The content-side half of `PassiveTree/TreeEqualValue` (spec-tree-review.md §4.1): "the
    content-side half -- the one this module runs, over `tree-binder`'s prices -- proves the
    generated content honoured that budget." Returns one problem dict per divergence (never raises,
    unlike the plan-side `check_tree_equal_value`, so a caller sees every offending node in one
    pass rather than stopping at the first -- the content-side check is per-node arithmetic, and a
    reviewer benefits from the full list the same way `QuotaDrift`/`MechanismRamp` already report
    every offending axis/tier rather than only the first).

    Each problem dict names `treeId`, `nodeId`, `channelId` and a `reason`:
    - `"priceMismatch"` -- the actual bound `kMicro` disagrees with the value `_expected_kmicro`
      derives from this node's own `budgetShareMilli` (the acceptance bullet's own named case: "a
      corpus with one over-priced tree fails TreeEqualValue").
    - `"nodeNotInPlan"` / `"noMatchingPlan"` -- the bound report names a tree/node this corpus's
      own plan(s) do not carry (a corpus-consistency defect, not a pricing one).
    - `"noChannelAnchorSupplied"` -- the atom's channel needs an anchor
      (`_anchor_family_for_channel` returned a family) but the caller supplied none for it, so this
      atom's price cannot be verified either way -- named rather than silently skipped.

    A channel `_anchor_family_for_channel` cannot place (a `PerMilleRatio`/`ThetaLinear` channel, or
    an atom `TreeBinderRun` composed but did not price) is skipped outright: this formula never
    priced it in the first place, so there is nothing to compare it against."""
    plans_by_tree = {p.get("treeId"): p for p in plans}
    problems: "list[dict]" = []
    for tree_id, report in bound_reports_by_tree.items():
        plan = plans_by_tree.get(tree_id)
        if plan is None:
            problems.append({"treeId": tree_id, "nodeId": "(tree)", "channelId": "-",
                             "reason": "noMatchingPlan", "expectedKMicro": None, "actualKMicro": None})
            continue
        budget_by_node = {n["id"]: n.get("budgetShareMilli") for n in plan.get("nodes", [])}
        for bound_node in report.get("bound", []):
            node_id = bound_node.get("nodeId", "?")
            budget_share_milli = budget_by_node.get(node_id)
            if budget_share_milli is None:
                problems.append({"treeId": tree_id, "nodeId": node_id, "channelId": "-",
                                 "reason": "nodeNotInPlan", "expectedKMicro": None, "actualKMicro": None})
                continue
            for atom in bound_node.get("atoms", []):
                channel_id = atom.get("channelId")
                family = _anchor_family_for_channel(channel_id)
                if family is None:
                    continue  # not priced by this formula at all (TreeBinderRun's own scope note)
                actual = atom.get("kMicro")
                anchor = channel_anchor_milli.get(family)
                if anchor is None:
                    problems.append({"treeId": tree_id, "nodeId": node_id, "channelId": channel_id,
                                     "reason": "noChannelAnchorSupplied", "expectedKMicro": None,
                                     "actualKMicro": actual, "family": family})
                    continue
                expected = _expected_kmicro(tree_share_milli, tree_budget_milli, budget_share_milli,
                                            anchor, branches)
                if actual != expected:
                    problems.append({"treeId": tree_id, "nodeId": node_id, "channelId": channel_id,
                                     "reason": "priceMismatch", "expectedKMicro": expected,
                                     "actualKMicro": actual, "budgetShareMilli": budget_share_milli,
                                     "channelAnchorMilli": anchor, "family": family})
    return problems


class TreeEqualValueMetric(Metric):
    id = "PassiveTree/TreeEqualValue"
    family = "PassiveTree"
    loop = Loop.CLOSED
    gates = False  # promotion is a deliberate, later, separate act (spec-metrics.md §4) — the CLI's
                   # own --emit/--check path already hard-refuses via invariants.py directly; this
                   # registry entry is for `tree-review`'s corpus-wide read, not the emit gate.
    needs = frozenset({"passive_tree_plan"})
    covers: "tuple[str, ...]" = ()

    def run(self, ctx: Ctx) -> "list[Finding]":
        plan_ctx: PassiveTreePlanCtx = ctx.passive_tree_plan
        tree_ids = ", ".join(sorted(p.get("treeId", "?") for p in plan_ctx.plans))
        try:
            plan_invariants.check_tree_equal_value(
                plan_ctx.plans, plan_ctx.archetypes, plan_ctx.tier_count,
                plan_ctx.unlock_first_points, plan_ctx.unlock_step_points,
                plan_ctx.reward_spread_max_ratio_milli, plan_ctx.min_terminal_width,
            )
        except plan_invariants.PlanInvariantError as ex:
            return [Finding(
                metric=self.id, severity=Severity.GAP, subject=f"tree:{tree_ids or '(none)'}",
                message=str(ex),
                evidence={"code": type(ex).__name__},
                assertion="every tree spends the same total, R-A1/P-1/P-2 hold at every tier",
                remedy="seedsmith trees plan --emit — regenerate rather than hand-edit the plan",
            )]

        # H5 (spec-tree-review.md §4.1) — the CONTENT-side half, over `tree-binder`'s own bound
        # prices. SAME metric id, same registration as the plan-side check above — a second input
        # source, never a second metric. Opt-in: a caller that supplies no `bound_reports_by_tree`
        # (every pre-H5 construction site, and any plan-emit-time check that runs before
        # tree-binder has produced anything) exercises the plan-side half alone — the plain
        # "C1, R-A1, P-1 and P-2" NOTE below, unchanged from before H5 landed.
        if plan_ctx.bound_reports_by_tree:
            if plan_ctx.tree_share_milli is None or plan_ctx.tree_budget_milli is None:
                return [_not_measured(
                    self.id, f"tree:{tree_ids or '(none)'}",
                    "bound_reports_by_tree was supplied but tree_share_milli/tree_budget_milli "
                    "were not — the content-side half needs both to recompute an expected kMicro "
                    "(spec-tree-binder.md §3.3)")]
            problems = check_bound_prices_honour_budget(
                plan_ctx.plans, plan_ctx.bound_reports_by_tree,
                plan_ctx.tree_share_milli, plan_ctx.tree_budget_milli,
                plan_ctx.branches, plan_ctx.channel_anchor_milli)
            if problems:
                mismatches = [p for p in problems if p["reason"] == "priceMismatch"]
                names = "; ".join(
                    f"{p['treeId']}:{p['nodeId']}:{p['channelId']} bound={p['actualKMicro']} "
                    f"expected={p['expectedKMicro']} (reason={p['reason']})" for p in problems[:5])
                more = f" (+{len(problems) - 5} more)" if len(problems) > 5 else ""
                return [Finding(
                    metric=self.id, severity=Severity.GAP, subject=f"tree:{tree_ids or '(none)'}",
                    message=f"{len(problems)} bound-price problem(s), {len(mismatches)} of them an "
                            f"over/under-priced node: {names}{more}",
                    evidence={"problemCount": len(problems), "priceMismatchCount": len(mismatches),
                             "problems": problems},
                    assertion="every bound atom's kMicro equals round_half_away(treeShareMilli * "
                              "treeBudgetMilli * budgetShareMilli * channelAnchorMilli, branches * "
                              "1_000_000) — spec-tree-binder.md §3.3",
                    remedy="tools/TreeBinder -- --seed data/seed/passive-tree --out "
                           "data/generated/passive-tree — regenerate; never hand-edit a stored kMicro",
                )]
            return [Finding(
                metric=self.id, severity=Severity.NOTE, subject=f"tree:{tree_ids or '(none)'}",
                message=f"C1, R-A1, P-1 and P-2 all hold across {len(plan_ctx.plans)} tree(s); "
                        f"every bound atom's price matches its node's budget across "
                        f"{len(plan_ctx.bound_reports_by_tree)} bound tree report(s)",
                evidence={"treeCount": len(plan_ctx.plans),
                         "boundTreesChecked": len(plan_ctx.bound_reports_by_tree)},
            )]

        return [Finding(
            metric=self.id, severity=Severity.NOTE, subject=f"tree:{tree_ids or '(none)'}",
            message=f"C1, R-A1, P-1 and P-2 all hold across {len(plan_ctx.plans)} tree(s)",
            evidence={"treeCount": len(plan_ctx.plans)},
        )]


# ---------------------------------------------------------------------------------------------
# Task H4 — the eight `PassiveTree/*` corpus metrics (spec-tree-language.md §7 gates 15-22).
#
# All eight share `needs = frozenset({"passive_tree_plan"})` — the SAME need `TreeEqualValueMetric`
# already registered (never a new `Ctx`/`VALID_NEEDS` entry): `PassiveTreePlanCtx` is this module's
# own dataclass, so its H4 fields grow inside the file H4 is scoped to rather than reaching into
# `metrics/model.py` for a sibling need nothing else in this family would ever read.
# ---------------------------------------------------------------------------------------------

_NEEDS = frozenset({"passive_tree_plan"})


def _not_measured(metric_id: str, subject: str, message: str, **evidence: Any) -> Finding:
    return Finding(metric=metric_id, severity=Severity.NOT_MEASURED, subject=subject,
                   message=message, evidence=evidence)


class QuotaDriftMetric(Metric):
    """§7 gate 15 — **re-derives the quota, never reads a declared one.** The only quantity this
    metric trusts from its caller is `quota_cells_by_tree` (what the corpus shows each node was
    actually assigned); the TARGET it compares that against is always a fresh call to
    `quota.quota_for_plan(plan, targets, ...)` — the same function H3 built and the CLI's own
    `_cmd_trees_generate` calls at generation time (`report/cli.py`). Nothing about a stored
    "declared quota" (a brief's own printed cell, a cached report) is ever read as the target, which
    is what makes a mutated brief harmless to this metric: mutating whatever declared a target
    changes nothing this function looks at, because it never looks there (`coverage_report/
    derive.py:257-282`'s own `quota_drift_findings` is the precedent this mirrors — recompute the
    group target fresh, never trust a passed-in one, and compare against the corpus's own counts).

    Symmetric, per §7 gate 15 and the Success criteria's own wording: an axis value **over** its
    re-derived target by more than `toleranceUnits` is exactly as much a drift as one under it.
    """

    id = "PassiveTree/QuotaDrift"
    family = "PassiveTree"
    loop = Loop.CLOSED
    gates = False
    needs = _NEEDS
    covers: "tuple[str, ...]" = ()

    def run(self, ctx: Ctx) -> "list[Finding]":
        plan_ctx: PassiveTreePlanCtx = ctx.passive_tree_plan
        if not plan_ctx.tree_plans or plan_ctx.targets is None:
            return [_not_measured(self.id, "(suite)",
                                  "no tree_plans/targets supplied — nothing to re-derive a quota against")]

        tolerance = plan_ctx.targets.quota_drift_tolerance_units
        findings: "list[Finding]" = []
        for plan in plan_ctx.tree_plans:
            observed = dict(plan_ctx.quota_cells_by_tree.get(plan.tree_id) or {})
            if not observed:
                findings.append(_not_measured(self.id, plan.tree_id,
                                              "no observed quota cells for this tree"))
                continue
            try:
                expected = nodegen_quota.quota_for_plan(
                    plan, plan_ctx.targets, category=str(plan.raw.get("category")),
                    forced_element=plan.raw.get("forcedElement"),
                    forced_status=plan.raw.get("forcedStatus"))
            except (ValueError, KeyError) as ex:
                findings.append(_not_measured(self.id, plan.tree_id,
                                              f"quota could not be re-derived: {ex}"))
                continue

            for axis in nodegen_quota.AXES:
                expected_counts = Counter(cell.value_for(axis) for cell in expected.values())
                observed_counts = Counter(
                    cell.value_for(axis) for node_id, cell in observed.items() if node_id in expected)
                for value in sorted(set(expected_counts) | set(observed_counts)):
                    exp = expected_counts.get(value, 0)
                    obs = observed_counts.get(value, 0)
                    drift = obs - exp
                    if abs(drift) > tolerance:
                        findings.append(Finding(
                            metric=self.id, severity=Severity.GAP,
                            subject=f"{plan.tree_id}:{axis}={value}",
                            message=f"{plan.tree_id} {axis}={value!r}: corpus shows {obs}, the "
                                    f"re-derived quota is {exp} (drift {drift:+d}, tolerance "
                                    f"{tolerance} unit(s))",
                            evidence={"observed": obs, "expected": exp, "driftUnits": drift,
                                     "toleranceUnits": tolerance, "axis": axis, "value": value},
                            assertion=f"abs(observed - re-derived quota) <= {tolerance} for every "
                                      f"{axis} value",
                            remedy="tree-language: this axis's brief or the targets file has "
                                   "drifted from the quota this stage actually assigned"))
                    else:
                        findings.append(Finding(
                            metric=self.id, severity=Severity.NOTE,
                            subject=f"{plan.tree_id}:{axis}={value}",
                            message=f"{plan.tree_id} {axis}={value!r}: corpus shows {obs} vs "
                                    f"re-derived quota {exp} (drift {drift:+d})",
                            evidence={"observed": obs, "expected": exp, "driftUnits": drift,
                                     "toleranceUnits": tolerance, "axis": axis, "value": value}))
        return findings


class MechanismRampMetric(Metric):
    """§7 gate 16 — an **exact per-tier COUNT** against `archetypes[].mechNodes[t]`
    (`plan.mech_nodes_by_tier`, already read off the committed plan by `plan_read`), checked in
    BOTH directions. A threshold (`>=` some floor share) would pass an overshoot silently and would
    also fail to distinguish `broad-and-flat`'s own tiers 4-7 — `mechNodesByTier == [0,0,0,1,1,1,1,
    2,2,2]` for the shipped archetype — from one another: all four hold the identical target count
    (1 mechanism node out of a width-2 tier), so a RATIO-shaped threshold recomputed from the
    continuous ramp (`mechanism_share_milli`, which strictly increases tier over tier) would compute
    four different fractional targets for those four tiers and round some of them differently than
    the plan's own already-rounded `mechNodesByTier` did — flagging a tier that in fact matches
    exactly, or missing one that does not, purely from re-deriving the ramp instead of comparing the
    plan's own already-authoritative integer target. Comparing the exact integer avoids re-deriving
    the ramp formula (and its rounding) a second time in a different place.

    Plus the special case §7 gate 16 names by name: `mechNodes[tierCount] == w[tierCount]` (R-M1,
    `archetypes.py:mechanism_nodes`'s own docstring) — the deepest tier is 100% mechanism, checked
    here against the tree's OWN archetype width, never a formula re-derived locally.
    """

    id = "PassiveTree/MechanismRamp"
    family = "PassiveTree"
    loop = Loop.CLOSED
    gates = False
    needs = _NEEDS
    covers: "tuple[str, ...]" = ()

    def run(self, ctx: Ctx) -> "list[Finding]":
        plan_ctx: PassiveTreePlanCtx = ctx.passive_tree_plan
        if not plan_ctx.tree_plans:
            return [_not_measured(self.id, "(suite)", "no tree_plans supplied")]

        findings: "list[Finding]" = []
        for plan in plan_ctx.tree_plans:
            nodes = plan_ctx.nodes_by_tree.get(plan.tree_id) or []
            if not nodes:
                findings.append(_not_measured(self.id, plan.tree_id, "no emitted nodes for this tree"))
                continue
            target = tuple(plan.mech_nodes_by_tier)
            if len(target) != TIER_COUNT:
                findings.append(_not_measured(
                    self.id, plan.tree_id,
                    f"mechNodesByTier has {len(target)} entries, need {TIER_COUNT}"))
                continue

            node_class_by_id = {n["id"]: n.get("nodeClass") for n in nodes}
            branches = sorted({pn.branch for pn in plan.nodes})
            for branch in branches:
                for t in range(1, TIER_COUNT + 1):
                    tier_node_ids = [pn.node_id for pn in plan.nodes
                                     if pn.branch == branch and pn.tier == t]
                    actual = sum(1 for nid in tier_node_ids if node_class_by_id.get(nid) == "mechanism")
                    expected = target[t - 1]
                    if actual != expected:
                        findings.append(Finding(
                            metric=self.id, severity=Severity.GAP,
                            subject=f"{plan.tree_id}:{branch}:t{t}",
                            message=f"{plan.tree_id} {branch} tier {t}: {actual} mechanism node(s) "
                                    f"in the corpus, the archetype ramp names exactly {expected} — "
                                    f"exact count, not a threshold, so both a shortfall and an "
                                    f"excess are refused",
                            evidence={"actual": actual, "expected": expected, "tier": t,
                                     "branch": branch, "treeId": plan.tree_id},
                            assertion=f"count(nodeClass=mechanism, tier={t}, branch={branch}) == "
                                      f"{expected}"))

            try:
                archetype_obj = next(a for a in SHIPPED_ARCHETYPES if a.id == plan.archetype)
            except StopIteration:
                findings.append(_not_measured(
                    self.id, plan.tree_id,
                    f"archetype {plan.archetype!r} is not one of the shipped archetypes"))
                continue
            deepest_width = archetype_obj.widths[TIER_COUNT - 1]
            if target[TIER_COUNT - 1] != deepest_width:
                findings.append(Finding(
                    metric=self.id, severity=Severity.GAP, subject=f"{plan.tree_id}:deepest-tier",
                    message=f"{plan.tree_id}: mechNodesByTier[{TIER_COUNT}]={target[TIER_COUNT - 1]} "
                            f"but the {plan.archetype!r} archetype's own tier-{TIER_COUNT} width is "
                            f"{deepest_width} — R-M1 requires the deepest tier to be 100% mechanism",
                    evidence={"mechNodesAtDeepestTier": target[TIER_COUNT - 1], "width": deepest_width},
                    assertion=f"mechNodesByTier[{TIER_COUNT}] == archetype.widths[{TIER_COUNT}]"))
        return findings


class CellOccupancyMetric(Metric):
    """§7 gate 17 — `(channelFamily, sorted trigger+element multiset)` per node, `cells.py:56-68`'s
    own `(capability, sorted higher-threshold family multiset)` key adapted to this program's own
    six-axis `QuotaCell` (`quota.QuotaCell`) rather than a set-charm-gen threshold row. Median
    occupancy over that key must stay at or under `cellOccupancy.medianMax`, exactly the same
    ceiling shape `Distribution/CellOccupancy` already reports (max and singleton share alongside,
    never gating on their own).
    """

    id = "PassiveTree/CellOccupancy"
    family = "PassiveTree"
    loop = Loop.CLOSED
    gates = False
    needs = _NEEDS
    covers: "tuple[str, ...]" = ()

    def run(self, ctx: Ctx) -> "list[Finding]":
        plan_ctx: PassiveTreePlanCtx = ctx.passive_tree_plan
        cells_by_id: "dict[str, Any]" = {}
        for cells in plan_ctx.quota_cells_by_tree.values():
            cells_by_id.update(cells)
        if not cells_by_id:
            return [_not_measured(self.id, "(suite)", "no observed quota cells across the corpus")]
        if plan_ctx.targets is None:
            return [_not_measured(self.id, "(suite)", "cellOccupancy.medianMax threshold unavailable")]
        ceiling = plan_ctx.targets.cell_occupancy_median_max

        occupancy: "Counter[tuple[str, tuple[str, ...]]]" = Counter()
        for cell in cells_by_id.values():
            key = (cell.channel_family, tuple(sorted((cell.trigger, cell.element))))
            occupancy[key] += 1
        counts = sorted(occupancy.values())
        median = statistics.median(counts) if counts else 0.0
        maximum = max(counts) if counts else 0
        singletons = sum(1 for c in counts if c == 1)
        singleton_share_permille = (singletons * 1000) // len(counts) if counts else 0
        severity = Severity.NOTE if (counts and median <= ceiling) else Severity.GAP

        return [Finding(
            metric=self.id, severity=severity, subject="node:channelFamily+trigger+element",
            message=f"{len(cells_by_id)} nodes over {len(counts)} cells: median {median:g} "
                    f"(threshold <= {ceiling}), max {maximum}, singletons "
                    f"{singletons}/{len(counts) or 0} ({singleton_share_permille}‰)",
            evidence={"cells": len(counts), "population": len(cells_by_id), "median": median,
                     "max": maximum, "singletons": singletons,
                     "singletonSharePermille": singleton_share_permille, "medianMax": ceiling},
            assertion=f"median cell occupancy over (channelFamily, sorted trigger+element "
                      f"multiset) is at most {ceiling}",
            remedy="tree-language quota targets: this cell key is too fine for the corpus size, "
                   "or the corpus needs to grow before this cut is meaningful",
        )]


class ExclusionRateMetric(Metric):
    """§7 gate 18 — exclusion count / node count against `exclusionRate.maxSharePermille`, the form
    split across all four values reported beside it, plus every per-node D14/D40 requirement
    `nodegen.exclusion.validate_exclusion` already enforces at generation time — re-run here corpus-
    wide, never re-implemented (a `propertyKeys` entry naming a node id, a `none` form carrying
    keys, a non-`none` form carrying none). A `nullification` (or any non-`none` form) additionally
    has its `printedText` recomputed from its own `(form, propertyKeys)` via
    `exclusion.compose_printed_text` and compared byte-for-byte against what the corpus holds — the
    same "recompute rather than trust a stored value" discipline `QuotaDrift` uses, applied to the
    one field §2's own table says is template-composed, never asked of the model.

    **The corpus-side half (2026-09-11, the audit's C todo).** When the re-derived quota (the SAME
    two-stage `quota_for_plan` the generation CLI calls — `exclusionForm` now allocates `none` to
    ~98% of cells, with the 450/450/100 rung weights split over the ~2% designated subset) names a
    node's cell `none` while the COMMITTED record carries a non-`none` form, that is not a style
    note: it is a record whose exclusion was authored outside its own cell's allocation — the
    `tree-language/2` vintage measured 1638/1677 (97.7%) against a target of ≤30‰, with
    `QuotaDrift` blind to it (emitted and re-derived cells carried the same over-allocation,
    tautologically equal). Reported per node as a GAP naming both forms, never silently tolerated.

    **The cross-node half of D40/§5.2 rule 1 ("both sides name the same winner") is deliberately
    NOT re-checked here** — `nodegen.exclusion`'s own docstring already states why: there is no
    second node's response to compare against today, and the corpus-wide PAIRING census is
    `tree-review`'s job (spec-tree-review.md §6.4 rule 2), not this stage's. What this metric CAN
    and does check — that the printed text is a pure, reproducible function of this node's own
    claim — is the half that is actually its to check.
    """

    id = "PassiveTree/ExclusionRate"
    family = "PassiveTree"
    loop = Loop.CLOSED
    gates = False
    needs = _NEEDS
    covers: "tuple[str, ...]" = ()

    def run(self, ctx: Ctx) -> "list[Finding]":
        plan_ctx: PassiveTreePlanCtx = ctx.passive_tree_plan
        if not plan_ctx.nodes_by_tree or plan_ctx.targets is None:
            return [_not_measured(self.id, "(suite)", "no emitted nodes/targets supplied")]

        plan_by_id = {p.tree_id: p for p in plan_ctx.tree_plans}
        max_share = plan_ctx.targets.exclusion_rate_max_share_permille
        findings: "list[Finding]" = []
        total = 0
        by_form: "Counter[str]" = Counter()
        # C (2026-09-11): per-tree form mismatches between the re-derived cell and the corpus row.
        assignment_findings: "list[Finding]" = []

        for tree_id, nodes in plan_ctx.nodes_by_tree.items():
            plan = plan_by_id.get(tree_id)
            vocab = plan.property_vocabulary if plan is not None else {}
            # C (2026-09-11): the cells the CURRENT two-stage quota walk assigns this tree — the
            # same source `QuotaDrift` reads. Persisted cells (a regenerated corpus) overlay the
            # re-derivation upstream, so this is the assignment of record either way.
            rederived = plan_ctx.quota_cells_by_tree.get(tree_id) or {}
            for node in nodes:
                total += 1
                node_id = node.get("id", "?")
                exclusion = node.get("exclusion") or {}
                form = str(exclusion.get("form", nodegen_exclusion.NONE_FORM))
                keys = tuple(exclusion.get("propertyKeys") or ())
                by_form[form] += 1

                claim = nodegen_exclusion.ExclusionClaim(form=form, property_keys=keys)
                for defect in nodegen_exclusion.validate_exclusion(claim, vocab):
                    findings.append(Finding(
                        metric=self.id, severity=Severity.GAP, subject=node_id,
                        message=f"{node_id}: {defect}",
                        evidence={"code": "ExclusionFormDefect", "treeId": tree_id}))

                # C (2026-09-11): the corpus-side half of A2 - the node's COMMITTED form against
                # the cell the current quota assigns it. A mismatch is exactly a generation-vintage
                # row (authored before the two-stage apportionment) or an out-of-cell authorship;
                # both are defects this metric now names instead of leaving QuotaDrift's
                # tautology to hide them.
                cell = rederived.get(node_id)
                if cell is not None and form != cell.exclusion_form:
                    assignment_findings.append(Finding(
                        metric=self.id, severity=Severity.GAP, subject=node_id,
                        message=f"{node_id}: corpus holds form {form!r} but the cell the current "
                                f"quota assigns is {cell.exclusion_form!r} - a generation-vintage "
                                f"row or an out-of-cell authorship; regenerate via "
                                f"`trees generate --supersede`",
                        evidence={"code": "ExclusionOutsideCell", "treeId": tree_id,
                                  "corpusForm": form, "assignedForm": cell.exclusion_form}))

                if form != nodegen_exclusion.NONE_FORM:
                    expected_text = nodegen_exclusion.compose_printed_text(form, keys, role="loser")
                    actual_text = exclusion.get("printedText", "")
                    if not actual_text:
                        findings.append(Finding(
                            metric=self.id, severity=Severity.GAP, subject=node_id,
                            message=f"{node_id}: form {form!r} carries an empty printedText — "
                                    f"D40/§5.2 requires the rule to print",
                            evidence={"code": "MissingPrintedText", "treeId": tree_id}))
                    elif actual_text != expected_text:
                        findings.append(Finding(
                            metric=self.id, severity=Severity.GAP, subject=node_id,
                            message=f"{node_id}: printedText does not match the template "
                                    f"recomputed from its own (form, propertyKeys) — expected "
                                    f"{expected_text!r}, corpus holds {actual_text!r}",
                            evidence={"code": "PrintedTextDrift", "treeId": tree_id}))

        if total == 0:
            return [_not_measured(self.id, "(suite)", "no nodes")]

        excluded = total - by_form.get(nodegen_exclusion.NONE_FORM, 0)
        share_permille = (excluded * 1000) // total
        severity = Severity.NOTE if share_permille <= max_share else Severity.GAP
        findings.append(Finding(
            metric=self.id, severity=severity, subject="(suite)",
            message=f"{excluded}/{total} nodes carry an exclusion ({share_permille}‰), target <= "
                    f"{max_share}‰; form split {dict(sorted(by_form.items()))}"
                    + (f"; {len(assignment_findings)} node(s) outside their cell's allocation"
                       if assignment_findings else ""),
            evidence={"excluded": excluded, "total": total, "sharePermille": share_permille,
                     "byForm": dict(by_form), "maxSharePermille": max_share,
                     "outsideCell": len(assignment_findings)}))
        return findings


class ExclusionResolvableMetric(Metric):
    """§7 gate 19 — blocked on other work, tracked not open (spec-tree-language.md's own "Blocked
    on other work" note, restated verbatim): **the atom-tag registry (§5.1)** does not exist yet, so
    an exclusion predicate keys on `posture` and nothing else, and this gate reports `NOT_MEASURED`
    — never a false pass, and never a crash — for as long as `PassiveTreePlanCtx.atom_tag_registry`
    is `None`, which is its only real value today. Cited by name (never by ordinal) in both this
    docstring and every `NOT_MEASURED` finding this metric emits, per R8.

    The real check, wired the moment a caller supplies a real registry: every `propertyKeys` entry
    against the plan's own `propertyVocabulary` (already gate 19's per-response half,
    `exclusion.validate_exclusion`, re-run corpus-wide by `ExclusionRate` above) PLUS a genuine
    per-key membership check against the registry itself — `EligibilityRule.Validate`'s own
    pool-satisfiability question, which needs real per-affix atom tags to ask at all.
    """

    id = "PassiveTree/ExclusionResolvable"
    family = "PassiveTree"
    loop = Loop.CLOSED
    gates = False
    needs = _NEEDS
    covers: "tuple[str, ...]" = ()

    def run(self, ctx: Ctx) -> "list[Finding]":
        plan_ctx: PassiveTreePlanCtx = ctx.passive_tree_plan
        if plan_ctx.atom_tag_registry is None:
            return [_not_measured(
                self.id, "(suite)",
                "blocked on the atom-tag registry (spec-tree-language.md §5.1) — until it lands, "
                "an exclusion predicate keys on posture and nothing else, and this gate cannot "
                "resolve one against a per-affix atom-tag pool",
                code="AtomTagRegistryUnbuilt")]

        registry = plan_ctx.atom_tag_registry
        plan_by_id = {p.tree_id: p for p in plan_ctx.tree_plans}
        findings: "list[Finding]" = []
        for tree_id, nodes in plan_ctx.nodes_by_tree.items():
            if tree_id not in plan_by_id:
                continue
            for node in nodes:
                node_id = node.get("id", "?")
                exclusion = node.get("exclusion") or {}
                for key in tuple(exclusion.get("propertyKeys") or ()):
                    if key not in registry:
                        findings.append(Finding(
                            metric=self.id, severity=Severity.GAP, subject=node_id,
                            message=f"{node_id}: propertyKeys entry {key!r} is not in the "
                                    f"atom-tag registry",
                            evidence={"code": "UnknownPropertyKey", "treeId": tree_id}))
        return findings


def presentation_defects(node_id: str, form: str, property_keys: "tuple[str, ...]",
                         printed_text: str) -> "list[str]":
    """§6.4 rule 2's own three-part presentation contract for a non-`none` exclusion, minus the
    one-third `nodegen.exclusion`'s own docstring already proves holds BY CONSTRUCTION rather than
    by a runtime check: "both name the same winner" is guaranteed the moment `printedText` equals
    `compose_printed_text(form, property_keys, role="loser")`, since that function is pure in its
    three arguments — any two calls with the same `(form, property_keys)` produce the identical
    winner text, so there is no second node's data to compare against and nothing further to check
    for that third. What remains checkable, and is checked here: (a) the rule actually prints
    (non-empty `printedText`) and (b) what prints is the REAL template output, not drifted text —
    together, "both sides print the rule, and name the same winner" (rule 1). Rule 2 itself ("the
    surface renders the node INERT, not un-unlocked") is a RESOLVE-TIME/render-TIME property with
    no seed-content shape to check here — it is `TreeResolveReport.IsInert`
    (`ExclusionResolver.cs:60`, `node.ExclusionForm == ExclusionForm.Nullification`), already real,
    already computed, and already covered by its own C# tests; a Python seedsmith metric over
    static seed content has no data to re-check a resolve-time computation with, and does not
    pretend to.

    Deliberately the SAME two checks `PassiveTree/ExclusionRate` already makes per node (never
    re-implemented, only called from a second place) — §6.4's own table splits "how many exist"
    (reports, never gates) from "whether each one is presentable" (gates) as two DIFFERENT
    consumers of the identical underlying fact, not two different facts.
    """
    defects: "list[str]" = []
    expected = nodegen_exclusion.compose_printed_text(form, property_keys, role="loser")
    if not printed_text:
        defects.append(f"{node_id}: form {form!r} carries an empty printedText — D40/§5.2 rule 1 "
                       f"requires the rule to print")
    elif printed_text != expected:
        defects.append(f"{node_id}: printedText does not match the template recomputed from its "
                       f"own (form, propertyKeys) — expected {expected!r}, corpus holds "
                       f"{printed_text!r}")
    return defects


class ExclusionPresentationMetric(Metric):
    """§6.4 rule 2 — the ONE presentation-shaped condition among the nine unshippable conditions
    that GATES (unlike `PassiveTree/ExclusionRate`'s own rate, which only reports): "An exclusion
    fails its presentation contract... a hard finding, and it denies the lot a pass." D40's own
    three requirements (§5.2), split: rule 1 ("both sides print the rule, and name the same
    winner") is this metric's real, checkable job — `presentation_defects` above; rule 3 ("keys on
    a property, never a node id") is `PassiveTree/ExclusionResolvable`'s/`ExclusionRate`'s own
    per-response legality check, not repeated here; rule 2 ("rendered INERT, never un-unlocked") is
    a resolve-time C# fact (`TreeResolveReport.IsInert`) this Python-side metric has no seed data to
    re-derive and does not claim to gate on.

    A `none`-form node is never a member of this metric's own population at all — "none" means no
    conflict, so there is nothing to present (mirrors `validate_exclusion`'s identical reading).
    """

    id = "PassiveTree/ExclusionPresentation"
    family = "PassiveTree"
    loop = Loop.CLOSED
    gates = True
    needs = _NEEDS
    covers: "tuple[str, ...]" = ()

    def run(self, ctx: Ctx) -> "list[Finding]":
        plan_ctx: PassiveTreePlanCtx = ctx.passive_tree_plan
        if not plan_ctx.nodes_by_tree:
            return [_not_measured(self.id, "(suite)", "no emitted nodes supplied")]

        findings: "list[Finding]" = []
        checked = 0
        for tree_id, nodes in plan_ctx.nodes_by_tree.items():
            for node in nodes:
                node_id = node.get("id", "?")
                exclusion = node.get("exclusion") or {}
                form = str(exclusion.get("form", nodegen_exclusion.NONE_FORM))
                if form == nodegen_exclusion.NONE_FORM:
                    continue
                checked += 1
                keys = tuple(exclusion.get("propertyKeys") or ())
                printed_text = str(exclusion.get("printedText", ""))
                for defect in presentation_defects(node_id, form, keys, printed_text):
                    findings.append(Finding(
                        metric=self.id, severity=Severity.GAP, subject=node_id,
                        message=defect,
                        evidence={"code": "ExclusionPresentationDefect", "treeId": tree_id,
                                 "form": form}))

        if checked == 0:
            findings.append(Finding(
                metric=self.id, severity=Severity.NOTE, subject="(suite)",
                message="no non-'none' exclusion in this corpus — nothing to present",
                evidence={"presentableCount": 0}))
        elif not findings:
            findings.append(Finding(
                metric=self.id, severity=Severity.NOTE, subject="(suite)",
                message=f"{checked} exclusion(s) all present their rule correctly",
                evidence={"presentableCount": checked}))
        return findings


class NearDuplicateMetric(Metric):
    """§7 gate 20 — LOCAL EXACT Jaccard (`nodegen.dedup.exact_jaccard_permille`), deliberately
    **never** the shared `SemanticDedup/NearDuplicate` MinHash estimate: `nodegen/dedup.py`'s own
    docstring measured the MinHash over-report directly ('Tier Duration'/'Husk of the Murmuration':
    true 0.120, MinHash 0.844) — gating on a signal that inflates by up to 7x fails a run for the
    wrong reason. At this program's own eventual ceiling (1,560 nodes), direct O(n^2) exact-shingle
    comparison is cheap — the same tradeoff `metrics/dedup.py`'s own prose-near-duplicate check
    already makes at a similarly bounded, low-thousands scope, rather than pay LSH's recall loss
    for a corpus size that never needed it.
    """

    id = "PassiveTree/NearDuplicate"
    family = "PassiveTree"
    loop = Loop.CLOSED
    gates = False
    needs = _NEEDS
    covers: "tuple[str, ...]" = ()

    #: `nodegen.dedup.tier_report`'s own default rung, reused verbatim rather than a second,
    #: uncalibrated threshold invented for the corpus-wide scope.
    THRESHOLD_PERMILLE = 600

    def run(self, ctx: Ctx) -> "list[Finding]":
        plan_ctx: PassiveTreePlanCtx = ctx.passive_tree_plan
        if not plan_ctx.nodes_by_tree or plan_ctx.targets is None:
            return [_not_measured(self.id, "(suite)", "no emitted nodes/targets supplied")]

        names: "dict[str, str]" = {}
        for nodes in plan_ctx.nodes_by_tree.values():
            for node in nodes:
                node_id, name = node.get("id"), node.get("name")
                if node_id and name:
                    names[node_id] = name
        total = len(names)
        if total == 0:
            return [_not_measured(self.id, "(suite)", "no named nodes")]

        ids = sorted(names)
        near_pairs: "list[tuple[str, str, int]]" = []
        involved: "set[str]" = set()
        for i in range(len(ids)):
            for j in range(i + 1, len(ids)):
                a, b = ids[i], ids[j]
                if names[a].strip().lower() == names[b].strip().lower():
                    continue  # exact duplicates are NameCollision's own job, never double-reported
                score = nodegen_dedup.exact_jaccard_permille(names[a], names[b])
                if score >= self.THRESHOLD_PERMILLE:
                    near_pairs.append((a, b, score))
                    involved.add(a)
                    involved.add(b)

        max_share = plan_ctx.targets.near_duplicate_rate_max_share_permille
        share_permille = (len(involved) * 1000) // total
        findings = [
            Finding(
                metric=self.id, severity=Severity.NOTE, subject=f"{a}~{b}",
                message=f"'{names[a]}' and '{names[b]}' are near-duplicate names (exact Jaccard "
                        f"{score / 1000:.3f})",
                evidence={"jaccardPermille": score, "names": [names[a], names[b]]})
            for a, b, score in near_pairs
        ]
        severity = Severity.NOTE if share_permille <= max_share else Severity.GAP
        findings.append(Finding(
            metric=self.id, severity=severity, subject="(suite)",
            message=f"{len(involved)}/{total} nodes ({share_permille}‰) sit in a near-duplicate "
                    f"name pair, target <= {max_share}‰",
            evidence={"involved": len(involved), "total": total, "sharePermille": share_permille,
                     "maxSharePermille": max_share, "pairCount": len(near_pairs)}))
        return findings


class NameCollisionMetric(Metric):
    """§7 gate 21 — reuses `workflow.validators.field_echo.name_collision` verbatim, never a second
    exact-name-collision implementation. This is the exact shape of the measured historical defect:
    **83 of 83** generated commander effects were named identically to their own creature, caught only
    once a CORPUS-WIDE check compared a draft's name against every OTHER subject's committed name —
    no per-item check could ever have seen it (`field_echo.py:69-94`'s own docstring). This metric
    is the tree-corpus application of that same primitive: a node's name colliding with any OTHER
    node's name, anywhere in the corpus, not only within its own tree.

    Implementation note: `name_collision`'s own contract takes the caller's already-assembled
    `takenNames` list — calling it once per node against the FULL name-count table (rather than
    building an O(n) "every other name" list per node) keeps this metric linear rather than
    quadratic at corpus scale, while still routing every actual collision decision through the
    shared function rather than a parallel `==` check.
    """

    id = "PassiveTree/NameCollision"
    family = "PassiveTree"
    loop = Loop.CLOSED
    gates = False
    needs = _NEEDS
    covers: "tuple[str, ...]" = ("appendix-a:16",)

    def run(self, ctx: Ctx) -> "list[Finding]":
        plan_ctx: PassiveTreePlanCtx = ctx.passive_tree_plan
        if not plan_ctx.nodes_by_tree:
            return [_not_measured(self.id, "(suite)", "no emitted nodes supplied")]

        entries: "list[tuple[str, str]]" = []  # (nodeId, name)
        for nodes in plan_ctx.nodes_by_tree.values():
            for node in nodes:
                name = str(node.get("name") or "").strip()
                if name:
                    entries.append((str(node.get("id", "?")), name))
        if not entries:
            return [_not_measured(self.id, "(suite)", "no named nodes")]

        name_counts = Counter(name for _, name in entries)
        findings: "list[Finding]" = []
        collided = 0
        for node_id, name in entries:
            if name_counts[name] <= 1:
                continue
            collided += 1
            for problem in name_collision({"name": name}, {"takenNames": [name]}):
                findings.append(Finding(
                    metric=self.id, severity=Severity.GAP, subject=node_id,
                    message=f"{node_id}: {problem}",
                    evidence={"code": "NameCollision", "name": name,
                             "collisionCount": name_counts[name]}))

        total = len(entries)
        share_permille = (collided * 1000) // total if total else 0
        findings.append(Finding(
            metric=self.id, severity=Severity.NOTE if collided == 0 else Severity.GAP,
            subject="(suite)",
            message=f"{collided}/{total} nodes ({share_permille}‰) share a name with another node "
                    f"in the corpus",
            evidence={"collided": collided, "total": total, "sharePermille": share_permille}))
        return findings


class UnresolvedCountMetric(Metric):
    """§7 gate 22 / §7.1 — **the one metric in this family promoted to `gates=True`**, mirroring
    `creature_roster.py:353-370`'s own `CreatureRoster/UnresolvedCount` promotion and its exact reasoning,
    transferred rather than re-argued: there, an unresolved `aptitudePrimary` was not merely a
    description-quality signal — `SpeciesExpander.Expand` had no edge to derive a magnitude from,
    so an unresolved species was silently generated with ZERO stats. The same shape holds here: an
    `affixIds` vote that never resolves (`nodegen/run.py`'s `generate_node`, `vote.confidence ==
    "unresolved"`) produces a `NodeOutcome` with no `record` at all — the node is silently ABSENT
    from `gk-data/packs/fusion/data/seed/passive-tree/nodes/<treeId>.json` rather than present with a broken effect,
    which `tree-binder` has nothing to price and the tree ends up with a hole nobody flagged.
    Gating the RATE stops a run early — before the remaining thousands of calls — the moment a node
    class's brief has become systematically too ambiguous for its one voted field to converge,
    rather than discovering the hole tree-by-tree after the corpus is already spent.

    Every other `PassiveTree/*` metric starts `gates=False` and stays there until a deliberate,
    later, separate promotion (`metrics/model.py`'s own rule) — this is the one gate §7.1 promotes
    up front, and `assert_exactly_one_hard_gate(registry, "PassiveTree")` is what proves it is the
    ONLY one once every metric in this file is registered together.

    **J5 addition (spec-species-tree.md §3.1/§4):** a species the not-yet-built favour-lock stage
    could not resolve to any of its three offered cells is the SAME shape of hole — silently absent
    from a decision that must be made, not merely absent from prose — so it gates under this SAME
    class as a second, independent `subject="mechanicalFavour"` population (`species_favour_
    outcomes`), rather than a second `gates=True` class, which `assert_exactly_one_hard_gate` would
    refuse. Reported only when a caller actually supplies it; every pre-J5 site is unaffected.
    """

    id = "PassiveTree/UnresolvedCount"
    family = "PassiveTree"
    loop = Loop.CLOSED
    gates = True
    needs = _NEEDS
    covers: "tuple[str, ...]" = ()

    def run(self, ctx: Ctx) -> "list[Finding]":
        plan_ctx: PassiveTreePlanCtx = ctx.passive_tree_plan
        findings: "list[Finding]" = []

        if not plan_ctx.outcomes_by_tree or plan_ctx.targets is None:
            findings.append(_not_measured(self.id, "affixIds", "no run outcomes/targets supplied"))
        else:
            max_share = plan_ctx.targets.unresolved_count_max_share_permille
            total = 0
            unresolved = 0
            for outcomes in plan_ctx.outcomes_by_tree.values():
                for outcome in outcomes:
                    total += 1
                    if outcome.get("outcome") == "unresolved":
                        unresolved += 1
            if total == 0:
                findings.append(_not_measured(self.id, "affixIds", "no subjects"))
            else:
                share_permille = (unresolved * 1000) // total
                severity = Severity.NOTE if share_permille <= max_share else Severity.GAP
                findings.append(Finding(
                    metric=self.id, severity=severity, subject="affixIds",
                    message=f"affixIds: {unresolved}/{total} unresolved ({share_permille}‰), target "
                            f"<= {max_share}‰",
                    evidence={"unresolved": unresolved, "total": total,
                             "sharePermille": share_permille, "maxSharePermille": max_share},
                    remedy="tree-language brief: strengthen this node class's affix-legality "
                           "description, or its motif contrast, if unresolved votes concentrate "
                           "there"))

        # J5 addition (spec-species-tree.md §3.1/§4): a SECOND, independent population under the
        # SAME gate -- a species the not-yet-built stage could not resolve to one of its three
        # offered favours. Reported/gated only when a caller actually supplies
        # `species_favour_outcomes`; every pre-J5 construction site (every existing test above)
        # omits it and gets EXACTLY the single `affixIds` finding it always has, proven by test.
        if plan_ctx.species_favour_outcomes:
            if plan_ctx.targets is None:
                findings.append(_not_measured(
                    self.id, "mechanicalFavour", "no targets supplied — no threshold to gate against"))
            else:
                max_share = plan_ctx.targets.unresolved_count_max_share_permille
                species_total = len(plan_ctx.species_favour_outcomes)
                species_unresolved = sum(
                    1 for o in plan_ctx.species_favour_outcomes if o.get("outcome") == "unresolved")
                share_permille = (species_unresolved * 1000) // species_total
                severity = Severity.NOTE if share_permille <= max_share else Severity.GAP
                findings.append(Finding(
                    metric=self.id, severity=severity, subject="mechanicalFavour",
                    message=f"mechanicalFavour: {species_unresolved}/{species_total} species "
                            f"unresolved ({share_permille}‰), target <= {max_share}‰",
                    evidence={"unresolved": species_unresolved, "total": species_total,
                             "sharePermille": share_permille, "maxSharePermille": max_share},
                    remedy="species-tree: a species the stage could not resolve to any of its three "
                           "offered favours — review its brief/lore, never silently default it"))
        return findings


#: Registration order matches §7's own gate order (15-22) — `UnresolvedCount` last, the same
#: "CLOSED first... gates=True last" reading order `ALL_CREATURE_ROSTER_METRICS` already uses.
#: ⚠ Deliberately NOT extended with H5's two new metrics below — this tuple is H4's own eight
#: (spec-tree-language.md §7 gates 15-22), and `test_passive_tree_metrics.py`'s
#: `AllPassiveTreeMetricsRegistrationTests` already asserts its exact length against that count
#: (`len(registry.all()) == 9` once `TreeEqualValueMetric` joins it). `DeepMechanismValueMetric` and
#: `HiddenFileCountMetric` are `tree-review`'s own family (H5, spec-tree-review.md §4.2/§7) and are
#: registered by whatever caller wants them, the same way `TreeEqualValueMetric` itself always was
#: — a metric class does not need to sit in this tuple to be a real, registrable `PassiveTree/*`
#: metric; the tuple is a convenience grouping for H4's own callers, not the family's registry.
ALL_PASSIVE_TREE_METRICS: "tuple[type[Metric], ...]" = (
    QuotaDriftMetric, MechanismRampMetric, CellOccupancyMetric, ExclusionRateMetric,
    ExclusionResolvableMetric, NearDuplicateMetric, NameCollisionMetric, UnresolvedCountMetric,
)
# ExclusionPresentationMetric (task J3, spec-tree-review.md §6.4 rule 2) is correctly NOT included
# here — a real, checked reason, not an oversight. This tuple feeds `report/cli.py`'s own
# generation-time registry, which `nodegen.verdict.assert_exactly_one_hard_gate` polices under a
# strict, doubly-tested `len(ids) != 1: raise` (§7.1: "exactly one gate is promoted to hard-fail
# FIRST" — already `PassiveTree/UnresolvedCount`, and multiple existing tests assert this stays
# exactly one). Registering a SECOND `gates=True` metric here would break real content generation's
# own `--write` path immediately (confirmed by reading `assert_exactly_one_hard_gate`'s own body
# before adding this, not assumed). §6.4's own "gates" is a REVIEW-TIME, already-generated-lot
# shippability verdict — a different concept from §7.1's generation-time spend gate, reusing the
# same word by analogy, not the same registry. `ExclusionPresentationMetric` belongs in J3's own
# review-verdict machinery (the "verdict queue"/nine-unshippable-conditions computation, not yet
# built) once it exists — this is a wiring gap tracked here, never an architectural wall
# (AGENTS.md's own rule), and never silently forcing a metric into a registry whose own invariant
# it would break.


# ---------------------------------------------------------------------------------------------
# Task H5 — the two remaining `tree-review` corpus metrics (spec-tree-review.md §4.1, §4.2, §7).
# `PassiveTree/TreeEqualValue`'s content-side half lives above, folded into C1's own registration.
# These two are genuinely new metric ids, both still under `needs = _NEEDS` (`passive_tree_plan`)
# per the same H4 discipline: a sibling need nothing else in this family would ever read grows this
# module's own `PassiveTreePlanCtx` rather than `metrics/model.py`'s `VALID_NEEDS`.
# ---------------------------------------------------------------------------------------------


class DeepMechanismValueMetric(Metric):
    """spec-tree-review.md §4.2 / §6.4's settled ruling (2026-09-05): the deep-tier behavioural
    sample REPORTS; it never gates. `MechanismRampMetric` above checks the plan's own LABEL
    (`nodeClass == "mechanism"` at the tier the archetype ramp names); this metric is the other
    half §4.2 names — does a mechanism node that deep actually DO anything, proxied by a
    `CombatSim` win-share delta over a sample. `gk-core/tools/CombatSim` is a C# tool this Python-side
    metric cannot run itself (a wiring gap in AGENTS.md's precise sense, not this task's own scope
    — stated here rather than papered over): this metric reads whatever samples a real sweep
    already produced (`deep_mechanism_samples`) and never derives a number from the plan or the
    corpus on its own, the same "compose real results, invent nothing" discipline every other
    CLOSED metric in this family already holds to.

    `gates = False` is not a threshold this metric merely happens to clear today — §4.2 states the
    reason once and this class exists to hold it structurally: "the score is a proxy for a proxy...
    and this module does not let an instrument that thin deny a lot a pass." A systemic
    below-threshold result still surfaces here as a GAP finding — it is not toothless, per §4.2's
    own "a systemic result... is a rung-3 or rung-4 trigger" — but `targets.GATING_METRICS` never
    names this metric id, and `RunReport.verdict` (`nodegen/verdict.py`) only ever consults a
    metric's outcome when it is in that dict or is `PassiveTree/UnresolvedCount` by name; a metric
    absent from both structurally cannot flip a run's PASS/FAIL regardless of its own findings'
    severity (`the_deep_mechanism_value_metric_never_gates` proves both halves of this: the class
    attribute, and the registry-level consequence).
    """

    id = "PassiveTree/DeepMechanismValue"
    family = "PassiveTree"
    loop = Loop.CLOSED
    gates = False
    needs = _NEEDS
    covers: "tuple[str, ...]" = ()

    def run(self, ctx: Ctx) -> "list[Finding]":
        plan_ctx: PassiveTreePlanCtx = ctx.passive_tree_plan
        samples = plan_ctx.deep_mechanism_samples
        if not samples:
            return [_not_measured(
                self.id, "(suite)",
                "no deep-tier CombatSim win-share samples supplied — this metric proxies a real "
                "sweep (tools/CombatSim), it never invents one")]

        threshold = plan_ctx.deep_mechanism_value_min_win_share_delta_milli
        findings: "list[Finding]" = []
        weak = 0
        total = 0
        for tree_id, tree_samples in samples.items():
            for sample in tree_samples:
                delta = sample.get("winShareDeltaMilli")
                if delta is None:
                    continue
                total += 1
                node_id = sample.get("nodeId", "?")
                if threshold is not None and delta < threshold:
                    weak += 1
                    findings.append(Finding(
                        metric=self.id, severity=Severity.GAP, subject=f"{tree_id}:{node_id}",
                        message=f"{tree_id}:{node_id}: CombatSim win-share delta {delta}‰ is below "
                                f"the reporting threshold {threshold}‰ — this deep-tier mechanism "
                                f"node is measurably inert in the sampled sweep",
                        evidence={"winShareDeltaMilli": delta, "thresholdMilli": threshold},
                        remedy="tree-plan/tree-language: a SYSTEMIC result across a quota cell is a "
                               "rung-3/4 trigger (spec-tree-review.md §6.2) — this finding never "
                               "denies this lot a pass on its own (§4.2)"))
        findings.append(Finding(
            metric=self.id, severity=Severity.NOTE, subject="(suite)",
            message=f"{weak}/{total} sampled deep-tier mechanism node(s) scored below the "
                    f"reporting threshold — reported only, per §4.2 this metric never gates",
            evidence={"weak": weak, "total": total, "thresholdMilli": threshold}))
        return findings


def _entries(path: "Path") -> "list[Any]":
    """Every record a `_`-prefixed seed file holds, regardless of whether it is authored as a bare
    list, an id-keyed map (the real historical `_needs-review.json` shape:
    `{"SnorkleZombie": {...}}`, spec-tree-review.md §7), or a single bare record with no wrapper at
    all. A list is every element; a dict whose every value is itself a dict is read as an id-keyed
    map (one entry per key); any other dict is one bare record. An empty file (`{}`/`[]`/whitespace)
    is zero entries, never an error — an empty `_`-prefixed file is a legal note or exemplar
    (`an_empty_underscore_file_is_not_a_finding`, spec-tree-review.md's own Testing table)."""
    try:
        text = path.read_text(encoding="utf-8").strip()
    except OSError:
        return []
    if not text:
        return []
    data = json.loads(text)
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        if not data:
            return []
        if all(isinstance(v, dict) for v in data.values()):
            return list(data.values())
        return [data]
    return [data]


class HiddenFileCountMetric(Metric):
    """Every `_`-prefixed file under a seed root, counted WITHOUT the skip that hides it
    (spec-tree-review.md §7).

    `CreatureQualityReport/Program.cs:77` skips `_`-prefixed files — a convention borrowed from
    `AtomImporter` that silently became a hole: one stale `SnorkleZombie` duplicate survived inside
    `zombie/_needs-review.json` while the tool reported "840 indexed — clean." A gate with an
    exclusion rule has a blind spot the size of that rule, so this metric is defined by NOT having
    one: it walks every `_*.json` file this program's own seed roots hold, `_index.json` excepted
    (§7's one named legitimate exception — an id-keyed manifest, not a parking bucket).

    Reports `visitedFileCount` on every run, always, as its own NOTE finding — a green result that
    visited zero files and a green result that visited forty empty files are the same *absence of a
    GAP* and completely different facts, and the whole point of this field is to keep the two
    distinguishable (spec-tree-review.md's own Success criteria: "a green can never mean the walk
    looked at nothing")."""

    id = "PassiveTree/HiddenFileCount"
    family = "PassiveTree"
    loop = Loop.CLOSED
    gates = False
    needs = _NEEDS
    covers: "tuple[str, ...]" = ()

    def run(self, ctx: Ctx) -> "list[Finding]":
        plan_ctx: PassiveTreePlanCtx = ctx.passive_tree_plan
        roots = plan_ctx.tree_seed_roots
        findings: "list[Finding]" = []
        visited = 0
        for root in roots:
            if not root.is_dir():
                continue
            for path in sorted(root.rglob("_*.json")):
                if path.name == "_index.json":
                    continue
                visited += 1
                count = len(_entries(path))
                if count == 0:
                    continue
                findings.append(Finding(
                    metric=self.id, severity=Severity.GAP, subject=str(path),
                    message=f"{count} entr{'y' if count == 1 else 'ies'} parked in a `_`-prefixed "
                            f"file — invisible to every tool that skips them",
                    evidence={"path": str(path), "entryCount": count},
                    remedy="tree-review: adjudicate and move, or delete; never leave it parked"))
        # A green with visitedFileCount == 0 means the walk found nothing to look at — a different
        # thing from "the files are empty," and the one this metric exists to distinguish.
        findings.append(Finding(
            metric=self.id, severity=Severity.NOTE, subject="(corpus)",
            message=f"walked {visited} `_`-prefixed file(s) across {len(roots)} seed root(s)",
            evidence={"visitedFileCount": visited, "rootCount": len(roots)}))
        return findings


# ---------------------------------------------------------------------------------------------
# Task J5 (spec-species-tree.md §3.1 step 4, §3.2/D32) -- the favour-lock drift gate. Same
# registration posture as H5's own two metrics above: a real, registrable `PassiveTree/*` metric,
# deliberately NOT added to `ALL_PASSIVE_TREE_METRICS` (that tuple is H4's own eight, frozen by a
# test asserting its exact length) -- registered by whatever caller wants it instead.
# ---------------------------------------------------------------------------------------------


class FavourDriftMetric(Metric):
    """spec-species-tree.md §3.1 step 4 / §3.2 (D32) — **re-derives each favour axis's own per-mille
    TARGET share independently**, via `species.plan.axis_weight_tables` (never a stored "declared"
    distribution — the same "recompute the target fresh, never trust a passed-in one" discipline
    `QuotaDriftMetric` already applies above), and compares it against the EMITTED corpus's own
    OBSERVED share. Symmetric, per D32's own wording and the todo's own acceptance bullet: an axis
    member running *over* its target is exactly as much a drift as one running under it — an
    injected skew and an injected overshoot are both real findings, never just the shortfall side.

    `gates = False`, for the exact reason `DeepMechanismValueMetric` above states for itself and
    `favour_drift_tolerance_share_permille`'s own docstring restates: no real species-corpus
    generation run exists yet to calibrate a tolerance against (§5.1's shipped posture — promote one
    gate at a time, only after a real run has been measured). A missing tolerance never turns this
    metric silent: every axis member's drift is still reported as a NOTE; only the GAP escalation
    is withheld until a caller supplies a real number (mirrors `DeepMechanismValueMetric`'s own
    `if threshold is not None and delta < threshold` shape exactly).
    """

    id = "PassiveTree/FavourDrift"
    family = "PassiveTree"
    loop = Loop.CLOSED
    gates = False
    needs = _NEEDS
    covers: "tuple[str, ...]" = ()

    def run(self, ctx: Ctx) -> "list[Finding]":
        plan_ctx: PassiveTreePlanCtx = ctx.passive_tree_plan
        if plan_ctx.targets is None:
            return [_not_measured(self.id, "(suite)", "no targets supplied — nothing to re-derive "
                                  "the favour target against")]
        assignments = list(plan_ctx.species_favour_assignments)
        if not assignments:
            return [_not_measured(self.id, "(suite)", "no species_favour_assignments supplied — "
                                  "nothing to compare against the re-derived target")]

        try:
            axis_tables = species_plan.axis_weight_tables(plan_ctx.targets)
        except (ValueError, KeyError, OSError) as ex:
            return [_not_measured(self.id, "(suite)", f"could not re-derive the favour target: {ex}")]

        total = len(assignments)
        tolerance = plan_ctx.favour_drift_tolerance_share_permille
        findings: "list[Finding]" = []
        for axis in species_plan.AXES:
            table = axis_tables[axis]
            observed_counts = Counter(a[axis] for a in assignments if axis in a)
            for member in sorted(set(table) | set(observed_counts)):
                expected_share = table.get(member, 0)
                observed_count = observed_counts.get(member, 0)
                observed_share = (observed_count * 1000) // total
                drift = observed_share - expected_share
                subject = f"{axis}={member}"
                evidence = {"observedCount": observed_count, "totalSpecies": total,
                           "observedSharePermille": observed_share,
                           "expectedSharePermille": expected_share, "driftSharePermille": drift,
                           "toleranceSharePermille": tolerance}
                if tolerance is not None and abs(drift) > tolerance:
                    findings.append(Finding(
                        metric=self.id, severity=Severity.GAP, subject=subject,
                        message=f"{subject}: observed {observed_share}‰ of the corpus vs the "
                                f"re-derived target {expected_share}‰ (drift {drift:+d}‰, "
                                f"tolerance {tolerance}‰)",
                        evidence=evidence,
                        assertion=f"abs(observed - re-derived target) <= {tolerance}‰ for every "
                                  f"{axis} member",
                        remedy="species-tree: the emitted favour distribution has drifted from "
                               "D32's declared near-uniform target — a broken quota or an "
                               "unaccounted-for forced set, never a lore judgement"))
                else:
                    findings.append(Finding(
                        metric=self.id, severity=Severity.NOTE, subject=subject,
                        message=f"{subject}: observed {observed_share}‰ vs re-derived target "
                                f"{expected_share}‰ (drift {drift:+d}‰)",
                        evidence=evidence))
        return findings


# ---------------------------------------------------------------------------------------------
# Task J6 (spec-species-tree.md §5, §5.1, §5.3 rules 3-5) -- D23's "nodes no other tree has"
# promise, made checkable. Same registration posture as every other post-H4 metric in this file:
# real, registrable, deliberately NOT added to `ALL_PASSIVE_TREE_METRICS`.
# ---------------------------------------------------------------------------------------------


class SpeciesUniquenessMetric(Metric):
    """spec-species-tree.md §5 — three uniqueness strengths, ONE reverse index built over every
    committed tree's own nodes, walked once per run:

    - **U1** text uniqueness — a `(name, flavor)` pair appearing on more than one node, corpus-wide.
      Generation-time `name_collision`/the shipped dedup (`metrics/dedup.py`) already catch this
      INCREMENTALLY as each tree generates against `takenNames`; this is the closed-corpus,
      all-trees-committed re-verification a review pass runs once, not a duplicate of that check —
      the two run at different times over different populations (one tree growing vs. the whole
      corpus at rest) and either can catch what the other's timing misses.
    - **U2** composition uniqueness — a `(affixIds multiset, quotaCell)` fingerprint appearing in
      more than one TREE. Needs `quota_cells_by_tree` alongside `nodes_by_tree`, since a node's own
      committed seed record does not persist its `quotaCell` (H4's own documented wiring gap, still
      open — a tree with no supplied quota cells simply contributes nothing to this half of the
      index, never a crash).
    - **U3** namespace uniqueness — any `affix.species.<speciesId>.*` id referenced by a node whose
      OWN tree is not `speciesId` (a species tree's `tree_id` IS its `speciesId`, matching every
      other tree category's own tree_id-is-the-roster-id convention). The one strength that
      actually costs (§5.2) — 6,720 authored affixes at `speciesUniqueAffixMin=8` (D41) — so this
      is the one worth a corpus-wide leak check, not just a per-tree glance.

    `gates = False`: §5.1's own shipped posture — *"gates on none of them until the pilot calibrates
    the thresholds... promote one gate at a time, only after a real run has been measured"* — the
    identical reasoning `FavourDriftMetric`/`DeepMechanismValueMetric` above already carry. Never a
    second `gates=True` class; `assert_exactly_one_hard_gate` would refuse it.
    """

    id = "PassiveTree/SpeciesUniqueness"
    family = "PassiveTree"
    loop = Loop.CLOSED
    gates = False
    needs = _NEEDS
    covers: "tuple[str, ...]" = ()

    def run(self, ctx: Ctx) -> "list[Finding]":
        plan_ctx: PassiveTreePlanCtx = ctx.passive_tree_plan
        if not plan_ctx.nodes_by_tree:
            return [_not_measured(self.id, "(suite)",
                                  "no nodes_by_tree supplied — nothing to build a reverse index over")]

        findings: "list[Finding]" = []

        # U1 -- (name, flavor) reverse index, keyed corpus-wide over every committed node.
        text_index: "dict[tuple, set[str]]" = {}
        for tree_id, nodes in plan_ctx.nodes_by_tree.items():
            for node in nodes:
                key = (node.get("name"), node.get("flavor"))
                text_index.setdefault(key, set()).add(f"{tree_id}:{node.get('id')}")
        for (name, flavor), node_refs in text_index.items():
            if len(node_refs) > 1:
                findings.append(Finding(
                    metric=self.id, severity=Severity.GAP, subject=f"U1:{name}",
                    message=f"name/flavor pair repeats across {len(node_refs)} node(s): "
                            f"{sorted(node_refs)}",
                    evidence={"nodeRefs": sorted(node_refs), "name": name, "flavor": flavor},
                    remedy="tree-language: two nodes converged on the same sentence — reroll one, "
                           "the closed-corpus re-check generation-time dedup cannot run itself"))

        # U2 -- (affixIds, quotaCell) reverse index, corpus-wide over TREES (never over individual
        # nodes -- the promise is "no other TREE has this composition," not "no other node").
        composition_index: "dict[tuple, set[str]]" = {}
        for tree_id, nodes in plan_ctx.nodes_by_tree.items():
            cells = plan_ctx.quota_cells_by_tree.get(tree_id) or {}
            for node in nodes:
                cell = cells.get(node.get("id"))
                if cell is None:
                    continue  # no observed quota cell for this node -- contributes nothing, not a crash
                fingerprint = (tuple(sorted(node.get("affixIds") or ())),
                              tuple(cell.value_for(axis) for axis in nodegen_quota.AXES))
                composition_index.setdefault(fingerprint, set()).add(tree_id)
        for fingerprint, tree_ids in composition_index.items():
            if len(tree_ids) > 1:
                findings.append(Finding(
                    metric=self.id, severity=Severity.GAP, subject=f"U2:{fingerprint[0]}",
                    message=f"(affixIds, quotaCell) fingerprint repeats across {len(tree_ids)} "
                            f"tree(s): {sorted(tree_ids)}",
                    evidence={"treeIds": sorted(tree_ids), "affixIds": fingerprint[0],
                             "quotaCell": fingerprint[1]},
                    remedy="species-tree: two species trees converged on an identical node "
                           "composition — U2's own promise, broken"))

        # U3 -- affix.species.<speciesId>.* referenced from a tree that is not speciesId itself.
        namespace_index: "dict[str, set[str]]" = {}
        for tree_id, nodes in plan_ctx.nodes_by_tree.items():
            for node in nodes:
                for affix_id in (node.get("affixIds") or ()):
                    if isinstance(affix_id, str) and affix_id.startswith("affix.species."):
                        namespace_index.setdefault(affix_id, set()).add(tree_id)
        for affix_id, tree_ids in namespace_index.items():
            parts = affix_id.split(".")
            owner = parts[2] if len(parts) > 2 else None
            foreign = sorted(t for t in tree_ids if t != owner)
            if foreign:
                findings.append(Finding(
                    metric=self.id, severity=Severity.GAP, subject=f"U3:{affix_id}",
                    message=f"{affix_id} (namespace owner {owner!r}) is referenced from another "
                            f"tree: {foreign}",
                    evidence={"affixId": affix_id, "owner": owner, "foreignTreeIds": foreign},
                    remedy="species-tree: a species-namespace affix leaked into another tree's own "
                           "generation — U3's own promise, broken"))

        findings.append(Finding(
            metric=self.id, severity=Severity.NOTE, subject="(corpus)",
            message=f"reverse index built over {len(plan_ctx.nodes_by_tree)} tree(s), "
                    f"{sum(len(v) for v in plan_ctx.nodes_by_tree.values())} node(s)",
            evidence={"treeCount": len(plan_ctx.nodes_by_tree),
                     "nodeCount": sum(len(v) for v in plan_ctx.nodes_by_tree.values())}))
        return findings
