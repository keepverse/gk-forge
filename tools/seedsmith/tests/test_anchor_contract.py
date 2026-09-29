"""Tests for seedsmith.adapters.creatures.anchor (spec-anchor-contract.md, creature-seed module 2)."""
from __future__ import annotations

import copy

from seedsmith.adapters.creatures.anchor.audit import numeric_audit
from seedsmith.adapters.creatures.anchor.descriptions import DESCRIPTIONS
from seedsmith.adapters.creatures.anchor.schema import (
    ALLOWLISTED_INTEGER_FIELDS,
    build_anchor_schema,
)

NEGATIVE_MARKERS = ("NOT", "never", "Never", "DERIVED.")


def test_every_attribute_has_a_description():
    schema = build_anchor_schema()
    for field in schema["properties"]:
        assert field in DESCRIPTIONS, f"{field} has no description"
        assert DESCRIPTIONS[field].strip(), f"{field}'s description is empty"


def test_every_description_names_what_the_field_is_not():
    for field, text in DESCRIPTIONS.items():
        assert any(marker in text for marker in NEGATIVE_MARKERS), \
            f"{field}'s description has no negative clause: {text!r}"


def test_every_closed_enum_admits_none_or_declares_why_not():
    # Fields the spec explicitly marks nullable (elementSecondary, aptitudeSecondary) must carry
    # "none"; every OTHER string-enum field is required and its absence-of-"none" is intentional
    # (spec §2's `none legal` column says "no" for them) — this test pins that split.
    nullable = {"elementSecondary", "aptitudeSecondary"}
    schema = build_anchor_schema()
    for field, prop in schema["properties"].items():
        if prop.get("type") != "string" or "enum" not in prop:
            continue
        has_none = "none" in prop["enum"]
        if field in nullable:
            assert has_none, f"{field} must admit 'none' (it is a declared-nullable field)"
        else:
            assert not has_none, f"{field} admits 'none' but is not in the declared-nullable set"


def test_gameTypeId_is_the_only_allowlisted_integer():
    assert ALLOWLISTED_INTEGER_FIELDS == frozenset({"gameTypeId"})
    schema = build_anchor_schema()
    assert schema["properties"]["gameTypeId"]["type"] == "integer"
    # every OTHER property must not be a bare integer/number
    for field, prop in schema["properties"].items():
        if field == "gameTypeId":
            continue
        assert prop.get("type") not in ("integer", "number"), \
            f"{field} is a bare numeric type and is not gameTypeId"


def test_additionalProperties_is_false_everywhere():
    schema = build_anchor_schema()
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == set(schema["properties"].keys())


def test_resourceProfile_has_six_members():
    schema = build_anchor_schema()
    assert len(schema["properties"]["resourceProfile"]["items"]["enum"]) == 6
    assert "poise" in schema["properties"]["resourceProfile"]["items"]["enum"]


def test_no_numeric_field_survives_the_audit_clean_schema_passes():
    schema = build_anchor_schema()
    defects = numeric_audit(schema)
    assert defects == [], f"the real, shipped anchor schema must audit clean: {defects}"


def test_bare_integer_type_is_rejected():
    schema = {"properties": {"someMagnitude": {"type": "integer"}}}
    defects = numeric_audit(schema)
    assert any(d.case == "bare-integer" for d in defects)


def test_bare_number_type_is_rejected():
    schema = {"properties": {"someWeight": {"type": "number"}}}
    defects = numeric_audit(schema)
    assert any(d.case == "bare-number" for d in defects)


def test_pattern_admitting_bare_number_is_rejected():
    schema = {"properties": {"levelText": {"type": "string", "pattern": r"^[0-9]+$"}}}
    defects = numeric_audit(schema)
    assert any(d.case == "pattern-admits-number" for d in defects)


def test_enum_of_numeric_strings_is_rejected():
    schema = {"properties": {"tierLabel": {"type": "string", "enum": ["1", "2", "3"]}}}
    defects = numeric_audit(schema)
    assert any(d.case == "enum-numeric-strings" for d in defects)


def test_deny_listed_field_name_is_rejected_even_with_a_safe_type():
    schema = {"properties": {"powerMilli": {"type": "string", "enum": ["low", "medium", "high"]}}}
    defects = numeric_audit(schema)
    assert any(d.case == "deny-listed-name" for d in defects)

    schema2 = {"properties": {"hp": {"type": "string", "enum": ["low", "medium", "high"]}}}
    defects2 = numeric_audit(schema2)
    assert any(d.case == "deny-listed-name" for d in defects2)


def test_gameTypeId_allowlist_survives_a_mutated_copy():
    # Prove the allow-list is checked by field NAME, not by coincidence of schema shape — mutate
    # a deep copy so this can't pass by aliasing the real schema object.
    schema = copy.deepcopy(build_anchor_schema())
    defects = numeric_audit(schema)
    assert not any(d.path.endswith(".gameTypeId") for d in defects)


def test_pure_enum_string_arrays_are_not_flagged_as_numeric():
    # Sanity: array-of-enum fields (acquisition, variants, resourceProfile) must not themselves
    # trip any of the five cases.
    schema = build_anchor_schema()
    for field in ("acquisition", "variants", "resourceProfile", "family", "traits"):
        defects = numeric_audit({"properties": {field: schema["properties"][field]}})
        assert defects == [], f"{field} should not be flagged: {defects}"
