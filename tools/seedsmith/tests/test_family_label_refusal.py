"""The refusal contract of the LIVE family-label pipeline, and the guard that there is only one of it.

**Which implementation decides.** `creatures/family/fallback.py` decides. The criterion used to
establish it, and the one this file pins, is **whether a module's return value can change which family
ids reach a committed artifact**: `resolve_unresolved_family` is reached from
`characteristic_pool/catalog.derive_live_family_assignments`, which three model-free generators call
(`generate_characteristic_pool`, `generate_coverage_report`, `generate_distribution_planner`), so its
verdict lands in `role-lean.json`, `family-map.json` and `_briefs/round-1.json`. The sibling
`consolidate.merge_corroborated` is NOT a second decider — it places every candidate somewhere and
delegates dropping to `fallback.py` by name — and `creatures/anchor/schema.py`'s two predicates are
deliberately per-CONSUMER, documented in that file's own "Consumer 1 / Consumer 2" sections.

**Why this file exists rather than the one it replaces.** `family/label_rules.py` shipped 33 tests
against a five-class taxonomy that no code consulted: commit `aedc3a4` added that module and its test
and touched nothing else, so it was never wired, and its docstring's claim that
`derive_live_family_assignments` "consults" `classify_vocabulary` was false from birth. The tests that
guarded that taxonomy are gone with it. The tests that guarded INVARIANTS OF THE SHIPPED PIPELINE
were not dead — they were true, and merely expressed against the wrong module — so they are restated
here against `fallback` and `catalog`.

**Two of them had to change meaning, and deliberately.**
`test_a_species_with_no_family_field_at_all_resolves_instead_of_raising` asserted that an empty family
set RESOLVES; the shipped loader RAISES (`catalog.py`'s `has no family`, kept on purpose because that
raise is what made 338 family-less species visible). Its replacement asserts the raise, which also
fills a real hole: **no test anywhere in the tree guarded that raise** — the brief named
`test_a_species_with_no_family_has_no_family` in `tests/test_actions_description_completeness.py`
(that file was deleted 2026-10-05 with the retired actions `description_backfill` generator; it never
contained that test either way), and that test does not exist in any file. `test_a_name_echo_that_groups_several_species_is_legitimate`
asserted that `squash` is never refused for being a name echo; the owner has since ruled the
opposite — a label may not be the whole of a species' name even when it groups other species — and
that clause is tested in this file too.

Per `docs/architecture/validation-ssot.md` §1 nothing here pins a count: the corpus grows whenever a
species ships, so every assertion is an invariant or a join against the live derivation.
"""
from __future__ import annotations

import importlib
import json
import pkgutil
from pathlib import Path

import pytest

from seedsmith.adapters.actions.characteristic_pool.catalog import (
    CATALOG_PATH,
    _committed_name_tokens,
    _key_owners,
    derive_live_family_assignments,
    load_curated_family_terms,
    load_live_records,
)
from seedsmith.adapters.creatures import family as family_pkg
from seedsmith.adapters.creatures.family.consolidate import (
    FamilyCandidateInput,
    consolidate,
)
from seedsmith.adapters.creatures.family.fallback import (
    family_label_is_artefact,
    label_is_species_own_name,
    resolve_unresolved_family,
)
from seedsmith.ladders import normalize_family_key

#: The modules this package is allowed to contain. A closed vocabulary the code owns, pinned because
#: the defect this file exists to prevent is a SECOND module answering "may this species keep this
#: label?" — a second predicate reads as authoritative to the next reader (the deleted one claimed in
#: its own docstring to be wired) and nothing in the tree would object. Adding a module here is
#: therefore a deliberate act: if it decides refusals, the invariant in this file is violated and the
#: live decider has to be moved rather than added to.
EXPECTED_FAMILY_MODULES = frozenset({"consolidate", "extract", "fallback", "schema"})


# =================================================================================================
# The kept raise — `catalog.derive_live_family_assignments`
# =================================================================================================


