"""seedsmith.pipeline — the only seedsmith module permitted a network dependency.

Only `llm_caller` exists so far (S0). Everything else here (schemas, briefs, guardrails,
runners — spec-pipeline.md) is Wave 3 and gates on `metrics`/`planner` existing.
"""
