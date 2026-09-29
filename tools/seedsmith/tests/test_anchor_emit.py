"""Tests for seedsmith.adapters.creatures.anchor.emit (spec-anchor-emit.md, creature-seed module 8)."""
from __future__ import annotations

import json
from pathlib import Path

from seedsmith.adapters.creatures.anchor.emit import (
    assert_no_magnitude,
    build_index,
    entry_for,
    render_family_file,
    render_index,
    stale_fields,
    stale_ids,
    write_family_file,
)
from seedsmith.adapters.creatures.anchor.provenance import (
    AnchorProvenance,
    PROMPT_VERSIONS,
    ReleadProvenance,
)

ANCHOR_FIELDS = {
    "side": "plant", "speciesId": "peashooter", "gameTypeId": 0,
    "elementPrimary": "earth", "elementSecondary": "none",
    "aptitudePrimary": "Might", "aptitudeSecondary": "none",
    "posture": "Force", "pure": True,
    "threatBand": "nuisance", "rarity": "sprout",
    "deployMode": "PlantAvatar", "acquisition": ["Summonable"],
    "variants": ["normal"], "resourceProfile": ["hp"],
    "basis": "observed", "family": ["plant"], "traits": ["ranged"],
    "attackTempo": "steady", "reach": "long", "targetPreference": "frontline",
}


def make_provenance(*, dump_hash="deadbeef") -> AnchorProvenance:
    return AnchorProvenance(
        dump_hash=dump_hash, prompt_versions=dict(PROMPT_VERSIONS), basis="observed",
        confidence={"elementPrimary": "high"}, minority_values={}, audit_verdict="agree",
        emitted_utc="2026-01-01T00:00:00Z")


# --- entry shape -----------------------------------------------------------------------------


def test_derived_fields_carry_the_derived_marker():
    entry = entry_for("peashooter", ANCHOR_FIELDS, provenance=make_provenance())
    # A CLOSED declaration, not a reading: DERIVED_FIELDS is the set of fields code owns and a
    # human changes by review, so pinning its members is the contract. `speciesKind` joined it
    # 2026-09-17 (creature-seed R-CS4) — "is this row a real creature" is a fact about the corpus,
    # never a model judgement. `rank` joined it 2026-09-23 (spec-species-rank.md §1) — the rung is
    # deterministic code over the resolved (threatBand, rarity) pair, so nothing votes on it.
    assert entry["_derived"] == sorted({"posture", "pure", "basis", "speciesKind", "rank"})
    assert entry["posture"] == "Force"  # still present as a value, just marked whose it is


def test_unresolved_field_is_written_as_unresolved_not_omitted():
    fields = dict(ANCHOR_FIELDS)
    fields["aptitudeSecondary"] = "unresolved"   # a 1-1-1 split (spec-option-permutation.md §4)
    entry = entry_for("peashooter", fields, provenance=make_provenance())
    assert entry["aptitudeSecondary"] == "unresolved"
    assert "aptitudeSecondary" in entry  # never omitted


def test_no_magnitude_appears_in_any_emitted_file():
    entry = entry_for("peashooter", ANCHOR_FIELDS, provenance=make_provenance())
    assert assert_no_magnitude(entry) == []


def test_a_smuggled_magnitude_is_caught():
    fields = dict(ANCHOR_FIELDS)
    fields["hp"] = 300   # would never come from real anchor fields, but the check must catch it
    entry = entry_for("peashooter", fields, provenance=make_provenance())
    assert "hp" in assert_no_magnitude(entry)


def test_gameTypeId_is_the_one_allowed_integer():
    entry = entry_for("peashooter", ANCHOR_FIELDS, provenance=make_provenance())
    assert entry["gameTypeId"] == 0
    assert "gameTypeId" not in assert_no_magnitude(entry)


# --- canonical serialisation + idempotency -----------------------------------------------------


def test_rerun_over_unchanged_dump_is_byte_identical():
    entries = [entry_for("peashooter", ANCHOR_FIELDS, provenance=make_provenance())]
    bytes_a = render_family_file(entries)
    bytes_b = render_family_file(entries)
    assert bytes_a == bytes_b


def test_family_file_is_sorted_by_species_id():
    entries = [
        entry_for("zzz-species", {**ANCHOR_FIELDS, "speciesId": "zzz-species"}, provenance=make_provenance()),
        entry_for("aaa-species", {**ANCHOR_FIELDS, "speciesId": "aaa-species"}, provenance=make_provenance()),
    ]
    rendered = render_family_file(entries)
    text = rendered.decode("utf-8")
    assert text.index('"aaa-species"') < text.index('"zzz-species"')


def test_cjk_names_are_not_escaped_in_emitted_files():
    fields = dict(ANCHOR_FIELDS)
    fields["family"] = ["豌豆"]
    entry = entry_for("peashooter", fields, provenance=make_provenance())
    rendered = render_family_file([entry]).decode("utf-8")
    assert "豌豆" in rendered
    assert "\\u" not in rendered


