"""seedsmith.adapters.actions.coverage_assignment.derive -- A-S7's own pure core
(spec-coverage-assignment.md SS2, SS4). Zero model calls, zero I/O in the assignment algorithm
itself -- callers hand in already-loaded data, the same discipline `usage_direction.weights`
already established for FC3.

**Recomputed fresh every round, never a persisted cursor** (spec SS5) -- the round-robin walk
below takes the CURRENT usage snapshot and the round's own plan entries as plain arguments; nothing
here remembers state between calls, so a rerun with the same two inputs is byte-identical by
construction, not by careful bookkeeping.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from ..usage_direction.weights import latest_usage_report_path

__all__ = [
    "usage_counts_from_report", "load_current_usage", "sort_population_by_usage",
    "assign_required_families", "splice_payoff_enablers", "MissingForcedEnablerError",
]


class MissingForcedEnablerError(ValueError):
    """An `enabler`-role brief has no `pairing.forcedEnabler` -- a stale, pre-A-S1-extension plan
    (spec-coverage-assignment.md SS3). Refused by name, never silently treated as `role: none`."""


def usage_counts_from_report(report: Mapping[str, Any]) -> "dict[str, int]":
    """FC1's own `allTime.counts` plus every `allTime.neverUsed` family explicitly at 0 -- a
    never-used family must sort as a real zero, never be silently absent from the population this
    module ranks (mirrors `weights_from_usage_report`'s own `all_families = counts | neverUsed`
    union, but keeps the raw counts rather than converting to a weight)."""
    counts: "dict[str, int]" = dict(report["allTime"]["counts"])
    for family_id in report["allTime"]["neverUsed"]:
        counts.setdefault(family_id, 0)
    return counts


def load_current_usage(reports_dir: Path) -> "dict[str, int]":
    """The real, live FC1 report, read fresh -- never cached, never a fallback to a stale one.
    Returns an empty map (never an error) when no report exists yet, so a fresh checkout degrades
    to "every family equally due" (sort_population_by_usage's own 0-for-everyone case) rather than
    refusing to run."""
    report_path = latest_usage_report_path(reports_dir)
    if report_path is None:
        return {}
    import json
    return usage_counts_from_report(json.loads(report_path.read_text(encoding="utf-8")))


def sort_population_by_usage(family_ids: Iterable[str],
                             usage_counts: Mapping[str, int]) -> "list[str]":
    """Ascending `(usageCount, familyId)` -- least-used first, ties (every zero-usage family, most
    of them) broken by id so the order is deterministic and reproducible, never insertion-order or
    dict-iteration-order dependent."""
    return sorted(set(family_ids), key=lambda f: (usage_counts.get(f, 0), f))


def _pairing_required_family(entry: Mapping[str, Any]) -> "list[str] | None":
    """`None` means "not a pairing brief, fall through to round-robin" -- an empty list is never
    returned here; a pairing brief always names exactly one family once its role is decided."""
    pairing = entry.get("pairing") or {}
    role = pairing.get("role", "none")
    brief_id = entry.get("briefId") or entry.get("id") or "<unknown>"
    if role == "payoff":
        payoff_family = pairing.get("pairedPayoffFamily")
        if not payoff_family:
            raise ValueError(f"{brief_id}: role='payoff' but pairedPayoffFamily is missing -- refused")
        return [payoff_family]
    if role == "enabler":
        forced = pairing.get("forcedEnabler")
        if not forced:
            raise MissingForcedEnablerError(
                f"{brief_id}: role='enabler' has no pairing.forcedEnabler -- refused (a stale, "
                f"pre-A-S1-extension plan? see spec-coverage-assignment.md SS3)")
        return [forced]
    return None


def assign_required_families(
    plan_entries: Sequence[Mapping[str, Any]], *, usage_counts: Mapping[str, int],
    family_ids: Iterable[str], payoff_families: Iterable[str] = (),
) -> "dict[str, list[str]]":
    """The whole of A-S7's own SS2/SS4 contract, over one round's plan entries (already in their
    own deterministic emitted order -- `brief.{scope}.{scopeKey}.{ordinal:03d}`, never re-sorted
    here). Returns `{briefId: [] | [familyId]}`.

    A pairing-role brief's own family always wins (`_pairing_required_family`); every other brief
    draws the next member of a population sorted ascending by CURRENT usage, walked by ONE GLOBAL
    cursor over the whole round -- never reset per subject, which is what keeps this from repeating
    `distribution_planner`'s own already-found pairing monoculture (spreading assignments across
    subjects by construction, not by discipline).

    ⛔ **`payoff_families` are SKIPPED by the round-robin (2026-09-12 fix).** A payoff key is only
    coherent alongside one of its enablers (that is the whole point of `pairings.json`, and it is
    exactly what A-S5's `enablerPayoffCoverage` checks). The round-robin has no idea which families
    are paired, so before this fix it happily made a **`role: "none"`** brief require
    `atom.rot-punisher` while nothing in that anchor required `atom.rot-enabler` -- and for a
    **species**-scope anchor that is unfixable, because `assign_pairing_roles` only ever emits
    pairing briefs on family/general scope. Measured on the live plan: **74 anchors** carried a
    required payoff with no possible enabler, every one a guaranteed future `enablerPayoffCoverage`
    gap. Payoff keys stay covered through their own `role: "payoff"` briefs (456 of them), whose
    `_pairing_required_family` branch returns the key together with its enabler; excluding them from
    the round-robin loses no coverage and removes the impossible requirement.

    A candidate already in the brief's own `forbiddenAtomFamilies` is skipped -- splicing it in
    would add back exactly the family that brief's own pool was built to exclude (constraint 4's
    multiplicative-pair forbidding, `build_pool`). The cursor advances past it; if every remaining
    population member is forbidden for this one brief (not reachable with today's real 2-forbidden-
    family table against a 100-family population, never assumed away), that brief's own
    `requiredFamilies` is `[]` -- a real, reported skip, never a raise and never a silent all-none.
    """
    payoff = frozenset(payoff_families)
    eligible = [f for f in family_ids if f not in payoff]
    population = sort_population_by_usage(eligible, usage_counts)
    result: "dict[str, list[str]]" = {}
    cursor = 0
    pop_len = len(population)
    for entry in plan_entries:
        brief_id = entry.get("briefId") or entry.get("id")
        pairing_family = _pairing_required_family(entry)
        if pairing_family is not None:
            result[brief_id] = pairing_family
            continue

        forbidden = set((entry.get("pool") or {}).get("forbiddenAtomFamilies") or ())
        assigned: "str | None" = None
        for _ in range(pop_len):
            candidate = population[cursor % pop_len] if pop_len else None
            cursor += 1
            if candidate is None:
                break
            if candidate in forbidden:
                continue
            assigned = candidate
            break
        result[brief_id] = [assigned] if assigned is not None else []
    return result


def splice_payoff_enablers(
    atom_families: Iterable[str], *, pairing_table: "Mapping[str, Sequence[str]]",
    allowed_atom_families: Iterable[str],
) -> "list[str]":
    """**Deterministic enabler splice for a model-picked payoff key (2026-09-12 fix).**

    The A-S7 splice unions a brief's own `requiredFamilies` into the accepted `atomFamilies`, but the
    model is free to pick any family in `allowedAtomFamilies` -- including a **payoff key** that the
    plan never required. When that happens the accepted row carries a payoff whose enabler may never
    be accepted in the same anchor, which A-S5's `enablerPayoffCoverage` correctly reports as a gap.
    Measured on the live round-2000 corpus: `caltropnut` and `snowgatling` each accepted
    `atom.rot-punisher` (itself allowed, and picked freely by the model) with no accepted enabler in
    that anchor -- while their own pools DID allow four enablers, so the requirement was satisfiable
    and simply was not scheduled.

    This closes it at the same place and in the same spirit as the plan-side splice: a pure,
    deterministic, **zero-model-call** addition. For every payoff key present in `atom_families`,
    the first of its enablers (in the `pairings.json` value's own declared order) that is ALSO in
    this brief's `allowed_atom_families` is added to the result. An enabler already present is left
    alone; a payoff key with no allowed enabler (impossible for a well-formed plan, since the pool
    is built to contain both) adds nothing rather than inventing a family outside the brief's own
    contract.

    Returns the union, sorted -- the same shape and ordering discipline the existing splice uses.
    """
    present = set(atom_families)
    spliced = set(present)
    for family in sorted(present):
        enablers = pairing_table.get(family)
        if not enablers:
            continue
        if any(e in present for e in enablers):
            continue
        allowed = set(allowed_atom_families)
        for enabler in enablers:
            if enabler in allowed:
                spliced.add(enabler)
                break
    return sorted(spliced)
