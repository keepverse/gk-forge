"""Tests for seedsmith.adapters.dungeon.completeness (`seedsmith-content-standard` Task 12) —
proves the two real gaps `completeness.py`'s own module docstring names are actually closed against
the REAL committed corpus, not a synthetic fixture:

1. `load_dungeon_corpus` can see dungeon's real one-object-per-file content at all (`Corpus.load()`
   cannot — it requires a top-level `kind`/`entries` wrapper no dungeon file has).
2. `ensure_completeness_registered` + `Content/FieldMissing`/`Content/LanguageContamination`
   (`metrics/content_completeness.py`) produce real findings against that real corpus, including a
   permanent regression proof that the ALREADY-FIXED live defect
   (`gk-data/packs/fusion/data/seed/dungeon/events/event.bargain-creature.allpeater-001.json`) stays clean.

    python -m pytest gk-forge/tools/seedsmith/tests/test_dungeon_completeness.py -v
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from seedsmith.adapters.dungeon.completeness import (  # noqa: E402
    DUNGEON_EVENT_KIND,
    ensure_completeness_registered,
    load_dungeon_corpus,
)
from seedsmith.metrics import Ctx, MetricRegistry, run_all  # noqa: E402
from seedsmith.metrics.content_completeness import (  # noqa: E402
    ContentFieldMissing,
    ContentLanguageContamination,
    clear_registry,
    registered_specs,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
LIVE_DUNGEON_ROOT = REPO_ROOT / "data" / "seed" / "dungeon"
REAL_DEFECT_ENTRY_ID = "event.bargain-creature.allpeater-001"


@unittest.skipUnless(LIVE_DUNGEON_ROOT.is_dir(), "live dungeon corpus not present in this checkout")
class LoadDungeonCorpusTests(unittest.TestCase):
    """Gap 1: `corpus.model.Corpus.load()` silently sees zero dungeon entries — confirmed once
    here as the negative case this module exists to fix, then the positive case via the real
    loader."""

    def test_generic_corpus_load_sees_nothing_real_under_dungeon_events(self) -> None:
        from seedsmith.corpus import Corpus as GenericCorpus

        generic = GenericCorpus.load(LIVE_DUNGEON_ROOT / "events")
        self.assertEqual(generic.by_kind(DUNGEON_EVENT_KIND), [])
        self.assertEqual(len(generic.entries), 0)

    def test_load_dungeon_corpus_reads_the_real_committed_events(self) -> None:
        corpus = load_dungeon_corpus(LIVE_DUNGEON_ROOT)
        events = corpus.by_kind(DUNGEON_EVENT_KIND)
        self.assertGreater(len(events), 0)
        ids = {e.id for e in events}
        self.assertIn(REAL_DEFECT_ENTRY_ID, ids)

    def test_index_json_is_not_loaded_as_an_entry(self) -> None:
        corpus = load_dungeon_corpus(LIVE_DUNGEON_ROOT)
        self.assertIsNone(corpus.by_id("_index"))


class EnsureCompletenessRegisteredTests(unittest.TestCase):
    def setUp(self) -> None:
        clear_registry()

    def tearDown(self) -> None:
        clear_registry()

    def test_registers_exactly_one_dungeon_spec(self) -> None:
        ensure_completeness_registered()
        dungeon_specs = [s for s in registered_specs() if s.domain == "dungeon"]
        self.assertEqual(len(dungeon_specs), 1)
        self.assertEqual(dungeon_specs[0].kinds, frozenset({DUNGEON_EVENT_KIND}))
        self.assertEqual(dungeon_specs[0].field, "flavor")

    def test_calling_twice_does_not_duplicate(self) -> None:
        ensure_completeness_registered()
        ensure_completeness_registered()
        dungeon_specs = [s for s in registered_specs() if s.domain == "dungeon"]
        self.assertEqual(len(dungeon_specs), 1)


@unittest.skipUnless(LIVE_DUNGEON_ROOT.is_dir(), "live dungeon corpus not present in this checkout")
class RealCorpusFindingsTests(unittest.TestCase):
    """Gap 2, proven end to end against the real corpus: registering + running produces real
    findings (or a real clean pass), not a mechanism that only works on synthetic data."""

    def setUp(self) -> None:
        clear_registry()
        ensure_completeness_registered()
        self.corpus = load_dungeon_corpus(LIVE_DUNGEON_ROOT)

    def tearDown(self) -> None:
        clear_registry()

    def test_content_field_missing_runs_clean_against_the_real_event_corpus(self) -> None:
        # Every real committed event carries a non-empty `flavor` (kinds.py's own EVENT.required
        # names it as required) — this is a real, current-state assertion, not an assumption: a
        # future generation pass that leaves one blank should make this test fail, which is
        # correct (that is exactly the gap this metric exists to report).
        registry = MetricRegistry()
        registry.register(ContentFieldMissing())
        ctx = Ctx(corpus=self.corpus, adapter=None)
        findings = run_all(registry, ctx)
        self.assertEqual(findings, [], [f.message for f in findings])

    def test_the_real_previously_defective_event_is_now_clean(self) -> None:
        """Regression proof for the fix: `event.bargain-creature.allpeater-001.json`'s own `flavor`
        field carried untranslated Chinese fragments ("offensive火力", "permanent 分配") mid-English
        sentence, found live 2026-09-08. After the fix, `Content/LanguageContamination` must report
        zero findings for this specific real entry — not a synthetic stand-in."""
        registry = MetricRegistry()
        registry.register(ContentLanguageContamination())
        ctx = Ctx(corpus=self.corpus, adapter=None)
        findings = run_all(registry, ctx)
        offending = [f for f in findings if REAL_DEFECT_ENTRY_ID in f.subject]
        self.assertEqual(offending, [], [f.message for f in offending])

    def test_the_real_defect_entrys_flavor_field_is_pure_ascii_english(self) -> None:
        entry = self.corpus.by_id(REAL_DEFECT_ENTRY_ID)
        self.assertIsNotNone(entry)
        flavor = entry.get("flavor")
        self.assertIsInstance(flavor, str)
        self.assertTrue(flavor.strip())
        non_ascii = [ch for ch in flavor if ord(ch) > 127]
        self.assertEqual(non_ascii, [], f"non-ASCII characters remain in flavor: {non_ascii!r}")


if __name__ == "__main__":
    unittest.main()
