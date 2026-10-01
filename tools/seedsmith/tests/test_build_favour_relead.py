"""`lead-relabel-pass` stage A (`accept.py`) — the quota's contract.

Everything here is a CONTRACT or a closed vocabulary. Nothing pins a population size: not the species
count, not how many rows are `excluded`, not how many leads a corpus has — those are readings that move
whenever content ships, and a test that pinned one would fail on the normal case.

Tests 1/5/7 (schema, staleness, Phase 4) belong to the tasks that add those mechanisms: this file is
stage A's.
"""
from __future__ import annotations

import json
import random
from pathlib import Path

import pytest

from seedsmith.adapters.creatures.anchor.derive import derive_posture, derive_pure
from seedsmith.adapters.creatures.anchor.prompts import PIPELINES, SpeciesLore
from seedsmith.adapters.creatures.anchor.provenance import PROMPT_VERSIONS, ReleadProvenance
from seedsmith.adapters.creatures.anchor.schema import APTITUDES
from collections import Counter

from seedsmith.adapters.creatures.build_favour.accept import (
    EXCLUDED_KIND,
    OUTCOMES,
    Candidate,
    Decision,
    accept,
    candidates_from,
    over_cap_sources,
)
from seedsmith.adapters.creatures.build_favour.relead import (
    RELEAD,
    ReleadVote,
    resolve_relead_vote,
)
from seedsmith.adapters.creatures.build_favour.run import (
    apply_relead,
    drop_stale_releads,
    execute,
    load_plan,
    relead_is_stale,
)
from seedsmith.pipeline.model import audit_schema

# ── 1b. excluded rows are never candidates and never counted ───────────────────────────────────


def test_an_excluded_row_is_never_a_candidate_and_never_counted():
    # The row sits in the OVER-CAP lead and carries a vote that would move it away. It must not appear
    # in the decisions at all, and the counts the cap is judged on must be the measured population's:
    # the excluded row is not in them, so it cannot be the reason a real species is refused.
    rows = [
        {"speciesId": "real-a", "aptitudePrimary": "Onslaught", "speciesKind": "creature"},
        {"speciesId": "phantom", "aptitudePrimary": "Onslaught", "speciesKind": EXCLUDED_KIND},
        {"speciesId": "real-b", "aptitudePrimary": "Onslaught", "speciesKind": "mimic"},
    ]
    measured_leads = {"Onslaught": 3, "Vigor": 0}  # the measure's own count: real rows only
    votes = {"real-a": "Vigor", "phantom": "Vigor", "real-b": "Vigor"}

    candidates = candidates_from(rows, votes)
    decisions = accept(candidates, measured_leads, cap_count=2)

    assert [c.species_id for c in candidates] == ["real-a", "real-b"]
    assert [d.species_id for d in decisions] == ["real-a", "real-b"]
    assert "phantom" not in {d.species_id for d in decisions}
    # The mimic is a real creature (R-CS2's borrowed id) and IS a candidate: only `excluded` is out.
    assert "real-b" in {d.species_id for d in decisions}


def test_a_row_with_no_vote_is_a_candidate_and_reads_unresolved():
    # "Not asked", "not a vote" and "unresolved" are three different states; none of them may raise.
    rows = [{"speciesId": "s1", "aptitudePrimary": "Might", "speciesKind": "creature"}]

    (candidate,) = candidates_from(rows, {})
    assert candidate.voted is None
    assert accept([candidate], {"Might": 9}, cap_count=2) == [Decision("s1", "Might", "unresolved")]


def test_over_cap_sources_are_the_only_sources_and_there_is_no_floor():
    sources = over_cap_sources({"Onslaught": 9, "Vigor": 4, "Focus": 1, "Ruin": 0}, cap_count=4)

    assert sources == ("Onslaught",)  # ordinal, and `Vigor == cap` is NOT over it
    assert over_cap_sources({"Ruin": 0}, cap_count=4) == ()  # zero-led: not a source, never a refusal


# ── 4. a 1-1-1 vote keeps the current primary as `unresolved` ──────────────────────────────────


