"""T7.1 (`affix-authoring`, spec-affix-authoring.md, effect-pipeline module 9) — the named,
multi-atom, slotted affix pipeline. Reuses `creature-seed`'s own `classify-pipelines` machinery
(`permute`/`vote`) and T5.0's own `build_generation_graph` skeleton — this file proves BOTH: the
domain logic (derivation, voting, numeric-smuggling), and that no second pipeline shape was forked
to build it.
"""
from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from seedsmith.adapters.creatures.anchor.audit import numeric_audit
from seedsmith.adapters.creatures.anchor.vote import resolve_vote
from seedsmith.adapters.effects.affix.derive import canonical_bundle_key, derive_affix_class
from seedsmith.adapters.effects.affix.generate_affixes import next_draw_start_index, run_voted_draws
from seedsmith.adapters.effects.affix.prompts import (
    AFFIX_SCHEMA,
    ID_PREFIX,
    build_brief,
    build_context,
    bundle_has_at_least_two_refs,
    entry_for,
    refs_are_known_atoms,
)
from seedsmith.workflow.graphs.effect_affix import build_affix_authoring_graph, state_for_affix

REPO_ROOT = Path(__file__).resolve().parents[3]

# `REPO_ROOT`-relative joins below ask which repository actually carries the path. A prefix-keyed
# rewrite is wrong: `data`, `data/seed` and `data/seed/creatures` all resolve back to gk-forge,
# because nearest-match-wins and gk-forge owns its own generator inputs. `or REPO_ROOT` is
# load-bearing - `owning_base` returns None for a path no repository carries, where
# `content_root()` would RAISE.

from seedsmith.workspace_roots import owning_base  # noqa: E402


def _owned(relative: str) -> "Path":
    """The repository carrying `relative`, joined to it; this one when none carries it."""
    return (owning_base(relative, REPO_ROOT) or REPO_ROOT) / relative

ADAPTER_DIR = _owned("tools/seedsmith/seedsmith/adapters/effects/affix")
GRAPH_FILE = _owned("tools/seedsmith/seedsmith/workflow/graphs/effect_affix.py")


# ---- affix_class is derived, never authored (P1 / seed-contract §2.1) -------------------------------


def test_prefix_when_no_atom_in_the_bundle_has_a_trigger():
    assert derive_affix_class(["atom.a", "atom.b"], has_trigger=lambda a: False) == "prefix"


def test_suffix_when_every_atom_in_the_bundle_has_a_trigger():
    assert derive_affix_class(["atom.a", "atom.b"], has_trigger=lambda a: True) == "suffix"


def test_mixed_when_the_bundle_spans_both_kinds():
    assert derive_affix_class(
        ["atom.passive", "atom.proc"], has_trigger=lambda a: a == "atom.proc"
    ) == "mixed"


def test_an_empty_bundle_raises_rather_than_guessing():
    with pytest.raises(ValueError):
        derive_affix_class([], has_trigger=lambda a: False)


def test_affix_class_is_never_a_field_the_model_authors():
    """The model's own draft schema has no `affixClass` property at all — deriving it is the ONLY
    way it reaches the committed entry. The committed key is `class`, matching
    AtomSeedFile.ReadAffix's real reader, never `affixClass` (found and fixed 2026-09-05 running
    this pipeline's real output through the real AtomImporter for the first time)."""
    assert "affixClass" not in AFFIX_SCHEMA["properties"]
    entry = entry_for({"name": "Master of Fire and Ice", "refs": ["atom.a", "atom.b"]},
                       affix_id="affix.authored.test", affix_class="mixed")
    assert entry["class"] == "mixed"
    assert "affixClass" not in entry


# ---- named bundle composition is 3-way voted, same machinery as creature-seed --------------------------


def test_a_3_0_bundle_vote_resolves_high_confidence():
    key = canonical_bundle_key(["atom.a", "atom.b"])
    result = resolve_vote([key, key, key])
    assert result.confidence == "high"
    assert result.value == key


def test_a_reordered_but_identical_bundle_still_counts_as_agreement():
    a = canonical_bundle_key(["atom.b", "atom.a"])
    b = canonical_bundle_key(["atom.a", "atom.b"])
    assert a == b  # canonicalisation, not luck


def test_a_2_1_split_on_bundle_composition_records_the_minority():
    majority = canonical_bundle_key(["atom.a", "atom.b"])
    minority = canonical_bundle_key(["atom.a", "atom.c"])
    result = resolve_vote([majority, majority, minority])
    assert result.confidence == "split"
    assert result.value == majority
    assert result.minority == minority


