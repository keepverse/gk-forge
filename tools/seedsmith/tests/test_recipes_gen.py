"""Tests for `recipes-gen` (item-seedgen module 14/Phase 4,
docs/architecture/item-seedgen/spec-recipes-gen.md).

Five groups:
1. `opvocab` — the real, transcribed `CraftOperation` vocabulary and `CostClassMatrix` mirrors.
2. Schema — the closed answer schema and the construction-time `audit_schema` guard.
3. Brief — real registries/tuning read fresh (cost bands, issuable materials, forge targets).
4. Emit — id minting, mechanical derivations (outputKind, upcycle output, tags), and validation.
5. Run / real-corpus regression — acceptance #3 (operation reconcile) and #5 (reference validation
   + container backfill), proven against the current shipped corpus, plus harness
   resume/reconcile/overwrite against a `tmp_path` ledger.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from seedsmith.adapters.items.basetypegen import emit as basetype_emit
from seedsmith.adapters.items.basetypegen import run as basetype_run
from seedsmith.adapters.items.materialgen import vocab as material_vocab
from seedsmith.adapters.items.recipegen import brief as brief_mod
from seedsmith.adapters.items.recipegen import emit as emit_mod
from seedsmith.adapters.items.recipegen import imbue as imbue_mod
from seedsmith.adapters.items.recipegen import opvocab
from seedsmith.adapters.items.recipegen import run as run_mod
from seedsmith.adapters.items.recipegen import schema as schema_mod
from seedsmith.pipeline.dependency_validator import BackfillRequest, HARD
from seedsmith.pipeline.model import audit_schema
from seedsmith.pipeline.run_ledger import RunLedger

REAL_RECIPES_PATH = run_mod.RECIPES_CORPUS_PATH


# ---------------------------------------------------------------------------------------------
# 1. opvocab — the real, transcribed CraftOperation / CostClassMatrix vocabulary
# ---------------------------------------------------------------------------------------------


def test_all_operations_matches_the_real_craft_operations_eleven_verb_enum():
    # species-gear-chain T23 appended `repair` — the eleventh member, the ordinal
    # deployment-hierarchy-map.md:89 reserved for the durability slice.
    assert opvocab.ALL_OPERATIONS == (
        "forge", "upcycle", "forge-gem", "bore", "imbue", "socket", "elevate", "temper",
        "reroll-one", "reroll-all", "repair",
    )
    assert len(opvocab.ALL_OPERATIONS) == 11


def test_forge_gem_is_supported_but_never_briefed_while_imbue_stays_unoffered():
    # species-gear-chain T9: forge-gem's reference target (gemgen) is specified, so the vocabulary
    # recognizes it — but its rows are DERIVED (forgegem.py), never model-authored, so the brief
    # path still refuses it. imbue is still real-but-unoffered (no reference target, no corpus use).
    assert "forge-gem" in opvocab.ALL_OPERATIONS
    assert "imbue" in opvocab.ALL_OPERATIONS
    assert "forge-gem" in opvocab.SUPPORTED_FOR_GENERATION
    assert "imbue" not in opvocab.SUPPORTED_FOR_GENERATION
    assert opvocab.output_kind_for("forge-gem") == "gem"
    with pytest.raises(emit_mod.IllegalChoiceError):
        emit_mod.assemble_entry(
            {"name": "X", "operation": "forge-gem", "frame": "any", "costLines": []}, seq=999)


def test_output_kind_matches_the_real_corpus_pattern():
    assert opvocab.output_kind_for("forge") == "container"
    assert opvocab.output_kind_for("upcycle") == "material"
    for op in ("bore", "socket", "elevate", "temper", "reroll-one", "reroll-all"):
        assert opvocab.output_kind_for(op) == "mutation"


def test_unsupported_operation_is_refused_not_silently_accepted():
    with pytest.raises(opvocab.UnsupportedOperationError):
        opvocab.require_supported_operation("reroll")  # the pre-2026-09-05 spelling
    with pytest.raises(opvocab.UnsupportedOperationError):
        opvocab.require_supported_operation("imbue")


def test_check_cost_class_mirrors_cost_class_matrix_allows():
    # forge may spend substrate/catalyst, never shard (CostClassMatrix.Allows).
    opvocab.check_cost_class("forge", "substrate", "substrate.humanoid.crude")
    opvocab.check_cost_class("forge", "catalyst", "catalyst.forge")
    with pytest.raises(opvocab.CostClassForbiddenError):
        opvocab.check_cost_class("forge", "shard", "shard.chaff")


def test_check_cost_class_catches_a_catalyst_riding_the_wrong_verb():
    """The spec's own named example: a forge recipe spending catalyst.temper."""
    with pytest.raises(opvocab.CatalystMismatchError):
        opvocab.check_cost_class("forge", "catalyst", "catalyst.temper")


def test_check_cost_class_souls_is_legal_for_every_operation():
    for op in opvocab.ALL_OPERATIONS:
        opvocab.check_cost_class(op, "souls", "")


