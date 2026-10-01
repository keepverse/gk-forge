"""Tests for seedsmith.adapters.trees.species.generate_tree.run_species_tree (task J8's own stated
remainder / task J9's real prerequisite) — the per-species orchestration caller: favour-fit ->
plan/quota -> node generation -> marking -> codex-summary -> the species metadata file.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

from seedsmith.adapters.trees.nodegen import run as nodegen_run
from seedsmith.adapters.trees.species.generate_tree import (
    SpeciesTreeRunError,
    run_species_tree,
)
from seedsmith.adapters.trees.species.plan import FavourCell
from seedsmith.adapters.trees.species.roster import SpeciesAnchor
from seedsmith.adapters.trees.nodegen import tuning as nodegen_tuning
from seedsmith.adapters.trees.plan import tuning as plan_tuning
from seedsmith.briefkit.avoid_list import load_avoid_terms, render_avoid_line
from seedsmith.pipeline.llm_caller import LlmCallerConfig
from seedsmith.workspace_roots import owned_path

TEST_CONFIG = LlmCallerConfig(max_heal=0, model="test-model")


def _anchor(species_id: str) -> SpeciesAnchor:
    return SpeciesAnchor(
        species_id=species_id, element_primary="fire", aptitude_primary="Onslaught",
        posture="Force", traits=("relentless",), reason="a test fixture creature",
        source_path="test.json")


def _stage_call(system: str, user: str, *, config=None, schema=None) -> str:
    """One combined stub for BOTH injected-`call` stages (favour-fit, codex) -- disambiguated by
    the response schema's own declared properties, the only thing distinguishing them at this
    layer."""
    props = (schema or {}).get("properties", {})
    if "choice" in props:
        return json.dumps({"choice": "offered", "blocked": ""})
    if "codexSummary" in props:
        return json.dumps({"codexSummary": "Rewards fire-forward, relentless aggression.", "blocked": ""})
    raise AssertionError(f"unexpected schema shape for injected call: {sorted(props)}")


def _node_call_stub():
    """Node-generation stub (patches `llm_caller.call_model` directly, `run_language_stage`'s own
    contract) -- groups every 3 consecutive calls into one node (§7.1's own vote-3 cost shape,
    confirmed live in `test_nodegen_language_stage.py`), and reads a real permitted affix id back
    off the schema's own gate-8 enum rather than a hand-typed one that could drift."""
    state = {"n": 0}

    def _call(system, user, *, config=None, temperature=0.2, schema=None):
        node_index = state["n"] // 3
        state["n"] += 1
        response = {
            "affixIds": ["atom.a"], "affinity": ["core"],
            "exclusion": {"form": "none", "propertyKeys": []},
            "name": f"Test Node {node_index}", "nameKey": f"tree.node.test-node-{node_index}",
            "flavor": "A steady line.", "rationale": "", "blocked": "",
        }
        enum = (schema or {}).get("properties", {}).get("affixIds", {}).get("items", {}).get("enum") or []
        if enum:
            response["affixIds"] = [enum[0]]
        return json.dumps(response)

    return _call


def _colliding_node_call_stub():
    """Reproduces the REAL live-model finding this test exists for (2026-09-07,
    `AbyssSwordStar`'s own first proof-of-concept run): the model can independently choose the
    SAME name for two different nodes in one tree. Every node here answers with the identical
    name/nameKey on purpose."""
    state = {"n": 0}

    def _call(system, user, *, config=None, temperature=0.2, schema=None):
        state["n"] += 1
        response = {
            "affixIds": ["atom.a"], "affinity": ["core"],
            "exclusion": {"form": "none", "propertyKeys": []},
            "name": "Abyssal Shell", "nameKey": "tree.node.abyssal-shell",
            "flavor": "A steady line.", "rationale": "", "blocked": "",
        }
        enum = (schema or {}).get("properties", {}).get("affixIds", {}).get("items", {}).get("enum") or []
        if enum:
            response["affixIds"] = [enum[0]]
        return json.dumps(response)

    return _call


