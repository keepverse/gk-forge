"""Tests for the `items generate --write` wiring (item module 13's deferred generation graph).

    python -m pytest gk-forge/tools/seedsmith/tests/test_item_gen_wiring.py -q

⭐ **What this file proves and what it deliberately does not.** It proves the PATH: a planned
subject reaches the graph, an authored answer comes back through the injected transport, the
already-built distributors price it or refuse it with their own rule names, a refusal re-prompts,
an exhausted subject escalates without taking the batch with it, and a clean batch writes a seed
file somewhere it was told to. It does not judge the CONTENT — that is what the run report's
distinctness metrics are for, and they are measured over a real batch in the module's todo entry.

⭐ **`Module13DefectsFixedTests` at the bottom is the five defects this wiring MEASURED in module
13's own machinery on 2026-09-06, now asserted in their fixed state.** They were first written as
"this is the state today", with the numbers, so that a fix could not land silently — the fix landed
the same day and the assertions were inverted rather than deleted. The before-numbers stay in the
docstrings, because a fix whose evidence has been deleted cannot be re-checked.
"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from seedsmith.adapters.items.charmgen import rules as charm_rules  # noqa: E402
from seedsmith.adapters.items.setgen import answers as answers_mod  # noqa: E402
from seedsmith.adapters.items.setgen import authored as authored_mod  # noqa: E402
from seedsmith.adapters.items.setgen import brief as brief_mod  # noqa: E402
from seedsmith.adapters.items.setgen import cells, distribute, emit  # noqa: E402
from seedsmith.adapters.items.setgen import schema as schema_mod  # noqa: E402
from seedsmith.adapters.items.setgen import seedfile as seedfile_mod  # noqa: E402
from seedsmith.adapters.items.setgen import tuning as tuning_mod  # noqa: E402
from seedsmith.adapters.items.setgen import vocab as vocab_mod  # noqa: E402
from seedsmith.adapters.items.setgen.run import RunPlan, Subject  # noqa: E402
from seedsmith.adapters.items.setgen.themes import Theme  # noqa: E402
from seedsmith.adapters.items.setgen.verdict import GATING_METRICS, Verdict  # noqa: E402
from seedsmith.workflow.graphs import item_set as graph_mod  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[3]

# `REPO_ROOT`-relative joins below ask which repository actually carries the path. A prefix-keyed
# rewrite is wrong: `data`, `data/seed` and `data/seed/creatures` all resolve back to gk-forge,
# because nearest-match-wins and gk-forge owns its own generator inputs. `or REPO_ROOT` is
# load-bearing - `owning_base` returns None for a path no repository carries, where
# `content_root()` would RAISE.

from seedsmith.workspace_roots import owning_base  # noqa: E402


def _owned(relative: str) -> "Path":
    """The repository carrying `relative`, joined to it; this one when none carries it."""
    return (owning_base(relative, REPO_ROOT) or REPO_ROOT) / relative

TUNING = tuning_mod.load()
VOCAB = vocab_mod.build(TUNING)

SET_ROLES = ("armament-primary", "core-guard", "manipulator", "footing")


def _build_theme() -> Theme:
    return Theme(
        theme_key="build.might-offense", species_id=None, display_name="Might / Offense",
        motifs=("might", "force", "offense"), anti_motifs=("defense",),
        expression_item="stat emphasis and threshold shape", basis="derived", rarity=None,
        retired=False, population="build", aptitude="Might", archetype="offense")


def _species_theme() -> Theme:
    return Theme(
        theme_key="creature.testspecies", species_id="testspecies", display_name="Test Species",
        motifs=("iron", "patience"), anti_motifs=(), expression_item="material and form",
        basis="text", rarity=None, retired=False, population="species")


def _legal_capability() -> str:
    """A capability pick legal on `SET_ROLES` — resolved, never pinned, so a corpus edit that moves
    a family's roles produces a red test here rather than a mystery refusal in a real run."""
    for pick in VOCAB.capability_for_roles(SET_ROLES):
        if pick.variant is None:
            return pick.family
    raise AssertionError("no element-free capability is legal on the four core roles")


def _legal_set_stat() -> str:
    for pick in VOCAB.stat:
        if (pick.variant is None
                and pick.kind_id in TUNING.stat_kinds
                and pick.family not in distribute.MORE_OP_FAMILIES
                and pick.family not in distribute.MATCH_SCOPE_ONLY_FAMILIES):
            return pick.family
    raise AssertionError("no stat family survives the set-tier rules")


def _legal_charm_families() -> "list[str]":
    """Element-free families from the pool the brief actually prints. Resolved, never pinned."""
    seen: "list[str]" = []
    for pick in charm_rules.charm_pool(TUNING, VOCAB.all_picks):
        if pick.variant is None and pick.family not in seen:
            seen.append(pick.family)
    if len(seen) < 2:
        raise AssertionError("the charm pool has fewer than two element-free families")
    return seen


def _legal_charm_family() -> str:
    return _legal_charm_families()[0]


def _clean_set_answer() -> dict:
    # ⛔ `nameKey` removed 2026-09-08 — the model is no longer asked for it at all (see
    # `setgen.schema._identity_fields`'s own docstring); a clean answer fixture must match what a
    # real, well-formed model answer now looks like, not the old contract.
    return {
        "name": "Proof Set",
        "flavor": "A fixture, and it says so.",
        "capability": {"family": _legal_capability()},
        "members": [{"role": r, "frame": "plant"} for r in SET_ROLES],
        "thresholds": [{"pieces": 2}, {"pieces": 4, "families": [_legal_set_stat()]}],
    }


def _clean_charm_answer() -> dict:
    return {
        "name": "Proof Charm",
        "flavor": "A fixture, and it says so.",
        "charmClass": "minor", "axis": "survivability", "frameHint": "any",
        "families": [_legal_charm_family()],
    }


def _set_plan(subject_count: int = 1) -> RunPlan:
    theme = _build_theme()
    subjects = [
        Subject(subject_id=f"set-build-build.might-offense-{i}", kind="set", population="build",
                theme_key=theme.theme_key, entry_id=emit.build_set_id("might", "offense", i + 1),
                brief=brief_mod.build_set_brief(theme, TUNING, VOCAB))
        for i in range(subject_count)
    ]
    return RunPlan(subjects=subjects, held=[], already_done=[])


def _charm_plan() -> RunPlan:
    theme = _species_theme()
    return RunPlan(subjects=[Subject(
        subject_id="charm-species-creature.testspecies", kind="charm", population="species",
        theme_key=theme.theme_key, entry_id="charm.(axis-group)-NNN for testspecies",
        brief=brief_mod.build_charm_brief(theme, TUNING, VOCAB))], held=[], already_done=[])


def _answer_file(kind: str, population: str, mapping: dict) -> answers_mod.AnswerFile:
    return answers_mod.AnswerFile(kind=kind, population=population,
                                  prompt_version=brief_mod.PROMPT_VERSION,
                                  by_subject={k: tuple(v if isinstance(v, list) else [v])
                                              for k, v in mapping.items()})


