"""`items repair-materials` / `items repair-charms` — the kind-narrowed duplicate-name repair.

    python -m pytest gk-forge/tools/seedsmith/tests/test_repair_names_kinds.py -q

**Why the commands exist.** `name_repair.plan()` is kind-agnostic and `repair-names` already planned
every losing row, so what was missing was not the ability to repair a material — it was the ability
to run the repair SCOPED to one kind. `--limit` cannot do it: it slices the entry-id-sorted plan, so
on a corpus with three colliding kinds it yields an arbitrary prefix, not one population. These
tests pin the narrowing and the properties that make it safe.

⛔ **Nothing here pins a population.** How many rows collide is a READING that moves whenever content
ships (measured 2026-10-01 on the real corpus: 66 groups, 72 material / 12 set losing rows, 0 charm).
Every assertion is a structural property — subset, no keeper, no self-keeper, exit code — so the
suite passes on a clean corpus and on a fully repaired one.

`collision_groups` is stubbed with groups in the validator's own `--collision-groups` shape, so these
tests never shell out to `dotnet`. The AUTHORITY is covered where it belongs: `plan()` against the
real corpus in `test_item_name_repair.RealCorpusPlanTests`, and a real end-to-end control
(temp corpus copy, real validator, real write, real re-validation) recorded in the change report.
"""
from __future__ import annotations

import contextlib
import io
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from seedsmith.adapters.items.setgen import name_repair  # noqa: E402
from seedsmith.report import cli as cli_mod  # noqa: E402

#: A collision group in the validator's own `--collision-groups` shape, same as the fixture
#: `test_item_name_repair._groups` builds. `reason: "name"` is the only reason these rows carry.
def _group(key: str, *members: "tuple[str, str, str]") -> dict:
    return {"reason": "name", "key": key, "members": [
        {"id": i, "name": n, "kind": k, "nameKey": f"{k}.{i}"} for i, n, k in members]}


#: Three groups over five rows, chosen so each narrowing has something to prove:
#:   G1 material/material  -> a material loses
#:   G2 charm/material     -> the CHARM keeps it, the material loses (cross-kind, keeper is a charm)
#:   G3 charm/charm        -> a charm genuinely loses, so `repair-charms` is not dead code
GROUPS = [
    _group("emberstone shard",
           ("material.a-001", "Emberstone Shard", "material"),
           ("material.b-001", "Shard of the Emberstone", "material")),
    _group("frostpine locket",
           ("charm.c-001", "Frostpine Locket", "charm"),
           ("material.c-001", "Frostpine Locket", "material")),
    _group("gloom chime",
           ("charm.a-001", "Gloom Chime", "charm"),
           ("charm.b-001", "Chime of the Gloom", "charm")),
]

CORPUS = {
    "materials/materials.json": ("material", [
        ("material.a-001", "Emberstone Shard", "material.emberstone-shard"),
        ("material.b-001", "Shard of the Emberstone", "material.shard-of-the-emberstone"),
        ("material.c-001", "Frostpine Locket", "material.frostpine-locket"),
    ]),
    "charms/charms.json": ("charm", [
        ("charm.a-001", "Gloom Chime", "charm.gloom-chime"),
        ("charm.b-001", "Chime of the Gloom", "charm.chime-of-the-gloom"),
        ("charm.c-001", "Frostpine Locket", "charm.frostpine-locket"),
    ]),
}


