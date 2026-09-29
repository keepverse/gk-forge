"""seedsmith.workflow.graphs — the ONLY package permitted to import LangGraph.

⛔ **The seam (spec-workflow-runtime.md §2.1).** Node bodies live in `workflow/nodes/` and import
nothing from LangGraph; these modules are thin wiring. If the engine is ever replaced, every node
survives unchanged and only this package is rewritten. `test_workflow_structure.py` asserts the
import boundary by grep — the rule is enforced, not trusted.
"""
from .base import RECURSION_LIMIT, build_generation_graph, route_after_validate

__all__ = ["build_generation_graph", "route_after_validate", "RECURSION_LIMIT"]