def test_a_1_1_1_split_on_bundle_composition_resolves_unresolved():
    a = canonical_bundle_key(["atom.a", "atom.b"])
    b = canonical_bundle_key(["atom.a", "atom.c"])
    c = canonical_bundle_key(["atom.a", "atom.d"])
    result = resolve_vote([a, b, c])
    assert result.confidence == "unresolved"
    assert result.value is None  # never silently the first sample


# ---- draw_id continuation (fixed 2026-09-06, [[affix-authoring-vote-bug]]'s second defect) --------


def test_next_draw_start_index_is_zero_on_an_empty_catalog():
    assert next_draw_start_index({}) == 0


def test_next_draw_start_index_continues_past_the_highest_existing_draw():
    existing = {
        "affix.authored.affix-draw-000": {},
        "affix.authored.affix-draw-007": {},
        "affix.authored.affix-draw-002": {},
    }
    assert next_draw_start_index(existing) == 8


def test_next_draw_start_index_ignores_non_draw_ids():
    """A future non-draw-shaped affix id (hand-authored, or from a different pipeline) must never
    perturb the draw-index sequence it has nothing to do with."""
    existing = {
        "affix.authored.affix-draw-003": {},
        "affix.hand-authored.something-else": {},
    }
    assert next_draw_start_index(existing) == 4


def test_next_draw_start_index_works_unmodified_over_a_species_namespaced_id():
    """Task J7: `next_draw_start_index` needed NO change to support `--species-id` — it reads the
    suffix AFTER `affix-draw-`, never the prefix, so a species-namespaced id
    (`affix.species.Alpha.affix-draw-002`) continues the sequence exactly like the shared
    `affix.authored.*` one already does."""
    existing = {"affix.species.Alpha.affix-draw-002": {}}
    assert next_draw_start_index(existing) == 3


def test_a_second_run_never_overwrites_the_first_runs_entries():
    """The actual regression this fixes: two back-to-back invocations must produce two DISTINCT
    committed entries, never the second silently replacing the first via a repeated draw-000 id —
    reproduced for real against the live model 2026-09-06 (`Frostbite Venom` was overwritten)."""
    first_responses = [
        {"name": "First Pass", "refs": ["atom.a", "atom.b"]},
    ] * 3
    call1, _ = _stub_call(first_responses)
    fresh1, unresolved1, _ = run_voted_draws(
        count=1, eligible=["atom.a", "atom.b", "atom.c", "atom.d"],
        atom_triggers={"atom.a": False, "atom.b": False, "atom.c": False, "atom.d": False},
        provenance_base={"pipeline": "affix-authoring", "model": "test"},
        start_index=0, call=call1, workers=1)
    assert unresolved1 == {}
    assert set(fresh1) == {"affix.authored.affix-draw-000"}

    second_responses = [
        {"name": "Second Pass", "refs": ["atom.c", "atom.d"]},
    ] * 3
    call2, _ = _stub_call(second_responses)
    start = next_draw_start_index(fresh1)
    fresh2, unresolved2, _ = run_voted_draws(
        count=1, eligible=["atom.a", "atom.b", "atom.c", "atom.d"],
        atom_triggers={"atom.a": False, "atom.b": False, "atom.c": False, "atom.d": False},
        provenance_base={"pipeline": "affix-authoring", "model": "test"},
        start_index=start, call=call2, workers=1)
    assert unresolved2 == {}
    assert set(fresh2) == {"affix.authored.affix-draw-001"}, (
        "the second run must land on a NEW draw id, never reuse draw-000 and silently overwrite it")

    merged = {**fresh1, **fresh2}
    assert len(merged) == 2
    assert merged["affix.authored.affix-draw-000"]["name"] == "First Pass"
    assert merged["affix.authored.affix-draw-001"]["name"] == "Second Pass"


def test_id_prefix_defaults_to_the_shared_affix_authored_namespace():
    """Every pre-J7 call site never passes `id_prefix` at all -- must keep producing exactly the
    same `affix.authored.*` ids it always has."""
    call, _ = _stub_call([{"name": "Plain", "refs": ["atom.a", "atom.b"]}] * 3)
    fresh, _, _ = run_voted_draws(
        count=1, eligible=["atom.a", "atom.b"], atom_triggers={"atom.a": False, "atom.b": False},
        provenance_base={"pipeline": "affix-authoring", "model": "test"}, call=call, workers=1)
    assert set(fresh) == {"affix.authored.affix-draw-000"}