class TransportTests(unittest.TestCase):
    def test_the_transport_module_cannot_reach_the_network(self):
        """The replay path must be provably offline, not merely intended to be. Asserted by module
        text, the same structural discipline `nothing_in_the_generator_writes_the_creatures_corpus`
        already uses for the creature corpus."""
        source = (Path(answers_mod.__file__)).read_text(encoding="utf-8")
        body = source.split('"""', 2)[-1]      # skip the header, which discusses llm_caller
        for banned in ("llm_caller", "urllib", "requests", "socket", "http"):
            self.assertNotIn(banned, body, f"{banned!r} appears in the replay transport's code")

    def test_an_answer_file_is_refused_rather_than_defaulted(self):
        cases = {
            "wrong version": {"schemaVersion": 99, "kind": "set", "population": "build",
                              "promptVersion": "x", "answers": {"a": {}}},
            "no answers": {"schemaVersion": 1, "kind": "set", "population": "build",
                           "promptVersion": "x", "answers": {}},
            "missing kind": {"schemaVersion": 1, "population": "build", "promptVersion": "x",
                             "answers": {"a": {}}},
            "answer is not an object": {"schemaVersion": 1, "kind": "set", "population": "build",
                                        "promptVersion": "x", "answers": {"a": ["nope"]}},
        }
        import tempfile
        for label, doc in cases.items():
            with self.subTest(label):
                with tempfile.TemporaryDirectory() as tmp:
                    path = Path(tmp) / "answers.json"
                    path.write_text(json.dumps(doc), encoding="utf-8")
                    with self.assertRaises(answers_mod.AnswerFileError):
                        answers_mod.load_answers(path)

    def test_attempts_are_served_in_order_and_then_escalate(self):
        briefs = {"s1": "BRIEF ONE"}
        file = _answer_file("set", "build", {"s1": [{"n": 1}, {"n": 2}]})
        call = answers_mod.replay_caller(briefs, file)
        self.assertEqual(json.loads(call("sys", "BRIEF ONE")), {"n": 1})
        self.assertEqual(json.loads(call("sys", "BRIEF ONE\n\nmore")), {"n": 2})
        with self.assertRaises(answers_mod.AnswerExhausted):
            call("sys", "BRIEF ONE")

    def test_an_exhausted_subject_carries_the_defects_it_was_asked_to_repair(self):
        """The repair prompt is the only place those strings still exist by the time the transport
        is reached; losing them turns a precise refusal into 'the batch stopped'."""
        briefs = {"s1": "BRIEF"}
        call = answers_mod.replay_caller(briefs, _answer_file("set", "build", {"s1": {"n": 1}}))
        call("sys", "BRIEF")
        repair = ("BRIEF\n\n" + answers_mod.REPAIR_HEADER
                  + "\n- SetTierForbiddenAtom: nope\n- SetRoleForbidden: also nope\nFix exactly these.")
        with self.assertRaises(answers_mod.AnswerExhausted) as caught:
            call("sys", repair)
        self.assertEqual(caught.exception.defects,
                         ("SetTierForbiddenAtom: nope", "SetRoleForbidden: also nope"))

    def test_a_prompt_from_another_plan_is_refused_not_guessed(self):
        call = answers_mod.replay_caller({"s1": "BRIEF"}, _answer_file("set", "build", {"s1": {}}))
        with self.assertRaises(answers_mod.AnswerMissing):
            call("sys", "a completely different brief")

    def test_two_subjects_with_identical_briefs_are_refused_not_cross_served(self):
        """Two subjects built from the same theme produce byte-identical briefs — module 13's own
        `re_running_over_unchanged_themes_is_byte_identical` guarantees it — so prefix matching
        alone would silently hand one subject's answer to the other."""
        call = answers_mod.replay_caller(
            {"s1": "SAME", "s2": "SAME"},
            _answer_file("set", "build", {"s1": {"n": 1}, "s2": {"n": 2}}))
        with self.assertRaises(answers_mod.AnswerMissing) as caught:
            call("sys", "SAME")
        self.assertIn("identical briefs", str(caught.exception))
        call.current_subject_id = "s2"
        self.assertEqual(json.loads(call("sys", "SAME")), {"n": 2})


class SchemaCheckTests(unittest.TestCase):
    """Constrained decoding is the ENDPOINT's guarantee; a replayed answer has to earn it here."""

    def test_a_clean_answer_has_no_schema_defects(self):
        for label, draft, schema in (
            ("set", _clean_set_answer(), schema_mod.set_schema(TUNING, vocabulary=VOCAB)),
            ("charm", _clean_charm_answer(), schema_mod.charm_schema(TUNING)),
        ):
            with self.subTest(label):
                self.assertEqual(answers_mod.schema_defects(draft, schema), [])

    def test_each_closed_keyword_is_actually_enforced(self):
        schema = schema_mod.set_schema(TUNING, vocabulary=VOCAB)
        cases = {
            "unknown field": ({**_clean_set_answer(), "tier": "x"}, "unknown field"),
            "bad role enum": ({**_clean_set_answer(),
                               "members": [{"role": "head-guard", "frame": "plant"}]},
                              "is not one of"),
            "bad pieces enum": ({**_clean_set_answer(),
                                 "thresholds": [{"pieces": 5}, {"pieces": 4}]}, "is not one of"),
            # ⛔ Real gap closed 2026-09-08 — `nameKey` is no longer a schema property at all (it
            # is derived deterministically from `name`, never asked of the model), so a draft that
            # still supplies one is an UNKNOWN field now, not a pattern violation.
            "nameKey is not a legal field anymore": ({**_clean_set_answer(), "nameKey": "set.x"},
                                                     "unknown field"),
            "short name": ({**_clean_set_answer(), "name": "x"}, "below the minimum"),
            "too many families": ({**_clean_set_answer(),
                                   "thresholds": [{"pieces": 2},
                                                  {"pieces": 4, "families": ["a", "b", "c", "d"]}]},
                                  "above the maximum"),
        }
        for label, (draft, needle) in cases.items():
            with self.subTest(label):
                found = answers_mod.schema_defects(draft, schema)
                self.assertTrue(any(needle in d for d in found), f"{label}: {found}")

    def test_a_boolean_is_not_an_integer(self):
        """`bool` is an `int` in Python and slips through a bare isinstance check."""
        self.assertTrue(answers_mod.schema_defects(
            {"pieces": True}, {"type": "object", "properties": {"pieces": {"type": "integer"}}}))


class OutDirGuardTests(unittest.TestCase):
    def test_the_production_tree_is_refused_unless_asked_for(self):
        inside = seedfile_mod.ITEM_SEED_ROOT / "_sample"
        with self.assertRaises(seedfile_mod.OutDirRefused):
            seedfile_mod.resolve_out_dir(inside)
        self.assertEqual(seedfile_mod.resolve_out_dir(inside, allow_production_tree=True),
                         inside.resolve())

    def test_a_path_outside_the_item_tree_is_allowed(self):
        outside = _owned("tools/seedsmith") / "_sample-runs" / "x"
        self.assertEqual(seedfile_mod.resolve_out_dir(outside), outside.resolve())


class IdTests(unittest.TestCase):
    def test_the_axis_group_fold_is_read_from_the_registry(self):
        mapping = seedfile_mod.axis_group_map()
        self.assertEqual(mapping["offense"], "off-ctrl")
        self.assertEqual(mapping["control"], "off-ctrl")
        self.assertEqual(mapping["survivability"], "surv-util")
        self.assertEqual(mapping["economy"], "econ")
        self.assertEqual(set(mapping), set(charm_rules.CHARM_AXES))

    def test_a_generated_charm_continues_the_shipped_partition(self):
        """Ids are never reused, so a generated charm resumes the partition rather than colliding
        with `charm.off-ctrl-001`. Measured off the live corpus, not assumed."""
        self.assertGreater(seedfile_mod.next_charm_seq("off-ctrl"), 1)


class DeriveNameKeyTests(unittest.TestCase):
    """⛔ Real gap closed 2026-09-08: `nameKey` used to be a field the model filled in directly.
    Two independent findings (`trees.nodegen`'s 2026-09-06 fallback-key finding, and this
    program's own 2026-09-08 degenerate-generation incident on the identical field) converge on
    never asking for it — `derive_name_key` computes it mechanically from `name` instead."""

    def test_matches_the_real_shipped_convention(self) -> None:
        # Measured directly off the real corpus 2026-09-08: name "Stillmarch" -> nameKey
        # "set.stillmarch"; name "Vengeful Bastion" -> nameKey "set.vengeful-bastion";
        # name "Hoarded Kernel" -> nameKey "charm.hoarded-kernel".
        self.assertEqual(seedfile_mod.derive_name_key("set", "Stillmarch"), "set.stillmarch")
        self.assertEqual(seedfile_mod.derive_name_key("set", "Vengeful Bastion"),
                         "set.vengeful-bastion")
        self.assertEqual(seedfile_mod.derive_name_key("charm", "Hoarded Kernel"),
                         "charm.hoarded-kernel")

    def test_punctuation_collapses_to_a_single_hyphen(self) -> None:
        self.assertEqual(seedfile_mod.derive_name_key("set", "Frost & Fire!!"), "set.frost-fire")

    def test_never_produces_a_leading_or_trailing_hyphen(self) -> None:
        self.assertEqual(seedfile_mod.derive_name_key("set", "  --Edge--  "), "set.edge")

    def test_an_unsluggable_name_is_refused_not_given_a_placeholder_key(self) -> None:
        """⛔ CORRECTED 2026-09-12. This test used to assert `derive_name_key("set", "!!!") ==
        "set.item"`, and the same `"item"` fallback fired for every non-Latin name — which is how
        six shipped sets (Chinese display names) all landed on the identical key `set.item`,
        satisfying the pattern while destroying global uniqueness. `seed-contract.md` §6 says the
        string may be free text but the KEY must be `^[a-z0-9.-]+$`, so a name with no ASCII
        content is a content defect, not a reason to mint a shared placeholder. Refuse it by name."""
        for name in ("!!!", "毁灭豌豆之友", "   "):
            with self.subTest(name=name):
                with self.assertRaises(seedfile_mod.NameKeyUnsluggable):
                    seedfile_mod.derive_name_key("set", name)

    def test_the_derived_key_matches_the_real_schema_pattern(self) -> None:
        import re
        pattern = re.compile(r"^[a-z][a-z0-9]*(\.[a-z0-9]+(-[a-z0-9]+)*)+$")
        for name in ("Stillmarch", "Vengeful Bastion", "Frost & Fire!!", "  --Edge--  "):
            with self.subTest(name=name):
                self.assertRegex(seedfile_mod.derive_name_key("set", name), pattern)


