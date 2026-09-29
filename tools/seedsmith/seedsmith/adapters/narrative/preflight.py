"""The gloss preflight (spec-gloss-fill.md §5, NS15).

**Exactly one real call**, made before a batch is spent, to prove the endpoint answers the chunk schema
the batch will use. It fails LOUDLY on any non-conforming reply — an unparseable body, a `blocked` set, a
missing entry, an empty gloss, a gloss that is the motif, a digit — because a batch run against an
endpoint that cannot honour the schema would burn its whole budget producing rows that all end unresolved.
"""
from __future__ import annotations

from typing import Any, Callable, Mapping, Sequence

from ...briefkit.gloss import BriefRefusal
from ...pipeline.llm_caller import LlmCallerConfig, extract_json
from .gloss.fill import SENSES, SYSTEM_PROMPT, sense_order_for, verify_chunk
from .gloss.prompt import build_chunk_brief, chunk_schema

__all__ = ["PREFLIGHT_MOTIF", "preflight"]

#: The one motif the preflight glosses. A real motif from the source vocabulary (fire) — the point is to
#: exercise the same prompt shape a batch uses, not a synthetic placeholder.
PREFLIGHT_MOTIF = "\u706B"


def preflight(*, call: "Callable[..., str] | None" = None, config: LlmCallerConfig,
              exemplars: "Sequence[Mapping[str, str]]", motif: str = PREFLIGHT_MOTIF,
              senses: "Sequence[str]" = SENSES) -> "dict[str, Any]":
    """Prove the endpoint honours the chunk schema with ONE call. Raises `BriefRefusal` otherwise."""
    from ...pipeline.llm_caller import call_model

    caller = call or call_model
    schema = chunk_schema(senses=senses)
    items = {"motifs": [motif]}
    brief = build_chunk_brief([motif], exemplars=exemplars, senses=senses,
                              sense_order={motif: sense_order_for(motif, senses)})
    try:
        raw = caller(SYSTEM_PROMPT, brief, config=config, schema=schema)
    except Exception as exc:                      # a dead endpoint is a preflight failure, not a crash
        raise BriefRefusal(f"preflight call failed: {type(exc).__name__}: {exc}") from None
    try:
        out = extract_json(raw)
    except Exception as exc:
        raise BriefRefusal(f"preflight reply is not JSON the schema's shape: {exc}") from None
    hard, soft = verify_chunk(items, out)
    if soft.get("blocked") or hard:
        reason = soft.get("blocked") or hard
        raise BriefRefusal(f"preflight reply did not conform to the chunk schema: {reason}")
    row = next(r for r in out["glosses"] if r.get("motif") == motif)
    return {"motif": motif, "gloss": row["gloss"], "sense": row["sense"], "calls": 1}
