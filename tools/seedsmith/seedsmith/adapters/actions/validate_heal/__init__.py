"""seedsmith.adapters.actions.validate_heal --- A-S4 (spec-validate-heal.md), the action-corpus
program's single acceptance point for every candidate the three propose pipelines (A-P1/A-P2/A-P3)
produce: the schema audit (Stage 0, extends `pipeline.model.audit_schema`), the per-candidate gates
(Stage 1, `gates.py`), the vote resolution (Stage 2) and the bounded self-heal (Stage 3, both in
`derive.py`). See `derive.py`'s own module docstring for the two-entry-point shape
(`validate_candidate` for the zero-model-call/recorded path, `run_self_heal` for the one live path)
and `../generate_validate_heal.py` for the CLI.
"""
from __future__ import annotations

from .derive import (
    CandidateVerdict,
    RoundReport,
    VoteSample,
    build_envelope,
    build_heal_user,
    build_verify_fn,
    canonical_dump,
    canonical_set_key,
    candidate_set_hash,
    default_for_none,
    resolve_vote_field,
    run_self_heal,
    validate_candidate,
    validate_round,
    verify_permutation,
)
from .gates import BriefContext, run_g1, run_g2, run_g3
from .preflight import PROBE_SCHEMA, PreflightResult, run_preflight
from .schema_audit import audit_descriptions
from .schemas import (
    FAMILY_SCHEMA,
    GENERAL_SCHEMA,
    PIPELINE_IDS,
    SCHEMAS_BY_PIPELINE,
    SIGNATURE_SCHEMA,
    STRUCTURE_AXES,
    VOTED_FIELDS_BY_PIPELINE,
)

__all__ = [
    "CandidateVerdict", "RoundReport", "VoteSample", "build_envelope", "build_heal_user",
    "build_verify_fn", "canonical_dump", "canonical_set_key", "candidate_set_hash",
    "default_for_none", "resolve_vote_field", "run_self_heal", "validate_candidate",
    "validate_round", "verify_permutation", "BriefContext", "run_g1", "run_g2", "run_g3",
    "PROBE_SCHEMA", "PreflightResult", "run_preflight", "audit_descriptions", "FAMILY_SCHEMA",
    "GENERAL_SCHEMA", "PIPELINE_IDS", "SCHEMAS_BY_PIPELINE", "SIGNATURE_SCHEMA", "STRUCTURE_AXES",
    "VOTED_FIELDS_BY_PIPELINE",
]
