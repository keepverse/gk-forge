"""T5.3 (`species-effects`, spec-species-effects.md) — the pipeline that turns a species anchor into
a `species-passive.{speciesId}` container seed. Every test stubs the transport (this module's own
"Every test stubs the transport" testing-strategy line, matching `test_offline_guarantee.py`'s
discipline elsewhere in this package).
"""
from __future__ import annotations

import pytest

from seedsmith.adapters.creatures.effects.prompts import (
    build_brief,
    build_context,
    entry_for,
    fixed_core_within_band,
    affix_ids_are_known,
)
from seedsmith.adapters.creatures.effects.schema import SPECIES_EFFECTS_SCHEMA
from seedsmith.ladders import RARITY_LADDER
from seedsmith.workflow.graphs.species_effects import (
    build_species_effects_graph,
    load_shape_tuning,
    spec_for_species,
    state_for_species,
)

REAL_ANCHOR = {
    "speciesId": "Peashooter",
    "rarity": "cultivated",
    "elementPrimary": "earth",
    "elementSecondary": "none",
    "aptitudePrimary": "Onslaught",
    "aptitudeSecondary": "none",
    "posture": "Force",
    "resourceProfile": ["hp", "stamina"],
    "family": ["Sentient Flora"],
    "traits": ["Projectile-launching", "Defensive", "Rapid-fire"],
    "flavorInfo": "As a basic first line of defense that deals consistent damage.",
    "threatBand": None,
}


# ---- the shape tuning file --------------------------------------------------------------------


def test_the_real_shape_tuning_loads_and_covers_all_ten_rungs():
    shape = load_shape_tuning()
    bands = shape["fixedCoreBandByRarity"]
    assert set(bands.keys()) == set(RARITY_LADDER)  # declaring read (T-2), never re-transcribed
    for band in bands.values():
        assert band["min"] <= band["max"]


# ---- threatBand does not influence membership --------------------------------------------------


def test_threatBand_does_not_influence_membership():
    """spec §2's own table: strength is species-generator's, through one P(Theta) — threatBand
    constrains nothing here. Proven, not just documented: an anchor differing ONLY in threatBand
    produces the identical context and the identical brief."""
    low = dict(REAL_ANCHOR, threatBand="nuisance")
    high = dict(REAL_ANCHOR, threatBand="calamity")

    ctx_low, ctx_high = build_context(low), build_context(high)
    assert ctx_low == ctx_high
    assert "threatBand" not in ctx_low

    brief_low = build_brief(low, {**ctx_low, "eligibleFamilies": [], "rarityBands": [], "tagSet": []})
    brief_high = build_brief(high, {**ctx_high, "eligibleFamilies": [], "rarityBands": [], "tagSet": []})
    assert brief_low == brief_high


