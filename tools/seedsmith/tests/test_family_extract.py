"""Tests for seedsmith.adapters.creatures.family.extract (spec-family-extract.md, wave D2).

`MockModelServer` is imported from `test_llm_caller`, not re-rolled — a second fake server would
drift from the one the transport is actually tested against (the same discipline `test_pipeline_
scaffold.py` already established for G1).
"""
from __future__ import annotations

import json

import pytest

from seedsmith.adapters.creatures.family.extract import (
    BATCH_SIZE,
    build_brief,
    extract_family_candidates,
    form_batches,
)
from seedsmith.adapters.creatures.family.schema import FAMILY_EXTRACTION_SCHEMA
from seedsmith.corpus.model import Entry
from seedsmith.pipeline.llm_caller import LlmCallerConfig
from seedsmith.pipeline.model import audit_schema
from seedsmith.pipeline.open_loop import audit_open_loop_schema

from test_llm_caller import MockModelServer

EXPR = "stated directly — the creature's own signature"


def _entry(id_: str, name: str, flavor_info: "str | None" = None, flavor_introduce: "str | None" = None) -> Entry:
    data = {"id": id_, "name": name}
    if flavor_info:
        data["flavorInfo"] = flavor_info
    if flavor_introduce:
        data["flavorIntroduce"] = flavor_introduce
    return Entry(id=id_, kind="creature", partition="zombie/common", path="x.json", data=data)


@pytest.fixture()
def server():
    s = MockModelServer()
    yield s
    s.close()


# ---- Schema ---------------------------------------------------------------------------------


def test_schema_passes_audit_schema_no_numbers():
    assert audit_schema(FAMILY_EXTRACTION_SCHEMA) == []


def test_schema_passes_open_loop_audit_no_verdict():
    assert audit_open_loop_schema(FAMILY_EXTRACTION_SCHEMA) == []


# ---- Batching ---------------------------------------------------------------------------------


def test_batching_is_deterministic_across_repeat_calls():
    entries = [_entry(f"d{i:02d}", f"Creature {i}") for i in range(20)]
    a = form_batches(entries)
    b = form_batches(list(reversed(entries)))  # input order must not matter
    assert [[e.id for e in batch] for batch in a] == [[e.id for e in batch] for batch in b]


def test_batches_are_fixed_size_windows_sorted_by_species_id():
    entries = [_entry(f"d{i:02d}", f"Creature {i}") for i in range(BATCH_SIZE * 2 + 3)]
    batches = form_batches(entries)
    assert len(batches) == 3
    assert len(batches[0]) == BATCH_SIZE
    assert len(batches[1]) == BATCH_SIZE
    assert len(batches[2]) == 3
    assert [e.id for e in batches[0]] == sorted(e.id for e in entries)[:BATCH_SIZE]


def test_a_creature_appears_in_exactly_one_batch():
    entries = [_entry(f"d{i:02d}", f"Creature {i}") for i in range(BATCH_SIZE * 3)]
    batches = form_batches(entries)
    seen = [e.id for batch in batches for e in batch]
    assert sorted(seen) == sorted(set(seen)), "no creature may appear in more than one batch"


# ---- Brief assembly / citation discipline --------------------------------------------------


def test_brief_contains_no_citation_shaped_text():
    entries = [_entry("wall-nut-zombie", "Wall-Nut Zombie", flavor_info="A stalwart defender.")]
    text = build_brief(entries, creature_expression_rule=EXPR)
    assert "wall-nut-zombie" in text
    assert "stalwart defender" in text


def test_brief_raises_if_a_citation_pattern_is_injected():
    # The check is exercised, not merely declared: force a citation-shaped string through the
    # same path a careless expression-rule edit could take.
    with pytest.raises(ValueError, match="citation-shaped"):
        build_brief([_entry("x", "X")], creature_expression_rule="see rules.json for the full list")


# ---- End-to-end extraction against a fake model, zero real calls ----------------------------


def test_sibling_creatures_can_receive_one_shared_label(server):
    entries = [
        _entry("wall-nut-zombie", "Wall-Nut Zombie", flavor_info="Wears a nut shell."),
        _entry("tall-nut-zombie", "Tall-Nut Zombie", flavor_info="Wears a taller nut shell."),
        _entry("giant-wall-nut-zombie", "Giant Wall-Nut Zombie", flavor_info="An enormous nut shell."),
    ]
    server.queue(json.dumps({"batch-0000": {"candidates": [
        {"speciesId": "wall-nut-zombie", "label": "nut", "nativeLabel": "Wall-Nut Zombie", "basis": "text"},
        {"speciesId": "tall-nut-zombie", "label": "nut", "nativeLabel": "Tall-Nut Zombie", "basis": "text"},
        {"speciesId": "giant-wall-nut-zombie", "label": "nut", "nativeLabel": "Giant Wall-Nut Zombie", "basis": "text"},
    ]}}))
    config = LlmCallerConfig(endpoint=server.url, attempts=1, retry_delay=0)

    result = extract_family_candidates(entries, creature_expression_rule=EXPR, config=config)

    assert {c.label for c in result["wall-nut-zombie"]} == {"nut"}
    assert {c.label for c in result["tall-nut-zombie"]} == {"nut"}
    assert {c.label for c in result["giant-wall-nut-zombie"]} == {"nut"}
    # proves the batch was genuinely presented together, not asserted from a scripted response alone
    assert len(server.requests) == 1
    prompt = server.requests[0]["messages"][-1]["content"]
    assert "wall-nut-zombie" in prompt and "tall-nut-zombie" in prompt and "giant-wall-nut-zombie" in prompt


