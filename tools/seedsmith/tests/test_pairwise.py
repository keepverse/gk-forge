"""Tests for seedsmith.metrics.pairwise (tasks/seedsmith-todo.md, S4).

    python -m pytest gk-forge/tools/seedsmith/tests/test_pairwise.py -v
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from seedsmith.adapters._stub import StubAdapter  # noqa: E402
from seedsmith.corpus import Corpus  # noqa: E402
from seedsmith.metrics import Ctx, MetricRegistry, run_all  # noqa: E402
from seedsmith.metrics.pairwise import PairwiseHole  # noqa: E402


def write(root: Path, kind: str, entries: list[dict], partition: str = "p") -> None:
    directory = root / (kind + "s")
    directory.mkdir(parents=True, exist_ok=True)
    doc = {"kind": kind, "_meta": {"partition": partition}, "entries": entries}
    (directory / "a.json").write_text(json.dumps(doc), encoding="utf-8")


class StubPairwiseTests(unittest.TestCase):
    """The stub declares color={red,blue} × size={small,large} on {widget}×{gadget}
    respectively — no common kind, so that pair is never checked. The illegal-pair test needs a
    dimension pair that DOES share a kind; we widen the stub's own vocabulary in these fixtures
    by putting both `color` and `size` fields directly onto widget entries, which the stub's
    dimensions don't apply_to widget for `size` — so instead we exercise the exact real seam:
    color is single-kind (widget only) by construction, proving a pair with no common kind is
    silently skipped, and the legal/illegal split is proven directly against the adapter's own
    `legal_combinations()` in test_stub_adapter.py. This suite proves the METRIC's behavior given
    a manufactured two-dimension-same-kind case.
    """

    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp())

    def test_no_common_kind_between_dimensions_is_silently_skipped(self) -> None:
        # color applies_to={widget}, size applies_to={gadget} in the real stub — no overlap.
        write(self.root, "widget", [{"id": "widget.a-001", "color": "red"}])
        write(self.root, "gadget", [{"id": "gadget.a-001", "size": "small"}])
        corpus = Corpus.load(self.root)
        registry = MetricRegistry()
        registry.register(PairwiseHole())
        findings = run_all(registry, Ctx(corpus=corpus, adapter=StubAdapter()))
        self.assertEqual(findings, [])


class _TwoFieldKindAdapter(StubAdapter):
    """A minimal adapter variant putting BOTH `color` and `size` on the same kind (`widget`), so
    a same-row dimension pair actually exists to test pairwise coverage against — the real stub
    deliberately keeps its two dimensions on separate kinds, which is right for THAT adapter's
    own purpose (proving cross-kind pairs are skipped) but wrong for exercising the "legal but
    missing" vs "illegal, never a finding" distinction pairwise coverage needs.
    """

    def dimensions(self):
        from seedsmith.adapters.base import Dimension
        return [
            Dimension(id="color", values=("red", "blue"), field="color",
                     applies_to=frozenset({"widget"})),
            Dimension(id="size", values=("small", "large"), field="size",
                     applies_to=frozenset({"widget"})),
        ]


class LegalityExclusionTests(unittest.TestCase):
    """The false-positive-flood test: a fixture with one legal-but-missing pair AND one illegal
    pair. Only the legal one may ever surface as a finding — an illegal pair counted as a hole is
    the single most likely way this metric becomes noise everybody ignores."""

    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp())
        self.adapter = _TwoFieldKindAdapter()

    def test_legal_missing_pair_is_a_finding_illegal_pair_is_not(self) -> None:
        # legal_combinations forbids (color=red, size=large). Content covers every OTHER pair
        # except the legal (color=blue, size=large) — that one must be the only finding.
        write(self.root, "widget", [
            {"id": "widget.a-001", "color": "red", "size": "small"},
            {"id": "widget.a-002", "color": "blue", "size": "small"},
            # (red, large) is illegal — never content, never a finding either way
        ])
        corpus = Corpus.load(self.root)
        registry = MetricRegistry()
        registry.register(PairwiseHole())
        findings = run_all(registry, Ctx(corpus=corpus, adapter=self.adapter))

        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].subject, "color×size")
        self.assertIn(("blue", "large"), findings[0].evidence["missingSample"])
        self.assertNotIn(("red", "large"), findings[0].evidence["missingSample"])

    def test_zero_findings_when_every_legal_pair_is_covered(self) -> None:
        write(self.root, "widget", [
            {"id": "widget.a-001", "color": "red", "size": "small"},
            {"id": "widget.a-002", "color": "blue", "size": "small"},
            {"id": "widget.a-003", "color": "blue", "size": "large"},
            # (red, large) is illegal — its absence must not produce a finding
        ])
        corpus = Corpus.load(self.root)
        registry = MetricRegistry()
        registry.register(PairwiseHole())
        findings = run_all(registry, Ctx(corpus=corpus, adapter=self.adapter))
        self.assertEqual(findings, [])

    def test_reports_seen_and_required_counts(self) -> None:
        write(self.root, "widget", [{"id": "widget.a-001", "color": "red", "size": "small"}])
        corpus = Corpus.load(self.root)
        registry = MetricRegistry()
        registry.register(PairwiseHole())
        findings = run_all(registry, Ctx(corpus=corpus, adapter=self.adapter))

        self.assertEqual(len(findings), 1)
        # 4 possible pairs minus 1 illegal (red,large) = 3 legal required; 1 seen, 2 missing
        self.assertEqual(findings[0].evidence["required"], 3)
        self.assertEqual(findings[0].evidence["seen"], 1)


if __name__ == "__main__":
    unittest.main()
