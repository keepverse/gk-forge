"""Tests for item module 21, `strain-splice-gen` (docs/architecture/item/spec-strain-splice-gen.md).

    python -m pytest gk-forge/tools/seedsmith/tests/test_strain_splice_gen.py -q

⭐ **Almost every assertion here runs against the REAL shipped corpus**, not a synthetic fixture: the
40-gem / 34-family insert vocabulary, the 740-entry base-type corpus, the 25 legacy socket-words, the
36-row build-theme registry, the twelve-aptitude roster and both live tuning files. That is
deliberate, and it is what caught this module's largest finding — the spec's central claim that "no
Strain and no Splice is buildable on any shipped chassis" is **stale**: module 6 re-issued the
`socketMax` table on 2026-09-04 and `armament-primary` / `core-guard` now reach 4.

Where a count is a moving target the test asserts the RELATIONSHIP rather than the number; where the
number IS the finding (the 25 legacy entries, the 102 cells) it is asserted exactly.
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from seedsmith.adapters.items.combogen import (  # noqa: E402
    brief as brief_mod,
    catalogue as catalogue_mod,
    deps as deps_mod,
    emit,
    grid,
    migrate as migrate_mod,
    run as run_mod,
    schema as schema_mod,
    supply as supply_mod,
    tuning as tuning_mod,
)
from seedsmith.corpus import Corpus  # noqa: E402
from seedsmith.metrics import Ctx, Severity  # noqa: E402
from seedsmith.metrics.linkage import COMBINATION_KINDS, CombinationIngredients  # noqa: E402
from seedsmith.pipeline.model import BLOCKED_FIELD, Pipeline, audit_schema  # noqa: E402
from seedsmith.pipeline.run_ledger import RunLedger  # noqa: E402
from seedsmith.planner.schedule import DEFAULT_MODEL_TIERS  # noqa: E402
from seedsmith.report import cli as cli_mod  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[3]
ITEMS_ROOT = REPO_ROOT / "data" / "seed" / "items"
COMBOGEN_DIR = (Path(__file__).resolve().parents[1] / "seedsmith" / "adapters" / "items"
                / "combogen")

TUNING = tuning_mod.load()
SUPPLY = supply_mod.build()
HOST_ROLES = TUNING.host_roles()
GRANTED = run_mod.granted_family_vocabulary()


def _entry(entry_id: str, kind: str, data: dict):
    """One synthetic corpus row — the only synthetic fixtures in this file, and they exist to prove
    a metric covers a kind id no shipped file carries YET."""
    from seedsmith.corpus import Entry
    return Entry(id=entry_id, kind=kind, partition="test", path=f"{kind}/{entry_id}.json",
                 data={"id": entry_id, **data})


def _tmp_json(testcase: unittest.TestCase, doc: dict) -> Path:
    """Write `doc` to a temp `.json` cleaned up when `testcase` finishes (Windows refuses a second
    open on a live handle, so the mkstemp fd is closed before writing)."""
    fd, name = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    path = Path(name)
    path.write_text(json.dumps(doc), encoding="utf-8")
    testcase.addCleanup(path.unlink, missing_ok=True)
    return path


def _base_type_entries() -> list[dict]:
    out: list[dict] = []
    for path in sorted((ITEMS_ROOT / "base-types").rglob("*.json")):
        doc = json.loads(path.read_text(encoding="utf-8"))
        if doc.get("kind") != "base-type":
            continue
        out.extend(doc.get("entries", []))
    return out


# ── the grid ────────────────────────────────────────────────────────────────────────────────────

class GridTests(unittest.TestCase):

    def test_the_grid_yields_exactly_36_strains_and_66_splices(self):
        aptitudes = grid.load_aptitudes()
        archetypes = grid.archetypes()
        # Both counts are read fresh from live content, never pinned as literals (population-pin
        # SE3.5, 2026-09-20); the formula below is the real contract.
        self.assertTrue(len(aptitudes) > 0)
        self.assertTrue(len(archetypes) > 0)
        # The re-derivation, so a thirteenth aptitude grows the grid instead of going red -- the
        # literal 36/66/102 this used to also assert directly were redundant with it.
        n = len(aptitudes)
        self.assertEqual(n * len(archetypes), len(grid.strain_cells()))
        self.assertEqual(n * (n - 1) // 2, len(grid.splice_cells()))
        self.assertEqual(len(grid.strain_cells()) + len(grid.splice_cells()), len(grid.all_cells()))

    def test_the_two_axes_are_read_never_transcribed(self):
        # `assert_grid_agrees` re-measures the registry against the roster on every call.
        self.assertEqual((12, 3), grid.assert_grid_agrees())

    def test_a_grid_that_moved_raises_instead_of_being_absorbed(self):
        rows = grid.load_aptitudes()
        themes = grid.load_build_themes()
        # An aptitude the registry does not cover — a thirteenth landing with no Strain cells.
        extra = rows + (grid.AptitudeRow("Umbrage", 12, "force", "made up", "For the test."),)
        with self.assertRaises(grid.GridDrift):
            grid.assert_grid_agrees(extra, themes)
        # …and an incomplete product: drop one cell and the grid is no longer 12 x 3.
        with self.assertRaises(grid.GridDrift):
            grid.assert_grid_agrees(rows, themes[:-1])

    def test_a_splice_pair_is_unordered_by_id_construction(self):
        by_id = {a.id: a for a in grid.load_aptitudes()}
        might, agility = by_id["Might"], by_id["Agility"]
        self.assertEqual(
            "combo.splice-might-agility",
            emit.splice_id(might.token, might.ordinal, agility.token, agility.ordinal))
        self.assertEqual(
            "combo.splice-might-agility",
            emit.splice_id(agility.token, agility.ordinal, might.token, might.ordinal))
        ids = [emit.combo_id(c) for c in grid.splice_cells()]
        self.assertEqual(len(ids), len(set(ids)))
        with self.assertRaises(emit.IdRefused):
            emit.splice_id("might", 0, "might", 0)

    def test_every_minted_id_is_a_legal_container_id(self):
        ids = [emit.combo_id(c) for c in grid.all_cells()]
        self.assertEqual(102, len(set(ids)))
        for minted in ids:
            self.assertEqual(1, minted.count("."))
            self.assertRegex(minted, r"^combo\.(strain|splice)-[a-z0-9]+(-[a-z0-9]+)*$")

    def test_no_id_name_or_prompt_contains_the_word_runeword(self):
        # ⛔ D20, over the emitted ids AND every source file in the package AND a real brief.
        for minted in (emit.combo_id(c) for c in grid.all_cells()):
            self.assertEqual([], grid.scan_for_banned_word(minted))
        # ⚠ Exactly three files may say it, and each because it ENFORCES the ban: `__init__.py`
        # states the rule at the top of the package, `grid.py` holds the constant and the scanner,
        # `brief.py` applies the scanner to its own output. Anywhere else — a name, a comment, a
        # docstring — is the drift D20 banned the word to prevent, and the set comparison catches a
        # fourth file the day it appears.
        saying_it = {path.name for path in sorted(COMBOGEN_DIR.glob("*.py"))
                     if grid.scan_for_banned_word(path.read_text(encoding="utf-8"))}
        self.assertEqual({"__init__.py", "grid.py", "brief.py"}, saying_it)
        cell = grid.strain_cells()[0]
        text = brief_mod.build_brief(cell, TUNING, SUPPLY,
                                     granted_families=GRANTED, host_roles=HOST_ROLES)
        self.assertEqual([], grid.scan_for_banned_word(text))

    def test_a_strain_cell_reuses_module_13s_theme_key_rather_than_minting_a_new_one(self):
        keys = {c.theme_key for c in grid.strain_cells()}
        # Formula, not a literal (population-pin SE3.5, 2026-09-20): every strain cell has a distinct
        # theme key.
        self.assertEqual(len(grid.strain_cells()), len(keys))
        self.assertTrue(all(k is not None and k.startswith("build.") for k in keys))
        # A Splice is a PAIR of build themes, not a 37th one — it deliberately carries no key.
        self.assertEqual({None}, {c.theme_key for c in grid.splice_cells()})


# ── the tuning files ────────────────────────────────────────────────────────────────────────────

class TuningTests(unittest.TestCase):

    def test_the_shipped_tuning_carries_D20s_four_ingredient_plan(self):
        self.assertEqual(4, TUNING.ingredient_count)
        self.assertEqual(TUNING.ingredient_count, len(TUNING.min_tier_plan))
        self.assertEqual(sorted(TUNING.min_tier_plan), list(TUNING.min_tier_plan))
        self.assertEqual(45, TUNING.catalogue_size_bar)
        self.assertEqual(1, TUNING.attuned_tier_bonus)

    def test_the_parser_refuses_rather_than_defaults(self):
        raw = json.loads(tuning_mod.STRAIN_SPLICE_PATH.read_text(encoding="utf-8"))
        for section in ("recipe", "learnability", "distinctness"):
            stripped = {k: v for k, v in raw.items() if k != section}
            path = self._tmp(stripped)
            with self.assertRaises(tuning_mod.ComboTuningError):
                tuning_mod.load(path)

    def test_a_key_module_16_owns_is_refused_as_a_fork(self):
        # ⛔ Two sources of truth for the ingredient count is how a generated combination stops
        # matching the evaluator that has to fire it.
        raw = json.loads(tuning_mod.STRAIN_SPLICE_PATH.read_text(encoding="utf-8"))
        raw["recipe"]["ingredientCount"] = 4
        with self.assertRaises(tuning_mod.ComboTuningError) as ctx:
            tuning_mod.load(self._tmp(raw))
        self.assertIn(tuning_mod.SOCKETS_PATH.name, str(ctx.exception))

    def test_a_min_tier_plan_that_disagrees_with_the_ingredient_count_raises(self):
        raw = json.loads(tuning_mod.STRAIN_SPLICE_PATH.read_text(encoding="utf-8"))
        raw["recipe"]["minTierPlan"] = [1, 1, 2]
        with self.assertRaises(tuning_mod.ComboTuningError) as ctx:
            tuning_mod.load(self._tmp(raw))
        self.assertIn("ingredient count", str(ctx.exception))

    def test_a_min_tier_outside_the_shipped_ladder_raises(self):
        raw = json.loads(tuning_mod.STRAIN_SPLICE_PATH.read_text(encoding="utf-8"))
        raw["recipe"]["minTierPlan"] = [1, 1, 2, TUNING.insert_tier_count + 1]
        with self.assertRaises(tuning_mod.ComboTuningError) as ctx:
            tuning_mod.load(self._tmp(raw))
        self.assertIn("insert ladder", str(ctx.exception))

    def test_the_tuning_file_carries_no_content_ceiling(self):
        # A cap on how many combinations may exist would be a hard progression ceiling on content
        # breadth (AGENTS.md). D17's dead tail, protected the way module 13 protects its own.
        text = tuning_mod.STRAIN_SPLICE_PATH.read_text(encoding="utf-8")
        for forbidden in ("maxCombinations", "maxStrains", "maxSplices", "gridCap"):
            self.assertNotIn(forbidden, text)
        self.assertIn("REPORTED, NEVER ENFORCED", text)

    def test_the_host_set_is_every_role_whose_ceiling_reaches_the_ingredient_count(self):
        # strain-splice-host SSH5.1 (circuit-topology §5, R11): `SocketGeometry.RolesThatCanHostAStrain`
        # is the C# half, this is the Python mirror, and both DERIVE the set from the same shipped
        # ceiling table. No role is named -- the derivation itself is the contract.
        sockets = json.loads(tuning_mod.SOCKETS_PATH.read_text(encoding="utf-8"))
        expected = tuple(sorted(r for r, c in sockets["socketCeiling"].items()
                                if c >= sockets["strainSplice"]["ingredientCount"]))
        self.assertEqual(expected, HOST_ROLES)
        self.assertTrue(HOST_ROLES)

    def test_a_role_hosts_a_word_iff_its_ceiling_reaches_the_ingredient_count(self):
        # strain-splice-host SSH1.5/SSH5.10: the rule is asserted, never the shipped list. Move ONE
        # below-count role's ceiling up to the ingredient count; it must enter host_roles() with no
        # code change between the two `load()` calls. No role is named.
        sockets = json.loads(tuning_mod.SOCKETS_PATH.read_text(encoding="utf-8"))
        wanted = sockets["strainSplice"]["ingredientCount"]
        below = sorted(r for r, c in sockets["socketCeiling"].items() if c < wanted)[0]

        self.assertNotIn(below, tuning_mod.load().host_roles())
        sockets["socketCeiling"][below] = wanted
        raised = self._tmp(sockets)
        self.assertIn(below, tuning_mod.load(sockets_path=raised).host_roles())

    def test_the_combogen_tuning_carries_no_module_16_cap(self):
        # strain-splice-host SSH4.2/SSH5.10 (R12): v2 REMOVES maxCombosPerActor; v1 keeps it as
        # history. An unknown key is ignored, so a fixture that ADDS the key still loads.
        sockets = json.loads(tuning_mod.SOCKETS_PATH.read_text(encoding="utf-8"))
        self.assertNotIn("maxCombosPerActor", sockets)
        sockets["maxCombosPerActor"] = 3
        tuning = tuning_mod.load(sockets_path=self._tmp(sockets))
        self.assertEqual(sockets["strainSplice"]["ingredientCount"], tuning.ingredient_count)

    def _tmp(self, doc: dict) -> Path:
        import os
        import tempfile
        fd, name = tempfile.mkstemp(suffix=".json")
        os.close(fd)                       # Windows refuses a second open on a live handle
        path = Path(name)
        path.write_text(json.dumps(doc), encoding="utf-8")
        self.addCleanup(path.unlink, missing_ok=True)
        return path


# ── the module-6 dependency, flipped ────────────────────────────────────────────────────────────

class ChassisTests(unittest.TestCase):

    def test_the_corpus_host_set_equals_the_tuning_host_set_and_no_row_exceeds_its_ceiling(self):
        """strain-splice-host SSH5.1 (circuit-topology §5) tightened by SSH5.12: two role-free
        contracts over the real base-type corpus. (2) the set of roles in which some base type reaches
        the ingredient count EQUALS the tuning host set -- every role the tuning offers a word in can
        actually carry one on the shipped corpus, and the corpus names no role the tuning does not
        offer; (3) no row's `socketMax` exceeds its own role's ceiling. SSH5.12's v2 re-stamp is what
        lifts this from subset to equality, so the re-stamped corpus and this contract land together."""
        sockets = json.loads(tuning_mod.SOCKETS_PATH.read_text(encoding="utf-8"))
        ceiling = sockets["socketCeiling"]
        wanted = sockets["strainSplice"]["ingredientCount"]

        entries = _base_type_entries()
        self.assertGreaterEqual(len(entries), 740)
        corpus_hosts: set[str] = set()
        for entry in entries:
            role = entry["role"]
            max_sockets = int(entry.get("socketMax", 0))
            if role in ceiling:
                self.assertLessEqual(
                    max_sockets, ceiling[role],
                    f"base-type role {role!r} socketMax {max_sockets} exceeds its ceiling {ceiling[role]}")
            if max_sockets >= wanted:
                corpus_hosts.add(role)

        # Equality, not subset: a tuning host role the corpus never reaches is a role whose words can
        # never fire on a shipped chassis. The two-sided diff is the failure message.
        self.assertEqual(set(HOST_ROLES), corpus_hosts)
        self.assertTrue(corpus_hosts)


# ── the schema, and P1 ──────────────────────────────────────────────────────────────────────────

class SchemaTests(unittest.TestCase):

    def schema(self) -> dict:
        return schema_mod.combination_schema(
            TUNING, supplied_families=SUPPLY.families, host_roles=HOST_ROLES,
            granted_families=GRANTED)

    def test_the_schema_is_audit_schema_clean(self):
        self.assertEqual([], audit_schema(self.schema()))

    def test_a_bare_integer_magnitude_field_fails_pipeline_construction(self):
        # Mechanical P1, proven rather than asserted: `Pipeline.__post_init__` runs the audit at
        # CONSTRUCTION, so a numeric field never reaches a call.
        bad = self.schema()
        bad["properties"]["grantedTier"] = {"type": "integer"}
        with self.assertRaises(ValueError) as ctx:
            Pipeline(metric="strain-splice-gen", scope="test", schema=bad,
                     gate=lambda _: [], on_persist=lambda _k, _v: None)
        self.assertIn("magnitudes come from", str(ctx.exception))

    def test_blocked_is_a_legal_answer_and_writes_nothing(self):
        written: list[tuple[str, object]] = []
        pipeline = Pipeline(metric="strain-splice-gen", scope="test", schema=self.schema(),
                            gate=lambda _: [], on_persist=lambda k, v: written.append((k, v)))
        self.assertIn(BLOCKED_FIELD, pipeline.schema["properties"])
        self.assertEqual([], written)

    def test_every_combination_takes_exactly_four_ingredients(self):
        node = self.schema()["properties"]["ingredients"]
        self.assertEqual(TUNING.ingredient_count, node["minItems"])
        self.assertEqual(TUNING.ingredient_count, node["maxItems"])

    def test_the_schema_offers_no_tier_no_cost_and_no_min_tier(self):
        names = schema_mod.schema_field_names(self.schema())
        for banned in ("tier", "cost", "chance", "duration", "minTier", "baseTier", "position"):
            self.assertNotIn(banned, names)

    def test_the_schema_offers_no_base_type_or_slot_pin(self):
        # strain-splice-host SSH1.4, host-gate ruling 2 (§4 row 2): a combination pins ROLE/FRAME/
        # SIZE (hostRole/hostFrame/minSockets) and never a specific base type or a slot. The Python
        # sibling of ComboMatcherTests.No_combination_contract_carries_a_base_or_slot_key (C#) and
        # CombinationKindTests.No_combination_contract_carries_a_base_or_slot_key (KindCatalog).
        names = schema_mod.schema_field_names(self.schema())
        for banned in ("baseType", "baseTypeId", "slot"):
            self.assertNotIn(banned, names)

    def test_the_host_role_enum_is_closed_to_roles_that_can_actually_hold_four(self):
        enum = self.schema()["properties"]["hostRole"]["enum"]
        self.assertEqual(list(HOST_ROLES) + [None], enum)

    def test_a_schema_with_no_supplied_family_or_no_host_role_is_refused(self):
        with self.assertRaises(ValueError):
            schema_mod.combination_schema(TUNING, supplied_families=(), host_roles=HOST_ROLES,
                                          granted_families=GRANTED)
        with self.assertRaises(ValueError):
            schema_mod.combination_schema(TUNING, supplied_families=SUPPLY.families,
                                          host_roles=(), granted_families=GRANTED)

    def test_the_host_role_enum_is_derived_from_the_loaded_ceilings(self) -> None:
        """strain-splice-host SSH2.7 (R11, spec-combination-regen "The helm joins the host set"):
        a fixture tuning that moves ONLY `head-guard`'s own ceiling must move the helm in and out of
        the schema's `hostRole` enum with no code change between the two `load()` calls. The rule is
        asserted, never the shipped list — `head-guard` is named only as the role whose ceiling the
        fixture moves, and the fixture's own `ingredientCount` is what it is compared against."""
        sockets = json.loads(tuning_mod.SOCKETS_PATH.read_text(encoding="utf-8"))
        ingredient = sockets["strainSplice"]["ingredientCount"]

        def tuning_and_enum(ceiling: int):
            fixture = json.loads(json.dumps(sockets))
            fixture["socketCeiling"]["head-guard"] = ceiling
            tuning = tuning_mod.load(sockets_path=_tmp_json(self, fixture))
            enum = schema_mod.combination_schema(
                tuning, supplied_families=SUPPLY.families, host_roles=tuning.host_roles(),
                granted_families=GRANTED)["properties"]["hostRole"]["enum"]
            return tuning, enum

        below, enum_below = tuning_and_enum(ingredient - 1)
        self.assertNotIn("head-guard", below.host_roles())
        self.assertNotIn("head-guard", enum_below)

        at, enum_at = tuning_and_enum(ingredient)
        self.assertIn("head-guard", at.host_roles())
        self.assertIn("head-guard", enum_at)
        # `null` stays legal in both — naming no role means "any chassis".
        self.assertIn(None, enum_at)
        self.assertIn(None, enum_below)


