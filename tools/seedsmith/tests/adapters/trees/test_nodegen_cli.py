"""Tests for the task-H2 CLI wiring in seedsmith.report.cli: `check --family PassiveTree --gate`
and `trees generate --dry-run` (spec-tree-language.md §Commands).

    python -m pytest gk-forge/tools/seedsmith/tests/adapters/trees/test_nodegen_cli.py -v

Every dry-run/refusal path here is asserted to make ZERO model calls by patching
`seedsmith.pipeline.llm_caller.call_model` with the same offline-transport stub every other test
file in this directory shares.
"""
from __future__ import annotations

import contextlib
import io
import itertools
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _nodegen_fixtures import raising_call  # noqa: E402

from seedsmith.adapters.trees.nodegen import run as run_mod  # noqa: E402
from seedsmith.report.cli import EXIT_CANNOT_RUN, EXIT_CLEAN, EXIT_GAP, EXIT_REFUSED, main  # noqa: E402


def _run_captured(argv: "list[str]") -> "tuple[int, str]":
    buf = io.StringIO()
    with patch("seedsmith.pipeline.llm_caller.call_model", raising_call):
        with contextlib.redirect_stdout(buf):
            code = main(argv)
    return code, buf.getvalue()


class CallsForArithmeticTests(unittest.TestCase):
    """The ~4,680-call figure §Commands cites, PROVEN computed rather than hardcoded: §6.1's own
    cited corpus is 39 trees x 40 nodes = 1,560 subjects, 1 voted field, 3 samples."""

    def test_the_generic_corpus_figure_is_exactly_4680(self) -> None:
        result = run_mod.calls_for(1560)
        self.assertEqual(result, {"baseCalls": 1560, "voteCalls": 3120, "totalCalls": 4680})

    def test_zero_subjects_costs_zero_calls(self) -> None:
        self.assertEqual(run_mod.calls_for(0), {"baseCalls": 0, "voteCalls": 0, "totalCalls": 0})


