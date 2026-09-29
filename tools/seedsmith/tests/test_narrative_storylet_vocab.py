"""Tests for the storylet vocabulary registries and their readers (NS20, spec-storylet-vocab.md §3).

    python -m pytest gk-forge/tools/seedsmith/tests/test_narrative_storylet_vocab.py -q

The committed registries are the subject: these are authored vocabularies, not generated content, and the
assertions are the CONTRACT (joins, closure, the shape rules, the pinned member lists) — never a row count,
which is a reading.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest  # noqa: E402

from seedsmith.adapters.narrative.storylet_vocab import (  # noqa: E402
    ARG_FAMILIES,
    TEACHING_ORDER,
    CONDITION_ARG_FAMILIES,
    RELATION_FACT_KINDS,
    REQUIREMENT_FAMILIES,
    REQUIREMENT_SHAPE,
    ROLE_KINDS,
    USABLE_IN,
    built_leaves,
    CLIMATES,
    CLIMATE_SOURCES,
    GATES,
    PLACES,
    REGISTRY_DIR,
    STORYLET_KINDS,
    all_defects,
    load_choice_kinds,
    load_choice_patterns,
    load_host_kinds,
    load_conditions,
    load_consequence_kinds,
    load_role_tags,
    load_room_kinds,
    load_teaches,
    load_value_notes,
    loop_headings,
    proposed_leaves,
    requirement_defects,
    validate_conditions,
    validate_consequence_kinds,
    validate_host_kinds,
    validate_role_tags,
    validate_teaches,
    validate_value_notes,
    value_note_sources,
    validate_patterns,
)
from seedsmith.workspace_roots import content_root  # noqa: E402



def test_every_value_has_a_description_and_a_negative():
    rows = load_host_kinds() + load_choice_kinds() + load_choice_patterns()
    assert rows
    for row in rows:
        assert row["description"].strip(), row["id"]
        assert row["negative"].strip(), row["id"]


def test_the_committed_registries_are_clean():
    # A READING on failure: the defect list names the row and the rule.
    assert all_defects() == []


def test_unknown_key_is_refused(tmp_path):
    doc = {"schemaVersion": 1, "registryVersion": 1,
           "hostKinds": [{"id": "x", "place": "delve", "roomKind": "curio", "admits": ["curio"],
                          "climateNeutral": False, "climateSource": "room", "climates": [],
                          "description": "d", "negative": "n", "extra": 1}]}
    path = tmp_path / "host-kinds.v1.json"
    path.write_text(json.dumps(doc), encoding="utf-8")
    with pytest.raises(ValueError, match="unknown key"):
        load_host_kinds(path)

    doc["hostKinds"][0].pop("extra")
    doc["hostKinds"][0].pop("negative")
    path.write_text(json.dumps(doc), encoding="utf-8")
    with pytest.raises(ValueError, match="missing required key"):
        load_host_kinds(path)


def test_host_kinds_join_room_kinds():
    hosts = load_host_kinds()
    room_kinds = load_room_kinds()
    delve = [h for h in hosts if h["place"] == "delve"]
    assert delve, "the Delve hosts are the ones with a room-kind join"
    for host in delve:
        row = room_kinds[host["roomKind"]]
        assert bool(row["climateNeutral"]) == bool(host["climateNeutral"]), host["id"]
    for host in hosts:
        if host["place"] != "delve":
            assert host["roomKind"] == "none", host["id"]
    for host in hosts:
        for kind in host["admits"]:
            assert kind in STORYLET_KINDS, (host["id"], kind)


def test_world_rows_read_sector_climate():
    world = [h for h in load_host_kinds() if h["place"] == "world"]
    assert world, "the eight world hosts exist on the seed side before their runtime does"
    for host in world:
        assert host["climateSource"] == "sector", host["id"]
        assert sorted(host["climates"]) == sorted(CLIMATES), host["id"]
    # R20 retires the sector-type mapping: no registry under _registry/ may map a sector to a climate.
    registry_dir = content_root() / REGISTRY_DIR
    offenders = [p.name for p in registry_dir.glob("*.json")
                 if "sector" in p.name and "climate" in p.name]
    assert offenders == [], f"a sector-climate registry is retired (R20): {offenders}"


def test_climate_sources_are_closed_and_room_rows_carry_no_climates():
    for host in load_host_kinds():
        assert host["climateSource"] in CLIMATE_SOURCES, host["id"]
        if host["climateSource"] != "sector":
            assert host["climates"] == [], host["id"]


def test_patterns_obey_the_shape_rules():
    patterns = load_choice_patterns()
    kinds = load_choice_kinds()
    gates = {row["id"]: row["gate"] for row in kinds}
    assert patterns and kinds
    for pattern in patterns:
        slots = pattern["slots"]
        assert 2 <= len(slots) <= 4, pattern["id"]
        assert [s["position"] for s in slots] == list(range(len(slots))), pattern["id"]
        named = [s["choiceKind"] for s in slots]
        assert len(set(named)) == len(named), pattern["id"]                 # no kind twice
        assert all(1 <= s["outcomes"] <= 3 for s in slots), pattern["id"]
        leaves = [s for s in slots if s["choiceKind"] == "leave"]
        assert len(leaves) == 1 and leaves[0]["outcomes"] == 1, pattern["id"]
        unconditioned = [k for k in named if gates[k] == "none"]
        assert len(unconditioned) == 2, (pattern["id"], unconditioned)
        assert len([k for k in named if gates[k] == "intrinsic"]) <= 2, pattern["id"]
        assert pattern["fitsKinds"], pattern["id"]


def test_every_choice_kind_and_storylet_kind_is_covered_by_a_pattern():
    patterns = load_choice_patterns()
    used = {slot["choiceKind"] for pattern in patterns for slot in pattern["slots"]}
    assert used == {row["id"] for row in load_choice_kinds()}
    fits = {kind for pattern in patterns for kind in pattern["fitsKinds"]}
    assert fits == set(STORYLET_KINDS), sorted(set(STORYLET_KINDS) - fits)


def test_member_lists_are_pinned_declarations():
    assert STORYLET_KINDS == ("curio", "encounter-event", "shrine", "trap", "bargain", "story")
    assert CLIMATES == ("fire", "ice", "air", "earth", "light", "dark", "none")
    assert PLACES == ("delve", "world", "homeworld", "expedition")
    assert CLIMATE_SOURCES == ("room", "sector", "none")
    assert GATES == ("none", "intrinsic")
    assert ARG_FAMILIES == ("none", "supplyTag", "stock", "element")
    assert [row["id"] for row in load_choice_kinds()] == [
        "interact", "leave", "use", "offer", "fight", "bring", "persuade", "threaten"]


def test_a_reader_refuses_a_defect_it_is_handed(tmp_path):
    # The validators are pure over rows, so a planted defect is caught without touching the registry.
    hosts = load_host_kinds()
    room_kinds = load_room_kinds()
    planted = [dict(row) for row in hosts]
    planted[0] = {**planted[0], "climateNeutral": not planted[0]["climateNeutral"]}
    assert any("disagrees with room kind" in d for d in validate_host_kinds(planted, room_kinds))

    patterns = [dict(row) for row in load_choice_patterns()]
    planted_patterns = [dict(row) for row in patterns]
    planted_patterns[0] = {**planted_patterns[0], "slots": [s for s in planted_patterns[0]["slots"][:1]]}
    assert any("outside 2-4" in d for d in validate_patterns(planted_patterns, load_choice_kinds()))


# ---------------------------------------------------------------------------------------------
# NS21 — conditions, consequence kinds, role tags (spec-storylet-vocab.md §3.4-§3.6)
# ---------------------------------------------------------------------------------------------


def test_leaves_are_built_or_proposed_never_both():
    built = built_leaves()
    proposed = proposed_leaves()
    assert len(built) == 16, built           # the runtime's own LeafId, parsed from the C# enum
    assert proposed, proposed                 # the ones this file says are owed to narrative-predicates
    assert not (set(built) & set(proposed)), sorted(set(built) & set(proposed))
    for condition in load_conditions():
        compiles = condition["compilesTo"]
        if condition["id"] == "none" or compiles.startswith("role requirement"):
            continue
        assert compiles in set(built) | set(proposed), (condition["id"], compiles)
    # A planted leaf that is BOTH is reported, so the day the runtime lands a leaf this file is told.
    planted = [{"id": "x", "argFamily": "none", "usableIn": ["slot"], "compilesTo": built[0],
                "description": "d", "negative": "n"}]
    assert any("both built and proposed" in d
               for d in validate_conditions(planted, proposed=[built[0]], built=built))


def test_condition_usable_in_closes():
    for condition in load_conditions():
        assert condition["usableIn"], condition["id"]
        for value in condition["usableIn"]:
            assert value in USABLE_IN, (condition["id"], value)
    by_id = {c["id"]: c for c in load_conditions()}
    assert by_id["story-flag-set"]["usableIn"] == ["slot", "eligibility"]   # both, per §3.4
    assert by_id["doctrine-studying"]["usableIn"] == ["eligibility"]
    assert by_id["none"]["argFamily"] == "none"


def test_arg_families_close():
    assert CONDITION_ARG_FAMILIES == ("none", "dangerBand", "disposition", "characterState",
                                      "storyFlag", "levelGate", "roleId")
    for condition in load_conditions():
        assert condition["argFamily"] in CONDITION_ARG_FAMILIES, condition["id"]
    assert REQUIREMENT_FAMILIES == ("source", "side", "element", "characterRole")


def test_consequence_ref_and_param_rules_close():
    kinds = {k["id"]: k for k in load_consequence_kinds()}
    assert kinds["relation.shift"]["params"] == list(RELATION_FACT_KINDS)
    assert kinds["relation.shift"]["refForms"] and all(":" in f for f in kinds["relation.shift"]["refForms"])
    for kind_id in ("none", "loot", "encounter", "scout"):
        assert kinds[kind_id]["refForms"] == [], kind_id
        assert kinds[kind_id]["params"] == ["none"], kind_id
    for kind_id in ("quest.offer", "story.flag", "recruit", "scene.play"):
        assert kinds[kind_id]["refForms"], kind_id
    assert validate_consequence_kinds(load_consequence_kinds()) == []


def test_consequence_kinds_cover_the_legacy_four():
    ids = {k["id"] for k in load_consequence_kinds()}
    assert {"none", "loot", "encounter", "scout"} <= ids, sorted(ids)
    assert len(load_consequence_kinds()) == 11      # the four plus the seven the runtime routes


def test_role_kinds_admit_none():
    tags = load_role_tags()
    assert [row["id"] for row in tags["roleKinds"]] == ["required", "optional", "forbidden", "none"]
    assert validate_role_tags(tags) == []
    # `none` is present because the structure call picks a role kind and must be able to decline.
    assert "none" in ROLE_KINDS


def test_requires_is_one_string_shape():
    assert REQUIREMENT_SHAPE == "<family>:<value>"
    assert load_role_tags()["requirementShape"] == REQUIREMENT_SHAPE
    assert requirement_defects(["source:party", "side:plant", "element:fire",
                                "characterRole:trader"]) == []
    assert requirement_defects([]) == []                       # empty means no requirement
    for bad in ("trader", "source:", ":party", "faction:party"):
        assert requirement_defects([bad]), bad


# ---------------------------------------------------------------------------------------------
# NS22 — value notes and the `teaches` registry (spec-storylet-vocab.md §3.7-§3.8)
# ---------------------------------------------------------------------------------------------


def test_value_notes_match_their_sources():
    rows = load_value_notes()
    sources = value_note_sources()
    assert validate_value_notes(rows) == []
    # The keys are exactly each source's members plus `none` — proven against the readers, not a copy.
    expected = {f"{lst}.{value}" for lst, members in sources.items() for value in list(members) + ["none"]}
    assert {row["key"] for row in rows} == expected
    # A planted extra key and a planted missing one are both reported.
    assert any("describes no source member" in d
               for d in validate_value_notes(rows + [{"key": "outcomeOrdinal.bogus", "source":
                                                      "outcomeOrdinal", "value": "bogus", "note": "n",
                                                      "negative": "NOT real."}], sources))
    assert any("is missing" in d for d in validate_value_notes(rows[1:], sources))


def test_model_facing_lists_have_none():
    rows = {row["key"] for row in load_value_notes()}
    for lst in value_note_sources():
        assert f"{lst}.none" in rows, lst
    # `none` is a real member of the lists whose model-facing enums carry one.
    for lst in ("conditionArgFamily", "choiceGate"):
        assert "none" not in value_note_sources()[lst], lst          # the source lists exclude it…
        assert f"{lst}.none" in rows, lst                            # …and the notes still carry it
    assert "eventKind.none" in rows


def test_teaches_close_and_order():
    rows = load_teaches()
    assert validate_teaches(rows) == []
    assert [row["value"] for row in rows] == list(TEACHING_ORDER)     # the file's order IS the teaching order
    assert [row["teachingOrder"] for row in rows] == list(range(1, len(rows) + 1))
    headings = loop_headings()
    assert headings, "the loops SSOT must have headings to join against"
    for row in rows:
        assert row["loop"] in headings, row["value"]
        assert row["negative"].strip(), row["value"]
        assert not any(ch.isdigit() for ch in row["teachingLine"]), row["value"]
    # A planted out-of-order row and a planted checkpoint teaching are both reported.
    planted = [dict(row) for row in rows]
    planted[0] = {**planted[0], "teachingOrder": 99}
    assert any("file position" in d for d in validate_teaches(planted, headings))
    planted[0] = {**rows[0], "teachingLine": "This is the first-session checkpoint, level 3."}
    planted_defects = validate_teaches(planted, headings)
    assert any("checkpoint" in d for d in planted_defects)
    assert any("digit" in d for d in planted_defects)