def _write_species(root: Path, species_id: str, family: object) -> None:
    """One species record in the shape `load_live_records` reads: a JSON list of entries."""
    root.mkdir(parents=True, exist_ok=True)
    entry: dict[str, object] = {"speciesId": species_id}
    if family is not _ABSENT:
        entry["family"] = family
    (root / f"{species_id}.json").write_text(
        json.dumps([entry]), encoding="utf-8", newline="\n")


class _Absent:
    """Distinguishes "no `family` key at all" from "`family` present but empty"."""

    def __repr__(self) -> str:  # pragma: no cover - only ever a failure message
        return "<absent>"


_ABSENT = _Absent()


@pytest.mark.parametrize("family", [_ABSENT, [], "", ["", "   "]], ids=[
    "key-absent", "empty-list", "empty-string", "whitespace-only"])
def test_a_species_with_no_usable_family_label_still_refuses_to_load(tmp_path, family):
    """⛔ The `has no family` raise is KEPT, and this is the test that pins it.

    It is the contract which made 338 family-less species visible in the first place. Relaxing it is
    not a cleanup: a silent default would hide the next one. Every `family` shape that yields no
    usable label must therefore raise rather than resolve — including the `family` key being absent
    entirely, which is the case a loader is most tempted to default.
    """
    root = tmp_path / "species"
    _write_species(root, "FamylessThing", family)
    with pytest.raises(ValueError, match="has no family"):
        derive_live_family_assignments(root)


def test_the_raise_names_the_species_and_the_file_it_came_from(tmp_path):
    """A refusal that cannot be acted on is a different defect. Both the offending species and the
    path that carried it must be in the message, or a 900-species load failure is unactionable."""
    root = tmp_path / "species"
    _write_species(root, "FamylessThing", [])
    with pytest.raises(ValueError) as caught:
        derive_live_family_assignments(root)
    message = str(caught.value)
    assert "famylessthing" in message.lower(), message
    assert "famylessthing.json" in message.lower(), message


def test_a_bare_string_family_label_is_accepted_not_refused(tmp_path):
    """`catalog` wraps a bare string rather than refusing it (an early draft of this file listed a
    bare string among the refusal cases and was wrong). The refusal is about there being no label at
    all, never about how one is spelled."""
    root = tmp_path / "species"
    _write_species(root, "Wallnut", "defensive nut")
    assert derive_live_family_assignments(root) == {"wallnut": ["nut"]}


def test_a_species_with_one_usable_family_label_loads(tmp_path):
    """The guard on the guard: the raise must not fire on a species that HAS a label, or the
    raise test above would pass for the wrong reason."""
    root = tmp_path / "species"
    _write_species(root, "Wallnut", ["defensive nut"])
    assert derive_live_family_assignments(root) == {"wallnut": ["nut"]}


# =================================================================================================
# One decider
# =================================================================================================


def test_the_family_package_contains_no_second_predicate_module():
    """⛔ THE INVARIANT: exactly one module in this package may decide a label's refusal.

    Established by measurement, not by taste: `label_rules.py` (483 lines, 33 tests) was dead from
    the commit that added it, and the live decider is `fallback.py`. See this file's docstring for the
    criterion and the call sites. This is the guard that keeps the count at one.
    """
    found = {info.name for info in pkgutil.iter_modules(family_pkg.__path__)}
    assert found == set(EXPECTED_FAMILY_MODULES), (
        f"creatures/family now holds {sorted(found)}; expected "
        f"{sorted(EXPECTED_FAMILY_MODULES)}. A new module here may be a second refusal predicate — "
        f"if it is, fold it into fallback.py rather than adding it beside."
    )


def test_the_live_decider_takes_the_corroboration_mapping_and_is_the_only_one_that_does():
    """`key_owners` is what makes the shipped structural test possible at all — "does this key bucket
    more than one thing?" is a corpus-wide reading, so it cannot be decided from one label alone. A
    second refusal predicate that did not take it could not answer the corpus question, and a second
    one that DID would be a second decider by construction."""
    import inspect

    takers: "dict[str, list[str]]" = {}
    for info in pkgutil.iter_modules(family_pkg.__path__):
        module = importlib.import_module(f"{family_pkg.__name__}.{info.name}")
        for name, obj in vars(module).items():
            if name.startswith("_") or not callable(obj):
                continue
            if getattr(obj, "__module__", None) != module.__name__:
                continue
            try:
                signature = inspect.signature(obj)
            except (TypeError, ValueError):  # pragma: no cover - builtins only
                continue
            if "key_owners" in signature.parameters:
                takers.setdefault(info.name, []).append(name)
    assert takers == {"fallback": ["family_label_is_artefact", "resolve_unresolved_family"]}


