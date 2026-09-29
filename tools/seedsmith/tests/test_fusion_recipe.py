"""creature-seed module 17 `fusion-recipe-generator` (spec-fusion-recipe-generator.md):
- T8.2 §2 `fusion-recipe-propose` — the propose MECHANISM only: canonicalization, per-member
  voting, A/B assignment, and the bounded prompt/schema shape. Pure functions over synthetic
  fixtures, no live model call.
- T8.3 §3/§3a/§4 `fusion-recipe-reconcile` — the deterministic reconciler's own validation,
  freeze-on-commit, and `crossRungGapFill` logic, exercised via synthetic seam fixtures (a fake
  `propose_fn` stands in for a live model — matching `anchor/vote.py`'s own test shape) PLUS one
  real end-to-end case that shells out to the actual `gk-forge/tools/CreatureRecipeReconcileInput` CLI against
  the real corpus (no model needed, since the real corpus's deterministic pass alone is what is
  being proven there).

The "-k not live" filter is for this module's own real endpoint tests (Checkpoint 8a, owner-run);
nothing in this file needs one.
"""
from __future__ import annotations

import subprocess

import pytest

from seedsmith.adapters.creatures.fusion import emit, reconcile
from seedsmith.adapters.creatures.fusion.prompts import (
    MAX_RUNG_DISTANCE,
    DeficitOutput,
    FusionCandidate,
    build_fusion_proposal_brief,
)
from seedsmith.adapters.creatures.fusion.schema import build_fusion_proposal_schema
from seedsmith.adapters.creatures.fusion.vote import assign_input_a_b, resolve_fusion_pair_vote


# --- vote.py: canonicalization + per-member majority --------------------------------------------

def test_a_pair_proposed_as_A_B_and_B_A_by_different_samples_votes_as_agreement():
    r = resolve_fusion_pair_vote([("firstseed-a", "sunwoven-b"), ("sunwoven-b", "firstseed-a"), ("firstseed-a", "sunwoven-b")])
    assert r.confidence == "high"
    assert r.pair == ("firstseed-a", "sunwoven-b")  # sorted


def test_two_of_three_samples_choosing_a_species_resolves_it_even_when_the_third_disagrees_on_the_partner():
    # "bee" is proposed by all three; "ant" by two of three; the third proposes "cat" instead of
    # "ant". Whole-pair equality would see three DIFFERENT pairs (bee+ant, bee+ant, bee+cat is
    # actually 2 identical + 1 different — still a real per-member majority case) and this is
    # exactly the scenario spec §2 names: 2-of-3 agreeing on a species resolves it even though the
    # third sample disagreed on who its partner was.
    r = resolve_fusion_pair_vote([("bee", "ant"), ("bee", "ant"), ("bee", "cat")])
    assert r.pair == ("ant", "bee")  # sorted; "cat" (1 vote) never clears the 2-of-3 threshold
    assert r.confidence == "split"


def test_a_1_1_1_split_with_no_species_at_majority_is_unresolved_not_sample_zeros_pick():
    r = resolve_fusion_pair_vote([("a", "b"), ("c", "d"), ("e", "f")])
    assert r.pair is None
    assert r.confidence == "unresolved"
    # Never silently returns sample 0's raw pick ("a", "b") — the one failure mode spec §2
    # explicitly calls out by name.
    assert r.pair != ("a", "b")


def test_a_three_way_cyclic_tie_is_unresolved_not_a_three_species_recipe():
    # A real edge case a naive ">=2 of 3" check misses: A-B / B-C / C-A each puts every member at
    # EXACTLY 2 votes, so all three clear the per-member threshold — resolve_set_vote itself would
    # report a 3-member "split" set. A fusion recipe takes exactly two inputs, so this must resolve
    # to unresolved, not a fabricated 3-species recipe.
    r = resolve_fusion_pair_vote([("a", "b"), ("b", "c"), ("c", "a")])
    assert r.pair is None
    assert r.confidence == "unresolved"


