"""seedsmith T27 (`set-species-binding` a, `setClass` half) — the set-planning classes.

    python -m pytest gk-forge/tools/seedsmith/tests/test_set_topology.py -q

The ladder is the whole contract: a set's class is resolved from its own DECLARED topology — the count
of distinct member roles and the threshold list — most-restrictive-first, with no default and no
fallback. Almost every assertion here is therefore a shape in, a class (or a refusal reason) out.

⛔ **Nothing here pins a population.** The shipped tally (how many sets are `general`, how many
`family`) is a READING that moves whenever content ships; `test_report_prints_the_shipped_tally_as_a_
reading` prints it and asserts only the closure property — every shipped entry resolves, and every
resolved entry satisfies its own class. Same rule `test_themes_v2.py` and the species-repair tests
already follow.
"""
from __future__ import annotations

import collections
import copy
import glob
import json
from pathlib import Path

import pytest

from seedsmith.adapters.items.setgen import topology as topology_mod
from seedsmith.adapters.items.setgen import tuning as set_charm_tuning_mod

REPO_ROOT = Path(__file__).resolve().parents[3]
SETS_DIR = REPO_ROOT / "data" / "seed" / "items" / "sets"

#: The three classes `decisions.md`'s 2026-09-10 row names. A CLOSED vocabulary the design owns — the
#: owner's 2026-09-21 ruling refused a fourth bucket — so pinning it is pinning the contract.
CLOSED_CLASS_IDS = frozenset({"general", "family", "unique-species"})


def _shape(distinct_roles: int, thresholds: "tuple[int, ...]") -> topology_mod.DeclaredTopology:
    return topology_mod.DeclaredTopology(distinct_roles=distinct_roles, thresholds=thresholds)


def _entry(entry_id: str, roles: "list[str]", thresholds: "tuple[int, ...]") -> dict:
    return {
        "id": entry_id,
        "members": [{"role": role, "frame": "plant", "baseType": f"item.{role}"} for role in roles],
        "thresholds": [{"pieces": pieces} for pieces in thresholds],
    }


def _shipped_entries() -> "list[tuple[Path, dict]]":
    out: "list[tuple[Path, dict]]" = []
    for name in sorted(glob.glob(str(SETS_DIR / "*.json"))):
        path = Path(name)
        document = json.loads(path.read_text(encoding="utf-8"))
        if document.get("kind") != "set":
            continue
        for entry in document.get("entries") or ():
            out.append((path, entry))
    return out


# --------------------------------------------------------------------------------------------
# the tuning file, as data
# --------------------------------------------------------------------------------------------


def test_the_real_tuning_file_loads_and_declares_the_closed_vocabulary():
    tuning = topology_mod.load()
    assert set(tuning.class_ids) == CLOSED_CLASS_IDS


def test_every_declared_class_is_in_the_ladder_and_the_ladder_only_names_declared_classes():
    tuning = topology_mod.load()
    assert set(tuning.resolution_order) == set(tuning.class_ids)
    assert len(tuning.resolution_order) == len(set(tuning.resolution_order))


def test_the_ladder_is_most_restrictive_first():
    """`unique-species` is a closed parameterization, so it must be tried before the classes whose
    floor is lower — otherwise a ten-role kit would resolve `general` and the class would be dead."""
    tuning = topology_mod.load()
    order = list(tuning.resolution_order)
    assert order.index("unique-species") < order.index("family") < order.index("general")


def test_the_class_numbers_are_the_decision_rows_numbers():
    """Pins the DESIGN, not a population: `decisions.md` 2026-09-10 fixes general 2 / family 5 /
    unique-species 10-or-15, with four / three / exactly-two bonus tiers."""
    tuning = topology_mod.load()
    assert tuning.klass("general").member_role_min == 2
    assert tuning.klass("general").bonus_tier_ceiling == 4
    assert tuning.klass("family").member_role_min == 5
    assert tuning.klass("family").bonus_tier_ceiling == 3
    assert tuning.klass("unique-species").member_role_set == (10, 15)
    assert tuning.klass("unique-species").bonus_tier_ceiling == 2
    assert tuning.klass("general").member_role_set == ()
    assert tuning.klass("family").member_role_set == ()


