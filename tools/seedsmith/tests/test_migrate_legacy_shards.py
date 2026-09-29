"""Tests for `recipegen.migrate_legacy_shards` — the fix for the "real, already-tracked" finding
`recipegen/run.py`'s own module docstring named (2026-09-07): seven pre-existing, hand-authored cost
lines in the real recipes corpus name a legacy, retired shard band id, refused at real C# import time
(`MaterialCatalog.IsLegacyShardId` / `MaterialUnissuableRule`).

Mapping mirrors `LegacyCreatureRarityIds.ForwardMap` (`gk-core/src/FusionRpg.Core/Creatures/CreatureRarity.cs:94-99`),
verified live in this session: common->chaff, rare->cultivated, epic->heirloom, legendary->sunwoven.
"""
from __future__ import annotations

import json

import pytest

from seedsmith.adapters.items.materialgen import vocab as material_vocab
from seedsmith.adapters.items.recipegen import migrate_legacy_shards as mod
from seedsmith.adapters.items.recipegen import run as run_mod


def _doc(entries):
    return {
        "schemaVersion": 1, "kind": "recipe",
        "_meta": {"batch": "b", "partition": "recipes", "contractVersion": 1,
                  "authoredUtc": "2026-01-01T00:00:00Z", "sourceRef": "x"},
        "entries": entries,
    }


def _entry(entry_id, *materials):
    return {
        "id": entry_id, "operation": "elevate",
        "costLines": [{"material": m, "costBand": "standard"} for m in materials],
    }


# ---------------------------------------------------------------------------------------------
# Mapping — a pure mirror of the one C# source of truth, never re-derived
# ---------------------------------------------------------------------------------------------


def test_forward_map_matches_LegacyCreatureRarityIds_exactly():
    assert mod.LEGACY_SHARD_FORWARD_MAP == {
        "common": "chaff", "rare": "cultivated", "epic": "heirloom", "legendary": "sunwoven",
    }


def test_every_migrated_target_is_a_real_issuable_shard_id():
    for legacy, new_rung in mod.LEGACY_SHARD_FORWARD_MAP.items():
        assert material_vocab.is_legacy_shard_id(f"shard.{legacy}")
        assert material_vocab.is_issuable(f"shard.{new_rung}")


# ---------------------------------------------------------------------------------------------
# Detect
# ---------------------------------------------------------------------------------------------


def test_detects_a_legacy_cost_line_by_entry_and_index():
    doc = _doc([_entry("recipe.x", "substrate.plant.sound", "shard.rare", "catalyst.temper")])
    findings = mod.find_legacy_shard_cost_lines(doc)
    assert len(findings) == 1
    f = findings[0]
    assert (f.entry_id, f.cost_line_index, f.legacy_material, f.migrated_material) == (
        "recipe.x", 1, "shard.rare", "shard.cultivated")


def test_a_clean_corpus_with_only_real_issuable_shard_ids_finds_nothing():
    doc = _doc([_entry("recipe.x", "shard.sprout", "catalyst.forge")])
    assert mod.find_legacy_shard_cost_lines(doc) == []


def test_an_entry_with_no_cost_lines_at_all_is_skipped_without_error():
    doc = _doc([{"id": "recipe.bare", "operation": "socket"}])
    assert mod.find_legacy_shard_cost_lines(doc) == []


def test_the_real_shipped_corpus_is_already_clean_of_legacy_shard_ids():
    """Regression guard: the seven real refusals (`recipe.009`/`010`/`011`/`017`/`018`/`025`/`029`)
    were fixed in place by running this module's own `apply_to_real_corpus` against the real file
    (2026-09-07) — see its `_meta.amendments` entry `recipegen/legacy-shard-migration-1`. A future
    regression (a hand-edit reintroducing a legacy shard id) should fail this test, not silently
    ship."""
    doc = json.loads(run_mod.RECIPES_CORPUS_PATH.read_text(encoding="utf-8"))
    assert mod.find_legacy_shard_cost_lines(doc) == []


# ---------------------------------------------------------------------------------------------
# Fix
# ---------------------------------------------------------------------------------------------


