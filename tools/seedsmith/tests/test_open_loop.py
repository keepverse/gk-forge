"""G3 — open-loop review queue wiring. Acceptance quoted from `tasks/seedsmith-plan.md` Phase 4:

1. "An open-loop pipeline's schema never includes a pass/fail field"
2. "Re-running `metrics` after an open-loop pipeline's generation still reports the same finding as
   open-loop (never silently flips to a pass) — proving generated content can be sampled for review
   without the pipeline being able to mark its own homework"
"""
from __future__ import annotations

import pytest

from seedsmith.metrics.model import Loop, Severity
from seedsmith.pipeline.model import BLOCKED_FIELD
from seedsmith.pipeline.open_loop import (
    NEEDS_REVIEW_FIELD,
    ReviewCandidate,
    audit_open_loop_schema,
    is_open_loop,
    mark_for_review,
    sample_for_review,
)
from seedsmith.pipeline.provenance import PROVENANCE_FIELD

FLAVOUR_SCHEMA = {
    "type": "object",
    "required": ["flavor"],
    "properties": {
        "flavor": {"type": "string"},
        BLOCKED_FIELD: {"type": "boolean"},
        "reason": {"type": "string"},
    },
}


def _generated(i: int, stratum: str = "unique") -> ReviewCandidate:
    return ReviewCandidate(
        id=f"{stratum}.gen-{i}", stratum=stratum,
        data={"flavor": f"line {i}", NEEDS_REVIEW_FIELD: True,
              PROVENANCE_FIELD: {"pipeline": "Quality/FlavourGeneric"}},
    )


# ---- Criterion 1: no pass/fail field, ever ------------------------------------------------------


def test_the_shipped_open_loop_schema_carries_no_verdict_field():
    """The positive control. Without it, every rejection below is satisfied by an audit that
    refuses everything."""
    assert audit_open_loop_schema(FLAVOUR_SCHEMA) == []


@pytest.mark.parametrize("field_name", [
    "pass", "passed", "ok", "valid", "isValid", "approved", "quality", "score", "verdict", "grade",
])
def test_a_verdict_field_is_rejected_under_any_of_its_usual_names(field_name):
    """`qualityOk` and `is_valid` are the same mistake wearing different spellings, so the match is
    normalized rather than exact."""
    defects = audit_open_loop_schema({
        "type": "object",
        "properties": {"flavor": {"type": "string"}, field_name: {"type": "boolean"}},
    })

    assert any(field_name in d.path for d in defects)
    assert "own homework" in defects[0].reason


def test_a_verdict_nested_in_an_array_of_objects_is_still_found():
    """It grades just as effectively from three levels down, and is harder to spot by eye — the same
    argument that makes the numeric audit recursive."""
    defects = audit_open_loop_schema({
        "type": "object",
        "properties": {"lines": {"type": "array", "items": {
            "type": "object", "properties": {"score": {"type": "integer"}}}}},
    })

    assert any("score" in d.path for d in defects)


def test_blocked_is_not_treated_as_a_verdict():
    """Declining to do the work is not a judgement about the work's quality. Conflating them would
    remove the model's only honest way out, which is the opposite of what G1 built."""
    defects = audit_open_loop_schema({
        "type": "object",
        "properties": {BLOCKED_FIELD: {"type": "boolean"}, "reason": {"type": "string"}},
    })

    assert defects == []


def test_an_ordinary_content_field_is_not_mistaken_for_a_verdict():
    """Over-refusing would push authors to rename real fields to dodge the audit, which is worse
    than the defect: the guard would then be routinely worked around."""
    defects = audit_open_loop_schema({
        "type": "object",
        "properties": {"flavor": {"type": "string"}, "tone": {"type": "string"},
                       "passage": {"type": "string"}},
    })

    assert defects == []


# ---- Criterion 2: the finding stays open; generated content is sampled, not graded --------------


def test_generated_rows_are_marked_needs_review():
    marked = mark_for_review({"flavor": "Cut from the last ember-tree."})

    assert marked[NEEDS_REVIEW_FIELD] is True


def test_marking_does_not_mutate_the_entry_it_was_given():
    original = {"flavor": "x"}

    mark_for_review(original)

    assert NEEDS_REVIEW_FIELD not in original


def test_every_sampled_finding_is_a_note_and_never_a_pass():
    """The criterion's core. An open-loop metric that emitted a pass would be answering a question
    it has already said has no machine answer."""
    findings = sample_for_review([_generated(i) for i in range(6)],
                                 metric_id="Quality/FlavourGeneric", revision="r1")

    assert findings
    for finding in findings:
        assert finding.severity is Severity.NOTE
        assert finding.evidence[NEEDS_REVIEW_FIELD] is True
        assert finding.severity is not Severity.GAP


