"""seedsmith.adapters.items.setgen.roles — THE TWELVE, and the cap applied *before* the call.

⛔ The cap is a GENERATOR INPUT, not a validation afterthought: `SetRoleNotUniversal` fires at LOAD
(ssot-sets.md §3.7), so ~1,000 sets checked after the fact is ~1,000 rejections and a re-run, not a
lint pass. The role list therefore reaches the model inside the brief, as the only legal answer.

Enumerated here rather than derived from `core.v1.json`'s `hybridEligible` flags — but for the
OPPOSITE reason the spec's code-style block gave when it was written. At that time the flags were
stale (13 roles / 895‰) and D3 had superseded them. **They are no longer stale: `core.v1.json` is
`registryVersion 2` and its twelve eligible roles sum to exactly 800‰** (measured 2026-09-04, and
`assert_core_agrees` re-measures it on every call rather than trusting this sentence). The list stays
enumerated because this module must keep working against a synthetic fixture that ships no registry —
the same reasoning `metrics/linkage.py`'s `NON_HYBRID_ROLES` already states — and `assert_core_agrees`
is what stops the two drifting apart silently.
"""
from __future__ import annotations

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[6]
CORE_REGISTRY = REPO_ROOT / "data" / "seed" / "items" / "_registry" / "core.v1.json"

#: D3's twelve-role hybrid core — 800‰ exactly. D3's own prose names *eleven* (it says "both jewels"
#: where three jewel roles are kept); the twelve are enumerated so nobody has to reconstruct that.
HYBRID_CORE_ROLES: "tuple[str, ...]" = (
    "armament-primary", "core-guard", "armament-secondary", "jewel-major",
    "manipulator", "mantle", "girdle", "footing",
    "infusion", "retinue", "jewel-minor-a", "jewel-minor-b",
)

#: The three D3 drops, by name. A generated set naming any of these is refused before the call.
DROPPED_ROLES: "frozenset[str]" = frozenset({"ward-array", "head-guard", "sense"})

#: ssot-sets §3.5 rule 4 — a set may claim at most ONE of these. "Weapons are where build identity
#: lives; a set that owns both owns the build."
ARMAMENT_ROLES: "frozenset[str]" = frozenset({"armament-primary", "armament-secondary"})

#: The budget the twelve are expected to sum to, in per-mille. STRUCTURAL, not a progression
#: ceiling: it is a property of the role table, re-measured on every `assert_core_agrees` call
#: rather than assumed, and a mismatch RAISES instead of being absorbed.
HYBRID_CORE_BUDGET_MILLI = 800


class RoleCapViolation(ValueError):
    """A role outside the twelve reached a generated set. Raised, never logged: the whole point of
    capping before the call is that this can only happen through a code path that skipped the cap."""


def core_registry_weights(path: "Path | None" = None) -> "dict[str, int]":
    """`roleId -> budgetWeightMilli` for the hybrid-eligible roles, read fresh from the registry.

    `int` throughout, and summed as `int` — Python's ints are arbitrary precision, so the
    widen-before-multiply rule has no analogue here, but the per-mille denominator is still divided
    exactly once and only at display (`ssot-power-scale` §11's arithmetic discipline restated for a
    tool that does the same arithmetic in a different language).
    """
    doc = json.loads((path or CORE_REGISTRY).read_text(encoding="utf-8"))
    return {r["roleId"]: int(r["budgetWeightMilli"])
            for r in doc["roles"]["list"] if r.get("hybridEligible")}


def assert_core_agrees(path: "Path | None" = None) -> int:
    """Re-measure `HYBRID_CORE_ROLES` against the live registry. Returns the summed per-mille.

    Two failure directions, both raised rather than warned: the registry's eligible set is not this
    module's twelve, or the twelve do not sum to `HYBRID_CORE_BUDGET_MILLI`. Either means a role
    table moved under a generator that has already emitted content against the old one.
    """
    weights = core_registry_weights(path)
    registry_roles = frozenset(weights)
    if registry_roles != frozenset(HYBRID_CORE_ROLES):
        missing = sorted(frozenset(HYBRID_CORE_ROLES) - registry_roles)
        extra = sorted(registry_roles - frozenset(HYBRID_CORE_ROLES))
        raise RoleCapViolation(
            f"core.v1.json's hybrid-eligible roles disagree with HYBRID_CORE_ROLES — "
            f"missing from the registry {missing}, present only in the registry {extra}")
    total = sum(weights.values())
    if total != HYBRID_CORE_BUDGET_MILLI:
        raise RoleCapViolation(
            f"the twelve hybrid-core roles sum to {total}‰, not {HYBRID_CORE_BUDGET_MILLI}‰ — "
            f"the role table moved and every set already generated against it is mispriced")
    return total


def refuse_roles(roles: "list[str] | tuple[str, ...]") -> "list[str]":
    """Every reason this member-role list may not be emitted, as messages. Empty list = legal.

    Deliberately returns ALL violations rather than the first: an author fixing a generated draft
    should see the whole refusal, and a run report that names one of three problems produces three
    round trips.
    """
    problems: "list[str]" = []
    ordered = list(roles)
    unknown = [r for r in ordered if r not in HYBRID_CORE_ROLES]
    for role in sorted(set(unknown)):
        why = ("dropped from the hybrid core by D3" if role in DROPPED_ROLES
               else "not a hybrid-core role")
        problems.append(f"SetRoleNotUniversal: role {role!r} is {why}; a hybrid frame could never "
                        f"complete this set")
    armaments = sorted({r for r in ordered if r in ARMAMENT_ROLES})
    if len(armaments) > 1:
        problems.append(f"SetRoleForbidden: a set may claim at most one armament role, got "
                        f"{armaments} — weapons are where build identity lives (ssot-sets §3.5 rule 4)")
    duplicates = sorted({r for r in ordered if ordered.count(r) > 1})
    if duplicates:
        problems.append(f"SetRoleDuplicated: {duplicates} appears more than once; membership is "
                        f"counted per ROLE, so a second row in the same role is a silent no-op")
    return problems
