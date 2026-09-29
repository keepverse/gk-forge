"""Tests for `items generate --kind base-type|enhancement-milestone|recipe|drop-table` — the
passthrough dispatch added 2026-09-08.

⛔ **Real gap this closes.** Every one of these four kinds already had real, tested generation
machinery (`basetypegen`/`milestonegen`/`recipegen`/`droptablegen`) AND a spec
(`docs/architecture/item-seedgen/spec-*.md`) documenting `items generate --kind <x> ... --write` as
the real invocation — but the CLI's own `--kind` choices only ever recognized `set`/`charm`/
`combination`. `cmd_items._cmd_items_generate_passthrough` is the fix: it builds an argv from the
shared flags and hands it to that module's own `main()`, mirroring `cmd_effects`'s own `--kind
affix` dispatch precedent exactly.

    python -m pytest gk-forge/tools/seedsmith/tests/test_items_generate_passthrough.py -q
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from seedsmith.adapters.items.affixfamgen import run as affixfamgen_run  # noqa: E402
from seedsmith.adapters.items.basetypegen import run as basetypegen_run  # noqa: E402
from seedsmith.adapters.items.consumablegen import run as consumablegen_run  # noqa: E402
from seedsmith.adapters.items.droptablegen import run as droptablegen_run  # noqa: E402
from seedsmith.adapters.items.gemgen import run as gemgen_run  # noqa: E402
from seedsmith.adapters.items.materialgen import run as materialgen_run  # noqa: E402
from seedsmith.adapters.items.milestonegen import run as milestonegen_run  # noqa: E402
from seedsmith.adapters.items.recipegen import run as recipegen_run  # noqa: E402
from seedsmith.report import cli as cli_mod  # noqa: E402


def _parse(argv: "list[str]"):
    parser = cli_mod.build_parser()
    return parser.parse_args(["items", "generate", *argv])


ALL_KINDS = ("set", "charm", "combination", "base-type", "enhancement-milestone", "recipe",
            "drop-table", "gem", "material", "consumable", "affix-family")


class KindChoicesTests(unittest.TestCase):
    def test_all_eight_new_kinds_are_accepted(self) -> None:
        for kind in ("base-type", "enhancement-milestone", "recipe", "drop-table", "gem",
                    "material", "consumable", "affix-family"):
            args = _parse(["--kind", kind])
            self.assertEqual(args.kind, kind)

    def test_exactly_these_eleven_kinds_are_legal_total(self) -> None:
        parser = cli_mod.build_parser()
        for kind in ALL_KINDS:
            with self.subTest(kind=kind):
                parser.parse_args(["items", "generate", "--kind", kind])
        with self.assertRaises(SystemExit):
            parser.parse_args(["items", "generate", "--kind", "unique"])


class AffixFamilyDispatchTests(unittest.TestCase):
    def test_dispatches_to_affixfamgen_with_group_and_affix_kind(self) -> None:
        captured = {}
        self.addCleanup(setattr, affixfamgen_run, "main", affixfamgen_run.main)
        affixfamgen_run.main = lambda argv=None: (captured.__setitem__("argv", argv), 0)[1]

        args = _parse(["--kind", "affix-family", "--group", "g.armour",
                      "--affix-kind", "stat.modify", "--dry-run", "--theme", "fire"])
        exit_code = cli_mod.cmd_items(args)

        self.assertEqual(exit_code, 0)
        argv = captured["argv"]
        self.assertEqual(argv[argv.index("--group") + 1], "g.armour")
        self.assertEqual(argv[argv.index("--affix-kind") + 1], "stat.modify")
        self.assertEqual(argv[argv.index("--theme") + 1], "fire")

    def test_refuses_before_dispatch_when_group_is_missing(self) -> None:
        args = _parse(["--kind", "affix-family", "--affix-kind", "stat.modify"])
        exit_code = cli_mod.cmd_items(args)
        self.assertEqual(exit_code, cli_mod.EXIT_CANNOT_RUN)

    def test_refuses_before_dispatch_when_affix_kind_is_missing(self) -> None:
        args = _parse(["--kind", "affix-family", "--group", "g.armour"])
        exit_code = cli_mod.cmd_items(args)
        self.assertEqual(exit_code, cli_mod.EXIT_CANNOT_RUN)

    def test_count_and_overwrite_are_never_passed_through_for_affix_family(self) -> None:
        captured = {}
        self.addCleanup(setattr, affixfamgen_run, "main", affixfamgen_run.main)
        affixfamgen_run.main = lambda argv=None: (captured.__setitem__("argv", argv), 0)[1]

        args = _parse(["--kind", "affix-family", "--group", "g.armour",
                      "--affix-kind", "stat.modify", "--dry-run", "--count", "3",
                      "--overwrite", "x"])
        cli_mod.cmd_items(args)

        self.assertNotIn("--count", captured["argv"])
        self.assertNotIn("--overwrite", captured["argv"])


class ConsumableDispatchTests(unittest.TestCase):
    def test_theme_passes_through_inline_not_as_a_brief_file(self) -> None:
        """Unlike recipe, consumablegen's own flag IS `--theme` (an inline string) — no file
        bridge needed here."""
        captured = {}
        self.addCleanup(setattr, consumablegen_run, "main", consumablegen_run.main)
        consumablegen_run.main = lambda argv=None: (captured.__setitem__("argv", argv), 0)[1]

        args = _parse(["--kind", "consumable", "--theme", "fire", "--slot", "1"])
        cli_mod.cmd_items(args)

        argv = captured["argv"]
        self.assertNotIn("--brief", argv)
        self.assertEqual(argv[argv.index("--theme") + 1], "fire")
        self.assertEqual(argv[argv.index("--slot") + 1], "1")

    def test_count_is_never_passed_through_for_consumable(self) -> None:
        """consumablegen has no `--count` flag at all — it always mints exactly one entry."""
        captured = {}
        self.addCleanup(setattr, consumablegen_run, "main", consumablegen_run.main)
        consumablegen_run.main = lambda argv=None: (captured.__setitem__("argv", argv), 0)[1]

        args = _parse(["--kind", "consumable", "--theme", "fire", "--slot", "1", "--count", "5"])
        cli_mod.cmd_items(args)

        self.assertNotIn("--count", captured["argv"])

    def test_slot_is_optional_for_consumable_unlike_drop_table_and_gem(self) -> None:
        captured = {}
        self.addCleanup(setattr, consumablegen_run, "main", consumablegen_run.main)
        consumablegen_run.main = lambda argv=None: (captured.__setitem__("argv", argv), 0)[1]

        args = _parse(["--kind", "consumable"])
        exit_code = cli_mod.cmd_items(args)

        self.assertEqual(exit_code, 0)
        self.assertNotIn("--slot", captured["argv"])


class MaterialDispatchTests(unittest.TestCase):
    def test_dispatches_to_materialgen_with_overwrite(self) -> None:
        captured = {}
        self.addCleanup(setattr, materialgen_run, "main", materialgen_run.main)
        materialgen_run.main = lambda argv=None: (captured.__setitem__("argv", argv), 0)[1]

        args = _parse(["--kind", "material", "--overwrite", "shard.chaff", "--dry-run"])
        exit_code = cli_mod.cmd_items(args)

        self.assertEqual(exit_code, 0)
        argv = captured["argv"]
        self.assertEqual(argv[argv.index("--overwrite") + 1], "shard.chaff")

    def test_theme_and_slot_and_role_are_not_passed_through_for_material(self) -> None:
        captured = {}
        self.addCleanup(setattr, materialgen_run, "main", materialgen_run.main)
        materialgen_run.main = lambda argv=None: (captured.__setitem__("argv", argv), 0)[1]

        args = _parse(["--kind", "material", "--dry-run", "--theme", "fire"])
        cli_mod.cmd_items(args)

        self.assertNotIn("--theme", captured["argv"])
        self.assertNotIn("--slot", captured["argv"])
        self.assertNotIn("--role", captured["argv"])


class BaseTypeDispatchTests(unittest.TestCase):
    def test_dispatches_to_basetypegen_with_role_frame_band(self) -> None:
        captured = {}
        self.addCleanup(setattr, basetypegen_run, "main", basetypegen_run.main)
        basetypegen_run.main = lambda argv=None: (captured.__setitem__("argv", argv), 0)[1]

        args = _parse(["--kind", "base-type", "--role", "armament-primary", "--frame", "humanoid",
                      "--band", "a", "--dry-run", "--count", "2", "--theme", "fire"])
        exit_code = cli_mod.cmd_items(args)

        self.assertEqual(exit_code, 0)
        argv = captured["argv"]
        self.assertIn("--role", argv)
        self.assertEqual(argv[argv.index("--role") + 1], "armament-primary")
        self.assertEqual(argv[argv.index("--frame") + 1], "humanoid")
        self.assertEqual(argv[argv.index("--band") + 1], "a")
        self.assertEqual(argv[argv.index("--theme") + 1], "fire")
        self.assertEqual(argv[argv.index("--count") + 1], "2")
        self.assertIn("--dry-run", argv)

    def test_refuses_before_dispatch_when_role_is_missing(self) -> None:
        args = _parse(["--kind", "base-type", "--frame", "humanoid", "--band", "a"])
        exit_code = cli_mod.cmd_items(args)
        self.assertEqual(exit_code, cli_mod.EXIT_CANNOT_RUN)


class DropTableDispatchTests(unittest.TestCase):
    def test_dispatches_to_droptablegen_with_slot(self) -> None:
        captured = {}
        self.addCleanup(setattr, droptablegen_run, "main", droptablegen_run.main)
        droptablegen_run.main = lambda argv=None: (captured.__setitem__("argv", argv), 0)[1]

        args = _parse(["--kind", "drop-table", "--slot", "2", "--dry-run"])
        exit_code = cli_mod.cmd_items(args)

        self.assertEqual(exit_code, 0)
        self.assertEqual(captured["argv"][captured["argv"].index("--slot") + 1], "2")

    def test_refuses_before_dispatch_when_slot_is_missing(self) -> None:
        args = _parse(["--kind", "drop-table", "--dry-run"])
        exit_code = cli_mod.cmd_items(args)
        self.assertEqual(exit_code, cli_mod.EXIT_CANNOT_RUN)


class GemDispatchTests(unittest.TestCase):
    def test_dispatches_to_gemgen_with_slot_and_count_mapped_to_batch_size(self) -> None:
        """gemgen's own flag is `--batch-size`, not `--count` — the shared `--count` flag still
        selects it, so an operator does not need to learn a second flag name per kind."""
        captured = {}
        self.addCleanup(setattr, gemgen_run, "main", gemgen_run.main)
        gemgen_run.main = lambda argv=None: (captured.__setitem__("argv", argv), 0)[1]

        args = _parse(["--kind", "gem", "--slot", "2", "--dry-run", "--count", "5"])
        exit_code = cli_mod.cmd_items(args)

        self.assertEqual(exit_code, 0)
        argv = captured["argv"]
        self.assertEqual(argv[argv.index("--slot") + 1], "2")
        self.assertIn("--batch-size", argv)
        self.assertEqual(argv[argv.index("--batch-size") + 1], "5")
        self.assertNotIn("--count", argv)

    def test_theme_is_not_passed_through_for_gem(self) -> None:
        """gemgen has no `--theme` flag at all — unlike the other four kinds."""
        captured = {}
        self.addCleanup(setattr, gemgen_run, "main", gemgen_run.main)
        gemgen_run.main = lambda argv=None: (captured.__setitem__("argv", argv), 0)[1]

        args = _parse(["--kind", "gem", "--slot", "2", "--dry-run", "--theme", "fire"])
        cli_mod.cmd_items(args)

        self.assertNotIn("--theme", captured["argv"])

    def test_refuses_before_dispatch_when_slot_is_missing(self) -> None:
        args = _parse(["--kind", "gem", "--dry-run"])
        exit_code = cli_mod.cmd_items(args)
        self.assertEqual(exit_code, cli_mod.EXIT_CANNOT_RUN)


class EnhancementMilestoneDispatchTests(unittest.TestCase):
    def test_dispatches_with_no_kind_specific_required_flags(self) -> None:
        captured = {}
        self.addCleanup(setattr, milestonegen_run, "main", milestonegen_run.main)
        milestonegen_run.main = lambda argv=None: (captured.__setitem__("argv", argv), 0)[1]

        args = _parse(["--kind", "enhancement-milestone", "--dry-run", "--count", "3"])
        exit_code = cli_mod.cmd_items(args)

        self.assertEqual(exit_code, 0)
        self.assertEqual(captured["argv"][captured["argv"].index("--count") + 1], "3")


class RecipeDispatchTests(unittest.TestCase):
    def test_count_is_omitted_from_argv_when_not_given_so_recipegen_keeps_its_own_zero_default(
            self) -> None:
        """⛔ The one subtlety this dispatch has to get right: recipegen's own `--count` default
        (0 == reconcile-only) differs from every sibling module's (1). The shared parser's own
        `--count` default is `None` specifically so an un-set `--count` is never forced onto
        recipegen as a literal `"1"`, which would silently turn a plain `items generate --kind
        recipe` into "draw 1 new recipe" instead of "reconcile the existing corpus"."""
        captured = {}
        self.addCleanup(setattr, recipegen_run, "main", recipegen_run.main)
        recipegen_run.main = lambda argv=None: (captured.__setitem__("argv", argv), 0)[1]

        args = _parse(["--kind", "recipe"])
        cli_mod.cmd_items(args)

        self.assertNotIn("--count", captured["argv"])

    def test_backfill_flag_passes_through_only_for_recipe(self) -> None:
        captured = {}
        self.addCleanup(setattr, recipegen_run, "main", recipegen_run.main)
        recipegen_run.main = lambda argv=None: (captured.__setitem__("argv", argv), 0)[1]

        args = _parse(["--kind", "recipe", "--count", "1", "--write", "--endpoint",
                      "http://unit-test", "--backfill"])
        cli_mod.cmd_items(args)

        self.assertIn("--backfill", captured["argv"])

    def test_theme_becomes_a_brief_file_for_recipe_not_an_inline_flag(self) -> None:
        """recipegen's own `--brief` reads a FILE PATH, unlike the other three kinds' `--theme`
        (an inline string) — the dispatch must bridge this, not pass `--theme` straight through
        to a module that has no such flag."""
        captured = {}
        self.addCleanup(setattr, recipegen_run, "main", recipegen_run.main)
        recipegen_run.main = lambda argv=None: (captured.__setitem__("argv", argv), 0)[1]

        args = _parse(["--kind", "recipe", "--count", "1", "--dry-run", "--theme", "molten"])
        cli_mod.cmd_items(args)

        argv = captured["argv"]
        self.assertNotIn("--theme", argv)
        self.assertIn("--brief", argv)
        brief_path = argv[argv.index("--brief") + 1]
        self.assertEqual(Path(brief_path).read_text(encoding="utf-8"), "molten")


if __name__ == "__main__":
    unittest.main()
