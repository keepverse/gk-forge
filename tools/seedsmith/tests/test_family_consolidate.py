"""Tests for seedsmith.adapters.creatures.family.consolidate (spec-family-consolidate.md, wave D2)."""
from __future__ import annotations

import pytest

from seedsmith.adapters.creatures.family.consolidate import (
    FamilyCandidateInput,
    canonical_key,
    consolidate,
    head_noun,
    load_synonyms,
    normalize,
)


def C(species_id: str, label: str, native_label: str, basis: str = "text") -> FamilyCandidateInput:
    return FamilyCandidateInput(species_id=species_id, label=label, native_label=native_label, basis=basis)


# ---- Normalization / head-noun --------------------------------------------------------------


def test_normalize_lowercases_strips_punctuation_and_kebabs():
    assert normalize("Wall-Nut!") == "wall-nut"
    assert normalize("  Nut Type  ") == "nut-type"


def test_head_noun_reduces_wall_nut_defensive_nut_and_nut_type_to_nut():
    assert head_noun(normalize("wall-nut")) == "nut"
    assert head_noun(normalize("defensive-nut")) == "nut"
    assert head_noun(normalize("nut-type")) == "nut"


def test_head_noun_of_a_single_token_is_itself():
    assert head_noun("shell") == "shell"


# ---- Deterministic merge ----------------------------------------------------------------------


def test_same_candidates_consolidated_twice_are_byte_identical():
    candidates = [
        C("wall-nut-zombie", "wall-nut", "Wall-Nut Zombie"),
        C("tall-nut-zombie", "defensive-nut", "Tall-Nut Zombie"),
        C("armor-zombie", "nut-type", "Armor Zombie"),
    ]
    a = consolidate(candidates)
    b = consolidate(list(reversed(candidates)))  # input order must not matter — sorted internally
    assert a.families == b.families
    assert a.assignments == b.assignments


def test_wall_nut_defensive_nut_and_nut_type_merge_into_one_family_headed_nut():
    candidates = [
        C("a", "wall-nut", "A"), C("b", "defensive-nut", "B"), C("c", "nut-type", "C"),
    ]
    result = consolidate(candidates)
    assert len(result.families) == 1
    family_id = next(iter(result.families))
    assert result.families[family_id]["canonicalKey"] == "nut"
    assert result.assignments == {"a": [family_id], "b": [family_id], "c": [family_id]}


# ---- Synonym map: load-bearing, not decorative -----------------------------------------------


def test_shell_and_armor_plated_merge_via_the_synonym_map():
    synonyms = load_synonyms()
    candidates = [C("a", "shell", "A"), C("b", "armor-plated", "B")]
    result = consolidate(candidates, synonyms=synonyms)
    assert len(result.families) == 1


def test_shell_and_armor_plated_do_not_merge_with_an_empty_synonym_map():
    """The contrast that proves the map is load-bearing rather than decorative (§6's own row)."""
    candidates = [C("a", "shell", "A"), C("b", "armor-plated", "B")]
    result = consolidate(candidates, synonyms={})
    assert len(result.families) == 2, "shell and armor-plated share no head token — only the synonym map merges them"


# ---- nativeLabel never merges ------------------------------------------------------------------


def test_two_candidates_differing_only_in_native_label_still_merge():
    candidates = [C("a", "nut", "黄金坚果"), C("b", "nut", "钻石坚果")]
    result = consolidate(candidates)
    assert len(result.families) == 1
    family_id = next(iter(result.families))
    assert set(result.families[family_id]["nativeLabels"]) == {"黄金坚果", "钻石坚果"}


# ---- Multi-membership and zero-membership ------------------------------------------------------


def test_blocked_creature_contributes_no_candidate_and_gets_zero_families():
    # A `blocked` creature (basis="blocked" in family-extract) never becomes a FamilyCandidateInput
    # at all — it simply has no row here. Confirmed by omission rather than a special value.
    result = consolidate([C("a", "nut", "A")])
    assert "blocked-creature" not in result.assignments