def test_reconcile_operations_finds_zero_drift_in_the_current_corpus():
    """Acceptance #3's own evidence: the 2026-09-05 hand patch already fixed the one drift this
    check exists to catch (`"reroll"` -> `"reroll-one"`/`"reroll-all"`), so today's real corpus is
    clean. Had this run against the corpus BEFORE that patch, `reconcile_operations` would have
    flagged every `operation: "reroll"` row as outside `ALL_OPERATIONS`.

    The corpus is intentionally open-ended, so this test checks the live count is non-empty rather
    than freezing a historical row count."""
    entries = run_mod.load_entries(REAL_RECIPES_PATH)
    assert len(entries) >= 32
    drift = opvocab.reconcile_operations(entries)
    assert drift == []


def test_reconcile_operations_catches_a_synthetic_pre_patch_style_drift():
    """Proves the mechanism itself, using the exact pre-patch spelling as a synthetic input — the
    positive control for the real-corpus test above finding nothing."""
    entries = {"recipe.099": {"operation": "reroll"}}
    drift = opvocab.reconcile_operations(entries)
    assert drift == [("recipe.099", "reroll")]


# ---------------------------------------------------------------------------------------------
# 2. Schema
# ---------------------------------------------------------------------------------------------


def test_bare_numeric_field_in_the_recipe_schema_fails_audit():
    schema = {"type": "object", "additionalProperties": False, "required": [],
             "properties": {"outputQty": {"type": "integer"}}}
    assert audit_schema(schema)


def test_recipe_schema_never_offers_the_fields_code_must_resolve():
    schema = schema_mod.recipe_schema(
        operations=("bore",), material_pool=("catalyst.forge",), cost_bands=("cheap",))
    fields = schema_mod.schema_field_names(schema)
    for forbidden in ("outputKind", "outputQty", "id", "nameKey", "outputRef"):
        assert forbidden not in fields, f"{forbidden!r} must never be an authorable field"


def test_recipe_schema_is_clean_under_the_shared_auditor():
    schema = schema_mod.recipe_schema(
        operations=opvocab.SUPPORTED_FOR_GENERATION, material_pool=("catalyst.forge",),
        cost_bands=("cheap", "modest"))
    assert audit_schema(schema) == []


def test_recipe_schema_refuses_empty_vocabularies():
    with pytest.raises(ValueError):
        schema_mod.recipe_schema(operations=(), material_pool=("catalyst.forge",), cost_bands=("cheap",))
    with pytest.raises(ValueError):
        schema_mod.recipe_schema(operations=("bore",), material_pool=(), cost_bands=("cheap",))
    with pytest.raises(ValueError):
        schema_mod.recipe_schema(operations=("bore",), material_pool=("catalyst.forge",), cost_bands=())


def test_recipe_answer_validation_names_an_operation_cost_incompatibility():
    schema = schema_mod.recipe_schema(
        operations=("temper",), material_pool=("essence.fire", "catalyst.temper"),
        cost_bands=("cheap",),
    )
    answer = {
        "name": "Bad Temper", "flavor": "", "operation": "temper", "frame": "any",
        "costLines": [{"material": "essence.fire", "costBand": "cheap"}],
    }

    defects = schema_mod.validate_answer(answer, schema)

    assert any("may not spend a essence" in defect for defect in defects)


def test_recipe_schema_offers_output_target_only_when_container_candidates_given():
    without = schema_mod.recipe_schema(
        operations=("bore",), material_pool=("catalyst.forge",), cost_bands=("cheap",))
    assert "outputTarget" not in without["properties"]
    withit = schema_mod.recipe_schema(
        operations=("forge",), material_pool=("catalyst.forge",), cost_bands=("cheap",),
        container_candidates=("item.humanoid-torso-a-005",))
    assert withit["properties"]["outputTarget"]["enum"] == [
        "item.humanoid-torso-a-005", schema_mod.MINT_NEW_SENTINEL]


def test_recipe_material_pool_includes_issuable_materials_with_an_acquisition_path():
    pool = brief_mod.load_material_pool()

    assert "shard.sprout" in pool
    # The live corpus now has drop/recipe paths for the grafted band too.  Keep this
    # assertion tied to the current reachability contract rather than the old 19-id snapshot.
    assert "shard.grafted" in pool


# ---------------------------------------------------------------------------------------------
# 3. Brief — real registries/tuning read fresh
# ---------------------------------------------------------------------------------------------


def test_load_cost_bands_matches_the_real_frozen_bands_registry():
    bands = brief_mod.load_cost_bands()
    assert set(bands) == {"cheap", "modest", "standard", "steep", "exorbitant"}
    assert bands[0] == "cheap" and bands[-1] == "exorbitant", "sorted by ascending multiplier"