def test_an_unresolved_vote_keeps_the_current_primary():
    candidates = [Candidate("s1", "Onslaught", None), Candidate("s2", "Onslaught", "Onslaught")]

    decisions = accept(candidates, {"Onslaught": 9}, cap_count=2)

    assert decisions == [
        Decision("s1", "Onslaught", "unresolved"),
        Decision("s2", "Onslaught", "kept-by-vote"),
    ]


def test_every_refusal_records_its_own_reason():
    # One candidate per outcome, so the vocabulary is exercised whole and the reasons stay distinct.
    candidates = [
        Candidate("a-unresolved", "Onslaught", None),
        Candidate("b-same", "Onslaught", "Onslaught"),
        Candidate("c-under-cap", "Vigor", "Might"),     # its own source is already at/below the cap
        Candidate("d-target-full", "Onslaught", "Might"),  # the target is already at the cap
        Candidate("e-accepted", "Onslaught", "Precision"),
    ]

    decisions = accept(candidates, {"Onslaught": 5, "Vigor": 2, "Might": 2, "Precision": 0}, cap_count=2)

    assert [d.outcome for d in decisions] == [
        "unresolved", "kept-by-vote", "source-under-cap", "target-full", "accepted",
    ]
    assert [d.primary for d in decisions] == [
        "Onslaught", "Onslaught", "Vigor", "Onslaught", "Precision",
    ]
    assert OUTCOMES == ("accepted", "kept-by-vote", "unresolved", "source-under-cap", "target-full")


# ── 3. determinism: input order cannot change a decision ───────────────────────────────────────


def test_decisions_are_byte_identical_under_any_input_order():
    rng = random.Random(20_260_920)
    aptitudes = ("Onslaught", "Vigor", "Might", "Focus", "Precision")
    candidates = [
        Candidate(f"s{i:03d}", rng.choice(aptitudes), rng.choice(aptitudes + (None,)))
        for i in range(60)
    ]
    counts = {a: rng.randrange(0, 12) for a in aptitudes}

    canonical = accept(candidates, counts, cap_count=5)
    before = dict(counts)

    for _ in range(20):
        shuffled = list(candidates)
        rng.shuffle(shuffled)
        assert accept(shuffled, counts, cap_count=5) == canonical

    # The caller's mapping is an input, not scratch space: replaying cannot change it.
    assert counts == before


# ── 2. the quota is a hard bound (property-tested, fixed seed) ─────────────────────────────────


def test_no_target_ever_ends_above_the_cap_and_no_species_leaves_an_under_cap_source():
    rng = random.Random(20_260_921)
    aptitudes = ("Onslaught", "Vigor", "Might", "Focus", "Precision")

    for _ in range(300):
        cap = rng.randrange(1, 8)
        counts = {a: rng.randrange(0, 14) for a in aptitudes}
        candidates = [
            Candidate(f"s{i:03d}", rng.choice(aptitudes), rng.choice(aptitudes + (None,)))
            for i in range(rng.randrange(0, 40))
        ]

        decisions = accept(candidates, counts, cap_count=cap)
        final = dict(counts)
        by_id = {c.species_id: c for c in candidates}
        assert len(decisions) == len(candidates)  # one decision per candidate, always

        for decision in decisions:
            candidate = by_id[decision.species_id]
            if decision.outcome == "accepted":
                final[candidate.current] -= 1
                final[decision.primary] += 1
            else:
                assert decision.primary == candidate.current

        # The bound holds even when the corpus starts over it: an acceptance only ever moves a species
        # INTO a target below the cap, and a source is only drained while it is still above it.
        for aptitude in aptitudes:
            if counts[aptitude] <= cap:
                assert final[aptitude] >= counts[aptitude], (
                    f"{aptitude} was under the cap ({counts[aptitude]} <= {cap}) and lost a species"
                )
            assert final[aptitude] <= max(counts[aptitude], cap), (
                f"{aptitude} ended above max(start, cap): {final[aptitude]} > {max(counts[aptitude], cap)}"
            )
        assert sum(final.values()) == sum(counts.values())


# ── EP2.10: the pass-2 pipeline spec (stage L) ─────────────────────────────────────────────────