# ── the gem-supply precheck ─────────────────────────────────────────────────────────────────────

class SupplyTests(unittest.TestCase):

    def test_the_live_gem_corpus_supplies_the_ingredient_vocabulary(self):
        # Floor pins: sockets-gen g2 (2026-09-07). Exact counts rise as more gems ship.
        self.assertGreaterEqual(SUPPLY.gem_count, 60)
        self.assertGreaterEqual(SUPPLY.family_count, 54)
        self.assertEqual(SUPPLY.family_count, len(set(SUPPLY.families)))

    def test_every_ingredient_family_is_supplied_by_a_live_gem(self):
        # The schema's enum IS the supplied set, so a well-formed answer cannot name anything else.
        node = schema_mod.combination_schema(
            TUNING, supplied_families=SUPPLY.families, host_roles=HOST_ROLES,
            granted_families=GRANTED)["properties"]["ingredients"]["items"]
        self.assertEqual([], SUPPLY.refuse(node["enum"]))

    def test_the_precheck_refuses_an_unsupplied_family_before_any_call(self):
        with self.assertRaises(supply_mod.SupplyRefused) as ctx:
            supply_mod.precheck(["atom.might", "atom.nonesuch"], SUPPLY)
        self.assertIn("atom.nonesuch", str(ctx.exception))
        self.assertNotIn("atom.might", str(ctx.exception))

    def test_the_gating_metric_agrees_with_the_precheck_on_the_live_corpus(self):
        corpus = Corpus.load(ITEMS_ROOT)
        findings = CombinationIngredients().run(Ctx(corpus=corpus, adapter=None))
        self.assertEqual([], findings)
        # …and the legacy corpus's own ingredient families are all supplied, which is why.
        legacy = migrate_mod.load_legacy()
        wanted = {f for e in legacy for f in e.ingredient_families}
        self.assertEqual([], SUPPLY.refuse(sorted(wanted)))