def test_the_mandatory_first_threshold_is_read_from_its_owning_domain_never_copied():
    """`set-charm-gen` owns `setShape.mandatoryThresholdPieces`; the topology file must not restate it.
    Proved twice: the default agrees with the owner, and an explicit override is honoured."""
    tuning = topology_mod.load()
    assert tuning.mandatory_first_pieces == set_charm_tuning_mod.load().mandatory_threshold_pieces

    overridden = topology_mod.load(mandatory_first_pieces=3)
    assert overridden.mandatory_first_pieces == 3
    assert topology_mod.resolve_shape(_shape(4, (3, 4)), overridden).class_id == "general"


def test_the_topology_file_does_not_restate_the_mandatory_threshold():
    """The rule is READ from `set-charm-gen.v1.json`, so the KEY must not exist here — prose in
    `_meta.note` naming the owner's key is what keeps the two from drifting silently."""
    document = json.loads(topology_mod.TUNING_PATH.read_text(encoding="utf-8"))

    def keys(node):
        if isinstance(node, dict):
            for key, value in node.items():
                yield key
                yield from keys(value)
        elif isinstance(node, list):
            for value in node:
                yield from keys(value)

    assert "mandatoryThresholdPieces" not in set(keys(document))
    assert "setShape" not in set(keys(document))


def test_a_missing_key_refuses_rather_than_defaulting(tmp_path):
    document = json.loads(topology_mod.TUNING_PATH.read_text(encoding="utf-8"))
    del document["classes"]
    path = tmp_path / "set-topology.v1.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(topology_mod.SetTopologyError) as caught:
        topology_mod.load(path)
    assert "classes" in str(caught.value)


def test_an_unknown_threshold_template_refuses_naming_the_vocabulary(tmp_path):
    document = json.loads(topology_mod.TUNING_PATH.read_text(encoding="utf-8"))
    document["classes"][-1]["thresholdTemplate"] = "whatever-seems-reasonable"
    path = tmp_path / "set-topology.v1.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(topology_mod.SetTopologyError) as caught:
        topology_mod.load(path)
    assert "ascending" in str(caught.value)


def test_a_class_missing_from_the_ladder_refuses(tmp_path):
    document = json.loads(topology_mod.TUNING_PATH.read_text(encoding="utf-8"))
    document["classes"].append({"id": "orphan", "memberRoleMin": 1, "bonusTierCeiling": 1,
                                "thresholdTemplate": "ascending"})
    path = tmp_path / "set-topology.v1.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(topology_mod.SetTopologyError) as caught:
        topology_mod.load(path)
    assert "resolutionOrder" in str(caught.value)


def test_a_parameterized_class_must_have_exactly_as_many_thresholds_as_values(tmp_path):
    document = json.loads(topology_mod.TUNING_PATH.read_text(encoding="utf-8"))
    for row in document["classes"]:
        if row["id"] == "unique-species":
            row["bonusTierCeiling"] = 1
    path = tmp_path / "set-topology.v1.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(topology_mod.SetTopologyError) as caught:
        topology_mod.load(path)
    assert "identity-then-full" in str(caught.value)


# --------------------------------------------------------------------------------------------
# the ladder
# --------------------------------------------------------------------------------------------


def test_a_four_role_two_tier_set_resolves_general():
    tuning = topology_mod.load()
    assert topology_mod.resolve_shape(_shape(4, (2, 4)), tuning).class_id == "general"