def test_the_fallback_module_is_the_one_catalog_delegates_to():
    """`catalog.derive_live_family_assignments` must route its refusal through `fallback`, importing
    it lazily inside the function. Asserted on the source text because the import is deliberate: a
    module-level import would make the decision a package invariant rather than a local one."""
    source = (
        Path(derive_live_family_assignments.__code__.co_filename).read_text(encoding="utf-8"))
    assert "from ...creatures.family.fallback import resolve_unresolved_family" in source


# =================================================================================================
# Over the committed corpus — the invariants the deleted module's tests actually guarded
# =================================================================================================


@pytest.fixture(scope="module")
def live_assignments() -> "dict[str, list[str]]":
    return derive_live_family_assignments(CATALOG_PATH)


@pytest.fixture(scope="module")
def live_records() -> "list[dict]":
    return load_live_records(CATALOG_PATH)


def test_no_species_resolves_to_an_empty_family_set(live_assignments):
    """The invariant `catalog` turns into a hard load failure, asserted where it is decided rather
    than only at the loader — a fallback that emptied a set would still leave this green."""
    empty = sorted(sid for sid, families in live_assignments.items() if not families)
    assert empty == [], f"species with no family at all: {empty}"


def test_every_species_in_the_corpus_is_still_assigned(live_assignments, live_records):
    """No species may be dropped by the derivation: the roster is the corpus, not a sample."""
    assert set(live_assignments) == {str(r["speciesId"]) for r in live_records}


def test_every_derived_id_is_a_legal_action_namespace_key(live_assignments):
    """A family id IS the action namespace key, so it must survive the consumer's own
    `normalize_family_key` unchanged rather than be normalised a second time here."""
    for species_id, families in live_assignments.items():
        for family in families:
            assert normalize_family_key(family) == family, f"{species_id}: {family!r}"


def test_the_derivation_is_deterministic_over_the_corpus(live_assignments):
    """`consolidate` is order-sensitive by construction (head-noun merging depends on the candidate
    set), so the whole derivation is re-run rather than re-sorted."""
    second = derive_live_family_assignments(CATALOG_PATH)
    assert second == live_assignments


def test_the_shipped_output_is_consolidate_then_fallback_and_nothing_in_between(live_assignments):
    """⛔ THE ONE-DECIDER CONTRACT, asserted behaviourally rather than by reading the module.

    `catalog.derive_live_family_assignments` must be exactly `consolidate` followed by
    `resolve_unresolved_family`, species for species. If `catalog` ever grew a refusal rule of its
    own — dropping a label, substituting a default, re-deriving a key — this stops matching, because
    `fallback` is the only thing that could have produced the difference. This is the assertion that
    `label_rules.py` would have failed if it had been consulted, and the reason the module-set guard
    above is a backstop rather than the primary defence.

    The consolidated input is rebuilt here rather than imported, so the test also pins the order and
    the candidate shape `catalog` feeds it.
    """
    records = load_live_records(CATALOG_PATH)
    curated = load_curated_family_terms()
    candidates = []
    for record in records:
        raw = record.get("family", [])
        if isinstance(raw, str):
            raw = [raw]
        for label in sorted({str(v).strip() for v in raw if str(v).strip()}):
            candidates.append(FamilyCandidateInput(
                species_id=str(record["speciesId"]), label=label,
                native_label=label, basis="text",
            ))
    consolidated = consolidate(candidates, established_terms=curated).assignments
    name_tokens = _committed_name_tokens(records)
    owners = _key_owners(consolidated)

    assert set(consolidated) == set(live_assignments), (
        "the consolidated roster and the shipped roster disagree about which species exist")

    for species_id, families in sorted(consolidated.items()):
        resolved, _was_deterministic = resolve_unresolved_family(
            families, species_id=species_id,
            name_tokens=name_tokens.get(species_id, ()),
            curated_terms=curated, key_owners=owners,
        )
        assert live_assignments[species_id] == sorted(set(resolved)), (
            f"{species_id}: shipped {live_assignments[species_id]} is not "
            f"resolve_unresolved_family({families}) = {sorted(set(resolved))}"
        )