class CheckFamilyExitCodeTests(unittest.TestCase):
    def test_an_unknown_family_exits_cannot_run(self) -> None:
        code, _ = _run_captured(["check", "--family", "NotARealFamily", "--gate"])
        self.assertEqual(code, EXIT_CANNOT_RUN)

    def test_no_committed_plan_exits_cannot_run(self) -> None:
        empty_root = Path(tempfile.mkdtemp())
        code, _ = _run_captured(["check", "--family", "PassiveTree", "--gate",
                                 "--plan-root", str(empty_root)])
        self.assertEqual(code, EXIT_CANNOT_RUN)

    def test_gate_against_the_real_committed_plan_runs_now_that_h4_and_the_registry_wiring_both_landed(self) -> None:
        """§7.1: "exactly one gate is promoted to hard-fail first." Before this test's own name
        changed (task H4 built `PassiveTree/UnresolvedCount` with `gates=True`, but `build_registry()`
        never carried it, so `assert_exactly_one_hard_gate` always found zero and `--gate` correctly
        refused rather than silently passing over a contract that was never wired — H9 §6.4 rule 1:
        "an absent check is never a pass"). Both gaps are closed now: the registry carries exactly one
        `gates=True` `PassiveTree/*` metric, so `--gate` runs for real instead of refusing. The real
        committed corpus (42 trees, 1677/1680 real generated nodes as of 2026-09-07) drives every
        H4/H5 metric for real now too (a SECOND wiring gap this same day: `_cmd_check_family` built
        `PassiveTreePlanCtx` with no `targets`/`tree_plans`/`nodes_by_tree`/`outcomes_by_tree` at
        all, so every corpus-side metric silently reported NOT_MEASURED regardless of what was
        actually committed) — `--gate` only ever exits on the ONE gating metric's own verdict, so
        this stays `(EXIT_CLEAN, EXIT_GAP)` either way; the real measured value is asserted directly
        below."""
        code, _ = _run_captured(["check", "--family", "PassiveTree", "--gate"])
        self.assertIn(code, (EXIT_CLEAN, EXIT_GAP))

    def test_the_hard_gate_is_measured_for_real_not_not_measured(self) -> None:
        """The real point of wiring `outcomes_by_tree`: `PassiveTree/UnresolvedCount` must report a
        real share, derived from comparing each committed plan's full node set against the real
        `tree-language.ledger.json` (`nodegen.plan_run`, the SAME resume logic a real generation run
        already uses) — never `NOT_MEASURED`, which is what this exact command always reported before
        this ctx-construction fix landed."""
        code, out = _run_captured(["check", "--family", "PassiveTree", "--gate"])
        self.assertIn(code, (EXIT_CLEAN, EXIT_GAP))
        self.assertIn("PassiveTree/UnresolvedCount", out)
        self.assertNotIn("[NOT_MEASURED] PassiveTree/UnresolvedCount", out)

    def test_hidden_file_count_runs_for_real_against_the_real_seed_root(self) -> None:
        """H5's own remaining real acceptance gap: `HiddenFileCountMetric` was fully built and
        tested but had zero production call site — `tree_seed_roots` always empty outside its own
        test, so this metric never actually walked anything. `_cmd_check_family` now registers it
        locally (never in the shared `build_registry()`, which correctly still excludes it for every
        OTHER caller that has no seed root to give it) and wires `tree_seed_roots` to the real
        `gk-data/packs/fusion/data/seed/passive-tree` directory it already resolved for everything else this command
        needs. This must print a real `visitedFileCount`, never silently skip the metric."""
        code, out = _run_captured(["check", "--family", "PassiveTree"])
        self.assertIn(code, (EXIT_CLEAN, EXIT_GAP))
        self.assertIn("PassiveTree/HiddenFileCount", out)
        self.assertIn("seed root(s)", out)

    def test_quota_drift_and_cell_occupancy_measure_for_real(self) -> None:
        """2026-09-10 distribution-audit wiring: `_cmd_check_family` used to leave
        `quota_cells_by_tree` empty, so `PassiveTree/QuotaDrift` and `PassiveTree/CellOccupancy`
        always reported NOT_MEASURED over a real committed corpus. Both must now measure — the
        cells are re-derived from each committed plan via `quota_for_plan` (the same function the
        generation CLI already calls)."""
        code, out = _run_captured(["check", "--family", "PassiveTree"])
        self.assertIn(code, (EXIT_CLEAN, EXIT_GAP))
        self.assertIn("PassiveTree/QuotaDrift", out)
        self.assertIn("PassiveTree/CellOccupancy", out)
        self.assertNotIn("[NOT_MEASURED] PassiveTree/QuotaDrift", out)
        self.assertNotIn("[NOT_MEASURED] PassiveTree/CellOccupancy", out)

    def test_species_uniqueness_runs_under_check_family(self) -> None:
        """SpeciesUniqueness is gates=False and deliberately outside ALL_PASSIVE_TREE_METRICS;
        `_cmd_check_family` registers it locally so a real corpus check surfaces U1/U2/U3."""
        code, out = _run_captured(["check", "--family", "PassiveTree"])
        self.assertIn(code, (EXIT_CLEAN, EXIT_GAP))
        self.assertIn("PassiveTree/SpeciesUniqueness", out)

    def test_without_gate_the_real_committed_plan_reports_and_exits_clean_or_gap(self) -> None:
        """No --gate: every registered PassiveTree finding is reported — this must reach a real
        verdict rather than EXIT_CANNOT_RUN/EXIT_REFUSED, proving the family dispatch actually runs
        the metric over the real committed plan."""
        code, _ = _run_captured(["check", "--family", "PassiveTree"])
        self.assertIn(code, (EXIT_CLEAN, EXIT_GAP))

    def test_check_with_neither_corpus_root_nor_family_exits_cannot_run(self) -> None:
        code, _ = _run_captured(["check"])
        self.assertEqual(code, EXIT_CANNOT_RUN)


