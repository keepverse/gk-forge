"""seedsmith.adapters.items.setgen.topology — the set-planning parser, resolver and validator.

species-gear-chain T27, the `setClass` half (`set-species-binding` a), to
`spec-set-species-binding.md` revision 2 § The set-planning system. One concern, four functions:

| Function | Question it answers |
|---|---|
| `load` | What are the three topology classes, as data? |
| `declared_topology` | What topology does THIS entry declare? (distinct member roles + thresholds) |
| `resolve_class(entry)` | Which class does that topology belong to? — the name the spec's ladder uses |
| `resolve_shape` | The same ladder over a bare shape, for a caller that has no entry |
| `validate_*` | Does the entry's declared topology satisfy its own class? |
| `stamp_class` | Write that class onto an entry — the ONE write path, shared by forward emission and the backward repair |

⛔ **Nothing in this module is a balance number.** The member-role counts and bonus-tier ceilings are
rows of `gk-core/data/tuning/set-topology.v1.json`; the universal "every set has a threshold at 2" rule is
READ from `set-charm-gen.v1.json`'s `setShape.mandatoryThresholdPieces`, which owns it
(`tunables-ssot.md` §2 — a number two domains need belongs to whichever owns the concept, and the
other reads it rather than copying it).

⛔ **The ladder has no default and no fallback.** The classes are tried most-restrictive-first in the
order `resolutionOrder` declares, and a shape no class admits raises `SetTopologyError` naming the
entry and every class's rejection — the same discipline `species_for_theme` already applies to a
`creature.*` themeKey (a defect is an ERROR, never an absent value). A fourth `legacy`/`unclassified`
bucket is exactly what the owner's 2026-09-21 ruling refused.

⚠ **`memberRoleCount` counts DISTINCT ROLES, never raw JSON member rows.** A role may ship one member
row per frame and still contributes one point to the counter (`crafting-coverage-engine.md`;
`ssot-sets.md` §4.5). An eight-row two-frame set is a four-role set, and resolving it as anything else
would misprice every shipped legacy set.

### The closed vocabularies (this module's whole refusal surface)

`thresholdTemplate`: `ascending` | `identity-then-full`.

Rejection / problem codes, each naming one authoring mistake:

| Code | Meaning |
|---|---|
| `no-members` | The entry declares zero member rows, so it has no role count to classify |
| `no-thresholds` | The entry declares zero thresholds — a set with no bonus at all |
| `first-threshold-not-mandatory` | The lowest threshold is not `mandatoryThresholdPieces`, so the first step is invisible |
| `thresholds-not-ascending` | The threshold list is not strictly increasing |
| `top-threshold-above-role-count` | The top threshold can never be reached (`SetThresholdUnreachable`) |
| `member-roles-not-in-class-set` | The class is parameterized (`unique-species`) and this role count is not one of its values |
| `member-roles-below-class-minimum` | The class's lowest member-role count is above this shape's |
| `tier-count-above-class-ceiling` | More cumulative thresholds than the class may expose |
| `threshold-template-mismatch` | The thresholds satisfy the count but not the class's template (`identity-then-full` wants the mandatory first threshold and the final member-role count) |
| `no-class-admits-this-shape` | Every class rejected; the entry cannot be classified at all |
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from .tuning import load as load_set_charm_tuning

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

TUNING_PATH = _owned("data/tuning/set-topology.v1.json")

#: The closed `thresholdTemplate` vocabulary. A new value is a reviewed change to the class design,
#: never a string this module silently ignores.
THRESHOLD_TEMPLATES: "frozenset[str]" = frozenset({"ascending", "identity-then-full"})

#: `identity-then-full`'s shape check: the thresholds are the mandatory first one and the template's
#: own final member-role count, and its length is the class's own ceiling (the design's "always
#: exactly two cumulative thresholds").
TEMPLATE_IDENTITY_THEN_FULL = "identity-then-full"

REASON_NO_MEMBERS = "no-members"
REASON_NO_THRESHOLDS = "no-thresholds"
REASON_FIRST_THRESHOLD_NOT_MANDATORY = "first-threshold-not-mandatory"
REASON_THRESHOLDS_NOT_ASCENDING = "thresholds-not-ascending"
REASON_TOP_THRESHOLD_ABOVE_ROLE_COUNT = "top-threshold-above-role-count"
REASON_ROLES_NOT_IN_CLASS_SET = "member-roles-not-in-class-set"
REASON_ROLES_BELOW_CLASS_MINIMUM = "member-roles-below-class-minimum"
REASON_TIER_COUNT_ABOVE_CEILING = "tier-count-above-class-ceiling"
REASON_THRESHOLD_TEMPLATE_MISMATCH = "threshold-template-mismatch"
REASON_NO_CLASS_ADMITS = "no-class-admits-this-shape"


class SetTopologyError(ValueError):
    """A set whose declared topology no class admits, or a topology file that is structurally
    unusable. Raised at load or at resolve, so the defect lands before a corpus is written."""


@dataclass(frozen=True)
class SetClassRule:
    """One row of `classes[]` — the numbers the 2026-09-10 decision row names, as data."""

    id: str
    member_role_min: int
    member_role_set: "tuple[int, ...]"      # () when the class has no closed parameterization
    bonus_tier_ceiling: int
    threshold_template: str
    note: str = ""

    @property
    def parameterized(self) -> bool:
        return bool(self.member_role_set)


@dataclass(frozen=True)
class SetTopologyTuning:
    resolution_order: "tuple[str, ...]"
    classes: "tuple[SetClassRule, ...]"
    mandatory_first_pieces: int

    @property
    def class_ids(self) -> "tuple[str, ...]":
        return tuple(rule.id for rule in self.classes)

    def klass(self, class_id: str) -> SetClassRule:
        for rule in self.classes:
            if rule.id == class_id:
                return rule
        raise SetTopologyError(
            f"unknown set class {class_id!r} — the classes are {list(self.class_ids)}")


@dataclass(frozen=True)
class DeclaredTopology:
    """What a set entry declares about its own shape: the two inputs the ladder reads."""

    distinct_roles: int
    thresholds: "tuple[int, ...]"


@dataclass(frozen=True)
class ClassResolution:
    """The resolved class, plus every rejection the ladder passed through to get there."""

    class_id: str
    rejected: "tuple[tuple[str, str], ...]"     # ((class_id, reason), ...) in ladder order


def _require(doc: Mapping[str, Any], *path: str):
    node: Any = doc
    for key in path:
        if not isinstance(node, Mapping) or key not in node:
            raise SetTopologyError(
                f"set-topology tuning is missing {'.'.join(path)!r} — refusing to substitute a "
                f"default; an unreviewed class shape here would classify every generated set")
        node = node[key]
    return node


def load(path: "Path | None" = None, *,
         mandatory_first_pieces: "int | None" = None) -> SetTopologyTuning:
    """Parse and validate `gk-core/data/tuning/set-topology.v1.json`.

    `mandatory_first_pieces` defaults to `set-charm-gen.v1.json`'s own
    `setShape.mandatoryThresholdPieces`: the universal threshold-at-2 rule belongs to the set-shape
    domain, and copying it here would be the drift `tunables-ssot.md` §2 names. It is a parameter only
    so a test can prove the reader honours whatever the owning domain publishes.
    """
    doc = json.loads((path or TUNING_PATH).read_text(encoding="utf-8"))

    classes = tuple(
        SetClassRule(
            id=str(row["id"]),
            member_role_min=int(row["memberRoleMin"]),
            member_role_set=tuple(int(v) for v in (row.get("memberRoleSet") or ())),
            bonus_tier_ceiling=int(row["bonusTierCeiling"]),
            threshold_template=str(row["thresholdTemplate"]),
            note=str(row.get("note") or ""),
        )
        for row in _require(doc, "classes")
    )
    if mandatory_first_pieces is None:
        mandatory_first_pieces = load_set_charm_tuning().mandatory_threshold_pieces

    tuning = SetTopologyTuning(
        resolution_order=tuple(str(v) for v in _require(doc, "resolutionOrder")),
        classes=classes,
        mandatory_first_pieces=int(mandatory_first_pieces),
    )
    _validate(tuning)
    return tuning


def _validate(t: SetTopologyTuning) -> None:
    """The structural invariants, each with its own message so an editor reads WHICH one broke.

    Same discipline `tuning._validate` applies to `set-charm-gen.v1.json`, and the same reason: a
    mis-shaped class row classifies generated content silently, and silence is the expensive option.
    """
    if not t.classes:
        raise SetTopologyError("set-topology tuning declares no classes — nothing could be resolved")
    ids = [rule.id for rule in t.classes]
    if len(set(ids)) != len(ids):
        raise SetTopologyError(f"duplicate set class id in {ids}")
    if not t.resolution_order:
        raise SetTopologyError(
            "resolutionOrder is empty — the ladder order is what stops the classes overlapping, so a "
            "file without one cannot resolve a single set")
    if len(set(t.resolution_order)) != len(t.resolution_order):
        raise SetTopologyError(f"duplicate id in resolutionOrder {list(t.resolution_order)}")
    for class_id in t.resolution_order:
        if class_id not in ids:
            raise SetTopologyError(
                f"resolutionOrder names {class_id!r}, which is not a declared class {ids}")
    for class_id in ids:
        if class_id not in t.resolution_order:
            raise SetTopologyError(
                f"class {class_id!r} is not in resolutionOrder {list(t.resolution_order)} — a class "
                "the ladder never tries is a row nothing reads")

    if t.mandatory_first_pieces < 1:
        raise SetTopologyError(
            f"mandatoryThresholdPieces {t.mandatory_first_pieces} cannot be a threshold; ssot-sets "
            "§3.4 requires every set to carry one")

    for rule in t.classes:
        if rule.member_role_min < 1:
            raise SetTopologyError(
                f"class {rule.id!r} has memberRoleMin {rule.member_role_min} — a set has at least one "
                "member role")
        if rule.bonus_tier_ceiling < 1:
            raise SetTopologyError(
                f"class {rule.id!r} has bonusTierCeiling {rule.bonus_tier_ceiling} — a class that may "
                "expose no threshold cannot be the target of a set plan")
        if rule.threshold_template not in THRESHOLD_TEMPLATES:
            raise SetTopologyError(
                f"class {rule.id!r} has thresholdTemplate {rule.threshold_template!r}, which is not "
                f"in the closed vocabulary {sorted(THRESHOLD_TEMPLATES)}")
        if rule.member_role_set:
            if sorted(rule.member_role_set) != list(rule.member_role_set):
                raise SetTopologyError(
                    f"class {rule.id!r} memberRoleSet {list(rule.member_role_set)} is not ascending — "
                    "the smallest legal kit is what the ladder must read first")
            if len(set(rule.member_role_set)) != len(rule.member_role_set):
                raise SetTopologyError(
                    f"class {rule.id!r} repeats a value in memberRoleSet "
                    f"{list(rule.member_role_set)}")
            if min(rule.member_role_set) != rule.member_role_min:
                raise SetTopologyError(
                    f"class {rule.id!r} has memberRoleMin {rule.member_role_min} but its "
                    f"memberRoleSet starts at {min(rule.member_role_set)} — the floor and the "
                    "parameterization must agree, or one of them is dead")
            if rule.threshold_template != TEMPLATE_IDENTITY_THEN_FULL:
                raise SetTopologyError(
                    f"class {rule.id!r} has a closed memberRoleSet but template "
                    f"{rule.threshold_template!r} — a parameterized class's final threshold IS its "
                    "final member-role count, which only identity-then-full can express")
        if (rule.threshold_template == TEMPLATE_IDENTITY_THEN_FULL
                and rule.bonus_tier_ceiling != len(rule.member_role_set)):
            raise SetTopologyError(
                f"class {rule.id!r} is identity-then-full over {list(rule.member_role_set)} but its "
                f"bonusTierCeiling is {rule.bonus_tier_ceiling} — the design fixes exactly as many "
                "thresholds as the parameterization has values")


def declared_topology(entry: Mapping[str, Any]) -> DeclaredTopology:
    """The entry's own declared shape: DISTINCT member roles and the threshold list, in file order.

    Reads nothing else. `identity`, `speciesId`, `themeKey` and the entry's name take no part in the
    class — `setClass` is a topology fact, orthogonal to species
    (`spec-set-species-binding.md` rev 2 § What the class does not decide).
    """
    members = entry.get("members") or ()
    roles = {member.get("role") for member in members
             if isinstance(member, Mapping) and member.get("role")}
    thresholds = tuple(threshold.get("pieces") for threshold in (entry.get("thresholds") or ())
                       if isinstance(threshold, Mapping))
    if not all(isinstance(pieces, int) and not isinstance(pieces, bool) for pieces in thresholds):
        raise SetTopologyError(
            f"set entry {entry.get('id')!r} has a threshold whose `pieces` is not an integer — the "
            "class ladder reads the threshold list directly and will not guess a number")
    return DeclaredTopology(distinct_roles=len(roles), thresholds=thresholds)


def universal_problems(shape: DeclaredTopology, tuning: SetTopologyTuning) -> "tuple[str, ...]":
    """The threshold rules that hold for EVERY class, checked before the ladder.

    `ssot-sets.md` §3.4 states all three as hard rules; a set that breaks one is not a set of some
    class, it is a defect, and resolving a class for it would launder that.
    """
    problems: "list[str]" = []
    if shape.distinct_roles <= 0:
        problems.append(REASON_NO_MEMBERS)
    if not shape.thresholds:
        problems.append(REASON_NO_THRESHOLDS)
        # Every remaining rule is about a list that does not exist; reporting them all would describe
        # one defect five times.
        return tuple(problems)
    if shape.thresholds[0] != tuning.mandatory_first_pieces:
        problems.append(REASON_FIRST_THRESHOLD_NOT_MANDATORY)
    if any(later <= earlier for earlier, later in zip(shape.thresholds, shape.thresholds[1:])):
        problems.append(REASON_THRESHOLDS_NOT_ASCENDING)
    if shape.distinct_roles > 0 and shape.thresholds[-1] > shape.distinct_roles:
        problems.append(REASON_TOP_THRESHOLD_ABOVE_ROLE_COUNT)
    return tuple(problems)


def _class_rejection(shape: DeclaredTopology, rule: SetClassRule,
                     tuning: SetTopologyTuning) -> "str | None":
    """Why `rule` does not admit `shape`, or None when it does. Order is the ladder's, so the reason
    a reader sees is the first rule that actually failed rather than a later coincidence."""
    if rule.parameterized and shape.distinct_roles not in rule.member_role_set:
        return REASON_ROLES_NOT_IN_CLASS_SET
    if shape.distinct_roles < rule.member_role_min:
        return REASON_ROLES_BELOW_CLASS_MINIMUM
    if len(shape.thresholds) > rule.bonus_tier_ceiling:
        return REASON_TIER_COUNT_ABOVE_CEILING
    if rule.threshold_template == TEMPLATE_IDENTITY_THEN_FULL:
        if shape.thresholds != (tuning.mandatory_first_pieces, shape.distinct_roles):
            return REASON_THRESHOLD_TEMPLATE_MISMATCH
    return None


def _ladder(shape: DeclaredTopology, tuning: SetTopologyTuning) -> ClassResolution:
    rejected: "list[tuple[str, str]]" = []
    for class_id in tuning.resolution_order:
        reason = _class_rejection(shape, tuning.klass(class_id), tuning)
        if reason is None:
            return ClassResolution(class_id=class_id, rejected=tuple(rejected))
        rejected.append((class_id, reason))
    raise SetTopologyError(
        f"no set class admits {shape.distinct_roles} distinct member roles with thresholds "
        f"{list(shape.thresholds)}: " + ", ".join(f"{c}: {r}" for c, r in rejected) +
        f" [{[REASON_NO_CLASS_ADMITS]}]")


def validate_shape(shape: DeclaredTopology, tuning: SetTopologyTuning) -> "tuple[str, ...]":
    """Every reason this shape is not a legal set of any class. Empty means it resolves.

    Returns the universal problems when there are any (the ladder is not run against a shape whose
    threshold list is already illegal), otherwise the ladder's own rejection codes plus
    `no-class-admits-this-shape` when every class refused.
    """
    problems = universal_problems(shape, tuning)
    if problems:
        return problems
    try:
        _ladder(shape, tuning)
    except SetTopologyError:
        return (REASON_NO_CLASS_ADMITS,)
    return ()


def resolve_shape(shape: DeclaredTopology, tuning: SetTopologyTuning) -> ClassResolution:
    """The class this shape belongs to, or a refusal naming every class's rejection."""
    problems = universal_problems(shape, tuning)
    if problems:
        raise SetTopologyError(
            f"set topology {shape.distinct_roles} roles / thresholds {list(shape.thresholds)} breaks "
            f"a universal threshold rule: {', '.join(problems)}")
    return _ladder(shape, tuning)


