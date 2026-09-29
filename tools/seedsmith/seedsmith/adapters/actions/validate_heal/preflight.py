"""seedsmith.adapters.actions.validate_heal.preflight --- `--preflight` (spec-validate-heal.md SS6
hazard 4, acceptance #9c). Stage 0's second half: the schema audit proves the schema FORBIDS a
number; this proves the server is READING the schema at all. One real call, one probe schema with a
single-member enum. Modelled closely on `adapters/creatures/preflight.py`'s own
`check_5_and_6_model` (the only other constrained-decoding preflight in this codebase) but scoped
down to the one check this module owns --- no dump/venv/disk checks, those are the creature-seed
program's own.

**This is the one item in this module that needs something outside the repo** (a live model
server) --- it blocks no module's build, only a real generation round (SS6 hazard 4's own words).
Every test in this module's own suite exercises this against the raising stub / under `--dry-run`
and asserts the SKIP, never the call, because tests never call a model (binding constraint 8).
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Callable

__all__ = ["PROBE_SCHEMA", "PreflightResult", "run_preflight", "CallModelFn"]

#: A single required property, a single-member enum --- the smallest possible probe that still
#: proves the server is constraining decoding to the SCHEMA's own vocabulary, not merely returning
#: valid JSON by luck.
PROBE_SCHEMA: "dict[str, object]" = {
    "type": "object",
    "properties": {
        "acknowledged": {"type": "string", "enum": ["preflight-ok"]},
    },
    "required": ["acknowledged"],
    "additionalProperties": False,
}

CallModelFn = Callable[[str, str, dict], str]


@dataclass(frozen=True)
class PreflightResult:
    status: str                 # "passed" | "failed" | "skipped"
    detail: str
    endpoint: "str | None" = None
    model_id: "str | None" = None

    @property
    def blocks_run(self) -> bool:
        """Only a real, FAILED probe blocks a run --- `skipped` (dry-run / no transport) does not,
        by construction (SS6 hazard 4: "it blocks no module's build")."""
        return self.status == "failed"


def run_preflight(*, skip: bool, call_model_fn: "Callable[[str, str, dict], str] | None" = None,
                  endpoint: "str | None" = None, model_id: "str | None" = None) -> PreflightResult:
    """`skip=True` (the `--dry-run` path, and every test in this module's own suite) never touches
    `call_model_fn` --- it need not even be supplied. `skip=False` with no `call_model_fn` is a
    caller error (there is no default real transport wired here on purpose: the caller, the CLI
    entrypoint, is the one place that legitimately knows how to reach a real model)."""
    if skip:
        return PreflightResult(status="skipped", detail="--dry-run or a raising test stub -- "
                               "constrained decoding was not proven this run", endpoint=endpoint,
                               model_id=model_id)
    if call_model_fn is None:
        raise ValueError("run_preflight(skip=False) requires call_model_fn")

    system = "You are a preflight probe. Reply only via the given schema."
    user = "Acknowledge you are online by setting acknowledged='preflight-ok'."
    try:
        raw = call_model_fn(system, user, PROBE_SCHEMA)
    except Exception as e:
        return PreflightResult(status="failed", detail=f"call failed: {e}", endpoint=endpoint,
                               model_id=model_id)

    from ....pipeline.llm_caller import extract_json
    try:
        parsed = extract_json(raw)
    except Exception:
        return PreflightResult(
            status="failed",
            detail=f"reply did not parse as JSON matching the probe schema: {raw[:200]!r}",
            endpoint=endpoint, model_id=model_id,
        )

    ok = isinstance(parsed, dict) and parsed.get("acknowledged") == "preflight-ok" \
        and set(parsed.keys()) == {"acknowledged"}
    if ok:
        return PreflightResult(status="passed", detail="server honours response_format=json_schema",
                               endpoint=endpoint, model_id=model_id)
    return PreflightResult(
        status="failed",
        detail=f"reply did not match the probe schema exactly: {json.dumps(parsed) if isinstance(parsed, dict) else raw[:200]}",
        endpoint=endpoint, model_id=model_id,
    )