def test_id_prefix_overrides_into_a_species_namespace():
    """Task J7: `--species-id Alpha` derives `id_prefix="affix.species.Alpha."` -- proven here at
    the `run_voted_draws` layer the CLI flag ultimately calls into, matching U3's own
    `affix.species.<speciesId>.*` pattern (`metrics/passive_tree.py`, task J6)."""
    call, _ = _stub_call([{"name": "Ember Mark", "refs": ["atom.a", "atom.b"]}] * 3)
    fresh, unresolved, _ = run_voted_draws(
        count=1, eligible=["atom.a", "atom.b"], atom_triggers={"atom.a": False, "atom.b": False},
        provenance_base={"pipeline": "affix-authoring", "model": "test"}, call=call, workers=1,
        id_prefix="affix.species.Alpha.")
    assert unresolved == {}
    assert set(fresh) == {"affix.species.Alpha.affix-draw-000"}


def test_load_existing_defaults_match_the_shared_corpus_path(tmp_path, monkeypatch):
    import seedsmith.adapters.effects.affix.generate_affixes as ga
    monkeypatch.setattr(ga, "OUTPUT_DIR", tmp_path)
    (tmp_path / "all.json").write_text(json.dumps(
        {"schemaVersion": 1, "kind": "affix", "entries": [{"id": "affix.authored.affix-draw-000"}]}),
        encoding="utf-8")
    assert set(ga.load_existing()) == {"affix.authored.affix-draw-000"}


def test_load_existing_reads_a_species_specific_file_when_given_one(tmp_path):
    from seedsmith.adapters.effects.affix.generate_affixes import load_existing
    species_dir = tmp_path / "species"
    species_dir.mkdir()
    (species_dir / "Alpha.json").write_text(json.dumps(
        {"schemaVersion": 1, "kind": "affix", "_meta": {"partition": "Alpha"},
        "entries": [{"id": "affix.species.Alpha.affix-draw-000"}]}), encoding="utf-8")
    existing = load_existing(species_dir, "Alpha.json")
    assert set(existing) == {"affix.species.Alpha.affix-draw-000"}


def test_load_existing_a_missing_species_file_is_empty_not_an_error(tmp_path):
    from seedsmith.adapters.effects.affix.generate_affixes import load_existing
    assert load_existing(tmp_path / "species", "Beta.json") == {}


# ---- T7.2: name + ref bundle are voted through the REAL generate_affixes CLI path, not resolve_vote
# ---- called in isolation -----------------------------------------------------------------------------


def _stub_call(responses: "list[dict]"):
    """A `call()` double plus the captured `user` briefs, in call order — the same injection seam
    `build_affix_authoring_graph(call=...)` already uses everywhere else in this file, used here to
    prove `run_voted_draws` (what `generate_affixes.main()` itself calls) makes THREE model calls
    per draw, not one. Zero real HTTP: this never reaches `llm_caller.call_model`."""
    log: "list[str]" = []

    def call(system, user, *, config=None, schema=None):
        log.append(user)
        return json.dumps(responses[len(log) - 1])

    return call, log


def test_named_bundle_composition_is_3_way_voted_via_generate_affixes_cli():
    """A real 2-1 split on the ref bundle, driven through `run_voted_draws` — the actual function
    `generate_affixes.main()` calls — not `resolve_vote` called directly against a fixture."""
    responses = [
        {"name": "Master of Fire and Ice", "refs": ["atom.a", "atom.b"]},
        {"name": "Master of Fire and Ice", "refs": ["atom.b", "atom.a"]},  # reordered, same bundle
        {"name": "Master of Fire and Ice", "refs": ["atom.a", "atom.c"]},  # minority
    ]
    call, log = _stub_call(responses)

    fresh, unresolved, results = run_voted_draws(
        count=1, eligible=["atom.a", "atom.b", "atom.c"],
        atom_triggers={"atom.a": False, "atom.b": False, "atom.c": True},
        provenance_base={"pipeline": "affix-authoring", "model": "test"},
        call=call, workers=1)

    assert len(log) == 3, "one draw must make exactly THREE model calls, not one"
    assert len(set(log)) > 1, "the three calls must carry genuinely different (permuted) briefs"

    assert unresolved == {}
    assert len(fresh) == 1
    entry = next(iter(fresh.values()))
    assert entry["name"] == "Master of Fire and Ice"
    # refs are objects with an "atom" key (AtomSeedFile.ReadAffix's real shape), not bare id
    # strings — a bare string is silently skipped by the real reader (found 2026-09-05).
    assert sorted(r["atom"] for r in entry["refs"]) == ["atom.a", "atom.b"]
    assert all("seq" in r for r in entry["refs"])
    assert entry["_provenance"]["voteConfidence"]["refs"] == "split"
    # Fixed 2026-09-06 ([[affix-authoring-vote-bug]]): per-MEMBER voting via `resolve_set_vote`,
    # not a whole-bundle string through `resolve_vote`. `atom.a` reached 3/3 and `atom.b` reached
    # 2/3 — both cross the majority threshold and are in the resolved bundle; only `atom.c` (1/3,
    # from the minority sample) is reported as minority — a single rejected MEMBER, never an
    # alternate whole-bundle guess (the old, less precise shape this replaces).
    assert entry["_provenance"]["voteMinority"]["refs"] == ["atom.c"]
    assert all(r.get("outcome") == "persisted" for r in results.values())