def test_a_single_unanimous_member_with_no_second_member_reaching_majority_is_unresolved():
    # "a" is unanimous (3/3) but b/c/d each appear only once — resolve_set_vote would happily
    # return a 1-member "split" result (valid for an open-arity field like `family`), but a fusion
    # recipe cannot ship with only one input, so this must be unresolved too.
    r = resolve_fusion_pair_vote([("a", "b"), ("a", "c"), ("a", "d")])
    assert r.pair is None
    assert r.confidence == "unresolved"


def test_resolve_fusion_pair_vote_rejects_a_sample_that_is_not_a_pair():
    with pytest.raises(ValueError):
        resolve_fusion_pair_vote([("a", "b", "c"), ("a", "b"), ("a", "b")])


# --- vote.py: A/B assignment ---------------------------------------------------------------------

def test_assign_input_a_b_picks_the_output_element_match_as_A():
    a, b = assign_input_a_b(
        ("fire-candidate", "ice-candidate"),
        candidate_elements={"fire-candidate": "fire", "ice-candidate": "ice"},
        output_element_primary="fire",
    )
    assert (a, b) == ("fire-candidate", "ice-candidate")


def test_assign_input_a_b_breaks_a_tie_on_species_id_ordinal_when_both_match():
    a, b = assign_input_a_b(
        ("zzz-fire", "aaa-fire"),
        candidate_elements={"zzz-fire": "fire", "aaa-fire": "fire"},
        output_element_primary="fire",
    )
    assert (a, b) == ("aaa-fire", "zzz-fire")


def test_assign_input_a_b_breaks_a_tie_on_species_id_ordinal_when_neither_matches():
    a, b = assign_input_a_b(
        ("zzz-ice", "aaa-earth"),
        candidate_elements={"zzz-ice": "ice", "aaa-earth": "earth"},
        output_element_primary="fire",
    )
    assert (a, b) == ("aaa-earth", "zzz-ice")


# --- prompts.py: bounded pool, mechanically enforced ---------------------------------------------

_OUTPUT = DeficitOutput(species_id="ultimatepaperzombie-heir", element_primary="dark", rarity="almanac")


def _candidate(species_id: str, rung_distance: int, element: str = "dark") -> FusionCandidate:
    return FusionCandidate(species_id=species_id, element_primary=element, rarity="sunwoven",
                            acquisition=("Summonable",), rung_distance=rung_distance)


def test_the_LLM_prompt_never_includes_a_species_more_than_the_bounded_rungs_below_the_output():
    too_far = _candidate("way-too-deep", rung_distance=MAX_RUNG_DISTANCE + 1)
    with pytest.raises(ValueError):
        build_fusion_proposal_brief(_OUTPUT, [_candidate("near", 1), too_far], claimed_pairs=[])


def test_the_LLM_prompt_accepts_every_rung_within_the_bound():
    candidates = [_candidate("near", 1), _candidate("mid", 2), _candidate("far", MAX_RUNG_DISTANCE)]
    brief = build_fusion_proposal_brief(_OUTPUT, candidates, claimed_pairs=[])
    for c in candidates:
        assert c.species_id in brief


def test_the_LLM_prompt_needs_at_least_two_candidates():
    with pytest.raises(ValueError):
        build_fusion_proposal_brief(_OUTPUT, [_candidate("only-one", 1)], claimed_pairs=[])


def test_the_LLM_prompt_shows_acquisition_and_already_claimed_pairs():
    candidates = [_candidate("near", 1), _candidate("mid", 2)]
    brief = build_fusion_proposal_brief(_OUTPUT, candidates, claimed_pairs=[("near", "someone-else")])
    assert "Summonable" in brief
    assert "near" in brief and "someone-else" in brief


# --- schema.py: bounded enum, echo-back id ---------------------------------------------------------