# ── the kind rename, and the gate that must follow it ───────────────────────────────────────────

class KindMigrationTests(unittest.TestCase):

    def test_IngredientUnsatisfiable_gates_after_the_kind_rename(self):
        """⭐ The migration's real risk, closed permanently rather than at cutover.

        The 2026-09-04 ruling warns that the metric "must follow the kind, or a `gates = True` check
        quietly stops gating". A metric keyed on ONE spelling does exactly that — it goes on passing,
        over zero rows, and nothing says so.
        """
        self.assertTrue(CombinationIngredients.gates)
        self.assertEqual("Registration/IngredientUnsatisfiable", CombinationIngredients.id)

        for kind in COMBINATION_KINDS:
            corpus = Corpus()
            corpus.add(_entry("gem.a", "gem", {"family": "atom.might", "powerBand": "high"}))
            corpus.add(_entry("x.001", kind, {
                "name": "Test", "ingredients": [{"family": "atom.nonesuch"}]}))
            findings = CombinationIngredients().run(Ctx(corpus=corpus, adapter=None))
            self.assertEqual(1, len(findings), f"kind {kind!r} is not covered by the gate")
            self.assertEqual(Severity.GAP, findings[0].severity)
            self.assertEqual(kind, findings[0].evidence["kind"])

    def test_ingredient_unsatisfiable_still_gates_after_the_retire(self):
        """strain-splice-host SSH2.6: the rename bundle's own risk (spec-combination-regen.md
        rename bundle #1) — once `socket-word` is retired for real (SSH2.3's verb, invoked by
        SSH2.6), `COMBINATION_KINDS` drops it too. The gate must still cover `combination` alone,
        and a `socket-word`-kinded row (none can ship any more, but the metric itself must not
        silently rely on that) is simply not in scope any more — never a second, dead spelling kept
        "just in case"."""
        self.assertEqual(("combination",), COMBINATION_KINDS)
        corpus = Corpus()
        corpus.add(_entry("gem.a", "gem", {"family": "atom.might", "powerBand": "high"}))
        corpus.add(_entry("x.001", "combination", {
            "name": "Test", "ingredients": [{"family": "atom.nonesuch"}]}))
        findings = CombinationIngredients().run(Ctx(corpus=corpus, adapter=None))
        self.assertEqual(1, len(findings))
        self.assertEqual(Severity.GAP, findings[0].severity)
        self.assertEqual("combination", findings[0].evidence["kind"])

    def test_the_KINDS_assertion_still_holds(self):
        from seedsmith.adapters.items.kinds import KINDS
        # 15 -> 16, 2026-09-15 (empire-development Task 1.3a: additive `relic` kind,
        # spec-relic-item-kind.md §Design 1) — a reviewed vocabulary growth, not drift. The count is
        # pinned once, test_items_adapter.py (population-pin SE3.5, 2026-09-20) -- reads that same
        # live length, never a second literal.
        self.assertEqual(len(KINDS), len({k.kind for k in KINDS}))
        # SSH2.4: the rename landed -- `socket-word` is gone from this port, `combination` is in
        # its slot. See `test_the_kind_is_renamed_not_removed` below for the full proof (both ports,
        # field shape).
        self.assertIn("combination", {k.kind for k in KINDS})
        self.assertNotIn("socket-word", {k.kind for k in KINDS})

    def test_the_kind_is_renamed_not_removed(self):
        """strain-splice-host SSH2.4+SSH2.6 (rename bundle #2-#3, both now complete). Proves the
        rename on BOTH ports: Python's `KINDS` no longer names `socket-word` and does name
        `combination`, with the field shape transcribed from the C# `combination` row (never
        re-derived); and the C# port's own source text shows the SAME shape — `socket-word`'s
        `Defined(...)` call is gone on BOTH ports now (SSH2.4 deferred the C# removal until the
        legacy file was actually retired — real `dotnet run --project gk-forge/tools/ItemSeedValidator`
        showed removing it earlier produced a real `KindUnknown` + 25 `IdOutsideNamespace` findings
        against the still-live `sockwords.json`; SSH2.6's own `combogen-migrate --write` retired
        that file first, then removed this row)."""
        from seedsmith.adapters.items.kinds import KINDS

        kind_ids = {k.kind for k in KINDS}
        self.assertNotIn("socket-word", kind_ids)
        self.assertIn("combination", kind_ids)
        combo = next(k for k in KINDS if k.kind == "combination")
        self.assertEqual(combo.directory, "combinations")
        self.assertEqual(combo.namespace, "combinations")
        self.assertTrue({"shape", "aptitudes", "minSockets", "ingredients", "grants"}
                        <= combo.required)
        # SSH7.5/SSH7.6 moved the granted tier to TUNING, so `grantedTier` left BOTH the required set
        # and the optional set on both ports — a row carrying one is now refused. The Python row still
        # listed it after the C# row dropped it, which is how a `--write` re-emitted 35 rows the C#
        # gate then rejected as `UnknownKey` (found live 2026-09-22).
        self.assertNotIn("grantedTier", combo.required | combo.optional)
        self.assertTrue({"archetype", "hostRole", "hostFrame"} <= combo.optional)
        # socket-word's own shape is gone -- a combination has no runtimeId/fixedAtoms of its own.
        self.assertNotIn("runtimeId", combo.required | combo.optional)
        self.assertNotIn("fixedAtoms", combo.required | combo.optional)

        catalog_path = REPO_ROOT / "tools" / "ItemSeedValidator" / "Registries" / "KindCatalog.cs"
        self.assertTrue(catalog_path.exists())  # one of migrate.MIGRATION_SITES's own real paths
        catalog_src = catalog_path.read_text(encoding="utf-8")
        self.assertIn('Defined("combination"', catalog_src)
        self.assertNotIn('Defined("socket-word"', catalog_src)

    def test_a_combination_gets_the_stronger_model(self):
        """ISG7-follow-up (2026-09-21): the retired `socket-word` name is gone from
        `invents_identity`, not merely shadowed by `combination` — SSH2.6 retired the kind for real,
        so the old dual-listing was residue. `combination` keeps the stronger model on its own."""
        self.assertEqual(DEFAULT_MODEL_TIERS.strong, DEFAULT_MODEL_TIERS.for_kind("combination"))
        self.assertNotIn("socket-word", DEFAULT_MODEL_TIERS.invents_identity)

    def test_the_legacy_partition_is_retired_and_legality_report_reads_it_as_empty(self):
        """strain-splice-host SSH2.6: `combogen-migrate --write` has run for real —
        `data/seed/items/socket-words/sockwords.json` is gone (95 real `combination` entries from
        SSH2.5 replace the 25 legacy ones). `legality_report()`'s default call (no path override)
        must read this as the SUCCESS state — zero entries, zero illegal, zero legal — never a
        crash; a crash here would mean `items generate --kind combination`'s own dry-run/plan path
        (which calls this unconditionally) breaks for everyone the moment retirement lands."""
        self.assertFalse(migrate_mod.LEGACY_FILE.exists())
        self.assertEqual((), migrate_mod.load_legacy())
        report = migrate_mod.legality_report(TUNING, host_roles=HOST_ROLES)
        self.assertEqual(0, report.total)
        self.assertEqual((), report.legal)
        self.assertEqual((), report.illegal)
        self.assertEqual({}, report.problems)

    def test_every_migration_site_still_exists(self):
        self.assertEqual([], migrate_mod.missing_sites())
        # pin: closed-vocabulary migrate.MIGRATION_SITES -- the bundle's own remaining site count;
        # a new site is a reviewed change to the tuple's own declaration, not corpus growth.
        self.assertEqual(6, len(migrate_mod.MIGRATION_SITES))


