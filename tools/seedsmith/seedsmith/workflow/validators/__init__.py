"""seedsmith.workflow.validators — tier-2 deterministic checks (spec-quality-gates.md §2.2).

Pure functions, no model, no LangGraph. Each returns a list of defect strings that name the FIELD
and the OFFENDING VALUE, because those strings become the repair prompt (`spec-pipeline.md` §3.6:
"name the exact defects"). Every validator here traces to a defect observed in a real run.

⛔ **A tier-2 pass is NOT a quality result (§2.4).** Measured: 8/8 first-attempt pass on visibly
shoehorned content. "Uses the token" is mechanically checkable; "uses it meaningfully" is not.
`TIER` exists so a caller cannot report one as the other by accident.
"""
from .field_echo import (
    DEFAULT_SUBJECT_KIND,
    field_echo,
    name_collision,
    non_empty,
    subject_name_echo,
)
from .language import language_consistency
from .motif import anti_motif_violation, motif_coverage
from .registry import TIER, Tier, ValidatorResult, run_validators
from .scripts import script_policy

__all__ = [
    "motif_coverage", "anti_motif_violation", "field_echo", "non_empty",
    "language_consistency", "subject_name_echo", "name_collision", "script_policy",
    "run_validators", "TIER", "Tier", "ValidatorResult", "DEFAULT_SUBJECT_KIND",
]