def test_load_material_pool_is_the_obtainable_issued_vocabulary():
    # species-gear-chain T33: the closed 27-id core is reconciled against material_vocab.ISSUABLE's
    # own closed-class count, never a bare literal.
    #
    # species-gear-chain T34 revises the scope of this reconciliation: `load_material_pool` filters
    # to ids with a real ACQUISITION path (a drop table or a material-output recipe) -- "obtainable",
    # a strictly narrower set than "issuable" (vocab.py's own module docstring: "necessary but
    # insufficient"). The 27-id closed core happens to be fully obtainable today, which is what made
    # `len(pool) == len(ISSUABLE)` true before Trophy existed -- a coincidence of THIS corpus's
    # current reachability, never a structural guarantee `load_material_pool` promises. Trophy ids
    # (T34) are issuable but have no acquisition path yet (wiring them into a creature-kill drop
    # table is T34c/T34d's own scope), so they are correctly ABSENT from `pool` today; asserting
    # `len(pool) == len(material_vocab.ISSUABLE)` as a whole would pin that absence as a permanent
    # bug rather than the deliberate, temporary reachability gap it is. species-gear-chain T40's
    # `assurance.*` ids are issuable for the identical reason and are excluded here too -- no recipe
    # or drop table prices/grants one yet (that is T41/T42's own scope, not T40's).
    pool = brief_mod.load_material_pool()
    closed_core_ids = [
        m.runtime_id for m in material_vocab.ISSUABLE
        if m.material_class not in ("trophy", "assurance")
    ]
    assert len(pool) == len(closed_core_ids)
    assert set(pool) == set(closed_core_ids)
    assert "shard.common" not in pool, "a legacy shard id is never issuable"
    assert "substrate.humanoid.crude" in pool
    assert "shard.grafted" in pool, "the current drop/recipe corpus makes this id obtainable"


def test_build_recipe_brief_excludes_forge_when_no_target_is_scoped():
    b = brief_mod.build_recipe_brief()
    assert "forge" not in b.operations
    assert "outputTarget" not in b.schema["properties"]
    assert "temper: catalyst, substrate" in b.render()
    assert "elevate: catalyst, shard, substrate; if using a catalyst, it must be catalyst.temper" in b.render()
    assert "An empty list is always legal" in b.render()
    # T34: the rendered count is the OBTAINABLE pool's own size (brief.py derives it from
    # `len(self.material_pool)`), not `len(material_vocab.ISSUABLE)` as a whole -- see
    # test_load_material_pool_is_the_obtainable_issued_vocabulary's own note.
    assert f"{len(brief_mod.load_material_pool())} obtainable, issuable ids" in b.render()


def test_build_recipe_brief_with_a_forge_target_offers_forge_and_its_candidates():
    target = brief_mod.load_forge_target("core-guard", "humanoid", "a")
    b = brief_mod.build_recipe_brief(forge_target=target)
    assert "forge" in b.operations
    assert "outputTarget" in b.schema["properties"]
    text = b.render()
    assert "core-guard:humanoid:a" in text
    assert schema_mod.MINT_NEW_SENTINEL in text


def test_forge_target_next_mint_id_matches_basetypegen_own_formula():
    target = brief_mod.load_forge_target("core-guard", "humanoid", "a")
    existing = basetype_run.load_existing("core-guard", "humanoid", "a")
    expected = basetype_emit.entry_id("humanoid", "torso", "a", basetype_emit.next_seq(tuple(existing)))
    assert target.next_mint_id == expected


def test_a_brief_offering_forge_with_no_target_is_refused():
    with pytest.raises(brief_mod.BriefBuildError):
        brief_mod.RecipeBrief(forge_target=None, operations=("forge",),
                              material_pool=("catalyst.forge",), cost_bands=("cheap",))


# ---------------------------------------------------------------------------------------------
# 4. Emit — ids, mechanical derivations, validation
# ---------------------------------------------------------------------------------------------


def test_slug_and_recipe_id():
    assert emit_mod.slug_from_name("Forge: Cloth Armor") == "forge-cloth-armor"
    assert emit_mod.name_key_for("forge-cloth-armor") == "recipe.forge-cloth-armor"
    assert emit_mod.recipe_id(31) == "recipe.031"


def test_next_seq_continues_past_the_real_corpus():
    """The next id always follows the highest currently shipped recipe, regardless of corpus growth."""
    entries = run_mod.load_entries(REAL_RECIPES_PATH)
    highest = max(int(recipe_id.rsplit(".", 1)[1]) for recipe_id in entries)
    assert emit_mod.next_seq(tuple(entries)) == highest + 1


def test_derive_upcycle_output_matches_the_real_corpus_examples():
    """recipe.005/006's own real mechanical relationship: same frame, one grade up."""
    assert emit_mod.derive_upcycle_output(
        [{"material": "substrate.humanoid.crude", "costBand": "modest"}]) == "substrate.humanoid.sound"
    assert emit_mod.derive_upcycle_output(
        [{"material": "substrate.humanoid.sound", "costBand": "standard"}]) == "substrate.humanoid.fine"