def test_a_six_role_three_tier_set_resolves_family():
    tuning = topology_mod.load()
    assert topology_mod.resolve_shape(_shape(6, (2, 4, 6)), tuning).class_id == "family"
    assert topology_mod.resolve_shape(_shape(6, (2, 3, 4)), tuning).class_id == "family"


def test_family_is_tried_before_general_so_its_band_wins():
    """A five-role shape is legal for both classes; the ladder's order is what decides, and the
    rejection trace shows only `unique-species` was tried first."""
    tuning = topology_mod.load()
    resolution = topology_mod.resolve_shape(_shape(5, (2, 4)), tuning)
    assert resolution.class_id == "family"
    assert resolution.rejected == (("unique-species", topology_mod.REASON_ROLES_NOT_IN_CLASS_SET),)


def test_a_six_role_four_tier_set_resolves_general_above_the_family_ceiling():
    tuning = topology_mod.load()
    resolution = topology_mod.resolve_shape(_shape(6, (2, 3, 4, 5)), tuning)
    assert resolution.class_id == "general"
    assert resolution.rejected == (("unique-species", topology_mod.REASON_ROLES_NOT_IN_CLASS_SET),
                                   ("family", topology_mod.REASON_TIER_COUNT_ABOVE_CEILING))


def test_the_ten_role_signature_kit_resolves_unique_species():
    tuning = topology_mod.load()
    assert topology_mod.resolve_shape(_shape(10, (2, 10)), tuning).class_id == "unique-species"


def test_the_fifteen_role_complete_kit_resolves_unique_species():
    tuning = topology_mod.load()
    assert topology_mod.resolve_shape(_shape(15, (2, 15)), tuning).class_id == "unique-species"


def test_the_unique_species_parameterization_is_closed_never_a_floor():
    """Twelve roles is not a unique-species kit: the design's ten and fifteen are an enumeration, and
    a floor reading would let any twelve-role set claim the species-bound class."""
    tuning = topology_mod.load()
    resolution = topology_mod.resolve_shape(_shape(12, (2, 12)), tuning)
    assert resolution.class_id == "family"
    assert resolution.rejected == (("unique-species", topology_mod.REASON_ROLES_NOT_IN_CLASS_SET),)


def test_a_ten_role_set_with_three_thresholds_is_not_a_unique_species_kit():
    tuning = topology_mod.load()
    resolution = topology_mod.resolve_shape(_shape(10, (2, 4, 6)), tuning)
    assert resolution.class_id == "family"
    assert resolution.rejected == (("unique-species", topology_mod.REASON_TIER_COUNT_ABOVE_CEILING),)


def test_a_ten_role_set_whose_second_threshold_is_not_its_role_count_is_not_a_unique_species_kit():
    """`identity-then-full` is the design's (mandatory first, final role count), so (2, 8) over ten
    roles is a two-threshold set that is not the kit. It falls to `family`, and the rejection says
    exactly which class and why."""
    tuning = topology_mod.load()
    resolution = topology_mod.resolve_shape(_shape(10, (2, 8)), tuning)
    assert resolution.class_id == "family"
    assert resolution.rejected == (
        ("unique-species", topology_mod.REASON_THRESHOLD_TEMPLATE_MISMATCH),)


def test_distinct_roles_are_counted_not_member_rows():
    """⭐ The trap this module counts around. A role ships one row per frame, so an eight-row two-frame
    set is a FOUR-role set — reading rows instead would resolve it `family` and misprice every
    shipped legacy set."""
    tuning = topology_mod.load()
    entry = _entry("set.two-frame-001",
                   roles=["armament-primary"] * 2 + ["core-guard"] * 2
                         + ["jewel-major"] * 2 + ["manipulator"] * 2,
                   thresholds=(2, 4))
    assert len(entry["members"]) == 8
    assert topology_mod.declared_topology(entry).distinct_roles == 4
    assert topology_mod.resolve_class(entry, tuning).class_id == "general"


