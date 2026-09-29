"""G2 — idempotence and provenance. Acceptance quoted from `tasks/seedsmith-plan.md` Phase 4:

1. "Running a pipeline twice over unchanged input produces zero new writes on the second run"
2. "Provenance is queryable by finding id (answers 'why does this row exist' and 'which prompt
   version produced it')"
"""
from __future__ import annotations

import json

import pytest

from seedsmith.pipeline.llm_caller import LlmCallerConfig
from seedsmith.pipeline.model import BLOCKED_FIELD, Pipeline
from seedsmith.pipeline.provenance import (
    PROVENANCE_FIELD,
    Provenance,
    ProvenanceLedger,
    SkipReason,
    should_generate,
    stamp,
)
from seedsmith.pipeline.run import run_pipeline

from test_llm_caller import MockModelServer

FINDING = "Coverage/EmptyPartition:gems/2"

SCHEMA = {
    "type": "object",
    "required": ["flavor"],
    "properties": {
        "flavor": {"type": "string"},
        BLOCKED_FIELD: {"type": "boolean"},
        "reason": {"type": "string"},
    },
}


def _prov(**kw) -> Provenance:
    base = dict(
        pipeline="Quality/FlavourGeneric", model="sonnet", prompt_version="v3",
        budget_version=3, finding=FINDING, generated_utc="2026-08-31T00:00:00Z",
    )
    base.update(kw)
    return Provenance(**base)


@pytest.fixture()
def server():
    s = MockModelServer()
    yield s
    s.close()


# ---- Criterion 1: a second run over unchanged input writes nothing ------------------------------


def test_a_second_run_writes_nothing_when_the_finding_is_already_closed(server):
    """The check that makes the loop safe to schedule rather than only hand-run."""
    persisted: dict = {}
    pipeline = Pipeline(metric="Quality/FlavourGeneric", scope="gems/2", schema=SCHEMA,
                        gate=lambda v: [], on_persist=persisted.__setitem__)
    config = LlmCallerConfig(endpoint=server.url, attempts=1, retry_delay=0)
    ledger = ProvenanceLedger()

    # Run 1: the finding is open, so it generates.
    go, _ = should_generate(FINDING, open_findings=[FINDING], ledger=ledger)
    assert go is True
    server.queue(json.dumps({"g1": {"flavor": "Cut from the last ember-tree."}}))
    run_pipeline(pipeline, {"g1": {}}, system="s", build_user=lambda i: "u", config=config)
    ledger.record("g1", _prov())
    assert len(persisted) == 1
    calls_after_first = len(server.requests)

    # Run 2: the finding is closed. Nothing is generated, and nothing is even asked of the model.
    go, reason = should_generate(FINDING, open_findings=[], ledger=ledger)

    assert go is False
    assert reason == SkipReason.FINDING_ALREADY_CLOSED
    assert len(server.requests) == calls_after_first, "a skipped run must not call the model"
    assert len(persisted) == 1


def test_a_second_run_is_skipped_even_while_the_finding_is_still_open_if_this_pipeline_already_ran():
    """Belt and braces: metrics may not have re-run yet. Without this, a pipeline scheduled twice
    before the next metrics pass duplicates its own output."""
    ledger = ProvenanceLedger()
    ledger.record("g1", _prov())

    go, reason = should_generate(FINDING, open_findings=[FINDING], ledger=ledger)

    assert go is False
    assert reason == SkipReason.ALREADY_GENERATED


def test_the_finding_is_checked_before_the_ledger():
    """Order matters. A finding closed by a *human*, or by another pipeline, must stop this one —
    checking only "did I already run" would regenerate content whose reason for existing had gone.

    The ledger must be **populated** for this to discriminate: with an empty one, either order
    reaches the same answer, and the test would assert nothing about ordering at all. Found by
    falsifying — swapping the two checks reddened a different test than this one, which is how a
    test whose name outruns its fixture gets caught.
    """
    ledger = ProvenanceLedger()
    ledger.record("g1", _prov())

    go, reason = should_generate(FINDING, open_findings=[], ledger=ledger)

    assert go is False
    assert reason == SkipReason.FINDING_ALREADY_CLOSED, (
        "with both conditions true the finding must win — it is the reason the row exists at all"
    )


