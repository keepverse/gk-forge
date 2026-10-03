"""The completion path must REFUSE an elementPrimary it cannot resolve, and never write it.

Measured live 2026-10-03 on a run that reported itself successful: 42 of 904 species were recorded
in `completed` while their entries carried an elementPrimary outside the six declared ids - 37
absent-or-empty and 5 the literal "unresolved". The consumer, characteristic_pool/catalog.py's
`_live_row`, raises ValueError on exactly that, so the corpus the run scored green could not load.

The refusal is fail-closed and lives BEFORE the write, so a bad entry is never persisted. These tests
need no model, no network and no run harness: they exercise the extracted predicate directly, which
is the same reasoning that made the two-mode authoring seam testable without a model.
"""
from __future__ import annotations

import pathlib

import pytest

pytest.importorskip("langgraph.graph")

from seedsmith.adapters.creatures.anchor.schema import ELEMENTS  # noqa: E402
from seedsmith.adapters.creatures.run import runner  # noqa: E402

RUNNER = pathlib.Path(runner.__file__)


def test_the_enum_is_reused_not_retranscribed():
    """A ninth copy of the six ids is exactly how they drift from ActorElementTypes.cs."""
    assert runner.VALID_ELEMENT_PRIMARY == frozenset(ELEMENTS), (
        "the guard must reuse anchor.schema.ELEMENTS, not spell the ids out again")
    assert len(runner.VALID_ELEMENT_PRIMARY) == 6


@pytest.mark.parametrize("value", sorted(ELEMENTS))
def test_every_declared_element_resolves(value):
    assert runner.element_primary_is_resolvable(value) is True


@pytest.mark.parametrize("value", ["FIRE", " Ice ", "earth", "LiGhT"])
def test_resolution_is_case_and_whitespace_insensitive(value):
    """The consumer lowercases before validating (catalog.py:159-163), so it must agree."""
    assert runner.element_primary_is_resolvable(value) is True


@pytest.mark.parametrize("value", [
    "",                 # what the live run actually wrote, 37 times
    "   ",              # whitespace-only is the same failure wearing a hat
    "unresolved",       # the vote-split sentinel, which the corpus consumer cannot load
    None,               # absent / null
    "fire,ice",         # a list smuggled into a scalar field
    "Element.Fire",     # a C# spelling in a JSON field
])
def test_unresolvable_values_are_refused(value):
    assert runner.element_primary_is_resolvable(value) is False


@pytest.mark.parametrize("value", [0, 1, True, ["fire"], {"element": "fire"}, ("fire",)])
def test_non_string_values_are_refused_without_raising(value):
    """Fail closed, never TypeError: a bad row must become a failure, not a crash of the run."""
    assert runner.element_primary_is_resolvable(value) is False


def test_the_refusal_precedes_the_write_and_the_completion_marker():
    """Placement is the whole fix. Anchoring on the first `_write_species_entry(` put the guard in a
    REPAIR pass - of the five call sites, only the last is followed by `record.completed.append`, and
    only that one can score a species as a success. Asserted against the source so a future edit
    cannot quietly move it back."""
    src = RUNNER.read_text(encoding="utf-8")
    lines = src.splitlines()

    guard = next(i for i, l in enumerate(lines) if "FAIL CLOSED on a required enum" in l)

    # The authoring call carries `merged` and the run's own dump hash; the four repair passes
    # pass `updates`, `{}`, or `{"elementSecondary": ...}` with a captured hash instead.
    write = next(i for i, l in enumerate(lines)
                 if "_write_species_entry(" in l
                 and "def " not in l
                 and "row, merged, dump_hash=record.dump_hash" in lines[i + 1])

    completed = next(i for i, l in enumerate(lines) if "record.completed.append" in l)

    assert guard < write, f"guard at {guard + 1} must precede the write at {write + 1}"
    assert write < completed, (
        f"write at {write + 1} must precede the completion marker at {completed + 1}")


def test_the_refusal_marks_the_species_failed_with_a_reason():
    """The refusal has to be ACTIONABLE: a rerun retries `failed`, and a species that never resolves
    must be visible. Appending to `completed` while refusing to write would be worse than either."""
    src = RUNNER.read_text(encoding="utf-8")
    guard_at = src.index("if violations:")
    window = src[guard_at: src.index("_write_species_entry(", guard_at)]
    assert "record.failed.append(species_id)" in window, window
    assert "_remember_failure(" in window, window
    assert "record.completed.append" not in window, window
    # The reason must name WHAT was wrong, not a fixed string - with ten guards behind it, a message
    # that only ever said "elementPrimary" would misreport nine of them.
    assert '"; ".join(violations)' in window, window


def test_the_refusal_judges_the_MERGED_fields_not_the_pass_output():
    """Regression for a bug this guard shipped with, found live.

    A pipeline-scoped rerun's `merged` holds ONLY that pipeline's own fields; every other field
    arrives via `merge_from`, and that merge happens INSIDE `_write_species_entry` - after the guard
    ran. Judging `merged` alone made the guard refuse every scoped rerun of a pipeline that does not
    itself author elementPrimary: measured, a 111-species `--pipeline identity` rerun failed 110 of
    them with this guard's own refusal, naming an element that was present and valid in the entry
    that would have been written.

    The guard must therefore judge what WILL BE written: the existing entry overlaid with the pass's
    own output, which is what `_write_species_entry` computes. Asserted structurally because the
    guard lives inside a closure with no reachable seam, and a structural assertion is still the
    thing that catches a regression to `merged.get(...)`.
    """
    src = RUNNER.read_text(encoding="utf-8")
    guard_at = src.index("FAIL CLOSED on a required enum")
    window = src[guard_at: src.index("_write_species_entry(", guard_at)]

    assert "effective = {k: v for k, v in (merge_from or {})" in window, (
        "the guard must build the effective fields from merge_from")
    assert "violations = seed_consumer_violations(effective)" in window, (
        "the guard must judge the effective fields, not the pass's own output")
    assert "seed_consumer_violations(merged)" not in window, (
        "the guard regressed to judging the pre-merge fields")
    # And it must reuse the value the write already computed, not compute it a second time.
    assert "merge_from=merge_from)" in src, (
        "the write call must reuse the guard's merge_from rather than recomputing it")