def test_a_duplicated_role_row_never_inflates_the_count():
    tuning = topology_mod.load()
    entry = _entry("set.dupe-role-001",
                   roles=["armament-primary", "armament-primary", "core-guard", "core-guard",
                          "jewel-major", "jewel-major", "manipulator", "manipulator",
                          "infusion"],
                   thresholds=(2, 5))
    assert topology_mod.declared_topology(entry).distinct_roles == 5
    assert topology_mod.resolve_class(entry, tuning).class_id == "family"


# --------------------------------------------------------------------------------------------
# refusals — the ladder has no default and no fallback
# --------------------------------------------------------------------------------------------


def test_a_first_threshold_below_the_mandatory_one_refuses():
    tuning = topology_mod.load()
    with pytest.raises(topology_mod.SetTopologyError) as caught:
        topology_mod.resolve_shape(_shape(4, (3, 4)), tuning)
    assert topology_mod.REASON_FIRST_THRESHOLD_NOT_MANDATORY in str(caught.value)
    assert topology_mod.validate_shape(_shape(4, (3, 4)), tuning) == (
        topology_mod.REASON_FIRST_THRESHOLD_NOT_MANDATORY,)


def test_a_non_ascending_threshold_list_refuses():
    tuning = topology_mod.load()
    assert topology_mod.validate_shape(_shape(4, (2, 2)), tuning) == (
        topology_mod.REASON_THRESHOLDS_NOT_ASCENDING,)


def test_a_top_threshold_above_the_role_count_refuses():
    tuning = topology_mod.load()
    assert topology_mod.validate_shape(_shape(4, (2, 6)), tuning) == (
        topology_mod.REASON_TOP_THRESHOLD_ABOVE_ROLE_COUNT,)


def test_a_five_threshold_set_refuses_because_no_class_admits_the_shape():
    tuning = topology_mod.load()
    assert topology_mod.validate_shape(_shape(6, (2, 3, 4, 5, 6)), tuning) == (
        topology_mod.REASON_NO_CLASS_ADMITS,)
    with pytest.raises(topology_mod.SetTopologyError) as caught:
        topology_mod.resolve_shape(_shape(6, (2, 3, 4, 5, 6)), tuning)
    message = str(caught.value)
    assert topology_mod.REASON_NO_CLASS_ADMITS in message
    assert "general" in message and "family" in message and "unique-species" in message


def test_a_below_floor_role_count_is_rejected_by_name_on_the_way_up_the_ladder():
    """A four-role shape is refused by `family` for being under its floor while `general` admits it,
    so the floor is a real, reachable rejection rather than a claim in a table.

    ⚠ `no-class-admits-this-shape` is NOT reachable through a role floor: the universal
    threshold-at-2 rule already forces a set to carry at least two roles, which is `general`'s own
    floor. It is reachable through the tier ceiling, which `test_a_five_threshold_set_...` covers —
    so the unreachable branch is named here rather than left as a silent dead reason."""
    tuning = topology_mod.load()
    resolution = topology_mod.resolve_shape(_shape(4, (2, 4)), tuning)
    assert resolution.class_id == "general"
    assert ("family", topology_mod.REASON_ROLES_BELOW_CLASS_MINIMUM) in resolution.rejected
    assert ("unique-species", topology_mod.REASON_ROLES_NOT_IN_CLASS_SET) in resolution.rejected


def test_no_members_and_no_thresholds_each_refuse_by_name():
    tuning = topology_mod.load()
    assert topology_mod.validate_shape(_shape(0, (2,)), tuning) == (
        topology_mod.REASON_NO_MEMBERS,)
    assert topology_mod.validate_shape(_shape(4, ()), tuning) == (
        topology_mod.REASON_NO_THRESHOLDS,)