def test_one_member_reaching_majority_is_too_small_a_bundle_not_unresolved():
    """Fixed 2026-09-06 ([[affix-authoring-vote-bug]]): per-member voting can resolve a REAL
    majority member (`atom.a`, 3/3 here) while every other candidate stays below threshold —
    genuinely different from nobody agreeing on anything, so it gets its own named reason rather
    than being folded into `vote_unresolved`. The schema's own `minItems: 2` makes a 1-member
    bundle invalid content regardless of how confidently that one member was chosen."""
    responses = [
        {"name": "X", "refs": ["atom.a", "atom.b"]},
        {"name": "X", "refs": ["atom.a", "atom.c"]},
        {"name": "X", "refs": ["atom.a", "atom.d"]},
    ]
    call, log = _stub_call(responses)

    fresh, unresolved, results = run_voted_draws(
        count=1, eligible=["atom.a", "atom.b", "atom.c", "atom.d"],
        atom_triggers={"atom.a": False, "atom.b": False, "atom.c": False, "atom.d": False},
        provenance_base={"pipeline": "affix-authoring", "model": "test"},
        call=call, workers=1)

    assert len(log) == 3
    assert fresh == {}, "a bundle that resolves too small must never fabricate a persisted entry"
    assert len(unresolved) == 1
    detail = next(iter(unresolved.values()))
    assert detail["reason"] == "bundle_too_small_after_vote"
    # "split", not "high" — `atom.b`/`atom.c`/`atom.d` are each real, tallied minority members
    # (1/3 apiece), so the vote as a whole did not land unanimously even though `atom.a` alone did.
    assert detail["refs"]["confidence"] == "split"
    assert detail["refs"]["resolved"] == ["atom.a"]


def test_zero_members_reaching_majority_resolves_unresolved():
    """The genuine "nobody agreed on anything" case — three samples with NO atom in common at all,
    so no member ever reaches the 2-of-3 threshold. Never silently the first sample (spec §4's own
    explicit warning) — proven through the real CLI path, not `resolve_set_vote` called directly."""
    responses = [
        {"name": "X", "refs": ["atom.a", "atom.b"]},
        {"name": "X", "refs": ["atom.c", "atom.d"]},
        {"name": "X", "refs": ["atom.e", "atom.f"]},
    ]
    call, log = _stub_call(responses)

    fresh, unresolved, results = run_voted_draws(
        count=1,
        eligible=["atom.a", "atom.b", "atom.c", "atom.d", "atom.e", "atom.f"],
        atom_triggers={a: False for a in ["atom.a", "atom.b", "atom.c", "atom.d", "atom.e", "atom.f"]},
        provenance_base={"pipeline": "affix-authoring", "model": "test"},
        call=call, workers=1)

    assert len(log) == 3
    assert fresh == {}, "a 1-1-1-style split must never fabricate a persisted entry"
    assert len(unresolved) == 1
    detail = next(iter(unresolved.values()))
    assert detail["reason"] == "vote_unresolved"
    assert detail["refs"]["confidence"] == "unresolved"
    assert detail["name"]["confidence"] == "high"  # the name DID resolve 3-0; only refs never agreed


# ---- validators -----------------------------------------------------------------------------------


