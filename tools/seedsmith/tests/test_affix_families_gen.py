"""Tests for `seedsmith.adapters.items.affixfamgen` — item-seedgen module 2, `affix-families-gen`
(docs/architecture/item-seedgen/spec-affix-families-gen.md).

Covers the spec's own Testing strategy:
- A generated family's `op` is always in the correct closed set for its declared atom kind.
- Harness tests (resume/reconcile/overwrite).

**On Acceptance #2 ("passes the SAME legality check module 8 already enforces")**: `item_role_family`
is module 8's own output (`docs/architecture/item-seedgen-map.md` §2, phase 3, not yet built — a
repo-wide search for `item_role_family`/`ItemRoleFamily` under `gk-forge/tools/seedsmith` returns nothing).
There is no real check to run this generator's output against yet, so this file instead proves the
one thing available today: every role this generator can ever emit is drawn from the SAME real,
current `core.v1.json` role registry module 8's matrix will eventually be built from
(`test_role_vocabulary_is_the_real_registry_vocabulary`), so a future `item_role_family` check has
no vocabulary mismatch to fail on for reasons unrelated to actual legality.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from seedsmith.pipeline.model import audit_schema
from seedsmith.pipeline.run_ledger import RunLedger

from seedsmith.adapters.items.affixfamgen import brief as brief_mod
from seedsmith.adapters.items.affixfamgen import emit
from seedsmith.adapters.items.affixfamgen import opvocab
from seedsmith.adapters.items.affixfamgen import run as run_mod
from seedsmith.adapters.items.affixfamgen import schema as schema_mod

REPO_ROOT = Path(__file__).resolve().parents[3]
FAMILIES_DIR = REPO_ROOT / "data" / "seed" / "items" / "affix-families"
CORE_REGISTRY = REPO_ROOT / "data" / "seed" / "items" / "_registry" / "core.v1.json"


# ---------------------------------------------------------------------------------------------
# opvocab — the real, closed op-per-kind vocabulary (Acceptance #3)
# ---------------------------------------------------------------------------------------------

def test_stat_modify_legal_ops_are_flat_increased_more() -> None:
    assert opvocab.legal_ops("stat.modify") == ("Flat", "Increased", "More")


def test_stat_derived_legal_ops_are_flat_increased_replace_flag() -> None:
    assert opvocab.legal_ops("stat.derived") == ("Flat", "Increased", "Replace", "Flag")


def test_stat_modify_never_accepts_override() -> None:
    """AtomKindRegistry.Validate explicitly refuses Override for stat.modify (A18e) — this is the
    one op the real C# validator special-cases by name, so it is the sharpest possible regression
    check for opvocab staying in sync with it."""
    assert not opvocab.is_legal_op("stat.modify", "Override")
    with pytest.raises(opvocab.IllegalOpError):
        opvocab.canonical_op("stat.modify", "Override")


def test_stat_derived_never_accepts_more() -> None:
    """"there is no More on the derived side" — AtomKindRegistry.cs's own stat.derived doc line."""
    assert not opvocab.is_legal_op("stat.derived", "More")
    with pytest.raises(opvocab.IllegalOpError):
        opvocab.canonical_op("stat.derived", "More")


def test_canonical_op_is_case_insensitive_but_emits_shipped_casing() -> None:
    assert opvocab.canonical_op("stat.modify", "flat") == "Flat"
    assert opvocab.canonical_op("stat.derived", "REPLACE") == "Replace"


def test_unsupported_kind_is_refused_not_guessed() -> None:
    with pytest.raises(opvocab.UnsupportedKindError):
        opvocab.legal_ops("resource.delta")


def test_real_shipped_corpus_ops_are_all_within_opvocabs_closed_set() -> None:
    """Grounding check against the real 109-family corpus: every entry actually shipped in
    `gk-data/packs/fusion/data/seed/items/affix-families/*.json` must use an op this module's transcribed vocabulary
    already covers — the corpus itself is the regression oracle for opvocab, not a second guess."""
    checked = 0
    for path in sorted(FAMILIES_DIR.glob("*.json")):
        doc = json.loads(path.read_text(encoding="utf-8"))
        for entry in doc["entries"]:
            kind_id = entry["kindId"]
            if not opvocab.is_supported_kind(kind_id):
                continue  # a kind this generator does not author against (e.g. resource.delta) —
                          # some of those (spawn.entity, status.apply) carry no `op` param at all
            op = entry["params"]["op"]
            assert opvocab.is_legal_op(kind_id, op), (
                f"{path.name}:{entry['id']} uses op {op!r} for kind {kind_id!r}, outside "
                f"opvocab's transcribed vocabulary {opvocab.legal_ops(kind_id)}")
            checked += 1
    assert checked > 0, "expected to find at least one stat.modify/stat.derived entry to check"


