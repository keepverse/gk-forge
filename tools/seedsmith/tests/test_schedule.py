"""P4 — scheduling and the work order. The known-answer test from spec-planner.md §7, plus the
plan's own two acceptance criteria:

1. "Given the real corpus's still-open partitions (`gems/2`, `display-templates/{4,5,6}`,
   `attributes`), the emitted plan places `gems/2` after its registry dependency and the three
   display-template partitions after the affix families they render"
2. "The four base-type partitions from S2 are correctly NOT included as generation jobs here — they
   are mislabeled, not empty"

Criterion 2 **contradicts spec-planner.md §7**, which says to place those four in the base-type
layer. The plan and todo are newer and evidence-backed: S2 verified their `_meta.partition` string
is wrong while the entries' own `role`/`frame` fields are intact, so they hold real content. The
plan wins, and this file pins that resolution so nobody re-derives it from the stale sentence.
"""
from __future__ import annotations

from dataclasses import dataclass

import pytest

from seedsmith.planner import derive_kind_order
from seedsmith.planner.schedule import (
    DEFAULT_MODEL_TIERS,
    EXCLUDED_REASON_MISLABELED,
    Partition,
    schedule,
)


@dataclass(frozen=True)
class _Kind:
    kind: str
    reference_fields: frozenset


def _real_shape_order():
    """The real corpus's dependency shape, reduced to the kinds this test needs.

    `gem` depends on its registry (`curve` stands in for the registry dependency the acceptance
    names), and `display-template` renders affix families.
    """
    graph = {
        "curve": set(),
        "affix-family": set(),
        "base-type": set(),
        "attribute": set(),
        "gem": {"curve"},
        "display-template": {"affix-family"},
    }
    return derive_kind_order(graph)


def _open_partitions():
    """The real corpus's eight still-open partitions (map §7.4), as the planner would receive them:
    four base-type cells excluded as mislabeled, four genuinely open."""
    return [
        Partition("gems/2", "gem", entries=6, closes=(("Coverage/EmptyPartition", "gems/2"),)),
        Partition("display-templates/4", "display-template", entries=3,
                  closes=(("Coverage/EmptyPartition", "display-templates/4"),)),
        Partition("display-templates/5", "display-template", entries=9,
                  closes=(("Coverage/EmptyPartition", "display-templates/5"),)),
        Partition("display-templates/6", "display-template", entries=2,
                  closes=(("Coverage/EmptyPartition", "display-templates/6"),)),
        Partition("attributes", "attribute", entries=4,
                  closes=(("Coverage/EmptyPartition", "attributes"),)),
        *[
            Partition(f"base-types/mislabeled-{i}", "base-type", entries=0,
                      excluded_reason=EXCLUDED_REASON_MISLABELED)
            for i in range(4)
        ],
    ]


def _order():
    return schedule(
        _open_partitions(), _real_shape_order(),
        budget_version=3, corpus_revision="abc123", concurrency=4,
    )


# ---- Criterion 1: the known-answer test --------------------------------------------------------


def test_gems_two_lands_after_its_registry_dependency():
    order = _order()
    assert order.layer_of("gems/2") > 1, "gem depends on curve; it cannot be in the first layer"


def test_the_three_display_template_partitions_land_after_the_affix_families_they_render():
    order = _order()
    for p in ("display-templates/4", "display-templates/5", "display-templates/6"):
        assert order.layer_of(p) > 1


def test_the_plan_matches_what_a_human_would_write():
    """spec-planner.md §7's own standard, asserted as a whole rather than field by field: two
    layers, independents first, dependents second."""
    order = _order()

    assert [l.layer for l in order.layers] == [1, 2]
    assert [j.partition for j in order.layers[0].jobs] == ["attributes"]
    assert [j.partition for j in order.layers[1].jobs] == [
        "display-templates/5",   # 9 entries — longest first
        "gems/2",                # 6
        "display-templates/4",   # 3
        "display-templates/6",   # 2
    ]


# ---- Criterion 2: the four mislabeled partitions are EXCLUDED, and said so ---------------------


def test_the_four_mislabeled_base_type_partitions_are_not_generation_jobs():
    order = _order()

    assert not any(j.kind == "base-type" for j in order.jobs)
    with pytest.raises(KeyError):
        order.layer_of("base-types/mislabeled-0")


def test_an_excluded_partition_is_reported_rather_than_silently_dropped():
    """A partition that vanishes with no explanation reads as a planner bug, and someone re-adds it.
    The reason has to travel with the artifact."""
    order = _order()

    assert len(order.excluded) == 4
    assert {e.reason for e in order.excluded} == {EXCLUDED_REASON_MISLABELED}
    assert "relabel" in EXCLUDED_REASON_MISLABELED
    assert all(e.kind == "base-type" for e in order.excluded)


