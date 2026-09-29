"""G3.3 — CoVe: specified in full, wired OFF (spec-quality-gates.md §2.3)."""
from __future__ import annotations

import pytest

from seedsmith.pipeline.open_loop import audit_open_loop_schema
from seedsmith.workflow.nodes.cove import (
    COVE_ENABLED,
    VERIFICATION_SCHEMA,
    SubjectiveQuestionError,
    is_source_grounded,
    make_cove_node,
)


def test_cove_is_disabled_by_default():
    """Specified, not built. Enabling it is an evidence-backed act — build it only if shoehorning
    is MEASURED to persist after motif-prose-filter removes its cause."""
    assert COVE_ENABLED is False


def test_the_default_node_is_inert_while_disabled():
    node = make_cove_node(ask=lambda **k: pytest.fail("must not call the model while disabled"),
                          questions_for=lambda d: ["what does the source say?"],
                          source_of=lambda c: "src")
    assert node({"draft": {"a": "b"}}) == {"verified": False}


def test_subjective_questions_are_rejected_mechanically():
    """The subjective form scored 1/3 — it passed BOTH shoehorned cases by rationalising them.
    The spec previously said only 'answer against the source material', ambiguous enough that its
    own author built the subjective form first. It is now a mechanical rule."""
    assert not is_source_grounded("Does this use the keyword meaningfully?")
    assert not is_source_grounded("Rate the quality of this doctrine")
    node = make_cove_node(ask=lambda **k: {"draftContradictsSource": False},
                          questions_for=lambda d: ["Is this meaningful?"],
                          source_of=lambda c: "src", enabled=True)
    with pytest.raises(SubjectiveQuestionError):
        node({"draft": {"a": "b"}, "context": {}})


def test_source_grounded_questions_are_accepted():
    assert is_source_grounded("According to the source, what does this creature do?")
    assert is_source_grounded("What does the source say about its defence?")


def test_a_contradiction_escalates_and_never_auto_repairs():
    """CoVe has a measured false-positive rate — it rejected good content 1/3. An unreliable judge
    must not silently drive the repair loop."""
    node = make_cove_node(
        ask=lambda **k: {"answerFromSource": "it explodes",
                         "draftContradictsSource": True,
                         "contradiction": "draft says it defends"},
        questions_for=lambda d: ["what does the source say it does?"],
        source_of=lambda c: "the creature explodes", enabled=True)
    out = node({"draft": {"doctrine": "it defends"}, "context": {}})
    assert out["outcome"] == "escalated"
    assert out["verified"] is False
    assert any("CoVe" in d for d in out["defects"])


def test_a_consistent_draft_verifies():
    node = make_cove_node(ask=lambda **k: {"answerFromSource": "it defends",
                                           "draftContradictsSource": False},
                          questions_for=lambda d: ["what does the source say it does?"],
                          source_of=lambda c: "the creature defends", enabled=True)
    assert node({"draft": {"doctrine": "it defends"}, "context": {}}) == {"verified": True}


def test_the_verification_schema_carries_no_verdict_field():
    assert audit_open_loop_schema(VERIFICATION_SCHEMA) == []
    assert "verdict" not in VERIFICATION_SCHEMA["properties"]
    assert "score" not in VERIFICATION_SCHEMA["properties"]


def test_cove_is_not_wired_into_the_default_graph():
    """The graph skeleton has four nodes; CoVe is not one of them."""
    pytest.importorskip("langgraph.graph")
    from seedsmith.workflow.graphs.base import build_generation_graph

    app = build_generation_graph(generate=lambda s: {}, validate=lambda s: {"defects": []},
                                 persist=lambda s: {"outcome": "persisted"})
    assert "cove" not in {str(n).lower() for n in app.get_graph().nodes}