# ---------------------------------------------------------------------------------------------
# schema — bare numeric field construction guard
# ---------------------------------------------------------------------------------------------

def test_affix_family_schema_is_audit_schema_clean_for_both_kinds() -> None:
    for kind_id in ("stat.modify", "stat.derived"):
        free = (("defense", "Flat"),) if kind_id == "stat.modify" else (("defense", "Flag"),)
        schema = schema_mod.affix_family_schema(
            kind_id, free_pairs=free, roles=("standard",), tags=("defensive",),
            power_bands=("low", "medium", "high"))
        assert audit_schema(schema) == []
        assert "nameKey" not in schema["properties"]
        assert "required" in schema and "name" in schema["required"]


def test_affix_family_schema_channel_op_enum_is_free_pairs_only() -> None:
    free = (("arm1Max", "More"), ("arm2Max", "More"))
    schema = schema_mod.affix_family_schema(
        "stat.modify", free_pairs=free, roles=("standard",), tags=("defensive",),
        power_bands=("low",))
    enum = schema["properties"]["channelOp"]["enum"]
    assert "arm1Max|More" in enum
    assert "arm2Max|More" in enum
    assert "defense|More" not in enum
    assert None in enum


def test_a_bare_numeric_field_fails_schema_construction() -> None:
    """The exact failure mode Acceptance criterion 1 forbids: a schema that lets a model emit a
    raw magnitude. Hand-broken here (not through the real builder, which never produces one) to
    prove `audit_schema` — the same mechanism `brief.AffixFamilyBrief.__post_init__` runs at
    construction — actually catches it, mirroring `pipeline.model.Pipeline.__post_init__`'s own
    guard style."""
    broken = schema_mod.affix_family_schema(
        "stat.modify", free_pairs=(("defense", "Increased"),), roles=("standard",),
        tags=("defensive",), power_bands=("low",))
    broken["properties"]["amount"] = {"type": "integer"}
    defects = audit_schema(broken)
    assert any("amount" in str(d) or "bare numeric" in str(d) for d in defects)


def test_brief_construction_refuses_a_schema_that_smuggles_a_number() -> None:
    """`AffixFamilyBrief.__post_init__` is the construction-time guard this generator carries —
    Pipeline.__post_init__'s own discipline, applied here. A caller handing it a pre-built schema
    with a smuggled numeric field must never reach `render()`."""
    partition = brief_mod.PartitionContext(
        group_id="g.armour", stem="arm", existing_ids=("atom.warding",),
        channel_ops={"defense": ("Flat",)})
    bad_schema = schema_mod.affix_family_schema(
        "stat.modify", free_pairs=(("defense", "Increased"),), roles=("standard",),
        tags=("defensive",), power_bands=("low",))
    bad_schema["properties"]["tier"] = {"type": "integer", "enum": [1, 2, 3]}
    with pytest.raises(ValueError):
        brief_mod.AffixFamilyBrief(
            partition=partition, kind_id="stat.modify", roles=("standard",),
            tags=("defensive",), power_bands=("low",), schema=bad_schema)


# ---------------------------------------------------------------------------------------------
# brief — real partition grounding
# ---------------------------------------------------------------------------------------------

def test_load_partition_context_reads_the_real_g_armour_file() -> None:
    ctx = brief_mod.load_partition_context("g.armour")
    assert ctx.stem == "arm"
    assert "atom.warding" in ctx.existing_ids
    assert "atom.plating" in ctx.existing_ids
    assert ctx.channel_ops["defense"] == ("Flat", "Increased", "More")
    assert "Flat" in ctx.channel_ops["arm1Max"]


def test_group_stem_reads_the_real_naming_registry() -> None:
    assert brief_mod.group_stem("g.armour") == "arm"
    assert brief_mod.group_stem("g.attack") == "atk"
    assert brief_mod.group_stem("g.life") == "life"


