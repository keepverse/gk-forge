import json
from pathlib import Path

import pytest

from seedsmith.adapters.creatures import theme_enrich
from seedsmith.pipeline.model import audit_schema


def _registry(path: Path, *, basis: str = "name") -> None:
    path.write_text(json.dumps({"schemaVersion": 1, "registryVersion": 1, "themes": {
        "creature.alpha": {
            "speciesId": "alpha", "displayName": "Alpha", "rarity": "common",
            "motifs": ["thorn"], "antiMotifs": ["ice"],
            "expression": {"item": "material", "action": "tempo"},
            "basis": basis, "retired": False,
        },
    },}, ensure_ascii=False), encoding="utf-8")


def test_schema_has_blocked_variant_and_no_numeric_fields():
    assert audit_schema(theme_enrich.THEME_ENRICH_SCHEMA) == []


def test_synthetic_unnamed_capture_slots_cannot_be_enriched():
    assert not theme_enrich.source_can_support_enrichment(
        {"speciesId": "enumvalue261", "displayName": "未命名"})
    assert not theme_enrich.source_can_support_enrichment(
        {"speciesId": "extract_single", "displayName": "未命名"})
    assert theme_enrich.source_can_support_enrichment(
        {"speciesId": "enumvalue261", "displayName": "未命名"},
        {"traitPool": ["nameless", "void-state"], "elementPrimary": "Earth"})
    assert theme_enrich.source_can_support_enrichment(
        {"speciesId": "magnetbox", "displayName": "未命名"})


def test_dry_run_does_not_call_model_or_write_ledger(tmp_path):
    registry = tmp_path / "themes.json"
    _registry(registry)
    result = theme_enrich.enrich(registry_path=registry, ledger_path=tmp_path / "ledger.json", write=False)
    assert result["planned"] == 1
    assert result["remaining"] == 1
    assert not (tmp_path / "ledger.json").exists()


def test_acceptance_marks_enriched_and_resume_is_idempotent(tmp_path):
    registry = tmp_path / "themes.json"
    ledger = tmp_path / "ledger.json"
    _registry(registry)
    calls = []

    def caller(brief, schema):
        calls.append((brief, schema))
        return {"blocked": False, "flavor": "Thorn-wrapped roots guard a patient green shrine.", "reason": ""}

    first = theme_enrich.enrich(registry_path=registry, ledger_path=ledger, caller=caller, write=True)
    assert first["enriched"] == 1
    assert first["complete"] is True
    row = json.loads(registry.read_text(encoding="utf-8"))["themes"]["creature.alpha"]
    assert row["basis"] == "enriched"
    assert row["flavor"].startswith("Thorn-wrapped")
    assert row["flavorProvenance"]["pipeline"] == "theme-enrich"

    second = theme_enrich.enrich(registry_path=registry, ledger_path=ledger, caller=caller, write=True)
    assert second["pending"] == 0
    assert len(calls) == 1


def test_blocked_answer_is_terminal_but_does_not_lie_about_basis(tmp_path):
    registry = tmp_path / "themes.json"
    ledger = tmp_path / "ledger.json"
    _registry(registry)
    result = theme_enrich.enrich(
        registry_path=registry, ledger_path=ledger,
        caller=lambda brief, schema: {"blocked": True, "flavor": "", "reason": "insufficient lore"},
        write=True,
    )
    assert result["blocked"] == 1
    assert result["complete"] is False
    row = json.loads(registry.read_text(encoding="utf-8"))["themes"]["creature.alpha"]
    assert row["basis"] == "name"


def test_bound_name_theme_is_refused_before_model_call(tmp_path):
    registry = tmp_path / "themes.json"
    items = tmp_path / "items"
    items.mkdir()
    _registry(registry)
    (items / "set.json").write_text('{"kind":"set","entries":[{"themeKey":"creature.alpha"}]}', encoding="utf-8")
    with pytest.raises(ValueError, match="item-bound"):
        theme_enrich.enrich(registry_path=registry, items_root=items,
                            ledger_path=tmp_path / "ledger.json",
                            caller=lambda brief, schema: pytest.fail("model called"), write=True)