def test_generated_content_enters_the_same_queue_as_existing_content():
    """Same terms, one queue. A separate queue for generated rows would let a reviewer clear the
    'real' one and believe the corpus was reviewed."""
    existing = ReviewCandidate("unique.old-1", "unique", {"flavor": "hand-written"})
    findings = sample_for_review([existing, *[_generated(i) for i in range(3)]],
                                 metric_id="Quality/FlavourGeneric", revision="r1", sample_size=4)

    kinds = {f.evidence["generated"] for f in findings}
    assert kinds == {True, False}, "both generated and existing rows must be sampleable"


def test_the_finding_stays_open_after_generation_rather_than_flipping_to_a_pass():
    """The acceptance, stated as the property that matters: running the pipeline **adds** review
    work. A pipeline able to close its own open-loop finding would make the queue look emptiest
    exactly when it had just filled it."""
    before = sample_for_review([ReviewCandidate("unique.old-1", "unique", {"flavor": "x"})],
                               metric_id="Quality/FlavourGeneric", revision="r1")
    after = sample_for_review(
        [ReviewCandidate("unique.old-1", "unique", {"flavor": "x"}),
         *[_generated(i) for i in range(3)]],
        metric_id="Quality/FlavourGeneric", revision="r2", sample_size=8)

    assert len(after) > len(before)
    assert all(f.severity is Severity.NOTE for f in before + after)


def test_the_sample_is_reproducible_byte_for_byte():
    """`FlavourGeneric` hit this live: Python randomises string hashing per process, so a dict built
    from a set iterates differently across runs even when the sampled *set* is identical.
    "Reproducible" has to mean byte-identical output, not merely set-equal — a reviewer re-reading
    last week's sample needs the same list in the same order."""
    candidates = [_generated(i, s) for s in ("unique", "gem", "charm") for i in range(4)]

    first = [(f.subject, f.message) for f in sample_for_review(
        candidates, metric_id="Quality/FlavourGeneric", revision="r1")]
    for _ in range(5):
        again = [(f.subject, f.message) for f in sample_for_review(
            candidates, metric_id="Quality/FlavourGeneric", revision="r1")]
        assert again == first


def test_the_output_order_does_not_follow_the_caller_s_input_order():
    """What `sorted(sampled)` actually protects against, established by falsifying rather than
    assumed.

    Removing the sort did **not** redden the reproducibility test above: that fixture passes a fixed
    list, so the strata dict is insertion-ordered and stable within and across processes. The sort
    earns its place against a *caller* whose candidate order varies between runs — one built from a
    set, say, which is exactly the shape `FlavourGeneric` was bitten by. This reaches that.
    """
    strata = ("unique", "gem", "charm")
    forward = [_generated(i, s) for s in strata for i in range(3)]
    backward = [_generated(i, s) for s in reversed(strata) for i in range(3)]
    assert [c.id for c in forward] != [c.id for c in backward]

    a = [f.subject for f in sample_for_review(forward, metric_id="m", revision="r1")]
    b = [f.subject for f in sample_for_review(backward, metric_id="m", revision="r1")]

    assert a == b, "output order must follow the strata, not the caller's input order"


def test_every_stratum_gets_at_least_one_sample():
    """The reused S8 guarantee, asserted here because it is the reason a corpus's neglected corners
    get looked at — a plain random N over-represents the largest stratum and can miss a band."""
    candidates = [
        *[_generated(i, "unique") for i in range(20)],
        _generated(0, "gem"),
        _generated(0, "charm"),
    ]

    findings = sample_for_review(candidates, metric_id="Quality/FlavourGeneric",
                                 revision="r1", sample_size=6)

    assert {f.evidence["stratum"] for f in findings} == {"unique", "gem", "charm"}


def test_the_sampler_is_the_shared_one_not_a_second_implementation():
    """G3 says "reused, not reimplemented". A second sampler would drift from the stratification
    guarantee above, and the drift would be invisible until a band went unreviewed."""
    import seedsmith.pipeline.open_loop as module

    assert module.stratified_sample.__module__ == "seedsmith.sampling"


def test_is_open_loop_reads_the_metric_s_own_declaration():
    class _Open:
        loop = Loop.OPEN

    class _Closed:
        loop = Loop.CLOSED

    assert is_open_loop(_Open()) is True
    assert is_open_loop(_Closed()) is False
    assert is_open_loop(object()) is False
