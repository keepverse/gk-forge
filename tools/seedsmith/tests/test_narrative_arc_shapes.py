"""`arc-shapes` (NS27, spec-arc-shapes.md §2-§4) — the four shapes and the six structural rules.

    python -m pytest gk-forge/tools/seedsmith/tests/test_narrative_arc_shapes.py -q -s

Fixture registries and a fixture shape carry the rule tests, so a real host kind or pattern can never turn
one red; `shape_ids_pinned` and the load test read the committed file and PRINT their readings. No test
counts arcs or chapters.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from seedsmith.adapters.narrative.arc_shapes import (  # noqa: E402
    AFTER_LAST,
    SHAPE_IDS,
    all_defects,
    links_in_order,
    load_arc_shapes,
    load_link_count_bounds,
    load_spine_frame,
    scene_beats_cap,
    shape,
    spine_chain,
    validate_arc_shapes,
    validate_spine_frame,
)

#: Fixture joins: one host admitting `story`, one pattern fitting it that contains `fight`, and one role id.
HOSTS = {"fixture.host": {"id": "fixture.host", "admits": ["story"]}}
PATTERNS = [{"id": "pattern.fixture",
             "slots": [{"choiceKind": "fight", "outcomes": 2, "position": 0},
                       {"choiceKind": "leave", "outcomes": 1, "position": 1}],
             "fitsKinds": ["story"]}]
ROLE_TAGS = {
    "roleKinds": [{"id": "required"}, {"id": "optional"}, {"id": "forbidden"}, {"id": "none"}],
    "requireFamilies": {"source": {"values": ["party", "named", "wild", "any"]},
                        "side": {"values": ["plant", "zombie"]},
                        "element": {"values": ["fire"]},
                        "characterRole": {"valuesFrom": "roles.v1.json"}},
    "requirementShape": "<family>:<value>",
}
ROLE_IDS = {"fixture-role"}
BOUNDS = (3, 5)

JOINS = {"host_kinds": HOSTS, "patterns": PATTERNS, "role_tags": ROLE_TAGS, "role_ids": ROLE_IDS,
         "bounds": BOUNDS}


def _link(index: int, *, host: str = "fixture.host", kind: str = "story", required: "tuple" = (),
          roles_used: "tuple" = (), sets: "tuple" = (), reads: "tuple" = ()) -> dict:
    return {"linkId": f"fixture.step{index}", "host": host, "storyletKind": kind,
            "requiredChoiceKinds": list(required), "rolesUsed": list(roles_used),
            "flagsSet": [{"flag": flag, "kind": flag_kind} for flag, flag_kind in sets],
            "flagsRead": list(reads)}


def _valid_links() -> "list[dict]":
    return [_link(1, sets=(("fixture.one", "progress"),)),
            _link(2, reads=("fixture.one",), sets=(("fixture.two", "progress"),)),
            _link(3, reads=("fixture.two",))]


def _valid_shape(**overrides) -> dict:
    row = {"description": "a fixture shape", "negative": "not a real shape", "antagonistRules": False,
           "roles": [], "links": _valid_links()}
    row.update(overrides)
    return row


def _defects(row: dict) -> "list[str]":
    return validate_arc_shapes({"fixture": row}, **JOINS)


def _mentions(defects: "list[str]", needle: str) -> bool:
    return any(needle in defect for defect in defects)


# --- the shape's own clauses ----------------------------------------------------------------------

def test_every_shape_has_description_and_negative() -> None:
    assert _defects(_valid_shape()) == []
    assert _mentions(_defects(_valid_shape(description="")), "has no description")
    assert _mentions(_defects(_valid_shape(negative="  ")), "has no negative")


def test_link_count_within_budget_bounds(capsys) -> None:
    assert _defects(_valid_shape()) == []
    two = _defects(_valid_shape(links=_valid_links()[:2]))
    assert _mentions(two, "outside arc.linkCount 3..5"), two
    six = _defects(_valid_shape(links=[_link(index) for index in range(1, 7)]))
    assert _mentions(six, "6 link(s), outside arc.linkCount 3..5"), six
    # A duplicate id and an unprefixed id are rule 1's other half.
    duplicate = _defects(_valid_shape(links=[_link(1), _link(1), _link(2)]))
    assert _mentions(duplicate, "duplicate link id")
    unprefixed = _defects(_valid_shape(links=[_link(1), _link(2),
                                              {**_link(3), "linkId": "other.step3"}]))
    assert _mentions(unprefixed, "is not prefixed by the shape id")
    # The real bound is read from the committed budget, never a constant in the reader.
    low, high = load_link_count_bounds()
    print(f"reading: committed arc.linkCount = {low}..{high}")
    assert low <= high


def test_hosts_and_kinds_are_legal() -> None:
    assert _defects(_valid_shape()) == []
    unknown_host = _defects(_valid_shape(links=[_link(1, host="nope.host"), _link(2), _link(3)]))
    assert _mentions(unknown_host, "is no storylet-vocab host kind")
    wrong_kind = _defects(_valid_shape(links=[_link(1, kind="curio"), _link(2), _link(3)]))
    assert _mentions(wrong_kind, "does not admit")


def test_required_choice_kinds_are_allocatable() -> None:
    allocatable = _defects(_valid_shape(links=[_link(1, required=("fight",)), _link(2), _link(3)]))
    assert allocatable == []
    unallocatable = _defects(_valid_shape(links=[_link(1, required=("offer",)), _link(2), _link(3)]))
    assert _mentions(unallocatable, "no pattern fitting"), unallocatable


def test_flags_read_are_set_earlier() -> None:
    assert _defects(_valid_shape()) == []
    # A link reading a flag a LATER link sets is the defect rule 4 exists for.
    out_of_order = _defects(_valid_shape(links=[
        _link(1, reads=("fixture.two",)),
        _link(2, sets=(("fixture.two", "progress"),)),
        _link(3),
    ]))
    assert _mentions(out_of_order, "which no earlier link of the shape sets"), out_of_order
    # A flag id carrying a digit is refused: the runtime stores flags as facts.
    digit = _defects(_valid_shape(links=[_link(1, sets=(("fixture.one2", "progress"),)), _link(2),
                                         _link(3)]))
    assert _mentions(digit, "outside ^[a-z][a-z-]*")
    unknown_kind = _defects(_valid_shape(links=[_link(1, sets=(("fixture.one", "counter"),)), _link(2),
                                               _link(3)]))
    assert _mentions(unknown_kind, "outside ['progress', 'outcome']")


def test_roles_close() -> None:
    role = {"roleId": "guide", "kind": "required", "allegiance": "independent",
            "requires": ["source:named"]}
    closing = _valid_shape(roles=[role], links=[_link(1, roles_used=("guide",),
                                                     sets=(("fixture.one", "progress"),)),
                                               _link(2, reads=("fixture.one",)),
                                               _link(3)])
    assert _defects(closing) == []
    # An undeclared role, a declared-but-unused role, a bad role id, and an unresolvable requirement.
    undeclared = _defects({**closing, "links": [{**_link(1), "rolesUsed": ["nobody"]}, _link(2),
                                                _link(3)]})
    assert _mentions(undeclared, "which the shape does not declare")
    unused = _defects({**closing, "links": _valid_links()})
    assert _mentions(unused, "which no link uses")
    bad_id = _defects({**closing, "roles": [{**role, "roleId": "Guide"}]})
    assert _mentions(bad_id, "is outside ^[a-z][a-z_]*$")
    reserved = _defects({**closing, "roles": [{**role, "roleId": "guide_start"}]})
    assert _mentions(reserved, "reserved suffix")
    bad_kind = _defects({**closing, "roles": [{**role, "kind": "captain"}]})
    assert _mentions(bad_kind, "kind 'captain' is outside")
    bad_allegiance = _defects({**closing, "roles": [{**role, "allegiance": "enemy"}]})
    assert _mentions(bad_allegiance, "allegiance 'enemy' is outside")
    bad_value = _defects({**closing, "roles": [{**role, "requires": ["source:ghost"]}]})
    assert _mentions(bad_value, "is outside ['party', 'named', 'wild', 'any']")
    bad_family = _defects({**closing, "roles": [{**role, "requires": ["mood:grim"]}]})
    assert _mentions(bad_family, "is not <family>:<value>")


# --- R13 ------------------------------------------------------------------------------------------

def _antagonist_shape(**overrides) -> dict:
    role = {"roleId": "rival", "kind": "required", "allegiance": "antagonist",
            "requires": ["source:named"]}
    row = _valid_shape(antagonistRules=True, roles=[role],
                       links=[_link(1, roles_used=("rival",), sets=(("fixture.one", "progress"),)),
                              _link(2, roles_used=("rival",), reads=("fixture.one",)),
                              _link(3, roles_used=("rival",))])
    row.update(overrides)
    return row


def test_rival_has_only_progress_flags() -> None:
    assert _defects(_antagonist_shape()) == []
    with_outcome = _defects(_antagonist_shape(links=[
        _link(1, roles_used=("rival",), sets=(("fixture.one", "outcome"),)),
        _link(2, roles_used=("rival",), reads=("fixture.one",)),
        _link(3, roles_used=("rival",)),
    ]))
    assert _mentions(with_outcome, "R13 rule 3"), with_outcome
    # R13 rule 1: a recruit choice against the antagonist.
    recruiting = _defects(_antagonist_shape(links=[
        _link(1, roles_used=("rival",), required=("fight",), sets=(("fixture.one", "progress"),)),
        _link(2, roles_used=("rival",), reads=("fixture.one",)),
        {**_link(3, roles_used=("rival",)), "requiredChoiceKinds": ["recruit"]},
    ]))
    assert _mentions(recruiting, "R13 rule 1"), recruiting


def test_antagonist_shape_has_one_antagonist_role() -> None:
    assert _defects(_antagonist_shape()) == []
    second = {"roleId": "rival_two", "kind": "required", "allegiance": "antagonist",
              "requires": ["source:named"]}
    two = _defects(_antagonist_shape(roles=[*_antagonist_shape()["roles"], second],
                                     links=[_link(1, roles_used=("rival", "rival_two"),
                                                  sets=(("fixture.one", "progress"),)),
                                            _link(2, roles_used=("rival", "rival_two"),
                                                  reads=("fixture.one",)),
                                            _link(3, roles_used=("rival", "rival_two"))]))
    assert _mentions(two, "R13 rule 2"), two


def test_antagonist_role_requires_antagonist_rules() -> None:
    silent = _defects(_antagonist_shape(antagonistRules=False))
    assert _mentions(silent, "antagonistRules must be true"), silent


# --- the committed file ---------------------------------------------------------------------------

def test_shape_ids_pinned(capsys) -> None:
    """A declaration, with its reason: the four v1 shapes are what the owner approved, so a fifth is a
    reviewed registry change rather than a row someone appends."""
    shapes = load_arc_shapes()
    assert tuple(shapes) == SHAPE_IDS
    assert len(SHAPE_IDS) == 4
    assert all_defects() == []
    for shape_id in SHAPE_IDS:
        row = shape(shape_id)
        print(f"reading: {shape_id}: {len(row['links'])} link(s), {len(row['roles'])} role(s), "
              f"antagonistRules={row['antagonistRules']}")
    assert links_in_order("rival")[0]["linkId"] == "rival.taunt"
    with pytest.raises(ValueError):
        shape("not-a-shape")


# --- the spine frame (spec §5) ---------------------------------------------------------------------

#: Fixture teaches rows: four the spine carries, one only a storylet does.
TEACHES = [
    {"value": "expedition-dispatch", "teachingOrder": 1, "carriers": ["spine", "storylet"]},
    {"value": "talk-verbs", "teachingOrder": 2, "carriers": ["spine"]},
    {"value": "world-command", "teachingOrder": 3, "carriers": ["spine"]},
    {"value": "counter-doctrine", "teachingOrder": 4, "carriers": ["spine"]},
    {"value": "quest-log", "teachingOrder": 5, "carriers": ["storylet"]},
]
MAX_BEATS = 3
CAST = ("lead_summoner", "lead_companion", "lead_antagonist")


def _scene(slot: str = "open", *, beats: int = 2, speakers: "tuple" = ("lead_antagonist",),
           teaches: str = "none") -> dict:
    return {"sceneSlot": slot, "beats": beats, "speakers": list(speakers), "teaches": teaches}


def _chapter(chapter_id: str, after: str, *, scenes: "tuple" = (), cast: "tuple" = CAST,
             piece: "str | None" = None) -> dict:
    return {"chapterId": chapter_id, "pieceId": piece or f"piece.{chapter_id.split('.', 1)[1]}",
            "after": after, "description": "a fixture chapter", "negative": "not a real chapter",
            "cast": list(cast), "scenes": [dict(scene) for scene in scenes]}


def _fragment(fragment_id: str, after_chapter: str, after: str) -> dict:
    return {"fragmentId": fragment_id, "afterChapter": after_chapter, "after": after,
            "description": "a fixture fragment", "negative": "not real lore"}


def _frame(chapters: "list", *, fragments: "list | None" = None, after_last: str = AFTER_LAST) -> dict:
    return {"schemaVersion": 1, "registryVersion": 1, "afterLast": after_last,
            "fragments": fragments if fragments is not None else [], "chapters": chapters}


def _spine_defects(frame: dict) -> "list[str]":
    return validate_spine_frame(frame, teaches=TEACHES, max_beats=MAX_BEATS)


def _three() -> "list":
    return [_chapter("chapter.a", "none"), _chapter("chapter.b", "chapter.a"),
            _chapter("chapter.c", "chapter.b")]


def test_spine_chain_is_single_and_acyclic(capsys) -> None:
    assert _spine_defects(_frame(_three())) == []
    cycle = _spine_defects(_frame([_chapter("chapter.a", "chapter.b"),
                                   _chapter("chapter.b", "chapter.a")]))
    assert _mentions(cycle, "cycle"), cycle
    gap = _spine_defects(_frame([_chapter("chapter.a", "none"), _chapter("chapter.b", "chapter.a"),
                                 _chapter("chapter.c", "chapter.nope")]))
    assert _mentions(gap, "is no row of the set") and _mentions(gap, "a gap"), gap
    two_roots = _spine_defects(_frame([_chapter("chapter.a", "none"), _chapter("chapter.b", "none"),
                                       _chapter("chapter.c", "chapter.a")]))
    assert _mentions(two_roots, "2 row(s) have after 'none'"), two_roots
    duplicate = _spine_defects(_frame([_chapter("chapter.a", "none"), _chapter("chapter.a", "none"),
                                      _chapter("chapter.b", "chapter.a")]))
    assert _mentions(duplicate, "duplicate id"), duplicate
    # The committed frame's chain, in order.
    committed = spine_chain()
    print(f"reading: committed spine chain = {list(committed)}")
    assert committed[0] == "chapter.one" and committed[-1] == "chapter.seven"


def test_frame_has_seven_chapter_slots(capsys) -> None:
    """A declaration, with its reason: the owner answered seven pieces (2026-09-19), so the frame ships
    seven chapter rows chained by `after` — not a population that grows when content ships."""
    frame = load_spine_frame()
    assert len(frame["chapters"]) == 7
    assert len(spine_chain()) == 7
    assert all_defects() == []
    print(f"reading: committed frame = {len(frame['chapters'])} chapter(s), "
          f"{len(frame['fragments'])} fragment(s), afterLast={frame['afterLast']!r}")


def test_chapter_row_without_scenes_plans_nothing(capsys) -> None:
    empty = _frame([_chapter("chapter.a", "none", scenes=()), *_three()[1:]])
    assert _spine_defects(empty) == []
    committed = load_spine_frame()
    assert all(chapter["scenes"] == [] for chapter in committed["chapters"])
    print(f"reading: committed chapters with scenes = "
          f"{sum(1 for chapter in committed['chapters'] if chapter['scenes'])}")


def test_scene_beats_within_tuning_cap(capsys) -> None:
    assert _spine_defects(_frame([_chapter("chapter.a", "none", scenes=(_scene(beats=MAX_BEATS),))])) == []
    over = _spine_defects(_frame([_chapter("chapter.a", "none", scenes=(_scene(beats=MAX_BEATS + 1),))]))
    assert _mentions(over, f"over scene.maxBeatsPerScene={MAX_BEATS}"), over
    zero = _spine_defects(_frame([_chapter("chapter.a", "none", scenes=(_scene(beats=0),))]))
    assert _mentions(zero, "at least one is required"), zero
    cap = scene_beats_cap()
    print(f"reading: committed scene.maxBeatsPerScene = {cap}")
    assert cap >= 1


def test_antagonist_speaks_when_chapters_exist() -> None:
    silent = _spine_defects(_frame([_chapter("chapter.a", "none",
                                             scenes=(_scene(speakers=("lead_summoner",)),))]))
    assert _mentions(silent, "R2"), silent
    speaking = _spine_defects(_frame([_chapter("chapter.a", "none", scenes=(
        _scene(speakers=("lead_antagonist",)),))]))
    assert speaking == []
    # A row with no scenes plans nothing, so it has no speakers to check — which is why the committed
    # frame's empty rows pass this rule until NS29 authors them.
    assert _spine_defects(_frame([_chapter("chapter.a", "none")])) == []
    unknown_speaker = _spine_defects(_frame([_chapter("chapter.a", "none", scenes=(
        _scene(speakers=("lead_antagonist", "someone-else")),))]))
    assert _mentions(unknown_speaker, "is not in the chapter's cast"), unknown_speaker


def test_frame_teaching_order() -> None:
    in_order = _frame([
        _chapter("chapter.a", "none", scenes=(_scene(teaches="expedition-dispatch"),)),
        _chapter("chapter.b", "chapter.a", scenes=(_scene(teaches="talk-verbs"),)),
        _chapter("chapter.c", "chapter.b", scenes=(_scene(teaches="world-command"),)),
    ])
    assert _spine_defects(in_order) == []
    backwards = _frame([
        _chapter("chapter.a", "none", scenes=(_scene(teaches="talk-verbs"),)),
        _chapter("chapter.b", "chapter.a", scenes=(_scene(teaches="expedition-dispatch"),)),
        _chapter("chapter.c", "chapter.b"),
    ])
    assert _mentions(_spine_defects(backwards), "teaches out of order")
    not_spine = _frame([_chapter("chapter.a", "none", scenes=(_scene(teaches="quest-log"),))])
    assert _mentions(_spine_defects(not_spine), "carried by the spine")
    twice = _frame([
        _chapter("chapter.a", "none", scenes=(_scene(teaches="talk-verbs"),)),
        _chapter("chapter.b", "chapter.a", scenes=(_scene(teaches="talk-verbs"),)),
    ])
    assert _mentions(_spine_defects(twice), "taught by two scenes")
    # `none` is always legal and teaches nothing.
    assert _spine_defects(_frame([_chapter("chapter.a", "none", scenes=(_scene(teaches="none"),))])) == []


def test_fragments_close() -> None:
    closing = _frame(_three(), fragments=[_fragment("fragment.a", "chapter.a", "none"),
                                          _fragment("fragment.b", "chapter.b", "fragment.a")])
    assert _spine_defects(closing) == []
    duplicate = _frame(_three(), fragments=[_fragment("fragment.a", "chapter.a", "none"),
                                            _fragment("fragment.a", "chapter.b", "fragment.a")])
    assert _mentions(_spine_defects(duplicate), "duplicate id")
    cycle = _frame(_three(), fragments=[_fragment("fragment.a", "chapter.a", "fragment.b"),
                                        _fragment("fragment.b", "chapter.b", "fragment.a")])
    assert _mentions(_spine_defects(cycle), "cycle")
    unknown_chapter = _frame(_three(), fragments=[_fragment("fragment.a", "chapter.nope", "none")])
    assert _mentions(_spine_defects(unknown_chapter), "which is no chapter of the frame")


def test_after_last_is_fixed() -> None:
    assert _spine_defects(_frame(_three(), after_last=AFTER_LAST)) == []
    assert _mentions(_spine_defects(_frame(_three(), after_last="nothing")), "it is fixed to")