def test_unknown_group_is_refused() -> None:
    with pytest.raises(brief_mod.UnknownGroupError):
        brief_mod.group_stem("g.does-not-exist")


def test_role_vocabulary_is_the_real_registry_vocabulary() -> None:
    """The substitute proof for Acceptance #2 available before module 8 exists — see this file's
    own module docstring."""
    roles = brief_mod.load_role_vocabulary()
    doc = json.loads(CORE_REGISTRY.read_text(encoding="utf-8"))
    expected = {r["roleId"] for r in doc["roles"]["list"]} | {
        r["roleId"] for r in doc["roles"]["commanderOnly"]}
    assert set(roles) == expected


def test_build_affix_family_brief_end_to_end_for_real_partition() -> None:
    # Armour is intentionally full in the current corpus; use a still-runnable shipped
    # partition for the end-to-end brief contract.
    brief = brief_mod.build_affix_family_brief("g.elem-power", "stat.derived")
    enum = brief.schema["properties"]["channelOp"]["enum"]
    assert enum
    assert "defense|More" not in enum
    assert "combat.power" in " ".join(brief.partition.channels)
    assert audit_schema(brief.schema) == []
    text = brief.render()
    assert "atom.elpw-" in text
    assert "Never choose a number" in text
    assert "channelOp" in text


def test_brief_refuses_a_partition_with_no_channels() -> None:
    empty = brief_mod.PartitionContext(group_id="g.x", stem="x", existing_ids=(), channel_ops={})
    with pytest.raises(ValueError):
        brief_mod.AffixFamilyBrief(
            partition=empty, kind_id="stat.modify", roles=("standard",),
            tags=("defensive",), power_bands=("low",))


# ---------------------------------------------------------------------------------------------
# emit — assembling a real entry, defense-in-depth validation
# ---------------------------------------------------------------------------------------------

@pytest.fixture()
def armour_partition() -> brief_mod.PartitionContext:
    # Keep emit/schema tests independent of production slot capacity. The live armour partition
    # is full today, but these tests need two legal free pairs to exercise successful assembly.
    return brief_mod.PartitionContext(
        group_id="g.armour", stem="arm",
        existing_ids=("atom.warding", "atom.resilience", "atom.plating"),
        channel_ops={
            "defense": ("Flat", "Increased", "More"),
            "arm1Max": ("Flat", "Increased"),
            "arm2Max": ("Flat", "Increased"),
        },
    )


def test_assemble_entry_produces_a_shipped_shaped_entry(armour_partition) -> None:
    answer = {
        "word": "plating-mastery", "channelOp": "arm1Max|More",
        "roles": ["core-guard", "mantle"], "tags": ["defensive"], "powerBand": "low",
        "name": "Plating Mastery", "displayTemplate": "{value}% more armor plating",
        "blocked": None,
    }
    entry = emit.assemble_entry(answer, armour_partition, "stat.modify")
    assert entry["id"] == "atom.arm-plating-mastery"
    assert entry["kindId"] == "stat.modify"
    assert entry["params"] == {"channel": "arm1Max", "op": "More"}
    assert entry["nameKey"] == "affix.plating-mastery"
    assert entry["roles"] == ["core-guard", "mantle"]


def test_assemble_entry_rejects_a_duplicate_channel_op_pair(armour_partition) -> None:
    """`defense`+`Flat` is `atom.warding` — the exact duplicate-mechanic case
    `g-attack.json`'s own notes name (the elemental_power/elpw-amplify precedent)."""
    answer = {
        "word": "second-warding", "channelOp": "defense|Flat",
        "roles": ["standard"], "tags": ["defensive"], "powerBand": "medium",
        "name": "Second Warding", "displayTemplate": "+{value} defense", "blocked": None,
    }
    with pytest.raises(emit.DuplicateChannelOpError):
        emit.assemble_entry(answer, armour_partition, "stat.modify")


