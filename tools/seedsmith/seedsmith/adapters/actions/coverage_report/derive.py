"""seedsmith.adapters.actions.coverage_report.derive — spec-coverage-report.md §3's algorithm
(module A-S5). Pure derivation; the one file that touches disk is the sibling entrypoint
`../generate_coverage_report.py`, matching every `derive.py` in this adapter family.

**This module's one non-negotiable rule, restated as code rather than prose** (spec's own opening
line): every metric function below returns `Finding`s tagged with a `Loop` the caller
(`seedsmith/metrics/action_coverage.py`) constructs the `Metric.loop` class attribute from — ten
CLOSED, two OPEN — and `gates=False` on every one of them (promotion is a deliberate, later,
separate act, `metrics/model.py:8-9,:85`). This module never sets `gates=True` anywhere, and never
will: the `Loop.OPEN` + `gates=True` contradiction is enforced by `MetricRegistry.register`
(`metrics/registry.py:18-21`), not by this module's own good behaviour — confirmed already
enforced, not aspirational, while this module was built (2026-09-04); see the build report for the
direct read of `registry.py`.

**Real input gap, same shape every prior module in this session has documented rather than
papered over.** The accepted corpus this report measures — A-S3's survivors plus whatever `A-C1`'s
loader finds already committed — is genuinely empty in this checkout: A-S4 (`validate-heal`) does
not exist, so A-S3 has never run for real (spec §1's "Real gap", restated in the map's own
build-order note). Every function below is proven against synthetic, in-memory accepted-row
fixtures (`tests/test_coverage_report.py`) — the same discipline `distribution_planner`/
`dedup_select` used against their own not-yet-existing siblings' outputs.

**A genuine judgment call, flagged rather than hidden — the cell/quota attribution rule.** Spec §3
step 1's cell key is the 4-tuple `(scope, category, rungBand, pairingRole)`, but A-T1's own
`categoryMilli` (what step 2 recomputes a quota FROM) is never split by `pairingRole` — pairing-role
assignment is a separate, orthogonal overlay `assign_pairing_roles` applies AFTER a subject's
category distribution is already fixed (`distribution_planner/derive.py:plan_subject`), so no
per-pairingRole quota exists to recompute. This module resolves that the same way
`metrics/distribution.py:CellDeviation` resolves an unbudgeted dimension: **quota is recomputed at
the `(scope, category, rungBand)` GROUP level** (one recomputed number per group, shared identically
across that group's three pairingRole-partitioned cell rows in the emitted report), while each row's
own `count` stays exact and role-specific. `cellOccupancy`/`thinCell`/`quotaDrift` all reason at the
GROUP level; only the emitted `entries` list is exploded one row per role, matching spec §2's JSONC
shape (every emitted cell row carries `pairingRole`, `quota` and `thin`).
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Mapping, Sequence

from ..characteristic_pool.derive import CATEGORIES
from ..distribution_planner.derive import (
    GENERAL_WEIGHTS, apportion_categories, largest_remainder_count,
)
from ..vocab import PAIRING_ROLES, SCOPES, STATUSES
from ....metrics.model import Finding, Severity
from .ctx import ActionCoverageCtx, RosterCounts

__all__ = [
    "recompute_subject_category_counts", "aggregate_scope_category_quota",
    "CellGroup", "partition_accepted", "build_cell_groups", "cell_entries",
    "cell_occupancy_findings", "thin_cell_findings", "quota_drift_findings",
    "enabler_payoff_coverage_findings", "pairing_reach_findings", "atom_family_namespace_findings",
    "species_collision_findings", "species_coverage_findings", "singleton_share_findings",
    "structure_enforceability_findings",
    "roster_reconciliation_findings", "flavour_quality_findings", "semantic_neighbour_findings",
    "next_round_targets", "Verdict", "compute_verdict", "corpus_hash", "build_envelope",
    "canonical_dump",
    "TOLERANCE_UNITS", "RESEARCH_BAND_UNITS", "RESEARCH_BAND_ROSTER",
]

_GENERAL_SUBJECT_KEY = "general"          # the general scope's one pseudo-subject


# ---------------------------------------------------------------------------------------------
# §3 step 2 — quota recomputation, independent of A-S1's own stored answer. Reuses A-S1's own
# `largest_remainder_count` helper (`distribution_planner/derive.py`) rather than a second copy.
# ---------------------------------------------------------------------------------------------

def recompute_subject_category_counts(
    *, species_ids: "Sequence[str]", family_members: "Mapping[str, Sequence[str]]",
    weights_by_key: "Mapping[tuple[str, str], object]", general_count: int,
    per_family_count: int, per_species_count: int,
) -> "dict[tuple[str, str], dict[str, int]]":
    """Returns `{(scope, subjectKey): {category: count}}` — `subjectKey` is the literal
    `'general'` for the single general pseudo-subject (never `None`: a dict key needs to be
    hashable and comparable alongside real species/family ids, and `'general'` can never collide
    with a real one). Re-derives EXACTLY the way `distribution_planner.derive.plan_round` does:
    the SCOPE-level two-level allocation (`apportion_categories`), never trusting a stored brief's
    own counts. The general scope has one subject, so its own per-subject split IS the scope
    allocation and `largest_remainder_count` is correct there."""
    out: "dict[tuple[str, str], dict[str, int]]" = {}
    if general_count:
        out[("general", _GENERAL_SUBJECT_KEY)] = largest_remainder_count(
            GENERAL_WEIGHTS.category_milli, CATEGORIES, general_count)

    species_subjects = [
        (species_id, weights_by_key[("species", species_id)].category_milli)
        for species_id in species_ids
        if weights_by_key.get(("species", species_id)) is not None and per_species_count
    ]
    for species_id, counts in apportion_categories(species_subjects, per_species_count).items():
        out[("species", species_id)] = counts

    family_subjects = [
        (family_id, weights_by_key[("family", family_id)].category_milli)
        for family_id in sorted(family_members)
        if weights_by_key.get(("family", family_id)) is not None and per_family_count
    ]
    for family_id, counts in apportion_categories(family_subjects, per_family_count).items():
        out[("family", family_id)] = counts
    return out


def aggregate_scope_category_quota(
    subject_counts: "Mapping[tuple[str, str], Mapping[str, int]]",
) -> "dict[tuple[str, str], int]":
    """`{(scope, subjectKey): {category: count}}` -> `{(scope, category): totalCount}` — the
    GROUP-level quota `build_cell_groups` below actually gates on."""
    out: "dict[tuple[str, str], int]" = {}
    for (scope, _key), by_category in subject_counts.items():
        for category, n in by_category.items():
            out[(scope, category)] = out.get((scope, category), 0) + n
    return out


# ---------------------------------------------------------------------------------------------
# §3 step 1 — the cell partition, at the `(scope, category, rungBand)` GROUP level (see module
# docstring for why pairingRole is not a quota axis).
# ---------------------------------------------------------------------------------------------

def _band_str(band: "tuple[int, int]") -> str:
    return f"{band[0]}-{band[1]}"


@dataclass(frozen=True)
class CellGroup:
    scope: str
    category: str
    rung_band: "tuple[int, int]"
    quota: int
    counts_by_role: "dict[str, int]"

    @property
    def id(self) -> str:
        return f"cell.{self.scope}.{self.category}.{_band_str(self.rung_band)}"

    @property
    def total_count(self) -> int:
        return sum(self.counts_by_role.values())

    @property
    def thin(self) -> bool:
        """Never fires on an unbudgeted (quota == 0) group — the same discipline
        `metrics/distribution.py:CellDeviation` uses for `row.target == 0`: a cell nobody planned
        for is not a coverage gap, whatever its count."""
        return self.quota > 0 and self.total_count < self.quota

    @property
    def shortfall(self) -> int:
        return max(0, self.quota - self.total_count)


def partition_accepted(
    accepted_rows: "Sequence[Mapping[str, object]]",
) -> "dict[tuple[str, str, tuple[int, int], str], list[Mapping[str, object]]]":
    cells: "dict[tuple[str, str, tuple[int, int], str], list] " = {}
    for row in accepted_rows:
        band = tuple(row["rungBand"])
        key = (row["scope"], row["category"], band, row["pairingRole"])
        cells.setdefault(key, []).append(row)
    return cells


def build_cell_groups(
    accepted_rows: "Sequence[Mapping[str, object]]",
    quota_by_scope_category: "Mapping[tuple[str, str], int]",
    windows: "Mapping[str, tuple[int, int]]",
) -> "list[CellGroup]":
    """Every PLANNED group (scope x category, at that scope's own rung window) always exists,
    quota >= 0, even at count 0 — acceptance #4: "cell counts and quotas are present for every
    planned cell, including cells with count 0." Accepted rows whose OWN `rungBand` does not match
    their scope's planned window still surface as their own (real) group rather than being folded
    or dropped — real content is never silently hidden, matching A-C1's own "total" discipline.

    ST3 (`spec-scope-window-tunables.md` contract 3): the windows are the LOADED ones, passed in by
    the caller -- this module no longer imports a constant."""
    groups: "dict[tuple[str, str, tuple[int, int]], dict[str, int]]" = {}
    quotas: "dict[tuple[str, str, tuple[int, int]], int]" = {}

    for scope in SCOPES:
        band = tuple(windows[scope])
        for category in CATEGORIES:
            key = (scope, category, band)
            groups[key] = {role: 0 for role in PAIRING_ROLES}
            quotas[key] = quota_by_scope_category.get((scope, category), 0)

    partitioned = partition_accepted(accepted_rows)
    for (scope, category, band, role), rows in partitioned.items():
        key = (scope, category, band)
        if key not in groups:
            groups[key] = {r: 0 for r in PAIRING_ROLES}
            quotas[key] = quota_by_scope_category.get((scope, category), 0)
        groups[key][role] = groups[key].get(role, 0) + len(rows)

    out = [
        CellGroup(scope=scope, category=category, rung_band=band, quota=quotas[key],
                 counts_by_role=dict(counts))
        for key, counts in groups.items()
        for (scope, category, band) in [key]
    ]
    return sorted(out, key=lambda g: g.id)


def cell_entries(groups: "Sequence[CellGroup]", *, round_no: int) -> "list[dict]":
    """One `kindOfEntry: 'cell'` row per (group x pairingRole) — spec §2's JSONC shape. `quota`
    and `thin` are the GROUP's own verdict, shared identically across its three role rows (module
    docstring).

    ⛔ `round_no` folded into the id (2026-09-06 finding): `CellGroup.id` carries no round number,
    so two rounds' reports emit the IDENTICAL cell id (`cell.family.attack.1-7.enabler`) — real,
    reproduced regression: writing a real `coverage-round-903.json` alongside the already-committed
    `coverage-round-2.json` made `Corpus.load` raise a duplicate-id error over the whole actions
    tree. `round-2`'s own already-shipped report is left in its old (unqualified) format rather
    than rewritten — it is still the only report at that id shape, so nothing collides with it."""
    entries: "list[dict]" = []
    for g in groups:
        for role in sorted(PAIRING_ROLES):
            entries.append({
                "id": f"cell.round-{round_no}.{g.scope}.{g.category}.{_band_str(g.rung_band)}.{role}",
                "kindOfEntry": "cell",
                "scope": g.scope,
                "category": g.category,
                "rungBand": list(g.rung_band),
                "pairingRole": role,
                "count": g.counts_by_role.get(role, 0),
                "quota": g.quota,
                "thin": g.thin,
            })
    return entries


# ---------------------------------------------------------------------------------------------
# §3 step 3 — the eleven CLOSED metrics. Every function returns `Finding`s directly (never raises);
# `metrics/action_coverage.py`'s `Metric.run` methods are thin one-line wrappers over these.
# ---------------------------------------------------------------------------------------------

def cell_occupancy_findings(metric_id: str, cov: ActionCoverageCtx) -> "list[Finding]":
    groups = build_cell_groups(cov.accepted_rows, cov.quota_by_scope_category, cov.scope_windows)
    return [
        Finding(
            metric=metric_id, severity=Severity.GAP, subject=g.id,
            message=f"{g.id}: planned (quota {g.quota}) but holds no accepted row",
            evidence={"quota": g.quota, "count": 0},
            assertion=f"len(accepted rows in {g.id}) > 0",
            remedy="distribution-planner/dedup-select: schedule and accept rows for this cell",
        )
        for g in groups if g.quota > 0 and g.total_count == 0
    ]


def thin_cell_findings(metric_id: str, cov: ActionCoverageCtx) -> "list[Finding]":
    groups = build_cell_groups(cov.accepted_rows, cov.quota_by_scope_category, cov.scope_windows)
    return [
        Finding(
            metric=metric_id, severity=Severity.GAP, subject=g.id,
            message=f"{g.id}: {g.total_count}/{g.quota} accepted — short by {g.shortfall}",
            evidence={"count": g.total_count, "quota": g.quota, "shortfall": g.shortfall},
            assertion=f"count({g.id}) >= {g.quota}",
            remedy="distribution-planner: this cell is a next-round target candidate",
        )
        for g in groups if g.thin
    ]


# The largest-remainder algorithm's own per-subject rounding slack — an algorithmic property, not
# a balance-surface number a design pass would retune (AGENTS.md's "structural, not tunable"
# exemption): summing many already-rounded per-subject outputs can drift a little from a freshly
# recomputed group target even when nothing is actually wrong.
TOLERANCE_UNITS = 1


def quota_drift_findings(metric_id: str, cov: ActionCoverageCtx) -> "list[Finding]":
    """Symmetric — unlike `thinCell` (undershoot only), this also catches an OVERSHOOT beyond
    `TOLERANCE_UNITS`, which `thinCell`/`cellOccupancy` have no way to see."""
    groups = build_cell_groups(cov.accepted_rows, cov.quota_by_scope_category, cov.scope_windows)
    findings: "list[Finding]" = []
    for g in groups:
        if g.quota <= 0:
            continue
        drift = g.total_count - g.quota
        relative = drift / g.quota
        if drift > TOLERANCE_UNITS:
            findings.append(Finding(
                metric=metric_id, severity=Severity.GAP, subject=g.id,
                message=f"{g.id}: {g.total_count} accepted vs quota {g.quota} — "
                        f"overshoot by {drift} (+{relative:.1%}), beyond the "
                        f"{TOLERANCE_UNITS}-unit rounding tolerance",
                evidence={"count": g.total_count, "quota": g.quota, "driftUnits": drift,
                         "relative": relative}))
        else:
            findings.append(Finding(
                metric=metric_id, severity=Severity.NOTE, subject=g.id,
                message=f"{g.id}: {g.total_count} accepted vs quota {g.quota} "
                        f"({relative:+.1%})",
                evidence={"count": g.total_count, "quota": g.quota, "driftUnits": drift,
                         "relative": relative}))
    return findings


def enabler_payoff_coverage_findings(metric_id: str, cov: ActionCoverageCtx) -> "list[Finding]":
    """The corpus-side twin of `EnablerPayoffCoverage.Check` (`EnablerPayoffCoverage.cs:21-34`):
    for every ANCHOR (scope, scopeKey)'s pooled `atomFamilies` — the set every accepted row in that
    anchor contributes to, the same "pool" a rung's container draws from — every family in the pool
    that IS a payoff key must have at least one of its enablers also present in the SAME pool.

    `cov.pairing_table is None` means `pairings.json` was not available this run — a genuinely
    missing input, not "zero pairings" (spec's own `metrics/model.py:34` NOT_MEASURED discipline:
    a metric whose needs are unmet reports NOT_MEASURED, never a pass, and never a false GAP
    either)."""
    if cov.pairing_table is None:
        return [Finding(metric=metric_id, severity=Severity.NOT_MEASURED, subject="(suite)",
                        message="pairings.json was not available this run — enabler/payoff "
                                "coverage cannot be checked", evidence={})]
    by_anchor: "dict[tuple[str, str], set[str]]" = {}
    for row in cov.accepted_rows:
        anchor = (row["scope"], row.get("scopeKey") or _GENERAL_SUBJECT_KEY)
        by_anchor.setdefault(anchor, set()).update(row.get("atomFamilies") or ())

    findings: "list[Finding]" = []
    for anchor in sorted(by_anchor):
        present = by_anchor[anchor]
        for family in sorted(present):
            if family not in cov.pairing_table:
                continue
            enablers = cov.pairing_table[family]
            if not any(e in present for e in enablers):
                findings.append(Finding(
                    metric=metric_id, severity=Severity.GAP, subject=f"{anchor[0]}.{anchor[1]}:{family}",
                    message=f"{anchor[0]}.{anchor[1]}: payoff family {family!r} accepted with no "
                            f"accepted row carrying one of its enablers {list(enablers)!r} in the "
                            f"same anchor",
                    evidence={"anchor": list(anchor), "payoffFamily": family,
                             "enablers": list(enablers)},
                    assertion=f"one of {list(enablers)!r} is present in the {anchor[0]}.{anchor[1]} pool",
                    remedy="dedup-select/distribution-planner: accept an enabler row for this anchor",
                ))
    return findings


def pairing_reach_findings(metric_id: str, cov: ActionCoverageCtx) -> "list[Finding]":
    """The honest denominator behind `enablerPayoffCoverage`: how many accepted rows carry
    `pairingRole: 'none'`, and how many of the 98 authored families are even reachable payoff keys
    today. Denominator is the 98-family namespace, never `pairings.json`'s own 5 keys (acceptance
    #7c). `cov.pairing_table is None` (the file was not available this run) is NOT_MEASURED, never
    a false "zero reach"."""
    if cov.pairing_table is None:
        return [Finding(metric=metric_id, severity=Severity.NOT_MEASURED, subject="(suite)",
                        message="pairings.json was not available this run — reach cannot be "
                                "measured", evidence={})]
    total = len(cov.accepted_rows)
    none_count = sum(1 for r in cov.accepted_rows if r.get("pairingRole") == "none")
    denominator = len(cov.family_ids)
    reachable = sorted(k for k in cov.pairing_table if k in cov.family_ids)

    if reachable:
        reach_clause = (f"{len(reachable)}/{denominator} authored affix families are reachable "
                        f"payoff keys ({reachable!r})")
    else:
        reach_clause = (f"zero reach while pairings.json still carries its "
                        f"{len(cov.pairing_table)} out-of-namespace ids")

    message = (f"pairingRole == 'none' for {none_count}/{total} accepted rows; {reach_clause}"
              if total else f"no accepted rows; {reach_clause}")

    return [Finding(
        metric=metric_id, severity=Severity.NOTE, subject="(suite)", message=message,
        evidence={"totalAccepted": total, "noneCount": none_count,
                 "familyNamespaceSize": denominator, "reachablePayoffKeys": reachable,
                 "pairingTableKeyCount": len(cov.pairing_table)},
    )]


def atom_family_namespace_findings(metric_id: str, cov: ActionCoverageCtx) -> "list[Finding]":
    """Every accepted row's `atomFamilies` and `pairedPayoffFamily` id must be one of the 98
    authored affix families. A status id (`STATUSES`) in either field is named specially — it is
    not merely out of namespace, it is the wrong KIND of vocabulary entirely (spec §5's "a status
    where a family belongs" case)."""
    findings: "list[Finding]" = []

    def _check(row_id: str, field_name: str, value: str) -> None:
        if value in STATUSES:
            findings.append(Finding(
                metric=metric_id, severity=Severity.GAP, subject=f"{row_id}.{field_name}",
                message=f"{row_id}: field {field_name!r} carries {value!r} — a STATUS id, not an "
                        f"atom family; the pairing surface keys on atom families only "
                        f"(EnablerPayoffPairings.cs:26,30-31)",
                evidence={"entryId": row_id, "field": field_name, "value": value, "code": "status-not-family"}))
            return
        if value not in cov.family_ids:
            findings.append(Finding(
                metric=metric_id, severity=Severity.GAP, subject=f"{row_id}.{field_name}",
                message=f"{row_id}: field {field_name!r} carries {value!r}, not one of the 98 "
                        f"authored affix families under data/seed/items/affix-families/*.json",
                evidence={"entryId": row_id, "field": field_name, "value": value, "code": "out-of-namespace"}))

    for row in cov.accepted_rows:
        row_id = row.get("id", "(no id)")
        for family in row.get("atomFamilies") or ():
            _check(row_id, "atomFamilies", family)
        paired = row.get("pairedPayoffFamily")
        if paired is not None:
            _check(row_id, "pairedPayoffFamily", paired)
    return findings


def species_collision_findings(metric_id: str, cov: ActionCoverageCtx) -> "list[Finding]":
    """Two species whose SIGNATURE sets render to the exact same set of fingerprints — the
    conservative (exact-match) reading of "tier-2 identical" this module uses, flagged plainly as
    a judgment call: `dedup_select.derive.run_tier2`'s own field-by-field near-duplicate matching
    is defined WITHIN one species' own accepted set, not across two different species' whole sets,
    so there is no single existing definition of "two species collide" to just import. Exact-set
    equality is the degenerate (distance-0) case of "at most one field apart" and is what a
    starved per-species count (the smoke default is 1) will actually produce first — the named
    re-tune trigger this metric exists to catch."""
    from ..distribution_planner.fingerprint import FingerprintComponents, render_fingerprint

    by_species: "dict[str, set[tuple[str, ...]]]" = {}
    for row in cov.accepted_rows:
        if row["scope"] != "species":
            continue
        fp = FingerprintComponents(
            atom_families=tuple(row.get("atomFamilies") or ()), category=row["category"],
            target_mode=row["targetMode"], area_shape=row.get("areaShape"),
            relation=row["relation"], structure_axes=tuple(row.get("structureAxes") or ()),
            pairing_role=row["pairingRole"])
        by_species.setdefault(row["scopeKey"], set()).add(render_fingerprint(fp))

    findings: "list[Finding]" = []
    species = sorted(by_species)
    for i in range(len(species)):
        for j in range(i + 1, len(species)):
            a, b = species[i], species[j]
            if by_species[a] and by_species[a] == by_species[b]:
                findings.append(Finding(
                    metric=metric_id, severity=Severity.GAP, subject=f"{a}~{b}",
                    message=f"species {a!r} and {b!r} have IDENTICAL accepted signature sets "
                            f"({len(by_species[a])} rows each) — the per-species run count has no "
                            f"differentiating signal between them",
                    evidence={"speciesA": a, "speciesB": b, "rowCount": len(by_species[a])},
                    remedy="action-corpus-run.v1.json: raise perSpeciesCount, or re-check A-T1 "
                           "weights for these two species"))
    return findings


def species_coverage_findings(metric_id: str, cov: ActionCoverageCtx) -> "list[Finding]":
    """**The per-species coverage gate — the granularity the scope-aggregate cells cannot see (G3).**

    ⛔ **The defect this closes, measured 2026-09-12.** `cellOccupancy`/`thinCell` gate on
    `cell.<scope>.<category>.<band>`, which at species scope is ONE aggregate over all 904 species:
    `cell.species.attack.1-10` had quota 976 (= 904 x 5 x 21.6%). That number can be satisfied by
    spreading 976 attack rows over ~100 species (9-10 each) while **804 species hold no attack
    action** — and the cell would read perfect. Measured at the time: **828 of 904 species had zero
    accepted actions, and no metric reported it.** A scope-aggregate cell is structurally blind to
    per-subject distribution; this metric is the per-subject view the design needs and the
    `next-target` derivation (`next_round_targets`, which already names individual species) already
    assumed.

    **What it asserts (the CONTRACT, not a population count).** Every live species id that the ctx
    knows about must have at least one accepted row. The roster is a POPULATION
    ([validation-ssot.md](../../../../../docs/architecture/validation-ssot.md)): the metric never
    compares a *count* to a literal; it compares the *set of species with zero rows* to the empty
    set. Adding a species makes the requirement grow, which is correct — the new species is simply
    another subject that must be covered.

    **One Finding per uncovered species**, naming that species, so the same rows feed the top-up
    loop as explicit work orders. Severity GAP: an uncovered species is a real hole, not a note.

    **Which species ids count as required.** `cov.family_ids` carries the authored atom-family
    namespace, not species ids, so the required roster is derived from `subject_category_counts`:
    every `("species", speciesId)` key the quota was recomputed for IS a planned species subject
    (`recompute_subject_category_counts` builds exactly the catalog ids). That keeps this metric's
    universe identical to the planner's, with no second roster read and no way for the two to
    disagree."""
    required = {key for (scope, key) in cov.subject_category_counts if scope == "species"}
    covered = {row["scopeKey"] for row in cov.accepted_rows
               if row.get("scope") == "species" and row.get("scopeKey")}
    uncovered = sorted(required - covered)
    return [
        Finding(
            metric=metric_id, severity=Severity.GAP, subject=species_id,
            message=f"species {species_id!r}: no accepted action — {len(covered)} of "
                    f"{len(required)} species have at least one; the scope-aggregate cells "
                    f"(cellOccupancy/thinCell) cannot see a missing species",
            evidence={"speciesKey": species_id, "coveredSpecies": len(covered),
                      "requiredSpecies": len(required)},
            assertion=f"{species_id!r} has >= 1 accepted action row",
            remedy="next-round target for this species, or raise perSpeciesCount / generalCount "
                   "so its planned briefs are drawn and accepted",
        )
        for species_id in uncovered
    ]


def singleton_share_findings(metric_id: str, cov: ActionCoverageCtx) -> "list[Finding]":
    """Median rows per occupied mechanical cell (the `(scope, category, rungBand, pairingRole)`
    literal partition, spec §3 step 1) and the singleton share, against the research target of
    median 1 and ~68% singletons (spec §2's own register entry) — measure-only, NOTE severity,
    same as `metrics/distribution.py`'s own Evenness/Inequality."""
    partitioned = partition_accepted(cov.accepted_rows)
    counts = sorted(len(rows) for rows in partitioned.values() if rows)
    if not counts:
        return [Finding(metric=metric_id, severity=Severity.NOT_MEASURED, subject="(suite)",
                        message="no occupied mechanical cells — nothing to measure", evidence={})]

    n = len(counts)
    mid = n // 2
    median = counts[mid] if n % 2 else (counts[mid - 1] + counts[mid]) / 2
    singleton_share = sum(1 for c in counts if c == 1) / n

    return [Finding(
        metric=metric_id, severity=Severity.NOTE, subject="(suite)",
        message=f"{n} occupied mechanical cells: median {median} rows/cell, "
                f"{singleton_share:.1%} singletons (research target: median 1, ~68% singletons)",
        evidence={"occupiedCellCount": n, "median": median, "singletonShare": singleton_share,
                 "targetMedian": 1, "targetSingletonShare": 0.68},
    )]


REACTION_AXIS = "reaction"
RESTRICTION_AXIS = "restriction"


def structure_enforceability_findings(metric_id: str, cov: ActionCoverageCtx) -> "list[Finding]":
    """Acceptance #7 / #7 correction: `restriction` is real but UNDETECTABLE by
    `StructureBudgetGuard.cs:30-34` (needs the effect-atom program's per-atom payload/target data —
    reported with that caveat, NOTE severity, never a defect). `reaction` is UNSPENDABLE
    (`ActionKind` has exactly three members, none reaction-shaped, `StructureBudgetGuard.cs:27-30`)
    — a non-zero count there is a real upstream defect, GAP severity."""
    restriction_count = sum(
        1 for r in cov.accepted_rows if RESTRICTION_AXIS in (r.get("structureAxes") or ()))
    reaction_count = sum(
        1 for r in cov.accepted_rows if REACTION_AXIS in (r.get("structureAxes") or ()))

    findings: "list[Finding]" = [Finding(
        metric=metric_id, severity=Severity.NOTE, subject=RESTRICTION_AXIS,
        message=f"{restriction_count} accepted rows spend {RESTRICTION_AXIS!r} — real spend, "
                f"undetectable by StructureBudgetGuard.cs:30-34 (detection needs the effect-atom "
                f"program's per-atom payload/target data)",
        evidence={"count": restriction_count})]

    if reaction_count > 0:
        findings.append(Finding(
            metric=metric_id, severity=Severity.GAP, subject=REACTION_AXIS,
            message=f"{reaction_count} accepted rows spend {REACTION_AXIS!r} — unspendable "
                    f"(ActionKind has exactly three members, none reaction-shaped, "
                    f"StructureBudgetGuard.cs:27-30) — a real upstream defect, not a reporting nuance",
            evidence={"count": reaction_count},
            assertion="count(rows spending 'reaction') == 0",
            remedy="distribution-planner/dedup-select: refuse a brief/candidate naming 'reaction'"))
    else:
        findings.append(Finding(
            metric=metric_id, severity=Severity.NOTE, subject=REACTION_AXIS,
            message="0 accepted rows spend 'reaction' — correct, it is unspendable",
            evidence={"count": 0}))

    return findings


# The research band is historical context. The live roster and the per-species count are read from
# the seed tree and `action-corpus-run.v1.json`; neither may be rejected because it differs from the
# old projection used by the original spec.
RESEARCH_BAND_UNITS = (1500, 3500)
RESEARCH_BAND_ROSTER = 904

def roster_reconciliation_findings(
    metric_id: str, roster: RosterCounts, accepted_corpus_size: int,
    signature_actions_per_species: int,
) -> "list[Finding]":
    """⛔ **`signature_actions_per_species` is REQUIRED, with no default (2026-09-12, G4).** It used
    to default to a module constant `SIGNATURE_ACTIONS_PER_SPECIES = 3`, which restated the SEALED
    ideal's *"3 signature actions per species"* (B1) as though it were the shipped value. The shipped
    `action-corpus-run.v1.json` sets `perSpeciesCount: 5`, so the default was wrong, and it was dead
    — the one caller (`metrics/action_coverage.py`) always passes `cov.per_species_count`. A wrong
    default that happens never to be reached is worse than no default: it is a second, contradictory
    source of truth that the next reader trusts. Making the parameter required means the tuning file
    is the only place this number lives, and a future caller cannot silently get `3`.

    `signatureTierEstimate` is therefore always `roster.species_count x` the LIVE tuning count, so
    the reconciliation message reports the corpus this run is actually sized for."""
    if signature_actions_per_species < 0:
        raise ValueError("signature_actions_per_species must be non-negative")
    signature_tier_estimate = roster.species_count * signature_actions_per_species
    below_band = signature_tier_estimate < RESEARCH_BAND_UNITS[0]
    return [Finding(
        metric=metric_id, severity=Severity.NOTE, subject="(suite)",
        message=(f"shipped roster: {roster.species_count} species, {roster.family_count} families, "
                 f"{roster.family_assigned_count} family-assigned. Signature-tier re-derivation: "
                 f"{roster.species_count} x {signature_actions_per_species} = "
                 f"{signature_tier_estimate}, "
                 f"{'below' if below_band else 'inside/above'} the "
                 f"{RESEARCH_BAND_UNITS[0]}-{RESEARCH_BAND_UNITS[1]} band (historical context from "
                 f"a {RESEARCH_BAND_ROSTER}-unit roster; this is not a pass/fail gate). Accepted "
                 f"corpus today: {accepted_corpus_size} rows."),
        evidence={"speciesCount": roster.species_count, "familyCount": roster.family_count,
                 "familyAssignedCount": roster.family_assigned_count,
                 "signatureTierEstimate": signature_tier_estimate,
                 "researchBandUnits": list(RESEARCH_BAND_UNITS),
                 "researchBandRoster": RESEARCH_BAND_ROSTER,
                 "acceptedCorpusSize": accepted_corpus_size, "belowBand": below_band})]


# ---------------------------------------------------------------------------------------------
# §3 step 4 — the two OPEN metrics. Review-queue only; NEVER a pass contributor (spec §4's first
# bullet). `Loop.OPEN` is set by the `Metric` subclass in `metrics/action_coverage.py`, not here —
# these functions just build the findings.
# ---------------------------------------------------------------------------------------------

_GENERIC_NAME_TOKENS = frozenset({"", "action", "skill", "move", "ability", "attack"})


def flavour_quality_findings(metric_id: str, cov: ActionCoverageCtx) -> "list[Finding]":
    """A human review queue, never a defect: a blank or single-generic-word `name` is flagged for
    a reviewer's judgment, not asserted as wrong (no model call — a real "does this read generic"
    verdict needs a reader, not arithmetic; spec §4's "never call a model, not to judge prose")."""
    findings: "list[Finding]" = []
    for row in cov.accepted_rows:
        name = (row.get("name") or "").strip()
        if name.lower() in _GENERIC_NAME_TOKENS:
            findings.append(Finding(
                metric=metric_id, severity=Severity.NOTE, subject=row.get("id", "(no id)"),
                message=f"{row.get('id', '(no id)')}: name {name!r} reads generic — queued for "
                        f"human review, not a defect",
                evidence={"name": name}))
    return findings


def semantic_neighbour_findings(metric_id: str, cov: ActionCoverageCtx) -> "list[Finding]":
    """Passes A-S3's own tier-3 `review-queue.json` rows through as findings — this module never
    recomputes similarity, it only surfaces what dedup-select already flagged for review."""
    return [
        Finding(
            metric=metric_id, severity=Severity.NOTE,
            subject=f"{row.get('candidateA')}~{row.get('candidateB')}",
            message=f"{row.get('candidateA')} and {row.get('candidateB')} are semantic "
                    f"near-neighbours (similarity {row.get('similarityMilli')}‰) — queued for "
                    f"human review, not a defect (constraint 4: cross-tier similarity is expected "
                    f"while family-access widening stays gated)",
            evidence={"similarityMilli": row.get("similarityMilli")})
        for row in cov.review_rows
    ]


# ---------------------------------------------------------------------------------------------
# §3 step 5 — next-round target derivation, a pure function of the same accepted-row/quota data
# the report itself is built from: same inputs -> same targets, and shuffling `accepted_rows`'
# input order changes nothing (both sorted internally before use).
# ---------------------------------------------------------------------------------------------

def next_round_targets(
    *, groups: "Sequence[CellGroup]", subject_counts: "Mapping[tuple[str, str], Mapping[str, int]]",
    accepted_rows: "Sequence[Mapping[str, object]]", round_no: int,
    windows: "Mapping[str, tuple[int, int]]",
) -> "list[dict]":
    accepted_by_subject_cat: "dict[tuple[str, str], dict[str, int]]" = {}
    for row in accepted_rows:
        key = (row["scope"], row.get("scopeKey") or _GENERAL_SUBJECT_KEY)
        d = accepted_by_subject_cat.setdefault(key, {})
        d[row["category"]] = d.get(row["category"], 0) + 1

    targets: "list[dict]" = []
    for g in sorted(groups, key=lambda g: g.id):
        if not g.thin:
            continue
        # One (subject, category) emits ONE target id
        # (`target.round-<n+1>.<scope>.<subjectKey>.<category>` — no band component), so only the
        # PLANNED-window group may drive top-up. An off-window group (real accepted content whose
        # own rungBand misses its scope's window — surfaced by `build_cell_groups`, never hidden)
        # shares its (scope, category) quota accounting with the planned cell, and its rows already
        # count toward the same subject shortfalls below; emitting from it too would duplicate the
        # id (`Corpus.load` refuses duplicates) or double the want (readers sum duplicate targets).
        # Phase-4-found 2026-09-15: `act.attack` (general scope, off-window band) created the
        # second general/attack group and the refreshed round-1 report carried the id twice.
        if tuple(g.rung_band) != tuple(windows[g.scope]):
            continue
        short_subjects: "list[tuple[int, str]]" = []
        for (scope, subject_key), by_cat in subject_counts.items():
            if scope != g.scope:
                continue
            subject_quota = by_cat.get(g.category, 0)
            if subject_quota <= 0:
                continue
            accepted = accepted_by_subject_cat.get((scope, subject_key), {}).get(g.category, 0)
            shortfall = subject_quota - accepted
            if shortfall > 0:
                short_subjects.append((shortfall, subject_key))
        short_subjects.sort(key=lambda t: (-t[0], t[1]))
        for shortfall, subject_key in short_subjects:
            scope_key = None if subject_key == _GENERAL_SUBJECT_KEY else subject_key
            targets.append({
                "id": f"target.round-{round_no + 1}.{g.scope}.{subject_key}.{g.category}",
                "kindOfEntry": "next-target",
                "scope": g.scope,
                "scopeKey": scope_key,
                "category": g.category,
                "want": shortfall,
                "because": f"{g.id}.none is thin",
            })
    return targets


# ---------------------------------------------------------------------------------------------
# §3 step 6 — the verdict. "pass" requires EVERY closed metric to have both run (no NOT_MEASURED)
# and stayed clean (no GAP), AND the run to be `mode: "full"` — a smoke-mode run can never claim a
# corpus-level pass (spec §4's "never schedule past the smoke batch"; testing table's "small batch
# honesty"). `evaluatedMetrics`/`notMeasuredMetrics` are always both present and explicit
# (acceptance #3): an unevaluated metric is NAMED, never silently missing.
# ---------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class Verdict:
    verdict: str                          # "pass" | "smoke-clean" | "not-clean"
    evaluated_metrics: "tuple[str, ...]"
    not_measured_metrics: "tuple[str, ...]"
    gap_metrics: "tuple[str, ...]"
    gating_metrics: "tuple[str, ...]" = ()

    def to_dict(self) -> dict:
        return {
            "verdict": self.verdict,
            "evaluatedMetrics": list(self.evaluated_metrics),
            "notMeasuredMetrics": list(self.not_measured_metrics),
            "gapMetrics": list(self.gap_metrics),
            "gatingMetrics": list(self.gating_metrics),
        }


def compute_verdict(closed_findings: "Sequence[Finding]", closed_metric_ids: "Sequence[str]",
                    mode: str, gating_metric_ids: "Sequence[str]" = (),
                    ) -> Verdict:
    """**The verdict, gated on `gates` — not on the mere existence of a GAP (T1.2, 2026-09-12).**

    `spec-metrics.md` §4 fixes the calibration order: *"New metric → `gates=False`, runs, reports.
    Then a threshold goes into `budget` and `gates` flips."* So a GAP from an UNPROMOTED metric is a
    reading plus a next-round work order, never a gate — and `spec-coverage-report.md` §3 step 6 says
    `pass` requires every **gating** CLOSED metric green. This function previously ignored the flag
    and treated any GAP as `not-clean`, which (with all eleven action metrics shipping unpromoted)
    made every verdict non-clean and the full-run gate unreachable by construction.

    **What blocks, precisely:**
    - `NOT_MEASURED` on **any** CLOSED metric → never clean, gating or not. An absent check must stay
      distinguishable from a pass (`spec §4`), and it is not a threshold question.
    - `GAP` on a metric in `gating_metric_ids` → not clean.
    - `GAP` on any other metric → reported in `gap_metrics`, does not block. `gating_metric_ids` is
      the caller's `{m.id for m in registry.all() if m.gates}` — the same set `report/cli.py` builds
      for `--gate`, so A-S5's verdict and the general reporter cannot disagree about what gates.

    The full GAP list is ALWAYS returned and always written to the report; promotion changes only
    whether a GAP flips the verdict, never whether it is visible."""
    by_metric: "dict[str, list[Finding]]" = {mid: [] for mid in closed_metric_ids}
    for f in closed_findings:
        by_metric.setdefault(f.metric, []).append(f)

    not_measured = tuple(sorted(
        mid for mid, fs in by_metric.items()
        if any(f.severity is Severity.NOT_MEASURED for f in fs)))
    gap = tuple(sorted(
        mid for mid, fs in by_metric.items()
        if any(f.severity is Severity.GAP for f in fs)))
    gating = tuple(sorted(set(gating_metric_ids)))
    evaluated = tuple(sorted(by_metric))

    gating_gap = tuple(sorted(set(gap) & set(gating)))
    clean = not not_measured and not gating_gap
    if clean and mode == "full":
        verdict = "pass"
    elif clean:
        verdict = "smoke-clean"
    else:
        verdict = "not-clean"

    return Verdict(verdict=verdict, evaluated_metrics=evaluated,
                   not_measured_metrics=not_measured, gap_metrics=gap,
                   gating_metrics=gating)


# ---------------------------------------------------------------------------------------------
# §3 step 7 — canonical envelope assembly + write. Sorted keys, fixed indent, trailing `\n`,
# explicit nulls — the same discipline every `_canonical_dump`/`canonical_dump` in this adapter
# family already uses.
# ---------------------------------------------------------------------------------------------

def corpus_hash(accepted_rows: "Sequence[Mapping[str, object]]") -> str:
    """A stable digest over the accepted rows this report measured — sorted by id first, so the
    hash is invariant to the caller's own input order (acceptance #8's "provenance recording the
    corpus hash"; same discipline `dedup_select.derive._hash_rows` already uses)."""
    ordered = sorted(accepted_rows, key=lambda r: r.get("id", ""))
    blob = json.dumps(ordered, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def build_envelope(entries: "list[dict]", meta: dict) -> dict:
    return {"schemaVersion": 1, "kind": "action-coverage", "_meta": meta, "entries": entries}


def canonical_dump(doc: dict) -> str:
    return json.dumps(doc, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