def test_the_proposal_schema_constrains_inputs_to_the_shown_pool_only():
    schema = build_fusion_proposal_schema("ultimatepaperzombie-heir", ["near", "mid", "far"])
    assert schema["properties"]["inputA"]["enum"] == ["near", "mid", "far"]
    assert schema["properties"]["inputB"]["enum"] == ["near", "mid", "far"]
    assert schema["properties"]["speciesId"]["enum"] == ["ultimatepaperzombie-heir"]
    assert schema["required"] == ["speciesId", "inputA", "inputB", "reason"]
    assert schema["additionalProperties"] is False


def test_the_proposal_schema_needs_at_least_two_candidates():
    with pytest.raises(ValueError):
        build_fusion_proposal_schema("out", ["only-one"])


# ==================================================================================================
# T8.3 — fusion-recipe-reconcile: the deterministic reconciler's own validation and freeze rules.
# ==================================================================================================

def _seam_candidate(species_id: str, rarity: str, *, element: str = "dark", acquisition=("Summonable",), rung_distance: int = 1) -> dict:
    return {"speciesId": species_id, "elementPrimary": element, "rarity": rarity,
            "acquisition": list(acquisition), "rungDistance": rung_distance}


def _deficit(output_id: str, candidates: "list[dict]", *, element: str = "dark", rarity: str = "almanac", nearest: str = "sunwoven") -> dict:
    return {"outputSpeciesId": output_id, "elementPrimary": element, "rarity": rarity,
            "nearestPopulatedRung": nearest, "candidatePool": candidates}


def _seam(*, deterministic=(), deficits=()) -> dict:
    return {"eligibleOutputs": [], "deterministicRecipes": list(deterministic), "deficits": list(deficits)}


def _fixed_sample_fn(*sample_sets):
    """A fake propose_fn returning one canned 3-sample list per call, in order — raises if called
    more times than fixtures were supplied (catches an accidental extra model call)."""
    calls = iter(sample_sets)

    def _fn(output, candidates, claimed):
        try:
            return next(calls)
        except StopIteration:
            raise AssertionError(f"propose_fn called more times than expected (for {output.species_id!r})")

    return _fn


def test_zero_shortfall_roster_never_calls_the_model():
    seam = _seam(deterministic=[{"recipeId": "recipe.x", "outputSpeciesId": "x", "inputSpeciesIdA": "a", "inputSpeciesIdB": "b"}])

    def _boom(*a, **kw):
        raise AssertionError("propose_fn must never be called when there are zero deficits")

    outcome = reconcile.reconcile(seam, _boom)
    assert outcome.recipes["recipe.x"]["crossRungGapFill"] is False
    assert outcome.unresolved == []
    assert outcome.model_calls_made == []


def test_a_pair_proposed_as_A_B_and_B_A_by_different_samples_votes_as_agreement_end_to_end():
    pool = [_seam_candidate("in-a", "sunwoven"), _seam_candidate("in-b", "sunwoven"), _seam_candidate("in-c", "sunwoven")]
    seam = _seam(deficits=[_deficit("out-1", pool)])
    propose = _fixed_sample_fn([("in-a", "in-b"), ("in-b", "in-a"), ("in-a", "in-b")])

    outcome = reconcile.reconcile(seam, propose)
    recipe = outcome.recipes["recipe.out-1"]
    assert {recipe["inputSpeciesIdA"], recipe["inputSpeciesIdB"]} == {"in-a", "in-b"}
    assert outcome.unresolved == []


def test_two_of_three_samples_choosing_a_species_resolves_it_even_when_the_third_disagrees_on_the_partner_end_to_end():
    pool = [_seam_candidate("bee", "sunwoven"), _seam_candidate("ant", "sunwoven"), _seam_candidate("cat", "sunwoven")]
    seam = _seam(deficits=[_deficit("out-1", pool)])
    propose = _fixed_sample_fn([("bee", "ant"), ("bee", "ant"), ("bee", "cat")])

    outcome = reconcile.reconcile(seam, propose)
    recipe = outcome.recipes["recipe.out-1"]
    assert {recipe["inputSpeciesIdA"], recipe["inputSpeciesIdB"]} == {"bee", "ant"}


