"""Tests for items fill UX + `.env` write defaults (seedsmith-cli-ux).

    python -m pytest gk-forge/tools/seedsmith/tests/test_items_fill_ux.py -q
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import ANY, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from seedsmith.adapters.items import defaults as defaults_mod  # noqa: E402
from seedsmith.adapters.items import fill as fill_mod  # noqa: E402
from seedsmith.pipeline.llm_caller import (  # noqa: E402
    resolve_dotenv_path,
    resolve_live_transport,
)
from seedsmith.report import cli as cli_mod  # noqa: E402


class ResolveDotenvPathTests(unittest.TestCase):
    def test_explicit_path_wins_even_when_absent(self) -> None:
        missing = Path(tempfile.mkdtemp()) / "no.env"
        self.assertEqual(resolve_dotenv_path(missing), missing)

    def test_default_resolution_prefers_existing_cwd_or_package(self) -> None:
        packaged = Path(__file__).resolve().parents[1] / ".env"
        cwd_env = Path(".env")
        resolved = resolve_dotenv_path(None)
        if cwd_env.exists():
            self.assertEqual(resolved.resolve(), cwd_env.resolve())
        elif packaged.exists():
            self.assertEqual(resolved.resolve(), packaged.resolve())
        else:
            self.assertEqual(resolved, Path(".env"))


class ResolveLiveTransportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.no_dotenv = self.tmp / "absent.env"

    def test_cli_endpoint_wins(self) -> None:
        cfg = resolve_live_transport(
            "http://cli-only:1/v1", "", dotenv_path=self.no_dotenv,
            toml_path=self.tmp / "no.toml")
        self.assertEqual(cfg.endpoint, "http://cli-only:1/v1/chat/completions")

    def test_empty_cli_uses_dotenv(self) -> None:
        dotenv = self.tmp / ".env"
        dotenv.write_text(
            "SEEDSMITH_LLM_ENDPOINT=http://from-env:9/v1\nSEEDSMITH_LLM_MODEL=env/model\n",
            encoding="utf-8")
        cfg = resolve_live_transport("", "", dotenv_path=dotenv, toml_path=self.tmp / "no.toml")
        self.assertEqual(cfg.endpoint, "http://from-env:9/v1/chat/completions")
        self.assertEqual(cfg.model, "env/model")

    def test_unrecorded_model_falls_through(self) -> None:
        dotenv = self.tmp / ".env"
        dotenv.write_text("SEEDSMITH_LLM_MODEL=env/model\n", encoding="utf-8")
        cfg = resolve_live_transport(
            "http://x", "unrecorded", dotenv_path=dotenv, toml_path=self.tmp / "no.toml")
        self.assertEqual(cfg.model, "env/model")


class ItemsDefaultsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())

    def test_allow_production_from_env(self) -> None:
        dotenv = self.tmp / ".env"
        dotenv.write_text("SEEDSMITH_ALLOW_PRODUCTION_TREE=1\n", encoding="utf-8")
        self.assertTrue(defaults_mod.allow_production_tree(dotenv_path=dotenv))
        dotenv.write_text("SEEDSMITH_ALLOW_PRODUCTION_TREE=0\n", encoding="utf-8")
        self.assertFalse(defaults_mod.allow_production_tree(dotenv_path=dotenv))

    def test_default_out_dir_for_set(self) -> None:
        path = defaults_mod.default_out_dir("set", dotenv_path=self.tmp / "absent.env")
        self.assertTrue(path.replace("\\", "/").endswith("data/seed/items/sets"))

    def test_resolve_out_dir_requires_allow(self) -> None:
        self.assertEqual(
            defaults_mod.resolve_out_dir_arg("set", "", allow_production=False,
                                             dotenv_path=self.tmp / "x"),
            "")
        self.assertTrue(
            defaults_mod.resolve_out_dir_arg("set", "", allow_production=True,
                                             dotenv_path=self.tmp / "x"))

    def test_production_relative_out_dir_is_repo_anchored(self) -> None:
        path = defaults_mod.resolve_out_dir_arg(
            "charm", "data/seed/items/charms", allow_production=True,
            dotenv_path=self.tmp / "absent.env")
        self.assertEqual(Path(path).resolve(), defaults_mod.PRODUCTION_OUT_DIRS["charm"].resolve())


class ItemsWriteDefaultsCliTests(unittest.TestCase):
    def test_empty_out_dir_defaults_when_allow_production(self) -> None:
        with patch("seedsmith.adapters.items.defaults.allow_production_tree",
                   return_value=True), \
             patch("seedsmith.adapters.items.defaults.resolve_out_dir_arg",
                   return_value=str(defaults_mod.PRODUCTION_OUT_DIRS["set"])) as resolve:
            args = cli_mod.build_parser().parse_args([
                "items", "generate", "--kind", "set", "--write"])
            cli_mod._apply_items_write_defaults(args)
            self.assertTrue(args.allow_production_tree)
            self.assertTrue(args.out_dir)
            resolve.assert_called()


class ItemsFillTests(unittest.TestCase):
    def _smoke_limits(self) -> fill_mod.FillLimits:
        return fill_mod.FillLimits(limit=1, count=1, batch_size=1, max_partitions=1)

    def test_dry_run_lists_kinds_in_dependency_order(self) -> None:
        report = fill_mod.run_fill(
            dry_run=True, allow_production=True, limits=self._smoke_limits())
        self.assertTrue(report.dry_run)
        self.assertFalse(report.refused_reason)
        kinds_seen = [s.kind for s in report.steps if s.status == "planned"]
        self.assertTrue(kinds_seen)
        order = {k: i for i, k in enumerate(defaults_mod.FILL_KIND_ORDER)}
        indexes = [order[k] for k in kinds_seen]
        self.assertEqual(indexes, sorted(indexes))

    def test_fill_cli_dry_run_requires_limit_or_full(self) -> None:
        args = cli_mod.build_parser().parse_args(["items", "fill", "--dry-run"])
        code = cli_mod.cmd_items(args)
        self.assertEqual(code, cli_mod.EXIT_REFUSED)

    def test_fill_cli_dry_run_with_limit(self) -> None:
        args = cli_mod.build_parser().parse_args([
            "items", "fill", "--dry-run", "--limit", "1", "--max-partitions", "1"])
        code = cli_mod.cmd_items(args)
        self.assertEqual(code, cli_mod.EXIT_CLEAN)

    def test_fill_dispatch_order_and_stop_on_refuse(self) -> None:
        calls: list[list[str]] = []

        def dispatch(argv: list[str]) -> int:
            calls.append(argv)
            if len(calls) == 2:
                return cli_mod.EXIT_REFUSED
            return cli_mod.EXIT_CLEAN

        with patch.object(fill_mod, "discover_gem_slots", return_value=[1]), \
             patch.object(fill_mod, "_gem_slot_has_work", return_value=True):
            report = fill_mod.run_fill(
                kinds=("material", "gem"), dry_run=False, allow_production=True,
                limits=self._smoke_limits(), dispatch=dispatch, stop_on_error=True)
        self.assertGreaterEqual(len(calls), 1)
        self.assertEqual(calls[0][:3], ["--kind", "material", "--write"])
        refused = [s for s in report.steps if s.status == "refused"]
        self.assertEqual(len(refused), 1)

    def test_fill_stops_on_gap(self) -> None:
        calls: list[list[str]] = []

        def dispatch(argv: list[str]) -> int:
            calls.append(argv)
            return cli_mod.EXIT_GAP

        report = fill_mod.run_fill(
            kinds=("material", "gem"), dry_run=False, allow_production=True,
            limits=self._smoke_limits(), dispatch=dispatch, stop_on_error=True)
        self.assertEqual(len(calls), 1)
        self.assertEqual(report.steps[0].status, "gap")
        self.assertEqual(report.worst_exit_code, cli_mod.EXIT_GAP)

    def test_fill_continues_after_recorded_escalation_by_default(self) -> None:
        calls: list[str] = []

        def dispatch(argv: list[str]) -> int:
            kind = argv[argv.index("--kind") + 1]
            calls.append(kind)
            return (cli_mod.EXIT_ESCALATED if kind == "material" else cli_mod.EXIT_CLEAN)

        report = fill_mod.run_fill(
            kinds=("material", "consumable"), dry_run=False, allow_production=True,
            limits=self._smoke_limits(), dispatch=dispatch, stop_on_error=True)
        self.assertEqual(calls, ["material", "consumable"])
        self.assertEqual(report.steps[0].status, "escalated")
        self.assertEqual(report.steps[1].status, "ran")
        self.assertEqual(report.worst_exit_code, cli_mod.EXIT_ESCALATED)

    def test_clean_resume_after_prior_escalation_exits_clean(self) -> None:
        report = fill_mod.run_fill(
            kinds=("consumable",), dry_run=False, allow_production=True,
            limits=self._smoke_limits(), dispatch=lambda _argv: cli_mod.EXIT_CLEAN,
            stop_on_error=True)
        self.assertEqual(report.worst_exit_code, cli_mod.EXIT_CLEAN)

    def test_affix_jobs_only_legal_kinds(self) -> None:
        jobs = fill_mod.discover_affix_family_jobs()
        legal = {"stat.modify", "stat.derived"}
        self.assertTrue(jobs)
        for _group, kid in jobs:
            self.assertIn(kid, legal)

    def test_base_type_discovery_reads_nested_and_legacy_partitions_by_content(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            entries = {
                "humanoid-armament-primary-a.json": {
                    "frame": "humanoid", "role": "armament-primary", "band": "a",
                },
                "humanoid-back-b.json": {
                    "frame": "humanoid", "role": "mantle", "band": "b",
                },
            }
            for name, entry in entries.items():
                (directory / name).write_text(
                    json.dumps({"kind": "base-type", "entries": [entry]}), encoding="utf-8")
            nested = directory / "footing" / "plant" / "a.json"
            nested.parent.mkdir(parents=True)
            nested.write_text(json.dumps({"kind": "base-type", "entries": [{
                "frame": "plant", "role": "footing", "band": "a",
            }]}), encoding="utf-8")
            self.assertEqual(
                fill_mod.discover_base_type_partitions(directory),
                [
                    ("armament-primary", "humanoid", "a"),
                    ("footing", "plant", "a"),
                    ("mantle", "humanoid", "b"),
                ],
            )

    def test_fill_catches_unexpected_exception(self) -> None:
        def dispatch(argv: list[str]) -> int:
            raise RuntimeError("boom")

        report = fill_mod.run_fill(
            kinds=("material",), dry_run=False, allow_production=True,
            limits=self._smoke_limits(), dispatch=dispatch, stop_on_error=True)
        self.assertEqual(report.steps[0].status, "error")
        self.assertEqual(report.worst_exit_code, cli_mod.EXIT_CANNOT_RUN)

    def test_fill_kinds_filter(self) -> None:
        steps, reason = fill_mod.plan_fill_steps(
            kinds=("material",), allow_production=True, limits=self._smoke_limits())
        self.assertEqual(reason, "")
        self.assertEqual([s.kind for s in steps], ["material"])

    def test_unbounded_grids_refused_without_limit(self) -> None:
        steps, reason = fill_mod.plan_fill_steps(
            kinds=("set",), allow_production=True,
            limits=fill_mod.FillLimits(limit=0, full=False))
        self.assertEqual(steps, [])
        self.assertIn("--limit", reason)

    def test_combination_strain_before_splice(self) -> None:
        steps, reason = fill_mod.plan_fill_steps(
            kinds=("combination",), allow_production=True, limits=self._smoke_limits())
        self.assertEqual(reason, "")
        shapes = [s.note for s in steps if s.argv]
        self.assertEqual(shapes, ["shape=strain", "shape=splice"])
        self.assertIn("--limit", steps[0].argv)
        self.assertIn("1", steps[0].argv)

    def test_recipe_fill_reconciles_without_an_unscoped_model_draw(self) -> None:
        steps, _ = fill_mod.plan_fill_steps(
            kinds=("recipe",), allow_production=True, limits=self._smoke_limits())
        argv = steps[0].argv
        self.assertEqual(argv, ["--kind", "recipe"])
        self.assertIn("reconcile", steps[0].note)

    def test_max_partitions_caps_gem(self) -> None:
        with patch.object(fill_mod, "discover_gem_slots", return_value=[1, 2]), \
             patch.object(fill_mod, "_gem_slot_has_work", return_value=True):
            steps, _ = fill_mod.plan_fill_steps(
                kinds=("gem",), allow_production=True,
                limits=fill_mod.FillLimits(max_partitions=1, batch_size=1))
        planned = [s for s in steps if s.argv]
        self.assertEqual(len(planned), 1)
        # Outer items generate CLI takes --count; remaps to gemgen --batch-size.
        self.assertIn("--count", planned[0].argv)
        self.assertNotIn("--batch-size", planned[0].argv)
        self.assertEqual(planned[0].argv[planned[0].argv.index("--count") + 1], "1")

    def test_affix_full_partition_planned_as_skipped(self) -> None:
        with patch.object(fill_mod, "discover_affix_family_jobs",
                          return_value=[("g.life", "stat.modify")]), \
             patch.object(fill_mod, "_affix_has_free_pairs", return_value=False):
            steps, reason = fill_mod.plan_fill_steps(
                kinds=("affix-family",), allow_production=True,
                limits=fill_mod.FillLimits(max_partitions=1))
        self.assertEqual(reason, "")
        self.assertTrue(all(not s.argv for s in steps))
        self.assertTrue(any("no free" in s.note for s in steps))

    def test_affix_no_free_pair_value_error_is_not_runnable(self) -> None:
        with patch(
            "seedsmith.adapters.items.affixfamgen.brief.load_partition_context",
            return_value=object(),
        ), patch(
            "seedsmith.adapters.items.affixfamgen.brief.free_channel_ops",
            return_value=(),
        ):
            self.assertFalse(fill_mod._affix_has_free_pairs("g.life", "stat.modify"))

    def test_affix_over_target_partition_is_not_runnable(self) -> None:
        class Partition:
            existing_ids = tuple(f"atom.x{i}" for i in range(7))

        with patch(
            "seedsmith.adapters.items.affixfamgen.brief.load_partition_context",
            return_value=Partition(),
        ), patch(
            "seedsmith.adapters.items.affixfamgen.brief.free_channel_ops",
            return_value=(("atk", "Flat"),),
        ), patch(
            "seedsmith.adapters.items.affixfamgen.brief.load_target_family_count",
            return_value=7,
        ):
            self.assertFalse(fill_mod._affix_has_free_pairs("g.elem-power", "stat.derived"))

    def test_gem_empty_slot_planned_as_skipped(self) -> None:
        with patch.object(fill_mod, "discover_gem_slots", return_value=[1]), \
             patch.object(fill_mod, "_gem_slot_has_work", return_value=False):
            steps, reason = fill_mod.plan_fill_steps(
                kinds=("gem",), allow_production=True,
                limits=fill_mod.FillLimits(max_partitions=1, batch_size=1))
        self.assertEqual(reason, "")
        self.assertTrue(all(not s.argv for s in steps))
        self.assertTrue(any("alreadyDone" in s.note for s in steps))

    def test_smoke_dry_run_step_count_is_small(self) -> None:
        steps, reason = fill_mod.plan_fill_steps(
            allow_production=True, limits=self._smoke_limits())
        self.assertEqual(reason, "")
        planned = [s for s in steps if s.argv]
        # 1 per phase-2 kind + 1 base-type + species set + build set + charm + recipe + 2 combo + 1 drop
        self.assertLessEqual(len(planned), 16)
        self.assertGreaterEqual(len(planned), 8)
        set_notes = [s.note for s in planned if s.kind == "set"]
        self.assertEqual(set_notes, ["population=species", "population=build"])

    def test_full_plan_uses_elevated_open_counts_without_unscoped_recipe_generation(self) -> None:
        steps, reason = fill_mod.plan_fill_steps(
            kinds=("enhancement-milestone", "base-type", "set", "combination", "recipe"),
            allow_production=True,
            limits=fill_mod.FillLimits(full=True, max_partitions=1))
        self.assertEqual(reason, "")
        milestone = next(s for s in steps if s.kind == "enhancement-milestone" and s.argv)
        self.assertEqual(milestone.argv[milestone.argv.index("--count") + 1],
                         str(fill_mod._FULL_OPEN_PASS))
        recipe = next(s for s in steps if s.kind == "recipe" and s.argv)
        self.assertEqual(recipe.argv, ["--kind", "recipe"])
        sets = [s for s in steps if s.kind == "set" and s.argv]
        self.assertEqual(len(sets), 2)
        for step in sets + [s for s in steps if s.kind == "combination" and s.argv]:
            self.assertNotIn("--limit", step.argv)

    def test_full_plan_honors_an_explicit_limit_as_a_checkpoint(self) -> None:
        steps, reason = fill_mod.plan_fill_steps(
            kinds=("set", "charm", "combination"), allow_production=True,
            limits=fill_mod.FillLimits(full=True, limit=10))
        self.assertEqual(reason, "")
        planned = [step for step in steps if step.argv]
        self.assertTrue(planned)
        for step in planned:
            if step.kind in {"set", "charm", "combination"}:
                self.assertEqual(step.argv[step.argv.index("--limit") + 1], "10")

    def test_full_run_automatically_repeats_set_checkpoints_until_complete(self) -> None:
        planned = [fill_mod.FillStep(kind="set", argv=["--kind", "set"], note="species", seq=0)]
        # The runner reconciles both before and after each checkpoint; repeat the intermediate
        # value for the second loop's pre-dispatch observation.
        remaining = iter((2, 1, 1, 0))
        calls: list[list[str]] = []

        def completion(*, kinds):
            self.assertEqual(kinds, ("set",))
            n = next(remaining)
            return {"complete": n == 0,
                    "checks": [{"kind": "set", "toGenerate": n, "held": 0}]}

        with patch.object(fill_mod, "plan_fill_steps", return_value=(planned, "")), \
             patch.object(fill_mod, "generation_completion", side_effect=completion):
            report = fill_mod.run_fill(
                kinds=("set",), allow_production=True,
                limits=fill_mod.FillLimits(full=True),
                dispatch=lambda argv: calls.append(argv) or cli_mod.EXIT_CLEAN)

        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0][-2:], ["--limit", str(fill_mod._FULL_GRID_CHECKPOINT)])
        self.assertEqual(calls[1][-2:], ["--limit", str(fill_mod._FULL_GRID_CHECKPOINT)])
        self.assertEqual(len([s for s in report.steps if s.status == "ran"]), 2)

    def test_full_does_not_turn_an_explicit_global_count_into_recipe_generation(self) -> None:
        steps, _ = fill_mod.plan_fill_steps(
            kinds=("recipe",), allow_production=True,
            limits=fill_mod.FillLimits(full=True, count=3, count_explicit=True))
        argv = steps[0].argv
        self.assertNotIn("--count", argv)

    def test_full_gem_plan_assigns_the_global_family_pool_to_one_slot(self) -> None:
        with patch.object(fill_mod, "discover_gem_slots", return_value=[1, 4]), \
             patch.object(fill_mod, "_gem_remaining", side_effect=lambda slot: {1: 3, 4: 7}[slot]):
            steps, reason = fill_mod.plan_fill_steps(
                kinds=("gem",), allow_production=True, limits=fill_mod.FillLimits(full=True))
        self.assertEqual(reason, "")
        planned = [step for step in steps if step.argv]
        self.assertEqual(len(planned), 1)
        self.assertEqual(planned[0].argv[planned[0].argv.index("--count") + 1], "3")
        self.assertTrue(any("global unauthored-family pool" in step.note
                            for step in steps if not step.argv))

    def test_generation_completion_exposes_held_closed_subjects(self) -> None:
        class Plan:
            subjects = ()
            held = (("creature.alpha", "basis=name"),)
            complete = False

            @staticmethod
            def summary():
                return {"heldByReason": {"basis=name": 1}}

        with patch("seedsmith.adapters.items.setgen.run.plan_run", return_value=Plan()), \
             patch.object(fill_mod, "_set_charm_exact_duplicate_count", return_value=0):
            report = fill_mod.generation_completion(kinds=("set",))

        self.assertFalse(report["complete"])
        self.assertEqual(report["checks"], [
            {"kind": "set", "population": "species", "toGenerate": 0, "held": 1,
             "ledgered": ANY,
             "heldByReason": {"basis=name": 1}, "exactDuplicateNames": 0, "complete": False},
            {"kind": "set", "population": "build", "toGenerate": 0, "held": 1,
             "ledgered": ANY,
             "heldByReason": {"basis=name": 1}, "exactDuplicateNames": 0, "complete": False},
        ])

    def test_generation_completion_refuses_to_call_duplicate_names_complete(self) -> None:
        class Plan:
            subjects = ()
            held = ()
            complete = True

            @staticmethod
            def summary():
                return {"heldByReason": {}}

        with patch("seedsmith.adapters.items.setgen.run.plan_run", return_value=Plan()), \
             patch.object(fill_mod, "_set_charm_exact_duplicate_count", return_value=1):
            report = fill_mod.generation_completion(kinds=("charm",))

        self.assertFalse(report["complete"])
        self.assertEqual(report["checks"][0]["exactDuplicateNames"], 1)
        self.assertFalse(report["checks"][0]["complete"])

    def test_fill_continues_past_gap_when_stop_on_error_false(self) -> None:
        calls: list[str] = []

        def dispatch(argv: list[str]) -> int:
            calls.append(argv[argv.index("--kind") + 1])
            if argv[argv.index("--kind") + 1] == "material":
                return cli_mod.EXIT_GAP
            return cli_mod.EXIT_CLEAN

        report = fill_mod.run_fill(
            kinds=("material", "consumable"), dry_run=False, allow_production=True,
            limits=self._smoke_limits(), dispatch=dispatch, stop_on_error=False)
        self.assertEqual(calls, ["material", "consumable"])
        self.assertEqual(report.steps[0].status, "gap")
        self.assertEqual(report.steps[1].status, "ran")
        self.assertEqual(report.worst_exit_code, cli_mod.EXIT_GAP)

    def test_fill_kind_order_is_valid_topo_of_map_edges(self) -> None:
        order = {k: i for i, k in enumerate(defaults_mod.FILL_KIND_ORDER)}
        for upstream, downstream in fill_mod.MAP_DEPENDENCY_EDGES:
            self.assertLess(
                order[upstream], order[downstream],
                f"{upstream} must precede {downstream}")

    def test_allow_production_not_required_for_material_only(self) -> None:
        with patch("seedsmith.adapters.items.defaults.allow_production_tree",
                   return_value=False):
            args = cli_mod.build_parser().parse_args([
                "items", "fill", "--dry-run", "--kinds", "material",
                "--limit", "1"])
            # dry-run never needs allow; material-only live also shouldn't require it
            code = cli_mod.cmd_items(args)
            self.assertEqual(code, cli_mod.EXIT_CLEAN)


if __name__ == "__main__":
    unittest.main()