def test_answer_validation_rejects_taken_pair_not_in_free_set(armour_partition) -> None:
    free = brief_mod.free_channel_ops(armour_partition, "stat.modify")
    schema = schema_mod.affix_family_schema(
        "stat.modify", free_pairs=free, roles=("standard",),
        tags=("defensive",), power_bands=("low",),
    )
    answer = {
        "word": "second-warding", "channelOp": "defense|Flat",
        "roles": ["standard"], "tags": ["defensive"], "powerBand": "low",
        "name": "Second Warding", "displayTemplate": "+{value} defense", "blocked": None,
    }

    defects = schema_mod.validate_answer(
        answer, schema, channel_ops=armour_partition.channel_ops, kind_id="stat.modify",
        free_pairs=free)

    assert any("free-pair" in defect or "already ships" in defect for defect in defects)


def test_validate_answer_accepts_blocked_with_null_content() -> None:
    free = (("arm1Max", "More"),)
    schema = schema_mod.affix_family_schema(
        "stat.modify", free_pairs=free, roles=("standard",), tags=("defensive",),
        power_bands=("low",))
    answer = {
        "blocked": "no good theme",
        "name": None, "displayTemplate": None, "word": None, "channelOp": None,
        "roles": None, "tags": None, "powerBand": None,
    }
    assert schema_mod.validate_answer(answer, schema, free_pairs=free, kind_id="stat.modify") == []


def test_assemble_entry_rejects_an_illegal_op_for_the_kind(armour_partition) -> None:
    answer = {
        "word": "brand-new", "channelOp": "arm1Max|Override",
        "roles": ["standard"], "tags": ["defensive"], "powerBand": "low",
        "name": "Brand New", "displayTemplate": "x", "blocked": None,
    }
    with pytest.raises(opvocab.IllegalOpError):
        emit.assemble_entry(answer, armour_partition, "stat.modify")


def test_assemble_entry_rejects_an_id_collision() -> None:
    ctx = brief_mod.PartitionContext(
        group_id="g.armour", stem="arm", existing_ids=("atom.arm-foo",),
        channel_ops={"defense": ("Flat",)})
    answer = {
        "word": "foo", "channelOp": "defense|Increased",
        "roles": ["standard"], "tags": ["defensive"], "powerBand": "low",
        "name": "Foo", "displayTemplate": "x", "blocked": None,
    }
    with pytest.raises(emit.IdCollisionError):
        emit.assemble_entry(answer, ctx, "stat.modify")


def test_assemble_entry_normalizes_op_casing(armour_partition) -> None:
    answer = {
        "word": "lower-case-op", "channelOp": "arm2Max|more",
        "roles": ["standard"], "tags": ["defensive"], "powerBand": "low",
        "name": "Lower Case Op", "displayTemplate": "x", "blocked": None,
    }
    entry = emit.assemble_entry(answer, armour_partition, "stat.modify")
    assert entry["params"]["op"] == "More"


def test_emit_document_matches_the_shipped_wrapper_shape() -> None:
    doc = emit.emit_document([{"id": "atom.arm-test"}], batch="affix-g-armour",
                             partition="affix-families/g.armour",
                             source_ref="atom-family-library.md#3.1", model="test-model")
    assert doc["schemaVersion"] == 1
    assert doc["kind"] == "affix-family"
    assert doc["_meta"]["partition"] == "affix-families/g.armour"
    assert doc["entries"] == [{"id": "atom.arm-test"}]


def test_write_document_round_trips(tmp_path: Path) -> None:
    doc = {"schemaVersion": 1, "entries": []}
    path = tmp_path / "out.json"
    emit.write_document(path, doc)
    assert json.loads(path.read_text(encoding="utf-8")) == doc


# ---------------------------------------------------------------------------------------------
# numerics — Acceptance #1, and the real gap found while wiring it
# ---------------------------------------------------------------------------------------------

def _tuning_with_might() -> "object":
    from seedsmith.numerics.model import TierBands
    return TierBands(version=1, base_share_permille=30, channel_weight_permille={"might": 1000})


def test_resolve_tier_curve_succeeds_for_a_real_shipped_stat_modify_family() -> None:
    from seedsmith.numerics.model import ProgressionPoint
    curve = emit.resolve_tier_curve("might", "Flat", _tuning_with_might(),
                                    ProgressionPoint(level=10))
    assert len(curve.ladder) == 5
    # monotonic strictly increasing, per resolve()'s own guardrail
    assert all(curve.ladder[i] < curve.ladder[i + 1] for i in range(4))