def test_derive_upcycle_output_refuses_top_grade_and_ambiguous_input():
    with pytest.raises(emit_mod.NoUpcycleInputError):
        emit_mod.derive_upcycle_output([{"material": "substrate.humanoid.prime", "costBand": "steep"}])
    with pytest.raises(emit_mod.NoUpcycleInputError):
        emit_mod.derive_upcycle_output([])
    with pytest.raises(emit_mod.NoUpcycleInputError):
        emit_mod.derive_upcycle_output([
            {"material": "substrate.humanoid.crude", "costBand": "modest"},
            {"material": "substrate.plant.crude", "costBand": "modest"},
        ])


def test_tags_for_matches_the_real_corpus_mechanical_pattern():
    assert emit_mod.tags_for("forge") == ["crafted-only"]
    for op in ("upcycle", "bore", "socket", "elevate", "temper", "reroll-one", "reroll-all"):
        assert emit_mod.tags_for(op) == []


def test_assemble_entry_for_a_mutation_recipe():
    answer = {"name": "Bore: Test Socket", "operation": "bore", "frame": "humanoid",
             "costLines": [{"material": "substrate.humanoid.sound", "costBand": "modest"},
                          {"material": "catalyst.forge", "costBand": "modest"}]}
    entry = emit_mod.assemble_entry(answer, seq=999)
    assert entry["id"] == "recipe.999"
    assert entry["outputKind"] == "mutation"
    assert "outputRef" not in entry
    assert entry["outputQty"] == 1
    assert entry["tags"] == []


def test_assemble_entry_for_an_upcycle_recipe_derives_output_ref():
    answer = {"name": "Upcycle: Test", "operation": "upcycle", "frame": "humanoid",
             "costLines": [{"material": "substrate.humanoid.crude", "costBand": "modest"}]}
    entry = emit_mod.assemble_entry(answer, seq=1000)
    assert entry["outputKind"] == "material"
    assert entry["outputRef"] == "substrate.humanoid.sound"


def test_assemble_entry_for_a_forge_recipe_with_mint_new():
    target = brief_mod.load_forge_target("core-guard", "humanoid", "a")
    answer = {"name": "Forge: Test", "operation": "forge", "frame": "humanoid",
             "costLines": [{"material": "substrate.humanoid.fine", "costBand": "steep"},
                          {"material": "catalyst.forge", "costBand": "cheap"}],
             "outputTarget": schema_mod.MINT_NEW_SENTINEL}
    entry = emit_mod.assemble_entry(answer, seq=1001, forge_target=target)
    assert entry["outputKind"] == "container"
    assert entry["outputRef"] == target.next_mint_id
    assert entry["tags"] == ["crafted-only"]


def test_assemble_entry_refuses_a_forge_recipe_with_no_target():
    answer = {"name": "Forge: Test", "operation": "forge", "frame": "humanoid", "costLines": []}
    with pytest.raises(emit_mod.IllegalChoiceError):
        emit_mod.assemble_entry(answer, seq=1002)  # no forge_target scoped at all


def test_assemble_entry_refuses_a_cost_line_the_real_loader_would_refuse():
    """A forge recipe spending shard.* — CostClassMatrix.Allows forbids it for forge."""
    answer = {"name": "Forge: Bad", "operation": "forge", "frame": "humanoid",
             "costLines": [{"material": "shard.chaff", "costBand": "modest"}],
             "outputTarget": schema_mod.MINT_NEW_SENTINEL}
    target = brief_mod.load_forge_target("core-guard", "humanoid", "a")
    with pytest.raises(opvocab.CostClassForbiddenError):
        emit_mod.assemble_entry(answer, seq=1003, forge_target=target)


def test_assemble_entry_refuses_a_legacy_shard_cost_line():
    """acceptance #1's own gate: never invent/accept a material id materials-gen does not issue."""
    answer = {"name": "Elevate: Bad", "operation": "elevate", "frame": "any",
             "costLines": [{"material": "shard.common", "costBand": "standard"}]}
    with pytest.raises(material_vocab.MaterialVocabularyRejection):
        emit_mod.assemble_entry(answer, seq=1004)


# ---------------------------------------------------------------------------------------------
# 5. Run / real-corpus regression — acceptance #3 and #5
# ---------------------------------------------------------------------------------------------


def test_reconcile_operations_against_real_corpus_wrapper_is_also_clean():
    assert run_mod.reconcile_operations_against_real_corpus() == []


def test_base_type_id_exists_matches_the_real_corpus():
    assert run_mod.base_type_id_exists("item.humanoid-torso-a-001") is True
    assert run_mod.base_type_id_exists("item.humanoid-torso-a-002") is True
    assert run_mod.base_type_id_exists("item.plant-stem-a-002") is True