def test_the_deterministic_fallback_only_uses_committed_vocabulary(live_assignments, live_records):
    """A fallback id is a family the corpus already groups by, so the repair adds no new key to the
    action namespace. `was_deterministic` is what the caller records as honest provenance, and a
    fallback that says it fired must have produced a vocabulary-legal key."""
    owners: "dict[str, set[str]]" = {}
    for species_id, families in live_assignments.items():
        for family in families:
            owners.setdefault(family, set()).add(species_id)
    name_tokens = {
        str(r["speciesId"]): tuple(r.get("_rawSpeciesId", r["speciesId"]).split())
        for r in live_records
    }
    for species_id, families in live_assignments.items():
        resolved, was_deterministic = resolve_unresolved_family(
            families, species_id=species_id, name_tokens=name_tokens.get(species_id, ()),
            curated_terms=(), key_owners=owners,
        )
        if not was_deterministic:
            continue
        for family in resolved:
            assert family in owners, f"{species_id}: fallback invented {family!r}"


# =================================================================================================
# The owner's clause — a label may not be the whole of a species' name, even when it groups others
# =================================================================================================
#
# Measured on the committed corpus by A/B in one process (clause disabled vs live): it fires on 6
# species and changes all 6, taking the namespace from 612 ids to 608. `squash` and `cactus` are the
# two that group OTHER species (7 and 8 members, 6 and 7 after) — they are the case the ruling is
# about, because the grouping test already passed them. None of the 6 is emptied, none is lost, and
# the deterministic-fallback surface is unchanged at 25, so no species gained a faked provenance.
# That count is a READING and is deliberately not pinned here (validation-ssot §1): the corpus grows.


def test_the_clause_reads_the_name_as_a_token_multiset_not_a_string():
    """`family_id` is kebab and `name_tokens` is CamelCase-split, so the two are written in
    different conventions by construction. A string comparison would refuse only the labels that
    happen to share the name's word order and silently pass the rest — a detector that looks present
    and is not, which is the same trap `identity_echo_of` fell into with a lower-cased id."""
    # same words, written the way a family label is written
    assert label_is_species_own_name("ice-bean", name_tokens=("ice", "bean"))
    assert label_is_species_own_name("firecracker", name_tokens=("firecracker",))
    # same words, ORDER SWAPPED — word order is not load-bearing in a two-noun compound, and the
    # corpus writes both `LanternPumpkin` and `PumpkinLantern`
    assert label_is_species_own_name("pumpkin-lantern", name_tokens=("lantern", "pumpkin"))
    # case is normalised, so a caller's un-lowercased tokens still answer correctly
    assert label_is_species_own_name("ice-bean", name_tokens=("Ice", "Bean"))


def test_a_fragment_of_the_name_is_not_the_whole_of_it():
    """`CactusBlover` carrying `cactus` is a different question — is that word a grouping for this
    creature? — and the grouping test answers it. Catching it here would refuse the seven-species
    `cactus` family on every one of its members."""
    assert not label_is_species_own_name("cactus", name_tokens=("cactus", "blover"))
    assert not label_is_species_own_name("corn", name_tokens=("ice", "corn"))


def test_no_name_signal_answers_no_rather_than_guessing():
    """A species with no name signal is a missing-data defect. Refusing labels on its behalf would be
    a guess, and the honest branch for that is `resolve_unresolved_family`'s own no-derivation exit."""
    assert not label_is_species_own_name("nut", name_tokens=())
    assert not label_is_species_own_name("nut", name_tokens=("",))