def test_a_1_1_1_split_with_no_species_at_majority_is_unresolved_not_sample_zeros_pick_end_to_end():
    pool = [_seam_candidate("a", "sunwoven"), _seam_candidate("b", "sunwoven"), _seam_candidate("c", "sunwoven"),
            _seam_candidate("d", "sunwoven"), _seam_candidate("e", "sunwoven"), _seam_candidate("f", "sunwoven")]
    seam = _seam(deficits=[_deficit("out-1", pool)])
    propose = _fixed_sample_fn([("a", "b"), ("c", "d"), ("e", "f")])

    outcome = reconcile.reconcile(seam, propose)
    assert "recipe.out-1" not in outcome.recipes
    assert outcome.unresolved == ["out-1"]


def test_a_capture_only_proposed_input_is_refused_not_silently_dropped():
    pool = [_seam_candidate("locked", "sunwoven", acquisition=("CaptureOnly",)), _seam_candidate("free", "sunwoven")]
    seam = _seam(deficits=[_deficit("out-1", pool)])
    # All 3 samples agree on the CaptureOnly pair — a real, resolved vote that must still be refused.
    propose = _fixed_sample_fn([("locked", "free")] * 3)

    outcome = reconcile.reconcile(seam, propose)
    assert "recipe.out-1" not in outcome.recipes
    assert outcome.unresolved == ["out-1"]


def test_a_candidate_with_summonable_and_captureonly_both_set_is_a_legal_input():
    # Real corpus case (e.g. "blackfootball"): CreatureRecipeCatalog.cs's own established rule
    # everywhere (`Acquisition != CreatureAcquisition.CaptureOnly`, exact equality) admits a
    # multi-flag Summonable+CaptureOnly species into the candidate pool, since it is not
    # EXCLUSIVELY capture-only — a player can still summon it. Owner lock 6 must match that same
    # rule, not reject on "CaptureOnly present at all".
    pool = [_seam_candidate("dual-flag", "sunwoven", acquisition=("Summonable", "CaptureOnly")),
            _seam_candidate("free", "sunwoven")]
    seam = _seam(deficits=[_deficit("out-1", pool)])
    propose = _fixed_sample_fn([("dual-flag", "free")] * 3)

    outcome = reconcile.reconcile(seam, propose)
    assert "recipe.out-1" in outcome.recipes
    assert outcome.unresolved == []


def test_a_duplicate_proposed_pair_is_refused():
    pool = [_seam_candidate("x", "sunwoven"), _seam_candidate("y", "sunwoven")]
    seam = _seam(
        deterministic=[{"recipeId": "recipe.other", "outputSpeciesId": "other", "inputSpeciesIdA": "x", "inputSpeciesIdB": "y"}],
        deficits=[_deficit("out-1", pool)],
    )
    propose = _fixed_sample_fn([("x", "y")] * 3)  # the only possible pair, already claimed deterministically

    outcome = reconcile.reconcile(seam, propose)
    assert "recipe.out-1" not in outcome.recipes
    assert outcome.unresolved == ["out-1"]


def test_two_deficits_colliding_on_usedPairs_resolve_the_same_way_across_reruns():
    # Both deficits' votes resolve to the SAME pair {x, y} — only the SpeciesId-ordinal-first
    # output ("out-a" < "out-b") may claim it; the second must be refused, and this must hold
    # identically across independent runs (no incidental dict/order dependence).
    pool = [_seam_candidate("x", "sunwoven"), _seam_candidate("y", "sunwoven")]
    seam = _seam(deficits=[_deficit("out-b", pool), _deficit("out-a", pool)])  # deliberately out of order

    def run_once():
        propose = _fixed_sample_fn([("x", "y")] * 3, [("x", "y")] * 3)
        return reconcile.reconcile(seam, propose)

    for _ in range(2):
        outcome = run_once()
        assert "recipe.out-a" in outcome.recipes
        assert "recipe.out-b" not in outcome.recipes
        assert outcome.unresolved == ["out-b"]
        # Processed in SpeciesId order regardless of the seam's own list order.
        assert outcome.model_calls_made == ["out-a", "out-b"]