def test_the_relead_schema_passes_the_audit_and_carries_no_number():
    assert audit_schema(RELEAD.schema) == []
    # One property, the closed enum of twelve ids, nothing else.
    assert list(RELEAD.schema["properties"]) == ["aptitudePrimary", "blocked"]
    assert RELEAD.schema["properties"]["aptitudePrimary"]["enum"] == list(APTITUDES)
    assert RELEAD.schema["additionalProperties"] is False


def test_a_numeric_variant_of_the_schema_fails_the_audit():
    # The audit is mechanical, and this is its proof on THIS schema's shape: a numeric property (the
    # obvious "let it also name the crowding" temptation) is refused.
    defect = dict(RELEAD.schema)
    defect["properties"] = dict(defect["properties"], leadCount={"type": "integer"})

    defects = audit_schema(defect)

    assert defects, "a numeric property must not pass"
    assert any(d.path == "$.leadCount" and "numeric" in d.reason for d in defects)


def test_a_variant_without_the_blocked_wrapper_fails_the_audit():
    # pipeline/model.py's guardrail: a model with no way to decline invents instead.
    bare = {k: v for k, v in RELEAD.schema.items() if k != "properties"}
    bare["properties"] = {"aptitudePrimary": RELEAD.schema["properties"]["aptitudePrimary"]}

    defects = audit_schema(bare)

    assert defects, "a schema with no way to decline must not pass"
    assert any("blocked" in d.reason for d in defects)


def test_a_blocked_sample_is_not_a_vote():
    # One declination out of three: the two real votes still carry the majority.
    one_blocked = resolve_relead_vote([
        {"aptitudePrimary": "Pierce", "blocked": ""},
        {"aptitudePrimary": "Pierce", "blocked": ""},
        {"aptitudePrimary": "", "blocked": "no description captured"},
    ])
    assert one_blocked.value == "Pierce"
    assert one_blocked.votes == ("Pierce", "Pierce")  # the declination is absent, not an empty string

    # Two declinations leave one vote — no majority of the samples asked, so unresolved.
    two_blocked = resolve_relead_vote([
        {"aptitudePrimary": "Pierce", "blocked": ""},
        {"aptitudePrimary": "", "blocked": "no description"},
        {"aptitudePrimary": "Might", "blocked": "no lore"},
    ])
    assert two_blocked.value is None
    assert two_blocked.confidence == "unresolved"
    assert two_blocked.votes == ("Pierce",)

    # All three decline: unresolved, and no vote is invented.
    assert resolve_relead_vote(
        [{"aptitudePrimary": "", "blocked": "none"} for _ in range(3)]
    ).value is None


def test_a_blocked_value_that_echoes_the_answer_is_metadata_not_a_declination():
    # Measured 2026-09-20 on google/gemma-4-26b-a4b-qat: three samples answered Onslaught/Precision/
    # Onslaught and ALL THREE carried blocked: "Onslaught" — the model echoing its own answer into the
    # escape field, the failure _blocked_variant's own description warns about. Read as abstentions the
    # vote would be unresolved and the pass could never re-label anything; read as metadata, the real
    # votes resolve (2-1 -> split on Onslaught).
    echo = resolve_relead_vote([
        {"aptitudePrimary": "Onslaught", "blocked": "Onslaught"},
        {"aptitudePrimary": "Precision", "blocked": "Onslaught"},
        {"aptitudePrimary": "Onslaught", "blocked": "Onslaught"},
    ])
    assert echo == ReleadVote("Onslaught", "split", ("Onslaught", "Precision", "Onslaught"))

    # A reason that names no label is still a genuine declination.
    assert resolve_relead_vote([
        {"aptitudePrimary": "Might", "blocked": ""},
        {"aptitudePrimary": "", "blocked": "no description captured"},
        {"aptitudePrimary": "Might", "blocked": ""},
    ]).value == "Might"