def test_base_type_id_exists_is_true_via_the_frame_role_name_fallback():
    """⭐ Corrected 2026-09-07 (was a false positive, not a real gap): the original single-filename
    check built `plant-core-guard-b.json` (role-id-based) from `item.plant-stem-b-001`'s parsed
    (role=core-guard, frame=plant, band=b) and reported "missing", but the real, shipped file for
    that partition is `plant-stem-b.json` — authored under the display word (`frameRoleName`), the
    exact same roleId/frameRoleName filename inconsistency base-types-gen's own report already
    named across the corpus's older, pre-generator content. `base_type_id_exists` now also tries
    the frame-role-name-shaped filename before concluding an id is missing, so this real, existing
    base-type resolves correctly instead of reporting a dangling `recipe.004` reference."""
    assert run_mod.base_type_id_exists("item.plant-stem-b-001") is True


def test_base_type_id_exists_is_still_false_for_a_genuinely_missing_id():
    assert run_mod.base_type_id_exists("item.plant-bogus-b-999") is False


def test_build_reference_reports_against_the_real_corpus_finds_exactly_the_known_gaps():
    entries = run_mod.load_entries(REAL_RECIPES_PATH)
    reports = run_mod.build_reference_reports(entries)

    # ⭐ Corrected 2026-09-07: recipe.004's outputRef is not actually dangling — see
    # test_base_type_id_exists_is_true_via_the_frame_role_name_fallback above.
    assert reports.container.unresolved == []

    assert reports.material_output.unresolved == []

    # ⭐ Corrected 2026-09-07, later the same day: the seven legacy-shard cost-line refusals this
    # test used to pin (recipe.009/010/011/017/018/025/029) were fixed in place by
    # `migrate_legacy_shards.apply_to_real_corpus` — see that module's own test file and
    # `recipes.json`'s `_meta.amendments` entry `recipegen/legacy-shard-migration-1`. Zero
    # unresolved cost lines is now the correct, permanent expectation.
    assert reports.cost_lines.unresolved == []


def test_plan_container_backfill_names_exactly_the_real_dangling_target():
    entries = run_mod.load_entries(REAL_RECIPES_PATH)
    requests = run_mod.plan_container_backfill(entries)
    # ⭐ Corrected 2026-09-07: no real dangling container reference remains — see
    # test_build_reference_reports_against_the_real_corpus_finds_exactly_the_known_gaps above.
    assert requests == []


def _fake_base_type_call(name: str = "Test Base"):
    def call(brief: str, schema: dict) -> dict:
        cls = schema["properties"]["class"]["enum"][0]
        fam = schema["properties"]["implicitFamily"]["enum"][0]
        return {"name": name, "flavor": "A generated base type for testing.",
               "class": cls, "implicitFamily": fam, "tags": ["light"]}
    return call


def test_mint_forge_backfill_mints_exactly_the_missing_target_and_then_resolves(tmp_path):
    base_types_dir = tmp_path / "base-types"
    # Seed the partition with exactly 1 entry so the next mintable seq is 002 — matching a
    # fabricated missing reference at seq 002, the same shape as the real recipe.004 gap.
    ledger = RunLedger(tmp_path / "seed.ledger.json")
    seed_plan = basetype_run.plan_run(role="core-guard", frame="plant", band="a", count=1,
                                      ledger=ledger, base_types_dir=base_types_dir)
    fresh, _ = basetype_run.run_draws(seed_plan, ledger=ledger, call=_fake_base_type_call("Seed"))
    basetype_run.write_corpus("core-guard", "plant", "a", fresh, existing=seed_plan.existing,
                              base_types_dir=base_types_dir, model="test-model")

    missing_id = "item.plant-stem-a-002"
    entries = {"recipe.900": {"outputKind": "container", "outputRef": missing_id}}

    assert run_mod.base_type_id_exists(missing_id, base_types_dir=base_types_dir) is False
    requests = run_mod.plan_container_backfill(entries, base_types_dir=base_types_dir)
    assert requests == [BackfillRequest("base-types-gen", HARD, missing_id)]

    minted = run_mod.mint_forge_backfill(
        requests[0], base_types_dir=base_types_dir,
        ledger=RunLedger(tmp_path / "backfill.ledger.json"), model="test-model",
        call=_fake_base_type_call("Backfilled"))
    assert missing_id in minted

    assert run_mod.base_type_id_exists(missing_id, base_types_dir=base_types_dir) is True
    assert run_mod.plan_container_backfill(entries, base_types_dir=base_types_dir) == []


def test_mint_forge_backfill_refuses_a_target_that_is_not_the_next_mintable_seq(tmp_path):
    base_types_dir = tmp_path / "base-types"
    request = BackfillRequest("base-types-gen", HARD, "item.humanoid-torso-a-005")  # nothing minted yet
    with pytest.raises(run_mod.BackfillTargetError):
        run_mod.mint_forge_backfill(request, base_types_dir=base_types_dir,
                                    ledger=RunLedger(tmp_path / "ledger.json"),
                                    model="test-model", call=_fake_base_type_call())