class TreesGenerateDryRunTests(unittest.TestCase):
    def test_neither_tree_nor_all_exits_cannot_run(self) -> None:
        code, _ = _run_captured(["trees", "generate"])
        self.assertEqual(code, EXIT_CANNOT_RUN)

    def test_dry_run_against_the_real_committed_might_tree_prints_the_gate_report_before_any_call(self) -> None:
        code, out = _run_captured(["trees", "generate", "--tree", "might", "--dry-run"])
        self.assertEqual(code, EXIT_CLEAN)
        summary = json.loads(out)
        self.assertIn("gatingMetrics", summary)
        self.assertIn("gatesMissingAThreshold", summary)
        self.assertIn("totalCalls", summary)
        self.assertGreater(summary["totalSubjects"], 0)
        self.assertEqual(summary["totalCalls"],
                         summary["baseCalls"] + summary["voteCalls"])

    def test_write_reaches_the_real_pipeline_now_that_the_hard_gate_and_its_registry_wiring_both_landed(self) -> None:
        """H3 wires the quota stage for real (`resolvedSubjects` below proves it). `--write` used
        to be refused for §7.1's own reason (no `PassiveTree/*` metric was `gates=True` in the live
        registry) — that gap is closed (task H4 built `PassiveTree/UnresolvedCount`; this module's
        own `build_registry()` now registers all eight `PassiveTree/*` metrics). `--write` now
        reaches the REAL `run_language_stage` pipeline for every one of `might`'s 40 real nodes —
        proven here against a schema-driven fake `call_model` (never the real network: every call
        is answered by inspecting the SCHEMA it was actually called with and returning the first
        legal enum choice for every field, so this stays correct regardless of which node/branch a
        given call is for) rather than the simpler `raising_call`/canned-payload fixtures this file
        uses elsewhere, since a single canned response cannot satisfy 40 different real per-node
        schemas (each with its own `affixIds` enum).

        `--plan-root`/`--ledger-path` both point at a fresh temp directory carrying a COPY of the
        real committed `might.v1.json` plan, never the real one — `write_seed_document`'s own
        `seed_root` shares `--plan-root`'s root (both default to `gk-data/packs/fusion/data/seed`), so a test that left
        `--plan-root` at its default would overwrite the real, committed
        `gk-data/packs/fusion/data/seed/passive-tree/nodes/might.json` with fake test content. This is exactly the class
        of accidental-real-write this test exists to prevent while still exercising the real
        CLI-to-pipeline wiring end to end."""
        from seedsmith.adapters.trees.nodegen import plan_read as plan_read_mod

        def _run_with_fake_model(argv: "list[str]", fake) -> "tuple[int, str]":
            # Deliberately NOT `_run_captured`: that helper hard-wires `raising_call` as an inner
            # patch that always wins over an outer one, by design, for every OTHER test in this file
            # (§7 gate 24's offline guarantee). This is the one test in the suite that legitimately
            # needs a real (faked) model response, so it applies its own patch directly around
            # `main(argv)` rather than fighting `_run_captured`'s own safety net.
            buf = io.StringIO()
            with patch("seedsmith.pipeline.llm_caller.call_model", side_effect=fake):
                with contextlib.redirect_stdout(buf):
                    code = main(argv)
            return code, buf.getvalue()

        call_counter = itertools.count()

        def fake_call_model(_system, _user, *, config=None, temperature=0.2, schema=None):
            # A unique name/nameKey per CALL (not per node) is deliberately wasteful but simple and
            # always correct: `generate_node` only ever persists the base call's (sample_index=0)
            # name/nameKey into the final record, so the vote calls' own throwaway uniqueness costs
            # nothing and this fake never has to parse the brief text to recover which node a given
            # call is for.
            n = next(call_counter)
            props = schema["properties"]
            affix_ids = props["affixIds"]["items"]["enum"][:1]
            return json.dumps({
                "affixIds": affix_ids,
                "affinity": ["core"] * len(affix_ids),
                "exclusion": {"form": "none", "propertyKeys": []},
                "name": f"Test Node {n}", "nameKey": f"tree.node.test-node-{n}",
                "flavor": "A steady line.", "rationale": "", "blocked": "",
            })

        # H9's own real generation runs (2026-09-06) have started legitimately writing to the real
        # committed path below, so this test can no longer assert it stays ABSENT -- it asserts the
        # test's OWN run never TOUCHES it instead, by snapshotting whatever is there (present or not)
        # before, and comparing byte-for-byte after.
        real_committed_path = plan_read_mod.REPO_ROOT / "data" / "seed" / "passive-tree" / "nodes" / "might.json"
        real_before = real_committed_path.read_bytes() if real_committed_path.exists() else None

        with tempfile.TemporaryDirectory() as tmp:
            tmp_root = Path(tmp)
            real_plan_path = plan_read_mod.plan_path("might")
            tmp_plan_path = plan_read_mod.plan_path("might", tmp_root)
            tmp_plan_path.parent.mkdir(parents=True, exist_ok=True)
            tmp_plan_path.write_bytes(real_plan_path.read_bytes())
            ledger_path = tmp_root / "ledger.json"

            code, out = _run_with_fake_model([
                "trees", "generate", "--tree", "might", "--write",
                "--plan-root", str(tmp_root), "--ledger-path", str(ledger_path),
            ], fake_call_model)

            # The write landed under the temp root, never the real committed seed document.
            written_path = tmp_root / "passive-tree" / "nodes" / "might.json"
            self.assertTrue(written_path.exists())
            real_after = real_committed_path.read_bytes() if real_committed_path.exists() else None
            self.assertEqual(real_before, real_after,
                            "the real committed seed document must never be touched by this test, "
                            "whether or not it already existed going in")

        # The dry-run-shaped summary prints first (unchanged), then the real per-tree write report
        # as a second, separately-printed JSON document — both land in the same captured stdout.
        self.assertIn("gatingMetrics", out)
        self.assertIn('"outcomeTotals"', out)
        self.assertIn('"accepted": 40', out)  # every one of might's 40 real nodes, unanimous vote
        self.assertEqual(code, EXIT_CLEAN)

    def test_an_unplanned_tree_id_exits_cannot_run(self) -> None:
        code, _ = _run_captured(["trees", "generate", "--tree", "no-such-tree", "--dry-run"])
        self.assertEqual(code, EXIT_CANNOT_RUN)

    def test_node_selector_restricts_a_write_run_to_one_subject(self) -> None:
        """ip-censor T16/IC-4.1: `--node <id>` re-rolls exactly that one node. Modelled on the
        fake-model write test above (a temp plan root + fake model, never the real seed document),
        but restricted to a single node id so only ONE call's worth of content is accepted."""
        from seedsmith.adapters.trees.nodegen import plan_read as plan_read_mod

        def fake_call_model(_system, _user, *, config=None, temperature=0.2, schema=None):
            props = schema["properties"]
            affix_ids = props["affixIds"]["items"]["enum"][:1]
            return json.dumps({
                "affixIds": affix_ids,
                "affinity": ["core"] * len(affix_ids),
                "exclusion": {"form": "none", "propertyKeys": []},
                "name": "One Node", "nameKey": "tree.node.one-node",
                "flavor": "A steady line.", "rationale": "", "blocked": "",
            })

        buf = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            tmp_root = Path(tmp)
            real_plan_path = plan_read_mod.plan_path("might")
            tmp_plan_path = plan_read_mod.plan_path("might", tmp_root)
            tmp_plan_path.parent.mkdir(parents=True, exist_ok=True)
            tmp_plan_path.write_bytes(real_plan_path.read_bytes())
            ledger_path = tmp_root / "ledger.json"

            with patch("seedsmith.pipeline.llm_caller.call_model", side_effect=fake_call_model):
                with contextlib.redirect_stdout(buf):
                    code = main([
                        "trees", "generate", "--tree", "might", "--write",
                        "--node", "skill.might-off-t1-n0",
                        "--plan-root", str(tmp_root), "--ledger-path", str(ledger_path),
                    ])
        out = buf.getvalue()
        self.assertEqual(code, EXIT_CLEAN)
        self.assertIn('"accepted": 1', out)

    def test_an_unknown_node_selector_id_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_root = Path(tmp)
            from seedsmith.adapters.trees.nodegen import plan_read as plan_read_mod
            tmp_plan_path = plan_read_mod.plan_path("might", tmp_root)
            tmp_plan_path.parent.mkdir(parents=True, exist_ok=True)
            tmp_plan_path.write_bytes(plan_read_mod.plan_path("might").read_bytes())
            code, _ = _run_captured([
                "trees", "generate", "--tree", "might", "--write", "--supersede",
                "--node", "skill.might-off-t9-n9",
                "--plan-root", str(tmp_root), "--ledger-path", str(tmp_root / "ledger.json"),
            ])
        self.assertEqual(code, EXIT_CANNOT_RUN)

    def test_the_avoid_list_reaches_the_rendered_sample_brief(self) -> None:
        """ip-censor T16/IC-4.1, at the CLI seam the brief tests never enter: the registry is read
        once by the caller and handed to the brief, so the rendered sample brief carries the line.

        Fixture registry, invented marks only — `gk-forge/tools/seedsmith/**` is an enforced
        `generator-prompt` surface, so a real registry spelling may not appear in this file. The
        fixture is reached by patching the helper's own default path, not by a new parameter, so
        this also pins WHERE the CLI reads from.
        """
        from seedsmith.briefkit import avoid_list as avoid_mod

        fixture = (Path(__file__).resolve().parents[2] / "fixtures" / "avoid_list" / "registry.json")
        self.assertTrue(fixture.exists(), fixture)
        with patch.object(avoid_mod, "DEFAULT_REGISTRY_FILE", fixture):
            code, out = _run_captured(
                ["trees", "generate", "--tree", "might", "--dry-run", "--sample-brief"])
        self.assertEqual(code, EXIT_CLEAN)
        self.assertIn(avoid_mod.render_avoid_line(avoid_mod.load_avoid_terms(fixture)), out)

    def test_an_unreadable_avoid_list_registry_is_refused_not_silently_empty(self) -> None:
        """The fail-closed half, and the reason the refusal is not an empty list: a brief with no
        avoid line reads as "nothing to avoid", which is indistinguishable from a real clean
        registry. IC-3 forbids *blocking generation on an answer-side check*; it does not license
        generating content under a silently-absent prompt control, so an unreadable registry stops
        the run before any model call (`raising_call` would raise if one were made)."""
        from seedsmith.briefkit import avoid_list as avoid_mod

        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "no-such-registry.json"
            out, err = io.StringIO(), io.StringIO()
            with patch.object(avoid_mod, "DEFAULT_REGISTRY_FILE", missing):
                with patch("seedsmith.pipeline.llm_caller.call_model", raising_call):
                    with contextlib.redirect_stdout(out):
                        with contextlib.redirect_stderr(err):
                            code = main(["trees", "generate", "--tree", "might", "--dry-run"])
        self.assertEqual(code, EXIT_CANNOT_RUN)
        self.assertIn("avoid-list registry could not be read", err.getvalue())

    def test_every_node_getting_a_distinct_name_that_slugs_identically_still_gets_a_unique_nameKey(self) -> None:
        """2026-09-06 real-call finding, chapter 1: two accepted `might` nodes independently named
        themselves "Deep Rooting", colliding on `nameKey` -- `NodeKeyRefused` propagated straight out
        of `run_language_stage` with no handler, crashing the CLI. Chapter 2 (same day): even after
        catching the crash cleanly, the REAL root cause -- the model choosing `nameKey` independent of
        its own `name` -- kept recurring against the real model twice in a row, including after an
        explicit schema-wording fix. Closed for real: `nameKey` is no longer trusted from the model at
        all, it is derived deterministically from the model's own accepted `name`, with a numeric
        suffix on collision (`_derive_unique_name_key`). 2026-09-11, gate 21's generation-time half:
        the ORIGINAL shape -- a fake model returning the IDENTICAL name for all 40 nodes -- is now
        REFUSED from node 2 onward (a same-name draft from another node is exactly the measured
        collision defect), so this test exercises the suffix contract's only remaining legal shape:
        40 DISTINCT names (casing variants) that all slug to `deep-rooting`, proving all 40 still get
        unique keys, never a refusal."""
        from seedsmith.adapters.trees.nodegen import plan_read as plan_read_mod

        def _run_with_fake_model(argv: "list[str]", fake) -> "tuple[int, str]":
            buf = io.StringIO()
            with patch("seedsmith.pipeline.llm_caller.call_model", side_effect=fake):
                with contextlib.redirect_stdout(buf):
                    code = main(argv)
            return code, buf.getvalue()

        def fake_call_model(_system, _user, *, config=None, temperature=0.2, schema=None):
            props = schema["properties"]
            affix_ids = props["affixIds"]["items"]["enum"][:1]
            node_index = _deep_rooting_calls["n"] // 3  # 3 calls per node (base + 2 votes), sequential
            _deep_rooting_calls["n"] += 1
            # 40 DISTINCT exact names (a 6-bit casing mask cycling over the base's letters), every
            # one slugging to `deep-rooting` (slugify lowercases; "!" collapses into the trailing
            # hyphen and is stripped) -- gate 21's exact-name comparison passes for all 40, while
            # the KEY still collides and must be suffixed: the suffix mechanism's contract, end to
            # end through the CLI.
            base = "Deep Rooting"
            bits = f"{node_index:06b}"
            name = "".join(
                (ch.upper() if bits[k % len(bits)] == "1" else ch.lower())
                if ch.isalpha() else ch
                for k, ch in enumerate(base)
            )
            return json.dumps({
                "affixIds": affix_ids, "affinity": ["core"] * len(affix_ids),
                "exclusion": {"form": "none", "propertyKeys": []},
                "name": name, "nameKey": "tree.node.deep-rooting",
                "flavor": "A steady line.", "rationale": "", "blocked": "",
            })

        with tempfile.TemporaryDirectory() as tmp:
            tmp_root = Path(tmp)
            real_plan_path = plan_read_mod.plan_path("might")
            tmp_plan_path = plan_read_mod.plan_path("might", tmp_root)
            tmp_plan_path.parent.mkdir(parents=True, exist_ok=True)
            tmp_plan_path.write_bytes(real_plan_path.read_bytes())
            ledger_path = tmp_root / "ledger.json"
            _deep_rooting_calls = {"n": 0}

            code, out = _run_with_fake_model([
                "trees", "generate", "--tree", "might", "--write",
                "--plan-root", str(tmp_root), "--ledger-path", str(ledger_path),
            ], fake_call_model)

            self.assertNotIn("Traceback", out)
            self.assertNotIn("nameKeyRefused", out)
            self.assertIn('"accepted": 40', out)
            self.assertEqual(code, EXIT_CLEAN)

            ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
            # Same fixed 40-node tree shape as the CLI's own "accepted": 40 output above -- never a
            # second literal (population-pin SE3.5, 2026-09-20).
            self.assertTrue(len(ledger["done"]) > 0)
            name_keys = [entry["record"]["nameKey"] for entry in ledger["done"].values()]
            self.assertEqual(len(name_keys), len(set(name_keys)),
                            "every one of the 40 slug-equal but DISTINCT-named nodes must still get a unique nameKey")
            # The deterministic derivation is visible, not hidden -- the base slug plus numeric
            # suffixes, never the model's own literal (and collision-prone) "deep-rooting" repeated.
            self.assertIn("tree.node.deep-rooting", name_keys)
            self.assertIn("tree.node.deep-rooting-2", name_keys)
            # Gate 21's own ledger-level proof: 40 DISTINCT exact names, no duplicates to measure.
            names = [entry["record"]["name"] for entry in ledger["done"].values()]
            self.assertEqual(len(names), len(set(names)),
                            "gate 21 refuses an exact-name re-use, so the accepted names must all differ")

    def test_the_cli_still_reports_a_genuine_nameKeyRefused_cleanly_if_one_ever_reaches_it(self) -> None:
        """The auto-dedup above closes the ONE real way this fired in practice, but the CLI's own
        exception-handling (report cleanly, EXIT_GAP, never a raw traceback, continue to other trees
        under --all) is a real, independent property worth pinning on its own terms -- proven here by
        making `run_language_stage` itself raise, bypassing generation entirely, so this test survives
        even if the dedup fix above is ever changed or removed."""
        from seedsmith.adapters.trees.nodegen import emit as emit_mod

        def _raise_name_key_refused(*_a, **_kw):
            raise emit_mod.NodeKeyRefused("nameKey 'tree.node.x' is used by both node index 0 and node index 1")

        with tempfile.TemporaryDirectory() as tmp:
            tmp_root = Path(tmp)
            from seedsmith.adapters.trees.nodegen import plan_read as plan_read_mod
            real_plan_path = plan_read_mod.plan_path("might")
            tmp_plan_path = plan_read_mod.plan_path("might", tmp_root)
            tmp_plan_path.parent.mkdir(parents=True, exist_ok=True)
            tmp_plan_path.write_bytes(real_plan_path.read_bytes())

            buf = io.StringIO()
            # `report/cli.py` imports `run` as `run_mod` via a LOCAL import inside the function --
            # `run_mod` is the same module object as `seedsmith.adapters.trees.nodegen.run`, so
            # patching the attribute there (not a nonexistent `cli.run_mod`) is what actually reaches it.
            with patch("seedsmith.adapters.trees.nodegen.run.run_language_stage", side_effect=_raise_name_key_refused):
                with contextlib.redirect_stdout(buf):
                    code = main([
                        "trees", "generate", "--tree", "might", "--write",
                        "--plan-root", str(tmp_root),
                    ])
            out = buf.getvalue()

        self.assertNotIn("Traceback", out)
        self.assertIn("nameKeyRefused", out)
        self.assertEqual(code, EXIT_GAP)