def test_refs_outside_the_eligible_set_are_rejected_naming_the_offender():
    ctx = build_context(["atom.a", "atom.b"])
    defects = refs_are_known_atoms({"name": "x", "refs": ["atom.a", "atom.unknown"]}, ctx)
    assert defects and "atom.unknown" in defects[0]


def test_refs_inside_the_eligible_set_pass():
    ctx = build_context(["atom.a", "atom.b"])
    assert refs_are_known_atoms({"name": "x", "refs": ["atom.a", "atom.b"]}, ctx) == []


def test_a_single_ref_bundle_is_a_defect_here_that_is_affix_librarys_job():
    defects = bundle_has_at_least_two_refs({"name": "x", "refs": ["atom.a"]}, {})
    assert defects
    assert bundle_has_at_least_two_refs({"name": "x", "refs": ["atom.a", "atom.b"]}, {}) == []


# ---- the numeric-smuggling audit, same five cases anchor-contract already proves ---------------------


def test_no_magnitude_ever_appears_in_the_authored_schema():
    defects = numeric_audit(AFFIX_SCHEMA)
    assert defects == [], f"authored affix schema smuggles a magnitude: {defects}"


# ---- brief assembly ---------------------------------------------------------------------------------


def test_build_brief_inlines_the_eligible_atoms_literally_never_a_file_citation():
    ctx = build_context(["atom.fire", "atom.ice"], theme_hint="elemental duality")
    brief = build_brief(ctx)
    assert "atom.fire" in brief and "atom.ice" in brief
    assert "elemental duality" in brief
    assert ".json" not in brief  # cites nothing, per commander_effect.py's own established reason


def test_state_for_affix_folds_context_into_a_real_brief():
    state = state_for_affix("test-run", ["atom.fire", "atom.ice"])
    assert state["subject_id"] == "test-run"
    assert "atom.fire" in state["brief"]
    assert state["context"]["eligibleAtoms"] == ["atom.fire", "atom.ice"]


def test_entry_id_uses_the_declared_prefix():
    entry = entry_for({"name": "x", "refs": ["atom.a", "atom.b"]},
                       affix_id=f"{ID_PREFIX}test", affix_class="prefix")
    assert entry["id"].startswith(ID_PREFIX)


# ---- pipeline shape: no fork, same skeleton creature-seed's classify-pipelines already proved -----------


def test_pipeline_shape_matches_creature_seeds_classify_pipelines_exactly():
    """`effect_affix.py` must wire `build_generation_graph`, never construct its own `StateGraph`
    — the repo-wide sweep (`test_no_second_authoring_pipeline_shape_exists`, T5.0) already covers
    every file under `graphs/` including this one; this test additionally proves this specific
    module actually COMPILES into a graph object via that shared skeleton, not merely that it
    avoids the forbidden call."""
    tree = ast.parse(GRAPH_FILE.read_text(encoding="utf-8"))
    calls_state_graph = any(
        isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "StateGraph"
        for node in ast.walk(tree)
    )
    assert not calls_state_graph

    def raising_call(*_a, **_kw):
        raise AssertionError("graph construction must not call a model")

    graph = build_affix_authoring_graph(call=raising_call)
    assert graph is not None


def test_zero_bare_http_calls_outside_llm_caller():
    """Matches `llm_caller.py`'s own dependency-isolation test convention: this module reaches the
    model only through the injected `call`/`caller` param — a direct `requests`/`httpx`/`urllib`
    import here would bypass `call_with_self_heal`'s self-heal and no-silent-drop guarantees."""
    forbidden = {"requests", "httpx", "urllib"}
    for path in list(ADAPTER_DIR.glob("*.py")) + [GRAPH_FILE]:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            mods = ([a.name for a in node.names] if isinstance(node, ast.Import)
                    else [node.module or ""] if isinstance(node, ast.ImportFrom) else [])
            hit = [m for m in mods if m.split(".")[0] in forbidden]
            assert not hit, f"{path.name} imports {hit} directly — route through llm_caller instead"


# ---------------------------------------------------------------------------------------------
# Slot eligibility -- DERIVED from the real catalog, never authored (ep-9's remaining P1-table
# row). Added 2026-09-05. Correctly INERT today; these tests are what make it light up on its own.
# ---------------------------------------------------------------------------------------------

def test_element_domain_is_read_from_the_real_committed_roster():
    from seedsmith.adapters.effects.affix.generate_affixes import load_element_domain
    assert load_element_domain() == {"fire", "ice", "air", "earth", "light", "dark"}


