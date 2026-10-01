"""Cross-corpus name blindness in the materials generator: the fail-before/pass-after pair.

⛔ The defect, measured 2026-09-28. `materialgen`'s name gate compared an authored name only against the
MATERIALS corpus. A `charm.*` or a `droptable.*` holding the same name was invisible to it, so the answer
was persisted; and because the re-ask brief is built from the same blind view, re-asking returned the SAME
name and re-persisted it. A targeted pass over exactly those 4 ids reported "PERSISTED 3 refused 1" and left
all 4 byte-identical.

Evidence that this is WIRING and not a model limit, because the two have opposite fixes: 2,123 of 3,633
names in the same run did change (584 per mille) and all 4 of these did change relative to the rescue ref.
The model was varying names fine. It was simply never told these four were taken, and the gate that
validated the answer could not see that either - so "more spending" and "more attempts" were both the wrong
lever, and the refusal budget was correctly reporting a limit that did not exist.

Each test names a PROPERTY, not a mechanism, and the fixture is a real `items/` tree (`materials/`, `charms/`,
`_runs/`) because the defect is about which file is excluded - a flat one-file fixture cannot tell a correct
skip from a broken one, which is how the earlier doubled-path bug passed its own review.
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

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

sys.path.insert(0, str(_owned("tools/seedsmith")))

from seedsmith.adapters.items.materialgen import run as run_mod  # noqa: E402
from seedsmith.pipeline import cross_corpus_names  # noqa: E402
from seedsmith.pipeline.run_ledger import RunLedger  # noqa: E402

#: A real issuable id, so `emit.build_entry` mints a genuine row. `shard.chaff` is used by the sibling
#: suite for the same reason: a fabricated id here would fail the vocabulary check and the test would pass
#: for the wrong reason.
SUBJECT = "shard.chaff"
CHARM_ID = "charm.surv-util-338"
CHARM_NAME = "Permafrost Core"


def _answer(name: str) -> dict:
    return {"name": name, "flavor": "A fixture, and it says so, in one full sentence.", "tags": ["mineral"]}


class _TreeCase(unittest.TestCase):
    """A real `items/` tree, and a ledger of its OWN.

    `run_batch` defaults its ledger to the REPO's `gk-data/packs/fusion/data/seed/items/_runs/materials-gen.ledger.json`. A test
    that lets it would write the live 2,133-row ledger, so the temp ledger is not hygiene - it is the
    difference between a test and an incident.
    """

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.items = Path(self._tmp.name) / "items"
        (self.items / "materials").mkdir(parents=True)
        (self.items / "charms").mkdir(parents=True)
        (self.items / "_runs").mkdir(parents=True)
        self.materials_path = self.items / "materials" / "materials.json"
        self.ledger = RunLedger(self.items / "_runs" / "materials-gen.ledger.json")
        # A run ledger carries no `entries` list, so it must be skipped BY SHAPE. It also holds a real name,
        # so a shape-blind collector would invent a collision that does not exist.
        (self.items / "_runs" / "materials-gen.ledger.json").write_text(
            json.dumps({"done": {SUBJECT: {"name": "Ledger Only Name"}}, "schemaVersion": 1}), encoding="utf-8")

    def _charms(self, *names: str) -> None:
        (self.items / "charms" / "charms.json").write_text(
            json.dumps({"kind": "charm",
                        "entries": [{"id": CHARM_ID, "name": n} for n in names]}), encoding="utf-8")

    def _materials(self, *entries: dict) -> None:
        self.materials_path.write_text(
            json.dumps({"schemaVersion": 1, "kind": "material", "entries": list(entries)}), encoding="utf-8")

    def _plan(self):
        return run_mod.plan_run(materials_path=self.materials_path, ledger=self.ledger)

    def _batch(self, name: str):
        plan = self._plan()
        self.assertIn(SUBJECT, {s.subject_id for s in plan.subjects},
                      f"fixture problem: {SUBJECT} must be planned or this test proves nothing")
        result = run_mod.run_batch(plan, {SUBJECT: _answer(name)},
                                   materials_path=self.materials_path, ledger=self.ledger)
        # An empty materials corpus plans EVERY issuable id, so the batch carries `missing_answer`
        # outcomes too. Select this subject's outcome rather than assuming the batch holds one row -
        # unpacking the first outcome would be a check about a different subject.
        mine = [o for o in result.outcomes if o.subject_id == SUBJECT]
        self.assertEqual(len(mine), 1, "exactly one outcome must be recorded for the subject under test")
        return mine[0]


    def test_a_flat_corpus_path_does_not_make_the_gate_walk_an_arbitrary_tree(self) -> None:
        """⛔ Measured hang, from the first version of this. `run_batch(materials_path=...)` is a real
        parameter and the sibling suite passes a FLAT `tmp/materials.json`, so deriving the items root as
        `parent.parent` made the walk `rglob` the system temp tree: 25 tests passed in 3s, the 26th was
        still running after 15 minutes.

        Asserted on the RETURN, not on timing: a time-based assertion would be slow when it passes and
        unreliable when it does not, and the property is really "there is no items root here, so the
        walk does not happen".
        """
        flat = Path(self._tmp.name) / "materials.json"
        flat.write_text(json.dumps({"schemaVersion": 1, "kind": "material", "entries": []}), encoding="utf-8")
        owners, root = run_mod._cross_corpus_owners(flat)
        self.assertEqual(owners, {}, "a flat path has no items root, so no corpus is visible")
        self.assertIsNone(root, "and the absence must be REPORTED, not read as 'nothing collides'")

    def test_the_real_layout_does_resolve_an_items_root(self) -> None:
        """The control for the test above: the shape the corpus actually ships in must still work, or
        'skip when in doubt' has silently disabled the check in production."""
        owners, root = run_mod._cross_corpus_owners(self.materials_path)
        self.assertEqual(root, self.items.resolve(), "items/materials/materials.json must resolve to items")
        self.assertEqual(owners, {}, "no charm names seeded yet, so nothing is held")


class CrossCorpusNameGateTests(_TreeCase):
    """The generator must refuse a name another corpus already holds, and say whose it is."""

    def test_a_name_a_charm_already_holds_is_refused_and_the_holder_is_named(self) -> None:
        self._charms(CHARM_NAME)
        self._materials()
        out = self._batch(CHARM_NAME)
        self.assertEqual(out.outcome, "refused",
                         f"a name a charm already holds must not be persisted; defects={out.defects}")
        self.assertTrue(any(d.startswith(run_mod.CROSS_CORPUS_DEFECT_PREFIX) for d in out.defects),
                        f"FAIL-BEFORE: no cross-corpus defect was raised; got {out.defects}")
        self.assertIn(CHARM_ID, " ".join(out.defects),
                      "the refusal must NAME the other holder: that string is what the retry brief quotes "
                      "back to the model, and a bare count is why these 4 never cleared")

    def test_a_name_nothing_else_holds_is_still_persisted(self) -> None:
        """The gate must not become a blanket refusal. The run is 2,123 legitimate rewrites; a check that
        refused everything would have 'fixed' the 4 by refusing the corpus."""
        self._charms("Something Else Entirely")
        self._materials()
        out = self._batch("Verdant Echo")
        self.assertEqual(out.outcome, "persisted", f"defects: {out.defects}")
        self.assertIn(SUBJECT, self.ledger.read_done())

    def test_the_own_corpus_is_excluded_so_its_own_names_are_not_cross_corpus_collisions(self) -> None:
        """The property that was broken once already, restated against the shared collector: excluding the
        WRONG file puts this corpus's own names into `owners`, and every within-corpus duplicate then reads
        as a cross-corpus one - 181 reported against 13 real, last time."""
        self._charms()
        self._materials(
            {"id": "material.0001", "runtimeId": "trophy.family.a.1", "name": "Ancestral Sap",
             "nameKey": "material.trophy-family-a-1", "materialClass": "trophy", "iconKey": "i", "tags": []},
            {"id": "material.0002", "runtimeId": "trophy.family.b.1", "name": "Ancestral Sap",
             "nameKey": "material.trophy-family-b-1", "materialClass": "trophy", "iconKey": "i", "tags": []},
        )
        owners = cross_corpus_names.other_corpus_names(self.items, self.materials_path)
        self.assertNotIn("ancestral sap", owners,
                         "FAIL-BEFORE: the materials corpus was not excluded, so its own names read as "
                         "held elsewhere")
        self.assertNotIn("ledger only name", owners,
                         "a run-ledger row is not a name holder; it has no `entries` list")

    def test_the_gate_and_the_collector_agree_on_normalisation(self) -> None:
        """One form, not two that agree today. A gate keyed one way and an owner map keyed another finds
        nothing, which is indistinguishable from a clean tree - that is the whole failure mode."""
        for raw in ["  Permafrost   Core ", "Permafrost Core", "PERMAFROST CORE"]:
            self.assertEqual(run_mod._name_key(raw), cross_corpus_names.name_key(raw))
        self._charms("Glacial Bloom")
        owners = cross_corpus_names.other_corpus_names(self.items, self.materials_path)
        self.assertIn(cross_corpus_names.name_key("GLACIAL   bloom"), owners,
                      "the owner map must be keyed by the form the GATE asks with")
        self.assertEqual(cross_corpus_names.cross_corpus_conflict("glacial bloom", owners), [CHARM_ID])

    def test_an_entry_holding_its_own_name_is_not_reported(self) -> None:
        """`own_id` exists so a caller that does not exclude its own file still cannot collide a row with
        itself. A shared collector earns its keep here, and the guard is cheaper than the next bug."""
        self._charms(CHARM_NAME)
        owners = {cross_corpus_names.name_key(CHARM_NAME): ["charm.c-1", "material.0007"]}
        self.assertEqual(
            cross_corpus_names.cross_corpus_conflict(CHARM_NAME, owners, own_id="material.0007"),
            ["charm.c-1"])


    def test_the_refusal_bans_the_individual_words_not_only_the_phrase(self) -> None:
        """⛔ Measured: 1 subject of 3,633 refused 20 consecutive times with the refused PHRASE quoted and no
        word ban. A model told "not 'Primordial Silt'" reaches for "Primordial Loam" - the phrase is easy to
        escape and the two words are not, so quoting only the phrase re-asks a question with the same anchor
        sitting in it. Words of 3 characters or fewer are dropped as stop-word noise ("of", "the")."""
        owners = {cross_corpus_names.name_key("Primordial Silt"): ["charm.surv-util-074"]}
        defect = run_mod._cross_corpus_name_defect({"name": "Primordial Silt"}, owners)
        self.assertIsNotNone(defect)
        self.assertIn("Primordial", defect, "the word ban must name the offending words")
        self.assertIn("Silt", defect)

    def test_a_single_word_name_still_produces_a_usable_refusal(self) -> None:
        """The word ban is derived from the name, so a nameless or punctuation-only answer must not produce
        an empty clause like "do not use the word(s)  in any new name"."""
        owners = {cross_corpus_names.name_key("Core"): ["charm.c-1"]}
        defect = run_mod._cross_corpus_name_defect({"name": "Core"}, owners)
        self.assertIsNotNone(defect)
        self.assertIn("charm.c-1", defect, "the holder is the part that carries the repair")
        brief = run_mod._name_retry_brief("base", (defect,))
        self.assertIn("charm.c-1", brief)
        self.assertNotIn("word(s) ,", brief, "an empty word list must not reach the prompt")


class CrossCorpusRepairBriefTests(unittest.TestCase):
    """The repair IS the model learning which name is unavailable, so the brief has to say it."""

    def test_the_brief_names_the_holder_and_says_the_name_is_taken_outside_the_corpus(self) -> None:
        defects = (f"{run_mod.CROSS_CORPUS_DEFECT_PREFIX}'{CHARM_NAME}' is already used by {CHARM_ID}",)
        brief = run_mod._name_retry_brief("base brief", defects)
        self.assertIn(CHARM_ID, brief, "the holder must reach the model")
        self.assertIn("ELSEWHERE", brief,
                      "FAIL-BEFORE: the brief only said 'already in the corpus', which is what the model "
                      "already assumed - a charm is not in its corpus, which is the entire reason it "
                      "answered the same way twice")

    def test_the_cross_corpus_defect_counts_as_a_name_defect(self) -> None:
        """If this were false the subject would never be re-asked and the pass would persist the same name
        forever - the exact measured behaviour before this change."""
        self.assertTrue(run_mod._is_name_defect(
            f"{run_mod.CROSS_CORPUS_DEFECT_PREFIX}'X' is already used by charm.c-1"))
        self.assertFalse(run_mod._is_name_defect("$.name: expected at least 3 characters"),
                         "a schema defect must still not be re-asked as a name defect")


if __name__ == "__main__":
    unittest.main()
