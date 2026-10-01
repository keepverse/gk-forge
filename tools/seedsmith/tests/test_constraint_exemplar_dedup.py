"""Tests for seedsmith.metrics.{constraint,exemplar,dedup} (tasks/seedsmith-todo.md, S7).

    python -m pytest gk-forge/tools/seedsmith/tests/test_constraint_exemplar_dedup.py -v
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from seedsmith.workspace_roots import seed_root  # noqa: E402
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from seedsmith.adapters.base import KindSpec  # noqa: E402
from seedsmith.adapters.creatures import CreaturesAdapter  # noqa: E402
from seedsmith.adapters.items import ItemsAdapter  # noqa: E402
from seedsmith.corpus import Corpus  # noqa: E402
from seedsmith.metrics import Ctx, MetricRegistry, Severity, run_all  # noqa: E402
from seedsmith.metrics.constraint import KNOWN_RULES, Constraint, RuleBinding  # noqa: E402
from seedsmith.metrics.dedup import (  # noqa: E402
    SemanticDedup,
    jaccard_estimate,
    minhash_signature,
    shingles,
)
from seedsmith.metrics.exemplar import ExemplarConformance  # noqa: E402


class _StubAdapterWithDedupFields:
    """Minimal adapter double exposing only .kinds(), which is all SemanticDedup reads."""

    def __init__(self, specs: "list[KindSpec]") -> None:
        self._specs = specs

    def kinds(self) -> "list[KindSpec]":
        return self._specs


def write(root: Path, rel_path: str, kind: str, entries: list, partition: str = "p") -> None:
    directory = root / Path(rel_path).parent
    directory.mkdir(parents=True, exist_ok=True)
    doc = {"kind": kind, "_meta": {"partition": partition}, "entries": entries}
    (root / rel_path).write_text(json.dumps(doc), encoding="utf-8")


class ConstraintManifestTests(unittest.TestCase):
    def test_the_real_manifest_has_no_currently_unbound_rule(self) -> None:
        # Every rule in KNOWN_RULES was individually verified (grep against the C# source, or
        # against seedsmith.metrics.linkage) to have at least one binding — this pins that
        # verification as a regression check, not a live claim about undiscovered lane-doc rules.
        registry = MetricRegistry()
        registry.register(Constraint())
        findings = run_all(registry, Ctx(corpus=None, adapter=None))
        self.assertEqual(findings, [])

    def test_an_unbound_rule_is_reported(self) -> None:
        rules = KNOWN_RULES + (
            RuleBinding("HypotheticalUnboundRule", "a rule nobody wrote a check for",
                       "some-lane-doc.md", frozenset()),
        )
        registry = MetricRegistry()
        registry.register(Constraint(rules=rules))
        findings = run_all(registry, Ctx(corpus=None, adapter=None))

        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].subject, "HypotheticalUnboundRule")
        self.assertEqual(findings[0].severity, Severity.GAP)

    def test_set_role_not_hybrid_core_is_bound_only_in_seedsmith_not_csharp(self) -> None:
        # The specific correction this task made to spec-metrics.md: verified live against
        # gk-forge/tools/ItemSeedValidator/Checks/*.cs (no "hybrid" match anywhere).
        rule = next(r for r in KNOWN_RULES if r.rule_id == "SetRoleNotHybridCore")
        self.assertEqual(rule.bound_in, frozenset({"seedsmith"}))


class ExemplarConformanceTests(unittest.TestCase):
    """Replays the three historical exemplar defects as fixtures."""

    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp())
        self.adapter = ItemsAdapter()

    def test_missing_required_power_axis_on_a_unique_exemplar_is_caught(self) -> None:
        write(self.root, "_exemplars/unique.json", "unique", [{
            "id": "unique.exemplar-001", "nameKey": "u.ex1", "name": "Exemplar",
            "frame": "plant", "baseType": "item.plant-stem-a-001", "rarity": "grafted",
            "fixedAtoms": [], "counterPressure": {}, "tags": [],
            # powerAxis deliberately omitted — the exact historical defect
        }])
        corpus = Corpus.load(self.root)
        registry = MetricRegistry()
        registry.register(ExemplarConformance())
        findings = run_all(registry, Ctx(corpus=corpus, adapter=self.adapter))

        codes = {f.evidence["code"] for f in findings}
        self.assertIn("RequiredFieldMissing", codes)
        missing_finding = next(f for f in findings if f.evidence["code"] == "RequiredFieldMissing")
        self.assertIn("powerAxis", missing_finding.evidence["missing"])

    def test_set_exemplar_teaching_members_by_role_alone_is_caught(self) -> None:
        write(self.root, "_exemplars/set.json", "set", [{
            "id": "set.exemplar-001", "nameKey": "s.ex1", "name": "Exemplar Set",
            "themeKey": "ex", "members": [{"role": "core-guard"}, {"role": "head-guard"}],
            "thresholds": [{"pieces": 2}],
        }])
        corpus = Corpus.load(self.root)
        registry = MetricRegistry()
        registry.register(ExemplarConformance())
        findings = run_all(registry, Ctx(corpus=corpus, adapter=self.adapter))

        codes = {f.evidence["code"] for f in findings}
        self.assertIn("SetUncompletable", codes)

    def test_an_unknown_field_on_an_exemplar_is_caught(self) -> None:
        # A display-template-shaped defect (wrong/extra field) generalized: any exemplar
        # carrying a field its KindSpec does not allow teaches the wrong contract.
        write(self.root, "_exemplars/gem.json", "gem", [{
            "id": "gem.exemplar-001", "nameKey": "g.ex1", "name": "Exemplar Gem",
            "family": "atom.vitality", "powerBand": "low",
            "totallyMadeUpField": "should not be here",
        }])
        corpus = Corpus.load(self.root)
        registry = MetricRegistry()
        registry.register(ExemplarConformance())
        findings = run_all(registry, Ctx(corpus=corpus, adapter=self.adapter))

        codes = {f.evidence["code"] for f in findings}
        self.assertIn("UnknownField", codes)

    def test_a_valid_exemplar_produces_no_findings(self) -> None:
        write(self.root, "_exemplars/gem.json", "gem", [{
            "id": "gem.exemplar-001", "nameKey": "g.ex1", "name": "Exemplar Gem",
            "family": "atom.vitality", "powerBand": "low",
        }])
        corpus = Corpus.load(self.root)
        registry = MetricRegistry()
        registry.register(ExemplarConformance())
        self.assertEqual(run_all(registry, Ctx(corpus=corpus, adapter=self.adapter)), [])

    def test_real_shipped_exemplars_all_currently_conform(self) -> None:
        live_root = seed_root() / "items"
        if not live_root.is_dir():
            self.skipTest("live item corpus not present in this checkout")
        corpus = Corpus.load(live_root)
        registry = MetricRegistry()
        registry.register(ExemplarConformance())
        findings = run_all(registry, Ctx(corpus=corpus, adapter=self.adapter))
        self.assertEqual(findings, [], f"live exemplars should already conform: {findings}")


class SemanticDedupTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp())

    def test_exact_duplicate_name_across_kinds_is_caught(self) -> None:
        # The historical incident: gem.g1-015 and consumable.k1-007 both named "Mending Pulse" —
        # already fixed in the live corpus, replayed here as the fixture it should have been.
        write(self.root, "gems/a.json", "gem",
             [{"id": "gem.g1-015", "nameKey": "g.1", "name": "Mending Pulse"}])
        write(self.root, "consumables/a.json", "consumable",
             [{"id": "consumable.k1-007", "nameKey": "c.1", "name": "Mending Pulse"}])
        corpus = Corpus.load(self.root)
        registry = MetricRegistry()
        registry.register(SemanticDedup())
        findings = run_all(registry, Ctx(corpus=corpus, adapter=None))

        exact = [f for f in findings if f.evidence["code"] == "ExactDuplicateName"]
        self.assertEqual(len(exact), 1)
        self.assertEqual(exact[0].severity, Severity.GAP)
        self.assertEqual(set(exact[0].evidence["entryIds"]), {"gem.g1-015", "consumable.k1-007"})

    def test_distinct_names_produce_no_exact_duplicate_finding(self) -> None:
        write(self.root, "gems/a.json", "gem", [
            {"id": "gem.g1-001", "nameKey": "g.1", "name": "Ember Shard"},
            {"id": "gem.g1-002", "nameKey": "g.2", "name": "Frost Shard"},
        ])
        corpus = Corpus.load(self.root)
        registry = MetricRegistry()
        registry.register(SemanticDedup())
        findings = run_all(registry, Ctx(corpus=corpus, adapter=None))
        self.assertEqual([f for f in findings if f.evidence["code"] == "ExactDuplicateName"], [])

    def test_display_templates_are_not_player_facing_names(self) -> None:
        write(self.root, "display-templates/a.json", "display-template", [
            {"id": "disptpl.a-001", "name": "{value} bonus damage on hit"},
            {"id": "disptpl.a-002", "name": "{value} bonus damage on hit"},
        ])
        corpus = Corpus.load(self.root)
        registry = MetricRegistry()
        registry.register(SemanticDedup())
        findings = run_all(registry, Ctx(corpus=corpus, adapter=None))
        self.assertEqual([f for f in findings if f.evidence["code"] == "ExactDuplicateName"], [])

    def test_canonical_duplicate_ignores_word_order(self) -> None:
        write(self.root, "gems/a.json", "gem", [
            {"id": "gem.g1-001", "nameKey": "g.1", "name": "Ashen Fang"},
            {"id": "gem.g1-002", "nameKey": "g.2", "name": "Fang, Ashen"},
        ])
        corpus = Corpus.load(self.root)
        registry = MetricRegistry()
        registry.register(SemanticDedup())
        findings = run_all(registry, Ctx(corpus=corpus, adapter=None))
        canonical = [f for f in findings if f.evidence["code"] == "CanonicalDuplicate"]
        self.assertEqual(len(canonical), 1)

    def test_minhash_jaccard_is_deterministic_across_calls(self) -> None:
        sig_a = minhash_signature(shingles("Ashen Fang"))
        sig_b = minhash_signature(shingles("Ashen Fang"))
        self.assertEqual(sig_a, sig_b)  # would fail if the hash were process-randomized

    def test_near_identical_names_score_high_jaccard_unrelated_names_score_low(self) -> None:
        # spec-analytics.md §6.2's own worked example: "finds 'Sapvein' vs 'Sapveil'".
        close = jaccard_estimate(minhash_signature(shingles("Sapvein")),
                                 minhash_signature(shingles("Sapveil")))
        far = jaccard_estimate(minhash_signature(shingles("Sapvein")),
                               minhash_signature(shingles("Quantum Tax Filing")))
        self.assertGreater(close, far)
        self.assertGreaterEqual(close, 0.5)


class ProseDedupTests(unittest.TestCase):
    """`KindSpec.dedup_fields` — added 2026-09-06 to close the gap `SemanticDedup` had for any
    kind's own free-text field (only `name` was ever checked). `commander-effect`'s `doctrine` is
    the first real consumer.
    """

    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp())
        self.spec_with_doctrine = KindSpec(
            kind="commander-effect", directory="commander-effect", namespace="commanderEffect",
            required=frozenset({"id", "nameKey", "name", "creatureId"}),
            dedup_fields=frozenset({"doctrine"}),
        )

    def test_a_kind_with_no_declared_dedup_fields_is_untouched(self) -> None:
        # Every kind before this change (and every kind that never opts in) must produce zero
        # prose findings — additive means nothing regresses for an adapter that says nothing.
        write(self.root, "gems/a.json", "gem", [
            {"id": "gem.g1-001", "nameKey": "g.1", "name": "Ember Shard",
             "flavor": "A shard of pure ember, still warm to the touch."},
            {"id": "gem.g1-002", "nameKey": "g.2", "name": "Frost Shard",
             "flavor": "A shard of pure ember, still warm to the touch."},  # identical, but unwatched
        ])
        corpus = Corpus.load(self.root)
        registry = MetricRegistry()
        registry.register(SemanticDedup())
        adapter = _StubAdapterWithDedupFields([
            KindSpec(kind="gem", directory="gems", namespace="gem"),  # no dedup_fields
        ])
        findings = run_all(registry, Ctx(corpus=corpus, adapter=adapter))
        self.assertEqual([f for f in findings if "Prose" in f.evidence["code"]], [])

    def test_no_adapter_means_no_prose_check_but_name_check_still_runs(self) -> None:
        # SemanticDedup is called with adapter=None elsewhere in this suite (name-only checks
        # never needed KindSpec) — that must keep working exactly as before.
        write(self.root, "gems/a.json", "gem",
             [{"id": "gem.g1-015", "nameKey": "g.1", "name": "Mending Pulse"}])
        write(self.root, "consumables/a.json", "consumable",
             [{"id": "consumable.k1-007", "nameKey": "c.1", "name": "Mending Pulse"}])
        corpus = Corpus.load(self.root)
        registry = MetricRegistry()
        registry.register(SemanticDedup())
        findings = run_all(registry, Ctx(corpus=corpus, adapter=None))
        self.assertEqual(len([f for f in findings if f.evidence["code"] == "ExactDuplicateName"]), 1)

    def test_exact_duplicate_prose_text_across_two_entries_is_caught(self) -> None:
        write(self.root, "commander-effect/a.json", "commander-effect", [
            {"id": "commander-effect.a", "nameKey": "ce.a", "name": "A", "creatureId": "a",
             "doctrine": "The squad focuses fire on the nearest target."},
            {"id": "commander-effect.b", "nameKey": "ce.b", "name": "B", "creatureId": "b",
             "doctrine": "The squad focuses fire on the nearest target."},
        ])
        corpus = Corpus.load(self.root)
        registry = MetricRegistry()
        registry.register(SemanticDedup())
        adapter = _StubAdapterWithDedupFields([self.spec_with_doctrine])
        findings = run_all(registry, Ctx(corpus=corpus, adapter=adapter))

        exact = [f for f in findings if f.evidence["code"] == "ExactProseDuplicate"]
        self.assertEqual(len(exact), 1)
        self.assertEqual(exact[0].severity, Severity.GAP)
        self.assertEqual(set(exact[0].evidence["entryIds"]),
                         {"commander-effect.a", "commander-effect.b"})
        # An exact duplicate must not ALSO be double-reported as a near-duplicate.
        self.assertEqual([f for f in findings if f.evidence["code"] == "ProseNearDuplicate"], [])

    def test_the_real_corpus_near_duplicate_pair_is_caught(self) -> None:
        # Replays the real finding from the live corpus, verified 2026-09-06: two commander
        # effects describing the same split-shot mechanic in near-identical sentences.
        write(self.root, "commander-effect/a.json", "commander-effect", [
            {"id": "commander-effect.doublecherry", "nameKey": "ce.a", "name": "A",
             "creatureId": "doublecherry",
             "doctrine": "每次发射时，子弹会分裂为两枚，呈扇形向目标区域覆盖。"},
            {"id": "commander-effect.doubleshooter", "nameKey": "ce.b", "name": "B",
             "creatureId": "doubleshooter",
             "doctrine": "每次发射时，子弹会分裂为两枚，呈扇形向前方区域扩散。"},
        ])
        corpus = Corpus.load(self.root)
        registry = MetricRegistry()
        registry.register(SemanticDedup())
        adapter = _StubAdapterWithDedupFields([self.spec_with_doctrine])
        findings = run_all(registry, Ctx(corpus=corpus, adapter=adapter))

        near = [f for f in findings if f.evidence["code"] == "ProseNearDuplicate"]
        self.assertEqual(len(near), 1)
        self.assertGreaterEqual(near[0].evidence["jaccard"], 0.5)
        self.assertEqual(set(near[0].evidence["entryIds"]),
                         {"commander-effect.doublecherry", "commander-effect.doubleshooter"})

    def test_doctrines_sharing_only_a_verb_are_not_flagged(self) -> None:
        # The real corpus's weaker candidates (Jaccard 0.41, 0.34) share one verb and are
        # legitimate distinct doctrines — the threshold must not flag them.
        write(self.root, "commander-effect/a.json", "commander-effect", [
            {"id": "commander-effect.jalagatling", "nameKey": "ce.a", "name": "A",
             "creatureId": "jalagatling",
             "doctrine": "通过持续的发射动作，在目标行径路径上留下带有地刺触感的弹道轨迹。"},
            {"id": "commander-effect.jalapeashooter", "nameKey": "ce.b", "name": "B",
             "creatureId": "jalapeashooter",
             "doctrine": "通过连续的发射动作引发地刺般的灼热冲击，对目标造成持续的触感灼伤。"},
        ])
        corpus = Corpus.load(self.root)
        registry = MetricRegistry()
        registry.register(SemanticDedup())
        adapter = _StubAdapterWithDedupFields([self.spec_with_doctrine])
        findings = run_all(registry, Ctx(corpus=corpus, adapter=adapter))
        self.assertEqual([f for f in findings if f.evidence["code"] == "ProseNearDuplicate"], [])

    def test_real_commander_effect_corpus_reports_exactly_the_known_pair(self) -> None:
        live_root = seed_root() / "creatures"
        if not live_root.is_dir():
            self.skipTest("live creatures corpus not present in this checkout")
        corpus = Corpus.load(live_root)
        registry = MetricRegistry()
        registry.register(SemanticDedup())
        findings = run_all(registry, Ctx(corpus=corpus, adapter=CreaturesAdapter()))
        near = [f for f in findings if f.evidence["code"] == "ProseNearDuplicate"]
        self.assertEqual(
            [tuple(sorted(f.evidence["entryIds"])) for f in near],
            [("commander-effect.doublecherry", "commander-effect.doubleshooter")],
            f"live corpus's known-answer prose near-duplicate set changed: {near}")


if __name__ == "__main__":
    unittest.main()
