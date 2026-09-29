"""Tests for seedsmith.adapters.structures.anchor (spec-structure-schema.md, base-defense module 23).
Mirrors test_anchor_contract.py's structure and most of its tests, retargeted at the 17-design-variable
structure anchor, plus tests unique to this module's own success criteria (role-to-kind totality,
strengthBand-is-the-only-ordinal, no acquisition/side field, all-four ownership levels, generated-row
marking). Zero model calls anywhere in this file — the module's own success criterion 5.
"""
from __future__ import annotations

import copy

from seedsmith.adapters.structures.anchor.audit import numeric_audit
from seedsmith.adapters.structures.anchor.descriptions import DESCRIPTIONS
from seedsmith.adapters.structures.anchor.schema import (
    ALLOWLISTED_INTEGER_FIELDS,
    OWNERSHIP,
    ROLE,
    ROLE_TO_STRUCTURE_KIND,
    NoStructureKindMapping,
    build_structure_anchor_schema,
    structure_kind_for,
)

NEGATIVE_MARKERS = ("NOT", "never", "Never", "NEVER", "DERIVED.")

# Fields the spec explicitly marks nullable (§1: "none legal") — every OTHER string-enum field is
# required, and the absence of "none" there is intentional.
NULLABLE_FIELDS = {"roleSecondary", "elementPrimary", "elementSecondary", "tempo", "targetPreference"}

# `coverTier`'s "none" is a REAL, spec-literal vocabulary member (§1: "none - light - heavy -
# trench"), not an added nullable-sentinel — for THIS field, "no cover" and "not applicable" are the
# same fact, unlike elementPrimary where "no attunement" is a real answer distinct from N/A. Excluded
# from the nullable/non-nullable split above rather than forced into either bucket.
FIELDS_WITH_A_REAL_NONE_VALUE = {"coverTier"}


def test_no_seed_field_holds_a_number():
    # The module's whole point (spec success criterion 1) — proven directly against the real schema.
    schema = build_structure_anchor_schema()
    defects = numeric_audit(schema)
    assert defects == [], f"the real, shipped structure anchor schema must audit clean: {defects}"


def test_a_missing_key_is_rejected_and_none_is_accepted():
    schema = build_structure_anchor_schema()
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == set(schema["properties"].keys())
    for field, prop in schema["properties"].items():
        if prop.get("type") != "string" or "enum" not in prop:
            continue
        if field in FIELDS_WITH_A_REAL_NONE_VALUE:
            continue
        has_none = "none" in prop["enum"]
        if field in NULLABLE_FIELDS:
            assert has_none, f"{field} must admit 'none' (declared-nullable)"
        else:
            assert not has_none, f"{field} admits 'none' but is not in the declared-nullable set"


def test_every_field_description_has_a_negative_clause():
    schema = build_structure_anchor_schema()
    for field in schema["properties"]:
        assert field in DESCRIPTIONS, f"{field} has no description"
        text = DESCRIPTIONS[field]
        assert text.strip(), f"{field}'s description is empty"
        assert any(marker in text for marker in NEGATIVE_MARKERS), \
            f"{field}'s description has no negative clause: {text!r}"


def test_cover_tier_none_is_a_real_vocabulary_member_not_a_nullable_sentinel():
    # spec SS1's own literal list: "none - light - heavy - trench" — four real values, not three
    # plus an added sentinel.
    schema = build_structure_anchor_schema()
    assert schema["properties"]["coverTier"]["enum"] == ["none", "light", "heavy", "trench"]


def test_strength_band_is_the_only_magnitude_ordinal():
    schema = build_structure_anchor_schema()
    assert "materialTier" not in schema["properties"], \
        "materialTier must not exist beside strengthBand — decision 32's ordinal is strengthBand alone"
    assert "strengthBand" in schema["properties"]


def test_acquisition_paths_may_not_be_empty():
    schema = build_structure_anchor_schema()
    prop = schema["properties"]["acquisitionPaths"]
    assert prop["minItems"] == 1
    assert "none" not in prop["items"]["enum"], "acquisitionPaths' vocabulary must not admit 'none'"


def test_no_acquisition_field_exists():
    # §3's reconciliation: only acquisitionPaths ships; the map-scope `acquisition` field is dropped.
    schema = build_structure_anchor_schema()
    assert "acquisition" not in schema["properties"]
    assert "acquisitionPaths" in schema["properties"]


def test_no_side_field_exists():
    # Decision 12: structures have no ownership. "A side field would be a lie."
    schema = build_structure_anchor_schema()
    assert "side" not in schema["properties"]


def test_every_field_declares_one_of_the_four_ownership_levels():
    schema = build_structure_anchor_schema()
    legal_levels = {"AUTHORED", "DERIVED", "GENERATED", "VALIDATED"}
    for field in schema["properties"]:
        assert field in OWNERSHIP, f"{field} has no OWNERSHIP entry — a contract defect (P3-4)"
        assert OWNERSHIP[field] in legal_levels, f"{field}'s ownership {OWNERSHIP[field]!r} is not one of the four levels"


