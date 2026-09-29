"""P3 — the exemplar gate. Acceptance criteria quoted from `tasks/seedsmith-plan.md` Phase 2:

1. "A work order referencing a synthetic exemplar with a missing required field is refused, not
   partially emitted"
2. "A clean exemplar set passes through untouched"

Fixture helpers are borrowed from the existing exemplar tests rather than re-rolled — the shape of
a seed file on disk is already established, and a second dialect of it would drift.
"""
from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path

import pytest

from seedsmith.adapters.items import ItemsAdapter
from seedsmith.corpus.model import Corpus
from seedsmith.metrics.model import Ctx
from seedsmith.planner.validate import EXIT_EXEMPLAR_REFUSED, gate_exemplars


def write(root: Path, rel: str, kind: str, entries: list[dict]) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"kind": kind, "entries": entries}), encoding="utf-8")


CLEAN_UNIQUE = {
    "id": "unique.exemplar-001", "nameKey": "u.ex1", "name": "Exemplar",
    "frame": "plant", "baseType": "item.plant-stem-a-001", "rarity": "grafted",
    "fixedAtoms": [], "counterPressure": {}, "tags": [], "powerAxis": "might",
}


@pytest.fixture()
def root():
    d = Path(tempfile.mkdtemp())
    yield d
    shutil.rmtree(d, ignore_errors=True)


def ctx_for(root: Path) -> Ctx:
    return Ctx(corpus=Corpus.load(root), adapter=ItemsAdapter())


# ---- Criterion 1: refused, and refused WHOLE ---------------------------------------------------


def test_an_exemplar_missing_a_required_field_refuses_the_order(root):
    broken = dict(CLEAN_UNIQUE)
    del broken["powerAxis"]                      # the exact historical defect
    write(root, "_exemplars/unique.json", "unique", [broken])

    result = gate_exemplars(ctx_for(root))

    assert result.refused is True
    assert result.ok is False
    assert result.exit_code == EXIT_EXEMPLAR_REFUSED == 3


def test_the_refusal_names_the_exemplar_and_the_field(root):
    """A refusal nobody can act on sends an author to read every exemplar. The message has to carry
    both which file and which field."""
    broken = dict(CLEAN_UNIQUE)
    del broken["powerAxis"]
    write(root, "_exemplars/unique.json", "unique", [broken])

    explained = gate_exemplars(ctx_for(root)).explain()

    assert "REFUSED" in explained
    assert "unique.exemplar-001" in explained
    assert "powerAxis" in explained


def test_one_bad_exemplar_refuses_the_whole_order_not_just_its_own_kind(root):
    """"Refused, not partially emitted." A gate that let the clean kinds through would dispatch
    jobs against a corpus whose pattern set is known-broken, and leave no single artifact saying
    which half ran."""
    broken = dict(CLEAN_UNIQUE)
    del broken["powerAxis"]
    write(root, "_exemplars/unique.json", "unique", [broken])
    write(root, "_exemplars/gem.json", "gem", [{
        "id": "gem.exemplar-001", "nameKey": "g.ex1", "name": "Gem Exemplar",
        "family": "ruby", "powerBand": 3,
    }])

    result = gate_exemplars(ctx_for(root))

    assert result.refused is True
    assert "gem.exemplar-001" in result.checked, "the clean exemplar was still examined"
    assert all(f.subject == "unique.exemplar-001" for f in result.findings)


def test_the_set_exemplar_that_produced_thirty_uncompletable_sets_is_refused(root):
    """The worst of the three historical cases: an exemplar teaching members-by-role-alone. Every
    author who copied it shipped a set that could never be completed."""
    write(root, "_exemplars/set.json", "set", [{
        "id": "set.exemplar-001", "nameKey": "s.ex1", "name": "Exemplar Set",
        "themeKey": "ex", "members": [{"role": "core-guard"}, {"role": "head-guard"}],
        "thresholds": [{"pieces": 2}],
    }])

    result = gate_exemplars(ctx_for(root))

    assert result.refused is True
    assert any(f.evidence.get("code") == "SetUncompletable" for f in result.findings)


# ---- Criterion 2: a clean set passes through untouched -----------------------------------------


def test_a_clean_exemplar_set_passes(root):
    write(root, "_exemplars/unique.json", "unique", [CLEAN_UNIQUE])

    result = gate_exemplars(ctx_for(root))

    assert result.ok is True
    assert result.exit_code == 0
    assert result.findings == ()
    assert result.checked == ("unique.exemplar-001",)


def test_an_empty_corpus_passes_rather_than_refusing_on_nothing(root):
    """The positive control's control. A gate that refused an empty corpus would block the very
    first run of a new adapter, and "no exemplars" is not "bad exemplars"."""
    result = gate_exemplars(ctx_for(root))

    assert result.ok is True
    assert result.checked == ()


# ---- Scoping: the gate must be usable without becoming something people route around -----------


def test_a_broken_exemplar_for_an_unreferenced_kind_does_not_refuse_the_order(root):
    """Scoping matters for adoption, not just correctness: a gate that refuses an order over a kind
    the order never touches is one people learn to skip, and a skipped gate protects nothing."""
    broken = dict(CLEAN_UNIQUE)
    del broken["powerAxis"]
    write(root, "_exemplars/unique.json", "unique", [broken])
    write(root, "_exemplars/gem.json", "gem", [{
        "id": "gem.exemplar-001", "nameKey": "g.ex1", "name": "Gem Exemplar",
        "family": "ruby", "powerBand": 3,
    }])

    result = gate_exemplars(ctx_for(root), referenced_kinds={"gem"})

    assert result.ok is True
    assert result.checked == ("gem.exemplar-001",)


def test_scoping_still_refuses_when_the_referenced_kind_is_the_broken_one(root):
    """The other half of the same rule — without this, the scoping test above would also pass for a
    gate that had simply stopped refusing anything."""
    broken = dict(CLEAN_UNIQUE)
    del broken["powerAxis"]
    write(root, "_exemplars/unique.json", "unique", [broken])

    result = gate_exemplars(ctx_for(root), referenced_kinds={"unique"})

    assert result.refused is True
    assert result.exit_code == EXIT_EXEMPLAR_REFUSED


def test_the_gate_reuses_the_metric_rather_than_reimplementing_its_judgement(root):
    """P3's own instruction: "reused, not reimplemented". Asserted structurally — the gate's
    findings must be `ExemplarConformance`'s, id and all, so a future change to what a valid
    exemplar is cannot leave a second stale copy of that judgement here."""
    from seedsmith.metrics.exemplar import ExemplarConformance

    broken = dict(CLEAN_UNIQUE)
    del broken["powerAxis"]
    write(root, "_exemplars/unique.json", "unique", [broken])
    ctx = ctx_for(root)

    gate = gate_exemplars(ctx)
    direct = ExemplarConformance().run(ctx)

    assert [f.metric for f in gate.findings] == [f.metric for f in direct]
    assert all(f.metric == ExemplarConformance.id for f in gate.findings)
