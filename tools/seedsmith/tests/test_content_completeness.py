"""Task 3 (seedsmith-content-standard) — the generalized missing-field metric registry, proven
byte-identical to `Quality/FlavourMissing` on the REAL committed items corpus (not synthetic),
per spec-content-completeness-core.md §10's worked-example #2.

    python -m pytest gk-forge/tools/seedsmith/tests/test_content_completeness.py -q
"""
from __future__ import annotations

import unittest
from pathlib import Path

from seedsmith.adapters.items import ItemsAdapter
from seedsmith.corpus import Corpus, Entry
from seedsmith.metrics import Ctx, MetricRegistry, run_all
from seedsmith.metrics.content_completeness import (
    CompletenessSpec,
    ContentFieldMissing,
    ContentLanguageContamination,
    clear_registry,
    register_completeness,
    registered_specs,
)
from seedsmith.metrics.quality import FLAVOR_EXPECTED_KINDS, FlavourMissing

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

LIVE_ITEMS_ROOT = _owned("data/seed/items")


class RegistryMechanicsTests(unittest.TestCase):
    def setUp(self) -> None:
        clear_registry()

    def tearDown(self) -> None:
        clear_registry()

    def test_a_new_domain_registers_in_one_call_no_edit_to_shared_internals(self) -> None:
        register_completeness(CompletenessSpec(domain="widgets", kinds=frozenset({"gadget"}),
                                               field="blurb"))
        self.assertEqual(len(registered_specs()), 1)
        self.assertEqual(registered_specs()[0].domain, "widgets")

    def test_default_missing_check_is_falsy(self) -> None:
        spec = CompletenessSpec(domain="d", kinds=frozenset({"k"}), field="flavor")

        class FakeEntry:
            def get(self, key, default=None):
                return {"flavor": ""}.get(key, default)

        self.assertTrue(spec.missing(FakeEntry()))

    def test_is_missing_override_replaces_the_falsy_check(self) -> None:
        # A domain where an EMPTY STRING is a real, intentional value — only `None` counts as
        # missing (the plan's own Risks-table failure mode this override exists to prevent).
        spec = CompletenessSpec(domain="d", kinds=frozenset({"k"}), field="flavor",
                                is_missing=lambda data: data.get("flavor") is None)

        class FakeEntry:
            data = {"flavor": ""}

            def get(self, key, default=None):
                return self.data.get(key, default)

        self.assertFalse(spec.missing(FakeEntry()))


@unittest.skipUnless(LIVE_ITEMS_ROOT.is_dir(), "live item corpus not present in this checkout")
class ByteIdenticalToFlavourMissingTests(unittest.TestCase):
    """The real proof: register items' own FLAVOR_EXPECTED_KINDS/`flavor` shape as a
    CompletenessSpec and confirm `Content/FieldMissing` finds EXACTLY what `Quality/FlavourMissing`
    finds on the SAME real corpus — the generalization must be additive, never a behavior change."""

    def setUp(self) -> None:
        clear_registry()
        register_completeness(CompletenessSpec(
            domain="items", kinds=FLAVOR_EXPECTED_KINDS, field="flavor"))

    def tearDown(self) -> None:
        clear_registry()

    def test_same_missing_and_total_counts_per_kind_as_the_original_metric(self) -> None:
        corpus = Corpus.load(LIVE_ITEMS_ROOT)
        ctx = Ctx(corpus=corpus, adapter=ItemsAdapter())

        original_registry = MetricRegistry()
        original_registry.register(FlavourMissing())
        original = {f.subject: f for f in run_all(original_registry, ctx)}

        generalized_registry = MetricRegistry()
        generalized_registry.register(ContentFieldMissing())
        generalized = {f.subject.split(":", 1)[1]: f
                      for f in run_all(generalized_registry, ctx)}

        self.assertTrue(original)
        self.assertEqual(set(original.keys()), set(generalized.keys()))
        for kind, orig_finding in original.items():
            gen_finding = generalized[kind]
            self.assertEqual(orig_finding.evidence["missingCount"],
                             gen_finding.evidence["missingCount"], kind)
            self.assertEqual(orig_finding.evidence["totalCount"],
                             gen_finding.evidence["totalCount"], kind)