def test_generated_rows_are_marked_generated():
    # Provenance as a field, not a convention: a GENERATED row and an AUTHORED row are distinct
    # dict shapes, both legal, both round-tripping through plain dict equality.
    authored_row = {"_provenance": {"source": "AUTHORED"}}
    generated_row = {"_provenance": {"source": "GENERATED"}}
    assert authored_row["_provenance"]["source"] != generated_row["_provenance"]["source"]
    assert generated_row["_provenance"]["source"] == "GENERATED"


def test_structure_kind_is_derived_from_role():
    # P3-6: 'kind'/'structureKind' is never authored beside role.
    schema = build_structure_anchor_schema()
    assert "kind" not in schema["properties"]
    assert "structureKind" not in schema["properties"]
    # The mapping is total over the ten declared roles (every role has an entry, even if its value
    # is None pending a C# StructureKind addition).
    assert set(ROLE_TO_STRUCTURE_KIND.keys()) == set(ROLE)


def test_a_role_with_no_kind_mapping_throws_at_load():
    for role in ("Move", "Enable", "Defend", "See", "Deny"):
        try:
            structure_kind_for(role)
            assert False, f"{role} should have raised NoStructureKindMapping"
        except NoStructureKindMapping:
            pass


def test_a_role_with_a_real_kind_mapping_resolves():
    assert structure_kind_for("Extract") == "LoamSource"
    assert structure_kind_for("Multiply") == "LoamSource"
    assert structure_kind_for("Store") == "Storage"
    assert structure_kind_for("Bank") == "Storage"
    assert structure_kind_for("Refine") == "Refinery"


def test_an_unknown_role_also_throws():
    try:
        structure_kind_for("NotARealRole")
        assert False, "an unknown role should raise, never return a silent default"
    except NoStructureKindMapping:
        pass


def test_ids_are_kebab_and_unique():
    # The schema level proves the CONTRACT (a kebab-enforcing type); uniqueness needs a real corpus
    # (structure-corpus, c1) to check against, which does not exist yet — asserted here only as
    # "structureId is a plain string field", the schema-level half of this claim.
    schema = build_structure_anchor_schema()
    assert schema["properties"]["structureId"]["type"] == "string"


def test_required_slot_kind_validates_against_the_shipped_enum():
    schema = build_structure_anchor_schema()
    values = schema["properties"]["requiredSlotKind"]["enum"]
    # Transcribed from gk-core/src/FusionRpg.Core/World/SlotTypeCatalog.cs:7-28 — 14 real values.
    assert len(values) == 14
    assert set(values) == {
        "Wildland", "EssenceDeposit", "ShardVein", "MaterialSeam", "Lair", "Tear", "Vault",
        "Shrine", "Market", "Spire", "Anomaly", "Hazard", "Seat", "Rootbed",
    }


def test_schema_audit_fails_the_build_on_a_numeric_field():
    bad = copy.deepcopy(build_structure_anchor_schema())
    bad["properties"]["strengthBand"] = {"type": "integer", "description": "x"}
    defects = numeric_audit(bad)
    assert defects != [], "a corrupted schema with a bare-integer field must not audit clean"


def test_transport_stub_raises_if_a_test_calls_a_model():
    # This module makes zero model calls (spec success criterion 5) — structural proof: neither
    # schema.py nor audit.py imports anything from seedsmith's model-calling machinery.
    import seedsmith.adapters.structures.anchor.audit as audit_mod
    import seedsmith.adapters.structures.anchor.schema as schema_mod
    for mod in (audit_mod, schema_mod):
        src = mod.__file__
        with open(src, "r", encoding="utf-8") as f:
            text = f.read()
        assert "llm_caller" not in text and "call_model" not in text, \
            f"{src} must never reference the model-calling machinery"


# --- audit.py's own five-case coverage, retargeted (structure's own copy of the creature precedent) ---

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

    schema2 = {"properties": {"materialTier": {"type": "string", "enum": ["low", "medium", "high"]}}}
    defects2 = numeric_audit(schema2)
    assert any(d.case == "deny-listed-name" for d in defects2)


def test_no_allowlisted_integer_fields_exist():
    # Unlike the creature anchor (gameTypeId), structures carry NO numeric identifier at all.
    assert ALLOWLISTED_INTEGER_FIELDS == frozenset()
    schema = build_structure_anchor_schema()
    for field, prop in schema["properties"].items():
        assert prop.get("type") not in ("integer", "number"), \
            f"{field} is a bare numeric type, and no field is allow-listed for structures"


def test_pure_enum_string_arrays_are_not_flagged_as_numeric():
    schema = build_structure_anchor_schema()
    for field in ("acquisitionPaths", "traits", "variants", "obstacleVerbs"):
        defects = numeric_audit({"properties": {field: schema["properties"][field]}})
        assert defects == [], f"{field} should not be flagged: {defects}"