# ── emit ────────────────────────────────────────────────────────────────────────────────────────

class EmitTests(unittest.TestCase):

    def test_the_same_ingredients_in_any_arrangement_fold_to_the_same_rows(self):
        # D41 at the emit layer, not only at the matcher.
        picks = ["atom.bulwark", "atom.might", "atom.bulwark", "atom.vitality"]
        rows = emit.ingredient_rows(picks, TUNING)
        for arrangement in ([picks[i] for i in order] for order in
                            ((3, 2, 1, 0), (1, 0, 3, 2), (2, 3, 0, 1))):
            self.assertEqual(rows, emit.ingredient_rows(arrangement, TUNING))
        self.assertEqual(TUNING.ingredient_count, sum(r.quantity for r in rows))

    def test_an_ingredient_row_carries_no_position(self):
        row = emit.ingredient_rows(["atom.might"] * 4, TUNING)[0].to_dict()
        self.assertNotIn("position", row)
        self.assertEqual({"family", "quantity"}, set(row))

    def test_the_emitted_entry_carries_no_tier_number(self):
        """SSH7.3 (spec-tier-ladder §3): no tier anywhere in an emitted row. Which insert tier an
        ingredient needs is the LADDER's reading at match time and which tier a combination grants is
        `baseTier[shape] + ladder[rung].grantDelta + attunement` at RUNTIME — a seed that authored
        either number would pin one against a ladder a balance pass may republish without regenerating
        anything."""
        entry = emit.assemble_entry(
            entry_id="combo.strain-tier-free", name_key="combination.strain-tier-free",
            name="Test Name", flavor="A flavour string that is long enough.",
            shape="strain", aptitudes=("Might",), archetype="offense",
            ingredient_families=["atom.might", "atom.might", "atom.cruelty", "atom.ferocity"],
            grants=["atom.savagery"], tuning=TUNING, host_role="armament-primary")

        self.assertNotIn("grantedTier", entry)
        for row in entry["ingredients"]:
            self.assertEqual({"family", "quantity"}, set(row))
        # …and nothing tier-shaped hides anywhere in the emitted document.
        text = json.dumps(entry)
        for banned in ("minTier", "grantedTier", "baseTier", "\"tier\""):
            self.assertNotIn(banned, text)
        # Identical families FOLD — the same four picks in another arrangement are byte-identical.
        again = emit.assemble_entry(
            entry_id="combo.strain-tier-free", name_key="combination.strain-tier-free",
            name="Test Name", flavor="A flavour string that is long enough.",
            shape="strain", aptitudes=("Might",), archetype="offense",
            ingredient_families=["atom.ferocity", "atom.might", "atom.cruelty", "atom.might"],
            grants=["atom.savagery"], tuning=TUNING, host_role="armament-primary")
        self.assertEqual(entry, again)

    def test_a_wrong_ingredient_count_is_refused_at_the_emit_boundary(self):
        with self.assertRaises(emit.IdRefused):
            emit.ingredient_rows(["atom.might"] * 3, TUNING)

    def test_min_sockets_is_derived_never_authored(self):
        self.assertEqual(TUNING.ingredient_count, emit.min_sockets(TUNING))

    def test_the_ladder_carries_the_rung_and_the_runtime_owns_the_bonus(self):
        """The one-rung ladder the shipped `minTierPlan` describes, and rung 1 grants no delta — the
        Python side's half of the granted-tier formula. The other half (the rung a concrete fill
        reaches, and attunement's bonus on top) is a RUNTIME fact and is C#'s
        (`ComboMatcher`/`CombinationEvaluator`, tested in ComboMatcherTests)."""
        self.assertEqual(1, len(TUNING.tier_ladder))
        rung = TUNING.tier_ladder[0]
        self.assertEqual(1, rung.rung)
        self.assertEqual(TUNING.min_tier_plan, rung.floors)
        self.assertEqual(0, rung.grant_delta)
        self.assertGreaterEqual(TUNING.base_tier_for("strain") + rung.grant_delta, 1)

    def test_resonance_affinity_stays_a_plus_one_and_is_not_re_specified_here(self):
        # ⚠ The two layers treat affinity differently ON PURPOSE — soft `+1` to Pure's effective
        # count, an enhanced tier for a Strain/Splice — and this module re-specifies neither.
        sockets = json.loads(tuning_mod.SOCKETS_PATH.read_text(encoding="utf-8"))
        self.assertEqual(1, sockets["resonance"]["attunedEffectiveCountBonus"])
        self.assertEqual(1, sockets["resonance"]["attunedTierBonus"])
        # …and nothing in this package READS Pure's own bonus. Asserted as the read shape
        # (`"attunedEffectiveCountBonus")`), because `tuning.py` names the key deliberately — in the
        # list of keys it REFUSES, which is the opposite of reading it.
        for path in sorted(COMBOGEN_DIR.glob("*.py")):
            self.assertNotIn('"attunedEffectiveCountBonus")', path.read_text(encoding="utf-8"))
        self.assertIn("attunedEffectiveCountBonus", tuning_mod.SOCKETS_OWNED_KEYS)


