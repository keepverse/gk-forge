"""Tests for seedsmith.pipeline.dependency_validator — item-seedgen's generator-harness (module 1),
the hard/categorical/external reference resolution and backfill acceptance criteria from
docs/architecture/item-seedgen/spec-generator-harness.md.
"""
from __future__ import annotations

from seedsmith.pipeline.dependency_validator import (
    BackfillRequest,
    CATEGORICAL,
    EXTERNAL,
    HARD,
    ReferenceManifestEntry,
    plan_backfill,
    run_backfill_loop,
    validate,
)


def test_hard_reference_resolves_against_a_real_id() -> None:
    entries = {"recipe.001": {"outputRef": "item.humanoid-torso-a-001"}}
    manifest = [ReferenceManifestEntry("outputRef", HARD, "base-types-gen")]
    real_ids = {"item.humanoid-torso-a-001"}

    report = validate(
        entries, manifest,
        resolve_hard=lambda module, value: value in real_ids,
        resolve_categorical=lambda module, value: 0,
    )
    assert len(report.results) == 1
    assert report.results[0].resolved is True
    assert report.unresolved == []


def test_hard_reference_to_a_fabricated_id_is_reported_unresolved() -> None:
    entries = {"recipe.001": {"outputRef": "item.does-not-exist"}}
    manifest = [ReferenceManifestEntry("outputRef", HARD, "base-types-gen")]

    report = validate(
        entries, manifest,
        resolve_hard=lambda module, value: False,
        resolve_categorical=lambda module, value: 0,
    )
    unresolved = report.unresolved
    assert len(unresolved) == 1
    assert unresolved[0].value == "item.does-not-exist"


def test_categorical_reference_reports_a_real_match_count_not_just_a_boolean() -> None:
    entries = {"set.001": {"members": [{"role": "weapon", "frame": "plant"}]}}
    manifest = [ReferenceManifestEntry("members[].role", CATEGORICAL, "base-types-gen")]

    report = validate(
        entries, manifest,
        resolve_hard=lambda module, value: False,
        resolve_categorical=lambda module, value: 3,
    )
    assert report.results[0].resolved is True
    assert report.results[0].match_count == 3


def test_categorical_reference_with_zero_matches_is_unresolved() -> None:
    entries = {"set.001": {"members": [{"role": "weapon", "frame": "plant"}]}}
    manifest = [ReferenceManifestEntry("members[].role", CATEGORICAL, "base-types-gen")]

    report = validate(
        entries, manifest,
        resolve_hard=lambda module, value: False,
        resolve_categorical=lambda module, value: 0,
    )
    assert report.unresolved[0].match_count == 0
    assert report.unresolved[0].resolved is False


def test_external_reference_resolves_like_hard_but_is_flagged_distinctly() -> None:
    entries = {"consumable.k1-001": {"family": "atom.vitality"}}
    manifest = [ReferenceManifestEntry("family", EXTERNAL, "atom-family-library")]

    report = validate(
        entries, manifest,
        resolve_hard=lambda module, value: value == "atom.vitality",
        resolve_categorical=lambda module, value: 0,
    )
    assert report.results[0].resolved is True
    assert report.results[0].manifest.kind == EXTERNAL


def test_determinism_two_validate_calls_produce_byte_identical_json() -> None:
    entries = {"b": {"outputRef": "x"}, "a": {"outputRef": "y"}}
    manifest = [ReferenceManifestEntry("outputRef", HARD, "base-types-gen")]

    report1 = validate(entries, manifest, lambda m, v: True, lambda m, v: 0)
    report2 = validate(entries, manifest, lambda m, v: True, lambda m, v: 0)
    assert report1.to_json() == report2.to_json()


def test_backfill_names_the_exact_missing_id_for_a_hard_reference() -> None:
    entries = {"recipe.001": {"outputRef": "item.missing-050"}}
    manifest = [ReferenceManifestEntry("outputRef", HARD, "base-types-gen")]
    report = validate(entries, manifest, lambda m, v: False, lambda m, v: 0)

    requests = plan_backfill(report)
    assert requests == [BackfillRequest("base-types-gen", HARD, "item.missing-050")]


def test_backfill_never_targets_an_external_reference() -> None:
    entries = {"consumable.k1-001": {"family": "atom.does-not-exist"}}
    manifest = [ReferenceManifestEntry("family", EXTERNAL, "atom-family-library")]
    report = validate(entries, manifest, lambda m, v: False, lambda m, v: 0)

    assert plan_backfill(report) == []


def test_backfill_dedupes_two_entries_naming_the_identical_missing_selector() -> None:
    entries = {
        "set.001": {"members": [{"role": "weapon", "frame": "plant"}]},
        "set.002": {"members": [{"role": "weapon", "frame": "plant"}]},
    }
    manifest = [ReferenceManifestEntry("members[].role", CATEGORICAL, "base-types-gen")]
    report = validate(entries, manifest, lambda m, v: False, lambda m, v: 0)

    requests = plan_backfill(report)
    assert len(requests) == 1


def test_cascade_guard_validates_a_freshly_backfilled_entrys_own_reference() -> None:
    """The gap found on adversarial review: a backfilled base-type can itself carry an unresolved
    affix-family reference. The loop must catch that, not declare victory after one round."""
    entries = {"recipe.001": {"outputRef": "item.missing-050"}}
    manifest = [
        ReferenceManifestEntry("outputRef", HARD, "base-types-gen"),
        ReferenceManifestEntry("implicitFamily", HARD, "affix-families-gen"),
    ]
    minted_base_types: "dict[str, dict]" = {}
    minted_families: "set[str]" = set()

    def resolve_hard(module: str, value: object) -> bool:
        if module == "base-types-gen":
            return value in minted_base_types
        if module == "affix-families-gen":
            return value in minted_families
        return False

    def generate(req: BackfillRequest) -> "dict[str, dict]":
        if req.target_module == "base-types-gen":
            # Minting the missing base-type ITSELF introduces a new, still-unresolved reference —
            # the exact cascade case this guard exists to catch.
            minted_base_types[req.id_or_selector] = {}
            return {req.id_or_selector: {"implicitFamily": "atom.newly-required"}}
        if req.target_module == "affix-families-gen":
            minted_families.add(req.id_or_selector)
            return {}
        raise AssertionError(f"unexpected backfill target {req.target_module!r}")

    final_entries, remaining = run_backfill_loop(
        entries, manifest, resolve_hard,
        resolve_categorical=lambda m, v: 0,
        generate=generate,
        max_depth=3,
    )
    assert remaining == []
    assert "item.missing-050" in minted_base_types
    assert "atom.newly-required" in minted_families


def test_cascade_guard_reports_unresolvable_past_the_depth_cap() -> None:
    """A pathological generator that never actually closes the gap must not loop forever."""
    entries = {"recipe.001": {"outputRef": "item.never-minted"}}
    manifest = [ReferenceManifestEntry("outputRef", HARD, "base-types-gen")]

    def generate(req: BackfillRequest) -> "dict[str, dict]":
        return {}  # deliberately does not close the gap

    _, remaining = run_backfill_loop(
        entries, manifest,
        resolve_hard=lambda m, v: False,
        resolve_categorical=lambda m, v: 0,
        generate=generate,
        max_depth=2,
    )
    assert len(remaining) == 1
    assert remaining[0].id_or_selector == "item.never-minted"