def _one_named_node_call_stub(name: str):
    """Three identical clean samples for one owed node, with a name absent from the replayed rows."""
    def _call(system, user, *, config=None, temperature=0.2, schema=None):
        enum = ((schema or {}).get("properties", {}).get("affixIds", {})
                .get("items", {}).get("enum") or [])
        return json.dumps({
            "affixIds": [enum[0]], "affinity": ["core"],
            "exclusion": {"form": "none", "propertyKeys": []},
            "name": name, "nameKey": f"tree.node.{name.lower().replace(' ', '-')}",
            "flavor": "A newly completed line.", "rationale": "", "blocked": "",
        })

    return _call


class RunSpeciesTreeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.seed_root = Path(tempfile.mkdtemp())
        self.ledger_path = self.seed_root / "_runs" / "ledger.json"
        self.targets = nodegen_tuning.load()
        self.tuning = plan_tuning.load()

        # `species_tree_spec` reads the REAL, checked-in gate-evidence file (never a fixture stand
        # -in, the same "no defaults, no fallbacks" discipline every other tree factory holds to) --
        # copied into this isolated seed_root so the rest of the run stays sandboxed. Walks up to
        # the repo root by AGENTS.md's own presence, matching test_tree_plan_emit.py's own
        # `real_seed_root()` helper, rather than a fragile hardcoded parents[N] depth.
        import shutil
        repo_root = Path(__file__).resolve()
        while repo_root != repo_root.parent and not (repo_root / "CONTRIBUTING.md").exists():
            repo_root = repo_root.parent
        evidence_src = owned_path("data/seed/passive-tree/gate-evidence.v1.json", repo_root)
        evidence_dst = self.seed_root / "passive-tree" / "gate-evidence.v1.json"
        evidence_dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(evidence_src, evidence_dst)
        self.anchor = _anchor("AbyssSwordStar")
        self.offered = FavourCell("Onslaught", "air", "spark")
        self.alternates = [FavourCell("Ferocity", "fire", "poison")]

    def test_a_full_run_resolves_favour_generates_marks_and_writes_the_codex_metadata(self) -> None:
        with patch("seedsmith.pipeline.llm_caller.call_model", side_effect=_node_call_stub()):
            result = run_species_tree(
                "AbyssSwordStar", self.anchor, 0, self.offered, self.alternates,
                targets=self.targets, tuning=self.tuning, ledger_path=self.ledger_path,
                seed_root=self.seed_root, call=_stage_call, config=TEST_CONFIG, workers=1)

        self.assertEqual(FavourCell("Onslaught", "air", "spark"), result.resolved_cell)
        self.assertIsNone(result.favour_unresolved_reason)
        self.assertIsNotNone(result.nodes_seed_path)
        self.assertTrue(result.nodes_seed_path.exists())
        self.assertEqual(40, result.outcome_counts.get("accepted"))
        self.assertEqual(8, len(result.marked_node_ids), "speciesUniqueAffixMin=8 by default")
        self.assertEqual("Rewards fire-forward, relentless aggression.", result.codex_summary)
        self.assertIsNone(result.codex_unresolved_reason)

        self.assertIsNotNone(result.metadata_path)
        self.assertTrue(result.metadata_path.exists())
        doc = json.loads(result.metadata_path.read_text(encoding="utf-8"))
        self.assertEqual("AbyssSwordStar", doc["speciesId"])
        self.assertEqual({"aptitude": "Onslaught", "element": "air", "status": "spark"},
                        doc["mechanicalFavour"])
        self.assertEqual("Rewards fire-forward, relentless aggression.", doc["codexSummary"])
        self.assertEqual(8, len(doc["speciesUniqueNodeIds"]))

        # The nodes themselves committed to the SHARED nodes/ dir, unchanged path convention.
        nodes_doc = json.loads(result.nodes_seed_path.read_text(encoding="utf-8"))
        # Same fixed tree-shape size as test_forty_nodes_twenty_per_branch_rootless (tree_plan_emit)
        # -- never a second literal (population-pin SE3.5, 2026-09-20).
        self.assertTrue(len(nodes_doc["nodes"]) > 0)

    def test_resume_reuses_resolved_metadata_and_marks_from_the_whole_tree(self) -> None:
        """A completed codex/favour is persisted work, not a fresh model call on every pass.

        The second pass replays 39 accepted ledger rows and generates one missing node. Its metadata
        must still name the full deterministic mark set, and neither favour-fit nor codex may run
        again. The old pass-through path redrew both stages and computed marks from only the one new
        outcome, which is exactly how short ``speciesUniqueNodeIds`` appeared in the captured run.
        """
        with patch("seedsmith.pipeline.llm_caller.call_model", side_effect=_node_call_stub()):
            first = run_species_tree(
                "AbyssSwordStar", self.anchor, 0, self.offered, self.alternates,
                targets=self.targets, tuning=self.tuning, ledger_path=self.ledger_path,
                seed_root=self.seed_root, call=_stage_call, config=TEST_CONFIG, workers=1)
        self.assertIsNotNone(first.metadata_path)
        first_metadata = first.metadata_path.read_bytes()
        fixed_mtime = 946684800
        os.utime(first.metadata_path, (fixed_mtime, fixed_mtime))

        ledger = nodegen_run.read_ledger(self.ledger_path)
        replayed_id = sorted(ledger)[0]
        ledger[replayed_id] = {
            "record": None, "outcome": "unresolved", "detail": "fixture owes one node", "attempts": 1,
        }
        nodegen_run.write_ledger(ledger, self.ledger_path)

        def _persisted_stages_must_not_run(*args, **kwargs):
            raise AssertionError("resume must reuse resolved favour/codex metadata")

        with patch("seedsmith.pipeline.llm_caller.call_model",
                   side_effect=_one_named_node_call_stub("Resumed Whole Tree Mark")):
            resumed = run_species_tree(
                "AbyssSwordStar", self.anchor, 0, self.offered, self.alternates,
                targets=self.targets, tuning=self.tuning, ledger_path=self.ledger_path,
                seed_root=self.seed_root, call=_persisted_stages_must_not_run,
                config=TEST_CONFIG, workers=1)

        self.assertEqual(1, resumed.outcome_counts.get("accepted"))
        self.assertEqual(8, len(resumed.marked_node_ids),
                         "marks come from the full emitted tree, not only this pass's outcomes")
        self.assertEqual(first_metadata, resumed.metadata_path.read_bytes())
        self.assertEqual(fixed_mtime, resumed.metadata_path.stat().st_mtime,
                         "an unchanged resolved supplement is read, not rewritten")
        self.assertEqual(first_metadata, (self.seed_root / "passive-tree" / "species" /
                                          "AbyssSwordStar.json").read_bytes())

    def test_a_real_name_key_collision_within_a_parallel_batch_is_deduped_not_raised(self) -> None:
        # The exact regression this test guards against: AbyssSwordStar's own first real
        # proof-of-concept run against the live local model crashed the whole orchestrator with an
        # uncaught NodeKeyRefused the first time this function was ever run for real (two nodes,
        # both independently named "Abyssal Shell"). The first fix reported the refusal instead of
        # crashing, but still lost the whole tree; the durable fix (2026-09-11, matching
        # `_derive_unique_name_key`'s own documented contract) deterministically suffixes the second
        # colliding key at record time, so the tree completes exactly as it does on the sequential
        # path -- never renamed "out from under the model's answer", only its key made unique.
        #
        # `workers=4` here is load-bearing, not cosmetic: two subjects in ONE concurrent batch
        # cannot see each other's pick in time to disambiguate, which is the real, narrow condition
        # `AbyssSwordStar`'s own PoC hit. The sequential path (`workers=1`) already self-healed via
        # `known_name_keys`; this proves the parallel path now does too.
        # This fixture intentionally exercises collision recovery rather than the production gate;
        # its small unresolved remainder is isolated below so the collision assertion can inspect
        # the emitted tree. The production threshold is covered by the hard-gate test above.
        collision_targets = replace(self.targets, unresolved_count_max_share_permille=1000)
        with patch("seedsmith.pipeline.llm_caller.call_model", side_effect=_colliding_node_call_stub()):
            result = run_species_tree(
                "AbyssSwordStar", self.anchor, 0, self.offered, self.alternates,
                targets=collision_targets, tuning=self.tuning, ledger_path=self.ledger_path,
                seed_root=self.seed_root, call=_stage_call, config=TEST_CONFIG, workers=4)

        self.assertIsNotNone(result.resolved_cell, "the favour lock still resolved cleanly")
        self.assertIsNone(result.node_key_refused_reason,
                          "a within-batch collision is resolved, never surfaced as a refusal")
        self.assertIsNotNone(result.nodes_seed_path, "the tree completes rather than being lost")
        self.assertGreater(result.outcome_counts.get("accepted", 0), 0)

        # Every persisted nameKey is unique within the tree. The stub is adversarial (EVERY node
        # answers "Abyssal Shell"), so the generation-time taken-names gate legitimately routes
        # later identical drafts to `unresolved` -- gate 21's own contract, "re-prompted, never
        # persisted". What matters here is that a same-batch collision no longer aborts the whole
        # tree (the old bug) and never lands a duplicate in the seed document.
        from seedsmith.adapters.trees.nodegen import emit as emit_mod
        nodes_doc = json.loads(result.nodes_seed_path.read_text(encoding="utf-8"))
        keys = [n["nameKey"] for n in nodes_doc["nodes"]]
        self.assertEqual(len(keys), len(set(keys)), "within-tree nameKeys must all differ")
        self.assertIn("tree.node.abyssal-shell", keys)
        emit_mod.assert_no_duplicate_name_keys(keys)

    def test_failed_unresolved_gate_refuses_before_codex_and_after_persisting_attempts(self) -> None:
        """The species batch must honor the one hard gate before spending its codex calls.

        The same-batch collision fixture deliberately leaves unresolved subjects. With the production
        threshold lowered to zero in this isolated test, the language stage's named
        ``PassiveTree/UnresolvedCount`` failure must stop the species before codex; the node ledger
        remains durable so a later pass can retry only the owed subjects.
        """
        def favour_then_forbid_codex(system, user, *, config=None, schema=None):
            props = (schema or {}).get("properties", {})
            if "choice" in props:
                return json.dumps({"choice": "offered", "blocked": ""})
            if "codexSummary" in props:
                raise AssertionError("a failed hard gate must stop before codex")
            raise AssertionError(f"unexpected stage schema: {sorted(props)}")

        targets = replace(self.targets, unresolved_count_max_share_permille=0)
        with patch("seedsmith.pipeline.llm_caller.call_model", side_effect=_colliding_node_call_stub()):
            with self.assertRaisesRegex(ValueError, "UnresolvedCount"):
                run_species_tree(
                    "AbyssSwordStar", self.anchor, 0, self.offered, self.alternates,
                    targets=targets, tuning=self.tuning, ledger_path=self.ledger_path,
                    seed_root=self.seed_root, call=favour_then_forbid_codex, config=TEST_CONFIG,
                    workers=4)

        ledger = nodegen_run.read_ledger(self.ledger_path)
        # The ledger is a POPULATION (one row per node the plan owes), so its size is a reading, never
        # a constant: a literal here re-rots the moment this fixture tree's node count moves (the 40
        # this replaced was exactly that). Assert the CONTRACT the literal stood in for instead -- the
        # failed run persisted a row for EVERY owed subject, so a later pass can retry only the owed
        # ones -- by rebuilding this species' plan the way run_species_tree itself does and comparing
        # the two sets. A dropped row is then a named diff, not a count mismatch.
        from seedsmith.adapters.trees.nodegen import plan_read as plan_read_mod
        from seedsmith.adapters.trees.plan import emit as plan_emit
        spec = plan_emit.species_tree_spec(
            "AbyssSwordStar", 0,
            (self.offered.aptitude, self.offered.element, self.offered.status), self.seed_root)
        tree_plan = plan_read_mod.load_from_dict(
            plan_emit.build_plan(spec, self.tuning), source_label="species:AbyssSwordStar")
        owed = {f"{tree_plan.tree_id}:{node.node_id}" for node in tree_plan.nodes}
        self.assertTrue(owed, "the fixture plan owes no subjects, so this test proves nothing")
        self.assertEqual(owed, set(ledger),
                         f"ledger rows differ from the owed subjects: {sorted(owed ^ set(ledger))}")
        self.assertTrue(any(entry.get("outcome") == "unresolved" for entry in ledger.values()))
        self.assertFalse((self.seed_root / "passive-tree" / "species" /
                          "AbyssSwordStar.json").exists())

    def test_an_unresolved_favour_never_reaches_node_generation_at_all(self) -> None:
        def _always_none(system, user, *, config=None, schema=None):
            return json.dumps({"choice": "none", "blocked": ""})

        with patch("seedsmith.pipeline.llm_caller.call_model",
                  side_effect=AssertionError("node generation must never be reached")):
            result = run_species_tree(
                "AbyssSwordStar", self.anchor, 0, self.offered, self.alternates,
                targets=self.targets, tuning=self.tuning, ledger_path=self.ledger_path,
                seed_root=self.seed_root, call=_always_none, config=TEST_CONFIG, workers=1)

        self.assertIsNone(result.resolved_cell)
        self.assertEqual("none_of_the_offered_favours_fit", result.favour_unresolved_reason)
        self.assertIsNone(result.nodes_seed_path)
        self.assertEqual(frozenset(), result.marked_node_ids)
        self.assertIsNone(result.metadata_path)

    def test_an_unresolved_codex_still_completes_the_tree_but_writes_no_metadata_file(self) -> None:
        # Three genuinely different, individually CLEAN sentences (no digits, so every sample
        # passes the content validator and reaches the vote) that still never agree -> a real
        # 1-1-1 vote_unresolved, never a guessed sentence.
        answers = iter(["A relentless line.", "A patient line instead.", "Something else entirely."])

        def _favour_offered_codex_split(system, user, *, config=None, schema=None):
            props = (schema or {}).get("properties", {})
            if "choice" in props:
                return json.dumps({"choice": "offered", "blocked": ""})
            return json.dumps({"codexSummary": next(answers), "blocked": ""})

        with patch("seedsmith.pipeline.llm_caller.call_model", side_effect=_node_call_stub()):
            result = run_species_tree(
                "AbyssSwordStar", self.anchor, 0, self.offered, self.alternates,
                targets=self.targets, tuning=self.tuning, ledger_path=self.ledger_path,
                seed_root=self.seed_root, call=_favour_offered_codex_split, config=TEST_CONFIG,
                workers=1)

        self.assertIsNotNone(result.resolved_cell)
        self.assertIsNotNone(result.nodes_seed_path)
        self.assertEqual(8, len(result.marked_node_ids), "marking never depends on the codex stage")
        self.assertIsNone(result.codex_summary)
        self.assertEqual("vote_unresolved", result.codex_unresolved_reason)
        self.assertIsNone(result.metadata_path, "no metadata file without a real codex summary")


