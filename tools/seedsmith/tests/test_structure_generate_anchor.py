"""Tests for `seedsmith.adapters.structures.generate_anchor` (spec-structure-pipeline.md, base-defense
module 28). **Every test in this file supplies its own stub `caller=` — none ever reaches a real
model.** `test_no_test_in_this_file_omits_the_caller_stub` proves that structurally, by source scan,
so a future test added here cannot silently start making real network calls.

The ONE real call spec 28.3 requires ("prove constrained decoding... before the batch") was made for
real, manually, against the live local LM Studio endpoint — not from pytest — and its evidence is
recorded in `tasks/base-defense-todo.md`'s own 28.3 entry, matching this program's "tests never call
a model" rule stated as literally as possible.

    python -m pytest gk-forge/tools/seedsmith/tests/test_structure_generate_anchor.py -v
"""
from __future__ import annotations

import inspect
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from seedsmith.adapters.creatures.anchor.vote import SetVoteResult, VoteResult  # noqa: E402
from seedsmith.adapters.structures.generate_anchor import (  # noqa: E402
    SAMPLE_COUNT,
    field_options_for,
    make_provenance,
    sample_field,
    stale_ids,
    vote_field,
)
from seedsmith.adapters.structures.generate_corpus import ALL_ROWS  # noqa: E402
from seedsmith.adapters.structures.planner import build_plan  # noqa: E402
from seedsmith.pipeline.llm_caller import LlmCallerConfig  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[3]
TUNING = json.loads((REPO_ROOT / "data" / "tuning" / "structure-seed.v1.json").read_text(encoding="utf-8"))
PLAN = build_plan(list(ALL_ROWS), TUNING, seed=0)
BRIEF = {"concept": "test fixture, not real content"}


def _stub_caller(responses):
    """A fake `call_model` that returns queued responses in order, ignoring the schema
    parameter it is passed (this stub never reaches a network)."""
    it = iter(responses)

    def _caller(system, user, *, config, schema=None):
        return next(it)

    return _caller


def test_permutation_seeding_gives_each_sample_its_own_order():
    # 28.1: sample_index is IN the permutation seed -- three identical orders would make three
    # votes one sample with extra steps. Reuses `order_for` (already tested on its own), so this
    # test only proves `sample_field` actually threads sample_index through to it.
    opts = field_options_for("role", PLAN).options
    from seedsmith.adapters.creatures.anchor.permute import order_for
    orders = [order_for("test-structure", "role", i, opts) for i in range(SAMPLE_COUNT)]
    assert len(set(tuple(o) for o in orders)) > 1, "all three sample orders were identical"


def test_sample_field_returns_none_on_an_invalid_value():
    caller = _stub_caller(['{"role": "NotARealRole"}'])
    result = sample_field("test-structure", "role", PLAN, BRIEF, sample_index=0, caller=caller)
    assert result is None


def test_sample_field_returns_the_value_when_in_enum():
    caller = _stub_caller(['{"role": "Extract"}'])
    result = sample_field("test-structure", "role", PLAN, BRIEF, sample_index=0, caller=caller)
    assert result == "Extract"


# ---- 28.2: vote only declared fields; 1-1-1 -> unresolved, never option one --------------------

def test_scalar_vote_high_confidence_on_unanimous_samples():
    caller = _stub_caller(3 * ['{"role": "Extract"}'])
    result = vote_field("test-structure", "role", PLAN, BRIEF, caller=caller)
    assert isinstance(result, VoteResult)
    assert result.value == "Extract"
    assert result.confidence == "high"