def test_a_creature_with_candidates_from_two_heads_gets_both_families():
    candidates = [C("a", "wall-nut", "A"), C("a", "shell", "A")]
    result = consolidate(candidates, synonyms={})
    assert len(result.assignments["a"]) == 2


# ---- Append-only: never renamed, never re-positioned -------------------------------------------


def test_a_family_id_present_in_the_registry_is_never_renamed_or_repositioned():
    first = consolidate([C("a", "wall-nut", "A"), C("b", "shell", "B")], synonyms={})
    nut_id = next(fid for fid, rec in first.families.items() if rec["canonicalKey"] == "nut")
    shell_id = next(fid for fid, rec in first.families.items() if rec["canonicalKey"] == "shell")
    first_order = list(first.families.keys())

    second = consolidate(
        [C("a", "wall-nut", "A"), C("b", "shell", "B"), C("c", "tall-nut", "C")],
        synonyms={}, existing_registry=first.families,
    )
    assert list(second.families.keys())[:2] == first_order, "existing ids keep their position"
    assert second.families[nut_id]["canonicalKey"] == "nut"
    assert second.families[shell_id]["canonicalKey"] == "shell"


def test_adding_a_new_creature_and_rereading_leaves_existing_ids_unchanged_new_appended_at_end():
    first = consolidate([C("a", "wall-nut", "A")], synonyms={})
    second = consolidate(
        [C("a", "wall-nut", "A"), C("z", "shell", "Z")],
        synonyms={}, existing_registry=first.families,
    )
    ids = list(second.families.keys())
    assert ids[0] == list(first.families.keys())[0]
    assert len(ids) == 2
    assert second.families[ids[1]]["canonicalKey"] == "shell"


def test_an_existing_family_with_no_candidate_this_run_is_still_carried_forward_never_deleted():
    first = consolidate([C("a", "wall-nut", "A")], synonyms={})
    # Re-run with a totally disjoint candidate set — append-only means the old family persists.
    second = consolidate([C("z", "shell", "Z")], synonyms={}, existing_registry=first.families)
    assert set(first.families.keys()) <= set(second.families.keys())


# ---- Real defect, real model, 2026-08-31: generic relational suffixes beyond "family" -----------


def test_generic_relational_suffixes_do_not_become_the_family_head():
    """The exact labels `google/gemma-4-26b-a4b-qat` produced unprompted on the first real
    84-creature extraction run. Each pair below is semantically ONE family; before the fix, the
    suffix (not the theme word) became the head, so `ice-attackers`/`ice-family` split into two
    separate families instead of merging into one."""
    candidates = [
        C("a", "ice-attackers", "A"), C("b", "ice-family", "B"),
        C("c", "bucket-users", "C"),
        C("d", "sun-producers", "D"),
    ]
    result = consolidate(candidates, synonyms={})
    heads = {rec["canonicalKey"] for rec in result.families.values()}
    assert "attackers" not in heads and "users" not in heads and "producers" not in heads
    assert result.assignments["a"] == result.assignments["b"], "ice-attackers and ice-family must merge"


def test_generic_relational_suffixes_do_not_falsely_merge_different_themes():
    """The more dangerous direction, also from the real run: `fire-based`/`light-based` and
    `chomper-kin`/`nut-kin`/`pea-kin` are semantically DIFFERENT families that the unfixed suffix
    rule collapsed into one false "based" and one false "kin" family — a silent, wrong merge,
    exactly what audit A6 named this module to prevent."""
    candidates = [
        C("a", "fire-based", "A"), C("b", "light-based", "B"),
        C("c", "chomper-kin", "C"), C("d", "nut-kin", "D"), C("e", "pea-kin", "E"),
    ]
    result = consolidate(candidates, synonyms={})
    assert result.assignments["a"] != result.assignments["b"], "fire and light are not one family"
    assert len({result.assignments[s][0] for s in ("c", "d", "e")}) == 3, \
        "chomper, nut and pea are three distinct families, not one 'kin' bucket"


# ---- Cannot invent (§2.5) -----------------------------------------------------------------------


