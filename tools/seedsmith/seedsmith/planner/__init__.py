"""seedsmith.planner — refuses the impossible and orders the possible (spec-planner.md).

W2's home. Two incidents shaped it, and both are structural fixes rather than reminders:

- **75 uniques into 40 slots** was refused with a bare "infeasible", so finding *which* demands
  collided cost a manual bisect. `feasibility` now names the binding constraint via Koenig's
  theorem — the refusal is actionable by construction.
- **274 same-stage errors** happened because a generation stage was hand-labelled and the label
  went stale. Ordering is derived from the kind graph instead, so there is no label to forget.
"""
from __future__ import annotations

from .feasibility import (
    BindingConstraint,
    Demand,
    FeasibilityResult,
    check_feasibility,
    latin_square_axes,
    latin_square_collisions,
    maximum_matching,
    minimum_vertex_cover,
)
from .demand import Candidate, DemandGraph, Fulfilment, NeedSpec, declare, fulfil
from .schedule import (
    DEFAULT_MODEL_TIERS,
    EXCLUDED_REASON_MISLABELED,
    Excluded,
    Job,
    Layer,
    ModelTiers,
    Partition,
    WorkOrder,
    schedule,
)
from .validate import EXIT_EXEMPLAR_REFUSED, ExemplarGateResult, gate_exemplars
from .ordering import (
    KindOrder,
    OrderCycle,
    derive_kind_order,
    kind_edges,
    strongly_connected,
)

__all__ = [
    "BindingConstraint",
    "Demand",
    "FeasibilityResult",
    "check_feasibility",
    "latin_square_axes",
    "latin_square_collisions",
    "maximum_matching",
    "minimum_vertex_cover",
    "KindOrder",
    "OrderCycle",
    "derive_kind_order",
    "kind_edges",
    "strongly_connected",
    "EXIT_EXEMPLAR_REFUSED",
    "ExemplarGateResult",
    "gate_exemplars",
    "DEFAULT_MODEL_TIERS",
    "EXCLUDED_REASON_MISLABELED",
    "Excluded",
    "Job",
    "Layer",
    "ModelTiers",
    "Partition",
    "WorkOrder",
    "schedule",
    "Candidate",
    "DemandGraph",
    "Fulfilment",
    "NeedSpec",
    "declare",
    "fulfil",
]