# ── the brief ───────────────────────────────────────────────────────────────────────────────────

class BriefTests(unittest.TestCase):

    def brief(self, cell) -> str:
        return brief_mod.build_brief(cell, TUNING, SUPPLY,
                                     granted_families=GRANTED, host_roles=HOST_ROLES)

    def test_the_brief_carries_the_roster_words_verbatim(self):
        cell = grid.strain_cells()[0]
        apt = cell.aptitudes[0]
        text = self.brief(cell)
        self.assertIn(apt.meaning, text)
        self.assertIn(apt.reading, text)

    def test_the_brief_states_no_number_the_schema_already_fixes(self):
        for cell in (grid.strain_cells()[0], grid.splice_cells()[0]):
            self.assertEqual([], brief_mod.spells_the_count(self.brief(cell),
                                                            TUNING.ingredient_count))

    def test_the_brief_names_no_element(self):
        # ⚠ No aptitude → element mapping is introduced; the gap stays visible.
        for cell in (grid.strain_cells()[0], grid.splice_cells()[0]):
            text = self.brief(cell).lower()
            for element in ("fire", "ice", "earth", "air", "light", "dark", "omni"):
                self.assertNotIn(f" {element} ", text)

    def test_a_brief_that_spelled_the_count_would_be_refused(self):
        # The guard is real, not decorative — proven by feeding it a text that breaks it.
        with self.assertRaises(brief_mod.BriefRefused):
            brief_mod.build_brief(
                grid.strain_cells()[0], TUNING, SUPPLY, granted_families=GRANTED,
                host_roles=HOST_ROLES + ("four-ingredient-role",))

    def test_a_combination_asks_for_a_mechanism_not_a_flat_add(self):
        text = self.brief(grid.strain_cells()[0])
        self.assertIn("MECHANISM", text)
        self.assertIn("volume discount with a name", text)

    def test_defense_strain_brief_does_not_pair_hit_harder_with_avoid_offense(self):
        """might-defense themes ship Hit harder + antiMotifs offense; brief must not paste both."""
        cell = next(c for c in grid.strain_cells()
                    if c.aptitudes[0].token == "might" and c.archetype == "defense")
        text = self.brief(cell)
        self.assertIn("Avoid entirely: offense", text)
        self.assertNotIn("Hit harder", text)
        self.assertIn("archetype is 'defense'", text)

    def test_splice_brief_frames_opposing_readings_as_fusion_material(self):
        cell = grid.splice_cells()[0]
        text = self.brief(cell)
        self.assertIn("Opposing or tensioned readings", text)
        self.assertIn("do not refuse the cell", text)


# ── the run plan ────────────────────────────────────────────────────────────────────────────────

