"""seedsmith.workflow — workflow DEFINITION (spec-workflow-runtime.md).

`planner` answers *which* content to generate, in what order. This package answers *what happens
inside ONE generation*: steps, state, branching, bounded retry, crash-resume. Those are different
layers and only the first was solved before this module existed.

Importing this package does NOT import LangGraph — `state` and `nodes` are engine-free, and only
`workflow.graphs` pulls the engine in, so the measurement half of seedsmith keeps working without
the `workflow` extra installed.
"""
from .state import GenerationState, new_state

__all__ = ["GenerationState", "new_state"]