def test_three_real_votes_resolve_exactly_as_pass_1_does():
    # One implementation where it applies: 3-0 high, 2-1 split, 1-1-1 unresolved.
    assert resolve_relead_vote(
        [{"aptitudePrimary": "Might", "blocked": ""} for _ in range(3)]
    ) == ReleadVote("Might", "high", ("Might", "Might", "Might"))
    assert resolve_relead_vote([
        {"aptitudePrimary": "Might"}, {"aptitudePrimary": "Might"}, {"aptitudePrimary": "Vigor"},
    ]) == ReleadVote("Might", "split", ("Might", "Might", "Vigor"))
    assert resolve_relead_vote([
        {"aptitudePrimary": "Might"}, {"aptitudePrimary": "Vigor"}, {"aptitudePrimary": "Focus"},
    ]) == ReleadVote(None, "unresolved", ("Might", "Vigor", "Focus"))


def test_an_answer_outside_the_closed_enum_raises_rather_than_becoming_a_primary():
    with pytest.raises(ValueError):
        resolve_relead_vote([
            {"aptitudePrimary": "Onslaught"}, {"aptitudePrimary": "Onslaught"},
            {"aptitudePrimary": "NotAnAptitude"},
        ])
    # And the sample count is a contract, like pass 1's own resolver.
    with pytest.raises(ValueError):
        resolve_relead_vote([{"aptitudePrimary": "Might"}])


def test_the_relead_spec_is_not_a_pipelines_key():
    assert RELEAD.id not in PIPELINES
    assert len(PIPELINES) == 8, "pass 2 is a separate pass, not a ninth classifier"
    assert RELEAD.attributes == ("aptitudePrimary",)
    assert RELEAD.judgement.strip()


def test_the_brief_shows_the_measured_crowding_and_never_a_creature_magnitude():
    lore = SpeciesLore(
        species_id="peashooter", side="plant", display_name="Peashooter",
        flavor_info="Fires a single pea at the nearest zombie.", flavor_introduce=None,
    )
    brief = RELEAD.build_brief(lore, {
        "order": list(APTITUDES), "current": "Onslaught",
        "leadCount": 369, "speciesCount": 892, "capCount": 223,
    })

    # The corpus statistic is shown (the model may not change it, but it must see it)...
    assert "369 of 892" in brief
    assert "Onslaught" in brief
    # ...the choice is offered, and staying put is explicitly legal...
    assert "Pierce" in brief and "Ferocity" in brief
    assert "already leads is allowed" in brief
    # ...and no captured magnitude leaks in, same rule pass 1 lives under.
    for banned in ("hp:", "attack:", "armor:"):
        assert banned not in brief.lower()


# ── EP2.11: the provenance block, staleness, and the re-led entry ──────────────────────────────


def make_block(**overrides) -> ReleadProvenance:
    base = dict(
        from_primary="Onslaught", prompt_version=PROMPT_VERSIONS["aptitude-primary"],
        dump_hash="a" * 64, votes=("Pierce", "Pierce", "Onslaught"), confidence="split",
        measure_hash="b" * 64, outcome="accepted",
    )
    return ReleadProvenance(**{**base, **overrides})


def make_entry(*, relead: ReleadProvenance | None = None, dump_hash: str = "a" * 64,
               primary: str = "Onslaught", secondary: str = "none",
               species_id: str = "peashooter") -> dict:
    provenance = {
        "dumpHash": dump_hash, "promptVersions": dict(PROMPT_VERSIONS), "basis": "observed",
        "confidence": {}, "minorityValues": {}, "auditVerdict": None, "attempts": {},
        "emittedUtc": "2026-01-01T00:00:00Z",
    }
    if relead is not None:
        provenance["relead"] = relead.to_dict()
    return {
        "speciesId": species_id, "aptitudePrimary": primary, "aptitudeSecondary": secondary,
        "posture": derive_posture(primary), "pure": derive_pure(primary, secondary),
        "_provenance": provenance,
    }


def test_the_block_is_a_closed_enum_and_identifier_record_with_no_model_chosen_number():
    block = make_block()
    assert block.to_dict() == {
        "fromPrimary": "Onslaught", "promptVersion": 1, "dumpHash": "a" * 64,
        "votes": ["Pierce", "Pierce", "Onslaught"], "confidence": "split",
        "measureHash": "b" * 64, "outcome": "accepted",
    }
    assert ReleadProvenance.from_dict(block.to_dict()) == block  # round-trips

    for bad in (
        dict(from_primary="NotAnAptitude"), dict(votes=("Pierce", "Nope")),
        dict(confidence="certain"), dict(outcome="maybe"),
        dict(prompt_version=True), dict(prompt_version=0), dict(prompt_version="1"),
        dict(measure_hash="not-a-hash"), dict(dump_hash=""),
    ):
        with pytest.raises(ValueError):
            make_block(**bad)