def test_a_refusal_names_the_entry_and_every_class_that_refused_it():
    tuning = topology_mod.load()
    entry = _entry("set.hopeless-001",
                   roles=["a", "b", "c", "d", "e", "f"],
                   thresholds=(2, 3, 4, 5, 6))
    with pytest.raises(topology_mod.SetTopologyError) as caught:
        topology_mod.resolve_class(entry, tuning)
    message = str(caught.value)
    assert "set.hopeless-001" in message
    assert "unique-species" in message


def test_a_non_integer_threshold_refuses_rather_than_coercing():
    tuning = topology_mod.load()
    entry = {"id": "set.bad-threshold-001",
             "members": [{"role": "core-guard"}],
             "thresholds": [{"pieces": "2"}, {"pieces": 4}]}
    with pytest.raises(topology_mod.SetTopologyError) as caught:
        topology_mod.declared_topology(entry)
    assert "set.bad-threshold-001" in str(caught.value)


# --------------------------------------------------------------------------------------------
# the shipped corpus — closure properties, and one printed reading
# --------------------------------------------------------------------------------------------


def test_every_shipped_set_entry_resolves_to_exactly_one_class():
    tuning = topology_mod.load()
    entries = _shipped_entries()
    assert entries, "no shipped set entries found — the corpus path moved"
    for path, entry in entries:
        problems = topology_mod.validate_entry(entry, tuning)
        assert problems == (), f"{path.name}:{entry.get('id')} cannot be classified: {problems}"
        resolution = topology_mod.resolve_class(entry, tuning)
        assert resolution.class_id in tuning.class_ids


def test_every_shipped_set_entry_satisfies_its_own_class_template():
    tuning = topology_mod.load()
    for path, entry in _shipped_entries():
        shape = topology_mod.declared_topology(entry)
        rule = tuning.klass(topology_mod.resolve_class(entry, tuning).class_id)
        if rule.parameterized:
            assert shape.distinct_roles in rule.member_role_set, f"{path.name}:{entry['id']}"
        assert shape.distinct_roles >= rule.member_role_min, f"{path.name}:{entry['id']}"
        assert len(shape.thresholds) <= rule.bonus_tier_ceiling, f"{path.name}:{entry['id']}"
        assert shape.thresholds[0] == tuning.mandatory_first_pieces, f"{path.name}:{entry['id']}"


def test_resolution_is_deterministic_and_order_independent():
    """Same entry, same class — twice, and with the member rows reversed. No RNG, no model, no
    dependence on the order a file happens to list its members in."""
    tuning = topology_mod.load()
    entry = _entry("set.determinism-001", roles=["a", "b", "c", "d", "e"], thresholds=(2, 4))
    shuffled = copy.deepcopy(entry)
    shuffled["members"].reverse()
    first = topology_mod.resolve_class(entry, tuning)
    assert first.class_id == topology_mod.resolve_class(entry, tuning).class_id
    assert first.class_id == topology_mod.resolve_class(shuffled, tuning).class_id


def test_report_prints_the_shipped_tally_as_a_reading():
    """⭐ A READING, printed and never asserted: the shipped corpus moves whenever content ships, so a
    test pinning `general 906` would fail on the normal case and its "fix" would be to bump a number.
    The closure properties above are the assertions; this is the number a human reads."""
    tuning = topology_mod.load()
    tally: "collections.Counter[str]" = collections.Counter()
    by_prefix: "dict[str, collections.Counter[str]]" = collections.defaultdict(collections.Counter)
    for _path, entry in _shipped_entries():
        class_id = topology_mod.resolve_class(entry, tuning).class_id
        tally[class_id] += 1
        by_prefix[str(entry.get("themeKey", "")).partition(".")[0]][class_id] += 1
    print("\nset-topology reading (printed, not asserted):")
    for class_id in tuning.class_ids:
        print(f"  {class_id:<15} {tally.get(class_id, 0)}")
    for prefix in sorted(by_prefix):
        print(f"  by theme prefix {prefix!r}: {dict(by_prefix[prefix])}")