class ResolveCapabilityTests(unittest.TestCase):
    """⛔ Real incident, 2026-09-08: a live 53-subject run, AFTER the brief-truncation fix
    (see `test_set_charm_gen.py`'s own truncation test), still escalated on the same
    `capability` field, now for a DIFFERENT reason — the model never split an elemental pick's
    `family`/`variant` the way `resolve_capability`'s object contract expects, and there is
    nowhere else in this program a model is asked to produce a family as anything but one plain
    string (`resolve_pick`'s own docstring already tolerates two SPELLINGS of a plain string;
    this is a different shape problem). Two live shapes were observed:

    1. An elemental pick's full printed id echoed into BOTH fields:
       `{"family": "atom.deathblast.fire", "variant": "atom.deathblast.fire"}` instead of the
       split `{"family": "atom.deathblast", "variant": "fire"}` the schema actually asks for.
    2. A flat (variant-less) pick given a placeholder `variant` instead of omitting it:
       `{"family": "atom.freezing", "variant": "none"}`.

    Both are legal, unambiguous picks a human reading the printed list would recognize
    instantly. `resolve_capability` now tries the untouched `family` value as a plain pick_id
    FIRST (`resolve_pick`, the same tolerant lookup every stat/charm family already goes
    through) before falling back to the family+variant combination — so a model that never
    learned the split still resolves correctly.
    """

    def test_the_full_pick_id_echoed_into_both_fields_still_resolves(self) -> None:
        node = {"family": "atom.deathblast.fire", "variant": "atom.deathblast.fire"}
        pick = seedfile_mod.resolve_capability(VOCAB, node)
        self.assertIsNotNone(pick)
        self.assertEqual(pick.pick_id, "atom.deathblast.fire")

    def test_a_flat_pick_with_a_placeholder_variant_still_resolves(self) -> None:
        node = {"family": "atom.freezing", "variant": "none"}
        pick = seedfile_mod.resolve_capability(VOCAB, node)
        self.assertIsNotNone(pick)
        self.assertEqual(pick.pick_id, "atom.freezing")

    def test_the_correctly_split_shape_still_resolves(self) -> None:
        """The fix must not break the shape the schema actually documents."""
        node = {"family": "atom.deathblast", "variant": "fire"}
        pick = seedfile_mod.resolve_capability(VOCAB, node)
        self.assertIsNotNone(pick)
        self.assertEqual(pick.pick_id, "atom.deathblast.fire")

    def test_a_flat_pick_named_plainly_with_no_variant_key_still_resolves(self) -> None:
        node = {"family": "atom.freezing"}
        pick = seedfile_mod.resolve_capability(VOCAB, node)
        self.assertIsNotNone(pick)
        self.assertEqual(pick.pick_id, "atom.freezing")

    def test_a_family_that_names_nothing_real_returns_none(self) -> None:
        node = {"family": "atom.does-not-exist", "variant": "fire"}
        self.assertIsNone(seedfile_mod.resolve_capability(VOCAB, node))


class AnswerDeclaresContentBlockedLengthTests(unittest.TestCase):
    """⛔ Real incident, 2026-09-08, first live `charm` run: a real model answer came back
    `{"blocked": "blocked", ...}` — a bare placeholder repeating the field's own name, accepted
    as a legitimate refusal and silently dropping real, generatable content. `answer_declares_content`
    now refuses a `blocked` string too short to be a real explanation, naming it as a defect
    instead of a legitimate escape hatch."""

    def test_a_bare_placeholder_matching_the_field_name_is_a_named_defect(self) -> None:
        draft = {**_clean_charm_answer(), "blocked": "blocked"}
        defects = graph_mod.answer_declares_content(draft, {"kind": "charm"})
        self.assertTrue(any("too short" in d for d in defects), defects)

    def test_a_bare_none_placeholder_is_a_named_defect(self) -> None:
        draft = {**_clean_set_answer(), "blocked": "none"}
        defects = graph_mod.answer_declares_content(draft, {"kind": "set"})
        self.assertTrue(any("too short" in d for d in defects), defects)

    def test_a_real_reason_at_the_length_floor_is_accepted(self) -> None:
        draft = {"blocked": "no motifs land"}  # 15 chars, the existing fixture's own real reason
        self.assertEqual(graph_mod.answer_declares_content(draft, {"kind": "set"}), [])

    def test_a_null_blocked_with_complete_content_is_unaffected(self) -> None:
        self.assertEqual(
            graph_mod.answer_declares_content({**_clean_set_answer(), "blocked": None},
                                              {"kind": "set"}), [])