class RunTests(unittest.TestCase):

    def test_the_plan_covers_every_cell_of_its_shape(self):
        strains = run_mod.plan_run(shape="strain", tuning=TUNING, supply=SUPPLY)
        splices = run_mod.plan_run(shape="splice", tuning=TUNING, supply=SUPPLY)
        # Same grid shape GridTests re-derives from live content -- never a second literal
        # (population-pin SE3.5, 2026-09-20).
        self.assertEqual(len(grid.strain_cells()), len(strains.subjects))
        self.assertEqual(len(grid.splice_cells()), len(splices.subjects))
        self.assertTrue(strains.complete and splices.complete)
        ids = [s.entry_id for s in strains.subjects] + [s.entry_id for s in splices.subjects]
        self.assertEqual(102, len(set(ids)))

    def test_re_running_over_an_unchanged_grid_is_byte_identical(self):
        first = run_mod.plan_run(shape="strain", tuning=TUNING, supply=SUPPLY)
        second = run_mod.plan_run(shape="strain", tuning=TUNING, supply=SUPPLY)
        self.assertEqual([s.to_dict() for s in first.subjects],
                         [s.to_dict() for s in second.subjects])
        self.assertEqual([s.brief for s in first.subjects], [s.brief for s in second.subjects])
        self.assertEqual(first.summary(), second.summary())

    def test_an_unknown_shape_is_refused(self):
        with self.assertRaises(ValueError):
            run_mod.plan_run(shape="word", tuning=TUNING, supply=SUPPLY)

    def test_the_catalogue_size_is_reported_as_127_against_the_45_bar(self):
        report = catalogue_mod.report(TUNING, strains=36, splices=66)
        self.assertEqual(25, report.resonances)
        self.assertEqual(127, report.total)
        self.assertEqual(45, report.bar)
        self.assertTrue(report.over_bar)
        self.assertEqual(2822, report.ratio_permille)     # 2.8x, computed not quoted
        payload = report.to_dict()
        self.assertFalse(payload["enforced"])
        self.assertEqual(2, len(payload["requiredMitigations"]))
        self.assertTrue(all(m["owner"] == catalogue_mod.MITIGATION_OWNER
                            for m in payload["requiredMitigations"]))

    def test_the_resonance_half_of_the_count_is_derived_from_module_16s_own_tuning(self):
        sockets = json.loads(tuning_mod.SOCKETS_PATH.read_text(encoding="utf-8"))
        core = json.loads((ITEMS_ROOT / "_registry" / "core.v1.json").read_text(encoding="utf-8"))
        expected = (len(core["elements"]["concrete"]) * len(sockets["resonance"]["pureThresholds"])
                    + len(sockets["resonance"]["ringOrder"]) + 1
                    + len(sockets["resonance"]["diversityThresholds"]))
        self.assertEqual(expected, catalogue_mod.generated_resonance_count())


# ── R13: the still-blocked report, and --retry-blocked's own ledger discipline ────────────────────

