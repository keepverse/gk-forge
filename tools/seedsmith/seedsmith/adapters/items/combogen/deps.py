"""seedsmith.adapters.items.combogen.deps — acceptance 3a of `combination-write-unblock`, run
against the real corpus through the shared `pipeline.dependency_validator` (module 1,
`generator-harness`), not a second bespoke check.

⚠ **Two closures already do most of this work; this module reports them rather than replacing
them.** `run.plan_run` refuses to build a schema at all when `supply.build()` finds zero families or
`tuning.host_roles()` finds zero roles (`schema.combination_schema`'s own precheck), so a plan can
never come back naming a hostRole/family nothing satisfies — the guarantee acceptance 3a asks for is
already structural. What this module adds is the REPORTED form the spec's Commands block names
(`items validate --deps`): a count per family/role, run through `dependency_validator.validate` so
"resolves, but only barely (1 gem)" stays visible the way a bare boolean would not
(`dependency_validator.py`'s own stated reason for a count, not a bool).

`grants` is `EXTERNAL` (3b, resolved 2026-09-07): validated against the REAL PRODUCTION ATOM
CATALOG — `gk-data/packs/fusion/data/seed/items/affix-families/**` expanded by `FamilyExpansion.Expand`
(`items.registries.load_authored_affix_family_ids()`), the same set the C# `ReferenceCheck`
resolves a grant against. Identically to HARD, but never handed to `plan_backfill` — this program
has no standing to author atom-family content that does not exist yet.

⛔ **Not `load_atom_families()`.** That loader globs all of `gk-data/packs/fusion/data/seed/atoms/**`, which carries the
expansion snapshot PLUS hand-authored atom sources (`aura-content.json`, `fx-*.json`,
`patron-aura.json`, `trait-critical-hunter.json`, `extend-slot.json`) that no affix family carries.
`GemContainerBuild`'s own doc says the runtime does NOT resolve against that directory. Using it
turned this preflight green over a grants universe the validator rejects (SSH2.5's 19
`ReferenceUnresolved` grants).
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from . import supply as supply_mod
from .tuning import REPO_ROOT, ComboTuning
from ....workspace_roots import seed_root
from .. import registries
from ....pipeline.dependency_validator import (
    CATEGORICAL,
    EXTERNAL,
    ReferenceManifestEntry,
    ValidationReport,
    validate,
)

TARGET_INGREDIENTS = "sockets-gen"
TARGET_HOST_ROLE = "base-types-gen"
TARGET_GRANTS = "effect-atom/atom-family-library"

#: Where the REAL base-type corpus lives. A role the tuning offers must be a role at least one row
#: here can physically host (`socketMax >= ingredientCount`) — read from the corpus, never from
#: `base-types-gen`'s tuning, because the question is what the GAME has, not what a generator would
#: emit. Monkeypatched in tests to a fixture directory so the rule is asserted, not today's corpus.
# `data/seed` is gk-data's pack, not gk-forge's, so it cannot be joined onto a repository root.
# `seed_root` is the pack's own `data/seed`; when the pack is absent it returns a path that does
# not exist, and `base_type_reach` below already treats a missing directory as an empty mapping.
BASE_TYPES_DIR = seed_root(REPO_ROOT) / "items" / "base-types"


def base_type_reach(base_types_dir: "Path | None" = None) -> "dict[str, int]":
    """`role -> the highest socketMax any real shipped base-type row carries for it`.

    A missing role is simply absent from the mapping (the caller reads absent as zero). Every file
    under the directory is walked and a non-`base-type` document is skipped, matching the corpus
    loader's own "a file is a seed file iff it declares a kind and an entries list" rule.
    """
    root = Path(base_types_dir) if base_types_dir is not None else BASE_TYPES_DIR
    reach: "dict[str, int]" = {}
    for path in sorted(root.rglob("*.json")):
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(doc, dict) or doc.get("kind") != "base-type":
            continue
        for row in doc.get("entries") or ():
            if not isinstance(row, dict) or "role" not in row:
                continue
            role = str(row["role"])
            reach[role] = max(reach.get(role, 0), int(row.get("socketMax", 0)))
    return reach


def roles_without_a_base(tuning: ComboTuning, *,
                         base_types_dir: "Path | None" = None) -> "tuple[str, ...]":
    """The roles `tuning.host_roles()` offers the model that no real base type can host.

    The host set is derived from the TUNING ceilings (R11), not from the base-type corpus, so a
    re-run between `sockets.v2.json`'s publish and SSH5.12's `resocket --write` re-stamp offers the
    helm while no helm chassis yet holds four sockets — the model would author helm-pinned words the
    game cannot equip, and the grid would have to be regenerated. Returned by role name so the
    refusal can say which role needs re-stamping.
    """
    reach = base_type_reach(base_types_dir)
    needed = tuning.ingredient_count
    return tuple(sorted(role for role in tuning.host_roles() if reach.get(role, 0) < needed))

#: The manifest for one ALREADY-GENERATED combination entry (post-write shape, `emit.assemble_entry`'s
#: own field names) — used by `validate_entries` below, and by `test_combogen.py` against real
#: authored output.
ENTRY_MANIFEST: "tuple[ReferenceManifestEntry, ...]" = (
    ReferenceManifestEntry("ingredients[].family", CATEGORICAL, TARGET_INGREDIENTS),
    ReferenceManifestEntry("hostRole", CATEGORICAL, TARGET_HOST_ROLE),
    ReferenceManifestEntry("grants[]", EXTERNAL, TARGET_GRANTS),
)


@dataclass(frozen=True)
class DepsReport:
    """Acceptance 3a's own pre-flight, over the whole corpus a run COULD draw from — before any
    subject is planned, matching the acceptance criterion's own "before any real generation"
    ordering."""

    ingredient_families_checked: int
    host_roles_checked: int
    roles_without_a_base: "tuple[str, ...]"
    grants_checked: int
    ingredient_gem_counts: "dict[str, int]"
    result: ValidationReport

    @property
    def refused(self) -> bool:
        """Mirrors `schema.combination_schema`'s own refusal condition exactly — this is the
        REPORTED form of the same test, not a different one — plus the R11 base-reachability check:
        a role the tuning OFFERS that no shipped base type can host is the same defect one layer
        down (the schema would happily offer the helm while the game has no helm chassis).
        `grants_checked` is deliberately NOT part of this: `combination_schema` itself only raises
        on an empty `supplied_families` or an empty `host_roles` (checked above), never on an empty
        `granted_families` — an empty grants enum would ship a schema the model cannot answer, but
        that is a defect this report SURFACES (`grantsChecked` below), not one `combination_schema`
        structurally refuses today."""
        return (self.ingredient_families_checked == 0 or self.host_roles_checked == 0
                or bool(self.roles_without_a_base))

    def to_dict(self) -> dict:
        reasons: "list[str]" = []
        if self.ingredient_families_checked == 0:
            reasons.append(
                "no ingredient family is supplied by any live gem — run the gem-supply precheck "
                "first (supply.SupplyRefused is what a real run would raise here)")
        if self.host_roles_checked == 0:
            reasons.append(
                "no host role's socket ceiling reaches the ingredient count — no base type could "
                "ever host a combination")
        if self.roles_without_a_base:
            reasons.append(
                "no shipped base type's socketMax reaches the ingredient count for host role(s) "
                f"{', '.join(self.roles_without_a_base)} — the tuning offers a chassis nothing can "
                "host until the base-type corpus is re-stamped (circuit-topology SSH5.12 "
                "`resocket --write`)")
        return {
            "ingredientFamiliesChecked": self.ingredient_families_checked,
            "hostRolesChecked": self.host_roles_checked,
            "hostRolesWithoutABase": list(self.roles_without_a_base),
            "grantsChecked": self.grants_checked,
            "ingredientGemCounts": self.ingredient_gem_counts,
            "refused": self.refused,
            "reasons": reasons,
            "detail": self.result.to_dict(),
        }


def preflight(tuning: ComboTuning, *, supply: "supply_mod.SupplyReport | None" = None,
              base_types_dir: "Path | None" = None) -> DepsReport:
    """Run before `run.plan_run` — over every family/role/grant a run COULD request, not over one
    already planned subject. `resolve_categorical` dispatches on `target_module` because the same
    callback serves two different universes (`dependency_validator.validate`'s own contract: one
    caller-supplied resolver per kind, not per manifest entry).

    strain-splice-host SSH2.1: `grants[]` is EXTERNAL here too, closed against
    `registries.load_authored_affix_family_ids()` — the SAME corpus `run.granted_family_vocabulary()` draws the
    grants enum from and `validate_entries` below already validates a WRITTEN grant against. Before
    SSH2.1 this preflight carried no grants entry at all (`resolve_hard` was a stub that was "never
    reached"), so a run could silently offer a bad grants enum and this report would say nothing.

    strain-splice-host SSH2.7 (R11): `TARGET_HOST_ROLE` resolves against the REAL base-type corpus
    (`base_type_reach`), not against `tuning.host_roles()` itself. Before SSH2.7 the resolver
    returned `1 if value in host_roles else 0`, which made every offered role pass by construction —
    a role the tuning lifts to four sockets while no shipped base type can hold four (the helm
    between `sockets.v2.json` and SSH5.12's re-stamp) was invisible here. The role now resolves to
    the COUNT of base rows that can host it, so "offered but unhostable" is a real finding and
    `roles_without_a_base` names it."""
    report = supply or supply_mod.build()
    host_roles = tuning.host_roles()
    reach = base_type_reach(base_types_dir)
    granted_families = frozenset(registries.load_materialised_affix_family_ids())
    gem_counts = {family: len(report.bands.get(family, ())) for family in report.families}
    needed = tuning.ingredient_count
    stranded = tuple(sorted(role for role in host_roles if reach.get(role, 0) < needed))

    def resolve_categorical(target_module: str, value: object) -> int:
        if target_module == TARGET_INGREDIENTS:
            return gem_counts.get(str(value), 0)
        if target_module == TARGET_HOST_ROLE:
            return 1 if reach.get(str(value), 0) >= needed else 0
        return 0

    def resolve_hard(target_module: str, value: object) -> bool:
        if target_module == TARGET_GRANTS:
            return value in granted_families
        return False  # no other HARD/EXTERNAL manifest entry reaches here

    entries: "dict[str, dict]" = {f"family:{f}": {"ingredients": [f]} for f in report.families}
    entries.update({f"role:{r}": {"hostRole": r} for r in host_roles})
    entries.update({f"grant:{g}": {"grants": [g]} for g in granted_families})
    manifest = (
        ReferenceManifestEntry("ingredients[]", CATEGORICAL, TARGET_INGREDIENTS),
        ReferenceManifestEntry("hostRole", CATEGORICAL, TARGET_HOST_ROLE),
        ReferenceManifestEntry("grants[]", EXTERNAL, TARGET_GRANTS),
    )
    result = validate(entries, list(manifest), resolve_hard, resolve_categorical)
    return DepsReport(
        ingredient_families_checked=report.family_count,
        host_roles_checked=len(host_roles),
        roles_without_a_base=stranded,
        grants_checked=len(granted_families),
        ingredient_gem_counts=gem_counts,
        result=result,
    )


def validate_entries(entries: "dict[str, dict]", *,
                     supply: "supply_mod.SupplyReport | None" = None,
                     host_roles: "tuple[str, ...] | None" = None,
                     atom_families: "frozenset[str] | None" = None) -> ValidationReport:
    """The per-entry form, run over REAL assembled combinations (`emit.assemble_entry`'s own shape)
    once content exists — `ingredients[].family` and `hostRole` CATEGORICAL against the same live
    corpora `preflight` measured, `grants[]` EXTERNAL against the real production atom catalog
    (`affix-families/**` expanded by `FamilyExpansion`, i.e.
    `registries.load_authored_affix_family_ids()`). A combination whose `hostRole`/family/grant
    nothing satisfies is a real defect this reports on the finished entry, distinct from `preflight`'s pre-generation universe check."""
    report = supply or supply_mod.build()
    roles = host_roles if host_roles is not None else set()
    families = (atom_families if atom_families is not None
                else registries.load_materialised_affix_family_ids())
    gem_counts = {family: len(report.bands.get(family, ())) for family in report.families}

    def resolve_categorical(target_module: str, value: object) -> int:
        if target_module == TARGET_INGREDIENTS:
            return gem_counts.get(str(value), 0)
        if target_module == TARGET_HOST_ROLE:
            return 1 if value in roles else 0
        return 0

    def resolve_hard(target_module: str, value: object) -> bool:
        if target_module == TARGET_GRANTS:
            return value in families
        return False

    return validate(entries, list(ENTRY_MANIFEST), resolve_hard, resolve_categorical)