def test_crossRungGapFill_is_set_only_on_a_reconciled_gap_fill_recipe():
    same_rung_pool = [_seam_candidate("s1", "sunwoven", rung_distance=1), _seam_candidate("s2", "sunwoven", rung_distance=1)]
    cross_rung_pool = [_seam_candidate("s1", "sunwoven", rung_distance=1), _seam_candidate("f1", "firstseed", rung_distance=2)]
    seam = _seam(
        deterministic=[{"recipeId": "recipe.det", "outputSpeciesId": "det", "inputSpeciesIdA": "p", "inputSpeciesIdB": "q"}],
        deficits=[_deficit("same-rung-out", same_rung_pool), _deficit("cross-rung-out", cross_rung_pool)],
    )
    # reconcile() processes deficits in SpeciesId-ordinal order regardless of the seam's own list
    # order — "cross-rung-out" < "same-rung-out" — so the fake sampler's args are supplied in THAT
    # order, matching the real call order, not the order the deficits are listed above.
    propose = _fixed_sample_fn([("s1", "f1")] * 3, [("s1", "s2")] * 3)

    outcome = reconcile.reconcile(seam, propose)
    assert outcome.recipes["recipe.det"]["crossRungGapFill"] is False
    assert outcome.recipes["recipe.same-rung-out"]["crossRungGapFill"] is False
    assert outcome.recipes["recipe.cross-rung-out"]["crossRungGapFill"] is True


def test_an_unresolved_deficit_ships_with_no_recipe_not_a_fabricated_one():
    pool = [_seam_candidate("a", "sunwoven"), _seam_candidate("b", "sunwoven"), _seam_candidate("c", "sunwoven")]
    seam = _seam(deficits=[_deficit("out-1", pool)])
    propose = _fixed_sample_fn([(None), (None), (None)])  # every sample heal-exhausted

    outcome = reconcile.reconcile(seam, propose)
    assert list(outcome.recipes.keys()) == []
    assert outcome.unresolved == ["out-1"]


def test_a_rerun_with_an_unchanged_candidate_pool_never_calls_the_model_again():
    pool = [_seam_candidate("x", "sunwoven"), _seam_candidate("y", "sunwoven")]
    seam = _seam(deficits=[_deficit("out-1", pool)])

    first = reconcile.reconcile(seam, _fixed_sample_fn([("x", "y")] * 3))
    assert first.model_calls_made == ["out-1"]

    def _boom(*a, **kw):
        raise AssertionError("an unchanged candidate pool must never re-call the model")

    second = reconcile.reconcile(seam, _boom, existing_seed=first.recipes)
    assert second.model_calls_made == []
    assert second.recipes == first.recipes  # byte-identical entry, including its provenance


def test_a_changed_candidate_pool_re_derives_only_the_affected_entry():
    # Disjoint pools so both deficits resolve independently in v1 (a shared pool would make them
    # compete for the same one pair, defeating this test's own premise).
    stable_pool = [_seam_candidate("x", "sunwoven"), _seam_candidate("y", "sunwoven")]
    changing_pool_v1 = [_seam_candidate("p", "sunwoven"), _seam_candidate("q", "sunwoven")]
    seam_v1 = _seam(deficits=[_deficit("stable-out", stable_pool), _deficit("changing-out", changing_pool_v1)])
    # Processed in SpeciesId order: "changing-out" < "stable-out".
    v1 = reconcile.reconcile(seam_v1, _fixed_sample_fn([("p", "q")] * 3, [("x", "y")] * 3))

    # "changing-out"'s pool grows a new candidate — its own corpusContentHash changes; "stable-out"'s
    # pool and hash are untouched.
    changing_pool_v2 = changing_pool_v1 + [_seam_candidate("r", "sunwoven")]
    seam_v2 = _seam(deficits=[_deficit("stable-out", stable_pool), _deficit("changing-out", changing_pool_v2)])

    calls: "list[str]" = []

    def _tracking_propose(output, candidates, claimed):
        calls.append(output.species_id)
        return [("p", "q")] * 3

    v2 = reconcile.reconcile(seam_v2, _tracking_propose, existing_seed=v1.recipes)
    assert calls == ["changing-out"]  # "stable-out" never re-called
    assert v2.recipes["recipe.stable-out"] == v1.recipes["recipe.stable-out"]