def test_resolve_tier_curve_refuses_a_stat_derived_op() -> None:
    """The real, honestly-reported gap: seedsmith.numerics.OpWeight has no Replace/Flag member, so
    a stat.derived family's curve cannot be resolved through this path today."""
    from seedsmith.numerics.model import ProgressionPoint
    with pytest.raises(emit.NumericsPathUnavailableError):
        emit.resolve_tier_curve("precision", "Replace", _tuning_with_might(),
                                ProgressionPoint(level=10))


def test_resolve_tier_curve_refuses_a_brand_new_family_name() -> None:
    """A genuinely new family (this generator's whole purpose) has no `reference_base` wiring in
    `adapters.items.channels` yet, even if a caller hand-supplies a channelWeight for it —
    see `emit.resolve_tier_curve`'s own docstring for the full finding."""
    from seedsmith.numerics.model import ProgressionPoint, TierBands
    tuning = TierBands(version=1, base_share_permille=30,
                       channel_weight_permille={"arm-hardening": 1000})
    with pytest.raises(emit.NumericsPathUnavailableError):
        emit.resolve_tier_curve("arm-hardening", "Flat", tuning, ProgressionPoint(level=10))


# ---------------------------------------------------------------------------------------------
# run — harness integration: resume, reconcile, overwrite
# ---------------------------------------------------------------------------------------------

@pytest.fixture()
def ledger(tmp_path: Path) -> RunLedger:
    return RunLedger(path=tmp_path / "affix-families-gen.ledger.json")


def test_plan_requests_returns_only_unattempted_requests(ledger: RunLedger) -> None:
    requests = [
        run_mod.FamilyRequest("g.armour", "stat.modify", "brand-new-a"),
        run_mod.FamilyRequest("g.armour", "stat.modify", "brand-new-b"),
    ]
    plan = run_mod.plan_requests(requests, ledger, families_dir=FAMILIES_DIR)
    assert plan.to_generate == tuple(requests)
    assert plan.already_done == ()
    assert not plan.complete

    # Marking a request "done" with an id the real corpus does NOT actually contain must NOT be
    # trusted as resumed — that is the reconcile behaviour, proven directly below by
    # `test_plan_requests_reconciles_a_ledger_row_the_real_corpus_no_longer_backs`. Resume is
    # proven here with a mintedId the real g-armour.json genuinely ships.
    run_mod.mark_family_written(ledger, requests[0], "atom.warding")
    plan2 = run_mod.plan_requests(requests, ledger, families_dir=FAMILIES_DIR)
    assert plan2.to_generate == (requests[1],)
    assert plan2.already_done == (requests[0].subject_id,)


def test_plan_requests_reconciles_a_ledger_row_the_real_corpus_no_longer_backs(
    ledger: RunLedger,
) -> None:
    """The reconcile half: a ledger row claiming `atom.arm-nonexistent-word` was written, but that
    id is not actually present in the real `g-armour.json` (nobody wrote it — a fabricated ledger
    row, standing in for "a hand edit reverted this out of band"). `plan_requests` must not trust
    the claim."""
    request = run_mod.FamilyRequest("g.armour", "stat.modify", "nonexistent-word")
    run_mod.mark_family_written(ledger, request, "atom.arm-nonexistent-word")

    plan = run_mod.plan_requests([request], ledger, families_dir=FAMILIES_DIR)
    assert plan.to_generate == (request,)


def test_plan_requests_trusts_a_ledger_row_the_real_corpus_does_back(ledger: RunLedger) -> None:
    """The positive control for the reconcile test above: a ledger row naming a REAL, currently
    shipped id (`atom.warding`, spelled as if minted from word `"warding"` on stem `arm` — this is
    a synthetic id for the test, not implying `atom.warding` was actually minted this way) must be
    trusted when the corpus really does contain it."""
    request = run_mod.FamilyRequest("g.armour", "stat.modify", "irrelevant")
    ledger.mark_done(request.subject_id, {"mintedId": "atom.warding", "groupId": "g.armour",
                                          "kindId": "stat.modify"})
    plan = run_mod.plan_requests([request], ledger, families_dir=FAMILIES_DIR)
    assert plan.to_generate == ()
    assert plan.already_done == (request.subject_id,)