def test_migrate_rewrites_only_the_legacy_cost_lines():
    doc = _doc([_entry("recipe.x", "substrate.plant.sound", "shard.rare", "catalyst.temper")])
    new_doc, findings = mod.migrate_legacy_shard_ids(doc)
    assert len(findings) == 1
    new_cost_lines = new_doc["entries"][0]["costLines"]
    assert [c["material"] for c in new_cost_lines] == [
        "substrate.plant.sound", "shard.cultivated", "catalyst.temper"]
    # untouched sibling field on the same cost line survives the rewrite
    assert new_cost_lines[1]["costBand"] == "standard"


def test_migrate_is_a_no_op_on_an_already_clean_corpus():
    doc = _doc([_entry("recipe.x", "shard.sprout")])
    new_doc, findings = mod.migrate_legacy_shard_ids(doc)
    assert findings == []
    assert new_doc == doc


def test_migrate_never_mutates_the_input_doc_in_place():
    doc = _doc([_entry("recipe.x", "shard.epic")])
    before = json.loads(json.dumps(doc))  # deep copy for comparison
    mod.migrate_legacy_shard_ids(doc)
    assert doc == before


def test_migrate_leaves_entries_with_no_legacy_cost_lines_untouched_by_identity():
    clean_entry = _entry("recipe.clean", "shard.almanac")
    doc = _doc([clean_entry, _entry("recipe.dirty", "shard.common")])
    new_doc, _ = mod.migrate_legacy_shard_ids(doc)
    assert new_doc["entries"][0] is clean_entry  # untouched entries are not even copied


def test_re_running_migrate_on_its_own_output_finds_nothing_left():
    doc = _doc([_entry("recipe.x", "shard.common", "shard.rare", "shard.epic", "shard.legendary")])
    once, findings1 = mod.migrate_legacy_shard_ids(doc)
    assert len(findings1) == 4
    twice, findings2 = mod.migrate_legacy_shard_ids(once)
    assert findings2 == []
    assert twice == once


# ---------------------------------------------------------------------------------------------
# Apply to the real corpus file (round-trip via tmp_path, never the real repo file in a test)
# ---------------------------------------------------------------------------------------------


def test_apply_to_real_corpus_writes_the_fix_and_records_an_amendment(tmp_path):
    src = tmp_path / "recipes.json"
    src.write_text(json.dumps(_doc([
        _entry("recipe.a", "shard.common"),
        _entry("recipe.b", "substrate.humanoid.crude"),
    ])), encoding="utf-8")

    findings = mod.apply_to_real_corpus(src, authored_utc="2026-09-07T00:00:00Z")

    assert {f.entry_id for f in findings} == {"recipe.a"}
    written = json.loads(src.read_text(encoding="utf-8"))
    assert written["entries"][0]["costLines"][0]["material"] == "shard.chaff"
    assert written["entries"][1]["costLines"][0]["material"] == "substrate.humanoid.crude"

    amendments = written["_meta"]["amendments"]
    assert len(amendments) == 1
    assert amendments[0]["entries"] == ["recipe.a"]
    assert amendments[0]["authoredUtc"] == "2026-09-07T00:00:00Z"


def test_apply_to_real_corpus_appends_to_existing_amendments_rather_than_replacing(tmp_path):
    src = tmp_path / "recipes.json"
    doc = _doc([_entry("recipe.a", "shard.rare")])
    doc["_meta"]["amendments"] = [{"batch": "earlier", "entries": ["recipe.q"]}]
    src.write_text(json.dumps(doc), encoding="utf-8")

    mod.apply_to_real_corpus(src, authored_utc="2026-09-07T00:00:00Z")

    written = json.loads(src.read_text(encoding="utf-8"))
    assert [a["batch"] for a in written["_meta"]["amendments"]] == [
        "earlier", "recipegen/legacy-shard-migration-1"]


def test_apply_to_real_corpus_is_a_no_op_when_already_clean(tmp_path):
    src = tmp_path / "recipes.json"
    original_text = json.dumps(_doc([_entry("recipe.a", "shard.sprout")]))
    src.write_text(original_text, encoding="utf-8")

    findings = mod.apply_to_real_corpus(src, authored_utc="2026-09-07T00:00:00Z")

    assert findings == []
    assert src.read_text(encoding="utf-8") == original_text  # byte-identical -- no rewrite at all