def test_reconcile_check_refuses_a_stale_committed_file(tmp_path):
    recipes = {"recipe.x": {"outputSpeciesId": "x", "inputSpeciesIdA": "a", "inputSpeciesIdB": "b", "crossRungGapFill": False}}
    out = tmp_path / "_fusion-recipes.json"

    assert emit.check(recipes, out) != []  # missing file is stale
    assert emit.write(recipes, out) is True
    assert emit.check(recipes, out) == []  # freshly written, now clean

    out.write_text(out.read_text(encoding="utf-8").replace("false", "true"), encoding="utf-8")  # hand-edit
    assert emit.check(recipes, out) != []  # hand-edited file is stale again


def test_a_clean_rewrite_of_identical_content_writes_nothing(tmp_path):
    recipes = {"recipe.x": {"outputSpeciesId": "x", "inputSpeciesIdA": "a", "inputSpeciesIdB": "b", "crossRungGapFill": False}}
    out = tmp_path / "_fusion-recipes.json"
    assert emit.write(recipes, out) is True
    assert emit.write(recipes, out) is False  # unchanged content -> no write


def test_real_corpus_end_to_end():
    """Shells out to the REAL `gk-forge/tools/CreatureRecipeReconcileInput` CLI (no model needed — this proves
    the seam integration and the reconciler's own bookkeeping against the actual corpus). The seam's
    output counts move whenever species ship (the corpus is a population — validation-ssot.md), so
    this asserts the reconciler's CONTRACT rather than the 2026-09-07 snapshot: every deterministic
    recipe survives reconcile untouched, every named deficit stays unresolved through a always-fail
    propose_fn, and no gap-fill is fabricated.
    History (a reading, not a pin): 840 -> 903 species, then 904; 774/758/16 -> 775/759/16."""
    try:
        seam = reconcile.run_seam_cli()
    except (RuntimeError, FileNotFoundError, OSError) as e:
        pytest.skip(f"real C# seam not runnable in this environment: {e}")

    eligible = len(seam["eligibleOutputs"])
    deterministic = len(seam["deterministicRecipes"])
    deficits = len(seam["deficits"])
    assert deterministic + deficits == eligible, (
        "every eligible output is either covered by a deterministic recipe or is a named deficit")
    assert deterministic > 0 and deficits > 0, "real corpus must exercise both branches"

    # A propose_fn that always fails to resolve — proves the real deficits pass all the way through
    # reconcile() as named, unresolved outputs, and every deterministic recipe survives untouched,
    # with zero gap-fills fabricated.
    outcome = reconcile.reconcile(seam, _fixed_sample_fn(*([(None, None, None)] * deficits)))
    assert len(outcome.recipes) == deterministic
    assert len(outcome.unresolved) == deficits
    assert all(r["crossRungGapFill"] is False for r in outcome.recipes.values())
    print(f"fusion seam: {eligible} eligible = {deterministic} deterministic + {deficits} deficits")


def test_deterministic_only_propose_fn_never_resolves_and_makes_no_model_call():
    # The exact function `--deterministic-only` wires in — asserted directly since main()'s own CLI
    # wiring isn't exercised by these tests (it shells out to the real seam every invocation).
    pool = [_seam_candidate("a", "sunwoven"), _seam_candidate("b", "sunwoven"), _seam_candidate("c", "sunwoven")]
    seam = _seam(deficits=[_deficit("out-1", pool)])

    outcome = reconcile.reconcile(seam, reconcile._deterministic_only_propose_fn)
    assert outcome.unresolved == ["out-1"]
    assert "recipe.out-1" not in outcome.recipes