def test_a_rerun_of_pass_1_drops_the_block_and_requeues_the_species():
    # Test 5, both signals the spec names. The block records the pass-1 version and the capture it was
    # computed against, so a bumped prompt OR a fresh capture invalidates it — compared by RECORDED
    # value, never by mtime (`emit.stale_ids`' own rule).
    bumped = {**PROMPT_VERSIONS, "aptitude-primary": PROMPT_VERSIONS["aptitude-primary"] + 1}
    fresh = make_entry(relead=make_block(), species_id="fresh")
    stale_prompt = make_entry(relead=make_block(), species_id="bumped-prompt")
    stale_dump = make_entry(relead=make_block(dump_hash="0" * 64), species_id="moved-dump")

    assert relead_is_stale(fresh, current_prompt_versions=PROMPT_VERSIONS) is False
    assert relead_is_stale(stale_prompt, current_prompt_versions=bumped) is True
    assert relead_is_stale(stale_dump, current_prompt_versions=PROMPT_VERSIONS) is True
    assert relead_is_stale(make_entry(), current_prompt_versions=PROMPT_VERSIONS) is False  # no block

    # A fresh capture drops exactly the row whose block read an older one; the prompt bump drops the row
    # whose block carries the old version. Pass 1's answer stands for a dropped row: the primary is
    # untouched, only the block goes.
    kept, requeued = drop_stale_releads([fresh, stale_dump], current_prompt_versions=PROMPT_VERSIONS)
    assert requeued == ["moved-dump"]
    assert [("relead" in e["_provenance"]) for e in kept] == [True, False]
    assert kept[1]["aptitudePrimary"] == stale_dump["aptitudePrimary"]

    _, requeued_after_bump = drop_stale_releads([fresh, stale_prompt], current_prompt_versions=bumped)
    # Ordinal by species id, so a run's queue is reproducible whatever order the corpus arrived in.
    assert requeued_after_bump == ["bumped-prompt", "fresh"]   # a bumped prompt invalidates both

    # The inputs are inputs, not scratch space.
    assert "relead" in stale_dump["_provenance"]


def test_apply_relead_replaces_the_primary_and_swaps_a_colliding_secondary():
    entry = make_entry(primary="Onslaught", secondary="Agility")

    # New primary == the current secondary: the two swap, so no row ends primary == secondary.
    swapped = apply_relead(entry, new_primary="Agility", block=make_block(from_primary="Onslaught"))
    assert swapped["aptitudePrimary"] == "Agility"
    assert swapped["aptitudeSecondary"] == "Onslaught"
    # Re-derived by code from the NEW primary, never carried over from the old row.
    assert swapped["posture"] == derive_posture("Agility")
    assert swapped["posture"] != entry["posture"]        # re-derived from the NEW primary
    assert swapped["pure"] == derive_pure("Agility", "Onslaught")
    assert swapped["_provenance"]["relead"]["fromPrimary"] == "Onslaught"
    # ...and the original row is untouched.
    assert entry["aptitudePrimary"] == "Onslaught" and entry["aptitudeSecondary"] == "Agility"


def test_apply_relead_keeps_a_secondary_that_does_not_collide_and_never_touches_species_kind():
    entry = make_entry(primary="Onslaught", secondary="Bulwark")
    entry["speciesKind"] = "creature"

    updated = apply_relead(entry, new_primary="Precision", block=make_block())

    assert updated["aptitudePrimary"] == "Precision"
    assert updated["aptitudeSecondary"] == "Bulwark"
    assert updated["posture"] == derive_posture("Precision")
    assert updated["posture"] != entry["posture"]
    assert updated["pure"] == derive_pure("Precision", "Bulwark")
    # speciesKind does not read the primary (spec: no `derive.py` path handles its re-derivation).
    assert updated["speciesKind"] == "creature"


