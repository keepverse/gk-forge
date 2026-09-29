"""The `run-control` state machine (creature-seed module 9, spec-run-control.md §2). Pure — states
and legal transitions with no I/O — so every transition is testable without a database.

# A user pause is TRANSIENT, not QUALITY: resume replays the checkpoint and makes no new
# call. Blurring this makes pausing cost money and change answers - runner.py's own
# docstring is the reason, and it costs $150 to learn the other way.
"""
from __future__ import annotations

State = str  # "idle" | "running" | "paused" | "completed" | "cancelled" | "failed"
Verb = str   # "start" | "pause" | "resume" | "cancel" | "complete" | "fail"

STATES = frozenset({"idle", "running", "paused", "completed", "cancelled", "failed"})
TERMINAL_STATES = frozenset({"completed", "cancelled"})

#: `(from_state, verb) -> to_state`. `complete`/`fail` are the machine's own internal outcomes
#: (a run finishing or erroring), not user-issued verbs, but they share this table because they
#: are transitions too — spec §2's diagram draws both kinds on one graph.
_TRANSITIONS: "dict[tuple[State, Verb], State]" = {
    ("idle", "start"): "running",
    ("running", "pause"): "paused",
    ("paused", "resume"): "running",
    ("failed", "resume"): "running",
    ("running", "cancel"): "cancelled",
    ("paused", "cancel"): "cancelled",
    ("running", "complete"): "completed",
    ("running", "fail"): "failed",
}


class IllegalTransition(ValueError):
    def __init__(self, state: State, verb: Verb):
        super().__init__(f"cannot {verb!r} from state {state!r}")
        self.state = state
        self.verb = verb


def transition(state: State, verb: Verb) -> State:
    """Raises `IllegalTransition` rather than guessing — a state machine that silently no-ops on
    an illegal verb is how a resumed run ends up in two states at once."""
    key = (state, verb)
    if key not in _TRANSITIONS:
        raise IllegalTransition(state, verb)
    return _TRANSITIONS[key]


def is_terminal(state: State) -> bool:
    return state in TERMINAL_STATES


def can(state: State, verb: Verb) -> bool:
    return (state, verb) in _TRANSITIONS