def resolve_class(entry: Mapping[str, Any], tuning: SetTopologyTuning) -> ClassResolution:
    """The class a shipped or freshly emitted `set` entry belongs to.

    The name the spec's own ladder uses (`resolve_class(entry)`), so the code and the spec read alike.

    ❗ The ONE resolver both the emitter (`seedfile.set_entry`) and the backward repair
    (`topology_repair`) call, so a generated entry and a repaired one can never disagree about their
    own class.
    """
    try:
        return resolve_shape(declared_topology(entry), tuning)
    except SetTopologyError as error:
        raise SetTopologyError(f"set entry {entry.get('id')!r}: {error}") from None


def validate_entry(entry: Mapping[str, Any], tuning: SetTopologyTuning) -> "tuple[str, ...]":
    """Every reason this entry cannot be classified, empty when it can. Used by the repair pass, which
    refuses the WHOLE run on a non-empty result rather than writing a class for an illegal shape."""
    return validate_shape(declared_topology(entry), tuning)


def stamp_class(entry: "dict[str, Any]", tuning: SetTopologyTuning) -> str:
    """Resolve `entry`'s class and write it as `setClass`, immediately after `themeKey`.

    ❗ **The ONE write path.** `seedfile.set_entry` (forward emission) and `topology_repair`
    (backward re-plan) both call this, so the class an entry ships with is always the class its own
    declared topology resolves to — the two paths cannot disagree, because there is only one.

    Placing the key beside `themeKey` rather than appending it is not cosmetic: a repair over 910
    shipped entries then diffs as ONE ADDED LINE per entry, which is what makes the corpus diff
    reviewable. Every other key keeps its position. The entry is mutated in place and the class id is
    returned, so a caller can tally without re-resolving.

    A set entry with no `themeKey` refuses: `kinds.py` requires one on kind `set`, so that is a
    malformed entry, not a placement question.
    """
    if "themeKey" not in entry:
        raise SetTopologyError(
            f"set entry {entry.get('id')!r} has no themeKey to place setClass beside — kind `set` "
            "requires one (kinds.py), so this is a malformed entry")
    class_id = resolve_class(entry, tuning).class_id
    ordered: "dict[str, Any]" = {}
    for key, value in entry.items():
        if key == "setClass":
            continue
        ordered[key] = value
        if key == "themeKey":
            ordered["setClass"] = class_id
    entry.clear()
    entry.update(ordered)
    return class_id