def test_consolidation_produces_only_families_traceable_to_a_real_candidate():
    candidates = [C("a", "wall-nut", "A"), C("b", "shell", "B")]
    result = consolidate(candidates, synonyms={})
    derivable = {canonical_key(c.label, {}) for c in candidates}
    assert set(rec["canonicalKey"] for rec in result.families.values()) == derivable
    assert len(result.families) == len(derivable), "no extra, un-derivable family may appear"


def test_no_candidates_at_all_produces_no_families():
    result = consolidate([], synonyms={})
    assert result.families == {}
    assert result.assignments == {}


# ---- Inlinable, no citation-shaped text ---------------------------------------------------------


def test_family_ids_and_native_labels_are_plain_inlinable_strings():
    from seedsmith.briefkit.render import CITATION_PATTERNS

    result = consolidate([C("a", "wall-nut", "Wall-Nut Zombie")], synonyms={})
    for family_id, rec in result.families.items():
        for pattern in CITATION_PATTERNS:
            assert pattern.search(family_id) is None
            for native in rec["nativeLabels"]:
                assert pattern.search(native) is None


# ---- The missing entrypoint (added 2026-09-01) ---------------------------------------------------


def test_the_family_pipeline_has_a_committed_entrypoint():
    """⛔ Until 2026-09-01 it did not. `extract.py` and `consolidate.py` were library modules whose
    only callers were tests, so `family-candidates.json`, `families.v1.json` and
    `family-assignments.json` were committed artifacts **nothing in the repo could reproduce** — the
    2026-08-31 run used scratch scripts that live nowhere.

    Third instance of one defect: G1.3 recorded it for motifs, G4.3 fixed it for commander effects."""
    from seedsmith.adapters.creatures import generate_families

    assert callable(generate_families.run)


def test_families_is_reachable_from_the_documented_cli():
    from seedsmith.report.cli import build_parser

    args = build_parser().parse_args(["creatures", "families", "--dry-run"])
    assert args.creature_command == "families" and args.dry_run is True


def test_writing_is_refused_while_downstream_content_is_bound():
    """⛔ G1.3's own note: regeneration was safe *"only because nothing is bound to them ... **This
    window closes when G4 writes its first row.**"* G4 has since written 84 commander effects, so
    re-deriving families can move an id and silently invalidate three layers of committed,
    append-only content. The entrypoint must refuse by default, and say what is at stake."""
    from seedsmith.adapters.creatures.generate_families import bound_artifacts, run

    bound = bound_artifacts()
    assert bound, "no downstream artifacts found — the fixture moved; re-measure before trusting this"
    assert run(["--write"]) == 2, "a --write with the window closed must refuse, not proceed"


def test_the_refusal_names_every_bound_artifact_and_the_recovery_path(capsys):
    """A refusal that does not say what to do next just gets worked around."""
    from seedsmith.adapters.creatures.generate_families import run

    run(["--write"])
    out = capsys.readouterr().out
    for rel in ("motif-assignments.json", "themes.v1.json", "commander-effect/all.json"):
        assert rel in out, f"the refusal does not name {rel}"
    assert "--i-have-read-the-append-only-note" in out
    assert "--stale" in out, "the refusal must name the regeneration chain, not just say no"


def test_dry_run_makes_no_model_calls_and_still_reports_the_batching():
    import socket

    from seedsmith.adapters.creatures.generate_families import run

    real = socket.socket.connect

    def refuse(self, addr):  # noqa: ANN001
        raise AssertionError(f"--dry-run attempted a connection to {addr}")

    socket.socket.connect = refuse
    try:
        assert run(["--dry-run"]) == 0
    finally:
        socket.socket.connect = real


def test_writing_persists_all_three_family_artifacts_or_none():
    """`motif-derive` reads `family-assignments.json` AND `family-candidates.json`, and
    `families.v1.json` is the registry both are described by. Persisting only the candidates would
    leave the other two describing a different run — the same cross-artifact staleness
    `themes.v1.json` already taught this program once."""
    import inspect

    from seedsmith.adapters.creatures import generate_families

    src = inspect.getsource(generate_families.run)
    body = src.split("if args.write:")[1]
    for name in ("family-candidates.json", "families.v1.json", "family-assignments.json"):
        assert name in body, f"--write does not persist {name}"
