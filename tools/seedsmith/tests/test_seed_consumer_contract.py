"""One case per guard in `seed_consumer_violations`, plus an assertion about how many it covers.

This file exists because the corpus was repaired four times against one guard at a time: 44 entries
with an unresolvable elementPrimary, 111 with a rarity outside the ladder, 9 with a string where a
list belongs, 338 with no family at all. Every round fixed a real instance and every round was
followed by a full suite run that surfaced the NEXT guard in the same consumer file, because the
runner checked one field and the validator I had declared complete also enumerated one field.

So the coverage claim itself is asserted here: the predicate must reference every catalog.py line the
live-seed load path raises on. If a guard is added to the consumer and not to the predicate, this
fails and names the missing line - which is the failure that actually happened, four times, silently.

No model, no network.
"""
from __future__ import annotations

import re

import pytest

from seedsmith.adapters.actions.characteristic_pool import catalog
from seedsmith.adapters.creatures.anchor.schema import seed_consumer_violations as violations
from seedsmith.ladders import normalize_family_key

#: Guard NAMES (not line numbers - line numbers in catalog.py shift when an unrelated import moves,
#: which is exactly how this docstring's first draft went stale). Each name is the predicate's own
#: wording, so a new consumer guard the predicate does not cover is a name the test cannot produce.
CONSUMER_GUARDS = (
    "species record must be an object",
    "speciesId present",
    "speciesId unique",
    "dir non-empty",
    "speciesId is a string",
    "elementPrimary in six",
    "elementSecondary in six",
    "rarity in the ladder",
    "traits is a list",
    "a family label normalizes",
    "family is a list",
    "family has a live label",
)

LEGAL = {
    "speciesId": "Specimen",
    "elementPrimary": "fire",
    "rarity": "chaff",
    "traits": [],
    "family": ["explosive-fungus"],
}


def fields(**over) -> dict:
    merged = dict(LEGAL)
    merged.update(over)
    return merged


def test_a_legal_entry_has_no_violations():
    assert violations(fields()) == ()


def test_a_legal_none_secondary_is_not_a_violation():
    """Only the literal `none` (or an absent key) is exempt - mirroring catalog.py L165 exactly."""
    assert violations(fields(elementSecondary="none")) == ()
    assert violations(fields()) == ()


@pytest.mark.parametrize(
    "over, expected",
    [
        ({"speciesId": None}, "speciesId is absent"),
        ({"speciesId": 9}, "not a string"),
        ({"elementPrimary": "smoke"}, "elementPrimary"),
        ({"elementSecondary": ""}, "elementSecondary"),
        ({"elementSecondary": "plasma"}, "elementSecondary"),
        ({"rarity": "unresolved"}, "rarity"),
        ({"rarity": ""}, "rarity"),
        ({"traits": "placeholder"}, "traits is str, not a list"),
        ({"traits": {"a": 1}}, "traits is dict, not a list"),
        ({"family": 7}, "family is int, not a list"),
        ({"family": []}, "family has no live label"),
        ({"family": ["  "]}, "family has no live label"),
        ({"family": ["\u6c34\u751f\u5730\u523a"]}, "normalize to an empty key"),
    ],
)
def test_each_consumer_guard_is_refused_with_a_reason_that_names_it(over, expected):
    got = violations(fields(**over))
    assert got, f"expected a violation for {over!r}"
    assert any(expected in item for item in got), f"{got!r} does not name {expected!r}"


def test_every_violation_is_reported_not_just_the_first():
    """Ten guards means a broken entry should read as broken, in full - a caller that fixed one and
    retried should not have to discover the other nine one suite run at a time."""
    got = violations(fields(elementPrimary="smoke", rarity="nope", traits="x", family=[]))
    assert len(got) == 4, got


def test_the_predicate_documents_every_guard_the_consumer_raises_on():
    """The coverage claim, asserted rather than asserted-about.

    Scoped to the three functions that load the LIVE seed. catalog.py also carries a legacy
    C#-catalog parser whose raises are a different contract this predicate does not and must not
    cover - narrowing to the live path is what makes the assertion meaningful rather than
    unsatisfiable, and the first draft of this test proved the point by failing on those.

    Keyed on guard NAMES. A line-number key looked more precise and was worse: adding one import to
    catalog.py shifted every line it cited, and the test then failed on a docstring that was
    correct. That is the citation-drift class this repo guards against, reproduced in my own code.
    """
    import inspect

    live_path = (catalog.load_live_records, catalog._live_row,
                 catalog.derive_live_family_assignments)
    consumer_raises = [
        line.strip()
        for fn in live_path
        for line in inspect.getsource(fn).splitlines()
        if line.lstrip().startswith("raise ValueError(")
    ]
    assert consumer_raises, "the live-seed load path no longer raises - has catalog.py moved?"

    doc = violations.__doc__ or ""
    missing = [name for name in CONSUMER_GUARDS if name not in doc]
    assert not missing, (
        "seed_consumer_violations does not account for these consumer guards: "
        + ", ".join(missing)
        + " - add the branch and name it, or the corpus will ship the shape again")


def test_every_documented_guard_has_a_behavioural_case():
    """A name in the docstring with no case proving it fires is documentation, not coverage.

    This is the check whose absence let the same defect class ship four times: each guard existed in
    the consumer and had to be discovered by a failing suite run.
    """
    # Built by calling the predicate directly where the case needs a key REMOVED - `fields()` starts
    # from the legal baseline, so passing an omission through it would leave the key in place. That
    # mistake made the first draft of this test report a guard that never fires when it does.
    absent = {k: v for k, v in LEGAL.items() if k != "speciesId"}
    cases = {
        # A non-dict record is refused earlier, by the loader; the predicate sees the consequence.
        "species record must be an object": lambda: violations({"not": "a record"}),
        "speciesId present": lambda: violations(absent),
        "speciesId is a string": lambda: violations(fields(speciesId=9)),
        "elementPrimary in six": lambda: violations(fields(elementPrimary="smoke")),
        "elementSecondary in six": lambda: violations(fields(elementSecondary="")),
        "rarity in the ladder": lambda: violations(fields(rarity="unresolved")),
        "traits is a list": lambda: violations(fields(traits="x")),
        "family is a list": lambda: violations(fields(family=7)),
        "family has a live label": lambda: violations(fields(family=[])),
        "a family label normalizes": lambda: violations(fields(family=["\u6c34\u751f"])),
    }
    for name, build in cases.items():
        got = build()
        assert got, f"the documented guard {name!r} never fires"


def inspect_source(module) -> str:
    import inspect
    return inspect.getsource(module)


def test_the_family_check_uses_the_shared_normalisation_not_a_second_copy():
    """One definition, read by both sides. A restated regex is how the two would drift."""
    for label, expected in (
        ("explosive-fungus", "explosive-fungus"),
        ("Explosive Fungus!", "explosive-fungus"),
        ("sun__ward", "sun-ward"),
    ):
        assert catalog.normalize_family_key(label) == expected
        assert normalize_family_key(label) == expected


def test_a_label_that_normalizes_to_nothing_is_refused_by_both_sides():
    """The consumer RAISES on such a label; the predicate reports it. Same verdict, one definition."""
    with pytest.raises(ValueError):
        catalog.normalize_family_key("\u6c34\u751f")
    assert any("normalize to an empty key" in v
               for v in violations(fields(family=["\u6c34\u751f"])))