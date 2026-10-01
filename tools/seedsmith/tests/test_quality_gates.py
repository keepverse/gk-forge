"""G3.1-G3.2 — deterministic validators and tier labelling (spec-quality-gates.md).

Every validator gets a POSITIVE and a NEGATIVE test. A rule that only rejects would pass its own
rejection test while quietly breaking real content — over-refusal is its own defect.
"""
from __future__ import annotations

import pytest
from seedsmith.workspace_roots import seed_root  # noqa: E402

from seedsmith.workflow.validators import (
    TIER,
    Tier,
    anti_motif_violation,
    field_echo,
    motif_coverage,
    non_empty,
    run_validators,
)

CTX = {"motifs": ["坚果", "外壳"], "antiMotifs": ["脆弱"],
       "requiredFields": ["name", "doctrine"]}


def test_motif_coverage_rejects_output_using_no_motif():
    assert motif_coverage({"doctrine": "A squad that advances."}, CTX)


def test_motif_coverage_accepts_output_using_one_motif():
    assert motif_coverage({"doctrine": "以坚果为盾。"}, CTX) == []


def test_motif_coverage_is_silent_when_the_subject_has_no_motifs():
    """A blocked creature has nothing to cover — that is an answer, not a defect."""
    assert motif_coverage({"doctrine": "anything"}, {"motifs": []}) == []


def test_anti_motif_violation_rejects_a_forbidden_word():
    defects = anti_motif_violation({"doctrine": "这支部队很脆弱。"}, CTX)
    assert len(defects) == 1 and "脆弱" in defects[0]


def test_anti_motif_violation_accepts_output_avoiding_them():
    assert anti_motif_violation({"doctrine": "以坚果为盾。"}, CTX) == []


def test_field_echo_rejects_the_observed_doctrine_prefix():
    """The exact defect: 7 of 8 real outputs began with the field name as a label."""
    defects = field_echo({"doctrine": "DOCTRINE: creates an impenetrable shell"}, CTX)
    assert len(defects) == 1 and "doctrine" in defects[0]


def test_field_echo_accepts_legitimate_prose_mentioning_the_field_name():
    """The guard against over-refusal. A rule rejecting ANY mention would pass the test above and
    silently break real writing — the separator distinguishes leakage from prose."""
    assert field_echo({"doctrine": "The doctrine of the shell wall."}, CTX) == []


def test_field_echo_catches_a_fullwidth_colon_too():
    assert field_echo({"name": "name：坚果"}, CTX)


def test_field_echo_ignores_non_string_values():
    assert field_echo({"count": 3}, CTX) == []


def test_non_empty_rejects_whitespace_only_required_field():
    defects = non_empty({"name": "   ", "doctrine": "ok"}, CTX)
    assert len(defects) == 1 and "name" in defects[0]


def test_non_empty_accepts_populated_fields():
    assert non_empty({"name": "坚果", "doctrine": "ok"}, CTX) == []


def test_defect_strings_name_the_field_and_the_offending_value():
    d = field_echo({"doctrine": "DOCTRINE: x"}, CTX)[0]
    assert "doctrine" in d and "DOCTRINE" in d
    a = anti_motif_violation({"doctrine": "脆弱"}, CTX)[0]
    assert "脆弱" in a


def test_every_validator_is_registered_as_tier_two():
    assert set(TIER.values()) == {Tier.DETERMINISTIC}
    for name in ("motif_coverage", "anti_motif_violation", "field_echo", "non_empty"):
        assert TIER[name] is Tier.DETERMINISTIC


def test_a_passing_result_says_mechanically_valid_never_good():
    """Measured 8/8 pass on visibly shoehorned content. The summary must never read as quality."""
    r = run_validators({"name": "坚果", "doctrine": "以坚果为盾。"},
                       CTX, [motif_coverage, anti_motif_violation, field_echo, non_empty])
    assert r.passed
    summary = r.summary()
    assert "mechanically valid" in summary
    assert "tier 2" in summary
    for forbidden in ("good", "quality", "high-quality"):
        assert forbidden not in summary.lower()


def test_a_failing_result_reports_defect_count_with_its_tier():
    r = run_validators({"doctrine": "DOCTRINE: 脆弱"}, CTX,
                       [motif_coverage, anti_motif_violation, field_echo, non_empty])
    assert not r.passed
    assert "tier 2" in r.summary()


# ---- name_collision — the residue subject_name_echo could not reach (added 2026-09-01) -----------


def test_name_collision_rejects_a_name_another_subject_already_uses():
    from seedsmith.workflow.validators import name_collision

    defects = name_collision({"name": "双重连射"}, {"takenNames": ["双重连射", "星芒轨迹"]})
    assert len(defects) == 1
    assert "双重连射" in defects[0], "the defect must name the offending value, or repair is guesswork"