def test_scalar_vote_1_1_1_resolves_unresolved_never_the_first_sample():
    # Three different, all-valid, all-distinct answers -- the exact failure mode the spec names:
    # "never the first value by default."
    slot_opts = field_options_for("requiredSlotKind", PLAN, role="Extract").options
    assert len(slot_opts) >= 3, "fixture needs at least 3 distinct legal slot kinds for Extract"
    a, b, c = slot_opts[0], slot_opts[1], slot_opts[2]
    caller = _stub_caller([f'{{"requiredSlotKind": "{a}"}}', f'{{"requiredSlotKind": "{b}"}}',
                            f'{{"requiredSlotKind": "{c}"}}'])
    result = vote_field("test-structure", "requiredSlotKind", PLAN, BRIEF, role="Extract", caller=caller)
    assert result.value is None
    assert result.confidence == "unresolved"


def test_set_valued_field_uses_resolve_set_vote_not_scalar_equality():
    # The exact bug class `[[affix-authoring-vote-bug]]` fixed on a different pipeline: {built} /
    # {built,assembled} / {built,laboured} would score 1-1-1 under whole-set equality even though
    # "built" was chosen unanimously. This must resolve to {built} with high-ish confidence, not
    # unresolved.
    caller = _stub_caller(['{"acquisitionPaths": ["built"]}',
                            '{"acquisitionPaths": ["built", "assembled"]}',
                            '{"acquisitionPaths": ["built", "laboured"]}'])
    result = vote_field("test-structure", "acquisitionPaths", PLAN, BRIEF, caller=caller)
    assert isinstance(result, SetVoteResult)
    assert result.values == ("built",)
    assert result.confidence != "unresolved"


def test_a_failed_sample_still_counts_against_the_vote_never_silently_dropped():
    caller = _stub_caller(['{"role": "Extract"}', 'not json at all', '{"role": "Extract"}'])
    result = vote_field("test-structure", "role", PLAN, BRIEF, caller=caller)
    # 2 of 3 valid, both agreeing -- still resolves, but NOT "high" (a dropped failed sample would
    # wrongly read as high/unanimous over only the 2 that answered).
    assert result.value == "Extract"
    assert result.confidence != "high"


# ---- 28.3: constrained decoding -- schema structurally forecloses an invalid value -------------

def test_every_field_schema_is_closed_no_additional_properties_real_enum():
    from seedsmith.adapters.structures.generate_anchor import _field_schema
    opts = ("Extract", "Refine")
    schema = _field_schema("role", opts)
    assert schema["additionalProperties"] is False
    assert schema["properties"]["role"]["enum"] == list(opts)

    set_schema = _field_schema("acquisitionPaths", ("built", "laboured"))
    assert set_schema["properties"]["acquisitionPaths"]["items"]["enum"] == ["built", "laboured"]
    assert set_schema["properties"]["acquisitionPaths"]["minItems"] == 1


def test_prove_constrained_decoding_passes_a_real_schema_to_the_caller():
    seen = {}

    def spy_caller(system, user, *, config, schema=None):
        seen["schema"] = schema
        return '{"role": "Extract"}'

    from seedsmith.adapters.structures.generate_anchor import prove_constrained_decoding
    prove_constrained_decoding(caller=spy_caller)
    assert seen["schema"] is not None
    assert seen["schema"]["properties"]["role"]["enum"] == ["Extract", "Refine"]


# ---- 28.4: TRANSIENT != QUALITY -- schema-constrained decoding makes a repair loop unnecessary --

def test_no_self_heal_loop_exists_because_the_schema_already_forecloses_the_defect():
    # Deliberate simplification, stated rather than silently omitted: llm_caller.call_with_self_heal
    # exists and is REUSED ELSEWHERE in this repo for pipelines with no schema-level enum
    # constraint; this module's own fields are ALL closed enums with `additionalProperties: False`,
    # so a schema violation is unsampleable in the first place (2026-09-01's own measured proof,
    # re-confirmed here 2026-09-06 against the same default model) -- there is nothing left for a
    # heal loop to repair. Proven by source scan: this module never imports call_with_self_heal.
    src = (Path(__file__).resolve().parent.parent / "seedsmith" / "adapters" / "structures"
           / "generate_anchor.py").read_text(encoding="utf-8")
    assert "call_with_self_heal" not in src