def test_slot_eligible_families_are_derived_from_the_real_variant_axis():
    # A family is slot-shaped when the shipped catalog gives it more than one variant -- the same
    # (family, tier, variant) key the importer already derives ids from. Not a hand-listed set.
    # Updated 2026-09-06: `atom.patron-aura-defense`/`-power` (patron.aura's own pre-existing
    # content, unrelated to this task) now appear too -- each already carries all six real element
    # variants. See `test_two_families_are_now_groundable_...` immediately below for why this test
    # deliberately no longer asserts "no family is groundable."
    # ⛔ 2026-09-22: the `set(reg) == {five names}` equality that stood here was a hand-listed
    # POPULATION and it fired exactly the way this file's own milestone precedent predicts:
    # `atom.aura-bulwark`, `-composure`, `-ferocity`, `-onslaught` also ship every element variant, so
    # the derived set grew 5 -> 9 with no code change (validation-ssot: a guardrail validates the
    # CONTRACT and closed enums, never a population). What must not regress is that the five families
    # this rule was built for are still derived; what must stay true of ANY member is the derivation
    # itself, which the sibling test asserts for every member (`variants >= 2`).
    from seedsmith.adapters.effects.affix.generate_affixes import load_slot_eligible_families
    reg = load_slot_eligible_families()
    assert {"atom.fx-grid-item-cycle", "atom.fx-shield-grant",
            "atom.fx-spawn-plant-bullet", "atom.patron-aura-defense",
            "atom.patron-aura-power"} <= set(reg)
    assert reg["atom.fx-shield-grant"]["variants"] == ["a", "b", "c"]


def test_a_single_variant_family_is_not_slot_eligible():
    from seedsmith.adapters.effects.affix.generate_affixes import load_slot_eligible_families
    reg = load_slot_eligible_families()
    # one variant is not an axis to vary over
    assert all(len(r["variants"]) >= 2 for r in reg.values())


def test_two_families_are_now_groundable_the_milestone_this_tripwire_existed_to_catch():
    """⛔ **THE INERTNESS TEST HAS FIRED, 2026-09-06 — recorded, not silently patched around.**
    This test used to assert `groundable_slot_families(reg) == {}` with its own docstring saying
    verbatim: "This test is expected to GO RED the day a family ships element-id variants -- that
    is when the slot field becomes genuinely authorable and ep-9's last P1-table row can be built."
    `atom.patron-aura-defense`/`atom.patron-aura-power` (patron.aura's own pre-existing content,
    unrelated to any change in this task) now carry all SIX real element variants each
    (`air`/`dark`/`earth`/`fire`/`ice`/`light` — the complete roster, not a partial subset) —
    exactly the trigger condition this test was built to detect, so the answer this test protects
    is now the opposite of what it used to be: the slot field IS genuinely groundable today.

    **Still not built here.** A slot-domain authoring path (a schema letting the model name a
    DOMAIN rather than a concrete atom, a corresponding validator, and module 2's own runtime
    slot-resolver) is real, separate, `M`-or-larger work — this task's own prior evidence already
    named it exactly that ("not attempted this pass... not a closing touch on this task") when the
    precondition did not exist at all; it existing now does not shrink the scope of building it.
    Recorded here so the milestone is not lost, not built under this same pass's time budget.
    """
    from seedsmith.adapters.effects.affix.generate_affixes import (
        groundable_slot_families, load_slot_eligible_families)
    reg = load_slot_eligible_families()
    groundable = groundable_slot_families(reg)
    assert set(groundable) == {"atom.patron-aura-defense", "atom.patron-aura-power"}
    ELEMENTS = {"air", "dark", "earth", "fire", "ice", "light"}
    for family, info in groundable.items():
        assert info["domain"] == "element"
        assert set(info["variants"]) == ELEMENTS, f"{family} does not cover the full element roster"


def test_a_family_varying_over_real_element_ids_would_be_groundable():
    """The positive twin of the inertness test -- proves the mechanism actually fires rather than
    being vacuously empty, using a planted family whose variants ARE real element ids."""
    from seedsmith.adapters.effects.affix.generate_affixes import groundable_slot_families
    planted = {"atom.elemental-power": {"variants": ["fire", "ice"], "domain": "element"},
               "atom.fx-shield-grant": {"variants": ["a", "b"], "domain": None}}
    assert set(groundable_slot_families(planted)) == {"atom.elemental-power"}
