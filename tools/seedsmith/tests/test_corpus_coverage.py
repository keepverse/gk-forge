"""Tests for seedsmith.metrics.corpus_coverage (spec-corpus-dump.md/spec-power-parse.md,
creature-seed `seed-to-concrete` T1.10)."""
from __future__ import annotations

import json
from pathlib import Path

from seedsmith.adapters.creatures.dump_ctx import load_creature_dump_ctx
from seedsmith.corpus import Corpus
from seedsmith.metrics.corpus_coverage import BasisHistogramMetric, DumpCompletenessMetric
from seedsmith.metrics.model import Ctx, Loop, Severity


def write_dump(tmp_path: Path, *, plant: list, zombie: list, manifest_overrides: "dict | None" = None) -> Path:
    dump_dir = tmp_path / "_dump"
    (dump_dir / "almanac").mkdir(parents=True)
    (dump_dir / "almanac" / "plant.json").write_text(json.dumps(plant), encoding="utf-8")
    (dump_dir / "almanac" / "zombie.json").write_text(json.dumps(zombie), encoding="utf-8")
    (dump_dir / "spawn-baseline.json").write_text("[]", encoding="utf-8")
    (dump_dir / "recipes.json").write_text("[]", encoding="utf-8")
    manifest = {"plantCount": len(plant), "zombieCount": len(zombie),
                "baselineCount": 0, "recipeCount": 0}
    manifest.update(manifest_overrides or {})
    (dump_dir / "_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return dump_dir


def row(side: str, type_id: int, *, hp=None, attack=None, flavor=None, observed=False) -> dict:
    return {"side": side, "typeId": type_id, "typeName": None, "displayName": None,
            "flavorInfo": flavor, "flavorIntroduce": None, "sunCost": None, "cooldownSec": None,
            "costStatus": "absent", "hp": hp, "attack": attack, "armor": None, "armorMax": None,
            "statsObserved": observed, "contractVersion": 1, "rebuiltUtc": "2026-01-01T00:00:00Z",
            "enrichment": None}


def ctx_with_dump(dump_dir: Path) -> Ctx:
    creature_dump = load_creature_dump_ctx(dump_dir)
    assert creature_dump is not None
    return Ctx(corpus=Corpus(), adapter=None, creature_dump=creature_dump)


# --- DumpCompletenessMetric ------------------------------------------------------------------


def test_dump_completeness_metric_is_closed_and_named_correctly():
    m = DumpCompletenessMetric()
    assert m.id == "CorpusCoverage/DumpCompleteness"
    assert m.loop is Loop.CLOSED
    assert m.needs == frozenset({"creature_dump"})


def test_matching_counts_produce_no_findings(tmp_path: Path):
    dump_dir = write_dump(tmp_path, plant=[row("plant", 0)], zombie=[row("zombie", 0)])
    findings = DumpCompletenessMetric().run(ctx_with_dump(dump_dir))
    assert findings == []


def test_mismatched_plant_count_is_a_gap(tmp_path: Path):
    dump_dir = write_dump(tmp_path, plant=[row("plant", 0)], zombie=[],
                          manifest_overrides={"plantCount": 5})
    findings = DumpCompletenessMetric().run(ctx_with_dump(dump_dir))
    assert len(findings) == 1
    assert findings[0].severity is Severity.GAP
    assert findings[0].subject == "plantCount"
    assert findings[0].evidence["declared"] == 5
    assert findings[0].evidence["actual"] == 1


# --- BasisHistogramMetric ---------------------------------------------------------------------


def test_basis_histogram_metric_is_open_never_gates():
    m = BasisHistogramMetric()
    assert m.loop is Loop.OPEN
    assert m.gates is False


def test_empty_dump_is_not_measured(tmp_path: Path):
    dump_dir = write_dump(tmp_path, plant=[], zombie=[])
    findings = BasisHistogramMetric().run(ctx_with_dump(dump_dir))
    assert len(findings) == 1
    assert findings[0].severity is Severity.NOT_MEASURED


def test_healthy_basis_share_produces_no_findings(tmp_path: Path):
    # 8/10 observed, well above the 700‰ target; 0/10 blocked, well under 30‰.
    rows = [row("plant", i, hp=100, attack=10, observed=True) for i in range(8)]
    rows += [row("plant", 100 + i, flavor=f"伤害：{i}") for i in range(2)]  # stated
    dump_dir = write_dump(tmp_path, plant=rows, zombie=[])
    findings = BasisHistogramMetric().run(ctx_with_dump(dump_dir))
    assert findings == []


def test_low_observed_or_stated_share_is_a_gap(tmp_path: Path):
    # All 10 species are blocked (no text, not observed) — 0‰ observed+stated, way under target,
    # and 1000‰ blocked, way over target -> two findings.
    rows = [row("plant", i) for i in range(10)]
    dump_dir = write_dump(tmp_path, plant=rows, zombie=[])
    findings = BasisHistogramMetric().run(ctx_with_dump(dump_dir))
    subjects = {f.subject for f in findings}
    assert "observed+stated share" in subjects
    assert "blocked share" in subjects
    assert all(f.severity is Severity.GAP for f in findings)


def test_real_committed_dump_meets_both_targets():
    # No fixture — the real, live gk-data/packs/fusion/data/seed/creatures/_dump this program committed (T1.1/T1.2).
    from seedsmith.adapters.creatures.preflight import DEFAULT_DUMP_DIR
    creature_dump = load_creature_dump_ctx(DEFAULT_DUMP_DIR)
    assert creature_dump is not None
    ctx = Ctx(corpus=Corpus(), adapter=None, creature_dump=creature_dump)
    assert DumpCompletenessMetric().run(ctx) == []
    assert BasisHistogramMetric().run(ctx) == []
