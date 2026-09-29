"""`gloss-registry` (NS8, spec-gloss-registry.md) — the registry contract and the refusing lookup.

    python -m pytest gk-forge/tools/seedsmith/tests/test_briefkit_gloss.py -q -s

Fixture tables only: invented motifs and glosses, so a real registry row can never turn a test red
(validation-ssot.md). The one test that reads the committed file asserts the header contract and PRINTS
its row count — a population is a reading, never a constant.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from seedsmith.briefkit.gloss import (  # noqa: E402
    DEFAULT_LOCALE,
    GLOSS_ALLOWED_CHARS,
    SENSE,
    Sense,
    GlossMissing,
    GlossTable,
    coverage_report,
    load_glosses,
)
from seedsmith.briefkit.render import BriefRefusal  # noqa: E402

#: Invented motifs — never a real registry row.
MOTIF_A = "\u9F99\u7FFC"   # 龙翼
MOTIF_B = "\u6697\u6F6E"   # 暗潮


def _row(gloss: str = "dragon wing", sense: str = "concrete", model: str = "test-model",
         prompt_version: str = "gloss/1") -> dict:
    return {"gloss": gloss, "sense": sense, "model": model, "promptVersion": prompt_version}


def _fixture(tmp_path: Path, *, glosses: "dict | None" = None, locale: str = "en",
             max_words: int = 4, name: str = "motif-glosses.en.v1.json",
             **overrides) -> "tuple[Path, Path]":
    doc = {
        "schemaVersion": 1,
        "registryVersion": 1,
        "locale": locale,
        "source": {"registry": "data/seed/creatures/_registry/motifs.v1.json", "registryVersion": 1},
        "glosses": glosses if glosses is not None else {},
    }
    doc.update(overrides)
    registry = tmp_path / name
    registry.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    budget = tmp_path / "budget.v1.json"
    budget.write_text(json.dumps({"schemaVersion": 1, "version": 1, "gloss": {"maxWords": max_words}}),
                      encoding="utf-8")
    return registry, budget


def _load(tmp_path: Path, **kwargs) -> GlossTable:
    registry, budget = _fixture(tmp_path, **kwargs)
    return load_glosses(DEFAULT_LOCALE, registry, budget_path=budget)


def test_lookup_returns_gloss_never_motif(tmp_path):
    table = _load(tmp_path, glosses={MOTIF_A: _row("dragon wing")})
    assert table.gloss(MOTIF_A) == "dragon wing"
    assert table.gloss(MOTIF_A) != MOTIF_A
    assert table.gloss_all([MOTIF_A]) == ("dragon wing",)


def test_missing_motif_raises_with_every_missing_motif(tmp_path):
    table = _load(tmp_path, glosses={})
    with pytest.raises(GlossMissing) as ctx:
        table.gloss_all([MOTIF_A, MOTIF_B])
    assert ctx.value.motifs == tuple(sorted([MOTIF_A, MOTIF_B]))
    assert set(ctx.value.motifs) == {MOTIF_A, MOTIF_B}
    assert MOTIF_A in str(ctx.value) and MOTIF_B in str(ctx.value)
    # A partially glossed request names ONLY the missing one, and returns nothing.
    partial = _load(tmp_path, glosses={MOTIF_A: _row("dragon wing")})
    with pytest.raises(GlossMissing) as ctx2:
        partial.gloss_all([MOTIF_A, MOTIF_B])
    assert ctx2.value.motifs == (MOTIF_B,)


def test_single_lookup_raises_for_the_one_motif(tmp_path):
    table = _load(tmp_path, glosses={})
    with pytest.raises(GlossMissing) as ctx:
        table.gloss(MOTIF_A)
    assert ctx.value.motifs == (MOTIF_A,)


def test_gloss_missing_is_a_brief_refusal():
    assert issubclass(GlossMissing, BriefRefusal)


def test_loader_refuses_unknown_key(tmp_path):
    with pytest.raises(BriefRefusal, match="unknown key"):
        _load(tmp_path, notAKey=1)
    with pytest.raises(BriefRefusal, match="unknown key"):
        _load(tmp_path, glosses={MOTIF_A: {**_row(), "extra": "x"}})


def test_loader_refuses_missing_key(tmp_path):
    registry, budget = _fixture(tmp_path, glosses={MOTIF_A: _row()})
    doc = json.loads(registry.read_text(encoding="utf-8"))
    del doc["locale"]
    registry.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(BriefRefusal, match="missing required key"):
        load_glosses(DEFAULT_LOCALE, registry, budget_path=budget)

    with pytest.raises(BriefRefusal, match="missing required key"):
        _load(tmp_path, glosses={MOTIF_A: {"gloss": "dragon wing", "sense": "concrete",
                                           "model": "m"}})


def test_loader_refuses_locale_mismatch(tmp_path):
    with pytest.raises(BriefRefusal, match="does not match the requested locale"):
        _load(tmp_path, locale="fr")


def test_loader_refuses_the_file_names_own_locale_code(tmp_path):
    registry = tmp_path / "motif-glosses.fr.v1.json"
    registry.write_text(json.dumps({
        "schemaVersion": 1, "registryVersion": 1, "locale": "en",
        "source": {"registry": "x", "registryVersion": 1}, "glosses": {},
    }), encoding="utf-8")
    budget = tmp_path / "budget.v1.json"
    budget.write_text(json.dumps({"gloss": {"maxWords": 4}}), encoding="utf-8")
    with pytest.raises(BriefRefusal, match="file name says locale"):
        load_glosses(DEFAULT_LOCALE, registry, budget_path=budget)


def test_loader_refuses_empty_gloss(tmp_path):
    with pytest.raises(BriefRefusal, match="is empty"):
        _load(tmp_path, glosses={MOTIF_A: _row("")})
    with pytest.raises(BriefRefusal, match="is empty"):
        _load(tmp_path, glosses={MOTIF_A: _row("   ")})


def test_loader_refuses_a_digit_in_a_gloss(tmp_path):
    with pytest.raises(BriefRefusal, match="contains a digit"):
        _load(tmp_path, glosses={MOTIF_A: _row("dragon wing 2")})


def test_loader_refuses_foreign_script_in_a_gloss(tmp_path):
    with pytest.raises(BriefRefusal, match="outside the allowed gloss characters"):
        _load(tmp_path, glosses={MOTIF_A: _row("dragon \u7FFC")})
    with pytest.raises(BriefRefusal, match="outside the allowed gloss characters"):
        _load(tmp_path, glosses={MOTIF_A: _row("dragon\uFF0Cwing")})


def test_loader_refuses_gloss_over_max_words_and_the_bound_comes_from_the_budget(tmp_path):
    three = "one two three"
    with pytest.raises(BriefRefusal, match="over gloss.maxWords=2"):
        _load(tmp_path, glosses={MOTIF_A: _row(three)}, max_words=2)
    # The SAME gloss passes when the budget file allows it — the bound is the file's, not a constant.
    table = _load(tmp_path, glosses={MOTIF_A: _row(three)}, max_words=4)
    assert table.gloss(MOTIF_A) == three
    assert set(" -'") <= GLOSS_ALLOWED_CHARS, "space, hyphen and apostrophe are legal gloss characters"


def test_loader_refuses_a_gloss_equal_to_its_motif(tmp_path):
    with pytest.raises(BriefRefusal, match="is the motif itself"):
        _load(tmp_path, glosses={"dragonwing": _row("dragonwing")})


def test_loader_refuses_row_without_model_or_prompt_version(tmp_path):
    for key in ("model", "promptVersion"):
        row = _row()
        row[key] = ""
        with pytest.raises(BriefRefusal, match=key):
            _load(tmp_path, glosses={MOTIF_A: row})


def test_loader_refuses_unknown_sense(tmp_path):
    with pytest.raises(BriefRefusal, match="outside the closed enum"):
        _load(tmp_path, glosses={MOTIF_A: _row(sense="noun")})


def test_sense_is_closed():
    assert SENSE == ("concrete", "abstract", "action", "quality", "none")
    assert [s.value for s in Sense] == list(SENSE)


def test_coverage_report_lists_orphans_and_missing(tmp_path):
    table = _load(tmp_path, glosses={MOTIF_A: _row(), "retired": _row("old gloss")})
    report = coverage_report(table, source_motifs=[MOTIF_A, MOTIF_B])
    assert report["rows"] == 2
    assert report["orphans"] == ["retired"]
    assert report["unglossed"] == [MOTIF_B]
    assert report["sourceVersionTrails"] is False


def test_committed_file_loads():
    """The real file's header contract, plus its row count as a PRINTED reading (never asserted)."""
    table = load_glosses()
    assert table.locale == DEFAULT_LOCALE
    assert table.source_registry.endswith("motifs.v1.json")
    assert isinstance(table.rows, dict)
    report = coverage_report(table)
    print(f"\nmotif-glosses.en.v1.json rows={report['rows']} "
          f"unglossed={len(report['unglossed'])} orphans={len(report['orphans'])} "
          f"sourceRegistryVersion={report['sourceRegistryVersion']} "
          f"liveSourceRegistryVersion={report['liveSourceRegistryVersion']}")
