"""Tests for `content-completeness-actions` (Task 8, `seedsmith-content-standard`) — actions'
adoption of the shared engine from `content-completeness-core`, proven against the REAL committed
action corpus (`gk-data/packs/fusion/data/seed/actions/committed-round-1.json`, `committed-round-2.json`), not a
synthetic fixture, per Task 8's own acceptance ("the real committed action corpus... gains real
`_provenance` on a fresh generation pass" / "the new missing-field metric reports real findings (or
a real clean pass) against real committed data").

    python -m pytest gk-forge/tools/seedsmith/tests/test_actions_description_completeness.py -q
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from seedsmith.adapters.actions import ActionsAdapter, load_committed  # noqa: E402
from seedsmith.adapters.actions.description_backfill import (  # noqa: E402
    ACTIONS_COMPLETENESS_SPEC,
)
from seedsmith.adapters.actions.generate_action_descriptions import (  # noqa: E402
    ACTIONS_ROOT, LEDGER_PATH, backfill, is_authored, plan,
)
from seedsmith.corpus import Corpus, Entry  # noqa: E402
from seedsmith.metrics import Ctx, MetricRegistry, run_all  # noqa: E402
from seedsmith.metrics.content_completeness import (  # noqa: E402
    CompletenessSpec, ContentFieldMissing, ContentLanguageContamination, clear_registry,
    register_completeness, registered_specs,
)
from seedsmith.pipeline.llm_caller import LlmCallerConfig  # noqa: E402
from seedsmith.pipeline.provenance import PROVENANCE_FIELD  # noqa: E402
from seedsmith.pipeline.run_ledger import RunLedger  # noqa: E402
from seedsmith.report.cli import build_registry  # noqa: E402

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

LIVE_ACTIONS_ROOT = _owned("data/seed/actions")


def _authored_entry_ids(root: Path) -> "dict[str, list[str]]":
    """Every file under `root` whose OWN `_meta.authored` declares it authored → its entry ids.

    Enumerated from the tree rather than named, so the guard covers an authored file that lands later
    instead of only the one this lane happened to find (validation-ssot.md — assert the contract, never
    a transcription of today's population).
    """
    out: "dict[str, list[str]]" = {}
    for path in sorted(root.rglob("*.json")):
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        meta = doc.get("_meta") if isinstance(doc, dict) else None
        if not isinstance(meta, dict) or not meta.get("authored"):
            continue
        out[path.relative_to(root).as_posix()] = [
            e["id"] for e in (doc.get("entries") or []) if isinstance(e, dict) and e.get("id")]
    return out


class ActionsSpecShapeTests(unittest.TestCase):
    """§2's own decision: `description` is the missing-content field, `action-seed` the only kind,
    default falsy-check (no `is_missing` override — an action never has a legitimate reason to
    carry an intentionally-empty description)."""

    def test_spec_names_description_on_action_seed(self) -> None:
        self.assertEqual(ACTIONS_COMPLETENESS_SPEC.domain, "actions")
        self.assertEqual(ACTIONS_COMPLETENESS_SPEC.kinds, frozenset({"action-seed"}))
        self.assertEqual(ACTIONS_COMPLETENESS_SPEC.field, "description")
        self.assertIsNone(ACTIONS_COMPLETENESS_SPEC.is_missing)

    def test_build_registry_registers_it_exactly_once_across_repeated_calls(self) -> None:
        # The real defect content_completeness.py's own `register_completeness` was fixed for
        # (Task 6, `content-completeness-items`) — proven here for actions' own spec, not just
        # items': calling build_registry() twice must not double the spec.
        build_registry()
        build_registry()
        count = sum(1 for s in registered_specs() if s.domain == "actions")
        self.assertEqual(count, 1)


class DetectorActuallyDetectsTests(unittest.TestCase):
    """The real proof the metric WORKS, not just that a real corpus happens to be clean already
    (a detector that always reports clean would pass a clean-corpus-only test too) — mirrors
    `test_content_completeness.py`'s own `RegistryMechanicsTests` shape for items."""

    def setUp(self) -> None:
        clear_registry()
        register_completeness(ACTIONS_COMPLETENESS_SPEC)

    def tearDown(self) -> None:
        clear_registry()

    def _corpus(self, *, with_description: bool) -> Corpus:
        corpus = Corpus()
        corpus.add(Entry(id="action.general.9001", kind="action-seed", partition="actions",
                         path="committed-round-9.json",
                         data={"id": "action.general.9001", "name": "Test Action",
                              "description": "A test line." if with_description else None}))
        corpus.add(Entry(id="action.general.9002", kind="action-seed", partition="actions",
                         path="committed-round-9.json",
                         data={"id": "action.general.9002", "name": "Test Action Two",
                              "description": "Another real test line."}))
        return corpus

    def test_one_missing_description_is_reported(self) -> None:
        registry = MetricRegistry()
        registry.register(ContentFieldMissing())
        findings = run_all(registry, Ctx(corpus=self._corpus(with_description=False), adapter=None))

        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].subject, "actions:action-seed")
        self.assertEqual(findings[0].evidence["missingCount"], 1)
        self.assertEqual(findings[0].evidence["totalCount"], 2)

    def test_no_finding_when_every_entry_has_a_description(self) -> None:
        registry = MetricRegistry()
        registry.register(ContentFieldMissing())
        findings = run_all(registry, Ctx(corpus=self._corpus(with_description=True), adapter=None))

        self.assertEqual(findings, [])