class LanguageContaminationMetricTests(unittest.TestCase):
    """Task 4b's second acceptance bullet: the fixed bidirectional check must be reachable through
    `core`'s own registry, not left as a creatures/passive-tree-only import."""

    REAL_DUNGEON_DEFECT_FLAVOR = (
        "A towering silhouette of smoke and embers coalesces in the center of the chamber. It "
        "offers to bolster your party's offensive火力, turning your strikes into torrents of "
        "hellfire, but it demands a portion of your vitality as a permanent 分配 of your life "
        "force to its own furnace."
    )

    def setUp(self) -> None:
        clear_registry()
        register_completeness(CompletenessSpec(
            domain="dungeon", kinds=frozenset({"event"}), field="flavor"))

    def tearDown(self) -> None:
        clear_registry()

    def _corpus_with(self, flavor: str) -> Corpus:
        corpus = Corpus()
        corpus.add(Entry(id="event.bargain-creature.allpeater-001", kind="event",
                         partition="dungeon", path="events/x.json",
                         data={"flavor": flavor}))
        return corpus

    def test_the_real_dungeon_defect_text_is_caught_through_the_registry(self) -> None:
        corpus = self._corpus_with(self.REAL_DUNGEON_DEFECT_FLAVOR)
        registry = MetricRegistry()
        registry.register(ContentLanguageContamination())
        findings = run_all(registry, Ctx(corpus=corpus, adapter=None))

        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].subject, "dungeon:event.bargain-creature.allpeater-001")

    def test_clean_english_flavor_produces_no_findings(self) -> None:
        corpus = self._corpus_with("The bone grows dense and heavy under the weight of struggle.")
        registry = MetricRegistry()
        registry.register(ContentLanguageContamination())
        findings = run_all(registry, Ctx(corpus=corpus, adapter=None))

        self.assertEqual(findings, [])


@unittest.skipUnless(LIVE_ITEMS_ROOT.is_dir(), "live item corpus not present in this checkout")
class ProductionRegistrationTests(unittest.TestCase):
    """seedsmith-content-standard Task 6: a REAL gap found building `content-completeness-items` —
    Phase 0 (Task 3) built the registry and the metric, but nothing outside this test file's own
    `setUp`/`tearDown` ever called `register_completeness`, so `Content/FieldMissing` reported
    NOTHING on a real `python -m seedsmith.report.cli check` run even though every other piece was
    wired. `report.cli.build_registry()` (the one real production assembly point every real
    invocation goes through) now registers items' own `CompletenessSpec` itself — this proves that
    wiring directly, through the real function, not a hand-rolled registry standing in for it."""

    def setUp(self) -> None:
        clear_registry()

    def tearDown(self) -> None:
        clear_registry()

    def test_build_registry_registers_the_items_spec_and_finds_real_gaps(self) -> None:
        from seedsmith.report.cli import build_registry

        registry = build_registry()
        specs = registered_specs()
        self.assertTrue(any(s.domain == "items" and s.field == "flavor" for s in specs),
                        "report.cli.build_registry() must register items' own completeness spec")

        corpus = Corpus.load(LIVE_ITEMS_ROOT)
        ctx = Ctx(corpus=corpus, adapter=ItemsAdapter())
        findings = {f.subject: f for f in run_all(registry, ctx)
                   if f.metric == "Content/FieldMissing"}

        original_registry = MetricRegistry()
        original_registry.register(FlavourMissing())
        original = {f.subject: f for f in run_all(original_registry, ctx)}

        self.assertTrue(original, "the real items corpus must have at least one real missing-flavor "
                                  "gap for this proof to mean anything")
        for kind, orig_finding in original.items():
            gen_finding = findings[f"items:{kind}"]
            self.assertEqual(orig_finding.evidence["missingCount"],
                             gen_finding.evidence["missingCount"], kind)

    def test_build_registry_is_safe_to_call_more_than_once_in_one_process(self) -> None:
        """`build_registry()` runs once per real CLI invocation (a fresh process) but many times
        within one pytest process — `register_completeness`'s own idempotency (content_completeness.
        py) is what keeps a second call from double-counting the same missing entries."""
        from seedsmith.report.cli import build_registry

        build_registry()
        build_registry()
        specs = [s for s in registered_specs() if s.domain == "items" and s.field == "flavor"]
        self.assertEqual(len(specs), 1, "calling build_registry() twice must not duplicate the spec")


if __name__ == "__main__":
    unittest.main()