def test_the_clause_refuses_a_name_even_when_the_label_groups_other_species():
    """⛔ The ruling itself. `squash` groups six other species and is also the exact name of one, and
    grouping does not make a label something other than the creature's own name. This is the case the
    structural test cannot see: `squash` passes `family_label_is_artefact` outright, because six other
    species corroborate it."""
    owners = {"squash": {"squash"} | {f"squash{i}" for i in range(6)}}
    assert not family_label_is_artefact("squash", key_owners=owners, species_id="squash")
    assert resolve_unresolved_family(
        ["squash", "ambusher", "crusher"], species_id="squash",
        name_tokens=("squash",), curated_terms=(), key_owners=owners,
    ) == (["ambusher", "crusher"], False)


def test_the_clause_drops_only_the_offending_label_and_keeps_the_rest():
    """It is a per-LABEL refusal, not a whole-species verdict. `resolve_unresolved_family` consults
    `family_label_is_artefact` only when EVERY label is an artefact, so a fourth clause inside that
    predicate would be unreachable for any species holding a real grouping — which is all six of the
    corpus instances. Asserted here so the filter shape cannot quietly become an all-artefact clause."""
    owners = {"ambusher": {"a", "b"}, "squash": {"squash", "c"}}
    families, was_deterministic = resolve_unresolved_family(
        ["squash", "ambusher"], species_id="squash", name_tokens=("squash",),
        curated_terms=(), key_owners=owners,
    )
    assert families == ["ambusher"]
    assert was_deterministic is False, "dropping one label is not a deterministic repair"


def test_the_clause_never_empties_a_species():
    """A species whose ONLY label is its own name keeps it. Emptying would hand the loader a
    family-less species, which is the `has no family` load failure — so the filter backs off rather
    than trading an ugly label for a broken corpus."""
    assert resolve_unresolved_family(
        ["squash"], species_id="squash", name_tokens=("squash",),
        curated_terms=(), key_owners={"squash": {"squash", "c"}},
    ) == (["squash"], False)
    # and the same holds when the species would otherwise have taken the fallback
    assert resolve_unresolved_family(
        ["aloe"], species_id="aloe", name_tokens=("aloe",),
        curated_terms=(), key_owners={"aloe": {"aloe"}},
    ) == (["aloe"], False)


def test_the_fallback_may_not_re_select_the_label_the_clause_just_refused():
    """The hole the clause would otherwise fall into one line later. `Squash` holding
    `['squash', <artefact>]` still reaches the selection loops, and `squash` is its own most
    corroborated name word — so without the exclusion the derivation hands back the very label that
    was just refused and the clause is a no-op for that species."""
    owners = {"present": {"other"}, "squash": {"squash"} | {f"squash{i}" for i in range(6)}}
    families, _ = resolve_unresolved_family(
        ["squash", "present"], species_id="squash", name_tokens=("squash",),
        curated_terms=("nut",), key_owners=owners,
    )
    assert "squash" not in families, f"the clause was undone by the derivation: {families}"


def test_no_species_keeps_a_label_that_is_its_own_name(live_assignments, live_records):
    """The corpus-wide form, as an invariant and not a count: whatever the corpus holds, no species
    may come out of the derivation carrying a label that is its own name. Paired with the synthetic
    cases above, which prove the predicate fires at all."""
    name_tokens = _committed_name_tokens(live_records)
    kept = sorted(
        f"{species_id}:{family}"
        for species_id, families in live_assignments.items()
        for family in families
        if label_is_species_own_name(family, name_tokens=name_tokens.get(species_id, ()))
    )
    assert kept == [], f"species kept a label that is its own name: {kept}"


def test_the_clause_leaves_the_multi_member_families_themselves_intact(live_assignments):
    """The clause refuses the LABEL on the species that is named after it. It does not dissolve the
    family: `squash` and `cactus` are still real groupings for the six and seven species that are not
    named after them, which is the whole reason refusing the label is cheaper than fixing the list."""
    owners: "dict[str, set[str]]" = {}
    for species_id, families in live_assignments.items():
        for family in families:
            owners.setdefault(family, set()).add(species_id)
    for family in ("squash", "cactus"):
        assert len(owners.get(family, ())) > 1, (
            f"{family} was dissolved by the clause; it should survive for the species that are not "
            f"named after it")