def test_mutation_output_recipes_are_never_flagged_as_a_missing_container_reference():
    """A `mutation`-output recipe carries no `outputRef` at all in the real corpus — confirms the
    validator treats this correctly rather than a false-positive missing reference."""
    entries = {"recipe.901": {"outputKind": "mutation"}}
    reports = run_mod.build_reference_reports(entries)
    assert reports.container.results == ()
    assert reports.material_output.results == ()


# ---------------------------------------------------------------------------------------------
# Harness integration — RunLedger resume / reconcile / overwrite, via run.py
# ---------------------------------------------------------------------------------------------


def _fake_recipe_call(name: str = "Test Recipe", *, block: bool = False):
    def call(brief: str, schema: dict) -> dict:
        if block:
            return {"blocked": "no theme fits"}
        # "bore" is a mutation-output operation needing no derived outputRef — a safe, always-legal
        # pick regardless of which operations this brief's schema happens to offer.
        return {"name": name, "operation": "bore", "frame": "any", "costLines": []}
    return call


def test_plan_run_starts_the_entry_sequence_after_the_real_corpus(tmp_path):
    recipes_path = tmp_path / "recipes.json"
    ledger = RunLedger(tmp_path / "ledger.json")
    plan = run_mod.plan_run(count=2, ledger=ledger, recipes_path=recipes_path)
    assert [s.subject_id for s in plan.subjects] == ["recipe-draw-000", "recipe-draw-001"]
    assert [s.seq for s in plan.subjects] == [1, 2]


def test_run_draws_marks_the_ledger_done_and_partitions_fresh_vs_blocked(tmp_path):
    recipes_path = tmp_path / "recipes.json"
    ledger = RunLedger(tmp_path / "ledger.json")
    plan = run_mod.plan_run(count=2, ledger=ledger, recipes_path=recipes_path)

    calls = iter([_fake_recipe_call(name="First"), _fake_recipe_call(block=True)])
    fresh, blocked = run_mod.run_draws(plan, ledger=ledger, call=lambda b, s: next(calls)(b, s))

    assert len(fresh) == 1
    (entry,) = fresh.values()
    assert entry["id"] == "recipe.001"
    assert len(blocked) == 1
    done = ledger.read_done()
    assert set(done) == {"recipe-draw-000"}


def test_run_draws_does_not_checkpoint_before_persist_callback(tmp_path):
    recipes_path = tmp_path / "recipes.json"
    ledger = RunLedger(tmp_path / "ledger.json")
    plan = run_mod.plan_run(count=1, ledger=ledger, recipes_path=recipes_path)

    def persist(_entry):
        raise RuntimeError("simulated corpus write failure")

    with pytest.raises(RuntimeError, match="corpus write failure"):
        run_mod.run_draws(plan, ledger=ledger, call=_fake_recipe_call(name="Retry Me"), persist=persist)
    assert ledger.read_done() == {}


def test_run_draws_keeps_going_after_a_semantically_invalid_model_recipe(tmp_path):
    recipes_path = tmp_path / "recipes.json"
    ledger = RunLedger(tmp_path / "ledger.json")
    plan = run_mod.plan_run(count=2, ledger=ledger, recipes_path=recipes_path)
    calls = iter([
        {"name": "Invalid Temper", "operation": "temper", "frame": "any",
         "costLines": [{"material": "essence.fire", "costBand": "modest"}]},
        _fake_recipe_call(name="Recovered Recipe"),
    ])

    def call(brief: str, schema: dict) -> dict:
        result = next(calls)
        return result(brief, schema) if callable(result) else result

    fresh, blocked = run_mod.run_draws(plan, ledger=ledger, call=call)

    assert {entry["name"] for entry in fresh.values()} == {"Recovered Recipe"}
    assert set(blocked) == {"recipe-draw-000"}
    assert "may not spend a essence" in blocked["recipe-draw-000"]["reason"]
    assert set(ledger.read_done()) == {"recipe-draw-001"}


def test_resume_never_repeats_a_committed_draw_across_two_plan_run_calls(tmp_path):
    recipes_path = tmp_path / "recipes.json"
    ledger = RunLedger(tmp_path / "ledger.json")
    plan1 = run_mod.plan_run(count=1, ledger=ledger, recipes_path=recipes_path)
    fresh1, _ = run_mod.run_draws(plan1, ledger=ledger, call=_fake_recipe_call(name="One"))
    run_mod.write_corpus(fresh1, existing=plan1.existing, recipes_path=recipes_path,
                         model="test-model")

    plan2 = run_mod.plan_run(count=1, ledger=ledger, recipes_path=recipes_path)
    assert plan2.subjects[0].subject_id == "recipe-draw-001"
    assert plan2.subjects[0].seq == 2


def test_reconcile_resurfaces_a_draw_whose_entry_was_deleted_from_the_corpus():
    ledger_entry = {"entryId": "recipe.999", "operation": "bore"}
    assert run_mod.is_valid("x", ledger_entry, existing={}) is False