class StillBlockedReportTests(unittest.TestCase):
    """strain-splice-host SSH2.2 (`combination-regen` "Still-blocked cells"). Every test here uses a
    REAL `RunLedger` over a temp directory (the ledger file and the JSON report artefact are the
    thing under test, so disk is the right substrate — same precedent as `CliTests`/`AuthoredBatch
    Tests` isolating to `tempfile`), and a REAL `run_mod.plan_run` grid (never a synthetic Subject),
    so a real grid-id/subject-id shape defect would show up here rather than only in production."""

    def setUp(self) -> None:
        import tempfile

        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.ledger_root = Path(self._tmp.name)
        self.ledger = RunLedger(self.ledger_root / "combination-gen.ledger.json")
        self.plan = run_mod.plan_run(shape="strain", tuning=TUNING, supply=SUPPLY)
        self.blocked_subject = self.plan.subjects[0]
        self.persisted_subject = self.plan.subjects[1]

    def test_a_still_blocked_cell_is_reported_by_grid_id_and_never_withdrawn(self) -> None:
        self.ledger.mark_terminal(
            self.blocked_subject.subject_id, outcome="blocked",
            entry_id=self.blocked_subject.entry_id, attempts=3,
            blocked_reason="no ingredient family in the widened set fits this tension")

        rows = cli_mod._combination_still_blocked_rows(
            self.plan.subjects, self.ledger, shape="strain")

        self.assertEqual(len(rows), 1, rows)
        row = rows[0]
        # The grid id round-trips through the subject id's own `combination-{shape}-{cell.key}`
        # shape — recovered, never re-declared, so it cannot drift from what `run.plan_run` mints.
        self.assertEqual(f"combination-strain-{row['gridId']}", self.blocked_subject.subject_id)
        self.assertEqual(row["shape"], "strain")
        self.assertEqual(row["aptitudes"], list(self.blocked_subject.aptitudes))
        self.assertEqual(row["archetype"], self.blocked_subject.archetype)
        self.assertEqual(row["blockedReason"],
                         "no ingredient family in the widened set fits this tension")
        self.assertEqual(row["survivedReruns"], [])
        # Never withdrawn: the cell stays in the closed grid (this function never touches `grid.py`
        # or `plan.subjects`) and stays `blocked` in the ledger's own real rows.
        self.assertIn(self.blocked_subject, self.plan.subjects)
        self.assertEqual(self.ledger.read_done()[self.blocked_subject.subject_id]["outcome"],
                         "blocked")

    def test_an_escalated_cell_is_reported_by_id_rather_than_silently_dropped(self) -> None:
        """R13 reads "every cell is `entry` or listed by id". An escalated cell produced no entry
        AND no `blocked` row (the graph's validators refused every draft), so a report filtering on
        `blocked` alone loses it — measured 2026-09-21 on the real R11 re-run, where
        `combo.strain-ferocity-balance` escalated against the shipped-name guard."""
        self.ledger.mark_terminal(
            self.blocked_subject.subject_id, outcome="escalated",
            entry_id=self.blocked_subject.entry_id, attempts=3,
            defects=["name: 'Ironstead' is a fusion that does not decompose", "second defect"])

        rows = cli_mod._combination_still_blocked_rows(
            self.plan.subjects, self.ledger, shape="strain")

        self.assertEqual(len(rows), 1, rows)
        self.assertEqual(f"combination-strain-{rows[0]['gridId']}", self.blocked_subject.subject_id)
        self.assertEqual(rows[0]["outcome"], "escalated")
        self.assertIn("second defect", rows[0]["blockedReason"])
        # It is work remaining, not an authored cell: `--retry-blocked` re-attempts it.
        needing = cli_mod._combination_needing_work(self.plan, self.ledger, retry_blocked=True)
        self.assertIn(self.blocked_subject, needing)

    def test_a_never_attempted_cell_is_not_reported(self) -> None:
        # Untouched ledger: nothing is blocked yet, so nothing is reported — a still-blocked report
        # is a reading of REAL ledger rows, never a guess from the grid alone.
        rows = cli_mod._combination_still_blocked_rows(
            self.plan.subjects, self.ledger, shape="strain")
        self.assertEqual(rows, [])

    def test_still_blocked_report_records_which_rerun_a_cell_survived(self) -> None:
        self.ledger.mark_terminal(
            self.blocked_subject.subject_id, outcome="blocked",
            entry_id=self.blocked_subject.entry_id, attempts=1, blocked_reason="first reason")
        first_pass = cli_mod._combination_still_blocked_rows(
            self.plan.subjects, self.ledger, shape="strain", retry_label="widened-grants")
        self.assertEqual(first_pass[0]["survivedReruns"], ["widened-grants"])

        # A second retry pass under a DIFFERENT label, carrying the first label forward via
        # `prior_rows` (the JSON artefact's own last write, in real use) — the cell still answers
        # blocked, so the history accumulates rather than being overwritten.
        self.ledger.mark_terminal(
            self.blocked_subject.subject_id, outcome="blocked",
            entry_id=self.blocked_subject.entry_id, attempts=1, blocked_reason="second reason")
        second_pass = cli_mod._combination_still_blocked_rows(
            self.plan.subjects, self.ledger, shape="strain", retry_label="r11-helm",
            prior_rows=first_pass)
        self.assertEqual(second_pass[0]["survivedReruns"], ["widened-grants", "r11-helm"])
        self.assertEqual(second_pass[0]["blockedReason"], "second reason")

        # Re-reporting the SAME label twice in a row (e.g. the report regenerated without a real
        # retry happening in between) does not duplicate the last entry.
        third_pass = cli_mod._combination_still_blocked_rows(
            self.plan.subjects, self.ledger, shape="strain", retry_label="r11-helm",
            prior_rows=second_pass)
        self.assertEqual(third_pass[0]["survivedReruns"], ["widened-grants", "r11-helm"])

    def _persist(self, subjects, *, shape: str) -> None:
        prior = cli_mod._read_combination_still_blocked_prior(self.ledger_root)
        rows = cli_mod._combination_still_blocked_rows(
            subjects, self.ledger, shape=shape, prior_rows=prior)
        cli_mod._persist_combination_still_blocked_report(
            rows, shape=shape, ledger_root=self.ledger_root, prior_rows=prior)

    def test_the_still_blocked_artefact_merges_both_shapes_without_wiping_the_other(self) -> None:
        splice_plan = run_mod.plan_run(shape="splice", tuning=TUNING, supply=SUPPLY)
        splice_blocked = splice_plan.subjects[0]

        self.ledger.mark_terminal(
            self.blocked_subject.subject_id, outcome="blocked",
            entry_id=self.blocked_subject.entry_id, attempts=1, blocked_reason="strain reason")
        self._persist(self.plan.subjects, shape="strain")

        self.ledger.mark_terminal(
            splice_blocked.subject_id, outcome="blocked",
            entry_id=splice_blocked.entry_id, attempts=1, blocked_reason="splice reason")
        self._persist(splice_plan.subjects, shape="splice")

        doc = json.loads((self.ledger_root / "combination-still-blocked.json")
                         .read_text(encoding="utf-8"))
        shapes_present = {row["shape"] for row in doc["rows"]}
        self.assertEqual(shapes_present, {"strain", "splice"})
        self.assertEqual(len(doc["rows"]), 2)

    def test_dry_run_never_writes_the_still_blocked_artefact(self) -> None:
        """`--dry-run` reads and prints the report but never persists it -- only a real `--write`
        run does, matching every other path in `items generate --dry-run` (nothing here writes to
        the production tree implicitly)."""
        self.ledger.mark_terminal(
            self.blocked_subject.subject_id, outcome="blocked",
            entry_id=self.blocked_subject.entry_id, attempts=1, blocked_reason="reason")
        prior = cli_mod._read_combination_still_blocked_prior(self.ledger_root)
        cli_mod._combination_still_blocked_rows(
            self.plan.subjects, self.ledger, shape="strain", prior_rows=prior)
        # Reading/computing the report is the whole dry-run path; nothing writes unless the CLI
        # layer itself calls `_persist_combination_still_blocked_report`, which only happens under
        # `args.write` in `_cmd_items_combination` -- not exercised by a bare read here.
        self.assertFalse((self.ledger_root / "combination-still-blocked.json").exists())

    def test_a_refused_write_with_no_out_dir_never_touches_the_production_tree(self) -> None:
        """Real bug found while building this report: `--write` with no `--out-dir` and production
        defaults off is refused by `_cmd_items_combination_write` BEFORE any out-dir is resolved,
        but `_cmd_items_combination`'s own `ledger_root` still fell back to the REAL
        `authored_mod.COMBINATIONS_DIR` a few lines up (`Path(args.out_dir) if args.out_dir else
        authored_mod.COMBINATIONS_DIR`) — persisting the still-blocked report there would write
        into the real `gk-data/packs/fusion/data/seed/items/combinations/` as a side effect of a run that touched
        NOTHING else. Guarded by checking `args.out_dir` too, not just `args.write`."""
        import tempfile

        production_report = (REPO_ROOT / "data" / "seed" / "items" / "combinations"
                             / "combination-still-blocked.json")
        existed_before = production_report.exists()
        with tempfile.TemporaryDirectory() as temp:
            (Path(temp) / ".env").write_text("", encoding="utf-8")
            done = subprocess.run(
                [sys.executable, "-m", "seedsmith", "items", "generate", "--kind", "combination",
                 "--shape", "strain", "--write"],
                cwd=temp,
                capture_output=True, text=True, encoding="utf-8", errors="replace",
                env={**os.environ, "SEEDSMITH_LLM_ENDPOINT": "",
                     "SEEDSMITH_ALLOW_PRODUCTION_TREE": "0",
                     "PYTHONPATH": str(Path(__file__).resolve().parents[1])})
        self.assertEqual(3, done.returncode, done.stderr + done.stdout)
        self.assertEqual(existed_before, production_report.exists(),
                         "a refused write must not create the still-blocked artefact in production")

    def test_retry_blocked_never_reruns_an_authored_cell(self) -> None:
        self.ledger.mark_done(self.persisted_subject.subject_id, {
            "entryId": self.persisted_subject.entry_id,
            "entry": {"id": self.persisted_subject.entry_id},
        })
        self.ledger.mark_terminal(
            self.blocked_subject.subject_id, outcome="blocked",
            entry_id=self.blocked_subject.entry_id, attempts=2, blocked_reason="reason")

        without_retry = cli_mod._combination_needing_work(
            self.plan, self.ledger, retry_blocked=False)
        without_ids = {s.subject_id for s in without_retry}
        self.assertNotIn(self.persisted_subject.subject_id, without_ids)
        self.assertNotIn(self.blocked_subject.subject_id, without_ids)  # blocked reads valid too

        with_retry = cli_mod._combination_needing_work(
            self.plan, self.ledger, retry_blocked=True)
        with_ids = {s.subject_id for s in with_retry}
        self.assertIn(self.blocked_subject.subject_id, with_ids)
        self.assertNotIn(self.persisted_subject.subject_id, with_ids)


# ── the CLI ─────────────────────────────────────────────────────────────────────────────────────

