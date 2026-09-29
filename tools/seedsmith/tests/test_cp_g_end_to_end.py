"""⭐ CP-G — the loop closes end to end, against a fake model, before any real token is spent.

The integration the plan names:

    metrics finds a partition empty
      -> planner schedules it (P4)
      -> briefkit briefs it (P6)
      -> pipeline generates content (G1, MockModelServer — no real LLM spend)
      -> metrics re-run shows the finding cleared

This is *"the actual promise behind 'seedsmith replaces the agentic fanout', proven mechanically for
the first time, without spending a single real token to prove it."*

**The stub adapter is used rather than the item corpus**, on purpose. `spec-foundation` §2 keeps it
around precisely so an end-to-end test can run against a two-kind invented feature — which means
this test proves the *machinery* closes the loop, not that one particular corpus happens to.
"""
from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path

import pytest

from seedsmith.adapters._stub import StubAdapter
from seedsmith.briefkit import render_brief
from seedsmith.corpus.model import Corpus
from seedsmith.metrics.coverage import EmptyPartitionMetric
from seedsmith.metrics.model import Ctx
from seedsmith.planner import Partition, derive_kind_order, schedule
from seedsmith.pipeline.llm_caller import LlmCallerConfig
from seedsmith.pipeline.model import BLOCKED_FIELD, Pipeline
from seedsmith.pipeline.provenance import Provenance, ProvenanceLedger, should_generate, stamp
from seedsmith.pipeline.run import run_pipeline

from test_llm_caller import MockModelServer

WIDGET_SCHEMA = {
    "type": "object",
    "required": ["id", "color"],
    "properties": {
        "id": {"type": "string"},
        "color": {"type": "string", "enum": ["red", "blue"]},
        BLOCKED_FIELD: {"type": "boolean"},
        "reason": {"type": "string"},
    },
}


@pytest.fixture()
def root():
    d = Path(tempfile.mkdtemp())
    yield d
    shutil.rmtree(d, ignore_errors=True)


def write(root: Path, rel: str, kind: str, partition: str, entries: list[dict]) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"kind": kind, "_meta": {"partition": partition}, "entries": entries}),
        encoding="utf-8",
    )


def _open_findings(root: Path, adapter) -> list:
    return EmptyPartitionMetric().run(Ctx(corpus=Corpus.load(root), adapter=adapter))


def test_the_whole_loop_closes_without_spending_a_real_token(root):
    """CP-G, as one narrative. Each stage's output is the next stage's input — no stage is handed a
    fixture standing in for the one before it, which is the only way this proves the loop rather
    than proving five modules separately."""
    adapter = StubAdapter()
    server = MockModelServer()
    try:
        # ---- 1. metrics: partition "b" is allocated but empty --------------------------------
        write(root, "widgets/a.json", "widget", "a",
              [{"id": "widget.a-001", "color": "blue"}])

        findings = _open_findings(root, adapter)
        assert [f.subject for f in findings] == ["b"]
        finding = findings[0]
        finding_id = f"{finding.metric}:{finding.subject}"
        assert finding.remedy == "planner: schedule generation for this partition"

        # ---- 2. planner: schedule it, from the finding, not from a hand-written list ----------
        order = derive_kind_order({"widget": set(), "gadget": set()})
        work = schedule(
            [Partition(id=finding.subject, kind="widget", entries=1,
                       constraints={"color": "red"},
                       closes=((finding.metric, finding.subject),))],
            order, budget_version=1, corpus_revision="rev-1",
        )
        assert work.feasible
        job = work.jobs[0]
        assert job.closes == (finding_id,), "the job must name the finding it will close"

        # ---- 3. briefkit: brief the job, inlining the legal vocabulary ------------------------
        brief = render_brief(
            job,
            vocabularies={"color": adapter.registries().vocabularies.get("tags", ())
                          and ("red", "blue")},
            assertion=finding.assertion,
        )
        assert "red" in brief.text and "blue" in brief.text
        assert finding_id in brief.text
        assert ".json" not in brief.text, "a brief cites nothing"

        # ---- 4. pipeline: generate against the FAKE server ------------------------------------
        ledger = ProvenanceLedger()
        go, _ = should_generate(finding_id, open_findings=[finding_id], ledger=ledger)
        assert go is True

        produced: dict = {}
        pipeline = Pipeline(metric=finding.metric, scope=job.partition, schema=WIDGET_SCHEMA,
                            gate=lambda v: [], on_persist=produced.__setitem__)
        server.queue(json.dumps({"w1": {"id": "widget.b-001", "color": "red"}}))
        config = LlmCallerConfig(endpoint=server.url, attempts=1, retry_delay=0)

        result = run_pipeline(pipeline, {"w1": {}}, system=brief.text,
                              build_user=lambda i: json.dumps(i), config=config)
        assert result.ok and result.wrote_anything

        # ---- 5. write it into the corpus, stamped with why it exists --------------------------
        prov = Provenance(pipeline=finding.metric, model=job.model, prompt_version=brief.content_hash,
                          budget_version=1, finding=finding_id,
                          generated_utc="2026-08-31T00:00:00Z")
        entry = stamp(produced["w1"], prov)
        ledger.record(entry["id"], prov)
        write(root, "widgets/b.json", "widget", "b", [entry])

        # ---- 6. metrics re-run: the finding is CLEARED ----------------------------------------
        after = _open_findings(root, adapter)

        assert [f.subject for f in after] == [], (
            "the finding the job promised to close is still open — a job that ran without clearing "
            "its finding is a PIPELINE defect, which is exactly the distinction `closes` exists for"
        )
        assert server.url.startswith("http://127.0.0.1:"), "no real model was contacted"
    finally:
        server.close()