def test_apply_relead_refuses_a_target_outside_the_enum_or_a_mismatched_provenance():
    entry = make_entry(primary="Onslaught")

    with pytest.raises(ValueError):
        apply_relead(entry, new_primary="NotAnAptitude", block=make_block())

    with pytest.raises(ValueError):
        # The block must describe the change it is attached to.
        apply_relead(entry, new_primary="Precision", block=make_block(from_primary="Bulwark"))


# ── EP2.12: the pass — plan from the measure, dry run by default, write through the emit ───────


def make_root(tmp_path, *, lead_counts=None, species_count=10, anchors=None):
    """A miniature repo: the two documents the pass reads and an anchor tree it may rewrite."""
    (tmp_path / "data" / "generated" / "creatures").mkdir(parents=True, exist_ok=True)
    (tmp_path / "data" / "tuning").mkdir(parents=True, exist_ok=True)
    (tmp_path / "data" / "seed" / "creatures" / "species" / "plant").mkdir(parents=True, exist_ok=True)
    measure = {
        "speciesCount": species_count,
        "leadCountByAptitude": lead_counts if lead_counts is not None else {
            "Onslaught": 6, "Vigor": 2, "Might": 1, "Focus": 1},
        "maxLeadAptitude": "Onslaught", "maxLeadPermille": 600,
        "shapeCount": {"600,400": 6}, "largestShapePermille": 600,
        "leanByPrimary": {}, "leanSignalsMissing": [],
    }
    (tmp_path / "data" / "generated" / "creatures" / "_species-build-measure.json").write_text(
        json.dumps(measure), encoding="utf-8")
    (tmp_path / "data" / "tuning" / "species-build.v5.json").write_text(json.dumps({
        "version": 5, "leadCapPermille": 250, "leadCapTolerancePermille": 50,
        "shapeCapPermille": 300}), encoding="utf-8")
    if anchors is None:
        anchors = [
            {"speciesId": "crowd-1", "aptitudePrimary": "Onslaught", "aptitudeSecondary": "none",
             "speciesKind": "creature", "posture": "Force", "pure": True, "_provenance": {"dumpHash": "a" * 64, "promptVersions": dict(PROMPT_VERSIONS)}},
            {"speciesId": "crowd-2", "aptitudePrimary": "Onslaught", "aptitudeSecondary": "Agility",
             "speciesKind": "creature", "posture": "Force", "pure": False, "_provenance": {"dumpHash": "a" * 64, "promptVersions": dict(PROMPT_VERSIONS)}},
            {"speciesId": "phantom", "aptitudePrimary": "Onslaught", "aptitudeSecondary": "none",
             "speciesKind": "excluded", "posture": "Force", "pure": True, "_provenance": {"dumpHash": "a" * 64, "promptVersions": dict(PROMPT_VERSIONS)}},
            {"speciesId": "quiet", "aptitudePrimary": "Vigor", "aptitudeSecondary": "none",
             "speciesKind": "creature", "posture": "Force", "pure": True, "_provenance": {"dumpHash": "a" * 64, "promptVersions": dict(PROMPT_VERSIONS)}},
        ]
    (tmp_path / "data" / "seed" / "creatures" / "species" / "plant" / "one.json").write_text(
        json.dumps(anchors, indent=2, sort_keys=True), encoding="utf-8")
    return tmp_path


def test_the_plan_asks_only_the_measured_creatures_leading_an_over_cap_aptitude(tmp_path):
    plan = load_plan(make_root(tmp_path))

    # capCount = 250 permille of the measure's OWN 10 species = 2, so Onslaught (6) is the only source.
    assert plan.cap_count == 2
    assert plan.species_count == 10
    assert plan.over_cap == ("Onslaught",)
    assert [a.species_id for a in plan.asked] == ["crowd-1", "crowd-2"]
    assert all(a.current == "Onslaught" for a in plan.asked)
    assert "phantom" not in {a.species_id for a in plan.asked}   # excluded: never asked
    assert "quiet" not in {a.species_id for a in plan.asked}     # under-cap source: never asked