# ---- Scheduling rules --------------------------------------------------------------------------


def test_jobs_within_a_layer_are_longest_first():
    """List scheduling's whole point: starting the long jobs first shortens the makespan."""
    order = _order()
    sizes = [j.entries for j in order.layers[1].jobs]

    assert sizes == sorted(sizes, reverse=True)


def test_ties_break_on_partition_id_so_the_plan_is_reproducible():
    """A schedule that reorders between runs cannot be diffed against the one a human would write —
    which is the standard §7 judges this module by."""
    parts = [Partition(f"p{i}", "gem", entries=5) for i in range(6)]
    graph_order = derive_kind_order({"gem": set()})

    first = schedule(parts, graph_order, budget_version=1, corpus_revision="r").to_dict()
    for _ in range(5):
        assert schedule(parts, graph_order, budget_version=1,
                        corpus_revision="r").to_dict() == first


def test_the_concurrency_cap_chunks_a_layer_without_changing_its_dependency_stage():
    """`layer` means dependency stage. Folding the cap into it would conflate "cannot run yet" with
    "no worker free" — different problems with different fixes."""
    order = _order()

    assert len(order.layers) == 2, "the cap must not invent extra dependency layers"
    waves = order.waves(2)
    assert waves == (("display-templates/5", "gems/2", "display-templates/4", "display-templates/6"),)

    tight = schedule(_open_partitions(), _real_shape_order(),
                     budget_version=3, corpus_revision="r", concurrency=2)
    assert tight.waves(2) == (
        ("display-templates/5", "gems/2"),
        ("display-templates/4", "display-templates/6"),
    )
    assert len(tight.layers) == 2


# ---- Model tiers: a table, not an optimiser ----------------------------------------------------


def test_identity_inventing_kinds_get_the_stronger_model_and_vocabulary_consumers_the_cheaper():
    order = _order()
    by_partition = {j.partition: j.model for j in order.jobs}

    assert by_partition["gems/2"] == DEFAULT_MODEL_TIERS.strong
    assert by_partition["display-templates/4"] == DEFAULT_MODEL_TIERS.cheap


def test_the_tier_rule_is_a_table_a_caller_can_replace():
    """Auditable beats clever: the rule is data, so a caller can change it without editing the
    scheduler, and a reader can check it without following a search."""
    from seedsmith.planner.schedule import ModelTiers

    flipped = ModelTiers(strong="S", cheap="C", invents_identity=frozenset({"display-template"}))
    order = schedule(_open_partitions(), _real_shape_order(),
                     budget_version=1, corpus_revision="r", tiers=flipped)
    by_partition = {j.partition: j.model for j in order.jobs}

    assert by_partition["display-templates/4"] == "S"
    assert by_partition["gems/2"] == "C"


# ---- The output document -----------------------------------------------------------------------


def test_the_work_order_carries_every_key_spec_section_six_names():
    order = _order().to_dict()

    for key in ("budgetVersion", "corpusRevision", "layers", "feasible", "refusals"):
        assert key in order
    job = order["layers"][0]["jobs"][0]
    for key in ("partition", "kind", "entries", "brief", "model", "constraints", "closes"):
        assert key in job


def test_every_job_names_the_finding_it_closes():
    """The link that makes a work order gradeable. Without it a failed generation and content
    nobody attempted look identical after the fact."""
    order = _order()

    for job in order.jobs:
        assert job.closes, f"{job.partition} closes nothing — it cannot be graded"
        assert all("Coverage/EmptyPartition" in c for c in job.closes)
        assert any(job.partition in c for c in job.closes)


def test_a_dependency_cycle_produces_an_infeasible_order_rather_than_a_partial_schedule():
    """A half-schedule past a cycle is worse than none: some jobs dispatched in an order the graph
    says is impossible."""
    cyclic = derive_kind_order({"a": {"b"}, "b": {"a"}})

    order = schedule([Partition("p", "a", entries=1)], cyclic,
                     budget_version=1, corpus_revision="r")

    assert order.feasible is False
    assert order.layers == ()
    assert order.refusals and "cycle" in order.refusals[0]


def test_a_partition_for_an_unknown_kind_is_refused_in_the_artifact_not_dropped():
    """The adapter offering work for a kind the graph does not know is a real inconsistency. It
    belongs in the document a human reads, not in a stack trace or a silent gap."""
    order = schedule([Partition("p", "ghost", entries=1)], derive_kind_order({"gem": set()}),
                     budget_version=1, corpus_revision="r")

    assert order.jobs == ()
    assert order.refusals and "ghost" in order.refusals[0]