class ManifestRosterCoverageTests(unittest.TestCase):
    """`trees plan --manifest` must index the WHOLE roster, not the `--tree` default (2026-09-11).

    Before this fix the `--manifest` branch built `[spec]` from `--tree`'s own default ("might"), so
    a bare `--emit` rewrote `plan.v1.json` with a `trees[]` of length 1 while 41 committed per-tree
    plans sat unindexed, and the `roster` block mirrored a stale status count. These tests pin the
    two observable halves: the full roster is built when `--tree` is omitted, and an explicit
    `--tree` still narrows it.
    """

    def test_manifest_without_tree_builds_every_roster_tree(self) -> None:
        from seedsmith.adapters.trees.plan.vocabulary import load_roster
        from seedsmith.report.cli import _all_roster_specs

        roster = load_roster()
        specs = _all_roster_specs()
        expected = len(roster.aptitudes) + len(roster.elements) + len(roster.statuses)
        self.assertEqual(expected, len(specs))
        # Aptitude roster entries are PascalCase; their tree ids are the lower-cased form the CLI
        # accepts (`primary_tree_spec` lower-cases internally). Elements/statuses are already lower.
        expected_ids = ({a.lower() for a in roster.aptitudes}
                        | set(roster.elements) | set(roster.statuses))
        self.assertEqual(expected_ids, {s.tree_id for s in specs})

    def test_parser_distinguishes_an_omitted_tree_from_an_explicit_one(self) -> None:
        from seedsmith.report.cli import build_parser

        parser = build_parser()
        omitted = parser.parse_args(["trees", "plan", "--emit", "--manifest"])
        explicit = parser.parse_args(["trees", "plan", "--emit", "--manifest", "--tree", "fire"])
        self.assertIsNone(omitted.tree)
        self.assertEqual("fire", explicit.tree)


if __name__ == "__main__":
    unittest.main()