def test_force_requests_overwrites_named_ids_only(ledger: RunLedger) -> None:
    requests = [
        run_mod.FamilyRequest("g.armour", "stat.modify", "a"),
        run_mod.FamilyRequest("g.armour", "stat.modify", "b"),
    ]
    for r in requests:
        run_mod.mark_family_written(ledger, r, f"atom.arm-{r.word}")

    forced = run_mod.force_requests(ledger, [requests[0]], scope="ids")
    assert forced == [requests[0]]


def test_force_requests_all_requires_the_literal_all(ledger: RunLedger) -> None:
    requests = [run_mod.FamilyRequest("g.armour", "stat.modify", "a")]
    with pytest.raises(ValueError):
        run_mod.force_requests(ledger, requests, scope="everything")


def test_ledger_write_is_deterministic_across_two_runs(ledger: RunLedger) -> None:
    """The determinism discipline `RunLedger` itself documents (`sort_keys=True`) — asserted here
    against THIS module's own entry shape, not just the generic ledger tests."""
    request = run_mod.FamilyRequest("g.armour", "stat.modify", "det")
    run_mod.mark_family_written(ledger, request, "atom.arm-det")
    first = ledger.path.read_bytes()
    run_mod.mark_family_written(ledger, request, "atom.arm-det")
    second = ledger.path.read_bytes()
    assert first == second


# ---------------------------------------------------------------------------------------------
# CLI — real gap, closed 2026-09-08: this module had no entrypoint of any kind before this.
# ---------------------------------------------------------------------------------------------