def test_write_family_file_round_trips_through_disk(tmp_path: Path):
    entries = [entry_for("peashooter", ANCHOR_FIELDS, provenance=make_provenance())]
    path = tmp_path / "plant" / "basic.json"
    write_family_file(path, entries)
    assert path.exists()
    assert path.read_bytes() == render_family_file(entries)


# --- staleness ---------------------------------------------------------------------------------


def test_changed_dump_hash_marks_exactly_the_affected_entries_stale():
    fresh = entry_for("peashooter", ANCHOR_FIELDS, provenance=make_provenance(dump_hash="hash-A"))
    stale = entry_for("sunflower", {**ANCHOR_FIELDS, "speciesId": "sunflower"},
                      provenance=make_provenance(dump_hash="hash-OLD"))
    result = stale_ids([fresh, stale], current_dump_hash="hash-A",
                       current_prompt_versions=dict(PROMPT_VERSIONS))
    assert result == ["sunflower"]


def test_entry_with_no_provenance_is_reported_stale():
    entry = {**ANCHOR_FIELDS}  # no _provenance at all — predates tracking
    result = stale_ids([entry], current_dump_hash="hash-A", current_prompt_versions=dict(PROMPT_VERSIONS))
    assert result == ["peashooter"]


def test_changed_prompt_version_marks_only_that_pipelines_fields():
    entry = entry_for("peashooter", ANCHOR_FIELDS, provenance=make_provenance())
    bumped = dict(PROMPT_VERSIONS)
    bumped["element-primary"] = 2   # only this pipeline's prompt changed
    affected = stale_fields(entry, current_prompt_versions=bumped)
    assert affected == ["elementPrimary"]  # element-primary owns exactly this one field


def test_unchanged_prompt_versions_mark_nothing_stale():
    entry = entry_for("peashooter", ANCHOR_FIELDS, provenance=make_provenance())
    affected = stale_fields(entry, current_prompt_versions=dict(PROMPT_VERSIONS))
    assert affected == []


# --- index ---------------------------------------------------------------------------------


def test_index_resolves_every_species():
    entries_a = [entry_for("peashooter", ANCHOR_FIELDS, provenance=make_provenance())]
    entries_b = [entry_for("wallnut", {**ANCHOR_FIELDS, "speciesId": "wallnut"}, provenance=make_provenance())]
    index = build_index({"plant/basic.json": entries_a, "plant/wall.json": entries_b})
    assert index == {"peashooter": "plant/basic.json", "wallnut": "plant/wall.json"}
    rendered = render_index(index).decode("utf-8")
    assert '"peashooter": "plant/basic.json"' in rendered


# --- provenance.relead (empire-progression EP2.11) --------------------------------------------


def make_relead_block() -> ReleadProvenance:
    return ReleadProvenance(
        from_primary="Might", prompt_version=PROMPT_VERSIONS["aptitude-primary"],
        dump_hash="deadbeef" * 8, votes=("Pierce", "Pierce", "Might"), confidence="split",
        measure_hash="c0ffee00" * 8, outcome="accepted")


def test_a_relead_block_round_trips_through_the_emit_and_the_wire():
    # The block is written INTO the anchor (map D4) and read back by the next run, so the round trip
    # through render/parse is the contract — not the dataclass alone.
    provenance = AnchorProvenance(
        dump_hash="deadbeef" * 8, prompt_versions=dict(PROMPT_VERSIONS), basis="observed",
        confidence={}, minority_values={}, audit_verdict=None, emitted_utc="2026-01-01T00:00:00Z",
        relead=make_relead_block())
    entry = entry_for("peashooter", ANCHOR_FIELDS, provenance=provenance)

    parsed = json.loads(render_family_file([entry]).decode("utf-8"))[0]

    assert parsed["_provenance"]["relead"] == {
        "fromPrimary": "Might", "promptVersion": 1, "dumpHash": "deadbeef" * 8,
        "votes": ["Pierce", "Pierce", "Might"], "confidence": "split",
        "measureHash": "c0ffee00" * 8, "outcome": "accepted",
    }
    assert AnchorProvenance.from_dict(parsed["_provenance"]) == provenance
    # Labels and identifiers only: the magnitude check sees nothing new to complain about.
    assert assert_no_magnitude(parsed) == []


def test_an_anchor_without_a_relead_has_no_relead_key_at_all():
    # Absence, not a null: a pass-1 anchor must gain no claim about a pass that never ran, and a
    # re-emit of an untouched row must not add a `"relead": null` line to every file in the corpus.
    entry = entry_for("peashooter", ANCHOR_FIELDS, provenance=make_provenance())

    assert "relead" not in entry["_provenance"]
    assert AnchorProvenance.from_dict(entry["_provenance"]).relead is None