class CliTests(unittest.TestCase):

    def _run(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-m", "seedsmith", *args],
            cwd=str(Path(__file__).resolve().parents[1]),
            capture_output=True, text=True, encoding="utf-8", errors="replace")

    def test_items_generate_kind_combination_plans_both_shapes(self):
        for shape, grid_size in (("strain", 36), ("splice", 66)):
            done = self._run("items", "generate", "--kind", "combination", "--shape", shape,
                             "--dry-run")
            self.assertEqual(0, done.returncode, done.stderr)
            payload = json.loads(done.stdout)
            # plannedBeforeLimit is the closed grid; toGenerate is after ledger resume.
            self.assertEqual(grid_size, payload["plannedBeforeLimit"])
            self.assertLessEqual(payload["toGenerate"], grid_size)
            self.assertEqual("combination", payload["kind"])
            self.assertEqual(127, payload["catalogue"]["total"])
            self.assertEqual(0, payload["legacyRetirement"]["legalAsCombinationsToday"])

    def test_write_is_refused_rather_than_writing_nothing(self):
        # Isolate from tools/seedsmith/.env so --write cannot fall through to a live endpoint.
        import tempfile
        with tempfile.TemporaryDirectory() as temp:
            (Path(temp) / ".env").write_text("", encoding="utf-8")
            done = subprocess.run(
                [sys.executable, "-m", "seedsmith", "items", "generate", "--kind", "combination",
                 "--shape", "strain", "--write"],
                cwd=temp,
                capture_output=True, text=True, encoding="utf-8", errors="replace",
                env={**os.environ, "SEEDSMITH_LLM_ENDPOINT": "",
                     "SEEDSMITH_ALLOW_PRODUCTION_TREE": "0",
                     "PYTHONPATH": str(Path(__file__).resolve().parents[1])})
        self.assertEqual(3, done.returncode, done.stderr + done.stdout)
        self.assertIn("refused", done.stderr)

    def test_population_is_refused_for_a_combination_rather_than_ignored(self):
        done = self._run("items", "generate", "--kind", "combination", "--shape", "strain",
                         "--population", "build")
        self.assertEqual(2, done.returncode)
        self.assertIn("does not apply", done.stderr)

    def test_overwrite_selects_exactly_the_named_grid_cells(self):
        """item-seed-gen ISG3. SSH2.5 needed to re-author cells that were `persisted` but wrong and
        had to walk the whole grid because no flag could name them; `plan_overwrite` already
        supported an id list, only the CLI did not expose it. Accepts the validator's entry id or
        the ledger's subject id."""
        for token, expected in (("combo.splice-composure-bulwark", 1),
                                ("combination-splice-composure-bulwark", 1),
                                ("combo.splice-composure-bulwark,combo.splice-might-fortitude", 2)):
            done = self._run("items", "generate", "--kind", "combination", "--shape", "splice",
                             "--dry-run", "--overwrite", token)
            self.assertEqual(0, done.returncode, done.stderr)
            payload = json.loads(done.stdout)
            self.assertEqual(expected, payload["toGenerate"])
            self.assertEqual(66, payload["plannedBeforeLimit"])

    def test_overwrite_naming_no_grid_cell_refuses_loudly(self):
        done = self._run("items", "generate", "--kind", "combination", "--shape", "splice",
                         "--dry-run", "--overwrite", "combo.splice-not-a-cell")
        self.assertEqual(2, done.returncode)
        self.assertIn("not a grid subject", done.stderr)

    def test_overwrite_and_retry_blocked_together_refuse(self):
        done = self._run("items", "generate", "--kind", "combination", "--shape", "splice",
                         "--dry-run", "--overwrite", "all", "--retry-blocked")
        self.assertEqual(2, done.returncode)
        self.assertIn("one, not both", done.stderr)

    def test_the_r11_step_refuses_while_a_tuning_host_role_has_no_base_reaching_four(self) -> None:
        """strain-splice-host SSH2.7 (R11 step, spec-combination-regen). The host set is derived
        from the TUNING ceilings, not from the base corpus, so with v2 ceilings (`head-guard` at
        the ingredient count) and an un-restamped corpus (no base row reaching four on the helm)
        the `--retry-blocked` re-run must refuse BY NAME before any model call. Fixture tuning +
        fixture corpus, so the rule is asserted rather than today's shipped rows."""
        v2 = tuning_mod.load()
        wanted = v2.ingredient_count
        self.assertIn("head-guard", v2.host_roles())

        # Every offered host role has a base reaching the count EXCEPT the helm, so the helm is the
        # only role the R11 arm can name — the fixture asserts the rule, not today's corpus.
        base_types = tempfile.TemporaryDirectory()
        self.addCleanup(base_types.cleanup)
        base_dir = Path(base_types.name)
        (base_dir / "fixture.json").write_text(json.dumps({
            "kind": "base-type",
            "entries": [
                {"id": f"bt.{i}", "role": role,
                 "socketMax": wanted - (1 if role == "head-guard" else 0)}
                for i, role in enumerate(v2.host_roles())
            ],
        }), encoding="utf-8")
        self.assertEqual(("head-guard",),
                         deps_mod.roles_without_a_base(v2, base_types_dir=base_dir))

        for extra in (["--dry-run"], ["--write"]):
            stderr = io.StringIO()
            with patch.object(tuning_mod, "load", return_value=v2), \
                 patch.object(deps_mod, "BASE_TYPES_DIR", base_dir), \
                 contextlib.redirect_stderr(stderr):
                code = cli_mod.main(["items", "generate", "--kind", "combination", "--shape",
                                     "strain", "--retry-blocked", *extra])
            self.assertEqual(cli_mod.EXIT_REFUSED, code, stderr.getvalue())
            self.assertIn("head-guard", stderr.getvalue())
            # The refusal is the FIRST thing -- a `--write` run with no endpoint would otherwise
            # refuse on the missing transport instead, which is the proof no model path was reached.
            self.assertIn("before any model call", stderr.getvalue())
            self.assertNotIn("no transport", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()


# ── SSH7.4: the deterministic re-emit ───────────────────────────────────────────────────────────

class ReemitTests(unittest.TestCase):
    """`authored.reemit` — the shipped corpus re-shaped from the run ledger, no model call."""

    def setUp(self) -> None:
        from seedsmith.adapters.items.combogen import authored as authored_mod
        self.authored = authored_mod
        self.tuning = TUNING

    def _ledger_entries(self, shape: str) -> "list[dict]":
        return self.authored.entries_from_ledger(shape)

    def test_reemit_is_byte_identical_on_a_second_run(self) -> None:
        for shape in ("strain", "splice"):
            with self.subTest(shape):
                once = self.authored.reemit(shape, tuning=self.tuning)
                twice = [self.authored.reemit_entry(entry, self.tuning) for entry in once]
                self.assertEqual(once, twice)

    def test_reemit_changes_no_model_answer(self) -> None:
        """Families (as a multiset), grants, name, flavor, shape, aptitudes, archetype and the host
        pins are carried across verbatim; the emitted SHAPE is what moves."""
        for shape in ("strain", "splice"):
            current = {entry["id"]: entry for entry in self._ledger_entries(shape)}
            reemitted = {entry["id"]: entry for entry in self.authored.reemit(shape, tuning=self.tuning)}
            with self.subTest(shape):
                self.assertEqual(set(current), set(reemitted))
                for entry_id, entry in reemitted.items():
                    before = current[entry_id]
                    for field in ("name", "flavor", "grants", "hostRole", "hostFrame", "archetype"):
                        self.assertEqual(before.get(field), entry.get(field), field)
                    self.assertEqual(sorted(before.get("aptitudes") or []),
                                     sorted(entry.get("aptitudes") or []))
                    families_before = sorted(
                        f for row in before["ingredients"] for f in [row["family"]] * int(row.get("quantity", 1)))
                    families_after = sorted(
                        f for row in entry["ingredients"] for f in [row["family"]] * int(row.get("quantity", 1)))
                    self.assertEqual(families_before, families_after)
                    # …and the shape moved: no tier number anywhere in the re-emitted row.
                    self.assertNotIn("grantedTier", entry)
                    for row in entry["ingredients"]:
                        self.assertEqual({"family", "quantity"}, set(row))

    def test_the_reemit_verb_is_a_dry_run_by_default(self) -> None:
        from seedsmith.report import cli as cli_mod
        import argparse as ap
        args = ap.Namespace(write=False, shape="strain", out_dir="", ledger="",
                            model="combogen-reemit/1", authored_utc="1970-01-01T00:00:00Z")
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = cli_mod._cmd_items_combogen_reemit(args)
        self.assertEqual(cli_mod.EXIT_CLEAN, code)
        payload = json.loads(out.getvalue())
        self.assertFalse(payload["write"])
        self.assertGreater(payload["shapes"]["strain"]["entries"], 0)