# ---- the subject kind in a collision message (2026-09-27) --------------------------------------
#
# Both shared validators used to hardcode `commander effect` / `the creature's` in their message,
# while `subject_name_echo`'s only caller is the passive-tree node path — so every node refusal
# mislabelled what it was refusing. The noun is not cosmetic here: it is part of the failure-ledger
# text, and a 12.5 MB BCU2.12 ledger read as 984 distinct shapes partly because the noun was wrong.
# `adapters/dungeon/pipelines.py` already names the kind correctly at four sites, so this pins the
# shared primitive to the same convention and stops it drifting back.


def test_a_collision_message_names_the_kind_the_caller_declares():
    from seedsmith.workflow.validators import name_collision

    defects = name_collision({"name": "Primal Surge"},
                              {"takenNames": ["Primal Surge"], "subjectKind": "passive-tree node"})
    assert len(defects) == 1
    assert "already used by another passive-tree node" in defects[0]
    assert "commander effect" not in defects[0], (
        "a node refusal that calls itself a commander effect sends the operator to the wrong program")


def test_a_collision_message_is_neutral_when_the_caller_declares_no_kind():
    from seedsmith.workflow.validators import DEFAULT_SUBJECT_KIND, name_collision

    for context in ({"takenNames": ["Primal Surge"]}, {"takenNames": ["Primal Surge"],
                                                       "subjectKind": "   "}):
        defects = name_collision({"name": "Primal Surge"}, context)
        assert f"already used by another {DEFAULT_SUBJECT_KIND}" in defects[0]
        assert "commander effect" not in defects[0]


def test_subject_name_echo_names_the_kind_the_caller_declares():
    from seedsmith.workflow.validators import subject_name_echo

    defects = subject_name_echo({"name": "Cactus"}, {"displayName": "Cactus",
                                                     "subjectKind": "passive-tree node"})
    assert len(defects) == 1
    assert "give this passive-tree node its own distinct name" in defects[0]
    assert "the creature's" not in defects[0], (
        "subject_name_echo's only caller is the node path, so a creature is never the subject")


def test_the_validators_stay_pure_functions_of_draft_and_context():
    """`name_collision`'s own docstring claims this, so it is asserted rather than assumed."""
    from seedsmith.workflow.validators import name_collision

    draft, context = {"name": "Primal Surge"}, {"takenNames": ["Primal Surge"]}
    assert name_collision(draft, context) == name_collision(draft, dict(context))
    assert context == {"takenNames": ["Primal Surge"]}, "the validator must not mutate its context"


def test_name_collision_accepts_a_distinct_name():
    from seedsmith.workflow.validators import name_collision

    assert name_collision({"name": "双重射击律动"}, {"takenNames": ["双重连射"]}) == []


def test_name_collision_is_silent_with_no_taken_names():
    """The first subject of a fresh corpus has nothing to collide with — it must not be blocked."""
    from seedsmith.workflow.validators import name_collision

    assert name_collision({"name": "x"}, {}) == []
    assert name_collision({"name": "x"}, {"takenNames": []}) == []


def test_name_collision_does_not_fire_on_an_empty_draft_name():
    """`non_empty` owns the missing-name defect. Two validators reporting one problem produces two
    defect strings and a repair prompt that contradicts itself."""
    from seedsmith.workflow.validators import name_collision

    assert name_collision({"name": ""}, {"takenNames": ["a"]}) == []
    assert name_collision({}, {"takenNames": ["a"]}) == []


def test_name_collision_is_registered_as_a_commander_effect_validator():
    from seedsmith.adapters.creatures.commander_effect import VALIDATORS

    assert "name_collision" in [v.__name__ for v in VALIDATORS]


def test_every_committed_commander_effect_name_is_distinct():
    """⛔ Corpus-level regression. `SemanticDedup/NearDuplicate` reported 6 GAPs after
    `subject_name_echo` cut same-as-own-creature names from 83 to 6 — all sibling pairs
    (`doublecherry`/`doubleshooter`, `dollgold`/`dollsilver`, `pot`/`pumpkin`,
    `starfruit`/`starpea`, `jalapeno`/`jalastar`, `chomper`/`nutchomper`). Siblings share motifs, so
    the model converged on one name for both, and no per-draft validator could see it.

    Pinned here as well as in the metric because the metric is `gates=False` — a finding nobody is
    forced to look at is a finding that comes back."""
    import json
    from collections import Counter
    from pathlib import Path

    root = seed_root() / "creatures"
    entries = json.loads(
        (root / "commander-effect" / "all.json").read_text(encoding="utf-8"))["entries"]
    dupes = {n: c for n, c in Counter(e["name"] for e in entries).items() if c > 1}
    assert dupes == {}, f"commander-effect names collide: {dupes}"
    assert len({e["name"] for e in entries}) == len(entries)