def test_plan_run_reuses_an_invalid_ledger_slot_before_allocating_new_draws(tmp_path):
    recipes_path = tmp_path / "recipes.json"
    ledger = RunLedger(tmp_path / "ledger.json")
    ledger.mark_done("recipe-draw-000", {"entryId": "recipe.999", "operation": "forge"})
    plan = run_mod.plan_run(count=1, ledger=ledger, recipes_path=recipes_path)
    assert plan.subjects[0].subject_id == "recipe-draw-000"


def test_reconcile_leaves_a_draw_alone_when_its_entry_still_matches():
    ledger_entry = {"entryId": "recipe.999", "operation": "bore"}
    existing = {"recipe.999": {"operation": "bore"}}
    assert run_mod.is_valid("x", ledger_entry, existing=existing) is True


def test_write_corpus_is_additive_and_never_drops_an_existing_entry(tmp_path):
    recipes_path = tmp_path / "recipes.json"
    ledger = RunLedger(tmp_path / "ledger.json")
    plan1 = run_mod.plan_run(count=1, ledger=ledger, recipes_path=recipes_path)
    fresh1, _ = run_mod.run_draws(plan1, ledger=ledger, call=_fake_recipe_call(name="First"))
    path1 = run_mod.write_corpus(fresh1, existing=plan1.existing, recipes_path=recipes_path,
                                 model="test-model")

    ledger2 = RunLedger(tmp_path / "ledger.json")
    plan2 = run_mod.plan_run(count=1, ledger=ledger2, recipes_path=recipes_path)
    fresh2, _ = run_mod.run_draws(plan2, ledger=ledger2, call=_fake_recipe_call(name="Second"))
    path2 = run_mod.write_corpus(fresh2, existing=plan2.existing, recipes_path=recipes_path,
                                 model="test-model")

    assert path1 == path2
    written = json.loads(path2.read_text(encoding="utf-8"))
    written_ids = {e["id"] for e in written["entries"]}
    assert written_ids == {"recipe.001", "recipe.002"}


def test_overwrite_by_id_bypasses_validity_for_named_ids_only(tmp_path):
    ledger = RunLedger(tmp_path / "ledger.json")
    ledger.mark_done("recipe-draw-000", {"entryId": "recipe.001"})
    forced = ledger.force(["recipe-draw-000"], "ids")
    assert forced == ["recipe-draw-000"]


def test_cli_force_is_an_accepted_alias_for_overwrite(tmp_path, monkeypatch, capsys):
    """seedsmith-content-standard Task 6: `content-completeness-core`'s own naming convention is
    `--force` (matching `RunLedger.force()` and `generate_commander_effects.py --force`), while this
    CLI's own real, already-shipped flag is `--overwrite` -- an audit finding, not a placeholder
    (docs/architecture/item-seedgen/spec-recipes-gen.md already documents `--overwrite`). Renaming
    the shipped flag outright would break every doc/script referencing it for a cosmetic win; adding
    `--force` as a second flag string onto the SAME `argparse` argument (both set `args.overwrite`)
    gives the naming parity Task 6 asks for without breaking anything that already types
    `--overwrite`."""
    ledger_path = tmp_path / "ledger.json"
    monkeypatch.setattr(run_mod, "DEFAULT_LEDGER_PATH", ledger_path)
    ledger = RunLedger(ledger_path)
    ledger.mark_done("recipe-draw-000", {"entryId": "recipe.001"})

    exit_code = run_mod.main(["--force", "recipe-draw-000"])
    assert exit_code == 0
    assert "recipe-draw-000" in capsys.readouterr().out


def test_cli_reconcile_default_prints_a_summary_and_makes_no_model_calls(capsys, monkeypatch):
    monkeypatch.setattr(run_mod, "DEFAULT_LEDGER_PATH", run_mod.DEFAULT_LEDGER_PATH)
    exit_code = run_mod.main([])
    assert exit_code == 0
    out = json.loads(capsys.readouterr().out)
    assert out["operationDrift"] == []


def test_cli_dry_run_prints_a_sample_brief_and_makes_no_model_calls(capsys):
    exit_code = run_mod.main(["--dry-run", "--count", "1"])
    assert exit_code == 0
    out = capsys.readouterr().out
    assert "Legal operations" in out


def test_cli_refuses_a_real_run_with_no_model_call_wired():
    """⛔ Renamed in spirit 2026-09-08, unchanged in assertion — see basetypegen's identical test
    for the full account: this now refuses for lack of `--write`, not lack of wiring."""
    with pytest.raises(SystemExit):
        run_mod.main(["--count", "1"])


def test_cli_write_without_endpoint_refuses(monkeypatch):
    """Refuse only when the *resolved* transport has no endpoint (CLI empty + config empty)."""
    from seedsmith.pipeline.llm_caller import LlmCallerConfig
    monkeypatch.setattr(
        "seedsmith.pipeline.llm_caller.resolve_live_transport",
        lambda *a, **k: LlmCallerConfig(endpoint="", model="x"))
    with pytest.raises(SystemExit):
        run_mod.main(["--count", "1", "--write"])