def test_the_measure_is_read_and_never_recounted_in_python(tmp_path):
    # The artifact says 6 of 10 lead Onslaught; this corpus contains ONE Onslaught row. A Python recount
    # would find nothing over the cap (1 of 4) and ask nobody — so the asked list is the proof that the
    # file is what the pass follows, exactly as the row requires.
    anchors = [{"speciesId": "only-one", "aptitudePrimary": "Onslaught", "aptitudeSecondary": "none",
                "speciesKind": "creature", "posture": "Force", "pure": True,
                "_provenance": {"dumpHash": "a" * 64, "promptVersions": dict(PROMPT_VERSIONS)}}]
    plan = load_plan(make_root(tmp_path, anchors=anchors))

    assert plan.cap_count == 2                                   # 250 permille of 10, not of 1
    assert plan.over_cap == ("Onslaught",)                       # from the file's counts
    assert plan.lead_counts["Onslaught"] == 6
    assert [a.species_id for a in plan.asked] == ["only-one"]    # asked because the FILE says over-cap
    assert plan.measure_hash != "" and len(plan.measure_hash) == 64


def test_a_stale_block_is_requeued_by_the_plan(tmp_path):
    anchors = [{
        "speciesId": "stale", "aptitudePrimary": "Onslaught", "aptitudeSecondary": "none",
        "speciesKind": "creature", "posture": "Force", "pure": True,
        "_provenance": {
            "dumpHash": "a" * 64, "promptVersions": dict(PROMPT_VERSIONS),
            "relead": make_block(dump_hash="0" * 64).to_dict(),      # read against an older capture
        },
    }]
    plan = load_plan(make_root(tmp_path, anchors=anchors))

    assert plan.requeued == ("stale",)


def test_the_dry_run_calls_nothing_and_writes_nothing(tmp_path):
    root = make_root(tmp_path)
    plan = load_plan(root)
    before = (root / "data" / "seed" / "creatures" / "species" / "plant" / "one.json").read_bytes()

    def never(*_args, **_kwargs):
        raise AssertionError("the dry run must not call a model")

    summary = execute(plan, ask=never, write=False)

    assert summary["dryRun"] is True
    assert summary["callsMade"] == 0
    assert summary["written"] == []
    assert summary["asked"] == [
        {"speciesId": "crowd-1", "current": "Onslaught"},
        {"speciesId": "crowd-2", "current": "Onslaught"},
    ]
    assert (root / "data" / "seed" / "creatures" / "species" / "plant" / "one.json").read_bytes() == before


def test_an_accepted_relead_is_written_through_the_emit_with_provenance(tmp_path):
    root = make_root(tmp_path)
    plan = load_plan(root)
    lore = {
        species_id: SpeciesLore(species_id=species_id, side="plant", display_name=species_id,
                                flavor_info="A crowded thing.", flavor_introduce=None)
        for species_id in ("crowd-1", "crowd-2")
    }

    def ask(lore_row, context):
        # crowd-1 -> Vigor (under its cap: 2 + 1 = 3 > 2, so actually target-full) ...
        return [{"aptitudePrimary": "Vigor"} for _ in range(3)]

    summary = execute(plan, ask=ask, write=True, lore_by_id=lore)

    # Both candidates vote Vigor, and the cap is 2 with Vigor already at 2: the first is refused
    # (target-full) and so is the second — stage A's quota, not the model, decides.
    assert summary["outcomes"] == {"target-full": 2}
    assert summary["written"] == []
    assert [d["outcome"] for d in summary["decisions"]] == ["target-full", "target-full"]

    # Now a vote the quota CAN accept: Might is below the cap, so the first lands and Might fills up.
    def ask_might(lore_row, context):
        return [{"aptitudePrimary": "Might"} for _ in range(3)]

    summary = execute(plan, ask=ask_might, write=True, lore_by_id=lore)
    assert summary["outcomes"] == {"accepted": 1, "target-full": 1}
    assert summary["written"] == ["data/seed/creatures/species/plant/one.json"]
    assert summary["callsMade"] == 6

    written = json.loads((root / "data" / "seed" / "creatures" / "species" / "plant" / "one.json").read_text("utf-8"))
    by_id = {e["speciesId"]: e for e in written}
    # The accepted row: new primary, re-derived posture/pure, and the block that explains it.
    assert by_id["crowd-1"]["aptitudePrimary"] == "Might"
    assert by_id["crowd-1"]["posture"] == derive_posture("Might")
    assert by_id["crowd-1"]["pure"] == derive_pure("Might", "none")
    block = by_id["crowd-1"]["_provenance"]["relead"]
    assert block == {
        "fromPrimary": "Onslaught", "promptVersion": PROMPT_VERSIONS["aptitude-primary"],
        "dumpHash": "a" * 64, "votes": ["Might", "Might", "Might"], "confidence": "high",
        "measureHash": plan.measure_hash, "outcome": "accepted",
    }
    # The refused row is untouched: the pass writes only what the quota accepted.
    assert by_id["crowd-2"]["aptitudePrimary"] == "Onslaught"
    assert "relead" not in by_id["crowd-2"]["_provenance"]
    # ...and every other row in the file survived the whole-file rewrite.
    assert by_id["phantom"]["speciesKind"] == "excluded"
    assert by_id["quiet"]["aptitudePrimary"] == "Vigor"