@pytest.fixture
def corpus(tmp_path, monkeypatch) -> Path:
    """A throwaway corpus carrying the fixture rows, and a stubbed collision authority.

    The directory is NOT the production tree, so a `--write` here can never touch committed data
    (the same private-copy rule `test_role_repair` states).
    """
    root = tmp_path / "items"
    for relative, (kind, rows) in CORPUS.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({
            "_meta": {"schemaVersion": 1, "kind": kind, "partition": kind},
            "kind": kind,
            "entries": [{"id": i, "name": n, "nameKey": k} for i, n, k in rows],
        }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    monkeypatch.setattr(name_repair, "collision_groups", lambda *a, **k: GROUPS)
    # The write path also asks the validator for each candidate's normalized key. Stub it to a
    # casefold so this suite never shells out to `dotnet`; the real normalizer is the authority and
    # is covered by `test_item_name_repair` and by the recorded end-to-end control.
    monkeypatch.setattr(name_repair, "validator_keys",
                        lambda names, **k: {str(n): str(n).strip().casefold() for n in names})
    return root


def _run(argv: "list[str]") -> "tuple[int, dict, str]":
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = cli_mod.main(argv)
    text = out.getvalue()
    return code, (json.loads(text[text.index("{"):]) if "{" in text else {}), err.getvalue()


class TestRegistration:
    def test_both_commands_are_registered_under_items(self):
        parser = cli_mod.build_parser()
        for command in ("repair-names", "repair-materials", "repair-charms"):
            args = parser.parse_args(["items", command])
            assert args.items_command == command
            assert args.func is cli_mod.cmd_items

    def test_the_three_take_one_argument_set(self):
        """They are one implementation narrowed by `kind`, so a flag added to one and not the others
        is the drift this pins. `repair-names` is the baseline."""
        parser = cli_mod.build_parser()
        baseline = vars(parser.parse_args(["items", "repair-names"]))
        for command in ("repair-materials", "repair-charms"):
            narrowed = vars(parser.parse_args(["items", command]))
            assert set(narrowed) == set(baseline), f"{command} declares a different argument set"
            for option, value in baseline.items():
                if option in ("func", "items_command"):
                    continue
                assert narrowed[option] == value, f"{command} --{option} default drifted"

    def test_help_lists_both_commands(self, capsys):
        with pytest.raises(SystemExit):
            cli_mod.main(["items", "--help"])
        out = capsys.readouterr().out
        assert "repair-materials" in out
        assert "repair-charms" in out


class TestMaterialNarrowing:
    def test_it_plans_only_material_rows(self, corpus):
        code, payload, _ = _run(["items", "repair-materials", "--items-dir", str(corpus)])
        assert code == cli_mod.EXIT_CLEAN
        assert payload["write"] is False
        assert payload["kind"] == "material"
        assert {r["entryId"] for r in payload["repairs"]} == {"material.b-001", "material.c-001"}
        assert {r["kind"] for r in payload["repairs"]} == {"material"}

    def test_every_planned_row_carries_a_reask_brief(self, corpus):
        """The replacement name comes from the model via this brief, never an invented placeholder."""
        _, payload, _ = _run(["items", "repair-materials", "--items-dir", str(corpus)])
        for repair in payload["repairs"]:
            assert repair["brief"].strip(), repair["entryId"]
            assert repair["entryId"] in repair["brief"]
            assert repair["keeperId"] in repair["brief"]

    def test_a_narrowed_plan_is_exactly_its_kind_inside_the_unscoped_plan(self, corpus):
        _, wide, _ = _run(["items", "repair-names", "--items-dir", str(corpus)])
        assert "kind" not in wide, "repair-names stays unscoped and says so by omitting `kind`"
        for command, kind in (("repair-materials", "material"), ("repair-charms", "charm")):
            _, narrow, _ = _run(["items", command, "--items-dir", str(corpus)])
            expected = {r["entryId"] for r in wide["repairs"] if r["kind"] == kind}
            assert {r["entryId"] for r in narrow["repairs"]} == expected

    def test_limit_applies_after_the_narrowing(self, corpus):
        """`--limit` slices the NARROWED plan. The opposite order is the bug this pins: slicing the
        wide plan first and filtering after silently returns fewer rows than asked for."""
        _, payload, _ = _run(["items", "repair-materials", "--items-dir", str(corpus), "--limit", "1"])
        assert len(payload["repairs"]) == 1

    def test_it_never_plans_a_row_that_keeps_its_name(self, corpus):
        for command in ("repair-names", "repair-materials", "repair-charms"):
            _, payload, _ = _run(["items", command, "--items-dir", str(corpus)])
            for repair in payload["repairs"]:
                assert repair["entryId"] != repair["keeperId"], command


class TestCharmNarrowing:
    def test_a_charm_that_keeps_its_name_is_never_planned(self, corpus):
        """`charm.c-001` is the group's keeper in a cross-kind group, so `repair-materials` must not
        rename it. A narrowing that renamed the winner would fix the collision by breaking the row
        that was already right."""
        _, payload, _ = _run(["items", "repair-materials", "--items-dir", str(corpus)])
        assert "charm.c-001" not in {r["entryId"] for r in payload["repairs"]}

    def test_a_charm_that_genuinely_loses_is_planned(self, corpus):
        """The narrow kind is not dead code: two charms colliding means the second one is renamed."""
        code, payload, _ = _run(["items", "repair-charms", "--items-dir", str(corpus)])
        assert code == cli_mod.EXIT_CLEAN
        assert payload["kind"] == "charm"
        assert [r["entryId"] for r in payload["repairs"]] == ["charm.b-001"]


class TestEmptyPlan:
    """A clean corpus has nothing to repair. That is a CLEAN result, not a failed run — a narrowed
    command reaches `--write` on such a corpus routinely, and reporting "no usable answers (0
    failed)" would blame the model for a plan that never asked it anything."""

    def test_a_dry_run_with_nothing_to_repair_is_clean(self, corpus, monkeypatch):
        monkeypatch.setattr(name_repair, "collision_groups", lambda *a, **k: [])
        for command in ("repair-names", "repair-materials", "repair-charms"):
            code, payload, _ = _run(["items", command, "--items-dir", str(corpus)])
            assert code == cli_mod.EXIT_CLEAN, command
            assert payload["repairs"] == [], command

    def test_a_write_with_nothing_to_repair_is_clean_and_writes_nothing(self, corpus, monkeypatch):
        monkeypatch.setattr(name_repair, "collision_groups", lambda *a, **k: [])
        before = {p: p.read_text(encoding="utf-8") for p in corpus.rglob("*.json")}
        code, payload, _ = _run(
            ["items", "repair-materials", "--items-dir", str(corpus), "--write", "--answers", "x"])
        assert code == cli_mod.EXIT_CLEAN
        assert payload["changed"] == [] and payload["failed"] == []
        assert {p: p.read_text(encoding="utf-8") for p in corpus.rglob("*.json")} == before


class TestRefusal:
    def test_it_refuses_a_production_write_and_names_the_command_typed(self, corpus, monkeypatch):
        """Same refusal as every sibling repair entry, reported under the name the user typed —
        `repair-sets` / `repair-species` / `repair-set-class` each name their own."""
        monkeypatch.setattr(name_repair, "ITEM_SEED_ROOT", corpus)
        code, _, err = _run(["items", "repair-materials", "--items-dir", str(corpus), "--write"])
        assert code == cli_mod.EXIT_REFUSED
        assert "repair-materials refused" in err
        assert "allow-production-tree" in err

    def test_charms_refusal_names_its_own_command(self, corpus, monkeypatch):
        monkeypatch.setattr(name_repair, "ITEM_SEED_ROOT", corpus)
        code, _, err = _run(["items", "repair-charms", "--items-dir", str(corpus), "--write"])
        assert code == cli_mod.EXIT_REFUSED
        assert "repair-charms refused" in err

    def test_a_non_production_tree_is_not_refused(self, corpus):
        """A temp copy is writable without the flag — that is what makes the write path testable at
        all without touching the committed corpus.

        `validate_answers` demands an answer for EVERY planned row, so the narrowed plan's two
        losing rows both need one; a partial answer file is refused, not half-applied.
        """
        answers = corpus.parent / "answers.json"
        answers.write_text(json.dumps({"answers": {
            "material.b-001": {"name": "Slagglass Splinter"},
            "material.c-001": {"name": "Frostpine Locket Charm"},
        }}), encoding="utf-8")
        code, payload, _ = _run(["items", "repair-materials", "--items-dir", str(corpus),
                                 "--write", "--answers", str(answers)])
        assert code == cli_mod.EXIT_CLEAN
        assert [Path(p) for p in payload["changed"]] == [corpus / "materials" / "materials.json"]
        rows = json.loads((corpus / "materials" / "materials.json").read_text(encoding="utf-8"))["entries"]
        by_id = {r["id"]: r for r in rows}
        assert by_id["material.b-001"]["name"] == "Slagglass Splinter"
        assert by_id["material.b-001"]["nameKey"] == "material.slagglass-splinter"
        assert by_id["material.c-001"]["nameKey"] == "material.frostpine-locket-charm"
        # The keeper, and every unrelated row, are byte-for-byte what they were.
        assert by_id["material.a-001"] == {"id": "material.a-001", "name": "Emberstone Shard",
                                           "nameKey": "material.emberstone-shard"}
        charms = json.loads((corpus / "charms" / "charms.json").read_text(encoding="utf-8"))
        assert charms["entries"] == [
            {"id": "charm.a-001", "name": "Gloom Chime", "nameKey": "charm.gloom-chime"},
            {"id": "charm.b-001", "name": "Chime of the Gloom", "nameKey": "charm.chime-of-the-gloom"},
            {"id": "charm.c-001", "name": "Frostpine Locket", "nameKey": "charm.frostpine-locket"},
        ]

    def test_a_partial_answer_file_is_refused_rather_than_half_applied(self, corpus):
        """The narrowed plan names two rows; answering one is a refusal, not a partial write."""
        answers = corpus.parent / "answers.json"
        answers.write_text(json.dumps({"answers": {"material.b-001": {"name": "Slagglass Splinter"}}}),
                           encoding="utf-8")
        before = (corpus / "materials" / "materials.json").read_text(encoding="utf-8")
        code, _, err = _run(["items", "repair-materials", "--items-dir", str(corpus),
                             "--write", "--answers", str(answers)])
        assert code == cli_mod.EXIT_CANNOT_RUN
        assert "exactly" in err
        assert (corpus / "materials" / "materials.json").read_text(encoding="utf-8") == before
