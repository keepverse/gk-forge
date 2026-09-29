"""P6 — briefkit. Acceptance quoted from `tasks/seedsmith-plan.md` Phase 3:

1. "A brief for a real still-open partition (`gems/2`) inlines the literal legal `family` vocabulary
   read from the registry at brief-generation time — grep the brief text for a citation string like
   'see tags.v1.json' and fail if found"
2. "Two brief generations from byte-identical inputs produce the identical content hash (no
   wall-clock/random baked in)"
3. "A brief whose exemplar failed P3's gate is never emitted"
"""
from __future__ import annotations

import pytest

from seedsmith.briefkit import Brief, BriefRefusal, render_brief, render_briefs
from seedsmith.planner.schedule import Job
from seedsmith.planner.validate import ExemplarGateResult

GEM_FAMILIES = ("ruby", "sapphire", "emerald", "onyx", "topaz")


def _gems_job() -> Job:
    return Job(
        partition="gems/2", kind="gem", entries=6,
        brief="briefs/gems_2.md", model="opus",
        constraints={"band": "b", "powerBand": "3"},
        closes=("Coverage/EmptyPartition:gems/2",),
    )


def _brief(**kw) -> Brief:
    return render_brief(_gems_job(), vocabularies={"family": GEM_FAMILIES}, **kw)


# ---- Criterion 1: inlined literally, never cited ------------------------------------------------


def test_the_legal_family_vocabulary_is_written_out_in_full():
    brief = _brief()

    for family in GEM_FAMILIES:
        assert family in brief.text
    assert "5 legal values" in brief.text


def test_the_brief_contains_no_citation_string():
    """The literal grep the criterion asks for. An agent cannot follow a filename, so a citation is
    an invitation to invent — 51 tags, historically."""
    brief = _brief()
    lowered = brief.text.lower()

    for needle in ("see tags.v1.json", ".json", ".v1", "consult", "look it up", "as documented in"):
        assert needle not in lowered, f"brief cites {needle!r} instead of inlining it"


def test_a_brief_that_would_cite_a_registry_file_is_refused_not_emitted():
    """The rule has a check behind it, not a convention. Planted via a constraint value, which is
    caller-supplied text and therefore the realistic way a citation sneaks in."""
    job = Job(
        partition="gems/2", kind="gem", entries=6, brief="b.md", model="opus",
        constraints={"family": "see gems.v1.json for the list"},
        closes=(),
    )

    with pytest.raises(BriefRefusal, match="cites"):
        render_brief(job, vocabularies={"family": GEM_FAMILIES})


def test_the_refusal_explains_why_rather_than_just_refusing():
    job = Job(partition="p", kind="gem", entries=1, brief="b.md", model="opus",
              constraints={"note": "values are defined in tags.v1.json"}, closes=())

    with pytest.raises(BriefRefusal) as excinfo:
        render_brief(job, vocabularies={})

    assert "invents" in str(excinfo.value)


def test_an_empty_vocabulary_says_so_rather_than_being_omitted():
    """An absent section reads as "no constraint"; an empty one reads as "nothing is legal here".
    Those are opposite instructions, and the silent version is the dangerous one."""
    brief = render_brief(_gems_job(), vocabularies={"family": ()})

    assert "(none — this vocabulary is empty)" in brief.text


# ---- Criterion 2: content-addressed, and pure ---------------------------------------------------


def test_identical_inputs_produce_an_identical_content_hash():
    assert _brief().content_hash == _brief().content_hash


def test_the_hash_does_not_depend_on_vocabulary_or_constraint_ordering():
    """Purity's real test. If the hash tracked insertion order, the same brief would hash
    differently depending on how it was assembled — and "which brief produced this?" would have no
    stable answer."""
    a = render_brief(_gems_job(), vocabularies={"family": GEM_FAMILIES})
    b = render_brief(_gems_job(), vocabularies={"family": tuple(reversed(GEM_FAMILIES))})

    assert a.content_hash == b.content_hash
    assert a.text == b.text


def test_a_changed_input_changes_the_hash():
    """The control. A hash that never moves identifies nothing — every brief would be "the same
    version" forever."""
    base = _brief()

    assert _brief(assertion="gems/2 is no longer empty").content_hash != base.content_hash
    assert _brief(id_template="gem.{family}-{seq}").content_hash != base.content_hash
    assert render_brief(
        _gems_job(), vocabularies={"family": GEM_FAMILIES + ("pearl",)}
    ).content_hash != base.content_hash


def test_the_hash_ignores_payload_key_insertion_order():
    """`sort_keys=True` in `_hash_inputs`, exercised directly.

    Found by falsifying: removing it reddened **nothing**, because every payload this module builds
    is already assembled in a fixed order and its vocabularies are pre-sorted. The line was real
    belt-and-braces but entirely untested, and its docstring claimed it was load-bearing — a claim
    the falsifier disproved. Rather than soften the comment, this exercises the unit so the claim
    becomes true: two payloads differing only in insertion order must hash identically.
    """
    from seedsmith.briefkit.render import _hash_inputs

    forward = {"alpha": 1, "beta": 2, "gamma": 3}
    backward = {"gamma": 3, "beta": 2, "alpha": 1}
    assert list(forward) != list(backward), "the fixture must actually differ in order"

    assert _hash_inputs(forward) == _hash_inputs(backward)


def test_the_hash_is_stable_across_processes_not_just_within_one():
    """`hash()` on a str is salted per process, so a content hash built on it would silently break
    re-runnability across invocations. This pins that the digest is a real one."""
    import hashlib
    import json

    payload = {"partition": "gems/2"}
    expected = hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
    ).hexdigest()[:16]

    from seedsmith.briefkit.render import _hash_inputs

    assert _hash_inputs(payload) == expected
    assert len(_brief().content_hash) == 16


# ---- Criterion 3: a failed exemplar gate emits nothing -------------------------------------------


def test_no_brief_is_emitted_when_the_exemplar_gate_refused():
    refused = ExemplarGateResult(refused=True, findings=(), checked=("gem.exemplar-001",),
                                 exit_code=3)

    with pytest.raises(BriefRefusal, match="exemplar gate refused"):
        render_briefs([_gems_job()], gate=refused,
                      vocabularies_for={"gem": {"family": GEM_FAMILIES}})


def test_a_refused_gate_blocks_the_whole_batch_not_just_the_failing_kind():
    """P3 refuses orders whole; so does this. A half-batch built against a known-broken pattern set
    is worse than none, because nothing records which half."""
    refused = ExemplarGateResult(refused=True, findings=(), checked=(), exit_code=3)
    jobs = [_gems_job(), Job("display-templates/4", "display-template", 3, "b.md", "sonnet", {}, ())]

    with pytest.raises(BriefRefusal):
        render_briefs(jobs, gate=refused, vocabularies_for={})


def test_a_passing_gate_emits_one_brief_per_job():
    passed = ExemplarGateResult(refused=False, checked=("gem.exemplar-001",))
    jobs = [_gems_job(), Job("display-templates/4", "display-template", 3, "b.md", "sonnet", {}, ())]

    briefs = render_briefs(jobs, gate=passed,
                           vocabularies_for={"gem": {"family": GEM_FAMILIES}})

    assert [b.job for b in briefs] == ["gems/2", "display-templates/4"]
    assert len({b.content_hash for b in briefs}) == 2


def test_the_brief_carries_the_finding_it_closes():
    """The same grading link the work order carries — a brief that cannot be tied back to a finding
    cannot be judged after it runs."""
    assert "Coverage/EmptyPartition:gems/2" in _brief().text