def test_a_second_run_of_the_closed_loop_generates_nothing(root):
    """Idempotence, at the loop level rather than the unit level. Re-running the whole thing after
    it has closed must not re-author the same partition — which is what makes this safe to schedule
    rather than to trigger by hand."""
    adapter = StubAdapter()
    write(root, "widgets/a.json", "widget", "a", [{"id": "widget.a-001", "color": "blue"}])
    write(root, "widgets/b.json", "widget", "b", [{"id": "widget.b-001", "color": "red"}])

    findings = _open_findings(root, adapter)
    assert findings == [], "both partitions are occupied, so nothing is open"

    go, reason = should_generate("Coverage/EmptyPartition:b",
                                 open_findings=[f"{f.metric}:{f.subject}" for f in findings],
                                 ledger=ProvenanceLedger())

    assert go is False
    assert reason == "finding-already-closed"


def test_the_loop_refuses_rather_than_half_running_when_the_planner_finds_a_cycle(root):
    """The negative control for the whole chain. If the ordering is impossible, nothing downstream
    should get a job at all — a half-run loop is how content lands in an order the graph says
    cannot work."""
    cyclic = derive_kind_order({"widget": {"gadget"}, "gadget": {"widget"}})

    work = schedule([Partition("b", "widget", 1)], cyclic,
                    budget_version=1, corpus_revision="rev-1")

    assert work.feasible is False
    assert work.jobs == ()
    assert work.refusals


def test_a_blocked_model_leaves_the_finding_open_rather_than_faking_a_close(root):
    """The honest failure path. A model that declines must leave the partition empty and the finding
    open — the alternative is a loop that reports success while the corpus gained nothing."""
    adapter = StubAdapter()
    server = MockModelServer()
    try:
        write(root, "widgets/a.json", "widget", "a", [{"id": "widget.a-001", "color": "blue"}])
        before = _open_findings(root, adapter)
        assert [f.subject for f in before] == ["b"]

        produced: dict = {}
        pipeline = Pipeline(metric="Coverage/EmptyPartition", scope="b", schema=WIDGET_SCHEMA,
                            gate=lambda v: [], on_persist=produced.__setitem__)
        server.queue(json.dumps({"w1": {BLOCKED_FIELD: True, "reason": "no colour supplied"}}))
        config = LlmCallerConfig(endpoint=server.url, attempts=1, retry_delay=0)

        result = run_pipeline(pipeline, {"w1": {}}, system="s",
                              build_user=lambda i: "u", config=config)

        assert result.ok is True, "a declared block is not a pipeline failure"
        assert produced == {}
        after = _open_findings(root, adapter)
        assert [f.subject for f in after] == ["b"], "the finding must stay open"
    finally:
        server.close()