class BatchTests(unittest.TestCase):
    def test_a_small_batch_runs_end_to_end_and_writes_a_seed_file(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "sets"
            plan = _set_plan()
            subject_id = plan.subjects[0].subject_id
            result = authored_mod.run_batch(
                plan=plan, answers=_answer_file("set", "build", {subject_id: _clean_set_answer()}),
                tuning=TUNING, vocabulary=VOCAB, out_dir=out, kind="set", population="build",
                authored_utc="1970-01-01T00:00:00Z", model="fixture",
                ledger_path=out / "ledger.json")
            self.assertEqual(len(result.persisted), 1, result.to_dict())
            self.assertEqual(len(result.files), 1)
            doc = json.loads(result.files[0].read_text(encoding="utf-8"))
            self.assertEqual(doc["kind"], "set")
            entry = doc["entries"][0]
            self.assertEqual(entry["id"], "set.might-offense-001")
            self.assertEqual(entry["themeKey"], "build.might-offense")
            self.assertTrue(all(member.get("baseType") for member in entry["members"]))
            self.assertEqual([t["pieces"] for t in entry["thresholds"]], [2, 4])
            self.assertIn("capability", entry["thresholds"][0])
            self.assertIn("atoms", entry["thresholds"][1])
            self.assertTrue((out / "ledger.json").exists())

    def test_a_live_transport_runtime_error_escalates_one_subject(self):
        """A dead endpoint must not abort the whole batch or leave the subject untracked."""
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            plan = _set_plan(2)
            calls = iter((RuntimeError("endpoint unavailable"), _clean_set_answer()))

            def call(*_args, **_kwargs):
                answer = next(calls)
                if isinstance(answer, Exception):
                    raise answer
                return json.dumps(answer)

            result = authored_mod.run_batch(
                plan=plan, answers=_answer_file("set", "build", {}), tuning=TUNING,
                vocabulary=VOCAB, out_dir=Path(tmp) / "sets", kind="set", population="build",
                authored_utc="1970-01-01T00:00:00Z", model="fixture",
                ledger_path=Path(tmp) / "ledger.json", call=call)
            self.assertEqual([o.outcome for o in result.outcomes], ["escalated", "persisted"])
            done = json.loads((Path(tmp) / "ledger.json").read_text(encoding="utf-8"))["done"]
            self.assertEqual(done[plan.subjects[0].subject_id]["outcome"], "escalated")
            self.assertIn(plan.subjects[1].subject_id, done)


class SetMemberBindingTests(unittest.TestCase):
    def test_live_lookup_excludes_base_types_claimed_by_uniques(self):
        candidates = seedfile_mod.load_base_type_candidates()
        self.assertNotIn("item.plant-muzzle-a-005", candidates[("plant", "armament-primary")])
        all_candidates = seedfile_mod.load_base_type_candidates(include_unique=True)
        self.assertIn("item.plant-muzzle-a-005", all_candidates[("plant", "armament-primary")])

    def test_binding_is_stable_and_uses_only_the_offered_candidates(self):
        candidates = {("plant", "core-guard"): ("item.plant-core-a-001", "item.plant-core-a-002")}
        members = [{"role": "core-guard", "frame": "plant"}]
        first = seedfile_mod.bind_member_base_types("set.proof-001", members, candidates)
        second = seedfile_mod.bind_member_base_types("set.proof-001", members, candidates)
        self.assertEqual(first, second)
        self.assertIn(first[0]["baseType"], candidates[("plant", "core-guard")])

    def test_existing_binding_is_preserved_but_invalid_binding_refuses(self):
        candidates = {("plant", "core-guard"): ("item.plant-core-a-001",)}
        bound = seedfile_mod.bind_member_base_types(
            "set.proof-001", [{"role": "core-guard", "frame": "plant",
                              "baseType": "item.plant-core-a-001"}], candidates)
        self.assertEqual(bound[0]["baseType"], "item.plant-core-a-001")
        with self.assertRaises(ValueError):
            seedfile_mod.bind_member_base_types(
                "set.proof-001", [{"role": "core-guard", "frame": "plant",
                                  "baseType": "item.other-001"}], candidates)

    def test_missing_role_frame_pair_is_a_refusal_not_an_invented_id(self):
        with self.assertRaises(ValueError):
            seedfile_mod.bind_member_base_types(
                "set.proof-001", [{"role": "core-guard", "frame": "humanoid"}], {})

    def test_a_second_batch_does_not_erase_the_first_batchs_ledger_entries(self):
        """⛔ Real incident, 2026-09-08: a live full run persisted 24 sets and wrote a ledger with
        those 24 subject ids. A CONTINUATION run (freeing up one colliding subject for retry, then
        re-invoking `items generate --write` — the exact resumable-batch workflow this ledger
        exists for) came back reporting the same 24-persisted/29-escalated shape, and the ledger on
        disk afterward had ONLY 24 entries again, but a DIFFERENT 24 than the first run's — several
        subjects the first run had legitimately persisted (and whose seed files were still
        correctly on disk, untouched) had silently vanished from the ledger. Root cause: `run_batch`
        starts `done = {}` fresh every call and `write_ledger` does a full overwrite — so a batch
        that (correctly) skips already-done subjects never re-adds them to `done`, and the ledger
        write erases them. A THIRD run would then treat those subjects as never-generated and
        redo (and overwrite) them. Proven directly: two `run_batch` calls against the SAME ledger
        path, second call's plan containing only a DIFFERENT subject, must leave BOTH subjects'
        entries in the ledger afterward."""
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "sets"
            ledger_path = out / "ledger.json"
            first_plan = _set_plan(1)
            first_id = first_plan.subjects[0].subject_id
            authored_mod.run_batch(
                plan=first_plan,
                answers=_answer_file("set", "build", {first_id: _clean_set_answer()}),
                tuning=TUNING, vocabulary=VOCAB, out_dir=out, kind="set", population="build",
                authored_utc="1970-01-01T00:00:00Z", model="fixture", ledger_path=ledger_path)

            second_theme = Theme(
                theme_key="build.might-defense", species_id=None,
                display_name="Might / Defense", motifs=("might", "guard"), anti_motifs=(),
                expression_item="stat emphasis and threshold shape", basis="derived", rarity=None,
                retired=False, population="build", aptitude="Might", archetype="defense")
            second_subject = Subject(
                subject_id="set-build-build.might-defense", kind="set", population="build",
                theme_key=second_theme.theme_key,
                entry_id=emit.build_set_id("might", "defense", 1),
                brief=brief_mod.build_set_brief(second_theme, TUNING, VOCAB))
            second_plan = RunPlan(subjects=[second_subject], held=[], already_done=[first_id])
            authored_mod.run_batch(
                plan=second_plan,
                answers=_answer_file("set", "build",
                                     {second_subject.subject_id: _clean_set_answer()}),
                tuning=TUNING, vocabulary=VOCAB, out_dir=out, kind="set", population="build",
                authored_utc="1970-01-01T00:00:00Z", model="fixture", ledger_path=ledger_path)

            final_ledger = json.loads(ledger_path.read_text(encoding="utf-8"))["done"]
            self.assertIn(first_id, final_ledger,
                         "the first batch's subject must survive a second batch's ledger write")
            self.assertIn(second_subject.subject_id, final_ledger)
            self.assertTrue((out / "might-offense.json").exists(),
                            "the first batch's seed file must not be touched by the second batch")

    def test_a_charm_batch_mints_its_id_from_the_axis_the_model_chose(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "charms"
            plan = _charm_plan()
            subject_id = plan.subjects[0].subject_id
            result = authored_mod.run_batch(
                plan=plan,
                answers=_answer_file("charm", "species", {subject_id: _clean_charm_answer()}),
                tuning=TUNING, vocabulary=VOCAB, out_dir=out, kind="charm", population="species",
                authored_utc="1970-01-01T00:00:00Z", model="fixture")
            self.assertEqual(len(result.persisted), 1, result.to_dict())
            entry = result.entries[0]
            self.assertTrue(entry["id"].startswith("charm.surv-util-"), entry["id"])
            self.assertEqual(entry["apCost"], TUNING.charm_class("minor").ap_cost,
                             "apCost is derived from the class, never taken from the answer")

    def test_a_second_charm_batch_preserves_the_first_partitions_rows(self):
        """A continuation may add a charm, never replace its partition with that one row."""
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "charms"
            plan = _charm_plan()
            subject_id = plan.subjects[0].subject_id
            answers = _answer_file("charm", "species", {subject_id: _clean_charm_answer()})
            first = authored_mod.run_batch(
                plan=plan, answers=answers, tuning=TUNING, vocabulary=VOCAB, out_dir=out,
                kind="charm", population="species", authored_utc="1970-01-01T00:00:00Z",
                model="fixture", corpus_root=Path(tmp))
            second_answers = _answer_file(
                "charm", "species", {subject_id: {**_clean_charm_answer(), "name": "Proof Charm Two"}})
            second = authored_mod.run_batch(
                plan=plan, answers=second_answers, tuning=TUNING, vocabulary=VOCAB, out_dir=out,
                kind="charm", population="species", authored_utc="1970-01-01T00:00:00Z",
                model="fixture", corpus_root=Path(tmp))

            target = second.files[0]
            entries = json.loads(target.read_text(encoding="utf-8"))["entries"]
            self.assertEqual({entry["id"] for entry in entries},
                             {first.entries[0]["id"], second.entries[0]["id"]})

    def test_a_signets_drawback_is_marked_negative_the_way_the_corpus_marks_it(self):
        """`charm.econ-019` writes its cost as `params.sign = "negative"` on an ordinary fixed
        atom. Emitting it unmarked would turn a signet's cost into a second bonus."""
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            plan = _charm_plan()
            families = _legal_charm_families()
            answer = {**_clean_charm_answer(), "charmClass": "signet",
                      "families": [families[0]], "drawback": {"family": families[1]}}
            result = authored_mod.run_batch(
                plan=plan,
                answers=_answer_file("charm", "species", {plan.subjects[0].subject_id: answer}),
                tuning=TUNING, vocabulary=VOCAB, out_dir=Path(tmp) / "charms", kind="charm",
                population="species", authored_utc="1970-01-01T00:00:00Z", model="fixture")
            self.assertEqual(len(result.persisted), 1, result.to_dict())
            atoms = result.entries[0]["fixedAtoms"]
            self.assertEqual(atoms[-1]["family"], families[1])
            self.assertEqual(atoms[-1]["params"]["sign"], "negative")
            self.assertNotIn("sign", atoms[0].get("params", {}))

    def test_a_refused_draft_with_no_repair_escalates_that_subject_only(self):
        """One subject running out of attempts must not take the batch with it."""
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            plan = _set_plan(2)
            bad = {**_clean_set_answer(),
                   "thresholds": [{"pieces": 2},
                                  {"pieces": 4, "families": [sorted(distribute.MORE_OP_FAMILIES)[0]]}]}
            mapping = {plan.subjects[0].subject_id: bad,
                       plan.subjects[1].subject_id: _clean_set_answer()}
            result = authored_mod.run_batch(
                plan=plan, answers=_answer_file("set", "build", mapping), tuning=TUNING,
                vocabulary=VOCAB, out_dir=Path(tmp) / "sets", kind="set", population="build",
                authored_utc="1970-01-01T00:00:00Z", model="fixture")
            outcomes = {o.subject_id: o for o in result.outcomes}
            first = outcomes[plan.subjects[0].subject_id]
            self.assertEqual(first.outcome, "escalated")
            self.assertTrue(any("More-op" in d for d in first.defects), first.defects)
            self.assertEqual(outcomes[plan.subjects[1].subject_id].outcome, "persisted")

    def test_a_blocked_answer_writes_nothing_and_is_reported(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            plan = _set_plan(subject_count=2)
            out = Path(tmp) / "sets"
            ledger_path = Path(tmp) / "ledger.json"
            first_id = plan.subjects[0].subject_id
            second_id = plan.subjects[1].subject_id
            result = authored_mod.run_batch(
                plan=plan,
                answers=_answer_file("set", "build", {
                    first_id: {"blocked": "no motifs land"},
                    second_id: _clean_set_answer(),
                }),
                tuning=TUNING, vocabulary=VOCAB, out_dir=out, kind="set",
                population="build", authored_utc="1970-01-01T00:00:00Z", model="fixture",
                ledger_path=ledger_path)
            self.assertEqual(result.outcomes[0].outcome, "blocked")
            self.assertEqual(result.outcomes[1].outcome, "persisted")
            done = json.loads(ledger_path.read_text(encoding="utf-8"))["done"]
            self.assertEqual(done[first_id]["outcome"], "blocked")
            self.assertIn(second_id, done)
            # Presence alone advances set/charm resume — both subjects are done.
            remaining = [s.subject_id for s in plan.subjects if s.subject_id not in done]
            self.assertEqual(remaining, [])

    def test_the_model_call_is_the_only_path_to_a_model(self):
        """A raising stub in `call` proves nothing else in the batch driver reaches an endpoint."""
        import tempfile

        def raising(*_args, **_kwargs):
            raise AssertionError("the batch driver reached a model outside the injected call")

        with tempfile.TemporaryDirectory() as tmp:
            plan = _set_plan()
            with self.assertRaises(AssertionError):
                authored_mod.run_batch(
                    plan=plan,
                    answers=_answer_file("set", "build",
                                         {plan.subjects[0].subject_id: _clean_set_answer()}),
                    tuning=TUNING, vocabulary=VOCAB, out_dir=Path(tmp) / "sets", kind="set",
                    population="build", authored_utc="1970-01-01T00:00:00Z", model="fixture",
                    call=raising)

    def test_the_report_names_every_gating_metric_even_when_it_did_not_run(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            plan = _set_plan()
            result = authored_mod.run_batch(
                plan=plan,
                answers=_answer_file("set", "build",
                                     {plan.subjects[0].subject_id: _clean_set_answer()}),
                tuning=TUNING, vocabulary=VOCAB, out_dir=Path(tmp) / "sets", kind="set",
                population="build", authored_utc="1970-01-01T00:00:00Z", model="fixture")
            named = {o.metric for o in result.report.outcomes}
            self.assertEqual(named, set(GATING_METRICS))
            self.assertIs(result.report.verdict, Verdict.NOT_MEASURED,
                          "a batch that could not run every gate is never a pass")

    def test_a_held_partition_alone_denies_a_pass(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            plan = _set_plan()
            plan.held = [("creature.something", "basis=name")]
            result = authored_mod.run_batch(
                plan=plan,
                answers=_answer_file("set", "build",
                                     {plan.subjects[0].subject_id: _clean_set_answer()}),
                tuning=TUNING, vocabulary=VOCAB, out_dir=Path(tmp) / "sets", kind="set",
                population="build", authored_utc="1970-01-01T00:00:00Z", model="fixture")
            self.assertEqual(result.report.held_partitions, ["creature.something"])
            self.assertIs(result.report.verdict, Verdict.NOT_MEASURED)


class Module13DefectsFixedTests(unittest.TestCase):
    """⭐ Five defects were measured in module 13's OWN machinery on 2026-09-06 while wiring the
    graph, pinned here as "this is the state today", and **fixed on the same day**. Each test below
    now asserts the FIXED state with the same defect number, so a regression reads as the original
    defect coming back rather than as an anonymous failure.

    The before-numbers are kept in the docstrings on purpose: they are the measurement, and a fix
    whose evidence has been deleted cannot be re-checked.
    """

    def test_the_charm_brief_offers_exactly_the_pool_the_distributor_accepts(self):
        """DEFECT 1, FIXED. `build_charm_brief` printed `vocabulary.stat` truncated to the first 60
        of 242 picks, while `distribute_charm` accepted 56 picks across 14 families — every one
        armour or shield. Brief and distributor now read the same expression,
        `charmgen.rules.charm_pool`, and it is printed whole."""
        pool = charm_rules.charm_pool(TUNING, VOCAB.all_picks)
        shown = brief_mod.build_charm_brief(_species_theme(), TUNING, VOCAB)
        self.assertGreater(len(pool), 56)
        for pick in pool:
            self.assertIn(f"  - {pick.pick_id}\n", shown + "\n")
        self.assertNotIn("...and", shown, "the charm pool is never truncated")
        excluded = graph_mod.jewel_minor_for(TUNING, VOCAB)
        for pick in VOCAB.all_picks:
            if pick.family in excluded or pick.family in charm_rules.NON_FLAT_FAMILIES:
                with self.subTest(pick=pick.pick_id):
                    self.assertNotIn(f"  - {pick.pick_id}\n", shown + "\n")

    def test_a_charm_on_every_one_of_the_five_axes_is_authorable_from_the_brief(self):
        """DEFECT 1's consequence, FIXED. The surviving pool was 14 families, all defensive, so
        `offense` / `control` / `utility` / `economy` were unauthorable — four of the five axes in
        the historical 70-row corpus, covering 48 of those rows. The pool now spans every tag the
        family corpus has."""
        pool = charm_rules.charm_pool(TUNING, VOCAB.all_picks)
        families = {p.family for p in pool}
        self.assertIn("atom.might", families, "an offense charm needs an offense family")
        self.assertIn("atom.midas", families, "an economy charm needs an economy family")
        self.assertIn("atom.cleansing", families, "a utility charm needs a utility family")
        self.assertIn("atom.vitality", families, "a survivability charm needs a defensive family")
        # ssot-charms §3.6's own charm family list, every one of which the old rule refused.
        for named in ("atom.vitality", "atom.might", "atom.mending", "atom.regeneration",
                      "atom.sunbloom", "atom.midas", "atom.cleansing"):
            with self.subTest(family=named):
                self.assertIn(named, families)

    def test_the_charm_pool_now_covers_the_families_the_shipped_corpus_uses(self):
        """DEFECT 2, FIXED. 22 of the 29 distinct families in the historical 70-row corpus are
        CAPABILITY families; the brief offered `vocabulary.stat` only, so a generated population
        could not resemble the authored one. The pool is drawn from both buckets now.

        ⚠ Two named divergences survive on purpose and are asserted rather than smoothed away:
        three families the historical corpus uses are declared by no `affix-families/*.json` file,
        and 11 of its families are ssot-charms §3.6's ring layer — 20 historical rows, which are
        shipped content standing against §3.6, not a generator defect. The generator
        refuses to author more of it; changing the corpus is a separate, content-owning decision.
        """
        charms_dir = _owned("data/seed/items/charms")
        used: "set[str]" = set()
        rows_on_ring = 0
        for path in sorted(charms_dir.glob("*.json")):
            doc = json.loads(path.read_text(encoding="utf-8"))
            for entry in doc.get("entries") or []:
                for atom in entry.get("fixedAtoms") or []:
                    used.add(atom["family"])
        capability = {p.family for p in VOCAB.capability}
        stat = {p.family for p in VOCAB.stat}
        self.assertTrue(used & capability)
        self.assertTrue(used & stat)
        undeclared = used - capability - stat
        self.assertEqual(undeclared, {"atom.commanding", "atom.exposing", "atom.rallying"},
                         "three charm families are declared by no affix-family file")
        pool = {p.family for p in charm_rules.charm_pool(TUNING, VOCAB.all_picks)}
        ring = charm_rules.ring_layer_families(TUNING, VOCAB.all_picks)
        self.assertEqual(used - undeclared - pool, used & ring,
                         "the only shipped families the pool omits are §3.6's ring layer")
        self.assertTrue(ring)
        self.assertTrue(used & ring)
        for path in sorted(charms_dir.glob("*.json")):
            doc = json.loads(path.read_text(encoding="utf-8"))
            for entry in doc.get("entries") or []:
                if any(a["family"] in ring for a in entry.get("fixedAtoms") or []):
                    rows_on_ring += 1
        self.assertGreater(rows_on_ring, 0, "legacy rows standing against §3.6 remain measured")

    def test_the_set_brief_names_the_derived_piece_counts_and_the_schema_agrees(self):
        """DEFECT 3, FIXED. The schema offered `pieces` from `[2, 3, 4, 6]` and the brief said
        "the piece counts", while `threshold_ladder` derived `(2, 4)` from the member count and
        refused everything else — all three sets in the first real batch picked 3 and were refused.
        The enum, the row count and the brief all read the ladder now."""
        ladder = distribute.threshold_ladder(TUNING, TUNING.typical_members)
        self.assertEqual(ladder, (2, 4))
        node = schema_mod.set_schema(TUNING, vocabulary=VOCAB)["properties"]["thresholds"]
        self.assertEqual(node["items"]["properties"]["pieces"]["enum"], [2, 4])
        self.assertEqual((node["minItems"], node["maxItems"]), (2, 2))
        text = brief_mod.build_set_brief(_build_theme(), TUNING, VOCAB)
        self.assertIn("exactly 2 entries, at 2 and 4 pieces", text)
        self.assertIn("not yours to choose", text)

    def test_a_five_member_set_is_authorable(self):
        """DEFECT 4, FIXED. `threshold_ladder(5)` was `(2,)` — one threshold — against a schema
        that required `minItems: 2`, so a five-member set could satisfy neither, and nothing refused
        the member count either. §3.4 says the top threshold is `<=` the member count, not `=`, so
        the ladder now takes the highest legal count the set can reach.

        The two-member end is fixed by the same change from the other side: its ladder is legitimately
        one row, and the schema is now sized from the ladder instead of assuming two.
        """
        self.assertEqual(distribute.threshold_ladder(TUNING, 5), (2, 4))
        five = schema_mod.set_schema(TUNING, vocabulary=VOCAB, member_count=5)["properties"]["thresholds"]
        self.assertEqual((five["minItems"], five["maxItems"]), (2, 2))
        self.assertEqual(five["items"]["properties"]["pieces"]["enum"], [2, 4])
        two = schema_mod.set_schema(TUNING, vocabulary=VOCAB, member_count=2)["properties"]["thresholds"]
        self.assertEqual((two["minItems"], two["maxItems"]), (1, 1))
        for count in (2, 3, 4, 5, 6):
            with self.subTest(members=count):
                ladder = distribute.threshold_ladder(TUNING, count)
                node = schema_mod.set_schema(TUNING, vocabulary=VOCAB, member_count=count)["properties"]["thresholds"]
                self.assertEqual(node["minItems"], len(ladder))
                self.assertEqual(node["items"]["properties"]["pieces"]["enum"], list(ladder))

    def test_cell_occupancy_reads_the_element_the_corpus_actually_writes(self):
        """DEFECT 5, FIXED. `cells.threshold_capability` read a `variant` key; the corpus writes
        `params.element` (`set.frostbitten-vanguard-002`/`-003`, `set.sunwoven-almanac-003`), so
        `atom.deathblast.fire` and `atom.deathblast.ice` collapsed into one cell.

        ⚠ Found while fixing it, and fixed with it: `threshold_families` dropped the element the
        same way, on the higher-threshold atoms — which is where a GENERATED set puts most of its
        element-narrowed picks.
        """
        fire = {"family": "atom.deathblast", "powerBand": "low", "params": {"element": "fire"}}
        ice = {"family": "atom.deathblast", "powerBand": "low", "params": {"element": "ice"}}
        self.assertEqual(cells.threshold_capability({"capability": fire}), "atom.deathblast.fire")
        self.assertEqual(cells.threshold_capability({"capability": ice}), "atom.deathblast.ice")
        self.assertEqual(cells.threshold_families({"atoms": [fire, ice]}),
                         ("atom.deathblast.fire", "atom.deathblast.ice"))
        # The generator's own internal spelling still resolves — both shapes are read.
        self.assertEqual(cells.threshold_capability(
            {"capability": {"family": "atom.deathblast", "variant": "fire"}}),
            "atom.deathblast.fire")
        both = [{"thresholds": [{"pieces": 2, "capability": fire}]},
                {"thresholds": [{"pieces": 2, "capability": ice}]}]
        self.assertEqual(cells.cell_report(both).cells, 2,
                         "two elements of one family are two cells, not one")

    def test_the_axis_gini_report_names_its_own_floor(self):
        """Found while re-sampling the fixes, and fixed with them (not one of the five).

        Three charms over five axes is `[1,1,1,0,0]` at best — **400‰, against a 133‰ ceiling** —
        so the first sample's *"axis Gini 800‰ against a 133‰ ceiling"* and a perfectly diverse
        batch's *"400‰ against a 133‰ ceiling"* read identically, though one is a total collapse and
        the other is as flat as `n` allows. The floor is reported beside the measurement, the way
        `SemanticDedup/NearDuplicate` already says "granularity-bound below ~200 entries".
        """
        self.assertEqual(charm_rules.min_axis_gini_permille(1), 800)
        self.assertEqual(charm_rules.min_axis_gini_permille(3), 400)
        self.assertEqual(charm_rules.min_axis_gini_permille(5), 0)
        self.assertEqual(charm_rules.min_axis_gini_permille(0), 0)
        self.assertEqual(
            charm_rules.smallest_measurable_axis_population(TUNING.charm_axis_gini_max_permille), 5)
        # A one-axis collapse and a maximally spread batch must not print the same line.
        collapsed = charm_rules.axis_gini_permille(["survivability"] * 3)
        spread = charm_rules.axis_gini_permille(["offense", "control", "economy"])
        self.assertEqual((collapsed, spread), (800, 400))

    def test_the_element_read_does_not_move_the_shipped_corpus_numbers(self):
        """The same fix, measured where it matters: the live set corpus reports identically before
        and after, so the gate baseline does not move. Latent at 30 sets, real at ~904.

        30 -> 32 on 2026-09-07: the set-charm-live-endpoint trial batch added 2 real sets
        (set.retribution-offense-001/-002, a real build.* theme with no prior generated content),
        each landing in its own new cell — 28 -> 30 cells, 26 -> 28 singletons, max unchanged.

        32 -> 56 on 2026-09-08: the first real `items generate --write` batch against a live local
        model (`google/gemma-4-26b-a4b-qat`), after fixing the four real defects the run itself
        found that day (brief truncation, `resolve_capability`'s family/variant shape mismatch,
        the schema's `required: []` silently suppressing `name`/`flavor` under grammar-constrained
        decoding, and the lowest threshold being validated against the stat vocabulary it was
        never supposed to carry) — 24 subjects persisted, each its own new cell: 30 -> 53 cells,
        28 -> 50 singletons, max unchanged.

        56 -> 58 same day: a continuation run (freeing one exact-name collision, `'Triple-Line
        Volley'` on both `creature.allpeater` and `creature.threepeater`, for a fresh regenerate) hit a
        FIFTH real bug the same run found — `authored.run_batch` starting `done = {}` fresh every
        call and `write_ledger` doing a full overwrite meant the continuation's own ledger write
        erased the first run's entries outright (their seed files stayed on disk, untouched, but a
        third run would have redone and overwritten them). Fixed by merging with the on-disk
        ledger before writing. The continuation net-added 2 entries, each its own new cell:
        53 -> 55 cells, 50 -> 52 singletons, max unchanged.

        58 -> 61 same day: chasing that same regenerate down turned up a SIXTH real bug —
        `cmd_items` passed `ledger=None` to `plan_run` whenever `--ignore-ledger` was not given,
        which read a hardcoded default ledger path completely disconnected from the one
        `--write` actually reads/writes, so every invocation replanned the FULL population
        (`"alreadyDone": 0` always) regardless of what earlier runs had already persisted. Fixed
        in `cmd_items` to read the same `<out-dir>/set-charm-gen.ledger.json` `--write` uses. That
        fixed run itself net-added 3 more subjects, and separately reproduced 'Triple-Line
        Volley' again (this model converges on the same name for near-identical `species` themes
        at `temperature=0.2`) plus a second such collision, `'Glacial Spike Volley'` on
        `creature.snowgatling`/`creature.snowpeashooter` — both resolved by re-running just those two
        subjects through `run_batch`'s existing injectable `call` at `temperature=0.9`, no
        schema/CLI change needed. Measured directly, not derived: 55 -> 59 cells, 52 -> 57
        singletons, max unchanged."""
        entries = []
        for path in sorted((_owned("data/seed/items/sets")).glob("*.json")):
            doc = json.loads(path.read_text(encoding="utf-8"))
            entries.extend(doc.get("entries") or [])
        report = cells.cell_report(entries)
        self.assertEqual(report.population, len(entries))
        self.assertGreater(report.cells, 0)
        self.assertLessEqual(report.median, TUNING.median_cell_occupancy_max)


class SetIsDistributableMissingPiecesTests(unittest.TestCase):
    """⛔ Real bug, found 2026-09-08 on a live run against `meta/muse-glimmer`: a threshold with no
    `pieces` at all crashed `int(None)` uncaught inside `_resolved_stats`, aborting the WHOLE batch
    (every remaining subject, not just this one bad draft) instead of reporting a named defect for
    the self-heal loop. `google/gemma-4-26b-a4b-qat` never happened to produce this shape in any
    prior run, so nothing caught it until a different model did."""

    def test_a_threshold_missing_pieces_is_a_named_defect_not_a_crash(self):
        answer = {**_clean_set_answer(),
                 "thresholds": [{"families": [_legal_set_stat()]}, {"pieces": 4}]}
        defects = graph_mod.set_is_distributable(answer, {"tuning": TUNING, "vocabulary": VOCAB})
        self.assertTrue(any("pieces" in d for d in defects), defects)

    def test_a_threshold_with_a_null_pieces_is_a_named_defect_not_a_crash(self):
        answer = {**_clean_set_answer(),
                 "thresholds": [{"pieces": None, "families": [_legal_set_stat()]},
                                {"pieces": 4}]}
        defects = graph_mod.set_is_distributable(answer, {"tuning": TUNING, "vocabulary": VOCAB})
        self.assertTrue(any("pieces" in d for d in defects), defects)

    def test_a_boolean_pieces_is_rejected_not_silently_treated_as_0_or_1(self):
        answer = {**_clean_set_answer(),
                 "thresholds": [{"pieces": True, "families": [_legal_set_stat()]},
                                {"pieces": 4}]}
        defects = graph_mod.set_is_distributable(answer, {"tuning": TUNING, "vocabulary": VOCAB})
        self.assertTrue(any("pieces" in d for d in defects), defects)

    def test_a_well_formed_threshold_is_unaffected_by_the_guard(self):
        by_threshold, defects = graph_mod._resolved_stats(_clean_set_answer(), VOCAB)
        self.assertEqual(defects, [])
        self.assertIn(4, by_threshold)

    def test_the_lowest_threshold_carrying_families_anyway_is_not_a_defect(self):
        """⛔ Real incident, 2026-09-08: even after the brief-truncation and `resolve_capability`
        fixes, a live run kept escalating on `thresholds[2].families: 'atom.volley' is not a stat
        family` — the model reused its OWN `capability` pick inside the LOWEST threshold's
        `families`, exactly the field the brief tells it "takes no families — it carries the
        capability". The schema now lets a model answer `null` there (the 2026-09-08
        required+nullable fix), but a model that instead echoes its capability pick anyway is not
        wrong about anything the distributor actually uses — `_resolved_stats` already ignores the
        lowest threshold's families when building `by_threshold` (nothing reads it), so validating
        it against the STAT vocabulary only punishes a field that carries no real content, exactly
        as `set_schema`'s own field description already says."""
        answer = {**_clean_set_answer(),
                 "thresholds": [{"pieces": 2, "families": [_legal_capability()]},
                                {"pieces": 4, "families": [_legal_set_stat()]}]}
        by_threshold, defects = graph_mod._resolved_stats(answer, VOCAB)
        self.assertEqual(defects, [])
        self.assertNotIn(2, by_threshold)

    def test_an_empty_members_list_is_a_named_defect_not_a_crash(self):
        """⛔ A second real bug, found 2026-09-08 on the SAME live run, minutes after the first:
        an empty `members` list reached `distribute_set` -> `tuning.set_budget_milli`, which
        raises `SetCharmTuningError('a set has at least one member, got 0')` uncaught — the
        identical crash-the-whole-batch failure shape, a different unguarded precondition.
        `set_is_distributable` now catches `SetCharmTuningError` generally rather than needing a
        third live crash to find the next one."""
        answer = {**_clean_set_answer(), "members": []}
        defects = graph_mod.set_is_distributable(answer, {"tuning": TUNING, "vocabulary": VOCAB})
        self.assertTrue(any("member" in d for d in defects), defects)


class OverwriteIsHonouredOrRefusedTests(unittest.TestCase):
    """⛔ A flag that is accepted and silently ignored is the most expensive kind of CLI defect.

    Measured 2026-09-28: `items generate --kind set --overwrite set.abyssswordstar-001` reported
    `toGenerate: 60` and `plannedBeforeLimit: 60`. Naming ONE id planned 60 subjects, and nothing said
    the id had been dropped - so an operator asking to re-author one row would have paid for 60 and got
    60, with the summary reading like success.

    The cause is structural: `setgen.run.plan_run` takes no `overwrite` argument and setgen has no
    `plan_overwrite`, unlike `materialgen` which has one at `materialgen/run.py:104`. The flag's own
    `--help` documents it for `base-type` / `enhancement-milestone` / `recipe` / `drop-table` and for
    `combination` - never for `set` or `charm` - so it is an unkept argument rather than a broken promise,
    and the fix is a refusal rather than a feature. Nothing needs the feature: the natural set/charm plan
    is already the closure plan (60 subjects for `--population species` covering 60 of the 61 empty
    `sets/*` partitions, plus 1 for `--population build`), so the actionable advice is the population.

    **The assertion is a property over every accepted kind**, not the set/charm instance: `--overwrite`
    must be honoured or refused, never dropped. A test naming only `set` would pass while the same defect
    sat in the next kind's branch, which is exactly how this one was found - by reading which branches
    forward the flag, and finding the one that did not.
    """

    #: Kinds whose branch forwards or honours `--overwrite` today. `material` and `trophy` reach
    #: `_cmd_items_generate_passthrough`, which passes it to the child module; `combination` reads it via
    #: `getattr(args, "overwrite", "")` and narrows its grid subjects.
    HONOURED = ("base-type", "enhancement-milestone", "recipe", "drop-table", "gem", "material",
                "consumable", "affix-family", "trophy", "combination")
    #: Kinds that must REFUSE it. FAIL-BEFORE: these planned the whole population and said nothing.
    REFUSED = ("set", "charm")

    def test_set_and_charm_refuse_an_overwrite_they_cannot_honour(self) -> None:
        """FAIL-BEFORE: the run exited 0 after planning 60 subjects, having ignored the id entirely.

        Driven through `main()` because the refusal lives in `cmd_items`, and asserting on the CHANNEL a
        real operator sees: the message goes to stderr and the exit is non-zero. A refusal printed to
        stdout, or exiting 0, would both read as "it worked" to a human and to a script.
        """
        import contextlib
        import io
        from seedsmith.report import cli as cli_mod

        for kind in self.REFUSED:
            argv = ["items", "generate", "--kind", kind, "--overwrite", "set.abyssswordstar-001"]
            out, err = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = cli_mod.main(argv)
            self.assertEqual(code, cli_mod.EXIT_CANNOT_RUN,
                             f"FAIL-BEFORE: --kind {kind} exited {code} after being handed an "
                             f"--overwrite it cannot honour")
            self.assertNotIn("toGenerate", out.getvalue(),
                             "a refused run must not print a plan summary; that is what made the "
                             "silently-ignored version read as success")
            message = err.getvalue()
            self.assertIn("does not support --overwrite", message,
                          f"the refusal must name the problem, got: {message[:200]}")
            self.assertIn("set.abyssswordstar-001", message,
                          "the refusal must echo the value that would have been ignored, so the "
                          "operator can see their own argument")

    def test_the_refusal_names_the_kinds_that_do_support_it(self) -> None:
        """A refusal with no alternative is half a fix, and this one has a concrete alternative."""
        import contextlib
        import io
        from seedsmith.report import cli as cli_mod

        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            cli_mod.main(["items", "generate", "--kind", "set", "--overwrite", "x"])
        message = err.getvalue()
        for kind in ("material", "combination", "base-type"):
            self.assertIn(kind, message,
                          f"the refusal must name {kind!r} as a kind that does support --overwrite, "
                          f"got: {message[:200]}")
        self.assertIn("--population", message,
                      "the refusal must point at --population, since the natural plan is already the "
                      "closure plan and the population is how it is scoped")

    def test_no_accepted_kind_silently_drops_the_flag(self) -> None:
        """The property, over EVERY kind the CLI accepts.

        Reads the source rather than executing twenty plans: the defect is a branch that never consults
        the flag, so the check that catches a NEW instance is "the router consults it at all". A kind that
        honours it consults it in a forward or a narrowing; a kind that refuses it consults it in the
        refusal. A kind that consults it NOWHERE is the bug.

        Both spellings count, because the router legitimately uses each: `getattr(args, "overwrite", "")`
        where an argument may be absent from a sub-parser's namespace, and plain `args.overwrite` where
        the argument is certain to exist. Asserting one spelling would have failed the fix for choosing the
        other, which is the same "right value, wrong question" trap this suite's own history records.
        """
        import ast
        import inspect
        from seedsmith.report import cli as cli_mod

        tree = ast.parse(inspect.getsource(cli_mod))
        router = next((n for n in ast.walk(tree)
                       if isinstance(n, ast.FunctionDef) and n.name == "cmd_items"), None)
        self.assertIsNotNone(router, "cmd_items is the router; this test needs it by name")

        consulted = False
        for node in ast.walk(router):
            # `args.overwrite` / `args.some_overwrite_thing`
            if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) \
                    and node.value.id == "args" and "overwrite" in node.attr:
                consulted = True
            # `getattr(args, "overwrite", ...)`
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) \
                    and node.func.id == "getattr" and len(node.args) >= 2:
                if isinstance(node.args[0], ast.Name) and node.args[0].id == "args" \
                        and isinstance(node.args[1], ast.Constant) \
                        and isinstance(node.args[1].value, str) \
                        and "overwrite" in node.args[1].value:
                    consulted = True
        self.assertTrue(
            consulted,
            "FAIL-BEFORE: cmd_items never consulted args.overwrite at all, so every kind routed through "
            "it silently dropped the flag")

        literals = " ".join(
            ast.unparse(n) for n in ast.walk(router)
            if isinstance(n, ast.Constant) and isinstance(n.value, str))
        for kind in self.REFUSED:
            self.assertIn(kind, literals,
                          f"{kind!r} must appear in the router's refusal message, so an operator who "
                          f"passed --overwrite for it is told which kinds do accept one")
        for kind in ("material", "combination", "base-type"):
            self.assertIn(kind, literals,
                          f"{kind!r} honours --overwrite and must be named in the refusal's supported "
                          f"list, or the message sends the operator to a kind that ignores it")


class MaterialPassthroughKnobTests(unittest.TestCase):
    """⛔ THIRD instance of this programme's most expensive CLI defect: a named knob that never reaches the
    work. This one is about the passthrough, so the flag cannot even be typed.

    Measured 2026-09-28 on a live re-emit. `--max-name-attempts` is the only control over the re-emit's
    yield, because every refusal that pass exists to resolve is a NAME collision: at the generator's
    default of 3 attempts a refused subject keeps its old colliding name and its gap stays open. The flag
    was on `materialgen.run`'s own argparse, and `_cmd_items_generate_passthrough` forwarded neither it nor
    `--max-consecutive-call-failures`, so `seedsmith items generate --kind material` could not reach
    either.

    It surfaced as a **live** failure that reads like something else. The runner reported
    `REFUSED [batch-1] batch 1 of 108 exited 2 after 0 ids were written` - which looks like a wedged
    endpoint or a schema problem, and cost a diagnostic cycle before the cause was read off the exit code.
    2 is argparse's "unrecognized arguments", and 0 ids written is the tell that nothing was ever spent.

    The first two instances were `--overwrite` on `--kind set`/`charm` (accepted, then ignored) and
    `basetypegen`'s partition-name guard reading a registry `check` never consults. Same shape each time:
    something between the operator's intent and the work drops it quietly. **A knob is only a control if
    the whole path carries it**, which is why this asserts the child argv rather than the parser alone.
    """

    ARGV = ["items", "generate", "--kind", "material", "--overwrite", "trophy.species.a.1", "--write"]

    def _child_argv(self, extra: "list[str]") -> "list[str]":
        """The argv the passthrough hands the generator, captured without generating anything.

        The passthrough dispatches in-process - `cli.py` ends it with `return mod.main(passthrough)` - so
        the capture replaces that module's own `main`. No plan is built and no model is reached.
        """
        import contextlib
        import importlib
        import io
        from seedsmith.report import cli as cli_mod

        args = cli_mod.build_parser().parse_args(self.ARGV + extra)
        mod = importlib.import_module(cli_mod._PASSTHROUGH_MODULE_BY_KIND[args.kind],
                                      package=cli_mod.__package__)
        captured: "list[str]" = []
        real_main = mod.main
        mod.main = lambda argv: (captured.extend(argv), 0)[1]
        try:
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                cli_mod._cmd_items_generate_passthrough(args)
        finally:
            mod.main = real_main
        return captured

    def test_max_name_attempts_reaches_the_generator(self) -> None:
        argv = self._child_argv(["--max-name-attempts", "10"])
        self.assertIn("--max-name-attempts", argv,
                      "FAIL-BEFORE: the flag was rejected by the parser with exit 2, so the child could "
                      "never see it and an operator had no lever on the yield")
        self.assertEqual(argv[argv.index("--max-name-attempts") + 1], "10",
                         "the value asked for must be the value forwarded, not a default")

    def test_max_consecutive_call_failures_reaches_the_generator_too(self) -> None:
        """The same gap, second flag. It has been on the generator's parser since 2026-09-08 and was
        equally unreachable, so a wedged endpoint could not be bounded from the CLI."""
        argv = self._child_argv(["--max-consecutive-call-failures", "3"])
        self.assertIn("--max-consecutive-call-failures", argv)
        self.assertEqual(argv[argv.index("--max-consecutive-call-failures") + 1], "3")

    def test_an_explicit_zero_is_forwarded_rather_than_treated_as_unset(self) -> None:
        """`if args.x:` would swallow 0, and 0 is a real request in both cases: no re-ask at all, and never
        stop on call failures. Swallowing it would leave the operator believing they had disabled a retry
        while the default of 3 kept running - and spending calls on it."""
        for flag in ("--max-name-attempts", "--max-consecutive-call-failures"):
            argv = self._child_argv([flag, "0"])
            self.assertIn(flag, argv, f"{flag} 0 must be forwarded, not dropped as falsy")
            self.assertEqual(argv[argv.index(flag) + 1], "0")

    def test_omitting_them_leaves_the_generators_own_defaults_alone(self) -> None:
        """The common case must not pin the child's behaviour: an unpassed flag stays unpassed, so the
        generator's own defaults apply exactly as if its script had been invoked directly."""
        argv = self._child_argv([])
        for flag in ("--max-name-attempts", "--max-consecutive-call-failures"):
            self.assertNotIn(flag, argv,
                             f"{flag} must be absent when the operator did not ask for it, not injected "
                             f"with a value this command invented")

    def test_they_do_not_leak_into_another_kinds_branch(self) -> None:
        """The forwarding is gated on `--kind material`, because no sibling module has these flags and
        forwarding them there would hand a child an argument its own parser rejects - the same exit-2
        failure, one kind over."""
        import contextlib
        import importlib
        import io
        from seedsmith.report import cli as cli_mod

        args = cli_mod.build_parser().parse_args(
            ["items", "generate", "--kind", "gem", "--slot", "1", "--write",
             "--max-name-attempts", "10"])
        mod = importlib.import_module(cli_mod._PASSTHROUGH_MODULE_BY_KIND[args.kind],
                                      package=cli_mod.__package__)
        captured: "list[str]" = []
        real_main = mod.main
        mod.main = lambda argv: (captured.extend(argv), 0)[1]
        try:
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                cli_mod._cmd_items_generate_passthrough(args)
        finally:
            mod.main = real_main
        self.assertNotIn("--max-name-attempts", captured,
                         "gemgen has no such flag; forwarding it would make its own argparse exit 2")


if __name__ == "__main__":
    unittest.main()