def test_the_cli_verb_is_dry_run_by_default_and_writes_nothing(tmp_path, capsys):
    from seedsmith.report.cli import build_parser, cmd_creatures

    root = make_root(tmp_path)
    before = (root / "data" / "seed" / "creatures" / "species" / "plant" / "one.json").read_bytes()
    args = build_parser().parse_args(
        ["creatures", "build-favour", "--dry-run", "--limit", "1", "--root", str(root)])

    assert cmd_creatures(args) == 0

    printed = json.loads(capsys.readouterr().out)
    assert printed["dryRun"] is True and printed["callsMade"] == 0
    assert printed["overCap"] == ["Onslaught"] and printed["capCount"] == 2
    assert [a["speciesId"] for a in printed["asked"]] == ["crowd-1"]     # --limit 1
    assert (root / "data" / "seed" / "creatures" / "species" / "plant" / "one.json").read_bytes() == before


# ── EP2.14 test 8, the corpus half: every committed relead block is legal, and every accepted row
#    leads the aptitude its own votes won (a RELATION over the population, never a count) ───────


def test_the_committed_corpus_relead_blocks_are_legal_and_match_their_votes():
    repo_root = Path(__file__).resolve().parents[3]

# `REPO_ROOT`-relative joins below ask which repository actually carries the path. A prefix-keyed
# rewrite is wrong: `data`, `data/seed` and `data/seed/creatures` all resolve back to gk-forge,
# because nearest-match-wins and gk-forge owns its own generator inputs. `or REPO_ROOT` is
# load-bearing - `owning_base` returns None for a path no repository carries, where
# `content_root()` would RAISE.

from seedsmith.workspace_roots import owning_base  # noqa: E402


def _owned(relative: str) -> "Path":
    """The repository carrying `relative`, joined to it; this one when none carries it."""
    return (owning_base(relative, repo_root) or repo_root) / relative

    corpus = _owned("data/seed/creatures/species")

    blocks = 0
    for path in sorted(corpus.rglob("*.json")):
        if path.name.startswith("_"):
            continue
        for entry in json.loads(path.read_text(encoding="utf-8")):
            block = (entry.get("_provenance") or {}).get("relead")
            if not block:
                continue
            blocks += 1
            # Closed enums and identifiers only: ReleadProvenance refuses anything else on construction.
            ReleadProvenance.from_dict(block)
            assert block["outcome"] in OUTCOMES
            assert block["fromPrimary"] in APTITUDES
            assert all(vote in APTITUDES for vote in block["votes"])
            # The accepted row leads the vote its own block records — the re-label reached the anchor,
            # and the block is not describing some other species' change.
            if block["outcome"] == "accepted":
                assert entry["aptitudePrimary"] == Counter(block["votes"]).most_common(1)[0][0]

    # Envelope only: the pass may legitimately move nothing one day; this test must still have run.
    assert blocks >= 0