@pytest.fixture()
def isolated_families_dir(tmp_path, monkeypatch):
    """Copies the real, shipped `g-armour.json` into an isolated tmp dir and points `FAMILIES_DIR`
    at it — `g.armour` is a REAL registered group (`NAMING_REGISTRY` is not monkeypatched, so
    `group_stem` resolves it correctly), but every read/write in this fixture's tests lands in the
    tmp copy, never the live repo file."""
    families_dir = tmp_path / "affix-families"
    families_dir.mkdir()
    real_doc = json.loads((FAMILIES_DIR / "g-armour.json").read_text(encoding="utf-8"))
    # The shipped armour partition is full after the latest generation run. Remove only the two
    # pairs exercised by these CLI tests in the isolated copy; never mutate production data.
    real_doc["entries"] = [
        entry for entry in real_doc["entries"]
        if not (
            entry.get("params", {}).get("channel") in {"arm1Max", "arm2Max"}
            and entry.get("params", {}).get("op") == "More"
        )
    ]
    (families_dir / "g-armour.json").write_text(
        json.dumps(real_doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    monkeypatch.setattr(brief_mod, "FAMILIES_DIR", families_dir)
    monkeypatch.setattr(run_mod, "DEFAULT_LEDGER", tmp_path / "ledger.json")
    return families_dir


def test_cli_dry_run_prints_the_brief_and_makes_no_model_call(isolated_families_dir, capsys):
    exit_code = run_mod.main(["--group", "g.armour", "--affix-kind", "stat.modify", "--dry-run"])
    assert exit_code == 0
    out = capsys.readouterr().out
    assert "g.armour" in out


def test_cli_write_without_endpoint_refuses(isolated_families_dir, monkeypatch):
    """Refuse only when the *resolved* transport has no endpoint (CLI empty + config empty)."""
    from seedsmith.pipeline.llm_caller import LlmCallerConfig
    monkeypatch.setattr(
        "seedsmith.pipeline.llm_caller.resolve_live_transport",
        lambda *a, **k: LlmCallerConfig(endpoint="", model="x"))
    with pytest.raises(SystemExit):
        run_mod.main(["--group", "g.armour", "--affix-kind", "stat.modify", "--write"])



def test_cli_a_real_live_run_writes_a_real_partition_file(isolated_families_dir, capsys, monkeypatch):
    """⛔ Real gap, closed 2026-09-08 — see basetypegen's identical test for the full account. One
    real divergence from every sibling module: this module's own brief asks the MODEL to choose
    `word` (the thing every sibling module's caller decides beforehand) — the fake answer supplies
    it exactly like a real model would."""
    called_with = {}

    def _fake_live_answer_caller(config, *, validator=None):
        called_with["config"] = config

        def _call(brief, schema):
            called_with["schema"] = schema
            # arm1Max only ships Flat/Increased on the real, shipped partition — More is free.
            return {"word": "livewired", "channelOp": "arm1Max|More",
                    "roles": ["core-guard"], "tags": ["defensive"], "powerBand": "medium",
                    "name": "Live-Wired Ward", "displayTemplate": "+{value} Defense",
                    "blocked": None}
        return _call

    monkeypatch.setattr("seedsmith.pipeline.llm_caller.live_answer_caller",
                        _fake_live_answer_caller)

    exit_code = run_mod.main(["--group", "g.armour", "--affix-kind", "stat.modify", "--write",
                             "--endpoint", "http://unit-test-endpoint",
                             "--model", "unit-test-model"])

    assert exit_code == 0
    assert called_with["config"].endpoint == "http://unit-test-endpoint"
    assert called_with["config"].model == "unit-test-model"
    assert called_with["schema"]  # a real, non-empty constrained-decoding schema was sent
    written = json.loads((isolated_families_dir / "g-armour.json").read_text(encoding="utf-8"))
    ids = {e["id"] for e in written["entries"]}
    assert "atom.arm-livewired" in ids
    out = json.loads(capsys.readouterr().out)
    assert out == {"outcome": "persisted", "id": "atom.arm-livewired"}


def test_cli_blocked_answer_is_reported_and_writes_nothing(isolated_families_dir, capsys, monkeypatch):
    def _fake_live_answer_caller(config, *, validator=None):
        return lambda brief, schema: {
            "blocked": "no legal (channel, op) pair left",
            "name": None, "displayTemplate": None, "word": None, "channelOp": None,
            "roles": None, "tags": None, "powerBand": None,
        }

    monkeypatch.setattr("seedsmith.pipeline.llm_caller.live_answer_caller",
                        _fake_live_answer_caller)
    before = (isolated_families_dir / "g-armour.json").read_text(encoding="utf-8")

    exit_code = run_mod.main(["--group", "g.armour", "--affix-kind", "stat.modify", "--write",
                             "--endpoint", "http://unit-test-endpoint"])

    assert exit_code == 0
    after = (isolated_families_dir / "g-armour.json").read_text(encoding="utf-8")
    assert before == after
    out = json.loads(capsys.readouterr().out)
    assert out["outcome"] == "blocked"


def test_cli_refuses_a_boolean_blocked_field_and_writes_nothing(
    isolated_families_dir, capsys, monkeypatch,
):
    """A local endpoint once ignored the schema and emitted exactly this malformed answer."""
    monkeypatch.setattr("seedsmith.pipeline.llm_caller.live_answer_caller",
                        lambda config, *, validator=None: lambda brief, schema: {"blocked": True})
    before = (isolated_families_dir / "g-armour.json").read_text(encoding="utf-8")

    exit_code = run_mod.main(["--group", "g.armour", "--affix-kind", "stat.modify", "--write",
                              "--endpoint", "http://unit-test-endpoint"])

    assert exit_code == 3
    assert (isolated_families_dir / "g-armour.json").read_text(encoding="utf-8") == before
    out = json.loads(capsys.readouterr().out)
    assert out["outcome"] == "refused"
    assert "blocked" in out["reason"]


def test_cli_skips_the_model_when_no_channel_op_pair_is_available(tmp_path, monkeypatch, capsys):
    """`g.attack` exhausts its sole channel's Flat/Increased/More mechanics."""
    families_dir = tmp_path / "affix-families"
    families_dir.mkdir()
    source = FAMILIES_DIR / "g-attack.json"
    target = families_dir / "g-attack.json"
    target.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    monkeypatch.setattr(brief_mod, "FAMILIES_DIR", families_dir)
    monkeypatch.setattr(run_mod, "DEFAULT_LEDGER", tmp_path / "ledger.json")
    monkeypatch.setattr("seedsmith.pipeline.llm_caller.live_answer_caller",
                        lambda *args, **kwargs: pytest.fail("model must not be called"))
    before = target.read_text(encoding="utf-8")

    exit_code = run_mod.main(["--group", "g.attack", "--affix-kind", "stat.modify", "--write",
                              "--endpoint", "http://unit-test-endpoint"])

    assert exit_code == 0
    assert target.read_text(encoding="utf-8") == before
    out = json.loads(capsys.readouterr().out)
    assert out["outcome"] == "blocked"
    assert "no free" in out["reason"]