@unittest.skipUnless(LIVE_ACTIONS_ROOT.is_dir(), "live action corpus not present in this checkout")
class RealCommittedCorpusCleanPassTests(unittest.TestCase):
    """Task 8 acceptance bullet 2, against the REAL corpus post-generation-pass (Task 8's own real
    run, 2026-09-08 — see the evidence log for the exact command and its output). If a future
    committed action ever ships without a `description`, this test starts failing for a real
    reason, which is the point."""

    def test_load_committed_reports_zero_loader_findings(self) -> None:
        # `_runs/` (this task's own new ledger location) must be a DECLARED excluded prefix, not
        # an undeclared-prefix finding — proves the `_manifest.json` edit actually took.
        result = load_committed(LIVE_ACTIONS_ROOT)
        self.assertEqual(result.findings, [])

    def test_content_field_missing_is_clean_on_the_real_corpus(self) -> None:
        result = load_committed(LIVE_ACTIONS_ROOT)
        ctx = Ctx(corpus=result.corpus, adapter=ActionsAdapter())

        clear_registry()
        register_completeness(ACTIONS_COMPLETENESS_SPEC)
        try:
            registry = MetricRegistry()
            registry.register(ContentFieldMissing())
            findings = run_all(registry, ctx)
        finally:
            clear_registry()

        entries = result.corpus.by_kind("action-seed")
        self.assertGreater(len(entries), 0, "sanity: the real corpus has real action-seed rows")
        self.assertEqual(findings, [])

    def test_content_language_contamination_is_clean_on_the_real_corpus(self) -> None:
        result = load_committed(LIVE_ACTIONS_ROOT)
        ctx = Ctx(corpus=result.corpus, adapter=ActionsAdapter())

        clear_registry()
        register_completeness(ACTIONS_COMPLETENESS_SPEC)
        try:
            registry = MetricRegistry()
            registry.register(ContentLanguageContamination())
            findings = run_all(registry, ctx)
        finally:
            clear_registry()

        self.assertEqual(findings, [])

    def test_every_real_committed_action_carries_provenance(self) -> None:
        # ⚠ CORRECTED 2026-09-23 (lane sgc-6). This asserted `description` AND a
        # `description_backfill` `_provenance` on EVERY `action-seed` entry, which contradicts the
        # hand-authored `gk-data/packs/fusion/data/seed/actions/authored-basics.json`: its own `_meta.authored` says the row
        # "Deliberately carries no `_provenance` block" because that absence is what marks authored
        # content apart from generator output. The blanket form therefore demanded the exact hand-edit
        # the authored-content rule forbids — and the backfill PLAN targeted that row, so a real run
        # would have satisfied it by overwriting authored prose (see `is_authored`). The contract is
        # split: GENERATED rows carry both, AUTHORED rows carry a description and NO provenance.
        result = load_committed(LIVE_ACTIONS_ROOT)
        entries = result.corpus.by_kind("action-seed")
        self.assertGreater(len(entries), 0)
        generated = [e for e in entries if not is_authored(e)]
        authored = [e for e in entries if is_authored(e)]
        self.assertTrue(generated, "no generated action-seed row found — the corpus moved")
        for entry in generated:
            self.assertTrue(entry.get("description"), entry.id)
            prov = entry.get(PROVENANCE_FIELD)
            self.assertIsNotNone(prov, entry.id)
            self.assertEqual(prov["pipeline"], "seedsmith.adapters.actions.description_backfill")
            self.assertIn("stalenessKey", prov)
        for entry in authored:
            # the authored marker IS the absence of `_provenance`; stamping one would be the defect
            self.assertIsNone(entry.get(PROVENANCE_FIELD), entry.id)
            self.assertTrue(entry.get("description"), entry.id)

    def test_the_backfill_plan_never_targets_authored_content(self) -> None:
        """`authored-basics.json`'s `_meta.authored` states the rule — "A generator must never write
        here, and a regeneration run must never overwrite it" — so no plan may name its rows, however
        absent they are from the ledger. Measured 2026-09-23: the plan returned
        `['act.attack', 'action.family.academic.004']`, i.e. it targeted the authored row.

        Asserted STRUCTURALLY, over every file in the tree that declares itself authored — never on the
        one id this lane happened to find. A new authored file is covered the moment it lands, which is
        the difference between a contract and a transcription.
        """
        root = LIVE_ACTIONS_ROOT
        authored = _authored_entry_ids(root)
        self.assertTrue(authored, "no file under the live actions tree declares _meta.authored")
        authored_ids = {i for ids in authored.values() for i in ids}
        self.assertIn("act.attack", authored_ids)

        entries = {e.id: e for e in load_committed(root).corpus.by_kind("action-seed")}
        planned = plan(actions_root=root, ledger_path=LEDGER_PATH)
        self.assertEqual([i for i in planned if i in authored_ids], [])
        self.assertEqual([i for i in planned if is_authored(entries[i])], [])
        # ⚠ CORRECTED 2026-09-24 (mega-merge QC fix cycle 5). The prior form pinned the SGC5-F4 gap
        # itself open (`assertIn("action.family.academic.004", planned)`). Once that gap was repaired
        # via the sanctioned backfill the pin inverted into a failure that demanded the bug return —
        # the transcription the docstring warns against. Structural replacement: every planned id is a
        # real committed `action-seed` row, so the plan can never name a phantom; and the corpus it
        # draws from is non-empty, so an empty automatic plan means "all done", not "the loader broke".
        self.assertTrue(entries, "the live actions corpus loaded no action-seed rows")
        self.assertTrue(set(planned).issubset(entries), set(planned) - set(entries))
        # `--force` is the "regenerate everything" escape hatch and therefore the MOST dangerous path
        # for this rule: it bypasses the ledger, so only `is_authored` stands between it and the
        # authored file. Measured 2026-09-23: 180 targets, `act.attack` absent.
        forced = plan(actions_root=root, ledger_path=LEDGER_PATH, force=True)
        self.assertGreater(len(forced), len(planned))
        self.assertEqual([i for i in forced if i in authored_ids], [])
        self.assertEqual([i for i in forced if is_authored(entries[i])], [])

    def test_resumed_plan_is_empty_now_that_every_real_action_has_a_description(self) -> None:
        # The automatic path (`plan_missing`, via `plan()`) must be a no-op once every subject has
        # a real ledger entry — the resolved automatic-backfill contract (spec-content-
        # completeness-core.md §3): existing content is never regenerated on a resumed run.
        self.assertEqual(plan(actions_root=LIVE_ACTIONS_ROOT, ledger_path=LEDGER_PATH), [])

    def test_automatic_backfill_makes_zero_model_calls_and_writes_nothing_when_all_done(self) -> None:
        # `config` is real but unreachable-by-construction here on purpose: if this ever tried to
        # call it, the test would hang/fail on connection rather than silently pass, which is the
        # point — the automatic path must resolve entirely from the ledger, no network involved.
        unreachable = LlmCallerConfig(endpoint="http://127.0.0.1:1", attempts=1, timeout=0.2)
        result = backfill(actions_root=LIVE_ACTIONS_ROOT, ledger_path=LEDGER_PATH,
                          config=unreachable, dry_run=False)
        self.assertEqual(result["generated"], [])


class ManualForceEscapeHatchTests(unittest.TestCase):
    """Proves `--force` reaches the ledger's own already-real `RunLedger.force` contract for
    actions specifically, without ever touching the real committed files (dry_run=True — the
    planning half only, matching `test_backfill_loop.py`'s own "no model call needed to prove the
    plan" discipline)."""

    def test_force_all_targets_every_id_even_though_none_are_missing(self) -> None:
        tmp_dir = tempfile.mkdtemp()
        ledger = RunLedger(Path(tmp_dir) / "x.ledger.json")
        ledger.mark_done("action.general.0001", {"promptVersion": "x"})

        forced = plan(actions_root=LIVE_ACTIONS_ROOT, ledger_path=ledger.path, force=True,
                     only=("action.general.0001",))
        self.assertEqual(forced, ["action.general.0001"])


if __name__ == "__main__":
    unittest.main()
