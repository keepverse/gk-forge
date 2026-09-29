"""Tests for the motif gloss pipeline (NS14, spec-gloss-fill.md).

    python -m pytest gk-forge/tools/seedsmith/tests/test_narrative_gloss_fill.py -q -s

Fixture motifs and glosses only, and every call goes through a stub — the transport is never reached.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from seedsmith.adapters.narrative.gloss import (  # noqa: E402
    GLOSS_MAX_LENGTH,
    MAX_HEAL,
    SENSES,
    build_chunk_brief,
    chunk_motifs,
    chunk_schema,
    fill_glosses,
    sense_order_for,
)
from seedsmith.pipeline.llm_caller import LlmCallerConfig  # noqa: E402

MOTIFS = ["\u9F99\u7FFC", "\u6697\u6F6E", "\u706B"]          # 龙翼, 暗潮, 火
EXEMPLARS = [{"motif": "\u706B", "gloss": "fire", "sense": "concrete"}]


class StubCall:
    """A `call(system, user, *, config, schema) -> str` stub: queues answers, records the prompts."""

    def __init__(self, answers: "list[dict]") -> None:
        import collections

        self._answers = collections.deque(answers)
        self.calls: "list[tuple[str, str]]" = []

    def __call__(self, system: str, user: str, *, config=None, schema=None) -> str:
        self.calls.append((system, user))
        if not self._answers:
            raise AssertionError("stub exhausted -- more calls made than answers supplied")
        return json.dumps(self._answers.popleft())


class RaisingCall:
    def __call__(self, *args, **kwargs) -> str:
        raise AssertionError("a dry run must make no model call")


def _answer(*rows: "tuple[str, str, str]", blocked: str = "") -> dict:
    return {"blocked": blocked,
            "glosses": [{"motif": m, "gloss": g, "sense": s} for m, g, s in rows]}


def _fill(answers: "list[dict]", *, check=None, **kwargs) -> dict:
    return fill_glosses(MOTIFS, call=StubCall(answers), config=LlmCallerConfig(model="test-model"),
                        exemplars=EXEMPLARS, chunk_size=10, **kwargs)


def test_the_chunk_schema_is_closed_guarded_and_negative():
    schema = chunk_schema(senses=SENSES)
    assert schema["additionalProperties"] is False
    assert schema["required"] == ["blocked", "glosses"]
    item = schema["properties"]["glosses"]["items"]
    assert item["additionalProperties"] is False
    assert item["required"] == ["motif", "gloss", "sense"]
    assert item["properties"]["gloss"]["maxLength"] == GLOSS_MAX_LENGTH
    assert item["properties"]["sense"]["enum"] == list(SENSES)
    # Every field names what it is NOT, walked to every depth (the audit's own fourth rule).
    def walk(node, path="$"):
        if isinstance(node, dict):
            for key, value in node.items():
                if key == "description":
                    assert " NOT " in value, f"{path}.{key} has no negative clause: {value}"
                else:
                    walk(value, f"{path}.{key}")
        elif isinstance(node, list):
            for i, value in enumerate(node):
                walk(value, f"{path}[{i}]")
    walk(schema)


def test_sense_is_permuted_per_motif_and_reproducible():
    first = sense_order_for(MOTIFS[0])
    second = sense_order_for(MOTIFS[0])
    assert first == second                       # deterministic, seeded from the motif
    assert sorted(first) == sorted(SENSES)       # a permutation, never a subset
    assert sense_order_for(MOTIFS[1]) != first   # a different motif gets a different order


def test_chunking_is_order_preserving_and_bounded():
    chunks = chunk_motifs([f"m{i}" for i in range(7)], 3)
    assert [len(c) for c in chunks] == [3, 3, 1]
    assert [m for c in chunks for m in c] == [f"m{i}" for i in range(7)]


def test_dry_run_makes_no_call():
    result = fill_glosses(MOTIFS, call=RaisingCall(), config=LlmCallerConfig(model="m"),
                          exemplars=EXEMPLARS, chunk_size=2, dry_run=True)
    assert result["dryRun"] is True
    assert result["chunks"] == 2                 # 3 motifs at 2 per chunk
    assert result["glosses"] == {} and result["calls"] == 0


def test_limit_bounds_the_run():
    stub = StubCall([_answer((MOTIFS[0], "dragon wing", "concrete"))])
    result = fill_glosses(MOTIFS, call=stub, config=LlmCallerConfig(model="m"), exemplars=EXEMPLARS,
                          chunk_size=1, limit=1)
    assert len(stub.calls) == 1                  # three chunks available, one drawn
    assert result["chunks"] == 1
    assert result["glosses"][MOTIFS[0]]["gloss"] == "dragon wing"
    # The undrawn chunks were never attempted, so they are in NEITHER result: `--limit` bounds the run,
    # it does not mark the rest unresolved.
    assert result["unresolved"] == {}
    assert set(result["glosses"]) == {MOTIFS[0]}


def test_a_chunk_is_one_call_and_the_vote_set_is_empty_and_justified():
    stub = StubCall([_answer(*[(m, g, "concrete") for m, g in zip(MOTIFS, ("ember ward", "quiet stone", "salt wind"))])])
    result = fill_glosses(MOTIFS, call=stub, config=LlmCallerConfig(model="m"), exemplars=EXEMPLARS,
                          chunk_size=10)
    assert len(stub.calls) == 1                  # no cross-sample vote: one call per chunk
    assert result["votes"] == ()                 # empty by design, and the key exists to say so
    assert len(result["glosses"]) == 3


def test_two_repairs_then_unresolved():
    # The heal budget is passed explicitly as `max_heal=MAX_HEAL`: one attempt plus two repairs.
    bad = _answer((MOTIFS[0], "", "concrete"))
    stub = StubCall([bad, bad, bad])
    result = fill_glosses([MOTIFS[0]], call=stub, config=LlmCallerConfig(model="m"),
                          exemplars=EXEMPLARS, chunk_size=10)
    assert len(stub.calls) == 1 + MAX_HEAL == 3
    assert result["unresolved"][MOTIFS[0]].startswith("unresolved after heal")
    assert result["glosses"] == {}


def test_exhausted_heal_never_writes_the_source():
    # `default_for` answers the empty string, so the motif itself can never come back as its gloss.
    stub = StubCall([_answer() for _ in range(1 + MAX_HEAL)])
    result = fill_glosses(MOTIFS[:1], call=stub, config=LlmCallerConfig(model="m"),
                          exemplars=EXEMPLARS, chunk_size=10)
    assert MOTIFS[0] not in result["glosses"]
    assert all(row["gloss"] != MOTIFS[0] for row in result["glosses"].values())


def test_a_gloss_equal_to_its_motif_is_a_hard_defect():
    stub = StubCall([_answer((MOTIFS[0], MOTIFS[0], "concrete"))] + [_answer((MOTIFS[0], "fire", "concrete"))])
    result = fill_glosses([MOTIFS[0]], call=stub, config=LlmCallerConfig(model="m"),
                          exemplars=EXEMPLARS, chunk_size=10)
    assert len(stub.calls) == 2                  # the identity gloss was rejected, then repaired
    assert result["glosses"][MOTIFS[0]]["gloss"] == "fire"


def test_already_glossed_motifs_are_not_sent():
    stub = StubCall([_answer((MOTIFS[1], "dark tide", "abstract"),
                         (MOTIFS[2], "cinder spark", "concrete"))])
    result = fill_glosses(MOTIFS, call=stub, config=LlmCallerConfig(model="m"), exemplars=EXEMPLARS,
                          chunk_size=10, already_glossed=[MOTIFS[0]])
    assert len(stub.calls) == 1
    assert MOTIFS[0] not in stub.calls[0][1]     # the glossed motif is not in the brief at all
    assert MOTIFS[1] in stub.calls[0][1]
    assert MOTIFS[0] not in result["glosses"]


def test_a_blocked_chunk_writes_nothing_and_is_not_retried():
    stub = StubCall([_answer(blocked="the citations are contradictory")])
    result = fill_glosses(MOTIFS, call=stub, config=LlmCallerConfig(model="m"), exemplars=EXEMPLARS,
                          chunk_size=10, max_heal=MAX_HEAL)
    assert len(stub.calls) == 1                  # a refusal is not re-prompted
    assert result["glosses"] == {}
    assert all(reason.startswith("blocked:") for reason in result["unresolved"].values())


def test_the_committed_exemplars_and_budget_load():
    from seedsmith.workspace_roots import content_root

    doc = json.loads((content_root() / "data/seed/narrative/_exemplars/gloss.en.v1.json")
                     .read_text(encoding="utf-8"))
    assert doc["locale"] == "en"
    assert doc["pairs"], "the exemplar file must carry authored pairs"
    for pair in doc["pairs"]:
        assert pair["sense"] in SENSES
        assert not any(ch.isdigit() for ch in pair["gloss"])
    budget = json.loads((content_root() / "data/seed/narrative/_plan/budget.v1.json")
                        .read_text(encoding="utf-8"))
    assert budget["gloss"]["maxWords"] == 4
    assert budget["gloss"]["exemplarCount"] == len(doc["pairs"])
    print(f"\ngloss prompt readings: exemplar pairs={len(doc['pairs'])} "
          f"chunkSize={budget['gloss']['chunkSize']} reviewSample={budget['gloss']['reviewSample']}")


def test_the_brief_carries_this_chunks_own_sense_order():
    order = {m: sense_order_for(m) for m in MOTIFS}
    brief = build_chunk_brief(MOTIFS, exemplars=EXEMPLARS, senses=SENSES, sense_order=order)
    for motif in MOTIFS:
        assert f"- {motif}: {', '.join(order[motif])}" in brief
    assert "do not copy their words" in brief