def test_cli_a_real_live_run_writes_a_real_corpus_file(tmp_path, monkeypatch, capsys):
    """⛔ Real gap, closed 2026-09-08 — see basetypegen's identical test for the full account:
    `--write --endpoint <url>` was unreachable before this."""
    monkeypatch.setattr(run_mod, "RECIPES_CORPUS_PATH", tmp_path / "recipes.json")
    monkeypatch.setattr(run_mod, "DEFAULT_LEDGER_PATH", tmp_path / "ledger.json")

    called_with = {}

    def _fake_live_answer_caller(config, *, validator=None):
        called_with["config"] = config
        return _fake_recipe_call(name="Live-Wired Recipe")

    monkeypatch.setattr("seedsmith.pipeline.llm_caller.live_answer_caller",
                        _fake_live_answer_caller)

    exit_code = run_mod.main(["--count", "1", "--write", "--endpoint", "http://unit-test-endpoint",
                             "--model", "unit-test-model"])

    assert exit_code == 0
    assert called_with["config"].endpoint == "http://unit-test-endpoint"
    assert called_with["config"].model == "unit-test-model"
    written = json.loads((tmp_path / "recipes.json").read_text(encoding="utf-8"))
    names = {e["name"] for e in written["entries"]}
    assert "Live-Wired Recipe" in names
    summary = json.loads(capsys.readouterr().out)
    assert summary["planned"] == 1 and summary["fresh"] == 1 and summary["blocked"] == 0


# ---------------------------------------------------------------------------------------------
# 6. imbue — the derived emitter (strain-splice-host SSH8.1, spec-socket-pricing §1)
# ---------------------------------------------------------------------------------------------


def _planned_imbue_rows():
    """Plan against a corpus with the imbue rows STRIPPED: the emitter is what is under test, so the
    fixture is "the corpus before this step", not whatever the shipped file happens to carry today."""
    existing = run_mod.load_entries()
    without_imbue = {k: v for k, v in existing.items() if v.get("operation") != "imbue"}
    return without_imbue, imbue_mod.plan_rows(existing=without_imbue, start_seq=5000)


def test_imbue_rows_are_derived_and_idempotent():
    """Every (bore frame, concrete element) pair, and nothing else: the plan is the PRODUCT of the two
    closed sets, so a new frame or element adds rows with no code change — and re-planning over a corpus
    that already carries them converges to nothing."""
    existing, rows = _planned_imbue_rows()

    frames = {str(row.get("frame") or "any") for row in imbue_mod.bore_rows(existing)}
    elements = imbue_mod.concrete_elements()
    assert len(rows) == len(frames) * len(elements)
    assert {(str(row["frame"]), imbue_mod.imbued_element(row)) for row in rows} == {
        (frame, element) for frame in frames for element in elements}

    # Each row carries the bore frame's own lines VERBATIM plus the essence, and the bore row's band.
    bores = {str(row.get("frame") or "any"): row for row in imbue_mod.bore_rows(existing)}
    for row in rows:
        bore = bores[str(row["frame"])]
        assert row["costLines"][:-1] == bore["costLines"]
        assert row["soulsCostBand"] == bore["soulsCostBand"]
        assert {line["costBand"] for line in row["costLines"]} == {str(bore["soulsCostBand"])}
        assert row["outputKind"] == "mutation"
        assert row["tags"] == []

    # Idempotence: a corpus that already carries the plan plans nothing.
    merged = {**existing, **{row["id"]: row for row in rows}}
    assert imbue_mod.plan_rows(existing=merged, start_seq=9000) == []


def test_imbue_is_never_offered_to_the_model():
    """The emitter is a DERIVATION path: `imbue` stays outside `SUPPORTED_FOR_GENERATION`, so the
    generation gate refuses it before a brief could ever be built for it."""
    assert "imbue" not in opvocab.SUPPORTED_FOR_GENERATION
    assert "imbue" in opvocab.ALL_OPERATIONS          # parseable, just never offered
    with pytest.raises(opvocab.UnsupportedOperationError):
        opvocab.require_supported_operation("imbue")


def test_every_imbue_row_names_a_concrete_element_essence():
    _, rows = _planned_imbue_rows()
    assert rows, "the shipped bore rows admit at least one frame"
    for row in rows:
        essences = [line["material"] for line in row["costLines"]
                    if line["material"].startswith(imbue_mod.ESSENCE_PREFIX)]
        assert len(essences) == 1
        assert essences[0][len(imbue_mod.ESSENCE_PREFIX):] in imbue_mod.concrete_elements()


def test_omni_is_never_an_imbue_element():
    """`omni` is the absence of an affinity, and it lives under its own registry key — an
    `essence.omni` line would name a material no rule mints."""
    assert "omni" not in imbue_mod.concrete_elements()
    existing, _ = _planned_imbue_rows()
    with pytest.raises(ValueError) as ctx:
        imbue_mod.build_entry("humanoid", "omni", imbue_mod.bore_rows(existing)[0], seq=1)
    assert "omni" in str(ctx.value)
