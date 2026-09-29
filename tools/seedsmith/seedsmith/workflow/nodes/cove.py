"""Chain-of-verification — SPECIFIED IN FULL, NOT WIRED IN (spec-quality-gates.md §2.3).

⛔ **Why it exists but is off.** Measured on the real shoehorned outputs tier 2 had passed:

  * SUBJECTIVE form ("does this use the keyword meaningfully?") — agreed with human judgement
    **1/3**. It passed BOTH shoehorned cases, rationalising them (*"'一类' defines a specific
    category of behavior"*). Any text can be rationalised, so a subjective verifier defaults to
    charitable and catches nothing.
  * SOURCE-GROUNDED form ("what does the source say this creature does? is the draft consistent?") —
    **2/3**. It caught both shoehorned cases. Its one miss was a FALSE POSITIVE on good content.

So CoVe works only source-grounded, and even then it rejects good content sometimes.

⛔ **And it is not built into the default graph**, because shoehorning is caused by BAD MOTIFS,
which `motif-prose-filter` (G1) fixes at the source for zero model cost. CoVe treats the symptom at
3-4x the calls plus a false-positive rate. Build it only if shoehorning is MEASURED to persist
after G1 — `spec-pipeline.md:109`'s own rule applied to ourselves.
"""
from __future__ import annotations

from typing import Any, Callable, Mapping, Sequence

__all__ = ["COVE_ENABLED", "VERIFICATION_SCHEMA", "is_source_grounded",
           "make_cove_node", "SubjectiveQuestionError"]

#: ⛔ Off by default, asserted by test. Flipping this is an evidence-backed act, not a config tweak.
COVE_ENABLED = False

#: No verdict field: `audit_open_loop_schema`'s rule. The model answers a question FROM SOURCE and
#: states consistency; it never scores its own quality.
VERIFICATION_SCHEMA: "dict[str, Any]" = {
    "type": "object",
    "properties": {
        "answerFromSource": {"type": "string"},
        "draftContradictsSource": {"type": "boolean"},
        "contradiction": {"type": "string"},
    },
    "required": ["answerFromSource", "draftContradictsSource"],
    "additionalProperties": False,
}

#: Words that mark a question as asking for an OPINION rather than a fact recoverable from source.
_SUBJECTIVE_MARKERS = (
    "meaningful", "meaningfully", "good", "better", "best", "quality", "well written",
    "well-written", "evocative", "interesting", "compelling", "appropriate", "rate ", "score",
)


class SubjectiveQuestionError(ValueError):
    """Raised when a verification question asks for a quality opinion.

    This is the defect that made the first implementation useless (1/3). The spec previously said
    only "answer against the source material", which was ambiguous enough that its own author built
    the subjective form on the first attempt — so the rule is now mechanical."""


def is_source_grounded(question: str) -> bool:
    """A verification question must be answerable from source text ALONE."""
    q = question.lower()
    return not any(m in q for m in _SUBJECTIVE_MARKERS)


def make_cove_node(
    *,
    ask: "Callable[..., Mapping[str, Any]]",
    questions_for: "Callable[[Mapping[str, Any]], Sequence[str]]",
    source_of: "Callable[[Mapping[str, Any]], str]",
    enabled: bool = COVE_ENABLED,
):
    """Build the verification node. Rejection routes to ESCALATE, never to auto-repair — an
    unreliable judge (it has a measured false-positive rate) must not silently drive the loop."""

    def cove_node(state: dict) -> dict:
        if not enabled:
            return {"verified": False}
        draft = state.get("draft")
        if not isinstance(draft, dict):
            return {"verified": False}

        context = state.get("context") or {}
        source = source_of(context)
        for question in questions_for(draft):
            if not is_source_grounded(question):
                raise SubjectiveQuestionError(
                    f"verification question is subjective, not source-grounded: {question!r}")
            # The verifier is given the SOURCE and the DRAFT — never the draft's justification.
            verdict = ask(source=source, question=question, draft=draft)
            if verdict.get("draftContradictsSource"):
                reason = verdict.get("contradiction") or "draft contradicts the source"
                return {"verified": False, "defects": [f"CoVe: {reason}"], "outcome": "escalated"}
        return {"verified": True}

    return cove_node