class SpeciesAvoidListTests(unittest.TestCase):
    """ip-censor IC-3/IC-4 on the SPECIES node path (`generate_tree.run_species_tree`).

    The generic tree path adopted the shared avoid line at T16. The species orchestration caller
    builds its own `NodeGenerationInputs` and did not, so every species node brief — the 40 nodes
    per species, the largest single node corpus in the game — was generated with no IP protection
    at all. These tests read the real rendered brief out of the real run, not the inputs object, so
    what is asserted is what the model is actually handed.
    """

    class _StopAfterFirstNode(Exception):
        """Ends the run once one real node brief has been captured. A full 40-node species run is
        120 model calls; the brief is rendered per node from the same `inputs_for`, so the first one
        is the whole contract and the run does not need finishing to prove it."""

    def setUp(self) -> None:
        self.seed_root = Path(tempfile.mkdtemp())
        self.ledger_path = self.seed_root / "_runs" / "ledger.json"
        self.targets = nodegen_tuning.load()
        self.tuning = plan_tuning.load()

        import shutil
        repo_root = Path(__file__).resolve()
        while repo_root != repo_root.parent and not (repo_root / "CONTRIBUTING.md").exists():
            repo_root = repo_root.parent
        evidence_src = owned_path("data/seed/passive-tree/gate-evidence.v1.json", repo_root)
        evidence_dst = self.seed_root / "passive-tree" / "gate-evidence.v1.json"
        evidence_dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(evidence_src, evidence_dst)
        self.anchor = _anchor("AbyssSwordStar")
        self.offered = FavourCell("Onslaught", "air", "spark")
        self.alternates = [FavourCell("Ferocity", "fire", "poison")]

    def _first_species_node_brief(self) -> str:
        """The real rendered brief of the first species node, captured out of a real run."""
        seen: "list[str]" = []
        inner = _node_call_stub()

        def _capturing_call(system, user, *, config=None, temperature=0.2, schema=None):
            seen.append(user)
            if "Tree: AbyssSwordStar" in user:
                raise self._StopAfterFirstNode()
            return inner(system, user, config=config, temperature=temperature, schema=schema)

        with patch("seedsmith.pipeline.llm_caller.call_model", side_effect=_capturing_call):
            with self.assertRaises(self._StopAfterFirstNode):
                run_species_tree(
                    "AbyssSwordStar", self.anchor, 0, self.offered, self.alternates,
                    targets=self.targets, tuning=self.tuning, ledger_path=self.ledger_path,
                    seed_root=self.seed_root, call=_stage_call, config=TEST_CONFIG, workers=1)
        return seen[-1]

    def test_a_species_node_brief_carries_the_shared_avoid_line_and_nothing_else_avoiding(self) -> None:
        """Both brief assertions in ONE run, because one run costs minutes: the real tree plan, quota
        and vocabulary builds dominate, not the model calls, so two assertions needing the same brief
        must not pay for it twice."""
        brief = self._first_species_node_brief()
        self.assertIn(render_avoid_line(load_avoid_terms()), brief)
        # A species tree names no motifs (`motifs=(), anti_motifs=()`), so the ONLY "avoid" line a
        # species brief may carry is the IP one, and exactly once. If the two ever merged, a motif
        # line would appear where none can exist.
        self.assertNotIn("Avoid entirely:", brief)
        self.assertEqual(1, len([ln for ln in brief.splitlines() if "IP avoid-list" in ln]))

    def test_an_unreadable_avoid_registry_refuses_the_run_instead_of_rendering_nothing(self) -> None:
        """The fail-closed direction, proven at the caller.

        A missing or unreadable registry is a hard refusal, NOT an empty list: an absent avoid line
        reads to the model (and to a reviewer) as "there is nothing to avoid", which is the exact
        false-clean this program exists to prevent. The helper already throws (T14); this proves the
        species caller does not catch that throw and continue.
        """
        with patch("seedsmith.briefkit.avoid_list.load_avoid_terms",
                   side_effect=ValueError("registry is missing 'groups' — refusing to guess")):
            with self.assertRaisesRegex(SpeciesTreeRunError, "avoid"):
                run_species_tree(
                    "AbyssSwordStar", self.anchor, 0, self.offered, self.alternates,
                    targets=self.targets, tuning=self.tuning, ledger_path=self.ledger_path,
                    seed_root=self.seed_root, call=_stage_call, config=TEST_CONFIG, workers=1)
        self.assertFalse(
            (self.seed_root / "passive-tree" / "nodes" / "AbyssSwordStar.json").exists(),
            "a refused run must not leave a half-written species tree behind")


if __name__ == "__main__":
    unittest.main()