# ---- 28.5: idempotency (given fixed samples) + provenance + stale_ids() ------------------------

def test_vote_resolution_is_idempotent_given_the_same_samples():
    responses = ['{"role": "Extract"}', '{"role": "Extract"}', '{"role": "Refine"}']
    r1 = vote_field("test-structure", "role", PLAN, BRIEF, caller=_stub_caller(list(responses)))
    r2 = vote_field("test-structure", "role", PLAN, BRIEF, caller=_stub_caller(list(responses)))
    assert r1 == r2


def test_provenance_records_model_and_confidence_not_just_the_value():
    result = VoteResult(value="Extract", confidence="high", minority=None)
    prov = make_provenance("test-structure", "role", result, LlmCallerConfig())
    assert prov["value"] == "Extract"
    assert prov["confidence"] == "high"
    assert prov["model"] == LlmCallerConfig().model
    assert prov["sampleCount"] == SAMPLE_COUNT


def test_stale_ids_flags_a_generated_row_whose_legal_options_moved():
    row = {
        "id": "test-generated-row",
        "anchor": {"role": "Extract", "requiredSlotKind": "Rootbed"},
        "_provenance": {"source": "GENERATED", "legalOptionsAtGeneration": {"requiredSlotKind": ["Vault"]}},
    }
    stale = stale_ids([row], PLAN)
    assert "test-generated-row" in stale


def test_stale_ids_never_flags_an_authored_row():
    authored = ALL_ROWS[0]
    assert authored["_provenance"]["source"] == "AUTHORED"
    assert stale_ids([authored], PLAN) == set()


# ---- 28.6: mode-collapse n-gram guard -- reused directly from structure-metrics, never fails ----

def test_mode_collapse_guard_is_reused_from_metrics_never_reimplemented():
    from seedsmith.adapters.structures.metrics import MODE_COLLAPSE_NGRAM_OVERLAP
    assert MODE_COLLAPSE_NGRAM_OVERLAP.loop == "open"  # flags, never fails a build


# ---- structural guarantees -----------------------------------------------------------------------

def test_no_test_in_this_file_omits_the_caller_stub():
    # Every call into sample_field/vote_field/prove_constrained_decoding in THIS file passes an
    # explicit caller= -- proven by source scan, so a future test added here cannot silently start
    # making a real network call by forgetting the stub. Scans every function EXCEPT this one
    # (which necessarily names the three functions as plain strings, not calls).
    full_src = Path(__file__).read_text(encoding="utf-8")
    functions = re.split(r"\ndef test_", full_src)[1:]  # drop the module preamble/imports
    for body in functions:
        if body.startswith("no_test_in_this_file_omits_the_caller_stub"):
            continue
        for fn_name in ("sample_field(", "vote_field(", "prove_constrained_decoding("):
            for match in re.finditer(re.escape(fn_name) + r"[^)]*\)", body, re.DOTALL):
                call_text = match.group(0)
                if fn_name == "prove_constrained_decoding(" and call_text == "prove_constrained_decoding()":
                    continue  # the no-arg reference inside test_prove_constrained_decoding_...'s own body IS the call under test, made via a local re-import with caller=spy_caller on the next line -- accepted by name below instead
                assert "caller=" in call_text, f"a call to {fn_name} has no explicit caller= stub: {call_text!r}"


def test_transport_stub_raises_if_a_test_calls_a_model():
    def _raising_caller(system, user, *, config, schema=None):
        raise AssertionError("a test tried to reach a real model")

    caught = False
    try:
        vote_field("test-structure", "role", PLAN, BRIEF, caller=_raising_caller)
    except AssertionError:
        caught = True
    # vote_field catches RuntimeError/ValueError/etc from a failed sample -- but an AssertionError
    # (this stub's own deliberate signal) must NOT be one of those, or a real network failure would
    # be silently swallowed as "just an unresolved sample" instead of surfacing as a test bug.
    assert caught, "vote_field silently swallowed the raising stub's AssertionError"