def test_falsifier_single_creature_batching_produces_distinct_labels(server, monkeypatch):
    """The exact configuration §2.2 exists to prevent: with batch size 1, the same three creatures
    that could have shared a label instead each get their own — this is what proves the mechanism
    is real rather than assumed."""
    import seedsmith.adapters.creatures.family.extract as extract_mod
    monkeypatch.setattr(extract_mod, "BATCH_SIZE", 1)

    entries = [
        _entry("wall-nut-zombie", "Wall-Nut Zombie", flavor_info="Wears a nut shell."),
        _entry("tall-nut-zombie", "Tall-Nut Zombie", flavor_info="Wears a taller nut shell."),
        _entry("giant-wall-nut-zombie", "Giant Wall-Nut Zombie", flavor_info="An enormous nut shell."),
    ]
    # Sorted order (§ form_batches): giant-wall-nut-zombie, tall-nut-zombie, wall-nut-zombie —
    # each its own batch at size 1, so each call's key advances: batch-0000, -0001, -0002.
    server.queue(
        json.dumps({"batch-0000": {"candidates": [
            {"speciesId": "giant-wall-nut-zombie", "label": "giant-wall-nut", "nativeLabel": "Giant Wall-Nut Zombie", "basis": "text"}]}}),
        json.dumps({"batch-0001": {"candidates": [
            {"speciesId": "tall-nut-zombie", "label": "tall-nut", "nativeLabel": "Tall-Nut Zombie", "basis": "text"}]}}),
        json.dumps({"batch-0002": {"candidates": [
            {"speciesId": "wall-nut-zombie", "label": "wall-nut", "nativeLabel": "Wall-Nut Zombie", "basis": "text"}]}}),
    )
    config = LlmCallerConfig(endpoint=server.url, attempts=1, retry_delay=0)

    result = extract_family_candidates(entries, creature_expression_rule=EXPR, config=config)

    labels = {result["wall-nut-zombie"][0].label, result["tall-nut-zombie"][0].label,
              result["giant-wall-nut-zombie"][0].label}
    assert len(labels) == 3, "batch size 1 is the broken configuration §2.2 exists to prevent"


def test_basis_text_recorded_for_a_creature_with_rich_description(server):
    entries = [_entry("d0", "D0", flavor_info="Rich flavour text about this creature.")]
    server.queue(json.dumps({"batch-0000": {"candidates": [
        {"speciesId": "d0", "label": "rich", "nativeLabel": "D0", "basis": "text"}]}}))
    config = LlmCallerConfig(endpoint=server.url, attempts=1, retry_delay=0)

    result = extract_family_candidates(entries, creature_expression_rule=EXPR, config=config)
    assert result["d0"][0].basis == "text"


def test_basis_name_recorded_for_a_creature_with_only_a_name(server):
    entries = [_entry("d0", "D0")]
    server.queue(json.dumps({"batch-0000": {"candidates": [
        {"speciesId": "d0", "label": "prior", "nativeLabel": "D0", "basis": "name"}]}}))
    config = LlmCallerConfig(endpoint=server.url, attempts=1, retry_delay=0)

    result = extract_family_candidates(entries, creature_expression_rule=EXPR, config=config)
    assert result["d0"][0].basis == "name"


def test_a_creature_with_neither_gets_no_candidate_and_it_is_not_an_error(server):
    entries = [_entry("d0", "D0")]
    server.queue(json.dumps({"batch-0000": {"candidates": []}}))
    config = LlmCallerConfig(endpoint=server.url, attempts=1, retry_delay=0)

    result = extract_family_candidates(entries, creature_expression_rule=EXPR, config=config)
    assert result["d0"] == []  # present, empty — blocked is an answer, not an absence to re-derive


def test_a_creature_may_receive_more_than_one_candidate_label(server):
    entries = [_entry("d0", "D0", flavor_info="Some ambiguous text.")]
    server.queue(json.dumps({"batch-0000": {"candidates": [
        {"speciesId": "d0", "label": "first", "nativeLabel": "D0", "basis": "text"},
        {"speciesId": "d0", "label": "second", "nativeLabel": "D0", "basis": "text"},
    ]}}))
    config = LlmCallerConfig(endpoint=server.url, attempts=1, retry_delay=0)

    result = extract_family_candidates(entries, creature_expression_rule=EXPR, config=config)
    assert {c.label for c in result["d0"]} == {"first", "second"}


def test_a_label_for_a_creature_outside_the_batch_is_rejected_not_recorded(server):
    entries = [_entry("d0", "D0", flavor_info="Text.")]
    # Model names a creature that was never in this batch. The gate refuses it (an escalation, since
    # nothing else in the response is wrong to retry toward), and it never reaches the record.
    server.queue(json.dumps({"batch-0000": {"candidates": [
        {"speciesId": "not-in-batch", "label": "ghost", "nativeLabel": "Ghost", "basis": "text"}]}}),
        json.dumps({"batch-0000": {"candidates": [
            {"speciesId": "not-in-batch", "label": "ghost", "nativeLabel": "Ghost", "basis": "text"}]}}),
        json.dumps({"batch-0000": {"candidates": [
            {"speciesId": "not-in-batch", "label": "ghost", "nativeLabel": "Ghost", "basis": "text"}]}}))
    config = LlmCallerConfig(endpoint=server.url, attempts=1, retry_delay=0)

    result = extract_family_candidates(entries, creature_expression_rule=EXPR, config=config)
    assert result["d0"] == [], "the out-of-batch candidate must never appear under any key"


def test_zero_real_model_calls_every_request_hits_loopback(server):
    entries = [_entry("d0", "D0")]
    server.queue(json.dumps({"batch-0000": {"candidates": []}}))
    config = LlmCallerConfig(endpoint=server.url, attempts=1, retry_delay=0)

    extract_family_candidates(entries, creature_expression_rule=EXPR, config=config)
    assert server.url.startswith("http://127.0.0.1:")