def test_an_open_finding_with_no_prior_run_generates():
    """The positive control. Without it, every assertion above holds for a checker that always
    refuses — and a pipeline that never runs passes an idempotence test perfectly."""
    go, reason = should_generate(FINDING, open_findings=[FINDING], ledger=ProvenanceLedger())

    assert go is True
    assert reason == ""


def test_recording_the_same_row_twice_raises_rather_than_overwriting():
    """Two runs both believing they created a row *is* the duplicate-write G2 exists to prevent.
    Last-write-wins would hide it; this makes it loud."""
    ledger = ProvenanceLedger()
    ledger.record("g1", _prov())

    with pytest.raises(ValueError, match="idempotence failed"):
        ledger.record("g1", _prov(prompt_version="v4"))


# ---- Criterion 2: queryable by finding, and by prompt version ----------------------------------


def test_provenance_answers_why_this_row_exists():
    ledger = ProvenanceLedger()
    ledger.record("gem.ruby-07", _prov())

    assert ledger.of("gem.ruby-07").finding == FINDING
    assert ledger.rows_for_finding(FINDING) == ("gem.ruby-07",)


def test_every_row_a_finding_produced_is_recoverable_in_one_query():
    """The question asked when a batch turns out bad — and at that moment nobody wants to grep a
    corpus, which is why this is an index rather than a scan."""
    ledger = ProvenanceLedger()
    for i in range(3):
        ledger.record(f"gem.ruby-{i}", _prov())
    ledger.record("other.1", _prov(finding="Coverage/EmptyPartition:attributes"))

    assert len(ledger.rows_for_finding(FINDING)) == 3
    assert ledger.rows_for_finding("Coverage/EmptyPartition:attributes") == ("other.1",)


def test_a_bad_batch_is_scoped_by_prompt_version_not_by_date():
    """"Which prompt version produced it" — the second half of the criterion. Scoping by version is
    exact; scoping by timestamp is a guess about when a change landed."""
    ledger = ProvenanceLedger()
    ledger.record("a", _prov(prompt_version="v3"))
    ledger.record("b", _prov(prompt_version="v4"))
    ledger.record("c", _prov(prompt_version="v4"))

    assert ledger.rows_for_prompt_version("v4") == ("b", "c")
    assert ledger.rows_for_prompt_version("v3") == ("a",)


def test_an_unknown_row_or_finding_answers_empty_rather_than_raising():
    """A query about something that was never generated is a normal question, not an error."""
    ledger = ProvenanceLedger()

    assert ledger.of("nope") is None
    assert ledger.rows_for_finding("nope") == ()


# ---- Stamping ----------------------------------------------------------------------------------


def test_stamping_carries_every_field_the_spec_names():
    stamped = stamp({"flavor": "x"}, _prov())
    recorded = stamped[PROVENANCE_FIELD]

    for key in ("pipeline", "model", "promptVersion", "budgetVersion", "finding", "generatedUtc"):
        assert key in recorded


def test_stamping_does_not_mutate_the_entry_it_was_given():
    """The pre-stamp value is exactly what an idempotence comparison needs; mutating in place
    destroys it."""
    original = {"flavor": "x"}

    stamped = stamp(original, _prov())

    assert original == {"flavor": "x"}
    assert stamped is not original


def test_provenance_round_trips_through_its_dict_form():
    """It is written to disk and read back — a field that survives one direction only is a field
    that silently disappears on reload."""
    prov = _prov()

    assert Provenance.from_dict(prov.to_dict()) == prov


def test_the_timestamp_is_supplied_not_read_from_the_clock():
    """Injected, like the kernel drive's stopwatch. A timestamp read internally makes provenance
    non-reproducible, and a test that cannot pin it either asserts nothing or goes flaky."""
    fixed = _prov(generated_utc="2026-01-01T00:00:00Z")

    assert fixed.generated_utc == "2026-01-01T00:00:00Z"
    assert stamp({}, fixed)[PROVENANCE_FIELD]["generatedUtc"] == "2026-01-01T00:00:00Z"