def test_threatBand_string_appears_nowhere_in_the_module_reading_anchors():
    import ast
    import inspect

    from seedsmith.adapters.creatures.effects import prompts as prompts_module

    tree = ast.parse(inspect.getsource(prompts_module))

    # Every docstring node (module- or function-level) is exempt — explaining the deliberate
    # omission IS the point. A live code path (a dict key lookup, a string literal fed to logic)
    # is what this test actually forbids.
    docstring_ids = set()
    for scope in ast.walk(tree):
        if isinstance(scope, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if scope.body and isinstance(scope.body[0], ast.Expr) and isinstance(scope.body[0].value, ast.Constant):
                docstring_ids.add(id(scope.body[0].value))

    offenders = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and "threatBand" in node.value:
            if id(node) in docstring_ids:
                continue
            offenders.append(getattr(node, "lineno", "?"))
    assert offenders == [], f"threatBand read outside a docstring, at line(s): {offenders}"


# ---- the fixed core respects its rarity band -----------------------------------------------------


#: A stub affix -> real atom ids map, standing in for a real committed affix catalog lookup.
REFS_BY_AFFIX = {
    "affix.a": ["atom.a1", "atom.a2"],
    "affix.b": ["atom.b1"],
    "affix.c": ["atom.c1"],
}


def test_core_affinity_lands_in_the_fixed_core():
    """Fixed 2026-09-06: `core` flattens into the affix's OWN real atoms in the container's `atoms`
    list (`ReadContainer` has no `fixedAffixes` field — spec §4's own table: "core |
    effect_container_atom — always present"), never a bare affix id."""
    draft = {
        "eligibleAffixes": [
            {"affixId": "affix.a", "affinity": "core"},
            {"affixId": "affix.b", "affinity": "likely"},
        ],
        "eligibilityTags": {"requireTags": [], "anyOfTags": []},
    }
    entry = entry_for(REAL_ANCHOR, draft, affix_class_of=lambda _id: "Prefix",
                       affix_refs_of=REFS_BY_AFFIX.__getitem__)

    assert [a["atom"] for a in entry["atoms"]] == ["atom.a1", "atom.a2"]
    assert [a["seq"] for a in entry["atoms"]] == [0, 1]
    assert [p["affix"] for p in entry["pool"]] == ["affix.b"]
    assert "_provenance" not in entry  # no provenance supplied here


def test_core_affix_ids_are_recorded_in_provenance_when_supplied():
    draft = {
        "eligibleAffixes": [{"affixId": "affix.a", "affinity": "core"}],
        "eligibilityTags": {"requireTags": [], "anyOfTags": []},
    }
    entry = entry_for(REAL_ANCHOR, draft, affix_class_of=lambda _id: "Prefix",
                       affix_refs_of=REFS_BY_AFFIX.__getitem__, provenance={"promptVersion": 1})
    assert entry["_provenance"]["coreAffixIds"] == ["affix.a"]


def test_fixed_core_respects_its_rarity_band():
    # cultivated's band is {min:1, max:1} — three "core" picks must be flagged, not silently kept.
    band = load_shape_tuning()["fixedCoreBandByRarity"]["cultivated"]
    draft = {
        "eligibleAffixes": [
            {"affixId": "affix.a", "affinity": "core"},
            {"affixId": "affix.b", "affinity": "core"},
            {"affixId": "affix.c", "affinity": "core"},
        ],
        "eligibilityTags": {"requireTags": [], "anyOfTags": []},
    }

    defects = fixed_core_within_band(draft, {"fixedCoreBand": band})

    assert defects, "3 core picks against a max-1 band should have been flagged"
    assert "3" in defects[0] and "1" in defects[0]


def test_a_draft_within_the_band_is_never_flagged():
    band = {"min": 1, "max": 2}
    draft = {"eligibleAffixes": [{"affixId": "a", "affinity": "core"}], "eligibilityTags": {"requireTags": [], "anyOfTags": []}}

    assert fixed_core_within_band(draft, {"fixedCoreBand": band}) == []


# ---- mixed bundle counts against both budgets ----------------------------------------------------


def test_mixed_bundle_counts_against_both_budgets():
    draft = {
        "eligibleAffixes": [
            {"affixId": "affix.mixed", "affinity": "likely"},
            {"affixId": "affix.prefix-only", "affinity": "occasional"},
        ],
        "eligibilityTags": {"requireTags": [], "anyOfTags": []},
    }

    def class_of(affix_id: str) -> str:
        return "Mixed" if affix_id == "affix.mixed" else "Prefix"

    entry = entry_for(REAL_ANCHOR, draft, affix_class_of=class_of, affix_refs_of=lambda _id: [])

    # affix.mixed counts against BOTH; affix.prefix-only counts against prefix only.
    assert entry["prefixRolls"] == 2
    assert entry["suffixRolls"] == 1


def test_a_pure_suffix_pool_never_touches_the_prefix_budget():
    draft = {
        "eligibleAffixes": [{"affixId": "affix.suffix", "affinity": "likely"}],
        "eligibilityTags": {"requireTags": [], "anyOfTags": []},
    }
    entry = entry_for(REAL_ANCHOR, draft, affix_class_of=lambda _id: "Suffix", affix_refs_of=lambda _id: [])

    assert entry["prefixRolls"] == 0
    assert entry["suffixRolls"] == 1


# ---- no numeric field survives the audit -----------------------------------------------------


def test_schema_forbids_any_field_beyond_affixId_and_affinity():
    props = SPECIES_EFFECTS_SCHEMA["properties"]["eligibleAffixes"]["items"]
    assert props["additionalProperties"] is False
    assert set(props["properties"]) == {"affixId", "affinity"}
    # affinity is a closed string enum, never a number.
    assert props["properties"]["affinity"]["type"] == "string"


def test_no_MODEL_INVENTED_numeric_field_survives_the_audit():
    """Corrected 2026-09-06: spec §6's "no weight... resolved downstream" describes the MODEL never
    inventing a magnitude (P1) — the committed container's own `pool` rows still need a real int
    `weight` to be legal `ContainerPoolRow` content at all (confirmed: `SpeciesMaterialiser`/
    `Instantiator.Draw` have no independent path to this module's own tuning at roll time, so
    "resolved downstream" cannot mean "absent from the committed file"). This function is what turns
    the model's own `affinity` ORDINAL into that weight, via a real tuning table — never a model
    literal. What the audit actually forbids: `tier`/`magnitude`/an affix-authored weight, and any
    weight that does NOT trace to `pool_affinity_weight_milli`'s own table."""
    draft = {
        "eligibleAffixes": [
            {"affixId": "affix.a", "affinity": "core"},
            {"affixId": "affix.b", "affinity": "likely"},
        ],
        "eligibilityTags": {"requireTags": ["element"], "anyOfTags": []},
    }
    entry = entry_for(REAL_ANCHOR, draft, affix_class_of=lambda _id: "Prefix",
                       affix_refs_of=REFS_BY_AFFIX.__getitem__,
                       pool_affinity_weight_milli={"likely": 700, "occasional": 300})

    forbidden_keys = {"tier", "magnitude", "poolRolls", "pool_rolls", "affinity"}
    assert forbidden_keys.isdisjoint(entry.keys())
    assert forbidden_keys.isdisjoint(entry["pool"][0].keys())
    # The one number that IS present traces exactly to the real tuning table, never invented here.
    assert entry["pool"][0]["weight"] == 700


def test_affix_ids_not_in_the_eligible_family_set_are_rejected():
    draft = {
        "eligibleAffixes": [{"affixId": "affix.invented", "affinity": "core"}],
        "eligibilityTags": {"requireTags": [], "anyOfTags": []},
    }
    defects = affix_ids_are_known(draft, {"eligibleFamilies": ["affix.real-one"]})

    assert defects and "affix.invented" in defects[0]


# ---- rerun over unchanged anchors is byte-identical ------------------------------------------------


def test_rerun_over_unchanged_anchors_is_byte_identical():
    draft = {
        "eligibleAffixes": [
            {"affixId": "affix.a", "affinity": "core"},
            {"affixId": "affix.b", "affinity": "likely"},
        ],
        "eligibilityTags": {"requireTags": ["element"], "anyOfTags": []},
    }
    provenance = {"anchorHash": "abc123", "promptVersion": 1}

    first = entry_for(REAL_ANCHOR, draft, affix_class_of=lambda _id: "Prefix",
                       affix_refs_of=REFS_BY_AFFIX.__getitem__, provenance=provenance)
    second = entry_for(REAL_ANCHOR, draft, affix_class_of=lambda _id: "Prefix",
                        affix_refs_of=REFS_BY_AFFIX.__getitem__, provenance=provenance)

    assert first == second


# ---- dry-run makes zero calls, and the graph shape matches the shared skeleton -----------------------


def test_dry_run_makes_zero_calls():
    pytest.importorskip("langgraph.graph")

    def raising_call(*args, **kwargs):
        raise AssertionError("the model must never be called by building the graph alone")

    spec = spec_for_species(eligible_families=("affix.a",), rarity_bands=("cultivated",), tag_set=("element",))
    graph = build_species_effects_graph(spec, call=raising_call)

    assert graph is not None


def test_state_for_species_carries_the_species_own_fixed_core_band():
    spec = spec_for_species(eligible_families=("affix.a",), rarity_bands=("cultivated",), tag_set=("element",))
    state = state_for_species(spec, REAL_ANCHOR)

    assert state["context"]["fixedCoreBand"] == load_shape_tuning()["fixedCoreBandByRarity"]["cultivated"]
    assert state["subject_id"] == "Peashooter"


def test_the_graph_reuses_the_shared_skeleton_not_a_new_one():
    pytest.importorskip("langgraph.graph")

    spec = spec_for_species(eligible_families=("affix.a",), rarity_bands=("cultivated",), tag_set=("element",))
    app = build_species_effects_graph(spec, call=lambda *a, **k: '{"eligibleAffixes": [], "eligibilityTags": {"requireTags": [], "anyOfTags": []}}')

    nodes = set(app.get_graph().nodes)
    assert {"generate", "validate", "persist", "escalate"} <= nodes
